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
        assert out.args[:4] == (["Frankenstein Pops"], ["Food - 3 stages"],
                                ["cake pops"],
                                ["October/Mini 3 — Franken-Feast/"
                                 "Food - 3 stages/Frankenstein Pops"])

    def test_the_save_path_matches_what_order_assets_emits(self, nodes_mod):
        """A save node and a Pick node's save_path both take this value, so
        the two nodes disagreeing would file the same asset in two places."""
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

    def test_choosing_nothing_still_files_each_asset_under_its_own_path(
            self, nodes_mod):
        out = run(nodes_mod, order=ORDER)
        assert out.args[3][2] == "October/Mini 3 — Franken-Feast/Decoration/Bunting"

    def test_a_category_narrows_what_can_be_chosen(self, nodes_mod):
        out = run(nodes_mod, order=ORDER, category="Decoration")
        assert (out.args[0], out.args[1]) == (["Bunting"], ["Decoration"])


class TestTheFocusedOrder:
    def test_one_narrowed_order_per_focused_asset(self, nodes_mod):
        """The whole record on ONE wire: same event, same project, an assets
        list of exactly the focused asset — the shape every order consumer
        already reads."""
        out = run(nodes_mod, order=ORDER, asset="Frankenstein Pops")
        orders = out.args[4]
        assert len(orders) == 1
        assert orders[0]["assets"] == [ORDER["assets"][1]]
        assert orders[0]["feature"] == ORDER["feature"]
        assert orders[0]["month"] == ORDER["month"]

    def test_no_choice_fans_one_order_out_per_asset(self, nodes_mod):
        out = run(nodes_mod, order=ORDER)
        orders = out.args[4]
        assert [o["assets"][0]["assetName"] for o in orders] == \
            ["Frankencrisps", "Frankenstein Pops", "Bunting"]

    def test_the_incoming_order_is_not_mutated(self, nodes_mod):
        run(nodes_mod, order=ORDER, asset="Bunting")
        assert len(ORDER["assets"]) == 3


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
        # `event_order` excepted: it is the event, not a per-asset value, so
        # fanning it out would run everything downstream once per asset.
        assert all(o.is_output_list for o in schema.outputs
                   if o.display_name != "event_order")

    def test_the_order_output_replaced_index_on_the_tail_slot(self, nodes_mod):
        """`index` was wired nowhere in any live graph; the narrowed order
        takes its tail slot, so no earlier slot moved for saved graphs."""
        schema = nodes_mod.SymbioticaAssetFocus.GET_SCHEMA()
        assert [o.display_name for o in schema.outputs] == [
            "asset_name", "category", "client_prompt", "save_path", "order",
            "event_order", "bucket"]

    def test_it_is_registered(self, nodes_mod):
        assert nodes_mod.SymbioticaAssetFocus in nodes_mod.PIPELINE_NODE_CLASSES


class TestWhatThePanelIsTold:
    """The order arrives on a wire the canvas cannot read, so the run hands the
    panel everything it draws: the choices, their reference art, and the root
    that art is relative to."""

    @pytest.fixture()
    def pushed(self, nodes_mod, monkeypatch):
        seen = []
        monkeypatch.setattr(nodes_mod, "_push",
                            lambda event, detail: seen.append((event, detail)))
        return seen

    def detail(self, pushed):
        return next(d for e, d in pushed if e == "symbiotica.focus")

    def test_every_reference_file_goes_over_not_just_the_first(
            self, nodes_mod, pushed):
        """The panel draws a strip per asset. `assets_by_category` keeps the
        four fields a run needs and drops `refFiles`, so the names are looked
        back up in the raw order — reading them off its output sent nothing."""
        run(nodes_mod, order={**ORDER, "refsRoot": "/refs/bakery"})
        detail = self.detail(pushed)
        assert [(a["name"], a["refs"]) for a in detail["assets"]] == [
            ("Frankencrisps", ["a.png", "b.png"]),
            ("Frankenstein Pops", ["c.png"]),
            ("Bunting", []),
        ]

    def test_the_refs_root_rides_along(self, nodes_mod, pushed):
        """Relative file names alone cannot be turned into a thumbnail URL."""
        run(nodes_mod, order={**ORDER, "refsRoot": "/refs/bakery"})
        assert self.detail(pushed)["refs_root"] == "/refs/bakery"

    def test_an_order_with_no_refs_root_still_lists(self, nodes_mod, pushed):
        """A Reference Browser event may carry no root; names still draw."""
        run(nodes_mod, order=ORDER)
        assert self.detail(pushed)["refs_root"] == ""
        assert len(self.detail(pushed)["assets"]) == 3

    def test_the_category_narrows_what_is_offered(self, nodes_mod, pushed):
        """The panel must not offer a choice the node would refuse."""
        run(nodes_mod, order=ORDER, category="Decoration")
        assert [a["name"] for a in self.detail(pushed)["assets"]] == ["Bunting"]


