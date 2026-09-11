# ABOUTME: Tests workflow recipes — nodes titled `recipe:<key>` take their values
# ABOUTME: from a recipe file, and one template writes one workflow per category.
import copy
import json
import os
import uuid

import pytest

from _recipes import (RecipeError, apply_recipe, generate, promote_string_input,
                      recipe_slots, workflow_name)

SG_ID = "4ea6e827-ec92-4fdc-8d87-a021f5d6fb0a"


def string_node(node_id, title, text, link_out=None):
    return {
        "id": node_id, "type": "String", "pos": [0, 0], "size": [400, 100],
        "flags": {}, "order": 0, "mode": 0, "title": title,
        "inputs": [{"name": "String", "type": "STRING", "widget": {"name": "String"}, "link": None}],
        "outputs": [{"name": "STRING", "type": "STRING", "links": [link_out] if link_out else []}],
        "properties": {"Node name for S&R": "String"},
        "widgets_values": [text],
    }


def template():
    """A root graph with one slot of each kind, plus a subgraph instance."""
    return {
        "id": "79ab9a5b-f4bc-44e0-91eb-f83753cc7e99", "revision": 3,
        "last_node_id": 60, "last_link_id": 900,
        "nodes": [
            {"id": 10, "type": "LoadImage", "title": "recipe:control_image", "mode": 0,
             "inputs": [{"name": "image", "type": "COMBO", "widget": {"name": "image"}, "link": None}],
             "outputs": [], "widgets_values": ["old.png", "image"]},
            {"id": 11, "type": "NSQwenResolution", "title": "recipe:render_aspect", "mode": 0,
             "inputs": [{"name": "aspect", "type": "COMBO", "widget": {"name": "aspect"}, "link": None}],
             "outputs": [], "widgets_values": ["1:1 (Square)"]},
            {"id": 12, "type": "SplitTiles", "title": "recipe:grid", "mode": 0,
             "inputs": [{"name": "columns", "type": "INT", "widget": {"name": "columns"}, "link": None},
                        {"name": "rows", "type": "INT", "widget": {"name": "rows"}, "link": None}],
             "outputs": [], "widgets_values": [2, 3]},
            {"id": 13, "type": "ImageFlip", "title": "recipe:pre_flip?", "mode": 4,
             "inputs": [{"name": "flip_method", "type": "COMBO", "widget": {"name": "flip_method"}, "link": None}],
             "outputs": [], "widgets_values": ["y-axis: horizontally"]},
            {"id": 14, "type": SG_ID, "title": "recipe:render", "mode": 0,
             "inputs": [{"name": "text", "type": "STRING", "link": None},
                        {"name": "seed", "type": "INT", "widget": {"name": "seed"}, "link": None},
                        {"name": "lora_name", "type": "COMBO", "widget": {"name": "lora_name"}, "link": None},
                        {"name": "strength_model", "type": "FLOAT", "widget": {"name": "strength_model"}, "link": None}],
             "outputs": [], "widgets_values": [7, "old.safetensors", 0.5]},
            {"id": 15, "type": "String", "title": "User Custom Request", "mode": 0,
             "inputs": [{"name": "String", "type": "STRING", "widget": {"name": "String"}, "link": None}],
             "outputs": [], "widgets_values": ["leave me"]},
        ],
        "links": [], "groups": [],
        "definitions": {"subgraphs": [{"id": SG_ID, "name": "render", "inputs": [], "outputs": [],
                                       "nodes": [], "links": [], "state": {"lastLinkId": 5}}]},
        "extra": {}, "version": 0.4,
    }


def recipe():
    return {
        "workflow_prefix": "dev-imperia-bakery-",
        "game": {"render": {"lora_name": "bakery.safetensors"}},
        "categories": {
            "appliance1x1": {"control_image": "controlnet/bakery/appliance1x1.png",
                             "render_aspect": "1:1 (Square)", "grid": [2, 1], "pre_flip": False},
            "appliance1x2": {"control_image": "controlnet/bakery/appliance1x2.png",
                             "render_aspect": "9:16 (Widescreen Portrait)", "grid": [2, 1], "pre_flip": True},
        },
    }


