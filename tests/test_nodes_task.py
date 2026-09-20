# ABOUTME: Task — the browsing node: the whole pick down ONE wire, and Task
# ABOUTME: Specs fanning that wire back out into the columns a graph wires.
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(__file__))
# The same harness, the same event: Task is Asset Focus's selection on one
# wire, so a second ORDER or a second `nodes_mod` here would be two nodes
# tested against two different events — which is how they drift.
from test_nodes_asset_focus import ORDER, nodes_mod, run


def task(nodes, event, **kw):
    """Task reads the folder itself — `project_path` is its only input — so the
    event is put where that read lands. The xlsx parse has its own tests; this
    file is about the selection and the columns."""
    nodes.SymbioticaTask.hidden = types.SimpleNamespace(unique_id="9")
    kw.setdefault("project_path", "/p")
    built = nodes.build_event_order
    nodes.build_event_order = lambda *a, **k: event
    try:
        return nodes.SymbioticaTask.execute(**kw)
    finally:
        nodes.build_event_order = built


def fan_out(nodes, specs):
    return nodes.SymbioticaTaskSpecs.execute(specs=specs)


def flat_columns(out):
    """The columns that are a value rather than a tensor, by slot: name,
    category, prompt, save path, bucket, ref name, recipe, width, height."""
    return [out.args[i] for i in (0, 1, 2, 3, 6, 9, 10, 11, 12)]


@pytest.fixture()
def event(tmp_path):
    """The event with its reference art on disk and a canvas on one asset, so
    the columns the two nodes have to agree on are more than their defaults."""
    from PIL import Image
    root = tmp_path / "client-refs"
    root.mkdir()
    for name in ("a.png", "b.png", "c.png"):
        Image.new("RGB", (8, 4), (10, 20, 30)).save(root / name)
    return {**ORDER, "refsRoot": str(root), "assets": [
        ORDER["assets"][0],
        {**ORDER["assets"][1], "canvas": "128x256"},
        ORDER["assets"][2],
    ]}


class TestTheBrowsersSockets:
    """"a browsing node that is thirteen sockets tall is a browsing node you
    park off screen" — so it keeps what you look at while you browse and puts
    the rest on one wire."""

    def test_one_socket_and_nothing_beside_it(self, nodes_mod):
        """"drop the output links other than specs since the task specs node
        shows the same thing, there is no point in having them twice" — a
        value you can read off either of two nodes is a value you have to
        decide between every time you wire it."""
        schema = nodes_mod.SymbioticaTask.GET_SCHEMA()
        assert [o.display_name for o in schema.outputs] == ["specs"]

    def test_it_is_a_list_so_a_whole_event_still_fans_out(self, nodes_mod):
        """Same rule as Asset Focus: a list of one runs downstream exactly
        once, so choosing no asset can fan out over the event instead."""
        schema = nodes_mod.SymbioticaTask.GET_SCHEMA()
        assert [o.display_name for o in schema.outputs
                if getattr(o, "is_output_list", False)] == ["specs"]

    def test_the_path_is_the_only_input(self, nodes_mod):
        """"why do i still have an `Order` input mate, when project path is the
        only needed input?" — Asset Focus carries an `order` socket so one of
        them can feed another; this node reads the folder and that is the whole
        of it. The rest are the widgets the tree drives, and they keep Asset
        Focus's NAMES in Asset Focus's ORDER because the panel code, the
        prefill and `wireOrderSpecs` all key on them."""
        focus = nodes_mod.SymbioticaAssetFocus.GET_SCHEMA()
        assert [i.id for i in nodes_mod.SymbioticaTask.GET_SCHEMA().inputs] == \
            [i.id for i in focus.inputs if i.id != "order"]

    def test_nothing_on_it_takes_an_order(self, nodes_mod):
        """A socket for an order it never reads is a wire he has to look at and
        decide about every time."""
        schema = nodes_mod.SymbioticaTask.GET_SCHEMA()
        assert [i.id for i in schema.inputs if "ORDER" in str(i.__class__)
                or i.id == "order"] == []

    def test_it_is_in_the_one_folder_under_the_name_he_reads(self, nodes_mod):
        schema = nodes_mod.SymbioticaTask.GET_SCHEMA()
        assert (schema.node_id, schema.display_name, schema.category) == \
            ("SymbioticaTask", "Task (Symbiotica)", "Symbiotica")

    def test_it_can_be_queued_on_its_own(self, nodes_mod):
        """Its list of choices only exists once it has run, and a browser is
        the first node on the canvas — nothing is wired downstream yet."""
        assert nodes_mod.SymbioticaTask.GET_SCHEMA().is_output_node is True

    def test_it_is_registered(self, nodes_mod):
        assert nodes_mod.SymbioticaTask in nodes_mod.PIPELINE_NODE_CLASSES


