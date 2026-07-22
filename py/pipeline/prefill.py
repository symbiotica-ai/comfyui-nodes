# ABOUTME: Spec-driven region prefill — builds template regions FROM the order:
# ABOUTME: one strip per asset, cells at the order's canvas size, xlsx prompt.
# Port of symbiotica-hub apps/web/src/lib/flows/prefill-regions.ts.
from __future__ import annotations

from dataclasses import replace

from .order_sheet import canvas_spec_of
from .texture_pack import PackSettings, pack

PAD_PX = 16
# Gap between the CELLS of one region: zero — a pair region is exactly
# cell+cell (256x256 + 256x256), so its crop is the native sprite resolution.
CELL_GAP = 0
FALLBACK_CELL = 256
# Margin left around the block when scaling it to fill the sheet width (fit_width).
FIT_PAD_PX = 5


def _fit_block_to_width(regions: list[dict], sheet_w: int, sheet_h: int) -> None:
    """Scale the whole placed block up (or down) so it fills the sheet width
    minus FIT_PAD_PX on each side — the max scale that fits, capped so it never
    overflows the height. Scaling is about the block's top-left; _center_block
    re-centers afterwards. Region boxes, member cells, and cellPx all scale."""
    if not regions:
        return
    min_x = min(r["x"] for r in regions)
    max_x = max(r["x"] + r["w"] for r in regions)
    min_y = min(r["y"] for r in regions)
    max_y = max(r["y"] + r["h"] for r in regions)
    bw, bh = max_x - min_x, max_y - min_y
    if bw <= 0 or bh <= 0:
        return
    pad_x, pad_y = FIT_PAD_PX / sheet_w, FIT_PAD_PX / sheet_h
    s = min((1 - 2 * pad_x) / bw, (1 - 2 * pad_y) / bh)
    if s <= 0 or abs(s - 1) < 1e-9:
        return
    for r in regions:
        r["x"] = (r["x"] - min_x) * s
        r["y"] = (r["y"] - min_y) * s
        r["w"] *= s
        r["h"] *= s
        r["scale"] = r.get("scale", 1) * s
        cp = r.get("cellPx")
        if cp:
            r["cellPx"] = {"w": cp["w"] * s, "h": cp["h"] * s}
        for m in r.get("members", []):
            m["x"] = (m["x"] - min_x) * s
            m["y"] = (m["y"] - min_y) * s
            m["w"] *= s
            m["h"] *= s


def _cell_count(row: dict) -> int:
    return 2 if row["flip"] else len(row["paths"])


def _row_w(row: dict) -> float:
    n = _cell_count(row)
    return n * row["cellW"] + (n - 1) * CELL_GAP


def _region_at(row: dict, x_px: float, y_px: float, sheet_w: int, sheet_h: int) -> dict:
    cell_paths = [row["paths"][0], row["paths"][0]] if row["flip"] else row["paths"]
    x = x_px
    members = []
    for i, sprite_id in enumerate(cell_paths):
        m = {"spriteId": sprite_id, "x": x / sheet_w, "y": y_px / sheet_h,
             "w": row["cellW"] / sheet_w, "h": row["cellH"] / sheet_h}
        if row["flip"] and i == 1:
            m["flipX"] = True
        members.append(m)
        x += row["cellW"] + CELL_GAP
    x0 = members[0]["x"]
    last = members[-1]
    return {
        "id": f"region:spec:{row['asset']['assetName']}",
        "name": row["asset"]["assetName"],
        "x": x0,
        "y": y_px / sheet_h,
        "w": last["x"] + last["w"] - x0,
        "h": row["cellH"] / sheet_h,
        "kind": "object",
        "desc": row["asset"].get("prompt") or "",
        "text": "",
        "zIndex": 0,
        "scale": row.get("scale", 1),
        "assetType": row["asset"]["category"],
        # Native cell size in sheet px (canvas x user scale) — the ref-image
        # resolution formula: n_cells * cellPx.w wide by cellPx.h tall.
        "cellPx": {"w": row["cellW"], "h": row["cellH"]},
        "members": members,
        "taskRefs": {"paths": row["paths"], "mode": "meta"},
    }


