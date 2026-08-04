import json

import pytest

from pipeline.sheet_cells import (LAYOUTS, boxes_for_category, cell_boxes,
                                  crop_regions, layout_map, sheet_settings)


# The packer's real settings for the bakery project, and the boxes measured off
# the sheets it actually produced. These are the regression anchor: if the grid
# arithmetic drifts, a generated sheet starts getting cut off-centre and the only
# symptom is artwork clipped at an edge, which reads as a rendering fault.
CANVAS, PADDING = 1024, 20


def test_food2row_matches_the_packed_sheets():
    """Measured on `dataset/Food - 3 stages/*.png`: the single top cell spans
    y 20-501, and the pair below sits at x 20-501 and x 522-1003."""
    boxes = cell_boxes("food2row", CANVAS, CANVAS, PADDING)
    assert [b["role"] for b in boxes] == ["prep", "ready", "serving"]
    assert all(b["w"] == 482 and b["h"] == 482 for b in boxes)
    # Short row centred: prep sits over the midpoint of the pair, not above ready.
    assert (boxes[0]["x"], boxes[0]["y"]) == (271, 20)
    assert (boxes[1]["x"], boxes[1]["y"]) == (20, 522)
    assert (boxes[2]["x"], boxes[2]["y"]) == (522, 522)


def test_pair_matches_the_packed_sheets():
    """Measured on `dataset/Appliances/*.png`: cells at x 20-501 and 522-1003."""
    boxes = cell_boxes("pair", CANVAS, CANVAS, PADDING)
    assert [b["role"] for b in boxes] == ["rot-left", "rot-right"]
    assert [(b["x"], b["w"]) for b in boxes] == [(20, 482), (522, 482)]
    # One row on a square canvas is centred vertically, not pinned to the top.
    assert all(b["y"] == 271 for b in boxes)


def test_grid2x2_fills_both_rows():
    boxes = cell_boxes("grid2x2", CANVAS, CANVAS, PADDING)
    assert [(b["x"], b["y"]) for b in boxes] == [(20, 20), (522, 20),
                                                 (20, 522), (522, 522)]


def test_single_is_one_inset_cell():
    boxes = cell_boxes("single", CANVAS, CANVAS, PADDING)
    assert boxes == [{"role": "single", "x": 20, "y": 20, "w": 984, "h": 984}]


def test_interior_gutter_is_one_padding_not_two():
    """The bug this arithmetic exists to avoid: insetting each cell would make
    every interior gap two paddings wide while the sheet edge got only one."""
    boxes = cell_boxes("pair", CANVAS, CANVAS, PADDING)
    left, right = boxes[0], boxes[1]
    assert right["x"] - (left["x"] + left["w"]) == PADDING
    assert left["x"] == CANVAS - (right["x"] + right["w"])


def test_swapped_reverses_each_row():
    normal = cell_boxes("food2row", CANVAS, CANVAS, PADDING)
    swapped = cell_boxes("food2row", CANVAS, CANVAS, PADDING, swapped=True)
    assert [b["role"] for b in swapped] == ["prep", "serving", "ready"]
    # Only the role↔box pairing flips; the boxes themselves are unmoved.
    assert [(b["x"], b["y"]) for b in normal] == [(b["x"], b["y"])
                                                  for b in swapped]


def test_layouts_that_never_pack_a_sheet_have_no_cells():
    assert cell_boxes("separate", CANVAS, CANVAS, PADDING) == []
    assert cell_boxes("skip", CANVAS, CANVAS, PADDING) == []
    assert cell_boxes("no-such-layout", CANVAS, CANVAS, PADDING) == []


def test_boxes_scale_with_the_canvas():
    small = cell_boxes("food2row", 512, 512, 10)
    assert all(b["w"] == 241 for b in small)
    assert (small[0]["x"], small[0]["y"]) == (135, 10)


def test_absurd_padding_shrinks_instead_of_inverting_the_boxes():
    boxes = cell_boxes("pair", 100, 100, 10_000)
    assert boxes and all(b["w"] > 0 and b["h"] > 0 for b in boxes)


@pytest.fixture()
def project(tmp_path):
    sources = tmp_path / "_sources"
    sources.mkdir()
    (sources / "config.json").write_text(json.dumps({
        "layouts": {"Food - 3 stages": "food2row", "Chair": "grid2x2"},
        "swapped": {"Chair": True},
    }))
    (tmp_path / "assetkit-project.json").write_text(json.dumps({
        "settings": {"width": CANVAS, "height": CANVAS, "padding": PADDING},
    }))
    return tmp_path


def test_reads_the_projects_layout_and_settings(project):
    layouts, swapped = layout_map(str(project))
    assert layouts["Food - 3 stages"] == "food2row"
    assert swapped["Chair"] is True
    assert sheet_settings(str(project)) == (CANVAS, CANVAS, PADDING)


