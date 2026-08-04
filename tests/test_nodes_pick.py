# ABOUTME: Node-face tests for Symbiotica Pick — what it records, what it hands
# ABOUTME: on, and the muted-generator case the optional image input exists for.
import importlib
import json
import os
import sys
import types

import pytest
import torch

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


def frames(*values, size=4, channels=3):
    """A batch whose every frame is one flat colour, so a mixed-up pick shows
    up as the wrong value rather than merely the wrong count."""
    batch = torch.zeros(len(values), size, size, channels)
    for i, v in enumerate(values):
        batch[i] = v
    return batch


def run(nodes, node_id="7", **kw):
    nodes.SymbioticaPick.hidden = types.SimpleNamespace(unique_id=node_id)
    return nodes.SymbioticaPick.execute(**kw)


def buffer_of(nodes, tmp_path, node_id="7"):
    from pipeline.pick_buffer import buffer_dir, list_entries
    return list_entries(buffer_dir(str(tmp_path / "output"), node_id))


class TestSchema:
    def test_images_are_optional(self, nodes_mod):
        """The whole point of the optional input: once the picks are made the
        generator branch is muted and the node still serves them from disk, so
        queueing the edit stage does not re-fire a paid render."""
        schema = nodes_mod.SymbioticaPick.GET_SCHEMA()
        images = next(i for i in schema.inputs if i.id == "images")
        assert images.optional is True

    def test_the_picked_output_is_a_list(self, nodes_mod):
        """A list, not a batch: two picks of different sizes cannot stack into
        one tensor, and downstream should run once per approved image."""
        schema = nodes_mod.SymbioticaPick.GET_SCHEMA()
        assert schema.outputs[0].is_output_list is True

    def test_it_is_an_output_node(self, nodes_mod):
        """So the buffer can be filled on its own — "Queue Selected Output
        Node" on the picker collects candidates with nothing downstream yet."""
        assert nodes_mod.SymbioticaPick.GET_SCHEMA().is_output_node is True

    def test_it_is_registered(self, nodes_mod):
        assert nodes_mod.SymbioticaPick in nodes_mod.PIPELINE_NODE_CLASSES

    def test_the_widget_order_is_append_only(self, nodes_mod):
        """ComfyUI serialises widget values POSITIONALLY as `widgets_values`,
        so inserting a widget before an existing one shifts every value after
        it in every saved workflow. That is not cosmetic: adding `role` in the
        middle put the user's ticked-id JSON into `role` and his filter into
        `selection`, on a graph he had already saved. A new widget goes on the
        end. Changing this list means breaking someone's workflow.
        """
        schema = nodes_mod.SymbioticaPick.GET_SCHEMA()
        wires = {"images", "order"}
        widgets = [i.id for i in schema.inputs if i.id not in wires]
        assert widgets == ["get_new", "asset", "category", "selection",
                           "view", "role", "folder", "phase"]


class TestCollecting:
    def test_every_frame_becomes_a_candidate(self, nodes_mod, tmp_path):
        run(nodes_mod, images=frames(0.1, 0.2, 0.3))
        assert len(buffer_of(nodes_mod, tmp_path)) == 3

    def test_separate_runs_stack_up_instead_of_overwriting(self, nodes_mod, tmp_path):
        """Generating the same recipe three times is three candidates. This is
        the behaviour the node exists for."""
        run(nodes_mod, images=frames(0.1))
        run(nodes_mod, images=frames(0.2))
        run(nodes_mod, images=frames(0.3))
        assert len(buffer_of(nodes_mod, tmp_path)) == 3

    def test_a_replayed_frame_does_not_stack_up(self, nodes_mod, tmp_path):
        """Queueing a downstream node replays the generator from ComfyUI's
        cache, handing the picker the identical frame again."""
        run(nodes_mod, images=frames(0.1, 0.2))
        run(nodes_mod, images=frames(0.1, 0.2))
        assert len(buffer_of(nodes_mod, tmp_path)) == 2

    def test_a_single_frame_and_a_list_are_both_accepted(self, nodes_mod, tmp_path):
        run(nodes_mod, images=torch.full((4, 4, 3), 0.4))
        run(nodes_mod, images=[frames(0.5), frames(0.6)])
        assert len(buffer_of(nodes_mod, tmp_path)) == 3

    def test_no_images_records_nothing_and_does_not_raise(self, nodes_mod, tmp_path):
        out = run(nodes_mod, images=None)
        assert out.args[0] == []
        assert buffer_of(nodes_mod, tmp_path) == []

    def test_two_pickers_keep_separate_buffers(self, nodes_mod, tmp_path):
        """One after generation and one after the edit must never show each
        other's images."""
        run(nodes_mod, node_id="1", images=frames(0.1))
        run(nodes_mod, node_id="2", images=frames(0.2))
        assert len(buffer_of(nodes_mod, tmp_path, "1")) == 1
        assert len(buffer_of(nodes_mod, tmp_path, "2")) == 1