def by_id(workflow, node_id):
    return next(n for n in workflow["nodes"] if n["id"] == node_id)


class TestRecipeSlots:
    def test_every_recipe_titled_root_node_is_a_slot_keyed_without_the_prefix(self):
        slots = recipe_slots(template())
        assert set(slots) == {"control_image", "render_aspect", "grid", "pre_flip", "render"}

    def test_a_toggle_slot_drops_its_question_mark_from_the_key(self):
        slots = recipe_slots(template())
        assert [n["id"] for n in slots["pre_flip"]] == [13]

    def test_two_nodes_may_share_a_key(self):
        wf = template()
        wf["nodes"].append({**copy.deepcopy(by_id(wf, 11)), "id": 16})
        assert [n["id"] for n in recipe_slots(wf)["render_aspect"]] == [11, 16]

    def test_nodes_inside_subgraph_definitions_are_not_slots(self):
        wf = template()
        wf["definitions"]["subgraphs"][0]["nodes"].append(
            {"id": 1, "type": "String", "title": "recipe:hidden", "widgets_values": ["x"]})
        assert "hidden" not in recipe_slots(wf)


class TestApplyRecipe:
    def test_a_scalar_sets_the_first_widget_and_leaves_the_rest(self):
        wf = template()
        apply_recipe(wf, {"control_image": "new.png"})
        assert by_id(wf, 10)["widgets_values"] == ["new.png", "image"]

    def test_a_list_replaces_every_widget(self):
        wf = template()
        apply_recipe(wf, {"grid": [2, 1]})
        assert by_id(wf, 12)["widgets_values"] == [2, 1]

    def test_a_list_of_the_wrong_length_is_refused(self):
        with pytest.raises(RecipeError, match="grid"):
            apply_recipe(template(), {"grid": [2]})

    def test_a_dict_sets_promoted_widgets_by_name(self):
        wf = template()
        apply_recipe(wf, {"render": {"lora_name": "bakery.safetensors", "strength_model": 0.9}})
        assert by_id(wf, 14)["widgets_values"] == [7, "bakery.safetensors", 0.9]

    def test_a_dict_naming_a_widget_the_node_lacks_is_refused(self):
        with pytest.raises(RecipeError, match="steps"):
            apply_recipe(template(), {"render": {"steps": 8}})

    def test_a_toggle_sets_the_mode_true_on_false_bypassed(self):
        wf = template()
        apply_recipe(wf, {"pre_flip": True})
        assert by_id(wf, 13)["mode"] == 0
        apply_recipe(wf, {"pre_flip": False})
        assert by_id(wf, 13)["mode"] == 4

    def test_a_toggle_given_a_non_boolean_is_refused(self):
        with pytest.raises(RecipeError, match="pre_flip"):
            apply_recipe(template(), {"pre_flip": "yes"})

    def test_a_key_no_node_carries_is_refused_so_a_typo_cannot_render_the_template_value(self):
        with pytest.raises(RecipeError, match="controll_image"):
            apply_recipe(template(), {"controll_image": "x.png"})

    def test_nodes_without_a_recipe_title_are_untouched(self):
        wf = template()
        apply_recipe(wf, {"control_image": "new.png"})
        assert by_id(wf, 15)["widgets_values"] == ["leave me"]

    def test_reports_the_slots_the_values_left_at_their_template_value(self):
        report = apply_recipe(template(), {"control_image": "new.png"})
        assert report["applied"] == ["control_image"]
        assert report["template"] == ["grid", "pre_flip", "render", "render_aspect"]


