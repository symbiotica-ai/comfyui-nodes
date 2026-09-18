# ABOUTME: Asset Recipe — Asset Focus with the widget values that draw the
# ABOUTME: asset, one slot per widget dragged onto the node.
import importlib
import json
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
         "prompt": "crispy squares", "refFiles": []},
    ],
}


def slots(*rows) -> str:
    return json.dumps(list(rows))


def run(nodes, **kw):
    nodes.SymbioticaAssetRecipe.hidden = types.SimpleNamespace(unique_id="9")
    return nodes.SymbioticaAssetRecipe.execute(**kw)


class TestItIsAssetFocusWithSlots:
    def test_the_focus_outputs_come_first_and_unchanged(self, nodes_mod):
        """Same node, same outputs, in the same order — the slots go on the
        end. A canvas that swaps one for the other must keep every wire."""
        focus = nodes_mod.SymbioticaAssetFocus.GET_SCHEMA()
        recipe = nodes_mod.SymbioticaAssetRecipe.GET_SCHEMA()
        focus_names = [o.display_name for o in focus.outputs]
        assert [o.display_name for o in recipe.outputs[:len(focus.outputs)]] \
            == focus_names

    def test_the_slots_are_declared_outputs(self, nodes_mod):
        """ComfyUI has no dynamic outputs, so the canvas grows INTO a fixed
        set. The count is the node's, and the JS reads it off the definition
        rather than carrying a number of its own."""
        recipe = nodes_mod.SymbioticaAssetRecipe.GET_SCHEMA()
        tail = [o.display_name for o in recipe.outputs][-nodes_mod.SLOT_COUNT:]
        assert tail == [f"slot_{i}" for i in range(1, nodes_mod.SLOT_COUNT + 1)]

    def test_the_slot_table_is_the_last_input(self, nodes_mod):
        """A saved workflow restores widget values BY POSITION, so the one
        input this node adds goes after every input Asset Focus declares."""
        focus = nodes_mod.SymbioticaAssetFocus.GET_SCHEMA()
        recipe = nodes_mod.SymbioticaAssetRecipe.GET_SCHEMA()
        assert [i.id for i in recipe.inputs] == \
            [i.id for i in focus.inputs] + ["slots"]

    def test_it_registers_and_is_queueable_on_its_own(self, nodes_mod):
        assert nodes_mod.SymbioticaAssetRecipe in nodes_mod.PIPELINE_NODE_CLASSES
        assert nodes_mod.SymbioticaAssetRecipe.GET_SCHEMA().is_output_node is True

    def test_the_asset_is_still_chosen_here(self, nodes_mod):
        out = run(nodes_mod, order=ORDER, asset="Frankencrisps")
        assert out.args[0] == ["Frankencrisps"]
        assert out.args[3] == ["October/Mini 3 — Franken-Feast/"
                               "Food - 3 stages/Frankencrisps"]


