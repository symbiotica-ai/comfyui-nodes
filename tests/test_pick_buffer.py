# ABOUTME: The Pick node's candidate buffer — identity by pixels, tagging,
# ABOUTME: grouping, and the deletions that keep a triage folder from growing forever.
import json
import os

from PIL import Image

from pipeline.pick_buffer import (BUFFER_ROOT, INDEX_NAME, add_image,
                                  buffer_dir, clear,
                                  drop, folder_signature, group_key, groups,
                                  image_id, import_folder, import_if_changed,
                                  keep_picks, list_entries,
                                  name_matches_prefix,
                                  read_index, roles, safe_node_id,
                                  selected_paths, tag_from_path,
                                  write_index)


def solid(color=(10, 20, 30), size=(8, 6), mode="RGB"):
    return Image.new(mode, size, color)


class TestNodeIdBecomesADirectory:
    def test_an_ordinary_id_is_used_as_is(self):
        assert safe_node_id(42) == "42"
        assert safe_node_id("12:3") == "123"

    def test_traversal_cannot_escape_the_buffer_root(self):
        """The id reaches this from the graph and becomes a path segment, so
        the separators and dots have to be gone, not merely escaped."""
        assert safe_node_id("../../etc") == "etc"
        assert safe_node_id("/absolute/path") == "absolutepath"
        assert safe_node_id("a\x00b") == "ab"

    def test_an_id_that_reduces_to_nothing_still_gets_a_buffer(self):
        """Otherwise the join lands on the parent directory and one node's
        candidates would be written loose among every other node's."""
        assert safe_node_id("...") == "unknown"
        assert safe_node_id(None) == "unknown"
        assert safe_node_id("") == "unknown"

    def test_two_nodes_get_two_buffers(self, tmp_path):
        assert buffer_dir(str(tmp_path), 1) != buffer_dir(str(tmp_path), 2)
        assert buffer_dir(str(tmp_path), 7).startswith(str(tmp_path))


class TestIdentityIsThePixels:
    def test_the_same_image_twice_is_one_candidate(self, tmp_path):
        """The generator replays from ComfyUI's cache every time a downstream
        node is queued, so the picker is handed the same frame repeatedly. It
        must not stack up as a new thumbnail each press."""
        d = str(tmp_path / "buf")
        assert add_image(d, solid()) is not None
        assert add_image(d, solid()) is None
        assert len(list_entries(d)) == 1

    def test_different_pixels_are_different_candidates(self, tmp_path):
        d = str(tmp_path / "buf")
        add_image(d, solid((10, 20, 30)))
        add_image(d, solid((10, 20, 31)))
        assert len(list_entries(d)) == 2

    def test_same_pixels_at_a_different_size_do_not_collide(self):
        assert image_id(solid(size=(8, 6))) != image_id(solid(size=(6, 8)))


class TestWhatIsWrittenToDisk:
    def test_a_full_image_and_a_thumbnail_land_beside_the_index(self, tmp_path):
        d = str(tmp_path / "buf")
        entry = add_image(d, solid(size=(900, 700)))
        assert os.path.isfile(os.path.join(d, entry["file"]))
        assert os.path.isfile(os.path.join(d, entry["thumb"]))
        assert os.path.isfile(os.path.join(d, INDEX_NAME))

    def test_the_thumbnail_is_small_and_the_full_image_is_not(self, tmp_path):
        """The grid draws every candidate at once; serving full-size renders
        into 100px tiles is what makes a node feel broken."""
        d = str(tmp_path / "buf")
        entry = add_image(d, solid(size=(900, 700)))
        assert max(Image.open(os.path.join(d, entry["thumb"])).size) <= 320
        assert Image.open(os.path.join(d, entry["file"])).size == (900, 700)

    def test_transparency_survives_being_filed(self, tmp_path):
        """A background-removed candidate judged on a flattened thumbnail is
        being judged on the wrong image."""
        d = str(tmp_path / "buf")
        entry = add_image(d, solid((10, 20, 30, 0), mode="RGBA"))
        stored = Image.open(os.path.join(d, entry["file"]))
        assert stored.mode == "RGBA"
        assert stored.getpixel((0, 0))[3] == 0

    def test_the_index_is_replaced_atomically(self, tmp_path):
        d = str(tmp_path / "buf")
        add_image(d, solid())
        assert not os.path.exists(os.path.join(d, INDEX_NAME + ".tmp"))


