import time
from .wavespeed_api.utils import imageurl2tensor
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedQwenEdit:
    """
    Qwen Image Edit Node
    
    Qwen-Image-Edit — a 20B MMDiT model for next-gen image edit generation. 
    Built on 20B Qwen-Image, it brings precise bilingual text editing (Chinese & English) 
    while preserving style, and supports both semantic and appearance-level editing.
    """
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "prompt": ("STRING", {
                    "multiline": True, 
                    "default": "",
                    "tooltip": "The prompt to generate an image from (supports Chinese & English)"
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
            }
        }
    
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    
    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"
    
    def execute(self, client, prompt, image_url, seed=-1, output_format="jpeg", 
                enable_sync_mode=True):
        """
        Execute the Qwen Image Edit model
        
        Args:
            client: WaveSpeed API client
            prompt: Text prompt for image editing (supports bilingual)
            image_url: Input image URL to edit
            seed: Random seed (-1 for random)
            output_format: Output format (jpeg, png, or webp)
            enable_sync_mode: Whether to wait for completion
        
        Returns:
            Edited image tensor
        """
        
        # Prepare the request payload
        payload = {
            "prompt": prompt,
            "image": image_url,
            "seed": seed,
            "output_format": output_format,
            "enable_sync_mode": enable_sync_mode,
            "enable_base64_output": False
        }
        
        # API endpoint for Qwen Image Edit
        endpoint = "/api/v3/wavespeed-ai/qwen-image/edit"
        
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
                    raise Exception("No output received from API")
            
            # Handle async mode response
            else:
                # Poll for completion
                task_id = response.get("id")
                if not task_id:
                    raise Exception("No task ID received from API")
                
                # Poll endpoint
                poll_endpoint = f"/api/v3/tasks/{task_id}"
                max_attempts = 60  # Max 30 minutes with 30 second intervals
                
                for attempt in range(max_attempts):
                    time.sleep(30)  # Wait 30 seconds between polls
                    
                    poll_response = real_client.get(poll_endpoint)
                    status = poll_response.get("status")
                    
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
            print(f"Error in Qwen Image Edit: {str(e)}")
            raise e


# Node registration
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedQwenEdit": NSWaveSpeedQwenEdit
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedQwenEdit": "NS WaveSpeed Qwen Edit"
}