# ABOUTME: Hypereel clip node — cuts a [start, start+duration] window out of a VIDEO
# ABOUTME: with ffmpeg (no frame tensors, so a 7-minute or 7-hour source costs the same).
import os
import tempfile
import time

import folder_paths

from ._bins import FFMPEG, FFPROBE
from ._hypereel_ffmpeg import checked_window, clip_cmd, probe_duration


class HypereelClip:
    """Cuts one highlight window out of a gameplay video. The window is clamped
    fully inside the source (a highlight near EOF still yields a full slice).
    Decodes only the window — safe for arbitrarily long sources."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
                "start_sec": ("FLOAT", {"default": 0.0, "min": 0.0, "max": 359999.0, "step": 0.1}),
                "duration_sec": ("FLOAT", {"default": 10.0, "min": 0.5, "max": 600.0, "step": 0.1}),
            },
            "optional": {
                "keep_audio": ("BOOLEAN", {"default": True}),
            },
        }

    RETURN_TYPES = ("VIDEO", "FLOAT", "FLOAT")
    RETURN_NAMES = ("clip", "actual_start", "actual_duration")
    FUNCTION = "cut"
    CATEGORY = "Symbiotica/Hypereel"

    def cut(self, video, start_sec, duration_sec, keep_audio=True):
        import subprocess

        from comfy_api.latest import InputImpl

        src = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
        try:
            video.save_to(src, format="mp4", codec="h264")
            total = probe_duration(FFPROBE, src)
            start, dur = checked_window(start_sec, duration_sec, total)
            out = os.path.join(
                folder_paths.get_output_directory(),
                f"hypereel_clip_{int(time.time() * 1000)}.mp4",
            )
            result = subprocess.run(
                clip_cmd(FFMPEG, src, out, start, dur, keep_audio),
                capture_output=True,
            )
            if result.returncode != 0:
                raise RuntimeError(f"ffmpeg clip failed: {result.stderr.decode()[:400]}")
            return (InputImpl.VideoFromFile(out), start, dur)
        finally:
            try:
                os.unlink(src)
            except OSError:
                pass


NODE_CLASS_MAPPINGS = {
    "HypereelClip": HypereelClip,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HypereelClip": "Hypereel Clip (cut by seconds)",
}
