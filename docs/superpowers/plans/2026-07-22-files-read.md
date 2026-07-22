# SymbioticaFilesRead Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Files Read node that turns loose client reference folders into the standard Order wire, so the untouched Auto Packer builds LoRA dataset sheets from them.

**Architecture:** New pure builder (`files_read.py`) synthesizes order assets from a browser-managed selection JSON; a shared `resolve_ref` helper lets nested rel paths resolve in both the Python compositor and a new thumbnail route (JS parity by construction); a new JS overlay (`files_read.js`) reuses the template editor's tree mechanics for selection.

**Tech Stack:** ComfyUI V3 node API (`comfy_api.latest` io), PIL, aiohttp routes, vanilla-JS ComfyUI extension.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-22-files-read-design.md`.
- Auto Packer / Model Preset / Settings nodes untouched.
- Order wire payload shape: `{feature, eventName, assets, refsRoot, assetsRoot, guide}` (see `SymbioticaOrderSpecs.execute`, nodes.py:246-253).
- Asset dict fields consumed downstream: `assetName, category, canvas, rotation, refFiles, prompt`.
- pytest does NOT import nodes.py — node schema/execute verified live via `/api/object_info/SymbioticaFilesRead` only.
- Test runner: `/Users/razvanmatei/.claude-sessions/comfy-nodes/comfyui-nodes/.venv/bin/python -m pytest tests/ -q` run from the worktree root (worktree has no .venv).
- Commit style: conventional (`feat:`, `fix:`, `test:`), plain prose bodies.

---

### Task 1: files_read builder

**Files:**
- Create: `py/pipeline/files_read.py`
- Test: `tests/test_files_read.py`

**Interfaces:**
- Produces: `build_files_order(refs_root: str, selection: str | dict, name: str = "") -> dict` returning the Order payload.

- [ ] **Step 1: Write the failing tests** (`tests/test_files_read.py`)

```python
# ABOUTME: Tests for files_read — selection JSON -> Order payload synthesis.
import json

import pytest
from PIL import Image

from py.pipeline.files_read import build_files_order


def _png(path, w=64, h=64):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (w, h), (255, 0, 0, 255)).save(path)


@pytest.fixture()
def refs(tmp_path):
    _png(tmp_path / "Stoves" / "stove_red.png", 128, 128)
    _png(tmp_path / "Stoves" / "stove_blue.png", 128, 128)
    _png(tmp_path / "Food" / "Cakes" / "cake_a.png", 256, 192)
    return tmp_path


def _sel(groups):
    return json.dumps({"groups": groups})


def test_builds_order_payload(refs):
    order = build_files_order(str(refs), _sel([
        {"name": "stoves", "category": "Decoration",
         "files": ["Stoves/stove_red.png", "Stoves/stove_blue.png"]},
    ]), name="clientpack")
    assert order["feature"] == "clientpack"
    assert order["refsRoot"] == str(refs)
    assert order["assetsRoot"] == ""
    a = order["assets"][0]
    assert a["assetName"] == "stoves"
    assert a["category"] == "Decoration"
    assert a["canvas"] == "128x128"
    assert a["rotation"] == "-"
    assert a["refFiles"] == ["Stoves/stove_red.png", "Stoves/stove_blue.png"]


def test_canvas_is_max_dims_across_files(refs):
    _png(refs / "Food" / "Cakes" / "cake_b.png", 192, 256)
    order = build_files_order(str(refs), _sel([
        {"name": "cakes", "category": "Food",
         "files": ["Food/Cakes/cake_a.png", "Food/Cakes/cake_b.png"]},
    ]))
    assert order["assets"][0]["canvas"] == "256x256"


def test_variants_flag_sets_rotation_2(refs):
    order = build_files_order(str(refs), _sel([
        {"name": "stoves", "category": "Deco", "variants": True,
         "files": ["Stoves/stove_red.png", "Stoves/stove_blue.png"]},
    ]))
    assert order["assets"][0]["rotation"] == "2"


def test_desc_becomes_prompt_and_default_name(refs):
    order = build_files_order(str(refs), _sel([
        {"name": "stoves", "category": "Deco", "desc": "a cozy stove",
         "files": ["Stoves/stove_red.png"]},
    ]))
    assert order["assets"][0]["prompt"] == "a cozy stove"
    assert order["feature"] == refs.name  # folder name fallback


def test_missing_files_dropped_empty_group_raises(refs):
    order = build_files_order(str(refs), _sel([
        {"name": "stoves", "category": "Deco",
         "files": ["Stoves/stove_red.png", "Stoves/nope.png"]},
    ]))
    assert order["assets"][0]["refFiles"] == ["Stoves/stove_red.png"]
    with pytest.raises(ValueError, match="ghosts"):
        build_files_order(str(refs), _sel([
            {"name": "ghosts", "category": "Deco", "files": ["gone.png"]},
        ]))


