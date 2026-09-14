# ABOUTME: The control-image library — every image under a named folder of a
# ABOUTME: named root, listed by relative path so a recipe can name one.
import hashlib
import os

# The folder inside the input directory when the node names none. A DEFAULT, not
# the answer: the node carries `input_dir` and `folder` widgets, so a library
# kept somewhere else is a value typed on the canvas rather than a patch here.
CONTROL_DIR = "controlnet"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def control_folder(folder=None):
    """The library's folder name, normalised. Empty means `CONTROL_DIR`.

    The value arrives from a node widget and from an HTTP query, so a name that
    is absolute or climbs out of the input directory is refused rather than
    joined — every containment check below is written against a root that is
    actually inside it.
    """
    name = str(folder or "").strip().replace("\\", "/").rstrip("/")
    if not name:
        return CONTROL_DIR
    # A leading slash is REFUSED, not stripped: "/etc" means the absolute path,
    # and quietly reading it as a name inside the root would send the node to a
    # different folder than the one that was typed, with nothing said.
    if name.startswith("/") or any(p in ("", ".", "..") for p in name.split("/")):
        raise ValueError(f"not a folder inside the input directory: {folder!r}")
    return name


def base_dir(input_dir, root=None):
    """Which directory the library sits in. Empty `root` means ComfyUI's own
    input directory, which is where the library lived when it was the only
    place it could live; an absolute path is any other mount — the studio-assets
    Volume at `/studio-assets/_platform/resources`, say. Relative is refused:
    it would resolve against however ComfyUI happened to be launched."""
    base = str(root or "").strip().rstrip("/")
    if not base:
        return input_dir
    if not os.path.isabs(base):
        raise ValueError(f"the library root must be an absolute path: {root!r}")
    return base


def control_root(input_dir, folder=None, root=None):
    """The folder a listing walks: `<root or input_dir>/<folder>`."""
    return os.path.join(base_dir(input_dir, root), control_folder(folder))


def list_control_images(input_dir: str, folder=None, root=None) -> list[str]:
    """Every image under the library folder, as `folder/name.png` relative to
    it, sorted. Dotfiles and non-images are left out."""
    try:
        root = control_root(input_dir, folder, root)
    except ValueError:
        return []
    if not os.path.isdir(root):
        return []
    out = []
    for dirpath, dirs, files in os.walk(root, followlinks=True):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in files:
            if name.startswith(".") or not name.lower().endswith(IMAGE_SUFFIXES):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def control_image_path(input_dir: str, rel: str, folder=None, root=None) -> str:
    """The file a relative name stands for, inside the library folder only."""
    name = control_folder(folder)
    root = os.path.abspath(control_root(input_dir, name, root))
    rel = str(rel or "").replace("\\", "/").strip("/")
    if not rel:
        raise ValueError("no control image named")
    path = os.path.abspath(os.path.join(root, rel))
    if os.path.commonpath([root, path]) != root:
        raise ValueError(f"control image {rel!r} is outside {name}/")
    return path


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

    Used only when the library sits outside ComfyUI's input directory, because
    `LoadImage` resolves every name against that directory and cannot reach
    another mount. The conventions are copied rather than chosen: pixels arrive
    with alpha already flattened, the mask is `1 - alpha` so 1.0 means
    transparent, and a file with no alpha at all gets LoadImage's own 64x64
    all-zero stand-in. A graph must not be able to tell the two readers apart.
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
