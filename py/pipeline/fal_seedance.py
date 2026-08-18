# ABOUTME: Seedance through fal on AI Gateway's fal passthrough — which endpoint
# ABOUTME: each model is, what it accepts, and the request and reply fal speaks.
from __future__ import annotations

from typing import NamedTuple

from . import ai_gateway

# Cloudflare's slug for fal, and fal's own synchronous host for the direct arm.
PROVIDER = "fal"
FAL_API_BASE = "https://fal.run"

# fal splits the models across endpoints rather than taking a model name in the
# body, so the label chooses the URL. Keyed by the labels the canvas already
# shows, so a graph reads the same whichever arm carries it.
ENDPOINTS = {
    "Seedance 2.5": "bytedance/seedance-2.5/reference-to-video",
    "Seedance 2.0": "bytedance/seedance-2.0/reference-to-video",
    "Seedance 2.0 Fast": "bytedance/seedance-2.0/fast/reference-to-video",
    "Seedance 2.0 Mini": "bytedance/seedance-2.0/mini/reference-to-video",
}

# `auto` is fal's name for what ByteDance calls `adaptive`, and it is accepted
# on every model here — so editing and extending a clip work throughout, which
# on the Cloudflare catalog route they do not.
RATIOS = ["auto", "21:9", "16:9", "4:3", "1:1", "3:4", "9:16"]


def _durations(longest: int) -> list:
    """The durations one model offers, as fal names them.

    Strings, not numbers: fal takes an enum here, and `auto` is one of its
    members — which is what lets a clip's own length carry through an edit."""
    return ["auto"] + [str(second) for second in range(4, longest + 1)]


class ModelLimits(NamedTuple):
    """What one model will accept through fal.

    These are ByteDance's own numbers rather than the Cloudflare catalog's
    smaller ones: 9 reference images and 3 clips on the 2.0 family where the
    catalog takes 4 and one."""
    resolutions: list
    ratios: list
    durations: list
    max_images: int
    max_videos: int
    max_audios: int
    max_reference_seconds: float


def _limits_20(resolutions):
    return ModelLimits(resolutions=resolutions, ratios=RATIOS,
                       durations=_durations(15),
                       max_images=9, max_videos=3, max_audios=3,
                       max_reference_seconds=15)


LIMITS = {
    "Seedance 2.5": ModelLimits(
        resolutions=["480p", "720p", "1080p"], ratios=RATIOS,
        durations=_durations(30),
        max_images=30, max_videos=10, max_audios=10,
        # fal states 30.2 rather than a round 30, and states the same 1.8s
        # floor the provider does. Rounded down it refuses clips fal takes.
        max_reference_seconds=30.2),
    "Seedance 2.0": _limits_20(["480p", "720p", "1080p", "4k"]),
    "Seedance 2.0 Fast": _limits_20(["480p", "720p"]),
    "Seedance 2.0 Mini": _limits_20(["480p", "720p"]),
}


def build_request(values: dict, images: list, videos: list,
                  audios: list, seed: int | None = None) -> dict:
    """One fal request body: everything but which endpoint it goes to.

    No model name. fal puts that in the URL, and a `model` key here is a field
    the endpoint does not have.

    References are omitted rather than sent empty, so a model that branches on
    whether a reference kind is present sees the same thing it would if the
    node had never offered the slot."""
    editing = bool(values.get("video_editing"))
    body = {
        "prompt": values["prompt"],
        "resolution": values["resolution"],
        # An edit takes its length and shape from the clip being edited, and
        # fal spells that `auto` on both fields — an enum member rather than an
        # absent key, so there is nothing to infer.
        "aspect_ratio": "auto" if editing else values["ratio"],
        "duration": "auto" if editing else values["duration"],
        "generate_audio": values["generate_audio"],
    }
    if seed is not None:
        body["seed"] = seed
    for key, refs in (("image_urls", images), ("video_urls", videos),
                      ("audio_urls", audios)):
        if refs:
            body[key] = list(refs)
    return body


def video_url(body: dict) -> str:
    """Where the finished render can be fetched, or what came back instead.

    fal hands the output back as a File object carrying its own `url`, not as a
    bare string. The whole reply is quoted when there is no video in it: fal
    puts its refusals in `detail`, and a bare "no video" sends the reader
    looking at our request when the answer is in theirs."""
    video = body.get("video") or {}
    url = video.get("url") if isinstance(video, dict) else video
    if url:
        return url
    raise RuntimeError(f"fal returned no video for this run: {body}")


def resolve_transport(environ, label: str, interactive_key) -> ai_gateway.Transport:
    """The gateway's fal path when one is configured, fal directly otherwise.

    fal is a passthrough provider, so this is the same arm the Gemini and
    Claude nodes take — which is the whole reason to prefer it over the model
    catalog: the studio's own stored key pays, selected by alias, and the spend
    stays inside the BYOK boundary."""
    return ai_gateway.resolve_transport(
        environ, PROVIDER, f"/{ENDPOINTS[label]}", interactive_key,
        ai_gateway.DirectArm(
            FAL_API_BASE, "The fal API key",
            # `Key`, not `Bearer`. Sent as Bearer it is a 401 that reads like a
            # key which has been revoked.
            lambda key: {"Authorization": f"Key {key}"}))
