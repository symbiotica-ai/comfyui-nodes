# ABOUTME: Tests for studio_library pure logic — confinement resolver, lister,
# ABOUTME: selection fingerprint. Real tmp trees; no ComfyUI import.
import os

import pytest

from pipeline.studio_library import MODEL_KINDS, resolve_studio_path
from pipeline.studio_library import resolve_selection, selection_fingerprint


def _touch(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture()
def vol(tmp_path):
    # A studio-assets Volume root with one provisioned studio.
    _touch(tmp_path / "studios" / "ggs" / "references" / "hero.png")
    (tmp_path / "studios" / "ggs" / "empty_dir").mkdir(parents=True)
    return tmp_path


def test_resolves_file_to_absolute(vol):
    got = resolve_studio_path(str(vol), "studios/ggs/references/hero.png")
    assert got == os.path.realpath(str(vol / "studios" / "ggs" / "references" / "hero.png"))


def test_resolves_folder_and_studio_root(vol):
    assert resolve_studio_path(str(vol), "studios/ggs/references") == \
        os.path.realpath(str(vol / "studios" / "ggs" / "references"))
    assert resolve_studio_path(str(vol), "studios/ggs") == \
        os.path.realpath(str(vol / "studios" / "ggs"))


def test_empty_selection_raises(vol):
    with pytest.raises(ValueError, match="no selection"):
        resolve_studio_path(str(vol), "")
    with pytest.raises(ValueError, match="no selection"):
        resolve_studio_path(str(vol), "   ")


def test_absolute_selection_raises(vol):
    with pytest.raises(ValueError, match="not a studio path"):
        resolve_studio_path(str(vol), "/etc/passwd")


def test_non_studios_prefix_raises(vol):
    with pytest.raises(ValueError, match="not a studio path"):
        resolve_studio_path(str(vol), "elsewhere/x.png")


def test_dotdot_escape_raises(vol):
    # Textual prefix passes; realpath collapses .. to outside the Volume root.
    _touch(vol.parent / "secret.png")
    with pytest.raises(ValueError, match="outside the studio library"):
        resolve_studio_path(str(vol), "studios/ggs/../../../secret.png")


def test_in_tree_symlink_escape_raises(vol):
    outside = vol.parent / "outside.png"
    _touch(outside)
    link = vol / "studios" / "ggs" / "link.png"
    os.symlink(outside, link)
    with pytest.raises(ValueError, match="outside the studio library"):
        resolve_studio_path(str(vol), "studios/ggs/link.png")


def test_invalid_slug_raises(vol):
    with pytest.raises(ValueError, match="not a studio path"):
        resolve_studio_path(str(vol), "studios/Bad_Slug/x.png")


def test_long_kebab_slug_resolves(vol):
    # Studio slug shape has NO length cap and NO underscores (unlike user-id).
    slug = "a" + "-b" * 40  # > 32 chars, valid kebab
    _touch(vol / "studios" / slug / "f.png")
    assert resolve_studio_path(str(vol), f"studios/{slug}/f.png") == \
        os.path.realpath(str(vol / "studios" / slug / "f.png"))


def test_missing_path_raises(vol):
    with pytest.raises(ValueError, match="not found"):
        resolve_studio_path(str(vol), "studios/ggs/nope.png")


def test_empty_or_relative_base_raises(vol):
    with pytest.raises(ValueError):
        resolve_studio_path("", "studios/ggs/references/hero.png")
    with pytest.raises(ValueError):
        resolve_studio_path("relative/dir", "studios/ggs/references/hero.png")


def test_model_kinds_is_the_eight_names():
    # Pinned literal (independent of the module constant) — guards cross-repo drift
    # from services/comfy-modal/canvas_entry.py:14-25.
    assert MODEL_KINDS == frozenset({
        "checkpoints", "loras", "vae", "controlnet",
        "upscale_models", "embeddings", "diffusion_models", "text_encoders",
    })


def test_resolve_selection_is_dir_flag(vol):
    assert resolve_selection(str(vol), "studios/ggs/references/hero.png")[1] is False
    assert resolve_selection(str(vol), "studios/ggs/references")[1] is True


def test_fingerprint_changes_on_file_mtime_and_size(vol):
    sel = "studios/ggs/references/hero.png"
    f = vol / "studios" / "ggs" / "references" / "hero.png"
    fp0 = selection_fingerprint(str(vol), sel)
    os.utime(f, (1_000_000, 1_000_000))
    fp_mtime = selection_fingerprint(str(vol), sel)
    assert fp_mtime != fp0
    f.write_bytes(b"much longer content")  # size change
    assert selection_fingerprint(str(vol), sel) != fp_mtime


def test_fingerprint_folder_tracks_direntry_set_not_content(vol):
    sel = "studios/ggs/references"
    fp0 = selection_fingerprint(str(vol), sel)
    # Adding a direntry changes the fingerprint...
    (vol / "studios" / "ggs" / "references" / "new.png").write_bytes(b"y")
    fp_added = selection_fingerprint(str(vol), sel)
    assert fp_added != fp0
    # ...but an in-place rewrite of a file UNDER the folder does NOT (documented).
    (vol / "studios" / "ggs" / "references" / "hero.png").write_bytes(b"zzzzzzzz")
    assert selection_fingerprint(str(vol), sel) == fp_added


def test_fingerprint_stable_and_unresolved(vol):
    sel = "studios/ggs/references/hero.png"
    assert selection_fingerprint(str(vol), sel) == selection_fingerprint(str(vol), sel)
    a = selection_fingerprint(str(vol), "studios/ggs/gone.png")
    b = selection_fingerprint(str(vol), "studios/ggs/also-gone.png")
    assert a != b  # the selection string is always hashed
    assert selection_fingerprint(str(vol), "studios/ggs/gone.png") == a  # stable


def test_none_selection_does_not_raise(vol):
    # A value wired from an upstream STRING socket can be None.
    assert isinstance(selection_fingerprint(str(vol), None), str)
    with pytest.raises(ValueError, match="no selection"):
        resolve_selection(str(vol), None)


def test_resolution_ignores_canvas_studio(vol, monkeypatch):
    # execute()/fingerprint delegate here and must NOT consult CANVAS_STUDIO.
    sel = "studios/ggs/references/hero.png"
    monkeypatch.setenv("CANVAS_STUDIO", "imperia")  # a different, nonexistent studio
    with_env = resolve_selection(str(vol), sel)
    fp_env = selection_fingerprint(str(vol), sel)
    monkeypatch.delenv("CANVAS_STUDIO", raising=False)
    assert resolve_selection(str(vol), sel) == with_env
    assert selection_fingerprint(str(vol), sel) == fp_env
