# ABOUTME: aiohttp routes for the order pipeline — serves local ref-image
# ABOUTME: thumbnails, folder browsing, and project-asset listings.
from __future__ import annotations

import asyncio
import io
import os
import threading

from aiohttp import web
from server import PromptServer

from . import studio_library as studio_library_mod
from .paths import parse_roots, resolve_within
from .prompt_store import (PromptPathError, list_files, list_folders,
                           make_folder, read_file, remove, rename, write_file)

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
    """Allow serving images under this folder (called when a node executes
    with it — i.e. the user explicitly typed it into the graph)."""
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


@PromptServer.instance.routes.get("/symbiotica/local-image")
async def local_image(request):
    """One image file, for a canvas preview of something outside ComfyUI's own
    directories — the studio-assets mount a Control Image node or a picker
    reads. Served only from a root something already registered: browsing a
    folder registers it, and so does a node that loaded a file from it.

    Deleted with the obsolete nodes in 0a4f14d while two panels were still
    calling it (`web/js/control_image.js`, `web/js/browser_chrome.js`), which
    is why every preview outside `input/` has been a 404 since.
    """
    resolved = is_allowed(request.query.get("path", ""))
    if resolved is None:
        return web.json_response({"error": "not an allowed image path"},
                                 status=403)
    return web.FileResponse(resolved,
                            headers={"Cache-Control": "private, max-age=60"})


def _image_library(*names):
    """Members of the control-image library module.

    The pack is imported as `<pack>.py.pipeline.routes` inside ComfyUI and as a
    top-level `pipeline` under the test harness, where `..` is above the root
    package. Same module either way — `py/` is on the path there.
    """
    try:
        from .. import _control_image as mod
    except ImportError:
        import _control_image as mod
    return [getattr(mod, name) for name in names]


@PromptServer.instance.routes.get("/symbiotica/control-images")
async def control_images(request):
    """Every image under the folder a Control Image node points at, relative to
    it, sub-folders included — what the node's dropdown offers.

    The folder is a widget, so the listing cannot be built when the node class
    is registered; the canvas asks here whenever the path changes.

    The path IS the answer: whatever the user typed into the node, or wired
    into it, is the folder that gets browsed — the same folder `load` would
    read from on a queue, and the same rule the Prompts node has always had.
    It registers on the way through, because the preview of each file goes
    back through `local-image`, so a browse grants exactly what queueing the
    node once already granted. Declaring the folder first was a step with
    nothing behind it: "this is an image browser mate".

    What still holds is CONTAINMENT — every name a request can send is
    resolved inside the folder it named, so nothing here reaches a file the
    node was not pointed at.
    """
    library_dir, list_control_images, list_control_folders = (
        _image_library("library_dir", "list_control_images",
                       "list_control_folders"))

    raw = request.query.get("path", "")
    try:
        library = library_dir(raw)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    register_root(library)
    return web.json_response({
        "ok": True,
        "library": library,
        "folders": list_control_folders(raw),
        "images": list_control_images(raw),
    })


def _image_folder(request_path):
    """The library a request names: the absolute path the node was pointed at.

    Every write below is confined to it — `inside_library` resolves each name
    against this folder and refuses anything that climbs out — so what a
    request can touch is decided by containment, not by an allowlist of
    folders declared somewhere else.
    """
    library_dir = _image_library("library_dir")[0]
    library = library_dir(request_path)
    register_root(library)
    return library


async def _image_op(request, run):
    """The shape every write to an image library shares: read the body, check
    the library, do the thing, and turn a refusal into the reason for it."""
    body = await _json_body(request)
    try:
        _image_folder(body.get("path"))
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    try:
        return web.json_response({"ok": True, **run(body)})
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except OSError as exc:
        return web.json_response({"error": str(exc)}, status=500)


@PromptServer.instance.routes.post("/symbiotica/control-images-mkdir")
async def control_images_mkdir(request):
    """Create a sub-folder in the image library."""
    make_folder = _image_library("make_folder")[0]
    return await _image_op(request, lambda b: make_folder(
        b.get("path"), str(b.get("name") or "")))


@PromptServer.instance.routes.post("/symbiotica/control-images-rename")
async def control_images_rename(request):
    """Rename an image, or a sub-folder and everything under it."""
    rename = _image_library("rename")[0]
    return await _image_op(request, lambda b: rename(
        b.get("path"), str(b.get("from") or ""), str(b.get("to") or "")))


@PromptServer.instance.routes.post("/symbiotica/control-images-delete")
async def control_images_delete(request):
    """Delete an image, or a sub-folder and everything in it. The panel asks
    first, naming what goes."""
    remove = _image_library("remove")[0]
    return await _image_op(request, lambda b: remove(
        b.get("path"), str(b.get("name") or "")))


@PromptServer.instance.routes.post("/symbiotica/control-images-upload")
async def control_images_upload(request):
    """Files dropped onto the tree, written into the folder they landed on.

    Multipart, one part per file, because that is what a browser hands over
    from a drop. Nothing is overwritten — a name already taken gets `-2`.
    """
    save_upload = _image_library("save_upload")[0]
    try:
        data = await request.post()
    except Exception as exc:
        return web.json_response({"error": f"unreadable upload: {exc}"},
                                 status=400)
    try:
        _image_folder(data.get("path"))
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    saved, refused = [], []
    for field in data.getall("files", []):
        name = getattr(field, "filename", "") or ""
        try:
            body = field.file.read()
        except Exception as exc:
            refused.append(f"{name}: {exc}")
            continue
        try:
            saved.append(save_upload(data.get("path"), data.get("folder", ""),
                                     name, body)["name"])
        except (ValueError, OSError) as exc:
            refused.append(str(exc))
    # A partial drop is not a failure: a folder of PNGs with a stray .txt in it
    # should land the PNGs and say what it left.
    return web.json_response({"ok": True, "saved": saved, "refused": refused})


