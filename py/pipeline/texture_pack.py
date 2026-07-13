# ABOUTME: Pure packing algorithms (maxrects/shelf/grid/by-folder) — port of hub
# ABOUTME: texture-pack/pack.ts. Takes sprite dicts + settings, returns placements.
from __future__ import annotations

from dataclasses import dataclass

from .model_presets import preset_dims


@dataclass
class PackSettings:
    algorithm: str = "shelf"  # 'maxrects' | 'shelf' | 'grid'
    preset: dict | None = None
    max_width: int = 2048
    max_height: int = 2048
    padding: int = 0
    border: int = 0
    force_square: bool = False
    power_of_two: bool = False
    grid_cell: int = 0
    distribute_by_folder: bool = False
    columns: int = 0
    background: str = "#808080"  # "" = transparent


def effective_max(settings: PackSettings) -> dict:
    dims = preset_dims(settings.preset)
    if dims:
        return dims
    return {"w": settings.max_width, "h": settings.max_height}


def _boxes_for(sprites: list[dict], padding: int) -> list[dict]:
    return [{"id": s["id"], "w": s["width"] + padding, "h": s["height"] + padding}
            for s in sprites]


def _intersects(a: dict, b: dict) -> bool:
    return (a["x"] < b["x"] + b["w"] and a["x"] + a["w"] > b["x"]
            and a["y"] < b["y"] + b["h"] and a["y"] + a["h"] > b["y"])


def _contains(a: dict, b: dict) -> bool:
    return (b["x"] >= a["x"] and b["y"] >= a["y"]
            and b["x"] + b["w"] <= a["x"] + a["w"]
            and b["y"] + b["h"] <= a["y"] + a["h"])


def _prune(rects: list[dict]) -> list[dict]:
    out = list(rects)
    i = 0
    while i < len(out):
        j = i + 1
        removed_i = False
        while j < len(out):
            if _contains(out[j], out[i]):
                out.pop(i)
                removed_i = True
                break
            if _contains(out[i], out[j]):
                out.pop(j)
                continue
            j += 1
        if not removed_i:
            i += 1
    return out


def _pack_maxrects(boxes: list[dict], max_w: int, max_h: int) -> dict:
    order = sorted(boxes, key=lambda b: (-max(b["w"], b["h"]), -b["w"] * b["h"]))
    free = [{"x": 0, "y": 0, "w": max_w, "h": max_h}]
    placed, overflow = [], []
    used_w = used_h = 0
    for box in order:
        best = None
        for f in free:
            if box["w"] <= f["w"] and box["h"] <= f["h"]:
                leftover_h = f["w"] - box["w"]
                leftover_v = f["h"] - box["h"]
                short_side, long_side = sorted((leftover_h, leftover_v))
                if (best is None or short_side < best[2]
                        or (short_side == best[2] and long_side < best[3])):
                    best = (f["x"], f["y"], short_side, long_side)
        if best is None:
            overflow.append(box["id"])
            continue
        node = {"x": best[0], "y": best[1], "w": box["w"], "h": box["h"]}
        placed.append({"id": box["id"], "x": node["x"], "y": node["y"],
                       "width": box["w"], "height": box["h"]})
        used_w = max(used_w, node["x"] + box["w"])
        used_h = max(used_h, node["y"] + box["h"])
        nxt = []
        for f in free:
            if not _intersects(f, node):
                nxt.append(f)
                continue
            if f["x"] < node["x"] < f["x"] + f["w"]:
                nxt.append({"x": f["x"], "y": f["y"], "w": node["x"] - f["x"], "h": f["h"]})
            if node["x"] + node["w"] < f["x"] + f["w"]:
                nxt.append({"x": node["x"] + node["w"], "y": f["y"],
                            "w": f["x"] + f["w"] - (node["x"] + node["w"]), "h": f["h"]})
            if f["y"] < node["y"] < f["y"] + f["h"]:
                nxt.append({"x": f["x"], "y": f["y"], "w": f["w"], "h": node["y"] - f["y"]})
            if node["y"] + node["h"] < f["y"] + f["h"]:
                nxt.append({"x": f["x"], "y": node["y"] + node["h"], "w": f["w"],
                            "h": f["y"] + f["h"] - (node["y"] + node["h"])})
        free = _prune(nxt)
    return {"placed": placed, "overflow": overflow, "width": used_w, "height": used_h}


def _pack_shelf(boxes: list[dict], max_w: int, max_h: int) -> dict:
    order = sorted(boxes, key=lambda b: -b["h"])  # stable, like JS sort
    placed, overflow = [], []
    shelf_x = shelf_y = shelf_h = used_w = 0
    for box in order:
        if box["w"] > max_w or box["h"] > max_h:
            overflow.append(box["id"])
            continue
        if shelf_x + box["w"] > max_w:
            shelf_y += shelf_h
            shelf_x = 0
            shelf_h = 0
        if shelf_y + box["h"] > max_h:
            overflow.append(box["id"])
            continue
        placed.append({"id": box["id"], "x": shelf_x, "y": shelf_y,
                       "width": box["w"], "height": box["h"]})
        shelf_x += box["w"]
        shelf_h = max(shelf_h, box["h"])
        used_w = max(used_w, shelf_x)
    return {"placed": placed, "overflow": overflow, "width": used_w,
            "height": shelf_y + shelf_h}


