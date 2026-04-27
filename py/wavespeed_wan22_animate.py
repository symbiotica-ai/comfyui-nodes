import time
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedWan22Animate:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "image_url": ("STRING", {
                    "default": "",
                    "tooltip": "URL of input image for generating output (connect from Upload Image node)",
                    "forceInput": True
                }),
                "video_url": ("STRING", {
                    "default": "",
                    "tooltip": "URL of input video for generating output (connect from Upload Video node)",
                    "forceInput": True
                }),
                "resolution": (["480p", "720p"], {
                    "default": "480p",
                    "tooltip": "Output video resolution. 480p costs $0.25 per 5 seconds, 720p costs $0.50 per 5 seconds"
                }),
                "enable_sync_mode": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Wait for generation to complete before returning"
                }),
            },
            "optional": {
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Additional generation guidance for the animation"
                }),
                "seed": ("INT", {
                    "default": -1,
                    "min": -1,
                    "max": 2147483647,
                    "control_after_generate": True,
                    "tooltip": "Random seed for reproducible results. -1 for random seed"
                }),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_url",)
    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"

    def execute(self, client, image_url, video_url, resolution, enable_sync_mode, prompt="", seed=-1):
        # Create the actual client object from the client dict
        real_client = WaveSpeedClient(api_key=client["api_key"])

        # Build payload
        payload = {
            "image": image_url,
            "video": video_url,
            "resolution": resolution,
            "seed": seed
        }

        # Add prompt if provided
        if prompt and prompt.strip():
            payload["prompt"] = prompt.strip()

        # API endpoint
        endpoint = "/api/v3/wavespeed-ai/wan-2.2/animate"

        try:
            print(f"Submitting WAN 2.2 Animate task...")
            print(f"Resolution: {resolution}")
            print(f"Seed: {seed}")
            if prompt:
                print(f"Prompt: {prompt[:100]}...")

            response = real_client.post(endpoint, payload, timeout=real_client.once_timeout)

            if enable_sync_mode:
                # In sync mode, wait for the result
                if "outputs" in response and response["outputs"]:
                    video_urls = response["outputs"]  # Already a list
                    print(f"Task completed successfully. Received {len(video_urls)} video(s)")
                    # Return the first video URL like other WaveSpeed video nodes
                    video_url = video_urls[0]
                    return (video_url,)
                else:
                    raise Exception(f"No output received from sync API. Response: {response}")
            else:
                # In async mode, submit task and poll for results
                task_id = response["id"]
                print(f"Task submitted successfully. Request ID: {task_id}")

                try:
                    # Poll for task completion
                    result = real_client.wait_for_task(task_id, polling_interval=2, timeout=600)

                    if "outputs" in result and result["outputs"]:
                        video_urls = result["outputs"]  # Already a list
                        print(f"Task completed successfully. Received {len(video_urls)} video(s)")
                        # Return the first video URL like other WaveSpeed video nodes
                        video_url = video_urls[0]
                        return (video_url,)
                    else:
                        raise Exception(f"Task completed but no output received. Response: {result}")

                except Exception as e:
                    raise Exception(f"Async task failed: {str(e)}")

        except Exception as e:
            print(f"Error in WaveSpeedAI WAN 2.2 Animate: {str(e)}")
            raise e

# Node registration - REQUIRED
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedWan22Animate": NSWaveSpeedWan22Animate
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedWan22Animate": "NS WaveSpeed Wan 2.2 Animate"
}