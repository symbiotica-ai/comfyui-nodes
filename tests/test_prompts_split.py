# ABOUTME: Tests for the enhanced-prompt parser feeding desc_N sockets.
from pipeline.prompts_split import parse_region_prompts


def test_json_array_of_strings():
    out = parse_region_prompts('["ghost queue", "freezer cart"]', max_n=4)
    assert out == ["ghost queue", "freezer cart", "", ""]


def test_json_fenced_and_object_entries():
    text = '```json\n[{"id": "a", "desc": "cats"}, {"prompt": "cookies"}]\n```'
    assert parse_region_prompts(text, max_n=3) == ["cats", "cookies", ""]


def test_json_wrapped_in_regions_key():
    assert parse_region_prompts('{"regions": ["a", "b"]}', max_n=2) == ["a", "b"]


def test_numbered_lines_fallback():
    text = "1. ghost queue with trays\n2) freezer cart,\nblue stripes\n3. cats"
    out = parse_region_prompts(text, max_n=4)
    assert out == ["ghost queue with trays", "freezer cart, blue stripes", "cats", ""]


def test_garbage_and_empty_pad():
    assert parse_region_prompts("", max_n=2) == ["", ""]
    assert parse_region_prompts("no structure here", max_n=2) == ["", ""]


def test_truncates_past_max():
    out = parse_region_prompts('["a","b","c"]', max_n=2)
    assert out == ["a", "b"]
