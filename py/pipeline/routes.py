# ABOUTME: aiohttp routes for the order pipeline — serves local ref-image
# ABOUTME: thumbnails, folder browsing, and project-asset listings.
from __future__ import annotations

import asyncio
import base64
import json
import os
import threading

from aiohttp import web
from server import PromptServer

from . import studio_library as studio_library_mod
from .compose import scan_images
from .order_sheet import slugify
from .paths import parse_roots, resolve_within
from .prompt_store import (PromptPathError, list_book, read_block,
                           write_block)
from .pack_library import (
    KINDS,
    delete_pack_template_dirs,
    list_pack_templates_dirs,
    pack_dirs,
    qualified_name,
    save_dirs,
    split_qualified,
)

ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

_roots: set[str] = set()
_projects: set[str] = set()
_lock = threading.Lock()


ASSET_ROOTS_ENV = "SYMBIOTICA_ASSET_ROOTS"


def register_root(path: str) -> None:
    """Allow serving images under this folder (called when an Order Read node
    executes with it — i.e. the user explicitly typed it into the graph)."""
    real = os.path.realpath(path)
    if os.path.isdir(real):
        with _lock:
            _roots.add(real)


def _operator_roots() -> list[str]:
    """Extra asset folders the operator declared, from the Settings UI or the
    environment. This is how someone whose artwork lives outside ComfyUI's own
    folders keeps browsing it — they name the folder once instead of every
    request naming its own."""
    try:
        from .._settings import get_comfy_setting, setting_key
        declared = get_comfy_setting(setting_key(ASSET_ROOTS_ENV))
    except Exception:
        declared = None
    return parse_roots(declared) + parse_roots(os.environ.get(ASSET_ROOTS_ENV))


def declared_roots() -> list[str]:
    """The folders a request may point at: the studio-assets Volume, ComfyUI's
    own directories, whatever the operator declared, and whatever a graph
    execution registered. Never anything a request named for itself."""
    roots = [studio_library_mod.STUDIO_ASSETS_DIR, _template_dir()]
    try:
        import folder_paths
        roots += [folder_paths.get_input_directory(),
                  folder_paths.get_output_directory()]
    except Exception:
        pass
    roots += _operator_roots()
    with _lock:
        roots.extend(_roots)
        roots.extend(_projects)
    return [r for r in roots if r]


def executed_projects() -> list[str]:
    """The project folders graph executions have used, most useful to a node
    that must look one up when its own `project_path` widget is empty.

    ComfyUI calls a node's change-check BEFORE the upstream outputs exist, so a
    linked input reads as unset there — a node whose project arrives on the
    ORDER wire has no other way to find it. Sorted so a hash built from this is
    stable across calls, and copied under the lock so a caller can iterate it
    while another execution registers one.
    """
    with _lock:
        return sorted(_projects)


def executed_roots() -> list[str]:
    """The folders graph executions have registered, same purpose and same
    caveat as `executed_projects` — a reference folder reaches the graph on a
    wire, so a change-check cannot see it either."""
    with _lock:
        return sorted(_roots)


def register_root_within(path: str) -> bool:
    """Register `path` only when it lies inside a declared root, and report
    whether it was. The browse routes call this: a request may make a folder
    servable, but only one it was already entitled to see — otherwise asking to
    browse a folder is what grants access to it."""
    if not path:
        return False
    real = resolve_within(declared_roots(), path, kind="dir")
    if real is None:
        return False
    with _lock:
        _roots.add(real)
    return True


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


def _expand_project(value: str) -> str:
    """A volume-relative studios/<slug>/... project string (the Studio Library
    node's wire currency) becomes its absolute path under the studio-assets
    Volume; anything else passes through for the route's own checks."""
    return studio_library_mod.expand_studio_path(
        studio_library_mod.STUDIO_ASSETS_DIR, value)


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


@PromptServer.instance.routes.get("/symbiotica/browse-refs")
async def browse_refs(request):
    """One level of the Reference Browser's tree: folders + images (with pixel
    sizes) directly under root/dir. The user wired the root into the node, so
    that IS the intent — register it for thumbnail serving, like list-assets."""
    from .reference_browser import list_level

    root = _expand_project(request.query.get("root", ""))
    result = list_level(root, request.query.get("dir", ""))
    if "error" in result:
        return web.json_response(result, status=400)
    if not register_root_within(result["root"]):
        return web.json_response({"error": "folder is outside every allowed root"},
                                 status=403)
    return web.json_response(result)


