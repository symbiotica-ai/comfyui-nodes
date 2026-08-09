# ABOUTME: The Pick node's folder listing — the images already on disk for one
# ABOUTME: asset, numbered so they can be ticked, and the ticked ones copied out.
from __future__ import annotations

import os
import re
import shutil

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# What an edit was made FROM, carried in the file's own name.
#
# An edit is a NEW file: the save node gives it a fresh counter name that was
# never among the ticks of the render it came from, so no set of names can ever
# connect the two. The link has to be written at save time, and the filename is
# the one channel that travels with the picture — through a restart, a re-queue
# and a workflow re-open.
#
# The marker FOLLOWS the stage rather than leading the name because a picker
# lists that folder by the stage prefix (`name_matches_prefix`), and a file that
# stopped matching it would vanish from the very grid it was saved for.
FROM_MARKER = "_from."
_SAVE_COUNTER = re.compile(r"_\d+_$")


def edit_prefix(stage: str, parent: str) -> str:
    """The `filename_prefix` for saving work derived from `parent`.

    Naming no parent marks nothing: the prefix stays the plain stage and what it
    writes simply has no parent, which is the only honest answer when there is
    no single render to point at.
    """
    step = str(stage or "")
    stem = os.path.splitext(os.path.basename(str(parent or "")))[0]
    return f"{step}{FROM_MARKER}{stem}" if step and stem else step


def parent_of(name: str) -> str | None:
    """The render an edit was made from, or None when the file does not say.

    Only a marked name answers. Everything written before the marker existed
    carries none, and so does ComfyUI's own default — so an unmarked file has no
    parent rather than a wrong one, and nothing already on disk needs renaming.
    """
    stem = os.path.splitext(os.path.basename(str(name or "")))[0]
    marker = stem.find(FROM_MARKER)
    if marker < 0:
        return None
    return _SAVE_COUNTER.sub("", stem[marker + len(FROM_MARKER):]) or None

# One wrong folder must not try to list a whole output volume into a node body.
LISTING_LIMIT = 400


def name_matches_prefix(name: str, prefix: str) -> bool:
    """Whether a file was written under EXACTLY `prefix` by a Save Image node.

    ComfyUI appends `_00001_` to the prefix, so what follows the prefix must
    be its counter and nothing else: digits between underscores. Anything
    other than a counter is a DIFFERENT prefix that merely starts the same —
    `Spookies` claims neither `Spookies Deluxe_00001_.png` (another asset)
    nor `Spookies_lora_00001_.png` (another save lane into the same folder).
    The picker lists the path it is handed, literally; two lanes stay two
    listings because their save prefixes differ, with no convention beyond
    what is already typed into the save nodes.
    """
    stem = os.path.splitext(name)[0]
    if stem == prefix:
        return True
    # A marked derivative — `edits_from.<parent>_00001_` — is this stage's own
    # file: the mark is written by edit_prefix ON TOP of the stage prefix,
    # so it belongs to the stage the way a counter does.
    if stem.startswith(prefix + FROM_MARKER):
        return True
    if not stem.startswith(prefix + "_"):
        return False
    tail = stem[len(prefix) + 1:].rstrip("_")
    return tail.isdigit()


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
            limit: int = LISTING_LIMIT, keep=None) -> list[dict]:
    """The folder's images as the node's grid shows them: numbered, with paths.

    The number is the point — "selecting 3 images to go through the node should
    be just a fucking index select". It is 1-based because it is read off the
    screen, not out of an array.

    Pixel sizes come from the image header rather than by decoding, so listing
    four hundred renders stays a directory walk rather than four hundred loads.
    A file that cannot be read is listed without its size instead of being
    hidden — it is on disk, so it belongs in a listing of what is on disk.

    `keep` narrows by name BEFORE the cap. The cap is there so one wrong folder
    cannot list a whole volume into a node body; applied to the unnarrowed set
    it does the opposite, cutting the very files that were asked for and
    answering with an empty grid while they sit on disk.
    """
    from PIL import Image, UnidentifiedImageError

    names = images_in(folder, name_prefix)
    if keep is not None:
        names = [name for name in names if keep(name)]
    out = []
    for index, name in enumerate(names[:limit], 1):
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


