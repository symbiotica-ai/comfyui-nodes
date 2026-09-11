# ABOUTME: Recipe node — the canvas control for workflow recipes — and the routes
# ABOUTME: behind it: list, read (with the template's slots), new, save, generate.
import os

from ._recipes import (RECIPES_DIRNAME, RecipeError, delete_project, generate_all,
                       list_projects, new_project, projects_dir, read_project,
                       read_template, template_slots, write_project)

PICK = "— pick a project —"


def _project_names():
    try:
        return [p["name"] for p in list_projects(projects_dir())]
    except Exception:
        return []


class SymbioticaRecipe:
    """Frontend-only control: pick a project to edit its recipes on the node,
    start one from the open workflow, save it, or generate its workflows.
    Never executes — web/js/recipes.js marks it virtual."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "project": ([PICK] + _project_names(), {
                    "tooltip": "A project from user/default/recipes: one template "
                               "workflow, shared values, one recipe per asset type.",
                }),
                "recipe": ("STRING", {
                    "default": "",
                    "tooltip": "The recipe Capture writes into (created if new); "
                               "also the suffix of its workflow's name. Type it or "
                               "connect a text node.",
                }),
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "execute"
    CATEGORY = "Symbiotica/Recipes"
    DESCRIPTION = ("Workflow recipes: a project holds one template workflow, shared "
                   "values and one recipe per asset type; Generate writes one "
                   "workflow per recipe.")

    def execute(self, project=PICK, recipe=""):
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
            slots = template_slots(read_template(_workflows_dir(), project.get("template")))
        except RecipeError as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response({"project": project, "slots": slots})

    @routes.post("/symbiotica/recipes/new")
    async def projects_new(request):
        body = await request.json()
        try:
            name, project = new_project(_workflows_dir(), body.get("template"))
            if read_project(projects_dir(), name) is not None:
                return web.json_response({"error": f"project {name!r} exists — pick it instead"}, status=409)
            write_project(projects_dir(), name, project)
            slots = template_slots(read_template(_workflows_dir(), project["template"]))
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
            report = generate_all(_workflows_dir(), project)
        except RecipeError as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response(report)
