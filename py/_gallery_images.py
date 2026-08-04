# ABOUTME: Image plumbing for the gallery nodes — PIL->batch packing with white
# ABOUTME: letterbox padding, category grouping, report lines, empty placeholders.
import numpy as np
import torch
from PIL import Image

try:
    from ._gallery_classify import CATEGORIES
except ImportError:  # flat import under pytest (conftest puts py/ itself on sys.path)
    from _gallery_classify import CATEGORIES

PLACEHOLDER_SIDE = 64


def placeholder():
    """The stand-in a graph receives for an empty category: one white frame.
    Downstream gates on the count outputs, not on this frame."""
    return torch.ones((1, PLACEHOLDER_SIDE, PLACEHOLDER_SIDE, 3), dtype=torch.float32)


def to_batch(pil_images, image_size):
    """One (N,H,W,3) float batch: each image downscaled so its longest side fits
    image_size (never upscaled), then centred on a white canvas of the group's
    max dimensions — jewelry packshots are white-background, so white padding
    reads as more packshot, not as a border."""
    if not pil_images:
        return placeholder()
    scaled = []
    for im in pil_images:
        w, h = im.size
        s = image_size / max(w, h)
        if s < 1.0:
            im = im.resize((max(1, round(w * s)), max(1, round(h * s))), Image.LANCZOS)
        scaled.append(im)
    width = max(im.size[0] for im in scaled)
    height = max(im.size[1] for im in scaled)
    frames = []
    for im in scaled:
        canvas = Image.new("RGB", (width, height), (255, 255, 255))
        canvas.paste(im, ((width - im.size[0]) // 2, (height - im.size[1]) // 2))
        frames.append(np.asarray(canvas, dtype=np.float32) / 255.0)
    return torch.from_numpy(np.stack(frames))


def group_by_category(items, verdicts):
    """({category: [item, ...]}, report_lines) — items and verdicts aligned.
    Each line: category, pooled confidence, margin, and the item's label()."""
    groups = {c: [] for c in CATEGORIES}
    lines = []
    for (item, label), v in zip(items, verdicts):
        groups[v["category"]].append(item)
        lines.append(f"{v['category']:<9} {v['confidence']:.2f} "
                     f"(margin {v['margin']:.2f})  {label}")
    return groups, lines


def batch_to_pils(images):
    """ComfyUI IMAGE batch -> list of RGB PIL images."""
    frames = (images.cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
    return [Image.fromarray(f) for f in frames]


def pick_rows(images, indices):
    """The rows of a batch at `indices`, or the placeholder when empty."""
    if not indices:
        return placeholder()
    return images[indices]
