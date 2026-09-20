# comfyui-nodes — agent instructions

## How to answer him

**Lead with the action he has to take, in bold, on the first line**, and let
that line be the whole message unless it carries something he cannot read off
the canvas (a new widget's name, a value he has to type):

- **Hard-reload.** — `web/js` only
- **Restart Comfy.** — anything under `py/`, and a new node needs it to
  register at all
- **Nothing to do.** — tests, docs, a commit

Run `./push.sh` before that line. Never restart his ComfyUI yourself — ask with
the AskUserQuestion button, every time, however urgent it feels.

No summary of what changed, no "why this fixes your case" after the artifact,
no post-mortem of what failed before, no rationale paragraph at the end. Answer
the question he asked and stop: "is the model downloaded?" is answered by yes
and a size. A side observation is one line, once, or not at all.

**His feedback is a patch instruction, not a brief for a new version.** Take the
last thing he accepted, change the part he named, leave every other line alone.
A rewrite drops requirements he gave earlier and is not repeating now. If the
fix really needs restructuring, say so in one line and ask first.

**Never launch Chrome.** Not headless, not through a script. Browser automation
lives in the Browser pane: `preview_start {url: ...}`, then `javascript_tool`
against `window.app` and `computer` for screenshots.

## Verify before you say reload

Unit tests are not verification here, and shipping on them has cost him days.
Two places to run the thing, both reachable from this machine.

**Local ComfyUI** — `~/ComfyUI-Installs/ComfyUI (1)/ComfyUI`, this repo
symlinked in as `custom_nodes/symbiotica`, with the packs his canvas uses
(KJNodes, rgthree, easy-use, layerstyle, controlnet_aux, was-ns,
custom-scripts, ComfyLiterals). Start it with that install's own
`.venv/bin/python main.py`, open `http://127.0.0.1:8188` in the Browser pane,
and click the node: the panel renders, the handler fires, the queue runs, the
widget values survive a save and reopen. ONE instance, on whatever frontend
that install ships. Never start a second copy on another frontend version and
never pin one with `--front-end-version` or `--front-end-root`: the code has to
hold on ANY version, so a version difference is something to code around — the
links table as a Map or an object, a widget's value as an accessor or a plain
field — not something to prove twice. A spare, without touching the one he has
open:

    .venv/bin/python main.py --port 8189 --cpu --disable-auto-launch \
      --user-directory <tmp> --output-directory <tmp>

Drive either one headless with playwright (`python3 -m playwright`, chromium is
already installed) — `page.evaluate` against `window.app` reads the graph, and
`page.mouse` does a real drag onto a slot. His own workflows come down with
`./verify.sh api "/api/userdata/workflows%2F<name>.json"`, so a bug on his
canvas can be reproduced here with his file rather than a made-up one.

**His live editor** — `./verify.sh`, which reads the sandbox host and its
canvas key from his Modal token (`~/.modal.toml`, app `symbiotica-comfy`,
environment `dev`). No cURL to paste, and it queues nothing:

- `./verify.sh` — every `web/js` file, served against the tree: `ok`, `STALE`
  (the push has not landed in the sandbox) or `MISSING` (the sandbox never got
  the file), then the nodes that failed to register
- `./verify.sh node <Class>` — the schema the editor actually reports
- `./verify.sh js <file>` — one file, with the first line that differs

`MISSING` is the Volume sync, not the push: it updates files a running sandbox
already has and never creates a new one, so a new node's canvas code goes
INSIDE an existing `web/js` file. The gateway also 404s a file it does hold now
and then, so the check asks twice before it says MISSING — confirm one with
`./verify.sh js <file>` before acting on it.

When something could not be run, say what was tested and what was not, and do
not use the word "fixed".

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

One skill load per area per session is enough. Repo-specific patterns (the
panels in `web/js/asset_focus.js` and `web/js/recipes.js`, the v3 schemas in
`py/pipeline/nodes.py`) take precedence over skill examples when they
conflict — the repo has already solved ComfyUI's traps its own way.

## Node panels must stay resizable — read this before touching `web/js`

A DOM-widget panel (`node.addDOMWidget`) **must not define `computeSize`**.
LiteGraph builds a node's MINIMUM height by summing its widgets and prefers
`computeSize` over `computeLayoutSize`, so anything `computeSize` returns
becomes a floor the user cannot drag past — answer it with the content and the
node will not shrink below its content; answer it with "the space below me"
and the node can never shrink at all. Both shipped here, and both cost days.

The shape that works, in every panel in this pack (`asset_focus.js`,
`recipes.js`, `order_source.js`, and the two file browsers below):

- no `computeSize` on the DOM widget
- `getMinHeight: () => <small constant>` — never reads `node.size`,
  `scrollHeight` or `last_y`
- the element fills its box: `height:100%` + `overflow:auto`, content scrolls
- no render/refresh path calls `node.setSize` with a height; a starting height
  is set once, only for a node that has none

Full mechanism, the layout functions and a checklist:
`.claude/skills/comfyui-node-frontend/api-reference.md` → "Sizing a DOM widget,
and keeping the node RESIZABLE".

## The two file browsers — Prompts and Control Image

Both nodes are one DOM-widget panel: a tree of the folder on the left, a pane
on the right, the actions as icons. **The chrome is shared and lives in
`web/js/browser_chrome.js`** — `sidebarShell` (the two panes, the draggable
divider, the fold-to-a-rail toggle), `treeRow`, `walkTree`, `iconButton` and
the drawn `ICON` set. Change it there and both nodes follow; a second copy in
one node is how they drift. The width and the fold ride on `node.properties`,
never on widgets, which would shift the saved values of every workflow already
holding the node.

- The widgets the tree drives stay on the node and are `hideWidget`-ed:
  `folder`, `file` and `text` on Prompts, `image` on Control Image. They are
  what Python reads and what a saved workflow restores — removing one shifts
  every value after it. Prompts' `text` is a DOM widget, so its element is
  hidden too (`hideTextWidget`).
- Prompts edits in its own `<textarea>`; ⌘S saves. Control Image draws a
  thumbnail per row from `pick-thumb` (6 ms and 4 KB each, `Cache-Control`
  600 s, `loading="lazy"`, and rows exist only for folders you expanded) and
  the pick full size from `local-image`.
- A name is drawn with `font-feature-settings:'calt' 0` — Inter renders `1x1`
  as `1×1`, which is not what the folder is called.
- Files dragged from the desktop onto the tree upload into the folder they
  land on. Nothing is overwritten: a name already taken becomes `-2`.

**The path the node is given IS the folder it browses.** `control-images` and
its mkdir/rename/delete/upload routes used to refuse a folder outside
`declared_roots`, so a project folder had to be declared in Settings first —
"the node should browse the files from the path i input regardless of whether i
am on modal, local, etc" (2026-09-19). The routes now register whatever they
are handed, which is exactly what queueing the node already did. What decides
what a request can touch is CONTAINMENT: `inside_library` resolves every name
against the folder it named and refuses anything that climbs out, and
`tests/test_routes_control_images.py` is where that is held. The Prompts
routes never had the allowlist. Do not put it back.

## Set Hub / Get Hub — one node, many named constants

`web/js/find_node.js`, registered on the canvas alone: no Python, nothing in
the queued prompt. They are VIRTUAL nodes, and the frontend resolves them away
through `resolveVirtualOutput(slot)` then `getInputLink(slot)`, both indexed by
OUTPUT SLOT — that per-slot indexing is what lets one node stand in for twenty
KJNodes pairs, and it is in 1.48.7 as well as 1.52.7.

- **A constant's name is the slot's `label`**, not a widget value. The Set Hub
  draws one text row per named slot (`name_1`, `name_2`, … as widget names —
  they must be UNIQUE, the renderer keys on them, and two rows called `STRING`
  drew one row twice) and those rows are a VIEW: `serialize_widgets = false`,
  values written back from the slots on every rebuild, slots are what a saved
  workflow restores. So none of the widget-shift traps above apply.
- Renaming on the Set side carries every Get Hub pulling the old name
  (`repointGetters`). A Get slot whose name nothing publishes goes red.
- Names are ONE flat namespace shared with KJNodes' `SetNode`, so a Get Hub
  pulls a name off a plain Set node. Not the reverse: KJ's `GetNode` matches
  `type === 'SetNode'`.
- Wiring a slot names it after the output it came from, except when that name
  is a scalar type (`STRING`, `INT`, `FLOAT`, …) — then the source node's title
  answers, because STRING, STRING_2, STRING_3 is not a set of names. `MODEL`,
  `VAE`, `IMAGE` keep their own.
- Every hub ends in exactly one empty `+` slot, re-asserted on draw because the
  frontend's own "Remove Slot" fires no event the node can hear.
- **A Set Hub is a GROUP and its TITLE is the group's name** — `settings-01`,
  `paths`, `models`. The Get Hub's picker lists the groups above the individual
  names, and taking one loads every name on that hub at once. The group a Get
  is following rides on `node.properties.symbiotica_group` (serialises, and
  survives a retitle). Picking a group REPLACES what the node holds, wires and
  all — the node becomes that group, it does not accumulate the last one plus
  this one — and the title follows, from the stock title or from the group it
  was showing a second ago. A title typed by hand is his and stays. A followed group is re-asserted on draw, so a name added to
  the Set later arrives — APPENDED, never inserted, because a wire holds on to
  a slot's INDEX. A name that leaves the group leaves the Get too, unless a
  wire is on it: that one stays and goes red. "Remove unused slots" stops the
  hub following, or every slot it removed would come back on the next draw.
- A name row on the Set Hub holds no value of its own: `value` and `label` are
  own properties reading the slot it sits against, and writing `value` renames
  that slot. The frontend's widget store keys a remembered value by widget
  NAME and hands any widget under a name it has seen the state it already
  holds — two rows called `STRING` were handed ONE state between them and drew
  the same name twice. Nothing to write back means nothing to drift.

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

**`serialize = false` on a widget shifts every value after it.** Proven on
1.48.7 and 1.52.7 (2026-09-18): saving writes ONE ENTRY PER WIDGET, a button's
being `null`, and loading pairs those entries against the widgets that do NOT
carry the flag. `📁 Read folder` carried it in the middle of the list, so every
reopen moved `ref` onto the button's `null` and `slots` onto ref's string — the
Asset Recipe's table came back empty because `slots` was `null`. The flag is
only safe on the widgets at the very END of the list (the Asset Recipe's own
slot widgets, Studio Library's summary). `{ serialize: false }` passed in a
widget's OPTIONS is a different thing and harmless: neither side honours it.

**A widget re-created under a name the node has carried keeps the OLD value.**
ComfyUI remembers widget values by name, so `addWidget(kind, name, value, …)`
hands back a widget holding what that name held before and drops the value
passed. Anything that rebuilds widgets (`rebuildWidgets` in `asset_recipe.js`)
must write `widget.value` after adding it.

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

Dragging a widget onto the empty slot writes the row, grows the next slot and
adds the widget — verified with a real mouse drag on frontend 1.48.7 on
2026-09-18. It looked broken because the `slots` string was arriving as `null`
(the shift above), which left `readSlots` empty and made every wire land on a
slot the table did not know about.

## Repo ground rules

- Tests: run `pytest` from the repo root (tests stub `comfy_api`; see
  `tests/comfy_api_stub.py`). All tests must pass before a PR.
- JS and Python are parallel implementations of the same draw/compose rules in
  several places (template editor, prompt book, the recipe slot rule in
  `web/js/recipes.js` and `py/_recipes.py`) — change both in one commit.
- Versioning is calendar-based (`2026.M.N` in `pyproject.toml`); bump happens
  at release time, not per PR.
- **Every node declares `Symbiotica` as its category — one folder, no
  sub-folders.** The menu is case-sensitive, so `Symbiotica/Images` beside
  `symbiotica/pipeline` drew two, and a node adopted from another pack drew a
  third. A remote RNP node takes it from `rnp_protocol.CATEGORY` rather than
  the descriptor's. `test_every_node_is_in_the_one_folder` holds it. Display
  names are moving to `Node Name (Symbiotica)`; ten are still on older shapes.
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
