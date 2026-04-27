import time
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedSora2ImageToVideoPro:
    """
    OpenAI Sora 2 Image-to-Video Pro Node

    Professional-grade image-to-video with higher resolutions (720p/1080p).
    Preserves image identity, lighting, and composition while generating physics-aware motion.
    Supports cinematic camera movements and optional synchronized audio.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "image": ("STRING", {
                    "default": "",
                    "tooltip": "Reference image URL for video generation (PNG/JPEG) - connect from Upload Image node",
                    "forceInput": True
                }),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Describe the mood, motion style, or camera behavior for video generation"
                }),
                "resolution": (["720p", "1080p"], {
                    "default": "720p",
                    "tooltip": "Video output resolution - 720p or 1080p (higher cost)"
                }),
                "duration": ([4, 8, 12], {
                    "default": 4,
                    "tooltip": "Video duration in seconds (720p: 4s=$1.20, 8s=$2.40, 12s=$3.60 | 1080p: 4s=$2.00, 8s=$4.00, 12s=$6.00)"
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

    def execute(self, client, image, prompt, resolution="720p", duration=4, enable_sync_mode=False):
        """
        Execute the OpenAI Sora 2 Image-to-Video Pro model

        Args:
            client: WaveSpeed API client
            image: Reference image URL
            prompt: Motion and mood description for video generation
            resolution: Output resolution (720p or 1080p)
            duration: Video duration in seconds (4, 8, or 12)
            enable_sync_mode: Whether to wait for completion

        Returns:
            Video URL string
        """

        # Create the actual client object from the client dict
        real_client = WaveSpeedClient(api_key=client["api_key"])

        # Build payload with all parameters
        payload = {
            "prompt": prompt,
            "image": image,
            "resolution": resolution,
            "duration": duration
        }

        # API endpoint
        endpoint = "/api/v3/openai/sora-2/image-to-video-pro"

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
            print(f"Error in OpenAI Sora 2 Image-to-Video Pro: {str(e)}")
            raise e


# Node registration
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedSora2ImageToVideoPro": NSWaveSpeedSora2ImageToVideoPro
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedSora2ImageToVideoPro": "NS WaveSpeed Sora 2 Image to Video Pro"
}
