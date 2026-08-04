# ABOUTME: The Pick node's folder listing — which files belong to one asset, the
# ABOUTME: numbering the ticks are made against, and keeping what was picked.
import os

from PIL import Image

from pipeline.pick_folder import (images_in, keep_picks, listing, listing_for,
                                  name_matches_prefix, picked_paths,
                                  read_folders, remember, resolved)


def renders(folder, names, colour=10):
    os.makedirs(folder, exist_ok=True)
    for i, name in enumerate(names):
        Image.new("RGB", (6, 6), (colour + i, 0, 0)).save(
            os.path.join(folder, name))
    return folder


class TestWhichFilesBelongToAnAsset:
    """A Save Image node given `…/Food/Spookies` writes
    `Food/Spookies_00001_.png` — the last segment of a filename prefix names
    the FILE. So one folder holds every asset of a category, side by side."""

    def test_the_prefix_picks_out_one_assets_files(self, tmp_path):
        renders(str(tmp_path), ("Spookies_00001_.png", "Spookies_00002_.png",
                                "Ghosts_00001_.png"))
        assert images_in(str(tmp_path), "Spookies") == [
            "Spookies_00001_.png", "Spookies_00002_.png"]

    def test_a_longer_name_is_not_claimed_by_a_shorter_one(self):
        assert name_matches_prefix("Spookies_00001_.png", "Spookies") is True
        assert name_matches_prefix("Spookies.png", "Spookies") is True
        assert name_matches_prefix("Spookies Deluxe_00001_.png",
                                   "Spookies") is False

    def test_without_a_prefix_the_whole_folder_is_listed(self, tmp_path):
        renders(str(tmp_path), ("a.png", "b.png"))
        assert images_in(str(tmp_path)) == ["a.png", "b.png"]

    def test_it_does_not_descend(self, tmp_path):
        """The category folder holds every asset of that category — walking
        down from there drags in whatever else is filed below, including the
        folder the approved picks are kept in."""
        renders(str(tmp_path), ("Spookies_00001_.png",))
        renders(str(tmp_path / "Base"), ("kept.png",), colour=90)
        assert images_in(str(tmp_path)) == ["Spookies_00001_.png"]

    def test_non_images_and_dotfiles_are_left_out(self, tmp_path):
        renders(str(tmp_path), ("a.png",))
        (tmp_path / "notes.txt").write_text("x")
        (tmp_path / ".hidden.png").write_text("x")
        assert images_in(str(tmp_path)) == ["a.png"]

    def test_a_folder_that_is_not_there_lists_nothing(self, tmp_path):
        assert images_in(str(tmp_path / "nope")) == []


class TestTheNumbering:
    """"selecting 3 images to go through the node should be just a fucking
    index select"."""

    def test_every_image_is_numbered_from_one(self, tmp_path):
        renders(str(tmp_path), ("a.png", "b.png", "c.png"))
        assert [e["index"] for e in listing(str(tmp_path))] == [1, 2, 3]

    def test_the_order_is_the_order_they_were_rendered(self, tmp_path):
        """`<asset>_00001_` sorts by name into the order they were made, so a
        number on screen means the same thing on the next run."""
        renders(str(tmp_path), ("S_00003_.png", "S_00001_.png", "S_00002_.png"))
        assert [e["name"] for e in listing(str(tmp_path), "S")] == [
            "S_00001_.png", "S_00002_.png", "S_00003_.png"]

    def test_an_entry_carries_its_size_and_full_path(self, tmp_path):
        renders(str(tmp_path), ("a.png",))
        entry = listing(str(tmp_path))[0]
        assert (entry["w"], entry["h"]) == (6, 6)
        assert os.path.isfile(entry["path"])

    def test_the_id_is_the_file_name(self, tmp_path):
        """Ticks are saved in the workflow, so they have to name something
        stable — a position shifts the moment a new render lands."""
        renders(str(tmp_path), ("a.png",))
        assert listing(str(tmp_path))[0]["id"] == "a.png"

    def test_a_listing_is_capped(self, tmp_path):
        renders(str(tmp_path), tuple(f"a{i:03d}.png" for i in range(12)))
        assert len(listing(str(tmp_path), limit=5)) == 5

    def test_an_unreadable_file_is_still_listed(self, tmp_path):
        """It is on disk, so it belongs in a listing of what is on disk."""
        renders(str(tmp_path), ("good.png",))
        (tmp_path / "broken.png").write_bytes(b"not an image")
        entries = listing(str(tmp_path))
        assert [e["name"] for e in entries] == ["broken.png", "good.png"]
        assert entries[0]["w"] == 0


