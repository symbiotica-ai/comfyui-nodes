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
    assert [i.id for i in schema.inputs] == [
        "references", "results", "cell_size", "spacing", "background"]
    assert [o.display_name for o in schema.outputs] == ["sheet"]
