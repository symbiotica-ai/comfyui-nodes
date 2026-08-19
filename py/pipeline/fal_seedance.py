# ABOUTME: Seedance through fal on AI Gateway's fal passthrough — which endpoint
# ABOUTME: each model is, what it accepts, and the request and reply fal speaks.
from __future__ import annotations

import base64
import io
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


def chosen_arm(environ, has_key: bool) -> str:
    """Which route this box should take: "fal" or "catalog".

    fal wins wherever it is reachable. On an order sandbox both are, and fal is
    the one where the studio's own stored key pays — taking the catalog there
    would move the spend outside the BYOK boundary while a perfectly good fal
    route sat unused.

    The catalog is the fall back rather than the choice because it bills a
    single shared key, cannot carry a reference video at all, and cuts the 2.0
    family's reference counts by more than half."""
    if (environ.get("SYMBIOTICA_AIG_BASE") or "").strip():
        return "fal"
    # A personal key ranks below every route the box was configured with, the
    # same way `resolve_transport` ranks it below the gateway. Above them it is
    # the failure nobody detects afterwards: the render succeeds on somebody's
    # own key and the spend leaves the studio without an error to notice.
    if (environ.get("SYMBIOTICA_CF_ACCOUNT_ID") or "").strip():
        return "catalog"
    if has_key:
        return "fal"
    raise ValueError(
        "This box has no way to reach Seedance. Either give it "
        "SYMBIOTICA_AIG_BASE and SYMBIOTICA_AIG_TOKEN — from the "
        "symbiotica-comfy-aigateway secret on a sandbox, or under Settings → "
        "Symbiotica → AI Gateway on a box with no environment to set — which "
        "routes through fal on the studio's own key, or a personal fal key "
        "under Settings → Symbiotica → API Keys or in the environment — or "
        "SYMBIOTICA_CF_ACCOUNT_ID, SYMBIOTICA_CF_API_TOKEN and "
        "SYMBIOTICA_AIG_GATEWAY_ID for the Cloudflare catalog, which is the "
        "poorer route and bills a shared key.")


def check_fal_can_carry(watermark: bool) -> None:
    """Raise for anything the node offers that fal has no field for.

    Only the watermark today. fal writes no watermark and takes no such
    parameter, so a graph asking for one would get a clean video back and
    differ from the same graph on the catalog arm with nothing said."""
    if watermark:
        raise ValueError(
            "watermark is on, and fal has no watermark parameter — the render "
            "would come back clean with nothing to say so. Turn it off, or "
            "use a box that reaches Seedance through the Cloudflare catalog.")


def check_catalog_can_carry(label: str, images: int, videos: int,
                            audios: int, resolution: str = "",
                            duration: int = 0, ratio: str = "") -> None:
    """Raise unless the catalog arm can carry what has been wired.

    The schema offers fal's slots, because fal is the route the node is for. So
    a graph built against it can reach a box that has only the catalog, and
    what fits there is smaller. Refused by name rather than quietly dropped: a
    render that ignored the clips would come back looking finished."""
    from . import seedance_video as catalog
    limits = catalog.LIMITS[label]
    if videos:
        raise ValueError(
            f"{videos} reference video(s) are wired, and this box reaches "
            f"Seedance through the Cloudflare catalog, which takes none — "
            f"ByteDance accepts a reference video only as a public URL there. "
            f"Give this box the gateway's fal route, or unwire the clips.")
    if images > limits.max_images:
        raise ValueError(
            f"{images} reference images are wired and the Cloudflare catalog "
            f"takes {limits.max_images} for {label}. Through fal it takes "
            f"{LIMITS[label].max_images}; give this box the gateway's fal "
            f"route, or wire fewer.")
    if audios > limits.max_audios:
        raise ValueError(
            f"{audios} reference audio track(s) are wired and the Cloudflare "
            f"catalog takes {limits.max_audios} for {label}. Through fal it "
            f"takes {LIMITS[label].max_audios}.")
    # The widgets are fal's, so they offer settings this arm does not render.
    # Passed through, each is an upstream 400 naming neither node nor widget.
    if resolution and resolution not in limits.resolutions:
        raise ValueError(
            f"{label} renders {resolution} through fal, and through the "
            f"Cloudflare catalog it renders "
            f"{', '.join(limits.resolutions)}. Pick one of those, or give "
            f"this box the gateway's fal route.")
    if duration and duration > limits.max_duration:
        raise ValueError(
            f"{duration}s is asked for and the Cloudflare catalog stops at "
            f"{limits.max_duration}s for {label}, where fal runs to "
            f"{LIMITS[label].durations[-1]}s.")
    if ratio and ratio not in limits.ratios:
        # `adaptive` is the default on the whole 2.0 family and the catalog
        # takes it on 2.5 alone. Substituting 16:9 gave a render nobody asked
        # for and said nothing about it.
        raise ValueError(
            f"ratio '{ratio}' is asked for and the Cloudflare catalog does "
            f"not take it on {label} — it offers "
            f"{', '.join(limits.ratios)}. Through fal every model takes it.")


