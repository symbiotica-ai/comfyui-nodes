# ABOUTME: Linked subgraph modules — a library of published subgraphs and the
# ABOUTME: merge that swaps a workflow's stale copy for the library version.

# A workflow stores each subgraph once under definitions.subgraphs and every
# instance on the canvas is a node whose type is that subgraph's id. Comfy
# copies a subgraph into each workflow and never looks back, so a LoRA change
# has to be repeated in every file. A module is a subgraph tagged with a name
# and a revision in its `extra`; the library keeps the latest revision, and
# `apply_modules` brings a workflow's copy up to date, keeping the workflow's
# own subgraph id so the instances keep resolving.
#
# Promoted widget values (the LoRA picker on the outside of the node) live on
# the instance, not in the definition. Each instance carries a snapshot of the
# module's values as of its last sync; a value is overwritten only when the
# module's value changed since that snapshot, so a prompt typed into one
# workflow survives a LoRA change published from another.
#
# web/js/modules.js applies the same merge to the graph JSON on open. Change
# both together.
from __future__ import annotations

import copy
import json
import os
import re
from datetime import datetime, timezone

TAG = "symbiotica_module"
# A group module: every member node carries {name, key, rev, snapshot}. The
# frame itself is just the rectangle that says which tagged nodes belong
# together, so a copy-pasted group keeps working — the tags travel with the
# nodes.
GTAG = "symbiotica_group"
LIBRARY_DIRNAME = "symbiotica-modules"


class ModuleError(ValueError):
    pass


# ---------------------------------------------------------------- library --

def safe_filename(name: str) -> str:
    """The file a module is stored under. Letters, digits, dash, underscore and
    space survive; everything else becomes a dash, so a name can never walk
    out of the library directory."""
    cleaned = re.sub(r"[^A-Za-z0-9 _-]+", "-", str(name or "")).strip(" -")
    if not cleaned:
        raise ModuleError("module name is empty")
    return cleaned


def library_dir() -> str:
    import folder_paths
    return os.path.join(folder_paths.get_user_directory(), "default", LIBRARY_DIRNAME)


def _module_path(lib_dir: str, name: str) -> str:
    return os.path.join(lib_dir, safe_filename(name) + ".json")


def read_module(lib_dir: str, name: str) -> dict | None:
    path = _module_path(lib_dir, name)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_library(lib_dir: str) -> dict[str, dict]:
    """Every module in the library, keyed by name. Unreadable files are skipped
    rather than failing every sync for one bad file."""
    library: dict[str, dict] = {}
    if not os.path.isdir(lib_dir):
        return library
    for filename in sorted(os.listdir(lib_dir)):
        if not filename.endswith(".json"):
            continue
        try:
            with open(os.path.join(lib_dir, filename), "r", encoding="utf-8") as f:
                module = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        name = module.get("name")
        if not name:
            continue
        if isinstance(module.get("subgraph"), dict) or isinstance(module.get("nodes"), list):
            library[name] = module
    return library


def list_modules(lib_dir: str) -> list[dict]:
    return [
        {"name": m["name"], "rev": int(m.get("rev", 0)), "updated": m.get("updated"),
         "kind": m.get("kind", "subgraph")}
        for m in load_library(lib_dir).values()
    ]


