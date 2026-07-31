# ABOUTME: Tests the refs-folder loader — a bound absolute directory becomes an
# ABOUTME: ordered list of image paths, headless, with no browser selection.
import os

import pytest

from PIL import Image

from pipeline.refs_dir import (
    list_reference_images,
    open_reference_images,
    refs_fingerprint,
)


@pytest.fixture
def refs(tmp_path):
    d = tmp_path / "refs"
    d.mkdir()
    for name in ("b.png", "a.png", "c.png"):
        (d / name).write_bytes(b"x")
    return d


@pytest.fixture
def real_refs(tmp_path):
    """Three decodable PNGs — list_reference_images only reads names, but
    open_reference_images has to get real pixels back."""
    d = tmp_path / "real"
    d.mkdir()
    for i, name in enumerate(("a.png", "b.png", "c.png")):
        Image.new("RGB", (4 + i, 4), (i, 0, 0)).save(d / name)
    return d


class TestListing:
    def test_images_come_back_in_filename_order(self, refs):
        got = list_reference_images(str(refs))
        assert [p.rsplit("/", 1)[-1] for p in got] == ["a.png", "b.png", "c.png"]


class TestOpening:
    def test_images_open_in_the_listed_order(self, real_refs):
        got = open_reference_images(str(real_refs))
        assert [os.path.basename(p) for p, _ in got] == ["a.png", "b.png",
                                                         "c.png"]
        assert [im.size for _, im in got] == [(4, 4), (5, 4), (6, 4)]

    def test_an_undecodable_file_is_dropped_not_fatal(self, real_refs):
        (real_refs / "b-broken.png").write_bytes(b"not a png")
        got = open_reference_images(str(real_refs))
        assert [os.path.basename(p) for p, _ in got] == ["a.png", "b.png",
                                                         "c.png"]

    def test_a_folder_of_only_undecodable_files_raises(self, refs):
        # The `refs` fixture writes b"x" under .png names — named like images,
        # decodable as none.
        with pytest.raises(ValueError, match="none of the 3 image files"):
            open_reference_images(str(refs))

    def test_max_count_applies_to_readable_images(self, real_refs):
        # The cap is what the caller GETS, so a dropped file must not eat a
        # slot: 'a-broken' sorts first and still leaves two real images.
        (real_refs / "a-broken.png").write_bytes(b"not a png")
        got = open_reference_images(str(real_refs), max_count=2)
        assert [os.path.basename(p) for p, _ in got] == ["a.png", "b.png"]


class TestFingerprint:
    def test_an_unchanged_folder_keeps_its_fingerprint(self, real_refs):
        assert refs_fingerprint(str(real_refs), 0) == \
            refs_fingerprint(str(real_refs), 0)

    def test_adding_a_file_changes_the_fingerprint(self, real_refs):
        before = refs_fingerprint(str(real_refs), 0)
        Image.new("RGB", (4, 4)).save(real_refs / "d.png")
        assert refs_fingerprint(str(real_refs), 0) != before

    def test_rewriting_a_file_changes_the_fingerprint(self, real_refs):
        before = refs_fingerprint(str(real_refs), 0)
        Image.new("RGB", (40, 40), (9, 9, 9)).save(real_refs / "a.png")
        assert refs_fingerprint(str(real_refs), 0) != before

    def test_the_cap_is_part_of_the_fingerprint(self, real_refs):
        assert refs_fingerprint(str(real_refs), 2) != \
            refs_fingerprint(str(real_refs), 0)

    def test_a_missing_folder_fingerprints_instead_of_raising(self, tmp_path):
        # Comfy calls this during validation, before execute. Raising here would
        # surface as a graph-wide failure with no node to blame.
        assert isinstance(refs_fingerprint(str(tmp_path / "gone"), 0), str)


class TestWhatCounts:
    def test_a_folder_named_like_an_image_is_not_one(self, refs):
        (refs / "sprites.png").mkdir()
        got = list_reference_images(str(refs))
        assert [p.rsplit("/", 1)[-1] for p in got] == ["a.png", "b.png", "c.png"]

    def test_hidden_files_are_skipped(self, refs):
        (refs / ".DS_Store.png").write_bytes(b"x")
        assert len(list_reference_images(str(refs))) == 3

    def test_nested_images_are_not_reached(self, refs):
        sub = refs / "deeper"
        sub.mkdir()
        (sub / "z.png").write_bytes(b"x")
        assert len(list_reference_images(str(refs))) == 3

    def test_extension_matching_ignores_case(self, tmp_path):
        d = tmp_path / "caps"
        d.mkdir()
        (d / "shot.PNG").write_bytes(b"x")
        assert len(list_reference_images(str(d))) == 1


class TestMaxCount:
    def test_max_count_keeps_the_first_n_in_order(self, refs):
        got = list_reference_images(str(refs), max_count=2)
        assert [p.rsplit("/", 1)[-1] for p in got] == ["a.png", "b.png"]

    def test_zero_means_no_limit(self, refs):
        assert len(list_reference_images(str(refs), max_count=0)) == 3

    def test_a_limit_above_the_count_is_not_an_error(self, refs):
        assert len(list_reference_images(str(refs), max_count=99)) == 3


class TestRefusals:
    def test_a_missing_folder_raises_naming_it(self, tmp_path):
        gone = tmp_path / "not-there"
        with pytest.raises(ValueError, match="not-there"):
            list_reference_images(str(gone))

    def test_a_relative_path_is_refused_even_when_it_resolves(self, refs,
                                                              monkeypatch):
        # 'refs' exists under the CWD here, so isdir() would say yes. The
        # contract is an ABSOLUTE path: accepting a relative one silently binds
        # the graph to wherever the ComfyUI process happens to have started.
        monkeypatch.chdir(refs.parent)
        with pytest.raises(ValueError, match="absolute"):
            list_reference_images("refs")

    def test_an_empty_path_is_refused(self):
        # "" would resolve to the process CWD, which is never a refs folder.
        with pytest.raises(ValueError, match="absolute"):
            list_reference_images("")

    def test_a_folder_holding_no_image_raises(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        (d / "notes.txt").write_bytes(b"x")
        with pytest.raises(ValueError, match="no images"):
            list_reference_images(str(d))
