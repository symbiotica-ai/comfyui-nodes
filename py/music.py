# ABOUTME: Background music node that generates a continuous AI music track via ElevenLabs
# ABOUTME: Mixes generated music under the full video audio using FFmpeg

import os
import subprocess
import tempfile
import time

import wave
import struct

import torch
import requests
import folder_paths

from ._bins import FFMPEG, FFPROBE

ELEVENLABS_MUSIC_URL = "https://api.elevenlabs.io/v1/music"


class NSMusic:
    """
    Generates a background music track via ElevenLabs and mixes it under the video audio.
    Music length is auto-set from video duration. Supports silent videos as well.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "music_prompt": ("STRING", {"multiline": True}),
                "api_key": ("STRING", {"multiline": False}),
                "duration_sec": ("FLOAT", {"default": 30.0, "min": 3.0, "max": 600.0, "step": 1.0}),
            },
            "optional": {
                "video": ("VIDEO",),
                "volume": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 1.0, "step": 0.05}),
                "force_instrumental": ("BOOLEAN", {"default": True}),
                "duck": ("BOOLEAN", {"default": True}),
                "duck_ratio": ("FLOAT", {"default": 4.0, "min": 1.0, "max": 20.0, "step": 0.5}),
                "seed": ("INT", {"default": 0, "min": 0, "max": 0xffffffff}),
            }
        }

    RETURN_TYPES = ("VIDEO", "AUDIO")
    RETURN_NAMES = ("video", "audio")
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

    def _get_video_duration(self, path):
        """Return video duration in seconds as a float."""
        result = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True
        )
        return float(result.stdout.strip())

    def _wav_to_audio_out(self, wav_path):
        """Read a WAV file and return a ComfyUI AUDIO dict."""
        with wave.open(wav_path, "rb") as wf:
            n_channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            sample_rate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
        if sample_width == 2:
            samples = torch.frombuffer(bytearray(raw), dtype=torch.int16).float() / 32768.0
        else:
            samples = torch.frombuffer(bytearray(raw), dtype=torch.int32).float() / 2147483648.0
        waveform = samples.reshape(-1, n_channels).T
        return {"waveform": waveform.unsqueeze(0), "sample_rate": sample_rate}

    def _call_elevenlabs_music(self, api_key, prompt, duration_ms, force_instrumental, seed, temp_files):
        """Call ElevenLabs music API, return path to downloaded MP3."""
        payload = {
            "prompt": prompt,
            "music_length_ms": duration_ms,
            "force_instrumental": force_instrumental,
        }
        if seed > 0:
            payload["seed"] = seed

        headers = {
            "xi-api-key": api_key,
            "Content-Type": "application/json",
        }

        response = requests.post(
            ELEVENLABS_MUSIC_URL,
            json=payload,
            headers=headers,
            timeout=120,
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

    def execute(self, music_prompt, api_key, duration_sec=30.0, video=None,
                volume=0.3, force_instrumental=True, duck=True, duck_ratio=4.0, seed=0):
        from comfy_api.latest import InputImpl

        if not music_prompt.strip():
            print("[NSMusic] Empty music_prompt — returning unchanged")
            return (video, None)

        temp_files = []
        try:
            # Determine duration: from video if connected, else from duration_sec
            if video is not None:
                video_tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
                temp_files.append(video_tmp.name)
                video_tmp.close()
                video.save_to(video_tmp.name, format="mp4", codec="h264")
                duration_s = self._get_video_duration(video_tmp.name)
            else:
                video_tmp = None
                duration_s = duration_sec

            duration_ms = int(duration_s * 1000)
            MIN_MS, MAX_MS = 3000, 600000
            if duration_ms < MIN_MS:
                duration_ms = MIN_MS
            elif duration_ms > MAX_MS:
                duration_ms = MAX_MS
                print("[NSMusic] Duration capped at 600s — music will end before video")

            print(f"[NSMusic] Generating music ({duration_ms}ms): \"{music_prompt[:80]}\"")
            music_path = self._call_elevenlabs_music(
                api_key, music_prompt.strip(), duration_ms, force_instrumental, seed, temp_files
            )

            # No video — return leveled music as audio only (no speech to duck against)
            if video_tmp is None:
                music_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                temp_files.append(music_wav.name)
                music_wav.close()
                subprocess.run(
                    [FFMPEG, "-y", "-i", music_path, "-af", f"volume={volume:.4f}", music_wav.name],
                    capture_output=True, check=True
                )
                print("[NSMusic] No video input — returning audio only")
                return (None, self._wav_to_audio_out(music_wav.name))

            has_original_audio = self._has_audio(video_tmp.name)
            print(f"[NSMusic] Video has audio: {has_original_audio}")

            if has_original_audio:
                if duck:
                    video_filter = (
                        f"[0:a]asplit=2[speech][sc];"
                        f"[1:a]volume={volume:.4f}[music];"
                        f"[music][sc]sidechaincompress=threshold=0.02:ratio={duck_ratio:.1f}:attack=100:release=800[ducked];"
                        f"[speech][ducked]amix=inputs=2:duration=first:normalize=0[outa]"
                    )
                    # Audio pin: ducked music only, no speech mixed in
                    audio_filter = (
                        f"[1:a]volume={volume:.4f}[music];"
                        f"[music][0:a]sidechaincompress=threshold=0.02:ratio={duck_ratio:.1f}:attack=100:release=800[outa]"
                    )
                else:
                    video_filter = (
                        f"[1:a]volume={volume:.4f}[m];"
                        f"[0:a][m]amix=inputs=2:duration=first:normalize=0[outa]"
                    )
                    audio_filter = None
            else:
                video_filter = f"[1:a]volume={volume:.4f}[outa]"
                audio_filter = None

            output_dir = folder_paths.get_output_directory()
            output_path = os.path.join(output_dir, f"music_{int(time.time())}.mp4")

            cmd = (
                [FFMPEG, "-y", "-i", video_tmp.name, "-i", music_path]
                + ["-filter_complex", video_filter]
                + ["-map", "0:v", "-map", "[outa]"]
                + ["-c:v", "copy", "-c:a", "aac"]
                + [output_path]
            )

            print("[NSMusic] Mixing with FFmpeg...")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg error: {result.stderr[-500:]}")

            # Build audio output
            audio_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_files.append(audio_wav.name)
            audio_wav.close()
            if audio_filter:
                # Ducked music only (no speech) for the audio pin
                cmd_audio = (
                    [FFMPEG, "-y", "-i", video_tmp.name, "-i", music_path]
                    + ["-filter_complex", audio_filter]
                    + ["-map", "[outa]", "-vn"]
                    + [audio_wav.name]
                )
                result_audio = subprocess.run(cmd_audio, capture_output=True, text=True)
                if result_audio.returncode != 0:
                    raise RuntimeError(f"FFmpeg audio error: {result_audio.stderr[-500:]}")
            else:
                # No ducking — just apply volume to music
                subprocess.run(
                    [FFMPEG, "-y", "-i", music_path, "-af", f"volume={volume:.4f}", audio_wav.name],
                    capture_output=True, check=True
                )

            print(f"[NSMusic] Done -> {output_path}")
            return (InputImpl.VideoFromFile(output_path), self._wav_to_audio_out(audio_wav.name))

        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass


NODE_CLASS_MAPPINGS = {"NSMusic": NSMusic}
NODE_DISPLAY_NAME_MAPPINGS = {"NSMusic": "NS Music"}
