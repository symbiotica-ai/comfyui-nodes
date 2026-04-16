# ABOUTME: Wavespeed Nano Banana 2 (Google) custom nodes for Symbiotica.
# ABOUTME: Four nodes wrapping text-to-image / edit / -fast variants with optional web + image search grounding.

import base64
import io
import json
import os
import time

import numpy as np
import requests
import torch
from PIL import Image

WAVESPEED_BASE = "https://api.wavespeed.ai/api/v3"
POLL_INTERVAL_SECONDS = 1.0
MAX_EDIT_IMAGES = 14

ASPECT_RATIOS = [
    "auto",
    "1:1", "3:2", "2:3", "3:4", "4:3", "4:5", "5:4",
    "9:16", "16:9", "21:9",
    "1:4", "4:1", "1:8", "8:1",
]

RESOLUTIONS_FULL = ["0.5k", "1k", "2k", "4k"]
RESOLUTIONS_FAST = ["2k", "4k"]

OUTPUT_FORMATS = ["png", "jpeg"]


# --- Helpers ---

def _resolve_key(api_key: str) -> str:
    key = (api_key or "").strip() or os.environ.get("WAVESPEED_API_KEY", "").strip()
    if not key:
        raise Exception(
            "Wavespeed API key required. Set WAVESPEED_API_KEY env var or pass api_key on the node."
        )
    return key


def _tensor_to_png_data_uri(image: torch.Tensor) -> str:
    arr = image.cpu().numpy()
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0.0, 1.0)
        arr = (arr * 255.0).astype(np.uint8)
    if arr.ndim == 2:
        pil = Image.fromarray(arr, mode="L").convert("RGB")
    elif arr.shape[-1] == 4:
        pil = Image.fromarray(arr, mode="RGBA").convert("RGB")
    else:
        pil = Image.fromarray(arr, mode="RGB")
    buf = io.BytesIO()
    pil.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _images_tensor_to_data_uris(images: torch.Tensor) -> list:
    if images.dim() == 3:
        images = images.unsqueeze(0)
    batch = images.shape[0]
    if batch > MAX_EDIT_IMAGES:
        print(
            f"[Symbiotica Wavespeed] IMAGE batch has {batch} frames; "
            f"Nano Banana 2 Edit accepts up to {MAX_EDIT_IMAGES} — truncating."
        )
        images = images[:MAX_EDIT_IMAGES]
    return [_tensor_to_png_data_uri(images[i]) for i in range(images.shape[0])]


def _url_to_tensor(url: str) -> torch.Tensor:
    if url.startswith("data:"):
        _, b64 = url.split(",", 1)
        data = base64.b64decode(b64)
    else:
        resp = requests.get(url, timeout=120)
        resp.raise_for_status()
        data = resp.content
    pil = Image.open(io.BytesIO(data)).convert("RGB")
    arr = np.array(pil).astype(np.float32) / 255.0
    return torch.from_numpy(arr)[None, ...]


def _outputs_to_image_tensor(outputs: list) -> torch.Tensor:
    if not outputs:
        raise Exception("Wavespeed returned no output URLs.")
    return _url_to_tensor(outputs[0])


def _submit_and_poll(path: str, body: dict, api_key: str, poll_timeout: int) -> dict:
    key = _resolve_key(api_key)
    submit_url = f"{WAVESPEED_BASE}/{path}"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    resp = requests.post(submit_url, json=body, headers=headers, timeout=60)
    if resp.status_code != 200:
        raise Exception(f"Wavespeed submit failed [{resp.status_code}]: {resp.text}")
    payload = resp.json()
    if payload.get("code") and payload["code"] != 200:
        raise Exception(f"Wavespeed error: {payload.get('message', payload)}")

    data = payload.get("data") or {}
    task_id = data.get("id")
    if not task_id:
        raise Exception(f"Wavespeed returned no task id: {payload}")

    if data.get("status") == "completed" and data.get("outputs"):
        return data

    result_url = (data.get("urls") or {}).get("get") or f"{WAVESPEED_BASE}/predictions/{task_id}/result"
    poll_headers = {"Authorization": f"Bearer {key}"}

    started = time.time()
    while True:
        elapsed = time.time() - started
        if elapsed > poll_timeout:
            raise Exception(f"Wavespeed task {task_id} timed out after {poll_timeout}s.")
        time.sleep(POLL_INTERVAL_SECONDS)
        pr = requests.get(result_url, headers=poll_headers, timeout=60)
        if pr.status_code != 200:
            raise Exception(f"Wavespeed poll failed [{pr.status_code}]: {pr.text}")
        pdata = (pr.json() or {}).get("data") or {}
        status = pdata.get("status")
        if status == "completed":
            return pdata
        if status == "failed":
            err = pdata.get("error") or "(no error message)"
            sent = json.dumps(body, ensure_ascii=False)[:500]
            full = json.dumps(pdata, ensure_ascii=False)[:800]
            raise Exception(
                f"Wavespeed task {task_id} failed.\n"
                f"  Wavespeed error: {err}\n"
                f"  Sent body: {sent}\n"
                f"  Full response: {full}"
            )


