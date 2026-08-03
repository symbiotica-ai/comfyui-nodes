# ABOUTME: Gemini image node — a prompt and up to fourteen reference images
# ABOUTME: become a render, routed through Cloudflare AI Gateway when configured.
import os

import numpy as np
import requests
from PIL import Image

from .pipeline import gemini_image as core


class SymbioticaGeminiImage:
    """Generate an image with Google's Gemini image models.

    On a box carrying GEMINI_GATEWAY_URL the call goes through Cloudflare AI
    Gateway on the studio's own key, which is how order renders work headless
    and how their spend reaches the cockpit. Anywhere else it goes straight to
    Google on a key from the node, the Settings UI or the environment."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "What to draw. Reference images are described "
                               "by this prompt, not replaced by it."
                }),
                "model": (core.MODELS, {
                    "default": core.MODELS[0],
                    "tooltip": "The Lite model is the cheap lever for drafts"
                }),
                "seed": ("INT", {
                    "default": 0,
                    "min": 0,
                    "max": 0xFFFFFFFFFFFFFFFF,
                    "control_after_generate": True,
                    "tooltip": "Not sent to Google — Gemini takes no seed. It "
                               "exists so re-queueing re-runs this node "
                               "instead of serving ComfyUI's cached output."
                }),
                "aspect_ratio": (core.ASPECT_RATIOS, {
                    "default": "auto",
                    "tooltip": "'auto' matches the reference images, or gives "
                               "a square when there are none"
                }),
                "resolution": (core.RESOLUTIONS, {
                    "default": "2K",
                    "tooltip": "2K and 4K run Gemini's own upscaler"
                }),
            },
            "optional": {
                "images": ("IMAGE", {
                    "tooltip": f"Up to {core.MAX_REFERENCE_IMAGES} reference "
                               f"images, sent in batch order"
                }),
                "system_prompt": ("STRING", {
                    "multiline": True,
                    "default": core.GEMINI_IMAGE_SYS_PROMPT,
                    "tooltip": "Standing instructions. Emptying this lets a "
                               "conversational prompt come back as prose "
                               "instead of a picture."
                }),
                "api_key": ("STRING", {
                    "default": "",
                    "tooltip": "Google AI Studio key for direct calls; empty "
                               "falls back to the Symbiotica.GEMINI_API_KEY "
                               "setting or the GEMINI_API_KEY env var. "
                               "Ignored where the studio gateway is configured."
                }),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("image", "text")
    CATEGORY = "symbiotica/image"
    FUNCTION = "execute"

    def execute(self, prompt, model, seed, aspect_ratio, resolution,
                images=None, system_prompt="", api_key=""):
        def interactive_key():
            from ._settings import resolve_provider_key
            return resolve_provider_key(
                api_key, ["GEMINI_API_KEY", "GOOGLE_API_KEY"], "Gemini")

        transport = core.resolve_transport(os.environ, model, interactive_key)
        body = core.request_body(prompt, core.image_parts(to_pil(images)),
                                 aspect_ratio, resolution, system_prompt)

        response = requests.post(transport.url, json=body,
                                 headers=transport.headers,
                                 timeout=core.REQUEST_TIMEOUT_S)
        if response.status_code != 200:
            # The credentials are scrubbed because a gateway rejecting a token
            # quotes it back, and this message goes on to a toast and a log.
            raise RuntimeError(core.http_error(
                response.status_code, response.text,
                secrets=[os.environ.get("GEMINI_GATEWAY_TOKEN"),
                         transport.headers.get("x-goog-api-key")]))

        rendered, text = core.parse_response(response.json())
        return (to_tensor(rendered), text)


def to_pil(images):
    """A ComfyUI [B,H,W,C] float batch as a list of PIL images. None and an
    empty batch are both 'no references', which is a prompt-only generation."""
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


def to_tensor(pil_images):
    """PIL images back into one ComfyUI [N,H,W,C] float batch.

    Converted to RGB because a batch must stack, and Gemini is free to answer
    with a palette or RGBA image that would not share a channel count with the
    rest. Torch is imported here rather than at module scope: the pack's loader
    swallows an import failure with only a printed traceback, so a node that
    needs torch merely to register vanishes on any box without it."""
    import torch

    arrays = [np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0
              for im in pil_images]
    return torch.from_numpy(np.stack(arrays))


NODE_CLASS_MAPPINGS = {"SymbioticaGeminiImage": SymbioticaGeminiImage}

NODE_DISPLAY_NAME_MAPPINGS = {"SymbioticaGeminiImage": "Gemini Image (Symbiotica)"}
