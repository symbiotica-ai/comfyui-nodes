# Studio Library Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A ComfyUI V3 node `SymbioticaStudioLibrary` that browses the active studio's non-model asset tree inside the editor sandbox and outputs the picked file/folder's absolute sandbox `path` (STRING) plus `is_dir` (BOOLEAN).

**Architecture:** Pure logic in a new `py/pipeline/studio_library.py` (confinement resolver + never-raising lister), a thin V3 node in `py/pipeline/nodes.py` that delegates to it, a lazy per-level aiohttp browse route in `py/pipeline/routes.py` with a bounded async volume sync, and a single-select `web/js` overlay that exports a pure selection seam. Env-free resolution confined to the studio-assets Volume root is the load-bearing guard.

**Tech Stack:** ComfyUI V3 node API (`comfy_api.latest` io), aiohttp routes, vanilla-JS ComfyUI extension, `pytest` + node's built-in test runner.

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-23-studio-library-picker-design.md` (read it; Appendix B lists the 23 review dispositions this plan implements).
- **Test runner (Python):** run **`pytest tests/`** from the repo root (`/Users/alex.geana/.claude-sessions/sym-comfy-nodes/comfyui-nodes`). **NEVER `python -m pytest`** — CWD-on-`sys.path` makes the top-level `py/` package shadow pytest's bundled `py` lib (`AttributeError: py.path`). `tests/conftest.py` inserts `<repo>/py`, so tests import `pipeline.*`, never `py.pipeline.*`.
- **Test runner (JS):** `node --import ./tests/js/register_hooks.mjs --test 'tests/js/*.test.mjs'` (directory form breaks on Node 25 — use the glob). The stub now defines `requestAnimationFrame`.
- **Combined gate:** `pytest tests/ && { [ -d tests/js ] || exit 0; node --import ./tests/js/register_hooks.mjs --test 'tests/js/*.test.mjs'; }` (from `.claude/release.config.json`).
- **Baseline before starting:** 233 pytest + 24 JS green on branch `feat/studio-library-node`.
- **Env-free resolution.** `execute()`/`fingerprint_inputs()` MUST NOT read `CANVAS_STUDIO`. The only env the resolution path consults is `STUDIO_ASSETS_DIR`. `CANVAS_STUDIO` is read ONLY in the route.
- **One namespace.** Every `rel`/`dir`/`selection`/per-entry `rel` is volume-relative `studios/<slug>[/...]`; `""` is a route-only sentinel for the studio root.
- **Confinement is the load-bearing guard.** A stored selection must never resolve outside the Volume root. Use the repo's two-arm realpath idiom: `path == root or path.startswith(root + os.sep)` (see `files_read.py:63`, `routes.py:45,300,327`).
- **`MODEL_KINDS`** is the 8-name set from `services/comfy-modal/canvas_entry.py:14-25` (source of truth), hidden at the studio root only.
- **Slug shape** `[a-z0-9]+(?:-[a-z0-9]+)*` (`studio_fs.py:9`), `.fullmatch()` — no length cap, no underscores.
- **Commit style:** conventional (`feat:`, `fix:`, `test:`, `docs:`), plain prose bodies. Commit per task.
- **Registration:** a node joins by appending its class to `PIPELINE_NODE_CLASSES` (`nodes.py:1708`) and defining `define_schema`/`execute`; routes auto-register via `symbiotica_pipeline.py:16-19`.

---

### Task 1: Studio-path resolver + constants (pure)

**Files:**
- Create: `py/pipeline/studio_library.py`
- Test: `tests/test_studio_library.py`

**Interfaces:**
- Produces:
  - `STUDIO_ASSETS_DIR: str`, `MODEL_KINDS: frozenset[str]`, `RESERVED_PREFIX: str`, `_STUDIO_SLUG: re.Pattern`
  - `resolve_studio_path(base_dir: str, rel: str) -> str` (absolute path; raises `ValueError` on invalid/escaping)
  - internal helpers `_split_studio(rel) -> tuple[str, str] | None`, `_confined_root(base_dir) -> str`

- [ ] **Step 1: Write the failing tests** (`tests/test_studio_library.py`)

```python
# ABOUTME: Tests for studio_library pure logic — confinement resolver, lister,
# ABOUTME: selection fingerprint. Real tmp trees; no ComfyUI import.
import os

import pytest

from pipeline.studio_library import MODEL_KINDS, resolve_studio_path


