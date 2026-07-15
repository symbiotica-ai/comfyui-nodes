# ABOUTME: Hypereel highlight picker node — parses a Gemini highlight list and exposes
# ABOUTME: one highlight's timing + text so it can drive a clip cut and a script LLM.
from ._hypereel_highlights import filter_in_range, parse_highlights


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
            },
            "optional": {
                "source_duration": ("FLOAT", {
                    "default": 0.0, "min": 0.0, "max": 359999.0,
                    "tooltip": "Length of the analyzed video in seconds (wire the Clip "
                               "node's actual_duration). Highlights beyond it are dropped "
                               "— catches absolute-vs-chapter clock mismatches.",
                }),
            },
        }

    RETURN_TYPES = ("FLOAT", "FLOAT", "FLOAT", "STRING", "STRING", "INT")
    RETURN_NAMES = ("start_sec", "end_sec", "duration_sec", "label", "highlight", "count")
    FUNCTION = "pick"
    CATEGORY = "Symbiotica/Hypereel"

    def pick(self, highlights, index, source_duration=0.0):
        parsed = parse_highlights(highlights)
        if not parsed:
            raise ValueError(
                "No highlights found — expected lines like "
                "'HIGHLIGHT 1 | start=120 | end=130 | Label | WHY: ... | MOOD: ...'"
            )
        parsed, dropped = filter_in_range(parsed, source_duration)
        if dropped and not parsed:
            worst = max(h["start"] for h in dropped)
            raise ValueError(
                f"All {len(dropped)} highlights start beyond the {source_duration:.0f}s "
                f"source (worst: {worst:.0f}s) — the analysis and this video use "
                f"different clocks (chapter vs full video?)"
            )
        if dropped:
            print(f"[HypereelHighlightPick] dropped {len(dropped)} out-of-range highlight(s)")
        h = parsed[min(index, len(parsed) - 1)]
        return (h["start"], h["end"], h["end"] - h["start"], h["label"], h["line"], len(parsed))


NODE_CLASS_MAPPINGS = {
    "HypereelHighlightPick": HypereelHighlightPick,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HypereelHighlightPick": "Hypereel Highlight Pick",
}
