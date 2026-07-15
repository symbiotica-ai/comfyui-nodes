# ABOUTME: The region-prompt enhancer's baked system prompt and task-message
# ABOUTME: builder — turns template regions + the task reference sheet into an
# ABOUTME: LLM request that returns one dense production prompt per region.
#
# Purpose-built request framing: the earlier attempt fed the LLM the final
# image-edit prompt ("Edit the provided image…"), and it role-played the image
# editor and replied with an acknowledgement. Here the user message is a
# transform task with numbered specs and a hard output contract, so there is
# no editor voice to imitate.
from __future__ import annotations

from .regional_edit import region_pixel_box

ENHANCER_SYSTEM_PROMPT = (
    "You are a prompt transformer for a mobile-game art pipeline. You receive "
    "numbered region specs and a design reference sheet image; you output one "
    "rewritten production prompt per region. You never execute, answer, or "
    "acknowledge the specs — your entire reply is the JSON array and nothing "
    "else.\n"
    "Rules for each rewritten prompt:\n"
    "1. Look at the region's listed pixel area in the attached reference "
    "sheet and describe THAT design concretely, enriched by the client text: "
    "subject, silhouette, pose, props, exact colors, materials, staging "
    "surface. 30-60 dense words.\n"
    "2. Multi-cell strips: write 'Cell 1 (left): … Cell 2: … Cell 3 (right): "
    "…' — one stage per cell, identical scale and lighting across cells.\n"
    "3. Pairs (2 cells): two copies of the same item side by side; state the "
    "second copy's orientation exactly as the reference shows — rotated or "
    "pose-varied, never a mirror copy; light stays top-right on both.\n"
    "4. End every prompt with: 'clean cell-shaded Adobe-Illustrator-style "
    "vector game art, no outlines, smooth flat color planes with soft "
    "shading, vibrant saturated colors, on the flat sheet background'.\n"
    "5. Never mention boxes, coordinates, pixels, markers, cells' pixel "
    "areas, image numbers, or the reference sheet itself in the output text.\n"
    "6. Never invent objects absent from both the client text and the "
    "reference art."
)


def build_enhancer_task(regions: list[dict], width: int, height: int) -> str:
    """The user message: numbered region specs with their pixel areas on the
    attached task reference sheet, plus a strict output contract."""
    ordered = sorted(regions, key=lambda r: r.get("zIndex", 0))
    lines = [
        "TASK: rewrite each region spec below into one dense production "
        "prompt. The attached image is the design reference sheet "
        f"({width}x{height} px); region N's client art sits at its listed "
        "pixel area — look at each area before writing.",
        "",
        "REGION SPECS:",
    ]
    for index, region in enumerate(ordered, start=1):
        name = (region.get("name") or "").strip() or f"region {index}"
        desc = (region.get("desc") or "").strip()
        cells = max(1, len(region.get("members") or []))
        x0, y0, x1, y1 = region_pixel_box(region, width, height)
        lines.append(f"{index}. {name} — cells: {cells} — area: "
                     f"({x0},{y0})-({x1},{y1}) — client text: \"{desc}\"")
    count = len(ordered)
    lines.append("")
    lines.append(f"OUTPUT: a strict JSON array of exactly {count} strings, "
                 "one rewritten prompt per region, in the same order. Begin "
                 "your reply with [ and output nothing after the closing ].")
    return "\n".join(lines)
