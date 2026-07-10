# ABOUTME: aiohttp routes for the order pipeline — serves local ref-image
# ABOUTME: thumbnails, restricted to roots registered by executed nodes.
from __future__ import annotations

import os
import threading

from aiohttp import web
from server import PromptServer

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


def is_allowed(path: str) -> bool:
    if os.path.splitext(path)[1].lower() not in ALLOWED_EXTS:
        return False
    real = os.path.realpath(path)
    if not os.path.isfile(real):
        return False
    with _lock:
        roots = list(_roots)
    return any(real == r or real.startswith(r + os.sep) for r in roots)


@PromptServer.instance.routes.get("/symbiotica/local-image")
async def local_image(request):
    path = request.query.get("path", "")
    if not is_allowed(path):
        return web.json_response({"error": "not an allowed image path"}, status=403)
    return web.FileResponse(os.path.realpath(path),
                            headers={"Cache-Control": "private, max-age=60"})
