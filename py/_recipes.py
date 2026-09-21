# ABOUTME: Workflow recipes — a project file holds shared values and one recipe
# ABOUTME: per asset type; each recipe is written out as one workflow from a template.

# A template is an ordinary workflow whose variable nodes are painted the
# project's match colour, their title naming the slot (a title of the older
# form `recipe:<key>` still marks one). A project file (`imperia-bakery`) holds a `shared` block
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

import colorsys
import copy
import json
import os
import re
import uuid

try:
    from ._modules import _pos, _size, promoted_names
except ImportError:  # tests import py/ as top-level modules
    from _modules import _pos, _size, promoted_names

PREFIX = "recipe:"
TOGGLE = "?"
# LiteGraph's node palette, by the name the canvas shows for it.
PALETTE = {
    "red": "#533", "brown": "#593930", "green": "#353", "blue": "#335",
    "pale_blue": "#3f5159", "cyan": "#355", "purple": "#535", "yellow": "#653",
    "black": "#000",
}
HUE_TOLERANCE = 12
MODE_ACTIVE = 0
MODE_BYPASS = 4
NAMESPACE = uuid.UUID("5b7a3e8e-1a2c-4a0e-9c1f-6b2b6f6b2e11")


class RecipeError(ValueError):
    pass


# ------------------------------------------------------------------ color --

