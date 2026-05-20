"""
NS Structured Prompt List

Parses a JSON string (typically from an upstream LLM node), pulls a list of
items from it, and fans out two parallel STRING lists — one of prompts and
one of filename prefixes — so downstream nodes run once per item.

Generic by design: the JSON path and field names are widgets, so the same
node works for any pipeline that emits a list of items where each item has
a prompt string and an output-path string.
"""

import json
import re


def _strip_code_fences(s: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` fences if the LLM wrapped its output."""
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def _get_by_path(obj, path: str):
    """Resolve a dotted path inside a dict. Empty path returns the object itself."""
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        part = part.strip()
        if not part:
            continue
        if not isinstance(cur, dict):
            raise ValueError(
                f"Cannot descend into '{part}' — parent is {type(cur).__name__}, not an object."
            )
        if part not in cur:
            raise ValueError(
                f"Key '{part}' not found. Available keys: {list(cur.keys())}"
            )
        cur = cur[part]
    return cur


class NSStructuredPromptList:
    """
    Parse a JSON string and fan out prompt + filename_prefix as parallel lists.

    Pairs with any upstream LLM-chat node that emits JSON of the shape:

        {"items": [{"prompt": "...", "filename_prefix": "..."}, ...]}

    Field names and the array path are configurable so the node stays generic.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "json_string": ("STRING", {"multiline": True, "default": ""}),
                "items_path": ("STRING", {"default": "items"}),
                "prompt_field": ("STRING", {"default": "prompt"}),
                "filename_field": ("STRING", {"default": "filename_prefix"}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("prompts", "filename_prefixes", "count")
    OUTPUT_IS_LIST = (True, True, False)
    FUNCTION = "parse"
    CATEGORY = "neuralsins/Utils"

    DESCRIPTION = """
Parses a JSON string and emits two parallel STRING lists (prompts and
filename_prefixes) so the downstream graph runs once per item.

- **items_path**: dotted JSON path to the array. Default `items` matches
  `{"items": [...]}`. Leave empty if the JSON root is already an array.
- **prompt_field** / **filename_field**: keys to extract from each item.

Strips ```json fences if the upstream LLM wrapped its output. Raises a clear
error if the JSON is malformed or the fields/path don't resolve.
"""

    def parse(self, json_string, items_path, prompt_field, filename_field):
        raw = _strip_code_fences(json_string or "")
        if not raw:
            raise ValueError("json_string is empty.")

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            preview = raw[:200].replace("\n", " ")
            raise ValueError(
                f"Could not parse JSON: {e.msg} at line {e.lineno} col {e.colno}. "
                f"Input starts with: {preview!r}"
            ) from e

        items = _get_by_path(data, items_path.strip())
        if not isinstance(items, list):
            raise ValueError(
                f"Path '{items_path}' resolved to {type(items).__name__}, expected a list."
            )
        if not items:
            raise ValueError(f"Path '{items_path}' resolved to an empty list.")

        prompts = []
        filenames = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                raise ValueError(
                    f"Item #{idx} is {type(item).__name__}, expected an object."
                )
            if prompt_field not in item:
                raise ValueError(
                    f"Item #{idx} is missing field '{prompt_field}'. "
                    f"Available keys: {list(item.keys())}"
                )
            if filename_field not in item:
                raise ValueError(
                    f"Item #{idx} is missing field '{filename_field}'. "
                    f"Available keys: {list(item.keys())}"
                )
            prompts.append(str(item[prompt_field]))
            filenames.append(str(item[filename_field]))

        return (prompts, filenames, len(prompts))


NODE_CLASS_MAPPINGS = {
    "NSStructuredPromptList": NSStructuredPromptList,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSStructuredPromptList": "NS Structured Prompt List",
}
