# ABOUTME: Tests for the self-improving prompt tuner — refiner-response parsing,
# ABOUTME: serve/record loop logic (versions, halting, dedupe, guards), and the store.
import json
import os

import pytest

from prompt_tuner import (
    TunerHalt,
    TunerStore,
    parse_refiner_response,
    record,
    serve,
)


# ---------- parsing ----------

FULL_RESPONSE = """CRITIQUE: Cake tiers read too saturated vs the design sheet.
Palette wording is too loose.
VERDICT: IMPROVE
PROMPT:
You are a prompt rewriter for a text-to-image pipeline.

RULES
1. Keep wording intact.
END PROMPT
"""


def converged_response(prompt_text, critique="matches design now"):
    return f"CRITIQUE: {critique}\nVERDICT: CONVERGED\nPROMPT:\n{prompt_text}\nEND PROMPT"


def improve_response(prompt_text, critique="tightened wording"):
    return f"CRITIQUE: {critique}\nVERDICT: IMPROVE\nPROMPT:\n{prompt_text}\nEND PROMPT"


def test_parse_full_sections():
    out = parse_refiner_response(FULL_RESPONSE)
    assert out["parsed"] is True
    assert out["complete"] is True
    assert out["critique"].startswith("Cake tiers read too saturated")
    assert "Palette wording is too loose." in out["critique"]
    assert out["verdict"] == "IMPROVE"
    assert out["prompt"].startswith("You are a prompt rewriter")
    assert out["prompt"].endswith("1. Keep wording intact.")
    assert "END PROMPT" not in out["prompt"]


def test_parse_converged_case_insensitive():
    text = "critique: good match now\nverdict: CONVERGED\nprompt:\nfinal prompt text\nend prompt"
    out = parse_refiner_response(text)
    assert out["verdict"] == "CONVERGED"
    assert out["prompt"] == "final prompt text"
    assert out["complete"] is True


def test_parse_missing_terminator_flags_incomplete():
    out = parse_refiner_response("CRITIQUE: x\nVERDICT: IMPROVE\nPROMPT:\ncut off mid")
    assert out["parsed"] is True
    assert out["complete"] is False


def test_parse_missing_markers_falls_back_to_whole_text():
    out = parse_refiner_response("Just a bare rewritten prompt, no sections.")
    assert out["parsed"] is False
    assert out["prompt"] == "Just a bare rewritten prompt, no sections."
    assert out["verdict"] == "IMPROVE"


def test_parse_strips_code_fences():
    out = parse_refiner_response("CRITIQUE: y\nVERDICT: IMPROVE\nPROMPT:\n```\nfenced\n```\nEND PROMPT")
    assert out["prompt"] == "fenced"


def test_parse_quoted_prompt_marker_in_critique_does_not_corrupt():
    text = ("CRITIQUE: the line\nPROMPT: style rules\nwas too vague last round\n"
            "VERDICT: IMPROVE\nPROMPT:\nthe real prompt\nEND PROMPT")
    out = parse_refiner_response(text)
    assert out["prompt"] == "the real prompt"
    assert out["verdict"] == "IMPROVE"


def test_parse_loose_verdict_words_do_not_match():
    text = "CRITIQUE: x\nVERDICT: not converged yet\nPROMPT:\np\nEND PROMPT"
    assert parse_refiner_response(text)["verdict"] == "IMPROVE"


def test_parse_verdict_inside_prompt_body_is_ignored():
    text = "CRITIQUE: x\nVERDICT: IMPROVE\nPROMPT:\nbody line\nEND PROMPT"
    # a VERDICT line after the PROMPT marker must not override the real one
    text2 = text.replace("body line", "body line\nVERDICT: CONVERGED\nmore body")
    # the strict full-line VERDICT inside the body sits after PROMPT: — ignored
    assert parse_refiner_response(text2)["verdict"] == "IMPROVE"


# ---------- serve ----------

