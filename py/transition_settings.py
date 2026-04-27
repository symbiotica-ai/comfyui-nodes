# ABOUTME: Standalone node that outputs transition settings as a TRANSITION_SETTINGS dict
# ABOUTME: Decouples transition config from NS Video Concat so it can be reused by other nodes

TRANSITION_TYPES = [
    "tiktok_swipe",
    "slideleft", "slideright",
    "coverleft", "coverright",
    "wipeleft", "wiperight",
    "fadeblack", "dissolve",
]


class NSTransitionSettings:
    """
    Outputs a TRANSITION_SETTINGS dict that can be connected to
    NS Video Concat (or any future node that accepts transitions).
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "type": (TRANSITION_TYPES, {"default": "slideleft"}),
                "duration": ("FLOAT", {"default": 0.3, "min": 0.1, "max": 2.0, "step": 0.1}),
                "sound": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("TRANSITION_SETTINGS",)
    RETURN_NAMES = ("settings",)
    FUNCTION = "execute"
    CATEGORY = "neuralsins/Video"

    def execute(self, type, duration, sound):
        return ({
            "type": type,
            "duration": duration,
            "sound": sound,
        },)


NODE_CLASS_MAPPINGS = {
    "NSTransitionSettings": NSTransitionSettings
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSTransitionSettings": "NS Video Transitions"
}