def test_no_groups_raises_actionable(refs):
    with pytest.raises(ValueError, match="files browser"):
        build_files_order(str(refs), "{}")


def test_selection_accepts_dict_and_bad_json_raises(refs):
    order = build_files_order(str(refs), {"groups": [
        {"name": "s", "category": "c", "files": ["Stoves/stove_red.png"]}]})
    assert order["assets"][0]["assetName"] == "s"
    with pytest.raises(ValueError, match="selection"):
        build_files_order(str(refs), "{not json")


def test_duplicate_group_names_deduped(refs):
    order = build_files_order(str(refs), _sel([
        {"name": "s", "category": "c", "files": ["Stoves/stove_red.png"]},
        {"name": "s", "category": "c", "files": ["Stoves/stove_blue.png"]},
    ]))
    names = [a["assetName"] for a in order["assets"]]
    assert names == ["s", "s-2"]
```

- [ ] **Step 2: Run tests, verify they fail**

Run: `/Users/razvanmatei/.claude-sessions/comfy-nodes/comfyui-nodes/.venv/bin/python -m pytest tests/test_files_read.py -q`
Expected: FAIL — `ModuleNotFoundError: py.pipeline.files_read`

- [ ] **Step 3: Implement** (`py/pipeline/files_read.py`)

```python
# ABOUTME: Files Read builder — turn a browser selection over a loose client
# ABOUTME: reference folder into the standard Order payload the AutoPacker eats.
from __future__ import annotations

import json
import os

from PIL import Image


def _px_dims(path: str) -> tuple[int, int] | None:
    """Image pixel size via a header read; None when unreadable."""
    try:
        with Image.open(path) as im:
            return im.size
    except OSError:
        return None


def build_files_order(refs_root: str, selection, name: str = "") -> dict:
    """Selection JSON -> Order payload. One group = one asset (one sheet row);
    the group's files are its refFiles verbatim (rel paths, may nest). canvas =
    the group's max pixel dims, so (category, canvas) sheet grouping and the
    scale cutoff work exactly as they do for xlsx orders. Missing files are
    dropped; a group with nothing left raises (its name in the message)."""
    refs_root = (refs_root or "").strip()
    if not os.path.isdir(refs_root):
        raise ValueError(f"reference folder not found: {refs_root!r} — set "
                         "refs_path to the client folder of reference images")
    if isinstance(selection, str):
        try:
            selection = json.loads(selection or "{}")
        except ValueError as e:
            raise ValueError(f"selection is not valid JSON: {e}") from e
    groups = (selection or {}).get("groups") or []
    if not groups:
        raise ValueError("no groups selected — open the files browser and "
                         "tick folders/files to build groups")
    assets, seen = [], {}
    for g in groups:
        gname = (g.get("name") or "").strip() or "group"
        # Duplicate names would collide in prefill's by-name maps: suffix them.
        seen[gname] = seen.get(gname, 0) + 1
        if seen[gname] > 1:
            gname = f"{gname}-{seen[gname]}"
        files, w, h = [], 0, 0
        for rel in g.get("files") or []:
            p = os.path.join(refs_root, *str(rel).split("/"))
            dims = _px_dims(p) if os.path.isfile(p) else None
            if dims is None:
                continue
            files.append(str(rel))
            w, h = max(w, dims[0]), max(h, dims[1])
        if not files:
            raise ValueError(f"group {gname!r} has no readable images under "
                             f"{refs_root!r} — re-open the files browser")
        assets.append({
            "assetName": gname,
            "category": (g.get("category") or "").strip() or gname,
            "canvas": f"{w}x{h}",
            "rotation": "2" if g.get("variants") else "-",
            "refFiles": files,
            "prompt": (g.get("desc") or "").strip(),
        })
    feature = (name or "").strip() or os.path.basename(refs_root.rstrip(os.sep))
    return {"feature": feature, "eventName": feature, "assets": assets,
            "refsRoot": refs_root, "assetsRoot": "", "guide": None}
```

- [ ] **Step 4: Run tests, verify pass**

Run: `/Users/razvanmatei/.claude-sessions/comfy-nodes/comfyui-nodes/.venv/bin/python -m pytest tests/test_files_read.py -q`
Expected: 8 passed

- [ ] **Step 5: Commit** — `feat: files_read builder — selection JSON to Order payload`

---

### Task 2: nested-path resolution in prefill + compose

**Files:**
- Modify: `py/pipeline/prefill.py:132-136` (paths synthesis)
- Modify: `py/pipeline/compose.py:192-222` (`_draw_task_refs`, new `resolve_ref`)
- Test: `tests/test_files_read.py` (append), `tests/test_prefill.py` (append)

**Interfaces:**
- Consumes: Task 1 asset shape (`refFiles` rel paths containing `/`).
- Produces: `compose.resolve_ref(refs_root: str, path: str) -> str` (absolute path; exact rel when it exists, else flat basename — today's behavior). Used by Task 3's route.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_prefill.py`:

