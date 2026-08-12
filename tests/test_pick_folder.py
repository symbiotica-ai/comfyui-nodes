# ABOUTME: The Pick node's folder listing — which files belong to one asset, the
# ABOUTME: numbering the ticks are made against, and keeping what was picked.
import os

from PIL import Image

from pipeline.pick_folder import (edit_prefix, images_in, listing, listing_for,
                                  name_matches_prefix, picked_paths,
                                  parent_of, read_folders, remember, resolved)


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

    def test_another_lane_into_the_same_folder_is_not_claimed_either(self):
        """Two save nodes writing one folder under different prefixes are two
        listings: "i want the Pick node to read the path I attached to it".
        Only ComfyUI's own counter may follow the prefix — anything else is a
        different prefix that merely starts the same.
        """
        assert name_matches_prefix("Spookies_lora_00001_.png",
                                   "Spookies") is False
        assert name_matches_prefix("Spookies_lora_00001_.png",
                                   "Spookies_lora") is True
        assert name_matches_prefix("Spookies_lora.png",
                                   "Spookies_lora") is True
        # A bare counter with no trailing underscore still belongs.
        assert name_matches_prefix("Spookies_7.png", "Spookies") is True

    def test_a_names_entry_without_an_extension_is_a_save_prefix(self,
                                                                 tmp_path):
        """"do i have to ask you again instead of just connecting that
        filename prefix to the name input?" — no: the tag the save node was
        given IS the filter. With an extension an entry stays one exact file,
        so the client-references flow keeps its meaning.
        """
        renders(str(tmp_path), ("_base_00001_.png", "_base_00002_.png",
                                "edits_00001_.png",
                                "edits_from.X_00001__00001_.png",
                                "Spookies_00001_.png"))
        rows = listing_for(str(tmp_path), only=["_base"])
        assert [r["name"] for r in rows] == ["_base_00001_.png",
                                             "_base_00002_.png"]
        rows = listing_for(str(tmp_path), only=["edits"])
        assert [r["name"] for r in rows] == ["edits_00001_.png",
                                             "edits_from.X_00001__00001_.png"]
        rows = listing_for(str(tmp_path), only=["Spookies_00001_.png"])
        assert [r["name"] for r in rows] == ["Spookies_00001_.png"]
        # Exact and prefix entries compose in one list.
        rows = listing_for(str(tmp_path), only=["_base", "Spookies_00001_.png"])
        assert [r["name"] for r in rows] == ["Spookies_00001_.png",
                                             "_base_00001_.png",
                                             "_base_00002_.png"]

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
        assert resolved("7") == ("/out/Oct/Ev/Food/Spookies", None, None)

    def test_a_node_that_has_never_run_has_no_folder(self):
        assert resolved("no-such-node") == ("", None, None)

    def test_an_integer_and_its_string_are_the_same_node(self):
        remember(9, "/out/x")
        assert resolved("9") == ("/out/x", None, None)

    def test_a_shortlist_is_recorded_with_the_path(self):
        """A picker fed by another lists what that one approved, and the panel
        has to be able to ask for the same narrowed set."""
        remember("8", "/out/x", ["a.png", "b.png"])
        assert resolved("8") == ("/out/x", ["a.png", "b.png"], None)

    def test_the_edits_being_shown_are_recorded_too(self):
        """The panel has to ask the run's question, not a broader one: a picker
        showing the edits of one approval must not have its grid list every
        edit in the folder."""
        remember("6", "/out/x/edits", None, ["Chair_00001_.png"])
        assert resolved("6") == ("/out/x/edits", None, ["Chair_00001_.png"])


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

    def test_both_layouts_are_listed_and_names_narrows(self, tmp_path):
        """"that node should show everything from the folder if it's not
        filtered with a name" — the files named after the target AND the
        directory's own contents are one listing, prefix files first so a
        pure-prefix folder keeps its numbering. One lane is a `names` tag.
        """
        renders(str(tmp_path / "Food"), ("Spookies_00001_.png",))
        renders(str(tmp_path / "Food" / "Spookies"), ("edits_00001_.png",),
                colour=90)
        target = str(tmp_path / "Food" / "Spookies")
        assert [e["name"] for e in listing_for(target)] == [
            "Spookies_00001_.png", "edits_00001_.png"]
        assert [e["name"] for e in listing_for(target, only=["edits"])] == [
            "edits_00001_.png"]

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
        # With a directory of the same name, both layouts are read.
        renders(str(tmp_path / "Food" / "Spookies"), ("edits_00001_.png",))
        assert read_folders(str(tmp_path / "Food" / "Spookies")) == [
            (str(tmp_path / "Food"), "Spookies"),
            (str(tmp_path / "Food" / "Spookies"), "")]

    def test_nothing_to_read_is_no_folders(self):
        assert read_folders("") == []

    def test_a_folder_of_buckets_is_read_one_level_down(self, tmp_path):
        """`Food - 3 stages/{Food,Drinks}` holds no images itself, and a
        picker pointed at any path still has to show what is under it."""
        stages = tmp_path / "Food - 3 stages"
        renders(str(stages / "Food"), ("Truffles.png",))
        renders(str(stages / "Drinks"), ("Tea.png",))
        assert read_folders(str(stages)) == [
            (str(stages), ""),
            (str(stages / "Drinks"), ""),
            (str(stages / "Food"), "")]
        assert [e["name"] for e in listing_for(str(stages))] == ["Tea.png",
                                                                "Truffles.png"]

    def test_a_folder_with_its_own_images_ignores_its_sub_folders(self,
                                                                 tmp_path):
        """The step down is a fallback, so no listing that already worked
        changes — `discarded` in particular stays out of the grid."""
        stages = tmp_path / "Sheets"
        renders(str(stages), ("Ready.png",))
        renders(str(stages / "discarded"), ("Rejected.png",))
        assert read_folders(str(stages)) == [(str(stages), "")]


