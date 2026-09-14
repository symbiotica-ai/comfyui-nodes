# ABOUTME: Control Image node — picks a control image from a named folder of the
# ABOUTME: input directory, the shared library every editor and sandbox mounts.
import os

import folder_paths

from ._control_image import (CONTROL_DIR, base_dir, control_folder,
                             control_image_path, file_fingerprint,
                             list_control_images, load_rgba)


class SymbioticaControlImage:
    """Load Image, scoped to the control-image library: the dropdown lists
    every image under `input/<folder>` (subfolders included) by relative
    path, so the value a recipe stores is `bakery/counter.png` and the same
    file loads on any editor or render sandbox that mounts the inputs.

    Both halves of the location are widgets, not constants here: `root` is the
    mount the library sits on — empty means ComfyUI's own input directory, and
    `/studio-assets/_platform/resources` is the shared one every editor and
    render sandbox mounts — and `folder` is the library inside it.
    """

    @classmethod
    def INPUT_TYPES(cls):
        # Built once, at registration, so it can only list the DEFAULT folder —
        # a classmethod cannot see a sibling widget's value. The canvas replaces
        # these values with the current folder's (web/js/control_image.js); this
        # list is what an API-only caller and the first paint get.
        files = list_control_images(folder_paths.get_input_directory())
        # `image` FIRST and the two location widgets after it, because
        # `widgets_values` restores positionally: a workflow saved when `image`
        # was the only widget holds `[name]`, and a widget inserted ahead of it
        # would take that value and leave the pick blank.
        return {
            "required": {
                "image": (files or [f"[no images under input/{CONTROL_DIR}]"], {
                    "tooltip": "An image under the root and folder below, "
                               "subfolders included. Upload there from the "
                               "hub's storage browser; new files appear after "
                               "a browser reload.",
                }),
                "root": ("STRING", {
                    "default": "",
                    "tooltip": "The directory the library sits in. Empty is "
                               "ComfyUI's own input directory. The shared one "
                               "is /studio-assets/_platform/resources, which "
                               "the canvas and the render sandboxes mount — "
                               "the engine tier does not, it sees only its "
                               "own studio's subtree.",
                }),
                "folder": ("STRING", {
                    "default": CONTROL_DIR,
                    "tooltip": "The folder inside `root` that holds the "
                               "library. A name, not a path, and it cannot "
                               "climb out of the root. Changing either "
                               "re-lists `image`.",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    FUNCTION = "load"
    CATEGORY = "Symbiotica/Images"
    DESCRIPTION = ("A control image from the shared input library, loaded like "
                   "Load Image. The folder it reads is a widget.")

    def load(self, image, root, folder):
        inputs = folder_paths.get_input_directory()
        name = control_folder(folder)
        path = control_image_path(inputs, image, name, root)
        if base_dir(inputs, root) == inputs:
            from nodes import LoadImage
            # Through LoadImage while the library is in its own directory: the
            # reader ComfyUI has is the one to use where it reaches.
            return LoadImage().load_image(f"{name}/{image}")
        # Another mount, which LoadImage cannot reach — every name it takes is
        # resolved against the input directory. `load_rgba` copies its
        # conventions so the two paths are the same picture and the same mask.
        from .pipeline.routes import register_root
        register_root(os.path.dirname(path))
        return load_rgba(path)

    @classmethod
    def IS_CHANGED(cls, image, root, folder):
        try:
            return file_fingerprint(control_image_path(
                folder_paths.get_input_directory(), image, folder, root))
        except ValueError:
            return ""

    @classmethod
    def VALIDATE_INPUTS(cls, image, root, folder):
        try:
            name = control_folder(folder)
            path = control_image_path(folder_paths.get_input_directory(),
                                      image, name, root)
        except ValueError as e:
            return str(e)
        if not os.path.isfile(path):
            return f"no control image {image!r} under {os.path.dirname(path)}"
        return True


NODE_CLASS_MAPPINGS = {"SymbioticaControlImage": SymbioticaControlImage}
NODE_DISPLAY_NAME_MAPPINGS = {"SymbioticaControlImage": "Control Image"}
