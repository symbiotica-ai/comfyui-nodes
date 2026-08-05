# ABOUTME: Resolves an order's asset types to the architect system prompts kept
# ABOUTME: one per type under <project>/prompts/<Exact Category Name>.md.
import os


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


def read_named_blocks(directory):
    """The `.md` blocks of one folder as (filename, text), in filename order.

    Filename order so the numeric prefixes (`01-`, `02-`) decide composition
    order without anything in code knowing the block names. Blank files are
    dropped, and a missing directory yields nothing rather than raising: an
    absent folder means this project has not been split into blocks yet.
    """
    try:
        names = sorted(n for n in os.listdir(directory) if n.endswith(".md"))
    except OSError:
        return []
    blocks = []
    for name in names:
        try:
            with open(os.path.join(directory, name), encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        if text.strip():
            blocks.append((name, text.strip()))
    return blocks


def read_rule_blocks(project_path):
    """The shared rule blocks, in filename order, blanks dropped."""
    return [text for _, text in read_named_blocks(rules_dir(project_path))]


def compose_image_prompt(project_path):
    """The image model's system prompt: every `_image/` block, in order.

    Empty when the folder is absent, because the node carrying this output is
    also the editor that creates the folder — it has to load before the blocks
    it edits exist. The architect prompts raise on absence instead; they are
    read by a node that can do nothing without them.
    """
    return "\n\n".join(
        text for _, text in read_named_blocks(image_dir(project_path)))


def compose_prompt(rule_blocks, type_block):
    """Shared rules first, the asset type's own block LAST.

    Last because it is the most specific instruction and the tail of a long
    prompt is where a model weights most heavily — a type that contradicts a
    game-wide default (a wall decoration anchoring differently) has to win.
    """
    parts = [b.strip() for b in rule_blocks if b and b.strip()]
    parts.append(type_block.strip())
    return "\n\n".join(parts)


def compose_detail(project_path, category):
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
    rules = read_named_blocks(rules_dir(project_path))
    path = os.path.join(prompts_dir(project_path), f"{cat}.md")
    try:
        with open(path, encoding="utf-8") as fh:
            type_text = fh.read()
    except OSError:
        type_text = ""
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
