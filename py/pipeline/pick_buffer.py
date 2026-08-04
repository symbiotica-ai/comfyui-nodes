# ABOUTME: The Pick node's on-disk candidate buffer — each image that reaches the
# ABOUTME: node is filed under the hash of its pixels, tagged with the asset it
# ABOUTME: belongs to, listed for the canvas, and read back by the ticks it got.
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil

# Under ComfyUI's output directory, which is already a served root — so a
# thumbnail needs no route of its own, and the candidates survive a restart.
# A temp directory would lose the buffer exactly when a long session is
# interrupted, which is when the picks matter most.
BUFFER_ROOT = "symbiotica_pick"
INDEX_NAME = "index.json"
THUMB_PX = 320
THUMB_SUFFIX = "_thumb.png"

_UNSAFE = re.compile(r"[^A-Za-z0-9_-]")


def safe_node_id(node_id) -> str:
    """A node id reduced to what may name a directory.

    The id arrives from the graph (an integer in a saved workflow, a longer
    string inside a subgraph) and becomes a path segment, so everything that
    could traverse — dots, slashes, null bytes — is dropped rather than
    escaped. An id that reduces to nothing still gets a buffer, under a
    literal name, instead of writing to the parent directory.
    """
    cleaned = _UNSAFE.sub("", str("" if node_id is None else node_id).strip())
    return cleaned[:64] or "unknown"


def buffer_dir(base_dir: str, node_id) -> str:
    """Where one Pick node's candidates live. Per node, so two pickers in the
    same graph — one after generation, one after the edit — never show each
    other's images."""
    return os.path.join(base_dir, BUFFER_ROOT, safe_node_id(node_id))


def index_path(dir_path: str) -> str:
    return os.path.join(dir_path, INDEX_NAME)


