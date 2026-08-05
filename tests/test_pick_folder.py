# ABOUTME: The Pick node's folder listing — which files belong to one asset, the
# ABOUTME: numbering the ticks are made against, and keeping what was picked.
import os

from PIL import Image

from pipeline.pick_folder import (images_in, listing, listing_for,
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


class TestThePanelListsWhatTheNodeRead:
    """Asset and category arrive on wires, and a wired input has no value on
    the canvas — so the panel cannot work the folder out for itself."""

    def test_a_run_records_the_path_it_resolved(self):
        remember("7", "/out/Oct/Ev/Food/Spookies")
        assert resolved("7") == ("/out/Oct/Ev/Food/Spookies", None)

    def test_a_node_that_has_never_run_has_no_folder(self):
        assert resolved("no-such-node") == ("", None)

    def test_an_integer_and_its_string_are_the_same_node(self):
        remember(9, "/out/x")
        assert resolved("9") == ("/out/x", None)

    def test_a_shortlist_is_recorded_with_the_path(self):
        """A picker fed by another lists what that one approved, and the panel
        has to be able to ask for the same narrowed set."""
        remember("8", "/out/x", ["a.png", "b.png"])
        assert resolved("8") == ("/out/x", ["a.png", "b.png"])


class TestListingAShortlist:
    """"521 reads the indexed 3 images from 518" — the approved set is the
    upstream picker's ticks, so no folder of copies has to exist for it."""

    def test_only_the_named_files_are_listed(self, tmp_path):
        renders(str(tmp_path), ("a.png", "b.png", "c.png"))
        names = [e["name"] for e in
                 listing_for(str(tmp_path), only=["a.png", "c.png"])]
        assert names == ["a.png", "c.png"]

    def test_the_numbering_is_of_the_shortlist(self, tmp_path):
        """1 and 2, not 1 and 3: the number is what is read off the screen."""
        renders(str(tmp_path), ("a.png", "b.png", "c.png"))
        entries = listing_for(str(tmp_path), only=["a.png", "c.png"])
        assert [e["index"] for e in entries] == [1, 2]

    def test_an_empty_shortlist_lists_nothing(self, tmp_path):
        """Nothing approved upstream is not the same as no narrowing at all."""
        renders(str(tmp_path), ("a.png",))
        assert listing_for(str(tmp_path), only=[]) == []

    def test_a_name_that_is_gone_is_simply_absent(self, tmp_path):
        renders(str(tmp_path), ("a.png",))
        assert len(listing_for(str(tmp_path), only=["a.png", "gone.png"])) == 1


class TestWhichLayoutANameMeans:
    """A name is both a filename prefix and a directory at once, and only one
    of them is ever the answer."""

    def test_files_named_after_it_are_what_it_means(self, tmp_path):
        renders(str(tmp_path / "Food"), ("Spookies_00001_.png",))
        renders(str(tmp_path / "Food" / "Spookies"), ("edits_00001_.png",),
                colour=90)
        names = [e["name"] for e in listing_for(str(tmp_path / "Food" / "Spookies"))]
        # Not the edits inside `Spookies/` — those are a later step, and
        # merging them put every edit in the list of renders to choose a base
        # from, moving the numbering every time a stage was saved.
        assert names == ["Spookies_00001_.png"]

    def test_the_directory_is_meant_when_nothing_is_named_after_it(self,
                                                                    tmp_path):
        """Work saved a folder-per-asset still reads."""
        renders(str(tmp_path / "Food" / "Spookies"), ("one.png", "two.png"))
        names = [e["name"] for e in listing_for(str(tmp_path / "Food" / "Spookies"))]
        assert names == ["one.png", "two.png"]

    def test_a_stage_is_a_prefix_inside_the_assets_folder(self, tmp_path):
        renders(str(tmp_path / "Food"), ("Spookies_00001_.png",))
        renders(str(tmp_path / "Food" / "Spookies"),
                ("edits_00001_.png", "edits_00002_.png"), colour=90)
        entries = listing_for(str(tmp_path / "Food" / "Spookies" / "edits"))
        assert [e["name"] for e in entries] == ["edits_00001_.png",
                                                "edits_00002_.png"]
        assert [e["index"] for e in entries] == [1, 2]

    def test_read_folders_names_what_will_be_read(self, tmp_path):
        renders(str(tmp_path / "Food"), ("Spookies_00001_.png",))
        assert read_folders(str(tmp_path / "Food" / "Spookies")) == [
            (str(tmp_path / "Food"), "Spookies")]

    def test_nothing_to_read_is_no_folders(self):
        assert read_folders("") == []
