# ABOUTME: Parses an LLM's enhanced per-region prompt list (strict JSON or
# ABOUTME: numbered lines) into one string per region, in region order.
#
# The LLM enhancer returns one production prompt per template region; these
# fan out to ERPK Regional Prompt Builder's desc_N sockets, which override
# each canvas region's description at execute time. Parsing is tolerant
# because LLMs wrap output in fences or drift to numbered lists.
from __future__ import annotations

import json
import re

_FENCE = re.compile(r"^```[a-zA-Z]*\n|\n?```$")
_NUMBERED = re.compile(r"^\s*(\d+)[.)]\s*", re.MULTILINE)


def _from_json(data) -> list[str] | None:
    if isinstance(data, dict):
        for key in ("regions", "prompts", "descs"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            return None
    if not isinstance(data, list):
        return None
    out = []
    for entry in data:
        if isinstance(entry, str):
            out.append(entry.strip())
        elif isinstance(entry, dict):
            for key in ("desc", "prompt", "text"):
                if isinstance(entry.get(key), str) and entry[key].strip():
                    out.append(entry[key].strip())
                    break
            else:
                out.append("")
        else:
            out.append("")
    return out


def parse_region_prompts(text: str, max_n: int = 10) -> list[str]:
    """One enhanced prompt per region from LLM output, padded/truncated to
    max_n entries (empty string = leave that region's description alone)."""
    raw = _FENCE.sub("", (text or "").strip()).strip()
    prompts: list[str] | None = None
    if raw:
        try:
            prompts = _from_json(json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            prompts = None
        if prompts is None:
            matches = list(_NUMBERED.finditer(raw))
            if matches:
                prompts = []
                for i, m in enumerate(matches):
                    end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
                    prompts.append(raw[m.end():end].strip())
    prompts = prompts or []
    prompts = [p.replace("\n", " ").strip() for p in prompts[:max_n]]
    prompts += [""] * (max_n - len(prompts))
    return prompts
