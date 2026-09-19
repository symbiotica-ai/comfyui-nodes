# ABOUTME: The control-image library — every image under one folder, listed by
# ABOUTME: relative path so a recipe can name one and any mount can load it.
import hashlib
import os
import shutil

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


def is_image_name(name) -> bool:
    """Is this a name this library holds? The same rule the listing uses, so
    nothing can be renamed or uploaded into a shape the tree will not show."""
    base = str(name or "").strip().replace("\\", "/").rsplit("/", 1)[-1]
    return bool(base) and not base.startswith(".") \
        and base.lower().endswith(IMAGE_SUFFIXES)


def list_control_folders(path=None) -> list[str]:
    """Every sub-folder under the library, relative to it, sorted.

    The tree draws these as its branches. Empty ones are listed too: a folder
    just made has nothing in it yet and is exactly the one about to be filled.
    """
    try:
        base = library_dir(path)
    except ValueError:
        return []
    if not os.path.isdir(base):
        return []
    out = []
    for dirpath, dirs, _ in os.walk(base, followlinks=True):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in dirs:
            rel = os.path.relpath(os.path.join(dirpath, name), base)
            out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def inside_library(path, rel: str, what: str = "name") -> str:
    """`library/rel`, or raise when the name climbs out of the library.

    The same containment `control_image_path` applies to a read, applied to
    everything that writes: a crafted name cannot reach a file the node was
    never pointed at.
    """
    base = os.path.abspath(library_dir(path))
    clean = str(rel or "").replace("\\", "/").strip("/")
    if not clean or clean == ".":
        raise ValueError(f"no {what}")
    full = os.path.abspath(os.path.join(base, clean))
    if full == base:
        raise ValueError("the library itself cannot be named here")
    if os.path.commonpath([base, full]) != base:
        raise ValueError(f"{clean!r} is outside {base}")
    return full


def make_folder(path, name: str) -> dict:
    """Create a sub-folder in the library. Existing is fine."""
    full = inside_library(path, name, "folder name")
    os.makedirs(full, exist_ok=True)
    rel = str(name).replace("\\", "/").strip("/")
    return {"name": rel}


def rename(path, src: str, dst: str) -> dict:
    """Rename a file or a sub-folder inside the library. The target must not
    exist — a rename that lands on another image would delete it — and a file
    keeps an image extension, or the tree would stop showing it."""
    src_full = inside_library(path, src, "source name")
    dst_full = inside_library(path, dst, "target name")
    src_rel = str(src).replace("\\", "/").strip("/")
    dst_rel = str(dst).replace("\\", "/").strip("/")
    if not os.path.exists(src_full):
        raise ValueError(f"nothing called {src_rel!r}")
    if os.path.isfile(src_full) and not is_image_name(dst_rel):
        raise ValueError(f"not an image name: {dst_rel!r}")
    if os.path.exists(dst_full):
        raise ValueError(f"{dst_rel!r} already exists")
    os.makedirs(os.path.dirname(dst_full), exist_ok=True)
    os.rename(src_full, dst_full)
    return {"from": src_rel, "to": dst_rel}


def remove(path, name: str) -> dict:
    """Delete one image, or one sub-folder and everything in it.

    A symlink is unlinked, never followed: a library is a mount, and a link in
    it points at somebody else's disk.
    """
    full = inside_library(path, name, "name")
    rel = str(name).replace("\\", "/").strip("/")
    if os.path.islink(full):
        os.unlink(full)
        return {"name": rel, "kind": "link"}
    if os.path.isdir(full):
        shutil.rmtree(full)
        return {"name": rel, "kind": "folder"}
    if not os.path.isfile(full):
        raise ValueError(f"nothing called {rel!r}")
    if not is_image_name(rel):
        raise ValueError(f"not an image: {rel!r}")
    os.remove(full)
    return {"name": rel, "kind": "file"}


def free_name(path, folder: str, filename: str) -> str:
    """An unused name for an upload, as `<name>-2.png`, `-3`, and so on.

    Never an overwrite: dropping a folder of masks onto a library that already
    holds one of them must not quietly replace the one that is already wired
    into somebody's graph.
    """
    base = os.path.basename(str(filename or "").replace("\\", "/")).strip()
    if not is_image_name(base):
        raise ValueError(f"not an image: {filename!r}")
    folder = str(folder or "").replace("\\", "/").strip("/")
    stem, ext = os.path.splitext(base)
    for n in range(1, 500):
        candidate = base if n == 1 else f"{stem}-{n}{ext}"
        rel = f"{folder}/{candidate}" if folder else candidate
        if not os.path.exists(inside_library(path, rel, "upload name")):
            return rel
    raise ValueError(f"too many copies of {base!r}")


def save_upload(path, folder: str, filename: str, data: bytes) -> dict:
    """Write one dropped file into the library, under a name nothing holds."""
    rel = free_name(path, folder, filename)
    full = inside_library(path, rel, "upload name")
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(data)
    return {"name": rel}


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
