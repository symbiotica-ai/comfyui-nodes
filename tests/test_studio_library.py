# ABOUTME: Tests for studio_library pure logic — confinement resolver, lister,
# ABOUTME: selection fingerprint. Real tmp trees; no ComfyUI import.
import os

import pytest

from pipeline.studio_library import MODEL_KINDS, resolve_studio_path


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
