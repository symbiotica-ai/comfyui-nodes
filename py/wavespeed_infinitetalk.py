import time
from .wavespeed_api.utils import imageurl2tensor
from .wavespeed_api.client import WaveSpeedClient


class NSWaveSpeedInfiniteTalk:
    """
    WaveSpeed AI InfiniteTalk Node

    Audio-driven conversational AI video generation model that creates talking or singing videos
    from a single image and audio input. Features accurate lip synchronization, head movement
    alignment, and facial expression matching with the audio.

    Unlike traditional dubbing methods, InfiniteTalk enables infinite-length video generation
    with consistent identity preservation and instruction following capabilities.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "audio": ("STRING", {
                    "default": "",
                    "tooltip": "Audio file URL for generating lip-synced output (connect from Upload Audio node)",
                    "forceInput": True
                }),
                "image": ("STRING", {
                    "default": "",
                    "tooltip": "Image to animate (connect from Upload Image node)",
                    "forceInput": True
                }),
                "resolution": (["480p", "720p"], {
                    "default": "720p",
                    "tooltip": "Output video resolution (480p: $0.15 per 5 seconds, 720p: $0.3 per 5 seconds)"
                }),
                "enable_sync_mode": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Wait for video generation to complete before returning"
                }),
            },
            "optional": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Optional generation instructions to control scene, pose, and behavior while maintaining audio synchronization"
                }),
                "mask_image": ("STRING", {
                    "default": "",
                    "tooltip": "Optional mask image URL to specify which person to animate (connect from Upload Image node)",
                    "forceInput": True
                }),
                "seed": ("INT", {
                    "default": -1,
                    "min": -1,
                    "max": 2147483647,
                    "control_after_generate": True,
                    "tooltip": "Random seed for reproducible results. -1 for random seed"
                }),
                "enable_base64_output": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Enable base64 output format"
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_url",)
    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"

    def execute(self, client, audio, image, resolution, enable_sync_mode,
                prompt="", mask_image="", seed=-1, enable_base64_output=False):
        """
        Execute the InfiniteTalk model

        Args:
            client: WaveSpeed API client
            audio: Audio file URL for lip-sync generation
            image: Image URL to animate
            resolution: Output video resolution (480p or 720p)
            enable_sync_mode: Whether to wait for completion
            prompt: Optional generation instructions
            mask_image: Optional mask to specify person to animate
            seed: Random seed (-1 for random)
            enable_base64_output: Whether to enable base64 output

        Returns:
            Video URL as string
        """

        # Create the actual client object from the client dict
        real_client = WaveSpeedClient(api_key=client["api_key"])

        # Build payload
        payload = {
            "audio": audio,
            "image": image,
            "resolution": resolution,
            "enable_sync_mode": enable_sync_mode,
            "enable_base64_output": enable_base64_output,
        }

        # Add optional parameters if provided
        if prompt and prompt.strip():
            payload["prompt"] = prompt.strip()

        if mask_image and mask_image.strip():
            payload["mask_image"] = mask_image.strip()

        # Add seed if not random
        if seed != -1:
            payload["seed"] = seed

        # API endpoint for InfiniteTalk
        endpoint = "/api/v3/wavespeed-ai/infinitetalk"

        try:
            response = real_client.post(endpoint, payload, timeout=real_client.once_timeout)

            if enable_sync_mode:
                # In sync mode, we get the results directly
                if "outputs" in response and response["outputs"]:
                    # InfiniteTalk returns video URLs, take the first one
                    video_url = response["outputs"][0]
                    return (video_url,)
                else:
                    raise Exception(f"No output received from sync API. Response: {response}")
            else:
                # In async mode, we need to poll for results
                task_id = response["id"]
                print(f"InfiniteTalk task submitted successfully. Request ID: {task_id}")
                print("Note: Video generation may take several minutes depending on audio length and resolution.")

                try:
                    # Wait for task to complete - longer timeout for video generation
                    result = real_client.wait_for_task(task_id, polling_interval=2, timeout=1200)  # 20 minutes timeout

                    if "outputs" in result and result["outputs"]:
                        # Take the first video URL from outputs
                        video_url = result["outputs"][0]
                        return (video_url,)
                    else:
                        raise Exception("Task completed but no output received")

                except Exception as e:
                    raise Exception(f"Async task failed: {str(e)}")

        except Exception as e:
            print(f"Error in InfiniteTalk: {str(e)}")
            raise e


# Node registration - REQUIRED
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedInfiniteTalk": NSWaveSpeedInfiniteTalk
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedInfiniteTalk": "NS WaveSpeed InfiniteTalk"
}