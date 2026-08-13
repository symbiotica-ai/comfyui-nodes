# ABOUTME: Prompt Recipe — serves a saved preset, one prompt block per output,
# ABOUTME: so switching category switches every prompt it needs at once.
import importlib
import json
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


def make_book(tmp_path, slots=None, name="Decoration"):
    project = tmp_path / "project"
    book = project / "prompts"
    (book / "_rules").mkdir(parents=True)
    (book / "_image").mkdir(parents=True)
    (book / "_flip").mkdir(parents=True)
    (book / "_recipes").mkdir(parents=True)
    (book / "_rules" / "01-llm-prompt.md").write_text(
        "ARCHITECT\n\n<!-- version: tight -->\n\nARCHITECT TIGHT\n")
    (book / "_image" / "01-image-model.md").write_text("IMAGE RULES\n")
    (book / "_flip" / "01-flip.md").write_text("MIRROR RULES\n")
    if slots is None:
        slots = [{"block": "_rules/01-llm-prompt.md", "version": ""},
                 {"block": "_image/01-image-model.md", "version": ""},
                 {"block": "_flip/01-flip.md", "version": ""}]
    (book / "_recipes" / f"{name}.json").write_text(
        json.dumps({"slots": slots}))
    return project


def test_one_recipe_serves_every_block_it_names(nodes_mod, tmp_path):
    project = make_book(tmp_path)
    out = nodes_mod.SymbioticaPromptRecipe.execute(
        project_path=str(project), recipe="Decoration", slots=3)
    assert out.args[0].strip() == "ARCHITECT"
    assert out.args[1].strip() == "IMAGE RULES"
    assert out.args[2].strip() == "MIRROR RULES"


def test_outputs_past_the_slot_count_are_empty(nodes_mod, tmp_path):
    """The schema is fixed at six; `slots` is what says how many of them this
    recipe actually fills, so a two-prompt type leaves four empty wires."""
    project = make_book(tmp_path)
    out = nodes_mod.SymbioticaPromptRecipe.execute(
        project_path=str(project), recipe="Decoration", slots=2)
    assert out.args[1].strip() == "IMAGE RULES"
    assert out.args[2] == ""
    assert len(out.args) == nodes_mod.SymbioticaPromptRecipe.MAX_SLOTS


def test_a_slot_can_pin_a_version(nodes_mod, tmp_path):
    project = make_book(tmp_path, slots=[
        {"block": "_rules/01-llm-prompt.md", "version": "tight"}])
    out = nodes_mod.SymbioticaPromptRecipe.execute(
        project_path=str(project), recipe="Decoration", slots=1)
    assert out.args[0].strip() == "ARCHITECT TIGHT"


def test_the_order_wire_supplies_the_project(nodes_mod, tmp_path):
    project = make_book(tmp_path)
    order = {"project_path": str(project),
             "assets": [{"assetName": "Bunting", "category": "Decoration"}]}
    out = nodes_mod.SymbioticaPromptRecipe.execute(order=order,
                                                   recipe="Decoration")
    assert out.args[0].strip() == "ARCHITECT"


def test_no_recipe_picked_is_refused(nodes_mod, tmp_path):
    """Serving nothing silently would send an empty system prompt to a model
    that then bills for a useless render."""
    project = make_book(tmp_path)
    with pytest.raises(ValueError, match="no recipe picked"):
        nodes_mod.SymbioticaPromptRecipe.execute(project_path=str(project))


def test_a_recipe_that_is_not_on_disk_is_refused(nodes_mod, tmp_path):
    project = make_book(tmp_path)
    with pytest.raises(ValueError, match="names no blocks"):
        nodes_mod.SymbioticaPromptRecipe.execute(
            project_path=str(project), recipe="Nope")


def test_the_orders_category_beats_a_pinned_recipe(nodes_mod, tmp_path):
    """"still not fucking changing when i select a category in Asset focus" —
    a recipe pinned to Appliance kept serving Appliance prompts under a Food
    asset. With one category on the wire and a recipe saved under that name,
    the wire wins; picking the asset is the whole gesture."""
    project = make_book(tmp_path, name="Food - 3 stages")
    (project / "prompts" / "_recipes" / "Appliance.json").write_text(
        json.dumps({"slots": [{"block": "_image/01-image-model.md",
                               "version": ""}]}))
    order = {"project_path": str(project),
             "assets": [{"assetName": "Bat Croissants",
                         "category": "Food - 3 stages"}]}
    out = nodes_mod.SymbioticaPromptRecipe.execute(
        order=order, recipe="Appliance", slots=3)
    assert out.args[0].strip() == "ARCHITECT"      # the Food recipe's slot 1
    assert out.args[2].strip() == "MIRROR RULES"


def test_a_wired_category_beats_the_whole_events_categories(nodes_mod,
                                                           tmp_path):
    """Wiring Asset Focus's `event_order` hands over the WHOLE month, every
    category in it — ambiguous, so the node fell back to the pinned name and
    served Appliance prompts under a Food asset. Asset Focus's `category`
    output says which asset is picked; wired here, it decides."""
    project = make_book(tmp_path, name="Food - 3 stages")
    (project / "prompts" / "_recipes" / "Appliance.json").write_text(
        json.dumps({"slots": [{"block": "_image/01-image-model.md",
                               "version": ""}]}))
    event = {"project_path": str(project),
             "assets": [{"assetName": "Oven", "category": "Appliance"},
                        {"assetName": "Dark Depths Brew",
                         "category": "Food - 3 stages"},
                        {"assetName": "Bunting", "category": "Decoration"}]}
    out = nodes_mod.SymbioticaPromptRecipe.execute(
        order=event, category="Food - 3 stages", recipe="Appliance", slots=3)
    assert out.args[0].strip() == "ARCHITECT"
    assert out.args[2].strip() == "MIRROR RULES"


