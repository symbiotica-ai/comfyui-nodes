# ABOUTME: Control Image node — loads one image from a folder the node names,
# ABOUTME: anywhere on disk, picked from a dropdown of everything under it.
import os

from ._control_image import (control_image_path, file_fingerprint, library_dir,
                             load_rgba)


def _push(event: str, payload: dict) -> None:
    """Fire-and-forget UI push; an absent or failed server must never break a
    render over a dropdown that wanted filling."""
    try:
        from server import PromptServer
        PromptServer.instance.send_sync(event, payload)
    except Exception:
        pass


class SymbioticaControlImage:
    """Load Image, pointed at a folder instead of ComfyUI's input directory.

    `path` is where the images are — `/studio-assets/_platform/resources/
    controlnet-images`, the mount every editor and render sandbox sees. `image`
    is one file under it, named relative to it and sub-folders included, so the
    value a recipe stores is `general/1x1/1x1-box.png` and the same file loads
    wherever that folder is mounted.
    """

    @classmethod
    def INPUT_TYPES(cls):
        # Built once, at registration, when no node has said where it reads —
        # so there is nothing to list here. The canvas fills the dropdown from
        # the node's own path (web/js/control_image.js).
        return {
            "required": {
                # `image` FIRST: widget values restore positionally, and a
                # workflow saved before this holds [image, root, folder] —
                # `path` lands where `root` sat and inherits what it held.
                "image": (["[set a path]"], {
                    "tooltip": "A file under `path`, sub-folders included. "
                               "New files appear after a browser reload.",
                }),
                "path": ("STRING", {
                    "default": "",
                    "tooltip": "The folder holding the images. An absolute "
                               "path — /studio-assets/_platform/resources/"
                               "controlnet-images is the shared one. Type it "
                               "or wire a string.",
                }),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    # An output node so it can be queued on its own. A path arriving through a
    # Get node has no value on the canvas — the Get's only widget holds the
    # constant's NAME — so running the node is how the dropdown learns where it
    # reads, and with nothing downstream there would be no way to make that
    # run happen.
    OUTPUT_NODE = True

    RETURN_TYPES = ("IMAGE", "MASK")
    FUNCTION = "load"
    CATEGORY = "Symbiotica"
    DESCRIPTION = ("One image from a folder the node points at, loaded like "
                   "Load Image. The folder is a widget; the pick is a "
                   "dropdown of everything under it.")

    def load(self, image, path, unique_id=None):
        full = control_image_path(path, image)
        # The canvas fetches the preview back through `local-image`, which
        # serves registered roots only.
        from .pipeline.routes import register_root
        register_root(os.path.dirname(full))
        # The run knows the folder the canvas could only guess at, so it hands
        # it back — the same way the Prompts node does.
        _push("symbiotica.control_image",
              {"node_id": str(unique_id or ""), "path": str(path or "")})
        return load_rgba(full)

    @classmethod
    def IS_CHANGED(cls, image, path, unique_id=None):
        try:
            return file_fingerprint(control_image_path(path, image))
        except ValueError:
            return ""

    @classmethod
    def VALIDATE_INPUTS(cls, image, path, unique_id=None):
        # A WIRED path has no widget value here — validation runs before
        # anything executes, so the Get node feeding it has not spoken yet.
        # Refusing an empty path at this point rejects every node whose folder
        # arrives on a wire, which is every node on his canvas. `load` is
        # where a path that never arrives fails, with the same message.
        if not str(path or "").strip():
            return True
        try:
            full = control_image_path(path, image)
        except ValueError as e:
            return str(e)
        if not os.path.isdir(library_dir(path)):
            return f"no folder at {path}"
        if not os.path.isfile(full):
            return f"no image {image!r} under {path}"
        return True


NODE_CLASS_MAPPINGS = {"SymbioticaControlImage": SymbioticaControlImage}
NODE_DISPLAY_NAME_MAPPINGS = {"SymbioticaControlImage": "Control Image"}
