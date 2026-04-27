import time
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedRunwayUpscale:
    """
    WaveSpeed AI RunwayML Upscale V1 Node

    Enhanced video upscaling using RunwayML's advanced AI models.
    Improves video resolution and quality while preserving content integrity.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "video_url": ("STRING", {
                    "default": "",
                    "tooltip": "URL of input video for upscaling (connect from Upload Video node)",
                    "forceInput": True
                }),
                "enable_sync_mode": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Wait for upscaling to complete before returning"
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("upscaled_video_url",)
    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"

    def execute(self, client, video_url, enable_sync_mode):
        # Create the actual client object from the client dict
        real_client = WaveSpeedClient(api_key=client["api_key"])

        # Build payload
        payload = {
            "video": video_url
        }

        # API endpoint
        endpoint = "/api/v3/runwayml/upscale-v1"

        try:
            print(f"Submitting RunwayML Upscale V1 task...")
            print(f"Video URL: {video_url[:50]}...")

            response = real_client.post(endpoint, payload, timeout=real_client.once_timeout)

            if enable_sync_mode:
                # In sync mode, wait for the result
                if "outputs" in response and response["outputs"]:
                    video_urls = response["outputs"]  # Already a list
                    print(f"Task completed successfully. Received {len(video_urls)} video(s)")
                    # Return the first video URL
                    video_url = video_urls[0]
                    return (video_url,)
                else:
                    raise Exception(f"No output received from sync API. Response: {response}")
            else:
                # In async mode, submit task and poll for results
                task_id = response["id"]
                print(f"Task submitted successfully. Request ID: {task_id}")

                try:
                    # Poll for task completion - longer timeout for upscaling
                    result = real_client.wait_for_task(task_id, polling_interval=2, timeout=600)

                    if "outputs" in result and result["outputs"]:
                        video_urls = result["outputs"]  # Already a list
                        print(f"Task completed successfully. Received {len(video_urls)} video(s)")
                        # Return the first video URL
                        video_url = video_urls[0]
                        return (video_url,)
                    else:
                        raise Exception(f"Task completed but no output received. Response: {result}")

                except Exception as e:
                    raise Exception(f"Async task failed: {str(e)}")

        except Exception as e:
            print(f"Error in RunwayML Upscale V1: {str(e)}")
            raise e

# Add the mappings that your __init__.py file will automatically find
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedRunwayUpscale": NSWaveSpeedRunwayUpscale
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WaveSpeedAI_RunwaymlUpscaleV1Node": "WaveSpeedAI RunwayML Upscale V1"
}