def _build_common_body(prompt, aspect_ratio, resolution, output_format):
    if not prompt or not prompt.strip():
        raise Exception(
            "Wavespeed requires a non-empty prompt. Enter prompt text on the node before running."
        )
    body = {
        "prompt": prompt.strip(),
        "resolution": resolution,
        "output_format": output_format,
    }
    if aspect_ratio and aspect_ratio != "auto":
        body["aspect_ratio"] = aspect_ratio
    return body


def _check_search_mutex(enable_web_search, enable_image_search):
    if enable_web_search and enable_image_search:
        raise Exception(
            "Nano Banana 2: enable_web_search and enable_image_search cannot both be ON. "
            "Pick one — web search grounds on real-time text info, image search grounds on visual references."
        )


# --- Nodes ---

class SymbioticaWavespeedNanoBanana2:
    """Google Nano Banana 2 — Text to Image. Optional grounding via web + image search."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "auto"}),
                "resolution": (RESOLUTIONS_FULL, {"default": "1k"}),
                "enable_web_search": ("BOOLEAN", {"default": False, "label_on": "web search ON", "label_off": "web search off"}),
                "enable_image_search": ("BOOLEAN", {"default": False, "label_on": "image search ON", "label_off": "image search off"}),
                "output_format": (OUTPUT_FORMATS, {"default": "png"}),
            },
            "optional": {
                "api_key": ("STRING", {"default": ""}),
                "timeout": ("INT", {"default": 300, "min": 30, "max": 1800, "step": 10}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "task_id", "result_url")
    FUNCTION = "run"
    CATEGORY = "Symbiotica/Wavespeed"

    def run(self, prompt, aspect_ratio, resolution, enable_web_search, enable_image_search,
            output_format, api_key="", timeout=300):
        _check_search_mutex(enable_web_search, enable_image_search)
        body = _build_common_body(prompt, aspect_ratio, resolution, output_format)
        body["enable_web_search"] = bool(enable_web_search)
        body["enable_image_search"] = bool(enable_image_search)
        data = _submit_and_poll("google/nano-banana-2/text-to-image", body, api_key, timeout)
        outputs = data.get("outputs") or []
        image = _outputs_to_image_tensor(outputs)
        return (image, data.get("id", ""), outputs[0] if outputs else "")


class SymbioticaWavespeedNanoBanana2Fast:
    """Google Nano Banana 2 Fast — Text to Image. Optional web search grounding."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "auto"}),
                "resolution": (RESOLUTIONS_FAST, {"default": "2k"}),
                "enable_web_search": ("BOOLEAN", {"default": False, "label_on": "web search ON", "label_off": "web search off"}),
                "output_format": (OUTPUT_FORMATS, {"default": "png"}),
            },
            "optional": {
                "api_key": ("STRING", {"default": ""}),
                "timeout": ("INT", {"default": 180, "min": 30, "max": 1800, "step": 10}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "task_id", "result_url")
    FUNCTION = "run"
    CATEGORY = "Symbiotica/Wavespeed"

    def run(self, prompt, aspect_ratio, resolution, enable_web_search, output_format,
            api_key="", timeout=180):
        body = _build_common_body(prompt, aspect_ratio, resolution, output_format)
        body["enable_web_search"] = bool(enable_web_search)
        data = _submit_and_poll("google/nano-banana-2/text-to-image-fast", body, api_key, timeout)
        outputs = data.get("outputs") or []
        image = _outputs_to_image_tensor(outputs)
        return (image, data.get("id", ""), outputs[0] if outputs else "")


class SymbioticaWavespeedNanoBanana2Edit:
    """Google Nano Banana 2 — Edit. Takes up to 14 reference images; optional web + image search."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "auto"}),
                "resolution": (RESOLUTIONS_FULL, {"default": "1k"}),
                "enable_web_search": ("BOOLEAN", {"default": False, "label_on": "web search ON", "label_off": "web search off"}),
                "enable_image_search": ("BOOLEAN", {"default": False, "label_on": "image search ON", "label_off": "image search off"}),
                "output_format": (OUTPUT_FORMATS, {"default": "png"}),
            },
            "optional": {
                "api_key": ("STRING", {"default": ""}),
                "timeout": ("INT", {"default": 300, "min": 30, "max": 1800, "step": 10}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "task_id", "result_url")
    FUNCTION = "run"
    CATEGORY = "Symbiotica/Wavespeed"

    def run(self, images, prompt, aspect_ratio, resolution, enable_web_search, enable_image_search,
            output_format, api_key="", timeout=300):
        _check_search_mutex(enable_web_search, enable_image_search)
        body = _build_common_body(prompt, aspect_ratio, resolution, output_format)
        body["images"] = _images_tensor_to_data_uris(images)
        body["enable_web_search"] = bool(enable_web_search)
        body["enable_image_search"] = bool(enable_image_search)
        data = _submit_and_poll("google/nano-banana-2/edit", body, api_key, timeout)
        outputs = data.get("outputs") or []
        image = _outputs_to_image_tensor(outputs)
        return (image, data.get("id", ""), outputs[0] if outputs else "")


class SymbioticaWavespeedNanoBanana2EditFast:
    """Google Nano Banana 2 Edit Fast — up to 14 reference images; optional web search grounding."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "prompt": ("STRING", {"multiline": True, "default": ""}),
                "aspect_ratio": (ASPECT_RATIOS, {"default": "auto"}),
                "resolution": (RESOLUTIONS_FAST, {"default": "2k"}),
                "enable_web_search": ("BOOLEAN", {"default": False, "label_on": "web search ON", "label_off": "web search off"}),
                "output_format": (OUTPUT_FORMATS, {"default": "png"}),
            },
            "optional": {
                "api_key": ("STRING", {"default": ""}),
                "timeout": ("INT", {"default": 180, "min": 30, "max": 1800, "step": 10}),
            },
        }

    RETURN_TYPES = ("IMAGE", "STRING", "STRING")
    RETURN_NAMES = ("image", "task_id", "result_url")
    FUNCTION = "run"
    CATEGORY = "Symbiotica/Wavespeed"

    def run(self, images, prompt, aspect_ratio, resolution, enable_web_search, output_format,
            api_key="", timeout=180):
        body = _build_common_body(prompt, aspect_ratio, resolution, output_format)
        body["images"] = _images_tensor_to_data_uris(images)
        body["enable_web_search"] = bool(enable_web_search)
        data = _submit_and_poll("google/nano-banana-2/edit-fast", body, api_key, timeout)
        outputs = data.get("outputs") or []
        image = _outputs_to_image_tensor(outputs)
        return (image, data.get("id", ""), outputs[0] if outputs else "")


NODE_CLASS_MAPPINGS = {
    "SymbioticaWavespeedNanoBanana2": SymbioticaWavespeedNanoBanana2,
    "SymbioticaWavespeedNanoBanana2Fast": SymbioticaWavespeedNanoBanana2Fast,
    "SymbioticaWavespeedNanoBanana2Edit": SymbioticaWavespeedNanoBanana2Edit,
    "SymbioticaWavespeedNanoBanana2EditFast": SymbioticaWavespeedNanoBanana2EditFast,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SymbioticaWavespeedNanoBanana2": "Symbiotica Wavespeed Nano Banana 2",
    "SymbioticaWavespeedNanoBanana2Fast": "Symbiotica Wavespeed Nano Banana 2 Fast",
    "SymbioticaWavespeedNanoBanana2Edit": "Symbiotica Wavespeed Nano Banana 2 Edit",
    "SymbioticaWavespeedNanoBanana2EditFast": "Symbiotica Wavespeed Nano Banana 2 Edit Fast",
}
