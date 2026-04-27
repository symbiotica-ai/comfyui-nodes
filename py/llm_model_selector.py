# ABOUTME: Standalone LLM model selector node. Outputs a model name string
# ABOUTME: that can be wired into multiple NS LLM Chat nodes for centralized model switching.

from .llm_chat import all_models


class NSLLMModelSelector:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": (all_models, {"default": "claude-sonnet-4-6"}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("model",)
    FUNCTION = "select"
    CATEGORY = "neuralsins/LLM"

    def select(self, model: str):
        return (model,)


NODE_CLASS_MAPPINGS = {
    "NSLLMModelSelector": NSLLMModelSelector,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSLLMModelSelector": "NS LLM Model Selector",
}