class TestGenerate:
    def test_category_values_layer_over_game_values(self):
        wf, _ = generate(template(), recipe(), "appliance1x2")
        assert by_id(wf, 10)["widgets_values"][0] == "controlnet/bakery/appliance1x2.png"
        assert by_id(wf, 14)["widgets_values"][1] == "bakery.safetensors"
        assert by_id(wf, 13)["mode"] == 0

    def test_the_template_is_not_modified(self):
        tpl = template()
        before = copy.deepcopy(tpl)
        generate(tpl, recipe(), "appliance1x1")
        assert tpl == before

    def test_a_category_value_overrides_a_game_value_for_the_same_key(self):
        r = recipe()
        r["game"]["control_image"] = "game.png"
        wf, _ = generate(template(), r, "appliance1x1")
        assert by_id(wf, 10)["widgets_values"][0] == "controlnet/bakery/appliance1x1.png"

    def test_an_unknown_category_is_refused(self):
        with pytest.raises(RecipeError, match="chair"):
            generate(template(), recipe(), "chair")

    def test_each_generated_workflow_gets_its_own_stable_id_and_a_fresh_revision(self):
        a, _ = generate(template(), recipe(), "appliance1x1")
        b, _ = generate(template(), recipe(), "appliance1x2")
        again, _ = generate(template(), recipe(), "appliance1x1")
        assert a["id"] != template()["id"]
        assert a["id"] != b["id"]
        assert a["id"] == again["id"]
        assert a["revision"] == 0

    def test_the_workflow_name_is_the_prefix_plus_the_category(self):
        assert workflow_name(recipe(), "appliance1x2") == "dev-imperia-bakery-appliance1x2"


def subgraph_with_inner_string():
    """A subgraph whose inner String feeds a JoinStrings, the way the bakery
    preamble does; promoting it turns that link into a subgraph input."""
    return {
        "id": SG_ID, "name": "render", "version": 1,
        "state": {"lastNodeId": 3, "lastLinkId": 5},
        "inputNode": {"id": -10, "bounding": [-100, 0, 100, 100]},
        "outputNode": {"id": -20, "bounding": [500, 0, 100, 100]},
        "inputs": [{"id": "aaa", "name": "text", "type": "STRING", "linkIds": [4], "pos": [0, 0]}],
        "outputs": [],
        "nodes": [
            {"id": 1, "type": "String", "title": "Image Model Preamble", "mode": 0, "pos": [0, 0],
             "inputs": [{"name": "String", "type": "STRING", "widget": {"name": "String"}, "link": None}],
             "outputs": [{"name": "STRING", "type": "STRING", "links": [5]}],
             "widgets_values": ["A single isometric sprite"]},
            {"id": 2, "type": "JoinStrings", "mode": 0, "pos": [200, 0],
             "inputs": [{"name": "string1", "type": "STRING", "link": 5},
                        {"name": "string2", "type": "STRING", "link": 4},
                        {"name": "delimiter", "type": "STRING", "widget": {"name": "delimiter"}, "link": None}],
             "outputs": [{"name": "STRING", "type": "STRING", "links": []}],
             "widgets_values": [" "]},
        ],
        "links": [
            {"id": 4, "origin_id": -10, "origin_slot": 0, "target_id": 2, "target_slot": 1, "type": "STRING"},
            {"id": 5, "origin_id": 1, "origin_slot": 0, "target_id": 2, "target_slot": 0, "type": "STRING"},
        ],
        "extra": {},
    }


def workflow_with_instance():
    return {
        "last_node_id": 30, "last_link_id": 100,
        "nodes": [
            {"id": 20, "type": "PreviewAny", "mode": 0, "pos": [0, 0], "inputs": [],
             "outputs": [{"name": "STRING", "type": "STRING", "links": [100]}], "widgets_values": []},
            {"id": 30, "type": SG_ID, "mode": 0, "pos": [300, 0],
             "inputs": [{"name": "text", "type": "STRING", "link": 100}],
             "outputs": [], "widgets_values": []},
        ],
        "links": [[100, 20, 0, 30, 0, "STRING"]],
        "groups": [],
        "definitions": {"subgraphs": [subgraph_with_inner_string()]},
    }


