# Order → Auto-Packed Template Sheets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two new nodes — SymbioticaOrderSpecs (order picker → ORDER wire) and SymbioticaAutoPacker (ORDER → aligned `sheets` + `sheet_prompts` lists, paginated 1–2 columns × 3–4 rows of similar assets per sheet) — so a whole client order becomes Qwen-ready img2img template sheets in one queue press.

**Architecture:** A new pure module `py/pipeline/autopack.py` does grouping/pagination and orchestrates the existing pure functions (`prefill_regions`/`build_prefill_sheet`, `build_client_prompts`, `preset_dims`). The two nodes are thin V3 wrappers in `py/pipeline/nodes.py`, connected by a new custom wire `SYMBIOTICA_ORDER`. Minimal JS comboifies the month/event/category widgets. Spec: `docs/superpowers/specs/2026-07-21-order-autopack-nodes-design.md`.

**Tech Stack:** Python 3.12, PIL, ComfyUI V3 node API (`comfy_api` — NOT importable in the repo venv), pytest via `.venv/bin/pytest`, vanilla JS (no build step).

## Global Constraints

- Run tests ONLY as `.venv/bin/pytest` — never `.venv/bin/python -m pytest` (the repo's `py/` package shadows pytest's `py` dependency and crashes startup).
- pytest CANNOT cover `nodes.py` (needs `comfy_api`). Every `nodes.py` change must be verified live: deploy to `~/Documents/ComfyUI/custom_nodes/symbiotica`, `POST http://127.0.0.1:8000/api/v2/manager/reboot`, then check `/api/object_info/<NodeId>`.
- Never images and text on the same wire. Paired data = two index-aligned `is_output_list=True` outputs.
- An empty `is_output_list` output crashes downstream SaveImage (`IndexError` in `execution.py slice_dict`) — raise an actionable `ValueError` instead of returning empty lists.
- Follow the file's existing idioms exactly (V3 `io.Schema` classmethods, `_pil_to_tensor`, tooltip prose style, `# ABOUTME:` two-line headers on new files).
- Template Editor and all existing nodes stay untouched except for additive registration of the two new classes.
- Commit after every task; end messages with the standard co-author trailer used in this repo.

---

### Task 1: `autopack.plan_sheets` — grouping + pagination (pure, TDD)

**Files:**
- Create: `py/pipeline/autopack.py`
- Create: `tests/test_autopack.py`

**Interfaces:**
- Consumes: nothing new (plain dicts shaped like `prefill_regions` order assets: `{assetName, category, canvas, prompt, refFiles}`).
- Produces: `plan_sheets(assets: list[dict], columns: int, max_rows: int, category: str = "All") -> list[dict]` — each item `{"category": str, "canvas": str, "assets": list[dict], "index": int, "total": int}` where `index`/`total` are the 1-based chunk position within that `(category, canvas)` group. Also `sheet_name(base: str, chunk: dict, multi_canvas: bool) -> str`.

- [ ] **Step 1: Write the failing tests**

```python
# ABOUTME: Tests for order auto-packing — grouping by (category, canvas),
# ABOUTME: pagination into columns x max_rows chunks, sheet naming, rendering.
from pipeline.autopack import plan_sheets, sheet_name


def asset(name, refs=("a.png",), category="Decoration", canvas="128x128",
          prompt="p"):
    return {"assetName": name, "category": category, "canvas": canvas,
            "prompt": prompt, "refFiles": list(refs)}


def test_groups_by_category_and_canvas():
    assets = [
        asset("d1"), asset("d2", canvas="512x512"),
        asset("f1", category="Food - 3 stages"),
    ]
    chunks = plan_sheets(assets, columns=1, max_rows=4)
    keys = [(c["category"], c["canvas"]) for c in chunks]
    assert keys == [("Decoration", "128x128"), ("Decoration", "512x512"),
                    ("Food - 3 stages", "128x128")]


def test_paginates_at_columns_times_max_rows():
    assets = [asset(f"d{i}") for i in range(10)]
    chunks = plan_sheets(assets, columns=2, max_rows=3)  # 6 per sheet
    assert [len(c["assets"]) for c in chunks] == [6, 4]
    assert [(c["index"], c["total"]) for c in chunks] == [(1, 2), (2, 2)]
    # spec order preserved across the chunk boundary
    assert chunks[0]["assets"][0]["assetName"] == "d0"
    assert chunks[1]["assets"][0]["assetName"] == "d6"


def test_category_filter_and_no_refs_skipped():
    assets = [asset("d1"), asset("skip", refs=()),
              asset("f1", category="Food - 3 stages")]
    chunks = plan_sheets(assets, columns=1, max_rows=4,
                         category="Food - 3 stages")
    assert len(chunks) == 1
    assert [a["assetName"] for a in chunks[0]["assets"]] == ["f1"]


def test_sheet_name_variants():
    single = {"category": "Food - 3 stages", "canvas": "128x128",
              "index": 1, "total": 1}
    assert sheet_name("mini-2", single, multi_canvas=False) \
        == "mini-2-food-3-stages"
    paged = dict(single, index=2, total=3)
    assert sheet_name("mini-2", paged, multi_canvas=False) \
        == "mini-2-food-3-stages-2"
    sized = {"category": "Decoration", "canvas": "512x512",
             "index": 1, "total": 1}
    assert sheet_name("mini-2", sized, multi_canvas=True) \
        == "mini-2-decoration-512x512"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_autopack.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.autopack'`

