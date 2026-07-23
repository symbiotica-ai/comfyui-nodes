# NS Prompt Tuner — self-improving system-prompt loop

Improves the system prompt of an LLM prompt-rewriter stage by comparing each
generated image against a design reference, critiquing, and rewriting the
prompt — one refinement per queue run. Auto-Queue turns it into a hands-free
loop with full memory of what was already tried.

## How it works

Each queue run is one iteration:

```
NS Prompt Tuner Load ──system_prompt──▶ NS LLM Chat ──▶ image prompt ──▶ KSampler ──▶ result
        │                                                                          │
        │ refiner_context (guidance + history)          [design ref, result] batch │
        ▼                                                                          ▼
   JoinStringMulti ──────────────prompt───────────▶ NS LLM Chat Refiner
                                                             │ response
                                                             ▼
                                                   NS Prompt Tuner Save
                                                   (parses critique, saves v+1)
```

- **Load** (head) serves the current best prompt from
  `output/prompt_tuner/<tuner_id>.json`. First run of a new `tuner_id` seeds
  v0 from `initial_prompt`.
- The refiner LLM sees the design reference + this run's result, the client
  brief, the current system prompt, the image prompt it produced, and a
  tuning-context block (your guidance + every previous critique). It answers
  in a fixed `CRITIQUE / VERDICT / PROMPT` format
  (see `prompt-tuner-refiner-system-prompt.md`).
- **Save** (tail) parses that response and appends the refined prompt as the
  next version. An unchanged prompt is recorded as CONVERGED.
- The next run's Load picks up the new version automatically (its cache
  fingerprint is the state file), so **Auto-Queue = self-improving loop**.

## Node reference

**NS Prompt Tuner Load**
- `tuner_id` — one tuning experiment = one id = one state file.
- `guidance` — rough notes on what to improve ("focus on palette, counts are
  fine"). Changing it re-opens a converged tuner and steers the next critique.
- `version_override` — `-1` latest (tuning mode), `0` the initial prompt,
  `N` serve vN pinned (rollback / production mode: never halts, Save records
  nothing, and repeat queue runs are fully cached — a pinned graph costs no
  API calls after its first run).
- `max_iterations` — stop the loop once this many refinements exist for the
  tuner_id (lifetime count; default 12 as an Auto-Queue spend ceiling,
  0 = unlimited).
- Outputs: `system_prompt` (wire to your generator LLM **and** the refiner
  join), `refiner_context` (wire into the refiner's prompt), `status`
  (wire to a Preview Any).

**NS Prompt Tuner Save**
- `tuner_id` — must match the Load node.
- `response` — the refiner NS LLM Chat's output.

## Running a tuning session

1. Set `tuner_id`, connect your starting system prompt to `initial_prompt`,
   write rough `guidance`.
2. Fix your KSampler seed — the prompt should be the only variable.
3. Queue once and inspect, or enable Auto-Queue (instant) and watch the
   Design/Result compare. The loop stops itself on convergence or
   `max_iterations`; stopping Auto-Queue by hand is always fine.
4. Ship: set `version_override` to the best version and the graph serves that
   prompt forever. Roll back anytime — every version + critique lives in the
   state file, human-readable.

New experiment = new `tuner_id`. The state file is append-only; nothing is
ever overwritten.

## Guard rails

- A refiner reply without a `PROMPT:` section (refusal, commentary) or without
  the final `END PROMPT` line (token-cap truncation) is rejected with an error
  — the loop halts instead of saving a poisoned prompt.
- A rewritten prompt claiming CONVERGED is recorded as IMPROVE (it was never
  test-generated); convergence lands on the next run's verbatim repeat.
- A prompt identical to any earlier version is recorded as CONVERGED
  (oscillation stop).
- State is per-machine — a RunPod install tuning the same `tuner_id` keeps its
  own lineage. A corrupt state file fails loudly with its path; repair or
  delete it, or switch tuner_id.
