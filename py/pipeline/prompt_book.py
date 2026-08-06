# ABOUTME: Resolves an order's asset types to the architect system prompts kept
# ABOUTME: one per type under <project>/prompts/<Exact Category Name>.md.
import json
import os
import re


class MissingPromptsError(Exception):
    """Asset types with no usable prompt file. `missing` is [(category, path)],
    sorted, so the message names every offender in one go — a run that fails,
    gets one file written, and fails on the next type wastes the same minute
    repeatedly."""

    def __init__(self, missing):
        self.missing = missing
        width = max((len(c) for c, _ in missing), default=0)
        lines = "\n".join(f"  {c:<{width}}  ->  {p}" for c, p in missing)
        noun = "type" if len(missing) == 1 else "types"
        super().__init__(f"no architect prompt for {len(missing)} asset "
                         f"{noun} in this order:\n{lines}")


def prompts_dir(project_path):
    """The prompt book lives beside the project's orders and templates."""
    return os.path.join(project_path, "prompts")


RULES_DIR = "_rules"
IMAGE_DIR = "_image"


def rules_dir(project_path):
    """The game-wide rules every asset type is composed with."""
    return os.path.join(prompts_dir(project_path), RULES_DIR)


def image_dir(project_path):
    """The system prompt handed to the IMAGE model, not to the architect.

    A second document, kept in the book beside the rules so one panel edits
    both: the architect writes what the asset is, this one fixes how it is
    drawn. Blocks rather than a single file, so the same numeric-prefix
    ordering works here the day it needs splitting.
    """
    return os.path.join(prompts_dir(project_path), IMAGE_DIR)


VERSION_MARK = re.compile(r"^[ \t]*<!--\s*version:\s*([^>]+?)\s*-->[ \t]*$",
                          re.MULTILINE)


def split_versions(text):
    """A block file's versions, [(name, body)] in file order.

    Versions live INSIDE the block file, split by marker lines:

        <!-- version: tight -->

    A file with no markers is one unnamed version — the whole file — so every
    pre-versions block composes byte-identically to before. Non-blank text
    above the first marker is an unnamed version too. Blank bodies are dropped
    the same way blank files are.
    """
    text = str(text or "")
    marks = list(VERSION_MARK.finditer(text))
    if not marks:
        return [("", text)] if text.strip() else []
    out = []
    lead = text[:marks[0].start()]
    if lead.strip():
        out.append(("", lead))
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[mark.end():end]
        if body.strip():
            out.append((mark.group(1).strip(), body))
    return out


def pick_version(text, name=""):
    """One version's body, stripped. No name — or a name the file no longer
    has — falls back to the FIRST version: the top of the file is the active
    text, and a stale pin must degrade to that, not kill the queue."""
    versions = split_versions(text)
    if not versions:
        return ""
    if name:
        for vname, body in versions:
            if vname == name:
                return body.strip()
    return versions[0][1].strip()


