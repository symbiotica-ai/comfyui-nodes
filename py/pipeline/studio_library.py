# ABOUTME: Pure logic for the Studio Library Picker node — confines a stored
# ABOUTME: volume-relative selection to the studio-assets Volume root and lists it.
import hashlib
import os
import re

# The studio-assets Volume mount root (matches services/comfy-modal/app.py:110).
# Trim + `or` default so a set-but-empty/whitespace env cannot re-anchor the
# confinement root to the process CWD.
STUDIO_ASSETS_DIR = (os.environ.get("STUDIO_ASSETS_DIR") or "").strip() or "/studio-assets"

# The sub_path the studio-assets mount carries, when it carries one — the order
# sandbox mounts sub_path=studios/<slug> (services/comfy-modal/app.py:1943), so its
# mount point IS one studio's root. A selection is always written in VOLUME-ROOT
# coordinates (that is what the browser stores and what a pinned graph freezes), so
# under such a mount the scope is the part of the selection the mount already
# supplies. Empty on the canvas, which mounts the whole Volume.
STUDIO_ASSETS_SCOPE = (os.environ.get("STUDIO_ASSETS_SCOPE") or "").strip().strip("/")

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


def _within_scope(rel):
    """`rel` with the part the mount already supplies removed, for a mount that
    carries a sub_path. A selection naming anything outside it is refused rather
    than joined on: under such a mount that path simply does not exist, so joining
    it answers "not found" for a selection whose real problem is that it belongs to
    another studio. The refusal is not itself the tenancy boundary — the mount is
    (services/comfy-modal/control_plane.py:98) — it is how the miss reads."""
    if rel == STUDIO_ASSETS_SCOPE:
        return ""
    if rel.startswith(STUDIO_ASSETS_SCOPE + "/"):
        return rel[len(STUDIO_ASSETS_SCOPE) + 1:]
    raise ValueError(f"outside this mount: {rel}")


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
    # `rel` itself is never rebound: both messages below name the selection the
    # caller asked for, which is the one written on the node and in the pin.
    within = _within_scope(rel) if STUDIO_ASSETS_SCOPE else rel
    root = _confined_root(base_dir)
    path = os.path.realpath(os.path.join(root, within))
    if not (path == root or path.startswith(root + os.sep)):
        raise ValueError("outside the studio library")
    if not os.path.exists(path):
        raise ValueError(f"not found: {rel}")
    return path


def resolve_selection(base_dir, selection):
    """(absolute path, is_dir) for a stored selection. Env-free."""
    path = resolve_studio_path(base_dir, selection)
    return path, os.path.isdir(path)


def expand_studio_path(base_dir, value):
    """`value` with a volume-relative studios/<slug>/... string (the Studio
    Library node's wire currency) resolved to its absolute confined path; any
    other string — or one that fails to resolve — passes through unchanged so
    the caller's own existence/error handling applies."""
    value = str(value or "").strip()
    if not value.startswith(RESERVED_PREFIX):
        return value
    try:
        return resolve_studio_path(base_dir, value)
    except (ValueError, OSError):
        return value


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


def list_studio_dir(base_dir, studio, rel="", show_model_kinds=False):
    """Confined single-level listing of studios/<studio>[/rel]. Never raises —
    returns {"error": ...} for a bad/escaping dir, or a normal empty listing for
    an unprovisioned studio.

    `show_model_kinds` lists the model folders the root otherwise omits. When
    they are omitted, "hidden" carries how many there were: a folder that was
    skipped and a folder that does not exist produce the same listing, and the
    studio's own web view lists these, so the two disagree by exactly that
    count with nothing in either to say why."""
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
        hidden = 0
        with os.scandir(target) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                is_dir = os.path.isdir(os.path.join(target, e.name))  # follow; matches execute
                # The omission is about the FOLDERS the model loader picks by
                # kind. A file that happens to carry one of those names is an
                # ordinary asset: hiding it strands it where nothing can reach
                # it, and counting it makes the root account for a folder it
                # does not have.
                if at_root and is_dir and e.name in MODEL_KINDS and not show_model_kinds:
                    hidden += 1
                    continue
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
        result = {"studio": studio, "rel": rel, "parent": parent, "entries": entries}
        if hidden:
            result["hidden"] = hidden
        return result
    except (ValueError, OSError) as exc:
        return {"error": str(exc) or "listing failed"}
