# ABOUTME: Multi-provider LLM API client supporting Claude, Gemini, GPT, and Grok.
# ABOUTME: Handles image encoding, request building, and response parsing for each provider.

import base64
import io
import os
from typing import Optional

import numpy as np
import requests
from PIL import Image
from torch import Tensor


# --- Model registries ---

claude_models = [
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
]

gemini_models = [
    "gemini-3.1-pro-preview",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
]

openai_models = [
    "gpt-5.5",
    "gpt-5.5-pro",
    "gpt-5.4-mini",
]

grok_models = [
    "grok-4.3",
    "grok-4.20-0309-reasoning",
    "grok-4.20-0309-non-reasoning",
]

all_models = claude_models + gemini_models + openai_models + grok_models


# --- Image utilities ---

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
    return base64.b64encode(buffered.getvalue()).decode("utf-8")


# --- API callers ---

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
    content = []

    if image is not None:
        images = [image] if len(image.shape) == 3 else [image[i] for i in range(image.shape[0])]
        for idx, img in enumerate(images):
            image_base64 = pil2base64(tensor2pil(img))
            if len(images) > 1:
                content.append({"type": "text", "text": f"Image {idx + 1}:"})
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": image_base64},
            })

    content.append({"type": "text", "text": prompt})

    data = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "max_tokens": max_tokens,
    }
    # `temperature` intentionally omitted for Claude — current-gen models
    # (Opus 4.7, Sonnet 4.6, Haiku 4.5) have adaptive thinking always-on
    # and reject the parameter with "`temperature` is deprecated for this
    # model." The slider stays effective for Gemini/OpenAI/Grok callers.

    if system_prompt and system_prompt.strip():
        data["system"] = system_prompt

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    response = requests.post(f"{endpoint}/v1/messages", json=data, headers=headers, timeout=timeout)

    if response.status_code != 200:
        error_msg = f"Claude API request failed with status {response.status_code}"
        try:
            error_data = response.json()
            if error_data.get("error"):
                error_msg = error_data["error"].get("message", error_msg)
        except Exception:
            error_msg = f"{error_msg}: {response.text}"
        raise Exception(error_msg)

    response_data = response.json()
    if response_data.get("error"):
        raise Exception(response_data["error"].get("message", "Unknown error"))

    return response_data["content"][0]["text"]


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
    system_instruction = None
    if system_prompt and system_prompt.strip():
        system_instruction = {"parts": [{"text": system_prompt}]}

    parts = []

    if image is not None:
        images = [image] if len(image.shape) == 3 else [image[i] for i in range(image.shape[0])]
        for idx, img in enumerate(images):
            image_base64 = pil2base64(tensor2pil(img))
            if len(images) > 1:
                parts.append({"text": f"Image {idx + 1}:"})
            parts.append({"inline_data": {"mime_type": "image/png", "data": image_base64}})

    parts.append({"text": prompt})

    generation_config = {"maxOutputTokens": max_tokens, "temperature": temperature}
    if seed != -1:
        generation_config["seed"] = seed

    data = {"contents": [{"parts": parts}], "generationConfig": generation_config}
    if system_instruction:
        data["systemInstruction"] = system_instruction

    headers = {"x-goog-api-key": api_key, "content-type": "application/json"}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    response = requests.post(url, json=data, headers=headers, timeout=timeout)

    if response.status_code != 200:
        error_msg = f"Gemini API request failed with status {response.status_code}"
        try:
            error_data = response.json()
            if error_data.get("error"):
                error_msg = error_data["error"].get("message", error_msg)
        except Exception:
            error_msg = f"{error_msg}: {response.text}"
        raise Exception(error_msg)

    response_data = response.json()
    if response_data.get("error"):
        raise Exception(response_data["error"].get("message", "Unknown error"))

    if "candidates" in response_data and len(response_data["candidates"]) > 0:
        candidate = response_data["candidates"][0]
        if "content" in candidate and "parts" in candidate["content"] and len(candidate["content"]["parts"]) > 0:
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
    content = []

    if image is not None:
        images = [image] if len(image.shape) == 3 else [image[i] for i in range(image.shape[0])]
        for idx, img in enumerate(images):
            image_base64 = pil2base64(tensor2pil(img))
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

    data = {"messages": messages, "model": model, "max_tokens": max_tokens, "temperature": temperature}
    if seed != -1:
        data["seed"] = seed

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    response = requests.post("https://api.x.ai/v1/chat/completions", json=data, headers=headers, timeout=timeout)

    if response.status_code != 200:
        error_msg = f"Grok API request failed with status {response.status_code}"
        try:
            error_data = response.json()
            if error_data.get("error"):
                error_msg = error_data["error"].get("message", error_msg)
        except Exception:
            error_msg = f"{error_msg}: {response.text}"
        raise Exception(error_msg)

    response_data = response.json()
    if response_data.get("error"):
        raise Exception(response_data["error"].get("message", "Unknown error"))

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
    content = []

    if image is not None:
        images = [image] if len(image.shape) == 3 else [image[i] for i in range(image.shape[0])]
        for idx, img in enumerate(images):
            image_base64 = pil2base64(tensor2pil(img))
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

    data = {"messages": messages, "model": model, "max_tokens": max_tokens, "temperature": temperature}
    if seed != -1:
        data["seed"] = seed

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    response = requests.post("https://api.openai.com/v1/chat/completions", json=data, headers=headers, timeout=timeout)

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
        raise Exception(response_data["error"].get("message", "Unknown error"))

    if "choices" in response_data and len(response_data["choices"]) > 0:
        return response_data["choices"][0]["message"]["content"]

    raise Exception("No valid response received from OpenAI API")


def resolve_api_key(model: str, api_key: str) -> str:
    """Resolve API key from direct input, then environment variables."""
    if api_key and api_key.strip():
        return api_key.strip()

    if model in gemini_models:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not key:
            raise Exception("Gemini API key required. Set GEMINI_API_KEY environment variable.")
        return key
    elif model in grok_models:
        key = os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY")
        if not key:
            raise Exception("xAI API key required. Set XAI_API_KEY environment variable.")
        return key
    elif model in openai_models:
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise Exception("OpenAI API key required. Set OPENAI_API_KEY environment variable.")
        return key
    else:
        key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
        if not key:
            raise Exception("Claude API key required. Set ANTHROPIC_API_KEY environment variable.")
        return key


def call_llm(
    model: str,
    api_key: str,
    prompt: str,
    system_prompt: str,
    image: Optional[Tensor],
    max_tokens: int,
    temperature: float,
    seed: int = -1,
    timeout: int = 500,
) -> str:
    """Route to the appropriate provider based on the model name."""
    resolved_key = resolve_api_key(model, api_key)

    if model in gemini_models:
        return call_gemini_api(resolved_key, model, prompt, system_prompt, image, max_tokens, temperature, seed, timeout)
    elif model in grok_models:
        return call_grok_api(resolved_key, model, prompt, system_prompt, image, max_tokens, temperature, seed, timeout)
    elif model in openai_models:
        return call_openai_api(resolved_key, model, prompt, system_prompt, image, max_tokens, temperature, seed, timeout)
    else:
        return call_claude_api(resolved_key, model, prompt, system_prompt, image, max_tokens, temperature, seed, timeout)