class TestTaskSpecsSockets:
    def test_one_wire_in_and_nothing_to_pick(self, nodes_mod):
        """No widgets at all: the pick was made on the Task, and being asked
        the same question twice is the click that was removed."""
        assert [i.id for i in nodes_mod.SymbioticaTaskSpecs.GET_SCHEMA().inputs] \
            == ["specs"]

    def test_it_emits_exactly_what_asset_focus_emits(self, nodes_mod):
        """The anti-drift contract. These outputs are BUILT from Asset Focus's,
        so an output added there lands here too, in the same order — a graph
        that swaps one node for the other keeps every wire."""
        focus = nodes_mod.SymbioticaAssetFocus.GET_SCHEMA()
        specs = nodes_mod.SymbioticaTaskSpecs.GET_SCHEMA()
        assert [o.display_name for o in specs.outputs] == \
            [o.display_name for o in focus.outputs]

    def test_it_is_not_a_node_to_queue(self, nodes_mod):
        """Nothing to fill: it has no panel, and it says nothing a run would
        teach it. It answers when the graph reaches it."""
        schema = nodes_mod.SymbioticaTaskSpecs.GET_SCHEMA()
        assert getattr(schema, "is_output_node", False) is False

    def test_it_is_registered(self, nodes_mod):
        assert nodes_mod.SymbioticaTaskSpecs in nodes_mod.PIPELINE_NODE_CLASSES


class TestTheWholeRecordOnOneWire:
    def test_task_specs_says_what_asset_focus_says(self, nodes_mod, event):
        """The point of the split: the two nodes together are the one node.
        A column that answered differently here would file the same asset in
        another folder, or draw it at another size."""
        picked = task(nodes_mod, event, asset="Frankenstein Pops").args[0]
        out = fan_out(nodes_mod, picked[0])
        assert flat_columns(out) == flat_columns(
            run(nodes_mod, order=event, asset="Frankenstein Pops"))
        assert (out.args[0], out.args[3]) == (
            ["Frankenstein Pops"],
            ["October/Mini 3 — Franken-Feast/Food - 3 stages/"
             "Frankenstein Pops"])
        assert out.args[-3:] == (["Food - 3 stages 1x2"], [128], [256])

    def test_the_reference_and_the_prompt_come_off_task_specs(
            self, nodes_mod, event):
        """They are not on the browser any more, and they do not need to be:
        the wire carries the record they are read from."""
        specs = task(nodes_mod, event, asset="Frankenstein Pops").args[0]
        out = fan_out(nodes_mod, specs[0])
        assert out.args[2] == ["cake pops"]
        assert tuple(out.args[7][0].shape) == (1, 4, 8, 3)
        assert tuple(out.args[8][0].shape) == (1, 4, 8)

    def test_the_event_survives_the_narrowing(self, nodes_mod, event):
        """The Order Tracker wants the EVENT, and it must not change every time
        he focuses a different asset. The narrowing replaces `assets` with the
        one asset, so the event rides along beside it and `event_order` is
        rebuilt from that — otherwise it would be gone the moment the pick went
        on a wire."""
        specs = task(nodes_mod, event, asset="Bunting").args[0]
        whole = fan_out(nodes_mod, specs[0]).args[5]
        assert isinstance(whole, dict)
        assert [a["assetName"] for a in whole["assets"]] == \
            [a["assetName"] for a in event["assets"]]
        assert whole["feature"] == event["feature"]