class TestReadingABrokenBuffer:
    def test_a_missing_index_reads_as_empty(self, tmp_path):
        assert read_index(str(tmp_path / "nope")) == []

    def test_a_corrupt_index_reads_as_empty_rather_than_raising(self, tmp_path):
        """A half-written JSON file must not be able to hide every candidate
        behind a stack trace on the canvas."""
        d = tmp_path / "buf"
        d.mkdir()
        (d / INDEX_NAME).write_text('[{"id": "a"')
        assert read_index(str(d)) == []

    def test_an_entry_whose_image_was_deleted_by_hand_is_dropped(self, tmp_path):
        """The buffer lives in the output directory, which people do clean out."""
        d = str(tmp_path / "buf")
        keep = add_image(d, solid((1, 2, 3)))
        gone = add_image(d, solid((4, 5, 6)))
        os.remove(os.path.join(d, gone["file"]))
        entries = list_entries(d)
        assert [e["id"] for e in entries] == [keep["id"]]
        assert [e["id"] for e in read_index(d)] == [keep["id"]]

    def test_a_missing_thumbnail_falls_back_to_the_full_image(self, tmp_path):
        d = str(tmp_path / "buf")
        entry = add_image(d, solid())
        os.remove(os.path.join(d, entry["thumb"]))
        assert list_entries(d)[0]["thumb_path"] == os.path.join(d, entry["file"])

    def test_an_index_that_is_not_a_list_reads_as_empty(self, tmp_path):
        d = tmp_path / "buf"
        d.mkdir()
        (d / INDEX_NAME).write_text('{"id": "a"}')
        assert read_index(str(d)) == []


class TestTagsAndGroups:
    def test_the_label_runs_coarse_to_fine(self):
        assert group_key({"feature": "Halloween", "category": "Food",
                          "asset": "pumpkin-cake"}) == \
            "Halloween / Food / pumpkin-cake"

    def test_missing_parts_drop_out_instead_of_leaving_separators(self):
        assert group_key({"category": "Food"}) == "Food"
        assert group_key({"feature": "Halloween", "asset": "cake"}) == \
            "Halloween / cake"

    def test_an_untagged_candidate_groups_under_a_name_of_its_own(self):
        """An empty label renders as a blank row in the node's filter."""
        assert group_key({}) == "untagged"

    def test_a_candidate_carries_the_context_it_was_recorded_under(self, tmp_path):
        d = str(tmp_path / "buf")
        add_image(d, solid(), tag={"asset": "cake", "category": "Food",
                                   "feature": "Halloween", "month": "10"})
        entry = list_entries(d)[0]
        assert entry["asset"] == "cake"
        assert entry["month"] == "10"
        assert entry["group"] == "Halloween / Food / cake"

    def test_groups_are_counted_in_the_order_they_appeared(self, tmp_path):
        """Arrival order, not alphabetical: the thing being worked on now stays
        where it turned up rather than jumping around the list."""
        d = str(tmp_path / "buf")
        add_image(d, solid((1, 1, 1)), tag={"asset": "zebra"})
        add_image(d, solid((2, 2, 2)), tag={"asset": "apple"})
        add_image(d, solid((3, 3, 3)), tag={"asset": "zebra"})
        assert groups(list_entries(d)) == [
            {"key": "zebra", "count": 2}, {"key": "apple", "count": 1}]


