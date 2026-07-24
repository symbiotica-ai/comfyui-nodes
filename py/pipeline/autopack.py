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


def apply_overrides(assets, overrides):
    """Apply the per-asset panel overrides: drop hidden assets and pick/reorder
    each asset's cells. `overrides` = {"hidden": [name, ...],
    "cells": {name: [kept 1-based ref indices, in order]}} — the cells list is
    reorder + duplicate-removal in one."""
    out = assets
    for name in (overrides or {}).get("hidden", []) or []:
        out = apply_removal(out, name)
    cells = (overrides or {}).get("cells") or {}
    if cells:
        out = [({**a, "refFiles": select_cells(a.get("refFiles", []),
                                               cells[a["assetName"]])}
                if a.get("assetName") in cells else a) for a in out]
    return out


def apply_removal(assets, asset_name):
    """Return `assets` without the one named asset (drop a duplicate). No-op
    (same list) when nothing is selected."""
    name = (asset_name or "").strip()
    if not name or name == "none":
        return assets
    return [a for a in assets if a.get("assetName") != name]


def select_cells(refs, indices):
    """Keep the given 1-based ref indices, in that order — reorder AND drop in
    one pass. Out-of-range indices are skipped; an empty selection keeps none."""
    return [refs[i - 1] for i in (indices or []) if 1 <= i <= len(refs)]


def _is_variant(asset):
    """A directional asset (rotation 2 or 4) whose refs are distinct VARIANTS,
    not a food recipe's stages (rotation '-'). Only these get split."""
    rot = str(asset.get("rotation", "")).strip()
    return rot.isdigit() and int(rot) >= 2


def _variant_sheets(assets, refs_root, sheet_w, sheet_h, settings, scales,
                    base_name, category, cap=3):
    """One sheet per variant ref (up to `cap`) for each variant asset: a
    rotation=2 asset mirrors each ref (ref + horizontal flip); rotation=4 draws
    the single ref (a flip can't stand in for 4 directions). Food (rotation '-')
    is skipped.

    A single-ref variant still gets its own sheet (its one ref + flip) — the
    per-item deliverable — separate from the combined sheet that groups it with
    the rest of its (category, canvas). Only a truly ref-less asset is skipped."""
    out = []
    for a in assets:
        if not _is_variant(a) or not (a.get("refFiles") or []):
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


def _combined_sheets(assets, refs_root, sheet_w, sheet_h, settings, scales,
                     base_name, category, columns, max_rows):
    """The grouped 'combined' sheets, one (category, canvas) group at a time.

    A VARIANT group (directional decorations, rotation 2/4): every reference of
    every asset becomes its own single-ref mirror-pair region (rotation 2 = ref
    + horizontal flip; rotation >= 3 = the single ref). Those units flatten in
    asset order and paginate by columns x max_rows, so ONE asset's refs stay
    together on a sheet when they fit — they are no longer split across per-ref
    sheets. A STAGE group (food, rotation '-') keeps each recipe's stages
    together in one region, many assets packed per sheet."""
    per_sheet = max(1, int(columns)) * max(1, int(max_rows))
    groups: dict[tuple[str, str], list[dict]] = {}
    for a in assets:
        if not a.get("refFiles"):
            continue
        if category != "All" and a.get("category") != category:
            continue
        groups.setdefault((a.get("category", ""), a.get("canvas", "")),
                          []).append(a)
    canvases_per_cat: dict[str, set] = {}
    for cat, canvas in groups:
        canvases_per_cat.setdefault(cat, set()).add(canvas)

    def emit(cat, canvas, page_assets, suffix, out):
        sheet, regions, _ov = build_prefill_sheet(
            page_assets, refs_root, sheet_w, sheet_h, settings, scales=scales)
        if not regions:
            return
        name = f"{base_name}-{slugify(cat)}"
        if len(canvases_per_cat[cat]) > 1:
            name += f"-{canvas}"
        name += suffix
        out.append({"image": sheet, "regions": regions,
                    "prompts": build_client_prompts(regions), "name": name})

    out = []
    for (cat, canvas), group in groups.items():
        if any(_is_variant(a) for a in group):
            # One single-ref region per reference, kept in asset order so an
            # asset's refs stay adjacent; paginate the flat list by max_rows.
            units = []
            for a in group:
                for ref in a["refFiles"]:
                    synth = {**a, "refFiles": [ref]}
                    # Suppress the single-ref mirror only for true multi-
                    # direction variants (rotation >= 3, where a flip can't
                    # stand in). Rotation-2 mirrors; a NON-variant asset that
                    # merely shares the group (blank/'-' rotation) keeps its
                    # normal in-game pair behavior.
                    rot = str(a.get("rotation", "")).strip()
                    if rot.isdigit() and int(rot) >= 3:
                        synth["noMirror"] = True
                    units.append(synth)
            pages = [units[i:i + per_sheet]
                     for i in range(0, len(units), per_sheet)]
            for pi, page in enumerate(pages, 1):
                suffix = f"-{pi}" if len(pages) > 1 else ""
                emit(cat, canvas, page, suffix, out)
        else:
            pages = [group[i:i + per_sheet]
                     for i in range(0, len(group), per_sheet)]
            for pi, page in enumerate(pages, 1):
                suffix = f"-{pi}" if len(pages) > 1 else ""
                emit(cat, canvas, page, suffix, out)
    return out