class TestAFannedOutLaneIsOneRun:
    """Found live: one image ticked, three in the preview downstream. The lane
    above the picker fans out, so ComfyUI ran the node once per item and each
    execution re-emitted the same single pick."""

    def test_the_schema_takes_the_whole_run_at_once(self, nodes_mod):
        assert nodes_mod.SymbioticaPick.GET_SCHEMA().is_input_list is True

    def test_a_fanned_out_lane_records_every_item_in_one_execution(self, nodes_mod,
                                                                   tmp_path):
        out = run(nodes_mod, images=[frames(0.1), frames(0.2), frames(0.3)])
        assert len(buffer_of(nodes_mod, tmp_path)) == 3
        assert out.args[0] == []

    def test_one_tick_leaves_the_node_once_not_once_per_item(self, nodes_mod,
                                                             tmp_path):
        run(nodes_mod, images=[frames(0.1), frames(0.2), frames(0.3)])
        ident = buffer_of(nodes_mod, tmp_path)[0]["id"]
        out = run(nodes_mod, images=[frames(0.1), frames(0.2), frames(0.3)],
                  selection=[json.dumps([ident])])
        assert len(out.args[0]) == 1

    def test_widgets_arriving_as_lists_of_one_are_unwrapped(self, nodes_mod,
                                                            tmp_path):
        """is_input_list hands EVERY input in as a list, widgets included."""
        run(nodes_mod, images=[frames(0.4)], asset=["cake"], category=["Food"],
            order=[{"feature": "Halloween", "month": "2026-10"}])
        entry = buffer_of(nodes_mod, tmp_path)[0]
        assert entry["group"] == "Halloween / Food / cake"

    def test_each_item_is_tagged_with_its_own_label(self, nodes_mod, tmp_path):
        run(nodes_mod, images=[frames(0.1), frames(0.2)],
            asset=["cake", "pie"], category=["Food", "Food"])
        assert [e["asset"] for e in buffer_of(nodes_mod, tmp_path)] == ["cake", "pie"]

    def test_one_label_covers_a_whole_batch_of_variants(self, nodes_mod, tmp_path):
        """Three variants of one asset: the label must not run out after the
        first image and leave the rest untagged."""
        run(nodes_mod, images=[frames(0.1, 0.2, 0.3)], asset=["cake"])
        assert [e["asset"] for e in buffer_of(nodes_mod, tmp_path)] == \
            ["cake", "cake", "cake"]

    def test_fewer_labels_than_items_repeats_the_first(self, nodes_mod, tmp_path):
        run(nodes_mod, images=[frames(0.1), frames(0.2)], asset=["cake"])
        assert [e["asset"] for e in buffer_of(nodes_mod, tmp_path)] == \
            ["cake", "cake"]


class TestTagging:
    def test_candidates_carry_the_asset_they_were_made_for(self, nodes_mod, tmp_path):
        run(nodes_mod, images=frames(0.1), asset="pumpkin-cake", category="Food",
            order={"feature": "Halloween", "month": "2026-10"})
        entry = buffer_of(nodes_mod, tmp_path)[0]
        assert entry["asset"] == "pumpkin-cake"
        assert entry["category"] == "Food"
        assert entry["group"] == "Halloween / Food / pumpkin-cake"

    def test_an_order_that_is_not_a_dict_is_ignored(self, nodes_mod, tmp_path):
        run(nodes_mod, images=frames(0.1), asset="cake", order="nonsense")
        assert buffer_of(nodes_mod, tmp_path)[0]["group"] == "cake"

    def test_untagged_candidates_still_group(self, nodes_mod, tmp_path):
        run(nodes_mod, images=frames(0.1))
        assert buffer_of(nodes_mod, tmp_path)[0]["group"] == "untagged"


