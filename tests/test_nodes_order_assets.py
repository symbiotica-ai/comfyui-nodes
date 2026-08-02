# ABOUTME: Node-face tests for the per-asset iterator and the dataset draw —
# ABOUTME: output order, list alignment, and the whole-list input declaration.
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


def _asset(name, category, prompt="brief"):
    return {"assetName": name, "category": category, "prompt": prompt,
            "canvas": "128x128", "rotation": "-", "refFiles": ["a.png"]}


MINI_1 = {"feature": "Mini 1", "assets": [
    _asset("Phantom Freezer Cart", "Decoration"),
    _asset("Ghost Bakery Queue", "Decoration"),
    _asset("Witch Cat Tea Parlor", "Decoration"),
    _asset("Spookies", "Food - 3 stages"),
    _asset("Spooky Stack Popsicle", "Food - 3 stages"),
    _asset("Ghostly Jelly Cake", "Food - 3 stages"),
]}


def test_order_assets_outputs_stay_aligned(nodes_mod):
    schema = nodes_mod.SymbioticaOrderAssets.define_schema()
    assert [o.display_name for o in schema.outputs] == [
        "asset_names", "categories", "client_prompts"]
    names, cats, prompts = nodes_mod.SymbioticaOrderAssets.execute(
        order=MINI_1).args
    assert len(names) == len(cats) == len(prompts) == 6
    assert cats == ["Decoration"] * 3 + ["Food - 3 stages"] * 3
    assert names[0] == "Phantom Freezer Cart" and names[3] == "Spookies"


def test_order_assets_refuses_an_unwired_order(nodes_mod):
    with pytest.raises(ValueError, match="wire an Order Specs"):
        nodes_mod.SymbioticaOrderAssets.execute(order=None)


def test_order_assets_names_the_empty_event(nodes_mod):
    with pytest.raises(ValueError, match="Mini 9"):
        nodes_mod.SymbioticaOrderAssets.execute(
            order={"feature": "Mini 9", "assets": []})


def _project(tmp_path, **cats):
    proj = tmp_path / "bakery"
    for cat, n in cats.items():
        d = proj / "dataset" / cat
        d.mkdir(parents=True)
        for i in range(n):
            Image.new("RGB", (8, 8), (i * 20, 0, 0)).save(d / f"{cat}-{i}.png")
    return proj


def test_dataset_reference_declares_whole_list_input(nodes_mod):
    # Mapped per asset, each execute would see one category and could not make
    # the draw per TYPE — every asset would get its own random reference.
    schema = nodes_mod.SymbioticaDatasetReference.define_schema()
    assert schema.is_input_list is True
    assert [o.display_name for o in schema.outputs] == [
        "images", "reference_names"]


def test_dataset_reference_gives_one_image_per_asset(nodes_mod, tmp_path):
    proj = _project(tmp_path, **{"Decoration": 4, "Food - 3 stages": 4})
    cats = ["Decoration"] * 3 + ["Food - 3 stages"] * 3
    images, names = nodes_mod.SymbioticaDatasetReference.execute(
        categories=cats, seed=[7], project_path=[str(proj)]).args
    assert len(images) == 6 and len(names) == 6
    assert len(set(names[:3])) == 1, "one reference shared by all decorations"
    assert len(set(names[3:])) == 1, "one reference shared by all food"
    assert names[0] != names[3]


def test_dataset_reference_reads_the_project_from_the_order(nodes_mod, tmp_path):
    proj = _project(tmp_path, **{"Decoration": 2})
    _images, names = nodes_mod.SymbioticaDatasetReference.execute(
        categories=["Decoration"], seed=[1], project_path=[""],
        order=[{"project_path": str(proj)}]).args
    assert names[0].startswith("Decoration-")


def test_dataset_reference_names_a_missing_type_folder(nodes_mod, tmp_path):
    proj = _project(tmp_path, **{"Decoration": 2})
    with pytest.raises(Exception, match="Signage"):
        nodes_mod.SymbioticaDatasetReference.execute(
            categories=["Decoration", "Signage"], seed=[1],
            project_path=[str(proj)])


def test_dataset_reference_fingerprint_survives_linked_inputs(nodes_mod,
                                                              tmp_path):
    # Every LINKED input arrives as None here. Raising would set is_changed to
    # NaN and re-bill the LLM and Gemini on every queue press.
    proj = _project(tmp_path, **{"Decoration": 2})
    fp = nodes_mod.SymbioticaDatasetReference.fingerprint_inputs
    assert isinstance(fp(categories=None, seed=[3], project_path=[str(proj)],
                         order=None), str)


def test_dataset_reference_fingerprint_moves_with_the_seed(nodes_mod, tmp_path):
    proj = _project(tmp_path, **{"Decoration": 2})
    fp = nodes_mod.SymbioticaDatasetReference.fingerprint_inputs
    assert fp(seed=[1], project_path=[str(proj)]) != \
        fp(seed=[2], project_path=[str(proj)])


def test_dataset_reference_fingerprint_moves_when_a_file_is_added(nodes_mod,
                                                                  tmp_path):
    proj = _project(tmp_path, **{"Decoration": 2})
    fp = nodes_mod.SymbioticaDatasetReference.fingerprint_inputs
    before = fp(seed=[1], project_path=[str(proj)])
    Image.new("RGB", (8, 8)).save(proj / "dataset" / "Decoration" / "new.png")
    assert fp(seed=[1], project_path=[str(proj)]) != before
