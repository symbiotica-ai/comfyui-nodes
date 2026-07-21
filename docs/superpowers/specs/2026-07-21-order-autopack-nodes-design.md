# Order → Auto-Packed Template Sheets: small-node pipeline design

Date: 2026-07-21
Status: approved by Razvan (design discussion, this session)
Builds in: local desktop ComfyUI (:8000), install clone at `~/Documents/ComfyUI/custom_nodes/symbiotica`

## Goal (the one thing that matters)

Input is the client order; output is template sheets — sprites auto-arranged,
generally 1–2 columns × 3–4 rows of similar assets per sheet — each sheet paired
with its client prompts, ready for img2img models (Qwen). The ENTIRE collection
runs in ONE modular workflow, one queue press.

The Template Editor stays untouched: it remains the interactive fallback and the
reference implementation. This pipeline is the fast, hands-off path.

## Principles

- **Small nodes, one operation each.** (Direction change: supersedes the old
  "grow one node" rule.)
- **Never images and text on the same wire.** IMAGE wires feed img2img / VAE;
  STRING wires feed LLM Chat / prompt inputs; one custom ORDER wire is the
  backbone between our nodes.
- **Aligned lists** for paired data: `sheets[i]` ↔ `sheet_prompts[i]`
  (`is_output_list=True`, the proven pattern — downstream nodes run once per
  item).
- **Reuse `py/pipeline/` pure functions.** Nodes are thin V3 wrappers. New logic
  lands as new pure modules with pytest coverage.
- Asset categories are **dynamic per game** (read from the order xlsx — Bakery
  has 2, other games 13+). Never hardcode category sockets; use dropdowns
  populated from the parsed order, and multiple node instances per category
  when needed.

## The ORDER wire

New custom type: `Order = io.Custom("SYMBIOTICA_ORDER")`.

Payload (dict): the **selected event**, resolved to everything downstream nodes
need — no re-parsing, no path logic in leaf nodes:

```python
{
  "feature":    str,          # e.g. "Mini 2"
  "eventName":  str,          # e.g. "Purrfection Sweets"
  "assets":     [ {           # spec order preserved
      "assetName": str,
      "category":  str,       # e.g. "Food - 3 stages"
      "canvas":    str,       # e.g. "128x128"
      "prompt":    str,       # client brief from the xlsx
      "refFiles":  [str],     # file names under refsRoot/<category>/<assetName>/
  } ],
  "refsRoot":   str,          # that month's client-refs folder
  "assetsRoot": str,          # the game sprite catalog (project reference)
  "guide":      str | None,   # contents of <project>/order-guide.md if present
}
```

Existing `OrderEvents` / `EventSpec` custom types stay as-is (legacy chain).

## Node 1 — SymbioticaOrderSpecs

The picker. Face mirrors the editor's left-rail top panel (project folder,
month, event, required-assets list with client-ref thumbnails).