def _touch(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture()
def vol(tmp_path):
    # A studio-assets Volume root with one provisioned studio.
    _touch(tmp_path / "studios" / "ggs" / "references" / "hero.png")
    (tmp_path / "studios" / "ggs" / "empty_dir").mkdir(parents=True)
    return tmp_path


def test_resolves_file_to_absolute(vol):
    got = resolve_studio_path(str(vol), "studios/ggs/references/hero.png")
    assert got == os.path.realpath(str(vol / "studios" / "ggs" / "references" / "hero.png"))


def test_resolves_folder_and_studio_root(vol):
    assert resolve_studio_path(str(vol), "studios/ggs/references") == \
        os.path.realpath(str(vol / "studios" / "ggs" / "references"))
    assert resolve_studio_path(str(vol), "studios/ggs") == \
        os.path.realpath(str(vol / "studios" / "ggs"))


def test_empty_selection_raises(vol):
    with pytest.raises(ValueError, match="no selection"):
        resolve_studio_path(str(vol), "")
    with pytest.raises(ValueError, match="no selection"):
        resolve_studio_path(str(vol), "   ")


def test_absolute_selection_raises(vol):
    with pytest.raises(ValueError, match="not a studio path"):
        resolve_studio_path(str(vol), "/etc/passwd")


def test_non_studios_prefix_raises(vol):
    with pytest.raises(ValueError, match="not a studio path"):
        resolve_studio_path(str(vol), "elsewhere/x.png")


def test_dotdot_escape_raises(vol):
    # Textual prefix passes; realpath collapses .. to outside the Volume root.
    _touch(vol.parent / "secret.png")
    with pytest.raises(ValueError, match="outside the studio library"):
        resolve_studio_path(str(vol), "studios/ggs/../../../secret.png")


def test_in_tree_symlink_escape_raises(vol):
    outside = vol.parent / "outside.png"
    _touch(outside)
    link = vol / "studios" / "ggs" / "link.png"
    os.symlink(outside, link)
    with pytest.raises(ValueError, match="outside the studio library"):
        resolve_studio_path(str(vol), "studios/ggs/link.png")


def test_invalid_slug_raises(vol):
    with pytest.raises(ValueError, match="not a studio path"):
        resolve_studio_path(str(vol), "studios/Bad_Slug/x.png")


def test_long_kebab_slug_resolves(vol):
    # Studio slug shape has NO length cap and NO underscores (unlike user-id).
    slug = "a" + "-b" * 40  # > 32 chars, valid kebab
    _touch(vol / "studios" / slug / "f.png")
    assert resolve_studio_path(str(vol), f"studios/{slug}/f.png") == \
        os.path.realpath(str(vol / "studios" / slug / "f.png"))


def test_missing_path_raises(vol):
    with pytest.raises(ValueError, match="not found"):
        resolve_studio_path(str(vol), "studios/ggs/nope.png")


def test_empty_or_relative_base_raises(vol):
    with pytest.raises(ValueError):
        resolve_studio_path("", "studios/ggs/references/hero.png")
    with pytest.raises(ValueError):
        resolve_studio_path("relative/dir", "studios/ggs/references/hero.png")


def test_model_kinds_is_the_eight_names():
    # Pinned literal (independent of the module constant) — guards cross-repo drift
    # from services/comfy-modal/canvas_entry.py:14-25.
    assert MODEL_KINDS == frozenset({
        "checkpoints", "loras", "vae", "controlnet",
        "upscale_models", "embeddings", "diffusion_models", "text_encoders",
    })
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_studio_library.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pipeline.studio_library'`.

- [ ] **Step 3: Write minimal implementation** (`py/pipeline/studio_library.py`)

```python
# ABOUTME: Pure logic for the Studio Library Picker node — confines a stored
# ABOUTME: volume-relative selection to the studio-assets Volume root and lists it.
import hashlib
import os
import re

# The studio-assets Volume mount root (matches services/comfy-modal/app.py:110).
# Trim + `or` default so a set-but-empty/whitespace env cannot re-anchor the
# confinement root to the process CWD.
STUDIO_ASSETS_DIR = (os.environ.get("STUDIO_ASSETS_DIR") or "").strip() or "/studio-assets"

# Model kinds the editor already surfaces natively via /comfy-models; hidden from
# the browse listing at the studio root. Source of truth (a cross-repo copy):
# services/comfy-modal/canvas_entry.py:14-25 (the sym hub).
MODEL_KINDS = frozenset({
    "checkpoints", "loras", "vae", "controlnet",
    "upscale_models", "embeddings", "diffusion_models", "text_encoders",
})

RESERVED_PREFIX = "studios/"  # services/comfy-modal/studio_assets.py:7

# Studio slug shape (services/comfy-modal/studio_fs.py:9): lowercase kebab-case,
# no length cap, no underscores. Applied with .fullmatch().
_STUDIO_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _split_studio(rel):
    """(slug, tail) for a volume-relative studios/<slug>[/...] rel, else None."""
    parts = rel.split("/")
    if len(parts) < 2 or parts[0] != "studios" or not _STUDIO_SLUG.fullmatch(parts[1]):
        return None
    return parts[1], "/".join(parts[2:])


def _confined_root(base_dir):
    """realpath'd Volume root; raise ValueError if base_dir is not a usable
    absolute directory (an empty/relative env must not re-anchor to CWD)."""
    if not os.path.isabs(base_dir):
        raise ValueError(f"studio-assets dir is not absolute: {base_dir!r}")
    root = os.path.realpath(base_dir)
    if not os.path.isdir(root):
        raise ValueError(f"studio-assets dir does not exist: {base_dir!r}")
    return root


def resolve_studio_path(base_dir, rel):
    """Absolute path for a volume-relative selection, confined to the Volume root.
    Raises ValueError on empty, non-studio, escaping, or missing input."""
    rel = str(rel or "").strip()
    if not rel:
        raise ValueError("no selection")
    if _split_studio(rel) is None:
        raise ValueError(f"not a studio path: {rel!r}")
    root = _confined_root(base_dir)
    path = os.path.realpath(os.path.join(root, rel))
    if not (path == root or path.startswith(root + os.sep)):
        raise ValueError("outside the studio library")
    if not os.path.exists(path):
        raise ValueError(f"not found: {rel}")
    return path
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_studio_library.py -q`
Expected: PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add py/pipeline/studio_library.py tests/test_studio_library.py
git commit -m "feat: studio-path confinement resolver for the studio library node"
```

---

### Task 2: `resolve_selection` + `selection_fingerprint` (pure)

**Files:**
- Modify: `py/pipeline/studio_library.py`
- Test: `tests/test_studio_library.py` (append)

**Interfaces:**
- Consumes: `resolve_studio_path` (Task 1).
- Produces:
  - `resolve_selection(base_dir: str, selection: str) -> tuple[str, bool]` (path, is_dir)
  - `selection_fingerprint(base_dir: str, selection: str) -> str` (hex sha256)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_studio_library.py`)

