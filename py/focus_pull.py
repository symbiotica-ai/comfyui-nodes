# ABOUTME: Focus pull node — racks a VIDEO between defocused and sharp over a set time.
# ABOUTME: ffmpeg decodes and encodes via the shared harness; the defocus is a disc convolution.

import os
import tempfile
import time

import folder_paths

from ._focus_pull import (
    DIRECTION_IN,
    DIRECTIONS,
    MIN_RADIUS_PX,
    disc_blur,
    focus_curve,
    max_radius_px,
)
from ._video_fx import DEFAULT_CRF, probe, process


class FocusPull:
    """
    Racks focus across the clip: the shot resolves from soft to sharp, or falls
    away from sharp to soft, over `seconds`.

    The whole frame moves together — there is no depth model here, so this is a
    rack between "the lens is on this shot" and "the lens is off it", not a
    rack between two planes inside one shot. That is what the shot it exists for
    actually needs: the subject is already the frame, and the pull is the reveal.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
                "direction": (DIRECTIONS, {
                    "default": DIRECTION_IN,
                    "tooltip": "Which way the lens travels. 'into focus' opens "
                               "the clip soft and lets it resolve — the reveal. "
                               "'out of focus' opens sharp and lets the shot "
                               "fall away, ending soft.",
                }),
                "strength": ("FLOAT", {
                    "default": 0.6, "min": 0.0, "max": 1.0, "step": 0.05,
                    "tooltip": "How far out of focus the soft end of the pull "
                               "goes. 0.3 is a gentle breath, 1.0 puts a face "
                               "past recognising. 0 passes the video through "
                               "untouched.",
                }),
                "seconds": ("FLOAT", {
                    "default": 1.2, "min": 0.1, "max": 10.0, "step": 0.1,
                    "tooltip": "How long the rack takes. It starts on the first "
                               "frame going into focus and lands on the last "
                               "frame coming out of it, so there is nothing to "
                               "line up. Longer than the clip and it simply "
                               "uses the whole clip.",
                }),
            },
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "execute"
    CATEGORY = "Symbiotica/Video"

    def _process_file(self, source_path, output_path, settings):
        info = probe(source_path)
        curve = focus_curve(info["n_frames"], info["fps"],
                            settings["direction"], settings["strength"],
                            info["height"], settings["seconds"])

        peak = max_radius_px(settings["strength"], info["height"])
        print(f"[Focus Pull] {info['width']}x{info['height']} @ "
              f"{info['fps']:.3f}fps, ~{info['n_frames']} frames, "
              f"{settings['direction']} over {settings['seconds']:.2f}s, "
              f"defocus radius {peak:.1f}px")

        def rack(frame, index, info):
            # ffprobe's frame count is an estimate, so a real clip can run past
            # the curve. Holding the last value is right either way: going in
            # the tail is already sharp, coming out it is already fully soft.
            radius = curve[index] if index < len(curve) else curve[-1]
            if radius < MIN_RADIUS_PX:
                return frame
            return disc_blur(frame, radius)

        n = process(source_path, output_path, rack, settings["crf"])
        print(f"[Focus Pull] {n} frames written.")

    def execute(self, video, direction=DIRECTION_IN, strength=0.6, seconds=1.2):
        from comfy_api.latest import InputImpl

        if strength <= 0.0:
            print("[Focus Pull] strength is 0, returning original video")
            return (video,)
        if direction not in DIRECTIONS:
            raise ValueError(f"unknown direction: {direction!r}")

        settings = {
            "direction": direction,
            "strength": strength,
            "seconds": seconds,
            "crf": DEFAULT_CRF,
        }

        temp_files = []
        try:
            source_path = tempfile.NamedTemporaryFile(
                suffix=".mp4", delete=False
            ).name
            temp_files.append(source_path)
            video.save_to(source_path, format="mp4", codec="h264")

            output_dir = folder_paths.get_output_directory()
            output_path = os.path.join(
                output_dir, f"focus_pull_{int(time.time())}.mp4"
            )

            self._process_file(source_path, output_path, settings)

            print(f"[Focus Pull] Done -> {output_path}")
            return (InputImpl.VideoFromFile(output_path),)
        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass


NODE_CLASS_MAPPINGS = {
    "FocusPull": FocusPull,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FocusPull": "Focus Pull",
}