# Defaults for this module, which must stay importable without ComfyUI. The node
# passes comfy_api's own VideoContainer and VideoCodec: they are str enums, so
# these compare equal, but ComfyUI branches on `isinstance(format,
# VideoContainer)` when deciding what to tell ffmpeg.
MP4 = "mp4"
H264 = "h264"


def video_data_uri(video, label: str, container=MP4, codec=H264,
                   budget=None, resize=None) -> str:
    """One reference clip as a data URI.

    Re-encoded to h264 in mp4 whatever it arrived as: a ComfyUI VIDEO may hold
    any container ffmpeg reads, and fal documents mp4 and mov alone — so passing
    the source bytes through would work for most clips and fail for the ones
    somebody had to convert in the first place."""
    from . import seedance_video as media
    length = seconds(video)
    ceiling = LIMITS[label].max_reference_seconds
    if length and length < media.MIN_REFERENCE_SECONDS:
        raise ValueError(
            f"A reference clip is {length:.1f}s. Seedance takes nothing under "
            f"{media.MIN_REFERENCE_SECONDS}s.")
    if length > ceiling:
        raise ValueError(
            f"A reference clip is {length:.1f}s, over the {ceiling}s "
            f"{label} takes. Trim it, or choose a model with more room.")
    buffer = io.BytesIO()
    video.save_to(buffer, format=container, codec=codec)
    payload = fit_to_budget(buffer.getvalue(), _dimensions(video), budget,
                            resize)
    return ("data:video/mp4;base64,"
            + base64.b64encode(payload).decode("ascii"))


def _dimensions(video):
    """The clip's width and height, or (0, 0) when it will not say.

    Unknown reads as inside every budget, so a clip whose dimensions cannot be
    read goes unscaled rather than being scaled against a guess."""
    try:
        return int(video.get_dimensions()[0]), int(video.get_dimensions()[1])
    except Exception:
        return 0, 0


def seconds(video) -> float:
    """How long the clip runs, or 0 when it will not say.

    A container the reader cannot seek gives no duration, and refusing the clip
    for that would refuse it for the reader's limitation rather than for
    anything about the clip. fal still checks its own bounds."""
    try:
        return float(video.get_duration())
    except Exception:
        return 0.0


# The one model that will run on a reference audio with nothing else, which is
# the exception ComfyUI's own node makes and makes only here.
AUDIO_ONLY_MODEL = "Seedance 2.5"


def check_has_references(label: str, images: int, videos: int,
                         audios: int) -> None:
    """Raise unless something was actually wired in to reference.

    Without this a reference node quietly becomes a text-to-video node, which
    the pack already ships separately — and the render succeeds, so nobody
    finds out they were using the wrong node."""
    if images or videos:
        return
    if audios and label == AUDIO_ONLY_MODEL:
        return
    kinds = ("image, video or audio" if label == AUDIO_ONLY_MODEL
             else "image or video")
    raise ValueError(
        f"{label} needs at least one reference {kinds} — that is what this "
        f"node is for. For a video from the prompt alone, use a text-to-video "
        f"node instead.")


def check_total_seconds(label: str, lengths, kind: str) -> None:
    """Raise if these references are over budget taken together.

    Each clip inside its own bounds says nothing about the set: three five
    second clips are individually fine and collectively over on some models.
    Checked here because the alternative is discovering it after the whole
    encoded set has crossed the wire."""
    total = sum(lengths)
    ceiling = LIMITS[label].max_reference_seconds
    if total > ceiling:
        raise ValueError(
            f"The reference {kind}s run to {total:.1f}s together, over the "
            f"{ceiling}s {label} takes across all of them. Each one is inside "
            f"its own limit; it is the total that is over.")


# fal's queue host. The synchronous host holds the connection for the whole
# render, and a thirty-second 2.5 clip takes long enough that fal's own clients
# use the queue for these models rather than treating it as an optimisation.
QUEUE_BASE = "https://queue.fal.run"

FINISHED = "COMPLETED"
# Everything else fal reports is either still running or already lost.
RUNNING = ("IN_QUEUE", "IN_PROGRESS")


def queue_target(label: str) -> str:
    """Where a job for this model is submitted."""
    return f"{QUEUE_BASE}/{ENDPOINTS[label]}"


def status_target(submitted: dict) -> str:
    """Where to ask how the job is going, as fal itself named it.

    Read from the reply rather than built from the endpoint: fal drops the
    model's sub-path in the URLs it hands back, so a constructed
    `/reference-to-video/requests/{id}/status` answers 405."""
    return _named(submitted, "status_url")


