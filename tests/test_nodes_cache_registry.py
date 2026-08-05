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
# routes pulls in aiohttp and ComfyUI's server; the root-scope tests already
# keep a stub loader for exactly that, and two copies would drift.
from test_routes_root_scope import _load_routes


@pytest.fixture()
def nodes_mod(monkeypatch, tmp_path):
    pkg, latest = build_modules()
    monkeypatch.setitem(sys.modules, "comfy_api", pkg)
    monkeypatch.setitem(sys.modules, "comfy_api.latest", latest)
    fp = types.ModuleType("folder_paths")
    out = tmp_path / "output"
    out.mkdir()
    inp = tmp_path / "input"
    inp.mkdir()
    fp.get_output_directory = lambda: str(out)
    # routes.declared_roots reads BOTH, and its guard is one try/except around
    # the pair — a stub missing this one silently declares neither.
    fp.get_input_directory = lambda: str(inp)
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
    monkeypatch.setattr(nodes_mod, "_reference_roots", lambda: [str(refs)])
    fp = nodes_mod.SymbioticaAssetRefs.fingerprint_inputs
    before = fp()

    # Same filename, different picture — the path alone would look unchanged.
    Image.new("RGB", (16, 16), (9, 9, 9)).save(refs / "Spookies.png")
    assert fp() != before


def test_asset_refs_ignores_folders_a_browse_route_made_servable(nodes_mod,
                                                                 monkeypatch,
                                                                 tmp_path):
    """A picker's thumbnail buffer is a served folder, not a reference folder.
    Hashing every folder the process ever made servable put the Pick buffers —
    which the pipeline WRITES to — inside this node's cache key: ticking a
    thumbnail re-ran the reference load, and with it the LLM that reads the
    reference and the image model that reads the LLM. One render per click, on
    an unchanged seed."""
    routes = _load_routes(monkeypatch)
    refs = tmp_path / "Bakery-October"
    refs.mkdir()
    Image.new("RGB", (8, 8), (1, 2, 3)).save(refs / "Spookies.png")
    buffer = tmp_path / "output" / "symbiotica_pick" / "483"
    buffer.mkdir(parents=True)
    routes.register_refs_root(str(refs))
    assert routes.register_root_within(str(buffer)) is True

    fp = nodes_mod.SymbioticaAssetRefs.fingerprint_inputs
    before = fp()
    Image.new("RGB", (8, 8), (4, 5, 6)).save(buffer / "abc123_thumb.png")
    assert fp() == before
    # …and the reference folder still moves it.
    Image.new("RGB", (16, 16), (9, 9, 9)).save(refs / "Spookies.png")
    assert fp() != before


def test_a_served_root_is_not_a_reference_root(monkeypatch, tmp_path):
    """The two registries answer different questions: what may be served, and
    what this node's output depends on. A save destination is the first without
    being the second."""
    routes = _load_routes(monkeypatch)
    refs = tmp_path / "refs"
    saves = tmp_path / "output" / "templates"
    refs.mkdir()
    saves.mkdir(parents=True)
    routes.register_refs_root(str(refs))
    routes.register_root(str(saves))
    assert os.path.realpath(str(refs)) in routes.reference_roots()
    assert os.path.realpath(str(saves)) not in routes.reference_roots()
    # Both remain servable — narrowing the watch list must not narrow access.
    assert os.path.realpath(str(refs)) in routes.executed_roots()
    assert os.path.realpath(str(saves)) in routes.executed_roots()


def test_asset_refs_moves_with_its_own_widgets(nodes_mod, monkeypatch,
                                               tmp_path):
    monkeypatch.setattr(nodes_mod, "_reference_roots", lambda: [])
    fp = nodes_mod.SymbioticaAssetRefs.fingerprint_inputs
    assert fp(background=["#808080"]) != fp(background=["#000000"])
    assert fp(output_size=["native"]) != fp(output_size=["512"])


def test_neither_change_check_raises_on_a_missing_folder(nodes_mod,
                                                         monkeypatch):
    # A raise here becomes NaN and re-bills every descendant per queue press.
    monkeypatch.setattr(nodes_mod, "_reference_roots", lambda: ["/nope/gone"])
    monkeypatch.setattr(nodes_mod, "_executed_projects", lambda: ["/nope/gone"])
    assert isinstance(nodes_mod.SymbioticaAssetRefs.fingerprint_inputs(), str)
    assert isinstance(
        nodes_mod.SymbioticaDatasetReference.fingerprint_inputs(
            seed=[1], project_path=[""]), str)


def test_dataset_reference_serves_the_folder_it_drew_from(nodes_mod, monkeypatch,
                                                          tmp_path):
    """A picker wired to `dataset_path` fetches its thumbnails over a route,
    and a project outside the studio volume is servable only once an execution
    vouches for it. Servable, never WATCHED: a dataset folder in the refs set
    would put every new reference file into Asset Refs' change-check and
    re-bill the lane that reads it."""
    routes = _load_routes(monkeypatch)
    drawn_from = tmp_path / "bakery" / "dataset" / "Decoration"
    drawn_from.mkdir(parents=True)
    Image.new("RGB", (8, 8), (1, 2, 3)).save(drawn_from / "Bunting.png")

    _images, _names, _boxes, folders = \
        nodes_mod.SymbioticaDatasetReference.execute(
            categories=["Decoration"], seed=[1],
            project_path=[str(tmp_path / "bakery")]).args

    assert folders == [str(drawn_from)]
    real = os.path.realpath(str(drawn_from))
    assert real in routes.executed_roots()
    assert real not in routes.reference_roots()
