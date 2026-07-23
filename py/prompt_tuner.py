# ABOUTME: Self-improving system-prompt tuner. Load serves the current best prompt
# ABOUTME: from a per-tuner_id state file; Save records the refiner's critique and
# ABOUTME: refined prompt. Each queue run is one iteration; Auto-Queue drives the loop.
#
# Caching contract (verified against ComfyUI 0.28 comfy_execution/caching.py):
# cache keys are built from each node's own IS_CHANGED plus every ANCESTOR's
# IS_CHANGED — runtime output values never enter a key. The tuning loop's
# freshness therefore depends on Load's state file changing between runs (its
# IS_CHANGED is the file signature): the last_served write in auto mode is
# load-bearing — removing it would let the generator LLM serve stale cached
# responses. Conversely, in pinned mode (version_override >= 0) serve() skips
# the write when nothing changed, so a production graph becomes fully cached
# and a queue press costs nothing.

import json
import os
import re
from datetime import datetime


class TunerHalt(Exception):
    """Raised by the Load node to stop the Auto-Queue loop cleanly."""


# How many auto serves in a row the Save node may leave unrecorded before the
# loop stops itself. A muted/bypassed Save records nothing, so max_iterations
# (which counts recorded refinements) can never fire; without this the loop
# re-bills the generator every queue forever. Tolerates a couple of transient
# misses, then halts.
_MAX_UNCONSUMED_SERVES = 3


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _first_line(text: str, cap: int = 160) -> str:
    line = (text or "").strip().split("\n", 1)[0]
    return line[:cap]


_PROMPT_RE = re.compile(r"^[ \t]*PROMPT[ \t]*:[ \t]*", re.IGNORECASE | re.MULTILINE)
_VERDICT_RE = re.compile(
    r"^[ \t]*VERDICT[ \t]*:[ \t]*(IMPROVE|CONVERGED)[ \t]*$",
    re.IGNORECASE | re.MULTILINE)
_CRITIQUE_RE = re.compile(r"^[ \t]*CRITIQUE[ \t]*:[ \t]*", re.IGNORECASE | re.MULTILINE)

HISTORY_CONTEXT_CAP = 20


def _strip_fences(text: str) -> str:
    lines = text.strip().split("\n")
    if len(lines) >= 2 and lines[0].lstrip().startswith("```") and lines[-1].strip().startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return text.strip()


def _strip_terminator(body: str) -> tuple:
    """The refiner must end its reply with an END PROMPT line — the cheap proof
    that the prompt was not cut off at the token cap. Returns (body, complete)."""
    lines = body.rstrip().split("\n")
    if lines and lines[-1].strip().upper() == "END PROMPT":
        return "\n".join(lines[:-1]).rstrip(), True
    return body, False


def parse_refiner_response(text: str) -> dict:
    """Parse the refiner's CRITIQUE / VERDICT / PROMPT sections.

    Anchored on the LAST line-initial PROMPT: marker, with the verdict taken
    from the last strict `VERDICT: IMPROVE|CONVERGED` line before it — so a
    critique that quotes a marker cannot corrupt the saved prompt or fake a
    verdict. `parsed` is False when no PROMPT marker exists; `complete` is
    False when the END PROMPT terminator is missing (likely truncation)."""
    text = text or ""
    prompt_matches = list(_PROMPT_RE.finditer(text))

    if not prompt_matches:
        verdicts = list(_VERDICT_RE.finditer(text))
        verdict = ("CONVERGED" if verdicts and verdicts[-1].group(1).upper() == "CONVERGED"
                   else "IMPROVE")
        body, complete = _strip_terminator(text.strip())
        return {"critique": "", "verdict": verdict, "prompt": _strip_fences(body),
                "parsed": False, "complete": complete}

    pm = prompt_matches[-1]
    verdicts = [m for m in _VERDICT_RE.finditer(text) if m.start() < pm.start()]
    verdict = ("CONVERGED" if verdicts and verdicts[-1].group(1).upper() == "CONVERGED"
               else "IMPROVE")

    body, complete = _strip_terminator(text[pm.end():].strip())
    prompt = _strip_fences(body)

    critique = ""
    cm = _CRITIQUE_RE.search(text)
    if cm and cm.end() <= pm.start():
        end = (verdicts[-1].start() if verdicts and verdicts[-1].start() > cm.end()
               else pm.start())
        critique = text[cm.end():end].strip()

    return {"critique": critique, "verdict": verdict, "prompt": prompt,
            "parsed": True, "complete": complete}


