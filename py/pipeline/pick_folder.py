# ABOUTME: The Pick node's folder listing — the images already on disk for one
# ABOUTME: asset, numbered so they can be ticked, and the ticked ones copied out.
from __future__ import annotations

import os
import shutil

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# One wrong folder must not try to list a whole output volume into a node body.
LISTING_LIMIT = 400


def name_matches_prefix(name: str, prefix: str) -> bool:
    """Whether a file was written under `prefix` by a Save Image node.

    ComfyUI appends `_00001_` to the prefix, so an underscore has to follow it
    rather than merely the prefix matching: `Spookies` must not claim
    `Spookies Deluxe_00001_.png`, a different asset filed in the same category
    folder. Only the underscore counts, because a space or a dash is an
    ordinary character in an asset name — "Black Cat Lollipop" — while the
    underscore before the counter is ComfyUI's own convention.
    """
    stem = os.path.splitext(name)[0]
    if stem == prefix:
        return True
    return stem.startswith(prefix + "_")


def images_in(folder: str, name_prefix: str = "") -> list[str]:
    """The image files in `folder`, sorted by name.

    One level only. This lists what a Save Image node wrote for one asset, and
    the folder it wrote into holds every other asset of that category — walking
    down from there would pull in whatever else happens to be filed below.

    Sorted by name, which for `<asset>_00001_.png` is the order they were
    rendered in, so the number beside a thumbnail means something stable.
    """
    try:
        names = sorted(os.listdir(folder))
    except OSError:
        return []
    out = []
    for name in names:
        if name.startswith("."):
            continue
        if os.path.splitext(name)[1].lower() not in IMAGE_EXTS:
            continue
        if name_prefix and not name_matches_prefix(name, name_prefix):
            continue
        if not os.path.isfile(os.path.join(folder, name)):
            continue
        out.append(name)
    return out


def listing(folder: str, name_prefix: str = "",
            limit: int = LISTING_LIMIT) -> list[dict]:
    """The folder's images as the node's grid shows them: numbered, with paths.

    The number is the point — "selecting 3 images to go through the node should
    be just a fucking index select". It is 1-based because it is read off the
    screen, not out of an array.

    Pixel sizes come from the image header rather than by decoding, so listing
    four hundred renders stays a directory walk rather than four hundred loads.
    A file that cannot be read is listed without its size instead of being
    hidden — it is on disk, so it belongs in a listing of what is on disk.
    """
    from PIL import Image, UnidentifiedImageError

    out = []
    for index, name in enumerate(images_in(folder, name_prefix)[:limit], 1):
        path = os.path.join(folder, name)
        width = height = 0
        try:
            with Image.open(path) as img:
                width, height = img.size
        except (OSError, UnidentifiedImageError, ValueError):
            pass
        try:
            when = os.stat(path).st_mtime
        except OSError:
            when = 0.0
        out.append({"id": name, "name": name, "index": index, "path": path,
                    "w": width, "h": height, "at": when})
    return out


def read_folders(target: str) -> list[tuple[str, str]]:
    """The (folder, prefix) pairs to read for one name. The prefix layout wins.

    A name is both things at once and only one of them is ever the answer. A
    Save Image node given `…/Food - 3 stages/Spookies` writes
    `Spookies_00001_.png` one level UP — the last segment of a filename prefix
    names the file — while `…/Spookies/` is also a real directory, holding the
    steps that come after: `…/Spookies/edits_00001_.png`.

    So when files named after it sit beside it, those ARE it, and the directory
    of the same name belongs to the stages within. Reading both merged them
    together, which put every edit in the list of renders to choose a base
    from, and moved the numbering under someone every time a stage was saved.
    Only when nothing is named after it is the directory the thing meant —
    which is how work saved a folder-per-asset still reads.
    """
    if not target:
        return []
    parent, own = os.path.dirname(target), os.path.basename(target)
    if own and os.path.isdir(parent) and images_in(parent, own):
        return [(parent, own)]
    if os.path.isdir(target):
        return [(target, "")]
    return []


def listing_for(target: str, limit: int = LISTING_LIMIT, only=None) -> list[dict]:
    """One stage's images, numbered across both layouts as a single grid.

    `only` narrows to a set of file names, which is how a picker fed by another
    picker shows exactly what that one approved — no folder of copies in
    between, and nothing to keep in sync.
    """
    wanted = None if only is None else {str(name) for name in only}
    entries: list[dict] = []
    for folder, prefix in read_folders(target):
        entries.extend(listing(folder, prefix, limit))
    # `id` is the file name, which is what a tick records, so the same name
    # arriving from both layouts must not become two tiles with one identity.
    seen, unique = set(), []
    for entry in entries:
        if entry["id"] in seen or (wanted is not None and entry["id"] not in wanted):
            continue
        if len(unique) >= limit:
            break
        seen.add(entry["id"])
        unique.append({**entry, "index": len(unique) + 1})
    return unique


def picked_paths(entries, selection) -> list[str]:
    """The ticked files, in the order the grid shows them.

    Listing order, not click order: the run has to be reproducible from the
    saved workflow, and click order is recorded nowhere. A tick naming a file
    that is no longer there is skipped rather than raised — deleting a render
    must not break the graph the picker is wired into.
    """
    wanted = {str(s) for s in (selection or [])}
    return [e["path"] for e in entries
            if e.get("id") in wanted and os.path.isfile(e.get("path", ""))]


# What each picker resolved, so the panel can list the same thing the node
# read. In memory on purpose: it is derived from the node's own wires every
# run, and writing it down would be another file in someone's tree for
# something a single queue rebuilds.
_resolved: dict[str, tuple[str, object]] = {}


def remember(node_id, target: str, only=None) -> None:
    _resolved[str(node_id)] = (target or "",
                               None if only is None else [str(n) for n in only])


def resolved(node_id) -> tuple[str, object]:
    """(path, only) this picker last read. ("", None) before it has ever run.

    `only` is None for a picker reading a folder, and the list of names for one
    reading another picker's approvals.
    """
    return _resolved.get(str(node_id), ("", None))
