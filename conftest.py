import os
import sys

# Add repo root to sys.path before pytest imports test modules
_repo_root = os.path.dirname(os.path.abspath(__file__))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

# Extend the py namespace package to include our local py/ directory
import py
_local_py_path = os.path.join(_repo_root, "py")
if _local_py_path not in py.__path__:
    py.__path__.append(_local_py_path)
