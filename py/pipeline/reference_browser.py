# ABOUTME: Reference Browser builder — turn a browser selection over the game's
# ABOUTME: asset library into the standard Order payload the AutoPacker eats.
from __future__ import annotations

import json
import os

from PIL import Image

from .compose import IMG_EXTS
from .project_layout import project_root_of


def _px_dims(path: str) -> tuple[int, int] | None:
    """Image pixel size via a header read; None when unreadable — including a
    decompression-bomb-sized image (a huge client scan), which Pillow rejects
    with DecompressionBombError (not an OSError) at open time."""
    try:
        with Image.open(path) as im:
            return im.size
    except (OSError, Image.DecompressionBombError):
        return None


def list_level(refs_root: str, rel: str = "") -> dict:
    """One level of the library tree: the folders and the images directly inside
    `refs_root/rel`. Never raises — a bad or escaping rel returns {"error": ...}.

    Confinement is by realpath containment, the same rule the builder applies, so
    the browser can never list (and then pick) anything outside the root the user
    wired in. Image entries carry pixel size because the row's canvas comes from
    the largest image in it; an unreadable header yields w/h of None rather than
    dropping the file, so the user still sees it in the tree.
    """
    refs_root = (refs_root or "").strip()
    try:
        root_real = os.path.realpath(refs_root)
        if not refs_root or not os.path.isdir(root_real):
            return {"error": f"not a readable directory: {refs_root!r}"}
        rel = str(rel or "").strip().strip("/")
        target = os.path.realpath(os.path.join(root_real, *rel.split("/"))) \
            if rel else root_real
        if not (target == root_real or target.startswith(root_real + os.sep)):
            return {"error": "outside the reference folder"}
        if not os.path.isdir(target):
            return {"error": f"not a folder: {rel!r}"}
        dirs, images = [], []
        with os.scandir(target) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                child_rel = f"{rel}/{e.name}" if rel else e.name
                if e.is_dir():  # follow symlinks: the containment check above
                    dirs.append({"name": e.name, "rel": child_rel})
                    continue
                if os.path.splitext(e.name)[1].lower() not in IMG_EXTS:
                    continue
                dims = _px_dims(e.path)
                images.append({"name": e.name, "rel": child_rel,
                               "w": dims[0] if dims else None,
                               "h": dims[1] if dims else None})
    except OSError as exc:
        return {"error": f"could not read {rel or '.'}: {exc}"}
    dirs.sort(key=lambda d: d["name"].lower())
    images.sort(key=lambda i: i["name"].lower())
    parent = None if not rel else "/".join(rel.split("/")[:-1])
    return {"root": root_real, "rel": rel, "parent": parent,
            "dirs": dirs, "images": images}


def build_reference_order(refs_root: str, selection, name: str = "") -> dict:
    """Selection JSON -> Order payload. One group = one asset (one sheet row);
    the group's files are its refFiles verbatim (rel paths, may nest). canvas =
    the group's max pixel dims, so (category, canvas) sheet grouping and the
    scale cutoff work exactly as they do for xlsx orders. Missing files are
    dropped; a group with nothing left raises (its name in the message)."""
    refs_root = (refs_root or "").strip()
    if not os.path.isdir(refs_root):
        raise ValueError(f"reference folder not found: {refs_root!r} — wire the "
                         "Studio Library's path into root_path, or type the "
                         "library folder")
    if isinstance(selection, str):
        try:
            selection = json.loads(selection or "{}")
        except ValueError as e:
            raise ValueError(f"selection is not valid JSON: {e}") from e
    # A hand-edited widget could hold valid JSON that is not an object (a list,
    # a number) — treat anything but a dict of groups as empty.
    groups = selection.get("groups") if isinstance(selection, dict) else None
    if not groups:
        raise ValueError("nothing picked — browse the library in the node and "
                         "tick folders or images")
    root_real = os.path.realpath(refs_root)
    assets, used = [], set()
    for g in groups:
        if not isinstance(g, dict):
            continue  # skip a malformed group entry rather than crash
        base = (g.get("name") or "").strip() or "group"
        # Duplicate names collide in prefill's by-name maps (one group's art
        # would overwrite another's), so make each unique — bumping past any
        # suffix a user already typed, never reusing a taken name.
        gname, n = base, 1
        while gname in used:
            n += 1
            gname = f"{base}-{n}"
        used.add(gname)
        files, w, h = [], 0, 0
        for rel in g.get("files") or []:
            p = os.path.join(refs_root, *str(rel).split("/"))
            # Confine reads to refs_root — an escaping rel ('../secret.png') is
            # dropped like a missing file, never composited into the sheet.
            real = os.path.realpath(p)
            inside = real == root_real or real.startswith(root_real + os.sep)
            dims = _px_dims(p) if inside and os.path.isfile(p) else None
            if dims is None:
                continue
            files.append(str(rel))
            w, h = max(w, dims[0]), max(h, dims[1])
        if not files:
            raise ValueError(f"group {gname!r} has no readable images under "
                             f"{refs_root!r} — re-pick it in the browser")
        assets.append({
            "assetName": gname,
            "category": (g.get("category") or "").strip() or gname,
            "canvas": f"{w}x{h}",
            "rotation": "2" if g.get("variants") else "-",
            "refFiles": files,
            "prompt": (g.get("desc") or "").strip(),
        })
    if not assets:
        raise ValueError("nothing valid picked — browse the library in the node "
                         "and tick folders or images")
    feature = (name or "").strip() or os.path.basename(refs_root.rstrip(os.sep))
    return {"feature": feature, "eventName": feature, "assets": assets,
            "refsRoot": refs_root, "assetsRoot": "", "guide": None,
            # The client project this library lives under, so "Save as template"
            # files the sheet in <project>/templates/reference/ — the universal
            # pool, month-free on purpose: a style guide built from the game's
            # asset library applies to every order. "" when the folder is not
            # inside a project — the packer then falls back to
            # output/templates/reference.
            "project_path": project_root_of(refs_root), "month": "",
            # Reference, not order: this is what routes the save (and what the
            # Template Library's kind filter reads back).
            "source": "reference"}
