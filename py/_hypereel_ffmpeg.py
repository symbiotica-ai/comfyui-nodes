# ABOUTME: Hypereel ffmpeg helpers — the platform compositor's exact clamp, filtergraphs
# ABOUTME: and commands (ported from symbiotica-hub services/compose-modal/app.py).
import os
import subprocess
import tempfile


def probe_duration(ffprobe, path):
    """Seconds, or 0.0 when the probe fails (callers treat 0 as unknown)."""
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nk=1:nw=1", path],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        return float(out)
    except Exception:
        return 0.0


def probe_has_audio(ffprobe, path):
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=codec_type", "-of", "default=nw=1", path],
        capture_output=True, text=True,
    ).stdout
    return "audio" in out


def clamp_window(start, dur, total):
    """Keep [start, start+dur] fully inside a `total`-second clip: cap the duration,
    then back the window off the end so a highlight near EOF still yields a full,
    non-empty slice (not a stub). total 0 = unknown -> no clamping."""
    start = max(0.0, float(start))
    dur = float(dur)
    if total > 0:
        dur = min(dur, total)
        start = max(0.0, min(start, total - dur))
    return (start, dur)


def vstack_filter(w, fc_h, gp_h):
    """Facecam scaled+center-cropped to w×fc_h on top, gameplay to w×gp_h below
    (center-crop drops a corner channel watermark)."""
    return (
        f"[0:v]scale={w}:{fc_h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{fc_h},setsar=1[fcv];"
        f"[1:v]scale={w}:{gp_h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{gp_h},setsar=1[gpv];"
        f"[fcv][gpv]vstack=inputs=2[v]"
    )


def audio_mix_filter(gain):
    """Voice at full volume + game audio at `gain`. normalize=0 keeps the pre-set
    volumes (amix defaults to normalizing, which would halve the voice)."""
    return (
        f"[0:a]volume=1.0[va];[1:a]volume={gain}[ga];"
        f"[va][ga]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[a]"
    )


def clip_cmd(ffmpeg, src, out, start, dur, keep_audio):
    """Cut [start, start+dur] out of a longer video (input-seek + re-encode for
    frame accuracy)."""
    cmd = [ffmpeg, "-y", "-ss", f"{start}", "-i", src, "-t", f"{dur}",
           "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p"]
    if keep_audio:
        cmd += ["-c:a", "aac", "-ar", "48000"]
    else:
        cmd += ["-an"]
    cmd.append(out)
    return cmd


def _stack_pair(ffmpeg, ffprobe, facecam, gameplay, out, w, fc_h, gp_h, gain, fps, crf):
    """One cut: facecam over gameplay; her voice full, game audio mixed at `gain`
    only when the gameplay actually has a track. Segment = min(facecam, gameplay)."""
    fdur = probe_duration(ffprobe, facecam)
    gdur = probe_duration(ffprobe, gameplay)
    dur = min(fdur, gdur) if (fdur and gdur) else (fdur or gdur or 5.0)
    vstack = vstack_filter(w, fc_h, gp_h)
    if probe_has_audio(ffprobe, gameplay):
        filtergraph = f"{vstack};{audio_mix_filter(gain)}"
        amap = ["-map", "[v]", "-map", "[a]"]
    else:
        # Gameplay is silent — carry only the streamer's voice.
        filtergraph = vstack
        amap = ["-map", "[v]", "-map", "0:a?"]
    subprocess.run(
        [ffmpeg, "-y", "-i", facecam, "-i", gameplay, "-filter_complex", filtergraph,
         *amap, "-r", f"{fps}", "-c:v", "libx264", "-crf", f"{crf}",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000",
         "-movflags", "+faststart", "-t", f"{dur}", out],
        check=True, capture_output=True,
    )


def compose_pairs(pairs, out, width, facecam_h, gameplay_h, game_audio_gain,
                  fps, crf, ffmpeg="ffmpeg", ffprobe="ffprobe"):
    """Stack each (facecam, gameplay) file pair into one cut and hard-cut-concat
    the cuts in order into `out`. Returns the number of cuts."""
    with tempfile.TemporaryDirectory() as d:
        segs = []
        for i, (fc, gp) in enumerate(pairs):
            seg = os.path.join(d, f"seg{i}.mp4")
            _stack_pair(ffmpeg, ffprobe, fc, gp, seg, width, facecam_h,
                        gameplay_h, game_audio_gain, fps, crf)
            segs.append(seg)
        if len(segs) == 1:
            subprocess.run([ffmpeg, "-y", "-i", segs[0], "-c", "copy", out],
                           check=True, capture_output=True)
        else:
            listfile = os.path.join(d, "concat.txt")
            with open(listfile, "w") as f:
                f.write("\n".join(f"file '{s}'" for s in segs))
            subprocess.run(
                [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", listfile,
                 "-c:v", "libx264", "-crf", f"{crf}", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-movflags", "+faststart", out],
                check=True, capture_output=True,
            )
    return len(segs)
