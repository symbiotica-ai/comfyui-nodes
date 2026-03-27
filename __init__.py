# ABOUTME: ComfyUI custom nodes package for Symbiotica AI agent system.
# ABOUTME: Auto-discovers and registers all node modules from the py/ directory.

import importlib
import os
import traceback

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
WEB_DIRECTORY = "./web"

py_dir = os.path.join(os.path.dirname(__file__), "py")

if os.path.isdir(py_dir):
    for filename in sorted(os.listdir(py_dir)):
        if filename.endswith(".py") and not filename.startswith("_"):
            module_name = filename[:-3]
            try:
                module = importlib.import_module(f".py.{module_name}", package=__name__)
                if hasattr(module, "NODE_CLASS_MAPPINGS"):
                    NODE_CLASS_MAPPINGS.update(module.NODE_CLASS_MAPPINGS)
                if hasattr(module, "NODE_DISPLAY_NAME_MAPPINGS"):
                    NODE_DISPLAY_NAME_MAPPINGS.update(module.NODE_DISPLAY_NAME_MAPPINGS)
            except Exception:
                print(f"[Symbiotica] Failed to load {module_name}:")
                traceback.print_exc()

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
