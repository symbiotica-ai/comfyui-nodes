# ABOUTME: Tests the screen-glow helpers — signal resampling, temporal smoothing,
# ABOUTME: screen-blend math, the bottom-up gradient, and a real-ffmpeg smoke test.
import os
import shutil
import subprocess
import tempfile

import numpy as np
import pytest

from _hypereel_glow import (
    blend_glow,
    bottom_gradient,
    ema_smooth,
    resample_signal,
    run_glow,
)


class TestSignal:
    def test_resample_stretches_to_target_length(self):
        sig = np.array([[0, 0, 0], [255, 255, 255]], dtype=np.float32)
        out = resample_signal(sig, 5)
        assert out.shape == (5, 3)
        assert out[0][0] == 0 and out[-1][0] == 255
        assert 100 < out[2][0] < 155  # midpoint interpolates

    def test_ema_smooth_zero_is_identity(self):
        sig = np.array([[0.0] * 3, [255.0] * 3, [0.0] * 3], dtype=np.float32)
        out = ema_smooth(sig, 0.0)
        assert np.allclose(out, sig)

    def test_ema_smooth_damps_flicker(self):
        sig = np.array([[0.0] * 3, [255.0] * 3, [0.0] * 3], dtype=np.float32)
        out = ema_smooth(sig, 0.8)
        assert out[1][0] < 255.0 and out[2][0] > 0.0


class TestBlend:
    def test_glow_brightens_never_darkens(self):
        frame = np.full((4, 4, 3), 100, dtype=np.uint8)
        glow = np.array([200.0, 50.0, 50.0], dtype=np.float32)
        grad = bottom_gradient(4)
        out = blend_glow(frame, glow, grad, strength=0.5)
        assert out.dtype == np.uint8
        assert (out.astype(int) >= frame.astype(int)).all()

    def test_zero_strength_is_identity(self):
        frame = np.random.randint(0, 255, (4, 4, 3), dtype=np.uint8)
        out = blend_glow(frame, np.array([255.0] * 3), bottom_gradient(4), strength=0.0)
        assert np.array_equal(out, frame)

    def test_gradient_stronger_at_bottom(self):
        g = bottom_gradient(10)
        assert g[-1] > g[0] and g.shape == (10,)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
class TestGlowSmoke:
    def _clip(self, d, name, vf, seconds=2, audio=False):
        path = os.path.join(d, name)
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", vf]
        if audio:
            cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-c:a", "aac", "-shortest"]
        cmd += ["-t", str(seconds), "-c:v", "libx264", "-pix_fmt", "yuv420p", path]
        subprocess.run(cmd, check=True, capture_output=True)
        return path

    def test_bright_gameplay_brightens_the_facecam(self):
        with tempfile.TemporaryDirectory() as d:
            facecam = self._clip(d, "fc.mp4", "color=c=gray:size=320x240:rate=24", audio=True)
            bright = self._clip(d, "gp_bright.mp4", "color=c=white:size=320x240:rate=24")
            dark = self._clip(d, "gp_dark.mp4", "color=c=black:size=320x240:rate=24")
            out_b = os.path.join(d, "out_b.mp4")
            out_d = os.path.join(d, "out_d.mp4")
            run_glow(facecam, bright, out_b, strength=0.6, smoothing=0.3)
            run_glow(facecam, dark, out_d, strength=0.6, smoothing=0.3)

            def mean_luma(path):
                raw = subprocess.run(
                    ["ffmpeg", "-v", "error", "-i", path, "-vf", "scale=1:1",
                     "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                    check=True, capture_output=True).stdout
                return raw[0]

            assert mean_luma(out_b) > mean_luma(out_d) + 10

    def test_audio_survives(self):
        with tempfile.TemporaryDirectory() as d:
            facecam = self._clip(d, "fc.mp4", "color=c=gray:size=320x240:rate=24", audio=True)
            gp = self._clip(d, "gp.mp4", "testsrc=size=320x240:rate=24")
            out = os.path.join(d, "out.mp4")
            run_glow(facecam, gp, out, strength=0.4, smoothing=0.5)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                 "stream=codec_type", "-of", "default=nw=1", out],
                capture_output=True, text=True).stdout
            assert "audio" in probe
