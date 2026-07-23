# ABOUTME: Tests for files_read — selection JSON -> Order payload synthesis.
import json

import pytest
from PIL import Image

from pipeline.files_read import build_files_order


def _png(path, w=64, h=64):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (w, h), (255, 0, 0, 255)).save(path)


@pytest.fixture()
def refs(tmp_path):
    _png(tmp_path / "Stoves" / "stove_red.png", 128, 128)
    _png(tmp_path / "Stoves" / "stove_blue.png", 128, 128)
    _png(tmp_path / "Food" / "Cakes" / "cake_a.png", 256, 192)
    return tmp_path


def _sel(groups):
    return json.dumps({"groups": groups})


def test_builds_order_payload(refs):
    order = build_files_order(str(refs), _sel([
        {"name": "stoves", "category": "Decoration",
         "files": ["Stoves/stove_red.png", "Stoves/stove_blue.png"]},
    ]), name="clientpack")
    assert order["feature"] == "clientpack"
    assert order["refsRoot"] == str(refs)
    assert order["assetsRoot"] == ""
    a = order["assets"][0]
    assert a["assetName"] == "stoves"
    assert a["category"] == "Decoration"
    assert a["canvas"] == "128x128"
    assert a["rotation"] == "-"
    assert a["refFiles"] == ["Stoves/stove_red.png", "Stoves/stove_blue.png"]


def test_canvas_is_max_dims_across_files(refs):
    _png(refs / "Food" / "Cakes" / "cake_b.png", 192, 256)
    order = build_files_order(str(refs), _sel([
        {"name": "cakes", "category": "Food",
         "files": ["Food/Cakes/cake_a.png", "Food/Cakes/cake_b.png"]},
    ]))
    assert order["assets"][0]["canvas"] == "256x256"


def test_variants_flag_sets_rotation_2(refs):
    order = build_files_order(str(refs), _sel([
        {"name": "stoves", "category": "Deco", "variants": True,
         "files": ["Stoves/stove_red.png", "Stoves/stove_blue.png"]},
    ]))
    assert order["assets"][0]["rotation"] == "2"


def test_desc_becomes_prompt_and_default_name(refs):
    order = build_files_order(str(refs), _sel([
        {"name": "stoves", "category": "Deco", "desc": "a cozy stove",
         "files": ["Stoves/stove_red.png"]},
    ]))
    assert order["assets"][0]["prompt"] == "a cozy stove"
    assert order["feature"] == refs.name  # folder name fallback


def test_missing_files_dropped_empty_group_raises(refs):
    order = build_files_order(str(refs), _sel([
        {"name": "stoves", "category": "Deco",
         "files": ["Stoves/stove_red.png", "Stoves/nope.png"]},
    ]))
    assert order["assets"][0]["refFiles"] == ["Stoves/stove_red.png"]
    with pytest.raises(ValueError, match="ghosts"):
        build_files_order(str(refs), _sel([
            {"name": "ghosts", "category": "Deco", "files": ["gone.png"]},
        ]))


def test_no_groups_raises_actionable(refs):
    with pytest.raises(ValueError, match="files browser"):
        build_files_order(str(refs), "{}")


def test_selection_accepts_dict_and_bad_json_raises(refs):
    order = build_files_order(str(refs), {"groups": [
        {"name": "s", "category": "c", "files": ["Stoves/stove_red.png"]}]})
    assert order["assets"][0]["assetName"] == "s"
    with pytest.raises(ValueError, match="selection"):
        build_files_order(str(refs), "{not json")


def test_duplicate_group_names_deduped(refs):
    order = build_files_order(str(refs), _sel([
        {"name": "s", "category": "c", "files": ["Stoves/stove_red.png"]},
        {"name": "s", "category": "c", "files": ["Stoves/stove_blue.png"]},
    ]))
    names = [a["assetName"] for a in order["assets"]]
    assert names == ["s", "s-2"]


def test_resolve_ref_exact_rel_then_basename(tmp_path):
    import os

    from pipeline.compose import resolve_ref
    _png(tmp_path / "Stoves" / "a.png")
    _png(tmp_path / "flat.png")
    nested = resolve_ref(str(tmp_path), "Stoves/a.png")
    assert nested.endswith(os.path.join("Stoves", "a.png"))
    # Synthetic order path ("Category/Asset/file.png") does not exist as a
    # rel — falls back to the flat basename lookup (today's behavior).
    flat = resolve_ref(str(tmp_path), "Deco/Stove/flat.png")
    assert flat == os.path.join(str(tmp_path), "flat.png")


def test_draw_task_refs_draws_nested_refs(tmp_path):
    from pipeline.compose import build_prefill_sheet
    from pipeline.texture_pack import PackSettings
    _png(tmp_path / "Stoves" / "a.png", 64, 64)
    assets = [{"assetName": "s", "category": "c", "canvas": "64x64",
               "rotation": "-", "refFiles": ["Stoves/a.png"], "prompt": ""}]
    settings = PackSettings(algorithm="shelf", columns=1, background="",
                            max_width=256, max_height=256)
    sheet, regions, _ = build_prefill_sheet(assets, str(tmp_path), 256, 256,
                                            settings)
    assert sheet.getbbox() is not None  # the nested ref actually drew


def test_dedup_avoids_collision_with_explicit_suffix(refs):
    # ['s','s-2','s'] must NOT produce a duplicate 's-2' (prefill's by-name map
    # would drop one group's content). Bump past taken suffixes.
    order = build_files_order(str(refs), _sel([
        {"name": "s", "category": "c", "files": ["Stoves/stove_red.png"]},
        {"name": "s-2", "category": "c", "files": ["Stoves/stove_blue.png"]},
        {"name": "s", "category": "c", "files": ["Food/Cakes/cake_a.png"]},
    ]))
    names = [a["assetName"] for a in order["assets"]]
    assert names == ["s", "s-2", "s-3"]
    assert len(set(names)) == 3


def test_non_dict_selection_is_empty_not_crash(refs):
    for bad in ["[1]", "5", '"x"']:
        with pytest.raises(ValueError, match="files browser"):
            build_files_order(str(refs), bad)


def test_non_dict_group_entries_skipped(refs):
    order = build_files_order(str(refs), _sel([
        1, {"name": "s", "category": "c", "files": ["Stoves/stove_red.png"]}]))
    assert [a["assetName"] for a in order["assets"]] == ["s"]


def test_all_invalid_groups_raise(refs):
    with pytest.raises(ValueError, match="files browser"):
        build_files_order(str(refs), _sel([1, 2]))


def test_oversized_image_is_dropped_not_raised(refs, monkeypatch):
    # A decompression-bomb-sized image must be dropped like any unreadable
    # file, not crash the node with a raw DecompressionBombError.
    from PIL import Image
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 16)  # 128x128 trips 2x guard
    with pytest.raises(ValueError, match="no readable images"):
        build_files_order(str(refs), _sel([
            {"name": "s", "category": "c", "files": ["Stoves/stove_red.png"]}]))


def test_escaping_rel_is_dropped(tmp_path):
    _png(tmp_path / "refs" / "Stoves" / "a.png")
    _png(tmp_path / "secret.png")
    root = str(tmp_path / "refs")
    # An escaping rel resolves outside root -> treated as missing (dropped).
    with pytest.raises(ValueError, match="no readable images"):
        build_files_order(root, _sel([
            {"name": "x", "category": "x", "files": ["../secret.png"]}]))
    order = build_files_order(root, _sel([
        {"name": "x", "category": "x", "files": ["Stoves/a.png"]}]))
    assert order["assets"][0]["refFiles"] == ["Stoves/a.png"]
