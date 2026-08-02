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
        "sheets", "sheet_prompts", "sheet_names", "categories",
        "sheet_categories"]
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


def test_execute_names_each_type_once(nodes_mod, tmp_path):
    # Two types, one sheet each: the 4th output names the types, in the order
    # they appear in the order sheet — as written there, not the slug.
    assets = [_asset("Ghost Bakery Queue", "Decoration", ["d0.png"],
                     canvas="512x512", rotation="2"),
              _asset("Ghostly Jelly Cake", "Food - 3 stages",
                     ["s0.png", "s1.png", "s2.png"])]
    out = nodes_mod.SymbioticaAutoPacker.execute(
        order=_order(tmp_path, assets), category="All")
    sheets, prompts, names, categories, _per_sheet = out.args
    assert categories == ["Decoration", "Food - 3 stages"]
    assert len(sheets) == len(prompts) == len(names) == 2
    # (no canvas suffix: neither category spans more than one canvas size)
    assert names == ["mini-1-decoration", "mini-1-food-3-stages"]


def test_execute_names_a_paginated_type_once_not_per_page(nodes_mod, tmp_path):
    # One asset per sheet (columns=1 x max_rows=1) — his food setup. Three
    # sheets, but one type: the list must NOT repeat it three times.
    assets = [_asset(n, "Food - 3 stages", ["s0.png", "s1.png", "s2.png"])
              for n in ("Spookies", "Spooky Stack Popsicle",
                        "Ghostly Jelly Cake")]
    out = nodes_mod.SymbioticaAutoPacker.execute(
        order=_order(tmp_path, assets), category="Food - 3 stages",
        preset={"model": "qwen-image", "tier": "1K", "ar": "1:1",
                "columns": 1, "max_rows": 1})
    sheets, _prompts, names, categories, _per_sheet = out.args
    assert len(sheets) == 3
    assert categories == ["Food - 3 stages"]
    assert names == ["mini-1-food-3-stages-1", "mini-1-food-3-stages-2",
                     "mini-1-food-3-stages-3"]


def test_execute_names_a_type_once_across_many_sheets(nodes_mod, tmp_path):
    # His actual graph: 3 decorations (2 refs each, rotation 2) + 3 food, all
    # on one sheet per item. Twelve sheets, two types — two entries.
    deco = [_asset(n, "Decoration", ["d0.png", "d1.png"], canvas="512x512",
                   rotation="2")
            for n in ("Phantom Freezer Cart", "Ghost Bakery Queue",
                      "Witch Cat Tea Parlor")]
    food = [_asset(n, "Food - 3 stages", ["s0.png", "s1.png", "s2.png"])
            for n in ("Spookies", "Spooky Stack Popsicle",
                      "Ghostly Jelly Cake")]
    out = nodes_mod.SymbioticaAutoPacker.execute(
        order=_order(tmp_path, deco + food), category="All",
        preset={"model": "qwen-image", "tier": "1K", "ar": "1:1",
                "columns": 1, "max_rows": 1})
    sheets, _prompts, _names, categories, _per_sheet = out.args
    assert len(sheets) > 2                      # many sheets…
    assert categories == ["Decoration", "Food - 3 stages"]   # …two types


def test_execute_emits_both_category_lists(nodes_mod, tmp_path):
    # The deduped list labels the pack; the per-sheet list is what pairs with
    # sheets when it drives the Category Prompts node.
    assets = [_asset(n, "Food - 3 stages", ["s0.png", "s1.png", "s2.png"])
              for n in ("Spookies", "Spooky Stack Popsicle",
                        "Ghostly Jelly Cake")]
    out = nodes_mod.SymbioticaAutoPacker.execute(
        order=_order(tmp_path, assets), category="Food - 3 stages",
        preset={"model": "qwen-image", "tier": "1K", "ar": "1:1",
                "columns": 1, "max_rows": 1})
    sheets, _prompts, _names, categories, sheet_categories = out.args
    assert categories == ["Food - 3 stages"]                # one per type
    assert sheet_categories == ["Food - 3 stages"] * 3      # one per sheet
    assert len(sheet_categories) == len(sheets)
