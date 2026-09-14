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
    assert out.args == ("GAME RULES\n",)


def test_prompts_with_nothing_picked_outputs_empty(nodes_mod):
    out = nodes_mod.SymbioticaPromptBlock.execute()
    assert out.args == ("",)


def test_prompts_is_four_widgets_and_one_output(nodes_mod):
    # The node is a literal with a file behind it: path, folder, file, text.
    # No category, slot, subfolder, passthrough or chain input — every one of
    # those was a second way to say something the canvas already says.
    schema = nodes_mod.SymbioticaPromptBlock.define_schema()
    assert schema.node_id == "SymbioticaPromptBlock"
    assert schema.display_name == "Prompts (Symbiotica)"
    assert [i.id for i in schema.inputs] == ["path", "folder", "file", "text"]
    assert [o.display_name for o in schema.outputs] == ["text"]
    text = schema.inputs[3]
    assert text.multiline is True
