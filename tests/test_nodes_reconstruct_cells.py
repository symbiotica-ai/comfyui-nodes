# ABOUTME: Node-face tests for putting cells back into their sheet — the round
# ABOUTME: trip with Slice Cells, canvas recovery, and transparency.
import importlib
import json
import os
import sys
import types

import pytest
import torch

sys.path.insert(0, os.path.dirname(__file__))
from comfy_api_stub import build_modules


@pytest.fixture()
def nodes_mod(monkeypatch, tmp_path):
    pkg, latest = build_modules()
    monkeypatch.setitem(sys.modules, "comfy_api", pkg)
    monkeypatch.setitem(sys.modules, "comfy_api.latest", latest)
    fp = types.ModuleType("folder_paths")
    out = tmp_path / "output"
    out.mkdir()
    fp.get_output_directory = lambda: str(out)
    monkeypatch.setitem(sys.modules, "folder_paths", fp)
    sys.modules.pop("pipeline.nodes", None)
    import pipeline.nodes as nodes
    importlib.reload(nodes)
    yield nodes
    sys.modules.pop("pipeline.nodes", None)


# The real bakery grid: 1024 canvas, 20 gutter, 482 cells.
FOOD = json.dumps([
    {"role": "prep", "x": 271, "y": 20, "w": 482, "h": 482},
    {"role": "ready", "x": 20, "y": 522, "w": 482, "h": 482},
    {"role": "serving", "x": 522, "y": 522, "w": 482, "h": 482},
])


def solid(shade, size=482):
    return torch.full((1, size, size, 3), shade, dtype=torch.float32)


def test_rebuilds_the_sheet_the_cells_were_cut_from(nodes_mod):
    out = nodes_mod.SymbioticaReconstructCells.execute(
        cells=[solid(0.2), solid(0.5), solid(0.9)], cell_boxes=[FOOD],
        background=["#000000"], canvas_size=[0]).args[0]
    # Canvas recovered from the boxes: the grid is centred, so the margin after
    # the last cell equals the one before the first.
    assert tuple(out.shape) == (1, 1024, 1024, 3)


def test_each_cell_lands_back_in_its_own_box(nodes_mod):
    out = nodes_mod.SymbioticaReconstructCells.execute(
        cells=[solid(0.2), solid(0.5), solid(0.9)], cell_boxes=[FOOD],
        background=["#000000"], canvas_size=[0]).args[0][0]

    def at(x, y):
        return round(float(out[y][x][0]) * 255)

    assert at(512, 260) == round(0.2 * 255), "prep, top centre"
    assert at(260, 763) == round(0.5 * 255), "ready, bottom left"
    assert at(763, 763) == round(0.9 * 255), "serving, bottom right"
    assert at(2, 2) == 0, "gutter is background"


def test_the_round_trip_with_slice_cells_preserves_placement(nodes_mod):
    """Cut a sheet up and put it back: every cell returns to where it was."""
    sheet = torch.zeros(1, 1024, 1024, 3)
    for shade, box in zip((0.2, 0.5, 0.9), json.loads(FOOD)):
        y, x, w, h = box["y"], box["x"], box["w"], box["h"]
        sheet[:, y:y + h, x:x + w, :] = shade

    cells, _roles = nodes_mod.SymbioticaSliceCells.execute(
        image=sheet, cell_boxes=FOOD, inset=0).args
    rebuilt = nodes_mod.SymbioticaReconstructCells.execute(
        cells=cells, cell_boxes=[FOOD], background=["#000000"],
        canvas_size=[0]).args[0]

    assert tuple(rebuilt.shape) == tuple(sheet.shape)
    for box in json.loads(FOOD):
        cy, cx = box["y"] + box["h"] // 2, box["x"] + box["w"] // 2
        assert torch.allclose(rebuilt[0, cy, cx], sheet[0, cy, cx], atol=0.01)


def test_a_cell_of_another_size_is_fitted_into_its_box(nodes_mod):
    """Cells come back from editing at whatever size the editor produced."""
    out = nodes_mod.SymbioticaReconstructCells.execute(
        cells=[solid(0.7, size=1024)], cell_boxes=[FOOD],
        background=["#000000"], canvas_size=[0]).args[0][0]
    assert round(float(out[260][512][0]) * 255) == round(0.7 * 255)


def test_canvas_size_overrides_the_recovered_one(nodes_mod):
    out = nodes_mod.SymbioticaReconstructCells.execute(
        cells=[solid(0.2)], cell_boxes=[FOOD], background=["#000000"],
        canvas_size=[1200]).args[0]
    assert tuple(out.shape) == (1, 1200, 1200, 3)


def test_fewer_sprites_than_cells_leaves_the_rest_background(nodes_mod):
    """A short run must not shift every later sprite into the wrong cell."""
    out = nodes_mod.SymbioticaReconstructCells.execute(
        cells=[solid(0.2)], cell_boxes=[FOOD], background=["#000000"],
        canvas_size=[0]).args[0][0]
    assert round(float(out[260][512][0]) * 255) == round(0.2 * 255)
    assert round(float(out[763][260][0]) * 255) == 0, "second cell untouched"


def test_a_mask_puts_the_background_behind_a_flattened_sprite(nodes_mod):
    sprite = torch.zeros(1, 482, 482, 3)      # loader output: art on black
    sprite[:, 100:380, 100:380, 1] = 0.8
    mask = torch.ones(1, 482, 482)            # LoadImage polarity
    mask[:, 100:380, 100:380] = 0.0
    out = nodes_mod.SymbioticaReconstructCells.execute(
        cells=[sprite], cell_boxes=[FOOD], background=["#808080"],
        canvas_size=[0], masks=[mask], mask_is_transparency=[True]).args[0][0]
    assert round(float(out[40][512][0]) * 255) == 128, "background, not black"
    assert round(float(out[260][512][1]) * 255) > 150, "art kept"


def test_no_boxes_names_the_wire_to_fix(nodes_mod):
    with pytest.raises(Exception, match="cell_boxes"):
        nodes_mod.SymbioticaReconstructCells.execute(
            cells=[solid(0.2)], cell_boxes=["[]"])


def test_no_cells_is_refused(nodes_mod):
    with pytest.raises(Exception, match="cells"):
        nodes_mod.SymbioticaReconstructCells.execute(cells=[],
                                                     cell_boxes=[FOOD])


def test_takes_every_cell_at_once(nodes_mod):
    schema = nodes_mod.SymbioticaReconstructCells.define_schema()
    assert schema.is_input_list is True
    assert [i.id for i in schema.inputs] == [
        "cells", "cell_boxes", "background", "canvas_size", "masks",
        "mask_is_transparency"]
    assert [o.display_name for o in schema.outputs] == ["sheet"]
