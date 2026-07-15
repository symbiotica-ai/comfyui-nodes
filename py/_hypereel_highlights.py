# ABOUTME: Parses Gemini highlight lists (HIGHLIGHT n | start=.. | end=.. | label |
# ABOUTME: WHY:.. | MOOD:..) into structured dicts. Accepts seconds, MM:SS and HH:MM:SS.
import re

_HEAD = re.compile(r"^(?:HIGHLIGHT\s*\d*|BEST)$", re.IGNORECASE)


def parse_timestamp(text):
    """'2674' / '12.5' -> seconds; 'MM:SS' / 'HH:MM:SS' -> seconds; junk -> None."""
    text = (text or "").strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    m = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2})", text)
    if m:
        h = int(m.group(1) or 0)
        return float(h * 3600 + int(m.group(2)) * 60 + int(m.group(3)))
    return None


def parse_highlights(text):
    """Every line carrying start=/end= fields becomes a highlight dict:
    { start, end, label, why, mood, line } — `line` is the pipe-joined row,
    ready to hand to the script-writing LLM. The BEST summary line and any
    surrounding prose are skipped."""
    out = []
    for raw in (text or "").splitlines():
        if "start=" not in raw or "end=" not in raw:
            continue
        fields = [f.strip() for f in raw.split("|")]
        if any(_HEAD.fullmatch(f) for f in fields if f) and fields[0].strip().upper().startswith("BEST"):
            continue  # "BEST start=.. end=.." recap, not a highlight row
        start = end = None
        label = why = mood = ""
        for f in fields:
            low = f.lower()
            if low.startswith("start="):
                start = parse_timestamp(f[len("start="):])
            elif low.startswith("end="):
                end = parse_timestamp(f[len("end="):])
            elif low.startswith("why:"):
                why = f[len("why:"):].strip()
            elif low.startswith("mood:"):
                mood = f[len("mood:"):].strip()
            elif f and "=" not in f and not _HEAD.fullmatch(f):
                label = label or f
        if start is None or end is None:
            continue
        out.append({
            "start": start,
            "end": end,
            "label": label,
            "why": why,
            "mood": mood,
            "line": f"HIGHLIGHT | {label} | WHY: {why} | MOOD: {mood}",
        })
    return out


def filter_in_range(highlights, source_duration):
    """Splits highlights into (kept, dropped) by whether their window fits inside
    a source_duration-second video. 0 = unknown duration -> keep everything."""
    if not source_duration or source_duration <= 0:
        return (list(highlights), [])
    kept = [h for h in highlights if h["start"] < source_duration]
    dropped = [h for h in highlights if h["start"] >= source_duration]
    return (kept, dropped)
