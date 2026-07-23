# ABOUTME: Files Read builder — turn a browser selection over a loose client
# ABOUTME: reference folder into the standard Order payload the AutoPacker eats.
from __future__ import annotations

import json
import os

from PIL import Image


def _px_dims(path: str) -> tuple[int, int] | None:
    """Image pixel size via a header read; None when unreadable — including a
    decompression-bomb-sized image (a huge client scan), which Pillow rejects
    with DecompressionBombError (not an OSError) at open time."""
    try:
        with Image.open(path) as im:
            return im.size
    except (OSError, Image.DecompressionBombError):
        return None


def build_files_order(refs_root: str, selection, name: str = "") -> dict:
    """Selection JSON -> Order payload. One group = one asset (one sheet row);
    the group's files are its refFiles verbatim (rel paths, may nest). canvas =
    the group's max pixel dims, so (category, canvas) sheet grouping and the
    scale cutoff work exactly as they do for xlsx orders. Missing files are
    dropped; a group with nothing left raises (its name in the message)."""
    refs_root = (refs_root or "").strip()
    if not os.path.isdir(refs_root):
        raise ValueError(f"reference folder not found: {refs_root!r} — set "
                         "refs_path to the client folder of reference images")
    if isinstance(selection, str):
        try:
            selection = json.loads(selection or "{}")
        except ValueError as e:
            raise ValueError(f"selection is not valid JSON: {e}") from e
    # A hand-edited widget could hold valid JSON that is not an object (a list,
    # a number) — treat anything but a dict of groups as empty.
    groups = selection.get("groups") if isinstance(selection, dict) else None
    if not groups:
        raise ValueError("no groups selected — open the files browser and "
                         "tick folders/files to build groups")
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
                             f"{refs_root!r} — re-open the files browser")
        assets.append({
            "assetName": gname,
            "category": (g.get("category") or "").strip() or gname,
            "canvas": f"{w}x{h}",
            "rotation": "2" if g.get("variants") else "-",
            "refFiles": files,
            "prompt": (g.get("desc") or "").strip(),
        })
    if not assets:
        raise ValueError("no valid groups — open the files browser and tick "
                         "folders/files to build groups")
    feature = (name or "").strip() or os.path.basename(refs_root.rstrip(os.sep))
    return {"feature": feature, "eventName": feature, "assets": assets,
            "refsRoot": refs_root, "assetsRoot": "", "guide": None}
