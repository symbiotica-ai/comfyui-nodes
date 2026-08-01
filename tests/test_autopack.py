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


def test_autopack_sheets_carry_their_category(tmp_path):
    # Every sheet names the asset type it holds — index-aligned with the sheets
    # and their names, so downstream can file/label by category.
    assets = [asset("Booth"), asset("Cake", refs=("s1.png", "s2.png"),
                                    category="Food - 3 stages")]
    root = _make_refs(tmp_path, assets)
    out = autopack_order(assets, root, sheet_w=256, sheet_h=256,
                         base_name="mini-2")
    assert [o["category"] for o in out] == ["Decoration", "Food - 3 stages"]


def test_autopack_paginated_sheets_repeat_the_category(tmp_path):
    assets = [asset(f"d{i}") for i in range(5)]
    root = _make_refs(tmp_path, assets)
    out = autopack_order(assets, root, sheet_w=256, sheet_h=256,
                         columns=1, max_rows=3, base_name="ev")
    assert [o["category"] for o in out] == ["Decoration", "Decoration"]


def test_autopack_split_variant_sheets_carry_the_category(tmp_path):
    a = _variant("Stall", ("s0.png", "s1.png"), "2")
    root = _make_refs(tmp_path, [a])
    out = autopack_order([a], root, sheet_w=1024, sheet_h=1024,
                         combined_sheet=False, split_variants=True)
    assert [o["category"] for o in out] == ["Decoration", "Decoration"]


def test_autopack_scale_enlarges_cells(tmp_path):
    assets = [asset("A", refs=("a.png",))]  # default canvas 128x128
    root = _make_refs(tmp_path, assets)
    small = autopack_order(assets, root, sheet_w=1000, sheet_h=1000)
    big = autopack_order(assets, root, sheet_w=1000, sheet_h=1000,
                         scale_target=256, scale_max=4.0)  # 128 -> x2
    sw = small[0]["regions"][0]["members"][0]["w"]
    bw = big[0]["regions"][0]["members"][0]["w"]
    assert bw > sw


def test_autopack_scale_target_per_size(tmp_path):
    # target 512 + cap 3x: 128 -> x3 (capped, 384px), 256 -> x2 (512),
    # 512 -> x1 (native). Small sprites scale more; the cap bounds the zoom.
    assets = [asset("food", canvas="128x128"),
              asset("deco", canvas="256x256"),
              asset("big", canvas="512x512")]
    root = _make_refs(tmp_path, assets)
    out = autopack_order(assets, root, sheet_w=4096, sheet_h=4096,
                         scale_target=512, scale_max=3.0)
    cells = {o["name"]: o["regions"][0]["cellPx"]["w"] for o in out}
    assert next(v for k, v in cells.items() if "128x128" in k) == 384  # 128*3 cap
    assert next(v for k, v in cells.items() if "256x256" in k) == 512  # 256*2
    assert next(v for k, v in cells.items() if "512x512" in k) == 512  # native


def test_autopack_scale_target_off_is_native(tmp_path):
    assets = [asset("a", canvas="128x128")]
    root = _make_refs(tmp_path, assets)
    out = autopack_order(assets, root, sheet_w=4096, sheet_h=4096,
                         scale_target=0, scale_max=3.0)
    assert out[0]["regions"][0]["cellPx"]["w"] == 128  # unscaled


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


def test_autopack_split_includes_single_ref_variant(tmp_path):
    # A 1-ref variant now gets its own split sheet (ref + flip) — the per-item
    # deliverable — separate from the combined sheet that groups it.
    single = _variant("Solo", ("s0.png",), "2")
    root = _make_refs(tmp_path, [single])
    out = autopack_order([single], root, sheet_w=1024, sheet_h=1024,
                         combined_sheet=False, split_variants=True)
    assert [o["name"] for o in out] == ["order-solo-v1"]
    ms = out[0]["regions"][0]["members"]
    assert len(ms) == 2 and ms[1].get("flipX") is True   # ref + horizontal flip


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


def test_autopack_max_refs_caps_variant_sheets(tmp_path):
    # A hard cap keeps only the first N refs per asset, in order — a 3-ref
    # variant with max_refs=2 splits into exactly 2 sheets (v1, v2).
    a = _variant("Many", ("a.png", "b.png", "c.png"), "2")
    root = _make_refs(tmp_path, [a])
    out = autopack_order([a], root, sheet_w=1024, sheet_h=1024,
                         combined_sheet=False, split_variants=True, max_refs=2)
    assert [o["name"] for o in out] == ["order-many-v1", "order-many-v2"]


