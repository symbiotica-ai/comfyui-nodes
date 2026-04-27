import time
from .wavespeed_api.utils import imageurl2tensor
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedImageUpscaler:
    """
    WaveSpeed AI Image Upscaler Node

    The AI image upscaler is a powerful tool designed to enhance the resolution and quality of images.
    Our model allows users to choose different levels of enhancement by adjusting the value of creativity.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "image_url": ("STRING", {
                    "default": "",
                    "tooltip": "URL of the image to upscale (connect from Upload Image node)",
                    "forceInput": True
                }),
                "target_resolution": (["2k", "4k", "8k"], {
                    "default": "4k",
                    "tooltip": "Target resolution for upscaling"
                }),
                "creativity": ("FLOAT", {
                    "default": 0.0,
                    "min": -2.0,
                    "max": 2.0,
                    "step": 0.1,
                    "display": "slider",
                    "tooltip": "Enhancement level (-2 to 2). Higher values add more detail but may alter the image"
                }),
                "output_format": (["jpeg", "png", "webp"], {
                    "default": "jpeg",
                    "tooltip": "Output image format"
                }),
                "enable_sync_mode": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Wait for upscaling to complete before returning"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("upscaled_image",)
    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"

    def execute(self, client, image_url, target_resolution="4k", creativity=0.0,
                output_format="jpeg", enable_sync_mode=True):
        """
        Execute the Image Upscaler model

        Args:
            client: WaveSpeed API client dictionary
            image_url: URL of the image to upscale
            target_resolution: Target resolution (2k, 4k, or 8k)
            creativity: Enhancement level (-2 to 2)
            output_format: Output format (jpeg, png, or webp)
            enable_sync_mode: Whether to wait for completion

        Returns:
            Upscaled image tensor
        """

        # Create the actual client object from the client dict
        real_client = WaveSpeedClient(api_key=client["api_key"])

        # Validate creativity range
        if creativity < -2.0 or creativity > 2.0:
            raise ValueError(f"Creativity must be between -2 and 2, got {creativity}")

        # Build payload
        payload = {
            "image": image_url,
            "target_resolution": target_resolution,
            "creativity": creativity,
            "output_format": output_format,
            "enable_sync_mode": enable_sync_mode,
            "enable_base64_output": False
        }

        # API endpoint for Image Upscaler
        endpoint = "/api/v3/wavespeed-ai/image-upscaler"

        try:
            # Make the API request
            response = real_client.post(endpoint, payload, timeout=real_client.once_timeout)

            if enable_sync_mode:
                # In sync mode, we get the results directly
                if "outputs" in response and response["outputs"]:
                    image_urls = response["outputs"]  # Already a list
                    return (imageurl2tensor(image_urls),)
                else:
                    raise Exception(f"No output received from sync API. Response: {response}")
            else:
                # In async mode, we need to poll for results
                task_id = response["id"]
                print(f"Task submitted successfully. Request ID: {task_id}")

                try:
                    # Wait for task to complete using the helper method
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
    "NSWaveSpeedImageUpscaler": NSWaveSpeedImageUpscaler
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedImageUpscaler": "NS WaveSpeed Image Upscaler"
}