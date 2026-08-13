# ABOUTME: The Grid Layout node's face — the ladder it climbs, the errors it
# ABOUTME: raises, and what it tells the canvas about the file it used.
import importlib
import os
import sys
import types

import pytest
from PIL import Image

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


def project_with(tmp_path, *names, size=(8, 4)):
    root = tmp_path / "bakery"
    folder = root / "datasets" / "layouts"
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        Image.new("RGBA", size, (16, 32, 48, 255)).save(folder / name)
    return str(root)


def test_it_is_registered(nodes_mod):
    assert nodes_mod.SymbioticaGridLayout in nodes_mod.PIPELINE_NODE_CLASSES


def test_the_wired_category_picks_the_file(nodes_mod, tmp_path):
    project = project_with(tmp_path, "Chair.png", "Food - 3 stages.png")
    out = nodes_mod.SymbioticaGridLayout.execute(
        project_path=project, category="Food - 3 stages")
    assert out.args[2] == "Food - 3 stages.png"


def test_a_bucket_narrows_it(nodes_mod, tmp_path):
    project = project_with(tmp_path, "Food - 3 stages.png",
                           "Food - 3 stages - Drinks.png")
    out = nodes_mod.SymbioticaGridLayout.execute(
        project_path=project, category="Food - 3 stages", bucket="Drinks")
    assert out.args[2] == "Food - 3 stages - Drinks.png"


def test_the_image_and_mask_have_the_layout_s_shape(nodes_mod, tmp_path):
    project = project_with(tmp_path, "Chair.png", size=(8, 4))
    out = nodes_mod.SymbioticaGridLayout.execute(
        project_path=project, category="Chair")
    assert tuple(out.args[0].shape) == (1, 4, 8, 3)
    assert tuple(out.args[1].shape) == (1, 4, 8)


def test_a_layout_without_alpha_gets_an_opaque_mask(nodes_mod, tmp_path):
    root = tmp_path / "bakery"
    folder = root / "datasets" / "layouts"
    folder.mkdir(parents=True)
    Image.new("RGB", (4, 4), (255, 0, 0)).save(folder / "Chair.png")
    out = nodes_mod.SymbioticaGridLayout.execute(
        project_path=str(root), category="Chair")
    assert float(out.args[1].min()) == 1.0


def test_the_order_carries_the_project(nodes_mod, tmp_path):
    project = project_with(tmp_path, "Chair.png")
    out = nodes_mod.SymbioticaGridLayout.execute(
        order={"project_path": project}, category="Chair")
    assert out.args[2] == "Chair.png"


def test_no_project_is_a_wiring_error(nodes_mod):
    with pytest.raises(ValueError, match="project"):
        nodes_mod.SymbioticaGridLayout.execute(category="Chair")


def test_a_missing_layout_names_the_folder_and_what_it_holds(nodes_mod,
                                                             tmp_path):
    """"no layout" is otherwise indistinguishable from "wrong project", and
    the fix is different."""
    project = project_with(tmp_path, "Chair.png")
    with pytest.raises(ValueError) as raised:
        nodes_mod.SymbioticaGridLayout.execute(project_path=project,
                                               category="Wallpaper")
    assert "Wallpaper" in str(raised.value)
    assert "Chair.png" in str(raised.value)
    assert os.path.join("datasets", "layouts") in str(raised.value)


def test_the_run_says_which_file_it_used(nodes_mod, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(nodes_mod, "_push",
                        lambda event, payload: seen.append((event, payload)))
    project = project_with(tmp_path, "Chair.png", "Table.png")
    nodes_mod.SymbioticaGridLayout.execute(project_path=project,
                                           category="Chair")
    pushed = [p for e, p in seen if e == "symbiotica.layout"]
    assert pushed and pushed[-1]["name"] == "Chair.png"
    assert pushed[-1]["layouts"] == ["Chair.png", "Table.png"]


def test_it_is_queueable_on_its_own(nodes_mod):
    assert nodes_mod.SymbioticaGridLayout.GET_SCHEMA().is_output_node is True


def test_the_fingerprint_follows_the_category_and_the_file(nodes_mod, tmp_path):
    project = project_with(tmp_path, "Chair.png", "Table.png")
    fp = nodes_mod.SymbioticaGridLayout.fingerprint_inputs
    assert (fp(project_path=project, category="Chair")
            != fp(project_path=project, category="Table"))
    before = fp(project_path=project, category="Chair")
    path = os.path.join(project, "datasets", "layouts", "Chair.png")
    Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(path)
    os.utime(path, ns=(1, 1))
    assert fp(project_path=project, category="Chair") != before


def test_the_fingerprint_never_raises(nodes_mod):
    assert nodes_mod.SymbioticaGridLayout.fingerprint_inputs(
        project_path=None, category=None)
