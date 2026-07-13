# ABOUTME: aiohttp routes for the order pipeline — serves local ref-image
# ABOUTME: thumbnails, folder browsing, and project-asset listings.
from __future__ import annotations

import os
import threading

from aiohttp import web
from server import PromptServer

from .compose import scan_images

ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

_roots: set[str] = set()
_lock = threading.Lock()


def register_root(path: str) -> None:
    """Allow serving images under this folder (called when an Order Read node
    executes with it — i.e. the user explicitly typed it into the graph)."""
    real = os.path.realpath(path)
    if os.path.isdir(real):
        with _lock:
            _roots.add(real)


def is_allowed(path: str) -> str | None:
    """Return the resolved realpath if it may be served, else None.

    The caller must serve exactly the returned path — resolving the raw path a
    second time would reopen the check-then-serve race this closes.
    """
    try:
        if os.path.splitext(path)[1].lower() not in ALLOWED_EXTS:
            return None
        real = os.path.realpath(path)
        if not os.path.isfile(real):
            return None
        with _lock:
            roots = list(_roots)
        if any(real == r or real.startswith(r + os.sep) for r in roots):
            return real
        return None
    except (ValueError, OSError):
        # Malformed input (e.g. embedded null byte) is a deny, not a 500.
        return None


def list_subdirs(path: str) -> dict | None:
    """Directory info for the folder browser: resolved path, parent, and the
    visible (non-dot) subdirectory names sorted case-insensitively. None when
    the path is not a readable directory."""
    try:
        real = os.path.realpath(path or os.path.expanduser("~"))
        if not os.path.isdir(real):
            return None
        dirs = sorted(
            (e.name for e in os.scandir(real)
             if e.is_dir(follow_symlinks=False) and not e.name.startswith(".")),
            key=str.lower,
        )
        parent = os.path.dirname(real)
        return {"path": real, "parent": parent if parent != real else None,
                "dirs": dirs}
    except (ValueError, OSError):
        return None


@PromptServer.instance.routes.get("/symbiotica/local-image")
async def local_image(request):
    path = request.query.get("path", "")
    resolved = is_allowed(path)
    if resolved is None:
        return web.json_response({"error": "not an allowed image path"}, status=403)
    return web.FileResponse(resolved,
                            headers={"Cache-Control": "private, max-age=60"})


@PromptServer.instance.routes.get("/symbiotica/browse-dirs")
async def browse_dirs(request):
    """Folder browser for picking a project reference folder. Lists directory
    NAMES only (no files) — the same local, single-user surface as ComfyUI's
    own filesystem pickers."""
    info = list_subdirs(request.query.get("path", ""))
    if info is None:
        return web.json_response({"error": "not a readable directory"}, status=400)
    return web.json_response(info)


@PromptServer.instance.routes.get("/symbiotica/list-assets")
async def list_assets(request):
    """Recursive image listing of a user-picked project folder. Picking the
    folder in the browser IS the user intent, so the root is registered for
    thumbnail serving via /symbiotica/local-image."""
    root = os.path.realpath(request.query.get("dir", ""))
    if not root or not os.path.isdir(root):
        return web.json_response({"error": "not a readable directory"}, status=400)
    register_root(root)
    try:
        images = scan_images(root)
    except OSError:
        return web.json_response({"error": "could not scan folder"}, status=400)
    return web.json_response({"root": root, "images": images})
