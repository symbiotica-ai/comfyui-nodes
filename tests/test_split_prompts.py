# ABOUTME: Tests the paragraph splitter behind the Split Prompts node —
# ABOUTME: blank-line splitting, the empty-breakline toggle, and edge cases.
from _split_prompts import split_prompts

FIVE = "\n\n".join(f"Clothing Booth prompt {i}." for i in range(1, 6))


def test_five_paragraphs_become_five_prompts():
    out = split_prompts(FIVE)
    assert len(out) == 5
    assert out[0] == "Clothing Booth prompt 1."
    assert out[4] == "Clothing Booth prompt 5."


def test_toggle_on_strips_empty_line():
    out = split_prompts("a\n\nb\n\n")
    assert out == ["a", "b"]


def test_toggle_off_keeps_empty_line():
    out = split_prompts("a\n\nb", remove_empty_breakline=False)
    assert out == ["a\n\n", "b\n\n"]


def test_multiple_blank_lines_and_whitespace_only_lines():
    out = split_prompts("a\n\n\n\n  \nb")
    assert out == ["a", "b"]


def test_crlf_and_single_newlines_inside_a_paragraph():
    out = split_prompts("line one\r\nline two\r\n\r\nnext")
    assert out == ["line one\nline two", "next"]


def test_empty_input():
    assert split_prompts("") == []
    assert split_prompts("\n\n  \n") == []
