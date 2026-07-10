# ABOUTME: Parser for a client's monthly asset-order spreadsheet (xlsx) — extracts
# ABOUTME: typed order rows, matches reference filenames, groups assets into events.
# Pure-Python port of symbiotica-hub apps/web/src/lib/flows/order-sheet.ts.
from __future__ import annotations

import io
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
