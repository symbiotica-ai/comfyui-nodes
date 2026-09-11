# ABOUTME: Control Image node — picks a control image from input/controlnet, the
# ABOUTME: shared library every editor and render sandbox mounts.
import folder_paths

from ._control_image import (CONTROL_DIR, control_image_path, file_fingerprint,
                             list_control_images)


class SymbioticaControlImage:
    """Load Image, scoped to the control-image library: the dropdown lists
    every image under input/controlnet (subfolders included) by relative
    path, so the value a recipe stores is `bakery/counter.png` and the same
    file loads on any editor or render sandbox that mounts the inputs."""

    @classmethod
    def INPUT_TYPES(cls):
        files = list_control_images(folder_paths.get_input_directory())
        return {
            "required": {
                "image": (files or [f"[no images under input/{CONTROL_DIR}]"], {
                    "tooltip": f"An image under input/{CONTROL_DIR}/, subfolders "
                               "included. Upload there from the hub's storage "
                               "browser; new files appear after a browser reload.",
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "MASK")
    FUNCTION = "load"
    CATEGORY = "Symbiotica/Images"
    DESCRIPTION = (f"A control image from the shared input/{CONTROL_DIR} library, "
                   "loaded like Load Image.")

    def load(self, image):
        control_image_path(folder_paths.get_input_directory(), image)
        from nodes import LoadImage
        return LoadImage().load_image(f"{CONTROL_DIR}/{image}")

    @classmethod
    def IS_CHANGED(cls, image):
        try:
            return file_fingerprint(control_image_path(folder_paths.get_input_directory(), image))
        except ValueError:
            return ""

    @classmethod
    def VALIDATE_INPUTS(cls, image):
        try:
            path = control_image_path(folder_paths.get_input_directory(), image)
        except ValueError as e:
            return str(e)
        import os
        if not os.path.isfile(path):
            return f"no control image {image!r} under input/{CONTROL_DIR}"
        return True


NODE_CLASS_MAPPINGS = {"SymbioticaControlImage": SymbioticaControlImage}
NODE_DISPLAY_NAME_MAPPINGS = {"SymbioticaControlImage": "Control Image"}
