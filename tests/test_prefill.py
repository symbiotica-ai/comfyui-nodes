# ABOUTME: Tests for spec-driven region prefill — one strip per order asset,
# ABOUTME: single-ref flip pairs, multi-ref cells, packed + centered layouts.
from pipeline.prefill import prefill_regions
from pipeline.texture_pack import PackSettings


def asset(name, refs, category="Decoration", canvas="128x128", prompt="p"):
    return {"assetName": name, "category": category, "canvas": canvas,
            "prompt": prompt, "refFiles": refs}


def test_single_ref_makes_flip_pair():
    res = prefill_regions([asset("Cart", ["Cart.png"])], 1024, 1024)
    (region,) = res["regions"]
    assert region["id"] == "region:spec:Cart"
    assert len(region["members"]) == 2
    assert region["members"][0]["spriteId"] == "Decoration/Cart/Cart.png"
    assert region["members"][1].get("flipX") is True
    assert region["taskRefs"] == {"paths": ["Decoration/Cart/Cart.png"], "mode": "meta"}
    assert region["assetType"] == "Decoration"
    assert region["desc"] == "p"


def test_multi_ref_one_cell_each_no_flip():
    res = prefill_regions([asset("Cake", ["Cake.png", "Cake_2.png", "Cake_3.png"])],
                          1024, 1024)
    (region,) = res["regions"]
    assert len(region["members"]) == 3
    assert all("flipX" not in m for m in region["members"])


def test_asset_without_refs_skipped():
    res = prefill_regions([asset("NoRefs", [])], 1024, 1024)
    assert res["regions"] == []


def test_chosen_paths_override_reffiles():
    res = prefill_regions([asset("Cart", ["Cart.png"])], 1024, 1024,
                          chosen={"Cart": ["Custom/Path/x.png", "Custom/Path/y.png"]})
    (region,) = res["regions"]
    assert [m["spriteId"] for m in region["members"]] == \
        ["Custom/Path/x.png", "Custom/Path/y.png"]


def test_unparsable_canvas_uses_fallback_cell():
    res = prefill_regions([asset("Cart", ["Cart.png"], canvas="-")], 1024, 1024)
    (region,) = res["regions"]
    # cell 256 → two cells + 16px pad = 528px wide on a 1024 sheet, scaled if needed
    assert 0 < region["w"] <= 1.0


def test_centered_layout_without_settings():
    res = prefill_regions([asset("A", ["A.png"]), asset("B", ["B.png"])], 1024, 1024)
    r0, r1 = res["regions"]
    assert r0["zIndex"] == 0 and r1["zIndex"] == 1
    assert r0["y"] < r1["y"]
    # strips horizontally centered
    mid0 = r0["x"] + r0["w"] / 2
    assert abs(mid0 - 0.5) < 0.01


def test_packed_layout_with_settings_and_overflow_stacks_below():
    settings = PackSettings(algorithm="shelf", preset=None, max_width=300,
                            max_height=140, distribute_by_folder=False)
    # Each strip: two 128-cells + pad = 272x128 → only one fits in 140 height.
    res = prefill_regions([asset("A", ["A.png"]), asset("B", ["B.png"])],
                          300, 140, settings=settings)
    assert res["overflow"] == ["B"] or res["overflow"] == ["A"]
    assert len(res["regions"]) == 2  # overflowed strip still becomes a region
    zs = [r["zIndex"] for r in sorted(res["regions"], key=lambda r: (r["y"], r["x"]))]
    assert zs == [0, 1]