def _build_context(iterations: list, active_v: int, guidance: str) -> str:
    refined = iterations[1:]
    lines = [
        "=== TUNING CONTEXT ===",
        f"Currently serving system prompt v{active_v} ({len(refined)} refinement(s) so far).",
        "User guidance (what to improve now):",
        guidance.strip() or "(none given)",
        "",
        "Iteration history (oldest first):",
    ]
    if not refined:
        lines.append("(no refinements yet — this is the first tuning run)")
    else:
        shown = refined[-HISTORY_CONTEXT_CAP:]
        if len(refined) > len(shown):
            lines.append(f"(…{len(refined) - len(shown)} earlier iteration(s) omitted)")
        for it in shown:
            lines.append(f"v{it['v']} [{it['verdict']}] {_first_line(it['critique'])}")
        last = refined[-1]
        if last.get("critique", "").strip():
            lines += ["", f"Latest critique (v{last['v']}) in full:", last["critique"].strip()]
    return "\n".join(lines)


def serve(state: dict, *, initial_prompt: str, guidance: str,
          version_override: int = -1, max_iterations: int = 0) -> tuple:
    """Decide which prompt version this run uses; halt a finished loop.

    Returns (state, served) where served includes "dirty" — whether the caller
    must persist the state. Auto mode is always dirty (the write drives the
    loop's cache invalidation, see module header); pinned mode goes clean once
    last_served matches, so a production graph caches fully. Raises TunerHalt
    (auto mode only) when converged with unchanged guidance or max_iterations
    is reached."""
    state = dict(state)
    prior_served = state.get("last_served")
    iterations = list(state.get("iterations") or [])
    initialized = False
    if not iterations:
        iterations = [{
            "v": 0, "prompt": initial_prompt, "critique": "(initial)",
            "verdict": "", "guidance": guidance, "parent": None, "ts": _now(),
        }]
        initialized = True
    state["iterations"] = iterations

    last = iterations[-1]
    max_v = last["v"]
    refined_count = len(iterations) - 1
    auto = version_override < 0

    if auto:
        if max_iterations > 0 and refined_count >= max_iterations:
            raise TunerHalt(
                f"Prompt tuner stopped: max_iterations reached ({refined_count}/{max_iterations} "
                f"lifetime refinements). Best prompt is v{max_v}. Raise max_iterations to "
                f"continue, or set version_override={max_v} to serve it without tuning.")
        if last["verdict"] == "CONVERGED" and last.get("guidance", "") == guidance:
            raise TunerHalt(
                f"Prompt tuner stopped: converged at v{max_v}. Change guidance to keep tuning, "
                f"or set version_override={max_v} to serve the final prompt (recording "
                f"stops automatically in that mode).")
        # Consecutive auto serves the Save node never recorded mean Save is
        # muted, bypassed, or on a different tuner_id — nothing is being tuned,
        # and max_iterations (which counts recorded refinements) can never halt
        # it. The count is top-level state so a pinned Load on the same tuner_id
        # cannot wipe it. Reset it and hand serve_prompt a halt marker to save
        # before it raises: a bare raise here cannot persist the reset, and an
        # uncleared counter would re-halt every queue forever — Save runs
        # downstream of this node, so it only clears the count once this node
        # serves again, which the reset now allows on the next queue.
        if state.get("unconsumed", 0) >= _MAX_UNCONSUMED_SERVES:
            state["unconsumed"] = 0
            return state, {"halt": (
                f"Prompt tuner stopped: the Save node has not recorded the last "
                f"{_MAX_UNCONSUMED_SERVES} serves — it is muted, bypassed, or wired to a "
                f"different tuner_id, so nothing is being tuned. Unmute or rewire Save and "
                f"queue again to resume, or set version_override to serve a fixed version.")}
        active = last
    else:
        by_v = {it["v"]: it for it in iterations}
        if version_override not in by_v:
            raise ValueError(
                f"version_override={version_override} does not exist; "
                f"available versions: v0..v{max_v}.")
        active = by_v[version_override]

    state["last_served"] = {
        "version": active["v"], "guidance": guidance,
        "record": auto, "consumed": False, "ts": _now(),
    }
    if auto:
        # Counts serves awaiting a record; record() zeroes it, so it only grows
        # while Save is not keeping up. Top-level so a pinned serve can't wipe it.
        state["unconsumed"] = state.get("unconsumed", 0) + 1

    dirty = True
    if not auto and not initialized and prior_served:
        # Pinned mode records nothing; it writes only to mark the slot
        # non-recording so a downstream Save stays a no-op. Preserve the slot
        # (don't churn, don't clobber) unless it's a CONSUMED auto serve that a
        # stale Save might otherwise re-record. Keep it when:
        #   - it's already a non-recording pinned marker (record False), so a
        #     different pin only churns the file — the two-pin re-billing case; or
        #   - it's a PENDING auto serve (record True, not yet consumed): a Save
        #     downstream must record THAT, not be suppressed by this pin.
        #     Clobbering it is what made a Save-active compare graph record
        #     nothing and halt blaming a Save that was fine.
        consumed_auto = prior_served.get("record") and prior_served.get("consumed")
        if not consumed_auto:
            state["last_served"] = prior_served
            dirty = False

    served = {
        "prompt": active["prompt"],
        "version": active["v"],
        "context": _build_context(iterations, active["v"], guidance),
        "status": (f"serving v{active['v']} of v{max_v} · {refined_count} refinement(s) · "
                   f"last verdict: {last['verdict'] or '—'}"),
        "dirty": dirty,
    }
    return state, served


