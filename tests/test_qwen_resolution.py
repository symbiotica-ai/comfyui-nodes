# ABOUTME: Tests for Qwen Resolution — the dropdown's sizes, and a wired image
# ABOUTME: picking the official size closest to its own aspect ratio.
import torch

from qwen_resolution_node import NSQwenResolution


def dims(resolution="1:1 (Square)", image=None):
    width, height, text, _ = NSQwenResolution().get_dimensions(resolution, image=image)
    return width, height, text


def blank(width, height):
    return torch.zeros(1, height, width, 3)


def test_dropdown_without_image():
    assert dims("4:3 (Standard Landscape)") == (1472, 1104, "1472 x 1104")


def test_square_flipped_and_stitched_is_16_9():
    # 1024 + 50 spacing + 1024 = 2098 x 1024
    assert dims("1:1 (Square)", blank(2098, 1024))[:2] == (1664, 928)


def test_one_by_two_flipped_and_stitched_is_1_1():
    # 928 + 50 spacing + 928 = 1906 x 1664, ratio 1.15: 1:1 is nearer than 4:3
    assert dims("4:3 (Standard Landscape)", blank(1906, 1664))[:2] == (1328, 1328)


def test_image_overrides_dropdown():
    assert dims("16:9 (Widescreen Landscape)", blank(1024, 1024))[:2] == (1328, 1328)
    assert dims("1:1 (Square)", blank(900, 1600))[:2] == (928, 1664)
    assert dims("1:1 (Square)", blank(1000, 1500))[:2] == (1056, 1584)


def test_optional_image_input_adds_no_widget():
    types = NSQwenResolution.INPUT_TYPES()
    assert list(types["required"]) == ["resolution"]
    assert types["optional"]["image"][0] == "IMAGE"
