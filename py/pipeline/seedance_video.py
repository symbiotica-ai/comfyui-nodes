# ABOUTME: Seedance video generation through Cloudflare's AI Gateway REST arm —
# ABOUTME: which models it offers, what each one accepts, and the request it sends.
from __future__ import annotations

import base64
import io
import wave
from typing import NamedTuple

import numpy as np
from PIL import Image

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
    reference images for the 2.0 family and offers `adaptive` on all four
    models; the catalog takes 4 and confines `adaptive` to 2.5. A schema built
    from the larger set would offer slots whose every render is refused before
    it starts.

    There is no video count. ByteDance takes a reference video only as a web
    URL, and everything this node can encode is inline."""
    resolutions: list
    ratios: list
    min_duration: int
    max_duration: int
    # Where the widgets open, matching ComfyUI's own node. It gives the 2.0
    # options no resolution default at all, so they open on the first entry;
    # opening them higher would make every freshly dropped node cost more than
    # the one this copies.
    default_resolution: str
    default_duration: int
    max_images: int
    max_audios: int
    output_formats: list
    max_reference_seconds: int


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
                       default_resolution=resolutions[0], default_duration=7,
                       max_images=4, max_audios=max_audios,
                       output_formats=[], max_reference_seconds=15)


LIMITS = {
    "Seedance 2.5": ModelLimits(
        resolutions=["480p", "720p"], ratios=RATIOS_25,
        min_duration=4, max_duration=30,
        default_resolution="720p", default_duration=5,
        max_images=30, max_audios=10,
        output_formats=["mp4", "mov"], max_reference_seconds=30),
    "Seedance 2.0": _limits_20(["480p", "720p", "1080p", "4k"]),
    "Seedance 2.0 Fast": _limits_20(["480p", "720p"]),
    "Seedance 2.0 Mini": _limits_20(["480p", "720p"], max_audios=1),
}


def build_request(label: str, values: dict, seed: int, watermark: bool,
                  images: list, audios: list) -> dict:
    """One `/ai/run` body: which model, and everything it is being asked for.

    `values` is the per-model combo's own widgets, so what is present here is
    already what that model offers — this decides only how each is named on the
    wire and which of them the model will accept.

    References are omitted rather than sent empty. An empty array is a claim
    that references were considered and none applied; leaving the key out
    leaves the model's own default untouched, and the two are not the same
    request to a model that branches on whether a reference kind is present."""
    limits = LIMITS[label]
    payload = {
        "prompt": values["prompt"],
        "resolution": values["resolution"],
        "seed": seed,
        "watermark": watermark,
        "generate_audio": values["generate_audio"],
    }
    # ComfyUI's node calls this `ratio`; the catalog calls it `aspect_ratio`
    # and refuses `ratio` outright as an unsupported field.
    payload["aspect_ratio"] = values["ratio"]
    payload["duration"] = values["duration"]
    if limits.output_formats:
        payload["output_format"] = values["output_format"]
    _attach(payload, "reference_image", images, limits.max_images)
    _attach(payload, "reference_audio", audios, limits.max_audios)
    return {"model": MODELS[label], "input": payload}


def _attach(payload: dict, singular: str, refs: list, cap: int) -> None:
    """The references of one kind, under the name this model knows them by.

    A model that takes many gets the plural array; one that takes a single
    reference gets a bare string under the singular name, and does not have
    the plural key at all — sending it fails the whole request rather than
    being ignored."""
    if not refs or cap < 1:
        return
    if cap == 1:
        payload[singular] = refs[0]
    else:
        payload[singular + "s"] = list(refs)


# Cloudflare stores no log above 10 MB, and AI Gateway analytics reads the log
# — so a request past that ceiling is spend that reaches no cockpit row, which
# is the whole reason this node routes through the gateway at all. The margin
# under 10 MB is for what JSON encoding adds on top of the bytes counted here.
# Same number and same reasoning as the Claude node's MAX_REQUEST_BYTES.
#
# Reference images are the whole of what this budget carries, and thirty of
# them at 2048px will not fit inside it. The images that do fit are the ones
# the render gets; the rest are refused rather than dropped.
MAX_REQUEST_BYTES = 8_000_000


def check_reference_size(refs) -> None:
    """Raise if the references will not fit inside one loggable request.

    Refuses rather than dropping references to fit. A video generated from two
    of five references is a wrong result that looks right, and that is the
    failure this pack exists not to ship. Measured on the encoded strings that
    actually cross the wire, because a check written against durations or
    dimensions cannot tell a static shot from a busy one at the same length."""
    size = sum(len(ref) for ref in refs)
    if size > MAX_REQUEST_BYTES:
        raise ValueError(
            f"The references encode to {size} bytes, over the "
            f"{MAX_REQUEST_BYTES} this node sends. Cloudflare stores no log "
            f"above 10 MB and AI Gateway analytics reads the log, so a request "
            f"this size would render without its spend ever being attributed "
            f"to the studio. Send fewer references, shorter clips, or smaller "
            f"images.")


def video_url(body: dict) -> str:
    """Where the finished render can be fetched, or what came back instead.

    Two envelopes deep. Cloudflare's own reply carries `result`, and the run
    inside it carries a `result` of its own alongside its `state` — so the URL
    is at `result.result.video`. Read one level too high it is simply absent,
    on every successful render.

    The catalog answers 200 even for a run that failed, so a refusal arrives
    here rather than as an HTTP error. The whole reply is quoted on the way
    out: a bare "no video in the response" sends the reader looking at our
    request when the answer is usually in theirs."""
    run = body.get("result") or {}
    url = (run.get("result") or {}).get("video")
    if url:
        return url
    raise RuntimeError(
        f"The gateway returned no video for this run: {body}")


# ByteDance's own bounds on a reference image, which the catalog forwards.
MIN_IMAGE_EDGE = 300
MAX_IMAGE_ASPECT = 2.5
MIN_IMAGE_ASPECT = 0.4
# Well under ByteDance's 6000px ceiling, and deliberately so. Seedance 2.5
# renders 720p at most, so detail past this is detail the model cannot use —
# and with thirty reference slots sharing one 8 MB budget, the ceiling that
# matters is ours, not theirs.
MAX_IMAGE_EDGE = 2048
# JPEG, unlike the Claude node's PNG. That node carries at most a couple of
# references and chose PNG so artifacts never reach a model being asked to
# read fine detail. Thirty references inside 8 MB is not a budget PNG can be
# spent on: one 2048px PNG photograph is most of it. The quality is high
# enough that the difference does not survive being resampled into 720p video.
JPEG_QUALITY = 90


def image_data_uri(image) -> str:
    """One reference image as the data URI the catalog accepts.

    Bounds are checked before encoding, so a graph wired to an unusable
    reference fails naming the slot rather than at ByteDance, whose message
    knows neither this node nor which of thirty images it meant."""
    width, height = image.size
    aspect = width / height
    if not MIN_IMAGE_ASPECT <= aspect <= MAX_IMAGE_ASPECT:
        raise ValueError(
            f"A reference image is {width}x{height}, an aspect ratio of "
            f"{aspect:.2f}. Seedance takes {MIN_IMAGE_ASPECT} to "
            f"{MAX_IMAGE_ASPECT}; crop it to something nearer the frame.")
    if min(width, height) < MIN_IMAGE_EDGE:
        raise ValueError(
            f"A reference image is {width}x{height}. Seedance takes nothing "
            f"under {MIN_IMAGE_EDGE}px on a side, and upscaling it here would "
            f"add pixels rather than detail.")
    return "data:image/jpeg;base64," + encode_jpeg(image, MAX_IMAGE_EDGE)


def encode_jpeg(image, edge: int) -> str:
    """The image as base64 JPEG, no larger than `edge` on its long side.

    Never enlarged — `thumbnail` guarantees that, and the guard above has
    already refused anything too small to be worth sending."""
    if max(image.size) > edge:
        image = image.copy()
        image.thumbnail((edge, edge), Image.LANCZOS)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


# ByteDance refuses a reference clip under this, on every model, and says so in
# these words: "audio duration (seconds) ... must be greater than or equal to
# 1.8". Not rounded up to 2: that would refuse clips the provider takes, and
# refuse them silently. The per-model ceiling is `max_reference_seconds` below.
MIN_REFERENCE_SECONDS = 1.8
PCM_FULL_SCALE = 32767


def audio_data_uri(audio, label: str) -> str:
    """One reference audio as the data URI the catalog accepts.

    WAV rather than mp3: it needs no encoder beyond the standard library, and
    reference audio is short enough by definition that the size it costs is
    spent inside the request budget rather than against it."""
    waveform = np.asarray(audio["waveform"])
    rate = int(audio["sample_rate"])
    seconds = waveform.shape[-1] / rate
    _check_reference_seconds(seconds, label, "audio")
    # (batch, channels, samples) -> interleaved frames, which is what WAV
    # stores. A file written straight from the array plays every channel in
    # sequence instead of together.
    channels = waveform[0] if waveform.ndim == 3 else waveform
    frames = np.clip(np.asarray(channels).T, -1.0, 1.0)
    pcm = (frames * PCM_FULL_SCALE).round().astype("<i2")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(pcm.shape[1] if pcm.ndim > 1 else 1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(pcm.tobytes())
    return ("data:audio/wav;base64,"
            + base64.b64encode(buffer.getvalue()).decode("ascii"))


def _check_reference_seconds(seconds: float, label: str, kind: str) -> None:
    """Raise unless this clip is a length the chosen model will take.

    The model is named because the same clip is fine on 2.5 and refused on
    Mini — a message that only gave the number would read as a bug in the
    clip rather than as a consequence of the model chosen."""
    if seconds < MIN_REFERENCE_SECONDS:
        raise ValueError(
            f"A reference {kind} is {seconds:.1f}s. Seedance takes nothing "
            f"under {MIN_REFERENCE_SECONDS}s.")
    ceiling = LIMITS[label].max_reference_seconds
    if seconds > ceiling:
        raise ValueError(
            f"A reference {kind} is {seconds:.1f}s, over the {ceiling}s "
            f"{label} takes. Trim it, or choose a model with more room.")


# What Cloudflare calls it when its own balance paid, rather than a key stored
# in the gateway.
UNIFIED_KEY_SOURCE = "Unified"


def key_source_warning(body: dict) -> str:
    """A line worth logging when this render's spend left the BYOK boundary.

    Every reply says which key paid, and on this path the answer is `Unified`
    until a ByteDance key is stored under the gateway's `default` alias. The
    render succeeds either way and nothing else in the system would ever
    mention it — so an unattributed render that looks perfect is exactly the
    thing worth saying out loud.

    Absent is not the same as Unified: warning about a field Cloudflare did not
    send would teach the reader to ignore the warning."""
    run = body.get("result") or {}
    source = (run.get("gatewayMetadata") or {}).get("keySource")
    if source != UNIFIED_KEY_SOURCE:
        return ""
    return (f"This render was billed with keySource={UNIFIED_KEY_SOURCE}: no "
            f"ByteDance key stored in the gateway paid for it, Cloudflare's "
            f"own balance did. The studio tag still rode on the call, so the "
            f"spend is attributable — but it is outside the BYOK boundary. "
            f"Store a ByteDance key under the gateway's `default` alias to "
            f"bring it back inside.")
