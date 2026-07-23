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
