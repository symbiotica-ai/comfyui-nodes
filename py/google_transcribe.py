# ABOUTME: Cloud speech-to-text node using Google Cloud Speech-to-Text API.
# ABOUTME: Handles casual speech, code-switching, and loanwords better than local Whisper.

import base64
import configparser
import os
import subprocess
import tempfile
import time
import requests

from ._bins import FFMPEG, FFPROBE

GOOGLE_STT_URL = "https://speech.googleapis.com/v1/speech"

GOOGLE_LANGUAGES = [
    "el-GR", "en-US", "en-GB", "es-ES", "fr-FR", "de-DE",
    "it-IT", "pt-BR", "pt-PT", "nl-NL", "ja-JP", "ko-KR",
    "zh-CN", "zh-TW", "ru-RU", "ar-SA", "hi-IN", "cs-CZ",
    "pl-PL", "tr-TR", "uk-UA", "ro-RO", "sv-SE", "da-DK",
    "fi-FI", "no-NO", "hu-HU",
]


class NSGoogleTranscribe:
    """
    Transcribes speech using Google Cloud Speech-to-Text.
    Better than Whisper for casual speech, code-switching, and non-English languages.
    Outputs TRANSCRIPT compatible with NS Video Captions.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
                "language": (GOOGLE_LANGUAGES, {"default": "en-US"}),
            },
            "optional": {
                "api_key": ("STRING", {
                    "default": "",
                    "tooltip": "Google Cloud API key (or set in config.ini / GOOGLE_STT_API_KEY env var)",
                }),
                "model": (["latest_long", "latest_short", "default"], {
                    "default": "latest_long",
                    "tooltip": "latest_long for video/podcast, latest_short for quick commands",
                }),
                "alt_language": (["none"] + GOOGLE_LANGUAGES, {
                    "default": "none",
                    "tooltip": "Secondary language for mixed speech (e.g., en-US when Greek has English words)",
                }),
            },
        }

    RETURN_TYPES = ("TRANSCRIPT",)
    RETURN_NAMES = ("transcript",)
    FUNCTION = "execute"
    CATEGORY = "neuralsins/Video"

    def _resolve_api_key(self, api_key):
        """Resolve API key from widget, config.ini, or environment variable."""
        if api_key:
            return api_key

        parent_dir = os.path.join(os.path.dirname(__file__), "..")
        config_path = os.path.join(parent_dir, "config.ini")
        if os.path.exists(config_path):
            config = configparser.ConfigParser()
            config.read(config_path)
            key = config.get("API", "google_stt_api_key", fallback="")
            if key:
                return key

        key = os.environ.get("GOOGLE_STT_API_KEY", "")
        if key:
            return key

        raise ValueError(
            "Google STT API key not found. Provide via the api_key input, "
            "config.ini [API] google_stt_api_key, or GOOGLE_STT_API_KEY env var."
        )

    def _extract_audio_flac(self, video_path, temp_files):
        """Extract audio as FLAC 16kHz mono for Google STT."""
        flac_path = tempfile.NamedTemporaryFile(suffix=".flac", delete=False).name
        temp_files.append(flac_path)
        cmd = [
            FFMPEG, "-y", "-i", video_path,
            "-vn", "-acodec", "flac",
            "-ar", "16000", "-ac", "1",
            flac_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        return flac_path

    def _get_duration(self, path):
        """Get media duration in seconds."""
        result = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True,
        )
        return float(result.stdout.strip())

    def _parse_time(self, t):
        """Parse Google STT time offset ('1.500s' or {'seconds': 1, 'nanos': 500000000})."""
        if isinstance(t, str):
            stripped = t.rstrip("s")
            return float(stripped) if stripped else 0.0
        if isinstance(t, dict):
            return float(t.get("seconds", 0)) + float(t.get("nanos", 0)) / 1e9
        return 0.0

    def _parse_response(self, response):
        """Parse Google STT response into TRANSCRIPT format."""
        words = []
        full_text_parts = []

        for result in response.get("results", []):
            alternatives = result.get("alternatives", [])
            if not alternatives:
                continue
            alt = alternatives[0]
            transcript = alt.get("transcript", "").strip()
            if transcript:
                full_text_parts.append(transcript)

            for w in alt.get("words", []):
                start = self._parse_time(w.get("startTime", "0s"))
                end = self._parse_time(w.get("endTime", "0s"))
                words.append({
                    "word": w["word"],
                    "start": round(start, 3),
                    "end": round(end, 3),
                })

        full_text = " ".join(full_text_parts)
        print(f"[NSGoogleTranscribe] Done: {len(words)} words")
        return {"text": full_text, "words": words}

    def _recognize_sync(self, key, config, audio_content):
        """Synchronous recognition for audio <= 1 minute."""
        url = f"{GOOGLE_STT_URL}:recognize?key={key}"
        payload = {
            "config": config,
            "audio": {"content": audio_content},
        }
        print("[NSGoogleTranscribe] Transcribing (sync)...")
        resp = requests.post(url, json=payload, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Google STT error ({resp.status_code}): {resp.text[:500]}"
            )
        return self._parse_response(resp.json())

    def _recognize_async(self, key, config, audio_content):
        """Async recognition for audio > 1 minute."""
        url = f"{GOOGLE_STT_URL}:longrunningrecognize?key={key}"
        payload = {
            "config": config,
            "audio": {"content": audio_content},
        }
        print("[NSGoogleTranscribe] Transcribing (async, longer audio)...")
        resp = requests.post(url, json=payload, timeout=120)
        if resp.status_code != 200:
            raise RuntimeError(
                f"Google STT error ({resp.status_code}): {resp.text[:500]}"
            )

        op_name = resp.json()["name"]
        poll_url = f"https://speech.googleapis.com/v1/operations/{op_name}?key={key}"
        start = time.time()

        while time.time() - start < 600:
            poll_resp = requests.get(poll_url, timeout=30)
            if poll_resp.status_code != 200:
                raise RuntimeError(
                    f"Google STT poll error ({poll_resp.status_code}): {poll_resp.text[:500]}"
                )
            data = poll_resp.json()
            if data.get("done"):
                if "error" in data:
                    raise RuntimeError(f"Google STT failed: {data['error']}")
                return self._parse_response(data.get("response", {}))

            print("[NSGoogleTranscribe] Processing...")
            time.sleep(3)

        raise RuntimeError("Google STT timeout (600s)")

    def execute(self, video, language, api_key="", model="latest_long",
                alt_language="none"):
        key = self._resolve_api_key(api_key)
        temp_files = []

        try:
            video_path = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
            temp_files.append(video_path)
            video.save_to(video_path, format="mp4", codec="h264")

            flac_path = self._extract_audio_flac(video_path, temp_files)
            if flac_path is None:
                print("[NSGoogleTranscribe] No audio stream found")
                return ({"text": "", "words": []},)

            # Check file size — inline audio limit is ~10MB
            file_size = os.path.getsize(flac_path)
            if file_size > 10_000_000:
                raise RuntimeError(
                    f"Audio too large for inline transcription ({file_size / 1e6:.1f} MB). "
                    "Try trimming the video to under ~8 minutes."
                )

            with open(flac_path, "rb") as f:
                audio_content = base64.b64encode(f.read()).decode("utf-8")

            config = {
                "encoding": "FLAC",
                "sampleRateHertz": 16000,
                "languageCode": language,
                "enableWordTimeOffsets": True,
                "model": model,
                "useEnhanced": True,
                "enableAutomaticPunctuation": True,
            }

            if alt_language != "none":
                config["alternativeLanguageCodes"] = [alt_language]

            duration = self._get_duration(flac_path)
            print(f"[NSGoogleTranscribe] Audio: {duration:.1f}s, language={language}, model={model}")

            try:
                if duration <= 60:
                    transcript = self._recognize_sync(key, config, audio_content)
                else:
                    transcript = self._recognize_async(key, config, audio_content)
            except RuntimeError as e:
                if "not supported for language" in str(e) and config["model"] != "default":
                    print(f"[NSGoogleTranscribe] Model '{config['model']}' not available for {language}, falling back to 'default'")
                    config["model"] = "default"
                    config.pop("useEnhanced", None)
                    if duration <= 60:
                        transcript = self._recognize_sync(key, config, audio_content)
                    else:
                        transcript = self._recognize_async(key, config, audio_content)
                else:
                    raise

            return (transcript,)

        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass


NODE_CLASS_MAPPINGS = {"NSGoogleTranscribe": NSGoogleTranscribe}
NODE_DISPLAY_NAME_MAPPINGS = {"NSGoogleTranscribe": "NS Google Transcribe"}
