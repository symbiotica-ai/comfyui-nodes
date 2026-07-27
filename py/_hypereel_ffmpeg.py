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


def checked_window(start, dur, total):
    """clamp_window plus a loud failure for clock mismatches: a start a few
    seconds past EOF is a legitimate clamp, but a start beyond the source's whole
    timeline means the timestamps belong to a different video (e.g. absolute
    full-video times cut against a chapter clip) — silent clamping would just
    manufacture a tail cut. total 0 = unknown -> pass through."""
    if total > 0 and float(start) >= total:
        raise ValueError(
            f"start {start:.0f}s is beyond the {total:.0f}s source — the timestamps "
            f"and this video use different clocks (chapter vs full video?)"
        )
    return clamp_window(start, dur, total)


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


def audio_plan(has_facecam_audio, has_gameplay_audio, gain, video_filter):
    """(filtergraph, output audio map) for a pair. Mix her voice ([0:a], full) with
    the game ([1:a], at `gain`) only when BOTH inputs carry audio — the mix filter
    references both streams, so a voiceless facecam or silent gameplay would make
    ffmpeg fail on a missing stream. Otherwise carry whichever single track exists
    via an optional (`?`) map that never crashes."""
    if has_facecam_audio and has_gameplay_audio:
        return f"{video_filter};{audio_mix_filter(gain)}", ["-map", "[v]", "-map", "[a]"]
    if has_gameplay_audio:  # facecam silent — carry the gameplay track
        return video_filter, ["-map", "[v]", "-map", "1:a?"]
    return video_filter, ["-map", "[v]", "-map", "0:a?"]  # gameplay silent (or neither)


# Named layout templates — each carries its canvas and how the facecam meets the
# gameplay. Stack layouts split the canvas; PiP layouts run the gameplay full-frame
# with the facecam overlaid in a corner (24px margin).
LAYOUTS = {
    "vertical · facecam top 40% / gameplay 60%": {
        "canvas": (1080, 1920), "mode": "stack", "facecam_h": 768,
    },
    "vertical · half / half": {
        "canvas": (1080, 1920), "mode": "stack", "facecam_h": 960,
    },
    "vertical · gameplay full + facecam corner": {
        "canvas": (1080, 1920), "mode": "pip", "pip_w": 460,
    },
    "horizontal · gameplay full + facecam corner": {
        "canvas": (1920, 1080), "mode": "pip", "pip_w": 560,
    },
}

DEFAULT_LAYOUT = "vertical · facecam top 40% / gameplay 60%"

# overlay x:y per corner — W/H are the gameplay canvas, w/h the facecam overlay.
_CORNERS = {
    "top-left": "24:24",
    "top-right": "W-w-24:24",
    "bottom-left": "24:H-h-24",
    "bottom-right": "W-w-24:H-h-24",
}


def pip_filter(w, h, pip_w, corner):
    """Gameplay scaled+center-cropped to the full w×h canvas; facecam scaled to
    pip_w wide (aspect kept) and overlaid in the chosen corner."""
    pos = _CORNERS[corner]
    return (
        f"[1:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},setsar=1[gpv];"
        f"[0:v]scale={pip_w}:-2,setsar=1[fcv];"
        f"[gpv][fcv]overlay={pos}[v]"
    )


def write_gray_video(ffmpeg, frames, w, h, fps, out):
    """Writes an (N,H,W) uint8 array as a grayscale video — the mask track for
    cutout compositing (alphamerge input)."""
    enc = subprocess.Popen(
        [ffmpeg, "-y", "-v", "error",
         "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{w}x{h}", "-r", f"{fps}", "-i", "-",
         "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", out],
        stdin=subprocess.PIPE,
    )
    try:
        for i in range(frames.shape[0]):
            enc.stdin.write(frames[i].tobytes())
    finally:
        enc.stdin.close()
        rc = enc.wait()
    if rc != 0:
        raise RuntimeError("ffmpeg failed writing the mask video")


