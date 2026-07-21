# ABOUTME: Auto-pack a client order into template sheets: group similar assets
# ABOUTME: (category+canvas), paginate into columns x max_rows chunks, render.
from .order_sheet import canvas_spec_of, slugify


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


def _is_variant(asset):
    """A directional asset (rotation 2 or 4) whose refs are distinct VARIANTS,
    not a food recipe's stages (rotation '-'). Only these get split."""
    rot = str(asset.get("rotation", "")).strip()
    return rot.isdigit() and int(rot) >= 2


def _variant_sheets(assets, refs_root, sheet_w, sheet_h, settings, scales,
                    base_name, category, cap=3):
    """One sheet per variant ref (up to `cap`) for each variant asset: a
    rotation=2 asset mirrors each ref (ref + horizontal flip); rotation=4 draws
    the single ref (a flip can't stand in for 4 directions). Food is skipped."""
    out = []
    for a in assets:
        if not a.get("refFiles") or not _is_variant(a):
            continue
        if category != "All" and a.get("category") != category:
            continue
        mirror = str(a.get("rotation", "")).strip() == "2"
        for i, ref in enumerate(a["refFiles"][:cap], 1):
            synth = {**a, "refFiles": [ref]}
            if not mirror:
                synth["noMirror"] = True
            sheet, regions, _ov = build_prefill_sheet(
                [synth], refs_root, sheet_w, sheet_h, settings, scales=scales)
            if not regions:
                continue
            out.append({
                "image": sheet, "regions": regions,
                "prompts": build_client_prompts(regions),
                "name": f"{base_name}-{slugify(a['assetName'])}-v{i}",
            })
    return out


def autopack_order(assets, refs_root, *, sheet_w, sheet_h, columns=1,
                   max_rows=4, background="#808080", category="All",
                   base_name="order", scale=1.0, algorithm="shelf",
                   distribute_by_folder=False, padding=0, border=0,
                   scale_max_canvas=256, combined_sheet=True,
                   split_variants=False):
    """The whole order as ready-to-run sheets: plan_sheets chunks similar
    assets, each chunk is prefilled + drawn on its own sheet, and each
    sheet's client prompts come from the SAME chunk's regions — so item i
    of the images and item i of the prompts always describe each other.

    The pack knobs (scale, algorithm, distribute_by_folder, padding, border)
    mirror the Template Editor's Pack Settings so a wired Auto Packer Settings
    node reproduces an editor sheet. `scale` enlarges a cell uniformly, but
    only for assets whose canvas max edge is <= `scale_max_canvas` — small
    sprites (food, 256 decorations) grow, already-large 512+ ones stay native.

    Two independent outputs: `combined_sheet` (the paginated grouped sheets —
    today's behavior) and `split_variants` (one mirrored sheet per variant ref
    of each directional asset). Both can be on."""
    settings = PackSettings(algorithm=algorithm, columns=max(1, int(columns)),
                            background=background, padding=max(0, int(padding)),
                            border=max(0, int(border)),
                            distribute_by_folder=bool(distribute_by_folder),
                            max_width=sheet_w, max_height=sheet_h)

    def _under_cutoff(a):
        spec = canvas_spec_of(a.get("canvas", "")) or {}
        return max(spec.get("w", 256), spec.get("h", 256)) <= scale_max_canvas

    scales = ({a["assetName"]: scale for a in assets
               if a.get("assetName") and _under_cutoff(a)} or None
              if scale and scale != 1 else None)
    out = []
    if combined_sheet:
        chunks = plan_sheets(assets, columns, max_rows, category=category)
        canvases_per_cat: dict[str, set] = {}
        for c in chunks:
            canvases_per_cat.setdefault(c["category"], set()).add(c["canvas"])
        for chunk in chunks:
            sheet, regions, _overflow = build_prefill_sheet(
                chunk["assets"], refs_root, sheet_w, sheet_h, settings,
                scales=scales)
            if not regions:
                continue
            out.append({
                "image": sheet,
                "regions": regions,
                "prompts": build_client_prompts(regions),
                "name": sheet_name(base_name, chunk,
                                   len(canvases_per_cat[chunk["category"]]) > 1),
            })
    if split_variants:
        out.extend(_variant_sheets(assets, refs_root, sheet_w, sheet_h,
                                   settings, scales, base_name, category))
    if not out:
        cats = sorted({a.get("category", "") for a in assets if a.get("refFiles")})
        raise ValueError(
            f"no assets to pack for category {category!r} — nothing to draw "
            f"(referenced asset types: {', '.join(cats) or '(none at all)'}; "
            f"variants split: {split_variants})")
    return out
