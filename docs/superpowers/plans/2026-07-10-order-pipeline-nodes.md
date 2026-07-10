# Order Pipeline ComfyUI Nodes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port symbiotica-hub's Order Read → Specs → Template flow nodes (flow `bakery-event-all`, steps s8/s11/s12) to ComfyUI V3 custom nodes in this repo, producing a working pipeline: order xlsx + refs folder → per-event spec → packed template sheet (IMAGE + template bundle) that feeds the pack's existing NanoBanana edit nodes.

**Architecture:** Pure-Python ports of the hub's parsing/packing logic live in `py/pipeline/` (stdlib + Pillow only, no ComfyUI imports — fully unit-testable). Thin V3 node classes (`comfy_api.latest` io.Schema) wrap them in `py/pipeline/nodes.py`. A V1 shim module `py/symbiotica_pipeline.py` registers the V3 classes through the repo's existing auto-discovery (required — see Global Constraints). A JS extension (`web/js/order_pipeline.js`) gives dynamic event/group combos and an events browser, fed by `PromptServer.send_sync` pushes. A small aiohttp route serves local ref-image thumbnails, restricted to registered roots.

**Tech Stack:** Python 3.12 (ComfyUI venv), stdlib `zipfile`/`re` for xlsx, Pillow for compositing, numpy+torch for IMAGE tensors (ship with ComfyUI), vanilla JS extension, pytest for tests.

## Global Constraints