class TestWhatLeavesTheNode:
    def test_only_the_ticked_files_come_back(self, tmp_path):
        renders(str(tmp_path), ("a.png", "b.png", "c.png"))
        entries = listing(str(tmp_path))
        picked = picked_paths(entries, ["a.png", "c.png"])
        assert [os.path.basename(p) for p in picked] == ["a.png", "c.png"]

    def test_they_come_back_in_the_order_the_grid_shows(self, tmp_path):
        """Listing order, not click order: the run has to be reproducible from
        the saved workflow, and click order is recorded nowhere."""
        renders(str(tmp_path), ("a.png", "b.png", "c.png"))
        entries = listing(str(tmp_path))
        picked = picked_paths(entries, ["c.png", "a.png"])
        assert [os.path.basename(p) for p in picked] == ["a.png", "c.png"]

    def test_a_tick_for_a_file_that_is_gone_is_skipped(self, tmp_path):
        """Deleting a render must not break the graph the picker is wired
        into."""
        renders(str(tmp_path), ("a.png",))
        entries = listing(str(tmp_path))
        os.remove(entries[0]["path"])
        assert picked_paths(entries, ["a.png"]) == []

    def test_nothing_ticked_is_not_an_error(self, tmp_path):
        renders(str(tmp_path), ("a.png",))
        assert picked_paths(listing(str(tmp_path)), []) == []


class TestKeepingWhatWasGood:
    """"images picked should land in …/Spookies/Base so we only keep what was
    good in these folders"."""

    def test_a_pick_is_copied_under_its_own_name(self, tmp_path):
        renders(str(tmp_path / "src"), ("Spookies_00007_.png",))
        dest = str(tmp_path / "src" / "Spookies" / "Base")
        written = keep_picks(
            [str(tmp_path / "src" / "Spookies_00007_.png")], dest)
        assert [os.path.basename(p) for p in written] == ["Spookies_00007_.png"]

    def test_keeping_twice_writes_once(self, tmp_path):
        """Every queue emits the same ticks; rewriting them each time would
        churn the delivery folder and whatever syncs it."""
        renders(str(tmp_path / "src"), ("a.png",))
        paths = [str(tmp_path / "src" / "a.png")]
        assert len(keep_picks(paths, str(tmp_path / "keep"))) == 1
        assert keep_picks(paths, str(tmp_path / "keep")) == []

    def test_the_rejects_stay_where_they_are(self, tmp_path):
        """Copied, never moved: deleting what was not picked is a different
        decision, and not one a node makes on its own."""
        renders(str(tmp_path / "src"), ("a.png", "b.png"))
        keep_picks([str(tmp_path / "src" / "a.png")], str(tmp_path / "keep"))
        assert sorted(os.listdir(str(tmp_path / "src"))) == ["a.png", "b.png"]

    def test_an_unwritable_destination_does_not_raise(self, tmp_path):
        """The picks are still on the wire, which is what the run is for."""
        renders(str(tmp_path / "src"), ("a.png",))
        blocker = tmp_path / "afile"
        blocker.write_text("not a directory")
        assert keep_picks([str(tmp_path / "src" / "a.png")],
                          str(blocker / "Base")) == []


class TestThePanelListsWhatTheNodeRead:
    """Asset and category arrive on wires, and a wired input has no value on
    the canvas — so the panel cannot work the folder out for itself."""

    def test_a_run_records_the_asset_it_resolved(self):
        remember("7", "/out/Oct/Ev/Food/Spookies")
        assert resolved("7") == "/out/Oct/Ev/Food/Spookies"

    def test_a_node_that_has_never_run_has_no_folder(self):
        assert resolved("no-such-node") == ""

    def test_an_integer_and_its_string_are_the_same_node(self):
        remember(9, "/out/x")
        assert resolved("9") == "/out/x"


class TestBothLayoutsAtOnce:
    """The moment approved picks are kept, `…/Spookies/` exists as a directory
    — and listing that instead of the prefixed files hid every new render
    behind the folder its own picks created."""

    def test_the_prefixed_files_survive_the_folder_appearing(self, tmp_path):
        renders(str(tmp_path / "Food"), ("Spookies_00001_.png",))
        renders(str(tmp_path / "Food" / "Spookies" / "Base"), ("kept.png",),
                colour=90)
        names = [e["name"] for e in listing_for(str(tmp_path / "Food" / "Spookies"))]
        assert names == ["Spookies_00001_.png"]

    def test_a_folder_of_its_own_is_listed_too(self, tmp_path):
        renders(str(tmp_path / "Food"), ("Spookies_00001_.png",))
        renders(str(tmp_path / "Food" / "Spookies"), ("older.png",), colour=90)
        entries = listing_for(str(tmp_path / "Food" / "Spookies"))
        assert [e["name"] for e in entries] == ["Spookies_00001_.png",
                                                "older.png"]
        assert [e["index"] for e in entries] == [1, 2]

    def test_the_same_name_from_both_layouts_is_one_tile(self, tmp_path):
        """`id` is the file name, which is what a tick records — two tiles
        with one identity would tick each other."""
        renders(str(tmp_path / "Food"), ("Spookies_00001_.png",))
        renders(str(tmp_path / "Food" / "Spookies"), ("Spookies_00001_.png",),
                colour=90)
        assert len(listing_for(str(tmp_path / "Food" / "Spookies"))) == 1

    def test_read_folders_names_what_will_be_read(self, tmp_path):
        renders(str(tmp_path / "Food"), ("Spookies_00001_.png",))
        assert read_folders(str(tmp_path / "Food" / "Spookies")) == [
            (str(tmp_path / "Food"), "Spookies")]

    def test_nothing_to_read_is_no_folders(self):
        assert read_folders("") == []
