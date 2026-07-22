# ABOUTME: Files Read builder — turn a browser selection over a loose client
# ABOUTME: reference folder into the standard Order payload the AutoPacker eats.
from __future__ import annotations

import json
import os

from PIL import Image


def _px_dims(path: str) -> tuple[int, int] | None:
    """Image pixel size via a header read; None when unreadable."""
    try:
        with Image.open(path) as im:
            return im.size
    except OSError:
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
    groups = (selection or {}).get("groups") or []
    if not groups:
        raise ValueError("no groups selected — open the files browser and "
                         "tick folders/files to build groups")
    assets, seen = [], {}
    for g in groups:
        gname = (g.get("name") or "").strip() or "group"
        # Duplicate names would collide in prefill's by-name maps: suffix them.
        seen[gname] = seen.get(gname, 0) + 1
        if seen[gname] > 1:
            gname = f"{gname}-{seen[gname]}"
        files, w, h = [], 0, 0
        for rel in g.get("files") or []:
            p = os.path.join(refs_root, *str(rel).split("/"))
            dims = _px_dims(p) if os.path.isfile(p) else None
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
    feature = (name or "").strip() or os.path.basename(refs_root.rstrip(os.sep))
    return {"feature": feature, "eventName": feature, "assets": assets,
            "refsRoot": refs_root, "assetsRoot": "", "guide": None}
