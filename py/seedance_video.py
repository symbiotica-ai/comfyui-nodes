# ABOUTME: Seedance reference-to-video node — reference images, clips and audio
# ABOUTME: become a video, billed through Cloudflare AI Gateway rather than Comfy.
import logging
import os
import tempfile
import time

import requests
from comfy_api.latest import io, Types

from .pipeline import seedance_video as catalog
from .pipeline import fal_seedance as fal
from .pipeline.reference_images import to_pil, slot_order
from .pipeline import ai_gateway

# A 720p Seedance render is minutes of work and /ai/run holds the connection
# open for all of it — background mode would need a public webhook this box has
# not got. So the read timeout is sized for the longest render the node can ask
# for rather than for a normal HTTP call.
# How long a render may take before this node stops waiting for it. Measured:
# four seconds of 480p on 2.5 took 221s, and the node offers thirty seconds at
# 720p — so the ceiling is generous rather than tight.
REQUEST_TIMEOUT_S = 3600
# Each individual request is short now that the render happens behind the
# queue: a submission, then a status read every few seconds.
READ_TIMEOUT_S = 120
# Long enough that a minutes-long render does not fill the gateway log with
# polls, short enough that a finished render is picked up promptly.
POLL_INTERVAL_S = 5


LABEL_25 = "Seedance 2.5"

# ComfyUI's own names, kept verbatim so a graph reads the same on either node.
# `adaptive` is what it calls the ratio a reference clip decides; fal spells the
# same thing `auto`, and the mapping happens on the way out.
RATIOS = ["16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive"]
ADAPTIVE = "adaptive"


def _default_resolution(label):
    """Where the resolution widget opens, as ComfyUI's own node opens it.

    It gives the 2.0 options no default at all, so they open on the first entry
    — the cheapest one. Opening them higher would make a freshly dropped node
    cost more per render than the node this copies."""
    return "720p" if label == LABEL_25 else "480p"


def _default_ratio(label):
    """ComfyUI defaults the 2.0 options to `adaptive` and 2.5 to 16:9."""
    return "16:9" if label == LABEL_25 else ADAPTIVE


def _default_duration(label):
    return 5 if label == LABEL_25 else 7


def _model_inputs(label):
    """The widgets one model carries, and only the ones it will accept.

    Built per option rather than shared: the four models differ in what they
    take, and a single flat input list can only offer the union — every widget
    in it that the chosen model does not have is a render refused before it
    starts.

    Sized to fal, which is the route this node is for. Where a box can only
    reach the Cloudflare catalog the slots are the same and fewer of them can
    be filled, which `check_catalog_can_carry` says by name at render time
    rather than by hiding sockets that exist everywhere else."""
    limits = fal.LIMITS[label]
    longest = int(limits.durations[-1])
    inputs = [
        io.String.Input("prompt", multiline=True, default="",
                        tooltip="What to make. Put spoken lines in double "
                                "quotes to steer the generated dialogue."),
        io.Combo.Input("resolution", options=limits.resolutions,
                       default=_default_resolution(label),
                       tooltip="Resolution of the output video."),
        io.Combo.Input("ratio", options=RATIOS, default=_default_ratio(label),
                       tooltip="Aspect ratio of the output video. 'adaptive' "
                               "takes it from the reference clip."),
        io.Int.Input("duration", default=_default_duration(label), min=4,
                     max=longest, step=1,
                     display_mode=io.NumberDisplay.slider,
                     tooltip=f"Length of the output video in seconds "
                             f"(4-{longest})."),
        io.Boolean.Input("generate_audio", default=True,
                         tooltip="Generate a soundtrack along with the video."),
    ]
    if label == LABEL_25:
        inputs.append(io.Boolean.Input(
            "video_editing", default=False,
            tooltip="Enable when the prompt edits a connected reference "
                    "video, for example replacing an object in it. The output "
                    "then keeps the source clip's own length and shape, and "
                    "the duration and ratio widgets are ignored."))
    inputs.append(io.Boolean.Input(
        "auto_downscale", default=True, optional=True,
        tooltip="Shrink reference clips that are over the model's pixel "
                "budget for the chosen resolution. An ordinary 1080p clip is "
                "over it on every 2.0 model, so with this off such a clip is "
                "simply refused. Aspect ratio is kept, and clips already "
                "inside the budget are not re-encoded."))
    inputs.append(io.Boolean.Input(
        "auto_upscale", default=False, advanced=True, optional=True,
        tooltip="Enlarge reference clips that fall under the model's minimum "
                "pixel count. Aspect ratio is kept. Enlarging a small clip "
                "adds no detail it did not have, which is why it is off."))
    inputs.append(_slots("images", io.Image.Input("reference_image"),
                         "image", limits.max_images))
    inputs.append(_slots("videos", io.Video.Input("reference_video"),
                         "video", limits.max_videos))
    inputs.append(_slots("audios", io.Audio.Input("reference_audio"),
                         "audio", limits.max_audios))
    return inputs


