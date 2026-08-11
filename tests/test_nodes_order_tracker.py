# ABOUTME: Order Tracker — one slot per asset the order asks for, filled by
# ABOUTME: whatever the `names` tag lists in that asset's own folder.
import importlib
import os
import sys
import types

import pytest

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
    nodes._TEST_OUTPUT = str(out)
    yield nodes
    sys.modules.pop("pipeline.nodes", None)


ORDER = {
    "feature": "Mini 3",
    "month": "October",
    "assets": [
        {"assetName": "Bat Brew", "category": "Decoration", "prompt": ""},
        {"assetName": "Bat Bookshelf", "category": "Decoration", "prompt": ""},
        {"assetName": "Spookies", "category": "Food - 3 stages", "prompt": ""},
    ],
}


def folder_for(nodes, asset, category):
    return os.path.join(nodes._TEST_OUTPUT, "October", "Mini 3", category, asset)


def render(folder, *names):
    from PIL import Image
    os.makedirs(folder, exist_ok=True)
    for name in names:
        Image.new("RGB", (4, 4)).save(os.path.join(folder, name))


def pushed(nodes, monkeypatch, **kw):
    seen = []
    monkeypatch.setattr(nodes, "_push",
                        lambda event, detail: seen.append((event, detail)))
    nodes.SymbioticaOrderTracker.hidden = types.SimpleNamespace(unique_id="7")
    nodes.SymbioticaOrderTracker.execute(**kw)
    return next(d for e, d in seen if e == "symbiotica.tracker")


class TestTheBoard:
    def test_a_slot_per_asset_the_order_asks_for(self, nodes_mod, monkeypatch):
        board = pushed(nodes_mod, monkeypatch, order=ORDER)
        assert [s["asset"] for s in board["slots"]] == [
            "Bat Brew", "Bat Bookshelf", "Spookies"]
        assert board["total"] == 3

    def test_an_empty_slot_is_work_left(self, nodes_mod, monkeypatch):
        board = pushed(nodes_mod, monkeypatch, order=ORDER)
        assert [s["image"] for s in board["slots"]] == [None, None, None]
        assert board["done"] == 0

    def test_a_final_fills_the_slot_for_its_asset(self, nodes_mod, monkeypatch):
        """The whole feature: the tracker reads the same folder the picker
        lists, so an approval shows up with no bookkeeping in between."""
        from pipeline.pick_folder import approve
        folder = folder_for(nodes_mod, "Bat Brew", "Decoration")
        render(folder, "_base_00007_.png")
        approve(folder, ["_base_00007_.png"])
        board = pushed(nodes_mod, monkeypatch, order=ORDER)
        filled = board["slots"][0]
        assert filled["asset"] == "Bat Brew"
        assert os.path.basename(filled["image"]) == \
            "_final_from._base_00007__00001_.png"
        assert board["done"] == 1

    def test_it_fills_from_the_prefix_layout_too(self, nodes_mod, monkeypatch):
        """His renders are `<category>/<asset>_00001_.png`, not
        `<category>/<asset>/_base_00001_.png` — the last segment of a save
        prefix names the FILE. The board was tested only against the second
        and could never fill against the first."""
        from pipeline.pick_folder import approve
        category = os.path.join(nodes_mod._TEST_OUTPUT, "October", "Mini 3",
                                "Decoration")
        render(category, "Bat Brew_00001_.png")
        approve(os.path.join(category, "Bat Brew"), ["Bat Brew_00001_.png"])
        board = pushed(nodes_mod, monkeypatch, order=ORDER)
        assert board["slots"][0]["asset"] == "Bat Brew"
        assert board["slots"][0]["image"] is not None
        assert board["done"] == 1

    def test_a_render_without_an_approval_leaves_the_slot_empty(
            self, nodes_mod, monkeypatch):
        """Rendering is not finishing — the board answers "what is done", and
        a folder of tries is the state it exists to make visible."""
        render(folder_for(nodes_mod, "Bat Brew", "Decoration"),
               "_base_00007_.png", "_base_00008_.png")
        board = pushed(nodes_mod, monkeypatch, order=ORDER)
        assert board["slots"][0]["image"] is None
        assert board["done"] == 0

    def test_the_tag_is_read_like_a_picker_reads_names(
            self, nodes_mod, monkeypatch):
        """`names` is a save prefix, so pointing the board at another lane is
        a string, not a code change."""
        render(folder_for(nodes_mod, "Bat Brew", "Decoration"),
               "_base_00007_.png")
        board = pushed(nodes_mod, monkeypatch, order=ORDER, names="_base")
        assert board["slots"][0]["image"] is not None
        assert board["slots"][0]["count"] == 1

    def test_the_category_narrows_the_board(self, nodes_mod, monkeypatch):
        board = pushed(nodes_mod, monkeypatch, order=ORDER,
                       category="Food - 3 stages")
        assert [s["asset"] for s in board["slots"]] == ["Spookies"]

    def test_each_slot_carries_its_category(self, nodes_mod, monkeypatch):
        board = pushed(nodes_mod, monkeypatch, order=ORDER)
        assert board["slots"][-1]["category"] == "Food - 3 stages"

    def test_no_order_says_what_to_wire(self, nodes_mod):
        nodes_mod.SymbioticaOrderTracker.hidden = types.SimpleNamespace(
            unique_id="7")
        with pytest.raises(ValueError, match="wire an Order Specs"):
            nodes_mod.SymbioticaOrderTracker.execute(order=None)


class TestItRefusesToGoStale:
    def test_it_never_caches(self, nodes_mod):
        """Disk changes without the graph changing — a render saved, an
        approval written. A cached board shows yesterday's work."""
        answer = nodes_mod.SymbioticaOrderTracker.fingerprint_inputs(
            order=ORDER)
        assert answer != answer     # NaN: never equal to the previous run

    def test_it_is_an_output_node(self, nodes_mod):
        """So "Queue Selected Output Node" re-reads the folders — the same
        gesture that refreshes a picker."""
        schema = nodes_mod.SymbioticaOrderTracker.GET_SCHEMA()
        assert schema.is_output_node is True
        assert schema.outputs == []

    def test_it_is_registered(self, nodes_mod):
        assert nodes_mod.SymbioticaOrderTracker in \
            nodes_mod.PIPELINE_NODE_CLASSES
