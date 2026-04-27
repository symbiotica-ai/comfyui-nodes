# ABOUTME: Video concatenation node that combines multiple videos into one sequence
# ABOUTME: Uses FFmpeg for concatenation with optional transitions (xfade) and whoosh SFX

import os
import subprocess
import tempfile
import time
import json

import folder_paths

from ._bins import FFMPEG, FFPROBE

# Quartic ease-out slideup for TikTok-style swipe.
# Fast start, long smooth deceleration — like a real finger flick.
# P goes 1→0 in FFmpeg 8's xfade, so ease-out(1-P) = 1-P⁴.
_EASED_SLIDEUP_EXPR = (
    "st(0,1-P*P*P*P);"
    "st(1,floor(ld(0)*H));"
    "if(eq(PLANE,0),"
    "if(lt(Y,H-ld(1)),a0(X,min(Y+ld(1),H-1)),b0(X,max(Y-H+ld(1),0))),"
    "if(eq(PLANE,1),"
    "if(lt(Y,H-ld(1)),a1(X,min(Y+ld(1),H-1)),b1(X,max(Y-H+ld(1),0))),"
    "if(lt(Y,H-ld(1)),a2(X,min(Y+ld(1),H-1)),b2(X,max(Y-H+ld(1),0)))"
    "))"
)


