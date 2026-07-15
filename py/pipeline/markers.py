# ABOUTME: Set-of-mark placement markers — a unique colored dot with a label
# ABOUTME: letter per region, drawn at the region's box center on image 1.
#
# Ported from eRepublik-Labs/comfyui-nodes-erpk region_image_ops.py so the dots
# and the prompt's marker language match that pack's battle-tested behavior: an
# edit model ignores box_2d coordinates but reads pixels, so a saturated dot at
# the element's center gives it a target it can actually see.
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

# Saturated, unnatural colors. Red is omitted because elements are often red
# and the marker must contrast with the object it marks. Names are cited
# verbatim in the prompt, so they read as natural color words.
MARKER_COLORS = [
    ("magenta", (255, 0, 255)),
    ("cyan", (0, 255, 255)),
    ("lime green", (153, 255, 0)),
    ("orange", (255, 128, 0)),
    ("yellow", (255, 255, 0)),
    ("hot pink", (255, 26, 140)),
]


def assign_markers(regions: list[dict]) -> dict[str, tuple[str, str]]:
    """Map region id -> (color name, label letter), in back-to-front order.

    Two independent identifiers make a mark unmistakable: a color name
    (skipping any color word already in the region's name/desc, so a magenta
    object never gets a magenta marker) and a sequential letter A, B, C… that
    the drawn glyph and the prompt's "marker A" both cite. A letter, not a
    number, avoids colliding with the prompt's own numbered element list.
    """
    marks: dict[str, tuple[str, str]] = {}
    used: set[str] = set()
    ordered = sorted(regions, key=lambda r: r.get("zIndex", 0))
    for counter, region in enumerate(ordered):
        text = f"{region.get('name') or ''} {region.get('desc') or ''}".lower()
        choice = next(
            (name for name, _ in MARKER_COLORS
             if name not in used and name.split()[-1] not in text),
            None,
        )
        if choice is None:
            choice = next((name for name, _ in MARKER_COLORS if name not in used),
                          MARKER_COLORS[0][0])
        used.add(choice)
        label = chr(ord("A") + counter) if counter < 26 else str(counter + 1)
        marks[region.get("id")] = (choice, label)
    return marks


def _marker_font(size: int):
    """A bitmap font at the requested size, falling back for older Pillow."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _draw_marker(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int,
                 rgb: tuple[int, int, int], label: str) -> None:
    """A solid colored dot with its label letter centered inside.

    A dark halo disc sits under the colored fill so the mark stays
    high-contrast on any scene color; the label ink is black on a bright fill
    and white on a dark one (by luminance) so it reads against its own dot.
    """
    draw.ellipse([cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2],
                 fill=(0, 0, 0, 255))
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=rgb + (255,))
    if not label:
        return
    luminance = 0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]
    ink = (0, 0, 0, 255) if luminance > 150 else (255, 255, 255, 255)
    font = _marker_font(max(11, int(r * 1.3)))
    # Faux-bold: a stroke in the ink color thickens the glyph (the default
    # font has no bold weight) so the letter reads boldly on the dot.
    stroke = max(1, r // 10)
    left, top, right, bottom = draw.textbbox((0, 0), label, font=font,
                                             stroke_width=stroke)
    tx = cx - (right - left) / 2 - left
    ty = cy - (bottom - top) / 2 - top
    draw.text((tx, ty), label, fill=ink, font=font,
              stroke_width=stroke, stroke_fill=ink)


def draw_placement_markers(img: Image.Image, regions: list[dict],
                           marks: dict[str, tuple[str, str]]) -> Image.Image:
    """Stamp each marked region's dot at its box center; returns a new image.

    The mark sits under where the element should land, so a hit hides it and a
    miss leaves a visible dot — an honest signal. Dot radius is 18% of the
    box's short side, clamped 10–30 px, mirroring ERPK.
    """
    out = img.copy()
    if not marks:
        return out
    palette = dict(MARKER_COLORS)
    width, height = out.size
    overlay = Image.new("RGBA", out.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    drew = False
    for region in regions:
        mark = marks.get(region.get("id"))
        if not mark:
            continue
        rgb = palette.get(mark[0])
        if rgb is None:
            continue
        x0 = max(0, min(width - 1, round(region["x"] * width)))
        y0 = max(0, min(height - 1, round(region["y"] * height)))
        x1 = max(x0 + 1, min(width, round((region["x"] + region["w"]) * width)))
        y1 = max(y0 + 1, min(height, round((region["y"] + region["h"]) * height)))
        cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
        r = int(min(max(min(x1 - x0, y1 - y0) * 0.18, 10), 30))
        _draw_marker(draw, cx, cy, r, rgb, mark[1])
        drew = True
    if not drew:
        return out
    return Image.alpha_composite(out.convert("RGBA"), overlay).convert("RGB")
