# ABOUTME: Reference images as they arrive from a node's inputs — Autogrow slots
# ABOUTME: or a plain batch — turned into PIL images in the order the canvas shows.
import numpy as np
from PIL import Image


def slot_order(name):
    """Autogrow slot names in the order the canvas shows them.

    Sorted as text, `image_10` lands between `image_1` and `image_2`, so a
    graph with ten references sends them in an order nobody wired and the
    prompt's "the second image" means the tenth. Unnumbered names keep their
    own alphabetical order after the numbered ones rather than raising."""
    _, _, suffix = name.rpartition("_")
    return (0, int(suffix), "") if suffix.isdigit() else (1, 0, name)


def to_pil(images):
    """Reference images as a list of PIL images, whatever shape they arrive in.

    Autogrow hands its slots over as a DICT keyed by slot name, and a slot may
    hold a batch of its own, so the slots are flattened in name order and each
    batch is expanded in place. Iterating that dict directly would yield its
    KEYS — a node doing so sends no images at all, or dies converting the
    string "image_1" to pixels.

    None, an empty dict and an empty batch are all 'no references', which is a
    prompt-only call. Shared by every node taking reference images: the two
    that had their own copies diverged, and only one of them learned about
    Autogrow."""
    if images is None:
        return []
    if isinstance(images, dict):
        out = []
        for name in sorted(images, key=slot_order):
            out.extend(to_pil(images[name]))
        return out
    out = []
    for frame in images:
        if hasattr(frame, "cpu"):
            frame = frame.cpu().numpy()
        arr = np.asarray(frame)
        if arr.dtype != np.uint8:
            arr = (np.clip(arr, 0.0, 1.0) * 255.0).round().astype(np.uint8)
        out.append(Image.fromarray(arr))
    return out
