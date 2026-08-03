# ABOUTME: Node-face tests for the comparison sheet — batch flattening, the
# ABOUTME: auto cell size, and refusing an empty pair.
import importlib
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


def frame(size=64, shade=0.5, batch=1):
    return torch.full((batch, size, size, 3), shade, dtype=torch.float32)


def test_lays_references_over_results(nodes_mod):
    out = nodes_mod.SymbioticaCompareSheet.execute(
        references=[frame(64, 1.0), frame(64, 1.0), frame(64, 1.0)],
        results=[frame(64, 0.0), frame(64, 0.0), frame(64, 0.0)],
        cell_size=[64], spacing=[8], background=["#808080"])
    sheet = out.args[0]
    # 3 columns x 2 rows of 64 with 8 gutters counted one more time than cells.
    assert tuple(sheet.shape) == (1, 64 * 2 + 8 * 3, 64 * 3 + 8 * 4, 3)


def test_flattens_a_batch_arriving_on_one_wire(nodes_mod):
    """A plain batch and a fanned-out list must both work on the same socket."""
    out = nodes_mod.SymbioticaCompareSheet.execute(
        references=[frame(32, 1.0, batch=3)],
        results=[frame(32, 0.0, batch=3)],
        cell_size=[32], spacing=[0], background=["#000000"])
    assert tuple(out.args[0].shape) == (1, 64, 96, 3)


def test_auto_cell_size_takes_the_largest_edge(nodes_mod):
    out = nodes_mod.SymbioticaCompareSheet.execute(
        references=[frame(128, 1.0)], results=[frame(32, 0.0)],
        cell_size=[0], spacing=[0], background=["#000000"])
    assert tuple(out.args[0].shape) == (1, 256, 128, 3)


def test_an_uneven_pair_keeps_its_columns_aligned(nodes_mod):
    out = nodes_mod.SymbioticaCompareSheet.execute(
        references=[frame(32, 1.0), frame(32, 1.0)], results=[frame(32, 0.0)],
        cell_size=[32], spacing=[0], background=["#000000"])
    sheet = out.args[0][0]
    assert tuple(sheet.shape) == (64, 64, 3)
    # The lone result sits in column 1, leaving column 2 as background.
    assert float(sheet[48][16][0]) > 0.9 or float(sheet[48][16][0]) < 0.1
    assert float(sheet[48][48][0]) == pytest.approx(0.0, abs=0.01)


def test_one_row_alone_still_makes_a_sheet(nodes_mod):
    out = nodes_mod.SymbioticaCompareSheet.execute(
        references=[frame(32, 1.0)], results=[], cell_size=[32], spacing=[0],
        background=["#000000"])
    assert tuple(out.args[0].shape) == (1, 64, 32, 3)


def test_two_empty_rows_name_the_wires_to_fix(nodes_mod):
    with pytest.raises(Exception, match="references"):
        nodes_mod.SymbioticaCompareSheet.execute(
            references=[], results=[], cell_size=[0], spacing=[8],
            background=["#808080"])


def test_takes_both_rows_whole(nodes_mod):
    schema = nodes_mod.SymbioticaCompareSheet.define_schema()
    # Mapped per image this would emit one sheet per cell.
    assert schema.is_input_list is True
    # The mask inputs are APPENDED — ComfyUI restores widgets_values
    # positionally, so a new one in the middle loads a saved pick onto the
    # wrong widget.
    assert [i.id for i in schema.inputs] == [
        "references", "results", "cell_size", "spacing", "background",
        "reference_masks", "result_masks", "mask_is_transparency"]
    assert [o.display_name for o in schema.outputs] == ["sheet"]


def _black_flattened(size=64):
    """What a loader hands on for a transparent PNG: art on black."""
    import torch
    t = torch.zeros(1, size, size, 3)
    t[:, 20:44, 20:44, 1] = 0.8
    return t


def _mask(size=64, transparency=True):
    """LoadImage polarity by default: 1 where the picture is see-through."""
    import torch
    m = torch.ones(1, size, size) if transparency else torch.zeros(1, size,
                                                                   size)
    m[:, 20:44, 20:44] = 0.0 if transparency else 1.0
    return m


def test_a_mask_puts_the_background_behind_a_flattened_sprite(nodes_mod):
    out = nodes_mod.SymbioticaCompareSheet.execute(
        references=[_black_flattened()], results=[_black_flattened()],
        cell_size=[64], spacing=[0], background=["#808080"],
        reference_masks=[_mask()], result_masks=[_mask()],
        mask_is_transparency=[True]).args[0]
    px = out[0]
    assert [round(float(v) * 255) for v in px[2][2]] == [128, 128, 128]
    assert round(float(px[30][30][1]) * 255) > 150, "art kept"


def test_without_masks_the_flattened_black_still_shows(nodes_mod):
    """Pins why the mask inputs exist at all."""
    out = nodes_mod.SymbioticaCompareSheet.execute(
        references=[_black_flattened()], results=[_black_flattened()],
        cell_size=[64], spacing=[0], background=["#808080"]).args[0]
    assert [round(float(v) * 255) for v in out[0][2][2]] == [0, 0, 0]


def test_straight_alpha_masks_work_when_declared(nodes_mod):
    out = nodes_mod.SymbioticaCompareSheet.execute(
        references=[_black_flattened()], results=[_black_flattened()],
        cell_size=[64], spacing=[0], background=["#808080"],
        reference_masks=[_mask(transparency=False)],
        result_masks=[_mask(transparency=False)],
        mask_is_transparency=[False]).args[0]
    assert [round(float(v) * 255) for v in out[0][2][2]] == [128, 128, 128]


def test_fewer_masks_than_images_leaves_the_rest_opaque(nodes_mod):
    import torch
    two = torch.cat([_black_flattened(), _black_flattened()], dim=0)
    out = nodes_mod.SymbioticaCompareSheet.execute(
        references=[two], results=[_black_flattened()],
        cell_size=[64], spacing=[0], background=["#808080"],
        reference_masks=[_mask()], mask_is_transparency=[True]).args[0]
    px = out[0]
    assert [round(float(v) * 255) for v in px[2][2]] == [128, 128, 128]
    assert [round(float(v) * 255) for v in px[2][66]] == [0, 0, 0]