class TestReadingTheTicksBack:
    def test_selected_paths_returns_only_the_ticked_ones(self, tmp_path):
        d = str(tmp_path / "buf")
        a = add_image(d, solid((1, 1, 1)))
        add_image(d, solid((2, 2, 2)))
        c = add_image(d, solid((3, 3, 3)))
        picked = selected_paths(d, [a["id"], c["id"]])
        assert [os.path.basename(p) for p in picked] == [a["file"], c["file"]]

    def test_order_is_the_buffer_not_the_order_the_ids_were_given(self, tmp_path):
        """The run has to be reproducible from the saved workflow, and click
        order is not recorded anywhere."""
        d = str(tmp_path / "buf")
        a = add_image(d, solid((1, 1, 1)))
        b = add_image(d, solid((2, 2, 2)))
        picked = selected_paths(d, [b["id"], a["id"]])
        assert [os.path.basename(p) for p in picked] == [a["file"], b["file"]]

    def test_a_tick_that_outlived_its_image_is_skipped_not_raised(self, tmp_path):
        d = str(tmp_path / "buf")
        a = add_image(d, solid())
        assert selected_paths(d, [a["id"], "deadbeef"]) == \
            [os.path.join(d, a["file"])]

    def test_nothing_ticked_is_nothing_picked(self, tmp_path):
        d = str(tmp_path / "buf")
        add_image(d, solid())
        assert selected_paths(d, []) == []
        assert selected_paths(d, None) == []


class TestDeleting:
    def test_dropping_one_removes_its_image_and_its_thumbnail(self, tmp_path):
        d = str(tmp_path / "buf")
        a = add_image(d, solid((1, 1, 1)))
        b = add_image(d, solid((2, 2, 2)))
        assert drop(d, [a["id"]]) == 1
        assert not os.path.exists(os.path.join(d, a["file"]))
        assert not os.path.exists(os.path.join(d, a["thumb"]))
        assert [e["id"] for e in list_entries(d)] == [b["id"]]

    def test_dropping_nothing_touches_nothing(self, tmp_path):
        d = str(tmp_path / "buf")
        add_image(d, solid())
        assert drop(d, []) == 0
        assert len(list_entries(d)) == 1

    def test_dropping_an_unknown_id_is_not_an_error(self, tmp_path):
        d = str(tmp_path / "buf")
        add_image(d, solid())
        assert drop(d, ["nope"]) == 0
        assert len(list_entries(d)) == 1

    def test_clear_empties_the_whole_buffer(self, tmp_path):
        d = str(tmp_path / "buf")
        add_image(d, solid())
        clear(d)
        assert list_entries(d) == []

    def test_clearing_a_buffer_that_never_existed_is_not_an_error(self, tmp_path):
        clear(str(tmp_path / "never"))


class TestIndexRoundTrip:
    def test_written_entries_read_back(self, tmp_path):
        d = str(tmp_path / "buf")
        write_index(d, [{"id": "a"}, {"id": "b"}])
        assert read_index(d) == [{"id": "a"}, {"id": "b"}]

    def test_non_dict_rows_are_skipped(self, tmp_path):
        d = tmp_path / "buf"
        d.mkdir()
        (d / INDEX_NAME).write_text(json.dumps([{"id": "a"}, "junk", 7]))
        assert read_index(str(d)) == [{"id": "a"}]


class TestStageRows:
    """He works a food asset as prep / ready / serving and wants each stage on
    its own row, compared against its own alternatives."""

    def test_a_candidate_records_the_stage_it_is(self, tmp_path):
        d = str(tmp_path / "buf")
        add_image(d, solid(), tag={"asset": "cake", "role": "prep"})
        assert list_entries(d)[0]["role"] == "prep"

    def test_the_stage_is_not_part_of_the_group_label(self, tmp_path):
        """Otherwise an asset's three stages become three groups that have to
        be switched between, which is the opposite of comparing them."""
        d = str(tmp_path / "buf")
        add_image(d, solid((1, 1, 1)), tag={"asset": "cake", "role": "prep"})
        add_image(d, solid((2, 2, 2)), tag={"asset": "cake", "role": "serving"})
        assert {e["group"] for e in list_entries(d)} == {"cake"}

    def test_rows_come_back_in_the_order_the_sheet_was_cut(self, tmp_path):
        """Arrival order, not alphabetical — alphabetically prep follows ready."""
        d = str(tmp_path / "buf")
        for i, role in enumerate(("prep", "ready", "serving", "prep")):
            add_image(d, solid((i + 1, i + 1, i + 1)), tag={"role": role})
        assert roles(list_entries(d)) == ["prep", "ready", "serving"]

    def test_untagged_candidates_report_one_empty_row(self, tmp_path):
        d = str(tmp_path / "buf")
        add_image(d, solid())
        assert roles(list_entries(d)) == [""]