def record(state: dict, response_text: str) -> tuple:
    """Append the refiner's output as the next version.

    Returns (state, {"version", "verdict", "status", "dirty"}). Guards:
    malformed or truncated responses raise (halting Auto-Queue) instead of
    poisoning the lineage; a pinned serve (version_override >= 0) records
    nothing; a prompt matching any existing version is recorded as CONVERGED
    (covers both "no change" and oscillation); a changed prompt claiming
    CONVERGED is downgraded to IMPROVE — it has never been test-generated."""
    state = dict(state)
    last_served = state.get("last_served")
    iterations = list(state.get("iterations") or [])
    if not last_served or not iterations:
        raise ValueError(
            "No serve record found — run the NS Prompt Tuner Load node in the same "
            "graph (same tuner_id) before Save.")

    if not last_served.get("record", True):
        return state, {
            "version": last_served["version"], "verdict": "",
            "status": (f"version_override active (serving v{last_served['version']}) — "
                       f"nothing recorded"),
            "dirty": False,
        }

    if last_served.get("consumed"):
        raise ValueError(
            "This serve was already recorded — duplicate Save execution or a "
            "tuner_id mismatch between the Load and Save nodes.")

    parsed = parse_refiner_response(response_text)
    if not parsed["parsed"]:
        raise ValueError(
            "Refiner response has no PROMPT: section — refusing to save it as a "
            f"system prompt. Response started with: {_first_line(response_text, 120)!r}")
    if not parsed["complete"]:
        raise ValueError(
            "Refiner response is missing the END PROMPT terminator — likely truncated "
            "at the token cap. Nothing saved; raise the refiner's max_tokens and re-queue.")
    new_prompt = parsed["prompt"].strip()
    if not new_prompt:
        raise ValueError("Refiner response contained no prompt text; nothing to save.")

    by_v = {it["v"]: it for it in iterations}
    served_iter = by_v.get(last_served["version"], iterations[-1])

    verdict = parsed["verdict"]
    matched = next((it for it in iterations if it["prompt"].strip() == new_prompt), None)
    if matched is not None:
        verdict = "CONVERGED"
    elif verdict == "CONVERGED":
        verdict = "IMPROVE"

    new_v = iterations[-1]["v"] + 1
    iterations.append({
        "v": new_v, "prompt": new_prompt, "critique": parsed["critique"],
        "verdict": verdict, "guidance": last_served.get("guidance", ""),
        "parent": last_served["version"], "ts": _now(),
    })
    state["iterations"] = iterations
    state["last_served"] = dict(last_served, consumed=True)
    state["unconsumed"] = 0   # Save recorded — the stall guard's count resets

    note = ""
    if matched is not None and matched["v"] != served_iter["v"]:
        note = f" (matches v{matched['v']} — oscillation)"
    status = f"saved v{new_v} [{verdict}]{note} {_first_line(parsed['critique'])}".strip()
    return state, {"version": new_v, "verdict": verdict, "status": status, "dirty": True}


class TunerStore:
    """Per-tuner_id JSON state files, written atomically. Human-readable.

    Note: state is per-machine — a RunPod install tuning the same tuner_id
    keeps its own independent lineage."""

    def __init__(self, root: str):
        self.root = root

    @staticmethod
    def _slug(tuner_id: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", (tuner_id or "").lower()).strip("-")
        return slug or "default"

    def _path(self, tuner_id: str) -> str:
        return os.path.join(self.root, f"{self._slug(tuner_id)}.json")

    def load(self, tuner_id: str) -> dict:
        path = self._path(tuner_id)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                state = json.load(f)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            raise ValueError(
                f"Prompt tuner state file is corrupt: {path} ({e}). "
                f"Repair or delete it, or switch to a new tuner_id.") from e
        for it in state.get("iterations") or []:
            if "v" not in it or "prompt" not in it:
                raise ValueError(
                    f"Prompt tuner state file has an unexpected schema: {path}. "
                    f"Repair or delete it, or switch to a new tuner_id.")
        return state

    def save(self, tuner_id: str, state: dict) -> None:
        state.setdefault("tuner_id", tuner_id)
        os.makedirs(self.root, exist_ok=True)
        path = self._path(tuner_id)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)

    def signature(self, tuner_id: str) -> str:
        """Cheap change token for IS_CHANGED — file identity, not content."""
        try:
            st = os.stat(self._path(tuner_id))
        except OSError:
            return "absent"
        return f"{st.st_mtime_ns}:{st.st_size}"