def test_first_serve_initializes_v0():
    state, served = serve({}, initial_prompt="seed prompt", guidance="more contrast")
    assert served["version"] == 0
    assert served["prompt"] == "seed prompt"
    assert served["dirty"] is True
    assert state["iterations"][0]["v"] == 0
    assert state["last_served"] == dict(
        state["last_served"], version=0, guidance="more contrast", record=True, consumed=False)
    assert "no refinements yet" in served["context"]
    assert "more contrast" in served["context"]
    assert "v0" in served["status"]


def test_serve_after_record_serves_latest():
    state, _ = serve({}, initial_prompt="seed", guidance="g")
    state, saved = record(state, FULL_RESPONSE)
    assert saved["version"] == 1
    state, served = serve(state, initial_prompt="seed", guidance="g")
    assert served["version"] == 1
    assert served["prompt"].startswith("You are a prompt rewriter")
    assert "v1" in served["context"]
    assert "Cake tiers read too saturated" in served["context"]


def test_serve_version_override_rollback_and_reset():
    state, _ = serve({}, initial_prompt="seed", guidance="")
    state, _ = record(state, FULL_RESPONSE)
    state, served = serve(state, initial_prompt="seed", guidance="", version_override=0)
    assert served["version"] == 0
    assert served["prompt"] == "seed"
    state, served = serve(state, initial_prompt="seed", guidance="", version_override=1)
    assert served["version"] == 1


def test_serve_override_out_of_range_raises():
    state, _ = serve({}, initial_prompt="seed", guidance="")
    with pytest.raises(ValueError, match="v0"):
        serve(state, initial_prompt="seed", guidance="", version_override=7)


def test_pinned_serve_goes_clean_after_first_write():
    state, _ = serve({}, initial_prompt="seed", guidance="g")
    state, _ = record(state, FULL_RESPONSE)
    state, served = serve(state, initial_prompt="seed", guidance="g", version_override=1)
    assert served["dirty"] is True
    state, served = serve(state, initial_prompt="seed", guidance="g", version_override=1)
    assert served["dirty"] is False  # repeat run: no write, graph fully cacheable


def test_halt_on_converged_with_same_guidance():
    state, _ = serve({}, initial_prompt="seed", guidance="g")
    state, _ = record(state, converged_response("seed"))  # verbatim repeat = converged
    with pytest.raises(TunerHalt, match="[Cc]onverged"):
        serve(state, initial_prompt="seed", guidance="g")


def test_guidance_change_unlocks_converged():
    state, _ = serve({}, initial_prompt="seed", guidance="g")
    state, _ = record(state, converged_response("seed"))
    state, served = serve(state, initial_prompt="seed", guidance="now improve mood")
    assert served["version"] == 1


def test_converged_version_still_servable_via_override():
    state, _ = serve({}, initial_prompt="seed", guidance="g")
    state, _ = record(state, converged_response("seed"))
    state, served = serve(state, initial_prompt="seed", guidance="g", version_override=1)
    assert served["prompt"] == "seed"


def test_halt_on_max_iterations():
    state, _ = serve({}, initial_prompt="seed", guidance="g", max_iterations=1)
    state, _ = record(state, FULL_RESPONSE)
    with pytest.raises(TunerHalt, match="max_iterations"):
        serve(state, initial_prompt="seed", guidance="g", max_iterations=1)
    # 0 = unlimited
    state, served = serve(state, initial_prompt="seed", guidance="g", max_iterations=0)
    assert served["version"] == 1


def test_context_caps_long_histories():
    state, _ = serve({}, initial_prompt="seed", guidance="")
    for i in range(25):
        state, _ = record(state, improve_response(f"prompt variant {i}", critique=f"edit {i}"))
        state, _ = serve(state, initial_prompt="seed", guidance="")
    _, served = serve(state, initial_prompt="seed", guidance="")
    assert "earlier iteration(s) omitted" in served["context"]
    assert "edit 24" in served["context"]
    assert "edit 1\n" not in served["context"]


# ---------- record ----------

def test_record_without_serve_raises():
    with pytest.raises(ValueError, match="[Ll]oad"):
        record({}, FULL_RESPONSE)


