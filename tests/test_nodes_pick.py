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


def run(nodes, node_id="7", source="SymbioticaPick", **kw):
    """Execute the node with `images` coming from another picker by default.

    That is the only wire this node ever reads — a generator's output reaches
    it from disk, never through the wire — so a test that wants images to be
    recorded has to say where they came from.
    """
    nodes.SymbioticaPick.hidden = types.SimpleNamespace(
        unique_id=node_id,
        prompt={node_id: {"inputs": {"images": ["99", 0]}},
                "99": {"class_type": source}},
        dynprompt=None)
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

    def test_an_unevaluated_wire_is_asked_for_whatever_feeds_it(self, nodes_mod):
        """Refusing every source but another picker was an over-correction:
        "fantastic mate, now no new image can come in". What a picker is wired
        to is a save or preview node, which ComfyUI runs on every queue anyway
        — asking for its output costs nothing that was not already spent."""
        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(
            unique_id="7",
            prompt={"7": {"inputs": {"images": ["9", 0]}},
                    "9": {"class_type": "SaveImage"}}, dynprompt=None)
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=None) == ["images"]

    def test_an_already_resolved_wire_is_not_asked_for_again(self, nodes_mod):
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=[frames(0.1)], get_new=[True]) == []

    def test_images_off_a_save_node_are_recorded(self, nodes_mod, tmp_path):
        """His actual lane: Slice Cells → Save Image → picker."""
        run(nodes_mod, images=[frames(0.1)], source="SaveImage")
        assert len(buffer_of(nodes_mod, tmp_path)) == 1

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

    def _wire(self, nodes_mod, images, source="SymbioticaPick"):
        node = {"inputs": {} if images is None else {"images": images}}
        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(
            unique_id="7",
            prompt={"7": node, "9": {"class_type": source}}, dynprompt=None)

    def test_a_connected_but_unevaluated_picker_wire_is_requested(self, nodes_mod):
        self._wire(nodes_mod, ["9", 0])
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=(None,)) == ["images"]

    def test_an_unconnected_wire_is_never_requested(self, nodes_mod):
        """A picker sitting on the canvas before anything is wired to it is an
        ordinary state, not a reason to fail the graph."""
        self._wire(nodes_mod, None)
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=(None,), get_new=[True]) == []

    def test_dynprompt_answers_when_the_raw_prompt_is_absent(self, nodes_mod):
        class _Dyn:
            def get_node(self, node_id):
                if node_id == "7":
                    return {"inputs": {"images": ["9", 0]}}
                if node_id == "9":
                    return {"class_type": "SymbioticaPick"}
                return None

        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(
            unique_id="7", prompt=None, dynprompt=_Dyn())
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=(None,)) == ["images"]

    def test_an_unanswerable_lookup_asks_for_nothing(self, nodes_mod):
        """Guessing wrong here costs a render, so silence means no."""
        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(unique_id=None)
        assert nodes_mod.SymbioticaPick.check_lazy_status(images=(None,)) == []

    def test_a_broken_prompt_lookup_does_not_escape(self, nodes_mod):
        class _Boom:
            def get_node(self, node_id):
                raise RuntimeError("no such node")

        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(
            unique_id="7", prompt=None, dynprompt=_Boom())
        assert nodes_mod.SymbioticaPick.check_lazy_status(images=(None,)) == []

    def test_a_generator_behind_the_wire_is_asked_too(self, nodes_mod):
        """Not because renders are free, but because refusing them is not what
        made them stop: `SymbioticaAssetRefs` fingerprinting a folder that a
        picker's thumbnails were written into was, and that is fixed."""
        self._wire(nodes_mod, ["9", 0], source="GeminiNanoBanana2V2")
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=(None,)) == ["images"]

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

    def test_the_folder_and_the_wire_both_land(self, nodes_mod, tmp_path):
        self.renders(tmp_path, "Oct/Mini 1/Food/Spookies")
        run(nodes_mod, source="GeminiNanoBanana2V2", images=[frames(0.5)],
            asset=["Spookies"], category=["Food"],
            order=[{"month": "Oct", "feature": "Mini 1"}])
        # The folder's one image AND the wire's one image.
        assert len(buffer_of(nodes_mod, tmp_path)) == 2

    def test_renders_saved_under_a_filename_prefix_are_found(self, nodes_mod,
                                                              tmp_path):
        """The layout ComfyUI actually writes. A Save Image node given
        `Oct/Mini 1/Food/Spookies` files `Food/Spookies_00001_.png` — the last
        segment names the FILE, not a folder — so the folder a picker derives
        for its asset does not exist. Reading only that folder is what showed
        "no candidates yet" while 17 renders sat one level up."""
        self.renders(tmp_path, "Oct/Mini 1/Food",
                     ("Spookies_00001_.png", "Spookies_00002_.png"))
        run(nodes_mod, asset=["Spookies"], category=["Food"],
            order=[{"month": "Oct", "feature": "Mini 1"}])
        entries = buffer_of(nodes_mod, tmp_path)
        assert len(entries) == 2
        # Tagged as this asset even though no folder said so, or the panel
        # would file them under the category and the picker would show none.
        assert {e["asset"] for e in entries} == {"Spookies"}

    def test_another_assets_files_in_the_same_folder_are_left_alone(
            self, nodes_mod, tmp_path):
        self.renders(tmp_path, "Oct/Mini 1/Food",
                     ("Spookies_00001_.png", "Ghostly Jelly Cake_00001_.png",
                      "Spookies Deluxe_00001_.png"))
        run(nodes_mod, asset=["Spookies"], category=["Food"],
            order=[{"month": "Oct", "feature": "Mini 1"}])
        assert len(buffer_of(nodes_mod, tmp_path)) == 1

    def test_a_prefix_read_is_tagged_with_what_the_node_is_wired_to(
            self, nodes_mod, tmp_path):
        """Found live. Reading by prefix means the file sits one level up, so
        the path names the CATEGORY where it used to name the asset — and a
        candidate whose group does not match the one on screen is filed
        invisibly and never leaves the node. The node states what it knows."""
        self.renders(tmp_path, "elsewhere", ("Spookies_00001_.png",))
        run(nodes_mod, folder=[str(tmp_path / "output" / "elsewhere"
                                   / "Spookies")],
            asset=["Spookies"], category=["Food"],
            order=[{"month": "Oct", "feature": "Mini 1"}])
        entry = buffer_of(nodes_mod, tmp_path)[0]
        # Browsing somewhere else, so only the name is claimed from the path.
        assert entry["asset"] == "Spookies"

    def test_its_own_assets_prefixed_renders_carry_the_wired_context(
            self, nodes_mod, tmp_path):
        self.renders(tmp_path, "Oct/Mini 1/Food", ("Spookies_00001_.png",))
        out = run(nodes_mod, asset=["Spookies"], category=["Food"],
                  order=[{"month": "Oct", "feature": "Mini 1"}])
        entry = buffer_of(nodes_mod, tmp_path)[0]
        assert (entry["asset"], entry["category"], entry["feature"],
                entry["month"]) == ("Spookies", "Food", "Mini 1", "Oct")
        # And therefore it is emitted, rather than filtered out as belonging
        # to some other group than the one being worked on.
        assert len(run(nodes_mod, asset=["Spookies"], category=["Food"],
                       order=[{"month": "Oct", "feature": "Mini 1"}],
                       selection=[json.dumps([entry["id"]])]).args[0]) == 1
        assert out.args[0] == []

    def test_a_typed_folder_falls_back_to_the_prefix_too(self, nodes_mod,
                                                          tmp_path):
        """Pasting the save node's own prefix into `folder` is the natural
        thing to try, and it named nothing that exists."""
        self.renders(tmp_path, "Oct/Mini 1/Food", ("Spookies_00001_.png",))
        run(nodes_mod, folder=["Oct/Mini 1/Food/Spookies"])
        assert len(buffer_of(nodes_mod, tmp_path)) == 1

    def test_both_layouts_are_read_at_once(self, nodes_mod, tmp_path):
        """Once picks are kept under `…/Spookies/Base`, that folder EXISTS —
        and reading it instead of the prefixed files would stop every new
        render from arriving. Both, always."""
        self.renders(tmp_path, "Oct/Mini 1/Food", ("Spookies_00001_.png",))
        self.renders(tmp_path, "Oct/Mini 1/Food/Spookies", ("older.png",),
                     colour=90)
        run(nodes_mod, asset=["Spookies"], category=["Food"],
            order=[{"month": "Oct", "feature": "Mini 1"}])
        assert len(buffer_of(nodes_mod, tmp_path)) == 2


