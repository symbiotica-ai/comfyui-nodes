# ABOUTME: Node-face tests for the client-reference lookup — image order,
# ABOUTME: the pairing note shown on canvas, and the refusals.
import importlib
import os
import sys
import types

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from comfy_api_stub import build_modules


@pytest.fixture()
def nodes_mod(monkeypatch, tmp_path):
    pkg, latest = build_modules()
    monkeypatch.setitem(sys.modules, "comfy_api", pkg)
    monkeypatch.setitem(sys.modules, "comfy_api.latest", latest)
    fp = types.ModuleType("folder_paths")
    out = tmp_path / "output"
    out.mkdir()
    fp.get_output_directory = lambda: str(out)
    monkeypatch.setitem(sys.modules, "folder_paths", fp)
    sys.modules.pop("pipeline.nodes", None)
    import pipeline.nodes as nodes
    importlib.reload(nodes)
    yield nodes
    sys.modules.pop("pipeline.nodes", None)


def make_order(tmp_path, sizes=((16, 16), (24, 24), (32, 32))):
    refs = tmp_path / "refs"
    refs.mkdir()
    names = ["Spookies.png", "Spookies_1.png", "Spookies_2.png"][:len(sizes)]
    for name, size in zip(names, sizes):
        Image.new("RGB", size, (10, 20, 30)).save(refs / name)
    return {
        "assets": [{"assetName": "Spookies", "category": "Food - 3 stages",
                    "refFiles": names}],
        "refsRoot": str(refs),
        "project_path": str(tmp_path / "project"),
    }


def test_returns_one_image_per_reference_in_order(nodes_mod, tmp_path):
    out = nodes_mod.SymbioticaAssetRefs.execute(
        order=make_order(tmp_path), asset_name="Spookies")
    images, names = out.args
    assert names == ["Spookies.png", "Spookies_1.png", "Spookies_2.png"]
    # Sizes prove each slot holds ITS OWN file rather than the same one thrice.
    assert [tuple(i.shape[1:3]) for i in images] == [(16, 16), (24, 24),
                                                     (32, 32)]


def test_canvas_note_warns_when_refs_do_not_match_the_cells(nodes_mod,
                                                            tmp_path):
    # Two references against a three-cell type: an index picks unrelated things
    # on each side, and that is invisible once the images are on the wire.
    order = make_order(tmp_path, sizes=((16, 16), (24, 24)))
    out = nodes_mod.SymbioticaAssetRefs.execute(order=order,
                                                asset_name="Spookies")
    assert "do NOT line up" in out.ui.value


def test_an_unknown_asset_lists_what_the_order_holds(nodes_mod, tmp_path):
    with pytest.raises(Exception, match="Spookies"):
        nodes_mod.SymbioticaAssetRefs.execute(
            order=make_order(tmp_path), asset_name="Nope")


def test_a_missing_order_names_the_wire_to_fix(nodes_mod):
    with pytest.raises(Exception, match="Order Specs"):
        nodes_mod.SymbioticaAssetRefs.execute(order=None, asset_name="x")


def test_outputs_are_lists_so_the_lane_fans_out(nodes_mod):
    schema = nodes_mod.SymbioticaAssetRefs.define_schema()
    assert [o.display_name for o in schema.outputs] == ["images", "ref_names"]
    assert all(o.is_output_list for o in schema.outputs)
    assert [i.id for i in schema.inputs] == ["order", "asset_name"]
