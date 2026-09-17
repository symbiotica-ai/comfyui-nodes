# ABOUTME: The control-image library — every image under one folder, listed by
# ABOUTME: relative path so a recipe can name one and any mount can load it.
import hashlib
import os

IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def library_dir(path=None) -> str:
    """The folder the node reads, as an absolute path.

    One widget says where the images are, and it is the whole answer: they live
    on the studio-assets mount, not in ComfyUI's input directory, so there is
    nothing to join a name onto. Relative is refused — it would resolve against
    however ComfyUI happened to be launched.
    """
    base = str(path or "").strip().replace("\\", "/").rstrip("/")
    if not base:
        raise ValueError("no image folder: type or wire a path")
    if not os.path.isabs(base):
        raise ValueError(f"the image folder must be an absolute path: {path!r}")
    return base


def list_control_images(path=None) -> list[str]:
    """Every image under the folder, as a path relative to it, sorted.

    Sub-folders included and shown in the value — `general/1x1/1x1-box.png` is
    one pick, not a folder to open first. Dotfiles and non-images are left out.
    """
    try:
        base = library_dir(path)
    except ValueError:
        return []
    if not os.path.isdir(base):
        return []
    out = []
    for dirpath, dirs, files in os.walk(base, followlinks=True):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in files:
            if name.startswith(".") or not name.lower().endswith(IMAGE_SUFFIXES):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), base)
            out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def control_image_path(path, rel: str) -> str:
    """The file a relative name stands for, inside the folder only."""
    base = os.path.abspath(library_dir(path))
    rel = str(rel or "").replace("\\", "/").strip("/")
    if not rel:
        raise ValueError("no control image named")
    full = os.path.abspath(os.path.join(base, rel))
    if os.path.commonpath([base, full]) != base:
        raise ValueError(f"control image {rel!r} is outside {base}")
    return full


def file_fingerprint(path: str) -> str:
    """A hash of the bytes, so a re-uploaded file with the same name re-runs
    the node and an untouched one does not."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return ""


def load_rgba(path: str):
    """One file as ComfyUI's `(IMAGE, MASK)` pair, to `LoadImage`'s conventions.

    The conventions are copied rather than chosen: pixels arrive with alpha
    already flattened, the mask is `1 - alpha` so 1.0 means transparent, and a
    file with no alpha at all gets LoadImage's own 64x64 all-zero stand-in. A
    graph must not be able to tell this reader and LoadImage apart.
    """
    import numpy as np
    import torch
    from PIL import Image, ImageOps

    with Image.open(path) as opened:
        opened = ImageOps.exif_transpose(opened)
        opened.load()
        has_alpha = "A" in opened.getbands()
        rgb = np.asarray(opened.convert("RGB"), dtype=np.float32) / 255.0
        image = torch.from_numpy(rgb)[None, ...]
        if has_alpha:
            alpha = np.asarray(opened.getchannel("A"),
                               dtype=np.float32) / 255.0
            mask = torch.from_numpy(1.0 - alpha)[None, ...]
        else:
            mask = torch.zeros((1, 64, 64), dtype=torch.float32)
    return image, mask
