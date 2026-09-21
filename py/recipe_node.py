# ABOUTME: Recipe node — the canvas control for workflow recipes — and the routes
# ABOUTME: behind it: list, read (with the template's slots), new, save, generate.
import os

from ._recipes import (RECIPES_DIRNAME, RecipeError, delete_project, generate_all,
                       list_projects, new_project, projects_dir, read_project,
                       read_template, template_slots, write_project)


class SymbioticaRecipe:
    """Frontend-only control: the project is the one whose template is the
    open workflow; edit its recipes on the node, start it from the open
    workflow, save it, or generate its workflows. Never executes —
    web/js/recipes.js marks it virtual."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "recipe": ("STRING", {
                    "default": "",
                    "tooltip": "The recipe Capture writes into (created if new); "
                               "also the suffix of its workflow's name. Type it or "
                               "connect a text node.",
                }),
                "match_color": ("STRING", {
                    "default": "purple",
                    "tooltip": "The colour that marks a recipe slot: every node "
                               "painted it on this workflow is a slot, and its "
                               "title is the slot's name. A palette name "
                               "(purple, green, blue, pale_blue, cyan, red, "
                               "brown, yellow, black) or a hex. A node titled "
                               "recipe:<name> is a slot whatever its colour.",
                }),
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "execute"
    CATEGORY = "Symbiotica"
    DESCRIPTION = ("Workflow recipes: a project holds one template workflow, shared "
                   "values and one recipe per asset type; Generate writes one "
                   "workflow per recipe.")

    def execute(self, recipe="", match_color=""):
        return ()


NODE_CLASS_MAPPINGS = {"SymbioticaRecipe": SymbioticaRecipe}
NODE_DISPLAY_NAME_MAPPINGS = {"SymbioticaRecipe": "Recipes"}


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

    def _display_names():
        """What the CANVAS draws on a node that was never retitled. A saved
        workflow stores no title for one, so without this the server reads
        `SymbioticaControlImage` where the canvas captured `Control Image`,
        and the recipe's value has no slot to land in."""
        try:
            import nodes
            return {k: v for k, v in (nodes.NODE_DISPLAY_NAME_MAPPINGS or {}).items()
                    if isinstance(k, str) and isinstance(v, str)}
        except Exception:
            return {}

    @routes.get("/symbiotica/recipes")
    async def projects_list(request):
        return web.json_response({"projects": list_projects(projects_dir()),
                                  "library": RECIPES_DIRNAME})

    @routes.get("/symbiotica/recipes/{name:.+}")
    async def projects_read(request):
        try:
            project = read_project(projects_dir(), request.match_info["name"])
            if project is None:
                return web.json_response({"error": "no such project"}, status=404)
            slots = template_slots(read_template(_workflows_dir(), project.get("template")),
                                   project.get("match_color"), _display_names())
        except RecipeError as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response({"project": project, "slots": slots})

    @routes.post("/symbiotica/recipes/new")
    async def projects_new(request):
        body = await request.json()
        try:
            name, project = new_project(_workflows_dir(), body.get("template"),
                                        body.get("match_color"))
            if read_project(projects_dir(), name) is not None:
                return web.json_response({"error": f"project {name!r} exists — pick it instead"}, status=409)
            write_project(projects_dir(), name, project)
            slots = template_slots(read_template(_workflows_dir(), project["template"]),
                                   project.get("match_color"), _display_names())
        except RecipeError as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response({"name": name, "project": project, "slots": slots})

    @routes.delete("/symbiotica/recipes/{name:.+}")
    async def projects_delete(request):
        try:
            removed = delete_project(projects_dir(), request.match_info["name"])
        except RecipeError as e:
            return web.json_response({"error": str(e)}, status=400)
        if not removed:
            return web.json_response({"error": "no such project"}, status=404)
        return web.json_response({"deleted": request.match_info["name"]})

    @routes.post("/symbiotica/recipes/save")
    async def projects_save(request):
        body = await request.json()
        try:
            write_project(projects_dir(), body.get("name") or "", body.get("project"))
        except RecipeError as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response({"saved": body.get("name")})

    @routes.post("/symbiotica/recipes/generate")
    async def projects_generate(request):
        body = await request.json()
        try:
            project = read_project(projects_dir(), body.get("name") or "")
            if project is None:
                return web.json_response({"error": "no such project"}, status=404)
            report = generate_all(_workflows_dir(), project, _display_names(),
                                  body.get("recipe") or None)
        except RecipeError as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response(report)
