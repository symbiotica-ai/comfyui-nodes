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


# Where assetkit builds them: one folder per category under the dataset it
# derived them from, `<Category> Layout/`, holding `<slug>-layout-NN.png`.
# Read in place rather than copied here — the file is already on disk under a
# name assetkit chose, and a second copy is a second thing to keep in step.
BUILT_DIR = ("datasets", "dataset-single")
BUILT_SUFFIX = " layout"


def _loose(name: str) -> str:
    """A folder or category name with the differences that do not matter gone.

    assetkit slugs some names and not others — `Chair Layout` beside
    `Food_-_3_stages Layout` — so matching on the exact string finds one and
    misses the other. Underscores are spaces, runs of space are one, case is
    nothing.
    """
    return " ".join(str(name or "").replace("_", " ").split()).casefold()


def built_dir(project_path: str, name: str) -> str:
    """assetkit's layout folder for `name`, or "".

    Matched loosely against every folder in the dataset, because the exact
    spelling is assetkit's to choose and this side only knows the order
    sheet's.
    """
    wanted = _loose(f"{name}{BUILT_SUFFIX}")
    if not _loose(name):
        return ""
    root = os.path.join(str(project_path or ""), *BUILT_DIR)
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return ""
    for entry in entries:
        found = os.path.join(root, entry)
        if _loose(entry) == wanted and os.path.isdir(found):
            return found
    return ""


def newest_in(folder: str) -> str:
    """The highest-numbered image in `folder`, or "".

    Every file in an assetkit layout folder belongs to that one category, so
    the category is not re-read off the filename — the trailing number is all
    that separates `…-layout-01` from `…-layout-06`. Sorted numerically: as
    text, `-10` lands before `-9`.
    """
    best, best_version = "", -1
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return ""
    for file_name in names:
        if file_name.startswith("."):
            continue
        if os.path.splitext(file_name)[1].lower() not in LAYOUT_EXTS:
            continue
        tail = _VERSION_TAIL.search(os.path.splitext(file_name)[0])
        version = int(tail.group(1)) if tail else 0
        if version >= best_version:
            best, best_version = file_name, version
    return os.path.join(folder, best) if best else ""


def for_name(project_path: str, name: str) -> str:
    """The layout answering to `name`, hand-placed first, then assetkit's.

    `datasets/layouts/` is the override: a file dropped there by hand beats a
    built one, which is how a grid gets tried without rebuilding the set.
    """
    return (newest_for(project_path, name)
            or newest_in(built_dir(project_path, name)))


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
        found = for_name(project_path, f"{category} - {bucket}")
        if found:
            return found
    return for_name(project_path, category)
