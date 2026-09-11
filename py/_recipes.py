# ABOUTME: Workflow recipes — one template graph plus a table of per-game and
# ABOUTME: per-category values, written out as one workflow file per category.

# A template is an ordinary workflow whose variable nodes carry a title of the
# form `recipe:<key>`. A recipe file holds a `game` block (values every
# category shares: library path, project name, LoRAs) and a `categories` table
# (the control image, aspect, preamble and so on that make appliance1x2 differ
# from appliance1x1). `generate` layers a category over the game block and
# writes those values into the slots, so the workflow files stop being hand
# edited copies and become build output.
#
# How a value lands depends on its shape: a scalar sets the node's first
# widget, a list replaces every widget, a dict sets promoted widgets by name
# (a subgraph instance's LoRA picker), and a boolean on a `recipe:<key>?` slot
# switches the node between active and bypassed.
from __future__ import annotations

import copy
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

def workflow_name(recipe: dict, category: str) -> str:
    return f"{recipe.get('workflow_prefix', '')}{category}"


def generate(template: dict, recipe: dict, category: str) -> tuple[dict, dict]:
    """One workflow for one category: the game block with the category's
    values layered on top. The id is stable per (recipe, category) so a
    regenerated file is the same workflow to the editor, not a new one."""
    categories = recipe.get("categories") or {}
    if category not in categories:
        raise RecipeError(f"recipe has no category {category!r}")
    values = {**(recipe.get("game") or {}), **(categories[category] or {})}
    workflow = copy.deepcopy(template)
    report = apply_recipe(workflow, values)
    workflow["id"] = str(uuid.uuid5(NAMESPACE, workflow_name(recipe, category)))
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
