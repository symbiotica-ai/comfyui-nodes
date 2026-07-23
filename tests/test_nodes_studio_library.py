# ABOUTME: Node-face test for SymbioticaStudioLibrary — installs a comfy_api
# ABOUTME: stub via monkeypatch so define_schema/execute run outside ComfyUI.
import importlib
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from comfy_api_stub import build_modules


@pytest.fixture()
def NodeCls(monkeypatch):
    # sys.modules.pop (not monkeypatch.delitem) for pipeline.nodes: a
    # monkeypatch-tracked delitem here would itself be undone by monkeypatch's
    # own end-of-test revert, restoring the fully-loaded, stub-wired module
    # back into sys.modules — leaking it into test_shim's ImportError check.
    pkg, latest = build_modules()
    monkeypatch.setitem(sys.modules, "comfy_api", pkg)
    monkeypatch.setitem(sys.modules, "comfy_api.latest", latest)
    monkeypatch.setitem(sys.modules, "folder_paths",
                        types.ModuleType("folder_paths"))
    sys.modules.pop("pipeline.nodes", None)
    import pipeline.nodes as nodes
    importlib.reload(nodes)
    yield nodes.SymbioticaStudioLibrary
    sys.modules.pop("pipeline.nodes", None)


def _vol(tmp_path):
    d = tmp_path / "studios" / "ggs" / "references"
    d.mkdir(parents=True)
    (d / "hero.png").write_bytes(b"1234")
    return tmp_path


def test_schema_outputs_and_input(NodeCls):
    schema = NodeCls.define_schema()
    assert schema.node_id == "SymbioticaStudioLibrary"
    assert schema.category == "symbiotica/pipeline"
    assert [o.display_name for o in schema.outputs] == ["path", "is_dir"]
    assert len(schema.inputs) == 1
    assert schema.inputs[0].id == "selection"


def test_execute_ignores_canvas_studio(NodeCls, tmp_path, monkeypatch):
    vol = _vol(tmp_path)
    from pipeline import studio_library
    monkeypatch.setattr(studio_library, "STUDIO_ASSETS_DIR", str(vol))
    monkeypatch.setenv("CANVAS_STUDIO", "imperia")
    out = NodeCls.execute(selection="studios/ggs/references/hero.png")
    monkeypatch.delenv("CANVAS_STUDIO", raising=False)
    out2 = NodeCls.execute(selection="studios/ggs/references/hero.png")
    want = os.path.realpath(str(vol / "studios/ggs/references/hero.png"))
    assert out.args[0] == out2.args[0] == want
    assert out.args[1] is False
