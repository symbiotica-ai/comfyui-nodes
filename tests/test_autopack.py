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


def test_autopack_scale_enlarges_cells(tmp_path):
    assets = [asset("A", refs=("a.png",))]
    root = _make_refs(tmp_path, assets)
    small = autopack_order(assets, root, sheet_w=1000, sheet_h=1000)
    big = autopack_order(assets, root, sheet_w=1000, sheet_h=1000, scale=2)
    sw = small[0]["regions"][0]["members"][0]["w"]
    bw = big[0]["regions"][0]["members"][0]["w"]
    assert bw > sw


def test_autopack_scale_gated_by_canvas(tmp_path):
    # scale_max_canvas=256: the 128 sprite scales x2, the 512 one is left native.
    assets = [asset("small", canvas="128x128"),
              asset("big", canvas="512x512")]
    root = _make_refs(tmp_path, assets)
    out = autopack_order(assets, root, sheet_w=4096, sheet_h=4096, scale=2,
                         scale_max_canvas=256)
    cells = {o["name"]: o["regions"][0]["cellPx"]["w"] for o in out}
    small = next(v for k, v in cells.items() if "128x128" in k)
    big = next(v for k, v in cells.items() if "512x512" in k)
    assert small == 256   # 128 * 2 — under the cutoff, scaled
    assert big == 512     # 512 > 256 cutoff — left native


def test_select_cells_reorder_and_drop():
    from pipeline.autopack import select_cells
    assert select_cells(["a", "b", "c"], [1, 3, 2]) == ["a", "c", "b"]  # reorder
    assert select_cells(["a", "b", "c"], [1, 3]) == ["a", "c"]          # drop b
    assert select_cells(["a", "b"], [2, 1, 3]) == ["b", "a"]            # oor skip
    assert select_cells(["a", "b", "c"], []) == []                      # keep none


def test_apply_overrides_multi():
    from pipeline.autopack import apply_overrides
    assets = [asset("A", refs=("a0", "a1", "a2")), asset("B"),
              asset("C", refs=("c0", "c1", "c2"))]
    out = apply_overrides(assets, {"hidden": ["B"],
                                   "cells": {"A": [1, 3], "C": [3, 1, 2]}})
    assert [a["assetName"] for a in out] == ["A", "C"]
    assert out[0]["refFiles"] == ["a0", "a2"]        # dropped the duplicate a1
    assert out[1]["refFiles"] == ["c2", "c0", "c1"]  # reordered, none dropped
    assert apply_overrides(assets, {}) == assets


def test_apply_removal_drops_named_asset():
    from pipeline.autopack import apply_removal
    assets = [asset("A"), asset("B"), asset("C")]
    assert [a["assetName"] for a in apply_removal(assets, "B")] == ["A", "C"]
    assert apply_removal(assets, "none") is assets
    assert apply_removal(assets, "") is assets


def _variant(name, refs, rotation, category="Decoration", canvas="256x256"):
    return {**asset(name, refs=refs, category=category, canvas=canvas),
            "rotation": rotation}


def test_autopack_split_variants_mirrors_rotation2(tmp_path):
    a = _variant("Stall", ("s0.png", "s1.png"), "2")
    root = _make_refs(tmp_path, [a])
    out = autopack_order([a], root, sheet_w=1024, sheet_h=1024,
                         combined_sheet=False, split_variants=True)
    assert [o["name"] for o in out] == ["order-stall-v1", "order-stall-v2"]
    for o in out:  # each variant sheet = ref + horizontal mirror
        ms = o["regions"][0]["members"]
        assert len(ms) == 2 and ms[1].get("flipX") is True


def test_autopack_split_skips_single_ref_no_duplicate(tmp_path):
    # A 1-ref variant asset has nothing to split — it must NOT get a redundant
    # variant sheet (was duplicating the combined sheet). combined keeps it once.
    single = _variant("Solo", ("s0.png",), "2")
    root = _make_refs(tmp_path, [single])
    with pytest.raises(ValueError):  # split-only: nothing to split
        autopack_order([single], root, sheet_w=1024, sheet_h=1024,
                       combined_sheet=False, split_variants=True)
    out = autopack_order([single], root, sheet_w=1024, sheet_h=1024,
                         combined_sheet=True, split_variants=True)
    assert len(out) == 1  # combined only, no duplicate variant sheet