def test_a_wired_category_arrives_as_a_list(nodes_mod, tmp_path):
    """Asset Focus's `category` is a LIST output — one entry per focused asset
    — so the value lands here wrapped, exactly as `_one` unwraps elsewhere."""
    project = make_book(tmp_path, name="Food - 3 stages")
    out = nodes_mod.SymbioticaPromptRecipe.execute(
        project_path=str(project), category=["Food - 3 stages"], slots=1)
    assert out.args[0].strip() == "ARCHITECT"


def test_a_wired_category_changes_the_change_check(nodes_mod, tmp_path):
    project = make_book(tmp_path, name="Food - 3 stages")
    r = nodes_mod.SymbioticaPromptRecipe
    assert (r.fingerprint_inputs(project_path=str(project), category="Food - 3 stages")
            != r.fingerprint_inputs(project_path=str(project), category="Appliance"))


def test_a_pinned_recipe_answers_for_a_category_the_book_has_none_for(
        nodes_mod, tmp_path):
    """Refusing to render because one category has no recipe yet would stop
    him mid-order; the pinned name is the fallback, not the ruler."""
    project = make_book(tmp_path, name="Appliance")
    order = {"project_path": str(project),
             "assets": [{"assetName": "Odd One", "category": "Wallpaper"}]}
    out = nodes_mod.SymbioticaPromptRecipe.execute(
        order=order, recipe="Appliance", slots=1)
    assert out.args[0].strip() == "ARCHITECT"


def test_follow_category_serves_the_recipe_named_after_the_asset(nodes_mod,
                                                                 tmp_path):
    """Picking a Food asset upstream must serve the Food recipe.

    "why arent the prompts changing when i select the food category?" — it is
    the point of the node that changing category is ONE move, and pinning the
    recipe by name made it two, silently serving the Appliance prompts under a
    Food asset.
    """
    project = make_book(tmp_path, name="Food - 3 stages")
    order = {"project_path": str(project),
             "assets": [{"assetName": "Bat Croissants",
                         "category": "Food - 3 stages"}]}
    out = nodes_mod.SymbioticaPromptRecipe.execute(
        order=order, recipe=nodes_mod.SymbioticaPromptRecipe.FOLLOW, slots=3)
    assert out.args[0].strip() == "ARCHITECT"
    assert out.args[2].strip() == "MIRROR RULES"


def test_follow_category_re_reads_when_the_category_changes(nodes_mod,
                                                            tmp_path):
    """The name comes off the wire, so the category must be in the change
    check — otherwise a switch of asset serves the previous category's cached
    prompts and nothing on the canvas says why."""
    project = make_book(tmp_path, name="Food - 3 stages")
    recipe = nodes_mod.SymbioticaPromptRecipe
    def fp(category):
        return recipe.fingerprint_inputs(
            recipe=recipe.FOLLOW, project_path=str(project),
            order={"project_path": str(project),
                   "assets": [{"assetName": "X", "category": category}]})
    assert fp("Food - 3 stages") != fp("Appliance")


def test_follow_category_on_a_wide_order_names_the_categories(nodes_mod,
                                                              tmp_path):
    """Guessing one of several would serve the wrong prompts under the right
    name, which is worse than refusing."""
    project = make_book(tmp_path, name="Food - 3 stages")
    order = {"project_path": str(project),
             "assets": [{"assetName": "A", "category": "Appliance"},
                        {"assetName": "B", "category": "Food - 3 stages"}]}
    with pytest.raises(ValueError, match="Appliance, Food - 3 stages"):
        nodes_mod.SymbioticaPromptRecipe.execute(
            order=order, recipe=nodes_mod.SymbioticaPromptRecipe.FOLLOW)


def test_follow_category_without_an_order_says_so(nodes_mod, tmp_path):
    project = make_book(tmp_path)
    with pytest.raises(ValueError, match="needs an order"):
        nodes_mod.SymbioticaPromptRecipe.execute(
            project_path=str(project),
            recipe=nodes_mod.SymbioticaPromptRecipe.FOLLOW)


def test_the_widgets_keep_their_order_and_the_wires_are_optional(nodes_mod):
    """Widgets restore POSITIONALLY in saved graphs, so the three of them stay
    first and in this order — his Recipe already came back once with
    `project_path = 1` because a list shifted. The wired-only inputs sit after
    them, and both are optional: a Recipe with no wires must still work."""
    schema = nodes_mod.SymbioticaPromptRecipe.GET_SCHEMA()
    ids = [i.id for i in schema.inputs]
    assert ids[:3] == ["recipe", "slots", "project_path"]
    assert set(ids[3:]) == {"order", "category"}
    for wire in ("order", "category"):
        assert next(i for i in schema.inputs if i.id == wire).optional is True
