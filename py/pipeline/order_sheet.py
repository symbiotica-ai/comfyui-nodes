# ABOUTME: Parser for a client's monthly asset-order spreadsheet (xlsx) — extracts
# ABOUTME: typed order rows, matches reference filenames, groups assets into events.
# Pure-Python port of symbiotica-hub apps/web/src/lib/flows/order-sheet.ts.
from __future__ import annotations

import io
import math
import re
import zipfile

_XML_ENTITIES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'"}
_ENTITY_RE = re.compile(r"&(?:amp|lt|gt|quot|apos);|&#x?[0-9a-fA-F]+;")
_T_RUN_RE = re.compile(r"<t(?:\s[^>]*)?>(.*?)</t>", re.S)
_SI_RE = re.compile(r"<si>(.*?)</si>", re.S)
_SELF_CLOSED_CELL_RE = re.compile(r"<c\s[^>]*/>")
_CELL_RE = re.compile(r"<c\s([^>]*)>(.*?)</c>", re.S)
_REF_RE = re.compile(r'r="([A-Z]+)(\d+)"')
_TYPE_RE = re.compile(r't="([^"]+)"')
_V_RE = re.compile(r"<v(?:\s[^>]*)?>(.*?)</v>", re.S)
_SHEET_NAME_RE = re.compile(r"^xl/worksheets/sheet\d+\.xml$")


def decode_xml(s: str) -> str:
    def repl(m: re.Match) -> str:
        token = m.group(0)
        if token in _XML_ENTITIES:
            return _XML_ENTITIES[token]
        try:
            code = int(token[3:-1], 16) if token.startswith("&#x") else int(token[2:-1])
        except ValueError:
            return token
        return chr(code)

    return _ENTITY_RE.sub(repl, s)


def text_runs(fragment: str) -> str:
    """Concatenated text of all <t> runs inside an <si>/<is> fragment."""
    return "".join(decode_xml(t) for t in _T_RUN_RE.findall(fragment))


def col_index(letters: str) -> int:
    """Column letters -> 0-based index (A->0, Z->25, AA->26)."""
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def numeric_text(v: str) -> str:
    """Numeric cell text -> display string ("46301" and "46301.0" both -> "46301")."""
    try:
        n = float(v)
    except ValueError:
        return v
    if n != n or n in (float("inf"), float("-inf")):
        return v
    if n == int(n) and abs(n) < 1e15:
        return str(int(n))
    return repr(n)


def parse_xlsx_grid(data: bytes) -> list[list[str]]:
    """Read the first worksheet of an xlsx into a dense row/col grid of cell text.

    Handles shared strings (t="s"), inline strings (t="inlineStr"), and numeric
    cells. Formula/error cells surface as their cached value text.
    """
    zf = zipfile.ZipFile(io.BytesIO(data))
    names = set(zf.namelist())
    shared: list[str] = []
    if "xl/sharedStrings.xml" in names:
        sst = zf.read("xl/sharedStrings.xml").decode("utf-8")
        shared = [text_runs(si) for si in _SI_RE.findall(sst)]
    sheet_names = sorted(n for n in names if _SHEET_NAME_RE.match(n))
    if not sheet_names:
        raise ValueError("xlsx has no worksheet")
    # Drop self-closing cells (styled-but-empty, common in Google Sheets exports)
    # so the cell regex can't swallow the following cell's body.
    sheet = _SELF_CLOSED_CELL_RE.sub("", zf.read(sheet_names[0]).decode("utf-8"))

    cells: dict[int, dict[int, str]] = {}
    for attrs, body in _CELL_RE.findall(sheet):
        ref = _REF_RE.search(attrs)
        if not ref:
            continue
        row = int(ref.group(2)) - 1
        col = col_index(ref.group(1))
        type_m = _TYPE_RE.search(attrs)
        ctype = type_m.group(1) if type_m else "n"
        if ctype == "inlineStr":
            text = text_runs(body)
        else:
            v = _V_RE.search(body)
            if not v:
                continue
            raw = decode_xml(v.group(1))
            if ctype == "s":
                idx = int(raw)
                text = shared[idx] if 0 <= idx < len(shared) else ""
            elif ctype == "n":
                text = numeric_text(raw)
            else:
                text = raw
        cells.setdefault(row, {})[col] = text

    height = max(cells, default=-1) + 1
    grid: list[list[str]] = []
    for r in range(height):
        row_cells = cells.get(r, {})
        width = max(row_cells, default=-1) + 1
        grid.append([row_cells.get(c, "") for c in range(width)])
    return grid


# Header labels we locate columns by (matched case-insensitively, trimmed).
HEADERS = {
    "status": "status",
    "release": "release",
    "feature": "feature",
    "eventName": "event name",
    "assetName": "asset name",
    "assetId": "id",
    "category": "asset category",
    "canvas": "canvas",
    "plot": "plot",
    "rotation": "rotation",
    "prompt": "prompt",
    "sets": "sets #",
}


