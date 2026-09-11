# ABOUTME: Workflow recipes — a project file holds shared values and one recipe
# ABOUTME: per asset type; each recipe is written out as one workflow from a template.

# A template is an ordinary workflow whose variable nodes carry a title of the
# form `recipe:<key>`. A project file (`imperia-bakery`) holds a `shared` block
# (values every recipe shares: library path, project name, LoRAs) and a
# `recipes` table, one recipe per asset type (the control image, aspect,
# preamble and so on that make appliance1x2 differ from appliance1x1).
# `generate` layers a recipe over the shared block and writes those values
# into the slots, so the workflow files stop being hand edited copies and
# become build output.
#
# How a value lands depends on its shape: a scalar sets the node's first
# widget, a list replaces every widget, a dict sets promoted widgets by name
# (a subgraph instance's LoRA picker), and a boolean on a `recipe:<key>?` slot
# switches the node between active and bypassed.
from __future__ import annotations

import copy
import json
import os
import re
import uuid

try:
    from ._modules import promoted_names
except ImportError:  # tests import py/ as top-level modules
    from _modules import promoted_names

PREFIX = "recipe:"
TOGGLE = "?"
MODE_ACTIVE = 0
MODE_BYPASS = 4
NAMESPACE = uuid.UUID("5b7a3e8e-1a2c-4a0e-9c1f-6b2b6f6b2e11")


class RecipeError(ValueError):
    pass


# ------------------------------------------------------------------ slots --

def slot_key(node: dict) -> str | None:
    title = node.get("title")
    if not isinstance(title, str) or not title.startswith(PREFIX):
        return None
    key = title[len(PREFIX):].strip()
    if key.endswith(TOGGLE):
        key = key[:-len(TOGGLE)].strip()
    return key or None


def is_toggle(node: dict) -> bool:
    return str(node.get("title", "")).rstrip().endswith(TOGGLE)


def recipe_slots(workflow: dict) -> dict[str, list[dict]]:
    """Every root node titled `recipe:<key>`, keyed by <key>. Two nodes may
    share a key (the same aspect fed to two places). Nodes inside subgraph
    definitions are not slots: a recipe speaks to the graph's surface."""
    slots: dict[str, list[dict]] = {}
    for node in workflow.get("nodes") or []:
        key = slot_key(node)
        if key:
            slots.setdefault(key, []).append(node)
    return slots


# ------------------------------------------------------------------ apply --

def _set_value(node: dict, key: str, value) -> None:
    if is_toggle(node):
        if not isinstance(value, bool):
            raise RecipeError(f"{key}: a toggle takes true or false, got {value!r}")
        node["mode"] = MODE_ACTIVE if value else MODE_BYPASS
        return
    widgets = node.get("widgets_values")
    if not isinstance(widgets, list):
        raise RecipeError(f"{key}: node {node.get('id')} has no widgets to set")
    if isinstance(value, dict):
        names = promoted_names(node)
        if len(names) != len(widgets):
            raise RecipeError(
                f"{key}: node {node.get('id')} widgets cannot be addressed by name "
                f"({len(names)} names for {len(widgets)} values)")
        for name, item in value.items():
            if name not in names:
                raise RecipeError(f"{key}: node {node.get('id')} has no widget {name!r}")
            widgets[names.index(name)] = copy.deepcopy(item)
    elif isinstance(value, list):
        if len(value) != len(widgets):
            raise RecipeError(
                f"{key}: node {node.get('id')} has {len(widgets)} widgets, got {len(value)} values")
        node["widgets_values"] = copy.deepcopy(value)
    else:
        if not widgets:
            raise RecipeError(f"{key}: node {node.get('id')} has no widgets to set")
        widgets[0] = copy.deepcopy(value)