def autopack_order(assets, refs_root, *, sheet_w, sheet_h, columns=1,
                   max_rows=4, background="#808080", category="All",
                   base_name="order", scale_target=0, scale_max=1.0,
                   algorithm="shelf", distribute_by_folder=False, padding=0,
                   border=0, combined_sheet=True, split_variants=False,
                   max_refs=None, fit_width=False):
    """The whole order as ready-to-run sheets: plan_sheets chunks similar
    assets, each chunk is prefilled + drawn on its own sheet, and each
    sheet's client prompts come from the SAME chunk's regions — so item i
    of the images and item i of the prompts always describe each other.

    Scaling is per-size: each sprite grows so its longest canvas edge reaches
    ~`scale_target` px, but never more than `scale_max`x and never below 1x
    (never shrink). So with target 512 + max 3x a 128 sprite scales 3x (capped),
    a 256 scales 2x, a 512 stays native — small sprites grow more, and the cap
    keeps a scaled sheet from overflowing. `scale_target=0` disables scaling.

    Two independent outputs: `combined_sheet` (the paginated grouped sheets —
    today's behavior) and `split_variants` (one mirrored sheet per variant ref
    of each directional asset). Both can be on.

    `max_refs` (int or None) is a hard cap on reference images per asset: keep
    the first N refFiles in order, drop the rest, before any packing — so a
    sheet is never overloaded with more refs than the model can handle. None =
    no cap. Applied after the per-asset panel overrides, so 'first N' respects a
    reordered cell list."""
    if max_refs:
        assets = [{**a, "refFiles": (a.get("refFiles") or [])[:int(max_refs)]}
                  for a in assets]
    settings = PackSettings(algorithm=algorithm, columns=max(1, int(columns)),
                            background=background, padding=max(0, int(padding)),
                            border=max(0, int(border)),
                            distribute_by_folder=bool(distribute_by_folder),
                            max_width=sheet_w, max_height=sheet_h,
                            fit_width=bool(fit_width))

    def _asset_scale(a):
        # Grow the sprite so its longest edge reaches ~scale_target px, capped at
        # scale_max, floored at 1x (never shrink). This makes a small sprite
        # scale MORE than a large one, and the cap bounds the zoom so a scaled
        # sheet can't overflow. scale_target=0 = scaling off.
        if not scale_target:
            return 1.0
        spec = canvas_spec_of(a.get("canvas", "")) or {}
        edge = max(spec.get("w", 0), spec.get("h", 0))
        if edge <= 0:
            return 1.0
        return max(1.0, min(scale_target / edge, scale_max))

    scales = None
    if scale_target:
        scales = {}
        for a in assets:
            name = a.get("assetName")
            if not name:
                continue
            factor = _asset_scale(a)
            if factor > 1.0:
                scales[name] = factor
        scales = scales or None
    out = []
    if combined_sheet:
        out.extend(_combined_sheets(assets, refs_root, sheet_w, sheet_h,
                                    settings, scales, base_name, category,
                                    columns, max_rows))
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
