# ABOUTME: Tests the refs-folder loader — a bound absolute directory becomes an
# ABOUTME: ordered list of image paths, headless, with no browser selection.
import errno
import os
import random

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

    def test_a_truncated_image_is_dropped(self, real_refs):
        # An intact PNG header over a cut-short body: Image.open succeeds and
        # reports a size, and only the decode fails. A check that stopped at
        # open() would pass this file on to blow up in whichever node first
        # touched its pixels. The image has to be big enough that half of it is
        # still past the header — half of a 4x4 PNG lands inside IHDR, which
        # fails at open() and proves nothing.
        rnd = random.Random(20260731)
        big = Image.new("RGB", (256, 256))
        big.putdata([(rnd.randrange(256), rnd.randrange(256),
                      rnd.randrange(256)) for _ in range(256 * 256)])
        big.save(real_refs / "b-cut.png")
        raw = (real_refs / "b-cut.png").read_bytes()
        (real_refs / "b-cut.png").write_bytes(raw[:len(raw) // 2])
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


def _open_fd_count():
    for d in ("/dev/fd", "/proc/self/fd"):
        if os.path.isdir(d):
            return len(os.listdir(d))
    return None


class TestHandles:
    def test_loading_a_folder_holds_no_file_open(self, tmp_path):
        """GIF is the one format in IMG_EXTS whose decoder keeps its handle for
        frame seeking, so a folder of them costs one descriptor per image. Once
        the process runs out, Image.open fails with an OSError that reads
        exactly like a corrupt file — the folder comes back silently short.

        Counting descriptors rather than inspecting the image: load() sets
        im.fp to None while the live handle survives on im._fp, so an attribute
        check reports success on the very case this guards."""
        d = tmp_path / "gifs"
        d.mkdir()
        for i in range(20):
            Image.new("P", (4, 4)).save(d / f"g{i:02d}.gif")
        base = _open_fd_count()
        if base is None:
            pytest.skip("no fd directory to count on this platform")
        opened = open_reference_images(str(d))
        held = _open_fd_count() - base
        assert len(opened) == 20
        assert held == 0, f"{held} descriptors still open after loading"


    def test_running_out_of_descriptors_is_not_read_as_corruption(
            self, real_refs, monkeypatch):
        """The dangerous shape: an exhausted process fails on EVERY remaining
        open, so counting it as a corrupt file would drop the rest of the
        folder and report the short list as the folder's contents. It has to
        surface, not degrade."""
        def out_of_fds(*a, **kw):
            raise OSError(errno.EMFILE, "Too many open files")
        monkeypatch.setattr(Image, "open", out_of_fds)
        with pytest.raises(OSError) as exc:
            open_reference_images(str(real_refs))
        assert exc.value.errno == errno.EMFILE


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

    def test_an_edit_that_keeps_the_byte_count_changes_the_fingerprint(
            self, real_refs):
        # Size and mtime cover for each other in every other test here, so
        # either could be dropped unnoticed. Re-saving art at the same
        # dimensions routinely lands on the same byte count, and then mtime is
        # the only thing that moved.
        before = refs_fingerprint(str(real_refs), 0)
        p = real_refs / "a.png"
        raw = p.read_bytes()
        p.write_bytes(b"\x00" * len(raw))
        os.utime(p, ns=(1_000_000_000, 1_000_000_000))
        assert p.stat().st_size == len(raw)
        assert refs_fingerprint(str(real_refs), 0) != before

    def test_a_resized_file_changes_the_fingerprint_on_its_own(self,
                                                               real_refs):
        # The mirror of the test above: hold mtime still so only st_size can
        # move. Without both, either field could be dropped and the other would
        # cover for it in every test here.
        p = real_refs / "a.png"
        stamp = p.stat().st_mtime_ns
        before = refs_fingerprint(str(real_refs), 0)
        p.write_bytes(p.read_bytes() + b"trailing")
        os.utime(p, ns=(stamp, stamp))
        assert p.stat().st_mtime_ns == stamp
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

    def test_ordering_ignores_case_rather_than_sorting_capitals_first(self,
                                                                      tmp_path):
        # Known-good order read the way a person reads the folder. A plain
        # byte-order sort would put every capital ahead of every lowercase
        # letter and give Boss, Zone, arrow, hero instead.
        d = tmp_path / "mixed"
        d.mkdir()
        for name in ("hero.png", "Boss.png", "arrow.png", "Zone.png"):
            (d / name).write_bytes(b"x")
        got = [os.path.basename(p) for p in list_reference_images(str(d))]
        assert got == ["arrow.png", "Boss.png", "hero.png", "Zone.png"]

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
