import time
from .wavespeed_api.utils import imageurl2tensor
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedFluxControlNetUnionPro2:
    """
    Flux ControlNet Union Pro 2.0 Node

    Advanced ControlNet model supporting simultaneous Canny, Depth, Soft Edge, Pose,
    and Grayscale conditioning for precise image generation control.
    """

    # Size presets following Flux typical resolutions
    SIZE_PRESETS = [
        "1024*1024",
        "1024*768",
        "768*1024",
        "1024*576",
        "576*1024",
        "1152*896",
        "896*1152",
        "1344*768",
        "768*1344",
        "1536*640",
        "640*1536",
    ]

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Text description of the image to generate"
                }),
                "control_image": ("STRING", {
                    "default": "",
                    "tooltip": "URL of control image for ControlNet guidance (connect from Upload Image node)",
                    "forceInput": True
                }),
                "size": (s.SIZE_PRESETS, {
                    "default": "1024*1024",
                    "tooltip": "Resolution of the generated image"
                }),
                "num_inference_steps": ("INT", {
                    "default": 28,
                    "min": 1,
                    "max": 50,
                    "tooltip": "Number of denoising steps (higher = better quality, slower)"
                }),
                "guidance_scale": ("FLOAT", {
                    "default": 3.5,
                    "min": 0.0,
                    "max": 20.0,
                    "step": 0.1,
                    "tooltip": "How closely to follow the prompt (higher = more adherence)"
                }),
                "controlnet_conditioning_scale": ("FLOAT", {
                    "default": 0.7,
                    "min": 0.0,
                    "max": 2.0,
                    "step": 0.1,
                    "tooltip": "Influence of control image on generation (0=none, 2=maximum)"
                }),
                "control_guidance_start": ("FLOAT", {
                    "default": 0.0,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "tooltip": "When to start applying control (0=beginning)"
                }),
                "control_guidance_end": ("FLOAT", {
                    "default": 0.8,
                    "min": 0.0,
                    "max": 1.0,
                    "step": 0.01,
                    "tooltip": "When to stop applying control (1=end)"
                }),
                "seed": ("INT", {
                    "default": -1,
                    "min": -1,
                    "max": 0xffffffffffffffff,
                    "control_after_generate": True,
                    "tooltip": "Random seed for reproducible results. -1 for random seed"
                }),
                "num_images": ("INT", {
                    "default": 1,
                    "min": 1,
                    "max": 4,
                    "tooltip": "Number of images to generate (1-4)"
                }),
                "output_format": (["jpeg", "png", "webp"], {
                    "default": "jpeg",
                    "tooltip": "Format of the output image"
                }),
                "enable_sync_mode": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Wait for generation to complete before returning"
                }),
            },
            "optional": {
                "custom_size": ("STRING", {
                    "default": "",
                    "tooltip": "Custom size as 'width*height' (e.g. '1920*1080'). Overrides size dropdown if provided."
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("output_image",)

    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"

    def execute(self, client, prompt, control_image, size="1024*1024",
                num_inference_steps=28, guidance_scale=3.5,
                controlnet_conditioning_scale=0.7, control_guidance_start=0.0,
                control_guidance_end=0.8, seed=-1, num_images=1,
                output_format="jpeg", enable_sync_mode=True, custom_size=""):
        """
        Execute the Flux ControlNet Union Pro 2.0 model

        Args:
            client: WaveSpeed API client
            prompt: Text description for image generation
            control_image: URL of control image for ControlNet guidance
            size: Image resolution (width*height)
            num_inference_steps: Number of denoising steps
            guidance_scale: Text prompt guidance strength
            controlnet_conditioning_scale: Control image influence strength
            control_guidance_start: When to start applying control
            control_guidance_end: When to stop applying control
            seed: Random seed (-1 for random)
            num_images: Number of images to generate
            output_format: Output format (jpeg, png, or webp)
            enable_sync_mode: Whether to wait for completion
            custom_size: Custom resolution override

        Returns:
            Generated image tensor(s)
        """

        # Use custom size if provided, otherwise use dropdown selection
        final_size = custom_size.strip() if custom_size.strip() else size

        # Validate custom size format
        if custom_size.strip() and '*' not in custom_size:
            raise ValueError(f"Invalid custom size format: {custom_size}. Must be 'width*height'")

        # Prepare the request payload
        payload = {
            "prompt": prompt,
            "control_image": control_image,
            "size": final_size,
            "num_inference_steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "controlnet_conditioning_scale": controlnet_conditioning_scale,
            "control_guidance_start": control_guidance_start,
            "control_guidance_end": control_guidance_end,
            "num_images": num_images,
            "output_format": output_format,
            "enable_sync_mode": enable_sync_mode,
        }

        # Add seed if not -1
        if seed != -1:
            payload["seed"] = seed

        # API endpoint for Flux ControlNet Union Pro 2.0
        endpoint = "/api/v3/wavespeed-ai/flux-controlnet-union-pro-2.0"

        try:
            # Create the actual client object from the client dict
            real_client = WaveSpeedClient(api_key=client["api_key"])

            # Make the API request
            response = real_client.post(endpoint, payload, timeout=real_client.once_timeout)

            # Handle sync mode response
            if enable_sync_mode:
                # Check if we have outputs
                if "outputs" in response and response["outputs"]:
                    # Get all output URLs
                    image_urls = response["outputs"]
                    # Pass the full URLs array to imageurl2tensor
                    return (imageurl2tensor(image_urls),)
                else:
                    raise Exception(f"No output received from API. Response: {response}")

            # Handle async mode response
            else:
                # Poll for completion
                task_id = response.get("id")
                if not task_id:
                    raise Exception(f"No task ID received from API. Response: {response}")

                print(f"Task submitted successfully. Request ID: {task_id}")

                # Poll endpoint
                poll_endpoint = f"/api/v3/tasks/{task_id}"
                max_attempts = 60  # Max 30 minutes with 30 second intervals

                for attempt in range(max_attempts):
                    time.sleep(30)  # Wait 30 seconds between polls

                    poll_response = real_client.get(poll_endpoint)
                    status = poll_response.get("status")

                    print(f"Task {task_id} status: {status} (attempt {attempt + 1}/{max_attempts})")

                    if status == "completed":
                        if "outputs" in poll_response and poll_response["outputs"]:
                            image_urls = poll_response["outputs"]
                            return (imageurl2tensor(image_urls),)
                        else:
                            raise Exception("Task completed but no output received")

                    elif status == "failed":
                        error_msg = poll_response.get("error", "Task failed without error message")
                        raise Exception(f"Task failed: {error_msg}")

                raise Exception("Task timed out after 30 minutes")

        except Exception as e:
            print(f"Error in Flux ControlNet Union Pro 2.0: {str(e)}")
            raise e


# Node registration
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedFluxControlNetUnionPro2": NSWaveSpeedFluxControlNetUnionPro2
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedFluxControlNetUnionPro2": "NS WaveSpeed Flux ControlNet Union Pro 2"
}
