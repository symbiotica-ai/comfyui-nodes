# comfyui-nodes — agent instructions

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
