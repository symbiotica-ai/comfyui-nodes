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


ORDER = {"month": "Oct", "feature": "Mini 1", "eventName": "Ghostly Goodies"}
# What `save_paths` writes for that order: the event's full label, not the bare
# feature. The node has to derive the same string or it names a path that has
# never existed.
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
    """The node pointed at its own asset, the way his graph wires it."""
    return run(nodes, asset=["Spookies"], category=["Food"], order=[ORDER],
               **kw)


class TestSchema:
    def test_the_widget_order_is_append_only(self, nodes_mod):
        """ComfyUI serialises widget values POSITIONALLY as `widgets_values`,
        so inserting a widget before an existing one shifts every value after
        it in every saved workflow. That is not cosmetic: adding `role` in the
        middle put the user's ticked ids into `role` and his filter into
        `selection`, on a graph he had already saved. `get_new` and `role` are
        dead and kept for exactly this reason. A new widget goes on the end.
        """
        schema = nodes_mod.SymbioticaPick.GET_SCHEMA()
        wires = {"images", "order"}
        widgets = [i.id for i in schema.inputs if i.id not in wires]
        assert widgets == ["get_new", "asset", "category", "selection",
                           "view", "role", "folder", "phase"]

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

    def test_the_pass_is_a_selector_with_the_three_passes(self, nodes_mod):
        schema = nodes_mod.SymbioticaPick.GET_SCHEMA()
        phase = next(i for i in schema.inputs if i.id == "phase")
        assert phase.options == ["", "base", "edit", "export"]


class TestItCannotCauseARender:
    """"I DONT WANT YOU TO GENERATE A NEW IMAGE EVERY SINGLE TIME". The images
    are read off disk, so the wire is never evaluated — a lazy input that is
    not requested is never computed, and nothing upstream runs."""

    def test_the_images_input_is_lazy(self, nodes_mod):
        images = next(i for i in nodes_mod.SymbioticaPick.GET_SCHEMA().inputs
                      if i.id == "images")
        assert images.lazy is True

    def test_the_wire_is_never_asked_for(self, nodes_mod):
        assert nodes_mod.SymbioticaPick.check_lazy_status(images=None) == []

    def test_not_even_when_something_is_wired_to_it(self, nodes_mod):
        nodes_mod.SymbioticaPick.hidden = types.SimpleNamespace(
            unique_id="7",
            prompt={"7": {"inputs": {"images": ["9", 0]}},
                    "9": {"class_type": "SaveImage"}})
        assert nodes_mod.SymbioticaPick.check_lazy_status(
            images=(None,)) == []

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
    def test_the_asset_folder_is_worked_out_from_the_wires(self, nodes_mod,
                                                           tmp_path):
        """Nothing to type in: the asset, category and order are already here.
        A Save Image node files `Food/Spookies_00001_.png`, so the asset's
        "folder" is a name shared by files one level up."""
        renders(tmp_path, f"{EVENT_DIR}/Food",
                ("Spookies_00001_.png", "Spookies_00002_.png",
                 "Ghosts_00001_.png"))
        spookies(nodes_mod, tmp_path)
        assert nodes_mod_resolved(nodes_mod, "7") == str(
            tmp_path / "output" / EVENT_DIR / "Food" / "Spookies")

    def test_the_event_folder_is_the_one_the_save_node_wrote(self, nodes_mod,
                                                             tmp_path):
        """`save_paths` files under `event_label(order)` — "Mini 1 — Ghostly
        Goodies" — while the order's own `feature` is "Mini 1". Deriving from
        the bare feature named a path that has never existed, and a folder that
        is not there reads exactly like a folder with nothing in it."""
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        out = spookies(nodes_mod, tmp_path,
                       selection=[json.dumps(["Spookies_00001_.png"])])
        assert len(out.args[0]) == 1

    def test_a_folder_of_its_own_is_listed_as_itself(self, nodes_mod, tmp_path):
        """Both layouts are real: some assets have a directory, most are a
        filename prefix."""
        renders(tmp_path, f"{EVENT_DIR}/Food/Spookies", ("one.png", "two.png"))
        out = spookies(nodes_mod, tmp_path,
                       selection=[json.dumps(["one.png", "two.png"])])
        assert len(out.args[0]) == 2

    def test_a_typed_folder_overrides_the_derived_one(self, nodes_mod,
                                                       tmp_path):
        elsewhere = renders(tmp_path, "elsewhere", ("x.png",))
        out = spookies(nodes_mod, tmp_path, folder=[str(elsewhere)],
                       selection=[json.dumps(["x.png"])])
        assert len(out.args[0]) == 1

    def test_a_typed_save_prefix_works_too(self, nodes_mod, tmp_path):
        """Pasting the save node's own prefix in is the natural thing to try,
        and it names nothing that exists."""
        renders(tmp_path, "elsewhere", ("Spookies_00001_.png",))
        out = run(nodes_mod, folder=[str(tmp_path / "output" / "elsewhere"
                                         / "Spookies")],
                  selection=[json.dumps(["Spookies_00001_.png"])])
        assert len(out.args[0]) == 1

    def test_a_folder_that_is_not_there_is_not_an_error(self, nodes_mod,
                                                         tmp_path):
        assert spookies(nodes_mod, tmp_path).args[0] == []

    def test_with_nothing_wired_it_lists_nothing(self, nodes_mod, tmp_path):
        """Deriving from a month alone would list every asset of every event.
        Better to show nothing than everything."""
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        assert run(nodes_mod, order=[ORDER]).args[0] == []


