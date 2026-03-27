# ABOUTME: Seed node that generates an integer within a configurable range.
# ABOUTME: Maps any seed value into [min, max] bounds, with server-side fallback for sentinel values.

import random

SPECIAL_SEED_RANDOM = -1
SPECIAL_SEED_INCREMENT = -2
SPECIAL_SEED_DECREMENT = -3
SPECIAL_SEEDS = {SPECIAL_SEED_RANDOM, SPECIAL_SEED_INCREMENT, SPECIAL_SEED_DECREMENT}


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

    @classmethod
    def IS_CHANGED(cls, seed, min_value, max_value):
        if seed in SPECIAL_SEEDS:
            return float("nan")
        return seed

    def execute(self, seed, min_value, max_value):
        lo = min(min_value, max_value)
        hi = max(min_value, max_value)

        if seed in SPECIAL_SEEDS:
            seed = random.randint(lo, hi)

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