- [ ] **Step 3: Write the implementation**

```python
# ABOUTME: Auto-pack a client order into template sheets: group similar assets
# ABOUTME: (category+canvas), paginate into columns x max_rows chunks, render.
from .order_sheet import slugify


def plan_sheets(assets, columns, max_rows, category="All"):
    """Chunk order assets into per-sheet groups: similar assets only —
    grouped by (category, canvas) — at most columns*max_rows assets per
    sheet, spec order preserved. Assets without refFiles are dropped (there
    is nothing to draw). category="All" keeps every type."""
    per_sheet = max(1, int(columns)) * max(1, int(max_rows))
    groups: dict[tuple[str, str], list[dict]] = {}
    for a in assets:
        if not a.get("refFiles"):
            continue
        if category != "All" and a.get("category") != category:
            continue
        groups.setdefault((a.get("category", ""), a.get("canvas", "")),
                          []).append(a)
    chunks = []
    for (cat, canvas), group in groups.items():
        pages = [group[i:i + per_sheet] for i in range(0, len(group), per_sheet)]
        for i, page in enumerate(pages, 1):
            chunks.append({"category": cat, "canvas": canvas, "assets": page,
                           "index": i, "total": len(pages)})
    return chunks


def sheet_name(base, chunk, multi_canvas):
    """mini-2-food-3-stages[-512x512][-2]: canvas only when the category
    spans several canvas sizes, page index only when paginated."""
    name = f"{base}-{slugify(chunk['category'])}"
    if multi_canvas:
        name += f"-{chunk['canvas']}"
    if chunk["total"] > 1:
        name += f"-{chunk['index']}"
    return name
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_autopack.py -v`
Expected: 4 PASS

- [ ] **Step 5: Run the whole suite, then commit**

Run: `.venv/bin/pytest`
Expected: all green (121 existing + 4 new).

```bash
git add py/pipeline/autopack.py tests/test_autopack.py
git commit -m "feat: autopack.plan_sheets — group similar assets, paginate into sheets"
```

---

### Task 2: `autopack.autopack_order` — render chunks to sheets + prompts (pure, TDD)

**Files:**
- Modify: `py/pipeline/autopack.py`
- Modify: `tests/test_autopack.py`

**Interfaces:**
- Consumes: `build_prefill_sheet(assets, refs_root, sheet_w, sheet_h, settings, chosen=None) -> (PIL.Image, regions, overflow)` from `pipeline.compose`; `build_client_prompts(regions) -> str` from `pipeline.skeleton`; `PackSettings` from `pipeline.texture_pack`; Task 1's `plan_sheets`/`sheet_name`.
- Produces: `autopack_order(assets, refs_root, *, sheet_w, sheet_h, columns=1, max_rows=4, background="#808080", category="All", base_name="order") -> list[dict]` — each `{"image": PIL.Image, "regions": list, "prompts": str, "name": str}`. Raises `ValueError` when nothing packs.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_autopack.py`)

```python
import pytest
from PIL import Image

from pipeline.autopack import autopack_order


def _make_refs(tmp_path, assets):
    for a in assets:
        d = tmp_path / a["category"] / a["assetName"]
        d.mkdir(parents=True, exist_ok=True)
        for f in a["refFiles"]:
            Image.new("RGBA", (32, 32), (200, 60, 60, 255)).save(d / f)
    return str(tmp_path)


