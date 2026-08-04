# ABOUTME: Claude text node — a prompt and up to twenty reference images become
# ABOUTME: an answer, routed through Cloudflare AI Gateway when configured.
import os

import requests
from comfy_api.latest import io

from .pipeline import claude_text as core
from .pipeline.reference_images import to_pil
from .pipeline import ai_gateway


def _model_inputs(label):
    """The inputs one model choice carries.

    Temperature and reasoning_effort are absent on the models that reject
    them, rather than present and ignored. A widget a model 400s on is worse
    than no widget: it reads as a setting that did nothing."""
    inputs = [
        io.Int.Input("max_tokens", default=32768, min=4096, max=64000,
                     advanced=True,
                     tooltip="A budget, not a target. On the models that think "
                             "by default this caps the reasoning and the "
                             "answer together, so a small value cuts the "
                             "answer off — which this node raises on rather "
                             "than handing back a fragment."),
    ]
    if label not in core.NO_TEMPERATURE:
        inputs.append(io.Float.Input(
            "temperature", default=1.0, min=0.0, max=1.0, step=0.01,
            advanced=True,
            tooltip="Lower is more repeatable. Ignored for Opus 4.7, and for "
                    "any model whenever reasoning is on — Anthropic rejects a "
                    "temperature alongside thinking."))
    if label in core.ALWAYS_THINKING:
        inputs.append(io.Combo.Input(
            "reasoning_effort",
            options=[e for e in core.REASONING_EFFORTS if e != "off"],
            default="high", advanced=True,
            tooltip="This model always reasons, so there is no 'off'."))
    elif label not in core.THINKING_UNSUPPORTED:
        inputs.append(io.Combo.Input(
            "reasoning_effort", options=core.REASONING_EFFORTS, default="off",
            advanced=True,
            tooltip="Extended thinking effort. 'off' disables reasoning."))
    inputs.append(io.Autogrow.Input(
        "images",
        template=io.Autogrow.TemplateNames(
            io.Image.Input("image"),
            names=[f"image_{i}" for i in range(1, core.MAX_IMAGES + 1)],
            min=0),
        tooltip=f"Reference images, in slot order. Each slot may itself carry "
                f"a batch; {core.MAX_IMAGES} images total is Anthropic's "
                f"ceiling, and the request size ceiling usually binds first."))
    return inputs


class SymbioticaClaude(io.ComfyNode):
    """Answer a prompt with Claude, optionally looking at images.

    On a box carrying SYMBIOTICA_AIG_BASE the call goes through Cloudflare AI
    Gateway on the studio's own key, which is how order graphs run headless and
    how their spend reaches the cockpit. Anywhere else it goes straight to
    Anthropic on a key from the node, the Settings UI or the environment.

    Claude draws nothing — this belongs in a graph as a prompt author, a
    caption or critique step, or a structured-extraction step feeding an image
    node."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaClaude",
            display_name="Claude (Symbiotica)",
            category="symbiotica/text",
            description="Answer a prompt with Claude, billed to the studio's "
                        "own key through Cloudflare AI Gateway rather than to "
                        "a ComfyUI account.",
            inputs=[
                io.String.Input("prompt", multiline=True, default="",
                                tooltip="What to ask. Reference images are "
                                        "described by this prompt, not "
                                        "replaced by it."),
                io.DynamicCombo.Input(
                    "model",
                    options=[io.DynamicCombo.Option(label, _model_inputs(label))
                             for label in core.MODEL_LABELS],
                    tooltip="Haiku is the cheap lever for bulk captioning."),
                io.Int.Input("seed", default=0, min=0,
                             max=0xFFFFFFFFFFFFFFFF,
                             control_after_generate=True,
                             tooltip="Not sent to Anthropic — Claude takes no "
                                     "seed. It exists so re-queueing re-runs "
                                     "this node instead of serving ComfyUI's "
                                     "cached output."),
                io.String.Input("system_prompt", multiline=True, default="",
                                optional=True, advanced=True,
                                tooltip="Standing instructions, sent as "
                                        "Anthropic's own top-level system "
                                        "field rather than as a message."),
                io.String.Input("api_key", default="", optional=True,
                                advanced=True,
                                tooltip="Anthropic key for direct calls; empty "
                                        "falls back to "
                                        "Symbiotica.ANTHROPIC_API_KEY or "
                                        "Symbiotica.CLAUDE_API_KEY in "
                                        "Settings, then the ANTHROPIC_API_KEY "
                                        "or CLAUDE_API_KEY env vars, in that "
                                        "order. Ignored where the studio "
                                        "gateway is configured."),
            ],
            outputs=[io.String.Output(display_name="text")],
        )

    @classmethod
    def execute(cls, prompt, model, seed, system_prompt="",
                api_key="") -> io.NodeOutput:
        def interactive_key():
            from ._settings import resolve_provider_key
            return resolve_provider_key(
                api_key, ["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"], "Claude")

        # Everything gated on the model rides inside the combo's value rather
        # than arriving as keywords, and a model that rejects a setting has no
        # input for it — so each is read with the default the API would apply.
        label = model["model"]
        model_id = core.MODEL_LABELS.get(label, label)
        max_tokens = model.get("max_tokens", 32768)
        effort = model.get("reasoning_effort", "off")
        thinking, output_config = core.thinking_config(
            label, effort, max_tokens)
        temperature = core.temperature_for(
            label, effort, model.get("temperature"))

        # First, because everything below it is wasted otherwise: the ladder
        # can reach a file on disk and the encoding runs once per reference.
        core.require_prompt(prompt)
        transport = core.resolve_transport(os.environ, interactive_key)
        body = core.request_body(
            prompt, core.image_blocks(to_pil(model.get("images")), model_id),
            model_id, max_tokens, system_prompt, thinking=thinking,
            output_config=output_config, temperature=temperature)

        # Anything that is not an answer goes through one formatter, so that a
        # failure carries the same account whether the gateway refused it,
        # never answered, or answered with something that was never a Claude
        # reply at all. The studio rides along on every gateway failure
        # whatever the cause: in an order sandbox this message is the only
        # thing that says whose call it was, and the credentials come off the
        # headers that were actually sent rather than back out of the
        # environment.
        def failure(status, text):
            return RuntimeError(ai_gateway.http_error(
                status, text, secrets=ai_gateway.header_secrets(transport.headers),
                studio=transport.studio,
                alias=transport.headers.get("cf-aig-byok-alias"),
                service="Claude"))

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

        return io.NodeOutput(core.parse_response(payload))


NODE_CLASS_MAPPINGS = {"SymbioticaClaude": SymbioticaClaude}

NODE_DISPLAY_NAME_MAPPINGS = {"SymbioticaClaude": "Claude (Symbiotica)"}
