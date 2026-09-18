# comfyui-nodes — agent instructions

## How to answer him

**Lead with the action he has to take, in bold, on the first line.** He is at
the canvas waiting to see the change, and digging for "do I reload or restart?"
is the whole cost of a long answer. One of:

- **Hard-reload.** — `web/js` only
- **Restart Comfy.** — anything under `py/`, and a new node needs it to
  register at all
- **Nothing to do.** — tests, docs, a commit, a release he has not pulled yet

Two words. Not "open Manager once, then Manager's Restart": he called that
token-wasting, and he was right. Before either line, run `./push.sh` — it puts
the working tree on the Modal Volume his editor mounts (see Repo ground
rules); the registry release is for when he asks for one.

**The action line is usually the WHOLE message.** Default to one line. Add a
second only when it carries information he cannot get from the canvas — a new
widget's name, a value he has to type, a file he has to open. Never a summary of
what changed, what you verified, what failed before, or what you learned: he
reads the message to find out whether to reload, and everything else is in his
way. "it's really fucking annoying" is the standing feedback on this.

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

**No post-mortems.** Never explain what you got wrong, why the last attempt
failed, or what you learned. He does not care and has said so. Fix it, say the
action line, stop. This includes the honest-sounding version ("what I got wrong
was…") — it is still a paragraph he has to read to find out whether he can
reload.

**Answer the question he asked, and stop.** "Is the model downloaded?" is
answered by yes and a size. Do not carry a finding from an earlier step into
every later message, and never offer to act on something he has not mentioned —
noticing a big file is not an invitation to propose deleting it. A side
observation goes in one line, once, or not at all.

Never restart his ComfyUI yourself without asking first — the AskUserQuestion
button, every time, however urgent it feels.

**Never launch Chrome.** Not headless, not through a script, not through the
old `.cs/local/browser` harness. He has disabled browser automation outside the
Browser pane on purpose, and going around it with a node script is not a
loophole. Verify in the pane: `preview_start {url: "http://127.0.0.1:8000"}`,
then `javascript_tool` against `window.app` and `computer` for screenshots.

He works on the **Modal editor** (the Symbiotica platform's ComfyUI sandbox),
not a local install — "there is no local comfy, we work on modal". Nothing
here can be verified against his canvas from this machine; say what was
tested (unit tests) and what was not.

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

The shape that works, in every panel in this pack (`pick.js`,
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

## A value that arrives on a wire

He wires almost everything through KJNodes **Set/Get** nodes. A GetNode's only
widget holds the NAME of the constant, not its value, so a canvas-side walk that
reads its widget gets `$$controlnet` and points the panel at a folder called
that. **`nodeOutputString` now hops the pair** (2026-09-18): the SetNode of that
name is on the canvas, so the walk finds it in the root graph and follows what is
wired INTO it, and answers `""` — never the name — when there is no Set to
follow. A value that only exists at RUN time (a prompt, a rendered path) still
needs the run.

The shape that works, in `prompts.js` and `control_image.js`:

- the node is an **output node** (`is_output_node=True`, or `OUTPUT_NODE = True`
  on a V1 class), so he can queue it alone with nothing wired downstream
- `execute`/`load` pushes what it actually received —
  `_push("symbiotica.<node>", {"node_id": ..., "path": ...})`, needs
  `unique_id` hidden — and the extension stores it in
  `node.properties.symbiotica_ran_path`, which serialises with the workflow
- the panel's resolver prefers a TYPED widget, then the run's value, then the
  static walk; the walk only ever stands in until the first run

**`VALIDATE_INPUTS` must not refuse an input that arrives on a wire.** It runs
before anything executes, so a wired widget is EMPTY there — validating it
rejects every node on his canvas with "a node rejected one or more input
values". Return `True` for the empty case and let execution be where a bad
value fails.

**A button widget shifts every widget saved after it.** `📁 Read folder` sets
`readBtn.serialize = false`, and the save wrote `null` for it anyway while the
load skips it — so on reopening, every value after the button lands one widget to
the LEFT (`ref` takes the `null`, the next widget takes `ref`'s string). A text
widget holding `null` then breaks the whole queue: pysssss's `presetText` calls
`.replace` on it inside `graphToPrompt`, and no node runs. Suspected, not yet
proven — see ROADMAP's Asset Recipe threads.

**A route the canvas fetches has to exist.** `/symbiotica/local-image` was
deleted with the obsolete nodes in `0a4f14d` while two panels still called it,
and every preview outside ComfyUI's `input/` 404'd for weeks with nothing in
the tests to catch it — the allowlist was tested, the handler was not.

## What a Recipes slot captures

A painted slot node is captured whole, not by its first widget
(`liveSlotValues`, `web/js/recipes.js`):

- a widget fed by a wire is left out at EVERY widget count (the wire is the
  value; recording the empty box writes that emptiness into every recipe)
- one widget left → the value itself
- more than one → a dict of every widget BY NAME
- a subgraph → its promoted inputs, wired ones left out
- rgthree's **Fast Group Bypasser** → one entry per GROUP TITLE. Every row
  widget is named `RGTHREE_TOGGLE_AND_NAV` and holds `{toggled}`, so by name
  they are one widget; loading calls `widget.toggle(bool)`, because assigning
  `.value` is inert and the group never moves.
- a key in the project file with no slot on the canvas is not a row: it leaves
  the table on sight and the file on the next `save project`.

## Asset Recipe — Asset Focus plus wired widget values

`SymbioticaAssetRecipe` (py/pipeline/nodes.py) SUBCLASSES `SymbioticaAssetFocus`
and builds its schema from the parent's, so an output added to Asset Focus lands
on both in the same order. After the focus outputs come `slot_1..slot_16`,
`io.AnyType` (`*`) — ComfyUI has no dynamic outputs, so the node declares a fixed
set and the canvas grows INTO them. `execute` calls `super().execute(**kwargs)`
(never the parent by name, or the focus panel's push goes out under the wrong
class) and appends the slot values.

The slots themselves live in `web/js/asset_recipe.js`:

- the whole table is ONE hidden `slots` string input (JSON), written by the
  canvas and read by Python; the per-slot widgets are `serialize = false`, so
  adding a slot never shifts another widget's saved value
- an output's NAME is its position (`slot_3` is the third row) and its LABEL is
  what you read; only ever append, and renumber after any removal
- `web/js/asset_focus.js` serves both classes through `FOCUS_CLASSES` — the
  panel, the selection widgets and the `symbiotica.focus` push are shared

**Dragging a widget onto the empty slot does not work on his canvas yet** (as of
2026-09-18): the wires land, no row is written, no widget appears. Unit tests
cover the handler; nothing has been verified on the Modal canvas.

## Repo ground rules

- Tests: run `pytest` from the repo root (tests stub `comfy_api`; see
  `tests/comfy_api_stub.py`). All tests must pass before a PR.
- JS and Python are parallel implementations of the same draw/compose rules in
  several places (template editor, prompt book, the recipe slot rule in
  `web/js/recipes.js` and `py/_recipes.py`) — change both in one commit.
- Versioning is calendar-based (`2026.M.N` in `pyproject.toml`); bump happens
  at release time, not per PR.
- Deploys: the pack is registry-managed on desktop installs and volume-mounted
  on Modal at `symbiotica-comfy-custom-nodes:symbiotica/`. `./push.sh` uploads
  `py/` and `web/` there and removes remote files the tree no longer has; the
  editor syncs that Volume after any ComfyUI Manager request, so a push lands
  in a running editor once Manager is opened. Cut a registry release
  (version bump + CHANGELOG + `gh release create`, which triggers
  `publish_action.yml`) only when asked or for a non-Modal install. Never
  leave versioned or backup `.js`/`.py` copies in the tree — ComfyUI loads
  every file under `web/`, and orphans register extensions twice.
- Vocabulary he insists on for the Recipes node: a **project** is the file
  (one per game, `imperia-bakery`, resolved from the open workflow), a
  **recipe** is one asset type in it (`appliance-1x2`), **shared** is what
  every recipe takes. Buttons are two words naming what they act on
  (`new project`, `capture recipe`). Node inputs are Comfy widgets, wirable,
  never DOM fields, and never the same thing twice. A recipe slot is a node
  painted the colour typed in the node's `match_color` input, its title the
  slot name — a node never retitled goes under its type's name, so PAINTING is
  the whole of what makes a slot (`recipe:<key>` titles still work). The slot
  list is read from the ROOT graph, never from the subgraph the canvas is
  showing. The node's contract is `docs/recipes-contract.md`; adding an input to a node
  shifts the widget values of every workflow already saved with it, so a new
  input lands on an old canvas holding the value of the widget that used to
  sit in its place.