def apply_recipe(workflow: dict, values: dict) -> dict:
    """Write values into the workflow's slots, in place. A key no slot carries
    is refused: the alternative is a typo that silently renders the template's
    own value at full price."""
    slots = recipe_slots(workflow)
    unknown = sorted(k for k in values if k not in slots)
    if unknown:
        raise RecipeError(f"no recipe slot named {', '.join(unknown)} in the template")
    for key, value in values.items():
        for node in slots[key]:
            _set_value(node, key, value)
    return {
        "applied": sorted(values),
        "template": sorted(k for k in slots if k not in values),
    }


# --------------------------------------------------------------- generate --

def workflow_name(project: dict, recipe: str) -> str:
    return f"{project.get('workflow_prefix', '')}{recipe}"


def generate(template: dict, project: dict, recipe: str) -> tuple[dict, dict]:
    """One workflow for one recipe: the project's shared block with the
    recipe's values layered on top. The id is stable per (project, recipe)
    so a regenerated file is the same workflow to the editor, not a new one."""
    recipes = project.get("recipes") or {}
    if recipe not in recipes:
        raise RecipeError(f"project has no recipe {recipe!r}")
    values = {**(project.get("shared") or {}), **(recipes[recipe] or {})}
    workflow = copy.deepcopy(template)
    report = apply_recipe(workflow, values)
    workflow["id"] = str(uuid.uuid5(NAMESPACE, workflow_name(project, recipe)))
    workflow["revision"] = 0
    return workflow, report


# ---------------------------------------------------------------- promote --

def _next_id(graph: dict, counter: str, items: list, field) -> int:
    current = max([int(graph.get(counter) or 0)] + [int(field(i)) for i in items])
    graph[counter] = current + 1
    return current + 1


def promote_string_input(workflow: dict, subgraph_name: str, inner_id: int,
                         input_name: str, title: str, pos: list) -> dict:
    """Lift a String node out of a subgraph so its text becomes a recipe slot.

    The inner String's single outgoing link is re-rooted at the subgraph's
    input node as a new STRING input, the String node itself is dropped, and
    every root instance of the subgraph gains the input slot, fed by a new
    root String node titled `title` that holds the old text. Returns the root
    node."""
    definitions = (workflow.get("definitions") or {}).get("subgraphs") or []
    sg = next((s for s in definitions if s.get("name") == subgraph_name), None)
    if sg is None:
        raise RecipeError(f"no subgraph named {subgraph_name!r}")
    inner = next((n for n in sg.get("nodes") or [] if n.get("id") == inner_id), None)
    if inner is None:
        raise RecipeError(f"subgraph {subgraph_name!r} has no node {inner_id}")
    outputs = inner.get("outputs") or []
    links_out = outputs[0].get("links") if outputs else None
    if (inner.get("type") not in ("String", "PrimitiveStringMultiline", "PrimitiveString")
            or len(outputs) != 1 or not links_out or len(links_out) != 1):
        raise RecipeError(
            f"node {inner_id} ({inner.get('type')}) is not a String with one outgoing link")
    text = (inner.get("widgets_values") or [""])[0]
    link_id = links_out[0]
    link = next(l for l in sg["links"] if l.get("id") == link_id)

    slot = len(sg["inputs"])
    sg["inputs"].append({
        "id": str(uuid.uuid4()), "name": input_name, "type": "STRING",
        "linkIds": [link_id],
        "pos": [pos[0], pos[1]],
    })
    link["origin_id"] = -10
    link["origin_slot"] = slot
    sg["nodes"] = [n for n in sg["nodes"] if n.get("id") != inner_id]

    root_nodes = workflow.setdefault("nodes", [])
    root_links = workflow.setdefault("links", [])
    node_id = _next_id(workflow, "last_node_id", root_nodes, lambda n: n.get("id") or 0)
    root = {
        "id": node_id, "type": "String", "pos": [pos[0], pos[1]], "size": [430, 160],
        "flags": {}, "order": 0, "mode": MODE_ACTIVE, "title": title,
        "inputs": [{"localized_name": "String", "name": "String", "type": "STRING",
                    "widget": {"name": "String"}, "link": None}],
        "outputs": [{"localized_name": "STRING", "name": "STRING", "type": "STRING", "links": []}],
        "properties": {"cnr_id": "ComfyLiterals", "Node name for S&R": "String"},
        "widgets_values": [text],
    }
    root_nodes.append(root)
    for instance in root_nodes:
        if instance.get("type") != sg.get("id"):
            continue
        new_link = _next_id(workflow, "last_link_id", root_links, lambda l: l[0])
        instance.setdefault("inputs", []).append(
            {"name": input_name, "type": "STRING", "link": new_link})
        root_links.append([new_link, node_id, 0, instance["id"], len(instance["inputs"]) - 1, "STRING"])
        root["outputs"][0]["links"].append(new_link)
    return root


