# ABOUTME: Video component extraction node — splits VIDEO into video, audio, and fps
# ABOUTME: Alternative to ComfyUI's Get Video Components with VIDEO output instead of image frames

import os
import subprocess
import tempfile
import json

import torch

from ._bins import FFMPEG, FFPROBE


class NSGetVideoComponents:
    """
    Splits a VIDEO into its components: video passthrough, audio, and fps.
    Unlike ComfyUI's Get Video Components, outputs VIDEO instead of image frames.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
            }
        }

    RETURN_TYPES = ("VIDEO", "AUDIO", "FLOAT")
    RETURN_NAMES = ("video", "audio", "fps")
    FUNCTION = "execute"
    CATEGORY = "neuralsins/Video"

    def execute(self, video):
        temp_files = []
        try:
            video_path = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
            temp_files.append(video_path)
            video.save_to(video_path, format="mp4", codec="h264")

            fps = self._get_fps(video_path)
            audio = self._extract_audio(video_path, temp_files)

            return (video, audio, fps)

        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass

    def _get_fps(self, video_path):
        """Get fps from video via ffprobe."""
        result = subprocess.run(
            [FFPROBE, "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=r_frame_rate",
             "-of", "json", video_path],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout)
        num, den = data["streams"][0]["r_frame_rate"].split("/")
        return float(num) / float(den)

    def _extract_audio(self, video_path, temp_files):
        """Extract audio from video and return as ComfyUI AUDIO dict."""
        wav_path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        temp_files.append(wav_path)

        cmd = [
            FFMPEG, "-y", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            wav_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print("[NSGetVideoComponents] No audio stream found, returning silence")
            return {"waveform": torch.zeros(1, 2, 44100), "sample_rate": 44100}

        try:
            import torchaudio
            waveform, sample_rate = torchaudio.load(wav_path)
            return {"waveform": waveform.unsqueeze(0), "sample_rate": sample_rate}
        except ImportError:
            pass

        # Fallback: scipy
        import numpy as np
        import scipy.io.wavfile as wavfile
        sample_rate, data = wavfile.read(wav_path)
        if data.ndim == 1:
            data = data[:, None]
        waveform = torch.from_numpy(data.T.astype("float32") / 32768.0).unsqueeze(0)
        return {"waveform": waveform, "sample_rate": sample_rate}


class NSCreateVideo:
    """
    Combines a VIDEO with optional AUDIO and fps into a single VIDEO.
    Inverse of NS Get Video Components — muxes audio onto video, optionally retimes fps.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
            },
            "optional": {
                "audio": ("AUDIO",),
                "fps": ("FLOAT", {"default": 30.0, "min": 1.0, "max": 120.0, "step": 0.01}),
            }
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "execute"
    CATEGORY = "neuralsins/Video"

    def execute(self, video, audio=None, fps=None):
        from comfy_api.latest import InputImpl
        import time
        import folder_paths

        temp_files = []
        try:
            video_path = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
            temp_files.append(video_path)
            video.save_to(video_path, format="mp4", codec="h264")

            inputs = [FFMPEG, "-y", "-i", video_path]
            filter_parts = []
            map_args = ["-map", "0:v"]

            # Write audio tensor to temp WAV if provided
            if audio is not None:
                wav_path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
                temp_files.append(wav_path)
                self._save_audio(audio, wav_path)
                inputs += ["-i", wav_path]
                map_args += ["-map", "1:a"]
            else:
                map_args += ["-map", "0:a?"]

            # fps filter
            if fps is not None:
                filter_parts.append(f"fps={fps}")

            output_path = os.path.join(
                folder_paths.get_output_directory(),
                f"created_{int(time.time())}.mp4"
            )

            cmd = inputs
            if filter_parts:
                cmd += ["-vf", ",".join(filter_parts)]
            cmd += map_args
            cmd += ["-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", output_path]

            print("[NSCreateVideo] Muxing video + audio...")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg error:\n{result.stderr[-500:]}")

            print(f"[NSCreateVideo] Done → {output_path}")
            return (InputImpl.VideoFromFile(output_path),)

        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass

    def _save_audio(self, audio, wav_path):
        """Write a ComfyUI AUDIO dict to a WAV file."""
        waveform = audio["waveform"]
        sample_rate = audio["sample_rate"]

        # Remove batch dim if present: (1, C, S) → (C, S)
        if waveform.dim() == 3:
            waveform = waveform.squeeze(0)

        try:
            import torchaudio
            torchaudio.save(wav_path, waveform, sample_rate)
            return
        except ImportError:
            pass

        import numpy as np
        import scipy.io.wavfile as wavfile
        data = (waveform.numpy().T * 32768).astype("int16")
        wavfile.write(wav_path, sample_rate, data)


NODE_CLASS_MAPPINGS = {
    "NSGetVideoComponents": NSGetVideoComponents,
    "NSCreateVideo": NSCreateVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSGetVideoComponents": "NS Get Video Components",
    "NSCreateVideo": "NS Create Video",
}
