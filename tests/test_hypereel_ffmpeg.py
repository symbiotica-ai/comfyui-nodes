# ABOUTME: Tests the Hypereel ffmpeg helpers — window clamping (the platform's exact
# ABOUTME: semantics), filtergraph strings, command builders, and an ffmpeg smoke test.
import os
import shutil
import subprocess
import tempfile

import pytest

from _hypereel_ffmpeg import (
    audio_mix_filter,
    audio_plan,
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
                                 game_audio_gain=0.3, fps=30, crf=23)
            assert cuts == 2
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0", out],
                check=True, capture_output=True, text=True).stdout.strip()
            assert probe == "1080,1920"
            assert probe_duration("ffprobe", out) == pytest.approx(4.0, abs=0.5)


class TestLayouts:
    """Layout templates replace raw pane numbers: named layouts carry the canvas +
    filtergraph; PiP layouts place the facecam in a chosen corner."""

    def test_vertical_stack_is_the_platform_default(self):
        from _hypereel_ffmpeg import LAYOUTS, layout_filter
        f, w, h = layout_filter("vertical · facecam top 40% / gameplay 60%", "bottom-right")
        assert (w, h) == (1080, 1920)
        assert "vstack=inputs=2" in f and "scale=1080:768" in f and "crop=1080:1152" in f

    def test_vertical_half_split(self):
        from _hypereel_ffmpeg import layout_filter
        f, w, h = layout_filter("vertical · half / half", "top-left")
        assert (w, h) == (1080, 1920)
        assert "scale=1080:960" in f and "crop=1080:960" in f

    def test_horizontal_pip_corners(self):
        from _hypereel_ffmpeg import layout_filter
        f, w, h = layout_filter("horizontal · gameplay full + facecam corner", "bottom-right")
        assert (w, h) == (1920, 1080)
        assert "overlay=" in f and "W-w-24" in f and "H-h-24" in f
        f_tl, _, _ = layout_filter("horizontal · gameplay full + facecam corner", "top-left")
        assert "overlay=24:24" in f_tl

    def test_vertical_pip(self):
        from _hypereel_ffmpeg import layout_filter
        f, w, h = layout_filter("vertical · gameplay full + facecam corner", "top-right")
        assert (w, h) == (1080, 1920)
        assert "overlay=W-w-24:24" in f

    def test_unknown_layout_raises(self):
        from _hypereel_ffmpeg import layout_filter
        with pytest.raises(KeyError):
            layout_filter("diagonal split", "top-left")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
class TestPipSmoke:
    def test_horizontal_pip_reel(self):
        with tempfile.TemporaryDirectory() as d:
            mk = TestComposeSmoke()
            fc = mk._testclip(d, "fc.mp4", 2, with_audio=True)
            gp = mk._testclip(d, "gp.mp4", 2, with_audio=False)
            out = os.path.join(d, "reel.mp4")
            cuts = compose_pairs([(fc, gp)], out,
                                 layout="horizontal · gameplay full + facecam corner",
                                 corner="bottom-right",
                                 game_audio_gain=0.3, fps=30, crf=23)
            assert cuts == 1
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0", out],
                check=True, capture_output=True, text=True).stdout.strip()
            assert probe == "1920,1080"


class TestClockMismatchGuard:
    """A start a few seconds past EOF is a legitimate clamp; a start BEYOND the
    source's whole timeline is a clock mismatch (e.g. absolute timestamps cut
    against a chapter clip) and must fail loudly, not silently cut the tail."""

    def test_small_overrun_still_clamps(self):
        from _hypereel_ffmpeg import checked_window
        # 58 + 5 overruns a 60s clip by 3s -> clamp, as before
        assert checked_window(58.0, 5.0, 60.0) == (55.0, 5.0)

    def test_start_beyond_source_raises_with_both_clocks(self):
        from _hypereel_ffmpeg import checked_window
        with pytest.raises(ValueError) as e:
            checked_window(1808.0, 9.0, 600.0)
        msg = str(e.value)
        assert "1808" in msg and "600" in msg

    def test_unknown_total_passes_through(self):
        from _hypereel_ffmpeg import checked_window
        assert checked_window(1808.0, 9.0, 0.0) == (1808.0, 9.0)