```python
from pipeline.studio_library import resolve_selection, selection_fingerprint


def test_resolve_selection_is_dir_flag(vol):
    assert resolve_selection(str(vol), "studios/ggs/references/hero.png")[1] is False
    assert resolve_selection(str(vol), "studios/ggs/references")[1] is True


def test_fingerprint_changes_on_file_mtime_and_size(vol):
    sel = "studios/ggs/references/hero.png"
    f = vol / "studios" / "ggs" / "references" / "hero.png"
    fp0 = selection_fingerprint(str(vol), sel)
    os.utime(f, (1_000_000, 1_000_000))
    fp_mtime = selection_fingerprint(str(vol), sel)
    assert fp_mtime != fp0
    f.write_bytes(b"much longer content")  # size change
    assert selection_fingerprint(str(vol), sel) != fp_mtime


def test_fingerprint_folder_tracks_direntry_set_not_content(vol):
    sel = "studios/ggs/references"
    fp0 = selection_fingerprint(str(vol), sel)
    # Adding a direntry changes the fingerprint...
    (vol / "studios" / "ggs" / "references" / "new.png").write_bytes(b"y")
    fp_added = selection_fingerprint(str(vol), sel)
    assert fp_added != fp0
    # ...but an in-place rewrite of a file UNDER the folder does NOT (documented).
    (vol / "studios" / "ggs" / "references" / "hero.png").write_bytes(b"zzzzzzzz")
    assert selection_fingerprint(str(vol), sel) == fp_added


def test_fingerprint_stable_and_unresolved(vol):
    sel = "studios/ggs/references/hero.png"
    assert selection_fingerprint(str(vol), sel) == selection_fingerprint(str(vol), sel)
    a = selection_fingerprint(str(vol), "studios/ggs/gone.png")
    b = selection_fingerprint(str(vol), "studios/ggs/also-gone.png")
    assert a != b  # the selection string is always hashed
    assert selection_fingerprint(str(vol), "studios/ggs/gone.png") == a  # stable


def test_none_selection_does_not_raise(vol):
    # A value wired from an upstream STRING socket can be None.
    assert isinstance(selection_fingerprint(str(vol), None), str)
    with pytest.raises(ValueError, match="no selection"):
        resolve_selection(str(vol), None)


def test_resolution_ignores_canvas_studio(vol, monkeypatch):
    # execute()/fingerprint delegate here and must NOT consult CANVAS_STUDIO.
    sel = "studios/ggs/references/hero.png"
    monkeypatch.setenv("CANVAS_STUDIO", "imperia")  # a different, nonexistent studio
    with_env = resolve_selection(str(vol), sel)
    fp_env = selection_fingerprint(str(vol), sel)
    monkeypatch.delenv("CANVAS_STUDIO", raising=False)
    assert resolve_selection(str(vol), sel) == with_env
    assert selection_fingerprint(str(vol), sel) == fp_env
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_studio_library.py -q -k "selection or fingerprint or canvas or none_selection"`
Expected: FAIL — `ImportError: cannot import name 'resolve_selection'`.

- [ ] **Step 3: Write minimal implementation** (append to `py/pipeline/studio_library.py`)

```python
def resolve_selection(base_dir, selection):
    """(absolute path, is_dir) for a stored selection. Env-free."""
    path = resolve_studio_path(base_dir, selection)
    return path, os.path.isdir(path)


def selection_fingerprint(base_dir, selection):
    """Content-change hash. Files: mtime+size. Folders: sorted direntry-name set
    (an in-place rewrite of a file UNDER a selected folder does NOT change it —
    a documented limitation). Always hashes the selection string itself."""
    selection = str(selection or "")
    h = hashlib.sha256(selection.encode())
    try:
        path, is_dir = resolve_selection(base_dir, selection)
        if is_dir:
            h.update("\x00".join(sorted(os.listdir(path))).encode())
        else:
            st = os.stat(path)
            h.update(f"{st.st_mtime_ns}:{st.st_size}".encode())
    except (ValueError, OSError):
        h.update(b"unresolved")
    return h.hexdigest()
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_studio_library.py -q`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add py/pipeline/studio_library.py tests/test_studio_library.py
git commit -m "feat: selection resolver and change fingerprint for studio library"
```

---

### Task 3: `list_studio_dir` (pure, never-raises lister)

**Files:**
- Modify: `py/pipeline/studio_library.py`
- Test: `tests/test_studio_library.py` (append)

**Interfaces:**
- Consumes: `_split_studio`, `_confined_root`, `MODEL_KINDS` (Task 1).
- Produces: `list_studio_dir(base_dir: str, studio: str, rel: str = "") -> dict` with keys `studio`, `rel`, `parent`, `entries` (list of `{name, rel, type, size}`) OR `{"error": str}`. Never raises.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_studio_library.py`)

```python
from pipeline.studio_library import list_studio_dir


@pytest.fixture()
def vol2(tmp_path):
    root = tmp_path
    for k in ("checkpoints", "loras", "references", "renders"):
        (root / "studios" / "ggs" / k).mkdir(parents=True)
    _touch(root / "studios" / "ggs" / "references" / "hero.png", b"1234")
    _touch(root / "studios" / "ggs" / "references" / ".hidden", b"x")
    (root / "studios" / "ggs" / "references" / "loras").mkdir()  # nested "loras" is legit
    _touch(root / "studios" / "ggs" / "brief.txt", b"hi")
    return root


def test_lists_dirs_first_and_hides_model_kinds_at_root(vol2):
    res = list_studio_dir(str(vol2), "ggs", "")
    assert "error" not in res
    assert res["rel"] == "studios/ggs"
    assert res["parent"] is None
    names = [e["name"] for e in res["entries"]]
    assert "checkpoints" not in names and "loras" not in names  # MODEL_KINDS hidden at root
    assert names == ["references", "renders", "brief.txt"]  # dirs first, case-insensitive
    ref = next(e for e in res["entries"] if e["name"] == "references")
    assert ref["type"] == "dir" and ref["rel"] == "studios/ggs/references"


def test_model_kinds_not_hidden_in_nested_dir(vol2):
    res = list_studio_dir(str(vol2), "ggs", "studios/ggs/references")
    names = [e["name"] for e in res["entries"]]
    assert "loras" in names  # a nested folder literally named "loras" is a real asset
    assert ".hidden" not in names  # dotfiles skipped
    hero = next(e for e in res["entries"] if e["name"] == "hero.png")
    assert hero["type"] == "file" and hero["size"] == 4
    assert res["parent"] == "studios/ggs"


def test_missing_studio_root_lists_empty_not_error(tmp_path):
    (tmp_path / "studios").mkdir()  # volume exists, studio not provisioned
    res = list_studio_dir(str(tmp_path), "brandnew", "")
    assert res == {"studio": "brandnew", "rel": "studios/brandnew", "parent": None, "entries": []}


def test_escaping_dir_returns_error_not_raise(vol2):
    assert "error" in list_studio_dir(str(vol2), "ggs", "studios/ggs/../imperia")
    assert "error" in list_studio_dir(str(vol2), "ggs", "studios/other/x")


def test_prefix_collision_sibling_not_inside(tmp_path):
    (tmp_path / "studios" / "ggs" / "a").mkdir(parents=True)
    (tmp_path / "studios" / "ggs-2" / "secret").mkdir(parents=True)
    assert "error" in list_studio_dir(str(tmp_path), "ggs", "studios/ggs-2")


def test_file_as_dir_returns_error(vol2):
    assert "error" in list_studio_dir(str(vol2), "ggs", "studios/ggs/brief.txt")


def test_nul_byte_returns_error_not_raise(vol2):
    assert "error" in list_studio_dir(str(vol2), "ggs", "studios/ggs/a\x00b")


def test_invalid_studio_returns_error(vol2):
    assert "error" in list_studio_dir(str(vol2), "Bad_Studio", "")


def test_symlinked_dir_types_as_dir(vol2):
    target = vol2 / "studios" / "ggs" / "renders"
    link = vol2 / "studios" / "ggs" / "references" / "link_dir"
    os.symlink(target, link)
    res = list_studio_dir(str(vol2), "ggs", "studios/ggs/references")
    e = next(e for e in res["entries"] if e["name"] == "link_dir")
    assert e["type"] == "dir"  # matches execute()'s os.path.isdir


def test_round_trip_child_rel_lists(vol2):
    root = list_studio_dir(str(vol2), "ggs", "")
    first_dir = next(e for e in root["entries"] if e["type"] == "dir")
    child = list_studio_dir(str(vol2), "ggs", first_dir["rel"])
    assert "error" not in child and child["rel"] == first_dir["rel"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_studio_library.py -q -k list or nul or prefix or symlink or round`
