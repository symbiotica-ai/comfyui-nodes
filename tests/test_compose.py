# ABOUTME: Tests for sheet compositing — catalog grid build, prefill ref draw,
# ABOUTME: and PNG+sidecar saving with slugged names.
import json
import os

import pytest
from PIL import Image

from pipeline.compose import (
    _box_color,
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
    assert img.getpixel((cx, cy))[:3] == (0, 255, 0)
    # Outside any region: background gray. (The packed strip sits at the top
    # of the sheet and the upscaled ref fills its cell, so sample well below.)
    assert img.getpixel((5, 500))[:3] == (128, 128, 128)


def test_box_color_contrasts_background():
    assert _box_color("#808080")[:3] == (30, 30, 30)     # light sheet → dark box
    assert _box_color("#000000")[:3] == (220, 220, 220)  # dark sheet → light box
    assert _box_color("")[:3] == (220, 220, 220)         # transparent → light box


def test_build_prefill_sheet_border_frames_each_cell(tmp_path):
    refs = tmp_path / "refs"
    make_png(str(refs / "Cart.png"), (128, 128), (0, 255, 0))  # fills the cell
    assets = [{"assetName": "Cart", "category": "Decoration", "canvas": "128x128",
               "prompt": "p", "refFiles": ["Cart.png"]}]
    settings = PackSettings(preset=None, max_width=512, max_height=512,
                            background="#808080", border=6)
    img, regions, overflow = build_prefill_sheet(assets, str(refs), 512, 512,
                                                 settings)
    m = regions[0]["members"][0]
    x0 = round(m["x"] * 512)
    cy = int((m["y"] + m["h"] / 2) * 512)
    # A few px inside the cell's left edge sits under the 6px frame → box color,
    # drawn OVER the green ref that fills the cell.
    assert img.getpixel((x0 + 2, cy))[:3] == (30, 30, 30)
    # The cell center is still the green ref.
    cx = int((m["x"] + m["w"] / 2) * 512)
    assert img.getpixel((cx, cy))[:3] == (0, 255, 0)


def test_build_prefill_sheet_no_border_no_box(tmp_path):
    refs = tmp_path / "refs"
    make_png(str(refs / "Cart.png"), (128, 128), (0, 255, 0))
    assets = [{"assetName": "Cart", "category": "Decoration", "canvas": "128x128",
               "prompt": "p", "refFiles": ["Cart.png"]}]
    settings = PackSettings(preset=None, max_width=512, max_height=512,
                            background="#808080", border=0)
    img, regions, _ = build_prefill_sheet(assets, str(refs), 512, 512, settings)
    m = regions[0]["members"][0]
    x0 = round(m["x"] * 512)
    cy = int((m["y"] + m["h"] / 2) * 512)
    assert img.getpixel((x0 + 2, cy))[:3] == (0, 255, 0)  # no frame → still green


def test_build_prefill_sheet_upscales_ref_to_fill_cell(tmp_path):
    # Hub parity: a 64px ref in a 128px cell is drawn at cell size (upscaled),
    # so the ref's color reaches the cell's corners, not just its center.
    refs = tmp_path / "refs"
    make_png(str(refs / "Cart.png"), (64, 64), (0, 255, 0))
    assets = [{"assetName": "Cart", "category": "Decoration", "canvas": "128x128",
               "prompt": "p", "refFiles": ["Cart.png"]}]
    settings = PackSettings(preset=None, max_width=512, max_height=512,
                            background="#808080")
    img, regions, overflow = build_prefill_sheet(assets, str(refs), 512, 512, settings)
    assert overflow == []
    m = regions[0]["members"][0]
    # ~4px in from the member cell's top-left corner: green only if upscaled to fill.
    px = int(m["x"] * 512) + 4
    py = int(m["y"] * 512) + 4
    assert img.getpixel((px, py))[:3] == (0, 255, 0)


def test_build_prefill_sheet_empty_background_transparent_rgba(tmp_path):
    refs = tmp_path / "refs"
    make_png(str(refs / "Cart.png"), (64, 64), (0, 255, 0))
    assets = [{"assetName": "Cart", "category": "Decoration", "canvas": "128x128",
               "prompt": "p", "refFiles": ["Cart.png"]}]
    settings = PackSettings(preset=None, max_width=512, max_height=512,
                            background="")
    img, regions, overflow = build_prefill_sheet(assets, str(refs), 512, 512, settings)
    assert img.mode == "RGBA"
    # Outside all regions (below the packed strip): fully transparent.
    assert img.getpixel((5, 500))[3] == 0


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


from pipeline.compose import build_paired_sheets


def test_build_paired_sheets_aligned_and_assigned(tmp_path):
    refs = tmp_path / "refs"
    make_png(str(refs / "Cart.png"), (64, 64), (0, 255, 0))
    catalog = tmp_path / "assets"
    make_png(str(catalog / "Decoration" / "Old Cart" / "old.png"), (64, 64), (255, 0, 0))
    assets = [{"assetName": "Cart", "category": "Decoration", "canvas": "128x128",
               "prompt": "p", "refFiles": ["Cart.png"]}]
    settings = PackSettings(preset=None, max_width=512, max_height=512,
                            background="#808080")
    base, task, regions, overflow = build_paired_sheets(
        assets, str(refs), str(catalog), {"Cart": "Decoration/Old Cart/old.png"},
        512, 512, settings)
    assert overflow == []
    (region,) = regions
    m = region["members"][0]
    cx = int((m["x"] + m["w"] / 2) * 512)
    cy = int((m["y"] + m["h"] / 2) * 512)
    # Same region layout, different content: ref on task, assigned art on base.
    assert task.getpixel((cx, cy))[:3] == (0, 255, 0)
    assert base.getpixel((cx, cy))[:3] == (255, 0, 0)
    # Flip pair: second member cell also drawn on the base sheet.
    m2 = region["members"][1]
    cx2 = int((m2["x"] + m2["w"] / 2) * 512)
    assert base.getpixel((cx2, cy))[:3] == (255, 0, 0)


def test_build_paired_sheets_unassigned_stays_background(tmp_path):
    refs = tmp_path / "refs"
    make_png(str(refs / "Cart.png"), (64, 64), (0, 255, 0))
    catalog = tmp_path / "assets"
    catalog.mkdir()
    assets = [{"assetName": "Cart", "category": "Decoration", "canvas": "128x128",
               "prompt": "p", "refFiles": ["Cart.png"]}]
    settings = PackSettings(preset=None, max_width=512, max_height=512,
                            background="#808080")
    base, task, regions, _ = build_paired_sheets(
        assets, str(refs), str(catalog), {}, 512, 512, settings)
    (region,) = regions
    m = region["members"][0]
    cx = int((m["x"] + m["w"] / 2) * 512)
    cy = int((m["y"] + m["h"] / 2) * 512)
    assert base.getpixel((cx, cy))[:3] == (128, 128, 128)  # background
    assert task.getpixel((cx, cy))[:3] == (0, 255, 0)      # ref still drawn


def test_build_paired_sheets_missing_assignment_file_is_background(tmp_path):
    refs = tmp_path / "refs"
    make_png(str(refs / "Cart.png"), (64, 64), (0, 255, 0))
    catalog = tmp_path / "assets"
    catalog.mkdir()
    assets = [{"assetName": "Cart", "category": "Decoration", "canvas": "128x128",
               "prompt": "p", "refFiles": ["Cart.png"]}]
    settings = PackSettings(preset=None, max_width=512, max_height=512,
                            background="#808080")
    base, _, regions, _ = build_paired_sheets(
        assets, str(refs), str(catalog), {"Cart": "Nope/missing.png"},
        512, 512, settings)
    m = regions[0]["members"][0]
    cx = int((m["x"] + m["w"] / 2) * 512)
    cy = int((m["y"] + m["h"] / 2) * 512)
    assert base.getpixel((cx, cy))[:3] == (128, 128, 128)


def test_draw_task_refs_honors_selection_and_pair_flip(tmp_path):
    from pipeline.compose import _draw_task_refs, _paint_background

    refs = tmp_path / "refs"
    # Asymmetric ref: left half green, right half red.
    img = Image.new("RGB", (64, 64), (0, 255, 0))
    for x in range(32, 64):
        for y in range(64):
            img.putpixel((x, y), (255, 0, 0))
    os.makedirs(refs, exist_ok=True)
    img.save(refs / "Cart_1.png")
    make_png(str(refs / "Cart.png"), (64, 64), (0, 0, 255))

    # Two-cell region born with two refs, user checked only Cart_1.png.
    regions = [{
        "id": "region:spec:Cart", "name": "Cart",
        "x": 0, "y": 0, "w": 0.5, "h": 0.25,
        "taskRefs": {"paths": ["Decoration/Cart/Cart_1.png"], "mode": "meta"},
        "members": [
            {"spriteId": "Decoration/Cart/Cart.png", "x": 0.0, "y": 0.0,
             "w": 0.125, "h": 0.125},
            {"spriteId": "Decoration/Cart/Cart_1.png", "x": 0.25, "y": 0.0,
             "w": 0.125, "h": 0.125},
        ],
    }]
    sheet = _paint_background(512, 512, "#808080")
    _draw_task_refs(sheet, regions, str(refs), 512, 512)
    # Cell 1 draws Cart_1 (not the blue Cart.png): left quarter green.
    assert sheet.getpixel((16, 32))[:3] == (0, 255, 0)
    # Cell 2 draws the SAME image mirrored: left quarter now red.
    assert sheet.getpixel((128 + 16, 32))[:3] == (255, 0, 0)


def test_draw_task_refs_two_checked_refs_no_baked_flip(tmp_path):
    from pipeline.compose import _draw_task_refs, _paint_background

    refs = tmp_path / "refs"
    os.makedirs(refs, exist_ok=True)
    # Asymmetric pair: left-green/right-red and its pre-mirrored counterpart.
    a = Image.new("RGB", (64, 64), (0, 255, 0))
    for x in range(32, 64):
        for y in range(64):
            a.putpixel((x, y), (255, 0, 0))
    a.save(refs / "Cart.png")
    a.transpose(Image.FLIP_LEFT_RIGHT).save(refs / "Cart_1.png")

    regions = [{
        "id": "region:spec:Cart", "name": "Cart",
        "x": 0, "y": 0, "w": 0.5, "h": 0.25,
        "taskRefs": {"paths": ["D/Cart/Cart.png", "D/Cart/Cart_1.png"],
                     "mode": "meta"},
        "members": [
            {"spriteId": "D/Cart/Cart.png", "x": 0.0, "y": 0.0,
             "w": 0.125, "h": 0.125},
            # Born as a flip pair: baked flipX must NOT apply to explicit picks.
            {"spriteId": "D/Cart/Cart.png", "x": 0.125, "y": 0.0,
             "w": 0.125, "h": 0.125, "flipX": True},
        ],
    }]
    sheet = _paint_background(512, 512, "#808080")
    _draw_task_refs(sheet, regions, str(refs), 512, 512)
    # Cell 1: Cart.png unflipped -> left quarter green.
    assert sheet.getpixel((16, 32))[:3] == (0, 255, 0)
    # Cell 2: Cart_1.png (pre-mirrored) drawn AS-IS -> left quarter red.
    assert sheet.getpixel((64 + 16, 32))[:3] == (255, 0, 0)
