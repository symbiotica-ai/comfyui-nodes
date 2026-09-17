# ABOUTME: The control-image library — every image under the folder the node
# ABOUTME: points at, resolved safely, fingerprinted by content.
import os

import pytest

from _control_image import (control_image_path, file_fingerprint, library_dir,
                            list_control_images)


def touch(root, rel, data=b"x"):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path


@pytest.fixture
def library(tmp_path):
    """The shape on the studio-assets mount."""
    root = str(tmp_path / "studio-assets" / "_platform" / "resources"
               / "controlnet-images")
    touch(root, "general/1x1/1x1-box.png")
    touch(root, "general/1x1/1x1-floor.png")
    touch(root, "general/1x2/1x2-box-dots.png")
    touch(root, "project-specific/chair/Loveletter Lounge Chair.png")
    return root


class TestTheFolder:
    def test_an_absolute_path_is_the_whole_answer(self, library):
        assert library_dir(library) == library
        assert library_dir(library + "/") == library

    def test_no_path_says_so_rather_than_guessing_a_default(self):
        # The images are not in ComfyUI's input directory, so there is no
        # default worth falling back to — a silent one is what sent the node
        # looking in `<library>/controlnet`.
        with pytest.raises(ValueError, match="no image folder"):
            library_dir("")
        with pytest.raises(ValueError, match="no image folder"):
            library_dir(None)

    def test_a_relative_path_is_refused(self):
        with pytest.raises(ValueError, match="absolute"):
            library_dir("controlnet-images")
        with pytest.raises(ValueError, match="absolute"):
            library_dir("./images")


class TestListing:
    def test_every_image_under_the_path_including_sub_folders(self, library):
        assert list_control_images(library) == [
            "general/1x1/1x1-box.png",
            "general/1x1/1x1-floor.png",
            "general/1x2/1x2-box-dots.png",
            "project-specific/chair/Loveletter Lounge Chair.png",
        ]

    def test_the_sub_folder_is_part_of_the_value(self, library):
        # One pick reaches a file three levels down; nothing has to be opened
        # first.
        assert "general/1x1/1x1-box.png" in list_control_images(library)

    def test_dotfiles_and_other_types_are_left_out(self, tmp_path):
        root = str(tmp_path / "lib")
        touch(root, "a.png")
        touch(root, ".hidden.png")
        touch(root, "notes.txt")
        touch(root, ".git/objects/x.png")
        assert list_control_images(root) == ["a.png"]

    def test_a_missing_or_unsayable_folder_lists_nothing(self, tmp_path):
        assert list_control_images(str(tmp_path / "nope")) == []
        assert list_control_images("") == []
        assert list_control_images("relative") == []


class TestResolving:
    def test_a_picked_name_resolves_under_the_path(self, library):
        assert control_image_path(library, "general/1x1/1x1-box.png") == \
            os.path.join(library, "general", "1x1", "1x1-box.png")

    def test_a_name_cannot_climb_out(self, library):
        with pytest.raises(ValueError, match="outside"):
            control_image_path(library, "../../secret.png")

    def test_an_empty_name_is_refused(self, library):
        with pytest.raises(ValueError, match="no control image named"):
            control_image_path(library, "")

    def test_no_path_is_refused(self):
        with pytest.raises(ValueError, match="no image folder"):
            control_image_path("", "a.png")


class TestFingerprint:
    def test_the_bytes_decide_not_the_name(self, tmp_path):
        a = touch(str(tmp_path), "a.png", b"one")
        assert file_fingerprint(a) == file_fingerprint(a)
        touch(str(tmp_path), "a.png", b"two")
        assert file_fingerprint(a) != file_fingerprint(
            touch(str(tmp_path), "b.png", b"one"))

    def test_a_missing_file_fingerprints_to_nothing(self, tmp_path):
        assert file_fingerprint(str(tmp_path / "nope.png")) == ""


class TestTheRunHandsBackThePath:
    """A path arriving through a Get node has no value on the canvas, so the
    run is what tells the dropdown where it reads."""

    @pytest.fixture
    def node_module(self, monkeypatch):
        """`py/control_image.py` loaded as part of a package, because its
        imports are relative — the pack is never a loose module."""
        import importlib
        import sys
        import types

        py_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        py_dir = os.path.join(py_dir, "py")
        pkg = types.ModuleType("symnodes")
        pkg.__path__ = [py_dir]
        monkeypatch.setitem(sys.modules, "symnodes", pkg)
        # `load` imports the routes lazily, and they want ComfyUI's server.
        routes = types.ModuleType("symnodes.pipeline.routes")
        routes.register_root = lambda path: None
        pipeline = types.ModuleType("symnodes.pipeline")
        pipeline.routes = routes
        monkeypatch.setitem(sys.modules, "symnodes.pipeline", pipeline)
        monkeypatch.setitem(sys.modules, "symnodes.pipeline.routes", routes)
        module = importlib.import_module("symnodes.control_image")
        monkeypatch.setitem(sys.modules, "symnodes.control_image", module)
        return module

    def test_it_is_an_output_node_so_it_can_be_queued_alone(self, node_module):
        assert node_module.SymbioticaControlImage.OUTPUT_NODE is True

    def test_the_run_pushes_the_folder_it_received(self, node_module, library,
                                                   monkeypatch):
        pushed = []
        monkeypatch.setattr(node_module, "_push",
                            lambda event, payload: pushed.append((event, payload)))
        monkeypatch.setattr(node_module, "load_rgba",
                            lambda path: ("IMAGE", "MASK"))
        node_module.SymbioticaControlImage().load(
            "general/1x1/1x1-box.png", library, unique_id=7)
        assert pushed == [("symbiotica.control_image",
                           {"node_id": "7", "path": library})]

    def test_a_run_that_cannot_resolve_the_file_pushes_nothing(self, node_module,
                                                               library, monkeypatch):
        pushed = []
        monkeypatch.setattr(node_module, "_push",
                            lambda event, payload: pushed.append((event, payload)))
        with pytest.raises(ValueError):
            node_module.SymbioticaControlImage().load("a.png", "", unique_id=7)
        assert pushed == []

    def test_a_wired_path_is_not_refused_before_it_has_spoken(self, node_module):
        # Validation runs before execution, so a path arriving from a Get node
        # is empty here. This is the exact failure the canvas showed:
        # "Invalid input — a node rejected one or more input values".
        node = node_module.SymbioticaControlImage
        assert node.VALIDATE_INPUTS("general/1x1/1x1-box.png", "") is True
        assert node.VALIDATE_INPUTS("general/1x1/1x1-box.png", None) is True

    def test_a_typed_path_is_still_checked(self, node_module, library):
        node = node_module.SymbioticaControlImage
        assert node.VALIDATE_INPUTS("general/1x1/1x1-box.png", library) is True
        assert "no image" in node.VALIDATE_INPUTS("gone.png", library)
        assert "absolute" in node.VALIDATE_INPUTS("a.png", "controlnet-images")
