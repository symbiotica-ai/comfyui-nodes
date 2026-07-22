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
