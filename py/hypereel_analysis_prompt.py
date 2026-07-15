# ABOUTME: Hypereel analysis prompt node — probes the video's real duration and writes
# ABOUTME: it into the Gemini prompt as a hard timestamp boundary. One clock, any length.
import os
import tempfile

from ._bins import FFPROBE
from ._hypereel_ffmpeg import probe_duration
from ._hypereel_highlights import build_analysis_prompt

DEFAULT_TASK = (
    "Watch the whole video and return the 3-6 most viral-worthy moments (big plays, "
    "kills, clutch escapes, funny fails, dramatic reveals), best first, one per line, "
    "exactly:\n\n"
    "HIGHLIGHT <n> | start=MM:SS | end=MM:SS | <punchy label> | WHY: <what happens on "
    "screen> | EVIDENCE: <exact subtitle/HUD text or visual detail visible at the start "
    "time> | MOOD: <hype/tense/funny/clutch/brutal/close-call>\n\n"
    "Before writing each line, verify: does your EVIDENCE actually appear at that start "
    "time in this video? If not, fix the time or drop the moment."
)


class HypereelAnalysisPrompt:
    """Builds the highlight-analysis prompt from the video itself: the real duration
    becomes the timestamp boundary line, and the same number feeds Highlight Pick's
    source_duration guard — the prompt and the guard can never disagree."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
                "task": ("STRING", {"multiline": True, "default": DEFAULT_TASK}),
            }
        }

    RETURN_TYPES = ("STRING", "FLOAT", "STRING")
    RETURN_NAMES = ("prompt", "duration_sec", "duration_mmss")
    FUNCTION = "build"
    CATEGORY = "Symbiotica/Hypereel"

    def build(self, video, task):
        from ._hypereel_highlights import fmt_mmss

        src = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
        try:
            video.save_to(src, format="mp4", codec="h264")
            duration = probe_duration(FFPROBE, src)
        finally:
            try:
                os.unlink(src)
            except OSError:
                pass
        return (build_analysis_prompt(duration, task), duration,
                fmt_mmss(duration) if duration > 0 else "")


NODE_CLASS_MAPPINGS = {
    "HypereelAnalysisPrompt": HypereelAnalysisPrompt,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HypereelAnalysisPrompt": "Hypereel Analysis Prompt (auto duration)",
}
