# ABOUTME: Where each asset sits inside a packed sheet, so a generated sheet can
# ABOUTME: be cut back into the individual cells the dataset was packed into.
import json
import os

# Which roles go in which cell, per layout — the same table assetkit packs by
# (its LAYOUTS). A ragged row is deliberate: "food2row" is one cell over two, and
# the short row is centred rather than left-aligned, so prep sits over the
# midpoint of the pair below it. `None` means the layout writes one file per role
# and never packs a sheet, so there is nothing to cut.
LAYOUTS = {
    "pair": [["rot-left", "rot-right"]],
    "grid2x2": [["rot-back-left", "rot-back-right"],
                ["rot-front-left", "rot-front-right"]],
    "single": [["single"]],
    "food2row": [["prep"],
                 ["ready", "serving"]],
    "separate": None,
    "skip": None,
}

# Written beside a category's sheets by the packer, when it writes one. Read in
# preference to computing the grid — see `boxes_for_category`.
OVERRIDE_NAME = "_layout.json"


def cell_boxes(layout, width, height, padding, swapped=False):
    """The pixel box of every cell in one packed sheet, in reading order.

    This is the packer's own placement arithmetic, not an approximation of it:
    padding is a GUTTER counted `cols + 1` times, so an interior gap is one
    padding wide and not two, and the grid is centred on the canvas. Each entry
    is {role, x, y, w, h} with integer pixels.

    Cells are assumed SQUARE, which is exact whenever the packed sprites are
    square: the box is `min(avail_w / cols, avail_h / rows)` and the sprites'
    own size cancels out of the fit entirely. Non-square sprites give non-square
    boxes AND shift the vertical origin, and nothing on disk records a sprite's
    aspect — that is the case `_layout.json` exists to cover.
    """
    grid = LAYOUTS.get(layout)
    if not grid:
        return []
    width, height = int(width), int(height)
    rows = [list(r) for r in grid]
    if swapped:
        for row in rows:
            row.reverse()

    cols = max(len(r) for r in rows)
    n_rows = len(rows)
    # Clamped exactly as the packer clamps it, so a padding larger than the
    # canvas can support shrinks instead of driving the boxes negative.
    padding = max(0, min(int(padding),
                         (width - cols) // (cols + 1),
                         (height - n_rows) // (n_rows + 1)))
    avail_w = width - padding * (cols + 1)
    avail_h = height - padding * (n_rows + 1)
    if avail_w <= 0 or avail_h <= 0:
        return []
    box = int(min(avail_w / cols, avail_h / n_rows))
    if box <= 0:
        return []

    sheet_w = box * cols + padding * (cols + 1)
    sheet_h = box * n_rows + padding * (n_rows + 1)
    origin_x = (width - sheet_w) // 2
    origin_y = (height - sheet_h) // 2

    out = []
    for r, row in enumerate(rows):
        # Counting declared cells rather than filled ones keeps a short row
        # centred the way the packer centres it.
        row_w = box * len(row) + padding * (len(row) + 1)
        row_x = origin_x + (sheet_w - row_w) // 2
        for c, role in enumerate(row):
            if role is None:
                continue
            out.append({
                "role": role,
                "x": row_x + padding + c * (box + padding),
                "y": origin_y + padding + r * (box + padding),
                "w": box,
                "h": box,
            })
    return out


def _read_json(path):
    """A malformed or absent config is not an error here — every caller has a
    working fallback, and raising would take the whole render down over a file
    the run may not even need."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def layout_map(project_path):
    """(layouts, swapped) for a project: which packing rule each asset type uses.

    Read from `<project>/_sources/config.json`, which the packer writes when the
    type's rule is chosen. Missing file ⇒ empty maps, and the caller falls back
    to treating the sheet as a single cell.
    """
    cfg = _read_json(os.path.join(project_path, "_sources", "config.json"))
    layouts = cfg.get("layouts")
    swapped = cfg.get("swapped")
    return (layouts if isinstance(layouts, dict) else {},
            swapped if isinstance(swapped, dict) else {})


def sheet_settings(project_path):
    """Canvas size and padding the sheets were packed at.

    From `<project>/assetkit-project.json`. The defaults match the packer's own,
    so a project that predates that file still cuts correctly at 1024/20.
    """
    settings = _read_json(
        os.path.join(project_path, "assetkit-project.json")).get("settings")
    if not isinstance(settings, dict):
        settings = {}

    def _int(key, fallback):
        try:
            return int(settings.get(key, fallback))
        except (TypeError, ValueError):
            return fallback

    return _int("width", 1024), _int("height", 1024), _int("padding", 20)


def override_boxes(project_path, category, folder="dataset"):
    """Cell boxes the packer recorded for this type, if it recorded any.

    Preferred over computing them: the packer knows the sprite aspect and the
    upscale policy, and this file is how it says so. Anything malformed is
    ignored rather than half-read — a partial box list would cut wrongly and
    look like a rendering fault.
    """
    data = _read_json(os.path.join(project_path, folder, category,
                                   OVERRIDE_NAME))
    cells = data.get("cells")
    if not isinstance(cells, list) or not cells:
        return []
    out = []
    for cell in cells:
        if not isinstance(cell, dict):
            return []
        try:
            box = {
                "role": str(cell.get("role", "")),
                "x": int(cell["x"]), "y": int(cell["y"]),
                "w": int(cell["w"]), "h": int(cell["h"]),
            }
        except (KeyError, TypeError, ValueError):
            return []
        if box["w"] <= 0 or box["h"] <= 0:
            return []
        out.append(box)
    return out


def boxes_for_category(project_path, category, width=None, height=None,
                       folder="dataset"):
    """Where each asset of `category` sits in its packed sheet.

    The packer's own record wins when present; otherwise the grid is recomputed
    from the type's layout and the project's sheet settings. `width`/`height`
    override the recorded canvas — pass the size of the image actually being
    cut, so a sheet re-rendered at another resolution still divides correctly.

    A type with no known layout falls back to ONE cell covering the whole image.
    That is the honest answer for an unpacked single sprite, and it keeps a
    downstream slice a no-op instead of an error.
    """
    project_path = str(project_path or "").strip()
    category = str(category or "").strip()
    if not project_path or not category:
        return []

    recorded = override_boxes(project_path, category, folder)
    if recorded:
        return _rescaled(recorded, width, height)

    cfg_w, cfg_h, padding = sheet_settings(project_path)
    layouts, swapped = layout_map(project_path)
    layout = str(layouts.get(category, "") or "").strip()
    w = int(width or cfg_w)
    h = int(height or cfg_h)
    if layout not in LAYOUTS:
        return [{"role": "single", "x": 0, "y": 0, "w": w, "h": h}]
    return cell_boxes(layout, w, h, padding, bool(swapped.get(category)))


def _rescaled(boxes, width, height):
    """Recorded boxes mapped onto an image of a different size.

    Only ever a whole-canvas rescale — the packer records against one canvas and
    a re-render at another resolution is uniform, so a single factor per axis is
    the whole story. Same size (the normal case) returns the boxes untouched, so
    no rounding is introduced where none is needed.
    """
    if not boxes or not width or not height:
        return boxes
    recorded_w = max(b["x"] + b["w"] for b in boxes)
    recorded_h = max(b["y"] + b["h"] for b in boxes)
    if recorded_w <= 0 or recorded_h <= 0:
        return boxes
    fx, fy = int(width) / recorded_w, int(height) / recorded_h
    if fx == 1.0 and fy == 1.0:
        return boxes
    return [{
        "role": b["role"],
        "x": int(round(b["x"] * fx)), "y": int(round(b["y"] * fy)),
        "w": int(round(b["w"] * fx)), "h": int(round(b["h"] * fy)),
    } for b in boxes]


def layout_fingerprint(project_path, folder="dataset"):
    """A hash over everything that decides where the cells are.

    Exists because the boxes are read from files that no node lists as an
    input: re-rule a type in the packer and the layout changes while every
    wired value stays identical, so a cached `cell_boxes` would go on
    describing the old grid and the crop would silently drift. Covers the
    per-type rules, the sheet settings, and any recorded `_layout.json`.

    Content, not mtime — a file rewritten with the same bytes should not
    invalidate a cache, and a copied project should not look changed. Never
    raises: this feeds a change-check, and a raise there becomes NaN and
    re-bills every downstream node on each queue press.
    """
    import hashlib
    h = hashlib.sha256()
    project_path = str(project_path or "").strip()
    if not project_path:
        return h.hexdigest()
    paths = [os.path.join(project_path, "_sources", "config.json"),
             os.path.join(project_path, "assetkit-project.json")]
    root = os.path.join(project_path, folder)
    try:
        paths += [os.path.join(root, name, OVERRIDE_NAME)
                  for name in sorted(os.listdir(root))
                  if os.path.isdir(os.path.join(root, name))]
    except OSError:
        pass
    for path in paths:
        h.update(path.encode())
        try:
            with open(path, "rb") as fh:
                h.update(fh.read())
        except OSError:
            # Absent is a state worth hashing too — adding a _layout.json has
            # to invalidate exactly as editing one does.
            h.update(b"\0")
    return h.hexdigest()


def crop_regions(boxes, width, height, inset=0):
    """`boxes` clamped to an actual image, as (role, left, top, right, bottom).

    `inset` shrinks every box towards its centre. It exists because these boxes
    describe the grid a generation was ASKED to hit, not where it landed: a
    render a pixel or two off would otherwise pull the matte colour in along an
    edge. One or two pixels of the asset's own margin costs nothing.

    Boxes that fall entirely outside the image are dropped rather than clamped
    to a sliver, so a mismatched sheet yields fewer cells instead of garbage.
    """
    inset = max(0, int(inset))
    width, height = int(width), int(height)
    out = []
    for b in boxes:
        left = max(0, int(b["x"]) + inset)
        top = max(0, int(b["y"]) + inset)
        right = min(width, int(b["x"]) + int(b["w"]) - inset)
        bottom = min(height, int(b["y"]) + int(b["h"]) - inset)
        if right - left <= 0 or bottom - top <= 0:
            continue
        out.append((str(b.get("role", "")), left, top, right, bottom))
    return out
