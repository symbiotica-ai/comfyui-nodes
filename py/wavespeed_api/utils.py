# ABOUTME: Utility functions for WaveSpeed API nodes
# Handles image URL to tensor conversions for ComfyUI

import io
import requests
import torch
import numpy as np
from PIL import Image
from typing import Union, List


def imageurl2tensor(image_urls: Union[str, List[str]]) -> torch.Tensor:
    """
    Convert image URL(s) to ComfyUI tensor format
    
    Args:
        image_urls: Single URL string or list of URL strings
        
    Returns:
        torch.Tensor in ComfyUI format [batch, height, width, channels]
    """
    # Handle single URL
    if isinstance(image_urls, str):
        image_urls = [image_urls]
    
    tensors = []
    
    for url in image_urls:
        try:
            # Download image
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            
            # Convert to PIL Image
            image = Image.open(io.BytesIO(response.content))
            
            # Convert to RGB if necessary
            if image.mode != "RGB":
                image = image.convert("RGB")
            
            # Convert to numpy array
            image_np = np.array(image).astype(np.float32) / 255.0
            
            # Convert to tensor
            image_tensor = torch.from_numpy(image_np)
            
            tensors.append(image_tensor)
            
        except Exception as e:
            raise Exception(f"Failed to load image from {url}: {str(e)}")
    
    # Stack all images into batch
    if len(tensors) == 1:
        return tensors[0].unsqueeze(0)
    else:
        return torch.stack(tensors)
