# ABOUTME: The control-image library — every image under input/controlnet, listed
# ABOUTME: by relative path so a recipe can name one and any editor can load it.
import hashlib
import os

CONTROL_DIR = "controlnet"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp")


def list_control_images(input_dir: str) -> list[str]:
    """Every image under input/controlnet, as `folder/name.png` relative to
    that folder, sorted. Dotfiles and non-images are left out."""
    root = os.path.join(input_dir, CONTROL_DIR)
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


def control_image_path(input_dir: str, rel: str) -> str:
    """The file a relative name stands for, inside input/controlnet only."""
    root = os.path.abspath(os.path.join(input_dir, CONTROL_DIR))
    rel = str(rel or "").replace("\\", "/").strip("/")
    if not rel:
        raise ValueError("no control image named")
    path = os.path.abspath(os.path.join(root, rel))
    if os.path.commonpath([root, path]) != root:
        raise ValueError(f"control image {rel!r} is outside {CONTROL_DIR}/")
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
