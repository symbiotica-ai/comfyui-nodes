# ABOUTME: Recipe node — the canvas control for workflow recipes — and the routes
# ABOUTME: behind it: list, read (with the template's slots), new, save, generate.
import os

from ._recipes import (RECIPES_DIRNAME, RecipeError, generate_all, list_recipes,
                       new_recipe, read_recipe, read_template, recipes_dir,
                       template_slots, write_recipe)

PICK = "— pick a recipe —"


def _recipe_names():
    try:
        return [r["name"] for r in list_recipes(recipes_dir())]
    except Exception:
        return []


class SymbioticaRecipe:
    """Frontend-only control: pick a recipe to edit it as a table on the node,
    start one from the open workflow, save it, or generate its workflows.
    Never executes — web/js/recipes.js marks it virtual."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "recipe": ([PICK] + _recipe_names(), {
                    "tooltip": "A recipe from user/default/recipes: one template "
                               "workflow plus a table of per-category values.",
                }),
                "category": ("STRING", {
                    "default": "",
                    "tooltip": "The category Capture writes into (created if new). "
                               "Type it or connect a text node.",
                }),
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "execute"
    CATEGORY = "Symbiotica/Recipes"
    DESCRIPTION = ("Workflow recipes: one template workflow, a table of values per "
                   "category, one generated workflow per category.")

    def execute(self, recipe=PICK, category=""):
        return ()


NODE_CLASS_MAPPINGS = {"SymbioticaRecipe": SymbioticaRecipe}
NODE_DISPLAY_NAME_MAPPINGS = {"SymbioticaRecipe": "Recipe"}


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
    async def recipes_list(request):
        return web.json_response({"recipes": list_recipes(recipes_dir()),
                                  "library": RECIPES_DIRNAME})

    @routes.get("/symbiotica/recipes/{name:.+}")
    async def recipes_read(request):
        try:
            recipe = read_recipe(recipes_dir(), request.match_info["name"])
            if recipe is None:
                return web.json_response({"error": "no such recipe"}, status=404)
            slots = template_slots(read_template(_workflows_dir(), recipe.get("template")))
        except RecipeError as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response({"recipe": recipe, "slots": slots})

    @routes.post("/symbiotica/recipes/new")
    async def recipes_new(request):
        body = await request.json()
        try:
            recipe = new_recipe(_workflows_dir(), body.get("template"))
            write_recipe(recipes_dir(), body.get("name") or "", recipe)
            slots = template_slots(read_template(_workflows_dir(), recipe["template"]))
        except RecipeError as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response({"recipe": recipe, "slots": slots})

    @routes.post("/symbiotica/recipes/save")
    async def recipes_save(request):
        body = await request.json()
        try:
            write_recipe(recipes_dir(), body.get("name") or "", body.get("recipe"))
        except RecipeError as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response({"saved": body.get("name")})

    @routes.post("/symbiotica/recipes/generate")
    async def recipes_generate(request):
        body = await request.json()
        try:
            recipe = read_recipe(recipes_dir(), body.get("name") or "")
            if recipe is None:
                return web.json_response({"error": "no such recipe"}, status=404)
            report = generate_all(_workflows_dir(), recipe)
        except RecipeError as e:
            return web.json_response({"error": str(e)}, status=400)
        return web.json_response(report)
