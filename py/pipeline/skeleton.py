# ABOUTME: Builds the framing-free layout skeleton the Template Editor hands to
# ABOUTME: an LLM: sheet size, then one numbered element per region with its
# ABOUTME: box_2d placement, reference image number, and the client's brief.

from .regional_prompt import box_2d, placement_phrase


def element_block(index, region, ref_number=None):
    """One element's facts: what it is, where it goes, which image shows it."""
    name = (region.get("name") or "").strip()
    desc = (region.get("desc") or "").strip()
    lines = [f'Element {index}: "{name}"' if name else f"Element {index}"]
    where = placement_phrase(region["x"], region["y"], region["w"], region["h"])
    lines.append(f"  placement: {where} · box_2d = {box_2d(region)}")
    if ref_number:
        lines.append(f"  reference: image {ref_number}")
    if desc:
        lines.append(f"  client brief: {desc}")
    return "\n".join(lines)


def build_client_prompts(regions):
    """The order's client prompts, one recipe per row — the exact text the
    recipe workflow hand-typed into its Client Prompt node.

    Each region's desc is the client's brief verbatim (for food, it already
    carries the "Prep) … Ready) … Serving) …" stage lines), so this only
    numbers them "row N" and stacks them in region order. Regions with no
    brief are skipped.
    """
    ordered = sorted(regions, key=lambda r: r.get("zIndex", 0))
    blocks = []
    row = 0
    for r in ordered:
        desc = (r.get("desc") or "").strip()
        if not desc:
            continue
        row += 1
        blocks.append(f"row {row}\n{desc}")
    return "\n\n".join(blocks)


def build_skeleton(regions, width, height, ref_numbers=None):
    """The layout facts, in region (back-to-front) order.

    Deliberately states no goal, no style, and no instruction about what to do
    with the references: this text is an LLM's input, and every framing word
    here would compete with the system prompt that owns the actual brief.
    """
    ref_numbers = ref_numbers or {}
    ordered = sorted(regions, key=lambda r: r.get("zIndex", 0))
    count = len(ordered)
    head = [
        f"Sheet: {width} x {height} px.",
        f"{count} element{'s' if count != 1 else ''}, listed back to front.",
        "Placements are box_2d = [ymin, xmin, ymax, xmax] on a 0-1000 grid "
        "with a top-left origin.",
    ]
    if ref_numbers:
        head.append("Image 1 is the sheet being edited; the reference images "
                    "are numbered from 2.")
    blocks = [element_block(i + 1, r, ref_numbers.get(r.get("id")))
              for i, r in enumerate(ordered)]
    return "\n".join(head) + "\n\n" + "\n\n".join(blocks)
