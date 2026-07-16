import base64
import io
import json
import os
from typing import Optional

import numpy as np
import requests
from PIL import Image
from torch import Tensor

claude_models = [
    "claude-fable-5",
    "claude-opus-4-8",
    "claude-sonnet-5",
    "claude-haiku-4-5",
]

gemini_models = [
    "gemini-3.1-pro-preview",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
]

openai_models = [
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.4-mini",
]

grok_models = [
    "grok-4.5",
]

# All available models
all_models = claude_models + gemini_models + openai_models + grok_models


# Utility functions
def numpy2pil(numpy_image: np.ndarray, mode=None) -> Image.Image:
    if numpy_image.dtype == np.float32 or numpy_image.dtype == np.float64:
        numpy_image = np.clip(numpy_image, 0, 1)
        numpy_image = (numpy_image * 255).astype(np.uint8)
    elif numpy_image.dtype != np.uint8:
        numpy_image = numpy_image.astype(np.uint8)

    if len(numpy_image.shape) == 3 and numpy_image.shape[2] == 1:
        numpy_image = numpy_image.squeeze(axis=2)

    if mode:
        return Image.fromarray(numpy_image, mode=mode)
    elif len(numpy_image.shape) == 2:
        return Image.fromarray(numpy_image, mode="L")
    elif len(numpy_image.shape) == 3:
        if numpy_image.shape[2] == 3:
            return Image.fromarray(numpy_image, mode="RGB")
        elif numpy_image.shape[2] == 4:
            return Image.fromarray(numpy_image, mode="RGBA")

    return Image.fromarray(numpy_image)


def tensor2pil(image: Tensor, mode=None):
    return numpy2pil(image.cpu().numpy().squeeze(), mode=mode)


def pil2base64(image: Image.Image):
    buffered = io.BytesIO()
    image.save(buffered, format="PNG")
    img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
    return img_str


def call_claude_api(
    api_key: str,
    model: str,
    prompt: str,
    system_prompt: str,
    image: Optional[Tensor],
    max_tokens: int,
    temperature: float,
    seed: int = -1,
    timeout: int = 500,
    endpoint: str = "https://api.anthropic.com",
):
    """Call Claude API with text and optional images (batch supported).

    Note: Claude API does not natively support seed parameter for reproducible outputs.
    The seed parameter is included for UI consistency but does not affect Claude's output.
    """

    # Build message content
    content = []

    # Add images if provided
    if image is not None:
        images = [image] if len(image.shape) == 3 else [image[i] for i in range(image.shape[0])]
        for idx, img in enumerate(images):
            pil_image = tensor2pil(img)
            image_base64 = pil2base64(pil_image)
            if len(images) > 1:
                content.append({"type": "text", "text": f"Image {idx + 1}:"})
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": image_base64,
                    },
                }
            )

    # Add text
    content.append({"type": "text", "text": prompt})

    # Build request
    url = f"{endpoint}/v1/messages"
    data = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
    }

    # Adaptive thinking is always-on for current-gen Claude models (Opus 4.8,
    # Sonnet 4.6, Haiku 4.5), and the API rejects `temperature` for any model
    # in this state with "`temperature` is deprecated for this model." We do
    # not send temperature for Claude at all — the model handles sampling
    # internally. The temperature slider in the node remains effective for
    # Gemini / OpenAI / Grok via their own callers.

    # Add system prompt if provided
    if system_prompt and system_prompt.strip():
        data["system"] = system_prompt

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    # Make request
    response = requests.post(url, json=data, headers=headers, timeout=timeout)

    # Handle errors
    if response.status_code != 200:
        error_msg = f"API request failed with status {response.status_code}"
        try:
            error_data = response.json()
            if error_data.get("error"):
                error_msg = error_data["error"].get("message", error_msg)
        except:
            error_msg = f"{error_msg}: {response.text}"
        raise Exception(error_msg)

    response_data = response.json()

    if response_data.get("error"):
        raise Exception(response_data.get("error").get("message", "Unknown error"))

    # Adaptive-thinking models may lead with a thinking block; the text
    # block(s) can sit anywhere in content, so join them instead of
    # indexing [0] (which raised KeyError: 'text').
    blocks = response_data.get("content") or []
    texts = [block.get("text", "") for block in blocks
             if isinstance(block, dict) and block.get("type", "text") == "text"]
    text = "\n".join(t for t in texts if t)
    if not text:
        kinds = [b.get("type") for b in blocks if isinstance(b, dict)]
        raise Exception(f"Claude response contained no text block (got: {kinds})")
    return text