@PromptServer.instance.routes.get("/symbiotica/list-orders")
async def list_orders(request):
    """The months available under a project folder's orders/ subdir, for the
    Order Read node's month picker."""
    from .project_layout import list_order_months

    project = _expand_project(request.query.get("project", ""))
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
    project = _expand_project(request.query.get("project", ""))
    month = request.query.get("month", "").strip()
    assets_root = ""
    if project:
        r = resolve_month(project, month)
        order_path = order_path or r["order_path"]
        refs_path = refs_path or r["refs_path"]
        assets_root = r["assets_root"]
    if not order_path:
        return web.json_response({"error": "order_path required"}, status=400)
    roots = declared_roots()
    if resolve_within(roots, order_path, kind="file") is None:
        return web.json_response({"error": "order path is outside every allowed root"},
                                 status=403)
    if refs_path and resolve_within(roots, refs_path, kind="dir") is None:
        return web.json_response({"error": "refs path is outside every allowed root"},
                                 status=403)
    try:
        loaded = load_order(order_path, refs_path)
    except ValueError as e:
        return web.json_response({"error": str(e)}, status=400)
    if refs_path:
        register_root_within(refs_path)
    if assets_root:
        register_root_within(assets_root)
    loaded["refsRoot"] = refs_path
    loaded["assetsRoot"] = assets_root
    return web.json_response(loaded)


@PromptServer.instance.routes.get("/symbiotica/list-assets")
async def list_assets(request):
    """Recursive image listing of a user-picked project folder. Picking the
    folder in the browser IS the user intent, so the root is registered for
    thumbnail serving via /symbiotica/local-image."""
    root = os.path.realpath(_expand_project(request.query.get("dir", "")))
    if not root or not os.path.isdir(root):
        return web.json_response({"error": "not a readable directory"}, status=400)
    if not register_root_within(root):
        return web.json_response({"error": "folder is outside every allowed root"},
                                 status=403)
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


SYNC_TIMEOUT_S = 10  # best-effort browse sync; time out and list the stale mount.


