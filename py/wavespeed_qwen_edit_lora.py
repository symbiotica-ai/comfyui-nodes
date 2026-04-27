import time
from .wavespeed_api.utils import imageurl2tensor
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedQwenEditLora:
    """
    Qwen Image Edit with LoRA Node

    Advanced version of Qwen-Image-Edit that supports LoRA (Low-Rank Adaptation) models
    for fine-tuned image editing capabilities. Enables more precise control over style
    and editing behavior through custom LoRA weights.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "The prompt to edit the image (e.g., 'Change into a white shirt and a black coat')"
                }),
                "image_url": ("STRING", {
                    "default": "",
                    "tooltip": "The image URL to edit (connect from Upload Image node)",
                    "forceInput": True
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
                "lora_1_path": ("STRING", {
                    "default": "",
                    "tooltip": "First LoRA model path (e.g., 'flymy-ai/qwen-image-style-lora')"
                }),
                "lora_1_scale": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.0,
                    "max": 2.0,
                    "step": 0.1,
                    "tooltip": "First LoRA influence scale (0.0 to 2.0)"
                }),
                "lora_2_path": ("STRING", {
                    "default": "",
                    "tooltip": "Second LoRA model path (optional)"
                }),
                "lora_2_scale": ("FLOAT", {
                    "default": 1.0,
                    "min": 0.0,
                    "max": 2.0,
                    "step": 0.1,
                    "tooltip": "Second LoRA influence scale (0.0 to 2.0)"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("output_image",)

    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"

    def execute(self, client, prompt, image_url, seed=-1, output_format="jpeg",
                enable_sync_mode=True,
                lora_1_path="", lora_1_scale=1.0,
                lora_2_path="", lora_2_scale=1.0):
        """
        Execute the Qwen Image Edit LoRA model

        Args:
            client: WaveSpeed API client
            prompt: Text prompt for image editing
            image_url: Input image URL to edit
            seed: Random seed (-1 for random)
            output_format: Output format (jpeg, png, or webp)
            enable_sync_mode: Whether to wait for completion
            lora_1_path: First LoRA model path
            lora_1_scale: First LoRA influence scale
            lora_2_path: Second LoRA model path (optional)
            lora_2_scale: Second LoRA influence scale

        Returns:
            Edited image tensor
        """

        # Build LoRA configuration list
        # The edit-lora API expects objects with path and scale properties
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

        # Prepare the request payload
        payload = {
            "prompt": prompt,
            "image": image_url,
            "seed": seed,
            "output_format": output_format,
            "enable_sync_mode": enable_sync_mode,
            "enable_base64_output": False,
            "loras": lora_list
        }

        # API endpoint for Qwen Image Edit with LoRA
        endpoint = "/api/v3/wavespeed-ai/qwen-image/edit-lora"

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
                    # Pass the full URLs array like original nodes do
                    return (imageurl2tensor(image_urls),)
                else:
                    raise Exception(f"No output received from sync API. Response: {response}")

            # Handle async mode response
            else:
                # Extract task ID
                task_id = response.get("id")
                if not task_id:
                    raise Exception(f"No task ID received from API. Response: {response}")

                print(f"Task submitted successfully. Request ID: {task_id}")

                try:
                    # Use the client's built-in wait_for_task method
                    result = real_client.wait_for_task(task_id, polling_interval=1, timeout=300)

                    if "outputs" in result and result["outputs"]:
                        image_urls = result["outputs"]
                        return (imageurl2tensor(image_urls),)
                    else:
                        raise Exception("Task completed but no output received")

                except Exception as e:
                    raise Exception(f"Async task failed: {str(e)}")

        except Exception as e:
            print(f"Error in Qwen Image Edit LoRA: {str(e)}")
            raise e


# Node registration
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedQwenEditLora": NSWaveSpeedQwenEditLora
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedQwenEditLora": "NS WaveSpeed Qwen Edit LoRA"
}