def parse_recipe(text):
    """{block name: version name} from the Recipe node's widget: a JSON
    object, or `block = version` lines. Malformed lines are skipped — a
    half-typed pin must not kill the queue, and an unknown version already
    degrades to the block's top version in pick_version."""
    text = str(text or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return {str(k).strip(): str(v).strip() for k, v in data.items()}
    except ValueError:
        pass
    pins = {}
    for line in text.splitlines():
        key, sep, val = line.partition("=")
        if sep and key.strip() and val.strip():
            pins[key.strip()] = val.strip()
    return pins


def list_versions(project_path):
    """Every block with its version names, in composition order — rules,
    image, types. Names only: the Recipe panel pins by name, and the Block
    node is where a version's text is previewed."""
    out = []
    for directory, prefix in ((rules_dir(project_path), f"{RULES_DIR}/"),
                              (image_dir(project_path), f"{IMAGE_DIR}/"),
                              (prompts_dir(project_path), "")):
        try:
            names = sorted(n for n in os.listdir(directory)
                           if n.endswith(".md"))
        except OSError:
            continue
        for name in names:
            try:
                with open(os.path.join(directory, name),
                          encoding="utf-8") as fh:
                    text = fh.read()
            except OSError:
                continue
            versions = split_versions(text)
            if versions:
                out.append({"name": f"{prefix}{name}",
                            "versions": [v for v, _ in versions]})
    return out


def read_named_blocks(directory, prefix="", recipe=None):
    """The `.md` blocks of one folder as (filename, active text), in filename
    order.

    Filename order so the numeric prefixes (`01-`, `02-`) decide composition
    order without anything in code knowing the block names. Blank files are
    dropped, and a missing directory yields nothing rather than raising: an
    absent folder means this project has not been split into blocks yet.

    Each file contributes ONE version of itself: the one `recipe` pins under
    `prefix + filename`, else its first. A file without version markers is its
    own single version, unchanged behaviour.
    """
    try:
        names = sorted(n for n in os.listdir(directory) if n.endswith(".md"))
    except OSError:
        return []
    recipe = recipe or {}
    blocks = []
    for name in names:
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        text = pick_version(text, recipe.get(f"{prefix}{name}", ""))
        if text:
            blocks.append((name, text))
    return blocks


def read_rule_blocks(project_path, recipe=None):
    """The shared rule blocks, in filename order, blanks dropped."""
    return [text for _, text in read_named_blocks(
        rules_dir(project_path), f"{RULES_DIR}/", recipe)]


def compose_image_prompt(project_path, recipe=None):
    """The image model's system prompt: every `_image/` block, in order.

    Empty when the folder is absent, because the node carrying this output is
    also the editor that creates the folder — it has to load before the blocks
    it edits exist. The architect prompts raise on absence instead; they are
    read by a node that can do nothing without them.
    """
    return "\n\n".join(
        text for _, text in read_named_blocks(
            image_dir(project_path), f"{IMAGE_DIR}/", recipe))


def compose_prompt(rule_blocks, type_block):
    """Shared rules first, the asset type's own block LAST.

    Last because it is the most specific instruction and the tail of a long
    prompt is where a model weights most heavily — a type that contradicts a
    game-wide default (a wall decoration anchoring differently) has to win.
    """
    parts = [b.strip() for b in rule_blocks if b and b.strip()]
    parts.append(type_block.strip())
    return "\n\n".join(parts)


def compose_detail(project_path, category, recipe=None):
    """One asset type's composed prompt, plus the blocks that built it.

    The text comes out of the same `read_named_blocks` + `compose_prompt` pair
    the queue runs, and is returned verbatim — no separators, no headings. A
    preview that reassembled the prompt its own way would be trusted and wrong
    on the day the two drifted, which is exactly the day it would be consulted.
    The block list is metadata alongside the text, not markers inside it.
    """
    cat = str(category or "").strip()
    if not cat:
        raise ValueError("no asset type to compose — pick one")
    recipe = recipe or {}
    rules = read_named_blocks(rules_dir(project_path), f"{RULES_DIR}/", recipe)
    path = os.path.join(prompts_dir(project_path), f"{cat}.md")
    try:
        with open(path, encoding="utf-8") as fh:
            type_text = fh.read()
    except OSError:
        type_text = ""
    type_text = pick_version(type_text, recipe.get(f"{cat}.md", ""))
    if not type_text.strip():
        raise MissingPromptsError([(cat, path)])
    text = compose_prompt([t for _, t in rules], type_text)
    blocks = [{"name": f"{RULES_DIR}/{n}", "chars": len(t)} for n, t in rules]
    blocks.append({"name": f"{cat}.md", "chars": len(type_text.strip())})
    return {"text": text, "blocks": blocks}


def resolve_category_prompts(project_path, categories):
    """One prompt text per category, in the order given — repeats included, so
    the result lines up with the sheets the categories came from.

    Each file is read once however many sheets share its type. There is no
    default: a stand-in prompt renders plausible assets in the wrong style and
    spends real credits doing it, so an absent, empty, or whitespace-only file
    raises instead."""
    blank = [c for c in categories if not (c or "").strip()]
    if blank:
        raise ValueError(
            f"{len(blank)} sheet(s) carry a blank asset type — the order sheet "
            "has rows with no category, so there is nothing to look up")
    # The filename IS the category, verbatim: "Food - 3 stages.md", not a slug.
    # One name, one file — so the folder reads as the order sheet's own type
    # list and there is no transform to get wrong in either direction.
    root = prompts_dir(project_path)
    # Read once for the whole order: the shared blocks are the same for every
    # type, so composing per category must not re-read them per category.
    rule_blocks = read_rule_blocks(project_path)
    texts, missing = {}, []
    for cat in dict.fromkeys(c.strip() for c in categories):
        path = os.path.join(root, f"{cat}.md")
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            text = ""
        text = pick_version(text)
        if text.strip():
            texts[cat] = compose_prompt(rule_blocks, text)
        else:
            # A type with no block of its own has nothing to say, even when the
            # shared rules would compose — the shared half describes the game,
            # not this asset.
            missing.append((cat, path))
    if missing:
        raise MissingPromptsError(sorted(missing))
    return [texts[c.strip()] for c in categories]


def compose_recipe(project_path, category, recipe=None):
    """Both composed prompts under one recipe: the architect system prompt for
    `category` and the image model's system prompt. Unpinned blocks compose
    their top version, so an empty recipe equals the book as-is."""
    recipe = recipe or {}
    detail = compose_detail(project_path, category, recipe)
    return {"system_prompt": detail["text"],
            "image_prompt": compose_image_prompt(project_path, recipe)}


def compose_indexed(project_path, category, index=1):
    """Both composed prompts at one version slot: every block contributes its
    `index`-th version (1-based), or its top one when it has fewer. Slot 1 is
    therefore always the book exactly as it stands."""
    idx = max(1, int(index or 1))
    recipe = {}
    for block in list_versions(project_path):
        names = block["versions"]
        if idx <= len(names):
            recipe[block["name"]] = names[idx - 1]
    return compose_recipe(project_path, category, recipe)