def cutout_filter(w, h, pip_w, corner):
    """Cutout variant of the corner layouts: the facecam is keyed by a mask video
    (input 2) via alphamerge, so the streamer's silhouette — not a rectangle —
    lands in the corner over the full-frame gameplay."""
    pos = _CORNERS[corner]
    return (
        f"[1:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},setsar=1[gpv];"
        f"[0:v]scale={pip_w}:-2,setsar=1[fcv];"
        f"[2:v]scale={pip_w}:-2[mkv];"
        f"[fcv][mkv]alphamerge[fca];"
        f"[gpv][fca]overlay={pos}[v]"
    )


def layout_video_filter(layout, corner, with_mask=False):
    """The video filtergraph + canvas for a named layout, cutout-aware. A mask on
    a stack layout is a wiring mistake — fail loudly rather than ignore it."""
    spec = LAYOUTS[layout]
    w, h = spec["canvas"]
    if with_mask:
        if spec["mode"] != "pip":
            raise ValueError(
                f"a facecam mask needs a corner layout, not '{layout}' - "
                f"pick one of the 'gameplay full + facecam corner' layouts"
            )
        return (cutout_filter(w, h, spec["pip_w"], corner), w, h)
    if spec["mode"] == "stack":
        return (vstack_filter(w, spec["facecam_h"], h - spec["facecam_h"]), w, h)
    return (pip_filter(w, h, spec["pip_w"], corner), w, h)


def layout_filter(layout, corner):
    """The video filtergraph + canvas for a named layout. KeyError on unknown
    layout/corner — the node surfaces it as a node error."""
    spec = LAYOUTS[layout]
    w, h = spec["canvas"]
    if spec["mode"] == "stack":
        return (vstack_filter(w, spec["facecam_h"], h - spec["facecam_h"]), w, h)
    return (pip_filter(w, h, spec["pip_w"], corner), w, h)


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


def _compose_pair(ffmpeg, ffprobe, facecam, gameplay, out, layout, corner, gain,
                  fps, crf, mask=None):
    """One cut in the chosen layout; her voice full, game audio mixed at `gain`
    only when the gameplay actually has a track. A mask video keys the facecam
    into a cutout (corner layouts only). Segment = min(facecam, gameplay)."""
    fdur = probe_duration(ffprobe, facecam)
    gdur = probe_duration(ffprobe, gameplay)
    dur = min(fdur, gdur) if (fdur and gdur) else (fdur or gdur or 5.0)
    video, _, _ = layout_video_filter(layout, corner, with_mask=mask is not None)
    filtergraph, amap = audio_plan(
        probe_has_audio(ffprobe, facecam), probe_has_audio(ffprobe, gameplay),
        gain, video)
    inputs = [ffmpeg, "-y", "-i", facecam, "-i", gameplay]
    if mask is not None:
        inputs += ["-i", mask]
    subprocess.run(
        [*inputs, "-filter_complex", filtergraph,
         *amap, "-r", f"{fps}", "-c:v", "libx264", "-crf", f"{crf}",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-ar", "48000",
         "-movflags", "+faststart", "-t", f"{dur}", out],
        check=True, capture_output=True,
    )


def compose_pairs(pairs, out, layout=DEFAULT_LAYOUT, corner="bottom-right",
                  game_audio_gain=0.30, fps=30, crf=20,
                  ffmpeg="ffmpeg", ffprobe="ffprobe", interrupt=None):
    """Compose each (facecam, gameplay) file pair into one cut in the chosen
    layout and hard-cut-concat the cuts in order into `out`. Returns the cut count.
    `interrupt()` (optional) is polled before each pair — a truthy return raises
    InterruptedError so a pressed Cancel stops the multi-encode job promptly."""
    with tempfile.TemporaryDirectory() as d:
        segs = []
        for i, pair in enumerate(pairs):
            if interrupt and interrupt():
                raise InterruptedError("compose cancelled")
            fc, gp = pair[0], pair[1]
            mask = pair[2] if len(pair) > 2 else None
            seg = os.path.join(d, f"seg{i}.mp4")
            _compose_pair(ffmpeg, ffprobe, fc, gp, seg, layout, corner,
                          game_audio_gain, fps, crf, mask=mask)
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