class TestImportingAFolderThatAlreadyExists:
    """The buffer is per node, so a picker added after the work was generated
    starts empty — and re-running the generator to fill it pays for renders
    that already exist."""

    def make(self, folder, names, colour=10):
        os.makedirs(folder, exist_ok=True)
        for i, name in enumerate(names):
            Image.new("RGB", (6, 6), (colour + i, 0, 0)).save(
                os.path.join(folder, name))

    def test_every_image_in_the_folder_becomes_a_candidate(self, tmp_path):
        src = str(tmp_path / "renders")
        self.make(src, ["a.png", "b.png", "c.jpg"])
        result = import_folder(str(tmp_path / "buf"), src)
        assert result["added"] == 3
        assert len(list_entries(str(tmp_path / "buf"))) == 3

    def test_subfolders_are_read_too(self, tmp_path):
        """Renders are filed one directory per asset; pointing at the parent is
        the natural thing to do."""
        src = str(tmp_path / "renders")
        self.make(src, ["a.png"])
        self.make(os.path.join(src, "cake"), ["b.png"], colour=90)
        assert import_folder(str(tmp_path / "buf"), src)["added"] == 2

    def test_importing_twice_does_not_double_the_buffer(self, tmp_path):
        src = str(tmp_path / "renders")
        self.make(src, ["a.png", "b.png"])
        d = str(tmp_path / "buf")
        import_folder(d, src)
        second = import_folder(d, src)
        assert second == {"added": 0, "skipped": 2, "failed": 0,
                          "filtered": 0, "found": 2, "truncated": 0}
        assert len(list_entries(d)) == 2

    def test_the_tag_is_applied_to_everything_imported(self, tmp_path):
        src = str(tmp_path / "renders")
        self.make(src, ["a.png"])
        import_folder(str(tmp_path / "buf"), src,
                      tag={"asset": "cake", "category": "Food", "role": "prep"})
        entry = list_entries(str(tmp_path / "buf"))[0]
        assert (entry["asset"], entry["role"]) == ("cake", "prep")

    def test_a_file_that_will_not_open_does_not_abort_the_import(self, tmp_path):
        """One bad file must not cost the other three hundred."""
        src = str(tmp_path / "renders")
        self.make(src, ["a.png"])
        with open(os.path.join(src, "broken.png"), "wb") as fh:
            fh.write(b"not a png")
        result = import_folder(str(tmp_path / "buf"), src)
        assert (result["added"], result["failed"]) == (1, 1)

    def test_non_images_are_ignored(self, tmp_path):
        src = str(tmp_path / "renders")
        self.make(src, ["a.png"])
        open(os.path.join(src, "notes.txt"), "w").close()
        assert import_folder(str(tmp_path / "buf"), src)["found"] == 1

    def test_the_buffers_own_thumbnails_are_not_re_imported(self, tmp_path):
        """Importing a thumbnail would file a 320px copy as a candidate of its
        own, beside the full image it is a thumbnail OF."""
        d = str(tmp_path / "buf")
        add_image(d, solid(size=(400, 400)))
        assert import_folder(str(tmp_path / "buf2"), d)["found"] == 1

    def test_a_huge_folder_is_capped_and_says_so(self, tmp_path):
        """One wrong click on a whole output volume must not file thousands."""
        src = str(tmp_path / "renders")
        self.make(src, [f"{i:03d}.png" for i in range(12)])
        result = import_folder(str(tmp_path / "buf"), src, limit=5)
        assert (result["added"], result["found"], result["truncated"]) == (5, 12, 7)

    def test_a_folder_that_is_not_there_imports_nothing(self, tmp_path):
        assert import_folder(str(tmp_path / "buf"),
                             str(tmp_path / "nope"))["found"] == 0