```python
def test_rel_path_reffiles_pass_through_verbatim():
    # A refFile containing "/" is already a rel path — no category/assetName
    # synthesis (the Files Read flow); basenames keep the synthetic prefix.
    assets = [{"assetName": "stoves", "category": "Deco", "canvas": "128x128",
               "rotation": "-", "refFiles": ["Stoves/a.png", "Stoves/b.png"]}]
    result = prefill_regions(assets, 1024, 1024)
    paths = result["regions"][0]["taskRefs"]["paths"]
    assert paths == ["Stoves/a.png", "Stoves/b.png"]
```

Append to `tests/test_files_read.py`:

```python
def test_resolve_ref_exact_rel_then_basename(tmp_path):
    from py.pipeline.compose import resolve_ref
    _png(tmp_path / "Stoves" / "a.png")
    _png(tmp_path / "flat.png")
    nested = resolve_ref(str(tmp_path), "Stoves/a.png")
    assert nested.endswith(os.path.join("Stoves", "a.png"))
    # Synthetic order path ("Category/Asset/file.png") does not exist as a
    # rel — falls back to the flat basename lookup (today's behavior).
    flat = resolve_ref(str(tmp_path), "Deco/Stove/flat.png")
    assert flat == os.path.join(str(tmp_path), "flat.png")


def test_draw_task_refs_draws_nested_refs(tmp_path):
    from py.pipeline.compose import build_prefill_sheet
    from py.pipeline.texture_pack import PackSettings
    _png(tmp_path / "Stoves" / "a.png", 64, 64)
    assets = [{"assetName": "s", "category": "c", "canvas": "64x64",
               "rotation": "-", "refFiles": ["Stoves/a.png"], "prompt": ""}]
    settings = PackSettings(algorithm="shelf", columns=1, background="",
                            max_width=256, max_height=256)
    sheet, regions, _ = build_prefill_sheet(assets, str(tmp_path), 256, 256,
                                            settings)
    assert sheet.getbbox() is not None  # the nested ref actually drew
```

(`tests/test_files_read.py` gains `import os` at the top.)

- [ ] **Step 2: Run, verify the new tests fail**

Run: `/Users/razvanmatei/.claude-sessions/comfy-nodes/comfyui-nodes/.venv/bin/python -m pytest tests/test_prefill.py tests/test_files_read.py -q`
Expected: the passthrough test fails (paths get `Deco/stoves/` prefix), resolve_ref fails with ImportError, draw test fails on blank sheet.

- [ ] **Step 3: Implement**

`py/pipeline/prefill.py` — in `prefill_regions`, replace the paths synthesis:

```python
        paths = picked if picked else [
            # A refFile containing "/" is already a rel path under refs_root
            # (Files Read); bare basenames get the synthetic order prefix.
            f if "/" in f else
            f"{asset['category']}/{asset['assetName']}/{f}"
            for f in asset["refFiles"]
        ]
```

`py/pipeline/compose.py` — add after `_load_rgba`:

```python
def resolve_ref(refs_root: str, path: str) -> str:
    """A member path -> the file to draw: the exact rel path under refs_root
    when it exists (nested Files Read refs), else the flat basename lookup
    (xlsx orders keep their refs flat; synthetic 'Category/Asset/file' paths
    never exist as rels and fall through)."""
    exact = os.path.join(refs_root, *path.split("/"))
    if os.path.isfile(exact):
        return exact
    return os.path.join(refs_root, path.split("/")[-1])
```

In `_draw_task_refs`, keep the flip logic byte-identical, but track the chosen
*path* instead of its basename and load through the resolver — replace the
body's filename handling:

```python
        for i, member in enumerate(members):
            flip = None  # member's own flipX
            if paths:
                if len(paths) == 1:
                    ref_path = paths[0]
                    flip = len(members) == 2 and i == 1
                else:
                    # Multiple checked refs are explicit per-cell art (often a
                    # pre-mirrored pair) — never apply the baked pair flip.
                    ref_path = paths[min(i, len(paths) - 1)]
                    flip = False
            else:
                sprite = member.get("spriteId")
                if not sprite:
                    continue
                ref_path = sprite
            img = _load_rgba(resolve_ref(refs_root, ref_path))
            if img is None:
                continue  # missing ref: cell stays background for the img2img pass
            _composite_member(sheet, img, member, sheet_w, sheet_h, flip)
```

- [ ] **Step 4: Run the whole suite** (regression gate — order flow must not move)

