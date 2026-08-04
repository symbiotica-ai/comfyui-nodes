# ABOUTME: Load Text List node — one text file of blank-line-separated blocks as a list.
# ABOUTME: Emits the same (prompts, names, count) contract as NSStructuredPromptList.

import folder_paths

from ._text_file import (
    file_fingerprint,
    list_text_files,
    resolve_text_file,
    select_blocks,
    split_blocks,
)

_ROOTS = {
    "input": folder_paths.get_input_directory,
    "output": folder_paths.get_output_directory,
    "temp": folder_paths.get_temp_directory,
}


def _root_path(root_dir):
    getter = _ROOTS.get(root_dir)
    if getter is None:
        raise ValueError(f"unknown root_dir: {root_dir!r}")
    return getter()


class LoadTextList:
    """
    Reads one text file of blank-line-separated blocks and emits them as a
    list, so the graph runs once per block from a single queue press.

    Each block's first line is taken as its name and the rest as its text, so
    a file of framings stays readable and hand-editable while the names come
    back as filename prefixes — renders arrive labelled rather than numbered.

    Deliberately the same output shape as NSStructuredPromptList, so it drops
    into a graph already built around that node without needing the JSON that
    one expects.
    """

    @classmethod
    def INPUT_TYPES(cls):
        files = list_text_files(folder_paths.get_input_directory())
        return {
            "required": {
                "root_dir": (list(_ROOTS), {"default": "input"}),
                "file": (files or ["[no text files found]"], {
                    "tooltip": "A file whose blocks are separated by blank "
                               "lines, each starting with a short name line.",
                }),
                "index": ("INT", {
                    "default": -1, "min": -1, "max": 999,
                    "tooltip": "-1 runs every block in the file, once each, "
                               "from one queue press. 0 or more runs only that "
                               "block. The wiring is the same either way.",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("prompts", "names", "count")
    OUTPUT_IS_LIST = (True, True, False)
    FUNCTION = "execute"
    CATEGORY = "Symbiotica/Text"
    DESCRIPTION = ("Load blank-line-separated blocks from a text file as a "
                   "list. Re-runs only when the file or index changes.")

    @classmethod
    def IS_CHANGED(cls, root_dir="input", file="", index=-1, **kwargs):
        try:
            path = resolve_text_file(_root_path(root_dir), file)
        except (ValueError, OSError):
            return float("nan")
        return f"{file_fingerprint(path)}|{index}"

    @classmethod
    def VALIDATE_INPUTS(cls, root_dir="input", file="", **kwargs):
        try:
            resolve_text_file(_root_path(root_dir), file)
        except (ValueError, OSError) as exc:
            return str(exc)
        return True

    def execute(self, root_dir="input", file="", index=-1):
        path = resolve_text_file(_root_path(root_dir), file)
        with open(path, "r", encoding="utf-8") as handle:
            blocks = split_blocks(handle.read())
        chosen = select_blocks(blocks, index)
        if not chosen:
            raise ValueError(f"no blocks found in {file!r}")
        names = [name for name, _ in chosen]
        prompts = [body for _, body in chosen]
        return (prompts, names, len(prompts))


NODE_CLASS_MAPPINGS = {"LoadTextList": LoadTextList}
NODE_DISPLAY_NAME_MAPPINGS = {"LoadTextList": "Load Text List"}