- **Inputs (widgets):** `project_path` (STRING), `month` (comboified by JS from
  `/symbiotica/list-orders`, same mechanism as Order Read), `feature` (event —
  comboified from the parsed order's events; default first event).
- **Output:** `order` (ORDER) — one socket, nothing else.
- **Resolution:** `project_layout.resolve_month(project, month)` →
  order xlsx / refsRoot / assetsRoot; existing xlsx parser → events; selected
  event → payload above.
- **order-guide.md slot (phase 1 = convention + detection only):** look for
  `<project>/order-guide.md`; if present, load its text into `payload["guide"]`
  and show a "guide found" hint on the node face; if absent show "no guide
  (using built-in Bakery conventions)". No LLM parsing yet — Bakery keeps the
  fast Python parser. The guide-driven LLM parse (xlsx text dump + guide →
  structured ORDER, cached) is phase 4, designed when a real second-game xlsx
  exists.
- **Face JS (phase 1):** month + event combos only (reuse the Order Read
  month-combo pattern in `order_pipeline.js`). The required-assets panel with
  client-ref thumbnails (mirroring the editor's rail, via
  `/symbiotica/local-image`) is phase-3 polish — the combos are enough to run
  the pipeline.
- **Errors:** unreadable project/month → actionable error naming the path
  tried. Event not found → actionable error listing available events.

## Node 2 — SymbioticaAutoPacker (the heart)

ORDER in → the whole collection as paired sheets + prompts out.

- **Inputs:** `order` (ORDER); widgets: `columns` (INT, default 1, his 1–2),
  `max_rows_per_sheet` (INT, default 4), `preset_model` / `resolution` /
  `aspect` (same combos as Template Editor; default Qwen / 1K / 1:1),
  `background` (STRING color, default the editor's default), `category`
  (COMBO: "All" + detected categories, default "All").
- **Outputs:** `sheets` (IMAGE, `is_output_list=True`) + `sheet_prompts`
  (STRING, `is_output_list=True`), index-aligned. Optionally `sheet_names`
  (STRING list, e.g. `mini-2-food-3-stages-1`) for SaveImage filename prefixes —
  include; it is text-only and cheap.
- **Pagination (the one genuinely new piece):**
  1. Filter assets by `category` (All = every category).
  2. Group by `(category, canvas)` — 256² and 512² decorations never share a
     sheet (Qwen sees consistent scale per sheet).
  3. Chunk each group in spec order into at most `columns × max_rows_per_sheet`
     assets per sheet.
  4. Per chunk: `build_prefill_sheet(chunk_assets, refsRoot, w, h, settings)`
     (w/h from `preset_dims`) → PIL sheet + regions; prompts =
     `build_client_prompts(regions)`.
  5. Collect sheets (PIL → tensor, same conversion as existing nodes) and
     prompts into the aligned lists.
- **New pure module:** `py/pipeline/autopack.py` — the grouping/chunking +
  per-chunk orchestration, returning `[(pil_sheet, regions, prompts, name)]`.
  Pure, PIL-only, pytest-covered against the real Bakery October order fixture.
- **Errors:** zero assets after filtering → raise actionable error ("no assets
  of type X in event Y") — NEVER return empty lists (empty `is_output_list`
  crashes downstream SaveImage with IndexError; learned live).
  Assets with no refFiles are skipped by `prefill_regions` already; surface a
  count in the error/logging path if a whole chunk lands empty.

## Phase 3 (after the core works) — taps on the same ORDER wire

- **SymbioticaTaskPrompts:** ORDER + category dropdown → `prompts` (STRING
  list, one per asset, spec order) + `prompts_text` (STRING, grouped text via
  `build_client_prompts`).
- **SymbioticaTaskImages:** ORDER + category dropdown → `strips` (IMAGE list,
  one composed strip per asset, refs side by side at native res). Aligns 1:1
  with TaskPrompts of the same category.
- **Spawn button on OrderSpecs:** JS creates one pre-wired TaskImages per
  detected category (precedent: the regions bridge auto-creates RefsSplit).
- **Required-assets panel on the OrderSpecs face** (thumbnails per category,
  mirroring the editor rail) — moved here from phase 1.

## Phase 4 / parked

- **LLM order-parse** driven by `order-guide.md` (new-game enrollment without
  code changes).
- **SymbioticaProjectReference** node (the project-assets tree as its own
  node/function) — parked deliberately, NOT forgotten; Razvan currently uses a
  LoRA for style + event-specific references instead.
- AutoPacker per-sheet region metadata output (bundle/skeleton-style), if the
  regional flow ever needs it.

## Testing & verification

- pytest: `autopack.py` unit tests (grouping, chunking, pagination counts,
  prompt alignment, name generation) + integration against the Bakery fixture.
  Run as `.venv/bin/pytest` (never `python -m pytest` — `py/` shadows the
  pytest dependency).
- Nodes are NOT covered by pytest (no `comfy_api` in the venv). After every
  `nodes.py` change: deploy to the local install, POST
  `/api/v2/manager/reboot`, verify `/api/object_info/<NodeId>` schema, then a
  live queue run end to end (OrderSpecs → AutoPacker → SaveImage + Show Text).
- Deploy loop (local): push main → `git -C ~/Documents/ComfyUI/custom_nodes/symbiotica pull`
  → reboot (Python) / hard refresh (JS).

## Non-goals

- No Template Editor changes. No Modal deploy work in this phase. No regional
  (Gemini edit) pipeline changes. No new nodes beyond the ones listed.
