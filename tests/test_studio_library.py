# ABOUTME: Tests for studio_library pure logic — confinement resolver, lister,
# ABOUTME: selection fingerprint. Real tmp trees; no ComfyUI import.
import os

import pytest

from pipeline.studio_library import MODEL_KINDS, resolve_studio_path
from pipeline.studio_library import resolve_selection, selection_fingerprint
from pipeline.studio_library import list_studio_dir


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


def test_sibling_prefix_of_volume_root_escape_raises(vol):
    # A sibling directory whose name merely starts with the Volume root's name
    # (not a subdirectory of it). A `startswith(root)` check missing the
    # `+ os.sep` would wrongly treat this as inside the root.
    secret = vol.parent / (vol.name + "-evil") / "secret.txt"
    _touch(secret)
    link = vol / "studios" / "ggs" / "link.txt"
    os.symlink(secret, link)
    with pytest.raises(ValueError, match="outside"):
        resolve_studio_path(str(vol), "studios/ggs/link.txt")


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


@pytest.fixture()
def vol2(tmp_path):
    root = tmp_path
    for k in ("checkpoints", "loras", "references", "renders"):
        (root / "studios" / "ggs" / k).mkdir(parents=True)
    _touch(root / "studios" / "ggs" / "references" / "hero.png", b"1234")
    _touch(root / "studios" / "ggs" / "references" / ".hidden", b"x")
    (root / "studios" / "ggs" / "references" / "loras").mkdir()  # nested "loras" is legit
    _touch(root / "studios" / "ggs" / "brief.txt", b"hi")
    return root


def test_lists_dirs_first_and_hides_model_kinds_at_root(vol2):
    res = list_studio_dir(str(vol2), "ggs", "")
    assert "error" not in res
    assert res["rel"] == "studios/ggs"
    assert res["parent"] is None
    names = [e["name"] for e in res["entries"]]
    assert "checkpoints" not in names and "loras" not in names  # MODEL_KINDS hidden at root
    assert names == ["references", "renders", "brief.txt"]  # dirs first, case-insensitive
    ref = next(e for e in res["entries"] if e["name"] == "references")
    assert ref["type"] == "dir" and ref["rel"] == "studios/ggs/references"


def test_model_kinds_not_hidden_in_nested_dir(vol2):
    res = list_studio_dir(str(vol2), "ggs", "studios/ggs/references")
    names = [e["name"] for e in res["entries"]]
    assert "loras" in names  # a nested folder literally named "loras" is a real asset
    assert ".hidden" not in names  # dotfiles skipped
    hero = next(e for e in res["entries"] if e["name"] == "hero.png")
    assert hero["type"] == "file" and hero["size"] == 4
    assert res["parent"] == "studios/ggs"


def test_missing_studio_root_lists_empty_not_error(tmp_path):
    (tmp_path / "studios").mkdir()  # volume exists, studio not provisioned
    res = list_studio_dir(str(tmp_path), "brandnew", "")
    assert res == {"studio": "brandnew", "rel": "studios/brandnew", "parent": None, "entries": []}


def test_escaping_dir_returns_error_not_raise(vol2):
    assert "error" in list_studio_dir(str(vol2), "ggs", "studios/ggs/../imperia")
    assert "error" in list_studio_dir(str(vol2), "ggs", "studios/other/x")


def test_prefix_collision_sibling_not_inside(tmp_path):
    (tmp_path / "studios" / "ggs" / "a").mkdir(parents=True)
    (tmp_path / "studios" / "ggs-2" / "secret").mkdir(parents=True)
    assert "error" in list_studio_dir(str(tmp_path), "ggs", "studios/ggs-2")


def test_sibling_studio_prefix_listing_escape(tmp_path):
    # studios/ggs-private is a SIBLING of studios/ggs, not a child of it; a
    # symlink inside ggs pointing at it must not be listable through ggs. A
    # `startswith(studio_root)` check missing the `+ os.sep` would wrongly
    # treat "studios/ggs-private" as inside "studios/ggs" (string prefix).
    _touch(tmp_path / "studios" / "ggs-private" / "secret.txt")
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    os.symlink(tmp_path / "studios" / "ggs-private", tmp_path / "studios" / "ggs" / "peek")
    res = list_studio_dir(str(tmp_path), "ggs", "studios/ggs/peek")
    assert "error" in res


def test_file_as_dir_returns_error(vol2):
    assert "error" in list_studio_dir(str(vol2), "ggs", "studios/ggs/brief.txt")


def test_nul_byte_returns_error_not_raise(vol2):
    assert "error" in list_studio_dir(str(vol2), "ggs", "studios/ggs/a\x00b")


def test_invalid_studio_returns_error(vol2):
    assert "error" in list_studio_dir(str(vol2), "Bad_Studio", "")


def test_symlinked_dir_types_as_dir(vol2):
    target = vol2 / "studios" / "ggs" / "renders"
    link = vol2 / "studios" / "ggs" / "references" / "link_dir"
    os.symlink(target, link)
    res = list_studio_dir(str(vol2), "ggs", "studios/ggs/references")
    e = next(e for e in res["entries"] if e["name"] == "link_dir")
    assert e["type"] == "dir"  # matches execute()'s os.path.isdir


def test_round_trip_child_rel_lists(vol2):
    root = list_studio_dir(str(vol2), "ggs", "")
    first_dir = next(e for e in root["entries"] if e["type"] == "dir")
    child = list_studio_dir(str(vol2), "ggs", first_dir["rel"])
    assert "error" not in child and child["rel"] == first_dir["rel"]
