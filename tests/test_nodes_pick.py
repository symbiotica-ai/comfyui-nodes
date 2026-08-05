# ABOUTME: Node-face tests for Symbiotica Pick — which folder it lists, which of
# ABOUTME: those files leave the node, and where the approved ones are kept.
import importlib
import json
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


# The folder layout `save_paths` writes: month, then the event's full label.
EVENT_DIR = "Oct/Mini 1 — Ghostly Goodies"


def renders(tmp_path, rel, names, colour=10):
    folder = tmp_path / "output" / rel
    folder.mkdir(parents=True, exist_ok=True)
    for i, name in enumerate(names):
        Image.new("RGB", (6, 6), (colour + i, 0, 0)).save(folder / name)
    return folder


def run(nodes, node_id="7", **kw):
    nodes.SymbioticaPick.hidden = types.SimpleNamespace(unique_id=node_id)
    return nodes.SymbioticaPick.execute(**kw)


def spookies(nodes, tmp_path, **kw):
    """The node pointed at its own asset, the way his graph wires it: the
    save node's path on the one `folder` wire."""
    return run(nodes, save_path=[f"{EVENT_DIR}/Food/Spookies"], **kw)


class TestSchema:
    def test_the_mode_is_a_selector_of_the_two_shapes(self, nodes_mod):
        schema = nodes_mod.SymbioticaPick.GET_SCHEMA()
        mode = next(i for i in schema.inputs if i.id == "mode")
        assert mode.options == ["multiple", "single"]
        assert mode.default == "multiple"

    def test_the_widget_order_is_append_only(self, nodes_mod):
        """ComfyUI serialises widget values POSITIONALLY as `widgets_values`,
        so inserting a widget before an existing one shifts every value after
        it in every saved workflow. The layout was stripped to one wire once —
        pick.js carries the migration for graphs saved before that — and from
        here a new widget goes on the end.
        """
        schema = nodes_mod.SymbioticaPick.GET_SCHEMA()
        widgets = [i.id for i in schema.inputs if i.id != "images"]
        assert widgets == ["save_path", "selection", "view", "mode", "stage"]

    def test_the_picked_output_is_a_list(self, nodes_mod):
        """A list, not a batch: two picks of different sizes cannot stack into
        one tensor, and downstream should run once per approved image."""
        assert nodes_mod.SymbioticaPick.GET_SCHEMA().outputs[0].is_output_list \
            is True

    def test_it_is_an_output_node(self, nodes_mod):
        """So it can be queued on its own — "Queue Selected Output Node" lists
        the folder and sends the ticks on with nothing downstream yet."""
        assert nodes_mod.SymbioticaPick.GET_SCHEMA().is_output_node is True

    def test_it_is_registered(self, nodes_mod):
        assert nodes_mod.SymbioticaPick in nodes_mod.PIPELINE_NODE_CLASSES


class TestItListsAgainOnEveryQueue:
    """"i created a new image i want to select in the pick 518 node — the
    generated images do not show up". The renders were on disk and the save
    node had run, but every queue reported `execution_cached: ['518']`: nothing
    the picker is wired to changes when a render is written, so ComfyUI had no
    reason to run it, and a picker that does not run does not list."""

    def test_it_reports_itself_as_always_changed(self, nodes_mod):
        """NaN is never equal to itself, which is how a node says "assume I
        changed". Cheap to honour — the whole execution is a listing."""
        first = nodes_mod.SymbioticaPick.fingerprint_inputs()
        assert first != first

    def test_the_wire_is_asked_for_so_the_save_node_goes_first(self, nodes_mod):
        """For its ORDER, not its value: `execute` ignores what arrives. With
        no dependency on the render lane, ComfyUI is free to run this node
        BEFORE the save node writes, and a fresh render then shows up one queue
        late, every time."""
        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(
            unique_id="7",
            prompt={"7": {"inputs": {"images": ["9", 0]}},
                    "9": {"class_type": "SaveImage"}})
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=(None,)) == ["images"]

    def test_an_unconnected_wire_is_never_asked_for(self, nodes_mod):
        """Asking for an input with no link fails the whole graph, and a picker
        with nothing wired to it is an ordinary state."""
        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(
            unique_id="7", prompt={"7": {"inputs": {}}})
        assert nodes_mod.SymbioticaPick.check_lazy_status(images=(None,)) == []

    def test_an_unanswerable_lookup_asks_for_nothing(self, nodes_mod):
        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(unique_id=None)
        assert nodes_mod.SymbioticaPick.check_lazy_status(images=(None,)) == []

    def test_a_resolved_wire_is_not_asked_for_again(self, nodes_mod):
        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(
            unique_id="7",
            prompt={"7": {"inputs": {"images": ["9", 0]}},
                    "9": {"class_type": "SaveImage"}})
        import torch
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=[torch.zeros(1, 4, 4, 3)]) == []


