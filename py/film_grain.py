# ABOUTME: Film grain node — emulsion grain on a VIDEO, sized by the gauge, not the pixel.
# ABOUTME: ffmpeg decode and encode come from _video_fx; the grain itself from _film_grain.

import os
import tempfile
import time

import folder_paths

from ._film_grain import (
    DEFAULT_PRESET,
    grain_size_px,
    make_grain,
    preset_choices,
)
from ._video_fx import DEFAULT_CRF, probe, process


class FilmGrain:
    """
    Lays film grain over a video: luminance-dependent, sized from the film
    gauge, re-rolled every frame.

    Three things separate this from adding noise, and all three are what the eye
    is actually reading when it calls something "filmic". Grain is strongest in
    the midtones and dies away in deep shadow and blown highlight, because that
    is where an emulsion has crystals left to vary. Grain is a fixed physical
    size on the negative, so it does not get finer as the footage gets sharper.
    And it is rolled fresh every frame — a fixed pattern is sensor noise, and
    reads as one immediately.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
                "preset": (preset_choices(), {
                    "default": DEFAULT_PRESET,
                    "tooltip": "Which film stock to imitate. 35mm is the fine, "
                               "barely-there grain of a modern feature and the "
                               "safe choice. 16mm is coarser and visibly "
                               "speckled, the documentary and indie look. "
                               "Super 8 is heavy, chunky home-movie grain. "
                               "35mm B&W is grey grain with no colour speckle "
                               "at all, because black-and-white film has only "
                               "one layer to grain.",
                }),
                "strength": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 3.0, "step": 0.05,
                    "tooltip": "How much grain, against how much that stock "
                               "normally has. 1.0 is the stock as shot; 0.5 is "
                               "a hint of it; above 1.5 it starts to be the "
                               "point rather than the texture. 0 passes the "
                               "video through untouched.",
                }),
                "seed": ("INT", {
                    "default": 0, "min": 0, "max": 100000, "step": 1,
                    "tooltip": "Same settings with a different number give a "
                               "different roll of the grain. Change it so two "
                               "takes cut together do not share the same "
                               "speckle.",
                }),
            },
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "execute"
    CATEGORY = "Symbiotica/Video"

    def _process_file(self, source_path, output_path, settings):
        # Probed here rather than left to process(): the plate is sized from the
        # frame geometry and has to exist before the first frame arrives.
        info = probe(source_path)
        width, height = info["width"], info["height"]

        clump = grain_size_px(settings["preset"], width, height)
        print(f"[Film Grain] {width}x{height} @ {info['fps']:.3f}fps, "
              f"~{info['n_frames']} frames, preset={settings['preset']}, "
              f"strength={settings['strength']}, seed={settings['seed']}")
        print(f"[Film Grain] grain clump is {clump:.2f}px on this frame")
        if clump <= 1.0:
            print("[Film Grain] WARNING: this stock's grain is finer than a "
                  "pixel at this resolution, so it will look like noise rather "
                  "than like grain. Use a smaller gauge or a larger frame.")

        grain = make_grain(settings["preset"], width, height,
                           strength=settings["strength"], seed=settings["seed"])
        frames = process(source_path, output_path, grain, settings["crf"])
        print(f"[Film Grain] {frames} frames written.")

    def execute(self, video, preset=DEFAULT_PRESET, strength=1.0, seed=0):
        from comfy_api.latest import InputImpl

        if strength <= 0.0:
            print("[Film Grain] strength is 0, returning original video")
            return (video,)
        if preset not in preset_choices():
            raise ValueError(f"unknown preset: {preset!r}")

        settings = {
            "preset": preset,
            "strength": strength,
            "seed": seed,
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
                output_dir, f"film_grain_{int(time.time())}.mp4"
            )

            self._process_file(source_path, output_path, settings)

            print(f"[Film Grain] Done -> {output_path}")
            return (InputImpl.VideoFromFile(output_path),)
        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass


NODE_CLASS_MAPPINGS = {
    "FilmGrain": FilmGrain,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "FilmGrain": "Film Grain",
}