def _center_block(regions: list[dict]) -> None:
    """Translate the whole placed block so it sits centered on the sheet (both
    axes). An axis whose content is wider/taller than the sheet anchors at 0
    (top-left) instead — nothing is pushed off-edge. Region boxes AND their
    member cells move together (the sheet draw uses members)."""
    if not regions:
        return
    min_x = min(r["x"] for r in regions)
    max_x = max(r["x"] + r["w"] for r in regions)
    min_y = min(r["y"] for r in regions)
    max_y = max(r["y"] + r["h"] for r in regions)
    off_x = -min_x if (max_x - min_x) >= 1 else (1 - (max_x - min_x)) / 2 - min_x
    off_y = -min_y if (max_y - min_y) >= 1 else (1 - (max_y - min_y)) / 2 - min_y
    if off_x == 0 and off_y == 0:
        return
    for r in regions:
        r["x"] += off_x
        r["y"] += off_y
        for m in r.get("members", []):
            m["x"] += off_x
            m["y"] += off_y


def prefill_regions(order_assets: list[dict], sheet_w: int, sheet_h: int,
                    chosen: dict[str, list[str]] | None = None,
                    settings: PackSettings | None = None,
                    scales: dict[str, float] | None = None) -> dict:
    """One region per asset. Single-ref assets show the ref plus a flipped copy
    (the in-game pair convention); multi-ref assets one cell per ref. With
    settings, strips run through the packer (overflow stacks below, visible);
    without, strips stack as centered rows distributed evenly down the sheet.

    `scales`: per-asset user scale ({assetName: factor}, mirrors the JS
    resolver) — the packer lays strips out at the SCALED cell size."""
    rows: list[dict] = []
    for asset in order_assets:
        picked = (chosen or {}).get(asset["assetName"])
        paths = picked if picked else [
            f"{asset['category']}/{asset['assetName']}/{f}" for f in asset["refFiles"]
        ]
        if not paths:
            continue
        spec = canvas_spec_of(asset["canvas"])
        k = (scales or {}).get(asset["assetName"], 1)
        rows.append({
            "asset": asset,
            "cellW": (spec or {}).get("w", FALLBACK_CELL) * k,
            "cellH": (spec or {}).get("h", FALLBACK_CELL) * k,
            "paths": paths,
            "flip": len(paths) == 1 and not asset.get("noMirror"),
            "scale": k,
        })
    if not rows:
        return {"regions": [], "overflow": []}

    if settings is not None:
        by_name = {r["asset"]["assetName"]: r for r in rows}
        pseudo = [{
            "id": r["asset"]["assetName"],
            "name": r["asset"]["assetName"],
            "path": f"{r['asset']['category']}/{r['asset']['assetName']}",
            "width": _row_w(r),
            "height": r["cellH"],
        } for r in rows]
        result = pack(pseudo, replace(settings, preset=None, max_width=sheet_w,
                                      max_height=sheet_h, force_square=False,
                                      power_of_two=False))
        regions = []
        for p in result["placed"]:
            row = by_name.get(p["id"])
            if row:
                regions.append(_region_at(row, p["x"], p["y"], sheet_w, sheet_h))
        overflow = []
        y_px = (max((r["y"] + r["h"]) * sheet_h for r in regions) + PAD_PX
                if regions else PAD_PX)
        for oid in result["overflow"]:
            row = by_name.get(oid)
            if not row:
                continue
            overflow.append(row["asset"]["assetName"])
            # floor at 0 — oversized strips clamp to the top edge instead of going out of bounds
            y = max(0, min(y_px, sheet_h - row["cellH"]))
            regions.append(_region_at(row, PAD_PX, y, sheet_w, sheet_h))
            y_px = y + row["cellH"] + PAD_PX
        if settings.fit_width:
            _fit_block_to_width(regions, sheet_w, sheet_h)
        _center_block(regions)
        regions.sort(key=lambda r: (r["y"], r["x"]))
        for i, r in enumerate(regions):
            r["zIndex"] = i
        return {"regions": regions, "overflow": overflow}

    # No settings: rows top-to-bottom in order-sheet order, each centered,
    # distributed space-evenly, fit-scaled together when they'd overflow.
    total_h = sum(r["cellH"] for r in rows) + (len(rows) + 1) * PAD_PX
    max_w = max(_row_w(r) for r in rows) + 2 * PAD_PX
    scale = min(1, sheet_h / total_h, sheet_w / max_w)
    rows_h = sum(r["cellH"] * scale for r in rows)
    gap = max(0, (sheet_h - rows_h) / (len(rows) + 1))
    regions = []
    y_px = gap
    for index, row in enumerate(rows):
        scaled = {**row, "cellW": row["cellW"] * scale, "cellH": row["cellH"] * scale}
        strip_w = _row_w(scaled)
        x_px = max(0, (sheet_w - strip_w) / 2)
        region = _region_at(scaled, x_px, y_px, sheet_w, sheet_h)
        region["zIndex"] = index
        regions.append(region)
        y_px += scaled["cellH"] + gap
    return {"regions": regions, "overflow": []}
