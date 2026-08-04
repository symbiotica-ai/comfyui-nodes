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


# --- transparency ------------------------------------------------------------
# ComfyUI carries an image and its transparency on separate wires, and a loader
# flattens alpha before the image reaches this node. For sprites exported over
# black that means a transparent area arrives BLACK, and pasting it would put a
# black rectangle where the sheet's own colour belongs.

def _sprite_over_black(size=100):
    """A loader's output: art in the middle, black where it was see-through."""
    im = Image.new("RGB", (size, size), (0, 0, 0))
    im.paste(Image.new("RGB", (40, 40), (0, 200, 0)), (30, 30))
    return im


def _alpha_mask(size=100, invert=False):
    """Opaque only where the art is. `invert` gives ComfyUI's LoadImage form."""
    m = Image.new("L", (size, size), 0 if not invert else 255)
    m.paste(Image.new("L", (40, 40), 255 if not invert else 0), (30, 30))
    return m


def test_a_flattened_sprite_without_its_mask_still_shows_black():
    """The bug, pinned: this is what the node did before masks existed."""
    sheet = compose_rows([[_sprite_over_black()]], cell=100, spacing=10,
                         background=(128, 128, 128))
    assert sheet.getpixel((15, 15)) == (0, 0, 0)


def test_loadimage_polarity_puts_the_background_back():
    from pipeline.compare_sheet import with_alpha
    img = with_alpha(_sprite_over_black(), _alpha_mask(invert=True),
                     mask_is_transparency=True)
    sheet = compose_rows([[img]], cell=100, spacing=10,
                         background=(128, 128, 128))
    assert sheet.getpixel((15, 15)) == (128, 128, 128), "background restored"
    assert sheet.getpixel((60, 60)) == (0, 200, 0), "art untouched"


def test_straight_alpha_polarity_works_when_declared():
    """Asset Refs emits straight alpha — 1 where the art is."""
    from pipeline.compare_sheet import with_alpha
    img = with_alpha(_sprite_over_black(), _alpha_mask(invert=False),
                     mask_is_transparency=False)
    sheet = compose_rows([[img]], cell=100, spacing=10,
                         background=(128, 128, 128))
    assert sheet.getpixel((15, 15)) == (128, 128, 128)
    assert sheet.getpixel((60, 60)) == (0, 200, 0)


def test_the_wrong_polarity_cuts_the_sprite_out_instead():
    """Worth pinning: a flipped mask does not fail, it silently inverts what is
    kept — which is why the node asks rather than guesses."""
    from pipeline.compare_sheet import with_alpha
    img = with_alpha(_sprite_over_black(), _alpha_mask(invert=False),
                     mask_is_transparency=True)
    sheet = compose_rows([[img]], cell=100, spacing=10,
                         background=(128, 128, 128))
    assert sheet.getpixel((60, 60)) == (128, 128, 128), "art removed"


def test_a_mask_of_another_size_is_resized_to_its_image():
    """LoadImage hands back a 64x64 all-zero mask for a file with no alpha —
    zero means opaque in its polarity, so the picture must survive whole."""
    from pipeline.compare_sheet import with_alpha
    img = with_alpha(_sprite_over_black(), Image.new("L", (64, 64), 0),
                     mask_is_transparency=True)
    sheet = compose_rows([[img]], cell=100, spacing=10,
                         background=(128, 128, 128))
    assert sheet.getpixel((15, 15)) == (0, 0, 0), "fully opaque, black kept"


def test_no_mask_leaves_the_image_alone():
    from pipeline.compare_sheet import with_alpha
    src = _sprite_over_black()
    assert with_alpha(src, None) is src


def test_an_rgba_image_composites_without_any_mask():
    """A path where alpha survived to PIL — paste through it, never convert."""
    im = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    im.paste(Image.new("RGBA", (40, 40), (0, 200, 0, 255)), (30, 30))
    sheet = compose_rows([[im]], cell=100, spacing=10,
                         background=(128, 128, 128))
    assert sheet.getpixel((15, 15)) == (128, 128, 128)
    assert sheet.getpixel((60, 60)) == (0, 200, 0)


# --- two colours -------------------------------------------------------------
# The packed sheets are grey cells on a black matte. A comparison read beside
# them should carry the same outline, so the cell colour and the gutter colour
# are separate.