class TestPicksAreKeptWhereTheWorkLives:
    """"images picked should land in 'October/Mini 1 — Ghostly Goodies/Food -
    3 stages/Spookies/Base' so we only keep what was good in these folders"."""

    def collected(self, nodes_mod, tmp_path, phase=None, **kw):
        common = {"asset": ["Spookies"], "category": ["Food"],
                  "order": [{"month": "Oct", "feature": "Mini 1"}]}
        if phase:
            common["phase"] = [phase]
        run(nodes_mod, images=[frames(0.4)], **common, **kw)
        ident = buffer_of(nodes_mod, tmp_path)[0]["id"]
        return common, ident

    def kept_in(self, tmp_path, *parts):
        return tmp_path / "output" / "Oct" / "Mini 1" / "Food" / "Spookies" \
            / os.path.join(*parts)

    def test_a_tick_is_copied_into_the_assets_own_folder(self, nodes_mod,
                                                          tmp_path):
        common, ident = self.collected(nodes_mod, tmp_path)
        run(nodes_mod, **common, selection=[json.dumps([ident])])
        assert len(list(self.kept_in(tmp_path, "Base").iterdir())) == 1

    def test_the_pass_names_the_folder(self, nodes_mod, tmp_path):
        common, ident = self.collected(nodes_mod, tmp_path, phase="export")
        run(nodes_mod, **common, selection=[json.dumps([ident])])
        assert self.kept_in(tmp_path, "Export").is_dir()

    def test_nothing_ticked_writes_nothing(self, nodes_mod, tmp_path):
        """Every collecting run before the images have been looked at, which
        must not leave an empty delivery folder behind."""
        common, _ = self.collected(nodes_mod, tmp_path)
        run(nodes_mod, **common, selection=[json.dumps([])])
        assert not self.kept_in(tmp_path, "Base").exists()

    def test_a_folder_to_read_is_not_a_folder_to_write_to(self, nodes_mod,
                                                           tmp_path):
        """`folder` names something to look at — pointing a picker at last
        month's work must not file this month's picks into it."""
        browsed = tmp_path / "output" / "elsewhere"
        browsed.mkdir(parents=True)
        common, ident = self.collected(nodes_mod, tmp_path)
        run(nodes_mod, **common, folder=[str(browsed)],
            selection=[json.dumps([ident])])
        assert list(browsed.iterdir()) == []
        assert self.kept_in(tmp_path, "Base").is_dir()

    def test_what_was_kept_does_not_come_back_as_a_new_candidate(
            self, nodes_mod, tmp_path):
        """The kept copy makes `…/Spookies` a real folder, which the next run
        reads. Identity is the pixels, so it is the image already held."""
        common, ident = self.collected(nodes_mod, tmp_path)
        run(nodes_mod, **common, selection=[json.dumps([ident])])
        run(nodes_mod, **common, selection=[json.dumps([ident])])
        assert len(buffer_of(nodes_mod, tmp_path)) == 1