class TestTagsReadOffTheFolderStructure:
    """Renders are filed `outputs/<month>/<event>/<category>/<recipe>/…`, so
    the path already says what an image is."""

    def make(self, folder, names=("a.png",), colour=10):
        os.makedirs(folder, exist_ok=True)
        for i, name in enumerate(names):
            Image.new("RGB", (6, 6), (colour + i, 0, 0)).save(
                os.path.join(folder, name))

    def test_the_four_levels_below_outputs_become_the_tag(self):
        tag = tag_from_path(
            "/studio/outputs/October/Mini 3 — Franken-Feast/Food - 3 stages/"
            "Frankencrisps")
        assert tag == {"month": "October", "feature": "Mini 3 — Franken-Feast",
                       "category": "Food - 3 stages", "asset": "Frankencrisps"}

    def test_a_partial_tree_fills_only_what_is_there(self):
        assert tag_from_path("/studio/outputs/October") == {"month": "October"}

    def test_subfolders_of_the_pointed_folder_continue_the_chain(self):
        """Point at the category and each recipe under it becomes its own asset
        in a single read."""
        tag = tag_from_path("/studio/outputs/October/Mini 3/Food",
                            "Frankencrisps/a.png")
        assert tag["asset"] == "Frankencrisps"
        assert tag["category"] == "Food"

    def test_the_last_outputs_wins_so_a_higher_one_shifts_nothing(self):
        tag = tag_from_path("/outputs/studio/outputs/October/Mini 3/Food/Cake")
        assert tag["month"] == "October" and tag["asset"] == "Cake"

    def test_levels_below_the_asset_are_ignored_not_folded_in(self):
        """Inventing a name for a deeper tree would file one asset under two
        labels."""
        tag = tag_from_path("/studio/outputs/Oct/Ev/Cat/Cake/extra/deeper")
        assert tag["asset"] == "Cake"

    def test_without_an_outputs_anchor_only_the_deepest_folder_is_read(self):
        assert tag_from_path("/somewhere/else/Frankencrisps") == \
            {"asset": "Frankencrisps"}

    def test_an_import_tags_each_recipe_from_its_own_subfolder(self, tmp_path):
        base = tmp_path / "outputs" / "October" / "Mini 3" / "Food - 3 stages"
        self.make(str(base / "Frankencrisps"), ("a.png",), colour=10)
        self.make(str(base / "Frankenstein Pops"), ("b.png",), colour=90)
        d = str(tmp_path / "buf")
        import_folder(d, str(base))
        by_asset = {e["asset"]: e for e in list_entries(d)}
        assert set(by_asset) == {"Frankencrisps", "Frankenstein Pops"}
        assert by_asset["Frankencrisps"]["group"] == \
            "Mini 3 / Food - 3 stages / Frankencrisps"

    def test_a_typed_value_overrides_what_the_path_says(self, tmp_path):
        base = tmp_path / "outputs" / "October" / "Mini 3" / "Food" / "Cake"
        self.make(str(base))
        d = str(tmp_path / "buf")
        import_folder(d, str(base), tag={"asset": "Renamed", "role": "prep"})
        entry = list_entries(d)[0]
        assert (entry["asset"], entry["role"]) == ("Renamed", "prep")
        assert entry["category"] == "Food"

    def test_a_blank_value_does_not_erase_what_the_path_says(self, tmp_path):
        """An untyped widget must not wipe a label the folder structure gave."""
        base = tmp_path / "outputs" / "October" / "Mini 3" / "Food" / "Cake"
        self.make(str(base))
        d = str(tmp_path / "buf")
        import_folder(d, str(base), tag={"asset": "", "category": "  "})
        entry = list_entries(d)[0]
        assert (entry["asset"], entry["category"]) == ("Cake", "Food")


class TestTheBuffersDoNotImportThemselves:
    def test_the_buffer_root_is_skipped_when_reading_its_parent(self, tmp_path):
        """The buffers live under the output directory. Pointing an import at
        that directory would re-file every picker's own copies as candidates of
        a new picker — one click to duplicate the lot."""
        out = tmp_path / "outputs"
        (out / "renders").mkdir(parents=True)
        Image.new("RGB", (6, 6), (5, 5, 5)).save(out / "renders" / "real.png")
        add_image(str(out / BUFFER_ROOT / "483"), solid((9, 9, 9)))
        result = import_folder(str(tmp_path / "buf"), str(out))
        assert result["found"] == 1


