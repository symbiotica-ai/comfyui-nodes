# Center the packed block on the sheet (editor Rearrange + AutoPacker)

Date: 2026-07-21
Status: approved by Razvan (design discussion, this session)
Builds in: local desktop ComfyUI (:8000), install clone on branch `auto-packer`

## Goal (the one thing that matters)

A packed sheet's content should sit **centered on the sheet** — both axes — instead
of anchored top-left. A single scaled sprite lands dead-center of the Qwen preset
canvas; a rows×columns grid centers as a block. This is what "press Rearrange
regions so the image recenters / auto-aligns to center based on the number of
rows/columns" should produce, and it makes the AutoPacker node emit centered
sprites with no manual step.

## Where the behavior lives

The layout is computed in two parallel, must-stay-in-sync implementations (the
established JS-resolver / Python-compose parity rule):

- JS: `web/js/template_editor/algos.js` → `prefillRegions(...)`
- Python: `py/pipeline/prefill.py` → `prefill_regions(...)`

Each has two paths:
- **settings path** (`pack()` texture-packer): used by the editor (it always has
  pack settings) and by the AutoPacker (`build_prefill_sheet` →
  `prefill_regions` with a `PackSettings`). Placements come out **top-left
  anchored**; overflow strips stack directly below. **This is the path that is
  not centered today.**
- **no-settings path**: already centers each row horizontally and distributes
  vertically. Unchanged.

So the whole change is: make the **settings path** center its block. That single
change reaches editor **Prefill from specs**, editor **Rearrange regions**
(`rebuildSpecRegions` calls `prefillRegions` with settings), and the
**AutoPacker** output — all three run this path.

## The change (symmetric, JS + Python)

After the settings path has collected ALL regions (packed placements **and** any
overflow strips) and before the final `sort` + `zIndex` pass, insert a
center-the-block post-pass:

1. Compute the block bounding box in **fraction space** (regions store
   `x/y/w/h` as fractions of the sheet):
   `minX = min(r.x)`, `maxX = max(r.x + r.w)`, `minY = min(r.y)`,
   `maxY = max(r.y + r.h)`.
2. `offsetX = (1 - (maxX - minX)) / 2 - minX`, and the same for `offsetY`.
3. **Clamp per axis** so nothing leaves the sheet: if the block is wider than
   the sheet (`maxX - minX >= 1`) anchor that axis at 0 (`offsetX = -minX`, the
   current top-left behavior); otherwise keep the centered offset (which is
   already within bounds by construction). Same for Y. This means an overflowing
   sheet (oversized strips stacked below) keeps its top-left anchor — no sprite
   is ever pushed off-edge.
4. Apply the offset to **each region's `x`/`y` AND to every one of its
   `members[]` cells' `x`/`y`** — the draw uses `members`, so both must move
   together. `w`/`h` are unchanged.

Then the existing `sort((y, x))` + `zIndex` runs on the translated regions.

Because the offset is a pure translation of the already-computed layout, the
grid the packer chose (its rows/columns) is preserved — only its position on the
sheet changes.

## Reach

- Editor **Prefill from specs** → centered block.
- Editor **Rearrange regions** → recenters (the requested step).
- **AutoPacker** node → each sheet's sprite(s) centered on the Qwen canvas.
- Editor manual steps that already work (Save sheet, ×2 scale, single-ref
  select, mirror pair) are untouched — centering just repositions the result.

Always-on when pack settings are present (matches "always auto-aligns to
center"); consistent with the no-settings path, which already centers.

## Testing & verification

- **Python (pytest, `.venv/bin/pytest`):** new `prefill_regions` settings-path
  cases —
  - one region → block centered on both axes (region + its members shifted;
    center of the block ≈ sheet center).
  - a small multi-region grid → block centered, internal layout unchanged
    (relative offsets between regions preserved).
  - an overflowing sheet (strips taller than the sheet) → anchored at top
    (`minY` maps to 0), never negative / off-edge.
  - existing `test_prefill.py` and `test_autopack.py` stay green.
- **JS:** `node --check web/js/template_editor/algos.js`; Razvan click-tests the
  editor (Rearrange recenters; the sprite sits centered) — the accepted JS
  verification in this repo (no JS test infra).
- **Live:** deploy to the install (branch `auto-packer`), reboot for Python,
  hard-refresh for JS; a queue run of OrderSpecs → AutoPacker shows centered
  sheets, and the editor Rearrange recenters.

## Non-goals

- No new pack settings / node widgets (always-on, not a toggle).
- No change to the no-settings path, the packer algorithms themselves, or any
  other node. Parity change lands JS + Python in one commit.
