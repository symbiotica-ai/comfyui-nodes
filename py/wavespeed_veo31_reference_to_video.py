import time
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedVeo31ReferenceToVideo:
    """
    Google VEO 3.1 Reference-to-Video Node

    Generates videos with consistent subject appearance across frames.
    Supports 1-3 reference images to maintain character/object consistency.
    Ideal for character-driven narratives and branded content.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Text description for video generation with subject consistency"
                }),
                "image_1": ("STRING", {
                    "default": "",
                    "tooltip": "First reference image URL (required) - connect from Upload Image node. PNG/JPEG/JPG/WebP, min 128x128px, max 50MB",
                    "forceInput": True
                }),
                "resolution": (["720p", "1080p"], {
                    "default": "1080p",
                    "tooltip": "Video output resolution"
                }),
                "generate_audio": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Generate native audio synchronized with the video"
                }),
            },
            "optional": {
                "image_2": ("STRING", {
                    "default": "",
                    "tooltip": "Second reference image URL (optional) for additional subject reference"
                }),
                "image_3": ("STRING", {
                    "default": "",
                    "tooltip": "Third reference image URL (optional) for additional subject reference"
                }),
                "negative_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Specify elements to avoid in the generated video"
                }),
                "seed": ("INT", {
                    "default": -1,
                    "min": -1,
                    "max": 2147483647,
                    "control_after_generate": True,
                    "tooltip": "Random seed for reproducible results. -1 for random seed"
                }),
                "enable_sync_mode": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Wait for generation to complete before returning"
                })
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_url",)
    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"

    def execute(self, client, prompt, image_1, resolution="1080p", generate_audio=False,
                image_2="", image_3="", negative_prompt="", seed=-1, enable_sync_mode=False):
        """
        Execute the Google VEO 3.1 Reference-to-Video model

        Args:
            client: WaveSpeed API client
            prompt: Text description for video generation
            image_1: First reference image URL (required)
            resolution: Output resolution (720p or 1080p)
            generate_audio: Whether to generate audio
            image_2: Second reference image URL (optional)
            image_3: Third reference image URL (optional)
            negative_prompt: Optional negative prompt
            seed: Random seed (-1 for random)
            enable_sync_mode: Whether to wait for completion

        Returns:
            Video URL string
        """

        # Create the actual client object from the client dict
        real_client = WaveSpeedClient(api_key=client["api_key"])

        # Build images array (1-3 images)
        images = [image_1]
        if image_2 and image_2.strip():
            images.append(image_2.strip())
        if image_3 and image_3.strip():
            images.append(image_3.strip())

        # Build payload with all parameters
        payload = {
            "prompt": prompt,
            "images": images,
            "resolution": resolution,
            "generate_audio": generate_audio
        }

        # Add optional parameters if provided
        if negative_prompt and negative_prompt.strip():
            payload["negative_prompt"] = negative_prompt.strip()

        if seed != -1:
            payload["seed"] = seed

        # API endpoint
        endpoint = "/api/v3/google/veo3.1/reference-to-video"

        try:
            response = real_client.post(endpoint, payload, timeout=real_client.once_timeout)

            if enable_sync_mode:
                # For sync mode, response should contain outputs directly
                if "outputs" in response and response["outputs"]:
                    video_url = response["outputs"][0]
                    print(f"Video generation completed. URL: {video_url}")
                    return (video_url,)
                else:
                    raise Exception(f"No output received from sync API. Response: {response}")
            else:
                # For async mode, get task ID and poll for results
                task_id = response["id"]
                print(f"Video generation task submitted. Request ID: {task_id}")
                print(f"This may take several minutes to complete...")

                try:
                    print(f"Waiting for video generation to complete (task ID: {task_id})...")
                    result = real_client.wait_for_task(task_id, polling_interval=2, timeout=1800)  # 30 minutes

                    if "outputs" in result and result["outputs"]:
                        video_url = result["outputs"][0]
                        print(f"Video generation completed. URL: {video_url}")
                        return (video_url,)
                    else:
                        raise Exception("Task completed but no output received")

                except Exception as e:
                    raise Exception(f"Async task failed: {str(e)}")

        except Exception as e:
            print(f"Error in Google VEO 3.1 Reference-to-Video: {str(e)}")
            raise e


# Node registration
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedVeo31ReferenceToVideo": NSWaveSpeedVeo31ReferenceToVideo
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedVeo31ReferenceToVideo": "NS WaveSpeed VEO 3.1 Reference to Video"
}
