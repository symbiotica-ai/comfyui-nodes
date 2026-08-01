# ABOUTME: Node-face tests for the Auto Packer's output slots — their ORDER
# ABOUTME: (links address a slot by index) and the per-sheet category export.
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
    """pipeline.nodes with ComfyUI stubbed out, and output/ pointed at tmp."""
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


def test_output_slots_keep_their_order(nodes_mod):
    # A saved workflow's links point at an output by SLOT INDEX, so a new slot
    # may only be APPENDED. Pin the order: inserting one re-points every wire.
    schema = nodes_mod.SymbioticaAutoPacker.define_schema()
    assert [o.display_name for o in schema.outputs] == [
        "sheets", "sheet_prompts", "sheet_names", "sheet_categories"]
    assert all(getattr(o, "is_output_list", False) for o in schema.outputs)


def _order(tmp_path, assets):
    """An order whose refs exist on disk, laid out the way the packer reads
    them: <refsRoot>/<category>/<assetName>/<ref>."""
    root = tmp_path / "refs"
    for a in assets:
        d = root / a["category"] / a["assetName"]
        d.mkdir(parents=True, exist_ok=True)
        for f in a["refFiles"]:
            Image.new("RGBA", (32, 32), (200, 60, 60, 255)).save(d / f)
    return {"feature": "Mini 1", "eventName": "Mini 1", "assets": assets,
            "refsRoot": str(root)}


def _asset(name, category, refs, canvas="128x128", rotation="-"):
    return {"assetName": name, "category": category, "canvas": canvas,
            "rotation": rotation, "prompt": "p", "refFiles": list(refs)}


def test_execute_exports_a_category_per_sheet(nodes_mod, tmp_path):
    # Two types, one sheet each: the 4th output names the type of sheet i, in
    # the order it appears in the order sheet — not the slug.
    assets = [_asset("Ghost Bakery Queue", "Decoration", ["d0.png"],
                     canvas="512x512", rotation="2"),
              _asset("Ghostly Jelly Cake", "Food - 3 stages",
                     ["s0.png", "s1.png", "s2.png"])]
    out = nodes_mod.SymbioticaAutoPacker.execute(
        order=_order(tmp_path, assets), category="All")
    sheets, prompts, names, categories = out.args
    assert categories == ["Decoration", "Food - 3 stages"]
    # index-aligned with every other output
    assert len(sheets) == len(prompts) == len(names) == len(categories) == 2
    # (no canvas suffix: neither category spans more than one canvas size)
    assert names == ["mini-1-decoration", "mini-1-food-3-stages"]


def test_execute_repeats_the_category_across_pages(nodes_mod, tmp_path):
    # One asset per sheet (columns=1 x max_rows=1) — his food setup. Each page
    # still carries the type, so the list stays aligned with sheets.
    assets = [_asset(n, "Food - 3 stages", ["s0.png", "s1.png", "s2.png"])
              for n in ("Spookies", "Spooky Stack Popsicle",
                        "Ghostly Jelly Cake")]
    out = nodes_mod.SymbioticaAutoPacker.execute(
        order=_order(tmp_path, assets), category="Food - 3 stages",
        preset={"model": "qwen-image", "tier": "1K", "ar": "1:1",
                "columns": 1, "max_rows": 1})
    sheets, _prompts, names, categories = out.args
    assert len(sheets) == 3
    assert categories == ["Food - 3 stages"] * 3
    assert names == ["mini-1-food-3-stages-1", "mini-1-food-3-stages-2",
                     "mini-1-food-3-stages-3"]
