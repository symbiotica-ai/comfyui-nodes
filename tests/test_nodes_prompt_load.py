# ABOUTME: Node-face tests for Prompt Load — the file the dropdown picked, read
# ABOUTME: from the path, cached on the file itself.
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


@pytest.fixture()
def prompts(tmp_path):
    folder = tmp_path / "prompts"
    (folder / "_rules").mkdir(parents=True)
    (folder / "Chair.md").write_text("CHAIR\n", encoding="utf-8")
    (folder / "_rules" / "01-refs.md").write_text("REFS\n", encoding="utf-8")
    return folder


def test_it_is_two_widgets_and_one_output(nodes_mod):
    # A path and a file. No root_dir: the path IS the root, which is the whole
    # reason this node exists next to Load Text File.
    schema = nodes_mod.SymbioticaPromptLoad.define_schema()
    assert schema.node_id == "SymbioticaPromptLoad"
    assert schema.display_name == "Prompt Load (Symbiotica)"
    assert [i.id for i in schema.inputs] == ["path", "file"]
    assert [o.display_name for o in schema.outputs] == ["text"]


def test_it_is_an_output_node_so_it_can_be_queued_alone(nodes_mod):
    assert nodes_mod.SymbioticaPromptLoad.define_schema().is_output_node is True


def test_it_outputs_the_file_under_the_path(nodes_mod, prompts):
    out = nodes_mod.SymbioticaPromptLoad.execute(
        path=str(prompts), file="_rules/01-refs.md")
    assert out.args == ("REFS\n",)


def test_nothing_picked_outputs_empty(nodes_mod, prompts):
    # The dropdown's placeholder is what a node with no path shows, and it
    # reaches Python as the string. It is not a file name.
    assert nodes_mod.SymbioticaPromptLoad.execute(
        path=str(prompts), file="[no files in folder]").args == ("",)
    assert nodes_mod.SymbioticaPromptLoad.execute(
        path=str(prompts), file="").args == ("",)
    assert nodes_mod.SymbioticaPromptLoad.execute().args == ("",)


def test_a_picked_file_that_is_gone_is_loud(nodes_mod, prompts):
    from pipeline.prompt_store import PromptPathError
    with pytest.raises(PromptPathError):
        nodes_mod.SymbioticaPromptLoad.execute(path=str(prompts),
                                               file="Sofa.md")


def test_it_cannot_be_pointed_outside_the_path(nodes_mod, prompts, tmp_path):
    from pipeline.prompt_store import PromptPathError
    (tmp_path / "secret.md").write_text("NO\n", encoding="utf-8")
    with pytest.raises(PromptPathError):
        nodes_mod.SymbioticaPromptLoad.execute(path=str(prompts),
                                               file="../secret.md")


def test_a_run_hands_the_path_it_received_back_to_the_canvas(nodes_mod, monkeypatch,
                                                             prompts):
    pushed = []
    monkeypatch.setattr(nodes_mod, "_push",
                        lambda event, payload: pushed.append((event, payload)))
    nodes_mod.SymbioticaPromptLoad.execute(path=str(prompts), file="Chair.md")
    assert pushed[0][0] == "symbiotica.prompt_load"
    assert pushed[0][1]["path"] == str(prompts)


def test_the_path_is_pushed_before_the_file_is_read(nodes_mod, monkeypatch,
                                                    prompts):
    # The first queue of a node whose path arrives on a wire has nothing
    # picked: if the push waited for a successful read it would never happen,
    # and the dropdown would never fill.
    pushed = []
    monkeypatch.setattr(nodes_mod, "_push",
                        lambda event, payload: pushed.append(payload))
    nodes_mod.SymbioticaPromptLoad.execute(path=str(prompts), file="[set path]")
    assert pushed and pushed[0]["path"] == str(prompts)


def test_it_re_runs_when_the_file_changes_and_not_otherwise(nodes_mod, prompts):
    load = nodes_mod.SymbioticaPromptLoad
    first = load.fingerprint_inputs(path=str(prompts), file="Chair.md")
    assert load.fingerprint_inputs(path=str(prompts), file="Chair.md") == first
    os.utime(prompts / "Chair.md", (1, 1))
    assert load.fingerprint_inputs(path=str(prompts), file="Chair.md") != first
    # Another file is another fingerprint, even with the same contents.
    assert load.fingerprint_inputs(path=str(prompts),
                                   file="_rules/01-refs.md") != first


def test_a_node_with_nothing_picked_holds_still(nodes_mod, prompts):
    # NaN here would make the node permanently "changed" and re-bill every
    # node downstream on every queue — the bug Load Text File exists to avoid.
    load = nodes_mod.SymbioticaPromptLoad
    assert load.fingerprint_inputs() == load.fingerprint_inputs()
    assert load.fingerprint_inputs(path=str(prompts), file="[set path]") \
        == load.fingerprint_inputs(path=str(prompts), file="[set path]")
