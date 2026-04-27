# ABOUTME: xAI Grok API Client Node for ComfyUI
# Creates authenticated client for Grok image and video generation

import configparser
import os

from .grok_api.client import GrokClient


class NSGrokClient:
    """
    xAI Grok API Client Node
    
    This node creates a client for connecting to the xAI Grok API.
    Used for image and video generation with Grok models.
    """
    
    def __init__(self):
        pass
    
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "api_key": ("STRING", {
                    "multiline": False,
                    "default": "",
                    "tooltip": "xAI API key from https://console.x.ai"
                }),
            },
        }
    
    RETURN_TYPES = ("GROK_API_CLIENT",)
    RETURN_NAMES = ("client",)
    
    FUNCTION = "create_client"
    
    CATEGORY = "neuralsins/Grok"
    
    def create_client(self, api_key):
        """
        Create a xAI Grok API client
        
        Args:
            api_key: xAI API key
            
        Returns:
            GrokClient: Grok API client instance
        """
        xai_api_key = ""
        
        if api_key == "":
            # Try to read from config.ini
            try:
                current_dir = os.path.dirname(os.path.abspath(__file__))
                parent_dir = os.path.dirname(current_dir)
                config_path = os.path.join(parent_dir, "config.ini")
                
                if os.path.exists(config_path):
                    config = configparser.ConfigParser()
                    config.read(config_path)
                    xai_api_key = config.get("API", "xai_api_key", fallback="")
                
                if not xai_api_key:
                    # Try environment variable
                    xai_api_key = os.environ.get("XAI_API_KEY", "")
                
                if not xai_api_key:
                    raise ValueError(
                        "XAI_API_KEY is empty. Please provide an API key or set it in config.ini"
                    )
                    
            except Exception as e:
                raise ValueError(f"Unable to find XAI_API_KEY: {str(e)}")
        
        else:
            xai_api_key = api_key
        
        return ({"api_key": xai_api_key},)


# Node registration
NODE_CLASS_MAPPINGS = {"NSGrokClient": NSGrokClient}

NODE_DISPLAY_NAME_MAPPINGS = {"NSGrokClient": "NS Grok Client"}
