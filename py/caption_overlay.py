# ABOUTME: Animated caption overlay node using Remotion for rendering
# ABOUTME: Composites spring-animated word-by-word captions onto video via FFmpeg

import os
import subprocess
import tempfile
import json
import shutil
import time

import folder_paths

from . import _whisper_models
from ._bins import FFMPEG, FFPROBE, NODE_BIN, NPX_BIN, NPM_BIN

REMOTION_DIR = os.path.join(os.path.dirname(__file__), "..", "remotion")
REMOTION_BUNDLE = os.path.join(REMOTION_DIR, "bundle")

# ComfyUI.app has a restricted PATH — ensure node/npm directories are included
_node_dir = os.path.dirname(NODE_BIN)
_env = os.environ.copy()
_env["PATH"] = _node_dir + ":" + _env.get("PATH", "")

_deps_checked = False


class NSCaptionOverlay:
    """
    Renders animated captions (word-by-word highlighting, spring animations,
    emoji reactions) onto a video using Remotion + FFmpeg.
    Runs Whisper internally if no transcript is connected.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
            },
            "optional": {
                "caption_style": ("CAPTION_STYLE",),
                "transcript": ("TRANSCRIPT",),
            }
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "execute"
    CATEGORY = "neuralsins/Video"

    def _ensure_deps(self):
        """Check Node.js is available and Remotion dependencies are installed."""
        global _deps_checked
        if _deps_checked:
            return

        if not os.path.isfile(NODE_BIN):
            raise RuntimeError(
                "Node.js not found. Install it from https://nodejs.org/ "
                "and restart ComfyUI."
            )

        # Check for a specific file that only exists after a complete install,
        # not just the node_modules directory (which may be partial/corrupted).
        cli_entry = os.path.join(
            REMOTION_DIR, "node_modules", "@remotion", "cli", "dist", "config", "index.js"
        )
        if not os.path.isfile(cli_entry):
            print("[NSCaptionOverlay] Installing Remotion dependencies...")
            result = subprocess.run(
                [NPM_BIN, "install"],
                cwd=REMOTION_DIR,
                capture_output=True, text=True,
                env=_env,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"npm install failed in remotion/:\n{result.stderr[-1000:]}"
                )
            print("[NSCaptionOverlay] Dependencies installed.")

        # Pre-build the Remotion bundle so renders skip TypeScript compilation
        bundle_index = os.path.join(REMOTION_BUNDLE, "index.html")
        if not os.path.isfile(bundle_index):
            print("[NSCaptionOverlay] Building Remotion bundle...")
            result = subprocess.run(
                [NPX_BIN, "remotion", "bundle", "src/index.ts",
                 f"--out-dir={REMOTION_BUNDLE}"],
                cwd=REMOTION_DIR,
                capture_output=True, text=True,
                env=_env,
            )
            if result.returncode != 0:
                print(f"[NSCaptionOverlay] Bundle build failed, will use source: "
                      f"{result.stderr[-500:]}")
            else:
                print("[NSCaptionOverlay] Bundle built.")

        _deps_checked = True

    def _get_video_info(self, path):
        """Get fps, width, height, and duration from a video file."""
        result = subprocess.run(
            [FFPROBE, "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate",
             "-show_entries", "format=duration",
             "-of", "json", path],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
        stream = data["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
        num, den = stream["r_frame_rate"].split("/")
        fps = float(num) / float(den)
        return fps, width, height, duration

    def _get_concurrency(self):
        """Detect available CPU cores, respecting cgroup limits on Linux pods."""
        try:
            n_cores = len(os.sched_getaffinity(0))
        except AttributeError:
            n_cores = os.cpu_count() or 1
        # Cap at 6 to avoid Chrome memory thrashing on pods
        return max(1, min(n_cores // 2, 6))

    @staticmethod
    def _kill_stale_chrome():
        """Kill leftover Chrome processes from previous renders."""
        import platform
        if platform.system() != "Linux":
            return
        subprocess.run(["pkill", "-9", "-f", "headless.*remotion"],
                       capture_output=True, text=True)
        time.sleep(1)

    def _render_sequence(self, props, frames_dir):
        """Render transparent caption overlay as a PNG image sequence."""
        props_path = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        )
        json.dump(props, props_path)
        props_path.close()

        try:
            concurrency = self._get_concurrency()
            entry = REMOTION_BUNDLE if os.path.isdir(REMOTION_BUNDLE) else "src/index.ts"
            cmd = [
                NPX_BIN, "remotion", "render",
                entry, "CaptionOverlay",
                f"--props={props_path.name}",
                "--sequence", "--image-format=png",
                f"--concurrency={concurrency}",
                f"--output={frames_dir}",
                "--log=error",
            ]
            n_frames = props['durationInFrames']
            render_timeout = max(600, n_frames * 3)
            print(f"[NSCaptionOverlay] Rendering {n_frames} frames "
                  f"(PNG sequence, concurrency={concurrency}, timeout={render_timeout}s)...")

            for attempt in range(3):
                result = subprocess.run(
                    cmd, cwd=REMOTION_DIR,
                    capture_output=True, text=True,
                    timeout=render_timeout,
                    env=_env,
                )
                if result.returncode == 0:
                    break
                if attempt < 2 and "Timed out" in result.stderr:
                    print(f"[NSCaptionOverlay] Chrome launch failed (attempt {attempt + 1}), cleaning up...")
                    self._kill_stale_chrome()
                    continue
                raise RuntimeError(
                    f"Remotion render failed:\n{result.stderr[-1500:]}"
                )
            print("[NSCaptionOverlay] Render complete.")
        finally:
            try:
                os.unlink(props_path.name)
            except OSError:
                pass

    def _overlay_sequence(self, input_path, frames_dir, fps, duration_in_frames, output_path):
        """Composite PNG caption sequence onto original video with FFmpeg."""
        pad_len = len(str(duration_in_frames - 1))
        png_pattern = os.path.join(frames_dir, f"element-%0{pad_len}d.png")
        cmd = [
            FFMPEG, "-y",
            "-i", input_path,
            "-framerate", str(round(fps)),
            "-start_number", "0",
            "-i", png_pattern,
            "-filter_complex", "[0:v][1:v]overlay=format=auto",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "copy",
            "-shortest",
            output_path,
        ]
        print(f"[NSCaptionOverlay] Compositing {duration_in_frames} frames with FFmpeg...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg overlay error:\n{result.stderr[-1000:]}")

    def _process_file(self, input_path, output_path, settings):
        """Apply caption overlay to a video file on disk. Used by execute() and NSVideoConcatMulti."""
        self._ensure_deps()

        words = settings.get("words", [])
        if not words:
            print("[NSCaptionOverlay] Empty words in settings, copying input")
            shutil.copy2(input_path, output_path)
            return

        frames_dir = None
        try:
            fps, width, height, duration = self._get_video_info(input_path)

            duration_in_frames = int(round(duration * fps))

            font_color = settings.get("fontColor", "")
            highlight_color = settings.get("highlightColor", "")

            props = {
                "words": words,
                "template": settings.get("template", "Hormozi"),
                "animation": settings.get("animation", "Pop"),
                "position": settings.get("position", 75),
                "fontSize": settings.get("fontSize", 58),
                "wordsPerLine": settings.get("wordsPerLine", 3),
                "fontColor": font_color if isinstance(font_color, str) and font_color else None,
                "highlightColor": highlight_color if isinstance(highlight_color, str) and highlight_color else None,
                "emojis": settings.get("emojis", True),
                "width": width,
                "height": height,
                "fps": round(fps),
                "durationInFrames": duration_in_frames,
            }

            # Render transparent caption overlay as PNG sequence (fast — no video in Chrome)
            frames_dir = tempfile.mkdtemp(prefix="caption_frames_")
            self._render_sequence(props, frames_dir)

            # Composite PNGs onto original video with FFmpeg
            self._overlay_sequence(input_path, frames_dir, fps, duration_in_frames, output_path)

        finally:
            if frames_dir:
                shutil.rmtree(frames_dir, ignore_errors=True)

    def _transcribe(self, video_path, language, model_size):
        """Run Whisper on a video file and return word list."""
        from faster_whisper import WhisperModel

        wav_path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        try:
            cmd = [
                FFMPEG, "-y", "-i", video_path,
                "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                wav_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print("[NSCaptionOverlay] No audio stream, returning empty transcript")
                return []

            model_id = _whisper_models.resolve_model(model_size)
            print(f"[NSCaptionOverlay] Transcribing with whisper '{model_id}'...")
            try:
                import ctypes
                ctypes.cdll.LoadLibrary("libcublas.so.12")
                model = WhisperModel(model_id, compute_type="int8")
            except (OSError, Exception):
                print("[NSCaptionOverlay] CUDA not available, using CPU")
                model = WhisperModel(model_id, device="cpu", compute_type="float32")
            lang = None if language == "auto" else language
            segments, info = model.transcribe(
                wav_path, language=lang, word_timestamps=True, vad_filter=True
            )

            words = []
            for segment in segments:
                if segment.words:
                    for w in segment.words:
                        words.append({
                            "word": w.word.strip(),
                            "start": round(w.start, 3),
                            "end": round(w.end, 3),
                        })

            print(f"[NSCaptionOverlay] Transcription done: {len(words)} words, language={info.language}")
            return words
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

    def execute(self, video, caption_style=None, transcript=None):
        from comfy_api.latest import InputImpl

        style = caption_style or {}
        template = style.get("template", "Hormozi")
        animation = style.get("animation", "Pop")
        position = style.get("position", 75)
        font_size = style.get("fontSize", 58)
        words_per_line = style.get("wordsPerLine", 3)
        font_color = style.get("fontColor") or ""
        highlight_color = style.get("highlightColor") or ""
        emojis = style.get("emojis", True)
        language = style.get("language", "auto")
        whisper_model = style.get("whisper_model", "base")

        settings = {
            "words": [],
            "template": template,
            "animation": animation,
            "position": position,
            "fontSize": font_size,
            "wordsPerLine": words_per_line,
            "fontColor": font_color if font_color else None,
            "highlightColor": highlight_color if highlight_color else None,
            "emojis": emojis,
        }

        temp_files = []
        try:
            original_path = tempfile.NamedTemporaryFile(
                suffix=".mp4", delete=False
            ).name
            temp_files.append(original_path)
            video.save_to(original_path, format="mp4", codec="h264")

            # Use provided transcript or run internal whisper
            # Handle both dict (from Whisper nodes) and JSON string (from LLM nodes)
            if transcript:
                if isinstance(transcript, str):
                    import json
                    import re
                    # Strip markdown code fences (```json ... ```)
                    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", transcript.strip())
                    cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()
                    try:
                        transcript = json.loads(cleaned)
                    except (json.JSONDecodeError, ValueError):
                        transcript = None
                if isinstance(transcript, dict) and transcript.get("words"):
                    words = transcript["words"]
                    print(f"[NSCaptionOverlay] Using provided transcript ({len(words)} words)")
                else:
                    transcript = None
            if not transcript:
                words = self._transcribe(original_path, language, whisper_model)

            if not words:
                print("[NSCaptionOverlay] No speech detected, returning original video")
                return (video,)

            # Clean punctuation artifacts from words (em dashes, quotes, etc.)
            for w in words:
                w["word"] = w["word"].strip("\u2013\u2014-\"'\u00ab\u00bb\u201e\u201c\u201d")
            words = [w for w in words if w["word"]]

            settings["words"] = words

            output_dir = folder_paths.get_output_directory()
            output_path = os.path.join(
                output_dir, f"captioned_{int(time.time())}.mp4"
            )

            self._process_file(original_path, output_path, settings)

            print(f"[NSCaptionOverlay] Done → {output_path}")
            return (InputImpl.VideoFromFile(output_path),)

        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass


class NSCaptionStyle:
    """
    Shared caption style settings. Connect to multiple NS Video Captions nodes
    so one change updates all of them at once.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {},
            "optional": {
                "template": (["Hormozi", "Beast", "Clean", "Neon", "Minimal"],
                             {"default": "Hormozi"}),
                "animation": (["Pop", "Bounce", "Slam", "Karaoke", "Glow", "Rise"],
                              {"default": "Pop"}),
                "position": ("INT", {"default": 75, "min": 0, "max": 100, "step": 1}),
                "font_size": ("INT", {"default": 58, "min": 20, "max": 120, "step": 1}),
                "words_per_line": ("INT", {"default": 3, "min": 1, "max": 8, "step": 1}),
                "font_color": ("STRING", {"default": ""}),
                "highlight_color": ("STRING", {"default": ""}),
                "emojis": ("BOOLEAN", {"default": True}),
                "language": (["auto", "en", "el", "es", "fr", "de", "it", "pt", "nl",
                              "ja", "ko", "zh", "ru", "ar", "hi", "cs", "pl",
                              "tr", "uk", "ro", "sv", "da", "fi", "no", "hu"],
                             {"default": "auto"}),
                "whisper_model": (_whisper_models.ALL_MODELS, {"default": "base"}),
            }
        }

    RETURN_TYPES = ("CAPTION_STYLE",)
    RETURN_NAMES = ("caption_style",)
    FUNCTION = "execute"
    CATEGORY = "neuralsins/Video"

    def execute(self, template="Hormozi", animation="Pop", position=75, font_size=58,
                words_per_line=3, font_color="", highlight_color="", emojis=True,
                language="auto", whisper_model="base"):
        return ({
            "template": template,
            "animation": animation,
            "position": position,
            "fontSize": font_size,
            "wordsPerLine": words_per_line,
            "fontColor": font_color if isinstance(font_color, str) and font_color else None,
            "highlightColor": highlight_color if isinstance(highlight_color, str) and highlight_color else None,
            "emojis": emojis,
            "language": language,
            "whisper_model": whisper_model,
        },)


NODE_CLASS_MAPPINGS = {
    "NSCaptionOverlay": NSCaptionOverlay,
    "NSCaptionStyle": NSCaptionStyle,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSCaptionOverlay": "NS Video Captions",
    "NSCaptionStyle": "NS Caption Style",
}