class TestPicking:
    def test_nothing_ticked_sends_nothing_forward(self, nodes_mod):
        """Not an error: it is what every collecting run looks like before the
        images have been looked at. An empty list runs nothing downstream."""
        out = run(nodes_mod, images=frames(0.1, 0.2))
        assert out.args[0] == []

    def test_only_the_ticked_candidates_leave_the_node(self, nodes_mod, tmp_path):
        run(nodes_mod, images=frames(0.25, 0.5, 0.75))
        ids = [e["id"] for e in buffer_of(nodes_mod, tmp_path)]
        out = run(nodes_mod, images=None,
                  selection=json.dumps([ids[0], ids[2]]))
        picked = out.args[0]
        assert len(picked) == 2
        assert picked[0].shape == (1, 4, 4, 3)
        assert round(float(picked[0].max()), 2) == 0.25
        assert round(float(picked[1].max()), 2) == 0.75

    def test_picks_survive_the_generator_being_muted(self, nodes_mod, tmp_path):
        """The case the optional input exists for: no images on the wire at
        all, and the approved renders still come out."""
        run(nodes_mod, images=frames(0.5))
        ident = buffer_of(nodes_mod, tmp_path)[0]["id"]
        out = run(nodes_mod, images=None, selection=json.dumps([ident]))
        assert len(out.args[0]) == 1

    def test_a_comma_separated_selection_is_accepted(self, nodes_mod, tmp_path):
        """So the widget stays usable by hand, not only by the canvas."""
        run(nodes_mod, images=frames(0.5, 0.9))
        ids = [e["id"] for e in buffer_of(nodes_mod, tmp_path)]
        out = run(nodes_mod, images=None, selection=f"{ids[0]}, {ids[1]}")
        assert len(out.args[0]) == 2

    def test_an_unparseable_selection_means_nothing_ticked(self, nodes_mod):
        run(nodes_mod, images=frames(0.5))
        assert run(nodes_mod, images=None, selection="{").args[0] == []

    def test_a_tick_whose_image_was_deleted_is_skipped(self, nodes_mod, tmp_path):
        run(nodes_mod, images=frames(0.5))
        ident = buffer_of(nodes_mod, tmp_path)[0]["id"]
        from pipeline.pick_buffer import buffer_dir, drop
        drop(buffer_dir(str(tmp_path / "output"), "7"), [ident])
        assert run(nodes_mod, images=None, selection=json.dumps([ident])).args[0] == []


class TestLookingAtAPickMustNotPayForIt:
    """Found live: queueing the stage AFTER the picker re-ran the stage BEFORE
    it. ComfyUI resolves an ordinary input by executing whatever produces it,
    and an API generator that does not cache re-renders every time — a fixed
    seed does not help when the node is asked for a value at all."""

    def test_the_images_input_is_lazy(self, nodes_mod):
        schema = nodes_mod.SymbioticaPick.GET_SCHEMA()
        images = next(i for i in schema.inputs if i.id == "images")
        assert images.lazy is True

    def test_collecting_asks_for_the_wire(self, nodes_mod):
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=None, get_new=[True]) == ["images"]

    def test_not_collecting_never_asks_for_the_wire(self, nodes_mod):
        """The whole point: an input that is not requested is never computed,
        so nothing upstream runs."""
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=None, get_new=[False]) == []

    def test_an_already_resolved_wire_is_not_asked_for_again(self, nodes_mod):
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=[frames(0.1)], get_new=[True]) == []

    def test_not_collecting_records_nothing(self, nodes_mod, tmp_path):
        run(nodes_mod, images=[frames(0.1)], get_new=[False])
        assert buffer_of(nodes_mod, tmp_path) == []

    def test_not_collecting_still_sends_the_picks_on(self, nodes_mod, tmp_path):
        run(nodes_mod, images=[frames(0.5)], get_new=[True])
        ident = buffer_of(nodes_mod, tmp_path)[0]["id"]
        out = run(nodes_mod, images=None, get_new=[False],
                  selection=[json.dumps([ident])])
        assert len(out.args[0]) == 1

    def test_get_new_defaults_to_on(self, nodes_mod, tmp_path):
        run(nodes_mod, images=[frames(0.1)])
        assert len(buffer_of(nodes_mod, tmp_path)) == 1