Expected: FAIL — `ImportError: cannot import name 'list_studio_dir'`.

- [ ] **Step 3: Write minimal implementation** (append to `py/pipeline/studio_library.py`)

```python
def list_studio_dir(base_dir, studio, rel=""):
    """Confined single-level listing of studios/<studio>[/rel]. Never raises —
    returns {"error": ...} for a bad/escaping dir, or a normal empty listing for
    an unprovisioned studio."""
    try:
        studio = str(studio or "")
        if not _STUDIO_SLUG.fullmatch(studio):
            return {"error": "invalid studio"}
        root = _confined_root(base_dir)
        studio_root = os.path.realpath(os.path.join(root, "studios", studio))
        if not os.path.isdir(studio_root):
            return {"studio": studio, "rel": f"studios/{studio}", "parent": None, "entries": []}
        rel = str(rel or "").strip() or f"studios/{studio}"
        parts = _split_studio(rel)
        if parts is None or parts[0] != studio:
            return {"error": "outside the studio library"}
        target = os.path.realpath(os.path.join(root, rel))
        if not (target == studio_root or target.startswith(studio_root + os.sep)):
            return {"error": "outside the studio library"}
        if not os.path.isdir(target):
            return {"error": "not a directory"}
        at_root = target == studio_root
        entries = []
        with os.scandir(target) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                if at_root and e.name in MODEL_KINDS:
                    continue
                is_dir = os.path.isdir(os.path.join(target, e.name))  # follow; matches execute
                size = None
                if not is_dir:
                    try:
                        size = e.stat().st_size
                    except OSError:
                        size = None
                entries.append({
                    "name": e.name,
                    "rel": f"{rel}/{e.name}",
                    "type": "dir" if is_dir else "file",
                    "size": size,
                })
        entries.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))
        parent = None if at_root else "/".join(rel.split("/")[:-1])
        return {"studio": studio, "rel": rel, "parent": parent, "entries": entries}
    except (ValueError, OSError) as exc:
        return {"error": str(exc) or "listing failed"}
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_studio_library.py -q`
Expected: PASS (all studio_library tests).

- [ ] **Step 5: Commit**

```bash
git add py/pipeline/studio_library.py tests/test_studio_library.py
git commit -m "feat: never-raising confined studio directory lister"
```

---

### Task 4: `SymbioticaStudioLibrary` node + registration + shim

**Files:**
- Modify: `py/pipeline/nodes.py` (add class near `SymbioticaFilesRead` ~257-308; append to `PIPELINE_NODE_CLASSES` ~1708)
- Modify: `tests/test_shim.py` (add `pipeline.studio_library` to the pure-import list)
- Test: `tests/test_shim.py`

**Interfaces:**
- Consumes: `resolve_selection`, `selection_fingerprint`, `STUDIO_ASSETS_DIR` (Tasks 1-2); `io.ComfyNode`/`io.Schema`/`io.String`/`io.Boolean`/`io.NodeOutput` (`nodes.py:11`).
- Produces: node id `SymbioticaStudioLibrary` in `PIPELINE_NODE_CLASSES`.

- [ ] **Step 1: Write the failing test** (edit `tests/test_shim.py`)

Add `"pipeline.studio_library"` to the list the shim imports without ComfyUI:

```python
    for mod in ["pipeline.order_sheet", "pipeline.order_loader",
                "pipeline.texture_pack", "pipeline.model_presets",
                "pipeline.prefill", "pipeline.compose",
                "pipeline.studio_library"]:
        importlib.import_module(mod)
```

- [ ] **Step 2: Run to verify shim still passes** (the module already imports pure)

Run: `pytest tests/test_shim.py -q`
Expected: PASS — `pipeline.studio_library` imports with no ComfyUI; `pipeline.nodes` still raises `ImportError`.

- [ ] **Step 3: Add the node class** (`py/pipeline/nodes.py`, after `SymbioticaFilesRead`)

```python
class SymbioticaStudioLibrary(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaStudioLibrary",
            display_name="Symbiotica Studio Library",
            category="symbiotica/pipeline",
            description="Pick a file or folder from the studio asset library; "
                        "outputs its absolute sandbox path (and whether it is a "
                        "folder). Open the browser, click one entry.",
            inputs=[
                io.String.Input("selection", default="", advanced=True,
                                tooltip="Volume-relative pick, set by the "
                                        "studio-library browser"),
            ],
            outputs=[
                io.String.Output(display_name="path"),
                io.Boolean.Output(display_name="is_dir"),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, selection=""):
        from .studio_library import STUDIO_ASSETS_DIR, selection_fingerprint
        return selection_fingerprint(STUDIO_ASSETS_DIR, selection)

    @classmethod
    def execute(cls, selection="") -> io.NodeOutput:
        from .studio_library import STUDIO_ASSETS_DIR, resolve_selection
        path, is_dir = resolve_selection(STUDIO_ASSETS_DIR, selection)
        return io.NodeOutput(path, is_dir)
```

