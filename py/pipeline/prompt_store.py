# ABOUTME: Read/write access to a project's prompt book for the editor panel —
# ABOUTME: confined to <project>/prompts/, shared _rules/ blocks and type blocks.
import json
import os

from .prompt_book import (BLOCK_DIRS, FLIP_DIR, IMAGE_DIR, RECIPES_DIR,
                          RULES_DIR, list_recipes, prompts_dir, read_recipe,
                          recipes_dir)


class PromptPathError(Exception):
    """A name that does not resolve inside the project's prompt book."""


def _root(project_path):
    return os.path.realpath(prompts_dir(project_path))


def resolve(project_path, name):
    """The absolute path of one prompt file, or raise.

    `name` is a type block (`Chair.md`), a shared rule
    (`_rules/03-unified-lighting.md`) or an image-model block
    (`_image/01-image-model.md`) — nothing else. Containment is by
    realpath, the same rule the reference browser applies, so a crafted name
    cannot climb out of the book and hand the editor an arbitrary file to
    overwrite. The extension is checked too: this editor writes prompts, and a
    name ending in anything else is a mistake worth refusing rather than
    guessing at.
    """
    if not str(project_path or "").strip():
        raise PromptPathError("no project")
    name = str(name or "").strip().replace("\\", "/")
    if not name or not name.endswith(".md"):
        raise PromptPathError(f"not a prompt file: {name!r}")
    root = _root(project_path)
    path = os.path.realpath(os.path.join(root, name))
    if path != root and not path.startswith(root + os.sep):
        raise PromptPathError(f"outside the prompt book: {name!r}")
    parent = os.path.dirname(path)
    folders = (root,) + tuple(os.path.join(root, d) for d in BLOCK_DIRS)
    if parent not in folders:
        raise PromptPathError(
            "prompts live in the book or its "
            + ", ".join(f"{d}/" for d in BLOCK_DIRS)
            + f" folders: {name!r}")
    return path


def list_book(project_path):
    """Every editable block: the shared rules first, in composition order, then
    the image-model blocks, then the per-type blocks. Each entry carries the
    size so the panel can show what it is about to open without reading all of
    them."""
    root = _root(project_path)

    def entries(directory, prefix):
        try:
            names = sorted(n for n in os.listdir(directory)
                           if n.endswith(".md"))
        except OSError:
            return []
        out = []
        for n in names:
            p = os.path.join(directory, n)
            try:
                size = os.path.getsize(p)
            except OSError:
                continue
            out.append({"name": f"{prefix}{n}", "title": n[:-3], "chars": size})
        return out

    return {
        "rules": entries(os.path.join(root, RULES_DIR), f"{RULES_DIR}/"),
        "image": entries(os.path.join(root, IMAGE_DIR), f"{IMAGE_DIR}/"),
        "flip": entries(os.path.join(root, FLIP_DIR), f"{FLIP_DIR}/"),
        "types": entries(root, ""),
    }


def recipes(project_path):
    """Every saved preset with its slots, so the Recipe panel fills its
    dropdowns from one request."""
    return [{"name": n, "slots": read_recipe(project_path, n)}
            for n in list_recipes(project_path)]


def write_recipe(project_path, name, slots):
    """Save one preset. The block names are checked against the book the same
    way a block save is — a recipe that can name any path on disk would make
    the reader a file-read primitive."""
    name = str(name or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise PromptPathError(f"not a recipe name: {name!r}")
    clean = []
    for slot in slots or []:
        block = str((slot or {}).get("block", "") or "").strip()
        if not block:
            clean.append({"block": "", "version": ""})
            continue
        resolve(project_path, block)   # raises when it is not in the book
        clean.append({"block": block,
                      "version": str((slot or {}).get("version", "")
                                     or "").strip()})
    directory = recipes_dir(project_path)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{name}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"slots": clean}, fh, indent=2)
        fh.write("\n")
    return {"name": name, "slots": clean}


def delete_recipe(project_path, name):
    """Remove one preset. The blocks it named stay — a recipe is a pointer."""
    name = str(name or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise PromptPathError(f"not a recipe name: {name!r}")
    path = os.path.join(recipes_dir(project_path), f"{name}.json")
    try:
        os.remove(path)
    except OSError:
        return {"name": name, "removed": False}
    return {"name": name, "removed": True}


def read_block(project_path, name):
    path = resolve(project_path, name)
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise PromptPathError(f"cannot read {name!r}: {exc}") from exc


def write_block(project_path, name, text):
    """Save one block, keeping a single .bak of what it replaced.

    One backup, not a version history: this editor is for tightening a rule in
    place, and the history that matters — which prompt produced which image —
    is provenance's job, not a pile of timestamped copies here.
    """
    path = resolve(project_path, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as fh:
                previous = fh.read()
            with open(path + ".bak", "w", encoding="utf-8") as fh:
                fh.write(previous)
        except OSError:
            pass
    body = str(text or "")
    if body and not body.endswith("\n"):
        body += "\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return {"name": name, "chars": len(body)}