def read_index(dir_path: str) -> list[dict]:
    """The buffer's entries, or an empty list.

    A missing or corrupt index reads as empty rather than raising: the index is
    a convenience over files that still exist, and a node that refuses to draw
    because one JSON file was half-written is worse than one that shows nothing
    until the next image arrives.
    """
    try:
        with open(index_path(dir_path), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    return [e for e in data if isinstance(e, dict)] if isinstance(data, list) else []


def write_index(dir_path: str, entries: list[dict]) -> None:
    """Replace the index atomically — a crash mid-write must not leave a
    truncated file that hides every candidate recorded before it."""
    os.makedirs(dir_path, exist_ok=True)
    tmp = index_path(dir_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(entries, fh, ensure_ascii=False)
    os.replace(tmp, index_path(dir_path))


def image_id(img) -> str:
    """A candidate's identity: the hash of its pixels, not of its file.

    Identity has to be the pixels because the same image arrives repeatedly —
    every time a downstream node is queued, the upstream generator replays from
    ComfyUI's cache and hands the picker the same frame again. Hashing the
    encoded PNG would work only as long as the encoder stayed byte-stable;
    hashing the raw buffer is true by construction. Size and mode join the hash
    so two different images that share a pixel buffer length cannot collide.
    """
    payload = img.tobytes()
    stamp = f"{img.width}x{img.height}:{img.mode}".encode("utf-8")
    return hashlib.sha256(payload + stamp).hexdigest()[:16]


def tag_of(asset: str = "", category: str = "", feature: str = "",
           month: str = "", role: str = "") -> dict:
    """The context one candidate was generated under, as recorded on it.

    `role` is deliberately not part of the group label: an asset's stages
    belong together in one view, laid out as rows, not split into separate
    groups that have to be switched between to compare them.
    """
    return {
        "asset": str(asset or "").strip(),
        "category": str(category or "").strip(),
        "feature": str(feature or "").strip(),
        "month": str(month or "").strip(),
        "role": str(role or "").strip(),
    }


def group_key(entry: dict) -> str:
    """The label a candidate is filtered by — the wired context, coarse to fine.

    Empty parts drop out rather than leaving separators, so a sheet recorded
    with only a category reads `Food` and a cell recorded with all of it reads
    `Halloween / Food / pumpkin-cake`. An entry with no context at all groups
    under a name of its own rather than an empty string, which would render as
    a blank row in the picker.
    """
    parts = [entry.get("feature", ""), entry.get("category", ""),
             entry.get("asset", "")]
    label = " / ".join(p for p in (str(x).strip() for x in parts) if p)
    return label or "untagged"


def add_image(dir_path: str, img, *, tag=None, at: str = "") -> dict | None:
    """File one candidate, or None when it is already in the buffer.

    Alpha is kept: a background-removed candidate whose transparency was
    flattened here would be judged on a black rectangle and would come out of
    the node flattened too. The thumbnail is written beside the full image
    because the grid draws every candidate at once — serving 4K PNGs to fill a
    strip of 54px tiles makes the node feel broken on a slow link.
    """
    os.makedirs(dir_path, exist_ok=True)
    ident = image_id(img)
    entries = read_index(dir_path)
    for existing in entries:
        if existing.get("id") == ident:
            return None

    name = f"{ident}.png"
    thumb_name = f"{ident}{THUMB_SUFFIX}"
    img.save(os.path.join(dir_path, name))
    thumb = img.copy()
    thumb.thumbnail((THUMB_PX, THUMB_PX))
    thumb.save(os.path.join(dir_path, thumb_name))

    entry = {"id": ident, "file": name, "thumb": thumb_name,
             "w": img.width, "h": img.height, "at": str(at or ""),
             **tag_of(**(tag or {}))}
    entries.append(entry)
    write_index(dir_path, entries)
    return entry


def list_entries(dir_path: str) -> list[dict]:
    """Every candidate still on disk, oldest first, each with absolute paths.

    An entry whose image was deleted underneath us is dropped from the index
    here rather than served as a broken tile — the buffer lives in the output
    directory, which people do clean out by hand.
    """
    entries = read_index(dir_path)
    alive, changed = [], False
    for entry in entries:
        full = os.path.join(dir_path, str(entry.get("file", "")))
        if not entry.get("file") or not os.path.isfile(full):
            changed = True
            continue
        thumb_rel = str(entry.get("thumb", ""))
        thumb = os.path.join(dir_path, thumb_rel) if thumb_rel else ""
        alive.append({**entry, "path": full,
                      "thumb_path": thumb if os.path.isfile(thumb) else full,
                      "group": group_key(entry)})
    if changed:
        write_index(dir_path, [{k: v for k, v in e.items()
                                if k not in ("path", "thumb_path", "group")}
                               for e in alive])
    return alive


def groups(entries: list[dict]) -> list[dict]:
    """The distinct labels present, with counts, in first-seen order — the
    picker's filter bar. Order is the order candidates arrived rather than
    alphabetical, so the thing being worked on now stays where it appeared."""
    out: list[dict] = []
    seen: dict[str, dict] = {}
    for entry in entries:
        key = entry.get("group") or group_key(entry)
        if key not in seen:
            seen[key] = {"key": key, "count": 0}
            out.append(seen[key])
        seen[key]["count"] += 1
    return out


def roles(entries: list[dict]) -> list[str]:
    """The distinct roles present, in first-seen order.

    Arrival order is the pipeline's own order — a food sheet is cut prep,
    ready, serving — so the rows read the way the stages run rather than
    alphabetically, where "prep" would follow "ready".
    """
    out: list[str] = []
    for entry in entries:
        role = str(entry.get("role", "") or "")
        if role not in out:
            out.append(role)
    return out


def selected_paths(dir_path: str, ids) -> list[str]:
    """Full-size paths for the ticked candidates, in buffer order.

    Buffer order, not click order: the run has to be reproducible from the
    saved workflow, and click order is not recorded anywhere. An id that no
    longer exists is skipped rather than raising — a tick that outlived its
    image must not break the graph it is wired into.
    """
    wanted = {str(i) for i in (ids or [])}
    return [e["path"] for e in list_entries(dir_path) if e.get("id") in wanted]


def drop(dir_path: str, ids) -> int:
    """Delete named candidates and their thumbnails. Returns how many went."""
    wanted = {str(i) for i in (ids or [])}
    if not wanted:
        return 0
    kept, removed = [], 0
    for entry in read_index(dir_path):
        if entry.get("id") in wanted:
            for key in ("file", "thumb"):
                name = str(entry.get(key, ""))
                if name:
                    try:
                        os.remove(os.path.join(dir_path, name))
                    except OSError:
                        pass
            removed += 1
        else:
            kept.append(entry)
    if removed:
        write_index(dir_path, kept)
    return removed


def clear(dir_path: str) -> None:
    """Empty the whole buffer. Missing is already empty, not an error."""
    shutil.rmtree(dir_path, ignore_errors=True)
