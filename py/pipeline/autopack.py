# ABOUTME: Auto-pack a client order into template sheets: group similar assets
# ABOUTME: (category+canvas), paginate into columns x max_rows chunks, render.
from .order_sheet import slugify


def plan_sheets(assets, columns, max_rows, category="All"):
    """Chunk order assets into per-sheet groups: similar assets only —
    grouped by (category, canvas) — at most columns*max_rows assets per
    sheet, spec order preserved. Assets without refFiles are dropped (there
    is nothing to draw). category="All" keeps every type."""
    per_sheet = max(1, int(columns)) * max(1, int(max_rows))
    groups: dict[tuple[str, str], list[dict]] = {}
    for a in assets:
        if not a.get("refFiles"):
            continue
        if category != "All" and a.get("category") != category:
            continue
        groups.setdefault((a.get("category", ""), a.get("canvas", "")),
                          []).append(a)
    chunks = []
    for (cat, canvas), group in groups.items():
        pages = [group[i:i + per_sheet] for i in range(0, len(group), per_sheet)]
        for i, page in enumerate(pages, 1):
            chunks.append({"category": cat, "canvas": canvas, "assets": page,
                           "index": i, "total": len(pages)})
    return chunks


def sheet_name(base, chunk, multi_canvas):
    """mini-2-food-3-stages[-512x512][-2]: canvas only when the category
    spans several canvas sizes, page index only when paginated."""
    name = f"{base}-{slugify(chunk['category'])}"
    if multi_canvas:
        name += f"-{chunk['canvas']}"
    if chunk["total"] > 1:
        name += f"-{chunk['index']}"
    return name


from .compose import build_prefill_sheet
from .skeleton import build_client_prompts
from .texture_pack import PackSettings


def autopack_order(assets, refs_root, *, sheet_w, sheet_h, columns=1,
                   max_rows=4, background="#808080", category="All",
                   base_name="order"):
    """The whole order as ready-to-run sheets: plan_sheets chunks similar
    assets, each chunk is prefilled + drawn on its own sheet, and each
    sheet's client prompts come from the SAME chunk's regions — so item i
    of the images and item i of the prompts always describe each other."""
    chunks = plan_sheets(assets, columns, max_rows, category=category)
    if not chunks:
        cats = sorted({a.get("category", "") for a in assets if a.get("refFiles")})
        raise ValueError(
            f"no assets to pack for category {category!r} — this event has "
            f"referenced assets in: {', '.join(cats) or '(none at all)'}")
    canvases_per_cat: dict[str, set] = {}
    for c in chunks:
        canvases_per_cat.setdefault(c["category"], set()).add(c["canvas"])
    settings = PackSettings(algorithm="shelf", columns=max(1, int(columns)),
                            background=background,
                            max_width=sheet_w, max_height=sheet_h)
    out = []
    for chunk in chunks:
        sheet, regions, _overflow = build_prefill_sheet(
            chunk["assets"], refs_root, sheet_w, sheet_h, settings)
        if not regions:
            continue
        out.append({
            "image": sheet,
            "regions": regions,
            "prompts": build_client_prompts(regions),
            "name": sheet_name(base_name, chunk,
                               len(canvases_per_cat[chunk["category"]]) > 1),
        })
    if not out:
        raise ValueError(
            f"no assets to pack for category {category!r} — every chunk came "
            "back empty (missing reference files on disk?)")
    return out