class TestCutoutFilter:
    def test_cutout_merges_alpha_and_overlays_at_corner(self):
        from _hypereel_ffmpeg import cutout_filter
        f = cutout_filter(1920, 1080, 560, "bottom-right")
        assert "alphamerge" in f
        assert "overlay=W-w-24:H-h-24" in f
        assert "[2:v]scale=560:-2" in f  # mask scaled with the facecam

    def test_mask_with_stack_layout_raises(self):
        from _hypereel_ffmpeg import layout_video_filter
        with pytest.raises(ValueError):
            layout_video_filter("vertical · facecam top 40% / gameplay 60%",
                                "bottom-right", with_mask=True)

    def test_layout_video_filter_picks_cutout_when_masked(self):
        from _hypereel_ffmpeg import layout_video_filter
        f, w, h = layout_video_filter("horizontal · gameplay full + facecam corner",
                                      "top-left", with_mask=True)
        assert "alphamerge" in f and (w, h) == (1920, 1080)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
class TestCutoutSmoke:
    def test_masked_facecam_lands_in_the_corner(self):
        with tempfile.TemporaryDirectory() as d:
            mk = TestComposeSmoke()
            fc = mk._testclip(d, "fc.mp4", 2, with_audio=True)
            gp = os.path.join(d, "gp.mp4")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                            "-i", "color=c=blue:size=640x360:rate=24", "-t", "2",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", gp],
                           check=True, capture_output=True)
            # mask: white square in the centre of the facecam frame
            mask = os.path.join(d, "mask.mp4")
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                            "-i", "color=c=black:size=640x360:rate=24",
                            "-vf", "drawbox=x=160:y=90:w=320:h=180:color=white:t=fill",
                            "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", mask],
                           check=True, capture_output=True)
            out = os.path.join(d, "out.mp4")
            cuts = compose_pairs([(fc, gp, mask)], out,
                                 layout="horizontal · gameplay full + facecam corner",
                                 corner="bottom-right",
                                 game_audio_gain=0.3, fps=30, crf=23)
            assert cuts == 1
            raw = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", "1", "-i", out,
                 "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                check=True, capture_output=True).stdout
            import numpy as np
            frame = np.frombuffer(raw, dtype=np.uint8).reshape(1080, 1920, 3)
            # top-left: pure gameplay (blue); masked-out facecam corner region edge
            # stays gameplay too because the mask is black there
            tl = frame[50, 50]
            assert tl[2] > 100 and tl[0] < 80  # blue-ish
            # centre of the pip region (mask white there) shows facecam content,
            # which is testsrc (not pure blue)
            cx, cy = 1920 - 24 - 280, 1080 - 24 - 158  # middle of 560-wide pip
            pip = frame[cy, cx]
            assert not (pip[2] > 100 and pip[0] < 80)


class TestAudioPlan:
    """No filtergraph may reference a [N:a] stream that doesn't exist — that's a
    hard ffmpeg failure. Voice+game mix only when both carry audio."""

    def test_both_audio_mixes(self):
        fg, amap = audio_plan(True, True, 0.30, "V")
        assert "amix" in fg and "[0:a]" in fg and "[1:a]" in fg
        assert amap == ["-map", "[v]", "-map", "[a]"]

    def test_facecam_silent_gameplay_audio_no_mix(self):
        fg, amap = audio_plan(False, True, 0.30, "V")
        assert "amix" not in fg and "[0:a]" not in fg  # would crash on a voiceless facecam
        assert amap == ["-map", "[v]", "-map", "1:a?"]

    def test_gameplay_silent_carries_facecam_voice(self):
        fg, amap = audio_plan(True, False, 0.30, "V")
        assert fg == "V" and amap == ["-map", "[v]", "-map", "0:a?"]

    def test_neither_has_audio_is_safe(self):
        fg, amap = audio_plan(False, False, 0.30, "V")
        assert amap == ["-map", "[v]", "-map", "0:a?"]  # optional map, no crash


class TestComposeInterrupt:
    def test_polls_interrupt_before_each_pair(self, monkeypatch):
        import _hypereel_ffmpeg as ff
        calls = []
        monkeypatch.setattr(ff, "_compose_pair", lambda *a, **k: calls.append(1))
        flags = iter([False, True])  # cancel arrives before the 2nd pair
        with pytest.raises(InterruptedError):
            ff.compose_pairs([("a", "b"), ("c", "d"), ("e", "f")], "out",
                             interrupt=lambda: next(flags))
        assert len(calls) == 1  # only the first pair encoded before the cancel

    def test_no_interrupt_runs_all(self, monkeypatch, tmp_path):
        import _hypereel_ffmpeg as ff
        calls = []
        monkeypatch.setattr(ff, "_compose_pair", lambda *a, **k: calls.append(1))
        monkeypatch.setattr(ff.subprocess, "run", lambda *a, **k: None)  # concat no-op
        ff.compose_pairs([("a", "b"), ("c", "d")], str(tmp_path / "o.mp4"))
        assert len(calls) == 2