def _slots(name, template, prefix, count):
    """One kind of reference, as many slots as this model will carry.

    Named rather than prefixed, because the names have to start at 1 to match
    the way the prompt refers to them — a prefix template numbers from zero."""
    return io.Autogrow.Input(
        name,
        template=io.Autogrow.TemplateNames(
            template,
            names=[f"{prefix}_{i}" for i in range(1, count + 1)],
            min=0),
        tooltip=f"Reference {prefix}s, in slot order. {count} is what this "
                f"model takes.")


class SymbioticaSeedanceReference(io.ComfyNode):
    """Generate video from reference images, clips and audio with Seedance.

    The call goes through Cloudflare AI Gateway to ByteDance's models in the
    Cloudflare catalog, tagged with the studio so its spend reaches the
    cockpit. There is no direct arm: a catalog model has no provider endpoint
    of its own to call on a personal key."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaSeedanceReference",
            display_name="Seedance Reference to Video (Symbiotica)",
            category="symbiotica/video",
            description="Generate, edit or extend video with Seedance 2.5 or "
                        "2.0 from reference images, videos and audio, billed "
                        "through Cloudflare AI Gateway rather than to a "
                        "ComfyUI account.",
            inputs=[
                io.DynamicCombo.Input(
                    "model",
                    options=[io.DynamicCombo.Option(label,
                                                    _model_inputs(label))
                             for label in fal.ENDPOINTS],
                    tooltip="2.5 is the newest, takes the most references "
                            "and runs to 30s; 2.0 reaches 4k; Fast trades "
                            "quality for speed and Mini is the cheap lever."),
                io.Int.Input("seed", default=0, min=0, max=2147483647, step=1,
                             display_mode=io.NumberDisplay.number,
                             control_after_generate=True,
                             tooltip="Seed decides whether this node re-runs; "
                                     "results are not reproducible from it."),
                io.Boolean.Input("watermark", default=False, advanced=True,
                                 tooltip="Add ByteDance's watermark to the "
                                         "output video."),
            ],
            outputs=[io.Video.Output(display_name="video")],
        )

    @classmethod
    def execute(cls, model, seed, watermark=False) -> io.NodeOutput:
        # The chosen option's own widgets ride inside the combo's value rather
        # than arriving as keywords, so everything gated on the model is read
        # from here.
        label = model["model"]
        prompt = (model.get("prompt") or "").strip()
        if not prompt:
            raise ValueError(
                "Seedance needs a prompt. Reference images say what is in the "
                "shot; the prompt is what happens in it.")

        def interactive_key():
            from ._settings import resolve_provider_key
            return resolve_provider_key("", ["FAL_KEY", "FAL_API_KEY"], "fal")

        # Before any encoding: the references cost a device copy and a full
        # re-encode apiece, and a box with no route configured cannot send them
        # anywhere.
        arm = fal.chosen_arm(os.environ, has_key=_has_fal_key())

        wired_images = to_pil(model.get("images"))
        wired_videos = _wired(model.get("videos"))
        wired_audios = _wired(model.get("audios"))
        # fal's own ceiling, not the catalog's — 30.2s where the catalog says
        # 30, so a 30.1s track is fine on the arm this node prefers.
        ceiling = fal.LIMITS[label].max_reference_seconds
        # Before any encoding: each reference costs a device copy and a full
        # re-encode, and none of these checks needs the encoded bytes.
        fal.check_has_references(label, len(wired_images), len(wired_videos),
                                 len(wired_audios))
        fal.check_total_seconds(label, [fal.seconds(v) for v in wired_videos],
                                "clip")
        fal.check_total_seconds(label, [_audio_seconds(a)
                                        for a in wired_audios], "audio")

        images = [catalog.image_data_uri(image) for image in wired_images]
        videos = wired_videos
        audios = [catalog.audio_data_uri(audio, label, ceiling)
                  for audio in wired_audios]
        if arm == "catalog":
            fal.check_catalog_can_carry(
                label, len(images), len(videos), len(audios),
                resolution=model["resolution"], duration=model["duration"],
                ratio=model["ratio"])
            if model.get("video_editing"):
                # It needs a source clip, and this arm cannot carry one. Left
                # unsaid it is simply ignored, and the render comes back the
                # length the widgets asked for rather than the clip's.
                raise ValueError(
                    "video_editing needs a reference clip, and this box "
                    "reaches Seedance through the Cloudflare catalog, which "
                    "carries none. Give it the gateway's fal route.")
            return cls._through_catalog(label, model, seed, watermark,
                                        images, audios)
        return cls._through_fal(label, model, seed, watermark, images,
                                videos, audios, interactive_key)

    @classmethod
    def _through_fal(cls, label, model, seed, watermark, images, videos,
                     audios, interactive_key) -> io.NodeOutput:
        """The route the node is for: the studio's own key, by alias.

        Submitted to fal's queue rather than its synchronous host. Thirty
        seconds of 2.5 is minutes of work — a four-second 480p clip measured at
        221s — and a synchronous call spends all of it holding a connection
        open, with no way to report progress and no way to notice a cancel."""
        fal.check_fal_can_carry(watermark)
        budget = fal.pixel_budget(label, model["resolution"])
        clips = [fal.video_data_uri(
                     video, label, Types.VideoContainer.MP4,
                     Types.VideoCodec.H264, budget, _resizer(model, budget))
                 for video in videos]
        catalog.check_reference_size(images + clips + audios)
        values = dict(model)
        if values.get("ratio") == ADAPTIVE:
            values["ratio"] = "auto"
        values["duration"] = str(values["duration"])
        body = fal.build_request(values, images, clips, audios, seed=seed)

        def aimed_at(target):
            return fal.queue_transport(os.environ, target, interactive_key)

        submitted = _post(aimed_at(fal.queue_target(label)), body, "fal")
        fal.request_id(submitted)
        _await_job(aimed_at(fal.status_target(submitted)), label)
        finished = _get(aimed_at(fal.result_target(submitted)), "fal")
        return io.NodeOutput(_fetch(fal.video_url(finished)))

    @classmethod
    def _through_catalog(cls, label, model, seed, watermark, images,
                         audios) -> io.NodeOutput:
        """The fall back, where a shared key pays and clips cannot ride."""
        transport = ai_gateway.resolve_rest_transport(os.environ)
        catalog.check_reference_size(images + audios)
        body = catalog.build_request(label, model, seed, watermark, images,
                                     audios)
        payload = _post(transport, body, "Seedance")
        left_byok = catalog.key_source_warning(payload)
        if left_byok:
            # Logged rather than raised: the render succeeded and throwing it
            # away would cost the spend twice. This is the only place the fact
            # is ever visible.
            logging.warning("[Symbiotica] Seedance: %s", left_byok)
        return io.NodeOutput(_fetch(catalog.video_url(payload)))


def _interrupted():
    """Whether the user has pressed Cancel.

    ComfyUI sets a flag and expects the node to notice; a node that never looks
    runs to its own timeout, which here is the user watching a button they
    already pressed for as long as the render takes."""
    try:
        from comfy import model_management
        return model_management.processing_interrupted()
    except Exception:
        return False


def _interrupted_base():
    """Raised as ComfyUI's own interrupt type, which it logs quietly and does
    not mark the node red for — a cancel reads as a cancel, not a failure."""
    try:
        from comfy.model_management import InterruptProcessingException
        return InterruptProcessingException
    except Exception:
        return Exception


class SeedanceInterrupted(_interrupted_base()):
    """Raised when the user cancels while a render is being polled."""


def _await_job(transport, label):
    """Poll until fal says the render is done, or the user gives up.

    The interval is generous because these renders are minutes long and each
    poll is a gateway request that lands in the log like any other."""
    deadline = time.monotonic() + REQUEST_TIMEOUT_S
    while True:
        if _interrupted():
            raise SeedanceInterrupted(
                f"Cancelled while waiting for the {label} render.")
        if fal.is_finished(_get(transport, "fal")):
            return
        if time.monotonic() > deadline:
            raise RuntimeError(
                f"The {label} render was still running after "
                f"{REQUEST_TIMEOUT_S}s. It may yet finish at fal; this node "
                f"stopped waiting.")
        time.sleep(POLL_INTERVAL_S)


def _resizer(model, budget):
    """The re-encoder for reference clips, or None to leave them alone.

    Which direction is allowed is the caller's choice: a clip over the ceiling
    is only shrunk when auto_downscale is on, and one under the floor only
    enlarged when auto_upscale is on. Off in the direction that matters means
    the clip goes as it is, for the provider to judge."""
    if not budget:
        return None
    down = model.get("auto_downscale", True)
    up = model.get("auto_upscale", False)
    if not down and not up:
        return None

    def resize(payload, width, height):
        shrinking = width * height <= budget[1]
        if (shrinking and not down) or (not shrinking and not up):
            return payload
        return _reencode(payload, width, height)

    return resize


def _reencode(payload: bytes, width: int, height: int) -> bytes:
    """The clip at exactly this size, through ffmpeg.

    Written to a file rather than piped: mp4 places its index by seeking, and
    ffmpeg writing mp4 to a pipe either fails or produces a file nothing
    plays."""
    import subprocess
    from . import _bins
    with tempfile.TemporaryDirectory() as work:
        source = os.path.join(work, "in.mp4")
        target = os.path.join(work, "out.mp4")
        with open(source, "wb") as handle:
            handle.write(payload)
        subprocess.run(
            [_bins.FFMPEG, "-y", "-v", "error", "-i", source,
             "-vf", f"scale={width}:{height}", "-c:v", "libx264",
             "-pix_fmt", "yuv420p", "-c:a", "copy", target],
            check=True, capture_output=True)
        with open(target, "rb") as handle:
            return handle.read()


def _audio_seconds(audio) -> float:
    """How long one reference audio runs, from the waveform itself."""
    import numpy as np
    waveform = np.asarray(audio["waveform"])
    return waveform.shape[-1] / int(audio["sample_rate"])


def _has_fal_key() -> bool:
    """Whether a personal fal key is reachable, without walking the ladder far.

    Only consulted on a box with no gateway, so the ladder's file read never
    happens on the route that would ignore the answer."""
    return bool((os.environ.get("FAL_KEY")
                 or os.environ.get("FAL_API_KEY") or "").strip())


def _is_ok(status) -> bool:
    """Whether this status carries an answer rather than a refusal.

    Not just 200: fal answers a status read with 202 for as long as the job is
    still running, which is most of the life of every render this node makes."""
    return 200 <= status < 300


def _get(transport, service):
    """One read, told apart from a submission only by the verb."""
    return _call(transport, service, body=None)


def _post(transport, body, service):
    """One call, with every failure carrying the same account of it."""
    return _call(transport, service, body)


def _call(transport, service, body):
    def failure(status, text):
        return RuntimeError(ai_gateway.http_error(
            status, text,
            secrets=ai_gateway.header_secrets(transport.headers),
            studio=transport.studio,
            alias=transport.headers.get("cf-aig-byok-alias"),
            service=service))

    try:
        send = requests.post if body is not None else requests.get
        kwargs = {"json": body} if body is not None else {}
        response = send(
            transport.url, headers=transport.headers,
            timeout=(ai_gateway.CONNECT_TIMEOUT_S, READ_TIMEOUT_S), **kwargs)
    except requests.RequestException as exc:
        # No response ever existed, so nothing downstream can add the context.
        # A bare ReadTimeout cannot be told apart from "the render is slow" and
        # "this box has no egress".
        raise failure("no response", f"{type(exc).__name__}: {exc}") from exc
    if not _is_ok(response.status_code):
        raise failure(response.status_code, response.text)
    try:
        return response.json()
    except ValueError:
        # A gateway interstitial or a challenge page answers 200 with HTML.
        raise failure(response.status_code,
                      f"reply was not JSON: {response.text}") from None


def _wired(slots):
    """The Autogrow slots that were actually connected, in canvas order.

    Autogrow hands its slots over as a dict keyed by slot name, and iterating
    it yields the KEYS. Sorted as text `video_10` lands between `video_1` and
    `video_2`, so the prompt's "the second clip" means the tenth."""
    if not slots:
        return []
    if not isinstance(slots, dict):
        return [slot for slot in slots if slot is not None]
    return [slots[name] for name in sorted(slots, key=slot_order)
            if slots[name] is not None]


def _fetch(url):
    """The finished render, downloaded to a file ComfyUI can hand on.

    `InputImpl` holds the concrete video class. `Input.Video` is the abstract
    VideoInput and carries no VideoFromFile at all, so reaching for it there
    raised only after the render had been paid for and fetched."""
    from comfy_api.latest import InputImpl
    handle, path = tempfile.mkstemp(suffix=".mp4")
    os.close(handle)
    _download(url, path)
    return InputImpl.VideoFromFile(path)


def _download(url, path):
    """The bytes at `url`, streamed to `path`."""
    with requests.get(url, stream=True, timeout=(
            ai_gateway.CONNECT_TIMEOUT_S, REQUEST_TIMEOUT_S)) as response:
        response.raise_for_status()
        with open(path, "wb") as out:
            for chunk in response.iter_content(chunk_size=1 << 20):
                out.write(chunk)


NODE_CLASS_MAPPINGS = {
    "SymbioticaSeedanceReference": SymbioticaSeedanceReference}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SymbioticaSeedanceReference": "Seedance Reference to Video (Symbiotica)"}
