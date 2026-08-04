# ABOUTME: Camera shake / handheld motion node — seeded Perlin wiggle on a VIDEO.
# ABOUTME: ffmpeg decodes and encodes; the per-frame affine warp is done in Pillow.

import json
import os
import subprocess
import tempfile
import time

import folder_paths

from ._bins import FFMPEG, FFPROBE
from ._camera_shake import (
    AUTO_PRESET,
    DEFAULT_SHOT_TYPE,
    SHUTTER_180,
    classify_shot,
    classify_shot_clip,
    cuts_from_scores,
    preset_choices,
    preset_for_shot,
    segments_from_cuts,
    affine_matrix,
    blur_sample_count,
    make_sampler,
    required_zoom,
    resolve_preset,
    shake_curve,
    shutter_path_px,
)

# Cap on sub-exposures per frame. Reached only by the violent presets; a subtle
# shake moves under a pixel per frame and resolves to a single sample.
_MAX_BLUR_SAMPLES = 16

# Gradient magnitude above which a pixel counts as "in focus" when measuring
# how much of a frame is sharp.
_DETAIL_EDGE_LEVEL = 12.0

# Seed stride between shots, so a cut genuinely re-rolls the shake rather than
# continuing the same motion into a different camera setup.
_SHOT_SEED_STRIDE = 7919

# Extra frames to include in the safety-zoom pre-pass. The frame count from
# ffprobe is an estimate for some containers, and a zoom computed one frame
# short would let an edge show on exactly the frame it missed.
_ZOOM_LOOKAHEAD = 60

# x264 quality of the re-encode. Fixed rather than exposed: 17 is visually
# transparent on generated footage and there is no reason to make the operator
# think about it.
_CRF = 17


