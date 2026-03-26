# ABOUTME: Stateless LLM agent node for ComfyUI. Accepts agent settings (soul, skills,
# ABOUTME: user context, instructions), assembles a system prompt, and executes one task.

from typing import Optional

from torch import Tensor

from .llm_api import all_models, call_llm


def build_agent_system_prompt(settings: dict) -> str:
    """Assemble a system prompt from agent settings.

    Order: Soul > User Context > Instructions (CLAUDE.md) > Skills.
    Each section is only included if the corresponding value is non-empty.
    """
    parts = []

    for heading, key in [("Soul", "soul"), ("User", "user_context"), ("Instructions", "instructions")]:
        content = settings.get(key, "")
        if content and content.strip():
            parts.append(f"# {heading}\n\n{content.strip()}")

    # Skills from wired skill nodes
    skills = settings.get("skills", [])
    if skills:
        skill_parts = []
        for skill in skills:
            name = skill.get("name", "")
            content = skill.get("content", "")
            if content and content.strip():
                if name:
                    skill_parts.append(f"## {name}\n\n{content.strip()}")
                else:
                    skill_parts.append(content.strip())
        if skill_parts:
            parts.append("# Skills\n\n" + "\n\n".join(skill_parts))

    return "\n\n".join(parts)


class SymbioticaAgent:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "agent_settings": ("AGENT_SETTINGS",),
                "prompt": ("STRING", {"multiline": True, "tooltip": "The task or question for the agent."}),
                "max_tokens": ("INT", {"default": 4096, "min": 1, "max": 200000}),
                "temperature": ("FLOAT", {"default": 0.7, "min": 0, "max": 2.0, "step": 0.01}),
                "seed": (
                    "INT",
                    {
                        "default": 1,
                        "min": -1,
                        "max": 0xFFFFFFFFFFFFFFFF,
                        "control_after_generate": False,
                        "tooltip": "Random seed. -1 for random. Works with Gemini and Grok. Claude ignores seeds.",
                    },
                ),
                "timeout": (
                    "INT",
                    {
                        "default": 500,
                        "min": 10,
                        "max": 3600,
                        "tooltip": "Request timeout in seconds.",
                    },
                ),
            },
            "optional": {
                "api_key": ("STRING", {"multiline": False, "default": "", "tooltip": "Overrides the agent settings API key."}),
                "model_override": ("STRING", {"forceInput": True, "tooltip": "Overrides the agent settings model."}),
                "image": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("response",)
    FUNCTION = "execute"
    CATEGORY = "symbiotica/LLM"

    def execute(
        self,
        agent_settings: dict,
        prompt: str,
        max_tokens: int,
        temperature: float,
        seed: int,
        timeout: int,
        api_key: str = "",
        model_override: Optional[str] = None,
        image: Optional[Tensor] = None,
    ):
        # Resolve model: direct override > agent settings
        if model_override and model_override.strip():
            model = model_override.strip()
        else:
            model = agent_settings.get("model", "claude-sonnet-4-6")

        # Resolve API key: direct input > agent settings > env var (handled by call_llm)
        resolved_key = api_key
        if not resolved_key or not resolved_key.strip():
            resolved_key = agent_settings.get("api_key", "")

        # Assemble system prompt from agent definition
        system_prompt = build_agent_system_prompt(agent_settings)

        response = call_llm(
            model=model,
            api_key=resolved_key,
            prompt=prompt,
            system_prompt=system_prompt,
            image=image,
            max_tokens=max_tokens,
            temperature=temperature,
            seed=seed,
            timeout=timeout,
        )

        return (response,)


NODE_CLASS_MAPPINGS = {
    "SymbioticaAgent": SymbioticaAgent,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SymbioticaAgent": "Symbiotica Agent",
}