def write_module(lib_dir: str, name: str, subgraph: dict | None = None,
                 values: dict | None = None, instance: dict | None = None,
                 group: dict | None = None) -> dict:
    """Publish: the next revision of a module. A subgraph module stores the
    definition (tagged so a workflow that receives it is linked from the
    start), its promoted values and an instance template; a group module
    stores the frame, the member nodes (positions relative to the frame) and
    the links between them."""
    name = str(name or "").strip()
    if not name:
        raise ModuleError("module name is empty")
    existing = read_module(lib_dir, name)
    rev = int(existing.get("rev", 0)) + 1 if existing else 1
    module = {
        "name": name,
        "rev": rev,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if group is not None:
        nodes = group.get("nodes")
        if not isinstance(nodes, list) or not nodes:
            raise ModuleError("group module has no nodes")
        nodes = copy.deepcopy(nodes)
        for node in nodes:
            (node.get("properties") or {}).pop(GTAG, None)
            for inp in node.get("inputs") or []:
                inp["link"] = None
            for out in node.get("outputs") or []:
                out["links"] = []
        module.update({
            "kind": "group",
            "group": copy.deepcopy(group.get("group") or {}),
            "nodes": nodes,
            "links": copy.deepcopy(group.get("links") or []),
        })
    else:
        if not isinstance(subgraph, dict) or not isinstance(subgraph.get("nodes"), list):
            raise ModuleError("subgraph definition missing")
        subgraph = copy.deepcopy(subgraph)
        subgraph.setdefault("extra", {})
        subgraph["extra"][TAG] = {"name": name, "rev": rev}
        module.update({
            "kind": "subgraph",
            "subgraph": subgraph,
            "values": dict(values or {}),
            "instance": instance,
        })
    os.makedirs(lib_dir, exist_ok=True)
    with open(_module_path(lib_dir, name), "w", encoding="utf-8") as f:
        json.dump(module, f, indent=2)
    return {"name": name, "rev": rev, "kind": module["kind"]}


# ------------------------------------------------------------------ merge --

def promoted_names(node: dict) -> list[str]:
    """The names behind an instance's widgets_values, in order: every input
    that carries a `widget` key is a promoted widget, and Comfy serializes
    their values positionally."""
    names = []
    for inp in node.get("inputs") or []:
        widget = inp.get("widget")
        if isinstance(widget, dict):
            names.append(widget.get("name") or inp.get("name"))
        elif widget:
            names.append(inp.get("name"))
    return names


def _all_nodes(workflow: dict):
    """Root nodes plus the nodes inside every subgraph definition: a module
    instance can sit inside another subgraph."""
    for node in workflow.get("nodes") or []:
        yield node
    for definition in (workflow.get("definitions") or {}).get("subgraphs") or []:
        for node in definition.get("nodes") or []:
            yield node


def _patch_instance(node: dict, name: str, rev: int, values: dict) -> bool:
    """Bring one instance to the module's values. Returns False when the
    positional mapping cannot be trusted (widget count differs), in which case
    only the snapshot is updated and the values are left alone."""
    props = node.setdefault("properties", {})
    snapshot = ((props.get(TAG) or {}).get("values")) or {}
    names = promoted_names(node)
    widgets_values = node.get("widgets_values")
    applied = True
    if isinstance(widgets_values, list) and len(widgets_values) == len(names):
        for index, widget_name in enumerate(names):
            if widget_name not in values:
                continue
            if values[widget_name] != snapshot.get(widget_name, _MISSING):
                widgets_values[index] = copy.deepcopy(values[widget_name])
    else:
        applied = False
    props[TAG] = {"name": name, "rev": rev, "values": copy.deepcopy(values)}
    return applied


_MISSING = object()


def apply_modules(workflow: dict, library: dict[str, dict]) -> dict:
    """Update every tagged subgraph in a workflow (in place) whose library
    revision is newer. Reports what changed."""
    report = {"updated": [], "values_skipped": [], "links_dropped": [], "changed": False}
    for graph in _all_graphs(workflow):
        _apply_group_modules(graph, library, report)
    definitions = (workflow.get("definitions") or {}).get("subgraphs")
    if not isinstance(definitions, list):
        return report
    for index, definition in enumerate(definitions):
        tag = (definition.get("extra") or {}).get(TAG)
        if not isinstance(tag, dict) or not tag.get("name"):
            continue
        module = library.get(tag["name"])
        if not module or not isinstance(module.get("subgraph"), dict):
            continue
        rev = int(module.get("rev", 0))
        if rev <= int(tag.get("rev", 0)):
            continue
        fresh = copy.deepcopy(module["subgraph"])
        fresh["id"] = definition.get("id")
        fresh.setdefault("extra", {})[TAG] = {"name": tag["name"], "rev": rev}
        definitions[index] = fresh
        values = module.get("values") or {}
        for node in _all_nodes(workflow):
            if node.get("type") != fresh["id"]:
                continue
            if not _patch_instance(node, tag["name"], rev, values):
                report["values_skipped"].append(node.get("id"))
        report["updated"].append({"name": tag["name"], "rev": rev})
        report["changed"] = True
    return report



# ----------------------------------------------------------- group merge --
# The root workflow and each subgraph definition are graphs of the same shape
# except for two details: root links are arrays and its counters are
# last_node_id/last_link_id; a definition's links are objects and its counters
# sit under state. The helpers below hide that.

_LINK_INDEX = {"id": 0, "origin_id": 1, "origin_slot": 2, "target_id": 3,
               "target_slot": 4, "type": 5}


def _all_graphs(workflow: dict):
    yield workflow
    for definition in (workflow.get("definitions") or {}).get("subgraphs") or []:
        if isinstance(definition, dict):
            yield definition


def _lk(link, field):
    if isinstance(link, dict):
        return link.get(field)
    index = _LINK_INDEX[field]
    return link[index] if index < len(link) else None


def _lk_set(link, field, value):
    if isinstance(link, dict):
        link[field] = value
    else:
        link[_LINK_INDEX[field]] = value


def _make_link(graph: dict, link_id, origin_id, origin_slot, target_id, target_slot, link_type):
    links = graph.get("links") or []
    as_dict = isinstance(links[0], dict) if links else ("state" in graph)
    if as_dict:
        return {"id": link_id, "origin_id": origin_id, "origin_slot": origin_slot,
                "target_id": target_id, "target_slot": target_slot, "type": link_type}
    return [link_id, origin_id, origin_slot, target_id, target_slot, link_type]


def _int_ids(values):
    out = []
    for value in values:
        try:
            out.append(int(value))
        except (TypeError, ValueError):
            continue
    return out


def _next_node_id(graph: dict) -> int:
    state = graph.get("state") if isinstance(graph.get("state"), dict) else None
    current = max(_int_ids([n.get("id") for n in graph.get("nodes") or []]
                           + [graph.get("last_node_id"), (state or {}).get("lastNodeId")]) or [0])
    new_id = current + 1
    if state is not None:
        state["lastNodeId"] = new_id
    if "last_node_id" in graph or state is None:
        graph["last_node_id"] = new_id
    return new_id


def _next_link_id(graph: dict) -> int:
    state = graph.get("state") if isinstance(graph.get("state"), dict) else None
    current = max(_int_ids([_lk(l, "id") for l in graph.get("links") or []]
                           + [graph.get("last_link_id"), (state or {}).get("lastLinkId")]) or [0])
    new_id = current + 1
    if state is not None:
        state["lastLinkId"] = new_id
    if "last_link_id" in graph or state is None:
        graph["last_link_id"] = new_id
    return new_id


def _pos(node):
    pos = node.get("pos")
    if isinstance(pos, dict):
        pos = [pos.get("0", 0), pos.get("1", 0)]
    return [float(pos[0]), float(pos[1])] if isinstance(pos, (list, tuple)) and len(pos) >= 2 else [0.0, 0.0]


def _size(node):
    size = node.get("size")
    if isinstance(size, dict):
        size = [size.get("0", 200), size.get("1", 100)]
    return [float(size[0]), float(size[1])] if isinstance(size, (list, tuple)) and len(size) >= 2 else [200.0, 100.0]


def _inside(node: dict, bounding) -> bool:
    if not isinstance(bounding, (list, tuple)) or len(bounding) < 4:
        return False
    x, y = _pos(node)
    bx, by, bw, bh = (float(v) for v in bounding[:4])
    return bx <= x <= bx + bw and by <= y <= by + bh


def _containing_group(node: dict, groups: list):
    """The smallest frame the node's top-left corner sits in, or None."""
    best, best_area = None, None
    for index, group in enumerate(groups):
        bounding = group.get("bounding")
        if not _inside(node, bounding):
            continue
        area = float(bounding[2]) * float(bounding[3])
        if best_area is None or area < best_area:
            best, best_area = index, area
    return best


def _slot_index(node: dict, side: str, slot_name):
    for index, slot in enumerate(node.get(side) or []):
        if slot.get("name") == slot_name:
            return index
    return None


def _drop_link(graph: dict, link, other_node: dict | None, other_side: str, other_slot):
    link_id = _lk(link, "id")
    graph["links"] = [l for l in graph.get("links") or [] if _lk(l, "id") != link_id]
    if other_node is None:
        return
    slots = other_node.get(other_side) or []
    if not isinstance(other_slot, int) or other_slot >= len(slots):
        return
    if other_side == "inputs":
        if slots[other_slot].get("link") == link_id:
            slots[other_slot]["link"] = None
    else:
        slots[other_slot]["links"] = [l for l in slots[other_slot].get("links") or [] if l != link_id]


def _apply_group_modules(graph: dict, library: dict, report: dict) -> None:
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return
    tagged = [n for n in nodes if isinstance((n.get("properties") or {}).get(GTAG), dict)]
    if not tagged:
        return
    groups = [g for g in graph.get("groups") or [] if isinstance(g, dict)]
    clusters: dict[tuple, list] = {}
    for node in tagged:
        name = node["properties"][GTAG].get("name")
        clusters.setdefault((name, _containing_group(node, groups)), []).append(node)
    for (name, group_index), members in clusters.items():
        module = library.get(name)
        if not module or not isinstance(module.get("nodes"), list):
            continue
        rev = int(module.get("rev", 0))
        current = min(int(m["properties"][GTAG].get("rev", 0)) for m in members)
        if rev <= current:
            continue
        group = groups[group_index] if group_index is not None else None
        _replace_group_members(graph, group, members, module, rev, report)
        report["updated"].append({"name": name, "rev": rev})
        report["changed"] = True


def _replace_group_members(graph: dict, group: dict | None, members: list,
                           module: dict, rev: int, report: dict) -> None:
    name = module["name"]
    nodes = graph["nodes"]
    links = graph.setdefault("links", [])
    node_by_id = {n.get("id"): n for n in nodes}
    old_by_key = {str(m["properties"][GTAG].get("key")): m for m in members}
    member_ids = {m.get("id") for m in members}
    if group is not None and isinstance(group.get("bounding"), (list, tuple)):
        origin = [float(group["bounding"][0]), float(group["bounding"][1])]
    else:
        origin = [min(_pos(m)[0] for m in members), min(_pos(m)[1] for m in members)]

    # Links touching the old members, classified before anything moves.
    internal_ids, incoming, outgoing = set(), [], []
    for link in links:
        origin_id, target_id = _lk(link, "origin_id"), _lk(link, "target_id")
        if origin_id in member_ids and target_id in member_ids:
            internal_ids.add(_lk(link, "id"))
        elif target_id in member_ids:
            member = node_by_id[target_id]
            slot = _lk(link, "target_slot")
            slots = member.get("inputs") or []
            slot_name = slots[slot].get("name") if isinstance(slot, int) and slot < len(slots) else None
            incoming.append((link, str(member["properties"][GTAG].get("key")), slot_name))
        elif origin_id in member_ids:
            member = node_by_id[origin_id]
            slot = _lk(link, "origin_slot")
            slots = member.get("outputs") or []
            slot_name = slots[slot].get("name") if isinstance(slot, int) and slot < len(slots) else None
            outgoing.append((link, str(member["properties"][GTAG].get("key")), slot_name))
    links[:] = [l for l in links if _lk(l, "id") not in internal_ids]

    # The new members: an existing node keeps its id, place and size; a new
    # one gets a fresh id at its module position. Values follow the snapshot
    # rule, per widget.
    new_by_key: dict[str, dict] = {}
    fresh_nodes = []
    for module_node in module["nodes"]:
        key = str(module_node.get("id"))
        node = copy.deepcopy(module_node)
        for inp in node.get("inputs") or []:
            inp["link"] = None
        for out in node.get("outputs") or []:
            out["links"] = []
        old = old_by_key.get(key)
        module_values = module_node.get("widgets_values")
        if old is not None:
            node["id"] = old["id"]
            node["pos"] = old.get("pos", node.get("pos"))
            if old.get("size") is not None:
                node["size"] = old["size"]
            snapshot = old["properties"][GTAG].get("snapshot")
            old_values = old.get("widgets_values")
            if (isinstance(module_values, list) and isinstance(old_values, list)
                    and isinstance(snapshot, list)
                    and len(module_values) == len(old_values) == len(snapshot)):
                node["widgets_values"] = [
                    copy.deepcopy(module_values[i]) if module_values[i] != snapshot[i]
                    else old_values[i]
                    for i in range(len(module_values))]
            elif isinstance(module_values, list) and isinstance(old_values, list):
                report["values_skipped"].append(old["id"])
                node["widgets_values"] = old_values
        else:
            node["id"] = _next_node_id(graph)
            rel = _pos(module_node)
            node["pos"] = [origin[0] + rel[0], origin[1] + rel[1]]
        node.setdefault("properties", {})[GTAG] = {
            "name": name, "key": key, "rev": rev,
            "snapshot": copy.deepcopy(module_values)}
        new_by_key[key] = node
        fresh_nodes.append(node)

    first_index = min(i for i, n in enumerate(nodes) if n.get("id") in member_ids)
    kept = [n for n in nodes if n.get("id") not in member_ids]
    graph["nodes"] = kept[:first_index] + fresh_nodes + kept[first_index:]
    node_by_id = {n.get("id"): n for n in graph["nodes"]}

    for module_link in module.get("links") or []:
        origin_node = new_by_key.get(str(_lk(module_link, "origin_id")))
        target_node = new_by_key.get(str(_lk(module_link, "target_id")))
        origin_slot, target_slot = _lk(module_link, "origin_slot"), _lk(module_link, "target_slot")
        if origin_node is None or target_node is None:
            continue
        outputs, inputs = origin_node.get("outputs") or [], target_node.get("inputs") or []
        if not isinstance(origin_slot, int) or not isinstance(target_slot, int):
            continue
        if origin_slot >= len(outputs) or target_slot >= len(inputs):
            continue
        link_id = _next_link_id(graph)
        outputs[origin_slot].setdefault("links", []).append(link_id)
        inputs[target_slot]["link"] = link_id
        links.append(_make_link(graph, link_id, origin_node["id"], origin_slot,
                                target_node["id"], target_slot, _lk(module_link, "type")))

    for link, key, slot_name in incoming:
        node = new_by_key.get(key)
        index = _slot_index(node, "inputs", slot_name) if node else None
        if index is None:
            other = node_by_id.get(_lk(link, "origin_id"))
            _drop_link(graph, link, other, "outputs", _lk(link, "origin_slot"))
            links = graph["links"]
            report["links_dropped"].append({"module": name, "key": key, "slot": slot_name})
            continue
        _lk_set(link, "target_id", node["id"])
        _lk_set(link, "target_slot", index)
        node["inputs"][index]["link"] = _lk(link, "id")
    for link, key, slot_name in outgoing:
        node = new_by_key.get(key)
        index = _slot_index(node, "outputs", slot_name) if node else None
        if index is None:
            other = node_by_id.get(_lk(link, "target_id"))
            _drop_link(graph, link, other, "inputs", _lk(link, "target_slot"))
            links = graph["links"]
            report["links_dropped"].append({"module": name, "key": key, "slot": slot_name})
            continue
        _lk_set(link, "origin_id", node["id"])
        _lk_set(link, "origin_slot", index)
        node["outputs"][index].setdefault("links", []).append(_lk(link, "id"))

    if group is not None and isinstance(group.get("bounding"), (list, tuple)) and fresh_nodes:
        pad, title = 12.0, 40.0
        xs = [_pos(n)[0] for n in fresh_nodes]
        ys = [_pos(n)[1] for n in fresh_nodes]
        x2 = [_pos(n)[0] + _size(n)[0] for n in fresh_nodes]
        y2 = [_pos(n)[1] + _size(n)[1] for n in fresh_nodes]
        bx, by, bw, bh = (float(v) for v in group["bounding"][:4])
        # Grow only: a side moves when a node crossed it, never to re-pad.
        nx = min(xs) - pad if min(xs) < bx else bx
        ny = min(ys) - title if min(ys) < by else by
        right = max(x2) + pad if max(x2) > bx + bw else bx + bw
        bottom = max(y2) + pad if max(y2) > by + bh else by + bh
        group["bounding"] = [nx, ny, right - nx, bottom - ny]

# ------------------------------------------------------------------- sync --

def _dump_like(original_text: str, workflow: dict) -> str:
    """Comfy saves workflows compact; hand-formatted files stay indented."""
    indent = 2 if original_text.lstrip().startswith("{\n") else None
    return json.dumps(workflow, indent=indent, ensure_ascii=False)


def sync_workflows(workflows_dir: str, library: dict[str, dict],
                   only_path: str | None = None) -> dict:
    """Rewrite every workflow file under `workflows_dir` (or just `only_path`,
    relative to it) whose modules are stale. Files that are not workflows or
    fail to parse are skipped and reported, never touched."""
    report = {"updated": [], "errors": [], "scanned": 0}
    if not library or not os.path.isdir(workflows_dir):
        return report
    root_real = os.path.realpath(workflows_dir)
    if only_path:
        rel = only_path.replace("\\", "/").lstrip("/")
        if rel.startswith("workflows/"):
            rel = rel[len("workflows/"):]
        candidate = os.path.realpath(os.path.join(workflows_dir, rel))
        if candidate != root_real and not candidate.startswith(root_real + os.sep):
            raise ModuleError("workflow path is outside the workflows directory")
        paths = [candidate] if os.path.isfile(candidate) else []
    else:
        paths = []
        for dirpath, _dirs, files in os.walk(workflows_dir, followlinks=True):
            for filename in sorted(files):
                if filename.endswith(".json"):
                    paths.append(os.path.join(dirpath, filename))
    for path in paths:
        rel = os.path.relpath(path, workflows_dir)
        report["scanned"] += 1
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
            workflow = json.loads(text)
        except (OSError, json.JSONDecodeError) as e:
            report["errors"].append({"path": rel, "error": str(e)})
            continue
        if not isinstance(workflow, dict) or "nodes" not in workflow:
            continue
        result = apply_modules(workflow, library)
        if not result["changed"]:
            continue
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(_dump_like(text, workflow))
        except OSError as e:
            report["errors"].append({"path": rel, "error": str(e)})
            continue
        report["updated"].append({
            "path": rel,
            "modules": result["updated"],
            "values_skipped": result["values_skipped"],
        })
    return report
