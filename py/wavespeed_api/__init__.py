# ABOUTME: WaveSpeed API package initialization
# Makes client and utils available for import

from .client import WaveSpeedClient
from .utils import imageurl2tensor

__all__ = ["WaveSpeedClient", "imageurl2tensor"]
