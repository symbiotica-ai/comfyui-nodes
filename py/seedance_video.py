# ABOUTME: Seedance reference-to-video node — reference images, clips and audio
# ABOUTME: become a video, billed through Cloudflare AI Gateway rather than Comfy.
import logging
import os
import tempfile

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
REQUEST_TIMEOUT_S = 900


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

        images = [catalog.image_data_uri(image)
                  for image in to_pil(model.get("images"))]
        videos = _wired(model.get("videos"))
        audios = [catalog.audio_data_uri(audio, label)
                  for audio in _wired(model.get("audios"))]
        if arm == "catalog":
            fal.check_catalog_can_carry(label, len(images), len(videos),
                                        len(audios))
            return cls._through_catalog(label, model, seed, watermark,
                                        images, audios)
        return cls._through_fal(label, model, seed, watermark, images,
                                videos, audios, interactive_key)

    @classmethod
    def _through_fal(cls, label, model, seed, watermark, images, videos,
                     audios, interactive_key) -> io.NodeOutput:
        """The route the node is for: the studio's own key, by alias."""
        transport = fal.resolve_transport(os.environ, label, interactive_key)
        clips = [fal.video_data_uri(video, label, Types.VideoContainer.MP4,
                                    Types.VideoCodec.H264)
                 for video in videos]
        catalog.check_reference_size(images + clips + audios)
        values = dict(model)
        if values.get("ratio") == ADAPTIVE:
            values["ratio"] = "auto"
        values["duration"] = str(values["duration"])
        body = fal.build_request(values, images, clips, audios, seed=seed)
        payload = _post(transport, body, "fal")
        return io.NodeOutput(_fetch(fal.video_url(payload)))

    @classmethod
    def _through_catalog(cls, label, model, seed, watermark, images,
                         audios) -> io.NodeOutput:
        """The fall back, where a shared key pays and clips cannot ride."""
        transport = ai_gateway.resolve_rest_transport(os.environ)
        catalog.check_reference_size(images + audios)
        values = dict(model)
        if values.get("ratio") == ADAPTIVE:
            # The catalog spells it `adaptive` too, but only on 2.5; the 2.0
            # options reject it, and they are the ones ComfyUI defaults to it.
            values["ratio"] = ADAPTIVE if label == LABEL_25 else "16:9"
        body = catalog.build_request(label, values, seed, watermark, images,
                                     audios)
        payload = _post(transport, body, "Seedance")
        left_byok = catalog.key_source_warning(payload)
        if left_byok:
            # Logged rather than raised: the render succeeded and throwing it
            # away would cost the spend twice. This is the only place the fact
            # is ever visible.
            logging.warning("[Symbiotica] Seedance: %s", left_byok)
        return io.NodeOutput(_fetch(catalog.video_url(payload)))


def _has_fal_key() -> bool:
    """Whether a personal fal key is reachable, without walking the ladder far.

    Only consulted on a box with no gateway, so the ladder's file read never
    happens on the route that would ignore the answer."""
    return bool((os.environ.get("FAL_KEY")
                 or os.environ.get("FAL_API_KEY") or "").strip())


def _post(transport, body, service):
    """One call, with every failure carrying the same account of it."""
    def failure(status, text):
        return RuntimeError(ai_gateway.http_error(
            status, text,
            secrets=ai_gateway.header_secrets(transport.headers),
            studio=transport.studio,
            alias=transport.headers.get("cf-aig-byok-alias"),
            service=service))

    try:
        response = requests.post(
            transport.url, json=body, headers=transport.headers,
            timeout=(ai_gateway.CONNECT_TIMEOUT_S, REQUEST_TIMEOUT_S))
    except requests.RequestException as exc:
        # No response ever existed, so nothing downstream can add the context.
        # A bare ReadTimeout cannot be told apart from "the render is slow" and
        # "this box has no egress".
        raise failure("no response", f"{type(exc).__name__}: {exc}") from exc
    if response.status_code != 200:
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
    """The finished render, downloaded to a file ComfyUI can hand on."""
    from comfy_api.latest import Input
    handle, path = tempfile.mkstemp(suffix=".mp4")
    os.close(handle)
    with requests.get(url, stream=True, timeout=(
            ai_gateway.CONNECT_TIMEOUT_S, REQUEST_TIMEOUT_S)) as response:
        response.raise_for_status()
        with open(path, "wb") as out:
            for chunk in response.iter_content(chunk_size=1 << 20):
                out.write(chunk)
    return Input.Video.VideoFromFile(path)


NODE_CLASS_MAPPINGS = {
    "SymbioticaSeedanceReference": SymbioticaSeedanceReference}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SymbioticaSeedanceReference": "Seedance Reference to Video (Symbiotica)"}
