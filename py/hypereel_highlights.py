# ABOUTME: Hypereel highlight picker node — parses a Gemini highlight list and exposes
# ABOUTME: one highlight's timing + text so it can drive a clip cut and a script LLM.
from ._hypereel_highlights import parse_highlights


class HypereelHighlightPick:
    """Parses the Gemini highlights text (HIGHLIGHT n | start=.. | end=.. | label |
    WHY:.. | MOOD:..; seconds or MM:SS) and returns the highlight at `index`. The
    timing drives Hypereel Clip; `highlight` is the row to hand the script LLM."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "highlights": ("STRING", {"multiline": True, "default": ""}),
                "index": ("INT", {"default": 0, "min": 0, "max": 99}),
            }
        }

    RETURN_TYPES = ("FLOAT", "FLOAT", "FLOAT", "STRING", "STRING", "INT")
    RETURN_NAMES = ("start_sec", "end_sec", "duration_sec", "label", "highlight", "count")
    FUNCTION = "pick"
    CATEGORY = "Symbiotica/Hypereel"

    def pick(self, highlights, index):
        parsed = parse_highlights(highlights)
        if not parsed:
            raise ValueError(
                "No highlights found — expected lines like "
                "'HIGHLIGHT 1 | start=120 | end=130 | Label | WHY: ... | MOOD: ...'"
            )
        h = parsed[min(index, len(parsed) - 1)]
        return (h["start"], h["end"], h["end"] - h["start"], h["label"], h["line"], len(parsed))


NODE_CLASS_MAPPINGS = {
    "HypereelHighlightPick": HypereelHighlightPick,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HypereelHighlightPick": "Hypereel Highlight Pick",
}
