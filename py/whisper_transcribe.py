# ABOUTME: Local speech-to-text transcription node using faster-whisper
# ABOUTME: Extracts word-level timestamps from video audio for caption generation

import os
import subprocess
import tempfile
from . import _whisper_models
from ._bins import FFMPEG


class NSWhisperTranscribe:
    """
    Transcribes speech from a video using faster-whisper (local, no API).
    Produces word-level timestamps for animated caption generation.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
            },
            "optional": {
                "language": (["auto", "en", "el", "es", "fr", "de", "it", "pt", "nl",
                              "ja", "ko", "zh", "ru", "ar", "hi", "cs", "pl",
                              "tr", "uk", "ro", "sv", "da", "fi", "no", "hu"],
                             {"default": "auto"}),
                "model_size": (_whisper_models.ALL_MODELS, {"default": "base"}),
                "initial_prompt": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "Text to bias Whisper toward (e.g., correct transcription from Gemini for accurate timestamps)",
                }),
            }
        }

    RETURN_TYPES = ("TRANSCRIPT",)
    RETURN_NAMES = ("transcript",)
    FUNCTION = "execute"
    CATEGORY = "neuralsins/Video"

    def _extract_text(self, prompt):
        """Extract plain text from initial_prompt — handles JSON, markdown fences, or plain text."""
        import json
        import re
        # Strip markdown code fences
        cleaned = re.sub(r"^```(?:json)?\s*\n?", "", prompt)
        cleaned = re.sub(r"\n?```\s*$", "", cleaned).strip()
        # Try parsing as JSON and extracting "text" field
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict) and "text" in data:
                return data["text"]
        except (json.JSONDecodeError, ValueError):
            pass
        return cleaned

    def _align_words(self, whisper_words, correct_text):
        """Map correct text onto Whisper's detected speech time range.

        Uses character-weighted proportional distribution — simple and predictable.
        Accurate enough for caption chunks (3+ words grouped together).
        """
        correct_tokens = correct_text.split()
        if not correct_tokens or not whisper_words:
            return whisper_words

        # If Whisper missed the beginning (first word > 0.5s), start from 0
        first_t = whisper_words[0]['start']
        time_start = 0.0 if first_t > 0.5 else first_t
        time_end = whisper_words[-1]['end']
        total_dur = time_end - time_start

        # Distribute time proportionally by character count
        char_weights = [len(w) + 1 for w in correct_tokens]
        total_weight = sum(char_weights)

        result = []
        t = time_start
        for word, weight in zip(correct_tokens, char_weights):
            word_dur = (weight / total_weight) * total_dur
            result.append({
                'word': word,
                'start': round(t, 3),
                'end': round(t + word_dur, 3),
            })
            t += word_dur

        print(f"[NSWhisperTranscribe] Aligned {len(result)} correct words "
              f"across {time_start:.1f}s–{time_end:.1f}s")
        return result

    def _extract_audio(self, video_path, temp_files):
        """Extract audio from video as 16kHz mono WAV for whisper."""
        wav_path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        temp_files.append(wav_path)

        cmd = [
            FFMPEG, "-y", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le",
            "-ar", "16000", "-ac", "1",
            wav_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return None  # No audio stream
        return wav_path

    def execute(self, video, language="auto", model_size="base", initial_prompt=""):
        from comfy_api.latest import InputImpl
        from faster_whisper import WhisperModel

        temp_files = []
        try:
            # Save video to temp file
            video_path = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
            temp_files.append(video_path)
            video.save_to(video_path, format="mp4", codec="h264")

            # Extract audio
            wav_path = self._extract_audio(video_path, temp_files)
            if wav_path is None:
                print("[NSWhisperTranscribe] No audio stream found, returning empty transcript")
                return ({"text": "", "words": []},)

            # Resolve model: custom path > fine-tuned lookup > standard size
            model_id = _whisper_models.resolve_model(model_size)
            print(f"[NSWhisperTranscribe] Loading model '{model_id}'...")
            try:
                import ctypes
                ctypes.cdll.LoadLibrary("libcublas.so.12")
                model = WhisperModel(model_id, compute_type="int8")
            except (OSError, Exception):
                print("[NSWhisperTranscribe] CUDA not available, using CPU")
                model = WhisperModel(model_id, device="cpu", compute_type="float32")

            lang = None if language == "auto" else language
            print(f"[NSWhisperTranscribe] Transcribing (language={language})...")

            transcribe_kwargs = {
                "language": lang,
                "word_timestamps": True,
                "vad_filter": True,
            }
            if initial_prompt and initial_prompt.strip():
                prompt_text = self._extract_text(initial_prompt.strip())
                transcribe_kwargs["initial_prompt"] = prompt_text
                print(f"[NSWhisperTranscribe] Using initial_prompt ({len(prompt_text)} chars)")

            segments, info = model.transcribe(wav_path, **transcribe_kwargs)

            # Collect words with timestamps
            words = []
            full_text_parts = []
            for segment in segments:
                full_text_parts.append(segment.text.strip())
                if segment.words:
                    for w in segment.words:
                        words.append({
                            "word": w.word.strip(),
                            "start": round(w.start, 3),
                            "end": round(w.end, 3),
                        })

            full_text = " ".join(full_text_parts)
            print(f"[NSWhisperTranscribe] Done: {len(words)} words, "
                  f"language={info.language} (prob={info.language_probability:.2f})")

            # If we have correct text from initial_prompt, align it to Whisper timestamps
            if words and initial_prompt and initial_prompt.strip():
                prompt_text = self._extract_text(initial_prompt.strip())
                if prompt_text:
                    words = self._align_words(words, prompt_text)
                    full_text = prompt_text

            return ({"text": full_text, "words": words},)

        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass


NODE_CLASS_MAPPINGS = {
    "NSWhisperTranscribe": NSWhisperTranscribe
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSWhisperTranscribe": "NS Whisper Transcribe"
}
