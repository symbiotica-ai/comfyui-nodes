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


def element_line(region: dict, ref_number: int | None) -> str:
    """One numbered layout line for a region: subject, optional image citation,
    verbal placement, and its box_2d."""
    name = (region.get("name") or "").strip()
    desc = (region.get("desc") or "").strip()
    subject = f"{name}: {desc}" if name and desc else (desc or name or "An element")
    if ref_number is not None:
        subject = f"{subject}, taken from image {ref_number} (reproduce that exact item)"
    placement = placement_phrase(region["x"], region["y"], region["w"], region["h"])
    return f"{subject}: {placement}. box_2d = {box_2d(region)}"


def build_regional_prompt(scene: str, width: int, height: int,
                          regions: list[dict],
                          ref_numbers: dict[str, int] | None = None) -> str:
    """Assemble the edit prompt: preamble, scene, refs legend (when any region
    cites a reference image), layout header, numbered element lines back to
    front (zIndex ascending), and the footer. `ref_numbers` maps region id ->
    image number (2-based; image 1 is the sheet being edited)."""
    ref_numbers = ref_numbers or {}
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
    if ordered:
        lines.append("")
        lines.append(LAYOUT_HEADER)
        for index, region in enumerate(ordered, start=1):
            lines.append(f"{index}. {element_line(region, ref_numbers.get(region.get('id')))}")
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