class TestThePassAPickerIsPinnedTo:
    """Three pickers — one in the Base image group, one in Edit, one in Export.
    A render and its exported cutout are different kinds of thing, not
    alternatives to each other."""

    def make(self, folder, names=("a.png",), colour=10):
        os.makedirs(folder, exist_ok=True)
        for i, name in enumerate(names):
            Image.new("RGB", (6, 6), (colour + i, 0, 0)).save(
                os.path.join(folder, name))

    def test_the_fifth_level_is_the_pass(self):
        tag = tag_from_path("/s/outputs/Oct/Mini 3/Food/Frankencrisps/export")
        assert tag["asset"] == "Frankencrisps" and tag["phase"] == "export"

    def test_levels_below_the_pass_are_still_ignored(self):
        tag = tag_from_path("/s/outputs/Oct/Ev/Cat/Cake/export/v2/deeper")
        assert tag["phase"] == "export"

    def test_a_recorded_candidate_carries_its_pass(self, tmp_path):
        d = str(tmp_path / "buf")
        add_image(d, solid(), tag={"asset": "cake", "phase": "edit"})
        assert list_entries(d)[0]["phase"] == "edit"

    def test_a_pinned_picker_reads_only_its_own_pass(self, tmp_path):
        """Filtering at import keeps two thirds of the images off its disk
        instead of merely off its grid."""
        base = tmp_path / "outputs" / "Oct" / "Mini 3" / "Food" / "Cake"
        for i, phase in enumerate(("base", "edit", "export")):
            self.make(str(base / phase), ("a.png",), colour=10 + i * 40)
        d = str(tmp_path / "buf")
        result = import_folder(d, str(base), only_phase="export")
        assert (result["added"], result["filtered"], result["found"]) == (1, 2, 3)
        assert list_entries(d)[0]["phase"] == "export"

    def test_no_pin_reads_every_pass(self, tmp_path):
        base = tmp_path / "outputs" / "Oct" / "Mini 3" / "Food" / "Cake"
        for i, phase in enumerate(("base", "edit", "export")):
            self.make(str(base / phase), ("a.png",), colour=10 + i * 40)
        d = str(tmp_path / "buf")
        assert import_folder(d, str(base))["added"] == 3

    def test_the_pass_is_not_part_of_the_group_label(self, tmp_path):
        """Each picker is pinned to one pass already, so repeating it in every
        label is noise."""
        d = str(tmp_path / "buf")
        add_image(d, solid(), tag={"asset": "cake", "phase": "export"})
        assert list_entries(d)[0]["group"] == "cake"


class TestReadingComfyUIsOwnSaveLayout:
    """A Save Image node given `…/Food/Spookies` writes
    `Food/Spookies_00001_.png` — the last segment of a filename prefix names
    the FILE. A picker deriving `…/Food/Spookies` as a folder found nothing."""

    def make(self, folder, names, colour=10):
        os.makedirs(folder, exist_ok=True)
        for i, name in enumerate(names):
            Image.new("RGB", (6, 6), (colour + i, 0, 0)).save(
                os.path.join(folder, name))

    def test_only_the_named_assets_files_are_read(self, tmp_path):
        src = str(tmp_path / "outputs" / "Oct" / "Ev" / "Food")
        self.make(src, ("Spookies_00001_.png", "Spookies_00002_.png",
                        "Ghosts_00001_.png"))
        d = str(tmp_path / "buf")
        assert import_folder(d, src, name_prefix="Spookies")["added"] == 2

    def test_a_longer_asset_name_is_not_claimed_by_a_shorter_one(self):
        assert name_matches_prefix("Spookies_00001_.png", "Spookies") is True
        assert name_matches_prefix("Spookies.png", "Spookies") is True
        assert name_matches_prefix("Spookies Deluxe_00001_.png",
                                   "Spookies") is False

    def test_the_prefix_read_does_not_descend(self, tmp_path):
        """The category folder holds every asset of that category, so
        recursing would drag in every other asset's subfolders — which is the
        mess the prefix exists to avoid."""
        src = str(tmp_path / "outputs" / "Oct" / "Ev" / "Food")
        self.make(src, ("Spookies_00001_.png",))
        self.make(os.path.join(src, "Ghosts"), ("a.png",), colour=90)
        d = str(tmp_path / "buf")
        assert import_folder(d, src, name_prefix="Spookies")["added"] == 1

    def test_the_signature_ignores_other_assets_renders(self, tmp_path):
        """Or every render of any asset in the category would say this one
        changed, and re-read it for nothing."""
        src = str(tmp_path / "outputs" / "Oct" / "Ev" / "Food")
        self.make(src, ("Spookies_00001_.png",))
        before = folder_signature(src, "Spookies")
        self.make(src, ("Ghosts_00001_.png",), colour=90)
        assert folder_signature(src, "Spookies") == before

    def test_the_same_folder_read_both_ways_is_not_one_mark(self, tmp_path):
        """A picker reads its asset's folder AND its prefixed files. Keying the
        mark by folder alone would tell the second read nothing had changed."""
        src = str(tmp_path / "outputs" / "Oct" / "Ev" / "Food")
        self.make(src, ("Spookies_00001_.png", "Ghosts_00001_.png"))
        d = str(tmp_path / "buf")
        assert import_if_changed(d, src)["added"] == 2
        assert import_if_changed(d, src, name_prefix="Spookies") is not None


