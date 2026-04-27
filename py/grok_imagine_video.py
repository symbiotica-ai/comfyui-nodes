# ABOUTME: Grok Imagine Video generation node for text-to-video and video editing
# Supports video generation from text, images, and video editing

from .grok_api.client import GrokClient
from .grok_api.utils import videourl_to_path


class NSGrokImagineVideo:
    """
    Grok Imagine Video - Text/Image to Video & Video Editing
    
    Generate videos from text prompts, animate images, or edit existing videos
    using xAI's Grok Imagine video generation model.
    
    Pricing: Varies by duration and resolution (see xAI pricing page)
    """
    
    # Aspect ratio options
    ASPECT_RATIOS = [
        "16:9",
        "4:3",
        "1:1",
        "9:16",
        "3:4",
        "3:2",
        "2:3",
    ]
    
    # Resolution options
    RESOLUTIONS = ["720p", "480p"]
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("GROK_API_CLIENT",),
                "prompt": (
                    "STRING",
                    {
                        "multiline": True,
                        "default": "",
                        "tooltip": "Text description of the video to generate or edit instruction",
                    },
                ),
                "duration": (
                    "INT",
                    {
                        "default": 5,
                        "min": 1,
                        "max": 15,
                        "step": 1,
                        "tooltip": "Video duration in seconds (1-15). Not used for video editing.",
                    },
                ),
                "aspect_ratio": (
                    s.ASPECT_RATIOS,
                    {
                        "default": "16:9",
                        "tooltip": "Aspect ratio of the generated video",
                    },
                ),
                "resolution": (
                    s.RESOLUTIONS,
                    {
                        "default": "720p",
                        "tooltip": "Output resolution (720p or 480p)",
                    },
                ),
            },
            "optional": {
                "image_url": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Optional: Image URL to animate (leave empty for text-to-video)",
                    },
                ),
                "video_url": (
                    "STRING",
                    {
                        "default": "",
                        "tooltip": "Optional: Video URL to edit (max 8.7s, overrides image_url)",
                    },
                ),
            }
        }
    
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_path",)
    CATEGORY = "neuralsins/Grok"
    FUNCTION = "execute"
    
    def execute(
        self,
        client,
        prompt,
        duration,
        aspect_ratio,
        resolution,
        image_url="",
        video_url="",
    ):
        """
        Execute Grok Imagine video generation or editing
        
        Args:
            client: Grok API client
            prompt: Text prompt or edit instruction
            duration: Video duration in seconds
            aspect_ratio: Video aspect ratio
            resolution: Output resolution
            image_url: Optional image URL to animate
            video_url: Optional video URL to edit
            
        Returns:
            Local path to the generated video file
        """
        real_client = GrokClient(api_key=client["api_key"])
        
        payload = {
            "model": "grok-imagine-video",
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        }
        
        # Determine mode: video editing, image-to-video, or text-to-video
        if video_url and video_url.strip():
            payload["video_url"] = video_url.strip()
            mode = "video editing"
            # Duration is not used for video editing
        elif image_url and image_url.strip():
            payload["image_url"] = image_url.strip()
            payload["duration"] = duration
            mode = "image-to-video"
        else:
            payload["duration"] = duration
            mode = "text-to-video"
        
        endpoint = "/v1/videos/generations"
        
        try:
            print(f"Starting {mode} generation with grok-imagine-video...")
            response = real_client.post(endpoint, payload, timeout=30)
            
            # Get request ID for polling
            if "request_id" in response:
                request_id = response["request_id"]
                print(f"Video generation started. Request ID: {request_id}")
                
                # Poll for completion
                result = real_client.wait_for_video(
                    request_id,
                    polling_interval=5,
                    timeout=600
                )
                
                # Extract video URL from result
                video_result_url = None
                if "url" in result:
                    video_result_url = result["url"]
                elif "data" in result and isinstance(result["data"], dict) and "url" in result["data"]:
                    video_result_url = result["data"]["url"]
                elif "data" in result and isinstance(result["data"], list) and len(result["data"]) > 0:
                    video_result_url = result["data"][0].get("url")
                
                if video_result_url:
                    print(f"Video generation completed: {video_result_url}")
                    
                    # Download video and return local path
                    video_path = videourl_to_path(video_result_url)
                    return (video_path,)
                else:
                    raise Exception(f"No video URL in result. Response: {result}")
            else:
                raise Exception(f"No request_id in response. Response: {response}")
                
        except Exception as e:
            print(f"Error in Grok Imagine Video: {str(e)}")
            raise e


NODE_CLASS_MAPPINGS = {"NSGrokImagineVideo": NSGrokImagineVideo}

NODE_DISPLAY_NAME_MAPPINGS = {"NSGrokImagineVideo": "NS Grok Imagine Video"}
