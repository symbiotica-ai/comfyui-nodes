# Center the Packed Block on the Sheet — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the settings-path packer center its whole block on the sheet (both axes), so the editor's Prefill/Rearrange and the AutoPacker node all output content centered on the Qwen canvas instead of anchored top-left.

**Architecture:** A pure post-pass, added symmetrically to the two parallel layout implementations — Python `prefill_regions` (`py/pipeline/prefill.py`) and JS `prefillRegions` (`web/js/template_editor/algos.js`). After the packer places all regions (+ overflow), compute the block bounding box in fraction space and translate every region **and its member cells** so the block centers; an axis whose content is bigger than the sheet anchors at 0 instead. The JS + Python change lands in ONE commit (the draw-rule parity rule).

**Tech Stack:** Python 3.12, PIL, pytest via `.venv/bin/pytest`; vanilla JS (`node --check`, no build step). Spec: `docs/superpowers/specs/2026-07-21-autopack-centering-design.md`.

## Global Constraints

- Run tests ONLY as `.venv/bin/pytest` — never `.venv/bin/python -m pytest` (the repo's `py/` package shadows pytest's `py` dependency and crashes startup).
- Regions store `x/y/w/h` as **fractions of the sheet**; each region also carries `members[]` cells with their own fractional `x/y/w/h`. The sheet draw uses `members`, so centering MUST translate the region's `x/y` AND every member's `x/y` by the same offset. `w/h` never change.
- JS resolver and Python compose are parallel draw rules — change both and commit them together (one commit).
- Center only the **settings path** of `prefill_regions`/`prefillRegions`. The no-settings path already centers — leave it, the packer algorithms, and every node untouched.
- Always-on (no toggle, no new widget/setting).
- Commit messages end with the repo's standard co-author trailer.

---

### Task 1: Center the packed block (Python TDD + JS parity, one commit)

**Files:**
- Modify: `py/pipeline/prefill.py` (add `_center_block`; call it in the settings path before the final `regions.sort`)
- Modify: `tests/test_prefill.py` (2 new tests)
- Modify: `web/js/template_editor/algos.js` (add `centerBlock`; call it in `prefillRegions` settings path before its `regions.sort`)

**Interfaces:**
- Consumes: existing `prefill_regions(order_assets, sheet_w, sheet_h, chosen=None, settings=None)` and its JS twin `prefillRegions(orderAssets, sheetW, sheetH, chosen, settings, scales)`; `PackSettings` from `pipeline.texture_pack`.
- Produces: `_center_block(regions: list[dict]) -> None` (Python, in-place) and `centerBlock(regions)` (JS, in-place) — the block-centering post-pass. No signature changes to the public functions.

- [ ] **Step 1: Write the failing Python tests** (append to `tests/test_prefill.py`)

```python
def test_packed_single_region_centered_both_axes():
    # A small strip on a big sheet: the packer drops it top-left; centering
    # must move it (and its member cells) to the middle of the sheet.
    settings = PackSettings(algorithm="shelf", preset=None, max_width=1000,
                            max_height=1000, distribute_by_folder=False)
    res = prefill_regions([asset("Cart", ["Cart.png"], canvas="128x128")],
                          1000, 1000, settings=settings)
    (region,) = res["regions"]
    assert abs(region["x"] + region["w"] / 2 - 0.5) < 0.01
    assert abs(region["y"] + region["h"] / 2 - 0.5) < 0.01
    # a member cell moved with its region (same row → same vertical center)
    m = region["members"][0]
    assert abs(m["y"] + m["h"] / 2 - 0.5) < 0.01


def test_packed_block_centered_symmetric():
    # Two strips: the block's bounding box is centered — left margin equals
    # right margin, top equals bottom.
    settings = PackSettings(algorithm="shelf", preset=None, max_width=1000,
                            max_height=1000, distribute_by_folder=False)
    res = prefill_regions([asset("A", ["A.png"]), asset("B", ["B.png"])],
                          1000, 1000, settings=settings)
    regs = res["regions"]
    min_x = min(r["x"] for r in regs)
    max_x = max(r["x"] + r["w"] for r in regs)
    min_y = min(r["y"] for r in regs)
    max_y = max(r["y"] + r["h"] for r in regs)
    assert abs(min_x - (1 - max_x)) < 0.01   # symmetric horizontally
    assert abs(min_y - (1 - max_y)) < 0.01   # symmetric vertically
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `.venv/bin/pytest tests/test_prefill.py::test_packed_single_region_centered_both_axes tests/test_prefill.py::test_packed_block_centered_symmetric -v`
Expected: both FAIL — the packer anchors top-left, so the region/block centers are not ≈ 0.5 / not symmetric.

- [ ] **Step 3: Write the Python implementation** — add the helper near the other module-private helpers in `py/pipeline/prefill.py` (e.g. after `_region_at`):

```python
def _center_block(regions: list[dict]) -> None:
    """Translate the whole placed block so it sits centered on the sheet (both
    axes). An axis whose content is wider/taller than the sheet anchors at 0
    (top-left) instead — nothing is pushed off-edge. Region boxes AND their
    member cells move together (the sheet draw uses members)."""
    if not regions:
        return
    min_x = min(r["x"] for r in regions)
    max_x = max(r["x"] + r["w"] for r in regions)
    min_y = min(r["y"] for r in regions)
    max_y = max(r["y"] + r["h"] for r in regions)
    off_x = -min_x if (max_x - min_x) >= 1 else (1 - (max_x - min_x)) / 2 - min_x
    off_y = -min_y if (max_y - min_y) >= 1 else (1 - (max_y - min_y)) / 2 - min_y
    if off_x == 0 and off_y == 0:
        return
    for r in regions:
        r["x"] += off_x
        r["y"] += off_y
        for m in r.get("members", []):
            m["x"] += off_x
            m["y"] += off_y
