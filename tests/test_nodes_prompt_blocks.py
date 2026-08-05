# ABOUTME: Node-face tests for the canvas prompt nodes — Prompt Block reads and
# ABOUTME: passes through, Prompt Compose matches the queue's composition.
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
    (proj / "prompts" / "_rules").mkdir(parents=True)
    for name, text in files.items():
        path = proj / "prompts" / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return proj


# --- Prompt Block -------------------------------------------------------------

def test_block_reads_its_file_and_passes_the_project_through(nodes_mod,
                                                             tmp_path):
    proj = _project(tmp_path, **{"_rules__01-game.md": "GAME RULES\n"})
    out = nodes_mod.SymbioticaPromptBlock.execute(
        project_path=str(proj), block="_rules/01-game.md")
    assert out.args == (str(proj), "GAME RULES")


def test_block_missing_file_is_empty_not_an_error(nodes_mod, tmp_path):
    # The node is the editor the block is written in — it must run before its
    # first save.
    proj = _project(tmp_path)
    out = nodes_mod.SymbioticaPromptBlock.execute(
        project_path=str(proj), block="_image/01-image-model.md")
    assert out.args == (str(proj), "")


def test_block_without_a_pick_is_a_wiring_error(nodes_mod, tmp_path):
    proj = _project(tmp_path)
    with pytest.raises(ValueError, match="no block picked"):
        nodes_mod.SymbioticaPromptBlock.execute(project_path=str(proj),
                                                block="")


def test_block_without_a_project_says_so(nodes_mod):
    with pytest.raises(ValueError, match="project"):
        nodes_mod.SymbioticaPromptBlock.execute(project_path="",
                                                block="Chair.md")


def test_block_fingerprint_changes_when_its_file_is_edited(nodes_mod,
                                                           tmp_path):
    proj = _project(tmp_path, **{"Chair.md": "one"})
    fp = nodes_mod.SymbioticaPromptBlock.fingerprint_inputs
    before = fp(project_path=str(proj), block="Chair.md")
    assert before == fp(project_path=str(proj), block="Chair.md")
    p = proj / "prompts" / "Chair.md"
    p.write_text("two")
    os.utime(p, ns=(1, 1))
    assert fp(project_path=str(proj), block="Chair.md") != before


def test_block_fingerprint_never_raises(nodes_mod):
    # A raise becomes NaN and re-bills every descendant each queue press.
    assert nodes_mod.SymbioticaPromptBlock.fingerprint_inputs(
        project_path=None, block=None)


# --- Prompt Compose -----------------------------------------------------------

def test_compose_matches_what_category_prompts_hands_the_llm(nodes_mod,
                                                             tmp_path):
    proj = _project(tmp_path, **{"_rules__01-game.md": "GAME",
                                 "_rules__02-inputs.md": "INPUTS",
                                 "Food - 3 stages.md": "FOOD TASK"})
    composed = nodes_mod.SymbioticaPromptCompose.execute(
        project_path=str(proj), category="Food - 3 stages").args[0]
    via_sheets = nodes_mod.SymbioticaCategoryPrompts.execute(
        sheet_categories=["Food - 3 stages"],
        project_path=[str(proj)]).args[1][0]
    assert composed == via_sheets == "GAME\n\nINPUTS\n\nFOOD TASK"


def test_compose_missing_type_names_the_file_to_create(nodes_mod, tmp_path):
    proj = _project(tmp_path, **{"_rules__01-game.md": "GAME"})
    with pytest.raises(Exception, match=r"Chair\.md"):
        nodes_mod.SymbioticaPromptCompose.execute(project_path=str(proj),
                                                  category="Chair")


def test_compose_fingerprint_ignores_render_and_backup_churn(nodes_mod,
                                                             tmp_path):
    # renders.jsonl and .bak share the folder and change every run — hashing
    # them would re-bill the LLM each queue press with the prompts untouched.
    proj = _project(tmp_path, **{"Chair.md": "one"})
    fp = nodes_mod.SymbioticaPromptCompose.fingerprint_inputs
    before = fp(project_path=str(proj), category="Chair")
    (proj / "prompts" / "renders.jsonl").write_text("{}\n")
    (proj / "prompts" / "Chair.md.bak").write_text("old")
    assert fp(project_path=str(proj), category="Chair") == before
    p = proj / "prompts" / "Chair.md"
    p.write_text("two")
    os.utime(p, ns=(1, 1))
    assert fp(project_path=str(proj), category="Chair") != before


def test_compose_fingerprint_falls_back_to_executed_projects(nodes_mod,
                                                             tmp_path,
                                                             monkeypatch):
    # With the project on the WIRE the widget is empty here — without the
    # fallback an edit never busts the cache in exactly the wired graphs.
    proj = _project(tmp_path, **{"Chair.md": "one"})
    monkeypatch.setattr(nodes_mod, "_executed_projects",
                        lambda: [str(proj)])
    fp = nodes_mod.SymbioticaPromptCompose.fingerprint_inputs
    before = fp(project_path="", category="Chair")
    p = proj / "prompts" / "Chair.md"
    p.write_text("two")
    os.utime(p, ns=(1, 1))
    assert fp(project_path="", category="Chair") != before


def test_category_prompts_fingerprint_ignores_render_churn(nodes_mod,
                                                           tmp_path):
    # The fix applies to the sheet-driven node too — it walks the same folder.
    proj = _project(tmp_path, **{"Chair.md": "one"})
    fp = nodes_mod.SymbioticaCategoryPrompts.fingerprint_inputs
    before = fp(project_path=[str(proj)])
    (proj / "prompts" / "renders.jsonl").write_text("{}\n")
    assert fp(project_path=[str(proj)]) == before


def test_blocks_chain_like_join_multi(nodes_mod, tmp_path):
    # GAME -> INPUTS chained by wire: the second node's text output carries
    # both, blank-line joined, same separator the book compose uses.
    proj = _project(tmp_path, **{"_rules__01-game.md": "GAME\n",
                                 "_rules__02-inputs.md": "INPUTS\n"})
    first = nodes_mod.SymbioticaPromptBlock.execute(
        project_path=str(proj), block="_rules/01-game.md")
    second = nodes_mod.SymbioticaPromptBlock.execute(
        project_path=first.args[0], block="_rules/02-inputs.md",
        text_in=first.args[1])
    assert second.args[1] == "GAME\n\nINPUTS"


def test_block_chain_skips_an_empty_link(nodes_mod, tmp_path):
    # A not-yet-saved block must not inject a blank segment mid-chain.
    proj = _project(tmp_path, **{"_rules__01-game.md": "GAME"})
    out = nodes_mod.SymbioticaPromptBlock.execute(
        project_path=str(proj), block="_image/01-image-model.md",
        text_in="GAME")
    assert out.args[1] == "GAME"
