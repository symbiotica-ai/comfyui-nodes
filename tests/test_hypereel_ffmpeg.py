# ABOUTME: Tests the Hypereel ffmpeg helpers — window clamping (the platform's exact
# ABOUTME: semantics), filtergraph strings, command builders, and an ffmpeg smoke test.
import os
import shutil
import subprocess
import tempfile

import pytest

from _hypereel_ffmpeg import (
    audio_mix_filter,
    clamp_window,
    clip_cmd,
    compose_pairs,
    probe_duration,
    vstack_filter,
)


class TestClampWindow:
    """The platform's compose() clamp: keep the window fully inside the clip so a
    highlight near EOF still yields a full-length slice, not a stub."""

    def test_inside_passes_through(self):
        assert clamp_window(10.0, 5.0, 60.0) == (10.0, 5.0)

    def test_duration_capped_to_total(self):
        assert clamp_window(0.0, 90.0, 60.0) == (0.0, 60.0)

    def test_start_backed_off_the_end(self):
        # start 58 + dur 5 overruns a 60s clip -> back off to 55
        assert clamp_window(58.0, 5.0, 60.0) == (55.0, 5.0)

    def test_negative_start_floors_to_zero(self):
        assert clamp_window(-3.0, 5.0, 60.0) == (0.0, 5.0)

    def test_unknown_total_passes_through(self):
        # total 0 = probe failed; do not clamp (platform behavior)
        assert clamp_window(58.0, 5.0, 0.0) == (58.0, 5.0)


class TestFilters:
    def test_vstack_geometry(self):
        f = vstack_filter(1080, 768, 1152)
        assert "scale=1080:768:force_original_aspect_ratio=increase" in f
        assert "crop=1080:1152" in f
        assert "vstack=inputs=2" in f

    def test_audio_mix_keeps_preset_volumes(self):
        f = audio_mix_filter(0.30)
        # normalize=0 keeps the pre-set volumes (amix defaults to normalizing,
        # which would halve the voice) — the /dev-release finding, ported.
        assert "normalize=0" in f
        assert "volume=0.3" in f
        assert "volume=1.0" in f


class TestClipCmd:
    def test_seeks_before_input_and_reencodes(self):
        cmd = clip_cmd("ffmpeg", "in.mp4", "out.mp4", 12.0, 8.0, keep_audio=True)
        assert cmd.index("-ss") < cmd.index("-i")  # fast input seek
        assert "-t" in cmd and "8.0" in cmd
        assert "libx264" in cmd and "aac" in cmd

    def test_drop_audio(self):
        cmd = clip_cmd("ffmpeg", "in.mp4", "out.mp4", 0.0, 5.0, keep_audio=False)
        assert "-an" in cmd and "aac" not in cmd


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
class TestComposeSmoke:
    """Real ffmpeg end-to-end on synthetic clips: two pairs stacked + concatenated
    must yield a 1080x1920 reel of both cuts."""

    def _testclip(self, d, name, seconds, with_audio):
        path = os.path.join(d, name)
        cmd = ["ffmpeg", "-y", "-v", "error",
               "-f", "lavfi", "-i", f"testsrc=size=640x360:rate=24:duration={seconds}"]
        if with_audio:
            cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    "-c:a", "aac", "-shortest"]
        cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", path]
        subprocess.run(cmd, check=True, capture_output=True)
        return path

    def test_two_pairs_make_a_vertical_reel(self):
        with tempfile.TemporaryDirectory() as d:
            fc1 = self._testclip(d, "fc1.mp4", 2, with_audio=True)
            gp1 = self._testclip(d, "gp1.mp4", 2, with_audio=False)
            fc2 = self._testclip(d, "fc2.mp4", 2, with_audio=True)
            gp2 = self._testclip(d, "gp2.mp4", 2, with_audio=True)
            out = os.path.join(d, "reel.mp4")
            cuts = compose_pairs([(fc1, gp1), (fc2, gp2)], out,
                                 width=1080, facecam_h=768, gameplay_h=1152,
                                 game_audio_gain=0.3, fps=30, crf=23)
            assert cuts == 2
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0", out],
                check=True, capture_output=True, text=True).stdout.strip()
            assert probe == "1080,1920"
            assert probe_duration("ffprobe", out) == pytest.approx(4.0, abs=0.5)
