import time
from .wavespeed_api.client import WaveSpeedClient

class NSWaveSpeedWan25TextToVideoFast:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Text description for video generation"
                }),
                "size": (["1280*720", "720*1280", "1920*1080", "1080*1920"], {
                    "default": "1280*720",
                    "tooltip": "Video resolution (width*height)"
                })
            },
            "optional": {
                "negative_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Describe what you don't want in the video"
                }),
                "audio": ("STRING", {
                    "default": "",
                    "tooltip": "Audio URL to guide video generation (3-30 seconds, wav/mp3, ≤15MB)"
                }),
                "duration": ([5, 10], {
                    "default": 5,
                    "tooltip": "Video duration in seconds"
                }),
                "enable_prompt_expansion": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Automatically expand and enhance the prompt"
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

    def execute(self, client, prompt, size, negative_prompt="", audio="", duration=5,
                enable_prompt_expansion=False, seed=-1, enable_sync_mode=False):
        # Create the actual client object from the client dict
        real_client = WaveSpeedClient(api_key=client["api_key"])

        # Build payload with all parameters from documentation
        payload = {
            "prompt": prompt,
            "size": size,
            "duration": duration,
            "enable_prompt_expansion": enable_prompt_expansion,
            "seed": seed
        }

        # Add optional parameters if provided
        if negative_prompt and negative_prompt.strip():
            payload["negative_prompt"] = negative_prompt.strip()

        if audio and audio.strip():
            payload["audio"] = audio.strip()

        # API endpoint for fast version
        endpoint = "/api/v3/alibaba/wan-2.5/text-to-video-fast"

        try:
            response = real_client.post(endpoint, payload, timeout=real_client.once_timeout)

            if enable_sync_mode:
                # For sync mode, response should contain outputs directly
                if "outputs" in response and response["outputs"]:
                    video_url = response["outputs"][0]
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
            print(f"Error in {self.__class__.__name__}: {str(e)}")
            raise e

# Node registration
NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedWan25TextToVideoFast": NSWaveSpeedWan25TextToVideoFast
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedWan25TextToVideoFast": "NS WaveSpeed Wan 2.5 Text to Video Fast"
}