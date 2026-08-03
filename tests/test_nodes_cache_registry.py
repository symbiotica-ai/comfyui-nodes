# ABOUTME: Change-checks for the two nodes whose files arrive on wires — both
# ABOUTME: read the execution registry, because a linked input reads as unset.
import importlib
import json
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


def make_project(tmp_path, layout="food2row"):
    proj = tmp_path / "bakery"
    (proj / "_sources").mkdir(parents=True)
    (proj / "_sources" / "config.json").write_text(
        json.dumps({"layouts": {"Food - 3 stages": layout}, "swapped": {}}))
    (proj / "assetkit-project.json").write_text(
        json.dumps({"settings": {"width": 1024, "height": 1024,
                                 "padding": 20}}))
    d = proj / "dataset" / "Food - 3 stages"
    d.mkdir(parents=True)
    Image.new("RGB", (8, 8)).save(d / "ref.png")
    return proj


def test_dataset_reference_finds_the_project_the_execution_registered(
        nodes_mod, monkeypatch, tmp_path):
    """The project arrives on the ORDER wire, so the widget is empty here. Left
    to the widget alone the folder walk resolved a relative 'dataset' that
    never existed, and the whole guard was dead in exactly the graphs it was
    written for."""
    proj = make_project(tmp_path)
    monkeypatch.setattr(nodes_mod, "_executed_projects", lambda: [str(proj)])
    fp = nodes_mod.SymbioticaDatasetReference.fingerprint_inputs
    before = fp(seed=[1], project_path=[""])

    Image.new("RGB", (8, 8)).save(
        proj / "dataset" / "Food - 3 stages" / "added.png")
    assert fp(seed=[1], project_path=[""]) != before


def test_dataset_reference_reruns_when_a_type_is_re_ruled(nodes_mod,
                                                          monkeypatch,
                                                          tmp_path):
    """cell_boxes comes from the layout, and nothing wired changes when the
    rule does — without this the crop silently keeps the old grid."""
    proj = make_project(tmp_path, layout="food2row")
    monkeypatch.setattr(nodes_mod, "_executed_projects", lambda: [str(proj)])
    fp = nodes_mod.SymbioticaDatasetReference.fingerprint_inputs
    before = fp(seed=[1], project_path=[""])

    (proj / "_sources" / "config.json").write_text(
        json.dumps({"layouts": {"Food - 3 stages": "grid2x2"}, "swapped": {}}))
    assert fp(seed=[1], project_path=[""]) != before


def test_dataset_reference_is_stable_when_nothing_changed(nodes_mod,
                                                          monkeypatch,
                                                          tmp_path):
    proj = make_project(tmp_path)
    monkeypatch.setattr(nodes_mod, "_executed_projects", lambda: [str(proj)])
    fp = nodes_mod.SymbioticaDatasetReference.fingerprint_inputs
    assert fp(seed=[1], project_path=[""]) == fp(seed=[1], project_path=[""])


def test_dataset_reference_still_prefers_an_explicit_widget(nodes_mod,
                                                            monkeypatch,
                                                            tmp_path):
    """A typed project must win over the registry, or two projects open at once
    would cross-contaminate each other's cache keys."""
    proj = make_project(tmp_path)
    monkeypatch.setattr(nodes_mod, "_executed_projects",
                        lambda: [str(tmp_path / "somewhere-else")])
    fp = nodes_mod.SymbioticaDatasetReference.fingerprint_inputs
    assert fp(seed=[1], project_path=[str(proj)]) != fp(seed=[1],
                                                        project_path=[""])


def test_asset_refs_reruns_when_a_reference_file_is_replaced(nodes_mod,
                                                             monkeypatch,
                                                             tmp_path):
    """Both of this node's file-naming inputs are linked, so a client dropping
    in a corrected reference changes nothing it can otherwise see."""
    refs = tmp_path / "Bakery-October"
    refs.mkdir()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(refs / "Spookies.png")
    monkeypatch.setattr(nodes_mod, "_executed_roots", lambda: [str(refs)])
    fp = nodes_mod.SymbioticaAssetRefs.fingerprint_inputs
    before = fp()

    # Same filename, different picture — the path alone would look unchanged.
    Image.new("RGB", (16, 16), (9, 9, 9)).save(refs / "Spookies.png")
    assert fp() != before


def test_asset_refs_moves_with_its_own_widgets(nodes_mod, monkeypatch,
                                               tmp_path):
    monkeypatch.setattr(nodes_mod, "_executed_roots", lambda: [])
    fp = nodes_mod.SymbioticaAssetRefs.fingerprint_inputs
    assert fp(background=["#808080"]) != fp(background=["#000000"])
    assert fp(output_size=["native"]) != fp(output_size=["512"])


def test_neither_change_check_raises_on_a_missing_folder(nodes_mod,
                                                         monkeypatch):
    # A raise here becomes NaN and re-bills every descendant per queue press.
    monkeypatch.setattr(nodes_mod, "_executed_roots", lambda: ["/nope/gone"])
    monkeypatch.setattr(nodes_mod, "_executed_projects", lambda: ["/nope/gone"])
    assert isinstance(nodes_mod.SymbioticaAssetRefs.fingerprint_inputs(), str)
    assert isinstance(
        nodes_mod.SymbioticaDatasetReference.fingerprint_inputs(
            seed=[1], project_path=[""]), str)
