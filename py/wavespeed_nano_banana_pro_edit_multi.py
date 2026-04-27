import time

from .wavespeed_api.client import WaveSpeedClient
from .wavespeed_api.utils import imageurl2tensor


class NSWaveSpeedNanoBananaProEditMulti:
    """
    Google Nano Banana Pro Edit Multi (Gemini 3.0 Pro Image)

    Next-generation multi-image editing model that produces multiple edited outputs
    from one or more input images in a single run.

    Features:
    - True multi-edit generation (multiple variants per request)
    - Consistent editing style across outputs
    - Industry-leading cost efficiency at $0.07/image
    - Precise editing behavior (object replacement, style changes, etc.)
    - Fast, reliable, no cold starts
    - Supports up to 6 input images

    Pricing: $0.07/image
    """

    # Aspect ratio options (more limited for multi)
    ASPECT_RATIOS = [
        "3:2",
        "2:3",
        "3:4",
        "4:3",
    ]

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
                        "tooltip": "Text description of the edit to perform",
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
                        "default": "3:2",
                        "tooltip": "Aspect ratio of the output images",
                    },
                ),
                "num_images": (
                    "INT",
                    {
                        "default": 2,
                        "min": 2,
                        "max": 2,
                        "tooltip": "Number of edited images to generate (fixed at 2)",
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
    RETURN_NAMES = ("output_images",)
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
        num_images,
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
            "num_images": num_images,
            "output_format": output_format,
            "enable_sync_mode": enable_sync_mode,
            "enable_base64_output": False,
        }

        endpoint = "/api/v3/google/nano-banana-pro/edit-multi"

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
    "NSWaveSpeedNanoBananaProEditMulti": NSWaveSpeedNanoBananaProEditMulti
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedNanoBananaProEditMulti": "NS WaveSpeed Nano Banana Pro Edit Multi"
}
