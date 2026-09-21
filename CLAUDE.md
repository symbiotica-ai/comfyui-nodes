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
- **The Set side and the Get side are in sync at all times.** Every way the Set
  side can change carries: **retitling the node FEEDING a slot renames the slot**
  (the slot was named after it, and a slot's `name` holding what the wire called
  it while `label` holds what it is called is the record that he took the name
  over by hand — those two are among the eleven fields a slot saves, where
  anything else hung on the slot is dropped on the next reopen; a slot carrying
  the `_2` a clash gave it is already following, and is left alone), a slot
  renamed renames it on every Get, a name added
  to a group arrives on every Get following it, a Set Hub RETITLED carries its
  followers (the group is remembered by the Set Hub's ID as well as its title,
  and the title is healed on the way past), a name that leaves the canvas takes
  its Get slots and their wires with it. The one thing never removed is a slot
  whose name is published somewhere the lookup cannot reach — another subgraph:
  that one goes red, because deleting over a blind spot would take his wiring.
- **A wire taken off a Set Hub input takes the slot and its row with it** — a
  name with nothing behind it publishes nothing, and the Gets pulling it lose
  their slots on the next draw. The removal is deferred by a tick and re-checks the SLOT OBJECT, never
  its index: rewiring a slot is a disconnect and a connect back to back, and
  the slot that has a wire again by the time the tick comes is being rewired,
  not abandoned.
- **A hub's title keeps the side it is on**: `Set _paths` and `Get _paths`, never
  two nodes carrying one name. The word is put in front of a title he types
  (`groupNameOf` / `keepSideInTitle`), the stock titles already say it, and the
  GROUP's name is the title without it — so `Set _paths` and `_paths` name the
  same group and a Get reading it is titled `Get _paths`.