def test_autopack_renders_aligned_sheets_and_prompts(tmp_path):
    assets = [
        asset("Booth", prompt="a booth"),
        asset("Cake", refs=("s1.png", "s2.png", "s3.png"),
              category="Food - 3 stages", prompt="Prep) x\nReady) y"),
    ]
    root = _make_refs(tmp_path, assets)
    out = autopack_order(assets, root, sheet_w=256, sheet_h=256,
                         base_name="mini-2")
    assert [o["name"] for o in out] == ["mini-2-decoration",
                                       "mini-2-food-3-stages"]
    assert all(o["image"].size == (256, 256) for o in out)
    # prompts belong to the SAME chunk as the image (aligned by construction)
    assert "a booth" in out[0]["prompts"]
    assert "Prep) x" in out[1]["prompts"]
    assert "a booth" not in out[1]["prompts"]


def test_autopack_paginates_and_numbers_names(tmp_path):
    assets = [asset(f"d{i}") for i in range(5)]
    root = _make_refs(tmp_path, assets)
    out = autopack_order(assets, root, sheet_w=256, sheet_h=256,
                         columns=1, max_rows=3, base_name="ev")
    assert [o["name"] for o in out] == ["ev-decoration-1", "ev-decoration-2"]
    assert len(out[0]["regions"]) == 3
    assert len(out[1]["regions"]) == 2


def test_autopack_multi_canvas_names_carry_size(tmp_path):
    assets = [asset("small"), asset("big", canvas="512x512")]
    root = _make_refs(tmp_path, assets)
    out = autopack_order(assets, root, sheet_w=256, sheet_h=256,
                         base_name="ev")
    assert sorted(o["name"] for o in out) \
        == ["ev-decoration-128x128", "ev-decoration-512x512"]


def test_autopack_empty_raises_actionable(tmp_path):
    with pytest.raises(ValueError, match="no assets"):
        autopack_order([asset("norefs", refs=())], str(tmp_path),
                       sheet_w=256, sheet_h=256, category="Food - 3 stages")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_autopack.py -v`
Expected: the 4 new tests FAIL — `ImportError: cannot import name 'autopack_order'`

- [ ] **Step 3: Write the implementation** (append to `py/pipeline/autopack.py`)

```python
from .compose import build_prefill_sheet
from .skeleton import build_client_prompts
from .texture_pack import PackSettings


