# ABOUTME: Node-face tests for the Prompts node — a text literal backed by a
# ABOUTME: file: the output is the text on the canvas, nothing else.
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


def test_prompts_outputs_the_text_as_shown(nodes_mod):
    out = nodes_mod.SymbioticaPromptBlock.execute(
        path="/p/bakery/prompts", folder="_rules", file="01-game.md",
        text="GAME RULES\n")
    assert out.args == ({"names": ["_rules/01-game.md"],
                         "texts": ["GAME RULES\n"]},)


def test_prompts_with_nothing_picked_outputs_empty(nodes_mod):
    out = nodes_mod.SymbioticaPromptBlock.execute()
    assert out.args == ({"names": [], "texts": []},)


def test_prompts_is_four_widgets_and_the_tick_list(nodes_mod):
    # The node is a literal with a file behind it: path, folder, file, text,
    # and the ticked files APPENDED after them so no saved value shifts.
    schema = nodes_mod.SymbioticaPromptBlock.define_schema()
    assert schema.node_id == "SymbioticaPromptBlock"
    assert schema.display_name == "Prompts (Symbiotica)"
    assert [i.id for i in schema.inputs] == ["path", "folder", "file", "text",
                                             "files"]
    assert [o.display_name for o in schema.outputs] == ["prompts"]
    text = schema.inputs[3]
    assert text.multiline is True


def _prompts(tmp_path):
    root = tmp_path / "prompts"
    (root / "image").mkdir(parents=True)
    (root / "llm").mkdir()
    (root / "image" / "sketch.md").write_text("SKETCH")
    (root / "image" / "final.md").write_text("FINAL")
    (root / "llm" / "system.md").write_text("SYSTEM")
    return root


def test_ticked_files_answer_in_tick_order(nodes_mod, tmp_path):
    root = _prompts(tmp_path)
    out = nodes_mod.SymbioticaPromptBlock.execute(
        path=str(root), folder="llm", file="system.md", text="SYSTEM",
        files='["image/final.md", "llm/system.md", "image/sketch.md"]')
    assert out.args[0] == {
        "names": ["image/final.md", "llm/system.md", "image/sketch.md"],
        "texts": ["FINAL", "SYSTEM", "SKETCH"]}


def test_prompt_specs_splits_the_wire_and_pads(nodes_mod):
    out = nodes_mod.SymbioticaPromptSpecs.execute(
        prompts={"names": ["a.md", "b.md"], "texts": ["A", "B"]})
    assert out.args[:2] == ("A", "B")
    assert out.args[2:] == ("",) * (nodes_mod.PROMPT_OUTPUTS - 2)
    with pytest.raises(ValueError):
        nodes_mod.SymbioticaPromptSpecs.execute()


def test_the_open_files_unsaved_edit_wins(nodes_mod, tmp_path):
    root = _prompts(tmp_path)
    out = nodes_mod.SymbioticaPromptBlock.execute(
        path=str(root), folder="image", file="sketch.md", text="EDITED",
        files='["image/sketch.md", "image/final.md"]')
    assert out.args[0]["texts"] == ["EDITED", "FINAL"]


def test_a_ticked_file_that_is_gone_fails_by_name(nodes_mod, tmp_path):
    root = _prompts(tmp_path)
    with pytest.raises(Exception, match="gone.md"):
        nodes_mod.SymbioticaPromptBlock.execute(
            path=str(root), folder="image", file="sketch.md", text="SKETCH",
            files='["image/gone.md"]')


def test_a_workflow_saved_before_ticks_reads_nothing_ticked(nodes_mod, tmp_path):
    # An old save hands `files` the panel's value: "" or null.
    root = _prompts(tmp_path)
    for old in ("", None, "not json", '{"a": 1}'):
        out = nodes_mod.SymbioticaPromptBlock.execute(
            path=str(root), folder="image", file="sketch.md", text="X",
            files=old)
        assert out.args == ({"names": ["image/sketch.md"], "texts": ["X"]},)


def test_editing_a_ticked_file_on_disk_reruns_the_node(nodes_mod, tmp_path):
    root = _prompts(tmp_path)
    args = dict(path=str(root), folder="image", file="sketch.md",
                text="SKETCH", files='["image/final.md"]')
    before = nodes_mod.SymbioticaPromptBlock.fingerprint_inputs(**args)
    assert before == nodes_mod.SymbioticaPromptBlock.fingerprint_inputs(**args)
    target = root / "image" / "final.md"
    target.write_text("FINAL, LONGER")
    os.utime(target, ns=(1, 1))
    assert before != nodes_mod.SymbioticaPromptBlock.fingerprint_inputs(**args)


def test_prompts_is_an_output_node_so_it_can_be_queued_alone(nodes_mod):
    # A path arriving through a Get node has no value on the canvas. Queueing
    # the node is how the path is read, and a node with nothing downstream is
    # only queueable as an output node.
    schema = nodes_mod.SymbioticaPromptBlock.define_schema()
    assert schema.is_output_node is True


def test_a_run_hands_the_path_it_received_back_to_the_canvas(nodes_mod, monkeypatch):
    pushed = []
    monkeypatch.setattr(nodes_mod, "_push",
                        lambda event, payload: pushed.append((event, payload)))
    nodes_mod.SymbioticaPromptBlock.execute(
        path="/studio-assets/_platform/resources", folder="/", file="a.md",
        text="X")
    assert pushed[0][0] == "symbiotica.prompts"
    assert pushed[0][1]["path"] == "/studio-assets/_platform/resources"
