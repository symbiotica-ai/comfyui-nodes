# comfyui-nodes — agent instructions

## How to answer him

**Lead with the action he has to take, in bold, on the first line.** He is at
the canvas waiting to see the change, and digging for "do I reload or restart?"
is the whole cost of a long answer. One of:

- **Hard-reload the Comfy tab.** — `web/js` only
- **Restart ComfyUI.** — anything under `py/`, and a new node needs it to
  register at all
- **Nothing to do.** — tests, docs, a commit, a release he has not pulled yet

Then keep it SHORT. A few lines. What changed and, only if it is not obvious,
the one reason it was broken. No walls of text, no restating the task, no
listing what you verified unless he asked. Explanations he did not ask for are
the thing to cut, not the detail he did.

**His feedback is a patch instruction, not a brief for a new version.** Take the
last thing he accepted, change the part he named, leave every other line alone.
A rewrite drops requirements he gave earlier and is not repeating now. If the
fix really needs restructuring, say so in one line and ask first.

**Never close a delivery with a rationale.** No "why it fixes your case", no
"this works because" after handing over a prompt, a patch or a file. He has
asked for this repeatedly: the claim is a prediction he has not tested, and it
reads as selling him something that often does not work. Hand over the artifact
and stop. A genuinely load-bearing reason goes in one clause BEFORE the
artifact, never as a closing paragraph.

**Answer the question he asked, and stop.** "Is the model downloaded?" is
answered by yes and a size. Do not carry a finding from an earlier step into
every later message, and never offer to act on something he has not mentioned —
noticing a big file is not an invitation to propose deleting it. A side
observation goes in one line, once, or not at all.

Never restart his ComfyUI yourself without asking first — the AskUserQuestion
button, every time, however urgent it feels.

## MANDATORY: load the ComfyUI skill for your task before writing code

This repo vendors the ComfyUI dev skills in `.claude/skills/`. Before creating
or modifying anything listed below, load the matching skill with the Skill
tool — do not work from memory:

| Touching | Load first |
|---|---|
| Python node classes (`py/pipeline/nodes.py`, `py/*.py` nodes) | `comfyui-nodes-dev`, plus `comfyui-node-inputs` / `comfyui-node-outputs` for schema work |
| Caching, `fingerprint_inputs`, `IS_CHANGED`, validation, lazy inputs | `comfyui-node-lifecycle` |
| JS extensions, DOM widgets, panels (`web/js/*.js`) | `comfyui-node-frontend` |
| Dynamic inputs, type matching, node expansion | `comfyui-node-advanced` |
| Tensors, IMAGE/MASK/LATENT handling | `comfyui-node-datatypes` |
| `pyproject.toml`, `__init__.py`, registry publishing | `comfyui-node-packaging` |
| Building or editing workflow JSON | `comfyui-workflow-builder`, `comfyui-api` |

One skill load per area per session is enough. Repo-specific patterns
(existing panels in `web/js/order_pipeline.js`, the v3 schemas in
`py/pipeline/nodes.py`) take precedence over skill examples when they
conflict — the repo has already solved ComfyUI's traps its own way.

## Node panels must stay resizable — read this before touching `web/js`

A DOM-widget panel (`node.addDOMWidget`) **must not define `computeSize`**.
LiteGraph builds a node's MINIMUM height by summing its widgets and prefers
`computeSize` over `computeLayoutSize`, so anything `computeSize` returns
becomes a floor the user cannot drag past — answer it with the content and the
node will not shrink below its content; answer it with "the space below me"
and the node can never shrink at all. Both shipped here, and both cost days.

The shape that works, in every panel in this pack (`pick.js`, `prompt_book.js`,
`asset_focus.js`, `order_pipeline.js`):

- no `computeSize` on the DOM widget
- `getMinHeight: () => <small constant>` — never reads `node.size`,
  `scrollHeight` or `last_y`
- the element fills its box: `height:100%` + `overflow:auto`, content scrolls
- no render/refresh path calls `node.setSize` with a height; a starting height
  is set once, only for a node that has none

Full mechanism, the layout functions and a checklist:
`.claude/skills/comfyui-node-frontend/api-reference.md` → "Sizing a DOM widget,
and keeping the node RESIZABLE".

## Repo ground rules

- Tests: run `pytest` from the repo root (tests stub `comfy_api`; see
  `tests/comfy_api_stub.py`). All tests must pass before a PR.
- JS and Python are parallel implementations of the same draw/compose rules in
  several places (template editor, prompt book) — change both in one commit.
- Versioning is calendar-based (`2026.M.N` in `pyproject.toml`); bump happens
  at release time, not per PR.
- Deploys: the pack is registry-managed on desktop installs and volume-mounted
  on Modal. Never leave versioned or backup `.js`/`.py` copies in the tree —
  ComfyUI loads every file under `web/`, and orphans register extensions twice.