```

Then, in `prefill_regions`, in the `if settings is not None:` branch, call it on the assembled regions (packed + overflow) immediately **before** the existing sort. Change:

```python
        regions.sort(key=lambda r: (r["y"], r["x"]))
        for i, r in enumerate(regions):
            r["zIndex"] = i
        return {"regions": regions, "overflow": overflow}
```

to:

```python
        _center_block(regions)
        regions.sort(key=lambda r: (r["y"], r["x"]))
        for i, r in enumerate(regions):
            r["zIndex"] = i
        return {"regions": regions, "overflow": overflow}
```

- [ ] **Step 4: Run the Python suite to verify pass**

Run: `.venv/bin/pytest tests/test_prefill.py tests/test_autopack.py -v`
Expected: all PASS — the 2 new centering tests pass; the existing overflow tests (`test_packed_overflow_oversized_cell_stays_in_bounds`, `test_packed_layout_with_settings_and_overflow_stacks_below`) still pass (translation preserves y-order and never makes y negative when content overflows).
Then the whole suite: `.venv/bin/pytest`
Expected: all green (129 + 2 = 131).

- [ ] **Step 5: Write the JS parity implementation** — in `web/js/template_editor/algos.js`, add the twin helper (near `regionAt`):

```javascript
function centerBlock(regions) {
    // Parity with py prefill._center_block: translate the packed block to the
    // sheet centre (both axes); an axis bigger than the sheet anchors at 0.
    // Region boxes AND their member cells move together (the draw uses members).
    if (!regions.length) return;
    const minX = Math.min(...regions.map((r) => r.x));
    const maxX = Math.max(...regions.map((r) => r.x + r.w));
    const minY = Math.min(...regions.map((r) => r.y));
    const maxY = Math.max(...regions.map((r) => r.y + r.h));
    const offX = (maxX - minX) >= 1 ? -minX : (1 - (maxX - minX)) / 2 - minX;
    const offY = (maxY - minY) >= 1 ? -minY : (1 - (maxY - minY)) / 2 - minY;
    if (offX === 0 && offY === 0) return;
    for (const r of regions) {
        r.x += offX;
        r.y += offY;
        for (const m of r.members ?? []) { m.x += offX; m.y += offY; }
    }
}
```

Then, in `prefillRegions`, in the `if (settings !== null) {` branch, call it immediately **before** the existing sort. Change:

```javascript
        regions.sort((a, b) => (a.y - b.y) || (a.x - b.x));
        regions.forEach((r, i) => { r.zIndex = i; });
        return { regions, overflow };
```

to:

```javascript
        centerBlock(regions);
        regions.sort((a, b) => (a.y - b.y) || (a.x - b.x));
        regions.forEach((r, i) => { r.zIndex = i; });
        return { regions, overflow };
```

- [ ] **Step 6: Syntax-check the JS, then commit both sides together**

Run: `node --check web/js/template_editor/algos.js`
Expected: clean (no output).

```bash
git add py/pipeline/prefill.py tests/test_prefill.py web/js/template_editor/algos.js
git commit -m "feat: center the packed block on the sheet (editor prefill/rearrange + autopacker)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N1AMzdCHCWKHTp3vUaLzcP"
```

---

### Task 2: Live verify + release

**Files:**
- Modify: `pyproject.toml` (version `2.38.0` → `2.39.0`)

- [ ] **Step 1: Deploy the branch to the local install**

```bash
git push origin auto-packer
git -C ~/Documents/ComfyUI/custom_nodes/symbiotica pull --ff-only
curl -s -X POST http://127.0.0.1:8000/api/v2/manager/reboot || true
# wait ~20s for the server to come back (poll /system_stats for http 200)
```
(JS is picked up by a hard browser refresh; the reboot covers the Python side.)

- [ ] **Step 2: Verify the AutoPacker output is centered (API queue on the real order)**

Queue `SymbioticaOrderSpecs(project=<bakery>, month=October)` → `SymbioticaAutoPacker` → `SaveImage` via `POST /prompt`, poll `/history`. For one saved sheet with a single small sprite, confirm the drawn content is centered — e.g. load the PNG and check the non-background bounding box is centered within ~2% of the sheet centre:

```python
# .venv/bin/python — over a saved sheet path P (RGB, grey #808080 background)
from PIL import Image, ImageChops
im = Image.open(P).convert("RGB")
bg = Image.new("RGB", im.size, (128, 128, 128))
bbox = ImageChops.difference(im, bg).getbbox()  # (l, t, r, b) of drawn content
cx = (bbox[0] + bbox[2]) / 2 / im.width
cy = (bbox[1] + bbox[3]) / 2 / im.height
print(cx, cy)            # expect ~0.5, ~0.5
```
Expected: `cx`, `cy` ≈ 0.5 (centered). Remove any smoke output afterward.

- [ ] **Step 3: Editor check (Razvan)** — hard-refresh the ComfyUI tab, open the Template Editor, Prefill/Rearrange: the block sits centered; a single ×2-scaled, single-ref, mirrored sprite lands dead-centre. (Browser behavior is Razvan's click-test — the accepted JS verification in this repo.)

- [ ] **Step 4: Bump version + commit**

Run: `.venv/bin/pytest`
Expected: green (131).

```bash
# edit pyproject.toml: version = "2.39.0"
git add pyproject.toml
git commit -m "release: v2.39.0 — center packed sheets (editor + autopacker)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01N1AMzdCHCWKHTp3vUaLzcP"
git push origin auto-packer
```
