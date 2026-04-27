import time
from .wavespeed_api.utils import imageurl2tensor
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedFluxKontextDev:
    """
    Flux Kontext Dev Node

    Advanced image-to-image transformation model for style conversion.
    Specializes in converting images to anime style and other artistic transformations.
    Built on Flux architecture with enhanced context understanding.
    """


    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "Turn pictures into anime style",
                    "tooltip": "Text prompt describing the desired transformation (e.g., 'Turn pictures into anime style')"
                }),
                "image_url": ("STRING", {
                    "default": "",
                    "tooltip": "The image URL to transform (connect from Upload Image node)",
                    "forceInput": True
                }),
                "guidance_scale": ("FLOAT", {
                    "default": 2.5,
                    "min": 1.0,
                    "max": 20.0,
                    "step": 0.1,
                    "tooltip": "How closely to follow the prompt (1.0 = loose, 20.0 = strict)"
                }),
                "num_inference_steps": ("INT", {
                    "default": 28,
                    "min": 10,
                    "max": 100,
                    "step": 1,
                    "tooltip": "Number of denoising steps (more steps = higher quality, slower)"
                }),
                "seed": ("INT", {
                    "default": -1,
                    "min": -1,
                    "max": 0xffffffffffffffff,
                    "control_after_generate": True,
                    "tooltip": "Random seed for reproducible results. -1 for random seed"
                }),
                "output_format": (["jpeg", "png", "webp"], {
                    "default": "jpeg",
                    "tooltip": "The format of the output image"
                }),
                "enable_sync_mode": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Wait for image generation to complete before returning"
                }),
            },
            "optional": {
                "num_images": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 4,
                    "step": 1,
                    "tooltip": "Number of images to generate (1-4)"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("output_image",)

    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"

    def execute(self, client, prompt, image_url, guidance_scale=2.5,
                num_inference_steps=28, seed=-1, output_format="jpeg", enable_sync_mode=True,
                num_images=1):
        """
        Execute the Flux Kontext Dev model

        Args:
            client: WaveSpeed API client
            prompt: Text prompt for image transformation
            image_url: Input image URL to transform
            guidance_scale: How closely to follow the prompt
            num_inference_steps: Number of denoising steps
            seed: Random seed (-1 for random)
            output_format: Output format (jpeg, png, or webp)
            enable_sync_mode: Whether to wait for completion
            num_images: Number of images to generate

        Returns:
            Transformed image tensor
        """

        # Prepare the request payload
        payload = {
            "prompt": prompt,
            "image": image_url,
            "guidance_scale": guidance_scale,
            "num_inference_steps": num_inference_steps,
            "num_images": num_images,
            "seed": seed,
            "output_format": output_format,
            "enable_sync_mode": enable_sync_mode,
            "enable_base64_output": False
        }

        # API endpoint for Flux Kontext Dev
        endpoint = "/api/v3/wavespeed-ai/flux-kontext-dev"

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
            print(f"Error in Flux Kontext Dev: {str(e)}")
            raise e


# Node registration
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedFluxKontextDev": NSWaveSpeedFluxKontextDev
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedFluxKontextDev": "NS WaveSpeed Flux Kontext Dev"
}