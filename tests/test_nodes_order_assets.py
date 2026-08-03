# ABOUTME: Node-face tests for the per-asset iterator and the dataset draw —
# ABOUTME: output order, list alignment, and the whole-list input declaration.
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
        "asset_names", "categories", "client_prompts", "save_paths"]
    names, cats, prompts, _paths = nodes_mod.SymbioticaOrderAssets.execute(
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


def test_category_widget_narrows_the_run(nodes_mod):
    names, cats, prompts, _paths = nodes_mod.SymbioticaOrderAssets.execute(
        order=MINI_1, category="Food - 3 stages").args
    assert len(names) == len(cats) == len(prompts) == 3
    assert cats == ["Food - 3 stages"] * 3
    assert names[0] == "Spookies"


def test_category_is_appended_not_inserted(nodes_mod):
    # ComfyUI restores widgets_values POSITIONALLY. `category` must come after
    # anything already on this node, or a saved workflow loads its pick onto
    # the wrong widget.
    schema = nodes_mod.SymbioticaOrderAssets.define_schema()
    assert [i.id for i in schema.inputs] == ["order", "category"]


def test_a_pick_with_no_assets_says_what_the_event_holds(nodes_mod):
    with pytest.raises(ValueError, match="Decoration, Food - 3 stages"):
        nodes_mod.SymbioticaOrderAssets.execute(order=MINI_1,
                                                category="Wallpaper")


def test_an_empty_event_is_still_its_own_error(nodes_mod):
    with pytest.raises(ValueError, match="no named assets"):
        nodes_mod.SymbioticaOrderAssets.execute(
            order={"feature": "Mini 9", "assets": []}, category="Decoration")


def _tensor(shade=0.5):
    import numpy as np
    import torch
    arr = np.full((8, 8, 3), shade, dtype=np.float32)
    return torch.from_numpy(arr)[None, ...]


def _book(proj, rules=None, **types):
    d = proj / "prompts"
    d.mkdir(parents=True, exist_ok=True)
    for stem, text in types.items():
        (d / f"{stem}.md").write_text(text)
    if rules:
        r = d / "_rules"
        r.mkdir(exist_ok=True)
        for stem, text in rules.items():
            (r / f"{stem}.md").write_text(text)
    return str(proj)


def test_save_render_writes_files_named_after_the_assets(nodes_mod, tmp_path):
    proj = _book(tmp_path / "bakery", rules={"01-light": "LIGHT"},
                 **{"Decoration": "DECO"})
    out = nodes_mod.SymbioticaSaveRender.execute(
        images=[_tensor(0.2), _tensor(0.8)],
        asset_names=["Ghost Bakery Queue", "Witch Cat Tea Parlor"],
        categories=["Decoration", "Decoration"],
        system_prompts=["LIGHT\n\nDECO"] * 2,
        reference_names=["Woodland.png"] * 2,
        seed=[7], subfolder=["renders"], project_path=[proj])
    files, shas = out.args
    assert len(files) == 2
    assert files[0].startswith("ghost-bakery-queue-")
    assert files[0].endswith("-01.png")
    assert shas[0] == shas[1], "same prompt, same hash"


def test_save_render_embeds_provenance_in_the_png(nodes_mod, tmp_path):
    # A record only in the log is lost the moment an image leaves the project.
    from PIL import Image
    proj = _book(tmp_path / "bakery", rules={"01-light": "LIGHT"},
                 **{"Decoration": "DECO"})
    out = nodes_mod.SymbioticaSaveRender.execute(
        images=[_tensor()], asset_names=["Ghost"], categories=["Decoration"],
        system_prompts=["LIGHT\n\nDECO"], reference_names=["Woodland.png"],
        seed=[3], subfolder=["renders"], project_path=[proj])
    path = tmp_path / "output" / "renders" / out.args[0][0]
    with Image.open(path) as im:
        rec = json.loads(im.text["symbiotica_provenance"])
    assert rec["asset"] == "Ghost" and rec["seed"] == 3
    assert rec["reference"] == "Woodland.png"
    assert [b["block"] for b in rec["blocks"]] == ["_rules/01-light.md",
                                                   "Decoration.md"]


def test_save_render_appends_one_log_line_per_image(nodes_mod, tmp_path):
    from pipeline.provenance import read_records
    proj = _book(tmp_path / "bakery", **{"Decoration": "DECO"})
    nodes_mod.SymbioticaSaveRender.execute(
        images=[_tensor(), _tensor()], asset_names=["A", "B"],
        categories=["Decoration"] * 2, system_prompts=["DECO"] * 2,
        subfolder=["renders"], project_path=[proj])
    assert [r["asset"] for r in read_records(proj)] == ["A", "B"]


def test_save_render_survives_a_short_label_list(nodes_mod, tmp_path):
    # A mis-wired label list is a wiring mistake; losing the render to it is a
    # worse outcome than a fallback name.
    proj = _book(tmp_path / "bakery", **{"Decoration": "DECO"})
    out = nodes_mod.SymbioticaSaveRender.execute(
        images=[_tensor(), _tensor()], asset_names=["OnlyOne"],
        categories=["Decoration"], system_prompts=["DECO"],
        subfolder=["renders"], project_path=[proj])
    assert len(out.args[0]) == 2
    assert out.args[0][1].startswith("render-2-")


def test_save_render_refuses_an_empty_batch(nodes_mod, tmp_path):
    with pytest.raises(ValueError, match="nothing to save"):
        nodes_mod.SymbioticaSaveRender.execute(
            images=[], asset_names=[], categories=[], system_prompts=[])


def test_order_assets_emits_a_save_path_per_asset(nodes_mod):
    order = {**MINI_1, "month": "October", "eventName": "Ghostly Goodies"}
    out = nodes_mod.SymbioticaOrderAssets.execute(order=order,
                                                  category="Food - 3 stages")
    names, cats, prompts, paths = out.args
    assert len(paths) == len(names) == 3
    assert paths[0] == ("October/Mini 1 — Ghostly Goodies/"
                        "Food - 3 stages/Spookies")


def test_save_paths_is_the_last_output_slot(nodes_mod):
    # Links address an output by index; inserting would re-point saved graphs.
    schema = nodes_mod.SymbioticaOrderAssets.define_schema()
    assert [o.display_name for o in schema.outputs] == [
        "asset_names", "categories", "client_prompts", "save_paths"]