def test_discarding_moves_files_under_the_listing_and_out_of_it(tmp_path):
    """A bad render leaves the grid without leaving the disk.

    Deleting is the one thing a picker must not do — it exists to choose
    between renders, several of which cost real money and cannot be made
    again. Moving them into `discarded/` under what the node lists takes them
    out of every listing (both layouts read one level only) and leaves the
    files where a human can drag them back."""
    from pipeline.pick_folder import discard, listing_for

    folder = tmp_path / "Skull Rose Cupcake"
    folder.mkdir()
    for i in (1, 2, 3):
        Image.new("RGB", (8, 8)).save(folder / f"render_0000{i}_.png")

    moved = discard(str(folder), ["render_00002_.png", "render_00003_.png"])

    assert sorted(os.path.basename(p) for p in moved) == [
        "render_00002_.png", "render_00003_.png"]
    assert [e["name"] for e in listing_for(str(folder))] == ["render_00001_.png"]
    kept = sorted(os.listdir(folder / "discarded"))
    assert kept == ["render_00002_.png", "render_00003_.png"]


def test_discarding_never_leaves_the_folder_it_lists(tmp_path):
    from pipeline.pick_folder import discard

    folder = tmp_path / "asset"
    folder.mkdir()
    Image.new("RGB", (8, 8)).save(folder / "keep.png")
    Image.new("RGB", (8, 8)).save(tmp_path / "outside.png")

    assert discard(str(folder), ["../outside.png", "nope.png"]) == []
    assert (tmp_path / "outside.png").is_file()


