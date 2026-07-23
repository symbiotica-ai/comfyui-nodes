# ABOUTME: WaveSpeed API client for making requests to WaveSpeed AI services
# Handles authentication, request/response processing, and task polling

import time
import requests
from typing import Dict, Any, Optional


def _resolve_interrupt_checker():
    """Reads ComfyUI's cancel flag, or reports "not cancelled" outside it.

    Pressing Cancel in ComfyUI does not stop a running node — it sets a flag
    and expects the node to notice. A node that never looks runs to its own
    timeout, which for a video job is minutes of the user watching a button
    they already pressed."""
    try:
        from comfy import model_management
        return model_management.processing_interrupted
    except Exception:
        return lambda: False


def _interrupted_base():
    """ComfyUI logs its own interrupt quietly and marks no node in red, so a
    cancel raised as that type reads as a cancel rather than a failure."""
    try:
        from comfy.model_management import InterruptProcessingException
        return InterruptProcessingException
    except Exception:
        return Exception


class WaveSpeedInterrupted(_interrupted_base()):
    """Raised when the user cancels while a task is being polled."""


class WaveSpeedTaskFailed(Exception):
    """Raised when the API reports the task itself failed."""


class WaveSpeedClient:
    """Client for interacting with WaveSpeed AI API"""
    
    def __init__(self, api_key: str, base_url: str = "https://api.wavespeed.ai"):
        """
        Initialize WaveSpeed API client
        
        Args:
            api_key: WaveSpeed AI API key
            base_url: Base URL for the API (default: https://api.wavespeed.ai)
        """
        self.api_key = api_key
        self.base_url = base_url
        self.once_timeout = 300  # Default timeout for single requests
        
    def post(self, endpoint: str, data: Dict[str, Any], timeout: int = 300) -> Dict[str, Any]:
        """
        Make a POST request to the WaveSpeed API
        
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
        
        try:
            response = requests.post(url, json=data, headers=headers, timeout=timeout)
            response.raise_for_status()
            
            result = response.json()
            
            # Extract 'data' field if present in response
            if isinstance(result, dict) and "data" in result:
                return result["data"]
            
            return result
            
        except requests.exceptions.RequestException as e:
            raise Exception(f"API request failed: {str(e)}")
    
    def wait_for_task(self, task_id: str, polling_interval: int = 1, timeout: int = 300) -> Dict[str, Any]:
        """
        Poll for task completion
        
        Args:
            task_id: Task ID to poll
            polling_interval: Time between polls in seconds
            timeout: Maximum time to wait in seconds
            
        Returns:
            Task result when complete
        """
        start_time = time.time()
        endpoint = f"/api/v3/wavespeed-ai/task/{task_id}"
        cancelled = _resolve_interrupt_checker()

        def sleep_unless_cancelled(seconds):
            """Sleep in slices so Cancel lands within a slice, not a poll."""
            remaining = seconds
            while remaining > 0:
                if cancelled():
                    raise WaveSpeedInterrupted("Cancelled while waiting for the task")
                slice_s = min(0.5, remaining)
                time.sleep(slice_s)
                remaining -= slice_s

        while True:
            if cancelled():
                raise WaveSpeedInterrupted("Cancelled while waiting for the task")

            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise Exception(f"Task polling timed out after {timeout} seconds")

            try:
                result = self.post(endpoint, {}, timeout=30)

                status = result.get("status", "")

                if status == "completed" or status == "success":
                    return result
                elif status == "failed" or status == "error":
                    error_msg = result.get("error", "Unknown error")
                    raise WaveSpeedTaskFailed(f"Task failed: {error_msg}")

                # Task still processing, wait and retry
                sleep_unless_cancelled(polling_interval)

            # These two must stay ABOVE the catch-all below. That handler exists
            # to ride out transient status-check errors, and it swallows whatever
            # it is given — a cancel caught there is a cancel ignored, and a
            # failed task caught there is retried until the timeout hides it.
            except WaveSpeedInterrupted:
                raise
            except WaveSpeedTaskFailed:
                raise
            except Exception as e:
                if "Task polling timed out" in str(e):
                    raise
                # For other errors, retry after interval
                sleep_unless_cancelled(polling_interval)
