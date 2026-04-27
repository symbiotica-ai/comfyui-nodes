import time

from .wavespeed_api.client import WaveSpeedClient
from .wavespeed_api.utils import imageurl2tensor


class NSWaveSpeedNanoBananaProEditUltra:
    """
    Google Nano Banana Pro Edit Ultra (Gemini 3.0 Pro Image)

    Ultra high-resolution AI-powered image editing with 4K/8K output support.
    Combines precision, flexibility, and semantic awareness for professional-grade editing.

    Features:
    - Native 4K/8K image generation with fine detail and clean edges
    - Natural-language, context-aware editing
    - Multilingual on-image text with auto translation
    - Camera-style controls (angle, focus, depth of field)
    - Consistent character and style rendering
    - Supports up to 6 input images

    Pricing: $0.15/image (4k), $0.18/image (8k)
    """

    # Aspect ratio options
    ASPECT_RATIOS = [
        "1:1",
        "3:2",
        "2:3",
        "3:4",
        "4:3",
        "4:5",
        "5:4",
        "9:16",
        "16:9",
        "21:9",
    ]

    # Resolution options (Ultra = 4k/8k)
    RESOLUTIONS = ["4k", "8k"]

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "prompt": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": "Text description of the edit to perform (e.g., 'Replace the cloudy sky with a clear sunset')",
                    },
                ),
                "image_1": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Primary input image URL (connect from Upload Image node)",
                        "forceInput": True,
                    },
                ),
                "image_2": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Second input image URL (optional)",
                    },
                ),
                "image_3": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Third input image URL (optional)",
                    },
                ),
                "image_4": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Fourth input image URL (optional)",
                    },
                ),
                "image_5": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Fifth input image URL (optional)",
                    },
                ),
                "image_6": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Sixth input image URL (optional)",
                    },
                ),
                "aspect_ratio": (
                    s.ASPECT_RATIOS,
                    {
                        "default": "1:1",
                        "tooltip": "Aspect ratio of the output image",
                    },
                ),
                "resolution": (
                    s.RESOLUTIONS,
                    {
                        "default": "4k",
                        "tooltip": "Output resolution: 4k ($0.15), 8k ($0.18)",
                    },
                ),
                "output_format": (
                    ["png", "jpeg"],
                    {
                        "default": "png",
                        "tooltip": "Output format - use PNG for transparency support",
                    },
                ),
                "enable_sync_mode": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "tooltip": "Wait for generation to complete before returning",
                    },
                ),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("output_image",)
    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"

    def execute(
        self,
        client,
        prompt,
        image_1,
        image_2,
        image_3,
        image_4,
        image_5,
        image_6,
        aspect_ratio,
        resolution,
        output_format,
        enable_sync_mode,
    ):
        real_client = WaveSpeedClient(api_key=client["api_key"])

        # Build images array from all provided image inputs
        images = [image_1]

        for img in [image_2, image_3, image_4, image_5, image_6]:
            if img and img.strip():
                images.append(img.strip())

        payload = {
            "prompt": prompt,
            "images": images,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": output_format,
            "enable_sync_mode": enable_sync_mode,
            "enable_base64_output": False,
        }

        endpoint = "/api/v3/google/nano-banana-pro/edit-ultra"

        try:
            response = real_client.post(
                endpoint, payload, timeout=real_client.once_timeout
            )

            if enable_sync_mode:
                if "outputs" in response and response["outputs"]:
                    image_urls = response["outputs"]
                    return (imageurl2tensor(image_urls),)
                else:
                    raise Exception(
                        f"No output received from sync API. Response: {response}"
                    )
            else:
                task_id = response["id"]
                print(f"Task submitted successfully. Request ID: {task_id}")

                try:
                    result = real_client.wait_for_task(
                        task_id, polling_interval=1, timeout=300
                    )

                    if "outputs" in result and result["outputs"]:
                        image_urls = result["outputs"]
                        return (imageurl2tensor(image_urls),)
                    else:
                        raise Exception("Task completed but no output received")

                except Exception as e:
                    raise Exception(f"Async task failed: {str(e)}")

        except Exception as e:
            print(f"Error in {self.__class__.__name__}: {str(e)}")
            raise e


NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedNanoBananaProEditUltra": NSWaveSpeedNanoBananaProEditUltra
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedNanoBananaProEditUltra": "NS WaveSpeed Nano Banana Pro Edit Ultra"
}