def autopack_order(assets, refs_root, *, sheet_w, sheet_h, columns=1,
                   max_rows=4, background="#808080", category="All",
                   base_name="order"):
    """The whole order as ready-to-run sheets: plan_sheets chunks similar
    assets, each chunk is prefilled + drawn on its own sheet, and each
    sheet's client prompts come from the SAME chunk's regions — so item i
    of the images and item i of the prompts always describe each other."""
    chunks = plan_sheets(assets, columns, max_rows, category=category)
    if not chunks:
        cats = sorted({a.get("category", "") for a in assets if a.get("refFiles")})
        raise ValueError(
            f"no assets to pack for category {category!r} — this event has "
            f"referenced assets in: {', '.join(cats) or '(none at all)'}")
    canvases_per_cat: dict[str, set] = {}
    for c in chunks:
        canvases_per_cat.setdefault(c["category"], set()).add(c["canvas"])
    settings = PackSettings(algorithm="shelf", columns=max(1, int(columns)),
                            background=background,
                            max_width=sheet_w, max_height=sheet_h)
    out = []
    for chunk in chunks:
        sheet, regions, _overflow = build_prefill_sheet(
            chunk["assets"], refs_root, sheet_w, sheet_h, settings)
        if not regions:
            continue
        out.append({
            "image": sheet,
            "regions": regions,
            "prompts": build_client_prompts(regions),
            "name": sheet_name(base_name, chunk,
                               len(canvases_per_cat[chunk["category"]]) > 1),
        })
    if not out:
        raise ValueError(
            f"no assets to pack for category {category!r} — every chunk came "
            "back empty (missing reference files on disk?)")
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_autopack.py -v`
Expected: 8 PASS

- [ ] **Step 5: Full suite, commit**

Run: `.venv/bin/pytest`
Expected: all green.

```bash
git add py/pipeline/autopack.py tests/test_autopack.py
git commit -m "feat: autopack_order — render paginated chunks into aligned sheets + prompts"
```

---

### Task 3: ORDER wire + SymbioticaOrderSpecs node

**Files:**
- Modify: `py/pipeline/nodes.py` (custom types block ~line 38; new class near SymbioticaOrderRead; node registration list — grep `SymbioticaOrderRead` to find both spots)

**Interfaces:**
- Consumes: `resolve_month` (via the `_paths` pattern copied from `SymbioticaOrderRead`), `load_order(order_path, refs_path)` + `event_spec(events, feature)` from `pipeline.order_loader`.
- Produces: `Order = io.Custom("SYMBIOTICA_ORDER")`; node `SymbioticaOrderSpecs` with output `order` carrying `{"feature", "eventName", "assets", "refsRoot", "assetsRoot", "guide"}` — the contract Task 4's AutoPacker consumes.

- [ ] **Step 1: Add the custom type** — next to the existing customs (nodes.py ~line 38):

```python
Order = io.Custom("SYMBIOTICA_ORDER")
```

- [ ] **Step 2: Add the node class** (place directly after `SymbioticaOrderRead`; copy its `_paths` + `fingerprint_inputs` idiom verbatim, extended with `feature` and the guide file):

```python
class SymbioticaOrderSpecs(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaOrderSpecs",
            display_name="Symbiotica Order Specs",
            category="symbiotica/pipeline",
            description="Pick a project, month, and event — outputs ONE "
                        "order wire carrying that event's assets, client "
                        "reference paths, and catalog root. Feed it to the "
                        "Auto Packer (and any task-prompt/task-image taps).",
            inputs=[
                io.String.Input("project_path", default="",
                                tooltip="The client project folder — the one "
                                        "that contains orders/ and "
                                        "reference-assets/"),
                io.String.Input("month", default="",
                                tooltip="Which month's order to read"),
                io.String.Input("feature", default="",
                                tooltip="Which event to build (empty = the "
                                        "order's first event)"),
            ],
            outputs=[Order.Output(display_name="order")],
        )

    @classmethod
    def _paths(cls, project_path, month):
        project_path = (project_path or "").strip()
        op = rp = assets_root = ""
        if project_path:
            from .project_layout import resolve_month
            r = resolve_month(project_path, (month or "").strip())
            op, rp, assets_root = r["order_path"], r["refs_path"], r["assets_root"]
        return op, rp, assets_root

    @classmethod
    def _guide(cls, project_path):
        path = os.path.join((project_path or "").strip(), "order-guide.md")
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    @classmethod
    def fingerprint_inputs(cls, project_path="", month="", feature=""):
        op, rp, _ = cls._paths(project_path, month)
        h = hashlib.sha256(f"{op}|{rp}|{feature}".encode())
        try:
            st = os.stat(op)
            h.update(f"{st.st_mtime_ns}:{st.st_size}".encode())
        except OSError:
            pass
        try:
            if rp:
                h.update("\n".join(sorted(os.listdir(rp))).encode())
        except OSError:
            pass
        h.update((cls._guide(project_path) or "").encode())
        return h.hexdigest()

    @classmethod
    def execute(cls, project_path="", month="", feature="") -> io.NodeOutput:
        op, rp, assets_root = cls._paths(project_path, month)
        if not op:
            raise ValueError(
                "no order file — set the project folder (the one with an "
                "orders/ subfolder of .xlsx files) and pick a month")
        loaded = load_order(op, rp)
        events = loaded["events"]
        if not events:
            raise ValueError(f"no events found in {op}")
        feature = (feature or "").strip()
        spec = event_spec(events, feature) if feature else events[0]
        if not spec or not spec.get("assets"):
            names = ", ".join(e.get("feature", "?") for e in events)
            raise ValueError(
                f"event {feature!r} not found in this order — it has: {names}")
        payload = {
            "feature": spec.get("feature", ""),
            "eventName": spec.get("eventName", ""),
            "assets": spec.get("assets", []),
            "refsRoot": rp,
            "assetsRoot": assets_root,
            "guide": cls._guide(project_path),
        }
        return io.NodeOutput(payload)
