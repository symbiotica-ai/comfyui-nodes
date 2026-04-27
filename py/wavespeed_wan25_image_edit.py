"""
Alibaba Wan 2.5 Image Edit node for ComfyUI
API Endpoint: /api/v3/alibaba/wan-2.5/image-edit
Documentation: https://wavespeed.ai/docs/docs-api/alibaba/alibaba-wan-2.5-image-edit
"""

import time
from .wavespeed_api.utils import imageurl2tensor
from .wavespeed_api.client import WaveSpeedClient


class NSWaveSpeedWan25ImageEdit:
    """
    Alibaba Wan 2.5 Image Edit node
    Preserves layout and subject structure while implementing high-quality updates based on natural language
    """

    # Resolution presets based on recommended resolutions from documentation
    RESOLUTION_MAP = {
        "1024x1024 (1:1)": (1024, 1024),
        "1448x1448 (1:1)": (1448, 1448),
        "1344x768 (16:9)": (1344, 768),
        "768x1344 (9:16)": (768, 1344),
        "1936x1089 (16:9 HD)": (1936, 1089),
        "1089x1936 (9:16 HD)": (1089, 1936),
        "1152x896 (4:3)": (1152, 896),
        "896x1152 (3:4)": (896, 1152),
        "1672x1254 (4:3 HD)": (1672, 1254),
        "1254x1672 (3:4 HD)": (1254, 1672),
        "Custom": (None, None)
    }

    SIZES = list(RESOLUTION_MAP.keys())

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Positive prompt describing desired adjustments to the image"
                }),
                "image_1": ("STRING", {
                    "default": "",
                    "tooltip": "First input image URL (required - connect from Upload Image node)",
                    "forceInput": True
                }),
                "size": (s.SIZES, {
                    "default": "1024x1024 (1:1)",
                    "tooltip": "The output resolution and aspect ratio"
                }),
                "seed": ("INT", {
                    "default": -1,
                    "min": -1,
                    "max": 2147483647,
                    "control_after_generate": True,
                    "tooltip": "Random seed for reproducible results. -1 for random seed"
                }),
                "enable_sync_mode": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Wait for generation to complete before returning"
                }),
            },
            "optional": {
                "image_2": ("STRING", {
                    "default": "",
                    "tooltip": "Second input image URL (optional - for multi-image editing)"
                }),
                "custom_width": ("INT", {
                    "default": 1024,
                    "min": 384,
                    "max": 5000,
                    "step": 8,
                    "tooltip": "Custom width (384-5000px, used when Custom is selected)"
                }),
                "custom_height": ("INT", {
                    "default": 1024,
                    "min": 384,
                    "max": 5000,
                    "step": 8,
                    "tooltip": "Custom height (384-5000px, used when Custom is selected)"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("output_image",)
    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"

    def execute(self, client, prompt, image_1, size="1024x1024 (1:1)", seed=-1,
                enable_sync_mode=True, image_2="", custom_width=1024, custom_height=1024):
        """
        Execute Alibaba Wan 2.5 Image Edit
        Preserves layout and subject structure while implementing high-quality updates
        """

        # Create the actual client object from the client dict
        real_client = WaveSpeedClient(api_key=client["api_key"])

        # Build images array (1-2 images supported)
        images = [image_1]
        if image_2 and image_2.strip():
            images.append(image_2.strip())

        # Determine output size
        if size == "Custom":
            # Use custom dimensions
            output_size = f"{custom_width}*{custom_height}"
        else:
            # Use preset dimensions
            if size in self.RESOLUTION_MAP:
                width, height = self.RESOLUTION_MAP[size]
                if width is None or height is None:
                    # Fallback to custom if preset is invalid
                    output_size = f"{custom_width}*{custom_height}"
                else:
                    output_size = f"{width}*{height}"
            else:
                raise ValueError(f"Invalid size selection: {size}")

        # Build payload
        payload = {
            "prompt": prompt,
            "images": images,
            "size": output_size
        }

        # Add seed if not random (-1)
        if seed != -1:
            payload["seed"] = seed

        # API endpoint
        endpoint = "/api/v3/alibaba/wan-2.5/image-edit"

        print(f"Alibaba Wan 2.5 Image Edit - Sending request with {len(images)} image(s)")
        print(f"Output size: {output_size}")
        print(f"Prompt: {prompt[:100]}..." if len(prompt) > 100 else f"Prompt: {prompt}")

        try:
            # Send request
            response = real_client.post(endpoint, payload, timeout=real_client.once_timeout)

            # Handle sync mode
            if enable_sync_mode:
                # In sync mode, the API should return the completed result
                if "outputs" in response and response["outputs"]:
                    image_urls = response["outputs"]  # Already a list
                    print(f"Sync mode: Received {len(image_urls)} output image(s)")
                    return (imageurl2tensor(image_urls),)
                else:
                    raise Exception(f"No output received from sync API. Response: {response}")

            # Handle async mode
            else:
                # Extract task ID for async polling
                task_id = response.get("id")
                if not task_id:
                    raise Exception(f"No task ID received from async API. Response: {response}")

                print(f"Async mode: Task submitted successfully. Request ID: {task_id}")
                print("Polling for results...")

                try:
                    # Poll for task completion
                    result = real_client.wait_for_task(
                        task_id,
                        polling_interval=2,  # Poll every 2 seconds
                        timeout=300  # 5 minute timeout
                    )

                    # Extract output URLs from completed task
                    if "outputs" in result and result["outputs"]:
                        image_urls = result["outputs"]  # Already a list
                        print(f"Async mode: Task completed. Received {len(image_urls)} output image(s)")

                        # Check for NSFW content warning
                        if "has_nsfw_contents" in result and any(result["has_nsfw_contents"]):
                            print("Warning: Some outputs may contain NSFW content")

                        return (imageurl2tensor(image_urls),)
                    else:
                        raise Exception("Task completed but no output images received")

                except Exception as e:
                    raise Exception(f"Async task failed: {str(e)}")

        except Exception as e:
            print(f"Error in Alibaba Wan 2.5 Image Edit: {str(e)}")
            raise e


# Node registration - REQUIRED
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedWan25ImageEdit": NSWaveSpeedWan25ImageEdit
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedWan25ImageEdit": "NS WaveSpeed Wan 2.5 Image Edit"
}