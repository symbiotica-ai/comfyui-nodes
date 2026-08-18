# ABOUTME: Seedance video generation through Cloudflare's AI Gateway REST arm —
# ABOUTME: which models it offers, what each one accepts, and the request it sends.
from __future__ import annotations

from typing import NamedTuple

# What the canvas shows against the slug Cloudflare's catalog answers to, in
# ComfyUI's own order and wording so a graph built against its node reads the
# same here. These are catalog slugs, not BytePlus model ids: the catalog
# resolves `bytedance/seedance-2.5` to `dreamina-seedance-2-5-260628` upstream,
# and pinning the dated id here would break the day BytePlus rolls it.
MODELS = {
    "Seedance 2.5": "bytedance/seedance-2.5",
    "Seedance 2.0": "bytedance/seedance-2.0",
    "Seedance 2.0 Fast": "bytedance/seedance-2.0-fast",
    "Seedance 2.0 Mini": "bytedance/seedance-2.0-mini",
}


class ModelLimits(NamedTuple):
    """What one model will accept, as the catalog wrapper accepts it.

    These are the wrapper's numbers, not BytePlus's. BytePlus itself takes 9
    reference images, 3 videos and 3 audios for the 2.0 family and offers
    `adaptive` on all four models; the catalog takes 4, one and none, and
    confines `adaptive` to 2.5. A schema built from the larger set would offer
    slots whose every render is refused before it starts."""
    resolutions: list
    ratios: list
    min_duration: int
    max_duration: int
    max_images: int
    max_videos: int
    max_audios: int
    output_formats: list


# 9:21 is the catalog's own addition on the 2.0 family — ComfyUI's node does
# not offer it, and it costs nothing to pass along.
RATIOS_20 = ["16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "9:21"]
RATIOS_25 = ["16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"]


def _limits_20(resolutions, max_audios=0):
    """The 2.0 models differ in which resolutions they render, and in whether
    they take an audio reference at all — Mini has a singular `reference_audio`
    the other two do not, and sending one to Fast is refused outright."""
    return ModelLimits(resolutions=resolutions, ratios=RATIOS_20,
                       min_duration=4, max_duration=12,
                       max_images=4, max_videos=1, max_audios=max_audios,
                       output_formats=[])


LIMITS = {
    "Seedance 2.5": ModelLimits(
        resolutions=["480p", "720p"], ratios=RATIOS_25,
        min_duration=4, max_duration=30,
        max_images=30, max_videos=10, max_audios=10,
        output_formats=["mp4", "mov"]),
    "Seedance 2.0": _limits_20(["480p", "720p", "1080p", "4k"]),
    "Seedance 2.0 Fast": _limits_20(["480p", "720p"]),
    "Seedance 2.0 Mini": _limits_20(["480p", "720p"], max_audios=1),
}
