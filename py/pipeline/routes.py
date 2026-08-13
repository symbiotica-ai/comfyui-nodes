# ABOUTME: aiohttp routes for the order pipeline — serves local ref-image
# ABOUTME: thumbnails, folder browsing, and project-asset listings.
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import threading

from aiohttp import web
from server import PromptServer

from . import studio_library as studio_library_mod
from .compose import scan_images
from .order_sheet import slugify
from .paths import parse_roots, resolve_within
from .prompt_book import (MissingPromptsError, compose_detail, list_versions,
                          parse_recipe)
from .prompt_store import (PromptPathError, delete_recipe, list_book,
                           read_block, recipes, write_block, write_recipe)
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
# A strict subset of `_roots`: the folders that hold SOURCE artwork — a month's
# client references, a sprite catalog. Every root is servable; only these are
# things a node's output can go stale against, and a change-check must watch
# nothing else. The pipeline writes into plenty of servable folders (a picker's
# thumbnail buffer, a template save destination), and watching those made every
# write look like a new reference. See `reference_roots`.
_refs_roots: set[str] = set()
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


def register_refs_root(path: str) -> None:
    """Serve this folder AND watch it: it holds reference artwork a node reads.
    Only for folders whose contents are input to the graph — never a folder the
    graph writes into."""
    real = os.path.realpath(path)
    if os.path.isdir(real):
        with _lock:
            _roots.add(real)
            _refs_roots.add(real)


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
    """Every folder this process has made servable — registered by a node's
    execution or by a browse route. Access, not provenance: see
    `reference_roots` for the ones a change-check may watch."""
    with _lock:
        return sorted(_roots)


def reference_roots() -> list[str]:
    """The registered folders that hold reference artwork, same purpose and
    same caveat as `executed_projects` — a reference folder reaches the graph on
    a wire, so a change-check cannot see it either.

    Sorted so a hash built from this is stable across calls."""
    with _lock:
        return sorted(_refs_roots)


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


@PromptServer.instance.routes.get("/symbiotica/prompt-compose")
async def prompt_compose(request):
    """One asset type's prompt as the LLM will receive it, plus its blocks.

    Read-only on purpose: this is the answer to "did my edit reach the model",
    and the panel that shows it must not be able to save a composed document
    back over the blocks it was assembled from.
    """
    project = _expand_project(request.query.get("project", ""))
    if not project:
        return web.json_response({"error": "project required"}, status=400)
    try:
        # `recipe` pins versions per block ({name: version} JSON, or
        # `block = version` lines) — the Recipe panel previews exactly what
        # its widget picks will compose. Absent, the top versions compose,
        # which is the book as it stands.
        detail = compose_detail(project, request.query.get("category", ""),
                                parse_recipe(request.query.get("recipe", "")))
    except (MissingPromptsError, ValueError) as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"ok": True, **detail})


@PromptServer.instance.routes.get("/symbiotica/prompt-versions")
async def prompt_versions(request):
    """Every block's version names, in composition order — what the Recipe
    panel needs to map its six slots onto the book's files."""
    project = _expand_project(request.query.get("project", ""))
    if not project:
        return web.json_response({"error": "project required"}, status=400)
    return web.json_response({"ok": True, "blocks": list_versions(project)})


@PromptServer.instance.routes.get("/symbiotica/layouts")
async def layouts_list(request):
    """The layout images a project holds — what the Grid Layout node's picker
    offers beside "(follow category)"."""
    from .layouts import list_layouts

    project = _expand_project(request.query.get("project", ""))
    if not project:
        return web.json_response({"error": "project required"}, status=400)
    return web.json_response({"ok": True, "layouts": list_layouts(project)})


@PromptServer.instance.routes.get("/symbiotica/recipe-list")
async def recipe_list(request):
    """Every saved recipe with its slots — one request fills the panel's
    picker AND its dropdowns, because a picker that needs a read per entry
    flickers through the whole list on open."""
    project = _expand_project(request.query.get("project", ""))
    if not project:
        return web.json_response({"error": "project required"}, status=400)
    return web.json_response({"ok": True, "recipes": recipes(project)})


@PromptServer.instance.routes.post("/symbiotica/recipe-write")
async def recipe_write(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    project = _expand_project(str(body.get("project") or ""))
    try:
        saved = write_recipe(project, str(body.get("name") or ""),
                             body.get("slots") or [])
    except PromptPathError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except OSError as exc:
        return web.json_response({"error": f"cannot save: {exc}"}, status=500)
    return web.json_response({"ok": True, **saved})


@PromptServer.instance.routes.post("/symbiotica/recipe-delete")
async def recipe_delete(request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    project = _expand_project(str(body.get("project") or ""))
    try:
        gone = delete_recipe(project, str(body.get("name") or ""))
    except PromptPathError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"ok": True, **gone})


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


