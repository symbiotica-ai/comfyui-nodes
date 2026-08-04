# ABOUTME: Text-file loading helpers — listing, safe path resolution, joining.
# ABOUTME: Pure functions with no ComfyUI imports so the caching logic is testable.

import os

TEXT_SUFFIXES = (".txt", ".md")


def list_text_files(root, suffixes=TEXT_SUFFIXES):
    """Every text file under `root`, as sorted paths relative to it.

    Called from INPUT_TYPES, which ComfyUI re-runs whenever the frontend asks
    for the node list — so a newly added file appears on a browser reload
    rather than needing a restart.
    """
    if not root or not os.path.isdir(root):
        return []
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Skip the usual noise; a prompt file never lives in one of these.
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d != "__pycache__"]
        for name in filenames:
            if name.startswith("."):
                continue
            if name.lower().endswith(tuple(suffixes)):
                found.append(os.path.relpath(os.path.join(dirpath, name), root))
    return sorted(found)


def resolve_text_file(root, relative):
    """Absolute path of `relative` inside `root`.

    Raises ValueError if it escapes `root`. The dropdown only ever offers paths
    from list_text_files(), but the value is a plain string in the saved
    workflow and can be edited by hand or via the API, so it is checked rather
    than trusted.
    """
    if not relative or not str(relative).strip():
        raise ValueError("no file selected")
    root_real = os.path.realpath(root)
    target = os.path.realpath(os.path.join(root_real, str(relative)))
    if target != root_real and not target.startswith(root_real + os.sep):
        raise ValueError(f"file is outside the allowed directory: {relative!r}")
    if not os.path.isfile(target):
        raise ValueError(f"file not found: {relative!r}")
    return target


def file_fingerprint(path):
    """Value that changes when the file's contents change.

    This is the whole reason this node exists. The obvious third-party
    implementation reads a class attribute that only ever exists on an
    instance, so it raises, and ComfyUI turns a raising IS_CHANGED into
    float("NaN") — which never compares equal to itself, so the node is
    permanently "changed" and every downstream node re-runs on every queue.
    With a billed API node downstream that silently re-charges for work that
    did not need doing.

    Returning NaN on failure is deliberate here and means the opposite: if the
    file cannot be read we genuinely do not know, so re-run.
    """
    try:
        stat = os.stat(path)
        return f"{stat.st_mtime_ns}:{stat.st_size}"
    except OSError:
        return float("nan")



def split_blocks(text):
    """Split a text file into (name, body) blocks separated by blank lines.

    The first line of a block is its name when it looks like a heading — short,
    no sentence-ending punctuation — and the rest is the body. A block with no
    such heading keeps its whole text as the body and is named by position, so
    a plain list of paragraphs still works.
    """
    blocks = []
    for chunk in [c for c in text.replace("\r\n", "\n").split("\n\n")]:
        lines = [ln for ln in chunk.split("\n") if ln.strip()]
        if not lines:
            continue
        head = lines[0].strip()
        is_heading = (len(lines) > 1 and len(head) <= 60
                      and not head.endswith((".", ",", ":", ";")))
        if is_heading:
            blocks.append((head, "\n".join(lines[1:]).strip()))
        else:
            blocks.append((f"block_{len(blocks) + 1}", "\n".join(lines).strip()))
    return blocks


def select_blocks(blocks, index=-1):
    """All blocks, or just one. A single selection still comes back as a list.

    That is the whole trick: ComfyUI runs the graph once per item of a list
    output, so one item means one run and six mean six, with no rewiring.
    """
    if not blocks:
        return []
    if index is None or index < 0:
        return list(blocks)
    if index >= len(blocks):
        raise ValueError(
            f"index {index} is past the end — the file has {len(blocks)} blocks")
    return [blocks[index]]
