# ABOUTME: Hypereel stack composite node — facecam over gameplay, hard-cut concat of
# ABOUTME: up to 4 pairs. Exact port of the platform's Modal compositor (compose-modal).
import os
import tempfile
import time

import folder_paths

from ._bins import FFMPEG, FFPROBE
from ._hypereel_cancel import as_comfy_cancel, cancelled
from ._hypereel_ffmpeg import DEFAULT_LAYOUT, LAYOUTS, compose_pairs


class HypereelStackComposite:
    """Composites facecam + gameplay pairs into one reel in a named layout:
    vertical stacks (facecam over gameplay — the platform's Modal geometry) or
    gameplay-full layouts with the facecam in a chosen corner. Wire a keyer's
    MASK into mask_n and that pair's facecam becomes a CUTOUT silhouette in the
    corner instead of a rectangle (corner layouts only). Her voice plays full;
    game audio is mixed at `game_audio_gain` only when the gameplay has a track.
    Pairs become cuts, hard-cut-concatenated in order."""

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
                "mask_1": ("MASK",),
                "facecam_2": ("VIDEO",),
                "gameplay_2": ("VIDEO",),
                "mask_2": ("MASK",),
                "facecam_3": ("VIDEO",),
                "gameplay_3": ("VIDEO",),
                "mask_3": ("MASK",),
                "facecam_4": ("VIDEO",),
                "gameplay_4": ("VIDEO",),
                "mask_4": ("MASK",),
            },
        }

    RETURN_TYPES = ("VIDEO", "INT")
    RETURN_NAMES = ("reel", "cuts")
    FUNCTION = "compose"
    CATEGORY = "Symbiotica/Hypereel"

    def compose(self, facecam_1, gameplay_1, layout, corner,
                game_audio_gain, fps, crf, **optional):
        import numpy as np

        from comfy_api.latest import InputImpl

        from ._hypereel_glow import probe_video
        from ._hypereel_ffmpeg import write_gray_video

        videos = {"facecam_1": facecam_1, "gameplay_1": gameplay_1, **optional}
        tempdir = tempfile.mkdtemp(prefix="hypereel_pairs_")
        temp_files = []
        try:
            pairs = []
            for i in range(1, 5):
                fc = videos.get(f"facecam_{i}")
                gp = videos.get(f"gameplay_{i}")
                mk = videos.get(f"mask_{i}")
                if fc is None and gp is None:
                    continue
                if fc is None or gp is None:
                    raise ValueError(f"pair {i} needs BOTH facecam_{i} and gameplay_{i}")
                fc_path = os.path.join(tempdir, f"fc{i}.mp4")
                gp_path = os.path.join(tempdir, f"gp{i}.mp4")
                fc.save_to(fc_path, format="mp4", codec="h264")
                gp.save_to(gp_path, format="mp4", codec="h264")
                temp_files += [fc_path, gp_path]
                mk_path = None
                if mk is not None:
                    # MASK tensor (B,H,W, float 0-1) -> grayscale video at the
                    # facecam's frame rate, so alphamerge pairs frames 1:1.
                    frames = (mk.cpu().numpy() * 255.0 + 0.5).astype(np.uint8)
                    _, _, mask_fps, _ = probe_video(FFPROBE, fc_path)
                    mk_path = os.path.join(tempdir, f"mask{i}.mp4")
                    write_gray_video(FFMPEG, frames, frames.shape[2], frames.shape[1],
                                     mask_fps, mk_path)
                    temp_files.append(mk_path)
                pairs.append((fc_path, gp_path, mk_path))

            out = os.path.join(
                folder_paths.get_output_directory(),
                f"hypereel_reel_{int(time.time() * 1000)}.mp4",
            )
            try:
                cuts = compose_pairs(pairs, out, layout=layout, corner=corner,
                                     game_audio_gain=game_audio_gain, fps=fps, crf=crf,
                                     ffmpeg=FFMPEG, ffprobe=FFPROBE, interrupt=cancelled)
                return (InputImpl.VideoFromFile(out), cuts)
            except InterruptedError as e:
                as_comfy_cancel(e)
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
