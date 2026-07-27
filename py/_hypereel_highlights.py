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
        label = why = mood = beats = ""
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
            elif low.startswith("beats:"):
                beats = f[len("beats:"):].strip()
            elif f and "=" not in f and not _HEAD.fullmatch(f):
                label = label or f
        if start is None or end is None:
            continue
        line = f"HIGHLIGHT | {label} | WHY: {why} | MOOD: {mood}"
        if beats:
            # The in-window event order rides along so the script LLM can pace the
            # reaction against the real beats (order words, never clock numbers).
            line = f"HIGHLIGHT | {label} | WHY: {why} | BEATS: {beats} | MOOD: {mood}"
        out.append({
            "start": start,
            "end": end,
            "label": label,
            "why": why,
            "mood": mood,
            "beats": beats,
            "line": line,
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


def fmt_mmss(seconds):
    """Seconds -> MM:SS (H:MM:SS past an hour) — Gemini's native timestamp format."""
    s = int(round(float(seconds)))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


def build_analysis_prompt(duration_sec, task):
    """Prepends the video's real duration as a hard timestamp boundary. Duration 0 =
    unknown -> just the task (the graph-side source_duration guard still applies)."""
    if not duration_sec or duration_sec <= 0:
        return task
    mmss = fmt_mmss(duration_sec)
    return (
        f"This video is exactly {mmss} long. Valid timestamps: 00:00 to {mmss}. "
        f"Any timestamp beyond {mmss} is a hard error.\n\n{task}"
    )