Append `SymbioticaStudioLibrary` to `PIPELINE_NODE_CLASSES` (last entry is fine):

```python
    SymbioticaTemplatePrompt,
    SymbioticaStudioLibrary,
]
```

- [ ] **Step 4: Verify no import breakage**

Run: `pytest tests/ -q`
Expected: PASS (233 + Task 1-3 tests). `nodes.py` is not imported by pytest, so this confirms nothing regressed.

- [ ] **Step 5: Verify the node registers live** (manual smoke — the pack loads in real ComfyUI)

Run: `python -c "import ast,sys; ast.parse(open('py/pipeline/nodes.py').read()); print('nodes.py parses')"`
Expected: `nodes.py parses`. (Full registration is verified when ComfyUI restarts — see Rollout in the spec.)

- [ ] **Step 6: Commit**

```bash
git add py/pipeline/nodes.py tests/test_shim.py
git commit -m "feat: SymbioticaStudioLibrary node delegating to pure resolver"
```

---

### Task 5: Browse route + bounded async sync

**Files:**
- Modify: `py/pipeline/routes.py` (add `import asyncio`; add `_sync_studio_assets` + the `studio_library` handler)
- Test: `tests/test_routes_studio_library.py`

**Interfaces:**
- Consumes: `list_studio_dir`, `STUDIO_ASSETS_DIR` (Tasks 1,3).
- Produces: route `GET /symbiotica/studio-library`; module-level `_sync_studio_assets(root) -> coroutine`, `SYNC_TIMEOUT_S`.

- [ ] **Step 1: Write the failing tests** (`tests/test_routes_studio_library.py`)

Mirror the `_load_routes` stub from `tests/test_routes_allowlist.py` but capture the response body/status, and drive the async handler with `asyncio.run`.

```python
# ABOUTME: Tests for the /symbiotica/studio-library route — a capturing
# ABOUTME: json_response stub + asyncio.run assert real payloads and statuses.
import asyncio
import importlib
import sys
from types import SimpleNamespace

import pytest


class _Routes:
    def get(self, path):
        def deco(fn):
            return fn
        return deco
    post = get


def _touch(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture()
def routes_mod(monkeypatch):
    captured = {}

    def json_response(body, status=200):
        captured.clear()
        captured.update(body=body, status=status)
        return SimpleNamespace(body=body, status=status)

    server = SimpleNamespace(instance=SimpleNamespace(routes=_Routes()))
    monkeypatch.setitem(sys.modules, "server", SimpleNamespace(PromptServer=server))
    from aiohttp import web
    monkeypatch.setattr(web, "json_response", json_response)
    from pipeline import routes as mod
    importlib.reload(mod)
    mod._captured = captured  # expose for assertions
    return mod


def _req(**query):
    return SimpleNamespace(query=query)


def test_no_canvas_studio_returns_503(routes_mod, monkeypatch, tmp_path):
    monkeypatch.delenv("CANVAS_STUDIO", raising=False)
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))
    asyncio.run(routes_mod.studio_library(_req()))
    assert routes_mod._captured["status"] == 503
    assert "error" in routes_mod._captured["body"]


def test_real_tree_returns_entries(routes_mod, monkeypatch, tmp_path):
    _touch(tmp_path / "studios" / "ggs" / "references" / "hero.png", b"1234")
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))
    asyncio.run(routes_mod.studio_library(_req(dir="studios/ggs/references")))
    assert routes_mod._captured["status"] == 200
    names = [e["name"] for e in routes_mod._captured["body"]["entries"]]
    assert "hero.png" in names


def test_escaping_dir_returns_400(routes_mod, monkeypatch, tmp_path):
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))
    asyncio.run(routes_mod.studio_library(_req(dir="studios/ggs/../imperia")))
    assert routes_mod._captured["status"] == 400


def test_sync_flag_spawns_and_still_lists(routes_mod, monkeypatch, tmp_path):
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))
    spawned = {"n": 0}

    class _Proc:
        async def wait(self):
            return 0
        def kill(self):
            pass

    async def _fake_exec(*a, **k):
        spawned["n"] += 1
        return _Proc()

    monkeypatch.setattr(routes_mod.asyncio, "create_subprocess_exec", _fake_exec)
    asyncio.run(routes_mod.studio_library(_req(sync="1")))
    assert spawned["n"] == 1
    assert routes_mod._captured["status"] == 200


def test_no_sync_flag_does_not_spawn(routes_mod, monkeypatch, tmp_path):
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))
    spawned = {"n": 0}

    async def _fake_exec(*a, **k):
        spawned["n"] += 1
        raise AssertionError("should not spawn")

    monkeypatch.setattr(routes_mod.asyncio, "create_subprocess_exec", _fake_exec)
    asyncio.run(routes_mod.studio_library(_req()))
    assert spawned["n"] == 0


def test_sync_timeout_still_lists_and_kills(routes_mod, monkeypatch, tmp_path):
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))
    killed = {"v": False}

    class _Proc:
        async def wait(self):
            return 0
        def kill(self):
            killed["v"] = True

    async def _fake_exec(*a, **k):
        return _Proc()

    async def _timeout(coro, timeout):
        coro.close()  # real wait_for cancels the inner awaitable on timeout
        raise asyncio.TimeoutError

    monkeypatch.setattr(routes_mod.asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(routes_mod.asyncio, "wait_for", _timeout)
    asyncio.run(routes_mod.studio_library(_req(sync="1")))
    assert killed["v"] is True
    assert routes_mod._captured["status"] == 200
```

Note: the handler does `from .studio_library import STUDIO_ASSETS_DIR, list_studio_dir` at call time, so the test overrides `routes_mod.studio_library_mod.STUDIO_ASSETS_DIR`. For that binding to exist, the route module must expose the pure module (see Step 3).

- [ ] **Step 2: Run to verify they fail**

Run: `pytest tests/test_routes_studio_library.py -q`
Expected: FAIL — `AttributeError: module 'pipeline.routes' has no attribute 'studio_library'`.

- [ ] **Step 3: Implement** (`py/pipeline/routes.py`)

