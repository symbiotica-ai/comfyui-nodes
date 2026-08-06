# ABOUTME: Resolve one client project folder into its parts — the monthly
# ABOUTME: order xlsx files, each month's client-refs folder, and the shared
# ABOUTME: sprite catalog — so the node takes one path plus a month, not three.
from __future__ import annotations

import os
import re

MONTHS = [
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
]

# Project layout under the one path the node is given:
#   <project>/orders/            monthly "<...> <Month> <...>.xlsx" + per-month
#                                 client-refs folders ("<...>-<Month>")
#   <project>/reference-assets/  the shared game sprite catalog (assets_root)
ORDERS_DIRS = ("orders",)
ASSETS_DIRS = ("reference-assets", "reference assets")
_XLSX_EXTS = (".xlsx", ".xlsm")


def _find_subdir(project_path: str, names: tuple[str, ...]) -> str | None:
    """First existing child directory whose name matches (case-insensitive)."""
    try:
        entries = os.listdir(project_path)
    except OSError:
        return None
    lower = {e.lower(): e for e in entries}
    for name in names:
        real = lower.get(name)
        if real and os.path.isdir(os.path.join(project_path, real)):
            return os.path.join(project_path, real)
    return None


def project_root_of(path: str, max_up: int = 6) -> str:
    """The client project folder a library path sits under, or "".

    The Reference Browser is handed a folder somewhere inside
    `<project>/reference-assets/…` (often several levels down — Minis/Mini 01/
    Food). Walking up to the folder that HAS an orders/ or reference-assets/
    child puts its saved templates in the same `<project>/templates/` the order
    pipeline writes to, instead of the machine-local output fallback.
    """
    cur = os.path.realpath(path or "")
    if not cur:
        return ""
    for _ in range(max_up + 1):
        if orders_dir(cur) or assets_dir(cur):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:   # filesystem root
            break
        cur = parent
    return ""


def orders_dir(project_path: str) -> str | None:
    return _find_subdir(project_path, ORDERS_DIRS)


def assets_dir(project_path: str) -> str | None:
    return _find_subdir(project_path, ASSETS_DIRS)


def _month_of(name: str) -> str | None:
    low = name.lower()
    for m in MONTHS:
        if re.search(rf"\b{m}\b", low):
            return m
    return None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def refs_folder_for(orders_path: str, xlsx_name: str) -> str | None:
    """The client-refs folder that goes with an order file. Matches on the
    shared month name first ("Bakery October Art.xlsx" -> "Bakery-October"),
    then falls back to a normalized name overlap."""
    try:
        dirs = [d for d in os.listdir(orders_path)
                if os.path.isdir(os.path.join(orders_path, d))]
    except OSError:
        return None
    month = _month_of(xlsx_name)
    if month:
        hits = sorted(d for d in dirs if month in d.lower())
        if hits:
            return os.path.join(orders_path, hits[0])
    stem = _norm(os.path.splitext(xlsx_name)[0])
    for d in sorted(dirs):
        dn = _norm(d)
        if dn and (dn in stem or stem.startswith(dn)):
            return os.path.join(orders_path, d)
    return None


def list_order_months(project_path: str) -> list[dict]:
    """The order files in <project>/orders, newest month first, each with a
    friendly label and its resolved client-refs folder (may be None)."""
    od = orders_dir(project_path)
    if not od:
        return []
    try:
        files = [f for f in os.listdir(od)
                 if f.lower().endswith(_XLSX_EXTS) and not f.startswith((".", "~"))]
    except OSError:
        return []
    out = []
    for f in sorted(files):
        month = _month_of(f)
        refs = refs_folder_for(od, f)
        out.append({
            "file": f,
            "label": month.capitalize() if month else os.path.splitext(f)[0],
            "month": month or "",
            "order_path": os.path.join(od, f),
            "refs_path": refs or "",
        })
    # Calendar order when months are known; unknown labels sink to the end.
    out.sort(key=lambda o: MONTHS.index(o["month"]) if o["month"] in MONTHS else 99)
    return out


def resolve_month(project_path: str, month: str) -> dict:
    """Resolve the picked month (its xlsx filename, or a month name) to
    {order_path, refs_path, assets_root, month}. Empty strings where unresolved.

    `month` is the CANONICAL name of the order that was picked — "", the month
    name, and the xlsx filename all resolve to the same one. Callers that key
    storage off the month (the order template pool) must use this, not the raw
    string, or three aliases of one month become three folders."""
    months = list_order_months(project_path)
    picked = None
    m = (month or "").strip().lower()
    if m:
        picked = next((o for o in months
                       if o["file"].lower() == m or o["month"] == m
                       or o["label"].lower() == m), None)
    if picked is None and months:
        picked = months[0]
    ad = assets_dir(project_path) or ""
    if picked is None:
        return {"order_path": "", "refs_path": "", "assets_root": ad,
                "month": ""}
    return {
        "order_path": picked["order_path"],
        "refs_path": picked["refs_path"],
        "assets_root": ad,
        "month": picked["month"] or picked["label"],
    }


class MonthNotFound(ValueError):
    """A named month that this project has no order for."""


def _answers_to(resolved: dict, wanted: str) -> bool:
    """Whether a resolution is the one `wanted` asked for.

    The aliases `resolve_month` itself matches on are the filename, the month
    and the label — and the label collapses onto the other two: with a month in
    the filename it is that month capitalized, without one it IS the resolved
    `month`. Admitting fewer than resolve_month accepts would refuse a correct
    resolution."""
    return wanted in {
        os.path.basename(resolved.get("order_path") or "").lower(),
        (resolved.get("month") or "").lower(),
    }


def require_month(project_path: str, month: str) -> dict:
    """`resolve_month`, minus its substitution: a NAMED month this project has
    no order for is refused instead of answered with the project's first one.

    The substitution is hospitable on a canvas, where the month came from a
    live listing and a wrong guess is one click from being seen. Headless it is
    the worst case: the wrong sheet renders, bills, and reports success, and
    the images it yields are indistinguishable from correct ones.

    A BLANK month is not a substitution — it means "whichever this project
    has", and the first order is the answer. Neither is an orderless project:
    nothing was substituted because there was nothing to substitute, and the
    caller's own "no order file" message is the useful one."""
    resolved = resolve_month(project_path, month)
    wanted = (month or "").strip().lower()
    if wanted and resolved["order_path"] and not _answers_to(resolved, wanted):
        have = ", ".join(o["label"] for o in list_order_months(project_path))
        raise MonthNotFound(
            f'"{month}" is not an order this project holds (it has: {have})')
    return resolved