def result_target(submitted: dict) -> str:
    """Where the finished render will be, as fal itself named it."""
    return _named(submitted, "response_url")


def _named(submitted: dict, key: str) -> str:
    found = submitted.get(key)
    if found:
        return found
    raise RuntimeError(
        f"fal's reply carries no {key}, so there is nowhere to follow this "
        f"job: {submitted}")


def queue_transport(environ, target: str, interactive_key):
    """A transport aimed at one fal URL, through the gateway or straight at it.

    The gateway's fal passthrough takes the real destination in
    `x-fal-target-url` rather than in the path, so the URL stays `{base}/fal`
    and the studio's key is still injected by alias. Without a gateway the
    target is simply the URL."""
    return ai_gateway.resolve_transport(
        environ, PROVIDER, "", interactive_key,
        ai_gateway.DirectArm(target, "The fal API key",
                             lambda key: {"Authorization": f"Key {key}"}),
        extra_headers={"x-fal-target-url": target})


def request_id(body: dict) -> str:
    """The id of the job just submitted, or what came back instead."""
    found = body.get("request_id")
    if found:
        return found
    raise RuntimeError(f"fal accepted no job for this request: {body}")


def is_finished(body: dict) -> bool:
    """Whether the job is done, raising if fal has given up on it.

    A failed job left to the polling loop would wait out the whole timeout and
    then report a timeout, which sends the reader looking at the network rather
    than at the refusal fal already sent."""
    status = body.get("status")
    if status == FINISHED:
        return True
    if status in RUNNING:
        return False
    raise RuntimeError(f"fal stopped working on this render: {body}")


# What ByteDance will accept as a reference clip, in total pixels, keyed by the
# model and by the resolution being rendered. Not one number: the 2.0 family
# stops at 927,408 — 834x1112 — where 2.5 takes eight million, so the same
# clip is fine on one model and refused on the next. fal documents the same
# ceiling in words ("~480p to ~720p"), which is the same 927,408.
#
# A 1920x1080 clip is 2,073,600 pixels, so an ordinary 1080p reference is over
# budget on the whole 2.0 family. That is what makes auto_downscale worth a
# widget rather than a footnote.
PIXEL_BUDGETS = {
    "Seedance 2.5": {"480p": (409_600, 8_295_044),
                     "720p": (409_600, 8_295_044)},
    "Seedance 2.0": {"480p": (409_600, 927_408),
                     "720p": (409_600, 927_408),
                     "1080p": (409_600, 2_073_600)},
    "Seedance 2.0 Fast": {"480p": (409_600, 927_408),
                          "720p": (409_600, 927_408)},
    "Seedance 2.0 Mini": {"480p": (409_600, 927_408),
                          "720p": (409_600, 927_408)},
}


def pixel_budget(label: str, resolution: str):
    """What a reference clip may measure for this model at this resolution.

    None where nothing is published — 4k on 2.0, for one. Inventing a budget
    there would scale a clip against a number nobody stated, so the clip goes
    as it is and the provider rules on it."""
    return PIXEL_BUDGETS.get(label, {}).get(resolution)


def scale_for_budget(width: int, height: int, budget):
    """The size this clip should be re-encoded at, or None to leave it alone.

    Aspect is preserved and both sides come back even, because h264 will not
    take odd dimensions. The result is clamped to the far bound as well as the
    near one: on a budget as narrow as the 2.0 family's, lifting a small clip
    to the floor can carry it past the ceiling in one step."""
    if not budget or width <= 0 or height <= 0:
        return None
    low, high = budget
    pixels = width * height
    if low <= pixels <= high:
        return None
    target = low if pixels < low else high
    scale = (target / pixels) ** 0.5
    for _ in range(4):
        sized = (_even(width * scale), _even(height * scale))
        if low <= sized[0] * sized[1] <= high:
            return sized
        # Rounding to even can step over a bound on a narrow budget; walk the
        # scale back toward the middle of the range rather than give up.
        scale *= ((low + high) / 2 / (sized[0] * sized[1])) ** 0.5
    return sized


def _even(value: float) -> int:
    """The nearest even number at or above two, which is h264's floor."""
    return max(2, int(round(value / 2)) * 2)


def fit_to_budget(payload: bytes, size, budget, resize) -> bytes:
    """The clip re-encoded to fit its model's budget, or exactly as it came.

    `resize` is passed in rather than imported so the decision — which sizes
    need changing, and to what — stays testable without ffmpeg on the box. None
    means the caller turned the switch off, and the clip goes unscaled for the
    provider to judge, which is what ComfyUI's own node does with it off."""
    if resize is None:
        return payload
    scaled = scale_for_budget(size[0], size[1], budget)
    if scaled is None:
        # Re-encoding costs a generation of quality for nothing.
        return payload
    return resize(payload, scaled[0], scaled[1])
