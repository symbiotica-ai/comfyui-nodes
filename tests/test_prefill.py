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


def test_packed_overflow_oversized_cell_stays_in_bounds():
    # Cell (256 fallback) taller than the 200px sheet: region must clamp to y=0,
    # never negative (normalized coords stay within 0-1).
    settings = PackSettings(algorithm="shelf", preset=None, max_width=200,
                            max_height=200, distribute_by_folder=False)
    res = prefill_regions([asset("Big", ["Big.png"], canvas="-")], 200, 200,
                          settings=settings)
    for region in res["regions"]:
        assert region["y"] >= 0
        for m in region["members"]:
            assert m["y"] >= 0


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


def test_packed_single_region_centered_both_axes():
    # A small strip on a big sheet: the packer drops it top-left; centering
    # must move it (and its member cells) to the middle of the sheet.
    settings = PackSettings(algorithm="shelf", preset=None, max_width=1000,
                            max_height=1000, distribute_by_folder=False)
    res = prefill_regions([asset("Cart", ["Cart.png"], canvas="128x128")],
                          1000, 1000, settings=settings)
    (region,) = res["regions"]
    assert abs(region["x"] + region["w"] / 2 - 0.5) < 0.01
    assert abs(region["y"] + region["h"] / 2 - 0.5) < 0.01
    # a member cell moved with its region (same row → same vertical center)
    m = region["members"][0]
    assert abs(m["y"] + m["h"] / 2 - 0.5) < 0.01


def test_packed_block_centered_symmetric():
    # Two strips: the block's bounding box is centered — left margin equals
    # right margin, top equals bottom.
    settings = PackSettings(algorithm="shelf", preset=None, max_width=1000,
                            max_height=1000, distribute_by_folder=False)
    res = prefill_regions([asset("A", ["A.png"]), asset("B", ["B.png"])],
                          1000, 1000, settings=settings)
    regs = res["regions"]
    min_x = min(r["x"] for r in regs)
    max_x = max(r["x"] + r["w"] for r in regs)
    min_y = min(r["y"] for r in regs)
    max_y = max(r["y"] + r["h"] for r in regs)
    assert abs(min_x - (1 - max_x)) < 0.01   # symmetric horizontally
    assert abs(min_y - (1 - max_y)) < 0.01   # symmetric vertically


def test_no_mirror_suppresses_flip():
    # A single-ref asset auto-flips (ref + mirror) unless noMirror is set —
    # the autopacker uses this for rotation=4 variants (a flip can't make 4).
    a = {"assetName": "X", "category": "Decoration", "canvas": "128x128",
         "prompt": "p", "refFiles": ["x.png"], "noMirror": True}
    (r,) = prefill_regions([a], 1024, 1024)["regions"]
    assert len(r["members"]) == 1
    assert "flipX" not in r["members"][0]


def test_scales_enlarge_cells():
    # Parity with the JS resolver's `scales`: a per-asset factor multiplies the
    # cell size (a big sheet so nothing overflows/fit-scales).
    s = PackSettings(algorithm="shelf", preset=None, max_width=2000,
                     max_height=2000, distribute_by_folder=False)
    base = prefill_regions([asset("Cart", ["Cart.png"], canvas="128x128")],
                           2000, 2000, settings=s)
    scaled = prefill_regions([asset("Cart", ["Cart.png"], canvas="128x128")],
                             2000, 2000, settings=s, scales={"Cart": 2})
    b = base["regions"][0]["members"][0]
    sc = scaled["regions"][0]["members"][0]
    assert abs(sc["w"] - 2 * b["w"]) < 1e-6
    assert abs(sc["h"] - 2 * b["h"]) < 1e-6
    assert scaled["regions"][0]["scale"] == 2
