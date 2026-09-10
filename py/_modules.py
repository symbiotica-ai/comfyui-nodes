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
        if name and isinstance(module.get("subgraph"), dict):
            library[name] = module
    return library


def list_modules(lib_dir: str) -> list[dict]:
    return [
        {"name": m["name"], "rev": int(m.get("rev", 0)), "updated": m.get("updated")}
        for m in load_library(lib_dir).values()
    ]


def write_module(lib_dir: str, name: str, subgraph: dict, values: dict,
                 instance: dict | None) -> dict:
    """Publish: the next revision of a module. The stored subgraph carries its
    own tag so a workflow that receives it is linked from the start."""
    if not isinstance(subgraph, dict) or not isinstance(subgraph.get("nodes"), list):
        raise ModuleError("subgraph definition missing")
    name = str(name).strip()
    if not name:
        raise ModuleError("module name is empty")
    existing = read_module(lib_dir, name)
    rev = int(existing.get("rev", 0)) + 1 if existing else 1
    subgraph = copy.deepcopy(subgraph)
    subgraph.setdefault("extra", {})
    subgraph["extra"][TAG] = {"name": name, "rev": rev}
    module = {
        "name": name,
        "rev": rev,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "subgraph": subgraph,
        "values": dict(values or {}),
        "instance": instance,
    }
    os.makedirs(lib_dir, exist_ok=True)
    with open(_module_path(lib_dir, name), "w", encoding="utf-8") as f:
        json.dump(module, f, indent=2)
    return {"name": name, "rev": rev}


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
    report = {"updated": [], "values_skipped": [], "changed": False}
    definitions = (workflow.get("definitions") or {}).get("subgraphs")
    if not isinstance(definitions, list):
        return report
    for index, definition in enumerate(definitions):
        tag = (definition.get("extra") or {}).get(TAG)
        if not isinstance(tag, dict) or not tag.get("name"):
            continue
        module = library.get(tag["name"])
        if not module:
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