class TestKeepingWhatWasGood:
    """"images picked should land in …/Spookies/Base so we only keep what was
    good in these folders" — the buffer is scratch, so approval that lives only
    there is not a delivery."""

    def imported(self, tmp_path, name="Spookies_00007_.png"):
        src = str(tmp_path / "outputs" / "Oct" / "Ev" / "Food")
        os.makedirs(src, exist_ok=True)
        Image.new("RGB", (6, 6), (11, 0, 0)).save(os.path.join(src, name))
        d = str(tmp_path / "buf")
        import_folder(d, src, name_prefix="Spookies")
        return list_entries(d)

    def test_a_pick_keeps_the_name_it_was_rendered_under(self, tmp_path):
        dest = str(tmp_path / "outputs" / "Oct" / "Ev" / "Food" / "Spookies"
                   / "Base")
        written = keep_picks(self.imported(tmp_path), dest)
        assert [os.path.basename(p) for p in written] == ["Spookies_00007_.png"]
        assert os.path.isfile(os.path.join(dest, "Spookies_00007_.png"))

    def test_an_image_that_never_had_a_name_still_gets_one(self, tmp_path):
        """Straight off the wire there is no filename to keep, and a bare pixel
        hash in a delivery folder is not something anyone can match by eye."""
        d = str(tmp_path / "buf")
        add_image(d, solid(), tag={"asset": "Spookies"})
        written = keep_picks(list_entries(d), str(tmp_path / "keep"))
        assert os.path.basename(written[0]).startswith("Spookies_")

    def test_keeping_twice_writes_once(self, tmp_path):
        """Every queue emits the same ticks; rewriting them each time would
        churn the delivery folder and its sync."""
        entries = self.imported(tmp_path)
        dest = str(tmp_path / "keep")
        assert len(keep_picks(entries, dest)) == 1
        assert keep_picks(entries, dest) == []

    def test_the_rejects_are_left_where_they_are(self, tmp_path):
        """Copied, never moved: deleting what was not picked is a different
        decision, and not one a node makes on its own."""
        entries = self.imported(tmp_path)
        keep_picks(entries, str(tmp_path / "keep"))
        assert os.path.isfile(str(tmp_path / "outputs" / "Oct" / "Ev" / "Food"
                                  / "Spookies_00007_.png"))

    def test_an_unwritable_destination_does_not_raise(self, tmp_path):
        """The picks are still on the wire, which is what the run is for."""
        entries = self.imported(tmp_path)
        blocker = tmp_path / "afile"
        blocker.write_text("not a directory")
        assert keep_picks(entries, str(blocker / "Base")) == []


class TestBothSpellingsOfTheOutputDirectory:
    def test_comfyuis_own_output_directory_anchors_too(self):
        """A default install calls it `output`; matching only `outputs` would
        silently reduce every derived tag to a bare asset name."""
        assert tag_from_path("/root/output/Oct/Ev/Food/Cake") == {
            "month": "Oct", "feature": "Ev", "category": "Food", "asset": "Cake"}

    def test_the_studios_plural_spelling_still_anchors(self):
        assert tag_from_path("/s/outputs/Oct/Ev/Food/Cake")["month"] == "Oct"
