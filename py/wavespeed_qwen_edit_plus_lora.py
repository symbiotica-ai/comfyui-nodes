import time
from .wavespeed_api.utils import imageurl2tensor
from .wavespeed_api.client import WaveSpeedClient


class NSWaveSpeedQwenEditPlusLora:
    # Resolution presets with aspect ratios (max 1536 pixels per dimension)
    RESOLUTION_MAP = {
        "1328x1328 (1:1)": (1328, 1328),
        "1536x864 (16:9)": (1536, 864),
        "864x1536 (9:16)": (864, 1536),
        "1472x1104 (4:3)": (1472, 1104),
        "1104x1472 (3:4)": (1104, 1472),
        "1536x1024 (3:2)": (1536, 1024),
        "1024x1536 (2:3)": (1024, 1536)
    }

    SIZES = list(RESOLUTION_MAP.keys())

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
            },
            "optional": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Edit instructions (supports Chinese & English). Describes the changes you want to make to the image."
                }),
                "image_url_1": ("STRING", {
                    "default": "",
                    "tooltip": "First reference image URL (connect from Upload Image node)",
                    "forceInput": True
                }),
                "image_url_2": ("STRING", {
                    "default": "",
                    "tooltip": "Second reference image URL (optional, max 3 total)"
                }),
                "image_url_3": ("STRING", {
                    "default": "",
                    "tooltip": "Third reference image URL (optional, max 3 total)"
                }),
                "lora_1_path": ("STRING", {
                    "default": "",
                    "tooltip": "First LoRA model path (e.g., 'flymy-ai/qwen-image-realism-lora')"
                }),
                "lora_1_scale": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.0,
                    "max": 4.0,
                    "step": 0.1,
                    "tooltip": "First LoRA influence scale (0.0 to 4.0)"
                }),
                "lora_2_path": ("STRING", {
                    "default": "",
                    "tooltip": "Second LoRA model path (optional)"
                }),
                "lora_2_scale": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.0,
                    "max": 4.0,
                    "step": 0.1,
                    "tooltip": "Second LoRA influence scale (0.0 to 4.0)"
                }),
                "lora_3_path": ("STRING", {
                    "default": "",
                    "tooltip": "Third LoRA model path (optional)"
                }),
                "lora_3_scale": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.0,
                    "max": 4.0,
                    "step": 0.1,
                    "tooltip": "Third LoRA influence scale (0.0 to 4.0)"
                }),
                "size": (s.SIZES, {
                    "default": "1328x1328 (1:1)",
                    "tooltip": "The aspect ratio and resolution of the output image"
                }),
                "custom_size": ("STRING", {
                    "default": "",
                    "tooltip": "Custom size as 'width*height' (e.g. '1920*1080'). Overrides size dropdown if provided."
                }),
                "seed": ("INT", {
                    "default": -1,
                    "min": -1,
                    "max": 2147483647,
                    "control_after_generate": True,
                    "tooltip": "Random seed for reproducible results. -1 for random seed"
                }),
                "output_format": (["jpeg", "png", "webp"], {
                    "default": "jpeg",
                    "tooltip": "Output image format"
                }),
                "enable_base64_output": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Return image as BASE64 encoded string instead of URL"
                }),
                "enable_sync_mode": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Wait for generation to complete before returning"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("output_image",)
    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"

    def execute(self, client, prompt="", image_url_1="", image_url_2="", image_url_3="",
                lora_1_path="", lora_1_scale=1.0, lora_2_path="", lora_2_scale=1.0,
                lora_3_path="", lora_3_scale=1.0, size="1328x1328 (1:1)", custom_size="",
                seed=-1, output_format="jpeg", enable_base64_output=False, enable_sync_mode=True):
        # Create the actual client object from the client dict
        real_client = WaveSpeedClient(api_key=client["api_key"])

        # Collect image URLs (max 3)
        image_urls = []
        if image_url_1 and image_url_1.strip():
            image_urls.append(image_url_1.strip())
        if image_url_2 and image_url_2.strip():
            image_urls.append(image_url_2.strip())
        if image_url_3 and image_url_3.strip():
            image_urls.append(image_url_3.strip())

        if not image_urls:
            raise Exception("At least one image URL is required for editing")

        # Use custom size if provided, otherwise convert dropdown selection to width*height
        if custom_size.strip():
            final_size = custom_size.strip()
            # Validate custom size format
            if '*' not in final_size:
                raise ValueError(f"Invalid custom size format: {final_size}. Must be 'width*height' (e.g., '1024*1024')")
        else:
            # Get resolution from map
            if size in self.RESOLUTION_MAP:
                width, height = self.RESOLUTION_MAP[size]
                final_size = f"{width}*{height}"
            else:
                raise ValueError(f"Invalid size selection: {size}")

        # Build LoRA list (max 3)
        lora_list = []
        if lora_1_path and lora_1_path.strip():
            lora_list.append({
                "path": lora_1_path.strip(),
                "scale": lora_1_scale
            })
        if lora_2_path and lora_2_path.strip():
            lora_list.append({
                "path": lora_2_path.strip(),
                "scale": lora_2_scale
            })
        if lora_3_path and lora_3_path.strip():
            lora_list.append({
                "path": lora_3_path.strip(),
                "scale": lora_3_scale
            })

        # Build payload
        payload = {
            "images": image_urls,
            "size": final_size,
            "output_format": output_format,
            "enable_base64_output": enable_base64_output,
            "enable_sync_mode": enable_sync_mode
        }

        # Add optional parameters
        if prompt and prompt.strip():
            payload["prompt"] = prompt.strip()

        if lora_list:
            payload["loras"] = lora_list

        if seed != -1:
            payload["seed"] = seed

        # API endpoint
        endpoint = "/api/v3/wavespeed-ai/qwen-image/edit-plus-lora"

        try:
            response = real_client.post(endpoint, payload, timeout=real_client.once_timeout)

            if enable_sync_mode:
                # Sync mode - response should contain outputs directly
                if "outputs" in response and response["outputs"]:
                    image_urls = response["outputs"]
                    return (imageurl2tensor(image_urls),)
                else:
                    raise Exception(f"No output received from sync API. Response: {response}")
            else:
                # Async mode - need to poll for results
                task_id = response["id"]
                print(f"Qwen Image Edit Plus LoRA task submitted. Request ID: {task_id}")

                try:
                    result = real_client.wait_for_task(task_id, polling_interval=2, timeout=300)

                    if "outputs" in result and result["outputs"]:
                        image_urls = result["outputs"]
                        return (imageurl2tensor(image_urls),)
                    else:
                        raise Exception("Task completed but no output received")

                except Exception as e:
                    raise Exception(f"Async task failed: {str(e)}")

        except Exception as e:
            print(f"Error in Qwen Image Edit Plus LoRA: {str(e)}")
            raise e


# Node registration
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedQwenEditPlusLora": NSWaveSpeedQwenEditPlusLora
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedQwenEditPlusLora": "NS WaveSpeed Qwen Edit Plus LoRA"
}