def test_a_second_discard_of_the_same_name_does_not_overwrite(tmp_path):
    # The counter restarts whenever a save node is pointed at a fresh folder,
    # so the same file name reaching `discarded/` twice is ordinary.
    from pipeline.pick_folder import discard

    folder = tmp_path / "asset"
    folder.mkdir()
    Image.new("RGB", (8, 8)).save(folder / "shot.png")
    discard(str(folder), ["shot.png"])
    Image.new("RGB", (8, 8), (9, 9, 9)).save(folder / "shot.png")
    discard(str(folder), ["shot.png"])

    assert sorted(os.listdir(folder / "discarded")) == ["shot-2.png", "shot.png"]


def test_discarding_a_prefixed_render_files_it_under_the_asset(tmp_path):
    # `…/Food - 3 stages/Spookies` names `Spookies_*` files one level up; the
    # discards belong under the asset's own folder, the way a stage does.
    from pipeline.pick_folder import discard, listing_for

    category = tmp_path / "Food - 3 stages"
    category.mkdir()
    Image.new("RGB", (8, 8)).save(category / "Spookies_00001_.png")
    Image.new("RGB", (8, 8)).save(category / "Spookies_00002_.png")
    target = str(category / "Spookies")

    moved = discard(target, ["Spookies_00002_.png"])

    assert [os.path.basename(p) for p in moved] == ["Spookies_00002_.png"]
    assert [e["name"] for e in listing_for(target)] == ["Spookies_00001_.png"]
    assert os.path.isfile(category / "Spookies" / "discarded"
                          / "Spookies_00002_.png")


class TestWhatAnEditWasMadeFrom:
    """An edit is a NEW file: the save node gives it a fresh counter name that
    was never in the tick set of the render it came from. So the link has to be
    written down at save time, in the one place that travels with the file —
    its name.

    The format is shaped by two constraints, not by taste. It has to survive
    ComfyUI appending `_00012_`, and it has to leave the file still matching the
    stage prefix a picker lists that folder by, which is why the marker follows
    `<stage>_` instead of leading the name.
    """

    def test_the_prefix_carries_the_render_the_edit_came_from(self):
        assert edit_prefix("edits", "Spiderweb Chair_00001_.png") == (
            "edits_from.Spiderweb Chair_00001_")

    def test_the_saved_file_says_what_it_came_from(self):
        # The name ComfyUI actually writes from that prefix, counter and all.
        assert parent_of("edits_from.Spiderweb Chair_00001__00012_.png") == (
            "Spiderweb Chair_00001_")

    def test_a_file_with_no_marker_has_no_parent_rather_than_a_wrong_one(self):
        assert parent_of("edits_00012_.png") is None
        assert parent_of("ComfyUI_00001_.png") is None
        assert parent_of("Spiderweb Chair_00001_.png") is None

    def test_naming_no_render_marks_nothing(self):
        # Never a wrong mark: with nothing to point at, the prefix stays the
        # plain stage and the file simply has no parent.
        assert edit_prefix("edits", "") == "edits"
        assert edit_prefix("edits", None) == "edits"

    def test_a_marked_edit_is_still_listed_under_its_stage(self, tmp_path):
        """The constraint that shaped the format. A picker lists `<asset>/edits`
        by the prefix `edits`, so a marked file that stopped matching it would
        vanish from the very grid it was saved for."""
        renders(str(tmp_path), ("edits_from.Spiderweb Chair_00001__00012_.png",
                                "edits_00003_.png"))
        assert images_in(str(tmp_path), "edits") == [
            "edits_00003_.png", "edits_from.Spiderweb Chair_00001__00012_.png"]