def _pick_target(node_id: str, folder: str = "") -> tuple[str, object, object]:
    """The asset path a Pick node's panel should list, resolved server-side.

    Without an explicit folder this is whatever the node itself resolved when
    it last ran, from the asset and category on its wires — the panel cannot
    work that out, because a wired input has no value on the canvas.

    An explicitly named folder is checked against the declared roots like every
    other path a request names: naming a folder is not what grants access to
    it. A save node's own prefix is accepted too, since that is the string
    people have to hand — `…/Food - 3 stages/Spookies` names the `Spookies_*`
    files one level up rather than a directory.
    """
    from .pick_folder import resolved

    named = str(folder or "").strip()
    if not named:
        return resolved(node_id)
    # Browsing by name is browsing a whole folder; a shortlist belongs to the
    # picker that made it, not to a path someone typed.
    if not os.path.isabs(named):
        try:
            import folder_paths
            named = os.path.normpath(
                os.path.join(folder_paths.get_output_directory(), named))
        except Exception:
            pass
    named = _expand_project(named)
    real = resolve_within(declared_roots(), named, kind="dir")
    if real is not None:
        return real, None, None
    parent = resolve_within(declared_roots(), os.path.dirname(named),
                            kind="dir")
    return (os.path.join(parent, os.path.basename(named)), None, None) if parent \
        else ("", None, None)