def test_autopack_fit_width_fills_sheet(tmp_path):
    # fit_width auto-scales the packed block to fill the sheet width (5px pad),
    # so a small asset ends up far larger than at native scale.
    a = asset("Tiny", refs=("t.png",), category="Decoration", canvas="128x128")
    root = _make_refs(tmp_path, [a])
    native = autopack_order([a], root, sheet_w=1024, sheet_h=1024)
    fit = autopack_order([a], root, sheet_w=1024, sheet_h=1024, fit_width=True)
    regions = fit[0]["regions"]
    span = (max(r["x"] + r["w"] for r in regions)
            - min(r["x"] for r in regions))
    assert span == pytest.approx((1024 - 10) / 1024, abs=0.02)  # width filled
    assert (max(r["w"] for r in regions)
            > max(r["w"] for r in native[0]["regions"]))         # scaled up


def test_autopack_max_refs_truncates_food_region(tmp_path):
    # Food keeps stages together in one region; max_refs=2 drops the 3rd stage
    # so the recipe region carries only the first two cells.
    food = _variant("Cake", ("c0.png", "c1.png", "c2.png"), "-",
                    category="Food - 3 stages", canvas="128x128")
    root = _make_refs(tmp_path, [food])
    full = autopack_order([food], root, sheet_w=512, sheet_h=512)
    capped = autopack_order([food], root, sheet_w=512, sheet_h=512, max_refs=2)
    assert len(full[0]["regions"][0]["members"]) == 3
    assert len(capped[0]["regions"][0]["members"]) == 2


def test_autopack_split_skips_food_rotation_dash(tmp_path):
    food = _variant("Cake", ("c0.png", "c1.png", "c2.png"), "-",
                    category="Food - 3 stages", canvas="128x128")
    root = _make_refs(tmp_path, [food])
    with pytest.raises(ValueError):  # food is not a variant → nothing to split
        autopack_order([food], root, sheet_w=512, sheet_h=512,
                       combined_sheet=False, split_variants=True)


def test_empty_split_only_on_stages_blames_combined_sheet(tmp_path):
    # The real report: combined_sheet off + split on, category = food. Neither
    # emitter can produce a sheet, and the message has to name the switch.
    food = _variant("Cake", ("c0.png",), "-", category="Food - 3 stages")
    root = _make_refs(tmp_path, [food])
    with pytest.raises(ValueError, match="turn combined_sheet on") as e:
        autopack_order([food], root, sheet_w=512, sheet_h=512,
                       category="Food - 3 stages", combined_sheet=False,
                       split_variants=True)
    assert "rotation 2/4" in str(e.value)


def test_empty_both_emitters_off_says_so(tmp_path):
    a = asset("Booth")
    root = _make_refs(tmp_path, [a])
    with pytest.raises(ValueError,
                       match="both combined_sheet and split_variants are off"):
        autopack_order([a], root, sheet_w=512, sheet_h=512,
                       combined_sheet=False, split_variants=False)


def test_empty_wrong_category_lists_the_types_present(tmp_path):
    a = asset("Booth")
    root = _make_refs(tmp_path, [a])
    with pytest.raises(ValueError, match="only references: Decoration"):
        autopack_order([a], root, sheet_w=512, sheet_h=512,
                       category="Food - 3 stages")


def test_empty_without_refs_says_no_reference_image(tmp_path):
    with pytest.raises(ValueError, match="no asset in the order has a "
                                         "reference image"):
        autopack_order([asset("norefs", refs=())], str(tmp_path),
                       sheet_w=256, sheet_h=256)


def test_autopack_combined_variant_keeps_asset_refs_together(tmp_path):
    # Two 2-ref rotation-2 decorations, same canvas → the combined sheet keeps
    # each asset's refs together (no per-ref v1/v2 split). At max_rows=4 all four
    # mirror-pair units land on ONE sheet, in asset order.
    a = _variant("GBQ", ("g0.png", "g1.png"), "2", canvas="512x512")
    b = _variant("WCT", ("w0.png", "w1.png"), "2", canvas="512x512")
    root = _make_refs(tmp_path, [a, b])
    out = autopack_order([a, b], root, sheet_w=1024, sheet_h=1024,
                         columns=1, max_rows=4,
                         combined_sheet=True, split_variants=False)
    assert [o["name"] for o in out] == ["order-decoration"]
    regs = out[0]["regions"]
    assert [r["name"] for r in regs] == ["GBQ", "GBQ", "WCT", "WCT"]
    assert all(len(r["members"]) == 2 for r in regs)   # each a mirror pair


