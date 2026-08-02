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
    texts, missing = {}, []
    for cat in dict.fromkeys(c.strip() for c in categories):
        path = os.path.join(root, f"{cat}.md")
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            text = ""
        if text.strip():
            texts[cat] = text
        else:
            missing.append((cat, path))
    if missing:
        raise MissingPromptsError(sorted(missing))
    return [texts[c.strip()] for c in categories]
