# ABOUTME: Tests the Gemini highlight-list parser — seconds and MM:SS timestamp
# ABOUTME: formats, the BEST line, field extraction, and junk tolerance.
import pytest

from _hypereel_highlights import parse_highlights, parse_timestamp


SECONDS_SAMPLE = """HIGHLIGHT 1 | start=2674 | end=2684 | Elevator Shaft Save | WHY: The player falls down an exploding elevator shaft and is dramatically caught by a teammate at the last second. | MOOD: clutch
HIGHLIGHT 2 | start=3008 | end=3020 | Motorcycle Jump | WHY: The player leaps from the back of a moving van onto a motorcycle. | MOOD: hype
BEST start=2674 end=2684"""

MMSS_SAMPLE = """HIGHLIGHT 1 | start=30:08 | end=30:17 | Van Jump Escape | WHY: A cinematic leap into a getaway van. | MOOD: hype
HIGHLIGHT 2 | start=14:01 | end=14:10 | Kitchen Tray Smash | WHY: A brutal tray takedown. | MOOD: brutal"""


class TestParseTimestamp:
    def test_plain_seconds(self):
        assert parse_timestamp("2674") == 2674.0

    def test_fractional_seconds(self):
        assert parse_timestamp("12.5") == 12.5

    def test_mm_ss(self):
        assert parse_timestamp("30:08") == 1808.0

    def test_hh_mm_ss(self):
        assert parse_timestamp("1:02:03") == 3723.0

    def test_garbage_is_none(self):
        assert parse_timestamp("soon") is None


class TestParseHighlights:
    def test_seconds_sample(self):
        hs = parse_highlights(SECONDS_SAMPLE)
        assert len(hs) == 2  # the BEST line is not a highlight row
        assert hs[0]["start"] == 2674.0
        assert hs[0]["end"] == 2684.0
        assert hs[0]["label"] == "Elevator Shaft Save"
        assert hs[0]["mood"] == "clutch"
        assert "exploding elevator shaft" in hs[0]["why"]

    def test_mmss_sample(self):
        hs = parse_highlights(MMSS_SAMPLE)
        assert hs[0]["start"] == 1808.0
        assert hs[1]["start"] == 841.0
        assert hs[1]["label"] == "Kitchen Tray Smash"

    def test_duration_derived(self):
        hs = parse_highlights(SECONDS_SAMPLE)
        assert hs[0]["end"] - hs[0]["start"] == pytest.approx(10.0)

    def test_junk_lines_skipped(self):
        text = "Here are the highlights:\n" + SECONDS_SAMPLE + "\n\nLet me know if you need more!"
        assert len(parse_highlights(text)) == 2

    def test_line_field_reconstructs_for_claude(self):
        hs = parse_highlights(SECONDS_SAMPLE)
        line = hs[0]["line"]
        assert "Elevator Shaft Save" in line and "MOOD: clutch" in line and "WHY:" in line

    def test_empty_text(self):
        assert parse_highlights("") == []


class TestSourceDurationFilter:
    def test_out_of_range_highlights_dropped(self):
        from _hypereel_highlights import filter_in_range
        hs = parse_highlights(SECONDS_SAMPLE)  # starts at 2674 and 3008
        kept, dropped = filter_in_range(hs, 600.0)
        assert kept == [] and len(dropped) == 2

    def test_in_range_kept(self):
        from _hypereel_highlights import filter_in_range
        hs = parse_highlights(MMSS_SAMPLE)  # 1808 and 841
        kept, dropped = filter_in_range(hs, 2000.0)
        assert len(kept) == 2 and dropped == []

    def test_zero_duration_means_no_filtering(self):
        from _hypereel_highlights import filter_in_range
        hs = parse_highlights(SECONDS_SAMPLE)
        kept, dropped = filter_in_range(hs, 0.0)
        assert len(kept) == 2 and dropped == []