def test_record_identical_prompt_marks_converged():
    state, _ = serve({}, initial_prompt="same prompt", guidance="")
    state, saved = record(state, improve_response("same prompt", critique="no changes needed"))
    assert saved["verdict"] == "CONVERGED"
    assert state["iterations"][-1]["verdict"] == "CONVERGED"


def test_record_changed_prompt_claiming_converged_is_downgraded():
    # a rewritten prompt has never been test-generated — one more loop first
    state, _ = serve({}, initial_prompt="seed", guidance="")
    state, saved = record(state, converged_response("brand new prompt"))
    assert saved["verdict"] == "IMPROVE"


def test_record_oscillation_back_to_old_version_converges():
    state, _ = serve({}, initial_prompt="seed", guidance="")
    state, _ = record(state, improve_response("variant b"))
    state, _ = serve(state, initial_prompt="seed", guidance="")
    state, saved = record(state, improve_response("seed"))  # back to v0
    assert saved["verdict"] == "CONVERGED"
    assert "oscillation" in saved["status"]


def test_record_rejects_missing_prompt_section():
    state, _ = serve({}, initial_prompt="seed", guidance="")
    with pytest.raises(ValueError, match="PROMPT"):
        record(state, "I cannot analyze these images, sorry.")


def test_record_rejects_truncated_response():
    state, _ = serve({}, initial_prompt="seed", guidance="")
    with pytest.raises(ValueError, match="[Tt]runcated"):
        record(state, "CRITIQUE: x\nVERDICT: IMPROVE\nPROMPT:\ncut off mid-sente")


def test_record_double_save_raises():
    state, _ = serve({}, initial_prompt="seed", guidance="")
    state, _ = record(state, FULL_RESPONSE)
    with pytest.raises(ValueError, match="already recorded|mismatch"):
        record(state, FULL_RESPONSE)


def test_record_noop_when_pinned():
    state, _ = serve({}, initial_prompt="seed", guidance="")
    state, _ = record(state, FULL_RESPONSE)
    state, served = serve(state, initial_prompt="seed", guidance="", version_override=1)
    state, saved = record(state, FULL_RESPONSE)
    assert saved["dirty"] is False
    assert "nothing recorded" in saved["status"]
    assert len(state["iterations"]) == 2  # v0 + v1 only


def test_record_keeps_lineage_fields():
    state, _ = serve({}, initial_prompt="seed", guidance="push contrast")
    state, saved = record(state, FULL_RESPONSE)
    it = state["iterations"][-1]
    assert it["parent"] == 0
    assert it["guidance"] == "push contrast"
    assert it["critique"].startswith("Cake tiers")
    assert it["ts"]


# ---------- store ----------

def test_store_roundtrip_and_signature(tmp_path):
    store = TunerStore(str(tmp_path))
    sig_empty = store.signature("bakery sheet")
    state, _ = serve({}, initial_prompt="seed", guidance="")
    store.save("bakery sheet", state)
    assert store.signature("bakery sheet") != sig_empty
    loaded = store.load("bakery sheet")
    assert loaded["iterations"][0]["prompt"] == "seed"
    assert os.listdir(tmp_path) == ["bakery-sheet.json"]
    with open(tmp_path / "bakery-sheet.json", encoding="utf-8") as f:
        assert json.load(f)["iterations"]


def test_store_load_missing_returns_empty(tmp_path):
    assert TunerStore(str(tmp_path)).load("nope") == {}


def test_store_corrupt_file_raises_actionable_error(tmp_path):
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt.*bad.json|bad.json.*corrupt"):
        TunerStore(str(tmp_path)).load("bad")