def test_gutters_take_the_padding_colour_and_cells_the_background():
    rows = [[_img(100, 100, (255, 0, 0))]]
    sheet = compose_rows(rows, cell=100, spacing=10, background=(128, 128, 128),
                         padding_color=(0, 0, 0))
    assert sheet.getpixel((2, 2)) == (0, 0, 0), "gutter is the matte"
    assert sheet.getpixel((50, 50)) == (255, 0, 0), "the art itself"


def test_an_empty_cell_reads_as_a_cell_not_as_matte():
    rows = [[_img(100, 100, (255, 0, 0)), None]]
    sheet = compose_rows(rows, cell=100, spacing=10, background=(128, 128, 128),
                         padding_color=(0, 0, 0))
    assert sheet.getpixel((170, 50)) == (128, 128, 128)


def test_one_colour_behaves_exactly_as_before():
    """Omitting the padding colour must not change a single pixel of the old
    single-colour sheet."""
    rows = [[_img(100, 100, (255, 0, 0))]]
    before = compose_rows(rows, cell=100, spacing=10, background=(8, 8, 8))
    after = compose_rows(rows, cell=100, spacing=10, background=(8, 8, 8),
                         padding_color=(8, 8, 8))
    assert before.tobytes() == after.tobytes()


# --- reference scale ---------------------------------------------------------
# The reference is often drawn bigger than the finished asset, which makes the
# asset read as the smaller of the two. Shrinking the reference INSIDE its own
# cell fixes the read without moving the grid.

def test_scaling_a_row_keeps_the_sheet_and_the_columns_identical():
    rows = [[_img(100, 100, (255, 0, 0))], [_img(100, 100, (0, 0, 255))]]
    full = compose_rows(rows, cell=100, spacing=10, background=(8, 8, 8))
    scaled = compose_rows(rows, cell=100, spacing=10, background=(8, 8, 8),
                          row_scales=[0.5, 1.0])
    assert full.size == scaled.size, "canvas must not move"


def test_a_scaled_row_is_centred_in_its_cell():
    rows = [[_img(100, 100, (255, 0, 0))], [_img(100, 100, (0, 0, 255))]]
    sheet = compose_rows(rows, cell=100, spacing=10, background=(8, 8, 8),
                         row_scales=[0.5, 1.0])
    # Cell spans 10..110. At 0.5 the picture occupies the middle 50: 35..85.
    assert sheet.getpixel((60, 60)) == (255, 0, 0), "centre of the reference"
    assert sheet.getpixel((20, 60)) == (8, 8, 8), "left of it is background"
    assert sheet.getpixel((100, 60)) == (8, 8, 8), "right of it is background"


def test_the_scaled_row_stays_column_aligned_with_the_unscaled_one():
    rows = [[_img(100, 100, (255, 0, 0)), _img(100, 100, (0, 255, 0))],
            [_img(100, 100, (0, 0, 255)), _img(100, 100, (255, 255, 0))]]
    sheet = compose_rows(rows, cell=100, spacing=10, background=(8, 8, 8),
                         row_scales=[0.5, 1.0])
    # Column 1's centre is x=170 in both rows.
    assert sheet.getpixel((170, 60)) == (0, 255, 0), "reference, column 1"
    assert sheet.getpixel((170, 170)) == (255, 255, 0), "result, column 1"


def test_the_results_row_is_untouched_by_the_reference_scale():
    rows = [[_img(100, 100, (255, 0, 0))], [_img(100, 100, (0, 0, 255))]]
    sheet = compose_rows(rows, cell=100, spacing=10, background=(8, 8, 8),
                         row_scales=[0.5, 1.0])
    assert sheet.getpixel((12, 120)) == (0, 0, 255), "result fills its cell"


def test_scale_of_one_is_pixel_identical_to_no_scale():
    rows = [[_img(100, 100, (255, 0, 0))], [_img(100, 100, (0, 0, 255))]]
    a = compose_rows(rows, cell=100, spacing=10, background=(8, 8, 8))
    b = compose_rows(rows, cell=100, spacing=10, background=(8, 8, 8),
                     row_scales=[1.0, 1.0])
    assert a.tobytes() == b.tobytes()


def test_an_absurd_scale_is_clamped_rather_than_inverting_the_cell():
    rows = [[_img(100, 100, (255, 0, 0))]]
    assert compose_rows(rows, cell=100, spacing=10, background=(8, 8, 8),
                        row_scales=[-3.0]).size == (120, 120)
    assert compose_rows(rows, cell=100, spacing=10, background=(8, 8, 8),
                        row_scales=[9.0]).size == (120, 120)
