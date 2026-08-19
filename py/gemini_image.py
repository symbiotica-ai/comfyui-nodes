# ABOUTME: Gemini image node — a prompt and up to fourteen reference images
# ABOUTME: become a render, routed through Cloudflare AI Gateway when configured.

import numpy as np
import requests
from comfy_api.latest import io

from .pipeline import gemini_image as core
from .pipeline.reference_images import to_pil
from .pipeline import ai_gateway
from ._settings import gateway_environ


def _model_inputs(resolutions):
    """The inputs one model choice carries.

    Built per option rather than shared, because the whole point of the
    per-model combo is that Lite offers 1K alone — a single input list with
    every resolution in it is the flat combo this replaced."""
    return [
        io.Combo.Input("aspect_ratio", options=core.ASPECT_RATIOS,
                       default="auto",
                       tooltip="'auto' matches the reference images, or gives "
                               "a square when there are none"),
        io.Combo.Input("resolution", options=resolutions,
                       tooltip="2K and 4K run Gemini's own upscaler"),
        io.Combo.Input("thinking_level", options=core.THINKING_LEVELS,
                       tooltip="HIGH lets the model plan the image before "
                               "drawing it, and is what the thought_image "
                               "output needs. It costs latency on every "
                               "render, so an order pipeline wants MINIMAL."),
        io.Autogrow.Input(
            "images",
            template=io.Autogrow.TemplateNames(
                io.Image.Input("image"),
                names=[f"image_{i}" for i in
                       range(1, core.MAX_REFERENCE_IMAGES + 1)],
                min=0),
            tooltip=f"Reference images, in slot order. Each slot may itself "
                    f"carry a batch; {core.MAX_REFERENCE_IMAGES} images total "
                    f"is Google's ceiling."),
        io.Custom("GEMINI_INPUT_FILES").Input(
            "files", optional=True,
            tooltip="Optional context files from ComfyUI's own Gemini Input "
                    "Files node. That node reads local .txt and .pdf and needs "
                    "no account, so it works in an order sandbox."),
    ]