- Target ComfyUI **0.27.1** (user's install: source `~/ComfyUI-Installs/ComfyUI/ComfyUI`, data/custom_nodes `~/Documents/ComfyUI`, venv `~/Documents/ComfyUI/.venv` py3.12, server `http://127.0.0.1:8000`).
- **Loader quirk (verified in nodes.py:2275-2284):** `load_custom_node` uses `elif` — if a package exposes `NODE_CLASS_MAPPINGS`, its `comfy_entrypoint` is NEVER called. This repo's root `__init__.py` exposes V1 mappings, so V3 nodes MUST be registered via the shim (`py/symbiotica_pipeline.py` builds `NODE_CLASS_MAPPINGS[schema.node_id] = cls` — identical to what the loader's V3 path does at nodes.py:2306). Do NOT add `comfy_entrypoint` to root `__init__.py`.
- Root `__init__.py` auto-discovers `py/*.py` (sorted, skipping `_`-prefixed); subdirectories are NOT auto-discovered — `py/pipeline/` is a plain subpackage like the existing `py/wavespeed_api/`.
- **No new Python deps.** `requirements.txt` stays `requests`, `pillow`, `faster-whisper`. Parser uses stdlib `zipfile` + regex (mirror of hub's fflate approach).
- **Wire-format parity with hub:** all dict keys camelCase, exactly matching hub types (`OrderRow`/`OrderAsset`/`OrderEvent`/`TemplateGroup` in `apps/web/src/lib/flows/order-sheet.ts`, `AtlasRegion` in `regional-atlas/types.ts`, `TemplateBundle` in `flows/template-bundle.ts`). A bundle emitted here must satisfy hub's `parseTemplateBundle`.
- `node_id`s are permanent once released: `SymbioticaOrderRead`, `SymbioticaEventSpecs`, `SymbioticaTemplateBuilder`, `SymbioticaTemplatePrompt`. Category: `symbiotica/pipeline`.
- Custom link types: `SYMBIOTICA_ORDER_EVENTS`, `SYMBIOTICA_EVENT_SPEC`, `SYMBIOTICA_TEMPLATE`.
- **pytest `py` shim:** pytest ships a top-level `py` module; tests import the pipeline as `pipeline.*` (conftest puts `<repo>/py` on sys.path). Never import `py.*` from tests; never delete `py/__init__.py`.
- Tests run with the repo-local dev venv: `python3 -m venv .venv && .venv/bin/pip install pytest pillow` (once, in Task 1). Run from repo root: `.venv/bin/pytest tests/ -v` — NEVER `python -m pytest` (prepends CWD; the repo `py/` package then shadows pytest's bundled `py` shim and crashes pytest startup). Pure modules must import WITHOUT ComfyUI present.
- Tensor truthiness: always `if image is not None:`, never `if image:`.
- Reference sources (read-only) live at `~/.claude-sessions/symbiotica-hub/apps/web/src/lib/` — cite files below per task.
- Every commit message ends with:
  ```
  Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01LtD8JgXajWjYqfZxCEMb21
  ```
- Template editor UI (hub `regional-drawer.svelte`) is **out of scope** — Phase 3, separate plan.

---

### Task 1: Test infra + xlsx grid parser

**Files:**
- Create: `py/pipeline/__init__.py` (empty)
- Create: `py/pipeline/order_sheet.py` (grid parser half)
- Create: `tests/conftest.py`
- Create: `tests/test_order_sheet.py`
- Modify: `.gitignore` (add `.venv/`)

**Interfaces:**
- Produces: `parse_xlsx_grid(data: bytes) -> list[list[str]]`, `decode_xml(s)`, `text_runs(fragment)`, `col_index(letters)`, `numeric_text(v)` — consumed by Task 2/3.
- Reference: hub `flows/order-sheet.ts:39-131`, test fixtures in `flows/order-sheet.test.ts:1-225`.

- [ ] **Step 1: Create dev venv**

```bash
cd /Users/razvanmatei/.claude-sessions/comfy-nodes/comfyui-nodes
python3 -m venv .venv && .venv/bin/pip install -q pytest pillow
echo ".venv/" >> .gitignore
```

- [ ] **Step 2: Write conftest with an in-memory xlsx builder + failing grid tests**

`tests/conftest.py`:
```python
# ABOUTME: Shared test fixtures — builds minimal xlsx byte blobs in memory
# ABOUTME: (sheet XML + optional sharedStrings) for the order-sheet parser tests.
import io
import zipfile

import pytest


def make_xlsx(sheet_xml: str, shared_strings_xml: str | None = None) -> bytes:
    """A minimal xlsx: just the entries our parser reads."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        if shared_strings_xml is not None:
            zf.writestr("xl/sharedStrings.xml", shared_strings_xml)
    return buf.getvalue()


def inline_cell(ref: str, text: str) -> str:
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def sheet_of_rows(*rows: str) -> str:
    body = "".join(f"<row>{r}</row>" for r in rows)
    return f'<worksheet><sheetData>{body}</sheetData></worksheet>'


@pytest.fixture
def xlsx():
    return make_xlsx
```

`tests/test_order_sheet.py` (first half):
```python
# ABOUTME: Tests for the order-sheet xlsx parser — ported 1:1 from hub's
# ABOUTME: order-sheet.test.ts so both parsers keep identical behavior.
from conftest import inline_cell, make_xlsx, sheet_of_rows

from pipeline.order_sheet import parse_xlsx_grid


def test_reads_inline_string_cells_into_grid():
    xml = sheet_of_rows(
        inline_cell("A1", "Feature") + inline_cell("B1", "Asset Name"),
        inline_cell("A2", "Crate") + inline_cell("B2", "Pastel Chest"),
    )
    grid = parse_xlsx_grid(make_xlsx(xml))
    assert grid[0][0] == "Feature"
    assert grid[0][1] == "Asset Name"
    assert grid[1] == ["Crate", "Pastel Chest"]


def test_self_closing_empty_cells_do_not_swallow_next_cell():
    # A styled-but-empty cell (<c .../>) must not eat B1's body.
    xml = sheet_of_rows('<c r="A1" s="3"/>' + inline_cell("B1", "Kept"))
    grid = parse_xlsx_grid(make_xlsx(xml))
    assert grid[0][1] == "Kept"
    assert grid[0][0] == ""


def test_reads_shared_string_cells():
    sst = (
        '<sst><si><t>Feature</t></si>'
        "<si><t>Split </t><t>Run</t></si></sst>"
    )
    xml = sheet_of_rows('<c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>')
    grid = parse_xlsx_grid(make_xlsx(xml, sst))
    assert grid[0] == ["Feature", "Split Run"]


def test_numeric_cells_normalize_trailing_zero():
    xml = sheet_of_rows('<c r="A1"><v>46301.0</v></c><c r="B1"><v>1.5</v></c>')
    grid = parse_xlsx_grid(make_xlsx(xml))
    assert grid[0] == ["46301", "1.5"]


def test_decodes_xml_entities_and_char_refs():
    xml = sheet_of_rows(inline_cell("A1", "Tom &amp; Jerry &#x41;"))
    grid = parse_xlsx_grid(make_xlsx(xml))
    assert grid[0][0] == "Tom & Jerry A"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_order_sheet.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.order_sheet'`

- [ ] **Step 4: Implement the grid parser**

Create empty `py/pipeline/__init__.py`. Then `py/pipeline/order_sheet.py`:

```python
# ABOUTME: Parser for a client's monthly asset-order spreadsheet (xlsx) — extracts
# ABOUTME: typed order rows, matches reference filenames, groups assets into events.
# Pure-Python port of symbiotica-hub apps/web/src/lib/flows/order-sheet.ts.
from __future__ import annotations

import io
import re
import zipfile

_XML_ENTITIES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'"}
_ENTITY_RE = re.compile(r"&(?:amp|lt|gt|quot|apos);|&#x?[0-9a-fA-F]+;")
_T_RUN_RE = re.compile(r"<t(?:\s[^>]*)?>(.*?)</t>", re.S)
_SI_RE = re.compile(r"<si>(.*?)</si>", re.S)
_SELF_CLOSED_CELL_RE = re.compile(r"<c\s[^>]*/>")
_CELL_RE = re.compile(r"<c\s([^>]*)>(.*?)</c>", re.S)
_REF_RE = re.compile(r'r="([A-Z]+)(\d+)"')
_TYPE_RE = re.compile(r't="([^"]+)"')
_V_RE = re.compile(r"<v(?:\s[^>]*)?>(.*?)</v>", re.S)
_SHEET_NAME_RE = re.compile(r"^xl/worksheets/sheet\d+\.xml$")


def decode_xml(s: str) -> str:
    def repl(m: re.Match) -> str:
        token = m.group(0)
        if token in _XML_ENTITIES:
            return _XML_ENTITIES[token]
        try:
            code = int(token[3:-1], 16) if token.startswith("&#x") else int(token[2:-1])
        except ValueError:
            return token
        return chr(code)

    return _ENTITY_RE.sub(repl, s)


def text_runs(fragment: str) -> str:
    """Concatenated text of all <t> runs inside an <si>/<is> fragment."""
    return "".join(decode_xml(t) for t in _T_RUN_RE.findall(fragment))


def col_index(letters: str) -> int:
    """Column letters -> 0-based index (A->0, Z->25, AA->26)."""
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def numeric_text(v: str) -> str:
    """Numeric cell text -> display string ("46301" and "46301.0" both -> "46301")."""
    try:
        n = float(v)
    except ValueError:
        return v
    if n != n or n in (float("inf"), float("-inf")):
        return v
    if n == int(n) and abs(n) < 1e15:
        return str(int(n))
    return repr(n)


def parse_xlsx_grid(data: bytes) -> list[list[str]]:
    """Read the first worksheet of an xlsx into a dense row/col grid of cell text.

    Handles shared strings (t="s"), inline strings (t="inlineStr"), and numeric
    cells. Formula/error cells surface as their cached value text.
    """
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = set(zf.namelist())
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        sst = zf.read("xl/sharedStrings.xml").decode("utf-8")
        shared = [text_runs(si) for si in _SI_RE.findall(sst)]
    sheet_names = sorted(n for n in names if _SHEET_NAME_RE.match(n))
    if not sheet_names:
        raise ValueError("xlsx has no worksheet")
    # Drop self-closing cells (styled-but-empty, common in Google Sheets exports)
    # so the cell regex can't swallow the following cell's body.
    sheet = _SELF_CLOSED_CELL_RE.sub("", zf.read(sheet_names[0]).decode("utf-8"))

    cells: dict[int, dict[int, str]] = {}
    for attrs, body in _CELL_RE.findall(sheet):
        ref = _REF_RE.search(attrs)
        if not ref:
            continue
        row = int(ref.group(2)) - 1
        col = col_index(ref.group(1))
        type_m = _TYPE_RE.search(attrs)
        ctype = type_m.group(1) if type_m else "n"
        if ctype == "inlineStr":
            text = text_runs(body)
        else:
            v = _V_RE.search(body)
            if not v:
                continue
            raw = decode_xml(v.group(1))
            if ctype == "s":
                idx = int(raw)
                text = shared[idx] if 0 <= idx < len(shared) else ""
            elif ctype == "n":
                text = numeric_text(raw)
            else:
                text = raw
        cells.setdefault(row, {})[col] = text

    height = max(cells, default=-1) + 1
    grid: list[list[str]] = []
    for r in range(height):
        row_cells = cells.get(r, {})
        width = max(row_cells, default=-1) + 1
        grid.append([row_cells.get(c, "") for c in range(width)])
    return grid
```

Path hook — pytest ships a top-level `py` shim module (imported at pytest startup), so tests must NOT import via top-level `py.*`. Instead, put `<repo>/py` itself on sys.path and import `pipeline.*`. Add to the TOP of `tests/conftest.py`:

```python
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py"))
```

Caveat: `py/__init__.py` (empty) MUST stay — ComfyUI's root `__init__.py` auto-discovery imports `.py.<module>` relative to the pack package. Tests never import through the `py` package name; only through `pipeline.*`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_order_sheet.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add py/pipeline/__init__.py py/pipeline/order_sheet.py tests/ .gitignore
git commit -m "feat(pipeline): xlsx grid parser ported from hub order-sheet"
```

---

### Task 2: Order rows, ref matching, event/template grouping

**Files:**
- Modify: `py/pipeline/order_sheet.py` (append)
- Modify: `tests/test_order_sheet.py` (append)

**Interfaces:**
- Produces (all consumed by Tasks 3/5/6/7):
  - `HEADERS: dict[str, str]`
  - `extract_order_rows(grid) -> list[dict]` — row dict keys: `row, status, release, feature, eventName, assetName, assetId, category, canvas, plot, rotation, prompt, sets`
  - `compact_asset_name(name) -> str`, `match_ref_files(asset_name, file_names) -> list[str]`
  - `slugify(s) -> str`, `canvas_spec_of(canvas) -> dict | None` (`{"w": int, "h": int}`)
  - `group_order_events(rows, ref_file_names) -> list[dict]` — event dict: `{feature, eventName, assets: [row + refFiles]}`
  - `template_groups(event) -> list[dict]` — `{template, category, canvas, assets}`
- Reference: hub `flows/order-sheet.ts:133-283`, `flows/task-refs.ts:80-86`.

- [ ] **Step 1: Write failing tests (ported from hub order-sheet.test.ts:226-341)**

Append to `tests/test_order_sheet.py`:

```python
from pipeline.order_sheet import (
    canvas_spec_of,
    compact_asset_name,
    extract_order_rows,
    group_order_events,
    match_ref_files,
    slugify,
    template_groups,
)


def _grid(*rows):
    return [list(r) for r in rows]


HEADER = ["Status", "Release", "Feature", "Event Name", "Asset Name", "ID",
          "Asset Category", "Canvas", "Plot", "Rotation", "Prompt", "Sets #"]


def _row(feature="", event="", name="", status="", category="", canvas="",
         prompt="", asset_id="", plot="", rotation="", release="", sets=""):
    return [status, release, feature, event, name, asset_id, category, canvas,
            plot, rotation, prompt, sets]


def test_detects_header_row_and_types_data_rows():
    grid = _grid(["junk"], HEADER, _row("QE 2", "Coven of Shadows", "Midnight Cat",
                                        "1", "Appliance", "128x128", "a cat", "241084"))
    rows = extract_order_rows(grid)
    assert len(rows) == 1
    r = rows[0]
    assert r["row"] == 3  # 1-based sheet row
    assert r["feature"] == "QE 2"
    assert r["eventName"] == "Coven of Shadows"
    assert r["assetName"] == "Midnight Cat"
    assert r["assetId"] == "241084"
    assert r["category"] == "Appliance"
    assert r["canvas"] == "128x128"
    assert r["prompt"] == "a cat"
    assert r["status"] == 1


def test_header_row_not_found_raises():
    import pytest
    with pytest.raises(ValueError, match="header row not found"):
        extract_order_rows(_grid(["a", "b"], ["c"]))


def test_first_duplicate_header_wins():
    grid = _grid(HEADER + ["Prompt"],  # artist copy column at the end
                 _row("Mini 1", "", "Thing", prompt="client prompt") + ["artist prompt"])
    assert extract_order_rows(grid)[0]["prompt"] == "client prompt"


def test_keeps_placeholder_rows_feature_only():
    grid = _grid(HEADER, _row("RR Crate"), _row())
    rows = extract_order_rows(grid)
    assert len(rows) == 1
    assert rows[0]["feature"] == "RR Crate"
    assert rows[0]["assetName"] == ""


def test_trims_whitespace_in_names():
    grid = _grid(HEADER, _row("Crate ", "", " Pastel Chest "))
    r = extract_order_rows(grid)[0]
    assert r["feature"] == "Crate"
    assert r["assetName"] == "Pastel Chest"


def test_empty_status_is_none():
    grid = _grid(HEADER, _row("Crate", "", "Chest"))
    assert extract_order_rows(grid)[0]["status"] is None


def test_compact_asset_name_removes_spaces_keeps_underscores():
    assert compact_asset_name("Bat Croissants") == "BatCroissants"
    assert compact_asset_name("Gargoyle_Handle x") == "Gargoyle_Handlex"


def test_match_ref_files_base_and_variants():
    files = ["BatCroissants.png", "BatCroissants_2.png", "BatCroissantsExtra.png",
             "batcroissants.png", "Other.png"]
    assert match_ref_files("Bat Croissants", files) == [
        "BatCroissants.png", "BatCroissants_2.png"]
    assert match_ref_files("Nope", files) == []
    assert match_ref_files("", files) == []


def test_group_order_events_first_appearance_order_and_event_name():
    rows = extract_order_rows(_grid(
        HEADER,
        _row("Crate", "", "Chest A"),
        _row("QE 2", "Coven of Shadows", "Cat"),
        _row("Crate", "Pastel Enchantment", "Chest B"),
    ))
    events = group_order_events(rows, ["Cat.png"])
    assert [e["feature"] for e in events] == ["Crate", "QE 2"]
    assert events[0]["eventName"] == "Pastel Enchantment"  # first non-empty wins
    assert events[1]["assets"][0]["refFiles"] == ["Cat.png"]
    assert events[0]["assets"][0]["refFiles"] == []


def test_group_empty_feature_bucket():
    rows = extract_order_rows(_grid(HEADER, _row("", "", "Orphan")))
    assert group_order_events(rows, [])[0]["feature"] == "(no feature)"


def test_template_groups_by_category_canvas_with_slug():
    rows = extract_order_rows(_grid(
        HEADER,
        _row("QE 2", "Coven", "Cat", category="Food - 3 stages", canvas="128x128"),
        _row("QE 2", "", "Dog", category="Food - 3 stages", canvas="128x128"),
        _row("QE 2", "", "Arch", category="Appliance", canvas="128x256"),
        _row("QE 2", "", ""),  # unnamed placeholder skipped
    ))
    groups = template_groups(group_order_events(rows, [])[0])
    assert [g["template"] for g in groups] == [
        "qe-2-food-3-stages-128x128", "qe-2-appliance-128x256"]
    assert len(groups[0]["assets"]) == 2


def test_slugify():
    assert slugify("QE 2-Appliance-128x128") == "qe-2-appliance-128x128"
    assert slugify("--Mini 1! Food--") == "mini-1-food"


def test_canvas_spec_of():
    assert canvas_spec_of("128x128") == {"w": 128, "h": 128}
    assert canvas_spec_of(" 200 X 100 ") == {"w": 200, "h": 100}
    assert canvas_spec_of("-") is None
    assert canvas_spec_of("") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_order_sheet.py -v`
Expected: new tests FAIL with `ImportError: cannot import name 'extract_order_rows'`

- [ ] **Step 3: Implement (append to `py/pipeline/order_sheet.py`)**

```python
# Header labels we locate columns by (matched case-insensitively, trimmed).
HEADERS = {
    "status": "status",
    "release": "release",
    "feature": "feature",
    "eventName": "event name",
    "assetName": "asset name",
    "assetId": "id",
    "category": "asset category",
    "canvas": "canvas",
    "plot": "plot",
    "rotation": "rotation",
    "prompt": "prompt",
    "sets": "sets #",
}


def _norm(s: str) -> str:
    return s.strip().lower()


def _number(s: str):
    try:
        f = float(s)
    except ValueError:
        return None  # JS Number("junk") is NaN; NaN serializes to null anyway.
    return int(f) if f == int(f) else f


def extract_order_rows(grid: list[list[str]]) -> list[dict]:
    """Find the header row (contains both "Feature" and "Asset Name"), map
    columns by header text, and type every data row below it. Rows with neither
    a feature nor an asset name are dropped; placeholder rows (feature only)
    are kept so unspecced slots stay visible."""
    header_row = -1
    for r, row in enumerate(grid):
        cells = [_norm(c) for c in row]
        if "feature" in cells and "asset name" in cells:
            header_row = r
            break
    if header_row < 0:
        raise ValueError(
            'order sheet: header row not found (needs "Feature" and "Asset Name" columns)'
        )

    cols: dict[str, int] = {}
    for i, cell_text in enumerate(grid[header_row]):
        label = _norm(cell_text)
        for key, header in HEADERS.items():
            # First matching column wins — later duplicate headers (artist copies) lose.
            if label == header and key not in cols:
                cols[key] = i

    def cell(row: list[str], key: str) -> str:
        i = cols.get(key)
        if i is None or i >= len(row):
            return ""
        return (row[i] or "").strip()

    rows: list[dict] = []
    for r in range(header_row + 1, len(grid)):
        raw = grid[r]
        feature = cell(raw, "feature")
        asset_name = cell(raw, "assetName")
        if not feature and not asset_name:
            continue
        status_text = cell(raw, "status")
        rows.append({
            "row": r + 1,
            "status": None if status_text == "" else _number(status_text),
            "release": cell(raw, "release"),
            "feature": feature,
            "eventName": cell(raw, "eventName"),
            "assetName": asset_name,
            "assetId": cell(raw, "assetId"),
            "category": cell(raw, "category"),
            "canvas": cell(raw, "canvas"),
            "plot": cell(raw, "plot"),
            "rotation": cell(raw, "rotation"),
            "prompt": cell(raw, "prompt"),
            "sets": cell(raw, "sets"),
        })
    return rows


def compact_asset_name(name: str) -> str:
    """Asset name -> the compact form used by reference filenames: spaces
    removed, everything else (underscores, case) kept as-is."""
    return re.sub(r"\s+", "", name)


def match_ref_files(asset_name: str, file_names: list[str]) -> list[str]:
    """Reference files whose basename is the asset's compact name, optionally
    with a _N variant suffix ("BatCroissants.png", "BatCroissants_2.png")."""
    compact = compact_asset_name(asset_name)
    if not compact:
        return []
    pattern = re.compile(rf"^{re.escape(compact)}(_\d+)?\.[a-zA-Z0-9]+$")
    return sorted(f for f in file_names if pattern.match(f))


def slugify(s: str) -> str:
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", s.lower()))


def canvas_spec_of(canvas: str) -> dict | None:
    """Parse "128x128" (case/space tolerant) into {"w", "h"}; None otherwise."""
    m = re.match(r"^(\d+)x(\d+)$", re.sub(r"\s+", "", canvas.lower()))
    return {"w": int(m.group(1)), "h": int(m.group(2))} if m else None


def group_order_events(rows: list[dict], ref_file_names: list[str]) -> list[dict]:
    """Group order rows into events by Feature (first-appearance order), attach
    matched reference files per asset. Event name = first non-empty one seen."""
    by_feature: dict[str, dict] = {}
    for row in rows:
        key = row["feature"] or "(no feature)"
        event = by_feature.get(key)
        if event is None:
            event = {"feature": key, "eventName": row["eventName"], "assets": []}
            by_feature[key] = event
        if not event["eventName"] and row["eventName"]:
            event["eventName"] = row["eventName"]
        event["assets"].append(
            {**row, "refFiles": match_ref_files(row["assetName"], ref_file_names)}
        )
    return list(by_feature.values())


def template_groups(event: dict) -> list[dict]:
    """Group an event's named assets by category + canvas into template sheets —
    the unit one generation pass renders. Unnamed placeholder rows are skipped."""
    groups: dict[str, dict] = {}
    for asset in event["assets"]:
        if not asset["assetName"]:
            continue
        key = f"{asset['category']}|{asset['canvas']}"
        group = groups.get(key)
        if group is None:
            group = {
                "template": slugify(f"{event['feature']}-{asset['category']}-{asset['canvas']}"),
                "category": asset["category"],
                "canvas": asset["canvas"],
                "assets": [],
            }
            groups[key] = group
        group["assets"].append(asset)
    return list(groups.values())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_order_sheet.py -v`
Expected: all PASS (18 total)

- [ ] **Step 5: Commit**

```bash
git add py/pipeline/order_sheet.py tests/test_order_sheet.py
git commit -m "feat(pipeline): order rows, ref matching, event/template grouping"
```

---

### Task 3: Order loader + spec/overview outputs

**Files:**
- Create: `py/pipeline/order_loader.py`
- Create: `tests/test_order_loader.py`

**Interfaces:**
- Produces (consumed by nodes in Task 7):
  - `load_order(order_path: str, refs_path: str = "") -> dict` — `{"events": [...], "refFileCount": int}`; raises `ValueError` with hub-matching messages on unreadable paths.
  - `event_spec(events: list[dict], feature: str) -> dict` — `{"feature", "eventName", "templates": template_groups(...)}` (FULL asset dicts, incl. `refFiles`); raises `ValueError` listing available features when not found.
  - `spec_wire_json(spec: dict) -> str` — hub's `orderOutput` selected-feature JSON (trimmed asset keys `name,id,canvas,plot,rotation,prompt,refFiles`, `indent=1`) for previews.
  - `order_overview(events: list[dict]) -> dict` — `{"events": [{feature, eventName, assetCount, named, refMatched}]}`.
- Reference: hub `flows/order-read.ts` (all 94 lines).

- [ ] **Step 1: Write failing tests**

`tests/test_order_loader.py`:
```python
# ABOUTME: Tests for load_order (filesystem xlsx + refs folder) and the
# ABOUTME: event-spec / overview output shapes ported from hub order-read.ts.
import json

import pytest
from conftest import inline_cell, make_xlsx, sheet_of_rows

from pipeline.order_loader import (
    event_spec,
    load_order,
    order_overview,
    spec_wire_json,
)


def _order_xlsx() -> bytes:
    header = "".join(
        inline_cell(f"{col}1", text)
        for col, text in zip("ABCDEFG", ["Feature", "Event Name", "Asset Name",
                                         "ID", "Asset Category", "Canvas", "Prompt"])
    )
    row2 = "".join(
        inline_cell(f"{col}2", text)
        for col, text in zip("ABCDEFG", ["Mini 1", "Ghostly Goodies", "Bat Croissants",
                                         "1", "Food - 3 stages", "128x128", "spooky bread"])
    )
    row3 = "".join(
        inline_cell(f"{col}3", text)
        for col, text in zip("ABCDEFG", ["Mini 1", "", "Ghost Cake",
                                         "2", "Decoration", "256x256", "a cake"])
    )
    return make_xlsx(sheet_of_rows(header, row2, row3))


@pytest.fixture
def order_dir(tmp_path):
    order = tmp_path / "Order.xlsx"
    order.write_bytes(_order_xlsx())
    refs = tmp_path / "refs"
    refs.mkdir()
    (refs / "BatCroissants.png").write_bytes(b"x")
    (refs / "BatCroissants_2.png").write_bytes(b"x")
    (refs / ".DS_Store").write_bytes(b"x")
    return order, refs


def test_load_order_parses_and_counts_refs(order_dir):
    order, refs = order_dir
    loaded = load_order(str(order), str(refs))
    assert loaded["refFileCount"] == 2  # dotfiles excluded
    assert len(loaded["events"]) == 1
    assets = loaded["events"][0]["assets"]
    assert assets[0]["refFiles"] == ["BatCroissants.png", "BatCroissants_2.png"]
    assert assets[1]["refFiles"] == []


def test_load_order_without_refs_path(order_dir):
    order, _ = order_dir
    loaded = load_order(str(order), "")
    assert loaded["refFileCount"] == 0


def test_load_order_unreadable_paths(tmp_path, order_dir):
    order, _ = order_dir
    with pytest.raises(ValueError, match="order file not readable"):
        load_order(str(tmp_path / "nope.xlsx"), "")
    with pytest.raises(ValueError, match="references folder not readable"):
        load_order(str(order), str(tmp_path / "norefs"))


def test_event_spec_selected_feature(order_dir):
    order, refs = order_dir
    events = load_order(str(order), str(refs))["events"]
    spec = event_spec(events, "Mini 1")
    assert spec["feature"] == "Mini 1"
    assert spec["eventName"] == "Ghostly Goodies"
    assert [t["template"] for t in spec["templates"]] == [
        "mini-1-food-3-stages-128x128", "mini-1-decoration-256x256"]
    # Full asset dicts survive (builder needs them).
    assert spec["templates"][0]["assets"][0]["assetName"] == "Bat Croissants"


def test_event_spec_unknown_feature_lists_available(order_dir):
    order, refs = order_dir
    events = load_order(str(order), str(refs))["events"]
    with pytest.raises(ValueError, match=r'"QE 9" is not in the parsed order \(have: Mini 1\)'):
        event_spec(events, "QE 9")


def test_spec_wire_json_trims_asset_keys(order_dir):
    order, refs = order_dir
    spec = event_spec(load_order(str(order), str(refs))["events"], "Mini 1")
    wire = json.loads(spec_wire_json(spec))
    asset = wire["templates"][0]["assets"][0]
    assert set(asset) == {"name", "id", "canvas", "plot", "rotation", "prompt", "refFiles"}
    assert asset["name"] == "Bat Croissants"


def test_order_overview_counts(order_dir):
    order, refs = order_dir
    events = load_order(str(order), str(refs))["events"]
    ov = order_overview(events)
    assert ov["events"] == [{"feature": "Mini 1", "eventName": "Ghostly Goodies",
                             "assetCount": 2, "named": 2, "refMatched": 1}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_order_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.order_loader'`

- [ ] **Step 3: Implement `py/pipeline/order_loader.py`**

```python
# ABOUTME: Runner side of the Order Read node — loads a client order (local xlsx +
# ABOUTME: reference-image folder) and emits per-event specs for downstream nodes.
# Port of symbiotica-hub apps/web/src/lib/flows/order-read.ts.
from __future__ import annotations

import json
import os

from .order_sheet import (
    extract_order_rows,
    group_order_events,
    parse_xlsx_grid,
    template_groups,
)


def load_order(order_path: str, refs_path: str = "") -> dict:
    """Read the order xlsx + list the refs folder (names only — images are
    never opened) and group into events."""
    try:
        with open(order_path, "rb") as f:
            data = f.read()
    except OSError:
        raise ValueError(f"order file not readable: {order_path}")
    ref_files: list[str] = []
    if refs_path:
        try:
            ref_files = [n for n in os.listdir(refs_path) if not n.startswith(".")]
        except OSError:
            raise ValueError(f"references folder not readable: {refs_path}")
    events = group_order_events(extract_order_rows(parse_xlsx_grid(data)), ref_files)
    return {"events": events, "refFileCount": len(ref_files)}


def event_spec(events: list[dict], feature: str) -> dict:
    """The picked event's full spec: its template groups with complete asset
    dicts (the Template builder needs category/canvas/prompt/refFiles)."""
    event = next((e for e in events if e["feature"] == feature), None)
    if event is None:
        have = ", ".join(e["feature"] for e in events)
        raise ValueError(
            f'selected feature "{feature}" is not in the parsed order (have: {have})'
        )
    return {
        "feature": event["feature"],
        "eventName": event["eventName"],
        "templates": template_groups(event),
    }


def spec_wire_json(spec: dict) -> str:
    """Hub's orderOutput(selected) wire shape — trimmed per-asset keys."""
    return json.dumps(
        {
            "feature": spec["feature"],
            "eventName": spec["eventName"],
            "templates": [
                {
                    "template": g["template"],
                    "category": g["category"],
                    "canvas": g["canvas"],
                    "assets": [
                        {
                            "name": a["assetName"],
                            "id": a["assetId"],
                            "canvas": a["canvas"],
                            "plot": a["plot"],
                            "rotation": a["rotation"],
                            "prompt": a["prompt"],
                            "refFiles": a["refFiles"],
                        }
                        for a in g["assets"]
                    ],
                }
                for g in spec["templates"]
            ],
        },
        indent=1,
    )


def order_overview(events: list[dict]) -> dict:
    """Month overview — one summary entry per event (the node's own preview)."""
    out = []
    for e in events:
        named = [a for a in e["assets"] if a["assetName"]]
        out.append({
            "feature": e["feature"],
            "eventName": e["eventName"],
            "assetCount": len(e["assets"]),
            "named": len(named),
            "refMatched": len([a for a in named if a["refFiles"]]),
        })
    return {"events": out}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/ -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add py/pipeline/order_loader.py tests/test_order_loader.py
git commit -m "feat(pipeline): order loader with event spec and overview outputs"
```

---

### Task 4: Model presets + packing algorithms

**Files:**
- Create: `py/pipeline/model_presets.py`
- Create: `py/pipeline/texture_pack.py`
- Create: `tests/test_texture_pack.py`

**Interfaces:**
- Produces (consumed by Tasks 5/6/7):
  - `model_presets.TIER_PX: dict[str, int]`, `MODEL_PRESETS: list[dict]`, `aspect_dims(ar, tier) -> dict`, `preset_dims(sel: dict | None) -> dict | None`
  - `texture_pack.PackSettings` dataclass — fields `algorithm ('shelf'|'maxrects'|'grid')`, `preset (dict|None)`, `max_width, max_height, padding, border, grid_cell, columns: int`, `force_square, power_of_two, distribute_by_folder: bool`, `background: str` (hex or `""` for transparent)
  - `texture_pack.pack(sprites: list[dict], settings) -> dict` — sprites `{id, name, path, width, height}`; result `{"placed": [{id,x,y,width,height}], "overflow": [ids], "width", "height"}`
  - `texture_pack.effective_max(settings) -> dict`, `sheet_size(width, height, settings) -> dict`
- Reference: hub `texture-pack/pack.ts` (all 341 lines), `texture-pack/model-presets.ts`, `texture-pack/types.ts`.

- [ ] **Step 1: Write failing tests**

`tests/test_texture_pack.py`:
```python
# ABOUTME: Tests for the packing algorithms (shelf/grid/maxrects/by-folder) and
# ABOUTME: model-preset sheet sizing — ported behaviors from hub pack.ts.
from pipeline.model_presets import aspect_dims, preset_dims
from pipeline.texture_pack import PackSettings, effective_max, pack, sheet_size


def sprite(sid, w, h, path=None):
    return {"id": sid, "name": sid, "path": path or f"Cat/{sid}/{sid}.png",
            "width": w, "height": h}


def test_preset_dims_nano_banana_pro_2k_square():
    assert preset_dims({"model": "nano-banana-pro", "tier": "2K", "ar": "1:1"}) == \
        {"w": 2048, "h": 2048}


def test_aspect_dims_long_edge_and_round8():
    assert aspect_dims("16:9", "1K") == {"w": 1024, "h": 576}
    assert aspect_dims("9:16", "1K") == {"w": 576, "h": 1024}


def test_preset_dims_invalid_returns_none():
    assert preset_dims(None) is None
    assert preset_dims({"model": "nope", "tier": "1K", "ar": "1:1"}) is None
    assert preset_dims({"model": "imagen-4", "tier": "4K", "ar": "1:1"}) is None


def test_effective_max_prefers_preset():
    s = PackSettings(preset={"model": "nano-banana-pro", "tier": "1K", "ar": "1:1"},
                     max_width=99, max_height=99)
    assert effective_max(s) == {"w": 1024, "h": 1024}
    assert effective_max(PackSettings(max_width=99, max_height=77)) == {"w": 99, "h": 77}


def test_shelf_packs_tallest_first_rows():
    s = PackSettings(algorithm="shelf", preset=None, max_width=100, max_height=100)
    res = pack([sprite("a", 40, 10), sprite("b", 40, 30), sprite("c", 40, 20)], s)
    by_id = {p["id"]: p for p in res["placed"]}
    assert by_id["b"]["y"] == 0 and by_id["c"]["y"] == 0  # tallest two on shelf 1
    assert by_id["a"]["y"] == 30  # next shelf below the tallest
    assert res["overflow"] == []


def test_shelf_overflow_when_too_tall():
    s = PackSettings(algorithm="shelf", preset=None, max_width=50, max_height=25)
    res = pack([sprite("a", 40, 20), sprite("b", 40, 20)], s)
    assert res["overflow"] == ["b"]


def test_grid_centres_in_cells():
    s = PackSettings(algorithm="grid", preset=None, max_width=100, max_height=100,
                     grid_cell=50)
    res = pack([sprite("a", 30, 30), sprite("b", 30, 30), sprite("c", 30, 30)], s)
    by_id = {p["id"]: p for p in res["placed"]}
    assert (by_id["a"]["x"], by_id["a"]["y"]) == (10, 10)
    assert (by_id["b"]["x"], by_id["b"]["y"]) == (60, 10)
    assert (by_id["c"]["x"], by_id["c"]["y"]) == (10, 60)


def test_maxrects_places_all_when_they_fit():
    s = PackSettings(algorithm="maxrects", preset=None, max_width=100, max_height=100)
    res = pack([sprite("a", 50, 50), sprite("b", 50, 50), sprite("c", 50, 50),
                sprite("d", 50, 50)], s)
    assert res["overflow"] == []
    coords = {(p["x"], p["y"]) for p in res["placed"]}
    assert coords == {(0, 0), (50, 0), (0, 50), (50, 50)}


def test_distribute_by_folder_rows_spread_evenly():
    s = PackSettings(preset=None, max_width=100, max_height=100,
                     distribute_by_folder=True)
    res = pack([sprite("a", 20, 10, "Food/A/a.png"), sprite("b", 20, 10, "Food/A/b.png"),
                sprite("c", 20, 10, "Deco/C/c.png")], s)
    by_id = {p["id"]: p for p in res["placed"]}
    # Two folder rows (A, C) of height 10 → gap = (100-20)/3.
    gap = (100 - 20) / 3
    assert abs(by_id["a"]["y"] - gap) < 1e-6
    assert abs(by_id["c"]["y"] - (gap * 2 + 10)) < 1e-6
    # Row 1 (a+b, width 40) centred: x starts at 30.
    assert abs(by_id["a"]["x"] - 30) < 1e-6


def test_border_shifts_placements():
    s = PackSettings(algorithm="shelf", preset=None, max_width=100, max_height=100,
                     border=10)
    res = pack([sprite("a", 20, 20)], s)
    assert (res["placed"][0]["x"], res["placed"][0]["y"]) == (10, 10)


def test_padding_inflates_boxes():
    s = PackSettings(algorithm="shelf", preset=None, max_width=100, max_height=100,
                     padding=4)
    res = pack([sprite("a", 20, 20), sprite("b", 20, 20)], s)
    by_id = {p["id"]: p for p in res["placed"]}
    assert by_id["b"]["x"] - by_id["a"]["x"] == 24


def test_sheet_size_preset_locks_pow2_square_otherwise():
    preset = PackSettings(preset={"model": "nano-banana-pro", "tier": "1K", "ar": "1:1"})
    assert sheet_size(10, 10, preset) == {"w": 1024, "h": 1024}
    free = PackSettings(preset=None, force_square=True, power_of_two=True)
    assert sheet_size(300, 500, free) == {"w": 512, "h": 512}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_texture_pack.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `py/pipeline/model_presets.py`**

```python
# ABOUTME: Native output resolutions for the image models we target — port of
# ABOUTME: hub texture-pack/model-presets.ts (long-edge convention, x8 snapping).
from __future__ import annotations

TIER_PX = {"0.5K": 512, "1K": 1024, "2K": 2048, "4K": 4096}

MODEL_PRESETS = [
    {
        "id": "nano-banana-pro",
        "label": "Nano Banana Pro",
        "endpoint": "fal-ai/nano-banana-pro",
        "tiers": ["1K", "2K", "4K"],
        "aspectRatios": ["21:9", "16:9", "3:2", "4:3", "5:4", "1:1", "4:5", "3:4",
                          "2:3", "9:16"],
    },
    {
        "id": "nano-banana-2",
        "label": "Nano Banana 2",
        "endpoint": "fal-ai/nano-banana-2",
        "tiers": ["0.5K", "1K", "2K", "4K"],
        "aspectRatios": ["21:9", "16:9", "3:2", "4:3", "5:4", "1:1", "4:5", "3:4",
                          "2:3", "9:16", "4:1", "1:4", "8:1", "1:8"],
    },
    {
        "id": "imagen-4",
        "label": "Imagen 4",
        "endpoint": "fal-ai/imagen4",
        "tiers": ["1K", "2K"],
        "aspectRatios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
    },
]


def _round8(n: float) -> int:
    return max(8, round(n / 8) * 8)


def aspect_dims(ar: str, tier: str) -> dict:
    """Pixel dimensions for an aspect ratio at a resolution tier."""
    long_edge = TIER_PX[tier]
    try:
        a, b = (int(x) for x in ar.split(":"))
    except ValueError:
        return {"w": long_edge, "h": long_edge}
    if not a or not b:
        return {"w": long_edge, "h": long_edge}
    if a >= b:
        return {"w": long_edge, "h": _round8(long_edge * b / a)}
    return {"w": _round8(long_edge * a / b), "h": long_edge}


def preset_dims(sel: dict | None) -> dict | None:
    """Resolve a stored selection {model, tier, ar} to exact pixel dims."""
    if not sel:
        return None
    model = next((m for m in MODEL_PRESETS if m["id"] == sel.get("model")), None)
    if (
        model is None
        or sel.get("tier") not in model["tiers"]
        or sel.get("ar") not in model["aspectRatios"]
    ):
        return None
    return aspect_dims(sel["ar"], sel["tier"])
```

- [ ] **Step 4: Implement `py/pipeline/texture_pack.py`**

```python
# ABOUTME: Pure packing algorithms (maxrects/shelf/grid/by-folder) — port of hub
# ABOUTME: texture-pack/pack.ts. Takes sprite dicts + settings, returns placements.
from __future__ import annotations

from dataclasses import dataclass, field

from .model_presets import preset_dims


@dataclass
class PackSettings:
    algorithm: str = "shelf"  # 'maxrects' | 'shelf' | 'grid'
    preset: dict | None = field(
        default_factory=lambda: {"model": "nano-banana-pro", "tier": "1K", "ar": "1:1"}
    )
    max_width: int = 2048
    max_height: int = 2048
    padding: int = 0
    border: int = 0
    force_square: bool = False
    power_of_two: bool = False
    grid_cell: int = 0
    distribute_by_folder: bool = False
    columns: int = 0
    background: str = "#808080"  # "" = transparent


def effective_max(settings: PackSettings) -> dict:
    dims = preset_dims(settings.preset)
    if dims:
        return dims
    return {"w": settings.max_width, "h": settings.max_height}


def _boxes_for(sprites: list[dict], padding: int) -> list[dict]:
    return [{"id": s["id"], "w": s["width"] + padding, "h": s["height"] + padding}
            for s in sprites]


def _intersects(a: dict, b: dict) -> bool:
    return (a["x"] < b["x"] + b["w"] and a["x"] + a["w"] > b["x"]
            and a["y"] < b["y"] + b["h"] and a["y"] + a["h"] > b["y"])


def _contains(a: dict, b: dict) -> bool:
    return (b["x"] >= a["x"] and b["y"] >= a["y"]
            and b["x"] + b["w"] <= a["x"] + a["w"]
            and b["y"] + b["h"] <= a["y"] + a["h"])


def _prune(rects: list[dict]) -> list[dict]:
    out = list(rects)
    i = 0
    while i < len(out):
        j = i + 1
        removed_i = False
        while j < len(out):
            if _contains(out[j], out[i]):
                out.pop(i)
                removed_i = True
                break
            if _contains(out[i], out[j]):
                out.pop(j)
                continue
            j += 1
        if not removed_i:
            i += 1
    return out


def _pack_maxrects(boxes: list[dict], max_w: int, max_h: int) -> dict:
    order = sorted(boxes, key=lambda b: (-max(b["w"], b["h"]), -b["w"] * b["h"]))
    free = [{"x": 0, "y": 0, "w": max_w, "h": max_h}]
    placed, overflow = [], []
    used_w = used_h = 0
    for box in order:
        best = None
        for f in free:
            if box["w"] <= f["w"] and box["h"] <= f["h"]:
                leftover_h = f["w"] - box["w"]
                leftover_v = f["h"] - box["h"]
                short_side, long_side = sorted((leftover_h, leftover_v))
                if (best is None or short_side < best[2]
                        or (short_side == best[2] and long_side < best[3])):
                    best = (f["x"], f["y"], short_side, long_side)
        if best is None:
            overflow.append(box["id"])
            continue
        node = {"x": best[0], "y": best[1], "w": box["w"], "h": box["h"]}
        placed.append({"id": box["id"], "x": node["x"], "y": node["y"],
                       "width": box["w"], "height": box["h"]})
        used_w = max(used_w, node["x"] + box["w"])
        used_h = max(used_h, node["y"] + box["h"])
        nxt = []
        for f in free:
            if not _intersects(f, node):
                nxt.append(f)
                continue
            if f["x"] < node["x"] < f["x"] + f["w"]:
                nxt.append({"x": f["x"], "y": f["y"], "w": node["x"] - f["x"], "h": f["h"]})
            if node["x"] + node["w"] < f["x"] + f["w"]:
                nxt.append({"x": node["x"] + node["w"], "y": f["y"],
                            "w": f["x"] + f["w"] - (node["x"] + node["w"]), "h": f["h"]})
            if f["y"] < node["y"] < f["y"] + f["h"]:
                nxt.append({"x": f["x"], "y": f["y"], "w": f["w"], "h": node["y"] - f["y"]})
            if node["y"] + node["h"] < f["y"] + f["h"]:
                nxt.append({"x": f["x"], "y": node["y"] + node["h"], "w": f["w"],
                            "h": f["y"] + f["h"] - (node["y"] + node["h"])})
        free = _prune(nxt)
    return {"placed": placed, "overflow": overflow, "width": used_w, "height": used_h}


def _pack_shelf(boxes: list[dict], max_w: int, max_h: int) -> dict:
    order = sorted(boxes, key=lambda b: -b["h"])  # stable, like JS sort
    placed, overflow = [], []
    shelf_x = shelf_y = shelf_h = used_w = 0
    for box in order:
        if box["w"] > max_w or box["h"] > max_h:
            overflow.append(box["id"])
            continue
        if shelf_x + box["w"] > max_w:
            shelf_y += shelf_h
            shelf_x = 0
            shelf_h = 0
        if shelf_y + box["h"] > max_h:
            overflow.append(box["id"])
            continue
        placed.append({"id": box["id"], "x": shelf_x, "y": shelf_y,
                       "width": box["w"], "height": box["h"]})
        shelf_x += box["w"]
        shelf_h = max(shelf_h, box["h"])
        used_w = max(used_w, shelf_x)
    return {"placed": placed, "overflow": overflow, "width": used_w,
            "height": shelf_y + shelf_h}


def _pack_grid(boxes: list[dict], max_w: int, max_h: int, cell: int) -> dict:
    c = cell if cell > 0 else max(1, max((max(b["w"], b["h"]) for b in boxes), default=1))
    cols = max(1, max_w // c)
    placed, overflow = [], []
    used_w = used_h = 0
    for i, box in enumerate(boxes):
        col, row = i % cols, i // cols
        cx, cy = col * c, row * c
        if cy + c > max_h:
            overflow.append(box["id"])
            continue
        placed.append({"id": box["id"], "x": cx + max(0, (c - box["w"]) / 2),
                       "y": cy + max(0, (c - box["h"]) / 2),
                       "width": box["w"], "height": box["h"]})
        used_w = max(used_w, cx + c)
        used_h = max(used_h, cy + c)
    return {"placed": placed, "overflow": overflow, "width": used_w, "height": used_h}


def _parent_folder(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else path


def _pack_by_folder(sprites: list[dict], padding: int, max_w: int, max_h: int,
                    columns: int) -> dict:
    placed, overflow = [], []
    groups: dict[str, list[dict]] = {}
    for s in sprites:
        box = {"id": s["id"], "w": s["width"] + padding, "h": s["height"] + padding}
        groups.setdefault(_parent_folder(s["path"]), []).append(box)

    rows: list[list[dict]] = []
    for boxes in groups.values():
        row: list[dict] = []
        row_w = 0
        for box in boxes:
            if box["w"] > max_w or box["h"] > max_h:
                overflow.append(box["id"])
                continue
            wrap_by_count = columns > 0 and len(row) >= columns
            wrap_by_width = row and row_w + box["w"] > max_w
            if wrap_by_count or wrap_by_width:
                rows.append(row)
                row, row_w = [], 0
            row.append(box)
            row_w += box["w"]
        if row:
            rows.append(row)

    if not rows:
        return {"placed": placed, "overflow": overflow, "width": max_w, "height": max_h}

    row_h = [max(b["h"] for b in r) for r in rows]
    total_h = sum(row_h)
    fits = total_h <= max_h
    gap = (max_h - total_h) / (len(rows) + 1) if fits else 0

    y = gap
    r = 0
    while r < len(rows):
        row, h = rows[r], row_h[r]
        if not fits and y + h > max_h:
            break
        row_w = sum(b["w"] for b in row)
        x = max(0, (max_w - row_w) / 2)
        for box in row:
            placed.append({"id": box["id"], "x": x, "y": y + max(0, (h - box["h"]) / 2),
                           "width": box["w"], "height": box["h"]})
            x += box["w"]
        y += h + gap
        r += 1
    while r < len(rows):
        overflow.extend(b["id"] for b in rows[r])
        r += 1
    return {"placed": placed, "overflow": overflow, "width": max_w, "height": max_h}


def pack(sprites: list[dict], settings: PackSettings) -> dict:
    """Dispatch to the chosen algorithm. Sprites must already be the enabled set."""
    if not sprites:
        return {"placed": [], "overflow": [], "width": 0, "height": 0}
    boxes = _boxes_for(sprites, settings.padding)
    mx = effective_max(settings)
    usable_w = max(1, mx["w"] - settings.border * 2)
    usable_h = max(1, mx["h"] - settings.border * 2)

    if settings.distribute_by_folder:
        res = _pack_by_folder(sprites, settings.padding, usable_w, usable_h,
                              settings.columns)
    elif settings.algorithm == "shelf":
        res = _pack_shelf(boxes, usable_w, usable_h)
    elif settings.algorithm == "grid":
        res = _pack_grid(boxes, usable_w, usable_h, settings.grid_cell)
    else:
        res = _pack_maxrects(boxes, usable_w, usable_h)

    if settings.border > 0:
        res["placed"] = [{**p, "x": p["x"] + settings.border,
                          "y": p["y"] + settings.border} for p in res["placed"]]
        res["width"] += settings.border * 2
        res["height"] += settings.border * 2
    return res


def sheet_size(width: float, height: float, settings: PackSettings) -> dict:
    """Final sheet size: preset locks native pixels; else content bounds rounded
    by force-square / power-of-two."""
    dims = preset_dims(settings.preset)
    if dims:
        return dims
    w, h = width, height
    if settings.force_square:
        w = h = max(w, h)
    if settings.power_of_two:
        w, h = _next_pow2(w), _next_pow2(h)
    return {"w": max(1, int(w)), "h": max(1, int(h))}


def _next_pow2(n: float) -> int:
    p = 1
    while p < n:
        p <<= 1
    return p
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_texture_pack.py -v`
Expected: 12 PASS

- [ ] **Step 6: Commit**

```bash
git add py/pipeline/model_presets.py py/pipeline/texture_pack.py tests/test_texture_pack.py
git commit -m "feat(pipeline): model presets and packing algorithms ported from hub"
```

---

### Task 5: Prefill-from-specs regions

**Files:**
- Create: `py/pipeline/prefill.py`
- Create: `tests/test_prefill.py`

**Interfaces:**
- Produces: `prefill_regions(order_assets: list[dict], sheet_w: int, sheet_h: int, chosen: dict[str, list[str]] | None = None, settings: PackSettings | None = None) -> dict` — returns `{"regions": [AtlasRegion dicts], "overflow": [asset names]}`. Region dict keys (camelCase, hub `AtlasRegion`): `id ("region:spec:<assetName>"), name, x, y, w, h (normalized 0-1), kind ("object"), desc, text (""), zIndex, assetType, members [{spriteId, x, y, w, h, flipX?}], taskRefs {"paths": [...], "mode": "meta"}`.
- Consumed by Task 6 (compose) and Task 7 (builder node).
- Reference: hub `flows/prefill-regions.ts` (all 175 lines). Constants: `PAD_PX = 16`, `FALLBACK_CELL = 256`.

- [ ] **Step 1: Write failing tests**

`tests/test_prefill.py`:
```python
# ABOUTME: Tests for spec-driven region prefill — one strip per order asset,
# ABOUTME: single-ref flip pairs, multi-ref cells, packed + centered layouts.
from pipeline.prefill import prefill_regions
from pipeline.texture_pack import PackSettings


def asset(name, refs, category="Decoration", canvas="128x128", prompt="p"):
    return {"assetName": name, "category": category, "canvas": canvas,
            "prompt": prompt, "refFiles": refs}


def test_single_ref_makes_flip_pair():
    res = prefill_regions([asset("Cart", ["Cart.png"])], 1024, 1024)
    (region,) = res["regions"]
    assert region["id"] == "region:spec:Cart"
    assert len(region["members"]) == 2
    assert region["members"][0]["spriteId"] == "Decoration/Cart/Cart.png"
    assert region["members"][1].get("flipX") is True
    assert region["taskRefs"] == {"paths": ["Decoration/Cart/Cart.png"], "mode": "meta"}
    assert region["assetType"] == "Decoration"
    assert region["desc"] == "p"


def test_multi_ref_one_cell_each_no_flip():
    res = prefill_regions([asset("Cake", ["Cake.png", "Cake_2.png", "Cake_3.png"])],
                          1024, 1024)
    (region,) = res["regions"]
    assert len(region["members"]) == 3
    assert all("flipX" not in m for m in region["members"])


def test_asset_without_refs_skipped():
    res = prefill_regions([asset("NoRefs", [])], 1024, 1024)
    assert res["regions"] == []


def test_chosen_paths_override_reffiles():
    res = prefill_regions([asset("Cart", ["Cart.png"])], 1024, 1024,
                          chosen={"Cart": ["Custom/Path/x.png", "Custom/Path/y.png"]})
    (region,) = res["regions"]
    assert [m["spriteId"] for m in region["members"]] == \
        ["Custom/Path/x.png", "Custom/Path/y.png"]


def test_unparsable_canvas_uses_fallback_cell():
    res = prefill_regions([asset("Cart", ["Cart.png"], canvas="-")], 1024, 1024)
    (region,) = res["regions"]
    # cell 256 → two cells + 16px pad = 528px wide on a 1024 sheet, scaled if needed
    assert 0 < region["w"] <= 1.0


def test_centered_layout_without_settings():
    res = prefill_regions([asset("A", ["A.png"]), asset("B", ["B.png"])], 1024, 1024)
    r0, r1 = res["regions"]
    assert r0["zIndex"] == 0 and r1["zIndex"] == 1
    assert r0["y"] < r1["y"]
    # strips horizontally centered
    mid0 = r0["x"] + r0["w"] / 2
    assert abs(mid0 - 0.5) < 0.01


def test_packed_layout_with_settings_and_overflow_stacks_below():
    settings = PackSettings(algorithm="shelf", preset=None, max_width=300,
                            max_height=140, distribute_by_folder=False)
    # Each strip: two 128-cells + pad = 272x128 → only one fits in 140 height.
    res = prefill_regions([asset("A", ["A.png"]), asset("B", ["B.png"])],
                          300, 140, settings=settings)
    assert res["overflow"] == ["B"] or res["overflow"] == ["A"]
    assert len(res["regions"]) == 2  # overflowed strip still becomes a region
    zs = [r["zIndex"] for r in sorted(res["regions"], key=lambda r: (r["y"], r["x"]))]
    assert zs == [0, 1]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_prefill.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `py/pipeline/prefill.py`**

```python
# ABOUTME: Spec-driven region prefill — builds template regions FROM the order:
# ABOUTME: one strip per asset, cells at the order's canvas size, xlsx prompt.
# Port of symbiotica-hub apps/web/src/lib/flows/prefill-regions.ts.
from __future__ import annotations

from dataclasses import replace

from .order_sheet import canvas_spec_of
from .texture_pack import PackSettings, pack

PAD_PX = 16
FALLBACK_CELL = 256


def _cell_count(row: dict) -> int:
    return 2 if row["flip"] else len(row["paths"])


def _row_w(row: dict) -> float:
    n = _cell_count(row)
    return n * row["cellW"] + (n - 1) * PAD_PX


def _region_at(row: dict, x_px: float, y_px: float, sheet_w: int, sheet_h: int) -> dict:
    cell_paths = [row["paths"][0], row["paths"][0]] if row["flip"] else row["paths"]
    x = x_px
    members = []
    for i, sprite_id in enumerate(cell_paths):
        m = {"spriteId": sprite_id, "x": x / sheet_w, "y": y_px / sheet_h,
             "w": row["cellW"] / sheet_w, "h": row["cellH"] / sheet_h}
        if row["flip"] and i == 1:
            m["flipX"] = True
        members.append(m)
        x += row["cellW"] + PAD_PX
    x0 = members[0]["x"]
    last = members[-1]
    return {
        "id": f"region:spec:{row['asset']['assetName']}",
        "name": row["asset"]["assetName"],
        "x": x0,
        "y": y_px / sheet_h,
        "w": last["x"] + last["w"] - x0,
        "h": row["cellH"] / sheet_h,
        "kind": "object",
        "desc": row["asset"].get("prompt") or "",
        "text": "",
        "zIndex": 0,
        "assetType": row["asset"]["category"],
        "members": members,
        "taskRefs": {"paths": row["paths"], "mode": "meta"},
    }


def prefill_regions(order_assets: list[dict], sheet_w: int, sheet_h: int,
                    chosen: dict[str, list[str]] | None = None,
                    settings: PackSettings | None = None) -> dict:
    """One region per asset. Single-ref assets show the ref plus a flipped copy
    (the in-game pair convention); multi-ref assets one cell per ref. With
    settings, strips run through the packer (overflow stacks below, visible);
    without, strips stack as centered rows distributed evenly down the sheet."""
    rows: list[dict] = []
    for asset in order_assets:
        picked = (chosen or {}).get(asset["assetName"])
        paths = picked if picked else [
            f"{asset['category']}/{asset['assetName']}/{f}" for f in asset["refFiles"]
        ]
        if not paths:
            continue
        spec = canvas_spec_of(asset["canvas"])
        rows.append({
            "asset": asset,
            "cellW": (spec or {}).get("w", FALLBACK_CELL),
            "cellH": (spec or {}).get("h", FALLBACK_CELL),
            "paths": paths,
            "flip": len(paths) == 1,
        })
    if not rows:
        return {"regions": [], "overflow": []}

    if settings is not None:
        by_name = {r["asset"]["assetName"]: r for r in rows}
        pseudo = [{
            "id": r["asset"]["assetName"],
            "name": r["asset"]["assetName"],
            "path": f"{r['asset']['category']}/{r['asset']['assetName']}",
            "width": _row_w(r),
            "height": r["cellH"],
        } for r in rows]
        result = pack(pseudo, replace(settings, preset=None, max_width=sheet_w,
                                      max_height=sheet_h, force_square=False,
                                      power_of_two=False))
        regions = []
        for p in result["placed"]:
            row = by_name.get(p["id"])
            if row:
                regions.append(_region_at(row, p["x"], p["y"], sheet_w, sheet_h))
        overflow = []
        y_px = (max((r["y"] + r["h"]) * sheet_h for r in regions) + PAD_PX
                if regions else PAD_PX)
        for oid in result["overflow"]:
            row = by_name.get(oid)
            if not row:
                continue
            overflow.append(row["asset"]["assetName"])
            y = min(y_px, sheet_h - row["cellH"])
            regions.append(_region_at(row, PAD_PX, y, sheet_w, sheet_h))
            y_px = y + row["cellH"] + PAD_PX
        regions.sort(key=lambda r: (r["y"], r["x"]))
        for i, r in enumerate(regions):
            r["zIndex"] = i
        return {"regions": regions, "overflow": overflow}

    # No settings: rows top-to-bottom in order-sheet order, each centered,
    # distributed space-evenly, fit-scaled together when they'd overflow.
    total_h = sum(r["cellH"] for r in rows) + (len(rows) + 1) * PAD_PX
    max_w = max(_row_w(r) for r in rows) + 2 * PAD_PX
    scale = min(1, sheet_h / total_h, sheet_w / max_w)
    rows_h = sum(r["cellH"] * scale for r in rows)
    gap = max(0, (sheet_h - rows_h) / (len(rows) + 1))
    regions = []
    y_px = gap
    for index, row in enumerate(rows):
        scaled = {**row, "cellW": row["cellW"] * scale, "cellH": row["cellH"] * scale}
        strip_w = _row_w(scaled)
        x_px = max(0, (sheet_w - strip_w) / 2)
        region = _region_at(scaled, x_px, y_px, sheet_w, sheet_h)
        region["zIndex"] = index
        regions.append(region)
        y_px += scaled["cellH"] + gap
    return {"regions": regions, "overflow": []}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_prefill.py -v`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add py/pipeline/prefill.py tests/test_prefill.py
git commit -m "feat(pipeline): prefill-from-specs region builder"
```

---

### Task 6: Sheet compositing (catalog grid + prefill draw) and save

**Files:**
- Create: `py/pipeline/compose.py`
- Create: `tests/test_compose.py`

**Interfaces:**
- Produces (consumed by Task 7):
  - `scan_images(root: str) -> list[str]` — sorted rel paths (`/`-separated) of images under root; exts `{.png,.jpg,.jpeg,.webp,.gif}`, dot-dirs skipped.
  - `category_candidates(rel_paths: list[str], category: str) -> list[str]` — hub's segment prefix match (`seg.startswith(cat) or cat.startswith(seg)`, case-insensitive).
  - `build_catalog_sheet(group: dict, assets_root: str) -> (PIL.Image, list[dict], int, int)` — hub template-node `buildTemplate()`: cell from group canvas (raises `ValueError` on unparsable canvas or empty group), round-robin candidates preferring exact cell-size art, grid `cols = min(max(1, 1024 // cell_w), n)`, regions `id "region:<assetName>"`, `spriteId slugify(assetName)`, `desc` = prompt, `zIndex` = i, `assetType` = category.
  - `build_prefill_sheet(assets: list[dict], refs_root: str, sheet_w: int, sheet_h: int, settings: PackSettings, chosen=None) -> (PIL.Image, list[dict], list[str])` — regions via `prefill_regions`, background painted per `settings.background`, each member cell draws its ref image contain-fit (flipX mirrors); returns (image, regions, overflow).
  - `save_sheet(img, regions: list[dict], name: str, out_root: str, subdir: str = "templates", meta: dict | None = None) -> str` — writes `<out_root>/<subdir>/<slug>.png` + sidecar `<slug>.json` (`{"name", "size", "spriteCount", "regions", **meta}`), returns rel key `"<subdir>/<slug>.png"`.
- Reference: hub `board/template-node.svelte:74-235` (catalog build), `regional-drawer.svelte` compose behavior (background, no smoothing → use `Image.NEAREST` for pixel-art fidelity when a member cell is smaller than the source, else `LANCZOS`; keep it simple: `LANCZOS` everywhere, matching the node's smoothed drawImage).

- [ ] **Step 1: Write failing tests**

`tests/test_compose.py`:
```python
# ABOUTME: Tests for sheet compositing — catalog grid build, prefill ref draw,
# ABOUTME: and PNG+sidecar saving with slugged names.
import json
import os

import pytest
from PIL import Image

from pipeline.compose import (
    build_catalog_sheet,
    build_prefill_sheet,
    category_candidates,
    save_sheet,
    scan_images,
)
from pipeline.texture_pack import PackSettings


def make_png(path, size=(128, 128), color=(255, 0, 0)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, color).save(path)


@pytest.fixture
def catalog(tmp_path):
    root = tmp_path / "assets"
    make_png(str(root / "Decoration" / "Old Cart" / "cart.png"), (128, 128))
    make_png(str(root / "Decorations" / "Bench" / "bench.png"), (64, 64))
    make_png(str(root / "Food" / "Pie" / "pie.png"), (128, 128))
    make_png(str(root / ".hidden" / "x.png"))
    return str(root)


def test_scan_images_recursive_sorted_no_dotdirs(catalog):
    rels = scan_images(catalog)
    assert rels == ["Decoration/Old Cart/cart.png", "Decorations/Bench/bench.png",
                    "Food/Pie/pie.png"]


def test_category_candidates_prefix_slack(catalog):
    rels = scan_images(catalog)
    # "Decoration" matches both "Decoration" and "Decorations" segments.
    assert category_candidates(rels, "Decoration") == [
        "Decoration/Old Cart/cart.png", "Decorations/Bench/bench.png"]
    assert category_candidates(rels, "food") == ["Food/Pie/pie.png"]
    assert category_candidates(rels, "Chair") == []


def _group(n=2, category="Decoration", canvas="128x128"):
    return {"template": "mini-1-decoration-128x128", "category": category,
            "canvas": canvas,
            "assets": [{"assetName": f"Asset {i}", "prompt": f"prompt {i}",
                        "category": category, "canvas": canvas, "refFiles": []}
                       for i in range(n)]}


def test_build_catalog_sheet_grid_and_regions(catalog):
    img, regions, w, h = build_catalog_sheet(_group(2), catalog)
    # 128px cells → cols = min(1024//128, 2) = 2 → sheet 256x128.
    assert (w, h) == (256, 128)
    assert img.size == (256, 128)
    assert len(regions) == 2
    assert regions[0]["id"] == "region:Asset 0"
    assert regions[0]["desc"] == "prompt 0"
    assert regions[0]["assetType"] == "Decoration"
    assert regions[1]["x"] == 0.5  # second cell starts mid-sheet
    assert regions[0]["zIndex"] == 0 and regions[1]["zIndex"] == 1


def test_build_catalog_sheet_bad_canvas_raises(catalog):
    with pytest.raises(ValueError, match="Can't parse canvas size"):
        build_catalog_sheet(_group(1, canvas="-"), catalog)


def test_build_catalog_sheet_empty_group_raises(catalog):
    group = _group(0)
    with pytest.raises(ValueError, match="no named assets"):
        build_catalog_sheet(group, catalog)


def test_build_prefill_sheet_draws_refs(tmp_path):
    refs = tmp_path / "refs"
    make_png(str(refs / "Cart.png"), (64, 64), (0, 255, 0))
    assets = [{"assetName": "Cart", "category": "Decoration", "canvas": "128x128",
               "prompt": "p", "refFiles": ["Cart.png"]}]
    settings = PackSettings(preset=None, max_width=512, max_height=512,
                            background="#808080")
    img, regions, overflow = build_prefill_sheet(assets, str(refs), 512, 512, settings)
    assert img.size == (512, 512)
    assert overflow == []
    (region,) = regions
    # Sample the center of the first member cell — the green ref must be there.
    m = region["members"][0]
    cx = int((m["x"] + m["w"] / 2) * 512)
    cy = int((m["y"] + m["h"] / 2) * 512)
    assert img.getpixel((cx, cy)) == (0, 255, 0)
    # Outside any region: background gray.
    assert img.getpixel((5, 5)) == (128, 128, 128)


def test_save_sheet_writes_png_and_sidecar(tmp_path):
    img = Image.new("RGB", (64, 64), (1, 2, 3))
    regions = [{"id": "region:A", "zIndex": 0}]
    rel = save_sheet(img, regions, "Mini 08!", str(tmp_path), meta={"template": "g"})
    assert rel == "templates/mini-08.png"
    assert os.path.isfile(tmp_path / "templates" / "mini-08.png")
    sidecar = json.loads((tmp_path / "templates" / "mini-08.json").read_text())
    assert sidecar["size"] == {"w": 64, "h": 64}
    assert sidecar["spriteCount"] == 1
    assert sidecar["regions"] == regions
    assert sidecar["template"] == "g"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_compose.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `py/pipeline/compose.py`**

```python
# ABOUTME: Sheet compositing — catalog-grid template build (port of hub
# ABOUTME: template-node buildTemplate) and prefill-ref drawing, plus PNG+sidecar save.
from __future__ import annotations

import json
import os
import re

from PIL import Image

from .order_sheet import slugify
from .prefill import prefill_regions
from .texture_pack import PackSettings

IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def scan_images(root: str) -> list[str]:
    """Sorted /-separated rel paths of all images under root; dot-dirs skipped."""
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for f in filenames:
            if os.path.splitext(f)[1].lower() in IMG_EXTS and not f.startswith("."):
                rel = os.path.relpath(os.path.join(dirpath, f), root)
                out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def category_candidates(rel_paths: list[str], category: str) -> list[str]:
    """Hub's match: any path segment prefix-matches the category (either way),
    case-insensitive."""
    cat = category.strip().lower()
    if not cat:
        return []
    def matches(rel: str) -> bool:
        for seg in rel.split("/"):
            s = seg.strip().lower()
            if s and (s.startswith(cat) or cat.startswith(s)):
                return True
        return False
    return [r for r in rel_paths if matches(r)]


class _RoundRobinPicker:
    """Round-robin through candidate images preferring exact cell-size art;
    wraps around when every candidate is consumed (more assets than art)."""

    def __init__(self, root: str, candidates: list[str], cell_w: int, cell_h: int):
        self.root = root
        self.candidates = candidates
        self.cell_w = cell_w
        self.cell_h = cell_h
        self.images: list[Image.Image | None | bool] = [False] * len(candidates)
        self.used = [False] * len(candidates)
        self.used_count = 0

    def _image_at(self, idx: int) -> Image.Image | None:
        if self.images[idx] is False:
            try:
                img = Image.open(os.path.join(self.root, self.candidates[idx]))
                img.load()
                self.images[idx] = img.convert("RGBA")
            except OSError:
                self.images[idx] = None
        return self.images[idx] or None

    def _mark(self, idx: int) -> None:
        self.used[idx] = True
        self.used_count += 1

    def pick(self) -> Image.Image | None:
        for _pass in range(2):
            fallback = -1
            for idx in range(len(self.candidates)):
                if self.used[idx]:
                    continue
                img = self._image_at(idx)
                if img is None:
                    self._mark(idx)
                    continue
                if fallback < 0:
                    fallback = idx
                if img.size == (self.cell_w, self.cell_h):
                    self._mark(idx)
                    return img
            if fallback >= 0:
                self._mark(fallback)
                return self._image_at(fallback)
            if self.used_count == 0:
                return None
            self.used = [False] * len(self.candidates)
            self.used_count = 0
        return None


def build_catalog_sheet(group: dict, assets_root: str):
    """Grid sheet from existing catalog art matched to the group's category.
    Returns (PIL.Image RGBA, regions, sheet_w, sheet_h)."""
    m = re.match(r"^(\d+)\s*[xX]\s*(\d+)$", group["canvas"].strip())
    if not m:
        raise ValueError(f"Can't parse canvas size \"{group['canvas']}\" (expected WxH).")
    cell_w, cell_h = int(m.group(1)), int(m.group(2))
    n = len(group["assets"])
    if n == 0:
        raise ValueError("The picked group has no named assets.")

    candidates = category_candidates(scan_images(assets_root), group["category"])
    picker = _RoundRobinPicker(assets_root, candidates, cell_w, cell_h)

    cols = min(max(1, 1024 // cell_w), n)
    sheet_w = cols * cell_w
    rows = -(-n // cols)  # ceil
    sheet_h = rows * cell_h
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))

    regions = []
    for i, asset in enumerate(group["assets"]):
        cx = (i % cols) * cell_w
        cy = (i // cols) * cell_h
        img = picker.pick()
        if img is not None:
            sheet.alpha_composite(img.resize((cell_w, cell_h), Image.LANCZOS), (cx, cy))
        regions.append({
            "id": f"region:{asset['assetName']}",
            "spriteId": slugify(asset["assetName"]),
            "name": asset["assetName"],
            "x": cx / sheet_w,
            "y": cy / sheet_h,
            "w": cell_w / sheet_w,
            "h": cell_h / sheet_h,
            "kind": "object",
            "desc": asset.get("prompt") or "",
            "text": "",
            "zIndex": i,
            "assetType": group["category"],
        })
    return sheet, regions, sheet_w, sheet_h


def _paint_background(sheet_w: int, sheet_h: int, background: str) -> Image.Image:
    if background:
        return Image.new("RGBA", (sheet_w, sheet_h), background)
    return Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))


def _contain_fit(img: Image.Image, w: int, h: int) -> tuple[Image.Image, int, int]:
    scale = min(w / img.width, h / img.height)
    fw, fh = max(1, round(img.width * scale)), max(1, round(img.height * scale))
    return img.resize((fw, fh), Image.LANCZOS), (w - fw) // 2, (h - fh) // 2


def build_prefill_sheet(assets: list[dict], refs_root: str, sheet_w: int,
                        sheet_h: int, settings: PackSettings, chosen=None):
    """Prefill-from-specs sheet: regions via prefill_regions, each member cell
    drawing its reference image contain-fit (flipX mirrors the single-ref pair).
    Returns (PIL.Image, regions, overflow_names)."""
    result = prefill_regions(assets, sheet_w, sheet_h, chosen=chosen,
                             settings=settings)
    sheet = _paint_background(sheet_w, sheet_h, settings.background)
    for region in result["regions"]:
        for member in region.get("members", []):
            # spriteId is "Category/AssetName/file.png"; the actual ref file
            # lives flat in refs_root under its basename.
            filename = member["spriteId"].split("/")[-1]
            path = os.path.join(refs_root, filename)
            try:
                img = Image.open(path)
                img.load()
                img = img.convert("RGBA")
            except OSError:
                continue  # missing ref: cell stays background for the img2img pass
            if member.get("flipX"):
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            cw = max(1, round(member["w"] * sheet_w))
            ch = max(1, round(member["h"] * sheet_h))
            fitted, ox, oy = _contain_fit(img, cw, ch)
            sheet.alpha_composite(
                fitted,
                (round(member["x"] * sheet_w) + ox, round(member["y"] * sheet_h) + oy),
            )
    return sheet, result["regions"], result["overflow"]


def save_sheet(img: Image.Image, regions: list[dict], name: str, out_root: str,
               subdir: str = "templates", meta: dict | None = None) -> str:
    """Write the sheet PNG + JSON sidecar (regions live in the sidecar, not the
    PNG). Returns the rel key "<subdir>/<slug>.png". Re-saves overwrite."""
    stem = slugify(name) or "template"
    out_dir = os.path.join(out_root, subdir)
    os.makedirs(out_dir, exist_ok=True)
    img.save(os.path.join(out_dir, f"{stem}.png"))
    sidecar = {
        "name": stem,
        "size": {"w": img.width, "h": img.height},
        "spriteCount": len(regions),
        "regions": regions,
        **(meta or {}),
    }
    with open(os.path.join(out_dir, f"{stem}.json"), "w") as f:
        json.dump(sidecar, f, indent=1)
    return f"{subdir}/{stem}.png"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/ -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add py/pipeline/compose.py tests/test_compose.py
git commit -m "feat(pipeline): catalog + prefill sheet compositing and sidecar save"
```

---

### Task 7: V3 nodes + registration shim

**Files:**
- Create: `py/pipeline/nodes.py`
- Create: `py/symbiotica_pipeline.py`
- Create: `tests/test_shim.py`

**Interfaces:**
- Consumes: everything from Tasks 3-6.
- Produces:
  - `py/pipeline/nodes.py`: `PIPELINE_NODE_CLASSES` (list of 4 V3 classes), custom types `OrderEvents = io.Custom("SYMBIOTICA_ORDER_EVENTS")`, `EventSpec = io.Custom("SYMBIOTICA_EVENT_SPEC")`, `Template = io.Custom("SYMBIOTICA_TEMPLATE")`.
  - Payload contracts (JS + downstream nodes rely on these):
    - ORDER_EVENTS: `{"events": [OrderEvent...], "refFileCount": int, "refsRoot": str}`
    - EVENT_SPEC: `{"feature", "eventName", "templates": [TemplateGroup...], "refsRoot"}`
    - TEMPLATE: hub `TemplateBundle` — `{"kind": "template", "template", "sheetFile", "templateSize": {"w","h"}, "regions": [...], "refPaths": {assetName: [abs paths]}}`
  - `py/symbiotica_pipeline.py`: `NODE_CLASS_MAPPINGS` / `NODE_DISPLAY_NAME_MAPPINGS` built from `GET_SCHEMA()` — picked up by the root auto-discovery unchanged.
- Reference: V3 skeleton per `~/.claude/skills/comfyui-node-basics/SKILL.md`; loader behavior nodes.py:2275-2311.

- [ ] **Step 1: Write the failing shim test**

`tests/test_shim.py`:
```python
# ABOUTME: Smoke test — the pipeline pure modules import without ComfyUI, and
# ABOUTME: the shim module registers exactly the four pipeline node ids.
import importlib

import pytest


def test_pure_modules_import_without_comfy():
    for mod in ["pipeline.order_sheet", "pipeline.order_loader",
                "pipeline.texture_pack", "pipeline.model_presets",
                "pipeline.prefill", "pipeline.compose"]:
        importlib.import_module(mod)


def test_nodes_module_requires_comfy():
    # Outside ComfyUI the V3 node module must fail cleanly (ImportError),
    # never crash the whole package import.
    with pytest.raises(ImportError):
        importlib.import_module("pipeline.nodes")
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/pytest tests/test_shim.py -v`
Expected: first FAILS (`nodes` doesn't exist yet → second test errors with ModuleNotFoundError, which IS an ImportError subclass — so after Step 3 both pass; right now `test_nodes_module_requires_comfy` may already pass; `test_pure_modules_import_without_comfy` must pass).

- [ ] **Step 3: Implement `py/pipeline/nodes.py`**

```python
# ABOUTME: V3 ComfyUI nodes for the order pipeline — Order Read, Event Specs,
# ABOUTME: Template Builder, Template Prompt. Thin wrappers over py/pipeline/*.
from __future__ import annotations

import hashlib
import json
import os

import numpy as np
import torch
from comfy_api.latest import io, ui

import folder_paths

from .compose import build_catalog_sheet, build_prefill_sheet, save_sheet
from .order_loader import event_spec, load_order, order_overview, spec_wire_json
from .order_sheet import slugify
from .texture_pack import PackSettings

OrderEvents = io.Custom("SYMBIOTICA_ORDER_EVENTS")
EventSpec = io.Custom("SYMBIOTICA_EVENT_SPEC")
Template = io.Custom("SYMBIOTICA_TEMPLATE")

_RESOLUTIONS = ["0.5K", "1K", "2K", "4K"]
_MODELS = ["nano-banana-pro", "nano-banana-2", "imagen-4", "custom"]
_ASPECTS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5",
            "21:9", "4:1", "1:4", "8:1", "1:8"]


def _push(event: str, payload: dict) -> None:
    """Fire-and-forget UI push; absent/failed server must never break execution."""
    try:
        from server import PromptServer
        PromptServer.instance.send_sync(event, payload)
    except Exception:
        pass


def _register_refs_root(path: str) -> None:
    try:
        from .routes import register_root
        register_root(path)
    except Exception:
        pass


def _pil_to_tensor(img) -> torch.Tensor:
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(arr)[None, ...]


class SymbioticaOrderRead(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaOrderRead",
            display_name="Symbiotica Order Read",
            category="symbiotica/pipeline",
            description="Parse a monthly order xlsx + reference-image folder "
                        "into events. Wire an Event Specs node after this to "
                        "pick an event to work on.",
            inputs=[
                io.String.Input("order_path", default="",
                                tooltip="Absolute path to the order .xlsx"),
                io.String.Input("refs_path", default="", optional=True,
                                tooltip="Folder of client reference images"),
            ],
            outputs=[OrderEvents.Output(display_name="events")],
            hidden=[io.Hidden.unique_id],
            is_output_node=True,
        )

    @classmethod
    def fingerprint_inputs(cls, order_path, refs_path=""):
        h = hashlib.sha256(f"{order_path}|{refs_path}".encode())
        try:
            st = os.stat(order_path)
            h.update(f"{st.st_mtime_ns}:{st.st_size}".encode())
        except OSError:
            pass
        try:
            if refs_path:
                h.update("\n".join(sorted(os.listdir(refs_path))).encode())
        except OSError:
            pass
        return h.hexdigest()

    @classmethod
    def execute(cls, order_path, refs_path="") -> io.NodeOutput:
        loaded = load_order(order_path.strip(), refs_path.strip())
        payload = {
            "events": loaded["events"],
            "refFileCount": loaded["refFileCount"],
            "refsRoot": refs_path.strip(),
        }
        if refs_path.strip():
            _register_refs_root(refs_path.strip())
        _push("symbiotica.order_events",
              {"node_id": cls.hidden.unique_id, **payload})
        summary = json.dumps(order_overview(loaded["events"]), indent=1)
        return io.NodeOutput(payload, ui=ui.PreviewText(summary))


class SymbioticaEventSpecs(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaEventSpecs",
            display_name="Symbiotica Event Specs",
            category="symbiotica/pipeline",
            description="Pick one event from the parsed order and emit its "
                        "spec — template groups with per-asset canvas, plot, "
                        "client prompt, and reference files.",
            inputs=[
                OrderEvents.Input("events"),
                io.String.Input("feature", default="",
                                tooltip="Event to work on (the order's Feature "
                                        "column, e.g. \"QE 2\")"),
            ],
            outputs=[EventSpec.Output(display_name="event spec")],
            hidden=[io.Hidden.unique_id],
        )

    @classmethod
    def execute(cls, events, feature) -> io.NodeOutput:
        spec = event_spec(events["events"], feature.strip())
        spec = {**spec, "refsRoot": events.get("refsRoot", "")}
        _push("symbiotica.event_spec",
              {"node_id": cls.hidden.unique_id, "feature": spec["feature"],
               "templates": [{"template": g["template"], "category": g["category"],
                              "canvas": g["canvas"], "assets": len(g["assets"])}
                             for g in spec["templates"]]})
        return io.NodeOutput(spec, ui=ui.PreviewText(spec_wire_json(spec)))


class SymbioticaTemplateBuilder(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaTemplateBuilder",
            display_name="Symbiotica Template Builder",
            category="symbiotica/pipeline",
            description="Compose a template sheet from an event spec: either "
                        "prefill strips from the client's reference images, or "
                        "a grid of existing catalog art for one template group.",
            inputs=[
                EventSpec.Input("spec"),
                io.Combo.Input("mode", options=["prefill_from_specs", "catalog_grid"],
                               default="prefill_from_specs"),
                io.String.Input("group", default="", optional=True,
                                tooltip="Template group slug (required for "
                                        "catalog_grid; filters prefill when set)"),
                io.String.Input("assets_root", default="", optional=True,
                                tooltip="Game asset catalog folder "
                                        "(catalog_grid mode)"),
                io.String.Input("sheet_name", default="", optional=True,
                                tooltip="Saved sheet name (defaults to the "
                                        "group / feature slug)"),
                io.Combo.Input("preset_model", options=_MODELS,
                               default="nano-banana-pro"),
                io.Combo.Input("resolution", options=_RESOLUTIONS, default="2K"),
                io.Combo.Input("aspect_ratio", options=_ASPECTS, default="1:1"),
                io.Int.Input("max_width", default=2048, min=64, max=8192,
                             optional=True, advanced=True,
                             tooltip="Sheet width when preset_model=custom"),
                io.Int.Input("max_height", default=2048, min=64, max=8192,
                             optional=True, advanced=True),
                io.Combo.Input("algorithm", options=["shelf", "maxrects", "grid"],
                               default="shelf"),
                io.Boolean.Input("distribute_by_folder", default=True),
                io.Int.Input("padding", default=0, min=0, max=512, optional=True,
                             advanced=True),
                io.Int.Input("border", default=0, min=0, max=512, optional=True,
                             advanced=True),
                io.Int.Input("grid_cell", default=0, min=0, max=4096, optional=True,
                             advanced=True),
                io.Int.Input("columns", default=0, min=0, max=64, optional=True,
                             advanced=True),
                io.String.Input("background", default="#808080", optional=True,
                                tooltip="Hex fill; empty = transparent"),
            ],
            outputs=[
                Template.Output(display_name="template"),
                io.Image.Output(display_name="sheet"),
                io.String.Output(display_name="bundle_json"),
            ],
            hidden=[io.Hidden.unique_id],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, spec, mode, group="", assets_root="", sheet_name="",
                preset_model="nano-banana-pro", resolution="2K", aspect_ratio="1:1",
                max_width=2048, max_height=2048, algorithm="shelf",
                distribute_by_folder=True, padding=0, border=0, grid_cell=0,
                columns=0, background="#808080") -> io.NodeOutput:
        groups = spec["templates"]
        group = group.strip()
        preset = (None if preset_model == "custom"
                  else {"model": preset_model, "tier": resolution, "ar": aspect_ratio})
        settings = PackSettings(
            algorithm=algorithm, preset=preset, max_width=max_width,
            max_height=max_height, padding=padding, border=border,
            grid_cell=grid_cell, distribute_by_folder=distribute_by_folder,
            columns=columns, background=background.strip(),
        )

        if mode == "catalog_grid":
            picked = next((g for g in groups if g["template"] == group), None)
            if picked is None:
                have = ", ".join(g["template"] for g in groups)
                raise ValueError(
                    f'group "{group}" is not in the event spec (have: {have})')
            if not assets_root.strip():
                raise ValueError("catalog_grid mode needs assets_root "
                                 "(the game's existing asset folder)")
            sheet, regions, sheet_w, sheet_h = build_catalog_sheet(
                picked, assets_root.strip())
            template_name = picked["template"]
            assets = picked["assets"]
        else:
            if group:
                groups = [g for g in groups if g["template"] == group]
                if not groups:
                    raise ValueError(f'group "{group}" is not in the event spec')
            assets = [a for g in groups for a in g["assets"] if a["refFiles"]]
            if not assets:
                raise ValueError(
                    "no assets with reference files to prefill — check the "
                    "Order Read refs_path")
            from .texture_pack import effective_max
            dims = effective_max(settings)
            sheet_w, sheet_h = dims["w"], dims["h"]
            sheet, regions, overflow = build_prefill_sheet(
                assets, spec.get("refsRoot", ""), sheet_w, sheet_h, settings)
            if overflow:
                print(f"[Symbiotica] template overflow (stacked below): {overflow}")
            template_name = group or f"{slugify(spec['feature'])}-specs"

        name = sheet_name.strip() or template_name
        rel = save_sheet(sheet, regions, name, folder_paths.get_output_directory(),
                         meta={"template": template_name})

        refs_root = (spec.get("refsRoot", "") or "").rstrip("/")
        ref_paths = (
            {a["assetName"]: [f"{refs_root}/{f}" for f in a["refFiles"]]
             for a in assets}
            if refs_root else {}
        )
        bundle = {
            "kind": "template",
            "template": template_name,
            "sheetFile": rel,
            "templateSize": {"w": sheet.width, "h": sheet.height},
            "regions": regions,
            "refPaths": ref_paths,
        }
        tensor = _pil_to_tensor(sheet)
        return io.NodeOutput(bundle, tensor, json.dumps(bundle, indent=1),
                             ui=ui.PreviewImage(tensor, cls=cls))


class SymbioticaTemplatePrompt(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaTemplatePrompt",
            display_name="Symbiotica Template Prompt",
            category="symbiotica/pipeline",
            description="Turn a template bundle into an edit prompt for the "
                        "image nodes: one numbered instruction per region, "
                        "using each asset's client prompt.",
            inputs=[
                Template.Input("template"),
                io.String.Input("scene", default="", multiline=True, optional=True,
                                tooltip="Overall scene/style instruction "
                                        "prepended to the region list"),
            ],
            outputs=[io.String.Output(display_name="prompt")],
        )

    @classmethod
    def execute(cls, template, scene="") -> io.NodeOutput:
        lines = []
        if scene.strip():
            lines.append(scene.strip())
        lines.append(
            "The image is a sprite template sheet. Replace the content of each "
            "listed region with a new game asset, keeping position and size; "
            "keep everything outside the regions unchanged.")
        for region in sorted(template["regions"], key=lambda r: r.get("zIndex", 0)):
            name = region.get("name") or region["id"]
            desc = (region.get("desc") or "").strip()
            asset_type = region.get("assetType") or ""
            suffix = f" ({asset_type})" if asset_type else ""
            lines.append(f"{region.get('zIndex', 0) + 1}. \"{name}\"{suffix}: "
                         f"{desc or 'match the sheet style'}")
        return io.NodeOutput("\n".join(lines))


PIPELINE_NODE_CLASSES = [
    SymbioticaOrderRead,
    SymbioticaEventSpecs,
    SymbioticaTemplateBuilder,
    SymbioticaTemplatePrompt,
]
```

- [ ] **Step 4: Implement the shim `py/symbiotica_pipeline.py`**

```python
# ABOUTME: Registration shim — exposes the V3 pipeline nodes through the repo's
# ABOUTME: V1 auto-discovery. Needed because ComfyUI's loader (nodes.py) ignores
# comfy_entrypoint when a package already exports NODE_CLASS_MAPPINGS (elif),
# and the V3 loader path does exactly this mapping anyway (nodes.py:2306).
from .pipeline.nodes import PIPELINE_NODE_CLASSES

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

for _cls in PIPELINE_NODE_CLASSES:
    _schema = _cls.GET_SCHEMA()
    NODE_CLASS_MAPPINGS[_schema.node_id] = _cls
    if _schema.display_name:
        NODE_DISPLAY_NAME_MAPPINGS[_schema.node_id] = _schema.display_name
```

- [ ] **Step 5: Run the test suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: all PASS (nodes.py import fails outside ComfyUI → covered by `test_nodes_module_requires_comfy`)

- [ ] **Step 6: Smoke-load inside the real ComfyUI environment**

Run (ComfyUI's venv + source on sys.path):
```bash
cd ~/ComfyUI-Installs/ComfyUI/ComfyUI && ~/Documents/ComfyUI/.venv/bin/python -c "
import sys; sys.path.insert(0, '.')
sys.path.insert(0, '/Users/razvanmatei/.claude-sessions/comfy-nodes/comfyui-nodes/py')
from pipeline.nodes import PIPELINE_NODE_CLASSES
for cls in PIPELINE_NODE_CLASSES:
    s = cls.GET_SCHEMA()
    print(s.node_id, '->', cls.INPUT_TYPES() is not None, cls.RETURN_TYPES)
"
```
Expected: four lines, one per node id, no tracebacks. If `from server import ...` errors appear, the guarded `_push`/`_register_refs_root` try/excepts are wrong — fix before continuing.

- [ ] **Step 7: Commit**

```bash
git add py/pipeline/nodes.py py/symbiotica_pipeline.py tests/test_shim.py
git commit -m "feat(pipeline): V3 order pipeline nodes with V1 shim registration"
```

---

### Task 8: Thumbnail route with root allowlist

**Files:**
- Create: `py/pipeline/routes.py`
- Modify: `py/symbiotica_pipeline.py` (import routes)
- Create: `tests/test_routes_allowlist.py`

**Interfaces:**
- Produces: `GET /symbiotica/local-image?path=<abs path>` — streams a local image IF its real path is under a registered root; `register_root(path)`, `is_allowed(path) -> bool` (pure, testable). Roots are registered by `SymbioticaOrderRead.execute` (refs_path) — Task 7 already calls `_register_refs_root`.
- Security: unlike hub's dev-only route, this must NOT serve arbitrary paths — only files under roots the user explicitly typed into an Order Read node this session, image extensions only.
- Reference: hub `routes/api/flows/local-file/+server.ts`, `lib/flows/local-assets.ts`.

- [ ] **Step 1: Write failing allowlist tests**

`tests/test_routes_allowlist.py`:
```python
# ABOUTME: Tests for the local-image route's path allowlist — only image files
# ABOUTME: under explicitly registered roots may be served.
import importlib
import os
import sys
import types


def _load_routes(monkeypatch):
    """Import routes.py with a stubbed `server` module (no ComfyUI needed)."""
    fake_server = types.ModuleType("server")

    class _Routes:
        def get(self, _path):
            def deco(fn):
                return fn
            return deco

    fake_server.PromptServer = types.SimpleNamespace(
        instance=types.SimpleNamespace(routes=_Routes()))
    monkeypatch.setitem(sys.modules, "server", fake_server)
    monkeypatch.setitem(sys.modules, "aiohttp", types.ModuleType("aiohttp"))
    web = types.ModuleType("aiohttp.web")
    web.json_response = lambda *a, **k: None
    web.FileResponse = lambda *a, **k: None
    sys.modules["aiohttp"].web = web
    monkeypatch.setitem(sys.modules, "aiohttp.web", web)
    import pipeline.routes as routes
    importlib.reload(routes)
    return routes


def test_allowlist(tmp_path, monkeypatch):
    routes = _load_routes(monkeypatch)
    root = tmp_path / "refs"
    root.mkdir()
    (root / "a.png").write_bytes(b"x")
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"x")

    assert not routes.is_allowed(str(root / "a.png"))  # nothing registered yet
    routes.register_root(str(root))
    assert routes.is_allowed(str(root / "a.png"))
    assert not routes.is_allowed(str(outside))
    # Traversal out of the root is rejected on the resolved path.
    assert not routes.is_allowed(str(root / ".." / "secret.png"))
    # Non-image extensions rejected even under the root.
    (root / "b.txt").write_bytes(b"x")
    assert not routes.is_allowed(str(root / "b.txt"))
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_routes_allowlist.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.routes'`

- [ ] **Step 3: Implement `py/pipeline/routes.py`**

```python
# ABOUTME: aiohttp routes for the order pipeline — serves local ref-image
# ABOUTME: thumbnails, restricted to roots registered by executed nodes.
from __future__ import annotations

import os
import threading

from aiohttp import web
from server import PromptServer

ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

_roots: set[str] = set()
_lock = threading.Lock()


def register_root(path: str) -> None:
    """Allow serving images under this folder (called when an Order Read node
    executes with it — i.e. the user explicitly typed it into the graph)."""
    real = os.path.realpath(path)
    if os.path.isdir(real):
        with _lock:
            _roots.add(real)


def is_allowed(path: str) -> bool:
    if os.path.splitext(path)[1].lower() not in ALLOWED_EXTS:
        return False
    real = os.path.realpath(path)
    if not os.path.isfile(real):
        return False
    with _lock:
        roots = list(_roots)
    return any(real == r or real.startswith(r + os.sep) for r in roots)


@PromptServer.instance.routes.get("/symbiotica/local-image")
async def local_image(request):
    path = request.query.get("path", "")
    if not is_allowed(path):
        return web.json_response({"error": "not an allowed image path"}, status=403)
    return web.FileResponse(os.path.realpath(path),
                            headers={"Cache-Control": "private, max-age=60"})
```

- [ ] **Step 4: Wire into the shim** — append to `py/symbiotica_pipeline.py`:

```python
try:
    from .pipeline import routes as _routes  # noqa: F401  (registers aiohttp route)
except Exception:
    pass  # outside a running ComfyUI server (e.g. tests) the route is unavailable
```

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/pytest tests/ -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add py/pipeline/routes.py py/symbiotica_pipeline.py tests/test_routes_allowlist.py
git commit -m "feat(pipeline): local-image thumbnail route with root allowlist"
```

---

### Task 9: JS extension — dynamic combos + events browser

**Files:**
- Create: `web/js/order_pipeline.js`

**Interfaces:**
- Consumes: `symbiotica.order_events` push `{node_id, events, refFileCount, refsRoot}` (Task 7); `/symbiotica/local-image?path=` (Task 8); mirrors `slugify` + `template_groups` from `py/pipeline/order_sheet.py` — keep in sync.
- Produces: on `SymbioticaEventSpecs`, the `feature` text widget becomes a combo listing parsed features; on `SymbioticaTemplateBuilder`, `group` becomes a combo listing the picked feature's template groups (computed client-side); `SymbioticaOrderRead` gets an events-browser DOM widget (feature / event name / asset + ref counts, expandable groups, ref thumbnails ≤5 per asset like hub's `MAX_REF_THUMBS`).
- No build step: vanilla ES module, loaded via existing `WEB_DIRECTORY = "./web"`.
- Reference: repo `web/js/seed.js` + `web/js/video_concat.js` (house style), hub `board/order-read-node.svelte` + `board/task-node.svelte` (behavior).

- [ ] **Step 1: Implement `web/js/order_pipeline.js`**

```javascript
// ABOUTME: Frontend for the Symbiotica order pipeline nodes — dynamic event and
// ABOUTME: group combos fed by server pushes, plus an events browser on Order Read.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// node.id -> {events, refFileCount, refsRoot} (last parse per Order Read node)
const orderCache = new Map();

// --- mirrors of py/pipeline/order_sheet.py (keep in sync) -------------------
function slugify(s) {
    return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function templateGroups(event) {
    const groups = new Map();
    for (const a of event.assets) {
        if (!a.assetName) continue;
        const key = `${a.category}|${a.canvas}`;
        if (!groups.has(key)) {
            groups.set(key, {
                template: slugify(`${event.feature}-${a.category}-${a.canvas}`),
                category: a.category,
                canvas: a.canvas,
                assets: [],
            });
        }
        groups.get(key).assets.push(a);
    }
    return [...groups.values()];
}

// --- graph helpers -----------------------------------------------------------
function upstreamNode(node, inputName) {
    const input = node.inputs?.find((i) => i.name === inputName);
    if (!input || input.link == null) return null;
    const link = app.graph.links[input.link];
    return link ? app.graph.getNodeById(link.origin_id) : null;
}

function downstreamNodes(node, type) {
    const out = [];
    for (const output of node.outputs ?? []) {
        for (const linkId of output.links ?? []) {
            const link = app.graph.links[linkId];
            const target = link && app.graph.getNodeById(link.target_id);
            if (target && target.comfyClass === type) out.push(target);
        }
    }
    return out;
}

function orderDataFor(node) {
    // Walk up: Specs -> Order Read; Template -> Specs -> Order Read.
    let cur = node;
    for (let hop = 0; hop < 3 && cur; hop++) {
        if (cur.comfyClass === "SymbioticaOrderRead") return orderCache.get(cur.id);
        cur = upstreamNode(cur, cur.comfyClass === "SymbioticaTemplateBuilder" ? "spec" : "events");
    }
    return undefined;
}

// --- widget upgrades ---------------------------------------------------------
function comboify(node, widgetName, valuesFn) {
    const w = node.widgets?.find((x) => x.name === widgetName);
    if (!w) return;
    w.type = "combo";
    w.options = w.options ?? {};
    w.options.values = valuesFn; // LiteGraph accepts a function — always fresh
}

function refreshCombos(node) {
    for (const specs of downstreamNodes(node, "SymbioticaEventSpecs")) {
        specs.setDirtyCanvas(true, true);
        for (const tpl of downstreamNodes(specs, "SymbioticaTemplateBuilder")) {
            tpl.setDirtyCanvas(true, true);
        }
    }
}

// --- events browser ----------------------------------------------------------
function thumbUrl(refsRoot, file) {
    return api.apiURL(
        `/symbiotica/local-image?path=${encodeURIComponent(`${refsRoot}/${file}`)}`
    ).replace("/api/", "/"); // route registered at server root, not under /api
}

function renderBrowser(container, data) {
    container.innerHTML = "";
    if (!data) {
        container.textContent = "Queue once to parse the order.";
        container.style.opacity = "0.6";
        return;
    }
    container.style.opacity = "1";
    for (const ev of data.events) {
        const named = ev.assets.filter((a) => a.assetName);
        const refCount = ev.assets.filter((a) => a.refFiles.length > 0).length;
        const unspecced = ev.assets.every((a) => !a.assetName);

        const card = document.createElement("div");
        card.style.cssText =
            "border:1px solid #444;border-radius:6px;margin:2px 0;padding:4px 6px;" +
            "font-size:11px;cursor:pointer;background:#2a2a2a;";
        const head = document.createElement("div");
        head.style.cssText = "display:flex;justify-content:space-between;gap:6px;";
        head.innerHTML =
            `<span><b>${ev.feature}</b> ${ev.eventName ?? ""}</span>` +
            `<span style="opacity:.7">${unspecced
                ? `${ev.assets.length} slots — unspecced`
                : `${ev.assets.length} assets · ${refCount} refs`}</span>`;
        card.appendChild(head);

        const body = document.createElement("div");
        body.style.display = "none";
        for (const g of templateGroups(ev)) {
            const gh = document.createElement("div");
            gh.style.cssText = "margin-top:4px;opacity:.7;text-transform:uppercase;font-size:10px;";
            gh.textContent = `${g.template} · ${g.assets.length}`;
            body.appendChild(gh);
            for (const a of g.assets) {
                const row = document.createElement("div");
                row.style.cssText = "display:flex;align-items:center;gap:4px;margin:2px 0;";
                const label = document.createElement("span");
                label.style.cssText = "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
                label.textContent = `${a.assetName} · ${a.canvas}`;
                row.appendChild(label);
                if (!a.refFiles.length) {
                    const chip = document.createElement("span");
                    chip.style.opacity = "0.5";
                    chip.textContent = "no refs";
                    row.appendChild(chip);
                } else if (data.refsRoot) {
                    for (const f of a.refFiles.slice(0, 5)) {
                        const img = document.createElement("img");
                        img.src = thumbUrl(data.refsRoot, f);
                        img.style.cssText =
                            "width:22px;height:22px;object-fit:contain;background:#111;border-radius:3px;";
                        row.appendChild(img);
                    }
                    if (a.refFiles.length > 5) {
                        const more = document.createElement("span");
                        more.textContent = `+${a.refFiles.length - 5}`;
                        row.appendChild(more);
                    }
                }
                body.appendChild(row);
            }
        }
        card.appendChild(body);
        head.addEventListener("click", () => {
            body.style.display = body.style.display === "none" ? "block" : "none";
        });
        container.appendChild(card);
    }
}

// --- extension ---------------------------------------------------------------
app.registerExtension({
    name: "symbiotica.order_pipeline",

    setup() {
        api.addEventListener("symbiotica.order_events", ({ detail }) => {
            const nodeId = Number(detail.node_id);
            orderCache.set(nodeId, detail);
            const node = app.graph.getNodeById(nodeId);
            if (!node) return;
            if (node._symbioticaBrowser) renderBrowser(node._symbioticaBrowser, detail);
            refreshCombos(node);
        });
    },

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "SymbioticaOrderRead") {
            const orig = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                orig?.apply(this, arguments);
                const container = document.createElement("div");
                container.style.cssText =
                    "max-height:280px;overflow-y:auto;padding:2px;";
                this._symbioticaBrowser = container;
                renderBrowser(container, undefined);
                this.addDOMWidget("events_browser", "custom", container,
                                  { serialize: false, hideOnZoom: true });
                this.size[0] = Math.max(this.size[0], 320);
            };
        }

        if (nodeData.name === "SymbioticaEventSpecs") {
            const orig = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                orig?.apply(this, arguments);
                comboify(this, "feature", () => {
                    const data = orderDataFor(this);
                    return data ? data.events.map((e) => e.feature) : [];
                });
            };
        }

        if (nodeData.name === "SymbioticaTemplateBuilder") {
            const orig = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                orig?.apply(this, arguments);
                comboify(this, "group", () => {
                    const data = orderDataFor(this);
                    if (!data) return [];
                    const specs = upstreamNode(this, "spec");
                    const feature = specs?.widgets?.find((w) => w.name === "feature")?.value;
                    const ev = data.events.find((e) => e.feature === feature);
                    return ev ? templateGroups(ev).map((g) => g.template) : [];
                });
            };
        }
    },
});
```

- [ ] **Step 2: Static sanity check (no test runner for browser JS here)**

Run: `node --check web/js/order_pipeline.js`
Expected: exits 0 (syntax valid). Behavior verification happens in Task 10's live E2E.

- [ ] **Step 3: Commit**

```bash
git add web/js/order_pipeline.js
git commit -m "feat(pipeline): dynamic combos and events browser JS extension"
```

---

### Task 10: Deploy locally, live E2E, README

**Files:**
- Modify: `README.md` (new "Order pipeline" section)
- No repo code changes expected; fixes discovered live go in as separate commits.

**Interfaces:**
- Consumes: everything. The live check uses the real bakery order from the hub flow:
  - order xlsx: `/Users/razvanmatei/Library/CloudStorage/GoogleDrive-*/.../Clients/Imperia/Projects/Bakery story/Orders/Bakery October Art.xlsx` — read the EXACT path from `~/.claude-sessions/symbiotica-hub/content/flows/bakery-event-all.json` step s8 `values.orderPath` / `values.refsPath` at execution time.

- [ ] **Step 1: Inspect the installed copy of this pack**

```bash
ls -la ~/Documents/ComfyUI/custom_nodes/symbiotica
git -C ~/Documents/ComfyUI/custom_nodes/symbiotica remote -v 2>/dev/null || echo "not a git checkout"
```
If it is a git checkout of `symbiotica-ai/comfyui-nodes`: note its state. Either way, replace it with a symlink to the working clone (back up first):

```bash
mv ~/Documents/ComfyUI/custom_nodes/symbiotica ~/Documents/ComfyUI/custom_nodes/symbiotica.bak-20260710
ln -s /Users/razvanmatei/.claude-sessions/comfy-nodes/comfyui-nodes ~/Documents/ComfyUI/custom_nodes/symbiotica
```

- [ ] **Step 2: Restart ComfyUI**

The server is the desktop app on port 8000 — ask the user to restart it (or use the app's "Restart" if reachable via API: `curl -s -X POST http://127.0.0.1:8000/api/manager/reboot` works when ComfyUI-Manager is installed, which it is — try that first).

- [ ] **Step 3: Verify nodes registered**

```bash
curl -s http://127.0.0.1:8000/object_info | python3 -c "
import json,sys
info = json.load(sys.stdin)
for n in ['SymbioticaOrderRead','SymbioticaEventSpecs','SymbioticaTemplateBuilder','SymbioticaTemplatePrompt']:
    print(n, 'OK' if n in info else 'MISSING')
"
```
Expected: four `OK`. If MISSING, check the server log: `tail -50 ~/Documents/ComfyUI/user/comfyui_8000.log` for `[Symbiotica] Failed to load symbiotica_pipeline`.

- [ ] **Step 4: Queue a live pipeline run (API-format workflow)**

Read real paths from the hub flow json first, then queue (comfyui-api skill patterns apply):

```bash
python3 - <<'EOF'
import json, urllib.request, pathlib
flow = json.loads(pathlib.Path(
    "/Users/razvanmatei/.claude-sessions/symbiotica-hub/content/flows/bakery-event-all.json"
).read_text())
s8 = next(s for s in flow["steps"] if s["id"] == "s8")
prompt = {
    "1": {"class_type": "SymbioticaOrderRead",
          "inputs": {"order_path": s8["values"]["orderPath"],
                      "refs_path": s8["values"]["refsPath"]}},
    "2": {"class_type": "SymbioticaEventSpecs",
          "inputs": {"events": ["1", 0], "feature": "Mini 1"}},
    "3": {"class_type": "SymbioticaTemplateBuilder",
          "inputs": {"spec": ["2", 0], "mode": "prefill_from_specs", "group": "",
                      "assets_root": "", "sheet_name": "e2e-mini1",
                      "preset_model": "nano-banana-pro", "resolution": "2K",
                      "aspect_ratio": "1:1", "max_width": 2048, "max_height": 2048,
                      "algorithm": "shelf", "distribute_by_folder": True,
                      "padding": 0, "border": 0, "grid_cell": 0, "columns": 0,
                      "background": "#808080"}},
    "4": {"class_type": "SymbioticaTemplatePrompt",
          "inputs": {"template": ["3", 0], "scene": ""}},
}
req = urllib.request.Request("http://127.0.0.1:8000/prompt",
                             json.dumps({"prompt": prompt}).encode(),
                             {"Content-Type": "application/json"})
print(urllib.request.urlopen(req).read().decode())
EOF
```
Expected: `{"prompt_id": "...", "number": ..., "node_errors": {}}`. Then poll history until done and verify:

```bash
ls -la ~/Documents/ComfyUI/output/templates/e2e-mini1.png \
       ~/Documents/ComfyUI/output/templates/e2e-mini1.json
```
Expected: both exist; open the PNG and confirm ref strips are visible on gray background. Check the history output of node 4 contains a numbered region prompt.

- [ ] **Step 5: Verify the JS extension in the browser**

Using claude-in-chrome (load tools first per harness instructions): open `http://127.0.0.1:8000`, add the three nodes, wire them, confirm (a) events browser fills after queueing, (b) `feature` combo lists the 8 features, (c) `group` combo lists the picked feature's groups, (d) ref thumbnails render (allowlist route). Screenshot for the user.

- [ ] **Step 6: README section**

Append to `README.md` after the existing node list:

```markdown
## Order pipeline (Symbiotica Hub port)

Recreates the hub's Order Read → Specs → Template flow as ComfyUI nodes:

- **Symbiotica Order Read** — parses a monthly order `.xlsx` (Feature / Asset
  Name / Canvas / Prompt columns) plus a folder of reference images
  (`AssetName.png`, `AssetName_2.png`, ...) into events.
- **Symbiotica Event Specs** — picks one event (feature) and emits its spec:
  template groups by category + canvas with per-asset prompts and refs.
- **Symbiotica Template Builder** — composes a template sheet: either
  `prefill_from_specs` (reference strips packed onto the sheet — single-ref
  assets get a flipped pair, multi-ref assets one cell per stage) or
  `catalog_grid` (existing game art matched by category). Sheets save to
  `output/templates/<name>.png` with a JSON region sidecar, and the bundle
  output feeds the Template Prompt node.
- **Symbiotica Template Prompt** — turns the bundle's regions into an edit
  prompt for the Nano Banana edit nodes.

The web extension adds an events browser on Order Read and populates the
feature/group dropdowns after the first queue.
```

- [ ] **Step 7: Run full test suite one last time, commit**

```bash
.venv/bin/pytest tests/ -v
git add README.md
git commit -m "docs: order pipeline node documentation"
```

- [ ] **Step 8: Verify with the superpowers:verification-before-completion skill, then offer the user the finishing options (superpowers:finishing-a-development-branch)** — do NOT push without asking.

---

## Self-Review Notes

- **Spec coverage:** Order Read parse+refs ✅ (T1-3), Specs pick+groups ✅ (T3, T7), Template build+pack+regions+bundle ✅ (T4-7), previews ✅ (T7), dynamic pickers + events browser + thumbnails ✅ (T8-9), hub wire parity ✅ (camelCase everywhere, `TemplateBundle` shape in T7), E2E on the real bakery order ✅ (T10). Template *editor* deliberately excluded (Phase 3 plan).
- **Type consistency check:** `PackSettings` fields used in T5/T6/T7 match T4's dataclass; region dict keys in T5/T6 match; `PIPELINE_NODE_CLASSES` name consistent T7 shim; `register_root`/`is_allowed` consistent T7/T8; JS mirrors named identically (`slugify`, `templateGroups`).
- **Known judgment calls:** (1) numeric edge `numeric_text` uses `repr(float)` — differs from JS `String(n)` only for exotic floats, not order data. (2) `thumbUrl` strips `/api` because custom routes register at server root — verify live in T10 step 5 and fix in the JS if the instance serves under `/api` only. (3) Prefill draws refs contain-fit; hub editor draws at canvas-spec cell size — same rects, minor scaling semantics, acceptable for the img2img base.