- **A Set Hub is a GROUP and its TITLE is the group's name** — `settings-01`,
  `paths`, `models`. The Get Hub's picker lists the groups above the individual
  names, and taking one loads every name on that hub at once. The groups a Get
  follows ride on `node.properties.symbiotica_group` — a LIST of titles beside
  a list of Set Hub ids, which serialises, survives a retitle, and reads a
  workflow saved before the list as its one bare string. **Every pick ADDS**
  (2026-09-21): a group lands beside whatever the node already holds and is
  followed as well, a single value lands beside it and changes nothing about
  what is followed — "i might want a group but also a few others from another
  group or solo values". Nothing a pick does removes a slot or cuts a wire:
  what leaves a Get Hub is what he takes off it ("Remove unused slots", the
  frontend's own "Remove Slot") or a name that has left the canvas. The title
  is the followed groups joined by `+`, then `+N` for whatever is carried
  beside them (`titleForGet`), and only ever overwrites a title the node wrote
  itself. A title typed by hand is his and stays. A followed group is
  re-asserted on draw, so a name added to the Set later arrives — APPENDED,
  never inserted, because a wire holds on to a slot's INDEX. A name that leaves
  the group leaves the Get too, unless a wire is on it or something else on the
  canvas still publishes it — a name picked on its own is exactly that, and it
  stays. "Remove unused slots" stops the hub following every group it followed,
  or every slot it removed would come back on the next draw.
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

**A category emptied by picking an asset still has to name a recipe.**
`chooseAsset` (`web/js/asset_focus.js`) sets `category` to `""` on purpose — with
one asset chosen the narrowing decides nothing, and a stale one is a hard
refusal at queue time. So the Recipes resolver falls back to the picked asset's
OWN row: `assetRecipeOf(node, assetName)` reads the order the node already
holds (`_symEvents`, no request and no run) and answers
`categoryRecipeOf` — `Gargoyle Drink Machine` names `appliance-1x2`. Without
it, picking an asset left the `recipe` wire holding null and the node stored
nothing, silently (2026-09-21).

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

## The Task node — one month, two ways to read it

`taskPanel` in `web/js/asset_focus.js` (not a new file: a new `web/js` file
never reaches the Modal sandbox). The tree is built by `taskRows` as one flat
list of row objects — never `walkTree`, which derives parentage from a
slash-joined key, and his sheet holds names with slashes in them.

- **Two groupings, one button in the head** (`ICON.layers`). By EVENT is the
  sheet's shape: month, event, category, asset. By CATEGORY drops the event
  level and gathers every asset of a type across the whole month — "so it's
  easier for me to test 10 decorations for example without skipping through
  events that contain that type of asset" (2026-09-21). The grouping rides on
  `node.properties[TASK_GROUP]`, like the sidebar width and the fold: a widget
  would shift the saved values of every workflow already holding the node.
- **A row carries its event, and taking one moves the node there.** In the
  category view an asset row is labelled `<name> · <event>`, `chooseAsset`
  hops through `chooseFound` when the event differs, and `chooseCategory` hops
  through `eventForCategory`. Both are the same rule: the queue builds ONE
  event, so a pick from the month has to say which.
- **Picking a category draws its first asset** (`previewRow`), rather than
  "Pick an asset in the tree." on a node listing twenty. It is a PREVIEW, not
  a pick: no widget moves, `runs N` is still the category's count, and the
  prompt header names the asset so it is not read as the category's. Clicking
  a reference tile is what turns it into a pick.
- `runList` is what the node would EMIT — the held event's assets narrowed by
  `category` — and is read off the parse, never off the rows on screen: a
  category has to be open to have asset rows, and counting those read `runs`
  as nothing beside a tree full of categories.

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

## Storing a recipe — the table, and the two sides that must agree

A project is a small JSON file in `user/default/recipes/`, bound to ONE base
workflow by path and named after it. It holds `template` plus `shared` plus one
block per recipe, keyed by the painted node's TITLE — and NOTHING else: `output`
and `workflow_prefix` were two more knobs for one rule and are gone, ignored in
any older file. Capture reads the canvas and stores only what differs from
shared; load layers shared under the recipe and writes it back; `generate
workflows` reads the BASE WORKFLOW from disk and writes one real workflow per
recipe, BESIDE the base and named `<project>-<recipe>.json` — the base is in
the name because `appliance-1x2.json` sitting next to its source says nothing
about which source made it. Both halves go through the same slug (`recipeSlug`
on the canvas, `slugify` in `py/_recipes.py`, parallel and changed together):
lowercase, dashes, no spaces. The recipe is a set of DIFFERENCES against one graph, which is what lets
a structural change reach every recipe at once — snapshots of the whole graph
were considered on 2026-09-21 and refused for that reason.

Everything below is a place the canvas and the server had to be taught to say
the same thing. Each one failed silently first.

- **`widgets_values` is positional and is regularly LONGER than the inputs the
  graph declares.** ComfyUI draws widgets nothing declares — a seed's
  `control_after_generate`, a node's own DOM panel — and a saved workflow
  records their values with no name. A KSampler is six declared names against
  seven values, which refused every recipe in the project. `_widget_positions`
  (`py/_recipes.py`) reconstructs the layout by MERGING two known subsequences:
  the declared input names in order, and the captured keys, which the canvas
  wrote in widget order with the wired ones left out. The merge only counts if
  it lands on exactly as many widgets as the node holds. Its limit, written
  down in the tests: an undeclared widget and a typo are indistinguishable, so
  the COUNT is the only discipline left.
- **A node never retitled is keyed by the name the CANVAS DRAWS on it**, which
  for a custom node is its display name (`Control Image`), not its class
  (`SymbioticaControlImage`). A saved workflow stores no title for one, so
  `recipe_slots`/`template_slots`/`apply_recipe`/`generate` all take a
  `display` map and `py/recipe_node.py` builds it from ComfyUI's
  `NODE_DISPLAY_NAME_MAPPINGS`. Without it the server keyed by class, the value
  had no slot to land in, and the next save DELETED it from the project.
- **`state.slots` follows the CANVAS; `state.templateSlots` is what the saved
  template file declares.** The difference between them is what `generate`
  would drop, and the status line names it — that is how a workflow he has
  painted but not saved announces itself instead of losing the keys.
- **Picking a recipe in the sidebar loads it AND points the wire at it.**
  `pointWireAt` walks back from the `recipe` input (`focusBehind`, the same
  hops as `nodeText`) to the Task / Asset Focus node, sets its `category` to
  the label whose slug is the recipe, and clears `asset` and `ref` — the same
  act as clicking that category in the Task tree. Without it, `auto` read the
  old name on the next repaint and pulled the canvas straight back. Three
  things it must keep doing:
  - **The labels come from `monthCategories(node)`, never from the widget's
    options.** Only Asset Focus makes `category` a combo (`comboify` runs in
    `focusPanel`, which serves `FOCUS_CLASSES` alone); on Task it is a plain
    hidden widget its tree writes. Reading options there found no label, the
    category never moved, and auto loaded the old recipe back over the pick.
  - **It moves `feature` too** (`eventForCategory`). A run is ONE event —
    the queue picks it by `feature`, then narrows by `category` — so a
    category the held event does not have is `runs 0` and a refusal naming
    the event it looked in. The sidebar lists the whole MONTH's categories,
    so a pick has to carry its event.
  - **The pane goes on following the wire afterwards.** A pick POINTS the
    wire, so the two agree from that moment and `autoSelected` is re-armed
    (`activeColumn() === column`). Comparing the click against where the wire
    WAS disarmed the follow on every click, and the pane then sat on one
    recipe while the Task walked through the others. A wire that moves to a
    name this project has no row for does not end the follow either — the
    pane waits for the next name it can show.
- **Every category the parsed MONTH holds is a sidebar row**, marked with an
  icon while nothing is stored for it (`syncCategories`, `state.offered`). A
  marked row is a row, not a recipe: clicking it points the wire, loads
  `shared` and writes NOTHING — `choose` adopts `auto.last` so auto does not
  read the wire as a name it has never seen and capture the canvas on the
  spot, which would write one recipe per click down the list. It becomes a
  recipe the moment something is captured into it, and `tableToProject` is
  where an offered-and-empty column is kept out of the file. `autoAdopt` /
  `autoDecision` are handed `realColumns()`, not every column, so the WIRE
  landing on an uncaptured category still captures the canvas into it —
  unchanged, and the one path that does write on its own.
- **A recipe that holds nothing writes nothing, and that is not an error.**
  "No recipe slots on this canvas" is for a `match_color` that matches
  nothing; with `shared` empty it fired on every category he had not been
  through yet, on the one click meant to START a recipe.
- **The column a switch writes back is the one the CANVAS is on
  (`auto.last.name`), never the one on screen.** With `auto` on, the wire loads
  its own recipe while the pane shows another; writing the picked column is how
  `appliance-1x2` came to hold `food`'s values on his canvas (2026-09-21).
- **`auto`'s own save RECONCILES the pane, never rebuilds it** (`renderAll`,
  not `renderFull`). It fires a second after an edit, which is while he is
  still typing the next one, and a rebuild there is the caret gone.