def _norm(s: str) -> str:
    return s.strip().lower()


def _number(s: str):
    try:
        f = float(s)
    except ValueError:
        return None  # JS Number("junk") is NaN; NaN serializes to null anyway.
    if not math.isfinite(f):
        return None  # hub: Number("nan"/"inf") -> NaN/Infinity -> JSON null
    return int(f) if f == int(f) else f


# What a Food row's Prep) line says it stands on. The client already writes the
# distinction — every food row names a chopping board, every drink row names an
# empty cup on a saucer — so the bucket is READ rather than guessed from the
# asset name, which would have caught "Skull Tea" but not "Fox Cocoa Float".
_PREP_BOARD = re.compile(r"\b(chopping|cutting)\s+board\b|\bboard\b", re.I)
_PREP_VESSEL = re.compile(
    r"\b(teacup|tea cup|cup|mug|glass|tumbler|saucer|goblet|stein)s?\b", re.I)


def is_staged(prompt: str) -> bool:
    """Does this row describe a thing packed in STAGES — a Prep) line, or a
    Ready) marker to read up to?

    Only `Food - 3 stages` writes that way. Everything else is one description
    of one object, and it has no prep line at all — which is not the same as
    having an empty one.
    """
    text = str(prompt or "")
    return ("Ready)" in text
            or any(line.strip().lower().startswith("prep")
                   for line in text.splitlines()))


def prep_line(prompt: str) -> str:
    """The client prompt's Prep) line, or everything before Ready), or "".

    The three states are three lines, but a sheet cell is one string whose
    newlines survive inconsistently — so falling back to "up to Ready)" reads
    the same row either way.

    A row with NEITHER has no prep line, and answering with the whole prompt
    was a quiet disaster one caller down: `Midnight Cathedral Oven` is an
    Appliance whose door carries "red and purple stained glass inserts", and
    the vessel test read that as a drink.
    """
    if not is_staged(prompt):
        return ""
    for line in str(prompt or "").splitlines():
        if line.strip().lower().startswith("prep"):
            return line
    return str(prompt or "").split("Ready)")[0]


def bucket_of(prompt: str) -> str:
    """Which sub-kind of its category an asset is, or "" for the plain one.

    Only `Drinks` today, and only ever a NARROWING: the category is untouched,
    so the sheets, the dataset folders and the save paths all stay where they
    are, and a row this cannot read simply keeps the category's own prompts.
    A board wins over a vessel — a food prep names a bowl or a cup on the board
    all the time, while a drink prep never has a board at all.
    """
    line = prep_line(prompt)
    if _PREP_BOARD.search(line):
        return ""
    return "Drinks" if _PREP_VESSEL.search(line) else ""


# One floor tile, in pixels. The Canvas column is a pixel size and assetkit
# names a grid by the tiles that size covers — `128x256` is the sheet it calls
# `Appliance 1x2` — so the two only meet through this number.
TILE_PX = 128


def canvas_tiles(canvas: str) -> str:
    """The asset's CANVAS measured in floor tiles, as `<w>x<h>`, or "".

    This is what assetkit's grid tag counts, and it is the distinction that
    matters when drawing: `Appliance 1x1` is a short room corner with two
    courses of wall and `Appliance 1x2` is the same floor under a wall twice as
    high, so "the 1x1 one appliance must fit in the grid box and not be taller
    than the grid walls".

    NOT the sheet's own `plot` column. That one is the game footprint and does
    not follow the canvas at all — the October sheet has both a 128x128 and a
    128x256 Appliance marked plot `1x1`, and Decoration rows on one 256x256
    canvas marked `1x2`, `2x2` and `3x3`. Reading `plot` here would put two
    different grids under one name.

    A canvas that is not a whole number of tiles — `200x200` (Crate Icon),
    `128x129` (a Wallpaper typo) — has no grid of its own and says so.
    """
    spec = canvas_spec_of(str(canvas or ""))
    if not spec or not spec["w"] or not spec["h"]:
        return ""
    if spec["w"] % TILE_PX or spec["h"] % TILE_PX:
        return ""
    return f"{spec['w'] // TILE_PX}x{spec['h'] // TILE_PX}"


def bucket_for(asset: dict) -> str:
    """The bucket of one asset ROW — how this row is drawn within its category.

    Two narrowings, one wire: what the Prep line says (`Drinks`) wins, and a
    row with nothing to read there falls back to its canvas in tiles. Both end
    up as `<category> - <bucket>` in the recipe book and in
    `datasets/layouts/`, so one name resolves the prompt AND the grid, and
    neither is ever a demand — a bucket with no recipe of its own is drawn the
    category's ordinary way.
    """
    asset = asset or {}
    return (str(asset.get("bucket") or "").strip()
            or bucket_of(asset.get("prompt", ""))
            or canvas_tiles(asset.get("canvas", "")))