Add `import asyncio` to the import block. Import the pure module at module top so tests can monkeypatch its `STUDIO_ASSETS_DIR`:

```python
from . import studio_library as studio_library_mod
```

Add the helper + handler (near the other `@PromptServer.instance.routes.get` handlers):

```python
SYNC_TIMEOUT_S = 10  # best-effort browse sync; time out and list the stale mount.


async def _sync_studio_assets(root):
    """Best-effort async publish/refresh of the studio-assets v2 mount before a
    browse-session listing. Never blocks the event loop; a stale listing is
    acceptable. Mirrors services/comfy-modal/symbiotica_platform/route.py:206-213."""
    try:
        proc = await asyncio.create_subprocess_exec("sync", root)
    except OSError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=SYNC_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()


@PromptServer.instance.routes.get("/symbiotica/studio-library")
async def studio_library(request):
    """Lazy per-level listing of the active studio's asset tree, confined to the
    studio-assets Volume root. `dir` is a volume-relative rel studios/<slug>[/...]
    (or '' for the studio root). A browse-session open (sync=1) refreshes first."""
    studio = (os.environ.get("CANVAS_STUDIO") or "").strip()
    if not studio:
        return web.json_response({"error": "studio library not available"}, status=503)
    if request.query.get("sync") == "1":
        await _sync_studio_assets(studio_library_mod.STUDIO_ASSETS_DIR)
    result = studio_library_mod.list_studio_dir(
        studio_library_mod.STUDIO_ASSETS_DIR, studio, request.query.get("dir", ""))
    return web.json_response(result, status=400 if "error" in result else 200)
```

- [ ] **Step 4: Run to verify they pass**

Run: `pytest tests/test_routes_studio_library.py -q`
Expected: PASS (6 tests).

- [ ] **Step 5: Full suite**

Run: `pytest tests/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add py/pipeline/routes.py tests/test_routes_studio_library.py
git commit -m "feat: studio-library browse route with bounded async volume sync"
```

---

### Task 6: `web/js/studio_library.js` — pure seam + overlay

**Files:**
- Create: `web/js/studio_library.js`
- Test: `tests/js/studio_library.test.mjs`

**Interfaces:**
- Consumes: `app`, `api` from `../../scripts/{app,api}.js` (aliased to `comfy_stub.mjs` in tests).
- Produces (named exports for testability): `summaryLabel(selection: string) -> string`, `applySelection(node, entryRel: string) -> void`, `filterEntries(entries, query: string) -> entries` (client-side name filter for the current pane).

- [ ] **Step 1: Write the failing tests** (`tests/js/studio_library.test.mjs`)

```javascript
// ABOUTME: Tests for studio_library.js — the pure selection seam and the
// ABOUTME: node's summary widget behavior under the comfy stub.
import { test } from "node:test";
import assert from "node:assert/strict";

import { app } from "./comfy_stub.mjs";
import "../../web/js/studio_library.js";
import { summaryLabel, applySelection, filterEntries } from "../../web/js/studio_library.js";

const tick = () => new Promise((r) => setTimeout(r, 0));

test("summaryLabel is prefix-bearing and handles empty", () => {
    assert.equal(summaryLabel(""), "no selection");
    assert.match(summaryLabel("studios/ggs/references/hero.png"), /ggs/);
    assert.equal(summaryLabel("studios/ggs/references/hero.png"), "ggs · references/hero.png");
});

test("filterEntries matches names case-insensitively, empty query passes all", () => {
    const entries = [
        { name: "references", type: "dir" },
        { name: "renders", type: "dir" },
        { name: "brief.txt", type: "file" },
    ];
    assert.deepEqual(filterEntries(entries, "ren").map((e) => e.name), ["references", "renders"]);
    assert.deepEqual(filterEntries(entries, "").map((e) => e.name), ["references", "renders", "brief.txt"]);
    assert.deepEqual(filterEntries(entries, "  ").map((e) => e.name), ["references", "renders", "brief.txt"]);
    assert.deepEqual(filterEntries(entries, "BRIEF").map((e) => e.name), ["brief.txt"]);
    assert.deepEqual(filterEntries(entries, "zzz"), []);
});

test("applySelection writes the rel into the selection widget and summary", () => {
    const node = app.create("SymbioticaStudioLibrary");
    node.onNodeCreated?.();
    applySelection(node, "studios/ggs/references/hero.png");
    const sel = node.widgets.find((w) => w.name === "selection");
    const summary = node.widgets.find((w) => w.name === "studio_summary");
    assert.equal(sel.value, "studios/ggs/references/hero.png");
    assert.match(summary.value, /ggs/);
    assert.equal(summary.serialize, false);
});

test("summary restores from a loaded workflow via onConfigure", async () => {
    const node = app.create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const sel = node.widgets.find((w) => w.name === "selection");
    sel.value = "studios/ggs/brief.txt";  // as if restored by configure()
    node.onConfigure?.();
    await tick();
    const summary = node.widgets.find((w) => w.name === "studio_summary");
    assert.match(summary.value, /brief\.txt/);
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `node --import ./tests/js/register_hooks.mjs --test 'tests/js/studio_library.test.mjs'`
Expected: FAIL — cannot find `../../web/js/studio_library.js`.

- [ ] **Step 3: Implement** (`web/js/studio_library.js`)

Modeled on `files_read.js` (fetchJson at :17-21, chained onNodeCreated at :394, summary `serialize:false`) and `order_pipeline.js:729-733` (onConfigure chaining).

```javascript
// ABOUTME: Single-select studio asset library browser — a lazy per-level overlay
// ABOUTME: that writes a volume-relative pick into the node's selection widget.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const ROUTE = "/symbiotica/studio-library";

export function summaryLabel(selection) {
    const rel = String(selection || "");
    const m = rel.match(/^studios\/([^/]+)\/(.+)$/);
    if (m) return `${m[1]} · ${m[2]}`;
    const root = rel.match(/^studios\/([^/]+)\/?$/);
    if (root) return `${root[1]} · (studio root)`;
    return "no selection";
}

export function filterEntries(entries, query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((e) => e.name.toLowerCase().includes(q));
}

