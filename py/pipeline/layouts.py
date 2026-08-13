# ABOUTME: The grid layout image an asset type is drawn on — one file per
# ABOUTME: category under <project>/datasets/layouts/, picked the way a recipe is.
from __future__ import annotations

import os
import re

# Where the layouts live. Under `datasets/`, not under `prompts/`: they are
# artwork, made in assetkit alongside the reference sets, and the prompt book
# holds text.
LAYOUTS_DIR = ("datasets", "layouts")

LAYOUT_EXTS = (".png", ".jpg", ".jpeg", ".webp")

# `Food - 3 stages-6`, `Food - 3 stages 6`, `Food - 3 stages_v2` — a version
# suffix on a name, which is how a new layout arrives: a file dropped beside the
# old one rather than a rename that would silently change what every past run
# used.
_VERSION_TAIL = re.compile(r"[\s._-]+v?(\d+)$", re.I)


def layouts_dir(project_path: str) -> str:
    return os.path.join(str(project_path or ""), *LAYOUTS_DIR)


def list_layouts(project_path: str) -> list[str]:
    """Every layout file's name, sorted. What the node's picker offers."""
    try:
        names = sorted(os.listdir(layouts_dir(project_path)))
    except OSError:
        return []
    return [n for n in names
            if not n.startswith(".")
            and os.path.splitext(n)[1].lower() in LAYOUT_EXTS]


def _version_of(stem: str, name: str):
    """How this file answers to `name`: (rank, version), or None for no match.

    An exact stem is version 0 and a numbered one is its number, so the highest
    number wins and a bare name is the floor rather than a competitor.
    """
    if stem == name:
        return 0
    if not stem.startswith(name):
        return None
    tail = _VERSION_TAIL.match(stem[len(name):])
    return int(tail.group(1)) if tail else None


def newest_for(project_path: str, name: str) -> str:
    """The highest-numbered layout answering to `name`, or "".

    "add grid-food7 without renaming anything" is the whole point: a new
    version is a new file, and the newest one is what runs. Ties cannot happen
    — two files with the same number differ by extension, and the sorted
    listing settles it.
    """
    name = str(name or "").strip()
    if not name:
        return ""
    best, best_version = "", -1
    for file_name in list_layouts(project_path):
        version = _version_of(os.path.splitext(file_name)[0], name)
        if version is not None and version > best_version:
            best, best_version = file_name, version
    return os.path.join(layouts_dir(project_path), best) if best else ""


def pick_layout(project_path: str, category: str = "", bucket: str = "",
                pinned: str = "") -> str:
    """The layout file to draw on, as an absolute path, or "".

    The ladder is the recipe's, so there is one naming rule to remember rather
    than two: a pinned name wins outright, then `<category> - <bucket>`, then
    the plain category. A bucket with no layout of its own falls back the same
    way a bucket with no recipe does — it is a narrowing, never a demand.
    """
    pinned = str(pinned or "").strip()
    if pinned:
        # A pinned name is a FILE in the folder, matched by listing rather than
        # joined onto the path: that is what stops `../` reaching out of the
        # project, the same way the prompt store resolves a block.
        for file_name in list_layouts(project_path):
            if file_name == pinned or os.path.splitext(file_name)[0] == pinned:
                return os.path.join(layouts_dir(project_path), file_name)
        return ""
    category = str(category or "").strip()
    bucket = str(bucket or "").strip()
    if category and bucket:
        found = newest_for(project_path, f"{category} - {bucket}")
        if found:
            return found
    return newest_for(project_path, category)
