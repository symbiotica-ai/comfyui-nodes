# ABOUTME: Tests for the per-region edit prompt builder and crop math used by
# ABOUTME: SymbioticaRegionalEdit.
from pipeline.regional_edit import region_edit_prompt, region_pixel_box


def region(name, desc, members, x=0.1, y=0.1, w=0.5, h=0.25):
    return {"id": "r", "name": name, "desc": desc, "members": members,
            "x": x, "y": y, "w": w, "h": h}


def test_region_pixel_box_clamps_and_min_size():
    assert region_pixel_box(region("A", "d", []), 2048, 2048) == (205, 205, 1229, 717)
    tiny = {"x": 0.999, "y": 0.999, "w": 0.5, "h": 0.5}
    x0, y0, x1, y1 = region_pixel_box(tiny, 100, 100)
    assert x1 > x0 and y1 > y0
    assert x1 <= 100 and y1 <= 100


def test_prompt_contains_subject_and_transfer_framing():
    p = region_edit_prompt(region("Ghost Queue", "cute ghosts with trays", [{}]))
    assert "Ghost Queue: cute ghosts with trays" in p
    assert p.startswith("Edit image 1")
    assert "design shown in image 2" in p
    assert "exact graphic style of image 1" in p


def test_prompt_pair_and_strip_notes():
    pair = region_edit_prompt(region("Cart", "d", [{}, {}]))
    assert "PAIR" in pair and "two copies" in pair
    strip = region_edit_prompt(region("Cookies", "d", [{}, {}, {}]))
    assert "strip of 3 cells" in strip and "one stage per cell" in strip
    single = region_edit_prompt(region("Solo", "d", [{}]))
    assert "PAIR" not in single and "strip of" not in single


def test_prompt_style_override_replaces_image1_style():
    p = region_edit_prompt(region("A", "d", []), style="watercolor storybook")
    assert "Re-render the design in this style: watercolor storybook" in p
    assert "exact graphic style of image 1" not in p