@PromptServer.instance.routes.get("/symbiotica/list-orders")
async def list_orders(request):
    """The months available under a project folder's orders/ subdir, for the
    Asset Focus node's month picker."""
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
        # The folder he typed IS the project — the same act as queueing the
        # node, which until now was the only way one was ever learned. Without
        # this the panel cannot read its own tree before the graph has run
        # once, and `order_cache` keeps the 403 as a FINAL answer for the rest
        # of the session. What a request may touch is still CONTAINMENT: every
        # path below is derived from this folder by `resolve_month`, and an
        # `order_path` the request named for itself is checked against it and
        # refused when it climbs out.
        register_project(project)
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


def _prompt_folder(value) -> str:
    """The folder a Prompts panel names. Same expansion as the template routes:
    on Modal the wire carries the volume-relative studios/<slug>/… form, which
    points at no folder at all unexpanded."""
    return _expand_project(str(value or "").strip())


async def _json_body(request) -> dict:
    try:
        body = await request.json()
    except Exception:
        body = {}
    return body if isinstance(body, dict) else {}


def _sync_root(folder):
    """The mount to refresh for a folder: the studio-assets root when the
    folder is inside it, so a prompts browse and a Studio Library browse share
    the one coalesced walk, else the folder itself."""
    root = studio_library_mod.STUDIO_ASSETS_DIR
    try:
        real = os.path.realpath(folder)
        root_real = os.path.realpath(root)
    except (ValueError, OSError):
        return folder
    return root if real == root_real or real.startswith(root_real + os.sep) else folder


@PromptServer.instance.routes.get("/symbiotica/prompts-list")
async def prompts_list(request):
    """Every sub-folder and every prompt file under the path, relative to
    it, in one answer: the panel derives the folder dropdown and the file
    dropdown from it without a request per click.

    `sync=1` refreshes the mount first, the same walk a Studio Library browse
    makes: a file added from outside this sandbox — the platform's file
    manager — is not on the mount until something goes and looks, and the
    panel's "[no files in folder]" over a folder that HAS one is that."""
    folder = _prompt_folder(request.query.get("folder", ""))
    if not folder:
        return web.json_response({"error": "folder required"}, status=400)
    outcome = None
    if request.query.get("sync") == "1":
        outcome = await _coalesced_sync(_sync_root(folder))
    body = {"ok": True, "folders": list_folders(folder),
            "files": list_files(folder)}
    if outcome:
        body["sync"] = outcome
    return web.json_response(body)


@PromptServer.instance.routes.get("/symbiotica/prompts-read")
async def prompts_read(request):
    folder = _prompt_folder(request.query.get("folder", ""))
    try:
        text = read_file(folder, request.query.get("name", ""))
    except PromptPathError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    return web.json_response({"ok": True, "text": text})


@PromptServer.instance.routes.post("/symbiotica/prompts-write")
async def prompts_write(request):
    """Save one file. A .bak of what it replaced sits beside it — an editor
    that can silently lose a tuned 6k-character prompt is not one to trust."""
    body = await _json_body(request)
    folder = _prompt_folder(body.get("folder"))
    try:
        saved = write_file(folder, str(body.get("name") or ""),
                           body.get("text"))
    except PromptPathError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except OSError as exc:
        return web.json_response({"error": f"cannot save: {exc}"}, status=500)
    return web.json_response({"ok": True, **saved})


@PromptServer.instance.routes.post("/symbiotica/prompts-mkdir")
async def prompts_mkdir(request):
    """Create a sub-folder inside the prompt folder."""
    body = await _json_body(request)
    folder = _prompt_folder(body.get("folder"))
    try:
        made = make_folder(folder, str(body.get("name") or ""))
    except PromptPathError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except OSError as exc:
        return web.json_response({"error": f"cannot create: {exc}"},
                                 status=500)
    return web.json_response({"ok": True, **made})


@PromptServer.instance.routes.post("/symbiotica/prompts-rename")
async def prompts_rename(request):
    """Rename a file or a sub-folder inside the prompt folder."""
    body = await _json_body(request)
    folder = _prompt_folder(body.get("folder"))
    try:
        moved = rename(folder, str(body.get("from") or ""),
                       str(body.get("to") or ""))
    except PromptPathError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except OSError as exc:
        return web.json_response({"error": f"cannot rename: {exc}"},
                                 status=500)
    return web.json_response({"ok": True, **moved})


@PromptServer.instance.routes.post("/symbiotica/prompts-delete")
async def prompts_delete(request):
    """Delete a file, or a sub-folder and everything in it. The panel asks
    first, naming what goes."""
    body = await _json_body(request)
    folder = _prompt_folder(body.get("folder"))
    try:
        gone = remove(folder, str(body.get("name") or ""))
    except PromptPathError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except OSError as exc:
        return web.json_response({"error": f"cannot delete: {exc}"},
                                 status=500)
    return web.json_response({"ok": True, **gone})


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
