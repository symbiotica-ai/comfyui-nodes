# ABOUTME: Hypereel ad prompt node — assembles the whole script-LLM input (product +
# ABOUTME: creator binding + presets) and carries the baked system prompt. Zero glue.
from ._hypereel_presets import HOOKS, SETTINGS, STYLES, SYSTEM_PROMPT, build_ad_prompt


class HypereelAdPrompt:
    """Platform-parity input: wire the scrape summary in, pick style/hook/setting,
    optionally type a persona - the node emits the complete user prompt AND the
    production system prompt for the script LLM. The creator photo goes to the
    video node's reference slot 1; this node writes the matching @Image1 binding."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "product_summary": ("STRING", {"forceInput": True}),
                "style": (list(STYLES.keys()),),
                "hook": (list(HOOKS.keys()),),
                "setting": (list(SETTINGS.keys()),),
            },
            "optional": {
                "persona": ("STRING", {"default": "", "multiline": True,
                                       "tooltip": "Optional creator persona, e.g. 'dry humor, low energy'."}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("user_prompt", "system_prompt")
    FUNCTION = "build"
    CATEGORY = "Symbiotica/Hypereel"

    def build(self, product_summary, style, hook, setting, persona=""):
        return (build_ad_prompt(product_summary, style, hook, setting, persona),
                SYSTEM_PROMPT)


NODE_CLASS_MAPPINGS = {
    "HypereelAdPrompt": HypereelAdPrompt,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HypereelAdPrompt": "Hypereel Ad Prompt (product + creator + presets)",
}