class TestAskingForTheWireOnlyWhenThereIsOne:
    """Two live failures, one loud and one silent. Asking for an input with no
    link fails the whole graph with NodeInputError. And under is_input_list an
    unevaluated lazy input arrives as `(None,)`, so testing for `None` read it
    as a real value, never requested the wire, and recorded nothing while the
    run reported success."""

    def test_an_unevaluated_input_list_input_is_a_tuple_of_none(self, nodes_mod):
        assert nodes_mod._unevaluated((None,)) is True
        assert nodes_mod._unevaluated([None, None]) is True
        assert nodes_mod._unevaluated(None) is True

    def test_a_real_value_is_not_mistaken_for_an_unevaluated_one(self, nodes_mod):
        assert nodes_mod._unevaluated([frames(0.1)]) is False
        assert nodes_mod._unevaluated([]) is False

    def _wire(self, nodes_mod, images):
        node = {"inputs": {} if images is None else {"images": images}}
        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(
            unique_id="7", prompt={"7": node}, dynprompt=None)

    def test_a_connected_but_unevaluated_wire_is_requested(self, nodes_mod):
        self._wire(nodes_mod, ["9", 0])
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=(None,), get_new=[True]) == ["images"]

    def test_an_unconnected_wire_is_never_requested(self, nodes_mod):
        """A picker sitting on the canvas before anything is wired to it is an
        ordinary state, not a reason to fail the graph."""
        self._wire(nodes_mod, None)
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=(None,), get_new=[True]) == []

    def test_dynprompt_answers_when_the_raw_prompt_is_absent(self, nodes_mod):
        class _Dyn:
            def get_node(self, node_id):
                return {"inputs": {"images": ["9", 0]}} if node_id == "7" else None

        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(
            unique_id="7", prompt=None, dynprompt=_Dyn())
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=(None,), get_new=[True]) == ["images"]

    def test_an_unanswerable_lookup_still_asks_rather_than_collecting_nothing(
            self, nodes_mod):
        """Silently never collecting is the worse failure of the two: it looks
        like a working run that produced nothing."""
        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(unique_id=None)
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=(None,), get_new=[True]) == ["images"]

    def test_a_broken_prompt_lookup_does_not_escape(self, nodes_mod):
        class _Boom:
            def get_node(self, node_id):
                raise RuntimeError("no such node")

        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(
            unique_id="7", prompt=None, dynprompt=_Boom())
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=(None,), get_new=[True]) == ["images"]

    def test_collecting_off_never_asks_even_with_a_wire(self, nodes_mod):
        self._wire(nodes_mod, ["9", 0])
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=(None,), get_new=[False]) == []

    def test_an_unevaluated_wire_records_nothing_rather_than_a_blank(self, nodes_mod,
                                                                     tmp_path):
        run(nodes_mod, images=(None,), get_new=[True])
        assert buffer_of(nodes_mod, tmp_path) == []


class TestChainingTwoPickers:
    def test_the_picks_of_one_become_the_candidates_of_the_next(self, nodes_mod,
                                                                tmp_path):
        run(nodes_mod, node_id="1", images=[frames(0.2, 0.4, 0.6)])
        first = [e["id"] for e in buffer_of(nodes_mod, tmp_path, "1")]
        passed = run(nodes_mod, node_id="1", images=None, get_new=[False],
                     selection=[json.dumps([first[0], first[2]])]).args[0]
        run(nodes_mod, node_id="2", images=passed)
        second = buffer_of(nodes_mod, tmp_path, "2")
        assert len(second) == 2
        # The same two images, not merely the same count.
        assert {e["id"] for e in second} == {first[0], first[2]}


