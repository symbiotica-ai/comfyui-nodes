# ABOUTME: Native output resolutions for the image models we target — port of
# ABOUTME: hub texture-pack/model-presets.ts (long-edge convention, x8 snapping).
from __future__ import annotations

TIER_PX = {"0.5K": 512, "1K": 1024, "2K": 2048, "4K": 4096}

MODEL_PRESETS = [
    {
        "id": "nano-banana-pro",
        "label": "Nano Banana Pro",
        "endpoint": "fal-ai/nano-banana-pro",
        "tiers": ["1K", "2K", "4K"],
        "aspectRatios": ["21:9", "16:9", "3:2", "4:3", "5:4", "1:1", "4:5", "3:4",
                          "2:3", "9:16"],
    },
    {
        "id": "nano-banana-2",
        "label": "Nano Banana 2",
        "endpoint": "fal-ai/nano-banana-2",
        "tiers": ["0.5K", "1K", "2K", "4K"],
        "aspectRatios": ["21:9", "16:9", "3:2", "4:3", "5:4", "1:1", "4:5", "3:4",
                          "2:3", "9:16", "4:1", "1:4", "8:1", "1:8"],
    },
    {
        "id": "imagen-4",
        "label": "Imagen 4",
        "endpoint": "fal-ai/imagen4",
        "tiers": ["1K", "2K"],
        "aspectRatios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
    },
    {
        # Qwen emits one fixed native size per aspect ratio (not a tier
        # long-edge scaled by AR), so "sizes" overrides the computed dims.
        "id": "qwen-image",
        "label": "Qwen Image",
        "endpoint": "fal-ai/qwen-image",
        "tiers": ["1K"],
        "aspectRatios": ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"],
        "sizes": {
            "1:1": {"w": 1328, "h": 1328},
            "16:9": {"w": 1664, "h": 928},
            "9:16": {"w": 928, "h": 1664},
            "4:3": {"w": 1472, "h": 1104},
            "3:4": {"w": 1104, "h": 1472},
            "3:2": {"w": 1584, "h": 1056},
            "2:3": {"w": 1056, "h": 1584},
        },
    },
]


def _round8(n: float) -> int:
    return max(8, round(n / 8) * 8)


def aspect_dims(ar: str, tier: str) -> dict:
    """Pixel dimensions for an aspect ratio at a resolution tier."""
    long_edge = TIER_PX[tier]
    try:
        a, b = (int(x) for x in ar.split(":"))
    except ValueError:
        return {"w": long_edge, "h": long_edge}
    if not a or not b:
        return {"w": long_edge, "h": long_edge}
    if a >= b:
        return {"w": long_edge, "h": _round8(long_edge * b / a)}
    return {"w": _round8(long_edge * a / b), "h": long_edge}


def preset_dims(sel: dict | None) -> dict | None:
    """Resolve a stored selection {model, tier, ar} to exact pixel dims."""
    if not sel:
        return None
    model = next((m for m in MODEL_PRESETS if m["id"] == sel.get("model")), None)
    if (
        model is None
        or sel.get("tier") not in model["tiers"]
        or sel.get("ar") not in model["aspectRatios"]
    ):
        return None
    # A model with fixed per-AR native sizes (e.g. Qwen) overrides the tier
    # long-edge computation.
    sizes = model.get("sizes")
    if sizes and sel["ar"] in sizes:
        return dict(sizes[sel["ar"]])
    return aspect_dims(sel["ar"], sel["tier"])
