# ABOUTME: Claude text node — a prompt and up to twenty reference images become
# ABOUTME: an answer, routed through Cloudflare AI Gateway when configured.
import os

import numpy as np
import requests
from PIL import Image

from .pipeline import claude_text as core
from .pipeline import ai_gateway


class SymbioticaClaude:
    """Answer a prompt with Claude, optionally looking at images.

    On a box carrying SYMBIOTICA_AIG_BASE the call goes through Cloudflare AI
    Gateway on the studio's own key, which is how order graphs run headless and
    how their spend reaches the cockpit. Anywhere else it goes straight to
    Anthropic on a key from the node, the Settings UI or the environment.

    Claude draws nothing — this belongs in a graph as a prompt author, a
    caption or critique step, or a structured-extraction step feeding an image
    node."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "What to ask. Reference images are described by "
                               "this prompt, not replaced by it."
                }),
                "model": (core.MODELS, {
                    "default": core.MODELS[0],
                    "tooltip": "Haiku is the cheap lever for bulk captioning"
                }),
                "max_tokens": ("INT", {
                    "default": 32768,
                    "min": 4096,
                    "max": 64000,
                    "tooltip": "A budget, not a target. On the models that "
                               "think by default this caps the reasoning and "
                               "the answer together, so a small value cuts the "
                               "answer off — which this node raises on rather "
                               "than handing back a fragment."
                }),
                "seed": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 0xFFFFFFFFFFFFFFFF,
                    "control_after_generate": True,
                    "tooltip": "Not sent to Anthropic — Claude takes no seed. "
                               "It exists so re-queueing re-runs this node "
                               "instead of serving ComfyUI's cached output."
                }),
            },
            "optional": {
                "images": ("IMAGE", {
                    "tooltip": f"Up to {core.MAX_IMAGES} reference images, sent "
                               f"in batch order. Large renders are brought down "
                               f"to the model's own ceiling first, and a batch "
                               f"too large to be logged is refused rather than "
                               f"trimmed."
                }),
                "system_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Standing instructions, sent as Anthropic's own "
                               "`system` field. Empty means none is sent."
                }),
                "api_key": ("STRING", {
                    "default": "",
                    "tooltip": "Anthropic key for direct calls; empty falls "
                               "back to Symbiotica.ANTHROPIC_API_KEY or "
                               "Symbiotica.CLAUDE_API_KEY in Settings, then "
                               "the ANTHROPIC_API_KEY or CLAUDE_API_KEY env "
                               "vars, in that order. Ignored where the studio "
                               "gateway is configured."
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    CATEGORY = "symbiotica/text"
    FUNCTION = "execute"

    def execute(self, prompt, model, max_tokens, seed, images=None,
                system_prompt="", api_key=""):
        def interactive_key():
            from ._settings import resolve_provider_key
            return resolve_provider_key(
                api_key, ["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"], "Claude")

        # First, because everything below it is wasted otherwise: the ladder
        # can reach a file on disk and the encoding runs once per reference.
        core.require_prompt(prompt)
        transport = core.resolve_transport(os.environ, interactive_key)
        body = core.request_body(prompt, core.image_blocks(to_pil(images),
                                                           model),
                                 model, max_tokens, system_prompt)

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

        return (core.parse_response(payload),)


def to_pil(images):
    """A ComfyUI [B,H,W,C] float batch as a list of PIL images. None and an
    empty batch are both 'no references', which is a text-only question."""
    if images is None:
        return []
    out = []
    for frame in images:
        if hasattr(frame, "cpu"):
            frame = frame.cpu().numpy()
        arr = np.asarray(frame)
        if arr.dtype != np.uint8:
            arr = (np.clip(arr, 0.0, 1.0) * 255.0).round().astype(np.uint8)
        out.append(Image.fromarray(arr))
    return out


NODE_CLASS_MAPPINGS = {"SymbioticaClaude": SymbioticaClaude}

NODE_DISPLAY_NAME_MAPPINGS = {"SymbioticaClaude": "Claude (Symbiotica)"}
