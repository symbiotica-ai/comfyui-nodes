# ABOUTME: Sound effects node that places ElevenLabs-generated SFX onto a video timeline
# ABOUTME: Takes JSON cues (time, sfx, duration, volume) and mixes audio with FFmpeg

import os
import re
import json
import subprocess
import tempfile
import time

import requests
import folder_paths

from ._bins import FFMPEG, FFPROBE

ELEVENLABS_SFX_URL = "https://api.elevenlabs.io/v1/sound-generation"


class NSSoundEffects:
    """
    Mixes ElevenLabs-generated sound effects onto a video at millisecond-precise timestamps.
    Accepts a JSON array of cues from NS LLM. ElevenLabs generates each SFX as MP3.
    FFmpeg mixes all SFX onto the video audio track without re-encoding video.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
                "sfx_cues": ("STRING", {"multiline": True}),
                "api_key": ("STRING", {"multiline": False}),
            },
            "optional": {
                "volume": ("FLOAT", {"default": 0.8, "min": 0.0, "max": 2.0, "step": 0.05}),
                "prompt_influence": ("FLOAT", {"default": 0.7, "min": 0.0, "max": 1.0, "step": 0.05}),
            }
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "execute"
    CATEGORY = "neuralsins/Video"

    def _has_audio(self, path):
        """Check if a video file has an audio stream."""
        result = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
            capture_output=True, text=True
        )
        return result.stdout.strip() != ""

    def _call_elevenlabs(self, api_key, sfx_text, duration, prompt_influence, temp_files):
        """Call ElevenLabs sound-generation API, return path to downloaded MP3."""
        payload = {"text": sfx_text, "prompt_influence": prompt_influence}
        if duration is not None:
            clamped = max(0.5, min(22.0, float(duration)))
            payload["duration_seconds"] = clamped

        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        }

        response = requests.post(
            ELEVENLABS_SFX_URL,
            json=payload,
            headers=headers,
            timeout=60,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"ElevenLabs API error {response.status_code}: {response.text[:300]}"
            )

        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        temp_files.append(tmp.name)
        tmp.write(response.content)
        tmp.close()
        return tmp.name

    def _build_filter_complex(self, cues, has_original_audio, global_volume):
        """Build FFmpeg filter_complex string for mixing SFX at precise timestamps."""
        parts = []

        for i, cue in enumerate(cues):
            delay_ms = int(float(cue["time"]) * 1000)
            cue_vol = float(cue.get("volume", 1.0)) * global_volume
            # Input index i+1 because index 0 is the video
            parts.append(
                f"[{i + 1}:a]adelay={delay_ms}|{delay_ms},volume={cue_vol:.4f}[s{i}]"
            )

        sfx_labels = "".join(f"[s{i}]" for i in range(len(cues)))

        if has_original_audio:
            num_inputs = len(cues) + 1
            parts.append(
                f"[0:a]{sfx_labels}amix=inputs={num_inputs}:duration=first:normalize=0[outa]"
            )
        else:
            num_inputs = len(cues)
            parts.append(
                f"{sfx_labels}amix=inputs={num_inputs}:duration=longest:normalize=0[outa]"
            )

        return ";".join(parts)

    def execute(self, video, sfx_cues, api_key, volume=0.8, prompt_influence=0.7):
        from comfy_api.latest import InputImpl

        # Strip markdown fences if present
        text = sfx_cues.strip()
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()

        # Parse JSON
        try:
            raw_cues = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"[NSSoundEffects] Invalid JSON in sfx_cues: {e} — returning original video")
            return (video,)

        if not isinstance(raw_cues, list):
            print("[NSSoundEffects] sfx_cues must be a JSON array — returning original video")
            return (video,)

        # Validate and drop malformed cues
        valid_cues = []
        for i, cue in enumerate(raw_cues):
            if not isinstance(cue, dict):
                print(f"[NSSoundEffects] Cue {i} is not an object, skipping")
                continue
            if not isinstance(cue.get("time"), (int, float)):
                print(f"[NSSoundEffects] Cue {i} missing valid 'time', skipping")
                continue
            if not isinstance(cue.get("sfx"), str) or not cue["sfx"].strip():
                print(f"[NSSoundEffects] Cue {i} missing valid 'sfx', skipping")
                continue
            valid_cues.append(cue)

        if not valid_cues:
            print("[NSSoundEffects] No valid cues — returning original video")
            return (video,)

        print(f"[NSSoundEffects] Processing {len(valid_cues)} SFX cue(s)...")

        temp_files = []
        try:
            # Save video to temp file
            video_tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            temp_files.append(video_tmp.name)
            video_tmp.close()
            video.save_to(video_tmp.name, format="mp4", codec="h264")

            has_original_audio = self._has_audio(video_tmp.name)
            print(f"[NSSoundEffects] Video has audio: {has_original_audio}")

            # Generate each SFX via ElevenLabs
            sfx_paths = []
            for i, cue in enumerate(valid_cues):
                duration = cue.get("duration")
                print(f"[NSSoundEffects] Generating SFX {i + 1}/{len(valid_cues)}: \"{cue['sfx'][:60]}\"")
                path = self._call_elevenlabs(api_key, cue["sfx"], duration, prompt_influence, temp_files)
                sfx_paths.append(path)

            # Build FFmpeg command
            filter_complex = self._build_filter_complex(valid_cues, has_original_audio, volume)

            inputs = ["-i", video_tmp.name]
            for sfx_path in sfx_paths:
                inputs += ["-i", sfx_path]

            output_dir = folder_paths.get_output_directory()
            output_path = os.path.join(output_dir, f"sfx_{int(time.time())}.mp4")

            cmd = (
                [FFMPEG, "-y"]
                + inputs
                + ["-filter_complex", filter_complex]
                + ["-map", "0:v", "-map", "[outa]"]
                + ["-c:v", "copy", "-c:a", "aac"]
                + [output_path]
            )

            print(f"[NSSoundEffects] Mixing with FFmpeg...")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg error: {result.stderr[-500:]}")

            print(f"[NSSoundEffects] Done -> {output_path}")
            return (InputImpl.VideoFromFile(output_path),)

        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass


NODE_CLASS_MAPPINGS = {"NSSoundEffects": NSSoundEffects}
NODE_DISPLAY_NAME_MAPPINGS = {"NSSoundEffects": "NS Sound Effects"}
