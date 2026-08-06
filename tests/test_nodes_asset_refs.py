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


def make_transparent_order(tmp_path):
    """A reference shaped like the real ones: bright pixels hidden under alpha 0
    and a part-transparent edge, which is what made assets glow."""
    refs = tmp_path / "refs"
    refs.mkdir()
    im = Image.new("RGBA", (4, 4), (255, 0, 0, 0))       # hidden red backdrop
    im.putpixel((1, 1), (255, 255, 255, 128))            # soft edge
    im.putpixel((2, 2), (10, 20, 30, 255))               # actual art
    im.save(refs / "Spookies.png")
    return {
        "assets": [{"assetName": "Spookies", "category": "Food - 3 stages",
                    "refFiles": ["Spookies.png"]}],
        "refsRoot": str(refs), "project_path": str(tmp_path / "project"),
    }


def test_flattens_onto_the_background_by_default(nodes_mod, tmp_path):
    images, _names, _masks, _folder = nodes_mod.SymbioticaAssetRefs.execute(
        order=make_transparent_order(tmp_path), asset_name="Spookies",
        background="#808080").args
    px = images[0][0]
    assert [round(float(v) * 255) for v in px[0][0]] == [128, 128, 128]
    assert [round(float(v) * 255) for v in px[2][2]] == [10, 20, 30]


def test_background_is_selectable(nodes_mod, tmp_path):
    images, _n, _m, _f = nodes_mod.SymbioticaAssetRefs.execute(
        order=make_transparent_order(tmp_path), asset_name="Spookies",
        background="#ff0000").args
    assert [round(float(v) * 255) for v in images[0][0][0][0]] == [255, 0, 0]


def test_keeping_transparency_leaves_the_pixels_and_gives_the_alpha(nodes_mod,
                                                                    tmp_path):
    images, _n, masks, _f = nodes_mod.SymbioticaAssetRefs.execute(
        order=make_transparent_order(tmp_path), asset_name="Spookies",
        keep_transparency=True).args
    # Un-composited, so the hidden backdrop is still there — usable only with
    # the mask, which is exactly why the mask comes with it.
    assert [round(float(v) * 255) for v in images[0][0][0][0]] == [255, 0, 0]
    assert round(float(masks[0][0][0][0]) * 255) == 0
    assert round(float(masks[0][0][2][2]) * 255) == 255


def test_masks_come_out_opaque_for_a_reference_with_no_alpha(nodes_mod,
                                                             tmp_path):
    _i, _n, masks, _f = nodes_mod.SymbioticaAssetRefs.execute(
        order=make_order(tmp_path), asset_name="Spookies").args
    assert all(float(m.min()) == 1.0 for m in masks)


def test_returns_one_image_per_reference_in_order(nodes_mod, tmp_path):
    out = nodes_mod.SymbioticaAssetRefs.execute(
        order=make_order(tmp_path), asset_name="Spookies")
    images, names, _masks, _folder = out.args
    assert names == ["Spookies.png", "Spookies_1.png", "Spookies_2.png"]
    # Sizes prove each slot holds ITS OWN file rather than the same one thrice.
    assert [tuple(i.shape[1:3]) for i in images] == [(16, 16), (24, 24),
                                                     (32, 32)]


def test_unwired_asset_name_reads_a_focused_orders_one_asset(nodes_mod,
                                                             tmp_path):
    """Asset Focus's `order` output names one asset, so the asset_name wire
    becomes redundant on that lane: one wire instead of two."""
    out = nodes_mod.SymbioticaAssetRefs.execute(order=make_order(tmp_path))
    _images, names, _masks, _folder = out.args
    assert names == ["Spookies.png", "Spookies_1.png", "Spookies_2.png"]


def test_unwired_asset_name_refuses_a_whole_event(nodes_mod, tmp_path):
    """Guessing one asset out of several would pair the wrong art in
    silence; the error names the wire that fixes it."""
    order = make_order(tmp_path)
    order["assets"].append({"assetName": "Other",
                            "category": "Decoration", "refFiles": []})
    with pytest.raises(ValueError, match="Asset Focus"):
        nodes_mod.SymbioticaAssetRefs.execute(order=order)


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


def test_output_size_resizes_the_image_and_its_mask_together(nodes_mod,
                                                             tmp_path):
    # A full-size cutout against a shrunk picture would not line up in any
    # downstream composite, so the mask has to follow the image.
    images, _n, masks, _f = nodes_mod.SymbioticaAssetRefs.execute(
        order=make_transparent_order(tmp_path), asset_name="Spookies",
        output_size="512").args
    assert tuple(images[0].shape) == (1, 512, 512, 3)
    assert tuple(masks[0].shape) == (1, 512, 512)


def test_native_leaves_every_reference_at_its_own_size(nodes_mod, tmp_path):
    images, _n, _m, _f = nodes_mod.SymbioticaAssetRefs.execute(
        order=make_order(tmp_path), asset_name="Spookies",
        output_size="native").args
    assert [tuple(i.shape[1:3]) for i in images] == [(16, 16), (24, 24),
                                                     (32, 32)]


def test_output_size_offers_the_sizes_worth_sending(nodes_mod):
    schema = nodes_mod.SymbioticaAssetRefs.define_schema()
    opts = next(i for i in schema.inputs if i.id == "output_size").options
    assert opts == ["native", "512", "1024"]


def test_outputs_are_lists_so_the_lane_fans_out(nodes_mod):
    schema = nodes_mod.SymbioticaAssetRefs.define_schema()
    assert [o.display_name for o in schema.outputs] == ["images", "names",
                                                        "masks", "save_path"]
    # The three that fan out are per-reference; `save_path` is the one place
    # they were all read from, so it is deliberately NOT a list — a picker
    # takes a directory, not one directory per file.
    # getattr, not attribute access: the stub keeps only the kwargs an output
    # passes, and `save_path` never mentions `is_output_list` at all.
    assert all(o.is_output_list for o in schema.outputs[:3])
    assert not getattr(schema.outputs[3], "is_output_list", False)
    # Widgets are APPENDED — ComfyUI restores widgets_values positionally, so a
    # new one in the middle loads a saved pick onto the wrong widget.
    assert [i.id for i in schema.inputs] == ["order", "asset_name",
                                             "background", "keep_transparency",
                                             "output_size"]


def test_folder_output_is_the_orders_references_root(nodes_mod, tmp_path):
    order = make_order(tmp_path)
    _i, _n, _m, folder = nodes_mod.SymbioticaAssetRefs.execute(
        order=order, asset_name="Spookies").args
    # A Pick node lists a DIRECTORY, so this is the folder the references were
    # read from, not the files themselves.
    assert folder == order["refsRoot"]