class SymbioticaGeminiImage(io.ComfyNode):
    """Generate an image with Google's Gemini image models.

    On a box carrying SYMBIOTICA_AIG_BASE the call goes through Cloudflare AI
    Gateway on the studio's own key, which is how order renders work headless
    and how their spend reaches the cockpit. Anywhere else it goes straight to
    Google on a key from the node, the Settings UI or the environment."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaGeminiImage",
            display_name="Gemini Image (Symbiotica)",
            category="symbiotica/image",
            description="Generate or edit images with Gemini, billed to the "
                        "studio's own key through Cloudflare AI Gateway rather "
                        "than to a ComfyUI account.",
            inputs=[
                io.String.Input("prompt", multiline=True, default="",
                                tooltip="What to draw. Reference images are "
                                        "described by this prompt, not "
                                        "replaced by it."),
                io.DynamicCombo.Input(
                    "model",
                    options=[
                        io.DynamicCombo.Option(
                            label,
                            _model_inputs(core.MODEL_RESOLUTIONS[model_id]))
                        for label, model_id in core.MODEL_LABELS.items()
                    ],
                    tooltip="The Lite model is the cheap lever for drafts, and "
                            "renders at 1K only."),
                io.Int.Input("seed", default=0, min=0,
                             max=0xFFFFFFFFFFFFFFFF,
                             control_after_generate=True,
                             tooltip="Not sent to Google — Gemini takes no "
                                     "seed. It exists so re-queueing re-runs "
                                     "this node instead of serving ComfyUI's "
                                     "cached output."),
                io.Combo.Input("response_modalities",
                               options=core.RESPONSE_MODALITIES,
                               default="IMAGE+TEXT", advanced=True,
                               tooltip="IMAGE alone suppresses the model's "
                                       "commentary, and with it the thought "
                                       "image."),
                io.String.Input("system_prompt", multiline=True,
                                default=core.GEMINI_IMAGE_SYS_PROMPT,
                                optional=True, advanced=True,
                                tooltip="Standing instructions. Emptying this "
                                        "lets a conversational prompt come "
                                        "back as prose instead of a picture."),
                io.Float.Input("temperature", default=1.0, min=0.0, max=2.0,
                               step=0.01, optional=True, advanced=True,
                               tooltip="Lower is more focused and repeatable."),
                io.Float.Input("top_p", default=0.95, min=0.0, max=1.0,
                               step=0.01, optional=True, advanced=True,
                               tooltip="Nucleus sampling threshold. Lower is "
                                       "more focused, higher more diverse."),
                io.String.Input("api_key", default="", optional=True,
                                advanced=True,
                                tooltip="Google AI Studio key for direct "
                                        "calls; empty falls back to "
                                        "Symbiotica.GEMINI_API_KEY or "
                                        "Symbiotica.GOOGLE_API_KEY in "
                                        "Settings, then the GEMINI_API_KEY or "
                                        "GOOGLE_API_KEY env vars, in that "
                                        "order. Ignored where the studio "
                                        "gateway is configured."),
            ],
            outputs=[
                io.Image.Output(display_name="image"),
                io.String.Output(display_name="text"),
                io.Image.Output(
                    display_name="thought_image",
                    tooltip="The model's interim sketch. Only arrives with "
                            "thinking_level HIGH and IMAGE+TEXT."),
            ],
        )

    @classmethod
    def execute(cls, prompt, model, seed, response_modalities="IMAGE+TEXT",
                system_prompt="", temperature=1.0, top_p=0.95,
                api_key="") -> io.NodeOutput:
        def interactive_key():
            from ._settings import resolve_provider_key
            return resolve_provider_key(
                api_key, ["GEMINI_API_KEY", "GOOGLE_API_KEY"], "Gemini")

        # The chosen option's own inputs ride inside the combo's value rather
        # than arriving as separate keywords, so everything gated on the model
        # is read from here.
        label = model["model"]
        model_id = core.MODEL_LABELS.get(label, label)

        # First, because everything below it is wasted otherwise: the ladder
        # can reach a file on disk, and every reference costs a device copy
        # and three full-size temporaries before it is even a PIL image.
        core.require_prompt(prompt)
        transport = core.resolve_transport(gateway_environ(), model_id,
                                           interactive_key)
        parts = (core.image_parts(to_pil(model.get("images")))
                 + core.file_parts(model.get("files")))
        body = core.request_body(prompt, parts, model["aspect_ratio"],
                                 model["resolution"], system_prompt,
                                 thinking_level=model["thinking_level"],
                                 temperature=temperature, top_p=top_p,
                                 response_modalities=response_modalities)

        # Anything that is not a rendered image goes through one formatter, so
        # that a failure carries the same account whether the gateway refused
        # it, never answered, or answered with something that was never a
        # Gemini reply at all. The studio rides along on every gateway failure
        # whatever the cause: in an order sandbox this message is the only
        # thing that says whose render it was, and the credentials come off
        # the headers that were actually sent rather than back out of the
        # environment.
        def failure(status, text):
            return RuntimeError(ai_gateway.http_error(
                status, text, secrets=ai_gateway.header_secrets(transport.headers),
                studio=transport.studio,
                alias=transport.headers.get("cf-aig-byok-alias"),
                service="Gemini"))

        try:
            response = requests.post(
                transport.url, json=body, headers=transport.headers,
                timeout=(ai_gateway.CONNECT_TIMEOUT_S, core.REQUEST_TIMEOUT_S))
        except requests.RequestException as exc:
            # No response ever existed, so nothing downstream can add the
            # context. A bare ConnectTimeout in a sandbox log cannot be told
            # apart from "the gateway is down" and "this box has no egress",
            # and some transport errors quote the request headers back.
            raise failure("no response",
                          f"{type(exc).__name__}: {exc}") from exc

        if response.status_code != 200:
            raise failure(response.status_code, response.text)
        try:
            payload = response.json()
        except ValueError:
            # A gateway interstitial or a challenge page answers 200 with HTML.
            # Bare, this is "Expecting value: line 1 column 1" and nothing
            # about which service produced it.
            raise failure(response.status_code,
                          f"reply was not JSON: {response.text}") from None

        rendered, text, thoughts = core.parse_response(payload)
        return io.NodeOutput(to_tensor(rendered), text, sketch(thoughts))


def sketch(thoughts):
    """The interim sketches as a batch, and never a reason the render fails.

    Two rules, both learned from what the alternatives do downstream.

    It cannot raise. Nothing constrains sketches to a common size — they are
    the one set of images that genuinely varies — so batching them with the
    helper that batches renders lets a diagnostic-only third output kill a
    good first one, blaming `aspect_ratio` and `resolution`, which govern the
    final image and would change nothing. Mismatched sketches fall back to the
    first, which is the one the model drew from.

    It is never None. thinking_level defaults to MINIMAL, so a freshly dropped
    node produces no sketch on EVERY run, and None reaching SaveImage dies on
    `images[0].shape` naming neither this node nor Gemini. ComfyUI's own node
    returns a placeholder here for the same reason. Three channels rather than
    its four, so the slot always carries the shape everything else on this node
    emits."""
    import torch

    for candidates in (thoughts, thoughts[:1] if thoughts else []):
        if not candidates:
            continue
        try:
            return to_tensor(candidates)
        except ValueError:
            continue
    return torch.zeros((1, 1024, 1024, 3))


def to_tensor(pil_images):
    """PIL images back into one ComfyUI [N,H,W,C] float batch.

    Converted to RGB because a batch must stack, and Gemini is free to answer
    with a palette or RGBA image that would not share a channel count with the
    rest. Size it cannot fix — nothing promises two returned images agree — so
    a mismatch is named here rather than left to numpy, whose complaint about
    array shapes names neither Gemini nor the sizes it sent. Torch is imported
    here rather than at module scope: the pack's loader swallows an import
    failure with only a printed traceback, so a node that needs torch merely to
    register vanishes on any box without it."""
    import torch

    sizes = {im.size for im in pil_images}
    if len(sizes) > 1:
        raise ValueError(
            f"Gemini returned {len(pil_images)} images of different sizes "
            f"({', '.join(f'{w}x{h}' for w, h in sorted(sizes))}), which "
            f"cannot be one batch. Pin `aspect_ratio` and `resolution` rather "
            f"than leaving them to the model.")
    arrays = [np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
              for im in pil_images]
    return torch.from_numpy(np.stack(arrays))


NODE_CLASS_MAPPINGS = {"SymbioticaGeminiImage": SymbioticaGeminiImage}

NODE_DISPLAY_NAME_MAPPINGS = {"SymbioticaGeminiImage": "Gemini Image (Symbiotica)"}