class CameraShake:
    """
    Adds handheld camera motion to a video: seeded Perlin wiggle on position,
    rotation and scale, with a safety zoom so the shake never reveals the
    frame edge.

    Modelled on the standard After Effects handheld rig, which is three
    wiggle() calls plus an edge guard. Two differences, both deliberate:
    the noise is real Perlin rather than summed sines, so the motion never
    repeats; and the safety zoom can be solved for exactly instead of nudged
    by hand.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
                "preset": (preset_choices(), {
                    "default": AUTO_PRESET,
                    "tooltip": "Auto finds the cuts and picks the right amount "
                               "of motion for each shot on its own — a macro "
                               "detail barely moves, a wide shot moves freely. "
                               "Pick a named preset to use that one throughout: "
                               "Micro and Subtle suit product macro, Handheld is "
                               "the everyday one, Impact hits once and settles.",
                }),
                "strength": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 3.0, "step": 0.05,
                    "tooltip": "Scales the preset up or down. 0 passes the "
                               "video through untouched.",
                }),
                "seed": ("INT", {
                    "default": 0, "min": 0, "max": 100000, "step": 1,
                    "tooltip": "Same settings with a different number give a "
                               "completely different shake. Change it so each "
                               "shot in a cut moves its own way.",
                }),
                "auto_safety_zoom": ("BOOLEAN", {
                    "default": True,
                    "tooltip": "Solve for the smallest zoom that hides the frame "
                               "edge. Off uses the preset's own zoom, which can "
                               "let an edge show at high strength.",
                }),
                "motion_blur": ("BOOLEAN", {
                    "default": False,
                    "tooltip": "Smear each frame along the path the camera "
                               "travels while the shutter is open, the way a "
                               "real one does. Costs render time only on frames "
                               "that actually move far enough to smear.",
                }),
                "blur_strength": ("FLOAT", {
                    "default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05,
                    "tooltip": "Shutter angle. 1.0 is a 180-degree shutter, the "
                               "cinema default; 2.0 is a fully open 360-degree "
                               "shutter and smears twice as far.",
                }),
            },
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "execute"
    CATEGORY = "Symbiotica/Video"

    def __init__(self):
        # Loaded once per node instance and reused across the clip's shots;
        # a fresh load per shot would dominate the render time.
        self._clip = None
        self._clip_failed = False

    # -- probing -----------------------------------------------------------

    def _probe(self, path):
        """Read the geometry, frame rate, frame count and colour tags."""
        result = subprocess.run(
            [FFPROBE, "-v", "error",
             "-show_entries",
             "stream=index,codec_type,width,height,r_frame_rate,nb_frames,"
             "color_range,color_space,color_primaries,color_transfer",
             "-show_entries", "format=duration",
             "-of", "json", path],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed:\n{result.stderr[-800:]}")
        data = json.loads(result.stdout)

        streams = data.get("streams", [])
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        if video is None:
            raise RuntimeError("input has no video stream")
        has_audio = any(s.get("codec_type") == "audio" for s in streams)

        num, den = video["r_frame_rate"].split("/")
        fps = float(num) / float(den)
        if fps <= 0:
            raise RuntimeError(f"invalid frame rate: {video['r_frame_rate']}")

        duration = float(data.get("format", {}).get("duration", 0.0) or 0.0)
        try:
            n_frames = int(video.get("nb_frames") or 0)
        except (TypeError, ValueError):
            n_frames = 0
        if n_frames <= 0:
            n_frames = int(round(duration * fps))

        return {
            "width": int(video["width"]),
            "height": int(video["height"]),
            "fps": fps,
            "fps_str": video["r_frame_rate"],
            "n_frames": max(n_frames, 1),
            "has_audio": has_audio,
            # Carried through to the encoder: decoding to RGB and re-encoding
            # without re-tagging is how a clip comes back with a colour shift.
            "color_range": video.get("color_range"),
            "color_space": video.get("color_space"),
            "color_primaries": video.get("color_primaries"),
            "color_transfer": video.get("color_transfer"),
        }

    # -- shot detection ----------------------------------------------------

    def _detect_cuts(self, path, fps):
        """Frame indices where a new shot begins.

        Uses ffmpeg's dedicated `scdet` rather than the `scene` expression:
        scdet separates real cuts from noise far better. On a generated clip
        the true cuts score 15.2 / 14.9 / 9.6 against a 1.7 maximum elsewhere,
        where the `scene` metric put a genuine cut at 0.245 — under any
        sensible fixed threshold. The threshold here is derived from the clip's
        own score distribution instead of being a constant.
        """
        result = subprocess.run(
            [FFMPEG, "-v", "error", "-nostdin", "-i", path,
             "-vf", "scdet=threshold=0,metadata=print:file=-",
             "-f", "null", "-"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print("[Camera Shake] scene detection failed, treating as one shot")
            return []

        scored = []
        score = None
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("lavfi.scd.score="):
                try:
                    score = float(line.split("=", 1)[1])
                except ValueError:
                    score = None
            elif line.startswith("lavfi.scd.time=") and score is not None:
                try:
                    scored.append((score, int(round(float(line.split("=", 1)[1]) * fps))))
                except ValueError:
                    pass
                score = None
        return cuts_from_scores(scored, fps)

    def _measure_shot(self, path, t_seconds, width, height):
        """Sample one frame and return (detail_fraction, face_fraction).

        detail_fraction is how much of the frame carries sharp local contrast —
        a proxy for what is in focus. face_fraction is the widest face as a
        share of frame width, or 0. OpenCV is optional: without it the
        classification falls back to focus coverage alone, which still
        separates a product detail from a wide shot.
        """
        import numpy as np
        from PIL import Image

        result = subprocess.run(
            [FFMPEG, "-v", "error", "-nostdin", "-ss", f"{t_seconds:.3f}",
             "-i", path, "-frames:v", "1", "-f", "rawvideo",
             "-pix_fmt", "gray", "-"],
            capture_output=True,
        )
        if result.returncode != 0 or len(result.stdout) < width * height:
            return (1.0, 0.0)

        gray = np.frombuffer(result.stdout[:width * height],
                             dtype=np.uint8).reshape(height, width)

        # Local contrast via a cheap gradient. Downsample first: focus is a
        # regional property and this keeps the measurement fast on 4K.
        step = max(1, min(width, height) // 360)
        small = gray[::step, ::step].astype(np.float32)
        gx = np.abs(np.diff(small, axis=1))[:-1, :]
        gy = np.abs(np.diff(small, axis=0))[:, :-1]
        detail = float(np.mean((gx + gy) > _DETAIL_EDGE_LEVEL))

        face = 0.0
        try:
            import cv2
            cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
            faces = cascade.detectMultiScale(gray, scaleFactor=1.1,
                                             minNeighbors=5, minSize=(40, 40))
            if len(faces):
                face = max(f[2] for f in faces) / float(width)
        except Exception:
            # No OpenCV, or the cascade failed to load — focus coverage alone.
            pass
        return (detail, face)

    def _classify_at(self, path, t_seconds, info):
        """Shot type for one instant. CLIP if available, measurements if not."""
        from PIL import Image

        width, height = info["width"], info["height"]
        rgb = subprocess.run(
            [FFMPEG, "-v", "error", "-nostdin", "-ss", f"{t_seconds:.3f}",
             "-i", path, "-frames:v", "1", "-f", "rawvideo",
             "-pix_fmt", "rgb24", "-"],
            capture_output=True,
        )
        if rgb.returncode == 0 and len(rgb.stdout) >= width * height * 3:
            frame = Image.frombuffer("RGB", (width, height),
                                     rgb.stdout[:width * height * 3],
                                     "raw", "RGB", 0, 1)
            if self._clip is None and not self._clip_failed:
                try:
                    from transformers import CLIPModel, CLIPProcessor
                    name = "openai/clip-vit-base-patch16"
                    self._clip = (CLIPModel.from_pretrained(name),
                                  CLIPProcessor.from_pretrained(name))
                except Exception:
                    self._clip_failed = True
                    print("[Camera Shake] CLIP unavailable, classifying shots "
                          "by focus coverage and face size instead")
            if self._clip is not None:
                guess = classify_shot_clip(frame, self._clip[0], self._clip[1])
                if guess is not None:
                    return guess

        detail, face = self._measure_shot(path, t_seconds, width, height)
        return classify_shot(detail, face)

    def _plan_shots(self, path, info, settings):
        """Split the clip into shots and decide each one's type.

        Returns a list of (start_frame, end_frame, shot_type, preset_name).

        Cuts are always detected, whichever preset is chosen: a cut is a new
        camera setup and the shake has to restart regardless. What Auto adds is
        choosing the amount of motion and the optics per shot instead of
        applying one choice to a clip whose shots may range from a macro detail
        to a wide.
        """
        n_frames = info["n_frames"]
        chosen = settings.get("preset", AUTO_PRESET)
        cuts = self._detect_cuts(path, info["fps"])
        segments = segments_from_cuts(cuts, n_frames)

        if chosen != AUTO_PRESET:
            # Named preset means exactly that preset, with neutral optics —
            # nothing is inferred behind the operator's back except the cuts.
            return [(start, end, DEFAULT_SHOT_TYPE, chosen)
                    for start, end in segments]

        plan = []
        for start, end in segments:
            # Sample a third of the way in: past any dissolve, before the shot
            # has had time to change much.
            t = (start + (end - start) / 3.0) / info["fps"]
            shot_type = self._classify_at(path, t, info)
            plan.append((start, end, shot_type, preset_for_shot(shot_type)))
        return plan

    # -- render ------------------------------------------------------------

    def _decoder(self, path):
        return subprocess.Popen(
            [FFMPEG, "-v", "error", "-nostdin", "-i", path,
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def _encoder(self, info, source_path, output_path, crf):
        cmd = [
            FFMPEG, "-y", "-v", "error", "-nostdin",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{info['width']}x{info['height']}",
            "-r", info["fps_str"],
            "-i", "pipe:0",
        ]
        # Second input supplies the original audio; the warp is video-only.
        cmd += ["-i", source_path]
        cmd += ["-map", "0:v:0"]
        if info["has_audio"]:
            # No -shortest: the audio track can round a hair under the video
            # length, and -shortest would drop the final frame to match it.
            cmd += ["-map", "1:a:0", "-c:a", "copy"]
        cmd += [
            "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
            "-pix_fmt", "yuv420p",
        ]
        for flag, key in (("-color_range", "color_range"),
                          ("-colorspace", "color_space"),
                          ("-color_primaries", "color_primaries"),
                          ("-color_trc", "color_transfer")):
            value = info.get(key)
            if value and value != "unknown":
                cmd += [flag, value]
        cmd += ["-movflags", "+faststart", output_path]

        return subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE,
        )

    def _blurred_frame(self, buf, width, height, sampler, t0, shutter_dt,
                       zoom, counter):
        """One frame smeared along the path the camera travels while the
        shutter is open.

        The number of sub-exposures adapts to how far the frame actually moves:
        under CIPA's visible-blur level it stays at one sample and costs
        nothing, so a subtle shake is effectively free and only the violent
        frames pay.
        """
        import numpy as np
        from PIL import Image

        path = shutter_path_px(sampler, t0, shutter_dt, width, height)
        n_samples = blur_sample_count(path, width, height, _MAX_BLUR_SAMPLES)

        frame = Image.frombuffer("RGB", (width, height), buf, "raw", "RGB", 0, 1)
        if n_samples <= 1:
            dx, dy, rot, scale_mult = sampler(t0)
            return frame.transform(
                (width, height), Image.AFFINE,
                affine_matrix(width, height, dx, dy, rot, zoom * scale_mult),
                resample=Image.BICUBIC).tobytes()

        counter[0] += 1
        counter[1] += n_samples
        acc = np.zeros((height, width, 3), dtype=np.float32)
        for i in range(n_samples):
            # Sample across the open shutter, not centred on the frame time:
            # a real shutter opens at the frame boundary.
            t = t0 + shutter_dt * (i / (n_samples - 1))
            dx, dy, rot, scale_mult = sampler(t)
            warped = frame.transform(
                (width, height), Image.AFFINE,
                affine_matrix(width, height, dx, dy, rot, zoom * scale_mult),
                resample=Image.BICUBIC)
            acc += np.asarray(warped, dtype=np.float32)
        acc /= n_samples
        return np.clip(acc, 0, 255).astype(np.uint8).tobytes()

    def _process_file(self, source_path, output_path, settings):
        from PIL import Image

        info = self._probe(source_path)
        width, height = info["width"], info["height"]

        plan = self._plan_shots(source_path, info, settings)
        if len(plan) > 1:
            print("[Camera Shake] " + str(len(plan)) + " shots: " + ", ".join(
                f"{s / info['fps']:.1f}-{e / info['fps']:.1f}s {t}/{p}"
                for s, e, t, p in plan))
        else:
            print(f"[Camera Shake] one shot, {plan[0][2]}/{plan[0][3]}")

        # Each shot is a different camera setup: its own seed, and its own
        # clock so the motion does not inherit mid-drift across a cut.
        shot_samplers = []
        for index, (start, end, shot_type, preset_name) in enumerate(plan):
            shot_params = resolve_preset(preset_name, pos_amt=0.0,
                                         rot_amt=0.0, safety_zoom=1.0)
            shot_samplers.append((start, end, make_sampler(
                shot_params, info["fps"],
                strength=settings["strength"],
                variation=settings["seed"] + index * _SHOT_SEED_STRIDE,
                height=height, width=width,
                impact_time=settings.get("impact_time", 0.0),
                shot_type=shot_type,
            )))

        def sample_at(t):
            n = int(t * info["fps"])
            for start, end, fn in shot_samplers:
                if n < end:
                    return fn(t - start / info["fps"])
            start, _, fn = shot_samplers[-1]
            return fn(t - start / info["fps"])

        curve = [sample_at(n / info["fps"])
                 for n in range(info["n_frames"] + _ZOOM_LOOKAHEAD)]

        solved = required_zoom(width, height, curve)
        if settings["auto_safety_zoom"]:
            zoom = solved
            print(f"[Camera Shake] Safety zoom solved at {zoom:.4f} "
                  f"(first shot's preset suggests "
                  f"{resolve_preset(plan[0][3], pos_amt=0.0, rot_amt=0.0, safety_zoom=1.0)['zoom']:.3f})")
        else:
            zoom = resolve_preset(plan[0][3], pos_amt=0.0, rot_amt=0.0,
                                  safety_zoom=1.0)["zoom"]
            if solved > zoom + 1e-9:
                print(f"[Camera Shake] WARNING: the preset's zoom {zoom:.4f} is "
                      f"below the {solved:.4f} this shake needs — the frame edge "
                      f"will show. Turn auto_safety_zoom on.")

        # Motion blur needs the rig evaluated *between* frames, at several
        # instants across the shutter opening, so it uses the continuous
        # sampler rather than the per-frame curve.
        sampler = None
        shutter_dt = 0.0
        blur_frames = [0, 0]  # frames blurred, total sub-exposures
        if settings.get("motion_blur") and settings.get("blur_strength", 0) > 0:
            shutter_dt = (SHUTTER_180 * settings["blur_strength"]
                          / info["fps"])
            sampler = sample_at

        frame_bytes = width * height * 3
        dec = self._decoder(source_path)
        enc = self._encoder(info, source_path, output_path, settings["crf"])

        print(f"[Camera Shake] {width}x{height} @ {info['fps']:.3f}fps, "
              f"~{info['n_frames']} frames, preset={settings['preset']}, "
              f"seed={settings['seed']}")

        n = 0
        try:
            while True:
                buf = dec.stdout.read(frame_bytes)
                if not buf or len(buf) < frame_bytes:
                    break
                if n < len(curve):
                    dx, dy, rot, scale_mult = curve[n]
                else:
                    # Longer than probed; hold the last computed value rather
                    # than snapping to zero mid-shot.
                    dx, dy, rot, scale_mult = curve[-1]

                total_scale = zoom * scale_mult
                if (dx == 0.0 and dy == 0.0 and rot == 0.0
                        and total_scale == 1.0):
                    # Nothing to do this frame — skip the resample entirely
                    # rather than run an identity warp and soften the picture.
                    enc.stdin.write(buf)
                elif sampler is not None:
                    enc.stdin.write(self._blurred_frame(
                        buf, width, height, sampler, n / info["fps"],
                        shutter_dt, zoom, blur_frames))
                else:
                    frame = Image.frombuffer("RGB", (width, height), buf,
                                             "raw", "RGB", 0, 1)
                    warped = frame.transform(
                        (width, height), Image.AFFINE,
                        affine_matrix(width, height, dx, dy, rot, total_scale),
                        resample=Image.BICUBIC,
                    )
                    enc.stdin.write(warped.tobytes())
                n += 1
        except BrokenPipeError:
            enc_err = enc.stderr.read().decode("utf-8", "replace")
            raise RuntimeError(f"ffmpeg encoder died:\n{enc_err[-1000:]}")
        finally:
            try:
                enc.stdin.close()
            except (OSError, ValueError):
                pass
            dec_err = dec.stderr.read().decode("utf-8", "replace")
            dec.stdout.close()
            dec.wait()
            enc_err = enc.stderr.read().decode("utf-8", "replace")
            enc.wait()

        if dec.returncode not in (0, None):
            raise RuntimeError(f"ffmpeg decode failed:\n{dec_err[-1000:]}")
        if enc.returncode != 0:
            raise RuntimeError(f"ffmpeg encode failed:\n{enc_err[-1000:]}")
        if n == 0:
            raise RuntimeError("no frames were decoded from the input video")

        if blur_frames and blur_frames[0]:
            print(f"[Camera Shake] motion blur on {blur_frames[0]}/{n} frames, "
                  f"{blur_frames[1] / blur_frames[0]:.1f} sub-exposures avg "
                  f"(the rest moved less than one visible pixel).")
        print(f"[Camera Shake] {n} frames written.")

    # -- entry point -------------------------------------------------------

    def execute(self, video, preset="Handheld", strength=1.0,
                seed=0, auto_safety_zoom=True,
                motion_blur=False, blur_strength=1.0):
        from comfy_api.latest import InputImpl

        if strength <= 0.0:
            print("[Camera Shake] strength is 0, returning original video")
            return (video,)
        if preset not in preset_choices():
            raise ValueError(f"unknown preset: {preset!r}")

        settings = {
            "preset": preset,
            "strength": strength,
            "seed": seed,
            "auto_safety_zoom": auto_safety_zoom,
            "motion_blur": motion_blur,
            "blur_strength": blur_strength,
            "crf": _CRF,
        }

        temp_files = []
        try:
            source_path = tempfile.NamedTemporaryFile(
                suffix=".mp4", delete=False
            ).name
            temp_files.append(source_path)
            video.save_to(source_path, format="mp4", codec="h264")

            output_dir = folder_paths.get_output_directory()
            output_path = os.path.join(
                output_dir, f"camera_shake_{int(time.time())}.mp4"
            )

            self._process_file(source_path, output_path, settings)

            print(f"[Camera Shake] Done -> {output_path}")
            return (InputImpl.VideoFromFile(output_path),)
        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass


NODE_CLASS_MAPPINGS = {
    "CameraShake": CameraShake,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "CameraShake": "Camera Shake",
}