class TestItCanBeQueuedOnItsOwn:
    def test_it_is_an_output_node(self, nodes_mod):
        """Its list of choices only exists once it has run, and nothing is
        wired downstream when it is first dropped — so without this there is no
        way to run it at all."""
        assert nodes_mod.SymbioticaAssetFocus.GET_SCHEMA().is_output_node is True


class TestItMakesItsOwnOrder:
    """"order specs and asset focus are 2 nodes that are doing one thing… i
    select month and feature in specs and asset in asset focus. this doesn't
    make any sense". So the whole selection lives here when nothing is wired
    in."""

    def test_project_and_month_read_an_order_without_a_wire(
            self, nodes_mod, monkeypatch):
        seen = {}
        monkeypatch.setattr(nodes_mod, "build_event_order",
                            lambda p, m, f: seen.update(
                                project=p, month=m, feature=f) or ORDER)
        out = run(nodes_mod, order=None, project_path="/p", month="October",
                  feature="Mini 3", asset="Bunting")
        assert seen == {"project": "/p", "month": "October",
                        "feature": "Mini 3"}
        assert out.args[0] == ["Bunting"]

    def test_a_wired_order_wins_over_the_widgets(self, nodes_mod, monkeypatch):
        """The wire is the explicit statement; reading the folder again would
        quietly ignore whatever produced it (a Reference Browser has no
        project_path at all)."""
        monkeypatch.setattr(nodes_mod, "build_event_order",
                            lambda *a: (_ for _ in ()).throw(
                                AssertionError("should not parse")))
        out = run(nodes_mod, order=ORDER, project_path="/p", asset="Bunting")
        assert out.args[0] == ["Bunting"]

    def test_neither_says_what_to_do(self, nodes_mod):
        with pytest.raises(ValueError, match="set project_path"):
            run(nodes_mod, order=None)

    def test_the_whole_event_comes_out_beside_the_focused_one(self, nodes_mod):
        """The Auto Packer, Order Assets and the Tracker want the EVENT, and
        they must not change every time he focuses a different asset."""
        out = run(nodes_mod, order=ORDER, asset="Bunting")
        assert out.args[5] is ORDER
        assert len(out.args[4]) == 1        # `order`, narrowed to the asset

    def test_the_event_is_not_a_list(self, nodes_mod):
        out = run(nodes_mod, order=ORDER)
        assert isinstance(out.args[5], dict)

    def test_its_own_order_also_comes_out_whole(self, nodes_mod, monkeypatch):
        monkeypatch.setattr(nodes_mod, "build_event_order",
                            lambda p, m, f: ORDER)
        out = run(nodes_mod, order=None, project_path="/p")
        assert out.args[5] is ORDER


class TestWhenItReReads:
    def test_its_own_order_follows_the_order_file(self, nodes_mod, monkeypatch):
        """Reading the folder itself means inheriting Order Specs' change
        check — the .xlsx moves without the graph moving."""
        monkeypatch.setattr(
            nodes_mod.SymbioticaOrderSpecs, "fingerprint_inputs",
            classmethod(lambda cls, project_path="", month="", feature="":
                        f"specs:{project_path}:{month}:{feature}"))
        assert nodes_mod.SymbioticaAssetFocus.fingerprint_inputs(
            project_path="/p", month="October", feature="Mini 3") \
            == "specs:/p:October:Mini 3"

    def test_a_wired_order_caches_on_the_choice(self, nodes_mod):
        """NaN here marks the node permanently dirty, and its outputs feed the
        string joins and the render lane — so every queue re-ran the whole
        graph with the seed untouched. The wire already carries whether the
        order changed; what is left is which asset was picked."""
        same = [nodes_mod.SymbioticaAssetFocus.fingerprint_inputs(
            order=ORDER, category="Decoration", asset="Bunting")
            for _ in range(2)]
        assert same[0] == same[1]
        assert same[0] == same[0]       # not NaN

    def test_choosing_another_asset_is_a_different_run(self, nodes_mod):
        first = nodes_mod.SymbioticaAssetFocus.fingerprint_inputs(
            order=ORDER, asset="Bunting")
        second = nodes_mod.SymbioticaAssetFocus.fingerprint_inputs(
            order=ORDER, asset="Frankencrisps")
        assert first != second

    def test_narrowing_the_category_is_a_different_run(self, nodes_mod):
        first = nodes_mod.SymbioticaAssetFocus.fingerprint_inputs(order=ORDER)
        second = nodes_mod.SymbioticaAssetFocus.fingerprint_inputs(
            order=ORDER, category="Decoration")
        assert first != second