def test_autopack_combined_variant_paginates_by_max_rows(tmp_path):
    # max_rows now controls pagination: 2 assets x 2 refs at max_rows=2 → two
    # sheets, each keeping one asset's two refs together.
    a = _variant("GBQ", ("g0.png", "g1.png"), "2", canvas="512x512")
    b = _variant("WCT", ("w0.png", "w1.png"), "2", canvas="512x512")
    root = _make_refs(tmp_path, [a, b])
    out = autopack_order([a, b], root, sheet_w=1024, sheet_h=1024,
                         columns=1, max_rows=2,
                         combined_sheet=True, split_variants=False)
    assert [o["name"] for o in out] == ["order-decoration-1",
                                        "order-decoration-2"]
    assert [r["name"] for r in out[0]["regions"]] == ["GBQ", "GBQ"]
    assert [r["name"] for r in out[1]["regions"]] == ["WCT", "WCT"]


def test_autopack_combined_mixed_group_keeps_pair(tmp_path):
    # A rotation-BLANK single-ref decoration sharing a (category, canvas) group
    # with a rotation-2 asset must KEEP its in-game mirror pair on the variant
    # sheets — only true multi-direction variants (rotation >= 3) suppress it.
    variant = _variant("Stall", ("s0.png", "s1.png"), "2")
    plain = _variant("Lamp", ("l0.png",), "")     # blank rotation, 1 ref
    four = _variant("Sign", ("d0.png", "d1.png"), "4")
    root = _make_refs(tmp_path, [variant, plain, four])
    out = autopack_order([variant, plain, four], root,
                         sheet_w=2048, sheet_h=2048, columns=1, max_rows=8,
                         combined_sheet=True, split_variants=False)
    assert [o["name"] for o in out] == ["order-decoration"]  # all units, 1 sheet
    by_name = {}
    for r in out[0]["regions"]:
        by_name.setdefault(r["name"], []).append(r["members"])
    assert len(by_name["Lamp"][0]) == 2                      # pair kept
    assert by_name["Lamp"][0][1].get("flipX") is True
    assert all(len(m) == 2 for m in by_name["Stall"])        # rotation-2 mirrors
    assert all(len(m) == 1 for m in by_name["Sign"])         # rotation-4: no mirror


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
        [a], root, sheet_w=1024, sheet_h=1024, columns=1, max_rows=4,
        combined_sheet=True, split_variants=True)]
    assert "order-decoration" in names               # both refs, one sheet
    assert "order-stall-v1" in names and "order-stall-v2" in names
    assert len(names) == 3


def test_autopack_mini2_combined_refs_together_split_singles(tmp_path):
    # Real Mini 2 shape: one 256 decoration with 2 refs + two 512 decorations
    # with 1 ref each, all rotation 2.
    #   combined  -> the 256's two refs TOGETHER on one sheet (not split per
    #                ref), and the two 512s together on one sheet.
    #   split     -> one ref+flip sheet per ref of EVERY variant asset, the
    #                single-ref 512s included.
    bc = _variant("Black Cat", ("bc0.png", "bc1.png"), "2", canvas="256x256")
    bone = _variant("Bone Rose", ("bo0.png",), "2", canvas="512x512")
    mad = _variant("Mad Baker", ("md0.png",), "2", canvas="512x512")
    root = _make_refs(tmp_path, [bc, bone, mad])
    out = autopack_order([bc, bone, mad], root, sheet_w=1328, sheet_h=1328,
                         columns=1, max_rows=4, category="Decoration",
                         combined_sheet=True, split_variants=True)
    names = [o["name"] for o in out]
    assert len(out) == 6
    # combined: canvas is in the name because Decoration spans 256 and 512
    assert "order-decoration-256x256" in names
    assert "order-decoration-512x512" in names
    # split: every variant ref its own ref+flip sheet, single-ref included
    assert "order-black-cat-v1" in names and "order-black-cat-v2" in names
    assert "order-bone-rose-v1" in names
    assert "order-mad-baker-v1" in names
    c256 = next(o for o in out if o["name"] == "order-decoration-256x256")
    assert len(c256["regions"]) == 2                    # both refs, together
    assert all(len(r["members"]) == 2 for r in c256["regions"])  # each a pair
    c512 = next(o for o in out if o["name"] == "order-decoration-512x512")
    assert {r["name"] for r in c512["regions"]} == {"Bone Rose", "Mad Baker"}


def test_autopack_padding_spaces_mirror_cells(tmp_path):
    # padding puts a gap between an asset and its mirror cell (was hardcoded 0).
    a = _variant("Stall", ("s0.png",), "2", canvas="128x128")  # 1 ref → pair
    root = _make_refs(tmp_path, [a])
    out = autopack_order([a], root, sheet_w=1000, sheet_h=1000,
                         combined_sheet=True, split_variants=False, padding=40)
    ms = out[0]["regions"][0]["members"]
    assert len(ms) == 2
    gap_px = (ms[1]["x"] - (ms[0]["x"] + ms[0]["w"])) * 1000
    assert round(gap_px) == 40


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
