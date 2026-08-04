# ABOUTME: Asset Focus — one asset out of the order with its whole record on
# ABOUTME: separate outputs, so nothing downstream has a list left to index.
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
    yield nodes
    sys.modules.pop("pipeline.nodes", None)


ORDER = {
    "feature": "Mini 3 — Franken-Feast",
    "month": "October",
    "assets": [
        {"assetName": "Frankencrisps", "category": "Food - 3 stages",
         "prompt": "crispy squares", "refFiles": ["a.png", "b.png"]},
        {"assetName": "Frankenstein Pops", "category": "Food - 3 stages",
         "prompt": "cake pops", "refFiles": ["c.png"]},
        {"assetName": "Bunting", "category": "Decoration",
         "prompt": "paper flags", "refFiles": []},
    ],
}


def run(nodes, **kw):
    nodes.SymbioticaAssetFocus.hidden = types.SimpleNamespace(unique_id="9")
    return nodes.SymbioticaAssetFocus.execute(**kw)


class TestOneAssetsWholeRecord:
    def test_every_field_comes_out_on_its_own_wire(self, nodes_mod):
        """The point of the node: the index is applied once, here, so nothing
        downstream has a list left to index. The outputs are lists of one,
        which runs downstream exactly once — the same as a scalar."""
        out = run(nodes_mod, order=ORDER, asset="Frankenstein Pops")
        assert out.args == (["Frankenstein Pops"], ["Food - 3 stages"],
                            ["cake pops"],
                            ["October/Mini 3 — Franken-Feast/Food - 3 stages/"
                             "Frankenstein Pops"], [1])

    def test_the_save_path_matches_what_order_assets_emits(self, nodes_mod):
        """A save node and a Pick node's folder both take this value, so the
        two nodes disagreeing would file the same asset in two places."""
        from pipeline.order_assets import assets_by_category, save_paths
        items = assets_by_category(ORDER, "")
        expected = save_paths(ORDER, items)
        for index, item in enumerate(items):
            out = run(nodes_mod, order=ORDER, asset=item["assetName"])
            assert out.args[3] == [expected[index]]

    def test_no_choice_means_the_whole_event(self, nodes_mod):
        """A button that reads "all" and emits one asset is lying about what
        the node is going to do."""
        out = run(nodes_mod, order=ORDER)
        assert out.args[0] == ["Frankencrisps", "Frankenstein Pops", "Bunting"]
        assert out.args[4] == [0, 1, 2]

    def test_choosing_nothing_still_files_each_asset_under_its_own_path(
            self, nodes_mod):
        out = run(nodes_mod, order=ORDER)
        assert out.args[3][2] == "October/Mini 3 — Franken-Feast/Decoration/Bunting"

    def test_a_category_narrows_what_can_be_chosen(self, nodes_mod):
        out = run(nodes_mod, order=ORDER, category="Decoration")
        assert (out.args[0], out.args[1]) == (["Bunting"], ["Decoration"])

    def test_the_index_is_within_the_narrowed_run(self, nodes_mod):
        """It addresses the list this node was choosing from, not the raw
        order — anything still handed a list gets that one."""
        out = run(nodes_mod, order=ORDER, category="Decoration",
                  asset="Bunting")
        assert out.args[4] == [0]


class TestRefusals:
    def test_a_name_that_is_not_in_the_event_is_refused(self, nodes_mod):
        """Falling back silently would render the wrong asset under the wrong
        name and file it in the wrong folder."""
        with pytest.raises(ValueError, match="no asset called 'Ghost'"):
            run(nodes_mod, order=ORDER, asset="Ghost")

    def test_the_refusal_lists_what_the_event_does_hold(self, nodes_mod):
        with pytest.raises(ValueError, match="Frankencrisps"):
            run(nodes_mod, order=ORDER, asset="Ghost")

    def test_an_asset_hidden_by_the_category_is_refused_not_silently_swapped(
            self, nodes_mod):
        with pytest.raises(ValueError, match="no asset called"):
            run(nodes_mod, order=ORDER, category="Decoration",
                asset="Frankencrisps")

    def test_a_category_with_nothing_in_it_names_what_is_there(self, nodes_mod):
        with pytest.raises(ValueError, match="Decoration"):
            run(nodes_mod, order=ORDER, category="Wallpaper")

    def test_no_order_says_what_to_wire(self, nodes_mod):
        with pytest.raises(ValueError, match="wire an Order Specs"):
            run(nodes_mod, order=None)


class TestSchema:
    def test_every_output_is_a_list(self, nodes_mod):
        """Lists, but normally of one. A single-element list runs downstream
        exactly once, so choosing an asset still leaves nothing to index —
        while choosing none can fan out over the whole event."""
        schema = nodes_mod.SymbioticaAssetFocus.GET_SCHEMA()
        assert all(o.is_output_list for o in schema.outputs)

    def test_it_is_registered(self, nodes_mod):
        assert nodes_mod.SymbioticaAssetFocus in nodes_mod.PIPELINE_NODE_CLASSES


class TestItCanBeQueuedOnItsOwn:
    def test_it_is_an_output_node(self, nodes_mod):
        """Its list of choices only exists once it has run, and nothing is
        wired downstream when it is first dropped — so without this there is no
        way to run it at all."""
        assert nodes_mod.SymbioticaAssetFocus.GET_SCHEMA().is_output_node is True
