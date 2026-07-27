# ABOUTME: Hypereel screen glow node — samples the gameplay's per-frame color and
# ABOUTME: applies it to the facecam as monitor light. Deterministic edit, audio untouched.
import os
import tempfile
import time

import folder_paths

from ._bins import FFMPEG, FFPROBE
from ._hypereel_cancel import as_comfy_cancel, cancelled
from ._hypereel_glow import run_glow


class HypereelScreenGlow:
    """Applies the gameplay's light onto the streamer's face: the gameplay clip's
    per-frame mean color (an explosion flashes orange, a dark corridor goes dim)
    becomes a bottom-up monitor glow screen-blended onto the facecam, frame-locked
    to the footage. The facecam's own audio passes through untouched."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "facecam": ("VIDEO",),
                "gameplay": ("VIDEO",),
                "strength": ("FLOAT", {"default": 0.35, "min": 0.0, "max": 1.0, "step": 0.05,
                                       "tooltip": "How much screen light lands on the streamer."}),
                "smoothing": ("FLOAT", {"default": 0.5, "min": 0.0, "max": 0.95, "step": 0.05,
                                        "tooltip": "0 = raw flicker, higher = softer, lagged glow."}),
            }
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("facecam_lit",)
    FUNCTION = "glow"
    CATEGORY = "Symbiotica/Hypereel"

    def glow(self, facecam, gameplay, strength, smoothing):
        from comfy_api.latest import InputImpl

        fc = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
        gp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
        try:
            facecam.save_to(fc, format="mp4", codec="h264")
            gameplay.save_to(gp, format="mp4", codec="h264")
            out = os.path.join(
                folder_paths.get_output_directory(),
                f"hypereel_glow_{int(time.time() * 1000)}.mp4",
            )
            try:
                run_glow(fc, gp, out, strength=strength, smoothing=smoothing,
                         ffmpeg=FFMPEG, ffprobe=FFPROBE, interrupt=cancelled)
                return (InputImpl.VideoFromFile(out),)
            except InterruptedError as e:
                as_comfy_cancel(e)
        finally:
            for f in (fc, gp):
                try:
                    os.unlink(f)
                except OSError:
                    pass


NODE_CLASS_MAPPINGS = {
    "HypereelScreenGlow": HypereelScreenGlow,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HypereelScreenGlow": "Hypereel Screen Glow (light from gameplay)",
}
