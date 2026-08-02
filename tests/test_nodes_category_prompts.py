# ABOUTME: Node-face tests for Category Prompts — whole-list input, the project
# ABOUTME: lookup order, and a fingerprint that only reads widget values.
import importlib
import os
import sys
import types

import pytest

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


def _project(tmp_path, **files):
    proj = tmp_path / "bakery"
    (proj / "prompts").mkdir(parents=True)
    (proj / "orders").mkdir()
    for stem, text in files.items():
        (proj / "prompts" / f"{stem}.md").write_text(text)
    return proj


def test_declares_whole_list_input(nodes_mod):
    # Without this the engine maps execute per category: each file would be read
    # once per sheet, and missing prompts would raise one at a time.
    schema = nodes_mod.SymbioticaCategoryPrompts.define_schema()
    assert schema.is_input_list is True
    assert [o.display_name for o in schema.outputs] == [
        "system_prompts", "sheet_system_prompts"]


def test_one_prompt_per_sheet_in_order(nodes_mod, tmp_path):
    proj = _project(tmp_path, **{"Decoration": "DECO", "Food - 3 stages": "FOOD"})
    out = nodes_mod.SymbioticaCategoryPrompts.execute(
        sheet_categories=["Decoration", "Food - 3 stages", "Food - 3 stages"],
        project_path=[str(proj)])
    # slot 0 = one per TYPE (for reading), slot 1 = one per SHEET (for the wire)
    assert out.args[0] == ["DECO", "FOOD"]
    assert out.args[1] == ["DECO", "FOOD", "FOOD"]


def test_project_comes_from_the_order_wire(nodes_mod, tmp_path):
    proj = _project(tmp_path, **{"Decoration": "DECO"})
    out = nodes_mod.SymbioticaCategoryPrompts.execute(
        sheet_categories=["Decoration"], project_path=[""],
        order=[{"project_path": str(proj)}])
    assert out.args[0] == ["DECO"]


def test_reference_order_falls_back_to_the_refs_root(nodes_mod, tmp_path):
    # A Reference Browser order carries no project_path at all — walk up from
    # refsRoot to the folder holding orders/.
    proj = _project(tmp_path, **{"Decoration": "DECO"})
    refs = proj / "reference-assets"
    refs.mkdir()
    out = nodes_mod.SymbioticaCategoryPrompts.execute(
        sheet_categories=["Decoration"], project_path=[""],
        order=[{"refsRoot": str(refs)}])
    assert out.args[0] == ["DECO"]


def test_no_project_says_so_rather_than_naming_a_junk_path(nodes_mod):
    with pytest.raises(ValueError, match="names no project folder"):
        nodes_mod.SymbioticaCategoryPrompts.execute(
            sheet_categories=["Decoration"], project_path=[""], order=[{}])


def test_missing_prompt_names_the_file_to_create(nodes_mod, tmp_path):
    proj = _project(tmp_path, **{"Decoration": "DECO"})
    with pytest.raises(Exception, match="Signage.md"):
        nodes_mod.SymbioticaCategoryPrompts.execute(
            sheet_categories=["Decoration", "Signage"],
            project_path=[str(proj)])


def test_no_sheets_is_a_wiring_error(nodes_mod, tmp_path):
    proj = _project(tmp_path, **{"Decoration": "DECO"})
    with pytest.raises(ValueError, match="sheet_categories"):
        nodes_mod.SymbioticaCategoryPrompts.execute(
            sheet_categories=[], project_path=[str(proj)])


def test_fingerprint_changes_when_a_prompt_is_edited(nodes_mod, tmp_path):
    proj = _project(tmp_path, **{"Decoration": "A"})
    fp = nodes_mod.SymbioticaCategoryPrompts.fingerprint_inputs
    before = fp(project_path=[str(proj)])
    f = proj / "prompts" / "decoration.md"
    f.write_text("B")
    os.utime(f, (10 ** 9, 10 ** 9))
    assert fp(project_path=[str(proj)]) != before