def call_gemini_api(
    api_key: str,
    model: str,
    prompt: str,
    system_prompt: str,
    image: Optional[Tensor],
    max_tokens: int,
    temperature: float,
    seed: int = -1,
    timeout: int = 500,
):
    """Call Gemini API with text and optional images (batch supported).

    Supports seed parameter for reproducible outputs when seed != -1.
    """

    # Build contents array
    contents = []

    # Add system instruction if provided
    system_instruction = None
    if system_prompt and system_prompt.strip():
        system_instruction = {"parts": [{"text": system_prompt}]}

    # Build content parts
    parts = []

    # Add images if provided
    if image is not None:
        images = [image] if len(image.shape) == 3 else [image[i] for i in range(image.shape[0])]
        for idx, img in enumerate(images):
            pil_image = tensor2pil(img)
            image_base64 = pil2base64(pil_image)
            if len(images) > 1:
                parts.append({"text": f"Image {idx + 1}:"})
            parts.append({"inline_data": {"mime_type": "image/png", "data": image_base64}})

    # Add text
    parts.append({"text": prompt})

    contents.append({"parts": parts})

    # Build request
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    generation_config = {
        "maxOutputTokens": max_tokens,
        "temperature": temperature,
    }

    # Add seed if specified (not -1)
    if seed != -1:
        generation_config["seed"] = seed

    data = {"contents": contents, "generationConfig": generation_config}

    # Add system instruction if provided
    if system_instruction:
        data["systemInstruction"] = system_instruction

    headers = {"x-goog-api-key": api_key, "content-type": "application/json"}

    # Make request
    response = requests.post(url, json=data, headers=headers, timeout=timeout)

    # Handle errors
    if response.status_code != 200:
        error_msg = f"Gemini API request failed with status {response.status_code}"
        try:
            error_data = response.json()
            if error_data.get("error"):
                error_msg = error_data["error"].get("message", error_msg)
        except:
            error_msg = f"{error_msg}: {response.text}"
        raise Exception(error_msg)

    response_data = response.json()

    if response_data.get("error"):
        raise Exception(response_data.get("error").get("message", "Unknown error"))

    # Extract text response from Gemini format
    if "candidates" in response_data and len(response_data["candidates"]) > 0:
        candidate = response_data["candidates"][0]
        if (
            "content" in candidate
            and "parts" in candidate["content"]
            and len(candidate["content"]["parts"]) > 0
        ):
            return candidate["content"]["parts"][0]["text"]

    raise Exception("No valid response received from Gemini API")


def call_grok_api(
    api_key: str,
    model: str,
    prompt: str,
    system_prompt: str,
    image: Optional[Tensor],
    max_tokens: int,
    temperature: float,
    seed: int = -1,
    timeout: int = 500,
):
    """Call xAI Grok API with text and optional images (batch supported).

    Uses OpenAI-compatible chat completions endpoint.
    Grok models support seed parameter for reproducible outputs when seed != -1.
    """
    
    # Build message content
    content = []
    
    # Add images if provided
    if image is not None:
        images = [image] if len(image.shape) == 3 else [image[i] for i in range(image.shape[0])]
        for idx, img in enumerate(images):
            pil_image = tensor2pil(img)
            image_base64 = pil2base64(pil_image)
            if len(images) > 1:
                content.append({"type": "text", "text": f"Image {idx + 1}:"})
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{image_base64}",
                }
            })

    # Add text
    content.append({"type": "text", "text": prompt})
    
    # Build messages array
    messages = []
    
    # Add system message if provided
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
    
    # Add user message - use simple string if no image, otherwise use content array
    if image is not None:
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": prompt})
    
    # Build request using OpenAI-compatible format
    url = "https://api.x.ai/v1/chat/completions"
    data = {
        "messages": messages,
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    
    # Add seed if specified (not -1)
    if seed != -1:
        data["seed"] = seed
    
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # Make request
    response = requests.post(url, json=data, headers=headers, timeout=timeout)
    
    # Handle errors
    if response.status_code != 200:
        error_msg = f"Grok API request failed with status {response.status_code}"
        try:
            error_data = response.json()
            if error_data.get("error"):
                error_msg = error_data["error"].get("message", error_msg)
        except:
            error_msg = f"{error_msg}: {response.text}"
        raise Exception(error_msg)
    
    response_data = response.json()
    
    if response_data.get("error"):
        raise Exception(response_data.get("error").get("message", "Unknown error"))
    
    # Extract text response from OpenAI-compatible format
    if "choices" in response_data and len(response_data["choices"]) > 0:
        return response_data["choices"][0]["message"]["content"]
    
    raise Exception("No valid response received from Grok API")


def call_openai_api(
    api_key: str,
    model: str,
    prompt: str,
    system_prompt: str,
    image: Optional[Tensor],
    max_tokens: int,
    temperature: float,
    seed: int = -1,
    timeout: int = 500,
):
    """Call OpenAI Chat Completions API with text and optional images (batch supported).

    Supports seed parameter for reproducible outputs when seed != -1.
    """

    content = []

    if image is not None:
        images = [image] if len(image.shape) == 3 else [image[i] for i in range(image.shape[0])]
        for idx, img in enumerate(images):
            pil_image = tensor2pil(img)
            image_base64 = pil2base64(pil_image)
            if len(images) > 1:
                content.append({"type": "text", "text": f"Image {idx + 1}:"})
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{image_base64}"},
            })

    content.append({"type": "text", "text": prompt})

    messages = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})

    if image is not None:
        messages.append({"role": "user", "content": content})
    else:
        messages.append({"role": "user", "content": prompt})

    data = {
        "messages": messages,
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    if seed != -1:
        data["seed"] = seed

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        json=data,
        headers=headers,
        timeout=timeout,
    )

    if response.status_code != 200:
        error_msg = f"OpenAI API request failed with status {response.status_code}"
        try:
            error_data = response.json()
            if error_data.get("error"):
                error_msg = error_data["error"].get("message", error_msg)
        except Exception:
            error_msg = f"{error_msg}: {response.text}"
        raise Exception(error_msg)

    response_data = response.json()

    if response_data.get("error"):
        raise Exception(response_data.get("error").get("message", "Unknown error"))

    if "choices" in response_data and len(response_data["choices"]) > 0:
        return response_data["choices"][0]["message"]["content"]

    raise Exception("No valid response received from OpenAI API")