Run: `/Users/razvanmatei/.claude-sessions/comfy-nodes/comfyui-nodes/.venv/bin/python -m pytest tests/ -q`
Expected: all pass (121 pre-existing + new).

- [ ] **Step 5: Commit** — `feat: nested ref paths resolve in prefill/compose (Files Read groundwork)`

---

### Task 3: /symbiotica/ref-image route (JS draw parity)

**Files:**
- Modify: `py/pipeline/routes.py` (new route after `local_image`)
- Modify: `web/js/order_pipeline.js:815-827` (`resolveMemberUrl` task/sprite branches)
- Test: `tests/test_routes_allowlist.py` (append)

**Interfaces:**
- Consumes: `compose.resolve_ref` (Task 2).
- Produces: `GET /symbiotica/ref-image?root=<abs>&rel=<path>` — serves the same file `_draw_task_refs` would draw; 403 outside registered roots.

- [ ] **Step 1: Write the failing test** (append to `tests/test_routes_allowlist.py`, following its existing style of testing the pure helpers)

```python
def test_ref_image_resolution_stays_inside_root(tmp_path):
    # The route resolves with compose.resolve_ref then gates on is_allowed —
    # a nested rel resolves, an escape attempt dies at the allowlist.
    from py.pipeline.compose import resolve_ref
    from py.pipeline.routes import is_allowed, register_root
    d = tmp_path / "refs" / "Stoves"
    d.mkdir(parents=True)
    (d / "a.png").write_bytes(b"x")
    root = str(tmp_path / "refs")
    register_root(root)
    assert is_allowed(resolve_ref(root, "Stoves/a.png")) is not None
    assert is_allowed(resolve_ref(root, "../../etc/passwd")) is None
```

- [ ] **Step 2: Run, verify state**

Run: `/Users/razvanmatei/.claude-sessions/comfy-nodes/comfyui-nodes/.venv/bin/python -m pytest tests/test_routes_allowlist.py -q`
Expected: PASS already (pure helpers exist) — this test pins the security contract the route relies on. The route itself is nodes-side code pytest can't import; it is verified live in Task 6.

- [ ] **Step 3: Implement the route** (`py/pipeline/routes.py`, after `local_image`)

```python
@PromptServer.instance.routes.get("/symbiotica/ref-image")
async def ref_image(request):
    """Serve the reference image a member path denotes, using the SAME
    resolution rule as compose._draw_task_refs (exact rel under root, else
    flat basename) — so the JS canvas shows exactly what the queued sheet
    will draw. Root must already be registered (a node execute did it)."""
    from .compose import resolve_ref
    root = request.query.get("root", "")
    rel = request.query.get("rel", "")
    resolved = is_allowed(resolve_ref(root, rel))
    if resolved is None:
        return web.json_response({"error": "not an allowed image path"}, status=403)
    return web.FileResponse(resolved,
                            headers={"Cache-Control": "private, max-age=60"})
```

- [ ] **Step 4: JS parity** (`web/js/order_pipeline.js`)

Add next to `thumbUrl`:

```javascript
    // Task-ref cells resolve through /symbiotica/ref-image, which applies the
    // SAME rule as the Python compositor (exact rel under refsRoot, else flat
    // basename) — the canvas preview and the queued sheet cannot disagree.
    const refUrl = (root, rel) => api.apiURL(
        `/symbiotica/ref-image?root=${encodeURIComponent(root)}&rel=${encodeURIComponent(rel)}`);
```

In `resolveMemberUrl`, replace the three task/sprite lookups:
- `thumbUrl(refsRoot, paths[0].split("/").pop())` → `refUrl(refsRoot, paths[0])`
- `thumbUrl(refsRoot, paths[Math.min(i, paths.length - 1)].split("/").pop())` → `refUrl(refsRoot, paths[Math.min(i, paths.length - 1)])`
- `thumbUrl(refsRoot, member.spriteId.split("/").pop())` → `refUrl(refsRoot, member.spriteId)`

(`projectPaths` branches keep `thumbUrl` — the catalog root already serves by rel.)

- [ ] **Step 5: Full suite + commit**

Run: `/Users/razvanmatei/.claude-sessions/comfy-nodes/comfyui-nodes/.venv/bin/python -m pytest tests/ -q`
Expected: all pass.
Commit: `feat: ref-image route — JS task-ref preview resolves like the compositor`

---

### Task 4: SymbioticaFilesRead node

**Files:**
- Modify: `py/pipeline/nodes.py` (new class after `SymbioticaOrderSpecs`, register in `PIPELINE_NODE_CLASSES`)

**Interfaces:**
- Consumes: `build_files_order` (Task 1), `_register_refs_root` (nodes.py:61).
- Produces: node `SymbioticaFilesRead`, output slot 0 = `Order`. JS (Task 5) reads/writes widgets `refs_path`, `name`, `selection`.

