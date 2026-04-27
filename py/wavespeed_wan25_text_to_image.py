import time
from .wavespeed_api.utils import imageurl2tensor
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedWan25TextToImage:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Text description for image generation"
                })
            },
            "optional": {
                "size": ("STRING", {
                    "default": "1024*1024",
                    "tooltip": "Image resolution (width*height). Range: 768~1440 pixels per dimension"
                }),
                "negative_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Describe what you don't want in the image"
                }),
                "enable_prompt_expansion": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Automatically expand and enhance the prompt"
                }),
                "seed": ("INT", {
                    "default": -1,
                    "min": -1,
                    "max": 2147483647,
                    "control_after_generate": True,
                    "tooltip": "Random seed for reproducible results. -1 for random seed"
                }),
                "enable_sync_mode": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Wait for generation to complete before returning"
                })
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("output_image",)
    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"

    def execute(self, client, prompt, size="1024*1024", negative_prompt="",
                enable_prompt_expansion=False, seed=-1, enable_sync_mode=False):
        # Create the actual client object from the client dict
        real_client = WaveSpeedClient(api_key=client["api_key"])

        # Build payload with all parameters from documentation
        payload = {
            "prompt": prompt,
            "size": size,
            "enable_prompt_expansion": enable_prompt_expansion,
            "seed": seed
        }

        # Add optional parameters if provided
        if negative_prompt and negative_prompt.strip():
            payload["negative_prompt"] = negative_prompt.strip()

        # API endpoint
        endpoint = "/api/v3/alibaba/wan-2.5/text-to-image"

        try:
            response = real_client.post(endpoint, payload, timeout=real_client.once_timeout)

            if enable_sync_mode:
                # For sync mode, response should contain outputs directly
                if "outputs" in response and response["outputs"]:
                    image_urls = response["outputs"]  # Already a list
                    return (imageurl2tensor(image_urls),)
                else:
                    raise Exception(f"No output received from sync API. Response: {response}")
            else:
                # For async mode, get task ID and poll for results
                task_id = response["id"]
                print(f"Task submitted successfully. Request ID: {task_id}")

                try:
                    result = real_client.wait_for_task(task_id, polling_interval=1, timeout=300)

                    if "outputs" in result and result["outputs"]:
                        image_urls = result["outputs"]  # Already a list
                        return (imageurl2tensor(image_urls),)
                    else:
                        raise Exception("Task completed but no output received")

                except Exception as e:
                    raise Exception(f"Async task failed: {str(e)}")

        except Exception as e:
            print(f"Error in {self.__class__.__name__}: {str(e)}")
            raise e

# Node registration
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedWan25TextToImage": NSWaveSpeedWan25TextToImage
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedWan25TextToImage": "NS WaveSpeed Wan 2.5 Text to Image"
}