def _hsl(value):
    """A colour as (hue 0-360, saturation, lightness), or None."""
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", text):
        return None
    r, g, b = (int(text[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360, s, l


def color_matcher(token):
    """"Is this node painted <token>", or None when nothing was typed. The
    token is a palette name or a hex; matching is by hue, so the light theme's
    lighter shade of the same colour still counts."""
    name = re.sub(r"[\s-]+", "_", str(token or "").strip().lower())
    target = _hsl(PALETTE.get(name, name))
    if target is None:
        return None
    th, ts, _ = target

    def matches(node: dict) -> bool:
        for value in (node.get("bgcolor"), node.get("color")):
            own = _hsl(value)
            if own is None:
                continue
            oh, os_, _ = own
            if ts < 0.1 or os_ < 0.1:
                if ts < 0.1 and os_ < 0.1:
                    return True
                continue
            diff = abs(oh - th)
            if min(diff, 360 - diff) <= HUE_TOLERANCE:
                return True
        return False

    return matches


# ------------------------------------------------------------------ slots --

def slot_key(node: dict, matches=None, names=None) -> str | None:
    """The key a node carries: its title, without the `recipe:` prefix and
    without a toggle's `?`. Painting is the whole of what makes a slot — a
    node never retitled goes under its type's name, which is what the canvas
    shows on it. `names` maps a subgraph id to that subgraph's name, so an
    instance is named the way LiteGraph titles it."""
    title = node.get("title")
    title = title if isinstance(title, str) else ""
    if title.startswith(PREFIX):
        key = title[len(PREFIX):]
    elif matches is not None and matches(node):
        type_ = node.get("type")
        key = title.strip() or (names or {}).get(type_) or (
            type_ if isinstance(type_, str) else "")
    else:
        return None
    key = key.strip()
    if key.endswith(TOGGLE):
        key = key[:-len(TOGGLE)].strip()
    return key or None


def subgraph_names(workflow: dict) -> dict:
    """Every subgraph definition's id to its name — the title LiteGraph puts
    on an instance that was never renamed."""
    definitions = ((workflow.get("definitions") or {}).get("subgraphs") or [])
    return {s.get("id"): s.get("name") for s in definitions
            if s.get("id") and isinstance(s.get("name"), str)}


def is_toggle(node: dict) -> bool:
    return str(node.get("title", "")).rstrip().endswith(TOGGLE)


def recipe_slots(workflow: dict, color=None, display=None) -> dict[str, list[dict]]:
    """Every root slot node, keyed by its title. Two nodes may share a key
    (the same aspect fed to two places). Nodes inside subgraph definitions are
    not slots: a recipe speaks to the graph's surface.

    `display` maps a node type to the name the CANVAS draws on it when it was
    never retitled. A saved workflow stores no title for such a node, so
    without it this reads `SymbioticaControlImage` where the canvas captured
    `Control Image`, and the recipe's value has no slot to land in."""
    slots: dict[str, list[dict]] = {}
    matches = color_matcher(color)
    names = {**subgraph_names(workflow), **(display or {})}
    for node in workflow.get("nodes") or []:
        key = slot_key(node, matches, names)
        if key:
            slots.setdefault(key, []).append(node)
    return slots


# ------------------------------------------------------------------ apply --

# rgthree's Fast Groups Muter / Bypasser. Its rows are not widgets with names:
# each one stands for a GROUP, and what it actually moves is the mode of every
# node inside that group's frame. A recipe records one entry per group title,
# so writing one means walking the workflow's groups, not the node's widgets.
RGTHREE_GROUP_NODES = {
    "Fast Groups Muter (rgthree)": 2,       # modeOff = NEVER
    "Fast Groups Bypasser (rgthree)": 4,    # modeOff = BYPASS
}


def is_group_switch(node: dict) -> bool:
    return node.get("type") in RGTHREE_GROUP_NODES


def _in_group(node: dict, bounding) -> bool:
    """rgthree decides membership by the node's CENTRE, not its corner, so a
    node overhanging a frame's edge belongs where the canvas shows it."""
    if not isinstance(bounding, (list, tuple)) or len(bounding) < 4:
        return False
    x, y = _pos(node)
    w, h = _size(node)
    cx, cy = x + w / 2, y + h / 2
    bx, by, bw, bh = (float(v) for v in bounding[:4])
    return bx <= cx < bx + bw and by <= cy < by + bh


def _group_nodes(workflow: dict, title: str) -> list[dict]:
    """Every root node sitting inside a group of this title."""
    boundings = [g.get("bounding") for g in workflow.get("groups") or []
                 if str(g.get("title", "")).strip() == title]
    if not boundings:
        return []
    return [n for n in workflow.get("nodes") or []
            if any(_in_group(n, b) for b in boundings)]


def _set_groups(workflow: dict, node: dict, key: str, value: dict) -> None:
    mode_off = RGTHREE_GROUP_NODES[node["type"]]
    for title, on in value.items():
        if not isinstance(on, bool):
            raise RecipeError(f"{key} / {title}: a group is on or off, got {on!r}")
        members = _group_nodes(workflow, title)
        if not members:
            raise RecipeError(f"{key}: the template has no group titled {title!r}")
        for member in members:
            if member is node:
                continue
            member["mode"] = MODE_ACTIVE if on else mode_off


# The name behind every widget input the graph declares, wired or not, and the
# subset of those whose value arrives on a link.
def _wired_widget_names(node: dict) -> set:
    out = set()
    for inp in node.get("inputs") or []:
        widget = inp.get("widget")
        if not widget or inp.get("link") is None:
            continue
        name = widget.get("name") if isinstance(widget, dict) else None
        out.add(name or inp.get("name"))
    return out


# Where each captured widget name sits in `widgets_values`, or None when the
# node cannot be addressed by name at all.
#
# `widgets_values` is POSITIONAL and is regularly longer than the inputs the
# graph declares. ComfyUI draws widgets the graph never declares -- a seed's
# `control_after_generate`, the DOM panel a node draws for itself -- and a
# saved workflow records their values with no name attached. A KSampler is six
# declared names against seven values, which used to refuse the whole project.
#
# Two orders are known and both are subsequences of the real one: the DECLARED
# names, in input order, and the CAPTURED keys, which the canvas wrote in
# widget order with the wired ones left out (`widgetValues`, web/js/recipes.js).
# Merging them reconstructs the layout -- a wired name sits where the declared
# order puts it, an undeclared one where the capture puts it -- and the merge
# only counts if it lands on exactly as many widgets as the node holds.
def _widget_positions(node: dict, captured) -> dict | None:
    names = promoted_names(node)
    widgets = node.get("widgets_values") or []
    if len(names) == len(widgets):
        return {name: i for i, name in enumerate(names)}
    wired = _wired_widget_names(node)
    keys = list(captured)
    order = []
    i = 0
    for name in names:
        if name in wired:
            order.append(name)
            continue
        while i < len(keys) and keys[i] != name:
            order.append(keys[i])
            i += 1
        if i >= len(keys):
            return None
        order.append(name)
        i += 1
    order.extend(keys[i:])
    if len(order) != len(widgets) or len(set(order)) != len(order):
        return None
    return {name: n for n, name in enumerate(order)}


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
        positions = _widget_positions(node, value)
        if positions is None:
            raise RecipeError(
                f"{key}: node {node.get('id')} holds {len(widgets)} widget values but the "
                f"template declares {len(promoted_names(node))} widget names, and the recipe "
                f"names {len(value)} of them. Capture the slot again so it holds every widget.")
        for name, item in value.items():
            if name not in positions:
                raise RecipeError(f"{key}: node {node.get('id')} has no widget {name!r}")
            widgets[positions[name]] = copy.deepcopy(item)
    elif isinstance(value, list):
        if len(value) != len(widgets):
            raise RecipeError(
                f"{key}: node {node.get('id')} has {len(widgets)} widgets, got {len(value)} values")
        node["widgets_values"] = copy.deepcopy(value)
    else:
        if not widgets:
            raise RecipeError(f"{key}: node {node.get('id')} has no widgets to set")
        widgets[0] = copy.deepcopy(value)


def apply_recipe(workflow: dict, values: dict, color=None, display=None) -> dict:
    """Write values into the workflow's slots, in place. A key no slot carries
    is refused: the alternative is a typo that silently renders the template's
    own value at full price."""
    slots = recipe_slots(workflow, color, display)
    unknown = sorted(k for k in values if k not in slots)
    if unknown:
        raise RecipeError(f"no recipe slot named {', '.join(unknown)} in the template")
    for key, value in values.items():
        for node in slots[key]:
            if is_group_switch(node):
                if not isinstance(value, dict):
                    raise RecipeError(
                        f"{key}: a group switch takes one true/false per group title, got {value!r}")
                _set_groups(workflow, node, key, value)
            else:
                _set_value(node, key, value)
    return {
        "applied": sorted(values),
        "template": sorted(k for k in slots if k not in values),
    }


# --------------------------------------------------------------- generate --

def workflow_name(project: dict, recipe: str) -> str:
    return f"{project.get('workflow_prefix', '')}{recipe}"


def generate(template: dict, project: dict, recipe: str, display=None) -> tuple[dict, dict]:
    """One workflow for one recipe: the project's shared block with the
    recipe's values layered on top. The id is stable per (project, recipe)
    so a regenerated file is the same workflow to the editor, not a new one."""
    recipes = project.get("recipes") or {}
    if recipe not in recipes:
        raise RecipeError(f"project has no recipe {recipe!r}")
    values = {**(project.get("shared") or {}), **(recipes[recipe] or {})}
    color = project.get("match_color")
    workflow = copy.deepcopy(template)
    # A key the template has no slot for is a value the panel already shows
    # struck through as ignored (a slot renamed since the capture), so it is
    # reported, not refused: one stale key must not block every workflow.
    slots = recipe_slots(workflow, color, display)
    ignored = sorted(k for k in values if k not in slots)
    report = apply_recipe(workflow, {k: v for k, v in values.items() if k in slots},
                          color, display)
    report["ignored"] = ignored
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

def template_slots(workflow: dict, color=None, display=None) -> list[dict]:
    """What a recipe can set in this template, one entry per key, in canvas
    order: the kind a value takes (toggle, dict for a subgraph instance,
    scalar otherwise), the template's own value, and how many widgets the
    node has (a scalar cell may still hold a list to set them all)."""
    subgraph_ids = {s.get("id") for s in
                    ((workflow.get("definitions") or {}).get("subgraphs") or [])}
    out = []
    for key, nodes in sorted(recipe_slots(workflow, color, display).items()):
        node = nodes[0]
        widgets = node.get("widgets_values") or []
        if is_toggle(node):
            out.append({"key": key, "kind": "toggle",
                        "default": node.get("mode", MODE_ACTIVE) == MODE_ACTIVE, "widgets": len(widgets)})
        elif is_group_switch(node):
            # What the template holds for a group is whether its nodes are
            # live, not the muter's own serialised rows.
            groups = {}
            for group in workflow.get("groups") or []:
                title = str(group.get("title", "")).strip()
                if not title:
                    continue
                members = [n for n in workflow.get("nodes") or []
                           if n is not node and _in_group(n, group.get("bounding"))]
                if members:
                    groups[title] = any(m.get("mode", MODE_ACTIVE) == MODE_ACTIVE for m in members)
            out.append({"key": key, "kind": "dict", "default": groups, "widgets": len(widgets)})
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


def new_project(workflows_dir: str, template_rel, color=None) -> tuple[str, dict]:
    """A project for one template, named from it, with the shared block
    started from the template's own values, no recipes yet, output beside
    the template."""
    rel = _template_rel(template_rel)
    slots = template_slots(read_template(workflows_dir, rel), color)
    project = {"template": rel}
    folder = os.path.dirname(rel)
    if folder:
        project["output"] = folder
    if str(color or "").strip():
        project["match_color"] = str(color).strip()
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


def generate_all(workflows_dir: str, project: dict, display=None, only=None) -> dict:
    """Every recipe of one project, written beside its template (or into the
    project's `output` folder). Every workflow is generated before any is
    written, so a bad row leaves the folder as it was."""
    template = read_template(workflows_dir, project.get("template"))
    output_rel = project.get("output") or os.path.dirname(_template_rel(project.get("template")))
    output_dir = _under(workflows_dir, output_rel, "output folder") if output_rel else workflows_dir
    written = []
    wanted = [r for r in (project.get("recipes") or {}) if only is None or r == only]
    if only is not None and not wanted:
        raise RecipeError(f"project has no recipe {only!r}")
    for recipe in wanted:
        workflow, report = generate(template, project, recipe, display)
        filename = f"{workflow_name(project, recipe)}.json"
        rel = f"{output_rel}/{filename}" if output_rel else filename
        written.append({"path": rel, "recipe": recipe, "workflow": workflow, **report})
    os.makedirs(output_dir, exist_ok=True)
    for item in written:
        with open(os.path.join(output_dir, os.path.basename(item["path"])), "w", encoding="utf-8") as f:
            json.dump(item.pop("workflow"), f, indent=2)
    return {"template": project.get("template"), "written": written}
