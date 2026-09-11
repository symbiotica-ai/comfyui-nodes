# ABOUTME: Tests the control-image library — every image under input/controlnet,
# ABOUTME: listed by relative path, resolved safely, fingerprinted by content.
import os

import pytest

from _control_image import (CONTROL_DIR, control_image_path, file_fingerprint,
                            list_control_images)


def touch(root, rel, data=b"x"):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


@pytest.fixture
def input_dir(tmp_path):
    root = str(tmp_path)
    touch(root, f"{CONTROL_DIR}/appliance-1x1.png")
    touch(root, f"{CONTROL_DIR}/bakery/counter.png")
    touch(root, f"{CONTROL_DIR}/bakery/notes.txt")
    touch(root, f"{CONTROL_DIR}/.keep")
    touch(root, "elsewhere.png")
    return root


class TestListControlImages:
    def test_lists_images_under_controlnet_by_relative_path_sorted(self, input_dir):
        assert list_control_images(input_dir) == ["appliance-1x1.png", "bakery/counter.png"]

    def test_no_folder_lists_nothing(self, tmp_path):
        assert list_control_images(str(tmp_path)) == []


class TestControlImagePath:
    def test_resolves_inside_the_folder(self, input_dir):
        assert control_image_path(input_dir, "bakery/counter.png") == os.path.join(input_dir, CONTROL_DIR, "bakery", "counter.png")

    def test_refuses_a_path_that_walks_out(self, input_dir):
        with pytest.raises(ValueError):
            control_image_path(input_dir, "../elsewhere.png")
        with pytest.raises(ValueError):
            control_image_path(input_dir, "")


class TestFingerprint:
    def test_changes_with_the_bytes_not_the_name(self, input_dir):
        a = file_fingerprint(os.path.join(input_dir, CONTROL_DIR, "appliance-1x1.png"))
        touch(input_dir, f"{CONTROL_DIR}/appliance-1x1.png", b"yy")
        b = file_fingerprint(os.path.join(input_dir, CONTROL_DIR, "appliance-1x1.png"))
        assert a != b
        assert file_fingerprint(os.path.join(input_dir, CONTROL_DIR, "missing.png")) == ""