class TestTransparency:
    def test_a_four_channel_pick_comes_out_with_four_channels(self, nodes_mod,
                                                              tmp_path):
        """The picker must not be the thing that undoes the background removal
        it was used to approve."""
        batch = torch.zeros(1, 4, 4, 4)
        batch[..., :3] = 0.5
        batch[..., 3] = 0.0
        run(nodes_mod, images=batch)
        ident = buffer_of(nodes_mod, tmp_path)[0]["id"]
        picked = run(nodes_mod, images=None,
                     selection=json.dumps([ident])).args[0]
        assert picked[0].shape == (1, 4, 4, 4)
        assert float(picked[0][..., 3].max()) == 0.0


class TestOnePickerPerPass:
    """One Pick in the Base image group, one in Edit, one in Export."""

    def test_the_pass_is_a_selector_with_the_three_passes(self, nodes_mod):
        schema = nodes_mod.SymbioticaPick.GET_SCHEMA()
        phase = next(i for i in schema.inputs if i.id == "phase")
        assert phase.options == ["", "base", "edit", "export"]

    def test_it_defaults_to_unpinned(self, nodes_mod):
        """A node that has not been assigned a pass keeps showing everything
        rather than silently nothing."""
        schema = nodes_mod.SymbioticaPick.GET_SCHEMA()
        assert next(i for i in schema.inputs if i.id == "phase").default == ""

    def test_what_a_pinned_picker_collects_is_stamped_with_its_pass(self, nodes_mod,
                                                                    tmp_path):
        run(nodes_mod, images=[frames(0.3)], asset=["cake"], phase=["export"])
        assert buffer_of(nodes_mod, tmp_path)[0]["phase"] == "export"

    def test_an_unpinned_picker_stamps_nothing(self, nodes_mod, tmp_path):
        run(nodes_mod, images=[frames(0.3)], asset=["cake"])
        assert buffer_of(nodes_mod, tmp_path)[0]["phase"] == ""

    def test_the_pass_does_not_change_the_group_label(self, nodes_mod, tmp_path):
        """Each picker is pinned to one pass already, so repeating it in every
        label is noise."""
        run(nodes_mod, images=[frames(0.3)], asset=["cake"], category=["Food"],
            phase=["edit"])
        assert buffer_of(nodes_mod, tmp_path)[0]["group"] == "Food / cake"


