# ABOUTME: Split Prompts node — one string of blank-line-separated paragraphs
# ABOUTME: in, a list of prompts out, so the graph runs once per paragraph.
from ._split_prompts import split_prompts


class SplitPrompts:
    """Feed it a block of prompts separated by empty lines and it emits them as
    a list. Downstream nodes run once per prompt from a single queue press."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {
                    "multiline": True, "default": "",
                    "tooltip": "Prompts separated by an empty line.",
                }),
                "remove_empty_breakline": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Delete the empty line between prompts. Off "
                               "keeps a trailing empty line on each prompt.",
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("prompts",)
    OUTPUT_IS_LIST = (True,)
    FUNCTION = "execute"
    CATEGORY = "Symbiotica/Text"
    DESCRIPTION = ("Split a block of empty-line-separated paragraphs into a "
                   "list of prompts, one per paragraph.")

    def execute(self, text="", remove_empty_breakline=True):
        prompts = split_prompts(text, remove_empty_breakline)
        if not prompts:
            raise ValueError("no prompts found: separate paragraphs with an empty line")
        return (prompts,)


NODE_CLASS_MAPPINGS = {"SplitPrompts": SplitPrompts}
NODE_DISPLAY_NAME_MAPPINGS = {"SplitPrompts": "Split Prompts"}