def _default_store() -> TunerStore:
    import folder_paths
    return TunerStore(os.path.join(folder_paths.get_output_directory(), "prompt_tuner"))


class NSPromptTunerLoad:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "tuner_id": ("STRING", {
                    "default": "default",
                    "tooltip": "Name of this tuning experiment. Each id has its own state file "
                               "(output/prompt_tuner/<id>.json) and version history. Case and "
                               "punctuation are folded: 'Bakery Sheet' and 'bakery-sheet' are "
                               "the same tuner."}),
                "guidance": ("STRING", {
                    "multiline": True, "default": "",
                    "tooltip": "Rough notes on what to improve next. Changing this re-opens a "
                               "converged tuner and steers the refiner."}),
                "version_override": ("INT", {
                    "default": -1, "min": -1, "max": 100000,
                    "tooltip": "-1 = latest version (tuning mode). 0 = the initial prompt. "
                               "N = serve vN pinned: never halts, Save records nothing, and "
                               "repeat runs are fully cached (rollback / production mode)."}),
                "max_iterations": ("INT", {
                    "default": 12, "min": 0, "max": 10000,
                    "tooltip": "Stop the loop once this many refinements exist for this "
                               "tuner_id (lifetime count, not per-session). 0 = unlimited — "
                               "no spend ceiling on Auto-Queue."}),
            },
            "optional": {
                "initial_prompt": ("STRING", {
                    "multiline": True, "default": "", "forceInput": True,
                    "tooltip": "Seed system prompt (becomes v0 on the first run of a new "
                               "tuner_id; after that the state file owns the lineage)."}),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("system_prompt", "refiner_context", "status")
    FUNCTION = "serve_prompt"
    CATEGORY = "neuralsins/LLM"

    @classmethod
    def IS_CHANGED(cls, tuner_id="default", **kwargs):
        return _default_store().signature(tuner_id)

    def serve_prompt(self, tuner_id, guidance, version_override, max_iterations,
                     initial_prompt=""):
        store = _default_store()
        state = store.load(tuner_id)
        if not (initial_prompt or "").strip() and not state.get("iterations"):
            raise ValueError(
                f"Tuner '{tuner_id}' has no state yet — connect initial_prompt "
                f"(your starting system prompt) for the first run.")
        state, served = serve(
            state, initial_prompt=initial_prompt, guidance=guidance,
            version_override=version_override, max_iterations=max_iterations)
        if "halt" in served:
            # The stall guard cleared its count in `state`; persist that before
            # halting so the next queue (once Save is fixed) serves afresh
            # instead of re-halting forever.
            store.save(tuner_id, state)
            raise TunerHalt(served["halt"])
        if served["dirty"]:
            store.save(tuner_id, state)
        return (served["prompt"], served["context"], served["status"])


class NSPromptTunerSave:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "tuner_id": ("STRING", {
                    "default": "default",
                    "tooltip": "Must match the NS Prompt Tuner Load node's tuner_id."}),
                "response": ("STRING", {
                    "forceInput": True,
                    "tooltip": "The refiner LLM's response "
                               "(CRITIQUE / VERDICT / PROMPT … END PROMPT)."}),
            },
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("status",)
    FUNCTION = "save_iteration"
    OUTPUT_NODE = True
    CATEGORY = "neuralsins/LLM"

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def save_iteration(self, tuner_id, response):
        store = _default_store()
        state = store.load(tuner_id)
        state, saved = record(state, response)
        if saved["dirty"]:
            store.save(tuner_id, state)
        return {"ui": {"text": [saved["status"]]}, "result": (saved["status"],)}


NODE_CLASS_MAPPINGS = {
    "NSPromptTunerLoad": NSPromptTunerLoad,
    "NSPromptTunerSave": NSPromptTunerSave,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSPromptTunerLoad": "NS Prompt Tuner Load",
    "NSPromptTunerSave": "NS Prompt Tuner Save",
}
