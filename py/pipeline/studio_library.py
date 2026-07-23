# ABOUTME: Pure logic for the Studio Library Picker node — confines a stored
# ABOUTME: volume-relative selection to the studio-assets Volume root and lists it.
import hashlib
import os
import re

# The studio-assets Volume mount root (matches services/comfy-modal/app.py:110).
# Trim + `or` default so a set-but-empty/whitespace env cannot re-anchor the
# confinement root to the process CWD.
STUDIO_ASSETS_DIR = (os.environ.get("STUDIO_ASSETS_DIR") or "").strip() or "/studio-assets"

# Model kinds the editor already surfaces natively via /comfy-models; hidden from
# the browse listing at the studio root. Source of truth (a cross-repo copy):
# services/comfy-modal/canvas_entry.py:14-25 (the sym hub).
MODEL_KINDS = frozenset({
    "checkpoints", "loras", "vae", "controlnet",
    "upscale_models", "embeddings", "diffusion_models", "text_encoders",
})

RESERVED_PREFIX = "studios/"  # services/comfy-modal/studio_assets.py:7

# Studio slug shape (services/comfy-modal/studio_fs.py:9): lowercase kebab-case,
# no length cap, no underscores. Applied with .fullmatch().
_STUDIO_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def _split_studio(rel):
    """(slug, tail) for a volume-relative studios/<slug>[/...] rel, else None."""
    parts = rel.split("/")
    if len(parts) < 2 or parts[0] != "studios" or not _STUDIO_SLUG.fullmatch(parts[1]):
        return None
    return parts[1], "/".join(parts[2:])


def _confined_root(base_dir):
    """realpath'd Volume root; raise ValueError if base_dir is not a usable
    absolute directory (an empty/relative env must not re-anchor to CWD)."""
    if not os.path.isabs(base_dir):
        raise ValueError(f"studio-assets dir is not absolute: {base_dir!r}")
    root = os.path.realpath(base_dir)
    if not os.path.isdir(root):
        raise ValueError(f"studio-assets dir does not exist: {base_dir!r}")
    return root


def resolve_studio_path(base_dir, rel):
    """Absolute path for a volume-relative selection, confined to the Volume root.
    Raises ValueError on empty, non-studio, escaping, or missing input."""
    rel = str(rel or "").strip()
    if not rel:
        raise ValueError("no selection")
    if _split_studio(rel) is None:
        raise ValueError(f"not a studio path: {rel!r}")
    root = _confined_root(base_dir)
    path = os.path.realpath(os.path.join(root, rel))
    if not (path == root or path.startswith(root + os.sep)):
        raise ValueError("outside the studio library")
    if not os.path.exists(path):
        raise ValueError(f"not found: {rel}")
    return path


def resolve_selection(base_dir, selection):
    """(absolute path, is_dir) for a stored selection. Env-free."""
    path = resolve_studio_path(base_dir, selection)
    return path, os.path.isdir(path)


def selection_fingerprint(base_dir, selection):
    """Content-change hash. Files: mtime+size. Folders: sorted direntry-name set
    (an in-place rewrite of a file UNDER a selected folder does NOT change it —
    a documented limitation). Always hashes the selection string itself."""
    selection = str(selection or "")
    h = hashlib.sha256(selection.encode())
    try:
        path, is_dir = resolve_selection(base_dir, selection)
        if is_dir:
            h.update("\x00".join(sorted(os.listdir(path))).encode())
        else:
            st = os.stat(path)
            h.update(f"{st.st_mtime_ns}:{st.st_size}".encode())
    except (ValueError, OSError):
        h.update(b"unresolved")
    return h.hexdigest()


def list_studio_dir(base_dir, studio, rel=""):
    """Confined single-level listing of studios/<studio>[/rel]. Never raises —
    returns {"error": ...} for a bad/escaping dir, or a normal empty listing for
    an unprovisioned studio."""
    try:
        studio = str(studio or "")
        if not _STUDIO_SLUG.fullmatch(studio):
            return {"error": "invalid studio"}
        root = _confined_root(base_dir)
        studio_root = os.path.realpath(os.path.join(root, "studios", studio))
        if not os.path.isdir(studio_root):
            return {"studio": studio, "rel": f"studios/{studio}", "parent": None, "entries": []}
        rel = str(rel or "").strip() or f"studios/{studio}"
        parts = _split_studio(rel)
        if parts is None or parts[0] != studio:
            return {"error": "outside the studio library"}
        target = os.path.realpath(os.path.join(root, rel))
        if not (target == studio_root or target.startswith(studio_root + os.sep)):
            return {"error": "outside the studio library"}
        if not os.path.isdir(target):
            return {"error": "not a directory"}
        at_root = target == studio_root
        entries = []
        with os.scandir(target) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                if at_root and e.name in MODEL_KINDS:
                    continue
                is_dir = os.path.isdir(os.path.join(target, e.name))  # follow; matches execute
                size = None
                if not is_dir:
                    try:
                        size = e.stat().st_size
                    except OSError:
                        size = None
                entries.append({
                    "name": e.name,
                    "rel": f"{rel}/{e.name}",
                    "type": "dir" if is_dir else "file",
                    "size": size,
                })
        entries.sort(key=lambda x: (x["type"] != "dir", x["name"].lower()))
        parent = None if at_root else "/".join(rel.split("/")[:-1])
        return {"studio": studio, "rel": rel, "parent": parent, "entries": entries}
    except (ValueError, OSError) as exc:
        return {"error": str(exc) or "listing failed"}