class TestAChainOfPickersCostsNothing:
    """"pick edit still not showing the selected images from pick base though
    and it also triggers a fucking new generation" — both from one mistake:
    `get_new` refused to speak to another picker, not just to a generator."""

    def wire(self, nodes_mod, source_class):
        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(
            unique_id="7",
            prompt={"7": {"inputs": {"images": ["9", 0]}},
                    "9": {"class_type": source_class}},
            dynprompt=None)

    def test_a_picker_upstream_is_read_even_with_fetching_off(self, nodes_mod):
        """Taking another picker's picks costs nothing: it serves what it holds
        or declines its own input in turn."""
        self.wire(nodes_mod, "SymbioticaPick")
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=(None,), get_new=[False]) == ["images"]

    def test_an_unknowable_source_is_still_refused(self, nodes_mod):
        """Guessing wrong costs a render, so silence means no."""
        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(unique_id="7")
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=(None,), get_new=[False]) == []

    def test_the_picks_of_the_picker_upstream_are_actually_recorded(self,
                                                                    nodes_mod,
                                                                    tmp_path):
        """Requesting the wire buys nothing if execute then throws it away."""
        self.wire(nodes_mod, "SymbioticaPick")
        nodes_mod.SymbioticaPick.execute(images=[frames(0.3), frames(0.6)],
                                         get_new=[False])
        assert len(buffer_of(nodes_mod, tmp_path)) == 2

    def test_a_declined_wire_files_nothing_rather_than_a_blank(
            self, nodes_mod, tmp_path):
        """An unrequested lazy input arrives as `(None,)`, which is a value as
        far as list handling is concerned — filing it would put a candidate
        made of nothing in the buffer."""
        self.wire(nodes_mod, "GeminiNanoBanana2V2")
        nodes_mod.SymbioticaPick.execute(images=(None,), get_new=[False])
        assert buffer_of(nodes_mod, tmp_path) == []