class TestItCannotCauseARender:
    """"I DONT WANT YOU TO GENERATE A NEW IMAGE EVERY SINGLE TIME". What a
    picker is wired to is a save or preview node — an output node ComfyUI runs
    on every queue anyway — and the value it hands over is thrown away: the
    images come off disk."""

    def test_the_images_input_is_lazy(self, nodes_mod):
        images = next(i for i in nodes_mod.SymbioticaPick.GET_SCHEMA().inputs
                      if i.id == "images")
        assert images.lazy is True

    def test_a_value_on_the_wire_is_ignored_rather_than_shown(self, nodes_mod,
                                                              tmp_path):
        """Nothing is stored, so an image with no file has nowhere to be: the
        node lists the folder and only the folder."""
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        import torch
        out = spookies(nodes_mod, tmp_path, images=[torch.zeros(1, 4, 4, 3)],
                       selection=[json.dumps(["Spookies_00001_.png"])])
        assert len(out.args[0]) == 1


class TestWhichFolderItLists:
    def test_a_folder_of_its_own_is_listed_as_itself(self, nodes_mod, tmp_path):
        """Both layouts are real: most assets are a filename prefix, but work
        saved a folder-per-asset still reads."""
        renders(tmp_path, f"{EVENT_DIR}/Food/Spookies", ("one.png", "two.png"))
        out = spookies(nodes_mod, tmp_path,
                       selection=[json.dumps(["one.png", "two.png"])])
        assert len(out.args[0]) == 2

    def test_a_typed_save_prefix_works_too(self, nodes_mod, tmp_path):
        """Pasting the save node's own prefix in is the natural thing to try,
        and it names nothing that exists."""
        renders(tmp_path, "elsewhere", ("Spookies_00001_.png",))
        out = run(nodes_mod, save_path=[str(tmp_path / "output" / "elsewhere"
                                         / "Spookies")],
                  selection=[json.dumps(["Spookies_00001_.png"])])
        assert len(out.args[0]) == 1

    def test_one_wire_from_save_path_is_enough(self, nodes_mod, tmp_path):
        """Asset Focus's `save_path` is relative and already names the asset —
        wired into `folder`, the picker needs no other wire."""
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        out = run(nodes_mod, save_path=[f"{EVENT_DIR}/Food/Spookies"],
                  selection=[json.dumps(["Spookies_00001_.png"])])
        assert len(out.args[0]) == 1
        assert out.args[1] == f"{EVENT_DIR}/Food/Spookies"

    def test_a_stage_is_a_step_under_the_wired_folder(self, nodes_mod,
                                                      tmp_path):
        """`save_path` names the asset; `stage` still names the step under it,
        exactly as it does for the derived folder."""
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        renders(tmp_path, f"{EVENT_DIR}/Food/Spookies", ("edits_00001_.png",),
                colour=90)
        out = run(nodes_mod, save_path=[f"{EVENT_DIR}/Food/Spookies"],
                  stage=["edits"],
                  selection=[json.dumps(["edits_00001_.png",
                                         "Spookies_00001_.png"])])
        assert len(out.args[0]) == 1
        assert out.args[1] == f"{EVENT_DIR}/Food/Spookies/edits"

    def test_a_folder_that_is_not_there_is_not_an_error(self, nodes_mod,
                                                         tmp_path):
        assert spookies(nodes_mod, tmp_path).args[0] == []

    def test_with_nothing_wired_it_lists_nothing(self, nodes_mod, tmp_path):
        """No folder on the wire means nowhere to look. Better to show
        nothing than to guess."""
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        assert run(nodes_mod).args[0] == []


