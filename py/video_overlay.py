# ABOUTME: Video overlay node for compositing images or videos on top of base video
# ABOUTME: Supports blend modes, positioning presets, opacity, and scale via FFmpeg

import os
import subprocess
import tempfile
import time
import shutil
import json

import folder_paths

from ._bins import FFMPEG, FFPROBE

NODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Pre-rendered overlay templates with alpha (WebM/VP8/yuva420p).
# Paths are relative to NODE_DIR.
OVERLAY_PRESETS = {
    "None": None,
    "TikTok": "assets/overlays/tiktok_overlay.webm",
    "Instagram": "assets/overlays/instagram_overlay.webm",
    "Facebook": "assets/overlays/facebook_overlay.webm",
}


class NSVideoOverlay:
    """
    Composites an image or video overlay onto a base video using FFmpeg.
    Supports blend modes, position presets, opacity, and scale.
    Useful for interface frames, animated overlays, watermarks, and borders.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
            },
            "optional": {
                "overlay_preset": (list(OVERLAY_PRESETS.keys()),
                                   {"default": "None"}),
                "image": ("IMAGE",),
                "overlay_video": ("VIDEO",),
                "position": (["Center", "Top Left", "Top Right",
                              "Bottom Left", "Bottom Right", "Custom"],
                             {"default": "Center"}),
                "x": ("INT", {"default": 0, "min": -5000, "max": 5000}),
                "y": ("INT", {"default": 0, "min": -5000, "max": 5000}),
                "scale": ("FLOAT", {"default": 1.0, "min": 0.1, "max": 5.0, "step": 0.05}),
                "opacity": ("FLOAT", {"default": 1.0, "min": 0.0, "max": 1.0, "step": 0.05}),
                "blend_mode": (["normal", "multiply", "screen", "overlay",
                                "soft_light", "hard_light", "darken", "lighten"],
                               {"default": "normal"}),
            }
        }

    RETURN_TYPES = ("VIDEO", "OVERLAY_SETTINGS")
    RETURN_NAMES = ("video", "overlay_settings")
    FUNCTION = "execute"
    CATEGORY = "neuralsins/Video"

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

    def _get_overlay_dimensions(self, path, is_video):
        """Get width and height of the overlay (image or video)."""
        if is_video:
            _, w, h, _ = self._get_video_info(path)
            return w, h
        result = subprocess.run(
            [FFPROBE, "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "json", path],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout)
        stream = data["streams"][0]
        return int(stream["width"]), int(stream["height"])

    def _calc_position(self, position, x, y, vw, vh, sw, sh):
        """Calculate overlay x, y based on position preset."""
        if position == "Center":
            return (vw - sw) // 2, (vh - sh) // 2
        elif position == "Top Left":
            return 0, 0
        elif position == "Top Right":
            return vw - sw, 0
        elif position == "Bottom Left":
            return 0, vh - sh
        elif position == "Bottom Right":
            return vw - sw, vh - sh
        else:  # Custom
            return x, y

    def _build_filter(self, settings, vw, vh, ow, oh, is_video):
        """Build the FFmpeg filter_complex string."""
        scale_factor = settings["scale"]
        opacity = settings["opacity"]
        blend_mode = settings["blend_mode"]

        sw = int(ow * scale_factor)
        sh = int(oh * scale_factor)
        # Ensure even dimensions for FFmpeg
        sw = sw + (sw % 2)
        sh = sh + (sh % 2)

        px, py = self._calc_position(
            settings["position"], settings["x"], settings["y"],
            vw, vh, sw, sh
        )

        if blend_mode == "normal":
            # Simple overlay — FFmpeg handles alpha natively
            parts = [
                f"[1:v]scale={sw}:{sh},format=rgba,colorchannelmixer=aa={opacity}[sc]",
                f"[0:v][sc]overlay=x={px}:y={py}:format=auto:eof_action=repeat[outv]",
            ]
        else:
            # Blend mode: crop overlay to visible area, pad to video size,
            # blend, then mask. Cropping prevents pad failure when overlay
            # is larger than the video.
            crop_x = max(0, -px)
            crop_y = max(0, -py)
            visible_w = max(2, min(sw - crop_x, vw - max(0, px)))
            visible_h = max(2, min(sh - crop_y, vh - max(0, py)))
            visible_w -= visible_w % 2
            visible_h -= visible_h % 2
            pad_x = max(0, px)
            pad_y = max(0, py)

            parts = [
                f"[1:v]scale={sw}:{sh},format=rgba,colorchannelmixer=aa={opacity},"
                f"crop={visible_w}:{visible_h}:{crop_x}:{crop_y}[sc]",
                f"[sc]split[prgb][palpha]",
                f"[palpha]alphaextract,pad={vw}:{vh}:{pad_x}:{pad_y}:color=black[mask]",
                f"[prgb]pad={vw}:{vh}:{pad_x}:{pad_y}:color=black@0[padded]",
                f"[0:v][padded]blend=all_mode={blend_mode}[blended]",
                f"[blended][0:v][mask]maskedmerge[outv]",
            ]

        return ";".join(parts)

    def _process_file(self, input_path, output_path, settings):
        """Apply overlay to a video file on disk. Used by execute() and NSVideoConcatMulti."""
        overlay_path = settings.get("overlay_path")
        if not overlay_path or not os.path.isfile(overlay_path):
            print("[NSVideoOverlay] No overlay file found, copying input")
            shutil.copy2(input_path, output_path)
            return

        is_video = settings.get("overlay_type") == "video"
        _, vw, vh, _ = self._get_video_info(input_path)
        ow, oh = self._get_overlay_dimensions(overlay_path, is_video)

        filter_complex = self._build_filter(settings, vw, vh, ow, oh, is_video)

        # Loop overlay to cover the whole video duration.
        is_webm = overlay_path.lower().endswith(".webm")
        if not is_video:
            overlay_inputs = ["-loop", "1", "-i", overlay_path]
        elif is_webm:
            # WebM VP8/VP9 with alpha needs libvpx decoder for transparency.
            overlay_inputs = [
                "-stream_loop", "-1",
                "-c:v", "libvpx", "-i", overlay_path,
            ]
        else:
            overlay_inputs = ["-stream_loop", "-1", "-i", overlay_path]

        cmd = [
            FFMPEG, "-y",
            "-i", input_path,
        ] + overlay_inputs + [
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "0:a?",
            "-c:v", "libx264", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            "-shortest",
            output_path,
        ]

        print(f"[NSVideoOverlay] Compositing overlay ({settings['blend_mode']})...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg overlay error:\n{result.stderr[-1000:]}"
            )

    def execute(self, video, overlay_preset="None", image=None,
                overlay_video=None, position="Center", x=0, y=0,
                scale=1.0, opacity=1.0, blend_mode="normal"):
        from comfy_api.latest import InputImpl

        has_overlay = (
            overlay_video is not None
            or image is not None
            or (overlay_preset != "None" and overlay_preset in OVERLAY_PRESETS)
        )
        if not has_overlay:
            print("[NSVideoOverlay] No overlay input, returning original video")
            settings = {
                "overlay_path": None,
                "overlay_type": None,
                "position": position,
                "x": x, "y": y,
                "scale": scale,
                "opacity": opacity,
                "blend_mode": blend_mode,
            }
            return (video, settings)

        temp_files = []
        try:
            # Save base video to temp
            original_path = tempfile.NamedTemporaryFile(
                suffix=".mp4", delete=False
            ).name
            temp_files.append(original_path)
            video.save_to(original_path, format="mp4", codec="h264")

            # Determine overlay type and save to persistent location
            output_dir = folder_paths.get_output_directory()
            timestamp = int(time.time())

            # Resolve overlay source: preset > overlay_video > image
            preset_rel = OVERLAY_PRESETS.get(overlay_preset)
            preset_path = None
            if preset_rel is not None:
                candidate = os.path.join(NODE_DIR, preset_rel)
                if os.path.isfile(candidate):
                    preset_path = candidate

            if preset_path is not None:
                overlay_type = "video"
                overlay_persist = preset_path
            elif overlay_video is not None:
                overlay_type = "video"
                overlay_persist = None

                # Try to use original file to preserve alpha channel.
                # ComfyUI's get_components/save_to strip alpha to RGB.
                try:
                    source = overlay_video.get_stream_source()
                    if isinstance(source, str) and os.path.isfile(source):
                        overlay_persist = source
                except (AttributeError, Exception):
                    pass

                if overlay_persist is None:
                    overlay_persist = os.path.join(
                        output_dir, f"overlay_{timestamp}.mp4"
                    )
                    overlay_video.save_to(
                        overlay_persist, format="mp4", codec="h264"
                    )
            else:
                overlay_type = "image"
                overlay_persist = os.path.join(
                    output_dir, f"overlay_{timestamp}.png"
                )
                from PIL import Image as PILImage
                import numpy as np
                img_np = image.cpu().numpy().squeeze()
                if img_np.max() <= 1.0:
                    img_np = (img_np * 255).astype(np.uint8)
                if img_np.ndim == 3 and img_np.shape[2] == 4:
                    pil_img = PILImage.fromarray(img_np, mode="RGBA")
                elif img_np.ndim == 3 and img_np.shape[2] == 3:
                    pil_img = PILImage.fromarray(img_np, mode="RGB")
                else:
                    pil_img = PILImage.fromarray(img_np)
                pil_img.save(overlay_persist, format="PNG")

            settings = {
                "overlay_path": overlay_persist,
                "overlay_type": overlay_type,
                "position": position,
                "x": x, "y": y,
                "scale": scale,
                "opacity": opacity,
                "blend_mode": blend_mode,
            }

            output_path = os.path.join(
                output_dir, f"overlaid_{timestamp}.mp4"
            )

            self._process_file(original_path, output_path, settings)

            print(f"[NSVideoOverlay] Done → {output_path}")
            return (InputImpl.VideoFromFile(output_path), settings)

        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass


NODE_CLASS_MAPPINGS = {
    "NSVideoOverlay": NSVideoOverlay
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSVideoOverlay": "NS Video Overlay"
}
