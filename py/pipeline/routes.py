# ABOUTME: aiohttp routes for the order pipeline — serves local ref-image
# ABOUTME: thumbnails, folder browsing, and project-asset listings.
from __future__ import annotations

import base64
import json
import os
import threading

from aiohttp import web
from server import PromptServer

from .compose import scan_images
from .order_sheet import slugify

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


def _template_dir() -> str | None:
    """ComfyUI's output/templates folder, or None when folder_paths is absent
    (unit tests import this module with server/aiohttp stubbed)."""
    try:
        import folder_paths
    except ImportError:
        return None
    return os.path.join(folder_paths.get_output_directory(), "templates")


def write_template(out_dir: str, name: str, png_bytes: bytes,
                   sidecar: dict) -> str:
    """Write <slug>.png + <slug>.json into out_dir. Returns the rel key
    "templates/<slug>.png". Re-saves overwrite."""
    stem = slugify(name) or "template"
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, f"{stem}.png"), "wb") as f:
        f.write(png_bytes)
    with open(os.path.join(out_dir, f"{stem}.json"), "w") as f:
        json.dump({"name": stem, **sidecar}, f, indent=1)
    return f"templates/{stem}.png"


def list_templates(out_dir: str | None) -> list[dict]:
    """Sidecar dicts for every readable template in out_dir (each gains
    "file": "templates/<slug>.png"), sorted by name. Unreadable or invalid
    sidecars are skipped; a missing dir is an empty list."""
    if not out_dir or not os.path.isdir(out_dir):
        return []
    templates = []
    for entry in sorted(os.listdir(out_dir)):
        if not entry.endswith(".json"):
            continue
        try:
            with open(os.path.join(out_dir, entry)) as f:
                sidecar = json.load(f)
        except (OSError, ValueError):
            continue  # corrupt/unreadable sidecar: skip, don't fail the list
        if not isinstance(sidecar, dict):
            continue
        sidecar["file"] = f"templates/{os.path.splitext(entry)[0]}.png"
        templates.append(sidecar)
    return sorted(templates, key=lambda s: str(s.get("name", "")))


@PromptServer.instance.routes.get("/symbiotica/local-image")
async def local_image(request):
    path = request.query.get("path", "")
    resolved = is_allowed(path)
    if resolved is None:
        return web.json_response({"error": "not an allowed image path"}, status=403)
    return web.FileResponse(resolved,
                            headers={"Cache-Control": "private, max-age=60"})


@PromptServer.instance.routes.get("/symbiotica/ref-image")
async def ref_image(request):
    """Serve the reference image a member path denotes, using the SAME
    resolution rule as compose._draw_task_refs (exact rel under root, else
    flat basename) — so the JS canvas shows exactly what the queued sheet
    will draw. Root must already be registered (a node execute did it)."""
    from .compose import resolve_ref
    root = request.query.get("root", "")
    rel = request.query.get("rel", "")
    resolved = is_allowed(resolve_ref(root, rel))
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


@PromptServer.instance.routes.get("/symbiotica/list-orders")
async def list_orders(request):
    """The months available under a project folder's orders/ subdir, for the
    Order Read node's month picker."""
    from .project_layout import list_order_months

    project = request.query.get("project", "").strip()
    if not project or not os.path.isdir(project):
        return web.json_response({"months": []})
    months = list_order_months(project)
    # The month combo only needs file + label; the paths are re-derived at
    # execute so a moved folder can't ship stale absolute paths in the graph.
    return web.json_response(
        {"months": [{"file": m["file"], "label": m["label"]} for m in months]})


@PromptServer.instance.routes.get("/symbiotica/parse-order")
async def parse_order(request):
    """On-demand order parse for the template editor — same loader the Order
    Read node uses, so task assets are available without queueing first.
    Resolves project+month like the node, or takes explicit order/refs paths."""
    from .order_loader import load_order
    from .project_layout import resolve_month

    order_path = request.query.get("order_path", "").strip()
    refs_path = request.query.get("refs_path", "").strip()
    project = request.query.get("project", "").strip()
    month = request.query.get("month", "").strip()
    assets_root = ""
    if project:
        r = resolve_month(project, month)
        order_path = order_path or r["order_path"]
        refs_path = refs_path or r["refs_path"]
        assets_root = r["assets_root"]
    if not order_path:
        return web.json_response({"error": "order_path required"}, status=400)
    try:
        loaded = load_order(order_path, refs_path)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    if refs_path:
        register_root(refs_path)
    if assets_root:
        register_root(assets_root)
    loaded["refsRoot"] = refs_path
    loaded["assetsRoot"] = assets_root
    return web.json_response(loaded)


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
        rels = scan_images(root)
    except OSError:
        return web.json_response({"error": "could not scan folder"}, status=400)
    images = []
    for rel in rels:
        # Pixel size drives the editor's resolution folders/filter (hub
        # parity); PIL reads only the header. Unreadable -> size unknown.
        try:
            from PIL import Image
            with Image.open(os.path.join(root, rel.replace("/", os.sep))) as im:
                w, h = im.size
        except Exception:
            w = h = None
        images.append({"rel": rel, "w": w, "h": h})
    return web.json_response({"root": root, "images": images})


