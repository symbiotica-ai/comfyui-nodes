# ABOUTME: Tests for order auto-packing — grouping by (category, canvas),
# ABOUTME: pagination into columns x max_rows chunks, sheet naming, rendering.
from pipeline.autopack import plan_sheets, sheet_name


def asset(name, refs=("a.png",), category="Decoration", canvas="128x128",
          prompt="p"):
    return {"assetName": name, "category": category, "canvas": canvas,
            "prompt": prompt, "refFiles": list(refs)}


def test_groups_by_category_and_canvas():
    assets = [
        asset("d1"), asset("d2", canvas="512x512"),
        asset("f1", category="Food - 3 stages"),
    ]
    chunks = plan_sheets(assets, columns=1, max_rows=4)
    keys = [(c["category"], c["canvas"]) for c in chunks]
    assert keys == [("Decoration", "128x128"), ("Decoration", "512x512"),
                    ("Food - 3 stages", "128x128")]


def test_paginates_at_columns_times_max_rows():
    assets = [asset(f"d{i}") for i in range(10)]
    chunks = plan_sheets(assets, columns=2, max_rows=3)  # 6 per sheet
    assert [len(c["assets"]) for c in chunks] == [6, 4]
    assert [(c["index"], c["total"]) for c in chunks] == [(1, 2), (2, 2)]
    # spec order preserved across the chunk boundary
    assert chunks[0]["assets"][0]["assetName"] == "d0"
    assert chunks[1]["assets"][0]["assetName"] == "d6"


def test_category_filter_and_no_refs_skipped():
    assets = [asset("d1"), asset("skip", refs=()),
              asset("f1", category="Food - 3 stages")]
    chunks = plan_sheets(assets, columns=1, max_rows=4,
                         category="Food - 3 stages")
    assert len(chunks) == 1
    assert [a["assetName"] for a in chunks[0]["assets"]] == ["f1"]


def test_sheet_name_variants():
    single = {"category": "Food - 3 stages", "canvas": "128x128",
              "index": 1, "total": 1}
    assert sheet_name("mini-2", single, multi_canvas=False) \
        == "mini-2-food-3-stages"
    paged = dict(single, index=2, total=3)
    assert sheet_name("mini-2", paged, multi_canvas=False) \
        == "mini-2-food-3-stages-2"
    sized = {"category": "Decoration", "canvas": "512x512",
             "index": 1, "total": 1}
    assert sheet_name("mini-2", sized, multi_canvas=True) \
        == "mini-2-decoration-512x512"


import pytest
from PIL import Image

from pipeline.autopack import autopack_order


def _make_refs(tmp_path, assets):
    for a in assets:
        d = tmp_path / a["category"] / a["assetName"]
        d.mkdir(parents=True, exist_ok=True)
        for f in a["refFiles"]:
            Image.new("RGBA", (32, 32), (200, 60, 60, 255)).save(d / f)
    return str(tmp_path)


def test_autopack_renders_aligned_sheets_and_prompts(tmp_path):
    assets = [
        asset("Booth", prompt="a booth"),
        asset("Cake", refs=("s1.png", "s2.png", "s3.png"),
              category="Food - 3 stages", prompt="Prep) x\nReady) y"),
    ]
    root = _make_refs(tmp_path, assets)
    out = autopack_order(assets, root, sheet_w=256, sheet_h=256,
                         base_name="mini-2")
    assert [o["name"] for o in out] == ["mini-2-decoration",
                                       "mini-2-food-3-stages"]
    assert all(o["image"].size == (256, 256) for o in out)
    # prompts belong to the SAME chunk as the image (aligned by construction)
    assert "a booth" in out[0]["prompts"]
    assert "Prep) x" in out[1]["prompts"]
    assert "a booth" not in out[1]["prompts"]


def test_autopack_paginates_and_numbers_names(tmp_path):
    assets = [asset(f"d{i}") for i in range(5)]
    root = _make_refs(tmp_path, assets)
    out = autopack_order(assets, root, sheet_w=256, sheet_h=256,
                         columns=1, max_rows=3, base_name="ev")
    assert [o["name"] for o in out] == ["ev-decoration-1", "ev-decoration-2"]
    assert len(out[0]["regions"]) == 3
    assert len(out[1]["regions"]) == 2


def test_autopack_multi_canvas_names_carry_size(tmp_path):
    assets = [asset("small"), asset("big", canvas="512x512")]
    root = _make_refs(tmp_path, assets)
    out = autopack_order(assets, root, sheet_w=256, sheet_h=256,
                         base_name="ev")
    assert sorted(o["name"] for o in out) \
        == ["ev-decoration-128x128", "ev-decoration-512x512"]


def test_autopack_empty_raises_actionable(tmp_path):
    with pytest.raises(ValueError, match="no assets"):
        autopack_order([asset("norefs", refs=())], str(tmp_path),
                       sheet_w=256, sheet_h=256, category="Food - 3 stages")
