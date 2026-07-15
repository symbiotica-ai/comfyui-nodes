# ABOUTME: Turns a template bundle's regions into a layout-aware edit prompt plus
# ABOUTME: interoperable pixel bboxes. Pure text/math — no torch or comfy imports.
#
# The prompt format mirrors eRepublik-Labs/comfyui-nodes-erpk RegionalPromptBuilder
# (same headers, box_2d convention, and image numbering) so the output wires into
# the same edit nodes and benefits from that pack's battle-tested phrasing.
from __future__ import annotations

import math

EDIT_PREAMBLE = (
    "Edit the provided image. Keep it faithful to the original — the same "
    "subjects, textures, colors, lighting, framing, and composition — and apply "
    "ONLY the changes described below. Do not re-render, restyle, or regenerate "
    "any part of the image that is not an explicit edit. Keep the original "
    "orientation and framing exactly: do not flip, mirror, rotate, or crop the "
    "image."
)
REFS_HEADER = (
    "Numbered images accompany this request: image 1 is the image being "
    "edited, and elements below reference later images by number. Reproduce "
    "each referenced item faithfully (shape, colors, materials, markings), "
    "adapting it to the scene's lighting and perspective. Keep everything "
    "else in image 1 unchanged."
)
LAYOUT_HEADER = (
    "Layout: place each element exactly where specified. Each position gives a "
    'verbal placement plus its placement area as "box_2d = [ymin, xmin, ymax, xmax]" '
    "on a 0-1000 grid with top-left origin. Elements are listed from back to "
    "front: where placement areas overlap, a later element appears in front of "
    "an earlier one."
)
MARKER_HEADER = (
    "Solid colored dots have been drawn on the image to mark placements — each "
    "is a filled dot in a unique color with a label letter inside it, and each "
    "element below names its marker(s) by letter and color. A newly added "
    "element has one dot: place it centered there. A move has two dots — one "
    "on the object at its current spot and one at its target — so move that "
    "object from the first dot onto the second. An object to be removed has "
    "one dot on it: delete that object and rebuild the background where it "
    "was. The dots are guides, not part of the scene: paint every dot out "
    "completely so none of it remains. Each dot is the exact, required "
    "location for its element — put the element on its dot even if a "
    "different spot in the scene looks more natural or more typical for it; "
    "never move it off its dot to a more likely place."
)
LAYOUT_FOOTER = (
    "Every element must stay fully inside its placement area and fill most of it. "
    "Put each element exactly at its own box_2d and nowhere else, even if a "
    "different, similar-looking spot in the image seems more natural. "
    "Do not add other prominent subjects. The placement areas are invisible "
    "composition guides: never draw boxes, frames, outlines, coordinates, or any "
    "annotation overlays in the image."
)


def placement_phrase(x: float, y: float, w: float, h: float) -> str:
    """Where a region's center falls on a 3x3 grid, e.g. "at the bottom-left"."""
    cx = x + w / 2
    cy = y + h / 2
    horizontal = "left" if cx < 1 / 3 else "center" if cx < 2 / 3 else "right"
    vertical = "top" if cy < 1 / 3 else "middle" if cy < 2 / 3 else "bottom"
    if vertical == "middle" and horizontal == "center":
        return "at the center"
    return f"at the {vertical}-{horizontal}"


def aspect_ratio_string(width: int, height: int) -> str:
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def _clamp_grid(v: float) -> int:
    return max(0, min(1000, round(v * 1000)))


def box_2d(region: dict) -> list[int]:
    """Normalized region rect -> [ymin, xmin, ymax, xmax] on the 0-1000 grid."""
    return [
        _clamp_grid(region["y"]),
        _clamp_grid(region["x"]),
        _clamp_grid(region["y"] + region["h"]),
        _clamp_grid(region["x"] + region["w"]),
    ]


def element_line(region: dict, ref_number: int | None,
                 marker: tuple[str, str] | None = None) -> str:
    """One numbered layout line for a region: subject, optional image citation,
    verbal placement, its box_2d, and — when the region carries a placement
    marker — the ERPK marker clause citing the dot by letter and color."""
    name = (region.get("name") or "").strip()
    desc = (region.get("desc") or "").strip()
    subject = f"{name}: {desc}" if name and desc else (desc or name or "An element")
    if ref_number is not None:
        subject = f"{subject}, taken from image {ref_number} (reproduce that exact item)"
    placement = placement_phrase(region["x"], region["y"], region["w"], region["h"])
    line = f"{subject}: {placement}. box_2d = {box_2d(region)}"
    if marker is not None:
        color, label = marker
        line += f" Center it on marker {label} (the {color} dot)."
    return line


def build_regional_prompt(scene: str, width: int, height: int,
                          regions: list[dict],
                          ref_numbers: dict[str, int] | None = None,
                          markers: dict[str, tuple[str, str]] | None = None) -> str:
    """Assemble the edit prompt: preamble, scene, refs legend (when any region
    cites a reference image), marker legend (when any region carries a drawn
    placement dot), layout header, numbered element lines back to front
    (zIndex ascending), and the footer. `ref_numbers` maps region id -> image
    number (2-based; image 1 is the sheet being edited); `markers` maps region
    id -> (color name, label letter) as drawn on image 1."""
    ref_numbers = ref_numbers or {}
    markers = markers or {}
    ordered = sorted(regions, key=lambda r: r.get("zIndex", 0))

    lines = [EDIT_PREAMBLE]
    scene = (scene or "").strip()
    if scene:
        lines.append("")
        lines.append(scene)
    lines.append("")
    lines.append(f"The image is {width}x{height} pixels.")
    if any(r.get("id") in ref_numbers for r in ordered):
        lines.append("")
        lines.append(REFS_HEADER)
    if any(r.get("id") in markers for r in ordered):
        lines.append("")
        lines.append(MARKER_HEADER)
    if ordered:
        lines.append("")
        lines.append(LAYOUT_HEADER)
        for index, region in enumerate(ordered, start=1):
            rid = region.get("id")
            lines.append(f"{index}. "
                         f"{element_line(region, ref_numbers.get(rid), markers.get(rid))}")
        lines.append("")
        lines.append(LAYOUT_FOOTER)
    return "\n".join(lines)


def regions_to_pixel_bboxes(regions: list[dict], width: int, height: int) -> list:
    """ERPK-compatible pixel boxes: [[{x, y, width, height}, ...]] or []."""
    ordered = sorted(regions, key=lambda r: r.get("zIndex", 0))
    if not ordered:
        return []
    return [[
        {"x": round(r["x"] * width),
         "y": round(r["y"] * height),
         "width": round(r["w"] * width),
         "height": round(r["h"] * height)}
        for r in ordered
    ]]


def target_ref_size(region: dict, fallback_w: int, fallback_h: int) -> tuple[int, int]:
    """The formula resolution for a region's reference image:
    n_cells * (canvas * scale) wide by (canvas * scale) tall, from the region's
    recorded cellPx. Regions without cellPx (old templates) keep the fallback
    (the raw crop size)."""
    cell = region.get("cellPx") or {}
    w = cell.get("w")
    h = cell.get("h")
    if not w or not h:
        return max(1, fallback_w), max(1, fallback_h)
    n = max(1, len(region.get("members") or []))
    return max(1, round(n * w)), max(1, round(h))
