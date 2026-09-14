# ABOUTME: The pinned API graphs a Modal render can run, and how a node's widget
# ABOUTME: values are bound into one. Shared by the Modal Render node and the RNP server.
import copy
import json
import os

# Where the pinned graphs live. The RNP server ships the same files to a
# different path and points here through the environment.
RECIPE_DIR = (os.environ.get("SYMBIOTICA_MODAL_RECIPES")
              or os.path.join(os.path.dirname(os.path.dirname(
                  os.path.abspath(__file__))), "modal_workflows"))
SUFFIX = ".api.json"
MANIFEST_KEY = "_symbiotica"


def recipes(recipe_dir=None):
    """Recipe names, one per pinned graph file, in name order."""
    root = recipe_dir or RECIPE_DIR
    try:
        names = os.listdir(root)
    except OSError:
        return []
    return sorted(n[:-len(SUFFIX)] for n in names if n.endswith(SUFFIX))


def load(name, recipe_dir=None):
    """One pinned graph by recipe name, manifest included and checked."""
    root = recipe_dir or RECIPE_DIR
    path = os.path.join(root, name + SUFFIX)
    if not os.path.isfile(path):
        raise ValueError(
            f"no Modal recipe named {name!r}; the pack has "
            f"{', '.join(recipes(root)) or 'none'}")
    with open(path, "r", encoding="utf-8") as f:
        graph = json.load(f)
    manifest(graph)
    return graph


def manifest(graph):
    """The `_symbiotica` block, or a reason the graph cannot be a recipe.

    Checked when loaded rather than when bound: a bind path naming a node
    that is not there would otherwise fail on the canvas as a KeyError,
    after the render was already queued in the user's mind."""
    block = graph.get(MANIFEST_KEY)
    if not isinstance(block, dict):
        raise ValueError(f"recipe has no {MANIFEST_KEY} block")
    inputs = block.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("recipe manifest declares no inputs")
    names = set()
    for spec in inputs:
        if (not isinstance(spec, list) or len(spec) < 2
                or not isinstance(spec[0], str) or not isinstance(spec[1], str)):
            raise ValueError(f"malformed recipe input {spec!r}")
        names.add(spec[0])
    bind = block.get("bind") or {}
    for name, target in bind.items():
        if name not in names:
            raise ValueError(f"recipe binds {name!r}, which is not an input")
        if (not isinstance(target, list) or len(target) != 2
                or str(target[0]) not in graph
                or target[1] not in (graph[str(target[0])].get("inputs") or {})):
            raise ValueError(
                f"recipe input {name!r} binds to {target!r}, which the graph "
                f"does not have")
    return block


def input_specs(graph):
    """The inputs a recipe takes, as (name, type, options) triples."""
    out = []
    for spec in manifest(graph)["inputs"]:
        options = spec[2] if len(spec) > 2 and isinstance(spec[2], dict) else {}
        out.append((spec[0], spec[1], dict(options)))
    return out


def defaults(graph):
    """Every input's default, so a caller can fill what it did not set."""
    return {name: options.get("default") for name, _, options in input_specs(graph)}


def bind(graph, values, strict=False):
    """The API graph ComfyUI runs, with `values` written into the bound inputs.

    Values the recipe does not bind are ignored unless `strict`, so a node
    with a fixed set of widgets can drive any recipe. The manifest block is
    dropped: ComfyUI rejects a prompt with a node that has no class_type."""
    block = manifest(graph)
    bound = copy.deepcopy(graph)
    del bound[MANIFEST_KEY]
    binds = block.get("bind") or {}
    for name, value in values.items():
        target = binds.get(name)
        if target is None:
            if strict:
                raise ValueError(f"recipe has no input named {name!r}")
            continue
        bound[str(target[0])]["inputs"][target[1]] = value
    return bound