class TestWhatTheSlotsSend:
    def test_every_slot_answers_in_order(self, nodes_mod):
        out = run(nodes_mod, order=ORDER,
                  slots=slots({"name": "lora-strength", "type": "FLOAT",
                               "value": 0.7},
                              {"name": "seed", "type": "INT", "value": 42}))
        focus = len(nodes_mod.SymbioticaAssetFocus.GET_SCHEMA().outputs)
        assert out.args[focus:focus + 2] == (0.7, 42)

    def test_a_slot_nobody_filled_is_empty(self, nodes_mod):
        """Every declared output answers whether or not it holds a slot —
        None is what an unconnected output means anyway."""
        out = run(nodes_mod, order=ORDER, slots=slots(
            {"name": "seed", "type": "INT", "value": 1}))
        focus = len(nodes_mod.SymbioticaAssetFocus.GET_SCHEMA().outputs)
        assert len(out.args) == focus + nodes_mod.SLOT_COUNT
        assert set(out.args[focus + 1:]) == {None}

    def test_a_seed_stays_an_int(self, nodes_mod):
        """JSON has one kind of number, and a float `seed` is one a sampler
        refuses. The type recorded when the wire was made is what decides."""
        out = run(nodes_mod, order=ORDER,
                  slots=slots({"name": "seed", "type": "INT", "value": 42.0}))
        focus = len(nodes_mod.SymbioticaAssetFocus.GET_SCHEMA().outputs)
        assert out.args[focus] == 42
        assert isinstance(out.args[focus], int)

    def test_a_number_typed_as_text_still_arrives_as_a_number(self, nodes_mod):
        out = run(nodes_mod, order=ORDER,
                  slots=slots({"name": "denoise", "type": "FLOAT",
                               "value": "0.35"}))
        focus = len(nodes_mod.SymbioticaAssetFocus.GET_SCHEMA().outputs)
        assert out.args[focus] == 0.35

    def test_a_lora_name_comes_out_as_it_went_in(self, nodes_mod):
        out = run(nodes_mod, order=ORDER,
                  slots=slots({"name": "lora_name", "type": "COMBO",
                               "value": "imperia/bakery.safetensors"}))
        focus = len(nodes_mod.SymbioticaAssetFocus.GET_SCHEMA().outputs)
        assert out.args[focus] == "imperia/bakery.safetensors"

    def test_a_toggle_comes_out_as_a_boolean(self, nodes_mod):
        out = run(nodes_mod, order=ORDER,
                  slots=slots({"name": "enable_turbo_mode",
                               "type": "BOOLEAN", "value": True}))
        focus = len(nodes_mod.SymbioticaAssetFocus.GET_SCHEMA().outputs)
        assert out.args[focus] is True

    def test_more_rows_than_slots_fill_the_slots_there_are(self, nodes_mod):
        rows = [{"name": f"w{i}", "type": "INT", "value": i}
                for i in range(nodes_mod.SLOT_COUNT + 4)]
        out = run(nodes_mod, order=ORDER, slots=json.dumps(rows))
        focus = len(nodes_mod.SymbioticaAssetFocus.GET_SCHEMA().outputs)
        assert len(out.args) == focus + nodes_mod.SLOT_COUNT
        assert out.args[-1] == nodes_mod.SLOT_COUNT - 1


class TestWhenTheTableIsWrong:
    def test_unreadable_json_still_names_the_asset(self, nodes_mod):
        """The focus half files the render. A mangled slot table must not take
        that down with it."""
        out = run(nodes_mod, order=ORDER, slots="{oops")
        assert out.args[0] == ["Frankencrisps"]
        focus = len(nodes_mod.SymbioticaAssetFocus.GET_SCHEMA().outputs)
        assert set(out.args[focus:]) == {None}

    def test_a_value_that_is_not_a_number_names_its_slot(self, nodes_mod):
        """The alternative is a type error thrown by whichever node the wire
        reaches, which says nothing about where the value came from."""
        with pytest.raises(ValueError, match="'lora-strength'"):
            run(nodes_mod, order=ORDER,
                slots=slots({"name": "lora-strength", "type": "FLOAT",
                             "value": "strong"}))

    def test_no_slots_at_all_is_the_ordinary_case(self, nodes_mod):
        out = run(nodes_mod, order=ORDER)
        focus = len(nodes_mod.SymbioticaAssetFocus.GET_SCHEMA().outputs)
        assert set(out.args[focus:]) == {None}


class TestCaching:
    def test_changing_a_slot_value_re_runs_the_graph(self, nodes_mod):
        """A strength is an input like any other: change it and the nodes it
        feeds have to run again."""
        one = nodes_mod.SymbioticaAssetRecipe.fingerprint_inputs(
            order=ORDER, slots=slots({"name": "s", "type": "FLOAT",
                                      "value": 0.7}))
        two = nodes_mod.SymbioticaAssetRecipe.fingerprint_inputs(
            order=ORDER, slots=slots({"name": "s", "type": "FLOAT",
                                      "value": 0.8}))
        assert one != two

    def test_the_same_table_is_the_same_answer(self, nodes_mod):
        table = slots({"name": "s", "type": "FLOAT", "value": 0.7})
        assert nodes_mod.SymbioticaAssetRecipe.fingerprint_inputs(
            order=ORDER, slots=table) == \
            nodes_mod.SymbioticaAssetRecipe.fingerprint_inputs(
                order=ORDER, slots=table)

    def test_the_focus_half_still_decides_too(self, nodes_mod):
        table = slots({"name": "s", "type": "FLOAT", "value": 0.7})
        assert nodes_mod.SymbioticaAssetRecipe.fingerprint_inputs(
            order=ORDER, asset="Frankencrisps", slots=table) != \
            nodes_mod.SymbioticaAssetRecipe.fingerprint_inputs(
                order=ORDER, asset="Bunting", slots=table)