@PromptServer.instance.routes.get("/symbiotica/pick-list")
async def pick_list(request):
    """The images in the folder a Pick node is looking at, numbered.

    No buffer, no copies: this lists the renders where the save node put them,
    which is why a picker shows a new generation the moment it is queued and
    why looking at one costs nothing.
    """
    from .pick_folder import (LISTING_LIMIT, listing_for, read_folders,
                              subfolders_in, under)

    named = str(request.query.get("folder", "") or "").strip()
    root, only, derived = _pick_target(request.query.get("node_id", ""), named)
    # Where the panel's breadcrumb is standing, as a path under the folder the
    # run resolved. Applied here rather than at the node so a click walks the
    # tree without a re-queue; `under` refuses anything that leaves the root.
    crumb = str(request.query.get("subfolder", "") or "").strip().strip("/")
    target = under(root, crumb)
    if target == root:
        crumb = ""
    if not target:
        # A folder that was asked for by name and could not be resolved is a
        # refusal and has to say so. Silence is only right for a picker that
        # has not run yet, which is every picker on a freshly opened graph.
        if named:
            return web.json_response(
                {"error": f"{named} is not inside a folder this install serves"},
                status=403)
        return web.json_response({"ok": True, "images": [], "folder": ""})
    # `is_allowed` consults only the folders an execution or a browse route
    # registered, never `declared_roots()`, so listing without this hands back
    # paths whose every thumbnail then 403s — a grid of broken images with the
    # right count. `register_root_within` refuses anything outside a declared
    # root, so this grants nothing that was not already entitled.
    allowed = [folder for folder, _ in read_folders(target)
               if register_root_within(folder)]
    if not allowed:
        # A stage folder before its first save has nothing to read and nothing
        # to register — which is not a refusal. Check the nearest directory
        # that DOES exist above it: entitlement is a question about the tree,
        # not about whether the leaf has been created yet. Refusing here told
        # the user their own asset folder "is not inside a folder this install
        # serves", which is both alarming and untrue.
        probe = target
        while probe and not os.path.isdir(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        if not (probe and register_root_within(probe)):
            return web.json_response(
                {"error": f"{target} is not inside a folder this install serves"},
                status=403)
        return web.json_response({"ok": True, "folder": target, "images": [],
                                  "root": root, "subfolder": crumb,
                                  "folders": subfolders_in(target),
                                  "shortlist": only is not None})
    entries = await asyncio.to_thread(listing_for, target, LISTING_LIMIT, only,
                                      derived)
    return web.json_response({
        "ok": True, "folder": target, "shortlist": only is not None,
        # What the breadcrumb draws: where the root is, which step of it this
        # listing is, and the folders one click further down.
        "root": root, "subfolder": crumb,
        "folders": subfolders_in(target),
        "images": [{"id": e["id"], "name": e["name"], "index": e["index"],
                    "path": e["path"], "w": e["w"], "h": e["h"],
                    "at": e["at"]} for e in entries],
    })


@PromptServer.instance.routes.post("/symbiotica/pick-discard")
async def pick_discard(request):
    """Take ticked files out of a picker's grid, without taking them off disk.

    "we need a way to delete some of the generations that are not good" — and
    a picker that could delete would be a node able to destroy the work it
    exists to choose between, several images of which cost real money and
    cannot be regenerated. So this MOVES them into `discarded/` under the same
    folder: gone from every listing, one drag from coming back.

    Scoped like the listing itself — a name is only accepted if it is one the
    node actually shows, so a request can no more discard by path than it can
    read by path.
    """
    from .pick_folder import discard, read_folders, under

    try:
        body = await request.json()
    except Exception:
        body = {}
    names = [str(n) for n in (body.get("names") or [])]
    root, _only, _derived = _pick_target(str(body.get("node_id") or ""),
                                 str(body.get("folder") or ""))
    # Discard what the grid IS SHOWING. A picker navigated into a sub-folder
    # lists names relative to that step, and matching them against the root's
    # listing would silently discard nothing.
    target = under(root, str(body.get("subfolder") or "").strip().strip("/"))
    if not target:
        return web.json_response(
            {"error": "queue this picker once before discarding from it"},
            status=409)
    if not names:
        return web.json_response({"ok": True, "discarded": []})
    if not register_root_within(target) and not any(
            register_root_within(folder)
            for folder, _ in read_folders(target)):
        return web.json_response(
            {"error": f"{target} is not inside a folder this install serves"},
            status=403)
    moved = await asyncio.to_thread(discard, target, names)
    return web.json_response({"ok": True,
                              "discarded": [os.path.basename(p) for p in moved]})


@PromptServer.instance.routes.post("/symbiotica/tracker-reject")
async def tracker_reject(request):
    """Send one asset's approved render back for another try.

    The board's slot is filled by a `_final` in that asset's folder, so
    rejecting is that file leaving the listing — the same move `pick-discard`
    makes, into `discarded/` under the same folder rather than off the disk.
    Several of these cost real money and the node exists to judge them.

    Scoped by the folder the file is IN, checked against the declared roots
    like every other path a request names, and the name is only accepted if it
    is one that folder actually lists.
    """
    from .pick_folder import discard

    try:
        body = await request.json()
    except Exception:
        body = {}
    path = str(body.get("path") or "").strip()
    if not path:
        return web.json_response({"error": "path required"}, status=400)
    folder, name = os.path.dirname(path), os.path.basename(path)
    if not register_root_within(folder):
        return web.json_response(
            {"error": f"{folder} is not inside a folder this install serves"},
            status=403)
    moved = await asyncio.to_thread(discard, folder, [name])
    if not moved:
        return web.json_response(
            {"error": f"{name} is not listed in that folder"}, status=404)
    return web.json_response({"ok": True,
                              "moved": [os.path.basename(p) for p in moved]})


@PromptServer.instance.routes.get("/symbiotica/pick-thumb")
async def pick_thumb(request):
    """One listed image, shrunk to grid size, never written to disk.

    The node draws every image in a folder at once, and serving full-size
    renders into a strip of 128px tiles makes it feel broken. Resizing per
    request rather than keeping a thumbnail folder is the whole point of this
    node holding nothing: the browser caches the result, so the work happens
    once per image per session and leaves nothing behind.
    """
    from PIL import Image, UnidentifiedImageError

    resolved_path = is_allowed(request.query.get("path", ""))
    if resolved_path is None:
        return web.json_response({"error": "not an allowed image path"},
                                 status=403)
    try:
        px = max(32, min(1024, int(request.query.get("px", "320"))))
    except ValueError:
        px = 320

    def _shrink():
        buffer = io.BytesIO()
        with Image.open(resolved_path) as img:
            img.load()
            # Alpha survives: a background-removed render judged on a black
            # rectangle is not the image that was approved.
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "transparency" in img.info
                                  else "RGB")
            img.thumbnail((px, px))
            img.save(buffer, format="PNG")
        return buffer.getvalue()

    try:
        body = await asyncio.to_thread(_shrink)
    except (OSError, UnidentifiedImageError, ValueError):
        return web.json_response({"error": "could not read that image"},
                                 status=400)
    return web.Response(body=body, content_type="image/png",
                        headers={"Cache-Control": "private, max-age=600"})
