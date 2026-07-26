# ABOUTME: Trellis 2 image-to-3D node backed by fal.ai — one image in, a textured
# ABOUTME: GLB mesh out (saved under the output dir for Preview 3D + download).
import base64
import io
import time

import numpy as np
import requests
from PIL import Image

FAL_ENDPOINT = "https://fal.run/fal-ai/trellis-2"
# Sync generation runs a couple of minutes; leave generous headroom.
REQUEST_TIMEOUT_S = 900


def image_to_data_uri(arr) -> str:
    """A float (0-1) or uint8 HWC numpy image as a PNG data URI — fal accepts
    data URIs directly, so no upload hop is needed."""
    a = np.asarray(arr)
    if a.dtype != np.uint8:
        a = (np.clip(a, 0.0, 1.0) * 255.0).round().astype(np.uint8)
    buf = io.BytesIO()
    Image.fromarray(a).save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def build_payload(image_uri: str, resolution: int, seed: int, texture_size: int) -> dict:
    """The fal request body; -1 means let the service pick a seed."""
    payload = {
        "image_url": image_uri,
        "resolution": resolution,
        "texture_size": texture_size,
    }
    if seed != -1:
        payload["seed"] = seed
    return payload


def glb_from_response(resp: dict) -> str:
    url = (resp.get("model_glb") or {}).get("url")
    if not url:
        raise ValueError(f"fal response carries no model_glb: {resp}")
    return url


class SymbioticaTrellis2:
    """Generate a textured 3D mesh (GLB) from a single image via fal's
    Trellis 2 endpoint. Feed `model_file` into ComfyUI's Preview 3D node."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "image": ("IMAGE",),
                "resolution": ([512, 1024, 1536], {
                    "default": 1024,
                    "tooltip": "Voxel resolution of the generated geometry"
                }),
                "texture_size": ([1024, 2048, 4096], {
                    "default": 2048,
                    "tooltip": "Baked PBR texture resolution"
                }),
                "seed": ("INT", {
                    "default": -1,
                    "min": -1,
                    "max": 2147483647,
                    "control_after_generate": True,
                    "tooltip": "-1 lets fal pick a random seed"
                }),
            },
            "optional": {
                "api_key": ("STRING", {
                    "default": "",
                    "tooltip": "fal API key; empty falls back to the Symbiotica.FAL_KEY setting or the FAL_KEY env var"
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("model_file", "glb_url")
    CATEGORY = "symbiotica/3D"
    FUNCTION = "execute"

    def execute(self, image, resolution, texture_size, seed, api_key=""):
        key = api_key.strip()
        if not key:
            from ._settings import resolve_key
            key = resolve_key(["FAL_KEY"]) or ""
        if not key:
            raise ValueError(
                "FAL_KEY is empty. Set it in Settings (Symbiotica.FAL_KEY), "
                "the FAL_KEY env var, or the node's api_key input."
            )

        # ComfyUI images are [batch, H, W, C] float tensors — first frame only.
        frame = image[0]
        if hasattr(frame, "cpu"):
            frame = frame.cpu().numpy()
        payload = build_payload(image_to_data_uri(frame), resolution, seed, texture_size)

        print("[Symbiotica] Trellis 2: submitting to fal (runs ~1-3 min)...")
        resp = requests.post(
            FAL_ENDPOINT,
            json=payload,
            headers={"Authorization": f"Key {key}"},
            timeout=REQUEST_TIMEOUT_S,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"fal trellis-2 failed ({resp.status_code}): {resp.text[:500]}")
        url = glb_from_response(resp.json())

        glb = requests.get(url, timeout=REQUEST_TIMEOUT_S)
        glb.raise_for_status()

        import os

        import folder_paths

        out_dir = os.path.join(folder_paths.get_output_directory(), "3d")
        os.makedirs(out_dir, exist_ok=True)
        name = f"trellis2_{int(time.time())}.glb"
        with open(os.path.join(out_dir, name), "wb") as f:
            f.write(glb.content)
        rel = f"3d/{name}"
        print(f"[Symbiotica] Trellis 2: saved {rel} ({len(glb.content)} bytes)")
        return (rel, url)


NODE_CLASS_MAPPINGS = {"SymbioticaTrellis2": SymbioticaTrellis2}

NODE_DISPLAY_NAME_MAPPINGS = {"SymbioticaTrellis2": "Trellis 2 Image to 3D (fal)"}