def test_category_boxes_come_from_the_projects_own_rule(project):
    boxes = boxes_for_category(str(project), "Food - 3 stages")
    assert [b["role"] for b in boxes] == ["prep", "ready", "serving"]
    # The per-type swap is applied, so Chair's roles come back mirrored.
    chair = boxes_for_category(str(project), "Chair")
    assert [b["role"] for b in chair][:2] == ["rot-back-right", "rot-back-left"]


def test_unknown_type_falls_back_to_the_whole_image(project):
    boxes = boxes_for_category(str(project), "Wallpaper", 800, 600)
    assert boxes == [{"role": "single", "x": 0, "y": 0, "w": 800, "h": 600}]


def test_a_project_with_no_config_still_cuts_at_the_packers_defaults(tmp_path):
    assert sheet_settings(str(tmp_path)) == (CANVAS, CANVAS, PADDING)
    assert layout_map(str(tmp_path)) == ({}, {})


def test_missing_project_or_category_yields_nothing(project):
    assert boxes_for_category("", "Chair") == []
    assert boxes_for_category(str(project), "") == []


def _write_override(project, category, cells):
    folder = project / "dataset" / category
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "_layout.json").write_text(json.dumps({"cells": cells}))


def test_a_recorded_layout_wins_over_the_computed_grid(project):
    """The packer knows the sprite aspect and the upscale policy; we do not. When
    it says where the cells are, that is the answer."""
    _write_override(project, "Food - 3 stages", [
        {"role": "prep", "x": 5, "y": 6, "w": 100, "h": 70},
    ])
    assert boxes_for_category(str(project), "Food - 3 stages") == [
        {"role": "prep", "x": 5, "y": 6, "w": 100, "h": 70}]


def test_a_malformed_record_is_ignored_whole(project):
    """Half-reading a box list would cut wrongly and look like a render fault."""
    _write_override(project, "Food - 3 stages", [
        {"role": "prep", "x": 5, "y": 6, "w": 100, "h": 70},
        {"role": "ready", "x": "nope"},
    ])
    assert [b["role"] for b in
            boxes_for_category(str(project), "Food - 3 stages")] == [
        "prep", "ready", "serving"]


def test_a_recorded_layout_rescales_to_the_image_being_cut(project):
    _write_override(project, "Chair", [
        {"role": "single", "x": 10, "y": 20, "w": 90, "h": 80},
    ])
    assert boxes_for_category(str(project), "Chair", 200, 200) == [
        {"role": "single", "x": 20, "y": 40, "w": 180, "h": 160}]


def test_same_size_rescale_introduces_no_rounding(project):
    cells = [{"role": "single", "x": 7, "y": 9, "w": 93, "h": 91}]
    _write_override(project, "Chair", cells)
    assert boxes_for_category(str(project), "Chair", 100, 100) == cells


def test_crop_regions_inset_shrinks_towards_the_centre():
    boxes = [{"role": "prep", "x": 20, "y": 20, "w": 482, "h": 482}]
    assert crop_regions(boxes, 1024, 1024, inset=1) == [
        ("prep", 21, 21, 501, 501)]


def test_crop_regions_drops_cells_outside_the_image():
    boxes = [{"role": "a", "x": 0, "y": 0, "w": 10, "h": 10},
             {"role": "b", "x": 900, "y": 900, "w": 10, "h": 10}]
    assert [r[0] for r in crop_regions(boxes, 100, 100)] == ["a"]


def test_crop_regions_drops_a_cell_the_inset_would_invert():
    boxes = [{"role": "tiny", "x": 0, "y": 0, "w": 4, "h": 4}]
    assert crop_regions(boxes, 100, 100, inset=3) == []


def test_every_layout_role_is_unique_within_its_sheet():
    """Roles name the cells downstream, so a duplicate would make two different
    assets answer to the same name."""
    for name, grid in LAYOUTS.items():
        if not grid:
            continue
        roles = [r for row in grid for r in row if r]
        assert len(roles) == len(set(roles)), name


def test_canvas_is_recovered_from_the_boxes():
    """The boxes stop at the last cell, so the far margin is missing from them
    — the grid is centred, which is what makes the full sheet recoverable."""
    from pipeline.sheet_cells import canvas_of
    assert canvas_of(cell_boxes("food2row", CANVAS, CANVAS, PADDING)) == (
        CANVAS, CANVAS)
    assert canvas_of(cell_boxes("pair", CANVAS, CANVAS, PADDING)) == (
        CANVAS, CANVAS)
    assert canvas_of(cell_boxes("grid2x2", CANVAS, CANVAS, PADDING)) == (
        CANVAS, CANVAS)
    assert canvas_of(cell_boxes("single", CANVAS, CANVAS, PADDING)) == (
        CANVAS, CANVAS)


def test_canvas_of_nothing_is_nothing():
    from pipeline.sheet_cells import canvas_of
    assert canvas_of([]) == (0, 0)
