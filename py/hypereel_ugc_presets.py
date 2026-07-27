# ABOUTME: Hypereel UGC preset picker — the platform's style/hook/setting catalogs as
# ABOUTME: three dropdowns; outputs the templates plus a pre-labeled combined block.
from ._hypereel_presets import HOOKS, SETTINGS, STYLES, build_notes


class HypereelUgcPresets:
    """The platform's UGC preset catalogs as dropdowns: pick a style, hook and
    setting by name; the node emits each template and a combined pre-labeled
    block (STYLE NOTE / HOOK PATTERN / SETTING NOTE) ready to concatenate after
    the product summary — one node instead of twelve primitives and a switch."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "style": (list(STYLES.keys()),),
                "hook": (list(HOOKS.keys()),),
                "setting": (list(SETTINGS.keys()),),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "STRING")
    RETURN_NAMES = ("style_note", "hook_note", "setting_note", "notes")
    FUNCTION = "pick"
    CATEGORY = "Symbiotica/Hypereel"

    def pick(self, style, hook, setting):
        return (STYLES[style], HOOKS[hook], SETTINGS[setting],
                build_notes(style, hook, setting))


NODE_CLASS_MAPPINGS = {
    "HypereelUgcPresets": HypereelUgcPresets,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HypereelUgcPresets": "Hypereel UGC Presets (style · hook · setting)",
}
