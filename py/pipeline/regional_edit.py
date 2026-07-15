# ABOUTME: Per-region edit prompts and crop math for SymbioticaRegionalEdit —
# ABOUTME: one small design-transfer request per region instead of one giant
# ABOUTME: whole-sheet edit. Pure text/math, no torch or comfy imports.
#
# Rationale: a single request that re-renders a dozen multi-cell sprites
# degrades badly (dropped instructions, leftover markers, fidelity loss),
# while the same model handles one region with one reference near-perfectly.
# So the sheet is assembled deterministically: each region's crop is edited
# in isolation and pasted back at its exact pixel box.
from __future__ import annotations


def region_pixel_box(region: dict, width: int, height: int) -> tuple[int, int, int, int]:
    """A region's normalized rect as pixel bounds (x0, y0, x1, y1) on a
    width x height sheet — always at least 1px in each axis."""
    x0 = max(0, min(width - 1, round(region["x"] * width)))
    y0 = max(0, min(height - 1, round(region["y"] * height)))
    x1 = max(x0 + 1, min(width, round((region["x"] + region["w"]) * width)))
    y1 = max(y0 + 1, min(height, round((region["y"] + region["h"]) * height)))
    return x0, y0, x1, y1


def _cells_note(region: dict) -> str:
    n = len(region.get("members") or [])
    if n == 2:
        return (" The region holds a PAIR: two copies of the same item side by "
                "side, exactly as image 2 arranges them — reproduce both "
                "copies with image 2's exact orientations; do not make them "
                "identical if image 2 shows them rotated or posed differently.")
    if n >= 3:
        return (f" The region is a strip of {n} cells left to right, one "
                "stage per cell as shown in image 2 — keep each stage in its "
                "own cell, same order, same scale.")
    return ""


def region_edit_prompt(region: dict, style: str = "") -> str:
    """The single-region design-transfer prompt: image 1 is the region's crop
    from the base sheet (placeholder art in the game's graphic style), image 2
    is the same crop from the design reference sheet. Both share one layout,
    so placement is copied from image 2 and style from image 1 (or an explicit
    style override)."""
    name = (region.get("name") or "").strip()
    desc = (region.get("desc") or "").strip()
    subject = f"{name}: {desc}" if name and desc else (desc or name or "the element")
    style = (style or "").strip()
    style_clause = (f" Re-render the design in this style: {style}"
                    if style else
                    " Re-render the design in the exact graphic style of "
                    "image 1's artwork — same rendering technique, line "
                    "treatment, shading, and color vibrancy.")
    return (
        "Edit image 1: replace its placeholder artwork entirely with the "
        "design shown in image 2.\n"
        f"The design is: {subject}\n"
        "Image 1 and image 2 are the same size and share the same layout."
        f"{_cells_note(region)}\n"
        "Reproduce image 2's design faithfully — the same subjects, "
        "silhouettes, props, colors, materials, and story — placed exactly "
        f"where image 2 places them.{style_clause} Keep image 1's flat "
        "background color everywhere the design leaves empty space. Do not "
        "crop, rotate, flip, or add borders, frames, shadows onto the "
        "background, text, or watermarks. Output only the redrawn image at "
        "the same framing as image 1."
    )
