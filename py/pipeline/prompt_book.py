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


def rules_dir(project_path):
    """The game-wide rules every asset type is composed with."""
    return os.path.join(prompts_dir(project_path), RULES_DIR)


def read_rule_blocks(project_path):
    """The shared rule blocks, in filename order, blanks dropped.

    Ordered by filename so the numeric prefixes (`01-`, `02-`) decide the order
    of the composed prompt without anything in code knowing the rule names. A
    missing directory is not an error: it means this project has not been split
    into blocks yet, and composing then yields the type's own file exactly as
    before.
    """
    root = rules_dir(project_path)
    try:
        names = sorted(n for n in os.listdir(root) if n.endswith(".md"))
    except OSError:
        return []
    blocks = []
    for name in names:
        try:
            with open(os.path.join(root, name), encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        if text.strip():
            blocks.append(text.strip())
    return blocks


def compose_prompt(rule_blocks, type_block):
    """Shared rules first, the asset type's own block LAST.

    Last because it is the most specific instruction and the tail of a long
    prompt is where a model weights most heavily — a type that contradicts a
    game-wide default (a wall decoration anchoring differently) has to win.
    """
    parts = [b.strip() for b in rule_blocks if b and b.strip()]
    parts.append(type_block.strip())
    return "\n\n".join(parts)


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
