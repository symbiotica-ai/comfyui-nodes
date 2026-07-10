# ABOUTME: Tests for sheet compositing — catalog grid build, prefill ref draw,
# ABOUTME: and PNG+sidecar saving with slugged names.
import json
import os

import pytest
from PIL import Image

from pipeline.compose import (
    build_catalog_sheet,
    build_prefill_sheet,
    category_candidates,
    save_sheet,
    scan_images,
)
from pipeline.texture_pack import PackSettings


def make_png(path, size=(128, 128), color=(255, 0, 0)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", size, color).save(path)


@pytest.fixture
def catalog(tmp_path):
    root = tmp_path / "assets"
    make_png(str(root / "Decoration" / "Old Cart" / "cart.png"), (128, 128))
    make_png(str(root / "Decorations" / "Bench" / "bench.png"), (64, 64))
    make_png(str(root / "Food" / "Pie" / "pie.png"), (128, 128))
    make_png(str(root / ".hidden" / "x.png"))
    return str(root)


def test_scan_images_recursive_sorted_no_dotdirs(catalog):
    rels = scan_images(catalog)
    assert rels == ["Decoration/Old Cart/cart.png", "Decorations/Bench/bench.png",
                    "Food/Pie/pie.png"]


def test_category_candidates_prefix_slack(catalog):
    rels = scan_images(catalog)
    # "Decoration" matches both "Decoration" and "Decorations" segments.
    assert category_candidates(rels, "Decoration") == [
        "Decoration/Old Cart/cart.png", "Decorations/Bench/bench.png"]
    assert category_candidates(rels, "food") == ["Food/Pie/pie.png"]
    assert category_candidates(rels, "Chair") == []


def _group(n=2, category="Decoration", canvas="128x128"):
    return {"template": "mini-1-decoration-128x128", "category": category,
            "canvas": canvas,
            "assets": [{"assetName": f"Asset {i}", "prompt": f"prompt {i}",
                        "category": category, "canvas": canvas, "refFiles": []}
                       for i in range(n)]}


def test_build_catalog_sheet_grid_and_regions(catalog):
    img, regions, w, h = build_catalog_sheet(_group(2), catalog)
    # 128px cells → cols = min(1024//128, 2) = 2 → sheet 256x128.
    assert (w, h) == (256, 128)
    assert img.size == (256, 128)
    assert len(regions) == 2
    assert regions[0]["id"] == "region:Asset 0"
    assert regions[0]["desc"] == "prompt 0"
    assert regions[0]["assetType"] == "Decoration"
    assert regions[1]["x"] == 0.5  # second cell starts mid-sheet
    assert regions[0]["zIndex"] == 0 and regions[1]["zIndex"] == 1


def test_build_catalog_sheet_bad_canvas_raises(catalog):
    with pytest.raises(ValueError, match="Can't parse canvas size"):
        build_catalog_sheet(_group(1, canvas="-"), catalog)


def test_build_catalog_sheet_empty_group_raises(catalog):
    group = _group(0)
    with pytest.raises(ValueError, match="no named assets"):
        build_catalog_sheet(group, catalog)


def test_build_prefill_sheet_draws_refs(tmp_path):
    refs = tmp_path / "refs"
    make_png(str(refs / "Cart.png"), (64, 64), (0, 255, 0))
    assets = [{"assetName": "Cart", "category": "Decoration", "canvas": "128x128",
               "prompt": "p", "refFiles": ["Cart.png"]}]
    settings = PackSettings(preset=None, max_width=512, max_height=512,
                            background="#808080")
    img, regions, overflow = build_prefill_sheet(assets, str(refs), 512, 512, settings)
    assert img.size == (512, 512)
    assert overflow == []
    (region,) = regions
    # Sample the center of the first member cell — the green ref must be there.
    m = region["members"][0]
    cx = int((m["x"] + m["w"] / 2) * 512)
    cy = int((m["y"] + m["h"] / 2) * 512)
    assert img.getpixel((cx, cy)) == (0, 255, 0)
    # Outside any region: background gray.
    assert img.getpixel((5, 5)) == (128, 128, 128)


def test_save_sheet_writes_png_and_sidecar(tmp_path):
    img = Image.new("RGB", (64, 64), (1, 2, 3))
    regions = [{"id": "region:A", "zIndex": 0}]
    rel = save_sheet(img, regions, "Mini 08!", str(tmp_path), meta={"template": "g"})
    assert rel == "templates/mini-08.png"
    assert os.path.isfile(tmp_path / "templates" / "mini-08.png")
    sidecar = json.loads((tmp_path / "templates" / "mini-08.json").read_text())
    assert sidecar["size"] == {"w": 64, "h": 64}
    assert sidecar["spriteCount"] == 1
    assert sidecar["regions"] == regions
    assert sidecar["template"] == "g"
