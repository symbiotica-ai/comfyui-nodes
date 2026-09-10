# ABOUTME: Tests the linked-module merge — a stale subgraph copy is replaced by
# ABOUTME: the library version, and promoted values follow the snapshot rule.
import copy
import json
import os

import pytest

from _modules import (TAG, ModuleError, apply_modules, load_library,
                      promoted_names, read_module, safe_filename,
                      sync_workflows, write_module)

SG_ID = "4ea6e827-ec92-4fdc-8d87-a021f5d6fb0a"


def subgraph(lora="old.safetensors", rev=None, sg_id=SG_ID):
    definition = {
        "id": sg_id, "version": 1, "name": "Image Edit",
        "inputs": [{"name": "prompt", "type": "STRING"},
                   {"name": "lora_name", "type": "COMBO"}],
        "outputs": [{"name": "IMAGE", "type": "IMAGE"}],
        "nodes": [{"id": 1, "type": "LoraLoaderModelOnly",
                   "widgets_values": [lora, 1.0]}],
        "links": [],
        "extra": {"workflowRendererVersion": "LG"},
    }
    if rev is not None:
        definition["extra"][TAG] = {"name": "edit", "rev": rev}
    return definition


def instance(node_id=770, prompt="make it bigger", lora="old.safetensors",
             snapshot=None, sg_id=SG_ID):
    node = {
        "id": node_id, "type": sg_id, "pos": [0, 0],
        "inputs": [{"name": "image", "type": "IMAGE", "link": None},
                   {"name": "prompt", "type": "STRING",
                    "widget": {"name": "prompt"}, "link": None},
                   {"name": "lora_name", "type": "COMBO",
                    "widget": {"name": "lora_name"}, "link": None}],
        "outputs": [], "properties": {},
        "widgets_values": [prompt, lora],
    }
    if snapshot is not None:
        node["properties"][TAG] = {"name": "edit", "rev": 1, "values": snapshot}
    return node


def workflow(definition, *nodes):
    return {"nodes": list(nodes), "links": [],
            "definitions": {"subgraphs": [definition]}, "extra": {}}


def module(rev=2, lora="new.safetensors", prompt="module prompt"):
    return {"name": "edit", "rev": rev, "subgraph": subgraph(lora=lora, rev=rev),
            "values": {"prompt": prompt, "lora_name": lora}}


class TestPromotedNames:
    def test_only_inputs_with_a_widget_count(self):
        assert promoted_names(instance()) == ["prompt", "lora_name"]


class TestApply:
    def test_stale_definition_is_replaced_and_keeps_the_workflow_id(self):
        w = workflow(subgraph(rev=1), instance(snapshot={"prompt": "module prompt",
                                                         "lora_name": "old.safetensors"}))
        report = apply_modules(w, {"edit": module()})
        d = w["definitions"]["subgraphs"][0]
        assert report["changed"] and report["updated"] == [{"name": "edit", "rev": 2}]
        assert d["id"] == SG_ID
        assert d["nodes"][0]["widgets_values"][0] == "new.safetensors"
        assert d["extra"][TAG] == {"name": "edit", "rev": 2}

    def test_changed_module_value_lands_and_untouched_one_survives(self):
        # The workflow typed its own prompt; the module only changed the LoRA.
        w = workflow(subgraph(rev=1), instance(
            prompt="my own prompt",
            snapshot={"prompt": "module prompt", "lora_name": "old.safetensors"}))
        apply_modules(w, {"edit": module()})
        node = w["nodes"][0]
        assert node["widgets_values"] == ["my own prompt", "new.safetensors"]
        assert node["properties"][TAG] == {
            "name": "edit", "rev": 2,
            "values": {"prompt": "module prompt", "lora_name": "new.safetensors"}}

    def test_no_snapshot_means_every_module_value_lands(self):
        w = workflow(subgraph(rev=1), instance(prompt="my own prompt"))
        apply_modules(w, {"edit": module()})
        assert w["nodes"][0]["widgets_values"] == ["module prompt", "new.safetensors"]

    def test_widget_count_mismatch_leaves_values_alone(self):
        node = instance()
        node["widgets_values"].append("randomize")
        w = workflow(subgraph(rev=1), node)
        report = apply_modules(w, {"edit": module()})
        assert w["nodes"][0]["widgets_values"] == ["make it bigger", "old.safetensors", "randomize"]
        assert report["values_skipped"] == [770]
        assert w["nodes"][0]["properties"][TAG]["rev"] == 2

    def test_instance_inside_another_subgraph_is_patched(self):
        outer = subgraph(sg_id="outer-id")
        outer["nodes"] = [instance(node_id=5)]
        w = workflow(subgraph(rev=1), instance(node_id=1))
        w["definitions"]["subgraphs"].append(outer)
        apply_modules(w, {"edit": module()})
        inner = w["definitions"]["subgraphs"][1]["nodes"][0]
        assert inner["widgets_values"][1] == "new.safetensors"

    def test_current_revision_is_left_alone(self):
        w = workflow(subgraph(rev=2), instance())
        before = copy.deepcopy(w)
        assert apply_modules(w, {"edit": module(rev=2)})["changed"] is False
        assert w == before

    def test_untagged_and_unknown_modules_are_ignored(self):
        w = workflow(subgraph(), instance())
        before = copy.deepcopy(w)
        assert apply_modules(w, {"edit": module()})["changed"] is False
        w2 = workflow(subgraph(rev=1), instance())
        w2["definitions"]["subgraphs"][0]["extra"][TAG]["name"] = "other"
        assert apply_modules(w2, {"edit": module()})["changed"] is False
        assert w == before

    def test_workflow_without_definitions(self):
        assert apply_modules({"nodes": []}, {"edit": module()})["changed"] is False


