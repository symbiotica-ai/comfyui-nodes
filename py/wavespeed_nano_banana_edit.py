from .wavespeed_api.utils import imageurl2tensor
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedNanoBananaEdit:
    """
    Google Nano Banana Edit Node
    
    Google's state-of-the-art image generation and editing model
    """
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "prompt": ("STRING", {
                    "multiline": True, 
                    "default": "",
                    "tooltip": "The positive prompt for image generation"
                }),
                "image_url": ("STRING", {
                    "default": "",
                    "tooltip": "URL of input image for editing (or connect from Upload Image node)",
                    "forceInput": True
                }),
                "output_format": (["png", "jpeg"], {
                    "default": "png",
                    "tooltip": "Output format - use PNG for transparency support"
                }),
                "enable_sync_mode": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Wait for image generation to complete before returning"
                }),
            },
            "optional": {
                "additional_images": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Additional image URLs (one per line, max 9 additional)"
                }),
            }
        }
    
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    
    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"
    
    def execute(self, client, prompt, image_url, output_format="png", 
                enable_sync_mode=True, additional_images=""):
        """
        Execute the Google Nano Banana Edit model
        
        Args:
            client: WaveSpeed API client
            prompt: Text prompt for image generation
            image_url: Primary input image URL
            output_format: Output format (png or jpeg)
            enable_sync_mode: Whether to wait for completion
            additional_images: Additional image URLs (newline separated)
        
        Returns:
            Generated/edited image tensor
        """
        
        # Prepare the list of image URLs
        images = [image_url]
        
        # Add additional images if provided
        if additional_images and additional_images.strip():
            additional_urls = [url.strip() for url in additional_images.split('\n') 
                             if url.strip()]
            # Limit to 9 additional images (10 total max)
            images.extend(additional_urls[:9])
        
        # Prepare the request payload
        payload = {
            "prompt": prompt,
            "images": images,
            "output_format": output_format,
            "enable_sync_mode": enable_sync_mode,
            "enable_base64_output": False
        }
        
        # API endpoint for Google Nano Banana Edit
        endpoint = "/api/v3/google/nano-banana/edit"
        
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
            print(f"Error in Google Nano Banana Edit: {str(e)}")
            raise e


# Node registration
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedNanoBananaEdit": NSWaveSpeedNanoBananaEdit
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedNanoBananaEdit": "NS WaveSpeed Nano Banana Edit"
}