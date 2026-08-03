# ABOUTME: Node-face tests for cutting a generated sheet back into cells —
# ABOUTME: role alignment, the off-by-a-render inset, and the refusals.
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


FOOD = json.dumps([
    {"role": "prep", "x": 271, "y": 20, "w": 482, "h": 482},
    {"role": "ready", "x": 20, "y": 522, "w": 482, "h": 482},
    {"role": "serving", "x": 522, "y": 522, "w": 482, "h": 482},
])


def sheet(size=1024):
    """A sheet whose pixels encode their own position, so a mis-cut is visible
    as a wrong value rather than merely a wrong shape."""
    ramp = torch.arange(size, dtype=torch.float32) / size
    img = ramp.view(1, size, 1, 1).expand(1, size, size, 3).clone()
    img[..., 1] = ramp.view(1, 1, size).expand(1, size, size)
    return img


def test_cuts_one_cell_per_box_with_its_role(nodes_mod):
    cells, roles = nodes_mod.SymbioticaSliceCells.execute(
        image=sheet(), cell_boxes=FOOD, inset=0).args
    assert roles == ["prep", "ready", "serving"]
    assert [tuple(c.shape) for c in cells] == [(1, 482, 482, 3)] * 3


def test_each_cell_holds_its_own_region(nodes_mod):
    src = sheet()
    cells, _ = nodes_mod.SymbioticaSliceCells.execute(
        image=src, cell_boxes=FOOD, inset=0).args
    for cell, box in zip(cells, json.loads(FOOD)):
        expected = src[:, box["y"]:box["y"] + box["h"],
                       box["x"]:box["x"] + box["w"], :]
        assert torch.equal(cell, expected)


def test_inset_shrinks_every_cell(nodes_mod):
    # The boxes are the grid the render was ASKED to hit; a couple of pixels of
    # slack keeps the matte out of a cell when it lands slightly off.
    cells, _ = nodes_mod.SymbioticaSliceCells.execute(
        image=sheet(), cell_boxes=FOOD, inset=2).args
    assert [tuple(c.shape) for c in cells] == [(1, 478, 478, 3)] * 3


def test_output_size_squares_every_cell(nodes_mod):
    cells, _ = nodes_mod.SymbioticaSliceCells.execute(
        image=sheet(), cell_boxes=FOOD, inset=1, output_size=512).args
    assert [tuple(c.shape) for c in cells] == [(1, 512, 512, 3)] * 3
    assert all(float(c.min()) >= 0.0 and float(c.max()) <= 1.0 for c in cells)


def test_a_sheet_of_another_size_is_refused_not_half_cut(nodes_mod):
    # Cutting 1024 boxes out of a 512 image would silently return slivers of the
    # top-left corner and look like a bad generation.
    with pytest.raises(Exception, match="not the sheet"):
        nodes_mod.SymbioticaSliceCells.execute(
            image=sheet(256), cell_boxes=FOOD, inset=0)


def test_no_boxes_names_the_wire_to_fix(nodes_mod):
    with pytest.raises(Exception, match="cell_boxes"):
        nodes_mod.SymbioticaSliceCells.execute(image=sheet(), cell_boxes="[]")


def test_malformed_boxes_are_refused(nodes_mod):
    with pytest.raises(Exception, match="cell_boxes"):
        nodes_mod.SymbioticaSliceCells.execute(image=sheet(),
                                               cell_boxes="{not json")


def test_outputs_are_lists_so_the_lane_fans_out(nodes_mod):
    schema = nodes_mod.SymbioticaSliceCells.define_schema()
    assert [o.display_name for o in schema.outputs] == ["cells", "roles"]
    assert all(o.is_output_list for o in schema.outputs)