@PromptServer.instance.routes.post("/symbiotica/template-save")
async def template_save(request):
    """Persist an editor-built template: PNG (data URL) + JSON sidecar under
    output/templates. The dir is registered so /symbiotica/local-image can
    serve the PNG back to the editor."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)
    name = str(body.get("name") or "")
    slug = slugify(name)
    if not slug:
        return web.json_response({"error": "name is required"}, status=400)
    png = str(body.get("png") or "")
    try:
        png_bytes = base64.b64decode(png.split(",", 1)[1])
    except (IndexError, ValueError):
        return web.json_response(
            {"error": "png must be a base64 PNG data URL"}, status=400)
    if not png_bytes:
        return web.json_response({"error": "png is empty"}, status=400)
    regions = body.get("regions")
    if not isinstance(regions, list):
        return web.json_response({"error": "regions must be a list"}, status=400)

    out_dir = _template_dir()
    if out_dir is None:
        return web.json_response(
            {"error": "output directory unavailable"}, status=500)
    sidecar = {
        "size": body.get("size"),
        "spriteCount": len(regions),
        "regions": regions,
        "settings": body.get("settings"),
        "scenePrompt": body.get("scenePrompt"),
    }
    try:
        rel = write_template(out_dir, name, png_bytes, sidecar)
    except OSError as e:
        return web.json_response({"error": f"could not write template: {e}"},
                                 status=400)
    register_root(out_dir)
    return web.json_response({"ok": True, "file": rel, "name": slug})


@PromptServer.instance.routes.get("/symbiotica/template-list")
async def template_list(request):
    return web.json_response({"templates": list_templates(_template_dir())})


@PromptServer.instance.routes.post("/symbiotica/template-delete")
async def template_delete(request):
    """Delete a saved template — its PNG + JSON sidecar — from output/templates,
    so the editor's grid can prune duplicates and bad sheets. basename-guarded to
    that dir (no traversal). Missing files are a no-op, not an error."""
    out_dir = _template_dir()
    if out_dir is None:
        return web.json_response({"error": "output dir unavailable"}, status=500)
    try:
        body = await request.json()
    except Exception:
        body = {}
    stem = os.path.splitext(os.path.basename(str(body.get("file") or "")))[0]
    if not stem:
        return web.json_response({"error": "file required"}, status=400)
    root = os.path.realpath(out_dir)
    removed = []
    for ext in (".png", ".json"):
        path = os.path.realpath(os.path.join(root, stem + ext))
        if (path == root or path.startswith(root + os.sep)) and os.path.isfile(path):
            try:
                os.remove(path)
                removed.append(os.path.basename(path))
            except OSError:
                pass
    return web.json_response({"ok": True, "removed": removed})


@PromptServer.instance.routes.get("/symbiotica/template-image")
async def template_image(request):
    """Serve a saved template PNG from output/templates by its rel key
    ("templates/<slug>.png" or "<slug>.png"). A local /symbiotica route on
    purpose: the editor's own thumbnails must be served from the editor's disk.
    ComfyUI's /view?type=output would work standalone, but behind the Modal
    canvas proxy that path is routed to the GPU render sandbox (stubbed empty
    while idle), which blanks the saved-sheet grid."""
    out_dir = _template_dir()
    if out_dir is None:
        return web.json_response({"error": "output dir unavailable"}, status=500)
    # basename drops any "templates/" prefix and defeats "../" traversal — only
    # a file directly under output/templates can be reached.
    name = os.path.basename(request.query.get("file", ""))
    if os.path.splitext(name)[1].lower() not in ALLOWED_EXTS:
        return web.json_response({"error": "not an image"}, status=403)
    root = os.path.realpath(out_dir)
    path = os.path.realpath(os.path.join(root, name))
    if not (path == root or path.startswith(root + os.sep)) or not os.path.isfile(path):
        return web.json_response({"error": "not found"}, status=404)
    return web.FileResponse(path, headers={"Cache-Control": "private, max-age=60"})
