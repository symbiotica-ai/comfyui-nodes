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
    """The order's client prompts, grouped under an asset-type header so each
    block is legible instead of an anonymous "row 1" stack. Each asset's own
    NAME is printed as a title above its brief — it gives the image model the
    item's identity, not just its description:

        Decoration
        Spider Web Doughnuts
        <the brief>

        Cashier's Desk
        row 1
        Spider Mosaic Cash Register
        <brief>

        row 2
        Gothic Cathedral Cash Register
        <brief>

    A single-asset type prints just its name + brief; a multi-asset type (e.g. a
    food sheet's recipes) numbers them row 1..N under the header. Each region's
    desc is the client's brief verbatim (for food it already carries the
    "Prep) … Ready) … Serving) …" stage lines). The name is `region["name"]`
    (the asset name); a nameless region just skips the title line. Regions with
    no brief are skipped; groups keep first-seen (region/z-index) order.
    """
    ordered = sorted(regions, key=lambda r: r.get("zIndex", 0))
    groups: dict[str, list[tuple[str, str]]] = {}
    for r in ordered:
        desc = (r.get("desc") or "").strip()
        if not desc:
            continue
        cat = (r.get("assetType") or r.get("category") or "").strip() or "Assets"
        name = (r.get("name") or "").strip()
        groups.setdefault(cat, []).append((name, desc))
    blocks = []
    for cat, items in groups.items():
        if len(items) == 1:
            name, d = items[0]
            blocks.append(f"{cat}\n{name}\n{d}" if name else f"{cat}\n{d}")
        else:
            rows = [(f"row {i}\n{name}\n{d}" if name else f"row {i}\n{d}")
                    for i, (name, d) in enumerate(items, 1)]
            blocks.append(f"{cat}\n" + "\n\n".join(rows))
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