export function applySelection(node, entryRel) {
    const sel = node.widgets?.find((w) => w.name === "selection");
    if (sel) sel.value = entryRel;
    const summary = node.widgets?.find((w) => w.name === "studio_summary");
    if (summary) summary.value = summaryLabel(entryRel);
    node.setDirtyCanvas?.(true, true);
}

async function fetchJson(url) {
    const res = await api.fetchApi(url);
    if (!res.ok) throw new Error((await res.json())?.error ?? res.statusText);
    return res.json();
}

function refreshSummary(node) {
    const sel = node.widgets?.find((w) => w.name === "selection");
    const summary = node.widgets?.find((w) => w.name === "studio_summary");
    if (summary) summary.value = summaryLabel(sel?.value ?? "");
}

function openBrowser(node) {
    // Fullscreen overlay: breadcrumb + a client-side name filter + a single lazy
    // tree pane. Folders expand by fetching ROUTE?dir=<rel>; the first open passes
    // sync=1. Clicking a row's select control calls applySelection(node, entry.rel)
    // and closes. A non-ok fetch throws in fetchJson and renders inline; an empty
    // listing shows a distinct empty state. The filter narrows the CURRENT pane by
    // name (it does not search into unopened folders).
    const overlay = document.createElement("div");
    overlay.className = "symbiotica-studio-library";
    const crumb = document.createElement("div");
    const filter = document.createElement("input");
    filter.type = "search";
    filter.placeholder = "🔎 filter this folder…";
    const errline = document.createElement("div");
    const pane = document.createElement("div");
    overlay.appendChild(crumb);
    overlay.appendChild(filter);
    overlay.appendChild(errline);
    overlay.appendChild(pane);
    document.body.appendChild(overlay);

    let firstOpen = true;
    let currentEntries = [];
    const close = () => overlay.remove();

    function renderRows() {
        pane.replaceChildren();
        if (currentEntries.length === 0) {
            pane.textContent = "No files in this studio library yet";
            return;
        }
        const shown = filterEntries(currentEntries, filter.value);
        if (shown.length === 0) {
            pane.textContent = "No matches";
            return;
        }
        for (const entry of shown) {
            const row = document.createElement("div");
            row.textContent = (entry.type === "dir" ? "📁 " : "📄 ") + entry.name;
            const pick = document.createElement("button");
            pick.textContent = "select";
            pick.addEventListener("click", () => { applySelection(node, entry.rel); close(); });
            if (entry.type === "dir") {
                const expand = document.createElement("button");
                expand.textContent = "open";
                expand.addEventListener("click", () => show(entry.rel));
                row.appendChild(expand);
            }
            row.appendChild(pick);
            pane.appendChild(row);
        }
    }

    filter.addEventListener("input", renderRows);

    async function show(dir) {
        errline.textContent = "";
        let data;
        try {
            const q = new URLSearchParams({ dir });
            if (firstOpen) q.set("sync", "1");
            firstOpen = false;
            data = await fetchJson(`${ROUTE}?${q.toString()}`);
        } catch (e) {
            errline.textContent = e.message || "studio library unavailable";
            return;
        }
        crumb.textContent = data.rel || "studios";
        currentEntries = data.entries || [];
        filter.value = "";
        renderRows();
    }
    show("");
}

app.registerExtension({
    name: "symbiotica.studio_library",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SymbioticaStudioLibrary") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            this.addWidget("button", "📂 Browse studio library", null, () => openBrowser(this));
            const summary = this.addWidget("text", "studio_summary", "", () => {});
            summary.disabled = true;
            summary.serialize = false;
            refreshSummary(this);
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            onConfigure?.apply(this, arguments);
            queueMicrotask(() => refreshSummary(this));
        };
    },
});
```

- [ ] **Step 4: Run to verify they pass**

Run: `node --import ./tests/js/register_hooks.mjs --test 'tests/js/studio_library.test.mjs'`
Expected: PASS (3 tests).

- [ ] **Step 5: Syntax + full JS suite**

Run: `node --check web/js/studio_library.js && node --import ./tests/js/register_hooks.mjs --test 'tests/js/*.test.mjs'`
Expected: `web/js/studio_library.js` parses; all JS tests pass.

- [ ] **Step 6: Commit**

```bash
git add web/js/studio_library.js tests/js/studio_library.test.mjs
git commit -m "feat: single-select studio library browser overlay"
```

---

### Task 7: Release deliverables (README + CHANGELOG)

**Files:**
- Modify: `README.md` (Order pipeline section)
- Modify: `CHANGELOG.md` (Added entry under the next unreleased heading)

**Interfaces:** none (documentation).

> Version bump + registry publish are DEFERRED to the release step (not this PR) — `main` is at `2026.7.6` with parallel release PRs in flight; bumping here risks a publish collision.

- [ ] **Step 1: Add the README bullet.** In `README.md`, under `## Order pipeline (Symbiotica Hub port)`, add:

```markdown
- **Symbiotica Studio Library** — pick a file or folder from the active studio's asset library; outputs its absolute sandbox path and whether it is a folder.
```

- [ ] **Step 2: Add the CHANGELOG entry.** In `CHANGELOG.md`, add a new top entry for the next unreleased version with:

```markdown
## Unreleased

### Added
- **Symbiotica Studio Library** — a single-select browser for the active studio's non-model asset tree (reference images, arbitrary files, folder paths), emitting an absolute sandbox path + `is_dir` for downstream path-consuming nodes. Model kinds stay hidden (already native via `/comfy-models`).
```

- [ ] **Step 3: Verify docs render / no broken markdown**

Run: `node --check /dev/stdin <<<'0' 2>/dev/null; rg -n "Symbiotica Studio Library" README.md CHANGELOG.md`
Expected: both files show the new lines.

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: list Symbiotica Studio Library in README and CHANGELOG"
```

---

### Task 8 (stretch, if cheap): node-class assertion via a `comfy_api` stub

**Files:**
- Create: `tests/comfy_api_stub.py` (a minimal `comfy_api.latest` fake — `io.ComfyNode`, `io.Schema`, `io.String`, `io.Boolean`, `io.NodeOutput`)
- Create: `tests/test_nodes_studio_library.py`

**Interfaces:**
- Produces: a test that imports `pipeline.nodes` with the stub injected and asserts `SymbioticaStudioLibrary.define_schema()` + `execute()`.

> Optional: the load-bearing CANVAS_STUDIO-invariance is already pinned at the pure-function level (Task 2). This adds a check on the node face itself (two outputs, the `selection` input, `execute()` ignoring `CANVAS_STUDIO`). Only build it if the stub stays ~30 lines; do NOT weaken `tests/test_shim.py` (which must keep asserting `pipeline.nodes` raises `ImportError` with no stub present).

- [ ] **Step 1: Write the failing test** (`tests/test_nodes_studio_library.py`)

```python
# ABOUTME: Node-face test for SymbioticaStudioLibrary — injects a comfy_api stub
# ABOUTME: so define_schema/execute run outside a live ComfyUI.
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))
import comfy_api_stub  # noqa: F401  (registers comfy_api.latest in sys.modules)


