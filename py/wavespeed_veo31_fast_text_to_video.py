import time
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedVeo31FastTextToVideo:
    """
    Google VEO 3.1 Fast Text-to-Video Node

    Generates cinematic 1080p videos with natural motion and lighting.
    Processes up to 30% faster than standard model.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Text description of the desired video scene"
                }),
                "aspect_ratio": (["16:9", "9:16"], {
                    "default": "16:9",
                    "tooltip": "Video aspect ratio - 16:9 (landscape) or 9:16 (portrait)"
                }),
                "duration": ([4, 6, 8], {
                    "default": 8,
                    "tooltip": "Video duration in seconds"
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
                "negative_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Specify what to avoid in the generated video"
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

    def execute(self, client, prompt, aspect_ratio="16:9", duration=8, resolution="1080p",
                generate_audio=False, negative_prompt="", seed=-1, enable_sync_mode=False):
        """
        Execute the Google VEO 3.1 Fast Text-to-Video model

        Args:
            client: WaveSpeed API client
            prompt: Text description for video generation
            aspect_ratio: Video aspect ratio (16:9 or 9:16)
            duration: Video duration in seconds (4, 6, or 8)
            resolution: Output resolution (720p or 1080p)
            generate_audio: Whether to generate audio
            negative_prompt: Optional negative prompt
            seed: Random seed (-1 for random)
            enable_sync_mode: Whether to wait for completion

        Returns:
            Video URL string
        """

        # Create the actual client object from the client dict
        real_client = WaveSpeedClient(api_key=client["api_key"])

        # Build payload with all parameters
        payload = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "duration": duration,
            "resolution": resolution,
            "generate_audio": generate_audio
        }

        # Add optional parameters if provided
        if negative_prompt and negative_prompt.strip():
            payload["negative_prompt"] = negative_prompt.strip()

        if seed != -1:
            payload["seed"] = seed

        # API endpoint
        endpoint = "/api/v3/google/veo3.1-fast/text-to-video"

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
            print(f"Error in Google VEO 3.1 Fast Text-to-Video: {str(e)}")
            raise e


# Node registration
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedVeo31FastTextToVideo": NSWaveSpeedVeo31FastTextToVideo
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedVeo31FastTextToVideo": "NS WaveSpeed VEO 3.1 Fast Text to Video"
}