class NSVideoConcatMulti:
    """
    Concatenates multiple videos into a single sequential video.
    Accepts VIDEO inputs (from LoadVideo, CreateVideo, etc.).
    Uses FFmpeg to merge all inputs into one output.
    Preserves audio when present.
    Connect an NS Transition Settings node to add transitions between clips.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "inputcount": ("INT", {"default": 2, "min": 2, "max": 20, "step": 1}),
                "video_1": ("VIDEO",),
            },
            "optional": {
                "video_2": ("VIDEO",),
                "transition_settings": ("TRANSITION_SETTINGS",),
            }
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "execute"
    CATEGORY = "neuralsins/Video"

    def _save_video_to_temp(self, video, temp_files):
        """Save a VIDEO input to a temp file and return the path."""
        temp_file = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        temp_files.append(temp_file.name)
        temp_file.close()
        video.save_to(temp_file.name, format="mp4", codec="h264")
        return temp_file.name

    def _has_audio(self, path):
        """Check if a video file has an audio stream."""
        result = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
            capture_output=True, text=True
        )
        return result.stdout.strip() != ""

    def _add_silent_audio(self, path, temp_files):
        """Add a silent audio track to a video that has none."""
        out = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        temp_files.append(out.name)
        out.close()
        subprocess.run(
            [FFMPEG, "-y", "-i", path,
             "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
             "-c:v", "copy", "-c:a", "aac", "-shortest", out.name],
            capture_output=True, text=True, check=True
        )
        return out.name

    def _get_video_info(self, path):
        """Get video duration, width, height, and fps via ffprobe."""
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
        # r_frame_rate is like "30/1" or "30000/1001"
        num, den = stream["r_frame_rate"].split("/")
        fps = float(num) / float(den)
        return duration, width, height, fps

    def _normalize_video(self, path, width, height, fps, temp_files):
        """Re-encode a video to a target resolution, fps, and pixel format."""
        out = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
        temp_files.append(out.name)
        out.close()
        cmd = [
            FFMPEG, "-y", "-i", path,
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                   f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p,setsar=1",
            "-c:v", "libx264", "-preset", "fast",
            "-c:a", "aac", "-ar", "44100", "-ac", "2",
            out.name
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg normalize error: {result.stderr[-500:]}")
        return out.name

    def _get_whoosh_path(self):
        """Return path to the bundled whoosh sound effect."""
        return os.path.join(os.path.dirname(__file__), "..", "assets", "whoosh.mp3")

    def _build_concat_filter(self, n, any_audio):
        """Build a simple concat filter (no transitions)."""
        if any_audio:
            streams = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(n))
            return f"{streams}concat=n={n}:v=1:a=1[outv][outa]", ["[outv]", "[outa]"]
        else:
            streams = "".join(f"[{i}:v:0]" for i in range(n))
            return f"{streams}concat=n={n}:v=1:a=0[outv]", ["[outv]"]

    def _build_xfade_filter(self, n, durations, transition_type, transition_duration,
                            any_audio, add_sound, whoosh_path, num_inputs):
        """Build chained xfade video + acrossfade audio filters with optional whoosh."""
        is_tiktok = transition_type == "tiktok_swipe"
        ffmpeg_transition = "slideup" if is_tiktok else transition_type

        parts = []
        # Video: chain xfade filters
        offset = durations[0] - transition_duration
        prev_v = "[0:v:0]"
        for i in range(1, n):
            if is_tiktok:
                # TikTok swipe: built-in slideup (correct A→B ordering)
                out_label = "outv" if i == n - 1 else f"xv{i}"
                parts.append(
                    f"{prev_v}[{i}:v:0]xfade=transition=custom"
                    f":expr='{_EASED_SLIDEUP_EXPR}'"
                    f":duration={transition_duration}:offset={offset}[{out_label}]"
                )
                prev_v = f"[{out_label}]"
            else:
                # Standard transition: xfade + directional blur during transition
                xf_label = f"xftmp{i}"
                parts.append(
                    f"{prev_v}[{i}:v:0]xfade=transition={ffmpeg_transition}"
                    f":duration={transition_duration}:offset={offset}[{xf_label}]"
                )
                blur_label = "outv" if i == n - 1 else f"xv{i}"
                parts.append(
                    f"[{xf_label}]gblur=sigma=30:sigmaV=0.5"
                    f":enable='between(t,{offset},{offset + transition_duration})'[{blur_label}]"
                )
                prev_v = f"[{blur_label}]"
            if i < n - 1:
                offset += durations[i] - transition_duration

        outputs = ["[outv]"]

        if any_audio:
            if is_tiktok:
                # TikTok: hard audio cut — trim each clip's audio to match
                # xfade overlap, then concat. Each clip except the last loses
                # transition_duration from its end (the overlapping portion).
                trim_labels = []
                for i in range(n):
                    if i < n - 1:
                        trim_end = durations[i] - transition_duration
                        trim_label = f"[at{i}]"
                        parts.append(
                            f"[{i}:a:0]atrim=0:{trim_end},asetpts=PTS-STARTPTS{trim_label}"
                        )
                        trim_labels.append(trim_label)
                    else:
                        trim_labels.append(f"[{i}:a:0]")
                audio_streams = "".join(trim_labels)
                parts.append(f"{audio_streams}concat=n={n}:v=0:a=1[outa]")
                outputs.append("[outa]")
            else:
                # Standard: chain acrossfade filters
                prev_a = "[0:a:0]"
                for i in range(1, n):
                    out_label = "tmpa" if i == n - 1 else f"xa{i}"
                    parts.append(
                        f"{prev_a}[{i}:a:0]acrossfade=d={transition_duration}:c1=tri:c2=tri[{out_label}]"
                    )
                    prev_a = f"[{out_label}]"

                if add_sound and whoosh_path:
                    whoosh_idx = num_inputs  # index of whoosh input
                    num_cuts = n - 1

                    # Calculate where each transition occurs in the output timeline
                    transition_offsets = []
                    for i in range(n - 1):
                        offset_t = sum(durations[:i + 1]) - (i + 1) * transition_duration
                        transition_offsets.append(offset_t)

                    # Split whoosh into N-1 copies
                    if num_cuts == 1:
                        split_labels = [f"[wh0]"]
                        parts.append(f"[{whoosh_idx}:a:0]acopy[wh0]")
                    else:
                        split_labels = [f"[wh{j}]" for j in range(num_cuts)]
                        parts.append(f"[{whoosh_idx}:a:0]asplit={num_cuts}{''.join(split_labels)}")

                    # Delay each whoosh copy to its transition point
                    delayed_labels = []
                    for j in range(num_cuts):
                        delay_ms = int(transition_offsets[j] * 1000)
                        d_label = f"[whd{j}]"
                        parts.append(f"{split_labels[j]}adelay={delay_ms}|{delay_ms}[whd{j}]")
                        delayed_labels.append(d_label)

                    # Mix all whoosh copies together
                    if num_cuts == 1:
                        whoosh_mixed = delayed_labels[0]
                    else:
                        parts.append(
                            f"{''.join(delayed_labels)}amix=inputs={num_cuts}:normalize=0[whooshmix]"
                        )
                        whoosh_mixed = "[whooshmix]"

                    # Mix whoosh with the crossfaded audio
                    parts.append(f"[tmpa]{whoosh_mixed}amix=inputs=2:weights=1 0.3:normalize=0[outa]")
                    outputs.append("[outa]")
                else:
                    # Rename tmpa → outa
                    parts[-1] = parts[-1].replace("[tmpa]", "[outa]")
                    outputs.append("[outa]")

        filter_complex = ";".join(parts)
        return filter_complex, outputs

    def execute(self, inputcount, **kwargs):
        from comfy_api.latest import InputImpl

        settings = kwargs.get("transition_settings")

        transitions = settings is not None
        transition_type = settings["type"] if settings else "slideleft"
        transition_duration = settings["duration"] if settings else 0.3
        transition_sound = settings["sound"] if settings else True

        paths = []
        temp_files = []

        try:
            for i in range(1, inputcount + 1):
                video = kwargs.get(f"video_{i}")
                if video is None:
                    continue
                paths.append(self._save_video_to_temp(video, temp_files))

            if len(paths) == 0:
                raise ValueError("No video inputs provided")

            if len(paths) == 1:
                return (InputImpl.VideoFromFile(paths[0]),)

            # Check which inputs have audio
            has_audio = [self._has_audio(p) for p in paths]
            any_audio = any(has_audio)

            # If some have audio and some don't, add silent tracks to fill gaps
            if any_audio:
                for i, (path, has) in enumerate(zip(paths, has_audio)):
                    if not has:
                        paths[i] = self._add_silent_audio(path, temp_files)

            n = len(paths)

            whoosh_path = None
            if transitions and n > 1:
                # Get video info from all clips
                infos = [self._get_video_info(p) for p in paths]
                # Use first clip's resolution and fps as the target
                target_w = infos[0][1]
                target_h = infos[0][2]
                target_fps = round(infos[0][3], 2)

                # Normalize all clips to matching resolution/fps/pixel format
                # xfade requires exact match on all of these
                print(f"[NSVideoConcatMulti] Normalizing to {target_w}x{target_h} @ {target_fps}fps")
                for i in range(n):
                    paths[i] = self._normalize_video(
                        paths[i], target_w, target_h, target_fps, temp_files
                    )

                # Re-probe durations after normalization (fps change can shift them)
                durations = [self._get_video_info(p)[0] for p in paths]
                print(f"[NSVideoConcatMulti] Clip durations: {durations}")

                # Clamp transition_duration so it doesn't exceed any clip
                min_dur = min(durations)
                if transition_duration >= min_dur:
                    transition_duration = max(0.1, min_dur - 0.1)
                    print(f"[NSVideoConcatMulti] Clamped transition_duration to {transition_duration}s")

                # Re-check audio after normalization (all clips now have audio tracks)
                has_audio = [self._has_audio(p) for p in paths]
                any_audio = any(has_audio)

                # Use bundled whoosh sound if needed (skip for tiktok_swipe)
                add_sound = transition_sound and any_audio and transition_type != "tiktok_swipe"
                if add_sound:
                    whoosh_path = self._get_whoosh_path()

                inputs = []
                for path in paths:
                    inputs.extend(["-i", path])
                if whoosh_path:
                    inputs.extend(["-i", whoosh_path])

                filter_complex, output_labels = self._build_xfade_filter(
                    n, durations, transition_type, transition_duration,
                    any_audio, add_sound, whoosh_path, n
                )
            else:
                inputs = []
                for path in paths:
                    inputs.extend(["-i", path])
                filter_complex, output_labels = self._build_concat_filter(n, any_audio)

            map_args = []
            for label in output_labels:
                map_args.extend(["-map", label])

            output_dir = folder_paths.get_output_directory()
            concat_file = os.path.join(output_dir, f"concat_{int(time.time())}.mp4")

            cmd = (
                [FFMPEG, "-y"]
                + inputs
                + ["-filter_complex", filter_complex]
                + map_args
                + ["-c:v", "libx264", "-preset", "fast",
                   "-pix_fmt", "yuv420p",
                   "-c:a", "aac",
                   concat_file]
            )

            mode = "transitions" if transitions else "concat"
            print(f"[NSVideoConcatMulti] {mode}: {n} videos (audio: {any_audio})...")
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(f"FFmpeg error: {result.stderr[-500:]}")

            print(f"[NSVideoConcatMulti] Done → {concat_file}")
            return (InputImpl.VideoFromFile(concat_file),)

        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass


NODE_CLASS_MAPPINGS = {
    "NSVideoConcatMulti": NSVideoConcatMulti
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSVideoConcatMulti": "NS Video Concat"
}