class TestWhatLeavesTheNode:
    def test_only_the_ticked_files(self, nodes_mod, tmp_path):
        renders(tmp_path, f"{EVENT_DIR}/Food",
                ("Spookies_00001_.png", "Spookies_00002_.png",
                 "Spookies_00003_.png"))
        out = spookies(nodes_mod, tmp_path, selection=[json.dumps(
            ["Spookies_00001_.png", "Spookies_00003_.png"])])
        assert len(out.args[0]) == 2

    def test_nothing_ticked_emits_nothing_rather_than_failing(self, nodes_mod,
                                                               tmp_path):
        """What every run looks like before the images have been looked at."""
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        assert spookies(nodes_mod, tmp_path, selection=["[]"]).args[0] == []

    def test_a_tick_from_another_asset_is_not_emitted(self, nodes_mod,
                                                       tmp_path):
        """Ticks are saved on the node, so switching the asset upstream leaves
        the old ones behind. They name files this folder does not have."""
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        out = spookies(nodes_mod, tmp_path, selection=[json.dumps(
            ["Spookies_00001_.png", "Ghosts_00004_.png"])])
        assert len(out.args[0]) == 1

    def test_transparency_survives(self, nodes_mod, tmp_path):
        """The picker must not be the thing that undoes the background removal
        it was used to approve."""
        folder = tmp_path / "output" / EVENT_DIR / "Food"
        folder.mkdir(parents=True)
        Image.new("RGBA", (4, 4), (10, 20, 30, 0)).save(
            folder / "Spookies_00001_.png")
        out = spookies(nodes_mod, tmp_path,
                       selection=[json.dumps(["Spookies_00001_.png"])])
        assert out.args[0][0].shape == (1, 4, 4, 4)
        assert float(out.args[0][0][..., 3].max()) == 0.0


class TestSingleMode:
    """"in edit mode i want to only be able to select one image. i am EDITING
    so it has to be the one i am working on"."""

    def test_an_edit_picker_emits_one_however_many_are_ticked(self, nodes_mod,
                                                               tmp_path):
        """For the graph saved with several ticks, or pinned to `edit` after
        the picks were made — the panel replaces rather than adds, but the node
        cannot rely on having been the one to record them."""
        renders(tmp_path, f"{EVENT_DIR}/Food",
                ("Spookies_00001_.png", "Spookies_00002_.png",
                 "Spookies_00003_.png"))
        out = spookies(nodes_mod, tmp_path, mode=["single"],
                       selection=[json.dumps(["Spookies_00002_.png",
                                              "Spookies_00003_.png"])])
        assert len(out.args[0]) == 1

    def test_it_is_the_first_in_listing_order(self, nodes_mod, tmp_path):
        """The one numbered lowest on screen, so which image travels is
        readable off the node rather than a matter of click history."""
        renders(tmp_path, f"{EVENT_DIR}/Food",
                ("Spookies_00001_.png", "Spookies_00002_.png"))
        out = spookies(nodes_mod, tmp_path, mode=["single"],
                       selection=[json.dumps(["Spookies_00002_.png",
                                              "Spookies_00001_.png"])])
        assert len(out.args[0]) == 1
        assert float(out.args[0][0].max()) == pytest.approx(10 / 255, abs=1e-3)

    def test_multiple_is_the_default_and_takes_a_set(self, nodes_mod, tmp_path):
        """Choosing what to keep is a set; only the edit step is one."""
        renders(tmp_path, f"{EVENT_DIR}/Food",
                ("Spookies_00001_.png", "Spookies_00002_.png"))
        out = spookies(nodes_mod, tmp_path,
                       selection=[json.dumps(["Spookies_00001_.png",
                                              "Spookies_00002_.png"])])
        assert len(out.args[0]) == 2

    def test_nothing_ticked_is_still_nothing(self, nodes_mod, tmp_path):
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        assert spookies(nodes_mod, tmp_path, mode=["single"],
                        selection=["[]"]).args[0] == []


class TestItWritesNothing:
    """"this node should basically list and index those images and nothing
    more". Copying approved files into a Base/Edit/Export tree made a second
    source of truth for something the graph already states — which save node
    wrote the file."""

    def test_emitting_picks_creates_no_folders(self, nodes_mod, tmp_path):
        renders(tmp_path, f"{EVENT_DIR}/Food",
                ("Spookies_00001_.png", "Spookies_00002_.png"))
        spookies(nodes_mod, tmp_path,
                 selection=[json.dumps(["Spookies_00001_.png"])])
        category = tmp_path / "output" / EVENT_DIR / "Food"
        assert sorted(p.name for p in category.iterdir()) == [
            "Spookies_00001_.png", "Spookies_00002_.png"]


class TestTheFolderItListsIsAnOutput:
    """One string names the folder a save node WRITES and the folder this node
    READS, so the two cannot disagree."""

    def test_it_hands_out_the_folder_it_listed(self, nodes_mod, tmp_path):
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        out = spookies(nodes_mod, tmp_path)
        assert out.args[1] == f"{EVENT_DIR}/Food/Spookies"

    def test_it_is_relative_so_a_save_node_can_take_it(self, nodes_mod,
                                                       tmp_path):
        """`filename_prefix` resolves under the output directory, which is what
        makes this string usable without any conversion."""
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        assert not os.path.isabs(spookies(nodes_mod, tmp_path).args[1])

    def test_a_stage_is_part_of_it(self, nodes_mod, tmp_path):
        out = spookies(nodes_mod, tmp_path, stage=["edits"])
        assert out.args[1] == f"{EVENT_DIR}/Food/Spookies/edits"