class TestTheClickedReferenceTravels:
    """Clicking the thumbnail IS the pick, and the pick has to survive the
    wire: "being asked the same question again is the click he wanted gone"."""

    def test_the_file_he_clicked_rides_on_the_specs_wire(
            self, nodes_mod, event):
        out = task(nodes_mod, event, asset="Frankencrisps", ref="b.png")
        assert out.args[0][0]["refPick"] == "b.png"

    def test_task_specs_draws_it_without_being_given_a_ref_of_its_own(
            self, nodes_mod, event):
        """It has no `ref` input at all — the wire is the only thing that can
        say which thumbnail was clicked."""
        picked = task(nodes_mod, event, asset="Frankencrisps",
                      ref="b.png").args[0]
        assert fan_out(nodes_mod, picked[0]).args[9] == ["b.png"]

    def test_the_pick_is_the_one_that_resolved_not_the_one_asked_for(
            self, nodes_mod, event):
        """`refPick` is what this run actually drew. An asset that does not
        have the clicked file falls back to its first, and the wire has to
        carry THAT or the next node draws a different picture."""
        out = task(nodes_mod, event, ref="b.png")
        assert [o["refPick"] for o in out.args[0]] == ["b.png", "c.png", ""]

    def test_asset_focus_fed_a_specs_wire_uses_the_pick_on_it(
            self, nodes_mod, event):
        picked = task(nodes_mod, event, asset="Frankencrisps",
                      ref="b.png").args[0]
        assert run(nodes_mod, order=picked[0]).args[9] == ["b.png"]

    def test_its_own_ref_still_wins_over_the_one_on_the_wire(
            self, nodes_mod, event):
        """The later answer wins: a node with a thumbnail of its own clicked is
        him saying which one, after the Task said it."""
        picked = task(nodes_mod, event, asset="Frankencrisps",
                      ref="b.png").args[0]
        assert run(nodes_mod, order=picked[0], ref="a.png").args[9] == ["a.png"]


class TestChoosingNoAsset:
    def test_one_specs_wire_per_asset(self, nodes_mod):
        """"all" has to mean all here too, or the browser and the node it
        feeds disagree about what was queued."""
        out = task(nodes_mod, ORDER)
        assert [o["assets"][0]["assetName"] for o in out.args[0]] == \
            ["Frankencrisps", "Frankenstein Pops", "Bunting"]

    def test_the_event_beside_them_is_still_one_dict(self, nodes_mod):
        """One specs wire per asset, and every one of them carries the SAME
        whole event — the fan-out is over the assets, never over the event. A
        list there would fan the Order Tracker out once per asset in it."""
        specs = task(nodes_mod, ORDER).args[0]
        events = [fan_out(nodes_mod, one).args[5] for one in specs]
        assert all(isinstance(e, dict) for e in events)
        assert {tuple(a["assetName"] for a in e["assets"]) for e in events} == \
            {tuple(a["assetName"] for a in ORDER["assets"])}
        assert len(specs) == 3


class TestRefusals:
    def test_a_task_specs_with_nothing_wired_says_what_to_do(self, nodes_mod):
        """It has no widgets, so an empty input has no other way to explain
        itself — and "a node rejected one or more input values" says nothing
        about which wire is missing."""
        with pytest.raises(ValueError, match="wire a Task's `specs`"):
            fan_out(nodes_mod, None)

    def test_a_name_that_is_not_in_the_event_is_refused_here_too(
            self, nodes_mod):
        with pytest.raises(ValueError, match="no asset called 'Ghost'"):
            task(nodes_mod, ORDER, asset="Ghost")


class TestWhatThePanelIsTold:
    @pytest.fixture()
    def pushed(self, nodes_mod, monkeypatch):
        seen = []
        monkeypatch.setattr(nodes_mod, "_push",
                            lambda event, detail: seen.append((event, detail)))
        return seen

    def test_the_browser_fills_its_own_panel(self, nodes_mod, pushed):
        """The same channel and the same payload as Asset Focus — the panel is
        shared — landing on THIS node's id."""
        task(nodes_mod, ORDER)
        detail = next(d for e, d in pushed if e == "symbiotica.focus")
        assert detail["node_id"] == "9"
        assert [a["name"] for a in detail["assets"]] == \
            ["Frankencrisps", "Frankenstein Pops", "Bunting"]

    def test_task_specs_has_no_panel_to_fill(self, nodes_mod, pushed):
        """A push under a class nothing listens for lands on no node at all,
        and would blank the panel of whichever Task shares its node id."""
        picked = task(nodes_mod, ORDER, asset="Bunting").args[0]
        pushed.clear()
        fan_out(nodes_mod, picked[0])
        assert pushed == []
