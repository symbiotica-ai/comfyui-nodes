# ABOUTME: Tests for set-of-mark placement markers — color/letter assignment
# ABOUTME: (ERPK parity) and the PIL dot renderer used on the image 1 output.
from PIL import Image

from pipeline.markers import MARKER_COLORS, assign_markers, draw_placement_markers


def region(rid, name, desc, x, y, w, h, z):
    return {"id": rid, "name": name, "desc": desc,
            "x": x, "y": y, "w": w, "h": h, "zIndex": z}


def test_assign_markers_sequential_letters_in_depth_order():
    regions = [
        region("front", "Front", "", 0.5, 0.5, 0.2, 0.2, 1),
        region("back", "Back", "", 0.1, 0.1, 0.2, 0.2, 0),
    ]
    marks = assign_markers(regions)
    # Letters follow back-to-front (zIndex) order, matching the prompt list.
    assert marks["back"] == ("magenta", "A")
    assert marks["front"] == ("cyan", "B")


def test_assign_markers_skips_color_named_in_desc():
    regions = [region("a", "Potion", "a magenta bottle", 0.1, 0.1, 0.2, 0.2, 0)]
    marks = assign_markers(regions)
    color, label = marks["a"]
    assert color != "magenta"
    assert label == "A"


def test_assign_markers_exhaustion_reuses_palette():
    regions = [region(f"r{i}", f"R{i}", "", 0.1, 0.1, 0.2, 0.2, i)
               for i in range(len(MARKER_COLORS) + 1)]
    marks = assign_markers(regions)
    # 7th region: every color used once, falls back to the first palette entry.
    assert marks["r6"] == ("magenta", "G")
    assert len(marks) == 7


def test_draw_placement_markers_stamps_dot_and_leaves_rest():
    img = Image.new("RGB", (200, 200), (255, 255, 255))
    regions = [region("a", "A", "", 0.0, 0.0, 1.0, 1.0, 0)]
    out = draw_placement_markers(img, regions, {"a": ("magenta", "A")})
    # Box short side 200 -> radius clamps to 30; dot centered at (100, 100).
    assert out.getpixel((120, 100)) == (255, 0, 255)  # inside dot, right of glyph
    assert out.getpixel((100, 69)) == (0, 0, 0)       # black halo ring (r+2)
    assert out.getpixel((5, 5)) == (255, 255, 255)    # far corner untouched
    assert img.getpixel((100, 100)) == (255, 255, 255)  # input never mutated


def test_draw_placement_markers_no_marks_returns_copy_unchanged():
    img = Image.new("RGB", (64, 64), (10, 20, 30))
    regions = [region("a", "A", "", 0.2, 0.2, 0.5, 0.5, 0)]
    out = draw_placement_markers(img, regions, {})
    assert out.tobytes() == img.tobytes()