class TestLibrary:
    def test_publish_increments_revision_and_tags_the_subgraph(self, tmp_path):
        lib = str(tmp_path / "lib")
        first = write_module(lib, "edit", subgraph(), {"lora_name": "a"}, None)
        second = write_module(lib, "edit", subgraph(), {"lora_name": "b"}, {"type": "x"})
        assert (first["rev"], second["rev"]) == (1, 2)
        stored = read_module(lib, "edit")
        assert stored["subgraph"]["extra"][TAG] == {"name": "edit", "rev": 2}
        assert stored["values"] == {"lora_name": "b"}
        assert load_library(lib)["edit"]["rev"] == 2

    def test_bad_names_and_definitions_are_refused(self, tmp_path):
        with pytest.raises(ModuleError):
            write_module(str(tmp_path), "  ", subgraph(), {}, None)
        with pytest.raises(ModuleError):
            write_module(str(tmp_path), "edit", {"nope": 1}, {}, None)
        assert safe_filename("../../etc/passwd") == "etc-passwd"
        assert read_module(str(tmp_path), "missing") is None

    def test_library_skips_broken_files(self, tmp_path):
        (tmp_path / "broken.json").write_text("{not json")
        write_module(str(tmp_path), "edit", subgraph(), {}, None)
        assert list(load_library(str(tmp_path))) == ["edit"]


class TestSync:
    def _tree(self, tmp_path):
        wf = tmp_path / "workflows"
        (wf / "modal").mkdir(parents=True)
        stale = workflow(subgraph(rev=1), instance(
            snapshot={"prompt": "module prompt", "lora_name": "old.safetensors"}))
        (wf / "a.json").write_text(json.dumps(stale))
        (wf / "modal" / "b.json").write_text(json.dumps(stale, indent=2))
        (wf / "current.json").write_text(json.dumps(workflow(subgraph(rev=2), instance())))
        (wf / "notes.json").write_text(json.dumps({"hello": 1}))
        (wf / "bad.json").write_text("{")
        return wf

    def test_only_stale_workflows_are_rewritten(self, tmp_path):
        wf = self._tree(tmp_path)
        report = sync_workflows(str(wf), {"edit": module()})
        assert sorted(u["path"] for u in report["updated"]) == ["a.json", "modal/b.json"]
        assert report["errors"] == [{"path": "bad.json", "error": report["errors"][0]["error"]}]
        a = json.loads((wf / "a.json").read_text())
        assert a["nodes"][0]["widgets_values"][1] == "new.safetensors"
        assert json.loads((wf / "current.json").read_text())["nodes"][0]["widgets_values"][1] == "old.safetensors"

    def test_indented_files_stay_indented_and_compact_stay_compact(self, tmp_path):
        wf = self._tree(tmp_path)
        sync_workflows(str(wf), {"edit": module()})
        assert (wf / "modal" / "b.json").read_text().startswith("{\n")
        assert (wf / "a.json").read_text().startswith('{"')

    def test_single_path_with_workflows_prefix(self, tmp_path):
        wf = self._tree(tmp_path)
        report = sync_workflows(str(wf), {"edit": module()}, only_path="workflows/modal/b.json")
        assert [u["path"] for u in report["updated"]] == ["modal/b.json"]

    def test_single_path_cannot_escape(self, tmp_path):
        wf = self._tree(tmp_path)
        (tmp_path / "outside.json").write_text(json.dumps(workflow(subgraph(rev=1), instance())))
        with pytest.raises(ModuleError):
            sync_workflows(str(wf), {"edit": module()}, only_path="../outside.json")

    def test_symlinked_workflows_dir_is_followed(self, tmp_path):
        wf = self._tree(tmp_path)
        link = tmp_path / "link"
        os.symlink(wf, link)
        report = sync_workflows(str(link), {"edit": module()})
        assert len(report["updated"]) == 2

    def test_empty_library_is_a_no_op(self, tmp_path):
        wf = self._tree(tmp_path)
        assert sync_workflows(str(wf), {}) == {"updated": [], "errors": [], "scanned": 0}
