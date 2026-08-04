# ABOUTME: Product image sort node — splits any IMAGE batch into product-only /
# ABOUTME: on-model / other outputs with the same zero-shot CLIP classifier the
# ABOUTME: gallery scrape node uses.
from ._gallery_classify import CATEGORIES, DEFAULT_MODEL, classify_images, get_backend
from ._gallery_images import batch_to_pils, pick_rows


class ProductImageSort:
    """Splits an IMAGE batch by content — product packshots, shots with a person
    wearing/using the product, everything else — via local zero-shot CLIP. Useful
    for sorting generated or hand-collected shots the same way the scrape node
    sorts a page gallery. Empty categories emit a white placeholder frame; gate
    on the count outputs."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
            },
            "optional": {
                "clip_model": ("STRING", {
                    "default": DEFAULT_MODEL,
                    "tooltip": "Hugging Face CLIP checkpoint for the classifier.",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "STRING", "INT", "INT", "INT")
    RETURN_NAMES = ("product_images", "on_model_images", "other_images",
                    "report", "product_count", "on_model_count", "other_count")
    FUNCTION = "sort"
    CATEGORY = "Symbiotica/Commerce"

    def sort(self, images, clip_model=DEFAULT_MODEL):
        pils = batch_to_pils(images)
        verdicts = classify_images(pils, get_backend(clip_model))

        indices = {c: [] for c in CATEGORIES}
        lines = [f"{len(pils)} image(s)"]
        for i, v in enumerate(verdicts):
            indices[v["category"]].append(i)
            lines.append(f"#{i}: {v['category']} {v['confidence']:.2f} "
                         f"(margin {v['margin']:.2f})")

        return (
            pick_rows(images, indices["product"]),
            pick_rows(images, indices["on_model"]),
            pick_rows(images, indices["other"]),
            "\n".join(lines),
            len(indices["product"]),
            len(indices["on_model"]),
            len(indices["other"]),
        )


NODE_CLASS_MAPPINGS = {
    "NSProductImageSort": ProductImageSort,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSProductImageSort": "Product Image Sort",
}
