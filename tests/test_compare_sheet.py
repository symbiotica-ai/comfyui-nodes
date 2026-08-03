# ABOUTME: Layout maths for the reference-over-result sheet — gutters, fitting,
# ABOUTME: and the column alignment that is the whole point of the thing.
import pytest
from PIL import Image

from pipeline.compare_sheet import (auto_cell, cell_origin, compose_rows,
                                    fit_box, grid_size)


def test_gutter_is_counted_once_more_than_the_cells():
    # Two cells of 100 with 10 spacing: border, cell, gap, cell, border.
    assert grid_size(2, 1, 100, 10) == (230, 120)


def test_every_gap_is_the_same_width_including_the_border():
    x0, _ = cell_origin(0, 0, 100, 10)
    x1, _ = cell_origin(1, 0, 100, 10)
    width, _ = grid_size(2, 1, 100, 10)
    assert x0 == 10
    assert x1 - (x0 + 100) == 10, "interior gap"
    assert width - (x1 + 100) == 10, "right border matches"


def test_rows_stack_by_the_same_arithmetic():
    _, y0 = cell_origin(0, 0, 100, 10)
    _, y1 = cell_origin(0, 1, 100, 10)
    assert y1 - (y0 + 100) == 10


def test_a_wide_image_is_fitted_and_centred_not_stretched():
    """A reference squashed to a different aspect than the result beside it is
    the one distortion that would make the sheet lie about what changed."""
    w, h, dx, dy = fit_box(200, 100, 100)
    assert (w, h) == (100, 50)
    assert (dx, dy) == (0, 25)


def test_a_tall_image_is_fitted_the_other_way():
    w, h, dx, dy = fit_box(100, 200, 100)
    assert (w, h) == (50, 100)
    assert (dx, dy) == (25, 0)


def test_a_square_image_fills_its_cell():
    assert fit_box(64, 64, 100)[:2] == (100, 100)


def test_a_degenerate_size_does_not_divide_by_zero():
    assert fit_box(0, 10, 100) == (0, 0, 0, 0)


def test_auto_cell_takes_the_largest_edge():
    # Nothing gets enlarged into softness; the biggest is shown at its own size.
    assert auto_cell([(480, 480), (1024, 1024), (200, 900)]) == 1024
    assert auto_cell([]) == 512


def _img(w, h, colour):
    return Image.new("RGB", (w, h), colour)


def test_composes_two_rows_at_the_expected_size():
    rows = [[_img(50, 50, "red"), _img(50, 50, "red")],
            [_img(50, 50, "blue"), _img(50, 50, "blue")]]
    sheet = compose_rows(rows, cell=100, spacing=10, background=(8, 8, 8))
    assert sheet.size == grid_size(2, 2, 100, 10)


def test_each_row_lands_in_its_own_band():
    rows = [[_img(100, 100, (255, 0, 0))],
            [_img(100, 100, (0, 0, 255))]]
    sheet = compose_rows(rows, cell=100, spacing=10, background=(8, 8, 8))
    assert sheet.getpixel((60, 60)) == (255, 0, 0), "reference on top"
    assert sheet.getpixel((60, 170)) == (0, 0, 255), "result beneath"


def test_a_short_row_keeps_its_hole_so_columns_stay_paired():
    """Column alignment IS the sheet's argument. A row that closed up would put
    each result under the wrong reference."""
    rows = [[_img(100, 100, (255, 0, 0)), _img(100, 100, (255, 0, 0))],
            [None, _img(100, 100, (0, 0, 255))]]
    sheet = compose_rows(rows, cell=100, spacing=10, background=(8, 8, 8))
    # Bottom-left cell stays background; the single result sits under column 2.
    assert sheet.getpixel((60, 170)) == (8, 8, 8)
    assert sheet.getpixel((170, 170)) == (0, 0, 255)


def test_gutters_show_the_background():
    rows = [[_img(100, 100, (255, 0, 0))]]
    sheet = compose_rows(rows, cell=100, spacing=10, background=(8, 8, 8))
    assert sheet.getpixel((2, 2)) == (8, 8, 8)


def test_mixed_sizes_share_one_cell():
    rows = [[_img(40, 40, (255, 0, 0)), _img(200, 200, (255, 0, 0))]]
    sheet = compose_rows(rows, cell=100, spacing=10, background=(8, 8, 8))
    assert sheet.size == grid_size(2, 1, 100, 10)


def test_nothing_to_lay_out_is_an_error_not_a_blank_image():
    with pytest.raises(ValueError, match="nothing to lay out"):
        compose_rows([], cell=100, spacing=10, background=(0, 0, 0))
