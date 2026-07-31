# ABOUTME: Tests the Refs Folder node end to end against stubbed ComfyUI modules
# ABOUTME: — it must be registered, run headless, and vouch for nothing.
import importlib
import os
import sys
import types

import pytest
from PIL import Image


@pytest.fixture
def nodes(monkeypatch):
    """py/pipeline/nodes.py with ComfyUI's runtime modules stubbed. CI ships
    minimal deps, so these are never imported for real."""
    sys.path.insert(0, os.path.dirname(__file__))
    from comfy_api_stub import build_modules
    pkg, latest = build_modules()
    monkeypatch.setitem(sys.modules, "comfy_api", pkg)
    monkeypatch.setitem(sys.modules, "comfy_api.latest", latest)
    monkeypatch.setitem(sys.modules, "folder_paths",
                        types.ModuleType("folder_paths"))
    sys.modules.pop("pipeline.nodes", None)
    import pipeline.nodes as mod
    importlib.reload(mod)
    return mod


@pytest.fixture
def refs(tmp_path):
    d = tmp_path / "refs"
    d.mkdir()
    for i, name in enumerate(("b.png", "a.png", "c.png")):
        Image.new("RGB", (4 + i, 6), (i, 0, 0)).save(d / name)
    return d


def test_the_node_is_registered(nodes):
    # __init__.py imports each module under a try/except, so a node that fails
    # to build is dropped with no error anyone sees.
    assert nodes.SymbioticaRefsFolder in nodes.PIPELINE_NODE_CLASSES


def test_it_loads_a_folder_with_no_selection_at_all(nodes, refs):
    out = nodes.SymbioticaRefsFolder.execute(refs_dir=str(refs))
    images, filenames, count = out.args if hasattr(out, "args") else out
    assert filenames == ["a.png", "b.png", "c.png"]
    assert count == 3
    # Filename order is image order: 'a.png' was written 5px wide, 'b.png' 4px.
    assert [tuple(im.shape[1:3]) for im in images] == [(6, 5), (6, 4), (6, 6)]


def test_the_cap_limits_what_comes_back(nodes, refs):
    out = nodes.SymbioticaRefsFolder.execute(refs_dir=str(refs), max_count=2)
    _, filenames, count = out.args if hasattr(out, "args") else out
    assert filenames == ["a.png", "b.png"]
    assert count == 2


def test_a_missing_folder_raises_against_this_node(nodes, tmp_path):
    with pytest.raises(ValueError, match="not-there"):
        nodes.SymbioticaRefsFolder.execute(refs_dir=str(tmp_path / "not-there"))


def test_it_vouches_for_no_project(nodes, refs, monkeypatch):
    """Registering would widen what the Template Library and image routes may
    read. This node returns pixels over the wire and serves nothing, so binding
    a folder to it must not grant that folder any browsing rights."""
    vouched = []
    monkeypatch.setattr(nodes, "_register_project", lambda p: vouched.append(p))
    monkeypatch.setattr(nodes, "_register_refs_root",
                        lambda p: vouched.append(p))
    nodes.SymbioticaRefsFolder.execute(refs_dir=str(refs))
    assert vouched == []


def test_the_fingerprint_moves_when_the_folder_changes(nodes, refs):
    before = nodes.SymbioticaRefsFolder.fingerprint_inputs(refs_dir=str(refs))
    Image.new("RGB", (4, 4)).save(refs / "d.png")
    after = nodes.SymbioticaRefsFolder.fingerprint_inputs(refs_dir=str(refs))
    assert before != after
