import time
from .wavespeed_api.utils import imageurl2tensor
from .wavespeed_api.client import WaveSpeedClient


class NSWaveSpeedNanoBananaTextToImage:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "client": ("WAVESPEED_AI_API_CLIENT",),
                "prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Text description of the image to generate"
                }),
                "seed": ("INT", {
                    "default": -1,
                    "min": -1,
                    "max": 0xffffffffffffffff,
                    "control_after_generate": True,
                    "tooltip": "Random seed for reproducible results. -1 for random seed"
                }),
                "output_format": (["jpeg", "png", "webp"], {
                    "default": "png",
                    "tooltip": "The format of the output image"
                }),
                "enable_sync_mode": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Wait for generation to complete before returning"
                }),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("output_image",)
    CATEGORY = "neuralsins/WaveSpeed"
    FUNCTION = "execute"

    def execute(self, client, prompt, seed, output_format, enable_sync_mode):
        real_client = WaveSpeedClient(api_key=client["api_key"])
        
        payload = {
            "enable_base64_output": False,
            "enable_sync_mode": enable_sync_mode,
            "output_format": output_format,
            "prompt": prompt
        }
        
        if seed != -1:
            payload["seed"] = seed

        endpoint = "/api/v3/google/nano-banana/text-to-image"
        
        try:
            response = real_client.post(endpoint, payload, timeout=real_client.once_timeout)
            
            if enable_sync_mode:
                if "outputs" in response and response["outputs"]:
                    image_urls = response["outputs"]
                    return (imageurl2tensor(image_urls),)
                else:
                    raise Exception(f"No output received from sync API. Response: {response}")
            else:
                task_id = response["id"]
                print(f"Task submitted successfully. Request ID: {task_id}")
                
                try:
                    result = real_client.wait_for_task(task_id, polling_interval=1, timeout=300)
                    
                    if "outputs" in result and result["outputs"]:
                        image_urls = result["outputs"]
                        return (imageurl2tensor(image_urls),)
                    else:
                        raise Exception("Task completed but no output received")
                        
                except Exception as e:
                    raise Exception(f"Async task failed: {str(e)}")
                
        except Exception as e:
            print(f"Error in {self.__class__.__name__}: {str(e)}")
            raise e


NODE_CLASS_MAPPINGS = {
    "NSWaveSpeedNanoBananaTextToImage": NSWaveSpeedNanoBananaTextToImage
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWaveSpeedNanoBananaTextToImage": "NS WaveSpeed Nano Banana Text to Image"
}