class TestTheFolderComesFromTheWireNotFromTyping:
    """`save_paths` from Order Assets is `month/feature/category/asset` — the
    tail of the tree the renders are already filed in — and it moves with the
    selected asset. Typing that path by hand goes stale the moment the asset
    changes."""

    def renders(self, tmp_path, rel, names=("a.png",), colour=10):
        from PIL import Image
        folder = tmp_path / "output" / rel
        folder.mkdir(parents=True, exist_ok=True)
        for i, name in enumerate(names):
            Image.new("RGB", (6, 6), (colour + i, 0, 0)).save(folder / name)
        return folder

    def test_a_relative_save_path_resolves_under_the_output_directory(self, nodes_mod,
                                                                      tmp_path):
        self.renders(tmp_path, "October/Mini 3/Food/Frankencrisps",
                     ("a.png", "b.png"))
        run(nodes_mod, folder=["October/Mini 3/Food/Frankencrisps"])
        assert len(buffer_of(nodes_mod, tmp_path)) == 2

    def test_the_tags_come_off_that_path(self, nodes_mod, tmp_path):
        self.renders(tmp_path, "October/Mini 3/Food/Frankencrisps")
        run(nodes_mod, folder=["October/Mini 3/Food/Frankencrisps"])
        entry = buffer_of(nodes_mod, tmp_path)[0]
        assert entry["group"] == "Mini 3 / Food / Frankencrisps"

    def test_switching_asset_reads_the_new_folder(self, nodes_mod, tmp_path):
        """The whole point of wiring it: no field to go back and edit."""
        self.renders(tmp_path, "Oct/Ev/Food/Frankencrisps", colour=10)
        self.renders(tmp_path, "Oct/Ev/Food/Pops", colour=200)
        run(nodes_mod, folder=["Oct/Ev/Food/Frankencrisps"])
        run(nodes_mod, folder=["Oct/Ev/Food/Pops"])
        assert {e["asset"] for e in buffer_of(nodes_mod, tmp_path)} == \
            {"Frankencrisps", "Pops"}

    def test_a_fanned_out_lane_reads_every_asset_folder_once(self, nodes_mod,
                                                             tmp_path):
        self.renders(tmp_path, "Oct/Ev/Food/A", colour=10)
        self.renders(tmp_path, "Oct/Ev/Food/B", colour=200)
        run(nodes_mod, folder=["Oct/Ev/Food/A", "Oct/Ev/Food/B",
                               "Oct/Ev/Food/A"])
        assert len(buffer_of(nodes_mod, tmp_path)) == 2

    def test_an_unchanged_folder_is_not_read_twice(self, nodes_mod, tmp_path):
        """Re-reading four hundred renders on every run means four hundred PIL
        opens for nothing."""
        from pipeline.pick_buffer import buffer_dir, read_marks
        self.renders(tmp_path, "Oct/Ev/Food/A")
        run(nodes_mod, folder=["Oct/Ev/Food/A"])
        marks = read_marks(buffer_dir(str(tmp_path / "output"), "7"))
        assert len(marks) == 1
        run(nodes_mod, folder=["Oct/Ev/Food/A"])
        assert len(buffer_of(nodes_mod, tmp_path)) == 1

    def test_a_new_render_in_a_read_folder_is_picked_up(self, nodes_mod, tmp_path):
        self.renders(tmp_path, "Oct/Ev/Food/A", ("a.png",), colour=10)
        run(nodes_mod, folder=["Oct/Ev/Food/A"])
        self.renders(tmp_path, "Oct/Ev/Food/A", ("b.png",), colour=200)
        run(nodes_mod, folder=["Oct/Ev/Food/A"])
        assert len(buffer_of(nodes_mod, tmp_path)) == 2

    def test_a_pinned_picker_reads_only_its_own_pass(self, nodes_mod, tmp_path):
        self.renders(tmp_path, "Oct/Ev/Food/A/base", colour=10)
        self.renders(tmp_path, "Oct/Ev/Food/A/export", colour=200)
        run(nodes_mod, folder=["Oct/Ev/Food/A"], phase=["export"])
        entries = buffer_of(nodes_mod, tmp_path)
        assert len(entries) == 1 and entries[0]["phase"] == "export"

    def test_a_folder_that_is_not_there_does_not_fail_the_graph(self, nodes_mod,
                                                                tmp_path):
        out = run(nodes_mod, folder=["Oct/Ev/Food/Nothing"])
        assert out.args[0] == []
        assert buffer_of(nodes_mod, tmp_path) == []

    def test_no_folder_reads_nothing(self, nodes_mod, tmp_path):
        run(nodes_mod, folder=[""], images=[frames(0.5)])
        assert len(buffer_of(nodes_mod, tmp_path)) == 1


