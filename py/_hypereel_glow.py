# ABOUTME: Screen-glow helpers — samples the gameplay's per-frame color and screen-blends
# ABOUTME: it onto the facecam as a bottom-up monitor glow. Deterministic; audio untouched.
import json
import subprocess

import numpy as np


def probe_video(ffprobe, path):
    """(width, height, fps, nb_frames_estimate) of the first video stream."""
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate,duration",
         "-of", "json", path],
        check=True, capture_output=True, text=True,
    ).stdout
    s = json.loads(out)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    fps = float(num) / float(den)
    duration = float(s.get("duration") or 0)
    return int(s["width"]), int(s["height"]), fps, max(1, int(round(duration * fps)))


def gameplay_signal(ffmpeg, path):
    """Per-frame mean color of a video as an (N, 3) float array — decoded at 1x1
    pixels, so a long clip costs almost nothing."""
    raw = subprocess.run(
        [ffmpeg, "-v", "error", "-i", path, "-vf", "scale=1:1",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True, capture_output=True,
    ).stdout
    n = len(raw) // 3
    return np.frombuffer(raw[: n * 3], dtype=np.uint8).reshape(n, 3).astype(np.float32)


def resample_signal(signal, target_len):
    """Linearly resamples an (N, 3) signal to (target_len, 3) so the gameplay's
    timeline maps onto the facecam's frame count."""
    n = signal.shape[0]
    if n == target_len:
        return signal.copy()
    src_x = np.linspace(0.0, 1.0, n)
    dst_x = np.linspace(0.0, 1.0, target_len)
    return np.stack([np.interp(dst_x, src_x, signal[:, c]) for c in range(3)], axis=1).astype(np.float32)


def ema_smooth(signal, smoothing):
    """Exponential moving average over frames. 0 = raw flicker, towards 1 = slower,
    softer light changes (real monitor glow has a little lag and diffusion)."""
    if smoothing <= 0:
        return signal.copy()
    a = 1.0 - min(0.99, float(smoothing))
    out = signal.copy()
    for i in range(1, out.shape[0]):
        out[i] = a * signal[i] + (1.0 - a) * out[i - 1]
    return out


def bottom_gradient(height):
    """Vertical weight, strongest at the bottom of the frame — the monitor sits
    below the webcam, so screen light hits the lower face/chest first."""
    return np.linspace(0.35, 1.0, height).astype(np.float32)


def blend_glow(frame, glow_rgb, gradient, strength):
    """Screen-blends the glow color onto one frame: brightens, never darkens,
    saturating gently instead of clipping. frame HxWx3 uint8 -> uint8."""
    if strength <= 0:
        return frame.copy()
    f = frame.astype(np.float32) / 255.0
    weight = (gradient * float(strength))[:, None, None]  # HxWx1 broadcast
    glow = (glow_rgb / 255.0)[None, None, :] * weight
    out = 1.0 - (1.0 - f) * (1.0 - glow)  # screen blend
    return (np.clip(out, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def run_glow(facecam, gameplay, out, strength=0.35, smoothing=0.5,
             ffmpeg="ffmpeg", ffprobe="ffprobe"):
    """Streams the facecam frame by frame, screen-blending the gameplay's smoothed
    per-frame color as a bottom-up glow; the facecam's own audio is mapped through
    untouched. Constant memory — clip length never matters."""
    w, h, fps, nframes = probe_video(ffprobe, facecam)
    signal = ema_smooth(resample_signal(gameplay_signal(ffmpeg, gameplay), nframes), smoothing)
    gradient = bottom_gradient(h)

    dec = subprocess.Popen(
        [ffmpeg, "-v", "error", "-i", facecam,
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        stdout=subprocess.PIPE,
    )
    enc = subprocess.Popen(
        [ffmpeg, "-y", "-v", "error",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", f"{fps}", "-i", "-",
         "-i", facecam,
         "-map", "0:v", "-map", "1:a?",
         "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p",
         "-c:a", "copy", "-movflags", "+faststart", out],
        stdin=subprocess.PIPE,
    )
    frame_bytes = w * h * 3
    i = 0
    try:
        while True:
            buf = dec.stdout.read(frame_bytes)
            if not buf or len(buf) < frame_bytes:
                break
            frame = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 3)
            glow_rgb = signal[min(i, signal.shape[0] - 1)]
            enc.stdin.write(blend_glow(frame, glow_rgb, gradient, strength).tobytes())
            i += 1
    finally:
        dec.stdout.close()
        enc.stdin.close()
        dec.wait()
        rc = enc.wait()
    if rc != 0:
        raise RuntimeError("ffmpeg encode failed for the glow pass")
    return i
