# ABOUTME: Seed node that generates an integer within a configurable range.
# ABOUTME: Maps any seed value into [min, max] bounds for controlled randomization.


class SymbioticaSeed:
    """Generates a deterministic integer within a configurable range from a seed value."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "seed": ("INT", {
                    "default": 0,
                    "min": -0xFFFFFFFFFFFFFFFF,
                    "max": 0xFFFFFFFFFFFFFFFF,
                }),
                "min_value": ("INT", {
                    "default": 0,
                    "min": -0xFFFFFFFFFFFFFFFF,
                    "max": 0xFFFFFFFFFFFFFFFF,
                    "tooltip": "Minimum value of the output range (inclusive)",
                }),
                "max_value": ("INT", {
                    "default": 100,
                    "min": -0xFFFFFFFFFFFFFFFF,
                    "max": 0xFFFFFFFFFFFFFFFF,
                    "tooltip": "Maximum value of the output range (inclusive)",
                }),
            },
        }

    RETURN_TYPES = ("INT",)
    RETURN_NAMES = ("value",)
    FUNCTION = "execute"
    CATEGORY = "symbiotica"

    def execute(self, seed, min_value, max_value):
        lo = min(min_value, max_value)
        hi = max(min_value, max_value)

        if lo == hi:
            return (lo,)

        result = lo + (abs(seed) % (hi - lo + 1))
        return (result,)


NODE_CLASS_MAPPINGS = {
    "SymbioticaSeed": SymbioticaSeed,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SymbioticaSeed": "Symbiotica Seed",
}
