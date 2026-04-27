# ABOUTME: Utility functions for Grok API nodes
# Handles image/video URL to tensor/path conversions for ComfyUI

import io
import os
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


def videourl_to_path(video_url: str, output_dir: str = "/tmp/grok_videos") -> str:
    """
    Download video from URL and save to local path
    
    Args:
        video_url: URL of the video to download
        output_dir: Directory to save videos to
        
    Returns:
        Local path to the downloaded video file
    """
    try:
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # Extract filename from URL or generate one
        import hashlib
        video_hash = hashlib.md5(video_url.encode()).hexdigest()
        filename = f"grok_video_{video_hash}.mp4"
        output_path = os.path.join(output_dir, filename)
        
        # Download video
        print(f"Downloading video from {video_url}...")
        response = requests.get(video_url, timeout=120, stream=True)
        response.raise_for_status()
        
        # Save to file
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        print(f"Video saved to {output_path}")
        return output_path
        
    except Exception as e:
        raise Exception(f"Failed to download video from {video_url}: {str(e)}")
