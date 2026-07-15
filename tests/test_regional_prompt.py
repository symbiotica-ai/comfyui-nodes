# ABOUTME: Tests for the regional prompt builder — ERPK-format parity: box_2d
# ABOUTME: grid, placement phrases, image numbering, and pixel bbox output.
from pipeline.regional_prompt import (
    box_2d,
    build_regional_prompt,
    element_line,
    placement_phrase,
    regions_to_pixel_bboxes,
)


def region(rid, name, desc, x, y, w, h, z):
    return {"id": rid, "name": name, "desc": desc,
            "x": x, "y": y, "w": w, "h": h, "zIndex": z}


def test_placement_phrase_grid():
    assert placement_phrase(0.0, 0.0, 0.1, 0.1) == "at the top-left"
    assert placement_phrase(0.45, 0.45, 0.1, 0.1) == "at the center"
    assert placement_phrase(0.8, 0.8, 0.15, 0.15) == "at the bottom-right"


def test_box_2d_grid_and_clamp():
    assert box_2d({"x": 0.25, "y": 0.1, "w": 0.5, "h": 0.3}) == [100, 250, 400, 750]
    assert box_2d({"x": -0.1, "y": 0.9, "w": 0.5, "h": 0.5}) == [900, 0, 1000, 400]


def test_element_line_with_and_without_ref():
    r = region("a", "Phantom Freezer Cart", "A glowing cart", 0.4, 0.0, 0.2, 0.1, 0)
    with_ref = element_line(r, 2)
    assert with_ref.startswith(
        "Phantom Freezer Cart: A glowing cart, taken from image 2 "
        "(reproduce that exact item): at the top-center. box_2d = ")
    without = element_line(r, None)
    assert "taken from image" not in without


def test_build_prompt_structure_and_numbering():
    regions = [
        region("b", "Back", "behind", 0.1, 0.1, 0.2, 0.2, 0),
        region("f", "Front", "in front", 0.5, 0.5, 0.2, 0.2, 1),
    ]
    prompt = build_regional_prompt("Spooky bakery scene", 2048, 2048, regions,
                                   {"b": 2, "f": 3})
    assert prompt.startswith("Edit the provided image.")
    assert "Spooky bakery scene" in prompt
    assert "The image is 2048x2048 pixels." in prompt
    assert "image 1 is the image being edited" in prompt
    assert "1. Back: behind, taken from image 2" in prompt
    assert "2. Front: in front, taken from image 3" in prompt
    assert prompt.rstrip().endswith("annotation overlays in the image.")


def test_build_prompt_no_refs_omits_legend():
    regions = [region("a", "Solo", "d", 0.1, 0.1, 0.2, 0.2, 0)]
    prompt = build_regional_prompt("", 1024, 1024, regions, {})
    assert "image 1 is the image being edited" not in prompt
    assert "1. Solo: d: at the top-left." in prompt


def test_regions_to_pixel_bboxes_erpk_shape():
    regions = [region("a", "A", "d", 0.25, 0.5, 0.25, 0.25, 1),
               region("b", "B", "d", 0.0, 0.0, 0.5, 0.5, 0)]
    out = regions_to_pixel_bboxes(regions, 1024, 1024)
    assert out == [[
        {"x": 0, "y": 0, "width": 512, "height": 512},
        {"x": 256, "y": 512, "width": 256, "height": 256},
    ]]
    assert regions_to_pixel_bboxes([], 1024, 1024) == []


def test_marker_header_and_per_line_clause():
    regions = [region("a", "Cart", "a glowing cart", 0.1, 0.1, 0.2, 0.2, 0)]
    prompt = build_regional_prompt("", 1000, 1000, regions, {"a": 2},
                                   {"a": ("magenta", "A")})
    assert "Solid colored dots have been drawn on the image" in prompt
    assert ("box_2d = [100, 100, 300, 300] "
            "Center it on marker A (the magenta dot).") in prompt


def test_no_markers_omits_header_and_clause():
    regions = [region("a", "Cart", "d", 0.1, 0.1, 0.2, 0.2, 0)]
    prompt = build_regional_prompt("", 1000, 1000, regions, {"a": 2})
    assert "Solid colored dots" not in prompt
    assert "Center it on marker" not in prompt


def test_target_ref_size_formula():
    from pipeline.regional_prompt import target_ref_size

    # 3-cell food region, 128 canvas scaled x2 -> 768x256.
    r = {"cellPx": {"w": 256, "h": 256},
         "members": [{}, {}, {}]}
    assert target_ref_size(r, 700, 240) == (768, 256)
    # Pair region, unscaled 128 -> 256x128.
    r = {"cellPx": {"w": 128, "h": 128}, "members": [{}, {}]}
    assert target_ref_size(r, 250, 130) == (256, 128)
    # Old region without cellPx keeps the crop size.
    assert target_ref_size({"members": [{}]}, 300, 100) == (300, 100)