@pytest.fixture()
def NodeCls():
    import importlib
    from pipeline import nodes
    importlib.reload(nodes)
    return nodes.SymbioticaStudioLibrary


def _vol(tmp_path):
    d = tmp_path / "studios" / "ggs" / "references"
    d.mkdir(parents=True)
    (d / "hero.png").write_bytes(b"1234")
    return tmp_path


def test_schema_outputs_and_input(NodeCls):
    schema = NodeCls.define_schema()
    assert schema.node_id == "SymbioticaStudioLibrary"
    assert [o.display_name for o in schema.outputs] == ["path", "is_dir"]
    assert schema.inputs[0].id == "selection"


def test_execute_ignores_canvas_studio(NodeCls, tmp_path, monkeypatch):
    vol = _vol(tmp_path)
    from pipeline import studio_library
    monkeypatch.setattr(studio_library, "STUDIO_ASSETS_DIR", str(vol))
    monkeypatch.setenv("CANVAS_STUDIO", "imperia")
    out = NodeCls.execute(selection="studios/ggs/references/hero.png")
    monkeypatch.delenv("CANVAS_STUDIO", raising=False)
    out2 = NodeCls.execute(selection="studios/ggs/references/hero.png")
    assert out.args[0] == out2.args[0] == os.path.realpath(str(vol / "studios/ggs/references/hero.png"))
    assert out.args[1] is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_nodes_studio_library.py -q`
Expected: FAIL — no `comfy_api_stub`.

- [ ] **Step 3: Write the stub** (`tests/comfy_api_stub.py`)

```python
# ABOUTME: Minimal comfy_api.latest fake so pipeline.nodes imports in pytest —
# ABOUTME: enough of the io namespace to run define_schema/execute for tests.
import sys
import types


class _Input:
    def __init__(self, id, **kw):
        self.id = id
        self.__dict__.update(kw)


class _Output:
    def __init__(self, display_name=None, **kw):
        self.display_name = display_name
        self.__dict__.update(kw)


class _IOType:
    Input = staticmethod(lambda id, **kw: _Input(id, **kw))
    Output = staticmethod(lambda **kw: _Output(**kw))


class Schema:
    def __init__(self, node_id=None, display_name=None, category=None,
                 description=None, inputs=None, outputs=None, **kw):
        self.node_id = node_id
        self.display_name = display_name
        self.category = category
        self.description = description
        self.inputs = inputs or []
        self.outputs = outputs or []


class ComfyNode:
    @classmethod
    def GET_SCHEMA(cls):
        return cls.define_schema()


class NodeOutput:
    def __init__(self, *args):
        self.args = args


io = types.SimpleNamespace(
    ComfyNode=ComfyNode, Schema=Schema, NodeOutput=NodeOutput,
    String=_IOType, Boolean=_IOType, Combo=_IOType,
    Custom=lambda name: _IOType,
)
ui = types.SimpleNamespace(PreviewText=object, PreviewImage=object)

_latest = types.ModuleType("comfy_api.latest")
_latest.io = io
_latest.ui = ui
_pkg = types.ModuleType("comfy_api")
_pkg.latest = _latest
sys.modules.setdefault("comfy_api", _pkg)
sys.modules.setdefault("comfy_api.latest", _latest)
```

> If `pipeline.nodes` needs additional stubs (e.g. `folder_paths`, `server`) to import, add the minimal shim per the session narrative's proven experiment (a ~5-line `folder_paths` returning `/tmp`, a `server.PromptServer` SimpleNamespace). If the stub balloons past ~40 lines total, STOP and leave this task undone — the pure-function invariance test already covers the load-bearing behavior.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_nodes_studio_library.py -q`
Expected: PASS. If it needs > ~40 lines of shims, abandon this task (see note) and `git checkout tests/comfy_api_stub.py tests/test_nodes_studio_library.py`.

- [ ] **Step 5: Confirm the shim test is unaffected**

Run: `pytest tests/test_shim.py -q`
Expected: PASS — `pipeline.nodes` still raises `ImportError` when the stub is not imported (the stub only lives in its own test module's process import).

- [ ] **Step 6: Commit**

```bash
git add tests/comfy_api_stub.py tests/test_nodes_studio_library.py
git commit -m "test: assert StudioLibrary node schema and env-free execute via comfy stub"
```

---

## Final verification (after all tasks)

- [ ] Run the full combined gate:

```bash
pytest tests/ && { [ -d tests/js ] || exit 0; node --import ./tests/js/register_hooks.mjs --test 'tests/js/*.test.mjs'; }
```
Expected: all Python + JS tests pass, exit 0.

- [ ] Copy the plan + spec are committed under `docs/superpowers/`.
- [ ] Open a PR against `symbiotica-ai/comfyui-nodes` from `feat/studio-library-node` (see the spec's Rollout + Release deliverables — no version bump in this PR).

## Self-Review coverage map (spec → task)

- Confinement resolver / one-namespace / slug / base-guard → Task 1.
- is_dir + fingerprint (folder direntry-set limitation) + CANVAS_STUDIO invariance → Task 2.
- Never-raising lister / MODEL_KINDS-at-root / round-trip / symlink typing / empty-studio → Task 3.
- V3 node + registration + shim import → Task 4.
- Route + real statuses (503/400/200) + async bounded sync + sync tests → Task 5.
- JS overlay + pure seam + prefix summary + onConfigure restore + empty/error states → Task 6.
- README + CHANGELOG (version bump deferred) → Task 7.
- Node-face assertion (stretch) → Task 8.
