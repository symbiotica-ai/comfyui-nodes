# ABOUTME: Hypereel stack composite node — facecam over gameplay, hard-cut concat of
# ABOUTME: up to 4 pairs. Exact port of the platform's Modal compositor (compose-modal).
import os
import tempfile
import time

import folder_paths

from ._bins import FFMPEG, FFPROBE
from ._hypereel_ffmpeg import DEFAULT_LAYOUT, LAYOUTS, compose_pairs


class HypereelStackComposite:
    """Composites facecam + gameplay pairs into one reel in a named layout:
    vertical stacks (facecam over gameplay — the platform's Modal geometry) or
    gameplay-full layouts with the facecam in a chosen corner. Her voice plays
    full; game audio is mixed at `game_audio_gain` only when the gameplay has a
    track. Pairs become cuts, hard-cut-concatenated in order."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "facecam_1": ("VIDEO",),
                "gameplay_1": ("VIDEO",),
                "layout": (list(LAYOUTS.keys()), {"default": DEFAULT_LAYOUT}),
                "corner": (["bottom-right", "bottom-left", "top-right", "top-left"],
                           {"default": "bottom-right",
                            "tooltip": "Facecam position — used by the corner layouts."}),
                "game_audio_gain": ("FLOAT", {"default": 0.30, "min": 0.0, "max": 1.0, "step": 0.05}),
                "fps": ("INT", {"default": 30, "min": 12, "max": 60}),
                "crf": ("INT", {"default": 20, "min": 10, "max": 35}),
            },
            "optional": {
                "facecam_2": ("VIDEO",),
                "gameplay_2": ("VIDEO",),
                "facecam_3": ("VIDEO",),
                "gameplay_3": ("VIDEO",),
                "facecam_4": ("VIDEO",),
                "gameplay_4": ("VIDEO",),
            },
        }

    RETURN_TYPES = ("VIDEO", "INT")
    RETURN_NAMES = ("reel", "cuts")
    FUNCTION = "compose"
    CATEGORY = "Symbiotica/Hypereel"

    def compose(self, facecam_1, gameplay_1, layout, corner,
                game_audio_gain, fps, crf, **optional):
        from comfy_api.latest import InputImpl

        videos = {"facecam_1": facecam_1, "gameplay_1": gameplay_1, **optional}
        tempdir = tempfile.mkdtemp(prefix="hypereel_pairs_")
        temp_files = []
        try:
            pairs = []
            for i in range(1, 5):
                fc = videos.get(f"facecam_{i}")
                gp = videos.get(f"gameplay_{i}")
                if fc is None and gp is None:
                    continue
                if fc is None or gp is None:
                    raise ValueError(f"pair {i} needs BOTH facecam_{i} and gameplay_{i}")
                fc_path = os.path.join(tempdir, f"fc{i}.mp4")
                gp_path = os.path.join(tempdir, f"gp{i}.mp4")
                fc.save_to(fc_path, format="mp4", codec="h264")
                gp.save_to(gp_path, format="mp4", codec="h264")
                temp_files += [fc_path, gp_path]
                pairs.append((fc_path, gp_path))

            out = os.path.join(
                folder_paths.get_output_directory(),
                f"hypereel_reel_{int(time.time() * 1000)}.mp4",
            )
            cuts = compose_pairs(pairs, out, layout=layout, corner=corner,
                                 game_audio_gain=game_audio_gain,
                                 fps=fps, crf=crf, ffmpeg=FFMPEG, ffprobe=FFPROBE)
            return (InputImpl.VideoFromFile(out), cuts)
        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass
            try:
                os.rmdir(tempdir)
            except OSError:
                pass


NODE_CLASS_MAPPINGS = {
    "HypereelStackComposite": HypereelStackComposite,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HypereelStackComposite": "Hypereel Stack Composite (facecam over gameplay)",
}