class TestWhatYouSeeIsWhatComesOut:
    """"i have 3 assets selected in base and i get 6 fucking images 3 being
    from somewhere else" — ticks survive a switch to another asset, so a picker
    used for two assets held ticks for both and emitted all of them."""

    def two_assets(self, nodes_mod, tmp_path):
        run(nodes_mod, images=[frames(0.1), frames(0.2)], asset=["Spookies"],
            category=["Food"], order=[{"month": "Oct", "feature": "Mini 1"}])
        run(nodes_mod, images=[frames(0.7), frames(0.8)], asset=["Frankencrisps"],
            category=["Food"], order=[{"month": "Oct", "feature": "Mini 3"}])
        by_asset = {}
        for e in buffer_of(nodes_mod, tmp_path):
            by_asset.setdefault(e["asset"], []).append(e["id"])
        return by_asset

    def test_only_the_ticks_of_the_asset_being_worked_on_leave(self, nodes_mod,
                                                               tmp_path):
        by_asset = self.two_assets(nodes_mod, tmp_path)
        every_tick = by_asset["Spookies"] + by_asset["Frankencrisps"]
        out = run(nodes_mod, asset=["Spookies"], category=["Food"],
                  order=[{"month": "Oct", "feature": "Mini 1"}],
                  selection=[json.dumps(every_tick)])
        assert len(out.args[0]) == len(by_asset["Spookies"]) == 2

    def test_switching_asset_switches_which_ticks_are_emitted(self, nodes_mod,
                                                              tmp_path):
        by_asset = self.two_assets(nodes_mod, tmp_path)
        every_tick = by_asset["Spookies"] + by_asset["Frankencrisps"]
        out = run(nodes_mod, asset=["Frankencrisps"], category=["Food"],
                  order=[{"month": "Oct", "feature": "Mini 3"}],
                  selection=[json.dumps(every_tick)])
        assert len(out.args[0]) == 2

    def test_a_pinned_pass_narrows_it_further(self, nodes_mod, tmp_path):
        run(nodes_mod, images=[frames(0.1)], asset=["Cake"], category=["Food"],
            phase=["base"], order=[{"month": "Oct", "feature": "Ev"}])
        run(nodes_mod, images=[frames(0.9)], asset=["Cake"], category=["Food"],
            phase=["edit"], order=[{"month": "Oct", "feature": "Ev"}])
        ids = [e["id"] for e in buffer_of(nodes_mod, tmp_path)]
        out = run(nodes_mod, asset=["Cake"], category=["Food"], phase=["edit"],
                  order=[{"month": "Oct", "feature": "Ev"}],
                  selection=[json.dumps(ids)])
        assert len(out.args[0]) == 1

    def test_with_no_context_every_tick_still_leaves(self, nodes_mod, tmp_path):
        """An untagged picker has no asset to narrow to, and silently emitting
        nothing would be worse than emitting what was ticked."""
        run(nodes_mod, images=[frames(0.1), frames(0.2)])
        ids = [e["id"] for e in buffer_of(nodes_mod, tmp_path)]
        out = run(nodes_mod, selection=[json.dumps(ids)])
        assert len(out.args[0]) == 2
