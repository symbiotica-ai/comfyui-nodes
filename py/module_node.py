# ABOUTME: Module node — the canvas control for linked subgraph modules — and
# ABOUTME: the routes behind it: list, read, publish and sync-all-workflows.
import os

from ._modules import (LIBRARY_DIRNAME, ModuleError, library_dir, list_modules,
                       load_library, read_module, sync_workflows, write_module)
PICK = "— pick a module —"


def _module_names():
    try:
        return [m["name"] for m in list_modules(library_dir())]
    except Exception:
        return []


class SymbioticaModule:
    """Frontend-only control: pick a published module to drop it on the canvas,
    publish the selected subgraph as a module, or sync every workflow file.
    Never executes — web/js/modules.js marks it virtual."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "module": ([PICK] + _module_names(), {
                    "tooltip": "Pick a published module to add it below this node.",
                }),
                "folder": ("STRING", {
                    "default": "",
                    "tooltip": "Project folder for new modules, e.g. bakery. "
                               "Type it or connect a text node.",
                }),
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "execute"
    CATEGORY = "Symbiotica/Modules"
    DESCRIPTION = ("Linked subgraph modules: publish a subgraph once, and every "
                   "workflow that uses it picks up the change.")

    def execute(self, module=PICK, folder=""):
        return ()


NODE_CLASS_MAPPINGS = {"SymbioticaModule": SymbioticaModule}
NODE_DISPLAY_NAME_MAPPINGS = {"SymbioticaModule": "Module"}


try:
    from aiohttp import web
    from server import PromptServer
except Exception:  # outside a running ComfyUI server (tests)
    PromptServer = None

if PromptServer is not None:
    routes = PromptServer.instance.routes

    def _workflows_dir():
        import folder_paths
        return os.path.join(folder_paths.get_user_directory(), "default", "workflows")

    @routes.get("/symbiotica/modules")
    async def modules_list(request):
        return web.json_response({"modules": list_modules(library_dir()),
                                  "library": LIBRARY_DIRNAME})

    @routes.get("/symbiotica/modules/{name:.+}")
    async def modules_read(request):
        try:
            module = read_module(library_dir(), request.match_info["name"])
        except ModuleError as e:
            return web.json_response({"error": str(e)}, status=400)
        if module is None:
            return web.json_response({"error": "no such module"}, status=404)
        return web.json_response(module)

    @routes.post("/symbiotica/modules/publish")
    async def modules_publish(request):
        body = await request.json()
        try:
            if body.get("kind") == "group":
                result = write_module(library_dir(), body.get("name"), group={
                    "group": body.get("group") or {},
                    "nodes": body.get("nodes"),
                    "links": body.get("links") or [],
                })
            else:
                result = write_module(library_dir(), body.get("name"),
                                      body.get("subgraph"), body.get("values") or {},
                                      body.get("instance"))
        except ModuleError as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response(result)

    @routes.post("/symbiotica/modules/sync")
    async def modules_sync(request):
        body = await request.json() if request.can_read_body else {}
        try:
            report = sync_workflows(_workflows_dir(), load_library(library_dir()),
                                    only_path=body.get("path") or None)
        except ModuleError as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response(report)