class TestListingWhatCameFromOnePick:
    """The second picker in an edit lane shows the edits OF the render that was
    approved — which it can only do by reading each file's own mark, since the
    edits were named by the save node long after the tick was made."""

    def test_only_the_edits_of_that_render_are_listed(self, tmp_path):
        renders(str(tmp_path), (
            "edits_from.Chair_00001__00001_.png",
            "edits_from.Chair_00001__00002_.png",
            "edits_from.Lamp_00007__00001_.png"))
        names = [e["name"] for e in
                 listing_for(str(tmp_path), derived_from=["Chair_00001_.png"])]
        assert names == ["edits_from.Chair_00001__00001_.png",
                         "edits_from.Chair_00001__00002_.png"]

    def test_an_unmarked_edit_is_claimed_by_no_one(self, tmp_path):
        """It does not say where it came from, so it cannot answer for a parent
        — the same rule that keeps every file already on disk out of trouble."""
        renders(str(tmp_path), ("edits_from.Chair_00001__00001_.png",
                                "edits_00002_.png"))
        names = [e["name"] for e in
                 listing_for(str(tmp_path), derived_from=["Chair_00001_.png"])]
        assert names == ["edits_from.Chair_00001__00001_.png"]

    def test_the_numbering_is_of_what_is_shown(self, tmp_path):
        renders(str(tmp_path), ("edits_from.Lamp_00007__00001_.png",
                                "edits_from.Chair_00001__00005_.png",
                                "edits_from.Chair_00001__00009_.png"))
        entries = listing_for(str(tmp_path),
                              derived_from=["Chair_00001_.png"])
        assert [e["index"] for e in entries] == [1, 2]

    def test_several_approved_renders_show_the_edits_of_each(self, tmp_path):
        renders(str(tmp_path), ("edits_from.Chair_00001__00005_.png",
                                "edits_from.Lamp_00007__00001_.png",
                                "edits_from.Rug_00002__00001_.png"))
        names = [e["name"] for e in listing_for(
            str(tmp_path), derived_from=["Chair_00001_.png", "Lamp_00007_.png"])]
        assert names == ["edits_from.Chair_00001__00005_.png",
                         "edits_from.Lamp_00007__00001_.png"]

    def test_nothing_approved_upstream_means_no_edits_to_show(self, tmp_path):
        """An empty set is a real answer, not the absence of a question — the
        same reading `only` gives it. Listing the whole folder here would offer
        edits of renders nobody approved."""
        renders(str(tmp_path), ("edits_from.Chair_00001__00001_.png",
                                "edits_00002_.png"))
        assert listing_for(str(tmp_path), derived_from=[]) == []

    def test_asking_about_no_parent_at_all_lists_the_folder(self, tmp_path):
        renders(str(tmp_path), ("edits_from.Chair_00001__00001_.png",
                                "edits_00002_.png"))
        assert len(listing_for(str(tmp_path), derived_from=None)) == 2


class TestNarrowingBeforeTheCap:
    """The cap exists so one wrong folder cannot list a whole volume into a
    node body. Applied before the narrowing it does the opposite: it throws
    away the very files that were asked for and hands back an empty grid while
    they sit on disk."""

    def test_a_marked_edit_survives_a_folder_at_the_cap(self, tmp_path):
        from pipeline.pick_folder import LISTING_LIMIT
        # Plain counter names sort before `edits_from.` ("0" < "f"), so every
        # marked edit is at the far end of the listing — exactly where a cap
        # applied first would cut them.
        renders(str(tmp_path),
                tuple(f"edits_{i:05d}_.png" for i in range(LISTING_LIMIT)))
        renders(str(tmp_path), ("edits_from.Chair_00001__00001_.png",))
        names = [e["name"] for e in
                 listing_for(str(tmp_path), derived_from=["Chair_00001_.png"])]
        assert names == ["edits_from.Chair_00001__00001_.png"]

    def test_a_shortlisted_file_survives_a_folder_at_the_cap(self, tmp_path):
        """The same cut, on the narrowing that shipped long before this one."""
        from pipeline.pick_folder import LISTING_LIMIT
        renders(str(tmp_path),
                tuple(f"a{i:05d}.png" for i in range(LISTING_LIMIT)))
        renders(str(tmp_path), ("zzz.png",))
        names = [e["name"] for e in listing_for(str(tmp_path), only=["zzz.png"])]
        assert names == ["zzz.png"]