- [ ] **Step 1: Implement** (pytest cannot see nodes.py — the failing/passing check for this task is the live object_info in Task 6)

```python
class SymbioticaFilesRead(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaFilesRead",
            display_name="Symbiotica Files Read",
            category="symbiotica/pipeline",
            description="Build an order from loose client reference folders — "
                        "no xlsx. Open the files browser, tick folders/files "
                        "into groups (folder = one sheet row, ticked files = "
                        "its cells), and wire 'order' into the Auto Packer.",
            inputs=[
                io.String.Input("refs_path", default="",
                                tooltip="The client folder of reference "
                                        "images (subfolders welcome)"),
                io.String.Input("name", default="",
                                tooltip="Base name for the sheets (empty = "
                                        "the folder's name)"),
                io.String.Input("selection", default="{}", advanced=True,
                                tooltip="Groups JSON, set by the files "
                                        "browser"),
            ],
            outputs=[Order.Output(display_name="order")],
        )

    @classmethod
    def fingerprint_inputs(cls, refs_path="", name="", selection="{}"):
        h = hashlib.sha256(f"{refs_path}|{name}|{selection}".encode())
        # Re-run when any selected file changes on disk.
        try:
            sel = json.loads(selection or "{}")
        except ValueError:
            sel = {}
        for g in (sel or {}).get("groups") or []:
            for rel in g.get("files") or []:
                p = os.path.join(refs_path, *str(rel).split("/"))
                try:
                    st = os.stat(p)
                    h.update(f"{rel}:{st.st_mtime_ns}:{st.st_size}".encode())
                except OSError:
                    h.update(f"{rel}:missing".encode())
        return h.hexdigest()

    @classmethod
    def execute(cls, refs_path="", name="", selection="{}") -> io.NodeOutput:
        from .files_read import build_files_order
        order = build_files_order(refs_path, selection, name)
        _register_refs_root(order["refsRoot"])
        return io.NodeOutput(order)
```

Register: add `SymbioticaFilesRead,` to `PIPELINE_NODE_CLASSES` after `SymbioticaOrderSpecs`.

