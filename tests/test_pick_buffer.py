# ABOUTME: The Pick node's candidate buffer — identity by pixels, tagging,
# ABOUTME: grouping, and the deletions that keep a triage folder from growing forever.
import json
import os

from PIL import Image

from pipeline.pick_buffer import (INDEX_NAME, add_image, buffer_dir, clear,
                                  drop, group_key, groups, image_id,
                                  list_entries, read_index, roles, safe_node_id,
                                  selected_paths, write_index)


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