class TestPromoteStringInput:
    def test_the_inner_string_becomes_a_subgraph_input_fed_from_a_root_recipe_node(self):
        wf = workflow_with_instance()
        promote_string_input(wf, "render", 1, "preamble", "recipe:preamble", pos=[-500, 0])
        sg = wf["definitions"]["subgraphs"][0]
        # inner: the String node is gone, its link now originates at the input node
        assert [n["id"] for n in sg["nodes"]] == [2]
        assert [i["name"] for i in sg["inputs"]] == ["text", "preamble"]
        moved = next(l for l in sg["links"] if l["id"] == 5)
        assert (moved["origin_id"], moved["origin_slot"], moved["target_id"], moved["target_slot"]) == (-10, 1, 2, 0)
        assert sg["inputs"][1]["linkIds"] == [5]
        assert sg["inputs"][1]["type"] == "STRING"
        # root: a String node titled for the recipe, wired into the new instance slot
        root = next(n for n in wf["nodes"] if n.get("title") == "recipe:preamble")
        assert root["type"] == "String"
        assert root["widgets_values"] == ["A single isometric sprite"]
        assert root["pos"] == [-500, 0]
        instance = next(n for n in wf["nodes"] if n["id"] == 30)
        assert [i["name"] for i in instance["inputs"]] == ["text", "preamble"]
        link_id = instance["inputs"][1]["link"]
        assert [link_id, root["id"], 0, 30, 1, "STRING"] in wf["links"]
        assert root["outputs"][0]["links"] == [link_id]
        assert wf["last_node_id"] == root["id"] > 30
        assert wf["last_link_id"] == link_id > 100

    def test_the_new_slot_is_a_recipe_slot(self):
        wf = workflow_with_instance()
        promote_string_input(wf, "render", 1, "preamble", "recipe:preamble", pos=[0, 0])
        assert "preamble" in recipe_slots(wf)

    def test_refuses_a_subgraph_or_node_that_is_not_there(self):
        with pytest.raises(RecipeError, match="nope"):
            promote_string_input(workflow_with_instance(), "nope", 1, "p", "recipe:p", pos=[0, 0])
        with pytest.raises(RecipeError, match="99"):
            promote_string_input(workflow_with_instance(), "render", 99, "p", "recipe:p", pos=[0, 0])

    def test_refuses_an_inner_node_that_is_not_a_single_output_string_source(self):
        with pytest.raises(RecipeError, match="JoinStrings"):
            promote_string_input(workflow_with_instance(), "render", 2, "p", "recipe:p", pos=[0, 0])


from _recipes import generate_all, list_recipes, read_recipe


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


@pytest.fixture
def library(tmp_path):
    """A workflows dir holding the template in a folder, and a recipes dir
    holding one recipe that names it."""
    workflows = str(tmp_path / "workflows")
    recipes = str(tmp_path / "recipes")
    write_json(os.path.join(workflows, "recipe-test", "bakery-template.json"), template())
    write_json(os.path.join(recipes, "imperia-bakery.json"),
               {**recipe(), "template": "recipe-test/bakery-template.json"})
    return {"workflows": workflows, "recipes": recipes}


class TestRecipeLibrary:
    def test_lists_every_recipe_with_its_template_and_categories(self, library):
        assert list_recipes(library["recipes"]) == [
            {"name": "imperia-bakery", "template": "recipe-test/bakery-template.json",
             "categories": ["appliance1x1", "appliance1x2"]}]

    def test_a_missing_dir_lists_nothing(self, tmp_path):
        assert list_recipes(str(tmp_path / "nope")) == []

    def test_reads_one_by_name_and_none_when_absent(self, library):
        assert read_recipe(library["recipes"], "imperia-bakery")["workflow_prefix"] == "dev-imperia-bakery-"
        assert read_recipe(library["recipes"], "other") is None

    def test_a_name_cannot_walk_out_of_the_dir(self, library):
        with pytest.raises(RecipeError):
            read_recipe(library["recipes"], "../secrets")