def test_fingerprint_changes_when_a_missing_prompt_is_created(nodes_mod,
                                                              tmp_path):
    proj = _project(tmp_path, **{"Decoration": "A"})
    fp = nodes_mod.SymbioticaCategoryPrompts.fingerprint_inputs
    before = fp(project_path=[str(proj)])
    (proj / "prompts" / "Signage.md").write_text("S")
    assert fp(project_path=[str(proj)]) != before


def test_fingerprint_survives_link_fed_inputs_being_none(nodes_mod, tmp_path):
    # ComfyUI passes every LINKED input as None here. It must not raise: a raise
    # sets is_changed to NaN, which folds into every descendant's cache key and
    # re-bills the LLM and Gemini on every queue press.
    proj = _project(tmp_path, **{"Decoration": "A"})
    fp = nodes_mod.SymbioticaCategoryPrompts.fingerprint_inputs
    assert isinstance(fp(sheet_categories=None, project_path=[str(proj)],
                         order=None), str)


def test_a_paginated_type_is_listed_once_but_wired_per_sheet(nodes_mod, tmp_path):
    # His Mini 1: 5 decoration sheets + 3 food sheets, two documents. The panel
    # should read as two, while the render still gets one per sheet.
    proj = _project(tmp_path, **{"Decoration": "DECO", "Food - 3 stages": "FOOD"})
    cats = ["Decoration"] * 5 + ["Food - 3 stages"] * 3
    out = nodes_mod.SymbioticaCategoryPrompts.execute(
        sheet_categories=cats, project_path=[str(proj)])
    assert out.args[0] == ["DECO", "FOOD"]
    assert len(out.args[1]) == 8


def test_types_sharing_one_document_collapse_in_the_reading_list(nodes_mod,
                                                                 tmp_path):
    # Appliances currently runs a byte-identical copy of the food prompt. Two
    # types, one document — the reading list says one.
    proj = _project(tmp_path, **{"Food - 3 stages": "SAME", "Appliance": "SAME"})
    out = nodes_mod.SymbioticaCategoryPrompts.execute(
        sheet_categories=["Food - 3 stages", "Appliance"],
        project_path=[str(proj)])
    assert out.args[0] == ["SAME"]
    assert out.args[1] == ["SAME", "SAME"]


def test_fingerprint_sees_an_edited_shared_rule(nodes_mod, tmp_path):
    # Listing prompts/ one level deep would miss this entirely: the queue would
    # reuse the cached prompt and render from the old lighting rule while the
    # new one sat on disk — which reads as "my edit did nothing".
    proj = _project(tmp_path, **{"Decoration": "D"})
    rules = proj / "prompts" / "_rules"
    rules.mkdir()
    (rules / "01-lighting.md").write_text("SOFT LIGHT")
    fp = nodes_mod.SymbioticaCategoryPrompts.fingerprint_inputs
    before = fp(project_path=[str(proj)])
    f = rules / "01-lighting.md"
    f.write_text("HARD RIM LIGHT")
    os.utime(f, (10 ** 9, 10 ** 9))
    assert fp(project_path=[str(proj)]) != before


def test_fingerprint_sees_a_new_shared_rule(nodes_mod, tmp_path):
    proj = _project(tmp_path, **{"Decoration": "D"})
    rules = proj / "prompts" / "_rules"
    rules.mkdir()
    (rules / "01-lighting.md").write_text("LIGHT")
    fp = nodes_mod.SymbioticaCategoryPrompts.fingerprint_inputs
    before = fp(project_path=[str(proj)])
    (rules / "02-negatives.md").write_text("NO BLUR")
    assert fp(project_path=[str(proj)]) != before


def test_composed_prompt_reaches_the_node_output(nodes_mod, tmp_path):
    proj = _project(tmp_path, **{"Decoration": "DECO", "Food - 3 stages": "FOOD"})
    rules = proj / "prompts" / "_rules"
    rules.mkdir()
    (rules / "01-lighting.md").write_text("LIGHT")
    out = nodes_mod.SymbioticaCategoryPrompts.execute(
        sheet_categories=["Decoration", "Food - 3 stages"],
        project_path=[str(proj)])
    assert out.args[1] == ["LIGHT\n\nDECO", "LIGHT\n\nFOOD"]
