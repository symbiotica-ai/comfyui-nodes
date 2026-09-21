# ABOUTME: Tests workflow recipes — nodes titled `recipe:<key>` take their values
# ABOUTME: from a project file, and one template writes one workflow per recipe.
import copy
import json
import os
import uuid

import pytest

from _recipes import (RecipeError, apply_recipe, generate, promote_string_input,
                      recipe_slots,
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


def project():
    return {
        "workflow_prefix": "dev-imperia-bakery-",
        "shared": {"render": {"lora_name": "bakery.safetensors"}},
        "recipes": {
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


# A node's widgets_values is positional and is regularly LONGER than the
# inputs the graph declares: ComfyUI draws widgets nothing declares (a seed's
# `control_after_generate`, a node's own DOM panel) and a saved workflow stores
# their values with no name. His whole project refused to generate on this.
def ksampler(widgets=None):
    return {"id": 13, "type": "KSampler", "mode": 0, "outputs": [],
            "color": "#323", "bgcolor": "#535",
            "inputs": [{"name": n, "type": "INT", "widget": {"name": n}, "link": None}
                       for n in ("seed", "steps", "cfg", "sampler_name", "scheduler", "denoise")],
            "widgets_values": widgets if widgets is not None
            else [2, "randomize", 20, 8, "euler", "simple", 1]}


def control_image():
    """Two declared inputs, one of them WIRED, and a DOM panel widget the
    graph never declares: three values behind two names."""
    return {"id": 21, "type": "SymbioticaControlImage", "mode": 0, "outputs": [],
            "color": "#323", "bgcolor": "#535", "title": None,
            "inputs": [{"name": "image", "type": "STRING", "widget": {"name": "image"}, "link": None},
                       {"name": "path", "type": "STRING", "widget": {"name": "path"}, "link": 17}],
            "widgets_values": ["old.png", "", ""]}


def painted(*nodes):
    return {"nodes": list(nodes), "links": [], "groups": [], "extra": {}, "version": 0.4}


class TestWidgetsBehindTheNames:
    def test_an_undeclared_widget_does_not_refuse_the_node(self):
        wf = painted(ksampler())
        apply_recipe(wf, {"KSampler": {
            "seed": 9, "control_after_generate": "fixed", "steps": 30,
            "cfg": 7, "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 0.8}},
            "purple")
        assert wf["nodes"][0]["widgets_values"] == [9, "fixed", 30, 7, "dpmpp_2m", "karras", 0.8]

    def test_a_wired_widget_holds_its_place_and_is_not_written(self):
        wf = painted(control_image())
        apply_recipe(wf, {"SymbioticaControlImage": {"image": "new.png", "images_panel": ""}},
                     "purple")
        # `path` is fed by a link: its box keeps whatever the template had.
        assert wf["nodes"][0]["widgets_values"] == ["new.png", "", ""]

    def test_a_capture_that_names_too_few_widgets_is_refused_by_name(self):
        wf = painted(ksampler())
        with pytest.raises(RecipeError, match="Capture the slot again"):
            apply_recipe(wf, {"KSampler": {"seed": 9}}, "purple")

    def test_an_undeclared_name_cannot_be_told_from_a_typo(self):
        # The limit of this, written down: a saved workflow records the VALUES
        # of the widgets it never declared and never their names, so
        # `control_after_generate` and a mistyped key look identical from
        # here. The COUNT is the discipline that is left — name as many
        # widgets as the node holds, or the slot is refused outright.
        wf = painted(ksampler())
        apply_recipe(wf, {"KSampler": {
            "seed": 9, "typo": "fixed", "steps": 30, "cfg": 7,
            "sampler_name": "euler", "scheduler": "simple", "denoise": 1}}, "purple")
        assert wf["nodes"][0]["widgets_values"] == [9, "fixed", 30, 7, "euler", "simple", 1]


class TestTheNameTheCanvasShows:
    """A node never retitled is captured under the name the canvas DRAWS on it.
    A saved workflow stores no title for one, so the server has to be told."""

    def test_without_display_names_the_class_name_is_the_key(self):
        wf = painted(control_image())
        assert sorted(recipe_slots(wf, "purple")) == ["SymbioticaControlImage"]

    def test_the_display_name_is_the_key_the_canvas_captured(self):
        wf = painted(control_image())
        display = {"SymbioticaControlImage": "Control Image"}
        assert sorted(recipe_slots(wf, "purple", display)) == ["Control Image"]
        apply_recipe(wf, {"Control Image": {"image": "new.png", "images_panel": ""}},
                     "purple", display)
        assert wf["nodes"][0]["widgets_values"][0] == "new.png"

    def test_a_title_he_typed_still_wins(self):
        node = control_image()
        node["title"] = "backdrop"
        wf = painted(node)
        assert sorted(recipe_slots(wf, "purple", {"SymbioticaControlImage": "Control Image"})) \
            == ["backdrop"]


class TestGenerate:
    def test_recipe_values_layer_over_shared_values(self):
        wf, _ = generate(template(), project(), "appliance1x2")
        assert by_id(wf, 10)["widgets_values"][0] == "controlnet/bakery/appliance1x2.png"
        assert by_id(wf, 14)["widgets_values"][1] == "bakery.safetensors"
        assert by_id(wf, 13)["mode"] == 0

    def test_the_template_is_not_modified(self):
        tpl = template()
        before = copy.deepcopy(tpl)
        generate(tpl, project(), "appliance1x1")
        assert tpl == before

    def test_a_recipe_value_overrides_a_shared_value_for_the_same_key(self):
        r = project()
        r["shared"]["control_image"] = "shared.png"
        wf, _ = generate(template(), r, "appliance1x1")
        assert by_id(wf, 10)["widgets_values"][0] == "controlnet/bakery/appliance1x1.png"

    def test_an_unknown_recipe_is_refused(self):
        with pytest.raises(RecipeError, match="chair"):
            generate(template(), project(), "chair")

    def test_a_key_the_template_no_longer_carries_is_left_out_and_reported(self):
        # The panel strikes such a row through and says the value is ignored;
        # the generator has to keep that promise instead of refusing the project.
        r = project()
        r["shared"]["old_slot"] = "x.png"
        r["recipes"]["appliance1x1"]["gone"] = True
        wf, report = generate(template(), r, "appliance1x1")
        assert by_id(wf, 10)["widgets_values"][0] == "controlnet/bakery/appliance1x1.png"
        assert report["ignored"] == ["gone", "old_slot"]
        assert "old_slot" not in report["applied"]

    def test_the_report_has_no_ignored_keys_when_every_value_has_a_slot(self):
        _, report = generate(template(), project(), "appliance1x1")
        assert report["ignored"] == []

    def test_each_generated_workflow_gets_its_own_stable_id_and_a_fresh_revision(self):
        a, _ = generate(template(), project(), "appliance1x1")
        b, _ = generate(template(), project(), "appliance1x2")
        again, _ = generate(template(), project(), "appliance1x1")
        assert a["id"] != template()["id"]
        assert a["id"] != b["id"]
        assert a["id"] == again["id"]
        assert a["revision"] == 0

    def test_the_workflow_name_is_the_base_workflow_plus_the_recipe(self):
        p = {**project(), "template": "recipe-test/bakery-template.json"}
        assert workflow_name(p, "appliance1x2") == "recipe-test-bakery-template-appliance1x2"
        # A `workflow_prefix` left in a project written before this is ignored:
        # the base's name IS the prefix.
        assert workflow_name({**p, "workflow_prefix": "dev-"}, "appliance1x2") \
            == "recipe-test-bakery-template-appliance1x2"


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


from _recipes import NAMESPACE, generate_all, list_projects, read_project


def write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


@pytest.fixture
def library(tmp_path):
    """A workflows dir holding the template in a folder, and a recipes dir
    holding one project that names it."""
    workflows = str(tmp_path / "workflows")
    recipes = str(tmp_path / "recipes")
    write_json(os.path.join(workflows, "recipe-test", "bakery-template.json"), template())
    write_json(os.path.join(recipes, "imperia-bakery.json"),
               {**project(), "template": "recipe-test/bakery-template.json"})
    return {"workflows": workflows, "recipes": recipes}


class TestRecipeLibrary:
    def test_lists_every_recipe_with_its_template_and_categories(self, library):
        assert list_projects(library["recipes"]) == [
            {"name": "imperia-bakery", "template": "recipe-test/bakery-template.json",
             "recipes": ["appliance1x1", "appliance1x2"]}]

    def test_a_missing_dir_lists_nothing(self, tmp_path):
        assert list_projects(str(tmp_path / "nope")) == []

    def test_reads_one_by_name_and_none_when_absent(self, library):
        assert read_project(library["recipes"], "imperia-bakery")["workflow_prefix"] == "dev-imperia-bakery-"
        assert read_project(library["recipes"], "other") is None

    def test_a_name_cannot_walk_out_of_the_dir(self, library):
        with pytest.raises(RecipeError):
            read_project(library["recipes"], "../secrets")


# What `generate` names a workflow from `recipe-test/bakery-template.json`.
GEN = "recipe-test-bakery-template"


class TestGenerateAll:
    def test_writes_one_workflow_per_recipe_next_to_the_template(self, library):
        # Named after the BASE and the recipe: a file called `appliance1x2.json`
        # beside its source says nothing about which source made it.
        r = read_project(library["recipes"], "imperia-bakery")
        report = generate_all(library["workflows"], r)
        paths = [w["path"] for w in report["written"]]
        assert paths == [f"recipe-test/{GEN}-appliance1x1.json",
                         f"recipe-test/{GEN}-appliance1x2.json"]
        wf = json.load(open(os.path.join(library["workflows"], paths[1])))
        assert by_id(wf, 10)["widgets_values"][0] == "controlnet/bakery/appliance1x2.png"
        assert report["written"][1]["recipe"] == "appliance1x2"
        assert report["written"][1]["applied"] == ["control_image", "grid", "pre_flip", "render", "render_aspect"]

    def test_an_output_folder_left_in_an_old_project_is_ignored(self, library):
        # The base workflow is the source and its outputs sit beside it. The
        # field was a second knob for the same rule and is gone; a value left
        # in a project file written before that must not move the files.
        r = {**read_project(library["recipes"], "imperia-bakery"), "output": "bakery/generated"}
        report = generate_all(library["workflows"], r)
        assert report["written"][0]["path"] == f"recipe-test/{GEN}-appliance1x1.json"
        assert os.path.isfile(os.path.join(library["workflows"], report["written"][0]["path"]))

    def test_a_prefix_left_in_an_old_project_is_ignored(self, library):
        # Same: the base's name IS the prefix now.
        r = {**read_project(library["recipes"], "imperia-bakery"),
             "workflow_prefix": "dev-imperia-bakery-"}
        report = generate_all(library["workflows"], r)
        assert report["written"][0]["path"] == f"recipe-test/{GEN}-appliance1x1.json"

    def test_regenerating_overwrites_the_previous_file(self, library):
        r = read_project(library["recipes"], "imperia-bakery")
        generate_all(library["workflows"], r)
        r["recipes"]["appliance1x1"]["control_image"] = "changed.png"
        generate_all(library["workflows"], r)
        wf = json.load(open(os.path.join(library["workflows"], f"recipe-test/{GEN}-appliance1x1.json")))
        assert by_id(wf, 10)["widgets_values"][0] == "changed.png"

    def test_names_the_file_the_old_naming_left_behind(self, library):
        # His `appliance1x1.json` from before the rename is still in the folder
        # and is not written any more: the name he has been opening all day
        # would go on holding the graph it froze with.
        # His own shape: no prefix, so the old name was the recipe alone.
        r = {**read_project(library["recipes"], "imperia-bakery"), "workflow_prefix": ""}
        old = os.path.join(library["workflows"], "recipe-test", "appliance1x1.json")
        write_json(old, {"id": str(uuid.uuid5(NAMESPACE, "appliance1x1")), "nodes": []})
        report = generate_all(library["workflows"], r)
        assert report["stale"] == ["recipe-test/appliance1x1.json"]
        assert os.path.isfile(old), "named, never deleted"

    def test_a_workflow_he_wrote_himself_is_not_named(self, library):
        # Ours is provable: a generated workflow's id is uuid5 over its own
        # name. One he saved by hand carries the editor's and is left alone.
        r = {**read_project(library["recipes"], "imperia-bakery"), "workflow_prefix": ""}
        mine = os.path.join(library["workflows"], "recipe-test", "appliance1x1.json")
        write_json(mine, {"id": "a6d1a0f2-0000-4000-8000-000000000000", "nodes": []})
        assert generate_all(library["workflows"], r)["stale"] == []

    def test_a_project_without_a_template_is_refused(self, library):
        with pytest.raises(RecipeError, match="template"):
            generate_all(library["workflows"], project())

    def test_a_template_that_is_not_there_is_refused(self, library):
        r = {**project(), "template": "recipe-test/missing.json"}
        with pytest.raises(RecipeError, match="missing.json"):
            generate_all(library["workflows"], r)

    def test_a_template_path_cannot_walk_out_of_the_workflows_dir(self, library):
        with pytest.raises(RecipeError):
            generate_all(library["workflows"], {**project(), "template": "../recipes/imperia-bakery.json"})

    def test_a_bad_recipe_value_fails_before_any_file_is_written(self, library):
        r = read_project(library["recipes"], "imperia-bakery")
        r["recipes"]["appliance1x2"]["pre_flip"] = "typo"
        with pytest.raises(RecipeError, match="typo"):
            generate_all(library["workflows"], r)
        assert not os.path.exists(os.path.join(library["workflows"], f"recipe-test/{GEN}-appliance1x1.json"))


from _recipes import new_project, project_name, read_template, template_slots, write_project


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


def muter_template():
    """A template whose purple Fast Groups Muter switches two render engines."""
    return {
        "nodes": [
            {"id": 1, "type": "Fast Groups Muter (rgthree)", "title": "engine",
             "color": "#323", "bgcolor": "#535", "pos": [0, 0], "size": [200, 60],
             "widgets_values": [{"toggled": True}, {"toggled": False}]},
            {"id": 2, "type": "KSampler", "pos": [520, 120], "size": [100, 50], "mode": 0},
            {"id": 3, "type": "KSampler", "pos": [520, 520], "size": [100, 50], "mode": 2},
        ],
        "groups": [
            {"title": "render-engine-nano2", "bounding": [500, 100, 300, 300]},
            {"title": "render-engine-qwen", "bounding": [500, 500, 300, 300]},
        ],
    }


class TestGroupSwitchSlots:
    def test_the_template_reports_a_group_switch_as_one_entry_per_group(self):
        slot = next(s for s in template_slots(muter_template(), "purple") if s["key"] == "engine")
        assert slot["kind"] == "dict"
        assert slot["default"] == {"render-engine-nano2": True, "render-engine-qwen": False}

    def test_generate_writes_the_modes_of_the_nodes_in_each_group(self):
        wf = muter_template()
        apply_recipe(wf, {"engine": {"render-engine-nano2": False, "render-engine-qwen": True}}, "purple")
        assert by_id(wf, 2)["mode"] == 2      # nano2 muted
        assert by_id(wf, 3)["mode"] == 0      # qwen live
        # The muter itself sits outside both frames and is never touched.
        assert "mode" not in by_id(wf, 1)

    def test_a_bypasser_bypasses_instead_of_muting(self):
        wf = muter_template()
        by_id(wf, 1)["type"] = "Fast Groups Bypasser (rgthree)"
        apply_recipe(wf, {"engine": {"render-engine-nano2": False, "render-engine-qwen": True}}, "purple")
        assert by_id(wf, 2)["mode"] == 4

    def test_a_group_the_template_does_not_have_is_refused_by_name(self):
        wf = muter_template()
        with pytest.raises(RecipeError, match="render-engine-gone"):
            apply_recipe(wf, {"engine": {"render-engine-gone": True}}, "purple")

    def test_a_group_value_that_is_not_true_or_false_is_refused(self):
        wf = muter_template()
        with pytest.raises(RecipeError, match="on or off"):
            apply_recipe(wf, {"engine": {"render-engine-nano2": "yes"}}, "purple")


class TestReadTemplate:
    def test_reads_by_path_relative_to_the_workflows_dir_with_or_without_the_workflows_prefix(self, library):
        a = read_template(library["workflows"], "recipe-test/bakery-template.json")
        b = read_template(library["workflows"], "workflows/recipe-test/bakery-template.json")
        assert a == b == template()

    def test_a_missing_template_is_refused_by_name(self, library):
        with pytest.raises(RecipeError, match="nope.json"):
            read_template(library["workflows"], "recipe-test/nope.json")


class TestWriteProject:
    def test_writes_the_file_the_name_reads_back(self, library):
        r = {**project(), "template": "recipe-test/bakery-template.json"}
        r["recipes"]["chair"] = {"control_image": "chair.png"}
        write_project(library["recipes"], "imperia-bakery", r)
        assert read_project(library["recipes"], "imperia-bakery")["recipes"]["chair"] == {"control_image": "chair.png"}

    def test_creates_the_dir_and_keeps_unicode_readable(self, tmp_path):
        d = str(tmp_path / "recipes")
        write_project(d, "x", {"template": "t.json", "recipes": {"a": {"preamble": "QE 2 — Coven"}}})
        assert "Coven" in open(os.path.join(d, "x.json"), encoding="utf-8").read()
        assert "\\u2014" not in open(os.path.join(d, "x.json"), encoding="utf-8").read()

    def test_refuses_a_project_that_is_not_a_table(self, tmp_path):
        with pytest.raises(RecipeError, match="recipes"):
            write_project(str(tmp_path), "x", {"template": "t.json"})
        with pytest.raises(RecipeError, match="template"):
            write_project(str(tmp_path), "x", {"recipes": {}})


class TestNewProject:
    def test_a_fresh_project_names_the_template_and_starts_shared_from_its_values(self, library):
        name, p = new_project(library["workflows"], "workflows/recipe-test/bakery-template.json")
        assert name == "recipe-test-bakery-template"
        assert p == {"template": "recipe-test/bakery-template.json",
                     "shared": {"control_image": "old.png", "grid": 2, "pre_flip": False,
                                "render": {"seed": 7, "lora_name": "old.safetensors", "strength_model": 0.5},
                                "render_aspect": "1:1 (Square)"},
                     "recipes": {}}

    def test_a_project_carries_nothing_but_its_base_and_its_recipes(self, library):
        # No `output` and no `workflow_prefix`: both were second knobs for one
        # rule, which is "beside the base, named after it".
        write_json(os.path.join(library["workflows"], "root-template.json"), template())
        name, p = new_project(library["workflows"], "root-template.json")
        assert name == "root-template"
        assert p["template"] == "root-template.json"
        assert "output" not in p and "workflow_prefix" not in p

    def test_the_name_is_the_base_workflow_path_slugged(self):
        # A project IS its base workflow. The FOLDER is in the name because two
        # bases with the same file name in different folders would otherwise
        # share one recipe table.
        assert project_name("recipe-test/bakery-template.json") == "recipe-test-bakery-template"
        assert project_name("workflows/October/Base Example.json") == "october-base-example"
        assert project_name("x.json") == "x"
        assert project_name("") == "project"


from _recipes import delete_project


class TestDeleteProject:
    def test_removes_the_file_and_says_so(self, library):
        assert delete_project(library["recipes"], "imperia-bakery") is True
        assert read_project(library["recipes"], "imperia-bakery") is None

    def test_a_project_that_is_not_there_is_false_not_an_error(self, library):
        assert delete_project(library["recipes"], "nope") is False

    def test_a_name_cannot_walk_out_of_the_dir(self, library):
        with pytest.raises(RecipeError):
            delete_project(library["recipes"], "../secrets")


from _recipes import color_matcher, slot_key, template_slots


class TestMatchColor:
    """A slot is a node painted the project's colour, its title the key."""

    def painted(self, title, color="#323", bgcolor="#535"):
        return {"id": 1, "type": "String", "title": title, "mode": 0,
                "color": color, "bgcolor": bgcolor, "widgets_values": ["x"]}

    def test_a_painted_node_is_a_slot_named_by_its_title(self):
        matches = color_matcher("purple")
        assert slot_key(self.painted("llm-prompt"), matches) == "llm-prompt"
        assert slot_key(self.painted("pre_flip?"), matches) == "pre_flip"

    def test_a_node_painted_something_else_is_not_a_slot(self):
        assert slot_key(self.painted("llm-prompt", "#232", "#353"), color_matcher("purple")) is None

    def test_an_unpainted_node_is_not_a_slot(self):
        node = {"id": 1, "type": "String", "title": "llm-prompt", "widgets_values": ["x"]}
        assert slot_key(node, color_matcher("purple")) is None

    def test_a_painted_node_with_no_title_goes_under_its_type_name(self):
        node = {"id": 1, "type": "String", "color": "#323", "bgcolor": "#535"}
        assert slot_key(node, color_matcher("purple")) == "String"

    def test_a_painted_subgraph_instance_goes_under_the_subgraphs_name(self):
        node = {"id": 1, "type": "abc-123", "color": "#323", "bgcolor": "#535"}
        assert slot_key(node, color_matcher("purple"), {"abc-123": "Render"}) == "Render"

    def test_the_recipe_prefix_still_marks_a_slot_whatever_the_colour(self):
        assert slot_key({"title": "recipe:grid"}, color_matcher("purple")) == "grid"
        assert slot_key({"title": "recipe:grid"}, None) == "grid"
        assert slot_key({"title": "grid"}, None) is None

    def test_the_prefix_is_dropped_from_a_painted_node_too(self):
        assert slot_key(self.painted("recipe:grid"), color_matcher("purple")) == "grid"

    def test_a_hex_and_a_lighter_shade_of_the_same_hue_match(self):
        matches = color_matcher("#535")
        assert matches(self.painted("x"))
        # What the light theme stores for the same purple.
        assert matches(self.painted("x", "#9b7f9b", "#b39bb3"))

    def test_the_palette_names_do_not_bleed_into_each_other(self):
        for name, hex_ in [("cyan", "#355"), ("blue", "#335"), ("pale_blue", "#3f5159"),
                           ("green", "#353"), ("purple", "#535"), ("red", "#533"),
                           ("yellow", "#653"), ("brown", "#593930")]:
            hits = [other for other in ("cyan", "blue", "pale_blue", "green", "purple",
                                        "red", "yellow", "brown")
                    if color_matcher(other)({"bgcolor": hex_})]
            assert hits == [name], (name, hits)

    def test_nothing_typed_matches_nothing(self):
        assert color_matcher("") is None
        assert color_matcher(None) is None
        assert color_matcher("chartreuse") is None

    def test_a_painted_template_generates_like_a_titled_one(self):
        wf = template()
        for node in wf["nodes"]:
            title = node.get("title") or ""
            if title.startswith("recipe:"):
                node["title"] = title[len("recipe:"):]
                node["bgcolor"] = "#535"
        slots = template_slots(wf, "purple")
        assert [s["key"] for s in slots] == [s["key"] for s in template_slots(template())]
        out, report = generate(wf, {"template": "t.json", "match_color": "purple",
                                    "shared": {"grid": 4}, "recipes": {"table": {}}}, "table")
        assert report["applied"] == ["grid"]
        assert recipe_slots(out, "purple")["grid"][0]["widgets_values"][0] == 4
