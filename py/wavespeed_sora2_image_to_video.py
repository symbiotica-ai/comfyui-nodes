import time
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedSora2ImageToVideo:
    """
    OpenAI Sora 2 Image-to-Video Node

    Transforms static images into dynamic videos with physics-aware motion.
    Preserves image identity, lighting, and composition while adding cinematic camera movements.
    Pricing: $0.10 per second.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "image": ("STRING", {
                    "default": "",
                    "tooltip": "Source image URL for video generation (connect from Upload Image node)",
                    "forceInput": True
                }),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Positive prompt guiding video generation - describe desired motion and characteristics"
                }),
                "duration": ([4, 8, 12], {
                    "default": 4,
                    "tooltip": "Video duration in seconds (4s=$0.40, 8s=$0.80, 12s=$1.20)"
                }),
            },
            "optional": {
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

    def execute(self, client, image, prompt, duration=4, enable_sync_mode=False):
        """
        Execute the OpenAI Sora 2 Image-to-Video model

        Args:
            client: WaveSpeed API client
            image: Source image URL
            prompt: Motion and characteristic description for video generation
            duration: Video duration in seconds (4, 8, or 12)
            enable_sync_mode: Whether to wait for completion

        Returns:
            Video URL string
        """

        # Create the actual client object from the client dict
        real_client = WaveSpeedClient(api_key=client["api_key"])

        # Build payload with all parameters
        payload = {
            "image": image,
            "prompt": prompt,
            "duration": duration
        }

        # API endpoint
        endpoint = "/api/v3/openai/sora-2/image-to-video"

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
            print(f"Error in OpenAI Sora 2 Image-to-Video: {str(e)}")
            raise e


# Node registration
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedSora2ImageToVideo": NSWaveSpeedSora2ImageToVideo
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedSora2ImageToVideo": "NS WaveSpeed Sora 2 Image to Video"
}