class TestAStageOfTheAsset:
    """"531 should read from the folder where the edited images are saved" —
    a step under the asset, listed the same way its first renders are."""

    def test_a_stage_lists_the_step_not_the_renders(self, nodes_mod, tmp_path):
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        renders(tmp_path, f"{EVENT_DIR}/Food/Spookies",
                ("edits_00001_.png", "edits_00002_.png"), colour=90)
        out = spookies(nodes_mod, tmp_path, stage=["edits"],
                       selection=[json.dumps(["edits_00001_.png",
                                              "edits_00002_.png",
                                              "Spookies_00001_.png"])])
        assert len(out.args[0]) == 2

    def test_no_stage_lists_the_assets_own_renders(self, nodes_mod, tmp_path):
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        renders(tmp_path, f"{EVENT_DIR}/Food/Spookies", ("edits_00001_.png",),
                colour=90)
        out = spookies(nodes_mod, tmp_path,
                       selection=[json.dumps(["Spookies_00001_.png",
                                              "edits_00001_.png"])])
        assert len(out.args[0]) == 1

    def test_a_stage_cannot_deepen_the_tree(self, nodes_mod, tmp_path):
        """Typed by hand beside a folder it becomes part of, so a slash in it
        would silently put the files somewhere else entirely."""
        out = spookies(nodes_mod, tmp_path, stage=["../../elsewhere"])
        assert ".." not in out.args[1]


class TestAPickerFedByAnotherPicker:
    """"521 reads the indexed 3 images from 518". The approved set is the
    upstream picker's ticks — no folder of copies has to exist for it."""

    def wire(self, nodes_mod, source_selection, source_id="9", node_id="7"):
        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(
            unique_id=node_id,
            prompt={node_id: {"inputs": {"images": [source_id, 0]}},
                    source_id: {"class_type": "SymbioticaPick",
                                "inputs": {"selection": source_selection}}})

    def test_it_lists_only_what_the_picker_above_approved(self, nodes_mod,
                                                          tmp_path):
        from pipeline.pick_folder import remember
        renders(tmp_path, f"{EVENT_DIR}/Food",
                ("Spookies_00001_.png", "Spookies_00002_.png",
                 "Spookies_00003_.png"))
        remember("9", str(tmp_path / "output" / EVENT_DIR / "Food" / "Spookies"))
        self.wire(nodes_mod, json.dumps(["Spookies_00002_.png",
                                         "Spookies_00003_.png"]))
        out = nodes_mod.SymbioticaPick.execute(
            save_path=[f"{EVENT_DIR}/Food/Spookies"],
            selection=[json.dumps(["Spookies_00001_.png",
                                   "Spookies_00002_.png"])])
        # Its own tick on an image the picker above did not approve is not a
        # choice it may make.
        assert len(out.args[0]) == 1

    def test_a_shortlist_of_a_shortlist_narrows_further(self, nodes_mod,
                                                         tmp_path):
        from pipeline.pick_folder import remember
        renders(tmp_path, f"{EVENT_DIR}/Food",
                ("Spookies_00001_.png", "Spookies_00002_.png"))
        remember("9", str(tmp_path / "output" / EVENT_DIR / "Food" / "Spookies"),
                 ["Spookies_00002_.png"])
        self.wire(nodes_mod, json.dumps(["Spookies_00001_.png",
                                         "Spookies_00002_.png"]))
        out = nodes_mod.SymbioticaPick.execute(
            save_path=[f"{EVENT_DIR}/Food/Spookies"],
            selection=[json.dumps(["Spookies_00001_.png",
                                   "Spookies_00002_.png"])])
        assert len(out.args[0]) == 1

    def test_a_save_node_upstream_is_not_a_shortlist(self, nodes_mod,
                                                      tmp_path):
        """Only another picker publishes an approved set; everything else is
        just the wire that puts this node after it."""
        renders(tmp_path, f"{EVENT_DIR}/Food",
                ("Spookies_00001_.png", "Spookies_00002_.png"))
        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(
            unique_id="7",
            prompt={"7": {"inputs": {"images": ["9", 0]}},
                    "9": {"class_type": "SaveImage"}})
        out = nodes_mod.SymbioticaPick.execute(
            save_path=[f"{EVENT_DIR}/Food/Spookies"],
            selection=[json.dumps(["Spookies_00001_.png",
                                   "Spookies_00002_.png"])])
        assert len(out.args[0]) == 2