class TestGenerateAll:
    def test_writes_one_workflow_per_category_next_to_the_template(self, library):
        r = read_recipe(library["recipes"], "imperia-bakery")
        report = generate_all(library["workflows"], r)
        paths = [w["path"] for w in report["written"]]
        assert paths == ["recipe-test/dev-imperia-bakery-appliance1x1.json",
                         "recipe-test/dev-imperia-bakery-appliance1x2.json"]
        wf = json.load(open(os.path.join(library["workflows"], paths[1])))
        assert by_id(wf, 10)["widgets_values"][0] == "controlnet/bakery/appliance1x2.png"
        assert report["written"][1]["category"] == "appliance1x2"
        assert report["written"][1]["applied"] == ["control_image", "grid", "pre_flip", "render", "render_aspect"]

    def test_an_output_folder_in_the_recipe_wins_over_the_template_folder(self, library):
        r = {**read_recipe(library["recipes"], "imperia-bakery"), "output": "bakery/generated"}
        report = generate_all(library["workflows"], r)
        assert report["written"][0]["path"] == "bakery/generated/dev-imperia-bakery-appliance1x1.json"
        assert os.path.isfile(os.path.join(library["workflows"], report["written"][0]["path"]))

    def test_regenerating_overwrites_the_previous_file(self, library):
        r = read_recipe(library["recipes"], "imperia-bakery")
        generate_all(library["workflows"], r)
        r["categories"]["appliance1x1"]["control_image"] = "changed.png"
        generate_all(library["workflows"], r)
        wf = json.load(open(os.path.join(library["workflows"], "recipe-test/dev-imperia-bakery-appliance1x1.json")))
        assert by_id(wf, 10)["widgets_values"][0] == "changed.png"

    def test_a_recipe_without_a_template_is_refused(self, library):
        with pytest.raises(RecipeError, match="template"):
            generate_all(library["workflows"], recipe())

    def test_a_template_that_is_not_there_is_refused(self, library):
        r = {**recipe(), "template": "recipe-test/missing.json"}
        with pytest.raises(RecipeError, match="missing.json"):
            generate_all(library["workflows"], r)

    def test_a_template_or_output_path_cannot_walk_out_of_the_workflows_dir(self, library):
        with pytest.raises(RecipeError):
            generate_all(library["workflows"], {**recipe(), "template": "../recipes/imperia-bakery.json"})
        r = {**read_recipe(library["recipes"], "imperia-bakery"), "output": "../elsewhere"}
        with pytest.raises(RecipeError):
            generate_all(library["workflows"], r)

    def test_a_bad_category_value_fails_before_any_file_is_written(self, library):
        r = read_recipe(library["recipes"], "imperia-bakery")
        r["categories"]["appliance1x2"]["typo"] = 1
        with pytest.raises(RecipeError, match="typo"):
            generate_all(library["workflows"], r)
        assert not os.path.exists(os.path.join(library["workflows"], "recipe-test/dev-imperia-bakery-appliance1x1.json"))


from _recipes import new_recipe, read_template, template_slots, write_recipe


