# ABOUTME: xAI Grok API client for image and video generation
# Handles authentication, request/response processing, and async task polling

import time
import requests
from typing import Dict, Any, Optional


class GrokClient:
    """Client for interacting with xAI Grok API"""
    
    def __init__(self, api_key: str, base_url: str = "https://api.x.ai"):
        """
        Initialize Grok API client
        
        Args:
            api_key: xAI API key
            base_url: Base URL for the API (default: https://api.x.ai)
        """
        self.api_key = api_key
        self.base_url = base_url
        self.timeout = 600  # Default timeout for requests
        
    def post(self, endpoint: str, data: Dict[str, Any], timeout: Optional[int] = None) -> Dict[str, Any]:
        """
        Make a POST request to the Grok API
        
        Args:
            endpoint: API endpoint path
            data: Request payload
            timeout: Request timeout in seconds
            
        Returns:
            API response data
        """
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        timeout = timeout or self.timeout
        
        try:
            response = requests.post(url, json=data, headers=headers, timeout=timeout)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"API request failed: {str(e)}")
    
    def get(self, endpoint: str, timeout: Optional[int] = None) -> Dict[str, Any]:
        """
        Make a GET request to the Grok API
        
        Args:
            endpoint: API endpoint path
            timeout: Request timeout in seconds
            
        Returns:
            API response data
        """
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
        }
        
        timeout = timeout or self.timeout
        
        try:
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"API request failed: {str(e)}")
    
    def wait_for_video(self, request_id: str, polling_interval: int = 5, timeout: int = 600) -> Dict[str, Any]:
        """
        Poll for video generation completion
        
        Args:
            request_id: Video generation request ID
            polling_interval: Time between polls in seconds
            timeout: Maximum time to wait in seconds
            
        Returns:
            Video result when complete
        """
        start_time = time.time()
        endpoint = f"/v1/videos/{request_id}"
        
        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise Exception(f"Video generation timed out after {timeout} seconds")
            
            try:
                result = self.get(endpoint, timeout=30)
                
                status = result.get("status", "")
                
                if status == "completed" or status == "success":
                    return result
                elif status == "failed" or status == "error":
                    error_msg = result.get("error", result.get("message", "Unknown error"))
                    raise Exception(f"Video generation failed: {error_msg}")
                
                # Task still processing, wait and retry
                print(f"Video generation status: {status}...")
                time.sleep(polling_interval)
                
            except Exception as e:
                if "timed out" in str(e):
                    raise
                # For other errors, retry after interval
                time.sleep(polling_interval)
