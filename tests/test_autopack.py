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
