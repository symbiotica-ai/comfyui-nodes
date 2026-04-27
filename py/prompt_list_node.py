"""
Dynamic Prompt List Node
A ComfyUI custom node with dynamic text box count for managing prompt lists.
"""


class NSPromptList:
    """
    Dynamic prompt list node with configurable number of text boxes.
    Returns a comma-separated string of all prompts.
    """

    @classmethod
    def INPUT_TYPES(cls):
        # Generate all 50 possible prompts in INPUT_TYPES
        inputs = {
            "required": {
                "inputcount": ("INT", {"default": 5, "min": 2, "max": 50, "step": 1}),
            },
        }

        # Add all 50 prompts to INPUT_TYPES so ComfyUI creates proper text boxes
        for i in range(1, 51):
            inputs["required"][f"prompt_{i}"] = (
                "STRING",
                {"multiline": True, "default": ""},
            )

        return inputs

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "create_prompt_list"
    CATEGORY = "neuralsins/Utils"

    DESCRIPTION = """
Creates a comma-separated list from text boxes.
Set the number of text boxes with the **inputcount** parameter (2-50).
Only the first 'inputcount' boxes will be visible.
"""

    def create_prompt_list(self, inputcount, **kwargs):
        """
        Creates a comma-separated string from text boxes.

        Args:
            inputcount: Number of text boxes to process
            **kwargs: Text values (prompt_1, prompt_2, etc.)

        Returns:
            Tuple containing comma-separated string
        """
        prompts = []

        # Only process the first 'inputcount' prompts
        for i in range(1, inputcount + 1):
            prompt_key = f"prompt_{i}"
            prompt = kwargs.get(prompt_key, "")

            # Add non-empty text
            if prompt and prompt.strip():
                prompts.append(prompt.strip())

        # Return as comma-separated string
        return (",".join(prompts),)


# Node registration
NODE_CLASS_MAPPINGS = {
    "NSPromptList": NSPromptList,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSPromptList": "NS Prompt List",
}