```

Note: check `event_spec`'s return shape in `py/pipeline/order_loader.py:35` before wiring — if it returns the spec dict (`{feature, eventName, assets…}` — same shape `events[0]` has via `group_order_events`), the code above is right; adjust the field pulls if it wraps differently.

- [ ] **Step 3: Register the node** — grep `"SymbioticaOrderRead"` in the repo (`nodes.py` list + `py/symbiotica_pipeline.py` shim if it enumerates classes) and add `SymbioticaOrderSpecs` everywhere its sibling appears.

- [ ] **Step 4: Syntax check + suite**

Run: `.venv/bin/python -c "import ast; ast.parse(open('py/pipeline/nodes.py').read())" && .venv/bin/pytest`
Expected: no syntax error; suite green (nodes.py itself is not imported by tests).

- [ ] **Step 5: Live verify**

```bash
git -C ~/Documents/ComfyUI/custom_nodes/symbiotica pull  # after pushing, or use a branch checkout there
curl -s -X POST http://127.0.0.1:8000/api/v2/manager/reboot || true
sleep 20
curl -s http://127.0.0.1:8000/api/object_info/SymbioticaOrderSpecs | python3 -m json.tool | head -40
```
Expected: schema with inputs `project_path`/`month`/`feature`, output type `SYMBIOTICA_ORDER`.

- [ ] **Step 6: Commit**

```bash
git add py/pipeline/nodes.py py/symbiotica_pipeline.py
git commit -m "feat: SymbioticaOrderSpecs — project/month/event picker onto one ORDER wire"
```

---

### Task 4: SymbioticaAutoPacker node

**Files:**
- Modify: `py/pipeline/nodes.py` (new class after SymbioticaOrderSpecs; same registration spots)

**Interfaces:**
- Consumes: Task 3's ORDER payload; Task 2's `autopack_order`; `preset_dims` from `pipeline.model_presets`; `_pil_to_tensor` (nodes.py:66); the model/resolution/aspect combo definitions — copy them from `SymbioticaTemplateEditor`'s schema (grep `preset_model` in nodes.py) so the options match the editor exactly.
- Produces: node `SymbioticaAutoPacker`, outputs `sheets` (Image, list) / `sheet_prompts` (String, list) / `sheet_names` (String, list), index-aligned.

- [ ] **Step 1: Add the node class**

```python
class SymbioticaAutoPacker(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        # Copy the preset_model / resolution / aspect Combo Inputs verbatim
        # from SymbioticaTemplateEditor's schema (same option lists, default
        # model "qwen-image", resolution "1K", aspect "1:1"), then:
        return io.Schema(
            node_id="SymbioticaAutoPacker",
            display_name="Symbiotica Auto Packer",
            category="symbiotica/pipeline",
            description="The whole order as ready-to-run template sheets: "
                        "similar assets grouped 1-2 columns x 3-4 rows per "
                        "sheet, each sheet paired with its client prompts. "
                        "Wire sheets -> img2img and sheet_prompts -> your "
                        "LLM/prompt input; downstream runs once per sheet.",
            inputs=[
                Order.Input("order"),
                io.Int.Input("columns", default=1, min=1, max=4,
                             tooltip="Assets side by side per row"),
                io.Int.Input("max_rows_per_sheet", default=4, min=1, max=12,
                             tooltip="Rows per sheet before starting a new "
                                     "sheet"),
                # ... the three preset combos copied from the editor ...
                io.String.Input("background", default="#808080",
                                tooltip="Sheet background color; empty = "
                                        "transparent"),
                io.String.Input("category", default="All",
                                tooltip="One asset type, or All"),
            ],
            outputs=[
                io.Image.Output(display_name="sheets", is_output_list=True,
                                tooltip="One template sheet per chunk of "
                                        "similar assets"),
                io.String.Output(display_name="sheet_prompts",
                                 is_output_list=True,
                                 tooltip="Client prompts for sheet i — "
                                         "index-aligned with sheets"),
                io.String.Output(display_name="sheet_names",
                                 is_output_list=True,
                                 tooltip="Slug per sheet — wire into Save "
                                         "Image filename_prefix"),
            ],
        )

    @classmethod
    def execute(cls, order, columns=1, max_rows_per_sheet=4,
                preset_model="qwen-image", resolution="1K", aspect="1:1",
                background="#808080", category="All") -> io.NodeOutput:
        if not isinstance(order, dict) or "assets" not in order:
            raise ValueError("order input must come from Symbiotica Order "
                             "Specs")
        dims = preset_dims({"model": preset_model, "tier": resolution,
                            "ar": aspect})
        if not dims:
            raise ValueError(
                f"invalid preset: {preset_model} / {resolution} / {aspect}")
        from .autopack import autopack_order
        base = slugify(order.get("feature", "")) or "order"
        packed = autopack_order(
            order["assets"], order.get("refsRoot", ""),
            sheet_w=dims["w"], sheet_h=dims["h"], columns=columns,
            max_rows=max_rows_per_sheet, background=background,
            category=(category or "All").strip() or "All", base_name=base)
        return io.NodeOutput(
            [_pil_to_tensor(p["image"]) for p in packed],
            [p["prompts"] for p in packed],
            [p["name"] for p in packed],
        )
```

Check `preset_dims`'s exact expected dict keys in `py/pipeline/model_presets.py:70` (`sel` shape) and how the editor's execute builds it — copy that call exactly.

- [ ] **Step 2: Register** — same two registration spots as Task 3.

- [ ] **Step 3: Syntax check + suite**

Run: `.venv/bin/python -c "import ast; ast.parse(open('py/pipeline/nodes.py').read())" && .venv/bin/pytest`
Expected: green.

- [ ] **Step 4: Live verify schema**

Deploy + reboot as in Task 3 Step 5, then:
```bash
curl -s http://127.0.0.1:8000/api/object_info/SymbioticaAutoPacker | python3 -m json.tool | head -60
```
Expected: input `order` typed `SYMBIOTICA_ORDER`; three outputs with `is_list` true.

- [ ] **Step 5: Live smoke — the real order, end to end**

Find Razvan's real project path (it is in his workflow autosaves):
```bash
grep -ho '"[^"]*Projects/[Bb]akery[^"]*"' ~/Documents/ComfyUI/user/default/workflows/*.json | sort -u | head
```
Queue a minimal graph via the API — OrderSpecs(project, October) → AutoPacker → SaveImage + one Show Text on `sheet_prompts` (build the JSON prompt by hand or in the UI). Verify: N saved sheet PNGs in `~/Documents/ComfyUI/output/`, each 1328×1328 (Qwen 1:1), decorations and food on separate sheets, prompts matching each sheet's assets. If Razvan is around, he clicks; otherwise POST `/prompt` and poll `/history`.

- [ ] **Step 6: Commit**

```bash
git add py/pipeline/nodes.py py/symbiotica_pipeline.py
git commit -m "feat: SymbioticaAutoPacker — order to aligned sheets + prompts, paginated"
```

---

### Task 5: JS — combo widgets for month / event / category

**Files:**
- Modify: `web/js/order_pipeline.js`

**Interfaces:**
- Consumes: the existing month-comboify pattern on Order Read (grep `list-orders` in `order_pipeline.js` — `onNodeCreated` swaps the STRING widget for a combo fed by `/symbiotica/list-orders`); the existing `/symbiotica/parse-order?project=&month=` route (returns events with features + assets with categories); the 4-hop upstream walk pattern (grep `upstreamNode`).
- Produces: OrderSpecs gets month + feature combos on its face; AutoPacker gets a category combo (values = "All" + distinct categories from the upstream OrderSpecs' parse).

- [ ] **Step 1: Extend the `beforeRegisterNodeDef` hook** — where the Order Read month combo is installed, apply the same treatment when `nodeData.name === "SymbioticaOrderSpecs"`: comboify `month` (identical code), and comboify `feature` with values from `fetchJson("/symbiotica/parse-order?...")` → `data.events.map(e => e.feature)`, refreshed whenever `project_path` or `month` changes.

- [ ] **Step 2: AutoPacker category combo** — when `nodeData.name === "SymbioticaAutoPacker"`, comboify `category`: walk `upstreamNode("order")` to the OrderSpecs node, read its `project_path`/`month`/`feature` widgets, fetch parse-order, values = `["All", ...new Set(event.assets.map(a => a.category))]`. Refresh on combo open (LiteGraph combos re-read `widget.options.values` when opened — mirror how the month combo does its refresh).

- [ ] **Step 3: Syntax check**

Run: `node --check web/js/order_pipeline.js`
Expected: clean. (No JS test infra — Razvan clicks the UI; that is the accepted verification for browser code in this repo.)

- [ ] **Step 4: Live verify** — hard refresh the ComfyUI tab (JS only, no reboot): add the two nodes, combos populate, queue runs.

- [ ] **Step 5: Commit**

```bash
git add web/js/order_pipeline.js
git commit -m "feat: month/event/category combos for OrderSpecs + AutoPacker"
```

---

### Task 6: Release

**Files:**
- Modify: `pyproject.toml` (version `2.37.0` → `2.38.0`)

- [ ] **Step 1: Bump version, full suite one last time**

Run: `.venv/bin/pytest`
Expected: green.

- [ ] **Step 2: Commit + merge to main per the repo's flow** (worktree branch → main; Razvan's deploy = push to main, then `git -C ~/Documents/ComfyUI/custom_nodes/symbiotica pull` + reboot)

```bash
git add pyproject.toml
git commit -m "release: v2.38.0 — OrderSpecs + AutoPacker (order to img2img-ready sheets)"
```

- [ ] **Step 3: Post-merge live check** — reboot, `/api/object_info` both nodes, one full queue on the real October order.
