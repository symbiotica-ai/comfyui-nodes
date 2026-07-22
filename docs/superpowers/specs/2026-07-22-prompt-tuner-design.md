# Design: NS Prompt Tuner — self-improving system-prompt loop

Date: 2026-07-22. Approved by Razvan in-session ("sounds good, build and let's test").

## Problem

The system-prompt finetuner workflow (generation LLM + refiner LLM comparing a
design reference against the generated result) required hand-copying the
refined prompt back into the System Prompt primitive each round, and the
refiner had no memory of previous attempts.

## Decision

Cross-run loop, no graph cycles: each queue run is one iteration and ComfyUI
Auto-Queue drives the loop. Two new V1 nodes in `py/prompt_tuner.py` plus a
per-`tuner_id` JSON state file under `output/prompt_tuner/`.

- **NS Prompt Tuner Load** (head): serves the active prompt version from the
  state file (v0 seeded from `initial_prompt` on first run), emits a
  refiner-context block (user guidance + one-line critique history + latest
  critique in full) and a status line. `IS_CHANGED` fingerprints the state
  file so a saved iteration re-triggers execution on the next run.
  Halts (raises `TunerHalt`) in auto mode when the last verdict is CONVERGED
  with unchanged guidance, or when `max_iterations` refinements exist —
  breaking Auto-Queue before any API spend. `version_override` (-1 latest /
  0 initial / N fixed) bypasses halting for rollback and production serving.
- **NS Prompt Tuner Save** (tail, OUTPUT_NODE, always re-executes): parses the
  refiner's `CRITIQUE / VERDICT: IMPROVE|CONVERGED / PROMPT` response
  (fallback: whole text = prompt), appends the next version with lineage
  (parent, guidance snapshot from `last_served`, timestamp). An unchanged
  prompt is recorded as CONVERGED.

Choices made: v1 memory is text-only (prompt versions + critiques); a
follow-up upgrade Razvan wants is saving per-version result thumbnails and
feeding the refiner a 3-image batch [design, previous result, current result].
Guidance lives on the Load node, separate from the universal refiner
meta-prompt (`docs/prompt-tuner-refiner-system-prompt.md`). State is
append-only; hard reset = new `tuner_id`.

## Testing

Pure logic (parsing, serve/record, store) covered by `tests/test_prompt_tuner.py`
(18 tests). Node schema/registration verified live via `/api/object_info` and a
real tuning run — pytest does not import Comfy node classes.
