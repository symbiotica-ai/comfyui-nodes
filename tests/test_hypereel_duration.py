# ABOUTME: Tests the script-duration parse — DURATION line extraction, clamping,
# ABOUTME: default fallback, and clean-prompt output for the video node.
from _hypereel_duration import parse_duration


class TestParseDuration:
    def test_extracts_and_strips_tagged_line(self):
        text, secs = parse_duration("Cut 1: she waves.\n\nDURATION: 9")
        assert secs == 9
        assert "DURATION" not in text
        assert text == "Cut 1: she waves."

    def test_case_and_whitespace_tolerant(self):
        text, secs = parse_duration("prompt body\n  duration:  11  \n")
        assert secs == 11
        assert text == "prompt body"

    def test_clamps_to_4_15(self):
        assert parse_duration("x\nDURATION: 30")[1] == 15
        assert parse_duration("x\nDURATION: 2")[1] == 4

    def test_missing_line_defaults_12_and_keeps_text(self):
        text, secs = parse_duration("just a prompt, no tag")
        assert secs == 12
        assert text == "just a prompt, no tag"

    def test_only_last_line_parsed_not_mid_text_mentions(self):
        body = "She says: \"the duration: 40 hours of gameplay\" wow.\nDURATION: 8"
        text, secs = parse_duration(body)
        assert secs == 8
        assert "40 hours" in text

    def test_mid_text_duration_line_not_stripped(self):
        body = "DURATION: 99 is not a real tag here because more prompt follows.\nreal ending"
        text, secs = parse_duration(body)
        assert secs == 12
        assert text == body
