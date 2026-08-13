# ABOUTME: The grid layout image an asset type is drawn on — one file per
# ABOUTME: category under <project>/datasets/layouts/, picked the way a recipe is.
from __future__ import annotations

import os
import re

# Where the layouts live, and the ONLY place they are read from. One folder,
# the same project path as everything else. Reading them out of the dataset
# folders instead was tried and reverted: assetkit writes a `<Category> Layout`
# beside every `<Category>` there, so every picker that lists that directory
# showed each category twice.
LAYOUTS_DIR = ("datasets", "layouts")

LAYOUT_EXTS = (".png", ".jpg", ".jpeg", ".webp")

# `Food - 3 stages-6`, `Food - 3 stages 6`, `Food - 3 stages_v2` — a version
# suffix on a name, which is how a new layout arrives: a file dropped beside the
# old one rather than a rename that would silently change what every past run
# used.
_VERSION_TAIL = re.compile(r"[\s._-]+v?(\d+)$", re.I)

# assetkit splits a category by tile footprint — `Appliance 1x2` for a category
# the order sheet calls plain `Appliance`. A size tag is the ONLY extra part
# tolerated after the category, so `Appliance Part` stays its own category and
# can never answer for `Appliance`.
_SIZE_TAG = re.compile(r"^\d+\s*x\s*\d+$", re.I)


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


def _loose(name: str) -> str:
    """A name with the differences that do not matter gone — underscores are
    spaces, runs of space are one, case is nothing. assetkit slugs some names
    and not others, so matching on the exact string finds one and misses the
    next."""
    return " ".join(str(name or "").replace("_", " ").split()).casefold()


def _rank(stem: str, name: str):
    """How this file answers to `name`, as (sized, version), or None.

    An exact stem is version 0 and a numbered one is its number, so the highest
    number wins and a bare name is the floor rather than a competitor. A size
    tag ranks BELOW an unsized match, so `Appliance.png` beats
    `Appliance 1x2.png` while the sized one still answers when it is all there
    is.
    """
    stem, name = _loose(stem), _loose(name)
    if not name or not stem.startswith(name):
        return None
    rest = stem[len(name):]
    tail = _VERSION_TAIL.search(rest)
    version = int(tail.group(1)) if tail else 0
    if tail:
        rest = rest[: tail.start()]
    rest = rest.strip()
    if not rest:
        return (0, version)
    if _SIZE_TAG.match(rest):
        return (1, version)
    return None


def newest_for(project_path: str, name: str) -> str:
    """The best layout answering to `name`, or "".

    "add grid-food7 without renaming anything" is the point: a new version is a
    new file, and the newest one is what runs. An unsized name beats a sized
    one; among equals the highest version wins, numerically, so `-10` beats
    `-9` rather than losing to it as text.
    """
    name = str(name or "").strip()
    if not name:
        return ""
    best, best_key = "", None
    for file_name in list_layouts(project_path):
        rank = _rank(os.path.splitext(file_name)[0], name)
        if rank is None:
            continue
        # Lower `sized` wins, then higher version; the file name settles ties
        # so the answer is the same on every run.
        key = (rank[0], -rank[1], file_name)
        if best_key is None or key < best_key:
            best, best_key = file_name, key
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
        # A size bucket is looked up the way assetkit WRITES it — `Appliance
        # 1x2.png`, a space and no dash — before the book's own `<category> -
        # <bucket>` form. Its export path is theirs to name and ours to read.
        # This lookup also settles a tie the plain category cannot: with
        # `Appliance 1x1.png` and `Appliance 1x2.png` both on disk and nothing
        # to choose between them, asking for the category alone answered
        # `1x1` for every appliance, including the tall ones.
        names = ([f"{category} {bucket}"] if _SIZE_TAG.match(bucket) else [])
        for name in [*names, f"{category} - {bucket}"]:
            found = newest_for(project_path, name)
            if found:
                return found
    return newest_for(project_path, category)