def extract_order_rows(grid: list[list[str]]) -> list[dict]:
    """Find the header row (contains both "Feature" and "Asset Name"), map
    columns by header text, and type every data row below it. Rows with neither
    a feature nor an asset name are dropped; placeholder rows (feature only)
    are kept so unspecced slots stay visible."""
    header_row = -1
    for r, row in enumerate(grid):
        cells = [_norm(c) for c in row]
        if "feature" in cells and "asset name" in cells:
            header_row = r
            break
    if header_row < 0:
        raise ValueError(
            'order sheet: header row not found (needs "Feature" and "Asset Name" columns)'
        )

    cols: dict[str, int] = {}
    for i, cell_text in enumerate(grid[header_row]):
        label = _norm(cell_text)
        for key, header in HEADERS.items():
            # First matching column wins — later duplicate headers (artist copies) lose.
            if label == header and key not in cols:
                cols[key] = i

    def cell(row: list[str], key: str) -> str:
        i = cols.get(key)
        if i is None or i >= len(row):
            return ""
        return (row[i] or "").strip()

    rows: list[dict] = []
    for r in range(header_row + 1, len(grid)):
        raw = grid[r]
        feature = cell(raw, "feature")
        asset_name = cell(raw, "assetName")
        if not feature and not asset_name:
            continue
        status_text = cell(raw, "status")
        rows.append({
            "row": r + 1,
            "status": None if status_text == "" else _number(status_text),
            "release": cell(raw, "release"),
            "feature": feature,
            "eventName": cell(raw, "eventName"),
            "assetName": asset_name,
            "assetId": cell(raw, "assetId"),
            "category": cell(raw, "category"),
            "canvas": cell(raw, "canvas"),
            "plot": cell(raw, "plot"),
            "rotation": cell(raw, "rotation"),
            "prompt": cell(raw, "prompt"),
            "sets": cell(raw, "sets"),
            "bucket": bucket_of(cell(raw, "prompt")),
        })
    return rows


def compact_asset_name(name: str) -> str:
    """Asset name -> the compact form used by reference filenames: spaces
    removed, everything else (underscores, case) kept as-is."""
    return re.sub(r"\s+", "", name)


def match_ref_files(asset_name: str, file_names: list[str]) -> list[str]:
    """Reference files whose basename is the asset's compact name, optionally
    with a _N variant suffix ("BatCroissants.png", "BatCroissants_2.png")."""
    compact = compact_asset_name(asset_name)
    if not compact:
        return []
    pattern = re.compile(rf"^{re.escape(compact)}(_\d+)?\.[a-zA-Z0-9]+$")
    return sorted(f for f in file_names if pattern.match(f))


def slugify(s: str) -> str:
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", s.lower()))


def canvas_spec_of(canvas: str) -> dict | None:
    """Parse "128x128" (case/space tolerant) into {"w", "h"}; None otherwise."""
    m = re.match(r"^(\d+)x(\d+)$", re.sub(r"\s+", "", canvas.lower()))
    return {"w": int(m.group(1)), "h": int(m.group(2))} if m else None


def group_order_events(rows: list[dict], ref_file_names: list[str]) -> list[dict]:
    """Group order rows into events by Feature (first-appearance order), attach
    matched reference files per asset. Event name = first non-empty one seen."""
    by_feature: dict[str, dict] = {}
    for row in rows:
        key = row["feature"] or "(no feature)"
        event = by_feature.get(key)
        if event is None:
            event = {"feature": key, "eventName": row["eventName"], "assets": []}
            by_feature[key] = event
        if not event["eventName"] and row["eventName"]:
            event["eventName"] = row["eventName"]
        event["assets"].append(
            {**row, "refFiles": match_ref_files(row["assetName"], ref_file_names)}
        )
    return list(by_feature.values())


def template_groups(event: dict) -> list[dict]:
    """Group an event's named assets by category + canvas into template sheets —
    the unit one generation pass renders. Unnamed placeholder rows are skipped."""
    groups: dict[str, dict] = {}
    for asset in event["assets"]:
        if not asset["assetName"]:
            continue
        key = f"{asset['category']}|{asset['canvas']}"
        group = groups.get(key)
        if group is None:
            group = {
                "template": slugify(f"{event['feature']}-{asset['category']}-{asset['canvas']}"),
                "category": asset["category"],
                "canvas": asset["canvas"],
                "assets": [],
            }
            groups[key] = group
        group["assets"].append(asset)
    return list(groups.values())
