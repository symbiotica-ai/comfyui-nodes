# ABOUTME: Shared binary path resolution for all nodes.
# ABOUTME: Searches PATH, macOS Homebrew, and common Linux locations.

import os
import shutil

_SEARCH_DIRS = ["/opt/homebrew/bin", "/usr/local/bin", "/usr/bin"]


def find(name, extra_dirs=None):
    """Find a binary in PATH, common macOS, and common Linux locations."""
    found = shutil.which(name)
    if found:
        return found
    dirs = list(extra_dirs or []) + _SEARCH_DIRS
    for d in dirs:
        p = os.path.join(d, name)
        if os.path.isfile(p):
            return p
    return name  # last resort — let subprocess raise if missing


FFMPEG = find("ffmpeg")
FFPROBE = find("ffprobe")
NODE_BIN = find("node")

# npm/npx are often in the same directory as node but not in PATH
_node_dir = os.path.dirname(NODE_BIN)
NPX_BIN = find("npx", extra_dirs=[_node_dir])
NPM_BIN = find("npm", extra_dirs=[_node_dir])
