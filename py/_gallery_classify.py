# ABOUTME: Zero-shot gallery image classifier — sorts e-commerce shots into
# ABOUTME: product-only / on-model / other via CLIP text-image similarity.
import math

CATEGORIES = ("product", "on_model", "other")

DEFAULT_MODEL = "openai/clip-vit-base-patch16"

# Several templates per category, pooled by mean logit — CLIP zero-shot is
# markedly more stable ensembled over paraphrases than on a single prompt.
# This table + mean-logit pooling + patch16 scored 29/29 on a labeled Teilor
# gallery benchmark (packshots / worn-on-model / packaging); sum-of-probability
# pooling on the same prompts scored 25/29 — pooling choice matters more than
# model size (large-patch14 did worse).
CATEGORY_PROMPTS = {
    "product": (
        "a piece of jewelry photographed alone on a seamless white background",
        "a macro studio photograph of a gold ring, bracelet, necklace or earrings, floating, nobody present",
        "an e-commerce packshot: the product only, white backdrop, soft shadow",
        "a close-up catalog photo of a product by itself",
    ),
    "on_model": (
        "a woman wearing jewelry on her body",
        "a photo showing part of a person: a hand, wrist, neck, ear or face",
        "a model in clothing posing with jewelry on",
        "a person's skin with a bracelet on the wrist or a necklace on the neck",
        "a close-up of a person's wrist or neck wearing jewelry, part of the face visible",
        "a person wearing jewelry",
    ),
    "other": (
        "luxury gift boxes, ribbons and a branded shopping bag",
        "product packaging boxes on a plain surface",
        "a brand logo graphic or website banner",
        "gift boxes, ribbons and shopping bags",
    ),
}


def flat_prompts(category_prompts=None):
    """(prompts, categories) as two aligned flat tuples."""
    table = category_prompts or CATEGORY_PROMPTS
    prompts, cats = [], []
    for cat in CATEGORIES:
        for p in table.get(cat, ()):
            prompts.append(p)
            cats.append(cat)
    return tuple(prompts), tuple(cats)


def aggregate(prompt_logits, prompt_categories):
    """Pool per-prompt CLIP logits into a category verdict.

    Mean logit per category (the standard zero-shot template ensemble), then a
    softmax over the three category means. Returns (category, confidence,
    margin): confidence is the winner's softmax share, margin its lead over the
    runner-up. CLIP logits arrive temperature-scaled (~x100), so confidences
    sit near 0 or 1 — the margin is the more readable uncertainty signal."""
    sums = {c: 0.0 for c in CATEGORIES}
    counts = {c: 0 for c in CATEGORIES}
    for logit, cat in zip(prompt_logits, prompt_categories):
        sums[cat] += float(logit)
        counts[cat] += 1
    means = {c: sums[c] / counts[c] for c in CATEGORIES if counts[c]}
    peak = max(means.values())
    exps = {c: math.exp(m - peak) for c, m in means.items()}
    total = sum(exps.values())
    ranked = sorted(((e / total, c) for c, e in exps.items()), reverse=True)
    confidence, category = ranked[0]
    margin = confidence - (ranked[1][0] if len(ranked) > 1 else 0.0)
    return category, confidence, margin


class ClipBackend:
    """Lazy CLIP wrapper. transformers is a ComfyUI runtime dependency the repo
    never declares (same stance as torch); it is imported only when a graph
    actually runs the clip classifier, so the test suite and registry scans
    never require it."""

    def __init__(self, model_id):
        self.model_id = model_id
        self._model = None
        self._processor = None
        self._device = None

    def _load(self):
        if self._model is not None:
            return
        import torch
        from transformers import CLIPModel, CLIPProcessor

        if torch.cuda.is_available():
            self._device = "cuda"
        elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            self._device = "mps"
        else:
            self._device = "cpu"
        self._model = CLIPModel.from_pretrained(self.model_id).to(self._device).eval()
        self._processor = CLIPProcessor.from_pretrained(self.model_id)

    def prompt_logits(self, pil_images, prompts):
        """rows: one raw logit per prompt per image (temperature-scaled cosine)."""
        import torch

        self._load()
        inputs = self._processor(
            text=list(prompts), images=pil_images, return_tensors="pt", padding=True
        ).to(self._device)
        with torch.no_grad():
            logits = self._model(**inputs).logits_per_image
        return logits.cpu().tolist()


_BACKENDS = {}


def get_backend(model_id):
    if model_id not in _BACKENDS:
        _BACKENDS[model_id] = ClipBackend(model_id)
    return _BACKENDS[model_id]


def classify_images(pil_images, backend, category_prompts=None):
    """[{category, confidence, margin}] per image, in input order."""
    if not pil_images:
        return []
    prompts, cats = flat_prompts(category_prompts)
    rows = backend.prompt_logits(pil_images, prompts)
    out = []
    for row in rows:
        category, confidence, margin = aggregate(row, cats)
        out.append({"category": category, "confidence": confidence, "margin": margin})
    return out
