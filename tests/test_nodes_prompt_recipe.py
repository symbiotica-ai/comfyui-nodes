# ABOUTME: Prompt Recipe — composes the two documents from the book at picked
# ABOUTME: versions, and takes project + category off a focused order wire.
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


def make_book(tmp_path):
    project = tmp_path / "project"
    rules = project / "prompts" / "_rules"
    image = project / "prompts" / "_image"
    rules.mkdir(parents=True)
    image.mkdir(parents=True)
    (rules / "01-game.md").write_text("GAME RULES\n")
    (rules / "02-inputs.md").write_text("INPUTS\n")
    (image / "01-image-model.md").write_text("IMAGE RULES\n")
    (project / "prompts" / "Decoration.md").write_text("DECO BLOCK\n")
    return project


def test_composes_both_documents(nodes_mod, tmp_path):
    project = make_book(tmp_path)
    out = nodes_mod.SymbioticaPromptRecipe.execute(
        project_path=str(project), category="Decoration")
    system_prompt, image_prompt = out.args
    assert "GAME RULES" in system_prompt
    assert system_prompt.rstrip().endswith("DECO BLOCK")
    assert "IMAGE RULES" in image_prompt


def test_a_focused_order_supplies_project_and_category(nodes_mod, tmp_path):
    """One wire from Asset Focus replaces the project_path and category
    wires: the narrowed order names both."""
    project = make_book(tmp_path)
    order = {"project_path": str(project),
             "assets": [{"assetName": "Bunting", "category": "Decoration"}]}
    out = nodes_mod.SymbioticaPromptRecipe.execute(order=order)
    system_prompt, _image = out.args
    assert system_prompt.rstrip().endswith("DECO BLOCK")


def test_an_order_with_several_types_is_refused(nodes_mod, tmp_path):
    """One prompt composes ONE type; picking a type silently would compose
    the wrong book for half the assets."""
    project = make_book(tmp_path)
    order = {"project_path": str(project),
             "assets": [{"assetName": "A", "category": "Decoration"},
                        {"assetName": "B", "category": "Food - 3 stages"}]}
    with pytest.raises(ValueError, match="several types"):
        nodes_mod.SymbioticaPromptRecipe.execute(order=order)


def test_wired_widgets_still_beat_the_order(nodes_mod, tmp_path):
    """Explicit wins: a typed category composes that type even when the
    order names another."""
    project = make_book(tmp_path)
    (tmp_path / "project" / "prompts" / "Food - 3 stages.md").write_text(
        "FOOD BLOCK\n")
    order = {"project_path": str(project),
             "assets": [{"assetName": "A", "category": "Decoration"}]}
    out = nodes_mod.SymbioticaPromptRecipe.execute(
        order=order, category="Food - 3 stages")
    assert out.args[0].rstrip().endswith("FOOD BLOCK")


def test_the_order_input_is_appended_and_optional(nodes_mod):
    """Widgets restore positionally in saved graphs, so the new input goes
    on the end; and a Recipe with no order must keep working from widgets."""
    schema = nodes_mod.SymbioticaPromptRecipe.GET_SCHEMA()
    assert schema.inputs[-1].id == "order"
    assert schema.inputs[-1].optional is True