def nodes_mod_resolved(nodes, node_id):
    from pipeline.pick_folder import resolved
    return resolved(node_id)


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


class TestKeepingWhatWasGood:
    """"images picked should land in 'October/Mini 1 — Ghostly Goodies/Food -
    3 stages/Spookies/Base' so we only keep what was good in these folders"."""

    def kept_dir(self, tmp_path, name="Base"):
        return tmp_path / "output" / EVENT_DIR / "Food" / "Spookies" / name

    def test_a_tick_is_copied_into_the_assets_own_folder(self, nodes_mod,
                                                         tmp_path):
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        spookies(nodes_mod, tmp_path,
                 selection=[json.dumps(["Spookies_00001_.png"])])
        assert [p.name for p in self.kept_dir(tmp_path).iterdir()] == [
            "Spookies_00001_.png"]

    def test_the_pass_names_the_folder(self, nodes_mod, tmp_path):
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        spookies(nodes_mod, tmp_path, phase=["export"],
                 selection=[json.dumps(["Spookies_00001_.png"])])
        assert self.kept_dir(tmp_path, "Export").is_dir()

    def test_nothing_ticked_writes_nothing(self, nodes_mod, tmp_path):
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        spookies(nodes_mod, tmp_path, selection=["[]"])
        assert not self.kept_dir(tmp_path).exists()

    def test_a_folder_to_browse_is_not_a_folder_to_write_to(self, nodes_mod,
                                                             tmp_path):
        """`folder` names something to look at — pointing a picker at last
        month's work must not file this month's picks into it."""
        browsed = renders(tmp_path, "elsewhere", ("x.png",))
        spookies(nodes_mod, tmp_path, folder=[str(browsed)],
                 selection=[json.dumps(["x.png"])])
        assert sorted(p.name for p in browsed.iterdir()) == ["x.png"]
        assert self.kept_dir(tmp_path).is_dir()

    def test_what_was_kept_is_not_listed_as_a_candidate(self, nodes_mod,
                                                        tmp_path):
        """The kept copies live under the asset, and the listing does not
        descend — or every pick would come back as a new image to pick."""
        renders(tmp_path, f"{EVENT_DIR}/Food", ("Spookies_00001_.png",))
        pick = [json.dumps(["Spookies_00001_.png"])]
        spookies(nodes_mod, tmp_path, selection=pick)
        out = spookies(nodes_mod, tmp_path, selection=pick)
        assert len(out.args[0]) == 1