def test_store_schema_drift_raises_actionable_error(tmp_path):
    (tmp_path / "old.json").write_text(json.dumps({"iterations": [{"foo": 1}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        TunerStore(str(tmp_path)).load("old")


# ---------- re-billing guards (added after two Fable validations) ----------
# The muted-Save halt now returns a {"halt": ...} marker from serve(); the Load
# node (serve_prompt) persists the reset it carries, then raises TunerHalt.

def _auto(state, guidance="g"):
    return serve(state, initial_prompt="p", guidance=guidance,
                 version_override=-1, max_iterations=0)


def test_auto_stall_halts_then_recovers():
    # A muted/unwired Save never records, so the count of unrecorded serves
    # climbs until the guard trips. Crucially it must recover: the trip resets
    # the count (persisted by the node), so the next queue serves afresh once
    # Save is fixed — not re-halt forever.
    state = {}
    served = {}
    for _ in range(20):
        state, served = _auto(state)       # no record() between serves
        if "halt" in served:
            break
    assert "halt" in served and "Save" in served["halt"]
    assert state.get("unconsumed", 0) == 0, "the trip must reset the count"

    # Save is fixed; the next serve proceeds (no halt) and records.
    state, served = _auto(state)
    assert "halt" not in served
    state, _ = record(state, improve_response("recovered prompt"))
    assert len(state["iterations"]) >= 2

    # And the loop keeps going normally afterwards.
    for i in range(4):
        state, served = _auto(state)
        assert "halt" not in served
        state, _ = record(state, improve_response(f"more {i}"))


def test_stall_count_survives_a_pinned_serve():
    # A pinned Load on the same tuner_id (a latest-vs-baseline compare graph)
    # must not reset the auto stall count — the two guards used to starve each
    # other and re-open the runaway.
    state = _seed_three_versions()
    served = {}
    for _ in range(20):
        state, served = _auto(state)                      # auto serve
        if "halt" in served:
            break
        state, _ = serve(state, initial_prompt="", guidance="g",
                         version_override=0, max_iterations=0)   # pinned serve, no record
    assert "halt" in served, "a pinned serve wiped the stall count"


def test_normal_loop_never_stalls():
    state = {}
    for i in range(8):
        state, served = _auto(state)
        assert "halt" not in served
        state, _ = record(state, improve_response(f"v{i+1}"))
    assert len(state["iterations"]) == 9


def _seed_three_versions():
    state = {}
    state, _ = _auto(state)
    state, _ = record(state, improve_response("p1"))
    state, _ = _auto(state)
    state, _ = record(state, improve_response("p2"))
    return state   # v0, v1, v2


def test_alternating_pinned_loads_settle_to_cached():
    state = _seed_three_versions()
    dirt = []
    for v in (1, 2, 1, 2, 1, 2):
        state, served = serve(state, initial_prompt="", guidance="g",
                              version_override=v, max_iterations=0)
        dirt.append(served["dirty"])
    assert dirt[0] is True
    assert not any(dirt[1:]), f"alternating pins kept re-writing: {dirt}"


def test_single_pin_serves_the_right_prompt():
    state = _seed_three_versions()
    state, a = serve(state, initial_prompt="", guidance="g",
                     version_override=1, max_iterations=0)
    state, b = serve(state, initial_prompt="", guidance="g",
                     version_override=2, max_iterations=0)
    assert a["version"] == 1 and a["prompt"] == "p1"
    assert b["version"] == 2 and b["prompt"] == "p2"


def test_serve_prompt_persists_the_reset_on_halt(tmp_path, monkeypatch):
    # End-to-end through the Load node: the halt must both raise AND leave the
    # state file with the count reset, so a re-queue recovers.
    import prompt_tuner
    store = TunerStore(str(tmp_path))
    monkeypatch.setattr(prompt_tuner, "_default_store", lambda: store)
    node = prompt_tuner.NSPromptTunerLoad()

    halted = False
    for _ in range(20):
        try:
            node.serve_prompt("t", "g", -1, 0, initial_prompt="p")
        except TunerHalt:
            halted = True
            break
    assert halted, "the node never halted with Save absent"
    assert store.load("t").get("unconsumed", 0) == 0, "reset not persisted"
    # The very next serve works (does not re-raise).
    node.serve_prompt("t", "g", -1, 0, initial_prompt="p")
