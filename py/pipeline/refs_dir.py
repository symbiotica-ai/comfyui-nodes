# ABOUTME: Refs-folder loader — a bound absolute directory becomes an ordered
# ABOUTME: list of image paths, with no browser selection and no editor.
from __future__ import annotations

import hashlib
import os

from PIL import Image

from .compose import IMG_EXTS


def list_reference_images(refs_dir: str, max_count: int = 0) -> list[str]:
    """The absolute paths of the images directly inside `refs_dir`, ordered by
    filename so the same folder always yields the same sequence, at most
    `max_count` of them (0 = every one).

    Raises rather than returning nothing: a graph that silently produced zero
    references would fail further downstream, where the folder is no longer in
    view."""
    refs_dir = (refs_dir or "").strip()
    # Checked BEFORE isdir(): a relative path resolves against wherever the
    # ComfyUI process was started, so a folder that merely happens to sit under
    # the CWD would bind the graph to the launch directory. "" is the same bug
    # in its worst form — it resolves to the CWD itself.
    if not os.path.isabs(refs_dir):
        raise ValueError(f"reference folder must be an absolute path, got "
                         f"{refs_dir!r}")
    if not os.path.isdir(refs_dir):
        raise ValueError(f"reference folder not found: {refs_dir!r}")
    # Flat on purpose: the folder IS the sheet, so a sub-folder is somebody
    # else's set, not more of this one. is_file() rather than a bare name check
    # because a DIRECTORY may perfectly well be called 'sprites.png'.
    with os.scandir(refs_dir) as it:
        names = [e.name for e in it
                 if not e.name.startswith(".") and e.is_file()
                 and os.path.splitext(e.name)[1].lower() in IMG_EXTS]
    if not names:
        raise ValueError(f"no images in {refs_dir!r} — the folder holds no "
                         f"{', '.join(sorted(IMG_EXTS))} file")
    # Case-insensitive first so a human reading the folder sees the same order,
    # then the raw name to break the tie 'A.png' / 'a.png' would otherwise leave
    # to scandir's arbitrary order.
    names.sort(key=lambda n: (n.lower(), n))
    if max_count and max_count > 0:
        names = names[:max_count]
    return [os.path.join(refs_dir, n) for n in names]


def refs_fingerprint(refs_dir: str, max_count: int = 0) -> str:
    """A cache key over what this folder would yield: the names, sizes and mtimes
    of the images in it. Editing an image or dropping one in re-runs the graph,
    where a key over the path alone would serve the previous batch forever.

    Never raises: Comfy calls this during validation, and a missing folder must
    reach `execute` to be reported against this node rather than failing the
    whole graph here."""
    h = hashlib.sha256(f"{refs_dir}|{max_count}".encode())
    try:
        paths = list_reference_images(refs_dir)
    except ValueError:
        return h.hexdigest()
    for p in paths:
        try:
            st = os.stat(p)
            h.update(f"{p}:{st.st_mtime_ns}:{st.st_size}".encode())
        except OSError:
            h.update(f"{p}:missing".encode())
    return h.hexdigest()


def open_reference_images(refs_dir: str, max_count: int = 0):
    """`(path, image)` for each readable image in `refs_dir`, in filename order,
    at most `max_count` pairs (0 = every one).

    A file that will not decode is dropped rather than fatal — one corrupt PNG
    in a library of forty should not lose the run — but a folder where nothing
    decodes raises, because that is indistinguishable to the caller from an
    empty one and would otherwise hand the graph zero references in silence.

    The cap counts what comes back, not what was tried, so a dropped file never
    costs a caller one of its slots.
    """
    paths = list_reference_images(refs_dir)
    opened, unreadable = [], 0
    for p in paths:
        if max_count and max_count > 0 and len(opened) >= max_count:
            break
        try:
            im = Image.open(p)
            im.load()  # Decode now: Image.open is lazy and defers the failure.
        except (OSError, ValueError, Image.DecompressionBombError):
            unreadable += 1
            continue
        opened.append((p, im))
    if not opened:
        raise ValueError(f"none of the {unreadable} image files in {refs_dir!r} "
                         "could be read")
    return opened