async def _sync_studio_assets(root):
    """Best-effort async publish/refresh of the studio-assets v2 mount before a
    browse-session listing. Never blocks the event loop; a stale listing is
    acceptable. Mirrors services/comfy-modal/symbiotica_platform/route.py.

    Returns "refreshed", "timeout" or "failed". A caller that discarded this
    could not tell a folder that is absent from one it never went to look for —
    the two produce the same listing, and only one of them is the studio's
    actual contents."""
    try:
        proc = await asyncio.create_subprocess_exec("sync", root)
    except OSError as exc:
        print(f"[symbiotica] studio-assets sync could not start: {exc}")
        return "failed"
    try:
        code = await asyncio.wait_for(proc.wait(), timeout=SYNC_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        print(f"[symbiotica] studio-assets sync exceeded {SYNC_TIMEOUT_S}s; "
              "listing the mount as it stands")
        return "timeout"
    if code != 0:
        print(f"[symbiotica] studio-assets sync exited {code}; "
              "listing the mount as it stands")
        return "failed"
    return "refreshed"


_SYNCS: dict[str, asyncio.Task] = {}


async def _coalesced_sync(root):
    """The outcome of one `sync` walk per mount at a time: a browse arriving
    while one is in flight awaits that one instead of starting a second. Safe
    because the walk is idempotent, so the shared answer is the answer the
    second caller would have computed — and necessary because the control that
    triggers it is a button that can be held down, and each walk is a FUSE
    traversal lasting up to the whole timeout. A finished walk is never reused:
    a browse after somebody else's upload needs one that could see it.

    Shielded, so a browser that navigates away mid-walk leaves the walk — and
    everyone waiting on it — running. Mirrors the hub's _coalesced."""
    task = _SYNCS.get(root)
    if task is None or task.done():
        task = asyncio.create_task(_sync_studio_assets(root))
        _SYNCS[root] = task
    return await asyncio.shield(task)


@PromptServer.instance.routes.get("/symbiotica/studio-library")
async def studio_library(request):
    """Lazy per-level listing of the active studio's asset tree, confined to the
    studio-assets Volume root. `dir` is a volume-relative rel studios/<slug>[/...]
    (or '' for the studio root). A browse-session open (sync=1) refreshes first."""
    studio = (os.environ.get("CANVAS_STUDIO") or "").strip()
    if not studio:
        return web.json_response({"error": "studio library not available"}, status=503)
    outcome = None
    if request.query.get("sync") == "1":
        outcome = await _coalesced_sync(studio_library_mod.STUDIO_ASSETS_DIR)
    result = studio_library_mod.list_studio_dir(
        studio_library_mod.STUDIO_ASSETS_DIR, studio, request.query.get("dir", ""),
        show_model_kinds=request.query.get("models") == "1")
    # What the walk did rides along with whatever the listing turned out to be:
    # the two succeed or fail independently, and the folder a caller asked for
    # can be gone precisely BECAUSE their view of the volume was stale. Reported
    # on the refused listing too, and reported on success — silence there would
    # be indistinguishable from a request that never asked, leaving a caller
    # showing a staleness warning no way to learn the volume is current again.
    # A degraded walk does not refuse the listing: the stale mount is still the
    # best answer available, and withholding it would cost a browse over a
    # folder that is probably right anyway.
    if outcome:
        result["sync"] = outcome
    return web.json_response(result, status=400 if "error" in result else 200)


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


def _kind(value: str) -> str:
    """A request's kind param as a pool id: "order"/"reference", or "" for every
    pool (what the UI's "All" sends)."""
    k = str(value or "").strip().lower()
    return k if k in KINDS else ""


def register_project(path: str) -> None:
    """Remember a project folder a graph execution used. Running a node with a
    project IS the user naming it, and it is the only way the pack learns about
    one: every other root it registers is a folder BENEATH the project, and a
    root cannot vouch for its own parent — trusting an ancestor would hand the
    home directory, or /, to routes that delete."""
    # Absolute only, and checked BEFORE resolving: realpath("") is the process
    # working directory, so an empty project widget — the default, and the case
    # that goes on to raise — would otherwise trust ComfyUI's own folder.
    if not path or not isinstance(path, str) or not os.path.isabs(path):
        return
    try:
        real = os.path.realpath(path)
    except (ValueError, OSError):
        return
    if os.path.isdir(real):
        with _lock:
            _projects.add(real)


def _allowed_project(project: str) -> str | None:
    """The RESOLVED project a caller may browse or delete from, or None.

    It qualifies when it resolves inside a declared root, or when a graph
    execution used it. The resolved path is returned rather than a yes/no,
    because the caller must go on to use exactly that path: resolving the
    caller's string a second time would reopen the check-then-use race the
    resolution closes."""
    if not project:
        return None
    real = resolve_within(declared_roots(), project, kind="dir")
    if real:
        return real
    try:
        real = os.path.realpath(project)
        with _lock:
            known = frozenset(_projects)
        return real if real in known else None
    except (ValueError, OSError):
        return None


def _pack_dirs(project: str, kind: str = "", month: str = "") -> list[str]:
    """Where Auto Packer templates of this kind live: the project's folders for
    that pool AND the matching output/templates fallback (used when the project
    is read-only or absent). Project first so a filed template shadows a
    fallback of the same name; kind "" adds the legacy flat pools too.

    A project the caller is not entitled to is dropped rather than browsed —
    these folders are handed to a recursive delete, so an unconfined project
    string would reach any tree on the host.
    """
    return pack_dirs(_allowed_project(project) or "", _kind(kind), month,
                     _template_dir() or "")


def pack_dirs_for_project(value: str, kind: str = "", month: str = "") -> list[str]:
    """_pack_dirs for a project as it arrives on the wire — a volume-relative
    studios/<slug>/... string or an absolute path. Both the list and the delete
    route resolve through here so they can never disagree about what a project
    means."""
    return _pack_dirs(_expand_project(value), kind, month)


@PromptServer.instance.routes.get("/symbiotica/pack-template-list")
async def pack_template_list(request):
    """The saved Auto Packer templates for a project, in one pool — reference
    (universal), order (one month), or all — plus the output/templates fallback.
    Registers every browsed dir so /symbiotica/local-image can serve each
    template's sheet thumbnails (abs sheetPaths ride along)."""
    project = _expand_project(request.query.get("project", ""))
    kind = _kind(request.query.get("kind", ""))
    month = request.query.get("month", "")
    dirs = _pack_dirs(project, kind, month)
    for d in dirs:
        register_root_within(d)
    # `dir` is what a save of this kind would write to — the crumb the browser
    # shows. With no kind picked, the order pool is the representative one.
    saves = save_dirs(_allowed_project(project) or "", kind or "order", month,
                      _template_dir() or "")
    return web.json_response({"dir": saves[0] if saves else "",
                              "dirs": dirs, "kind": kind,
                              "templates": list_pack_templates_dirs(dirs)})


@PromptServer.instance.routes.post("/symbiotica/pack-template-delete")
async def pack_template_delete(request):
    """Delete one saved Auto Packer template folder from wherever it lives
    (project pool or output/templates). A kind-qualified name ("order/mini-1")
    only deletes that pool's copy. basename/realpath-guarded; missing is a
    no-op, not an error."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    # Search EVERY pool (kind ""), not the request's: a template saved before
    # the split lives in the legacy flat <project>/templates, which pack_dirs
    # only returns for kind "" — and the browser always sends a concrete kind
    # (the list route infers one for legacy sidecars), so narrowing here made
    # those rows undeletable. The pool-qualified name is what keeps the delete
    # inside one pool: delete_pack_template_dirs skips a folder whose template
    # is another kind.
    #
    # Same expansion as the list route: the Library sends whatever its
    # project_path resolves to, which on Modal is the volume-relative
    # studios/<slug>/… form — unexpanded it points at no pool at all and the
    # delete silently removes nothing.
    name = str(body.get("name") or "")
    kind = _kind(str(body.get("kind") or ""))
    if kind and not split_qualified(name)[0]:
        name = qualified_name(kind, name)   # an older client sent a bare slug
    dirs = _pack_dirs(_expand_project(str(body.get("project") or "")), "",
                      str(body.get("month") or ""))
    removed = delete_pack_template_dirs(dirs, name)
    return web.json_response({"ok": True, "removed": removed})


@PromptServer.instance.routes.get("/symbiotica/prompt-book")
async def prompt_book(request):
    """The project's editable blocks: shared rules first, then type blocks.

    Same project expansion as the template routes — the node sends whatever its
    project_path resolves to, which on Modal is the volume-relative
    studios/<slug>/… form and points at no book at all unexpanded.
    """
    project = _expand_project(request.query.get("project", ""))
    if not project:
        return web.json_response({"error": "project required"}, status=400)
    return web.json_response({"ok": True, **list_book(project)})


@PromptServer.instance.routes.get("/symbiotica/prompt-read")
async def prompt_read(request):
    project = _expand_project(request.query.get("project", ""))
    try:
        text = read_block(project, request.query.get("name", ""))
    except PromptPathError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"ok": True, "text": text})


@PromptServer.instance.routes.post("/symbiotica/prompt-write")
async def prompt_write(request):
    """Save one block. A .bak of what it replaced sits beside it — an editor
    that can silently lose a tuned 6k-character rule is not one to trust."""
    try:
        body = await request.json()
    except Exception:
        body = {}
    project = _expand_project(str(body.get("project") or ""))
    try:
        saved = write_block(project, str(body.get("name") or ""),
                            body.get("text"))
    except PromptPathError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except OSError as exc:
        return web.json_response({"error": f"cannot save: {exc}"}, status=500)
    return web.json_response({"ok": True, **saved})


def _pick_dir(node_id: str) -> str:
    """One Pick node's buffer, derived server-side from its node id.

    The caller names a node, never a path: the id is reduced to a bare
    directory segment and joined onto ComfyUI's own output directory here, so
    there is no traversal to defend against further down. Requests that arrive
    before folder_paths is importable get no buffer rather than a stack trace.

    A blank id has no buffer. It must not fall through to the one the node
    itself uses when it runs without an id: a clear request that simply forgot
    to name a node would then delete a real node's candidates.
    """
    from .pick_buffer import buffer_dir
    if not str(node_id or "").strip():
        return ""
    try:
        import folder_paths
        base = folder_paths.get_output_directory()
    except Exception:
        return ""
    return buffer_dir(base, node_id)


@PromptServer.instance.routes.get("/symbiotica/pick-list")
async def pick_list(request):
    """The candidates a Pick node is holding, with the tags they were recorded
    under and the distinct groups those tags form — the node's filter bar."""
    from .pick_buffer import groups, list_entries

    dir_path = _pick_dir(request.query.get("node_id", ""))
    if not dir_path:
        return web.json_response({"ok": True, "images": [], "groups": []})
    # Make this one buffer servable. `is_allowed` consults only the folders an
    # execution registered, never `declared_roots()`, so listing candidates
    # without this hands back paths whose every thumbnail then 403s — the node
    # draws a grid of broken images while reporting the right count.
    # Narrower than the output directory it sits under (already a declared
    # root), and the path is derived from the node id here rather than sent by
    # the caller, so registering it grants nothing that was not already
    # entitled: `register_root_within` refuses anything outside a declared root.
    register_root_within(dir_path)
    entries = list_entries(dir_path)
    return web.json_response({
        "ok": True,
        "images": [{
            "id": e.get("id", ""), "path": e.get("path", ""),
            "thumb": e.get("thumb_path", ""), "group": e.get("group", ""),
            "role": e.get("role", ""), "phase": e.get("phase", ""),
            "asset": e.get("asset", ""), "category": e.get("category", ""),
            "feature": e.get("feature", ""), "month": e.get("month", ""),
            "w": e.get("w", 0), "h": e.get("h", 0), "at": e.get("at", ""),
        } for e in entries],
        "groups": groups(entries),
    })


@PromptServer.instance.routes.post("/symbiotica/pick-clear")
async def pick_clear(request):
    """Drop named candidates, or the whole buffer when no ids are given.

    Deleting is deliberate here rather than a "hidden" flag: the buffer is
    full-size PNGs of every render that was ever looked at, and a triage tool
    that only ever grows fills the output volume.
    """
    from .pick_buffer import clear, drop

    try:
        body = await request.json()
    except Exception:
        body = {}
    dir_path = _pick_dir(str(body.get("node_id") or ""))
    if not dir_path:
        return web.json_response({"error": "no buffer for that node"},
                                 status=400)
    ids = body.get("ids")
    if isinstance(ids, list) and ids:
        return web.json_response({"ok": True, "removed": drop(dir_path, ids)})
    clear(dir_path)
    return web.json_response({"ok": True, "removed": "all"})


@PromptServer.instance.routes.post("/symbiotica/pick-import")
async def pick_import(request):
    """File the images already sitting in a folder as one picker's candidates.

    The buffer is per node, so a picker added after the work was generated
    starts empty — and re-running the generator to fill it pays for renders
    that already exist. The folder is checked against the declared roots like
    every other path a request names; naming a folder is not what grants access
    to it.
    """
    from .pick_buffer import import_folder

    try:
        body = await request.json()
    except Exception:
        body = {}
    dir_path = _pick_dir(str(body.get("node_id") or ""))
    if not dir_path:
        return web.json_response({"error": "no buffer for that node"}, status=400)

    folder = _expand_project(str(body.get("folder") or "").strip())
    if not folder:
        return web.json_response(
            {"error": "type a folder into the node's `folder` field first"},
            status=400)
    real = resolve_within(declared_roots(), folder, kind="dir")
    if real is None:
        return web.json_response(
            {"error": f"{folder} is not inside a folder this install serves"},
            status=403)

    # The wired asset name is not readable from the canvas — a wired input has
    # no widget value — and it does not need to be: renders are filed
    # `outputs/<month>/<event>/<category>/<recipe>/…`, so the path states it.
    # Anything typed on the node still overrides what the path says.
    tag = {"asset": str(body.get("asset") or "").strip(),
           "category": str(body.get("category") or "").strip(),
           "role": str(body.get("role") or "").strip()}
    # A picker pinned to a pass reads only that pass, and stamps it on what it
    # reads — so a folder that has no `export` level still lands correctly
    # tagged in the Export picker.
    only_phase = str(body.get("phase") or "").strip()
    if only_phase:
        tag["phase"] = only_phase
    stamp = str(body.get("at") or "")
    # Off the event loop: a few hundred PNGs get opened and thumbnailed here,
    # and the canvas still needs to talk to the server while that runs.
    result = await asyncio.to_thread(import_folder, dir_path, real,
                                     tag=tag, at=stamp, only_phase=only_phase)
    register_root_within(dir_path)
    return web.json_response({"ok": True, "folder": real, **result})
