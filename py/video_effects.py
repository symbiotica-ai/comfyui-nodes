# ABOUTME: Video effects node (zoom, wiggle, face tracking) using Remotion for rendering
# ABOUTME: Applies camera effects to video independently from captions

import os
import subprocess
import tempfile
import json
import shutil
import time

import folder_paths

from ._bins import FFMPEG, FFPROBE, NODE_BIN, NPX_BIN, NPM_BIN

REMOTION_DIR = os.path.join(os.path.dirname(__file__), "..", "remotion")
REMOTION_BUNDLE = os.path.join(REMOTION_DIR, "bundle")

# ComfyUI.app has a restricted PATH — ensure node/npm directories are included
_node_dir = os.path.dirname(NODE_BIN)
_env = os.environ.copy()
_env["PATH"] = _node_dir + ":" + _env.get("PATH", "")

_deps_checked = False


class NSVideoEffects:
    """
    Applies video effects (zoom punches, wiggle, face tracking)
    to a video using Remotion. Can be chained before NSCaptionOverlay.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
            },
            "optional": {
                "zoom": ("BOOLEAN", {"default": False}),
                "zoom_amount": ("FLOAT", {"default": 0.05, "min": 0.01, "max": 0.20, "step": 0.01}),
                "zoom_frequency": ("INT", {"default": 5, "min": 1, "max": 10, "step": 1}),
                "zoom_speed": ("FLOAT", {"default": 1.0, "min": 0.1, "max": 3.0, "step": 0.1}),
                "zoom_blur": ("BOOLEAN", {"default": True}),
                "wiggle": ("BOOLEAN", {"default": False}),
                "wiggle_intensity": ("FLOAT", {"default": 3.0, "min": 0.5, "max": 10.0, "step": 0.5}),
                "face_tracking": ("BOOLEAN", {"default": False}),
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

        node_modules = os.path.join(REMOTION_DIR, "node_modules")
        if not os.path.isdir(node_modules):
            print("[NSVideoEffects] Installing Remotion dependencies (first run)...")
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
            print("[NSVideoEffects] Dependencies installed.")

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

    def _detect_face_positions(self, video_path, fps, duration):
        """Sample frames at ~0.5s intervals and detect face positions using OpenCV Haar cascade."""
        import cv2

        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print("[NSVideoEffects] Could not open video for face detection, using center fallback")
            return None

        sample_interval = 0.5  # seconds
        total_samples = int(duration / sample_interval) + 1
        positions = []
        last_x, last_y = 0.5, 0.5

        for i in range(total_samples):
            time_sec = i * sample_interval
            frame_num = int(time_sec * fps)
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
            ret, frame = cap.read()
            if not ret:
                positions.append({"frame": frame_num, "x": last_x, "y": last_y})
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))

            if len(faces) > 0:
                largest = max(faces, key=lambda f: f[2] * f[3])
                fx, fy, fw, fh = largest
                h, w = frame.shape[:2]
                last_x = (fx + fw / 2) / w
                last_y = (fy + fh / 2) / h

            positions.append({"frame": frame_num, "x": last_x, "y": last_y})

        cap.release()
        print(f"[NSVideoEffects] Face detection: {len(positions)} samples, {total_samples} expected")
        return positions

    @staticmethod
    def _kill_stale_chrome():
        """Kill leftover Chrome processes from previous renders."""
        import platform
        if platform.system() != "Linux":
            return
        subprocess.run(["pkill", "-9", "-f", "headless.*remotion"],
                       capture_output=True, text=True)
        time.sleep(1)

    def _render_video(self, props, output_path):
        """Call Remotion CLI to render the VideoEffects composition."""
        props_path = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        )
        json.dump(props, props_path)
        props_path.close()

        try:
            entry = REMOTION_BUNDLE if os.path.isdir(REMOTION_BUNDLE) else "src/index.ts"
            cmd = [
                NPX_BIN, "remotion", "render",
                entry, "VideoEffects",
                f"--props={props_path.name}",
                "--codec=h264",
                f"--output={output_path}",
                "--log=error",
            ]
            n_frames = props['durationInFrames']
            render_timeout = max(600, n_frames * 3)
            print(f"[NSVideoEffects] Rendering {n_frames} frames "
                  f"(timeout={render_timeout}s)...")

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
                    print(f"[NSVideoEffects] Chrome launch failed (attempt {attempt + 1}), cleaning up...")
                    self._kill_stale_chrome()
                    continue
                raise RuntimeError(
                    f"Remotion render failed:\n{result.stderr[-1500:]}"
                )
            print("[NSVideoEffects] Render complete.")
        finally:
            try:
                os.unlink(props_path.name)
            except OSError:
                pass

    def _mux_audio(self, remotion_video_path, original_path, output_path):
        """Mux audio from original video onto Remotion-rendered video."""
        cmd = [
            FFMPEG, "-y",
            "-i", remotion_video_path,
            "-i", original_path,
            "-map", "0:v",
            "-map", "1:a?",
            "-c", "copy",
            output_path
        ]

        print("[NSVideoEffects] Muxing audio...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg mux error:\n{result.stderr[-1000:]}"
            )

    def _process_file(self, input_path, output_path, settings):
        """Apply effects to a video file on disk. Used by execute() and NSVideoConcatMulti."""
        self._ensure_deps()

        temp_files = []
        try:
            fps, width, height, duration = self._get_video_info(input_path)
            duration_in_frames = int(round(duration * fps))

            face_positions = None
            if settings.get("face_tracking"):
                face_positions = self._detect_face_positions(input_path, fps, duration)

            # Copy video into the public/ dir that Remotion actually serves from
            # (bundle/public/ when using pre-built bundle, remotion/public/ otherwise)
            if os.path.isdir(REMOTION_BUNDLE):
                public_dir = os.path.join(REMOTION_BUNDLE, "public")
            else:
                public_dir = os.path.join(REMOTION_DIR, "public")
            os.makedirs(public_dir, exist_ok=True)
            video_filename = f"effects_source_{int(time.time())}.mp4"
            public_video_path = os.path.join(public_dir, video_filename)
            shutil.copy2(input_path, public_video_path)
            temp_files.append(public_video_path)

            props = {
                "videoSrc": video_filename,
                "zoom": settings.get("zoom", False),
                "zoomAmount": settings.get("zoom_amount", 0.05),
                "zoomFrequency": settings.get("zoom_frequency", 5),
                "zoomSpeed": settings.get("zoom_speed", 1.0),
                "zoomBlur": settings.get("zoom_blur", True),
                "wiggle": settings.get("wiggle", False),
                "wiggleIntensity": settings.get("wiggle_intensity", 3.0),
                "faceTracking": settings.get("face_tracking", False),
                "facePositions": face_positions,
                "width": width,
                "height": height,
                "fps": round(fps),
                "durationInFrames": duration_in_frames,
            }

            remotion_output = tempfile.NamedTemporaryFile(
                suffix=".mp4", delete=False
            ).name
            temp_files.append(remotion_output)

            self._render_video(props, remotion_output)
            self._mux_audio(remotion_output, input_path, output_path)

        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass

    def execute(self, video, zoom=False, zoom_amount=0.05,
                zoom_frequency=5, zoom_speed=1.0, zoom_blur=True,
                wiggle=False, wiggle_intensity=3.0, face_tracking=False):
        from comfy_api.latest import InputImpl

        settings = {
            "zoom": zoom,
            "zoom_amount": zoom_amount,
            "zoom_frequency": zoom_frequency,
            "zoom_speed": zoom_speed,
            "zoom_blur": zoom_blur,
            "wiggle": wiggle,
            "wiggle_intensity": wiggle_intensity,
            "face_tracking": face_tracking,
        }

        if not zoom and not wiggle:
            print("[NSVideoEffects] No effects enabled, returning original video")
            return (video,)

        temp_files = []
        try:
            original_path = tempfile.NamedTemporaryFile(
                suffix=".mp4", delete=False
            ).name
            temp_files.append(original_path)
            video.save_to(original_path, format="mp4", codec="h264")

            output_dir = folder_paths.get_output_directory()
            output_path = os.path.join(
                output_dir, f"effects_{int(time.time())}.mp4"
            )

            self._process_file(original_path, output_path, settings)

            print(f"[NSVideoEffects] Done → {output_path}")
            return (InputImpl.VideoFromFile(output_path),)

        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass


NODE_CLASS_MAPPINGS = {
    "NSVideoEffects": NSVideoEffects,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSVideoEffects": "NS Video Effects",
}