# ------------------------------------------------------------------ slots --

def template_slots(workflow: dict) -> list[dict]:
    """What a recipe can set in this template, one entry per key, in canvas
    order: the kind a value takes (toggle, dict for a subgraph instance,
    scalar otherwise), the template's own value, and how many widgets the
    node has (a scalar cell may still hold a list to set them all)."""
    subgraph_ids = {s.get("id") for s in
                    ((workflow.get("definitions") or {}).get("subgraphs") or [])}
    out = []
    for key, nodes in sorted(recipe_slots(workflow).items()):
        node = nodes[0]
        widgets = node.get("widgets_values") or []
        if is_toggle(node):
            out.append({"key": key, "kind": "toggle",
                        "default": node.get("mode", MODE_ACTIVE) == MODE_ACTIVE, "widgets": len(widgets)})
        elif node.get("type") in subgraph_ids:
            names = promoted_names(node)
            # A promoted input fed by a link (a seed node, a resolution node)
            # renders from the link, so its widget value is not a setting.
            wired = {(i.get("widget") or {}).get("name") or i.get("name")
                     for i in node.get("inputs") or [] if i.get("widget") and i.get("link") is not None}
            default = ({n: v for n, v in zip(names, widgets) if n not in wired}
                       if len(names) == len(widgets) else {})
            out.append({"key": key, "kind": "dict", "default": default, "widgets": len(widgets)})
        else:
            out.append({"key": key, "kind": "scalar",
                        "default": widgets[0] if widgets else None, "widgets": len(widgets)})
    return out


# ---------------------------------------------------------------- library --

RECIPES_DIRNAME = "recipes"
WORKFLOWS_PREFIX = "workflows/"
LIBRARY_ROOT = "studios/"


def _template_rel(rel) -> str:
    """A template path as the recipe stores it: relative to the workflows
    folder. The editor names the open workflow with a `workflows/` prefix."""
    rel = str(rel or "").replace("\\", "/").strip("/")
    if rel.startswith(WORKFLOWS_PREFIX):
        rel = rel[len(WORKFLOWS_PREFIX):]
    return rel


def read_template(workflows_dir: str, rel) -> dict:
    rel = _template_rel(rel)
    path = _under(workflows_dir, rel, "template")
    if not os.path.isfile(path):
        raise RecipeError(f"template {rel!r} is not in the workflows directory")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_project(dir_: str, name: str, project: dict) -> str:
    """Save a project as the file its name reads back. Refuses a shape the
    generator could not run, so a broken save cannot hide until Generate."""
    if not isinstance(project, dict) or not isinstance(project.get("recipes"), dict):
        raise RecipeError("a project needs a recipes table")
    if not str(project.get("template") or "").strip():
        raise RecipeError("a project needs a template")
    path = _under(dir_, f"{name}.json", "project name")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(project, f, indent=2, ensure_ascii=False)
    return path


def delete_project(dir_: str, name: str) -> bool:
    """Remove a project file. The generated workflows stay: they are files
    in the workflows folder like any other."""
    path = _under(dir_, f"{name}.json", "project name")
    if not os.path.isfile(path):
        return False
    os.remove(path)
    return True


