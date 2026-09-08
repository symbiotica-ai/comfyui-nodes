# ABOUTME: Pure paragraph splitter for the Split Prompts node — no ComfyUI imports.
# ABOUTME: One paragraph per item, blank lines optionally kept on each item.
import re

_BLANK_LINE = re.compile(r"\n[ \t]*\n+")


def split_prompts(text, remove_empty_breakline=True):
    """Split blank-line-separated paragraphs into a list, one prompt each.

    With `remove_empty_breakline` on, every prompt is stripped so the empty
    line between paragraphs is gone. Off, each prompt keeps a trailing empty
    line. Paragraphs that are only whitespace are dropped either way.
    """
    if not text:
        return []
    chunks = _BLANK_LINE.split(text.replace("\r\n", "\n"))
    prompts = []
    for chunk in chunks:
        body = chunk.strip()
        if not body:
            continue
        prompts.append(body if remove_empty_breakline else body + "\n\n")
    return prompts
