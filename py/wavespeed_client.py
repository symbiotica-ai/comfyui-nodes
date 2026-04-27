import configparser
import os

from .wavespeed_api.client import WaveSpeedClient


class NSWaveSpeedClient:
    """
    WaveSpeed AI API Client Node

    This node creates a client for connecting to the WaveSpeed AI API.
    """

    def __init__(self):
        pass

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "api_key": ("STRING", {"multiline": False, "default": ""}),
            },
        }

    RETURN_TYPES = ("WAVESPEED_AI_API_CLIENT",)
    RETURN_NAMES = ("client",)

    FUNCTION = "create_client"

    CATEGORY = "neuralsins/WaveSpeed"

    def create_client(self, api_key):
        """
        Create a WaveSpeed AI API client

        Args:
            api_key: WaveSpeed AI API key

        Returns:
            WaveSpeedAPI: WaveSpeed AI API client
        """
        wavespeed_api_key = ""

        if api_key == "":
            # Try to read from config.ini
            try:
                current_dir = os.path.dirname(os.path.abspath(__file__))
                parent_dir = os.path.dirname(current_dir)
                config_path = os.path.join(parent_dir, "config.ini")

                if os.path.exists(config_path):
                    config = configparser.ConfigParser()
                    config.read(config_path)
                    wavespeed_api_key = config.get("API", "api_key", fallback="")

                if not wavespeed_api_key:
                    # Try environment variable
                    wavespeed_api_key = os.environ.get("WAVESPEED_API_KEY", "")

                if not wavespeed_api_key:
                    raise ValueError(
                        "API_KEY is empty. Please provide an API key or set it in config.ini"
                    )

            except Exception as e:
                raise ValueError(f"Unable to find API_KEY: {str(e)}")

        else:
            wavespeed_api_key = api_key

        return ({"api_key": wavespeed_api_key},)


# Node registration
NODE_CLASS_MAPPINGS = {"NSWaveSpeedClient": NSWaveSpeedClient}

NODE_DISPLAY_NAME_MAPPINGS = {"NSWaveSpeedClient": "NS WaveSpeed Client"}