- After a save, that one recipe's workflow file is rewritten two seconds later
  (`/symbiotica/recipes/generate` takes an optional `recipe`), so the file on
  disk is the recipe rather than whatever `generate workflows` last wrote.

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

- Tests: `.venv/bin/pytest` from the repo root, and
  `node --import ./tests/js/register_hooks.mjs --test tests/js/*.test.mjs` for
  the canvas side. NOT `python3 -m pytest`: the repo's own `py/` directory
  shadows the `py` package pytest imports, and it dies in `_pytest.compat`.
  (`PYTHONSAFEPATH=1` is the other way out.) Tests stub `comfy_api`; see
  `tests/comfy_api_stub.py`. All tests must pass before a PR.
- **Never `assert.equal` two DOM elements from `tests/js/comfy_stub.mjs`.** They
  are cyclic, and on a FAILURE node builds a diff that never returns: the file
  is killed at 100s, every test after it never runs, and the reporter shows a
  passing run with the file marked failed. One real bug hid behind that for a
  day. Compare identity — `assert.ok(a === b, "...")`.
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
- Vocabulary he insists on for the Recipes node: a **project** IS its base
  workflow — one per base, named after it (`october/base_example.json` is
  `october-base-example`, folder included) and resolved from the open workflow
  by path. "Project" and "base workflow" are one thing under two words, and the
  file in `user/default/recipes/` is only where its recipes are kept
  ("i don't really understand what the difference between project and workflow
  is… it's not adding anything to have 2 things that are the same thing",
  2026-09-21). A **recipe** is one asset type in it (`appliance-1x2`),
  **shared** is what every recipe takes. Buttons are two words naming what they act on
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