class TestTheFolderNeedsNoWiringAtAll:
    """"what the f do I have to connect to folder mate?" — nothing. The node is
    already wired to the asset, the category and the order, which is exactly
    what `save_paths` builds the folder from."""

    def renders(self, tmp_path, rel, names=("a.png",), colour=10):
        from PIL import Image
        folder = tmp_path / "output" / rel
        folder.mkdir(parents=True, exist_ok=True)
        for i, name in enumerate(names):
            Image.new("RGB", (6, 6), (colour + i, 0, 0)).save(folder / name)
        return folder

    def test_the_asset_folder_is_read_with_no_folder_set(self, nodes_mod, tmp_path):
        self.renders(tmp_path, "October/Mini 1/Food - 3 stages/Spookies",
                     ("a.png", "b.png"))
        run(nodes_mod, asset=["Spookies"], category=["Food - 3 stages"],
            order=[{"month": "October", "feature": "Mini 1"}])
        assert len(buffer_of(nodes_mod, tmp_path)) == 2

    def test_switching_asset_reads_the_new_asset_folder(self, nodes_mod, tmp_path):
        self.renders(tmp_path, "October/Mini 1/Food/Spookies", colour=10)
        self.renders(tmp_path, "October/Mini 1/Food/Popsicle", colour=200)
        order = [{"month": "October", "feature": "Mini 1"}]
        run(nodes_mod, asset=["Spookies"], category=["Food"], order=order)
        run(nodes_mod, asset=["Popsicle"], category=["Food"], order=order)
        assert {e["asset"] for e in buffer_of(nodes_mod, tmp_path)} == \
            {"Spookies", "Popsicle"}

    def test_an_explicit_folder_still_wins(self, nodes_mod, tmp_path):
        self.renders(tmp_path, "October/Mini 1/Food/Spookies", colour=10)
        self.renders(tmp_path, "somewhere/else", colour=200)
        run(nodes_mod, asset=["Spookies"], category=["Food"],
            order=[{"month": "October", "feature": "Mini 1"}],
            folder=["somewhere/else"])
        assert len(buffer_of(nodes_mod, tmp_path)) == 1

    def test_a_pinned_pass_narrows_the_derived_folder_too(self, nodes_mod, tmp_path):
        self.renders(tmp_path, "Oct/Ev/Food/Cake/base", colour=10)
        self.renders(tmp_path, "Oct/Ev/Food/Cake/export", colour=200)
        run(nodes_mod, asset=["Cake"], category=["Food"], phase=["export"],
            order=[{"month": "Oct", "feature": "Ev"}])
        entries = buffer_of(nodes_mod, tmp_path)
        assert len(entries) == 1 and entries[0]["phase"] == "export"

    def test_too_little_context_reads_nothing(self, nodes_mod, tmp_path):
        """Reading a whole month because only the month is known would pull in
        every asset of every event."""
        self.renders(tmp_path, "October/Mini 1/Food/Spookies")
        run(nodes_mod, order=[{"month": "October", "feature": "Mini 1"}])
        assert buffer_of(nodes_mod, tmp_path) == []

    def test_a_separator_in_a_name_does_not_deepen_the_tree(self, nodes_mod,
                                                            tmp_path):
        """It has to match the folder a save node actually wrote."""
        self.renders(tmp_path, "Oct/Ev/Food/Sign Board")
        run(nodes_mod, asset=["Sign / Board"], category=["Food"],
            order=[{"month": "Oct", "feature": "Ev"}])
        assert len(buffer_of(nodes_mod, tmp_path)) == 1


class TestSeeingWhatWasAlreadyMade:
    """"after refresh there is no way for me to see previous generation without
    re-generating" — the asset's own render folder is read whether or not the
    node is fetching, so looking costs nothing."""

    def renders(self, tmp_path, rel, names=("a.png",), colour=10):
        from PIL import Image
        folder = tmp_path / "output" / rel
        folder.mkdir(parents=True, exist_ok=True)
        for i, name in enumerate(names):
            Image.new("RGB", (6, 6), (colour + i, 0, 0)).save(folder / name)
        return folder

    def test_the_folder_is_read_even_with_get_new_off(self, nodes_mod, tmp_path):
        """This is the whole point: queueing the picker with fetching off asks
        nothing upstream, costs no render, and still surfaces every image
        already made for this asset."""
        self.renders(tmp_path, "Oct/Mini 1/Food/Spookies", ("a.png", "b.png"))
        run(nodes_mod, get_new=[False], asset=["Spookies"], category=["Food"],
            order=[{"month": "Oct", "feature": "Mini 1"}])
        assert len(buffer_of(nodes_mod, tmp_path)) == 2

    def test_fetching_off_still_takes_nothing_off_the_wire(self, nodes_mod,
                                                           tmp_path):
        self.renders(tmp_path, "Oct/Mini 1/Food/Spookies")
        run(nodes_mod, get_new=[False], images=[frames(0.5)],
            asset=["Spookies"], category=["Food"],
            order=[{"month": "Oct", "feature": "Mini 1"}])
        # The folder's one image, and nothing from the wire.
        assert len(buffer_of(nodes_mod, tmp_path)) == 1
