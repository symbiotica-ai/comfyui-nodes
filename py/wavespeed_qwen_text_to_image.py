import time
from .wavespeed_api.utils import imageurl2tensor
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedQwenTextToImage:
    """
    Qwen Image Text-to-Image Node
    
    Qwen-Image — a 20B MMDiT model for next-gen text-to-image generation.
    """
    
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
                "prompt": ("STRING", {
                    "multiline": True, 
                    "default": "",
                    "tooltip": "Text prompt for image generation (supports Chinese & English)"
                }),
                "size": (s.SIZES, {
                    "default": "1328x1328 (1:1)",
                    "tooltip": "The aspect ratio and resolution of the generated image"
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
                "custom_size": ("STRING", {
                    "default": "",
                    "tooltip": "Custom size as 'width*height' (e.g. '1920*1080'). Overrides size dropdown if provided."
                }),
            }
        }
    
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    
    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"
    
    def execute(self, client, prompt, size="1328x1328 (1:1)", seed=-1,
                output_format="jpeg", enable_sync_mode=True, custom_size=""):
        """
        Execute the Qwen Image Text-to-Image model
        
        Args:
            client: WaveSpeed API client
            prompt: Text prompt for image generation
            size: Image size from dropdown (aspect ratio preset)
            seed: Random seed (-1 for random)
            output_format: Output format (jpeg, png, or webp)
            enable_sync_mode: Whether to wait for completion
            custom_size: Optional custom size override
        
        Returns:
            Generated image tensor
        """
        
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
        
        # Prepare the request payload
        payload = {
            "prompt": prompt,
            "size": final_size,
            "seed": seed,
            "output_format": output_format,
            "enable_sync_mode": enable_sync_mode,
            "enable_base64_output": False
        }
        
        # API endpoint for Qwen Image Text-to-Image
        endpoint = "/api/v3/wavespeed-ai/qwen-image/text-to-image"
        
        try:
            # Create the actual client object from the client dict
            real_client = WaveSpeedClient(api_key=client["api_key"])
            
            # Make the API request
            response = real_client.post(endpoint, payload, timeout=real_client.once_timeout)
            
            # Handle sync mode response
            if enable_sync_mode:
                # WaveSpeedClient already extracts the 'data' field, so response is the actual data
                if "outputs" in response and response["outputs"]:
                    image_urls = response["outputs"]
                    print(f"Sync mode completed. URLs: {image_urls}")
                    # Pass the full URLs array like original nodes do
                    return (imageurl2tensor(image_urls),)
                else:
                    raise Exception(f"No output received from sync API. Response: {response}")
            
            # Handle async mode response
            else:
                # Extract task ID from response (WaveSpeedClient already extracted 'data')
                if "id" not in response:
                    raise Exception(f"No task ID received from API. Response: {response}")
                
                task_id = response["id"]
                print(f"Task submitted successfully. Request ID: {task_id}")
                
                # Use the client's wait_for_task method which handles polling correctly
                try:
                    result = real_client.wait_for_task(task_id, polling_interval=1, timeout=300)
                    
                    if "outputs" in result and result["outputs"]:
                        image_urls = result["outputs"]
                        print(f"Task completed. URLs: {image_urls}")
                        # Pass the full URLs array like original nodes do
                        return (imageurl2tensor(image_urls),)
                    else:
                        raise Exception("Task completed but no output received")
                        
                except Exception as e:
                    raise Exception(f"Async task failed: {str(e)}")
        
        except Exception as e:
            print(f"Error in Qwen Image Text-to-Image: {str(e)}")
            raise e


# Node registration
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedQwenTextToImage": NSWaveSpeedQwenTextToImage
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WaveSpeedAI Qwen Image Text to Image": "WaveSpeedAI Qwen Image Text-to-Image"
}