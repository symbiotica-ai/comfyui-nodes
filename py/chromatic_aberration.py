# ABOUTME: Chromatic aberration node — radial per-channel colour fringing on a VIDEO.
# ABOUTME: ffmpeg decodes and encodes via the shared harness; the maths is numpy.

import os
import tempfile
import time

import folder_paths

from ._chromatic_aberration import corner_split_px, make_effect
from ._video_fx import DEFAULT_CRF, probe, process


class ChromaticAberration:
    """
    Lateral chromatic aberration: the colour fringing a lens leaves toward the
    edges of the frame, where red and blue focus at slightly different
    magnifications from green.

    Modelled as the real thing rather than as a channel offset. The displacement
    is radial and grows from nothing at the optical centre to its largest at the
    corners; red and blue move opposite ways with green held as the reference;
    and the two are asymmetric, because blue disperses about twice as far as red.
    A whole-frame channel shift — the usual shortcut — gets all three wrong at
    once, and reads as a glitch effect rather than as glass.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
                "strength": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 3.0, "step": 0.05,
                    "tooltip": "How much colour fringing the lens leaves in the "
                               "corners. 1.0 is a real lens you would notice if "
                               "you went looking; 2 to 3 is the stylised look. "
                               "The middle of the frame stays clean at every "
                               "setting, which is how the real thing behaves. "
                               "0 passes the video through untouched.",
                }),
            },
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "execute"
    CATEGORY = "Symbiotica/Video"

    def execute(self, video, strength=1.0):
        from comfy_api.latest import InputImpl

        if strength <= 0.0:
            print("[Chromatic Aberration] strength is 0, returning original video")
            return (video,)

        temp_files = []
        try:
            source_path = tempfile.NamedTemporaryFile(
                suffix=".mp4", delete=False
            ).name
            temp_files.append(source_path)
            video.save_to(source_path, format="mp4", codec="h264")

            output_dir = folder_paths.get_output_directory()
            output_path = os.path.join(
                output_dir, f"chromatic_aberration_{int(time.time())}.mp4"
            )

            # Probed up front only so the operator is told the amount in pixels
            # — "strength 1.4" means nothing until you know it is 2.4 px on this
            # frame size. process() does its own probe for the render.
            info = probe(source_path)
            split = corner_split_px(info["width"], info["height"], strength)
            print(f"[Chromatic Aberration] {info['width']}x{info['height']}, "
                  f"strength={strength:g}, {split:.2f}px of red-to-blue split at "
                  f"the corners and none at the centre")

            frames = process(source_path, output_path, make_effect(strength),
                             crf=DEFAULT_CRF)
            print(f"[Chromatic Aberration] {frames} frames written.")

            print(f"[Chromatic Aberration] Done -> {output_path}")
            return (InputImpl.VideoFromFile(output_path),)
        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass


NODE_CLASS_MAPPINGS = {
    "ChromaticAberration": ChromaticAberration,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "ChromaticAberration": "Chromatic Aberration",
}