def _pack_grid(boxes: list[dict], max_w: int, max_h: int, cell: int) -> dict:
    c = cell if cell > 0 else max(1, max((max(b["w"], b["h"]) for b in boxes), default=1))
    cols = max(1, max_w // c)
    placed, overflow = [], []
    used_w = used_h = 0
    for i, box in enumerate(boxes):
        col, row = i % cols, i // cols
        cx, cy = col * c, row * c
        if cy + c > max_h:
            overflow.append(box["id"])
            continue
        placed.append({"id": box["id"], "x": cx + max(0, (c - box["w"]) / 2),
                       "y": cy + max(0, (c - box["h"]) / 2),
                       "width": box["w"], "height": box["h"]})
        used_w = max(used_w, cx + c)
        used_h = max(used_h, cy + c)
    return {"placed": placed, "overflow": overflow, "width": used_w, "height": used_h}


def _parent_folder(path: str) -> str:
    parts = [p for p in path.split("/") if p]
    if len(parts) >= 2:
        return parts[-2]
    return parts[0] if parts else path


def _pack_by_folder(sprites: list[dict], padding: int, max_w: int, max_h: int,
                    columns: int) -> dict:
    placed, overflow = [], []
    groups: dict[str, list[dict]] = {}
    for s in sprites:
        box = {"id": s["id"], "w": s["width"] + padding, "h": s["height"] + padding}
        groups.setdefault(_parent_folder(s["path"]), []).append(box)

    rows: list[list[dict]] = []
    for boxes in groups.values():
        row: list[dict] = []
        row_w = 0
        for box in boxes:
            if box["w"] > max_w or box["h"] > max_h:
                overflow.append(box["id"])
                continue
            wrap_by_count = columns > 0 and len(row) >= columns
            wrap_by_width = row and row_w + box["w"] > max_w
            if wrap_by_count or wrap_by_width:
                rows.append(row)
                row, row_w = [], 0
            row.append(box)
            row_w += box["w"]
        if row:
            rows.append(row)

    if not rows:
        return {"placed": placed, "overflow": overflow, "width": max_w, "height": max_h}

    row_h = [max(b["h"] for b in r) for r in rows]
    total_h = sum(row_h)
    fits = total_h <= max_h
    gap = (max_h - total_h) / (len(rows) + 1) if fits else 0

    y = gap
    r = 0
    while r < len(rows):
        row, h = rows[r], row_h[r]
        if not fits and y + h > max_h:
            break
        row_w = sum(b["w"] for b in row)
        x = max(0, (max_w - row_w) / 2)
        for box in row:
            placed.append({"id": box["id"], "x": x, "y": y + max(0, (h - box["h"]) / 2),
                           "width": box["w"], "height": box["h"]})
            x += box["w"]
        y += h + gap
        r += 1
    while r < len(rows):
        overflow.extend(b["id"] for b in rows[r])
        r += 1
    return {"placed": placed, "overflow": overflow, "width": max_w, "height": max_h}


def pack(sprites: list[dict], settings: PackSettings) -> dict:
    """Dispatch to the chosen algorithm. Sprites must already be the enabled set."""
    if not sprites:
        return {"placed": [], "overflow": [], "width": 0, "height": 0}
    boxes = _boxes_for(sprites, settings.padding)
    mx = effective_max(settings)
    usable_w = max(1, mx["w"] - settings.border * 2)
    usable_h = max(1, mx["h"] - settings.border * 2)

    if settings.distribute_by_folder:
        res = _pack_by_folder(sprites, settings.padding, usable_w, usable_h,
                              settings.columns)
    elif settings.algorithm == "shelf":
        res = _pack_shelf(boxes, usable_w, usable_h)
    elif settings.algorithm == "grid":
        res = _pack_grid(boxes, usable_w, usable_h, settings.grid_cell)
    else:
        res = _pack_maxrects(boxes, usable_w, usable_h)

    if settings.border > 0:
        res["placed"] = [{**p, "x": p["x"] + settings.border,
                          "y": p["y"] + settings.border} for p in res["placed"]]
        res["width"] += settings.border * 2
        res["height"] += settings.border * 2
    return res


def sheet_size(width: float, height: float, settings: PackSettings) -> dict:
    """Final sheet size: preset locks native pixels; else content bounds rounded
    by force-square / power-of-two."""
    dims = preset_dims(settings.preset)
    if dims:
        return dims
    w, h = width, height
    if settings.force_square:
        w = h = max(w, h)
    if settings.power_of_two:
        w, h = _next_pow2(w), _next_pow2(h)
    return {"w": max(1, int(w)), "h": max(1, int(h))}


def _next_pow2(n: float) -> int:
    p = 1
    while p < n:
        p <<= 1
    return p
