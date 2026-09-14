# ABOUTME: Tests the control-image library — every image under the input folder
# ABOUTME: the node names, resolved safely, fingerprinted by content.
import os

import pytest

from _control_image import (CONTROL_DIR, base_dir, control_folder,
                            control_image_path, file_fingerprint,
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
    touch(root, "guides/wall.png")
    return root


class TestListControlImages:
    def test_lists_images_under_controlnet_by_relative_path_sorted(self, input_dir):
        assert list_control_images(input_dir) == ["appliance-1x1.png", "bakery/counter.png"]

    def test_no_folder_lists_nothing(self, tmp_path):
        assert list_control_images(str(tmp_path)) == []


class TestControlFolder:
    def test_empty_is_the_default(self):
        assert control_folder("") == CONTROL_DIR
        assert control_folder(None) == CONTROL_DIR

    def test_a_name_is_kept_and_tidied(self):
        assert control_folder("guides") == "guides"
        assert control_folder("guides/") == "guides"
        assert control_folder("  guides  ") == "guides"
        assert control_folder("a/b") == "a/b"

    def test_refuses_a_name_that_is_absolute_or_climbs_out(self):
        for bad in ("/etc", "/guides", "../up", "a/../..", "a//b"):
            with pytest.raises(ValueError):
                control_folder(bad)


class TestNamedFolder:
    def test_lists_the_folder_the_node_names(self, input_dir):
        assert list_control_images(input_dir, "guides") == ["wall.png"]

    def test_resolves_inside_the_named_folder(self, input_dir):
        assert control_image_path(input_dir, "wall.png", "guides") == \
            os.path.join(input_dir, "guides", "wall.png")

    def test_a_refused_folder_lists_nothing_and_raises_on_resolve(self, input_dir):
        assert list_control_images(input_dir, "../up") == []
        with pytest.raises(ValueError):
            control_image_path(input_dir, "wall.png", "../up")

    def test_the_default_folder_is_unchanged_by_the_new_argument(self, input_dir):
        assert list_control_images(input_dir, "") == list_control_images(input_dir)


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


class TestRoot:
    """The library moved off ComfyUI's input directory onto the studio-assets
    mount, so both halves of the location are the node's to say."""

    def test_empty_root_is_comfys_input_directory(self, input_dir):
        assert base_dir(input_dir, "") == input_dir
        assert base_dir(input_dir, None) == input_dir

    def test_an_absolute_root_wins(self, input_dir, tmp_path):
        other = str(tmp_path / "elsewhere")
        assert base_dir(input_dir, other) == other
        assert base_dir(input_dir, other + "/") == other

    def test_a_relative_root_is_refused(self, input_dir):
        # It would resolve against however ComfyUI happened to be launched.
        for bad in ("resources", "./resources", "../up"):
            with pytest.raises(ValueError):
                base_dir(input_dir, bad)

    def test_lists_and_resolves_under_the_named_root(self, tmp_path):
        mount = tmp_path / "studio-assets" / "_platform" / "resources"
        touch(str(mount), "controlnet/1x1/1x1-box.png")
        touch(str(mount), "controlnet/notes.txt")
        assert list_control_images("/unused", CONTROL_DIR, str(mount)) == \
            ["1x1/1x1-box.png"]
        assert control_image_path("/unused", "1x1/1x1-box.png", CONTROL_DIR,
                                  str(mount)) == \
            os.path.join(str(mount), CONTROL_DIR, "1x1", "1x1-box.png")

    def test_a_named_root_still_cannot_be_climbed_out_of(self, tmp_path):
        mount = tmp_path / "resources"
        touch(str(mount), "controlnet/keep.png")
        touch(str(tmp_path), "secret.png")
        with pytest.raises(ValueError):
            control_image_path("/unused", "../../secret.png", CONTROL_DIR,
                               str(mount))


class TestLoadRgba:
    """The reader used when the library is on another mount. LoadImage cannot
    reach there, and a graph must not be able to tell the two apart."""

    def _png(self, tmp_path, name, mode, colour):
        from PIL import Image
        path = tmp_path / name
        Image.new(mode, (4, 3), colour).save(path)
        return str(path)

    def test_alpha_becomes_the_inverted_mask(self, tmp_path):
        from _control_image import load_rgba
        # 25% opaque -> 0.75 transparent, LoadImage's 1 - alpha.
        path = self._png(tmp_path, "a.png", "RGBA", (10, 20, 30, 64))
        image, mask = load_rgba(path)
        assert tuple(image.shape) == (1, 3, 4, 3)
        assert tuple(mask.shape) == (1, 3, 4)
        assert abs(float(mask.max()) - (1.0 - 64 / 255.0)) < 1e-6
        assert abs(float(mask.min()) - (1.0 - 64 / 255.0)) < 1e-6

    def test_no_alpha_gets_loadimages_64x64_stand_in(self, tmp_path):
        from _control_image import load_rgba
        path = self._png(tmp_path, "b.png", "RGB", (10, 20, 30))
        image, mask = load_rgba(path)
        assert tuple(image.shape) == (1, 3, 4, 3)
        assert tuple(mask.shape) == (1, 64, 64)
        assert float(mask.max()) == 0.0

    def test_pixels_are_the_rgb_channels_scaled(self, tmp_path):
        from _control_image import load_rgba
        path = self._png(tmp_path, "c.png", "RGB", (255, 0, 128))
        image, _ = load_rgba(path)
        assert abs(float(image[0, 0, 0, 0]) - 1.0) < 1e-6
        assert abs(float(image[0, 0, 0, 1]) - 0.0) < 1e-6
        assert abs(float(image[0, 0, 0, 2]) - 128 / 255.0) < 1e-6


class TestWidgetOrder:
    """`widgets_values` restores positionally, so a workflow saved when `image`
    was the only widget must still land its name in `image`. A widget inserted
    ahead of it would take that value and leave the pick blank.

    Read off the source rather than the imported class: the node module uses a
    package-relative import and reaching it as `py.control_image` needs the repo
    root on the path, which is exactly what conftest keeps off it.
    """

    def test_image_is_declared_first(self):
        import ast

        src = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "py", "control_image.py")
        tree = ast.parse(open(src, encoding="utf-8").read())
        required = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = [k.value for k in node.keys
                    if isinstance(k, ast.Constant)]
            if keys == ["required"]:
                required = node.values[0]
                break
        assert required is not None, "INPUT_TYPES has no `required` dict"
        names = [k.value for k in required.keys if isinstance(k, ast.Constant)]
        assert names[0] == "image", names
        assert set(names) == {"image", "root", "folder"}
