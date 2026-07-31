# ABOUTME: Tests the path containment primitive — a caller-supplied value resolves
# ABOUTME: inside a declared root or is refused, with symlinks and traversal closed.
import os

import pytest

from pipeline.paths import resolve_within


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "root"
    (r / "sub").mkdir(parents=True)
    (r / "sub" / "a.png").write_bytes(b"x")
    (r / "note.txt").write_bytes(b"x")
    return r


class TestContainment:
    def test_a_path_inside_the_root_resolves(self, root):
        got = resolve_within([str(root)], str(root / "sub" / "a.png"))
        assert got == os.path.realpath(str(root / "sub" / "a.png"))

    def test_the_root_itself_resolves(self, root):
        assert resolve_within([str(root)], str(root)) == os.path.realpath(str(root))

    def test_a_sibling_outside_the_root_is_refused(self, root, tmp_path):
        outside = tmp_path / "outside.png"
        outside.write_bytes(b"x")
        assert resolve_within([str(root)], str(outside)) is None

    def test_traversal_out_of_the_root_is_refused(self, root):
        assert resolve_within([str(root)], str(root / ".." / "outside.png")) is None

    def test_a_prefix_sibling_is_not_inside(self, tmp_path):
        # "/a/root" must not admit "/a/root-evil": a bare startswith would.
        (tmp_path / "root").mkdir()
        evil = tmp_path / "root-evil"
        evil.mkdir()
        (evil / "f.png").write_bytes(b"x")
        assert resolve_within([str(tmp_path / "root")], str(evil / "f.png")) is None

    def test_a_symlink_pointing_out_is_refused(self, root, tmp_path):
        secret = tmp_path / "secret.png"
        secret.write_bytes(b"x")
        link = root / "sub" / "link.png"
        link.symlink_to(secret)
        assert resolve_within([str(root)], str(link)) is None

    def test_no_roots_refuses_everything(self, root):
        assert resolve_within([], str(root / "sub" / "a.png")) is None

    def test_the_filesystem_root_admits_nothing(self, root):
        # "/" as a root would otherwise make containment meaningless.
        assert resolve_within(["/"], str(root / "sub" / "a.png")) is None


class TestRefusesBadInput:
    @pytest.mark.parametrize("bad", ["", None, "rel/path.png", "bad\x00path.png"])
    def test_unusable_values_are_refused_not_raised(self, root, bad):
        assert resolve_within([str(root)], bad) is None

    def test_a_root_that_is_not_a_directory_is_ignored(self, root):
        assert resolve_within([str(root / "note.txt")], str(root / "note.txt")) is None


class TestKindAndExtension:
    def test_kind_file_refuses_a_directory(self, root):
        assert resolve_within([str(root)], str(root / "sub"), kind="file") is None

    def test_kind_dir_refuses_a_file(self, root):
        assert resolve_within([str(root)], str(root / "sub" / "a.png"), kind="dir") is None

    def test_kind_dir_accepts_a_directory(self, root):
        assert resolve_within([str(root)], str(root / "sub"), kind="dir") == \
            os.path.realpath(str(root / "sub"))

    def test_a_disallowed_extension_is_refused(self, root):
        assert resolve_within([str(root)], str(root / "note.txt"),
                              exts={".png"}) is None

    def test_an_allowed_extension_passes_case_insensitively(self, root):
        upper = root / "B.PNG"
        upper.write_bytes(b"x")
        assert resolve_within([str(root)], str(upper), exts={".png"}) == \
            os.path.realpath(str(upper))

    def test_a_missing_file_is_refused_even_inside_the_root(self, root):
        assert resolve_within([str(root)], str(root / "sub" / "gone.png"),
                              kind="file") is None


class TestMultipleRoots:
    def test_any_root_containing_the_path_admits_it(self, root, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        f = other / "b.png"
        f.write_bytes(b"x")
        assert resolve_within([str(root), str(other)], str(f)) == os.path.realpath(str(f))

    def test_a_path_in_none_of_the_roots_is_refused(self, root, tmp_path):
        other = tmp_path / "other"
        other.mkdir()
        stray = tmp_path / "stray.png"
        stray.write_bytes(b"x")
        assert resolve_within([str(root), str(other)], str(stray)) is None
