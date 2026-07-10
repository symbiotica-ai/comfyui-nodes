# ABOUTME: Spec-driven region prefill — builds template regions FROM the order:
# ABOUTME: one strip per asset, cells at the order's canvas size, xlsx prompt.
# Port of symbiotica-hub apps/web/src/lib/flows/prefill-regions.ts.
from __future__ import annotations

from dataclasses import replace

from .order_sheet import canvas_spec_of
from .texture_pack import PackSettings, pack

PAD_PX = 16
FALLBACK_CELL = 256


def _cell_count(row: dict) -> int:
    return 2 if row["flip"] else len(row["paths"])


def _row_w(row: dict) -> float:
    n = _cell_count(row)
    return n * row["cellW"] + (n - 1) * PAD_PX


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
        x += row["cellW"] + PAD_PX
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
        "assetType": row["asset"]["category"],
        "members": members,
        "taskRefs": {"paths": row["paths"], "mode": "meta"},
    }


def prefill_regions(order_assets: list[dict], sheet_w: int, sheet_h: int,
                    chosen: dict[str, list[str]] | None = None,
                    settings: PackSettings | None = None) -> dict:
    """One region per asset. Single-ref assets show the ref plus a flipped copy
    (the in-game pair convention); multi-ref assets one cell per ref. With
    settings, strips run through the packer (overflow stacks below, visible);
    without, strips stack as centered rows distributed evenly down the sheet."""
    rows: list[dict] = []
    for asset in order_assets:
        picked = (chosen or {}).get(asset["assetName"])
        paths = picked if picked else [
            f"{asset['category']}/{asset['assetName']}/{f}" for f in asset["refFiles"]
        ]
        if not paths:
            continue
        spec = canvas_spec_of(asset["canvas"])
        rows.append({
            "asset": asset,
            "cellW": (spec or {}).get("w", FALLBACK_CELL),
            "cellH": (spec or {}).get("h", FALLBACK_CELL),
            "paths": paths,
            "flip": len(paths) == 1,
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
            y = min(y_px, sheet_h - row["cellH"])
            regions.append(_region_at(row, PAD_PX, y, sheet_w, sheet_h))
            y_px = y + row["cellH"] + PAD_PX
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