def project_name(template_rel, slots: list[dict]) -> str:
    """What a new project is called: the template's `library` slot with the
    studios root dropped and slashes to dashes (`studios/imperia/bakery` is
    `imperia-bakery`), else the template's own file name."""
    library = next((s["default"] for s in slots if s["key"] == "library"), None)
    if isinstance(library, str) and library.strip():
        rel = library.strip().lstrip("/")
        if rel.startswith(LIBRARY_ROOT):
            rel = rel[len(LIBRARY_ROOT):]
        name = safe_project_name(rel.strip("/").replace("/", "-"))
        if name:
            return name
    stem = os.path.splitext(os.path.basename(_template_rel(template_rel)))[0]
    return safe_project_name(stem) or "project"


def safe_project_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(name or "")).strip("-.")


def new_project(workflows_dir: str, template_rel) -> tuple[str, dict]:
    """A project for one template, named from it, with the shared block
    started from the template's own values, no recipes yet, output beside
    the template."""
    rel = _template_rel(template_rel)
    slots = template_slots(read_template(workflows_dir, rel))
    project = {"template": rel}
    folder = os.path.dirname(rel)
    if folder:
        project["output"] = folder
    project.update({"workflow_prefix": "",
                    "shared": {s["key"]: copy.deepcopy(s["default"]) for s in slots if s["default"] is not None},
                    "recipes": {}})
    return project_name(rel, slots), project


def projects_dir() -> str:
    import folder_paths
    return os.path.join(folder_paths.get_user_directory(), "default", RECIPES_DIRNAME)


def _under(root: str, rel: str, what: str) -> str:
    """An absolute path inside root, or a refusal: a recipe names files
    relative to the workflows dir and must not reach past it."""
    rel = str(rel or "").replace("\\", "/").strip("/")
    if not rel:
        raise RecipeError(f"recipe has no {what}")
    path = os.path.normpath(os.path.join(root, rel))
    if os.path.commonpath([os.path.abspath(root), os.path.abspath(path)]) != os.path.abspath(root):
        raise RecipeError(f"{what} {rel!r} is outside the workflows directory")
    return path


def _current_keys(project: dict) -> dict:
    """Files written before the rename said `game` and `categories`."""
    if isinstance(project, dict):
        if "shared" not in project and "game" in project:
            project["shared"] = project.pop("game")
        if "recipes" not in project and "categories" in project:
            project["recipes"] = project.pop("categories")
    return project


def read_project(dir_: str, name: str) -> dict | None:
    path = _under(dir_, f"{name}.json", "project name")
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return _current_keys(json.load(f))


def list_projects(dir_: str) -> list[dict]:
    """Every project file, by name, with the template it builds from and the
    recipes it would write. Unreadable files are skipped."""
    if not os.path.isdir(dir_):
        return []
    out = []
    for filename in sorted(os.listdir(dir_)):
        if not filename.endswith(".json"):
            continue
        try:
            with open(os.path.join(dir_, filename), "r", encoding="utf-8") as f:
                project = _current_keys(json.load(f))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(project, dict) or not isinstance(project.get("recipes"), dict):
            continue
        out.append({"name": filename[:-len(".json")], "template": project.get("template"),
                    "recipes": list(project["recipes"])})
    return out


def generate_all(workflows_dir: str, project: dict) -> dict:
    """Every recipe of one project, written beside its template (or into the
    project's `output` folder). Every workflow is generated before any is
    written, so a bad row leaves the folder as it was."""
    template = read_template(workflows_dir, project.get("template"))
    output_rel = project.get("output") or os.path.dirname(_template_rel(project.get("template")))
    output_dir = _under(workflows_dir, output_rel, "output folder") if output_rel else workflows_dir
    written = []
    for recipe in project.get("recipes") or {}:
        workflow, report = generate(template, project, recipe)
        filename = f"{workflow_name(project, recipe)}.json"
        rel = f"{output_rel}/{filename}" if output_rel else filename
        written.append({"path": rel, "recipe": recipe, "workflow": workflow, **report})
    os.makedirs(output_dir, exist_ok=True)
    for item in written:
        with open(os.path.join(output_dir, os.path.basename(item["path"])), "w", encoding="utf-8") as f:
            json.dump(item.pop("workflow"), f, indent=2)
    return {"template": project.get("template"), "written": written}