- [ ] **Step 2: Import-sanity check** (catches syntax/decorator mistakes pytest won't — the stacked-decorator lesson)

Run: `/Users/razvanmatei/.claude-sessions/comfy-nodes/comfyui-nodes/.venv/bin/python -c "import ast; ast.parse(open('py/pipeline/nodes.py').read())"`
Expected: silence.

- [ ] **Step 3: Full suite + commit**

Run: `/Users/razvanmatei/.claude-sessions/comfy-nodes/comfyui-nodes/.venv/bin/python -m pytest tests/ -q`
Expected: all pass (nothing imports nodes.py).
Commit: `feat: SymbioticaFilesRead node — loose client folders in, Order wire out`

---

### Task 5: files browser JS overlay

**Files:**
- Create: `web/js/files_read.js`

**Interfaces:**
- Consumes: `/symbiotica/list-assets?dir=` (rel + px dims, registers root), `/symbiotica/local-image?path=` (thumbs), node widgets `refs_path`/`name`/`selection` (Task 4).
- Produces: overlay that writes `selection` JSON `{groups: [{name, category, files, desc, variants}]}`.

Follow the pack's JS idioms: `app.registerExtension` + `beforeRegisterNodeDef`
(see order_pipeline.js:492-534), native button widget, `el()`-style DOM
helpers, trie tree per rail.js:845-1001 (copied, not extracted — the editor
must not move).

- [ ] **Step 1: Implement** — full file:

```javascript
// ABOUTME: Files Read node UI — fullscreen files browser over a client refs
// ABOUTME: folder: tree + filters, folder=group / ticked files=cells, writes
// ABOUTME: the node's selection JSON. Tree mechanics referenced from rail.js.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const widgetOf = (node, name) => node.widgets?.find((w) => w.name === name);
const el = (tag, style = "", text = "") => {
    const d = document.createElement(tag);
    if (style) d.style.cssText = style;
    if (text) d.textContent = text;
    return d;
};
const thumbUrl = (root, rel) => api.apiURL(
    `/symbiotica/local-image?path=${encodeURIComponent(`${root}/${rel}`)}`);

async function fetchJson(url) {
    const res = await api.fetchApi(url);
    if (!res.ok) throw new Error((await res.json())?.error ?? res.statusText);
    return res.json();
}

function readSelection(node) {
    try {
        const g = JSON.parse(widgetOf(node, "selection")?.value || "{}").groups;
        return Array.isArray(g) ? g : [];
    } catch {
        return [];
    }
}

function writeSelection(node, groups) {
    const w = widgetOf(node, "selection");
    if (w) w.value = JSON.stringify({ groups });
    updateSummary(node);
}

function updateSummary(node) {
    const groups = readSelection(node);
    const n = groups.reduce((s, g) => s + (g.files?.length ?? 0), 0);
    const label = widgetOf(node, "files_summary");
    if (label) label.value = groups.length
        ? `${groups.length} groups · ${n} files`
        : "no groups — open the files browser";
    node.setDirtyCanvas(true, true);
}

// Category proposal: nested folder -> its parent folder's name; a top-level
// folder is its own category.
function proposeCategory(folderKey) {
    const parts = folderKey.split("/");
    return parts.length > 1 ? parts[parts.length - 2] : parts[0];
}

function openBrowser(node) {
    const root = (widgetOf(node, "refs_path")?.value || "").trim();
    if (!root) {
        alert("Set refs_path to the client reference folder first.");
        return;
    }
    const overlay = el("div",
        "position:fixed;inset:0;z-index:10000;background:#161616;color:#ddd;" +
        "display:flex;flex-direction:column;font:12px sans-serif;");
    const bar = el("div",
        "display:flex;align-items:center;gap:10px;padding:8px 12px;" +
        "background:#202020;border-bottom:1px solid #333;");
    bar.appendChild(el("b", "", "Files browser — folder = group, ticked files = its row cells"));
    const closeBtn = el("button", "margin-left:auto;", "Done");
    bar.appendChild(closeBtn);
    overlay.appendChild(bar);

    const body = el("div", "flex:1;display:flex;min-height:0;");
    const treePane = el("div",
        "flex:1;overflow:auto;padding:10px;border-right:1px solid #333;");
    const groupsPane = el("div", "width:340px;overflow:auto;padding:10px;");
    body.append(treePane, groupsPane);
    overlay.appendChild(body);
    document.body.appendChild(overlay);
    closeBtn.addEventListener("click", () => overlay.remove());

    let images = [];              // [{rel, w, h}]
    let groups = readSelection(node);
    let search = "";
    let sizeFilter = null;        // "WxH" | null
    const expanded = new Set();

    const groupOf = (folderKey) => groups.find((g) => g.folder === folderKey);
    const save = () => { writeSelection(node, groups); renderGroups(); };

    // --- filters -----------------------------------------------------------
    const filterBar = el("div",
        "display:flex;gap:6px;align-items:center;padding:6px 12px;" +
        "background:#1b1b1b;border-bottom:1px solid #2a2a2a;flex-wrap:wrap;");
    const searchBox = el("input", "width:220px;");
    searchBox.placeholder = "filter by name…";
    searchBox.addEventListener("input", () => {
        search = searchBox.value.trim().toLowerCase();
        renderTree();
    });
    filterBar.appendChild(searchBox);
    const sizeChips = el("div", "display:flex;gap:4px;flex-wrap:wrap;");
    filterBar.appendChild(sizeChips);
    overlay.insertBefore(filterBar, body);

    function renderSizeChips() {
        sizeChips.replaceChildren();
        const sizes = [...new Set(images.filter((i) => i.w && i.h)
            .map((i) => `${i.w}x${i.h}`))].sort((a, b) =>
                parseInt(a) - parseInt(b) || a.localeCompare(b));
        for (const label of ["all", ...sizes]) {
            const v = label === "all" ? null : label;
            const c = el("button",
                `opacity:${v === sizeFilter ? 1 : 0.55};`, label);
            c.addEventListener("click", () => {
                sizeFilter = v;
                renderSizeChips();
                renderTree();
            });
            sizeChips.appendChild(c);
        }
    }

    function visibleImages() {
        return images.filter((img) => {
            if (search && !img.rel.toLowerCase().includes(search)) return false;
            if (sizeFilter && `${img.w}x${img.h}` !== sizeFilter) return false;
            return true;
        });
    }

    // --- tree (trie per rail.js) ------------------------------------------
    function buildTree(entries) {
        const rootNode = { folders: new Map(), files: [], count: 0 };
        for (const entry of entries) {
            const parts = entry.rel.split("/");
            let n = rootNode;
            n.count++;
            for (let i = 0; i < parts.length - 1; i++) {
                if (!n.folders.has(parts[i])) {
                    n.folders.set(parts[i],
                        { folders: new Map(), files: [], count: 0 });
                }
                n = n.folders.get(parts[i]);
                n.count++;
            }
            n.files.push(entry);
        }
        return rootNode;
    }

    function renderTree() {
        treePane.replaceChildren();
        const entries = visibleImages();
        if (!entries.length) {
            treePane.appendChild(el("div", "opacity:.6;",
                images.length ? "no images match the filters"
                              : "⏳ loading folder…"));
            return;
        }

        function fileRow(entry, folderKey, depth) {
            const g = groupOf(folderKey);
            const row = el("div",
                `display:flex;align-items:center;gap:6px;padding:1px 0 1px ${12 * depth + 18}px;`);
            const check = el("input");
            check.type = "checkbox";
            check.checked = Boolean(g?.files?.includes(entry.rel));
            check.addEventListener("change", () => {
                let g2 = groupOf(folderKey);
                if (!g2) {
                    const name = folderKey.split("/").pop();
                    g2 = { folder: folderKey, name,
                           category: proposeCategory(folderKey), files: [],
                           desc: "", variants: false };
                    groups.push(g2);
                }
                g2.files = g2.files.filter((p) => p !== entry.rel);
                if (check.checked) g2.files.push(entry.rel); // tick order = cell order
                if (!g2.files.length) groups = groups.filter((x) => x !== g2);
                save();
                renderTree();
            });
            const img = el("img",
                "width:34px;height:34px;object-fit:contain;background:#111;" +
                "border-radius:3px;flex:none;");
            img.loading = "lazy";
            img.src = thumbUrl(root, entry.rel);
            const label = el("span",
                "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;",
                `${entry.rel.split("/").pop()}  ${entry.w ?? "?"}×${entry.h ?? "?"}`);
            label.title = entry.rel;
            row.append(check, img, label);
            return row;
        }

        function renderNode(node, prefix, depth) {
            for (const [dirName, child] of node.folders) {
                const key = prefix ? `${prefix}/${dirName}` : dirName;
                const open = expanded.has(key) || Boolean(search || sizeFilter);
                const g = groupOf(key);
                const direct = child.files.map((e) => e.rel);
                const nChecked = direct.filter((p) => g?.files?.includes(p)).length;
                const fh = el("div",
                    `display:flex;align-items:center;gap:4px;padding:2px 0 2px ${12 * depth}px;`);
                const check = el("input");
                check.type = "checkbox";
                check.checked = direct.length > 0 && nChecked === direct.length;
                check.indeterminate = nChecked > 0 && nChecked < direct.length;
                check.addEventListener("click", (e) => e.stopPropagation());
                check.addEventListener("change", () => {
                    // Folder tick = group its DIRECT visible files (subfolders
                    // are their own groups — one folder, one sheet row).
                    const clearing = nChecked > 0;
                    let g2 = groupOf(key);
                    if (clearing) {
                        if (g2) {
                            g2.files = g2.files.filter((p) => !direct.includes(p));
                            if (!g2.files.length) {
                                groups = groups.filter((x) => x !== g2);
                            }
                        }
                    } else {
                        if (!g2) {
                            g2 = { folder: key, name: dirName,
                                   category: proposeCategory(key), files: [],
                                   desc: "", variants: false };
                            groups.push(g2);
                        }
                        g2.files = [...new Set([...g2.files, ...direct])];
                    }
                    save();
                    renderTree();
                });
                const label = el("span", "flex:1;cursor:pointer;",
                    `${open ? "▾" : "▸"} 📁 ${dirName}  ${nChecked}/${child.count}`);
                label.addEventListener("click", () => {
                    expanded[open ? "delete" : "add"](key);
                    renderTree();
                });
                fh.append(check, label);
                treePane.appendChild(fh);
                if (open) renderNode(child, key, depth + 1);
            }
            for (const entry of node.files) {
                treePane.appendChild(fileRow(entry, prefix || "(root)", depth));
            }
        }
        renderNode(buildTree(entries), "", 0);
    }

    // --- groups panel ------------------------------------------------------
    function renderGroups() {
        groupsPane.replaceChildren();
        groupsPane.appendChild(el("div", "font-weight:bold;margin-bottom:6px;",
            `Groups · ${groups.length}`));
        if (!groups.length) {
            groupsPane.appendChild(el("div", "opacity:.6;",
                "Tick a folder (one group = one sheet row) or single files."));
        }
        for (const g of groups) {
            const card = el("div",
                "border:1px solid #333;border-radius:6px;padding:8px;margin-bottom:8px;");
            const head = el("div", "display:flex;gap:6px;align-items:center;");
            const nameIn = el("input", "flex:1;");
            nameIn.value = g.name;
            nameIn.addEventListener("change", () => { g.name = nameIn.value; save(); });
            const del = el("button", "", "✕");
            del.addEventListener("click", () => {
                groups = groups.filter((x) => x !== g);
                save();
                renderTree();
            });
            head.append(nameIn, del);
            card.appendChild(head);

            const catRow = el("div",
                "display:flex;gap:6px;align-items:center;margin-top:4px;");
            catRow.appendChild(el("span", "opacity:.6;", "category"));
            const catIn = el("input", "flex:1;");
            catIn.value = g.category;
            catIn.addEventListener("change", () => { g.category = catIn.value; save(); });
            catRow.appendChild(catIn);
            card.appendChild(catRow);

            const descRow = el("div",
                "display:flex;gap:6px;align-items:center;margin-top:4px;");
            descRow.appendChild(el("span", "opacity:.6;", "desc"));
            const descIn = el("input", "flex:1;");
            descIn.placeholder = "optional — becomes the sheet prompt";
            descIn.value = g.desc ?? "";
            descIn.addEventListener("change", () => { g.desc = descIn.value; save(); });
            descRow.appendChild(descIn);
            card.appendChild(descRow);

            const varRow = el("label",
                "display:flex;gap:6px;align-items:center;margin-top:4px;cursor:pointer;");
            const varCheck = el("input");
            varCheck.type = "checkbox";
            varCheck.checked = Boolean(g.variants);
            varCheck.addEventListener("change", () => {
                g.variants = varCheck.checked;
                save();
            });
            varRow.append(varCheck,
                el("span", "", "variants (distinct directions, mirror/split)"));
            card.appendChild(varRow);

            const cells = el("div",
                "display:flex;gap:4px;flex-wrap:wrap;margin-top:6px;");
            g.files.forEach((rel, i) => {
                const cell = el("div",
                    "position:relative;width:44px;text-align:center;");
                const img = el("img",
                    "width:40px;height:40px;object-fit:contain;background:#111;" +
                    "border-radius:3px;");
                img.src = thumbUrl(root, rel);
                img.title = rel;
                cell.appendChild(img);
                const ctl = el("div", "display:flex;justify-content:center;gap:2px;");
                const mk = (txt, fn) => {
                    const b = el("a", "cursor:pointer;font-size:10px;", txt);
                    b.addEventListener("click", fn);
                    return b;
                };
                if (i > 0) ctl.appendChild(mk("◀", () => {
                    g.files.splice(i - 1, 0, g.files.splice(i, 1)[0]);
                    save();
                }));
                ctl.appendChild(mk("✕", () => {
                    g.files.splice(i, 1);
                    if (!g.files.length) groups = groups.filter((x) => x !== g);
                    save();
                    renderTree();
                }));
                if (i < g.files.length - 1) ctl.appendChild(mk("▶", () => {
                    g.files.splice(i + 1, 0, g.files.splice(i, 1)[0]);
                    save();
                }));
                cell.appendChild(ctl);
                cells.appendChild(cell);
            });
            card.appendChild(cells);
            groupsPane.appendChild(card);
        }
    }

    renderGroups();
    renderTree();
    fetchJson(`/symbiotica/list-assets?dir=${encodeURIComponent(root)}`)
        .then((data) => {
            images = data.images ?? [];
            renderSizeChips();
            renderTree();
        })
        .catch((e) => {
            treePane.replaceChildren(
                el("div", "color:#f66;", `could not list folder: ${e.message}`));
        });
}

app.registerExtension({
    name: "symbiotica.files_read",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SymbioticaFilesRead") return;
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            const node = this;
            node.addWidget("button", "📂 Open files browser", null,
                () => openBrowser(node));
            const summary = node.addWidget("text", "files_summary", "", () => {});
            summary.disabled = true;
            summary.serialize = false;
            updateSummary(node);
        };
    },
});
```

- [ ] **Step 2: Syntax check**

Run: `node --check web/js/files_read.js`
Expected: silence.

- [ ] **Step 3: Commit** — `feat: files browser overlay for SymbioticaFilesRead`

---

### Task 6: live verification on the pod

**Files:** none (deploy + checks)

- [ ] **Step 1: Deploy branch to the RunPod pod**

```bash
ssh -p 11077 root@69.8.146.87 \
  "cd /workspace/runpod-slim/ComfyUI/custom_nodes/symbiotica && \
   git fetch origin autopack-datasets && git checkout autopack-datasets && \
   git pull --ff-only origin autopack-datasets"
```
(Push the branch to origin first.) Then reboot ComfyUI (pod's reboot route or process restart — check how the pod runs ComfyUI via `ssh ... 'ps aux | grep main.py'`).

- [ ] **Step 2: Schema check**

`curl https://d8x5xufbqr4kcv-8188.proxy.runpod.net/api/object_info/SymbioticaFilesRead` — inputs `refs_path`, `name` (+ advanced `selection`), output `SYMBIOTICA_ORDER`.

- [ ] **Step 3: Harness check** — `.cs/local/browser/drive.mjs` against the proxied URL: add node, open browser overlay on a real client folder, tick a folder, read the selection widget JSON, screenshot.

- [ ] **Step 4: End-to-end** — Files Read → Auto Packer (+ Preset/Settings) → queue; confirm sheets render the ticked nested refs (not blank cells).

- [ ] **Step 5: Report to Razvan** with the screenshot; note the pod is on the feature branch (flip back to main after merge).
