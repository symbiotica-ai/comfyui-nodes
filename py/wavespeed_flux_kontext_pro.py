import time
from .wavespeed_api.utils import imageurl2tensor
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedFluxKontextPro:
    """
    Flux Kontext Pro Node

    Professional-grade image-to-image transformation model optimized for production use.
    Streamlined version of Flux Kontext with simplified parameters and enhanced performance.
    Ideal for consistent, high-quality image transformations with minimal configuration.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "A woman is brewing tea",
                    "tooltip": "Text prompt describing the desired transformation or scene"
                }),
                "image_url": ("STRING", {
                    "default": "",
                    "tooltip": "The image URL to transform (connect from Upload Image node)",
                    "forceInput": True
                }),
                "guidance_scale": ("FLOAT", {
                    "default": 3.5,
                    "min": 1.0,
                    "max": 20.0,
                    "step": 0.1,
                    "tooltip": "How closely to follow the prompt (1.0 = loose, 20.0 = strict)"
                }),
                "enable_sync_mode": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Wait for image generation to complete before returning"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("output_image",)

    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"

    def execute(self, client, prompt, image_url, guidance_scale=3.5, enable_sync_mode=True):
        """
        Execute the Flux Kontext Pro model

        Args:
            client: WaveSpeed API client
            prompt: Text prompt for image transformation
            image_url: Input image URL to transform
            guidance_scale: How closely to follow the prompt
            enable_sync_mode: Whether to wait for completion

        Returns:
            Transformed image tensor
        """

        # Prepare the request payload
        payload = {
            "prompt": prompt,
            "image": image_url,
            "guidance_scale": guidance_scale,
            "enable_sync_mode": enable_sync_mode
        }

        # API endpoint for Flux Kontext Pro
        endpoint = "/api/v3/wavespeed-ai/flux-kontext-pro"

        try:
            # Create the actual client object from the client dict
            real_client = WaveSpeedClient(api_key=client["api_key"])

            # Make the API request
            response = real_client.post(endpoint, payload, timeout=real_client.once_timeout)

            # Handle sync mode response
            if enable_sync_mode:
                # WaveSpeedClient already extracts the 'data' field
                if "outputs" in response and response["outputs"]:
                    image_urls = response["outputs"]
                    print(f"Sync mode completed. Generated {len(image_urls)} image(s)")
                    # Pass the full URLs array
                    return (imageurl2tensor(image_urls),)
                else:
                    raise Exception(f"No output received from sync API. Response: {response}")

            # Handle async mode response
            else:
                # Extract task ID from response
                if "id" not in response:
                    raise Exception(f"No task ID received from API. Response: {response}")

                task_id = response["id"]
                print(f"Task submitted successfully. Request ID: {task_id}")

                # Use the client's wait_for_task method for polling
                try:
                    result = real_client.wait_for_task(task_id, polling_interval=1, timeout=300)

                    if "outputs" in result and result["outputs"]:
                        image_urls = result["outputs"]
                        print(f"Task completed. Generated {len(image_urls)} image(s)")
                        # Pass the full URLs array
                        return (imageurl2tensor(image_urls),)
                    else:
                        raise Exception("Task completed but no output received")

                except Exception as e:
                    raise Exception(f"Async task failed: {str(e)}")

        except Exception as e:
            print(f"Error in Flux Kontext Pro: {str(e)}")
            raise e


# Node registration
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedFluxKontextPro": NSWaveSpeedFluxKontextPro
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedFluxKontextPro": "NS WaveSpeed Flux Kontext Pro"
}