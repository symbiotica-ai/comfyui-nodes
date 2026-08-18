# ABOUTME: Seedance reference-to-video node — reference images, clips and audio
# ABOUTME: become a video, billed through Cloudflare AI Gateway rather than Comfy.
import logging
import os
import tempfile

import requests
from comfy_api.latest import io

from .pipeline import seedance_video as core
from .pipeline.reference_images import to_pil, slot_order
from .pipeline import ai_gateway

# A 720p Seedance render is minutes of work and /ai/run holds the connection
# open for all of it — background mode would need a public webhook this box has
# not got. So the read timeout is sized for the longest render the node can ask
# for rather than for a normal HTTP call.
REQUEST_TIMEOUT_S = 900


def _model_inputs(label):
    """The widgets one model carries, and only the ones it will accept.

    Built per option rather than shared: the four models differ in what they
    take, and a single flat input list can only offer the union — every widget
    in it that the chosen model does not have is a render refused before it
    starts."""
    limits = core.LIMITS[label]
    inputs = [
        io.String.Input("prompt", multiline=True, default="",
                        tooltip="What to make. Put spoken lines in double "
                                "quotes to steer the generated dialogue."),
        io.Combo.Input("resolution", options=limits.resolutions,
                       default="720p",
                       tooltip="Resolution of the output video."),
        io.Combo.Input("ratio", options=limits.ratios, default="16:9",
                       tooltip="Aspect ratio of the output video."),
        io.Int.Input("duration", default=5, min=limits.min_duration,
                     max=limits.max_duration, step=1,
                     display_mode=io.NumberDisplay.slider,
                     tooltip=f"Length of the output video in seconds "
                             f"({limits.min_duration}-{limits.max_duration})."),
        io.Boolean.Input("generate_audio", default=True,
                         tooltip="Generate a soundtrack along with the video."),
    ]
    if limits.output_formats:
        inputs.append(io.Combo.Input(
            "output_format", options=limits.output_formats, default="mp4",
            tooltip="Container format of the output video."))
    inputs.append(_slots("images", io.Image.Input("reference_image"),
                         "image", limits.max_images))
    if limits.max_audios:
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
                             for label in core.MODELS],
                    tooltip="2.5 is the newest and takes the most references; "
                            "2.0 reaches 4k; Fast trades quality for speed and "
                            "Mini is the cheap lever."),
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

        # Before any encoding: the references cost a device copy and a full
        # re-encode apiece, and a box with no gateway configured cannot send
        # them anywhere.
        transport = ai_gateway.resolve_rest_transport(os.environ)

        images = [core.image_data_uri(image)
                  for image in to_pil(model.get("images"))]
        audios = [core.audio_data_uri(audio, label)
                  for audio in _wired(model.get("audios"))]
        core.check_reference_size(images + audios)

        body = core.build_request(label, model, seed, watermark,
                                  images, audios)

        def failure(status, text):
            return RuntimeError(ai_gateway.http_error(
                status, text,
                secrets=ai_gateway.header_secrets(transport.headers),
                studio=transport.studio, service="Seedance"))

        try:
            response = requests.post(
                transport.url, json=body, headers=transport.headers,
                timeout=(ai_gateway.CONNECT_TIMEOUT_S, REQUEST_TIMEOUT_S))
        except requests.RequestException as exc:
            # No response ever existed, so nothing downstream can add the
            # context. A bare ReadTimeout here cannot be told apart from "the
            # render is slow" and "this box has no egress".
            raise failure("no response",
                          f"{type(exc).__name__}: {exc}") from exc
        if response.status_code != 200:
            raise failure(response.status_code, response.text)
        try:
            payload = response.json()
        except ValueError:
            # A gateway interstitial or a challenge page answers 200 with HTML.
            raise failure(response.status_code,
                          f"reply was not JSON: {response.text}") from None
        left_byok = core.key_source_warning(payload)
        if left_byok:
            # Logged rather than raised: the render succeeded and throwing it
            # away would cost the spend twice. This is the only place the fact
            # is ever visible.
            logging.warning("[Symbiotica] Seedance: %s", left_byok)
        return io.NodeOutput(_fetch(core.video_url(payload)))


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