def _parent_stems(derived_from):
    """The parent names to match against, or None for "no such question".

    None and an empty list are different answers, exactly as they are for
    `only`: nothing approved upstream means there are no edits to show, while
    asking about no parent at all means the whole folder.
    """
    if derived_from is None:
        return None
    names = [derived_from] if isinstance(derived_from, str) else derived_from
    return {os.path.splitext(os.path.basename(str(n)))[0]
            for n in names if str(n).strip()}


def listing_for(target: str, limit: int = LISTING_LIMIT, only=None,
                derived_from=None) -> list[dict]:
    """One stage's images, numbered across both layouts as a single grid.

    `only` narrows to a set of file names, which is how a picker fed by another
    picker shows exactly what that one approved — no folder of copies in
    between, and nothing to keep in sync.

    `derived_from` narrows to the edits OF one render instead, read off each
    file's own mark. It is the other question a second picker can ask, and the
    two cannot be the same one: an edit is a file the approving picker never
    saw, so its name can never be in that picker's ticks.

    Asking about no parent at all means the whole folder; asking about an empty
    set of them means nothing, because nothing approved upstream has no edits.
    """
    wanted = None if only is None else {str(name) for name in only}
    parents = _parent_stems(derived_from)

    def keep(name: str) -> bool:
        if wanted is not None and name not in wanted:
            return False
        return parents is None or parent_of(name) in parents

    entries: list[dict] = []
    for folder, prefix in read_folders(target):
        entries.extend(listing(folder, prefix, limit, keep))
    # `id` is the file name, which is what a tick records, so the same name
    # arriving from both layouts must not become two tiles with one identity.
    seen, unique = set(), []
    for entry in entries:
        if entry["id"] in seen:
            continue
        if len(unique) >= limit:
            break
        seen.add(entry["id"])
        unique.append({**entry, "index": len(unique) + 1})
    return unique


# Where a rejected render goes. A subfolder of what the node lists, because
# both layouts read one level only — so anything in here is out of every
# listing without being out of the tree.
DISCARD_DIR = "discarded"


def discard(target: str, names) -> list[str]:
    """Move `names` out of the listing for `target`. Returns the new paths.

    Never deletes. Several of these renders cost real money and cannot be made
    again, and the node exists to choose between them — so the worst a wrong
    click may do is file a picture one folder deeper, where dragging it back
    undoes it.

    A name is only ever taken from the folders `target` itself reads, matched
    against the listing rather than joined onto a path: that is what stops
    `../` and what stops a request naming a file the node never showed.
    """
    listed = {entry["name"]: entry["path"] for entry in listing_for(target)}
    home = os.path.join(target, DISCARD_DIR)
    moved = []
    for name in names or ():
        source = listed.get(str(name))
        if not source or not os.path.isfile(source):
            continue
        os.makedirs(home, exist_ok=True)
        stem, ext = os.path.splitext(os.path.basename(source))
        destination = os.path.join(home, stem + ext)
        # The save counter restarts whenever a node is pointed at a fresh
        # folder, so the same name arriving twice is ordinary — and the second
        # one must not overwrite the first discard.
        attempt = 1
        while os.path.exists(destination):
            attempt += 1
            destination = os.path.join(home, f"{stem}-{attempt}{ext}")
        try:
            shutil.move(source, destination)
        except OSError:
            continue
        moved.append(destination)
    return moved


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
_resolved: dict[str, tuple[str, object, object]] = {}


def remember(node_id, target: str, only=None, derived_from=None) -> None:
    _resolved[str(node_id)] = (
        target or "",
        None if only is None else [str(n) for n in only],
        None if derived_from is None else [str(n) for n in derived_from])


def resolved(node_id) -> tuple[str, object, object]:
    """(path, only, derived_from) this picker last read.

    ("", None, None) before it has ever run.

    `only` is None for a picker reading a folder, and the list of names for one
    reading another picker's approvals. `derived_from` is the list of renders
    whose edits it is showing instead — the panel has to ask the same question
    the node did, or it lists a folder the run never offered.
    """
    return _resolved.get(str(node_id), ("", None, None))
