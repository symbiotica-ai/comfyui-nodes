# ABOUTME: Load Text File node — reads a prompt file from the input directory.
# ABOUTME: Exists because the common third-party equivalent never caches correctly.

import folder_paths

from ._text_file import (
    file_fingerprint,
    list_text_files,
    resolve_text_file,
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


class LoadTextFile:
    """
    Loads a text file — a prompt, a set of framing lines, a spec — from the
    input directory.

    Written rather than reused because the widely-installed equivalent gets
    caching wrong in a way that costs money: its IS_CHANGED reads an attribute
    that only exists on an instance, so it raises, and ComfyUI turns that into
    a NaN which never compares equal to itself. The node is then permanently
    "changed" and every downstream node re-runs on every queue — including
    billed API nodes. This one re-runs when, and only when, the file changes.
    """

    @classmethod
    def INPUT_TYPES(cls):
        files = list_text_files(folder_paths.get_input_directory())
        return {
            "required": {
                "root_dir": (list(_ROOTS), {
                    "default": "input",
                    "tooltip": "Which ComfyUI directory the path is relative to.",
                }),
                "file": (files or ["[no text files found]"], {
                    "tooltip": "A .txt or .md file under the chosen directory. "
                               "Newly added files appear after a browser "
                               "reload; edits to an existing file are picked up "
                               "on the next queue with no reload needed.",
                }),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("text",)
    FUNCTION = "execute"
    CATEGORY = "Symbiotica/Text"
    DESCRIPTION = ("Load a prompt or other text from a file. Re-runs only "
                   "when the file changes.")

    @classmethod
    def IS_CHANGED(cls, root_dir="input", file="", **kwargs):
        """Resolve the path from the ARGUMENTS, never from instance state.

        Reading `self.file` here is the bug this node exists to avoid: on a
        classmethod there is no instance, so it raises, and ComfyUI turns a
        raising IS_CHANGED into NaN — which never equals itself, so the node
        re-runs forever and re-bills everything downstream.
        """
        try:
            path = resolve_text_file(_root_path(root_dir), file)
        except (ValueError, OSError):
            return float("nan")
        return file_fingerprint(path)

    @classmethod
    def VALIDATE_INPUTS(cls, root_dir="input", file="", **kwargs):
        try:
            resolve_text_file(_root_path(root_dir), file)
        except (ValueError, OSError) as exc:
            return str(exc)
        return True

    def execute(self, root_dir="input", file=""):
        path = resolve_text_file(_root_path(root_dir), file)
        with open(path, "r", encoding="utf-8") as handle:
            return (handle.read(),)


NODE_CLASS_MAPPINGS = {
    "LoadTextFile": LoadTextFile,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LoadTextFile": "Load Text File",
}
