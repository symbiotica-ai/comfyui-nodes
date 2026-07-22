# ABOUTME: Parses the script LLM's trailing "DURATION: N" line into a clamped
# ABOUTME: seconds value plus the clean prompt for the video node.
import re

MIN_SECONDS = 4
MAX_SECONDS = 15
DEFAULT_SECONDS = 12

_TAG = re.compile(r"\n\s*duration:\s*(\d+)\s*$", re.IGNORECASE)


def parse_duration(text):
    """(clean_text, seconds) from a script whose LAST line may be `DURATION: N`.

    Only a trailing tag counts — a duration mentioned mid-text is prompt
    content, not a directive. Missing tag falls back to DEFAULT_SECONDS; the
    value is clamped to the model's 4-15s range.
    """
    m = _TAG.search(text.rstrip())
    if not m:
        return text, DEFAULT_SECONDS
    seconds = max(MIN_SECONDS, min(MAX_SECONDS, int(m.group(1))))
    clean = text.rstrip()[: m.start()].rstrip()
    return clean, seconds
