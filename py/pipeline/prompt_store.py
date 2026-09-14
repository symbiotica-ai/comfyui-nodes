# ABOUTME: Read/write access to a folder of prompt files for the Prompts panel —
# ABOUTME: listing, reading, saving and sub-folder creation, confined to the folder.
import json
import os

from .prompt_book import list_recipes, prompts_dir, read_recipe, recipes_dir

# What the Prompts node lists and edits. Anything else in the folder — backups,
# recipes, images — is not a prompt and stays out of the dropdown.
TEXT_SUFFIXES = (".md", ".txt")


class PromptPathError(Exception):
    """A name that does not resolve inside the prompt folder."""


def _root(folder):
    if not str(folder or "").strip():
        raise PromptPathError("no folder")
    return os.path.realpath(str(folder).strip())


def _inside(root, name, what):
    """`root/name`, or raise when the name climbs out of the root."""
    name = str(name or "").strip().replace("\\", "/")
    if not name:
        raise PromptPathError(f"no {what} name")
    path = os.path.realpath(os.path.join(root, name))
    if path != root and not path.startswith(root + os.sep):
        raise PromptPathError(f"outside the folder: {name!r}")
    return path


def resolve_file(folder, name):
    """The absolute path of one prompt file, or raise.

    `name` is relative to the folder and may sit in any sub-folder
    (`_rules/03-light.md`). Containment is by realpath, so a crafted name
    cannot climb out and hand the editor an arbitrary file to overwrite. The
    extension is checked too: this editor writes prompts, and a name ending in
    anything else is a mistake worth refusing rather than guessing at.
    """
    root = _root(folder)
    clean = str(name or "").strip().replace("\\", "/")
    if not clean.lower().endswith(TEXT_SUFFIXES):
        raise PromptPathError(f"not a prompt file: {name!r}")
    path = _inside(root, clean, "file")
    if path == root:
        raise PromptPathError(f"not a prompt file: {name!r}")
    return path


def list_files(folder):
    """Every prompt file under the folder, as sorted paths relative to it.
    Dot-folders and dot-files are skipped. A folder that is not there lists
    nothing — the panel says so, the queue does not need to."""
    try:
        root = _root(folder)
    except PromptPathError:
        return []
    if not os.path.isdir(root):
        return []
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and d != "__pycache__")
        for fname in filenames:
            if fname.startswith("."):
                continue
            if fname.lower().endswith(TEXT_SUFFIXES):
                rel = os.path.relpath(os.path.join(dirpath, fname), root)
                found.append(rel.replace(os.sep, "/"))
    return sorted(found)


def list_folders(folder):
    """Every sub-folder under the folder, as sorted paths relative to it, so a
    dropdown can offer them — nobody should have to guess-type a folder name.
    Dot-folders are skipped. Empty folders are listed: a folder just made has
    nothing in it yet and is exactly the one about to be picked."""
    try:
        root = _root(folder)
    except PromptPathError:
        return []
    if not os.path.isdir(root):
        return []
    found = []
    for dirpath, dirnames, _ in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and d != "__pycache__")
        for d in dirnames:
            rel = os.path.relpath(os.path.join(dirpath, d), root)
            found.append(rel.replace(os.sep, "/"))
    return sorted(found)


def read_file(folder, name):
    path = resolve_file(folder, name)
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        raise PromptPathError(f"cannot read {name!r}: {exc}") from exc


def write_file(folder, name, text):
    """Save one file, keeping a single .bak of what it replaced.

    One backup, not a version history: this editor is for tightening a prompt
    in place, and the backup is never listed.
    """
    path = resolve_file(folder, name)
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
    return {"name": str(name).strip().replace("\\", "/"), "chars": len(body)}


def make_folder(folder, name):
    """Create a sub-folder inside the prompt folder. Existing is fine."""
    root = _root(folder)
    clean = str(name or "").strip().replace("\\", "/").strip("/")
    path = _inside(root, clean, "folder")
    if path == root:
        raise PromptPathError(f"no folder name")
    os.makedirs(path, exist_ok=True)
    return {"name": clean}


def rename(folder, src, dst):
    """Rename a file or a sub-folder inside the prompt folder. The target must
    not exist — a rename that lands on another prompt would delete it — and a
    file keeps a prompt extension."""
    root = _root(folder)
    src_rel = str(src or "").strip().replace("\\", "/").strip("/")
    dst_rel = str(dst or "").strip().replace("\\", "/").strip("/")
    src_path = _inside(root, src_rel, "source")
    dst_path = _inside(root, dst_rel, "target")
    if src_path == root or dst_path == root:
        raise PromptPathError("the path itself cannot be renamed")
    if not os.path.exists(src_path):
        raise PromptPathError(f"nothing called {src_rel!r}")
    if os.path.isfile(src_path) and not dst_rel.lower().endswith(TEXT_SUFFIXES):
        raise PromptPathError(f"not a prompt file: {dst_rel!r}")
    if os.path.exists(dst_path):
        raise PromptPathError(f"{dst_rel!r} already exists")
    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
    os.rename(src_path, dst_path)
    return {"from": src_rel, "to": dst_rel}


# --- recipes, kept for the Recipes tooling -------------------------------------

def resolve(project_path, name, subfolder=None):
    """A block name checked against the project's prompt book."""
    if not str(project_path or "").strip():
        raise PromptPathError("no project")
    return resolve_file(prompts_dir(project_path, subfolder), name)


def recipes(project_path, subfolder=None):
    """Every saved preset with its slots."""
    return [{"name": n, "slots": read_recipe(project_path, n, subfolder)}
            for n in list_recipes(project_path, subfolder)]


def write_recipe(project_path, name, slots, subfolder=None):
    """Save one preset. The block names are checked against the book the same
    way a file save is — a recipe that can name any path on disk would make
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
        # raises when it is not in the book
        resolve(project_path, block, subfolder)
        clean.append({"block": block,
                      "version": str((slot or {}).get("version", "")
                                     or "").strip()})
    directory = recipes_dir(project_path, subfolder)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{name}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"slots": clean}, fh, indent=2)
        fh.write("\n")
    return {"name": name, "slots": clean}


def delete_recipe(project_path, name, subfolder=None):
    """Remove one preset. The blocks it named stay — a recipe is a pointer."""
    name = str(name or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        raise PromptPathError(f"not a recipe name: {name!r}")
    path = os.path.join(recipes_dir(project_path, subfolder), f"{name}.json")
    try:
        os.remove(path)
    except OSError:
        return {"name": name, "removed": False}
    return {"name": name, "removed": True}
