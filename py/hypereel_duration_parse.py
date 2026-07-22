# ABOUTME: Hypereel duration parse node — splits the script LLM's trailing
# ABOUTME: "DURATION: N" line into the clean video prompt plus a seconds value.
from ._hypereel_duration import parse_duration


class HypereelDurationParse:
    """Reads the script LLM's output, strips the trailing `DURATION: N` line and
    returns the clean prompt plus the clamped seconds (4-15, default 12 when the
    line is missing). Wire the prompt onward to the References concat and the
    seconds into the video node's duration input (convert widget to input)."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "script": ("STRING", {"forceInput": True, "tooltip": "The script LLM's raw output."}),
            }
        }

    RETURN_TYPES = ("STRING", "INT", "FLOAT")
    RETURN_NAMES = ("prompt", "seconds", "seconds_float")
    FUNCTION = "parse"
    CATEGORY = "Symbiotica/Hypereel"

    def parse(self, script):
        prompt, seconds = parse_duration(script)
        return (prompt, seconds, float(seconds))


NODE_CLASS_MAPPINGS = {
    "HypereelDurationParse": HypereelDurationParse,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HypereelDurationParse": "Hypereel Duration Parse (script to prompt + seconds)",
}