class TestTemplateSlots:
    def test_describes_every_slot_with_its_kind_and_template_value(self):
        slots = template_slots(template())
        by_key = {s["key"]: s for s in slots}
        assert [s["key"] for s in slots] == ["control_image", "grid", "pre_flip", "render", "render_aspect"]
        assert by_key["control_image"] == {"key": "control_image", "kind": "scalar", "default": "old.png", "widgets": 2}
        assert by_key["grid"] == {"key": "grid", "kind": "scalar", "default": 2, "widgets": 2}
        assert by_key["pre_flip"] == {"key": "pre_flip", "kind": "toggle", "default": False, "widgets": 1}
        assert by_key["render"] == {"key": "render", "kind": "dict",
                                    "default": {"seed": 7, "lora_name": "old.safetensors", "strength_model": 0.5},
                                    "widgets": 3}

    def test_rows_come_in_key_order_so_the_table_does_not_shuffle_between_opens(self):
        wf = template()
        wf["nodes"].reverse()
        assert [s["key"] for s in template_slots(wf)] == ["control_image", "grid", "pre_flip", "render", "render_aspect"]

    def test_a_wired_promoted_input_is_not_offered_as_a_dict_default(self):
        wf = template()
        by_id(wf, 14)["inputs"][1]["link"] = 4400   # seed comes from a Seed node
        render = next(s for s in template_slots(wf) if s["key"] == "render")
        assert render["default"] == {"lora_name": "old.safetensors", "strength_model": 0.5}

    def test_a_key_shared_by_two_nodes_is_one_slot(self):
        wf = template()
        wf["nodes"].append({**copy.deepcopy(by_id(wf, 11)), "id": 16})
        assert [s["key"] for s in template_slots(wf)].count("render_aspect") == 1


class TestReadTemplate:
    def test_reads_by_path_relative_to_the_workflows_dir_with_or_without_the_workflows_prefix(self, library):
        a = read_template(library["workflows"], "recipe-test/bakery-template.json")
        b = read_template(library["workflows"], "workflows/recipe-test/bakery-template.json")
        assert a == b == template()

    def test_a_missing_template_is_refused_by_name(self, library):
        with pytest.raises(RecipeError, match="nope.json"):
            read_template(library["workflows"], "recipe-test/nope.json")


class TestWriteRecipe:
    def test_writes_the_file_the_name_reads_back(self, library):
        r = {**recipe(), "template": "recipe-test/bakery-template.json"}
        r["categories"]["chair"] = {"control_image": "chair.png"}
        write_recipe(library["recipes"], "imperia-bakery", r)
        assert read_recipe(library["recipes"], "imperia-bakery")["categories"]["chair"] == {"control_image": "chair.png"}

    def test_creates_the_dir_and_keeps_unicode_readable(self, tmp_path):
        d = str(tmp_path / "recipes")
        write_recipe(d, "x", {"template": "t.json", "categories": {"a": {"preamble": "QE 2 — Coven"}}})
        assert "Coven" in open(os.path.join(d, "x.json"), encoding="utf-8").read()
        assert "\\u2014" not in open(os.path.join(d, "x.json"), encoding="utf-8").read()

    def test_refuses_a_recipe_that_is_not_a_table(self, tmp_path):
        with pytest.raises(RecipeError, match="categories"):
            write_recipe(str(tmp_path), "x", {"template": "t.json"})
        with pytest.raises(RecipeError, match="template"):
            write_recipe(str(tmp_path), "x", {"categories": {}})


class TestNewRecipe:
    def test_a_fresh_recipe_names_the_template_and_starts_the_game_column_from_its_values(self, library):
        r = new_recipe(library["workflows"], "workflows/recipe-test/bakery-template.json")
        assert r == {"template": "recipe-test/bakery-template.json", "output": "recipe-test",
                     "workflow_prefix": "",
                     "game": {"control_image": "old.png", "grid": 2, "pre_flip": False,
                              "render": {"seed": 7, "lora_name": "old.safetensors", "strength_model": 0.5},
                              "render_aspect": "1:1 (Square)"},
                     "categories": {}}

    def test_a_template_at_the_workflows_root_has_no_output_folder(self, library):
        write_json(os.path.join(library["workflows"], "root-template.json"), template())
        r = new_recipe(library["workflows"], "root-template.json")
        assert r["template"] == "root-template.json"
        assert "output" not in r
