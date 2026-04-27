# ABOUTME: Grok Imagine Image generation node for text-to-image and image editing
# Supports multiple models and aspect ratios

from .grok_api.client import GrokClient
from .grok_api.utils import imageurl2tensor


class NSGrokImagineImage:
    """
    Grok Imagine Image - Text to Image & Image Editing
    
    Generate images from text prompts or edit existing images using xAI's Grok Imagine models.
    Supports multiple aspect ratios and high-quality image generation.
    
    Pricing: Varies by model (see xAI pricing page)
    """
    
    # Model options
    MODELS = [
        "grok-imagine-image-pro",
        "grok-imagine-image",
        "grok-2-image-1212",
    ]
    
    # Aspect ratio options
    ASPECT_RATIOS = [
        "1:1",
        "16:9",
        "9:16",
        "4:3",
        "3:4",
        "3:2",
        "2:3",
        "2:1",
        "1:2",
        "19.5:9",
        "9:19.5",
        "20:9",
        "9:20",
    ]
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("GROK_API_CLIENT",),
                "model": (
                    s.MODELS,
                    {
                        "default": "grok-imagine-image",
                        "tooltip": "Model to use for generation",
                    },
                ),
                "prompt": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": "Text description of the image to generate or edit instruction",
                    },
                ),
                "aspect_ratio": (
                    s.ASPECT_RATIOS,
                    {
                        "default": "1:1",
                        "tooltip": "Aspect ratio of the generated image",
                    },
                ),
                "num_images": (
                    "INT",
                    {
                        "default": 1,
                        "min": 1,
                        "max": 10,
                        "step": 1,
                        "tooltip": "Number of images to generate (1-10)",
                    },
                ),
            },
            "optional": {
                "image_url": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Optional: Image URL for editing (leave empty for text-to-image)",
                    },
                ),
            }
        }
    
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("output_image",)
    CATEGORY = "neuralsins/Grok"
    FUNCTION = "execute"
    
    def execute(
        self,
        client,
        model,
        prompt,
        aspect_ratio,
        num_images,
        image_url="",
    ):
        """
        Execute Grok Imagine image generation or editing
        
        Args:
            client: Grok API client
            model: Model to use
            prompt: Text prompt or edit instruction
            aspect_ratio: Image aspect ratio
            num_images: Number of images to generate
            image_url: Optional image URL for editing
            
        Returns:
            Generated or edited image tensor
        """
        real_client = GrokClient(api_key=client["api_key"])
        
        payload = {
            "model": model,
            "prompt": prompt,
            "n": num_images,
            "aspect_ratio": aspect_ratio,
        }
        
        # Add image URL if provided (for editing)
        if image_url and image_url.strip():
            payload["image_url"] = image_url.strip()
        
        endpoint = "/v1/images/generations"
        
        try:
            print(f"Generating {num_images} image(s) with {model}...")
            response = real_client.post(endpoint, payload, timeout=120)
            
            # Extract image URLs from response
            if "data" in response and response["data"]:
                image_urls = [img["url"] for img in response["data"] if "url" in img]
                
                if image_urls:
                    print(f"Generated {len(image_urls)} image(s)")
                    return (imageurl2tensor(image_urls),)
                else:
                    raise Exception("No image URLs in response")
            else:
                raise Exception(f"No data received from API. Response: {response}")
                
        except Exception as e:
            print(f"Error in Grok Imagine Image: {str(e)}")
            raise e


NODE_CLASS_MAPPINGS = {"NSGrokImagineImage": NSGrokImagineImage}

NODE_DISPLAY_NAME_MAPPINGS = {"NSGrokImagineImage": "NS Grok Imagine Image"}
