# ABOUTME: Path containment for the HTTP routes — resolves a caller-supplied value
# ABOUTME: inside a declared root, or refuses. Roots are declared, never caller-supplied.
from __future__ import annotations

import os


def resolve_within(roots, value, *, exts=None, kind="any") -> str | None:
    """The realpath of `value` when it lies inside one of `roots`, else None.

    The caller must use exactly the returned path. Resolving `value` a second
    time reopens the check-then-use race this closes, because the path can be
    replaced by a symlink between the two resolutions.

    Both sides are resolved before comparing, so a symlink pointing out of a
    root is refused rather than followed, and `..` cannot climb out. Matching is
    on a path-separator boundary, so the root `/a/root` does not admit
    `/a/root-evil`.

    `roots` that are not directories are ignored, and the filesystem root is
    never a usable root — treating "/" as one would make containment vacuous
    while still looking like a check.

    `exts` (a set of lowercase suffixes) and `kind` ("file", "dir", or "any")
    narrow what may be returned. Anything unusable — an empty value, a relative
    path, an embedded null byte — is a refusal, not an exception, because these
    arrive straight off an HTTP query string.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        if not os.path.isabs(value):
            return None
        if exts is not None and os.path.splitext(value)[1].lower() not in exts:
            return None
        real = os.path.realpath(value)
        if kind == "file" and not os.path.isfile(real):
            return None
        if kind == "dir" and not os.path.isdir(real):
            return None
        if kind == "any" and not os.path.exists(real):
            return None
        for root in roots or ():
            if not root or not isinstance(root, str):
                continue
            real_root = os.path.realpath(root)
            if real_root == os.sep or not os.path.isdir(real_root):
                continue
            if real == real_root or real.startswith(real_root + os.sep):
                return real
        return None
    except (ValueError, OSError):
        # Malformed input (e.g. an embedded null byte) is a deny, not a 500.
        return None