def test_autopack_split_variants_rotation4_no_mirror(tmp_path):
    a = _variant("Sign", ("d0.png", "d1.png"), "4")
    root = _make_refs(tmp_path, [a])
    out = autopack_order([a], root, sheet_w=1024, sheet_h=1024,
                         combined_sheet=False, split_variants=True)
    assert len(out) == 2
    for o in out:
        assert len(o["regions"][0]["members"]) == 1  # no mirror for 4-way


def test_autopack_split_caps_at_three(tmp_path):
    a = _variant("Many", ("a.png", "b.png", "c.png", "d.png"), "2")
    root = _make_refs(tmp_path, [a])
    out = autopack_order([a], root, sheet_w=1024, sheet_h=1024,
                         combined_sheet=False, split_variants=True)
    assert [o["name"] for o in out] == ["order-many-v1", "order-many-v2",
                                        "order-many-v3"]


def test_autopack_split_skips_food_rotation_dash(tmp_path):
    food = _variant("Cake", ("c0.png", "c1.png", "c2.png"), "-",
                    category="Food - 3 stages", canvas="128x128")
    root = _make_refs(tmp_path, [food])
    with pytest.raises(ValueError):  # food is not a variant → nothing to split
        autopack_order([food], root, sheet_w=512, sheet_h=512,
                       combined_sheet=False, split_variants=True)


def test_autopack_combined_variant_paginated_by_ref(tmp_path):
    # Two 2-ref rotation-2 decorations, same canvas → the combined sheet splits
    # BY reference index: sheet v1 = each asset's ref1, v2 = each asset's ref2.
    a = _variant("GBQ", ("g0.png", "g1.png"), "2", canvas="512x512")
    b = _variant("WCT", ("w0.png", "w1.png"), "2", canvas="512x512")
    root = _make_refs(tmp_path, [a, b])
    out = autopack_order([a, b], root, sheet_w=1024, sheet_h=1024,
                         combined_sheet=True, split_variants=False)
    assert [o["name"] for o in out] == ["order-decoration-v1",
                                        "order-decoration-v2"]
    for o in out:  # 2 assets' k-th ref, each a rotation-2 mirror pair
        assert len(o["regions"]) == 2
        assert len(o["regions"][0]["members"]) == 2


def test_autopack_combined_food_stays_whole(tmp_path):
    # Food (rotation '-') keeps its stages together — NOT paginated by ref.
    f = _variant("Cake", ("c0.png", "c1.png", "c2.png"), "-",
                 category="Food - 3 stages", canvas="128x128")
    root = _make_refs(tmp_path, [f])
    out = autopack_order([f], root, sheet_w=512, sheet_h=512,
                         combined_sheet=True, split_variants=False)
    assert [o["name"] for o in out] == ["order-food-3-stages"]
    assert len(out[0]["regions"][0]["members"]) == 3  # all 3 stages one region


def test_autopack_combined_and_split_together(tmp_path):
    a = _variant("Stall", ("s0.png", "s1.png"), "2")
    root = _make_refs(tmp_path, [a])
    names = [o["name"] for o in autopack_order(
        [a], root, sheet_w=1024, sheet_h=1024,
        combined_sheet=True, split_variants=True)]
    assert "order-decoration-v1" in names and "order-decoration-v2" in names
    assert "order-stall-v1" in names and "order-stall-v2" in names


def test_autopack_distribute_by_folder_stacks_categories(tmp_path):
    # distribute_by_folder=True lays each category's strip on its own row —
    # accepted as a keyword and drives the pack without error.
    assets = [asset("f1", category="Food - 3 stages"),
              asset("f2", category="Food - 3 stages")]
    root = _make_refs(tmp_path, assets)
    out = autopack_order(assets, root, sheet_w=1000, sheet_h=1000,
                         distribute_by_folder=True, algorithm="shelf",
                         padding=0, border=0)
    assert len(out) == 1
    assert len(out[0]["regions"]) == 2
