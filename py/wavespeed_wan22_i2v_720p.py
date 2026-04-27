import time
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedWan22I2V720p:
    """
    WaveSpeed AI Wan 2.2 I2V 720p Node

    Advanced image-to-video generation model that creates high-quality 720p videos
    from still images. Features enhanced motion modeling and temporal consistency
    with support for both short and medium duration outputs.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "image_url": ("STRING", {
                    "default": "",
                    "tooltip": "URL of input image for video generation (connect from Upload Image node)",
                    "forceInput": True
                }),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Text prompt describing the desired motion and content"
                }),
                "duration": ([5, 8], {
                    "default": 5,
                    "tooltip": "Duration of the generated video in seconds (5 or 8)"
                }),
                "enable_sync_mode": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Wait for generation to complete before returning"
                }),
            },
            "optional": {
                "negative_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Negative text prompt of what to avoid in the generation"
                }),
                "last_image_url": ("STRING", {
                    "default": "",
                    "tooltip": "Optional URL of an image to guide the end of the video (connect from Upload Image node)",
                    "forceInput": True
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

    def execute(self, client, image_url, prompt, duration, enable_sync_mode,
                negative_prompt="", last_image_url="", seed=-1):
        # Create the actual client object from the client dict
        real_client = WaveSpeedClient(api_key=client["api_key"])

        # Build payload
        payload = {
            "image": image_url,
            "prompt": prompt,
            "duration": duration,
            "seed": seed
        }

        # Add optional parameters if provided
        if negative_prompt and negative_prompt.strip():
            payload["negative_prompt"] = negative_prompt.strip()

        if last_image_url and last_image_url.strip():
            payload["last_image"] = last_image_url.strip()

        # API endpoint
        endpoint = "/api/v3/wavespeed-ai/wan-2.2/i2v-720p"

        try:
            print(f"Submitting WAN 2.2 I2V 720p task...")
            print(f"Duration: {duration} seconds")
            print(f"Seed: {seed}")
            if prompt:
                print(f"Prompt: {prompt[:100]}...")

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
                    # Poll for task completion - longer timeout for video generation
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
            print(f"Error in WAN 2.2 I2V 720p: {str(e)}")
            raise e

# Add the mappings that your __init__.py file will automatically find
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedWan22I2V720p": NSWaveSpeedWan22I2V720p
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "WaveSpeedAI_Wan22I2V720pNode": "WaveSpeedAI Wan2.2 I2V 720p"
}