# ComfyUI Node Class
class NSLLMChat:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "api_key": ("STRING", {"multiline": False}),
                "model": (all_models, {"default": "claude-opus-4-8"}),
                "prompt": ("STRING", {"multiline": True}),
                "max_tokens": ("INT", {"default": 4096, "min": 1, "max": 200000}),
                "temperature": (
                    "FLOAT",
                    {"default": 0.7, "min": 0, "max": 2.0, "step": 0.01},
                ),
                "seed": (
                    "INT",
                    {
                        "default": 1,
                        "min": -1,
                        "max": 0xFFFFFFFFFFFFFFFF,
                        "control_after_generate": False,
                        "tooltip": "Random seed for reproducible results. -1 for random seed. Note: Works with Gemini, Grok, and OpenAI models. Claude doesn't support seeds.",
                    },
                ),
                "timeout": (
                    "INT",
                    {
                        "default": 500,
                        "min": 10,
                        "max": 3600,
                        "tooltip": "Request timeout in seconds. Increase for large text processing (default: 500s)",
                    },
                ),
            },
            "optional": {
                "model_override": ("STRING", {"forceInput": True, "tooltip": "Connect an NS LLM Model Selector to control the model from a single node."}),
                "system_prompt": ("STRING", {"multiline": True, "default": ""}),
                "image": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("response",)
    FUNCTION = "chat"
    CATEGORY = "neuralsins/LLM"

    def chat(
        self,
        api_key: str,
        model: str,
        prompt: str,
        max_tokens: int,
        temperature: float,
        seed: int,
        timeout: int,
        model_override: Optional[str] = None,
        system_prompt: str = "",
        image: Optional[Tensor] = None,
    ):
        # Use connected model if provided
        if model_override and model_override.strip():
            model = model_override.strip()

        # Check the Settings UI (Symbiotica.* keys), then the environment.
        if not api_key or api_key.strip() == "":
            from ._settings import resolve_key
            if model in gemini_models:
                api_key = resolve_key(["GEMINI_API_KEY", "GOOGLE_API_KEY"])
            elif model in grok_models:
                api_key = resolve_key(["XAI_API_KEY", "GROK_API_KEY"])
            elif model in openai_models:
                api_key = resolve_key(["OPENAI_API_KEY"])
            else:
                api_key = resolve_key(["ANTHROPIC_API_KEY", "CLAUDE_API_KEY"])

        if not api_key:
            if model in gemini_models:
                raise Exception(
                    "Gemini API key is required. Provide it in the node or set GEMINI_API_KEY environment variable."
                )
            elif model in grok_models:
                raise Exception(
                    "xAI API key is required. Provide it in the node or set XAI_API_KEY environment variable."
                )
            elif model in openai_models:
                raise Exception(
                    "OpenAI API key is required. Provide it in the node or set OPENAI_API_KEY environment variable."
                )
            else:
                raise Exception(
                    "Claude API key is required. Provide it in the node or set ANTHROPIC_API_KEY environment variable."
                )

        # Route to appropriate API based on model
        if model in gemini_models:
            response = call_gemini_api(
                api_key=api_key.strip(),
                model=model,
                prompt=prompt,
                system_prompt=system_prompt,
                image=image,
                max_tokens=max_tokens,
                temperature=temperature,
                seed=seed,
                timeout=timeout,
            )
        elif model in grok_models:
            response = call_grok_api(
                api_key=api_key.strip(),
                model=model,
                prompt=prompt,
                system_prompt=system_prompt,
                image=image,
                max_tokens=max_tokens,
                temperature=temperature,
                seed=seed,
                timeout=timeout,
            )
        elif model in openai_models:
            response = call_openai_api(
                api_key=api_key.strip(),
                model=model,
                prompt=prompt,
                system_prompt=system_prompt,
                image=image,
                max_tokens=max_tokens,
                temperature=temperature,
                seed=seed,
                timeout=timeout,
            )
        else:
            response = call_claude_api(
                api_key=api_key.strip(),
                model=model,
                prompt=prompt,
                system_prompt=system_prompt,
                image=image,
                max_tokens=max_tokens,
                temperature=temperature,
                seed=seed,
                timeout=timeout,
            )

        return (response,)


# Node registration
NODE_CLASS_MAPPINGS = {
    "NSLLMChat": NSLLMChat,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSLLMChat": "NS LLM Chat",
}
