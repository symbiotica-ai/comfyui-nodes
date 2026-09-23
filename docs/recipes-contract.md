# Recipes — what the node must do

The rule everything else follows from:

> **What is on the canvas is what the node stores. What the node stores is what
> goes back onto the canvas. Nothing is dropped, and nothing is refused in
> silence.**

## 1. A slot is a node painted the match colour

- Painting a node the colour in `match_color` makes it a slot. **That alone.**
  No retitling, no `recipe:` prefix, no saving the workflow first.
- The row's name is the node's title. A node still carrying its type's name
  (`KSampler`) is named by that, and two nodes with the same name are one row
  that writes to both.
- A node painted while the panel is open shows up as a row **on the next
  repaint**, not after a save and reopen.
- Unpainting a node removes its row on sight, including when it was the last
  one.
- A node inside a subgraph is not a slot. The subgraph instance on the surface
  is, and its promoted inputs are its values.

## 2. A slot is captured whole

- One widget → the value.
- More than one → every widget by name.
- A subgraph instance → its promoted inputs.
- A node titled `<name>?` → on/off (its mode).
- An rgthree **Fast Groups Muter / Bypasser** → one entry per group title.
- A widget fed by a wire is left out, always, at every widget count. The wire
  is the value; recording the empty box writes that emptiness into the recipe.

## 3. Picking a recipe is loading it

- Clicking a recipe in the sidebar puts its values on the canvas and points the
  `recipe` wire at it: the `category` widget on the node feeding that wire is
  set to the label whose slug is the recipe, and `asset` and `ref` are cleared —
  the same act as clicking that category in the Task tree. A run is ONE event,
  and the rows are the whole month's categories, so the pick also moves
  `feature` to an event that HOLDS that category; without it the node sits on
  `runs 0` and the queue dies naming the event it looked in.
- The recipe you LEAVE is written first — the one the canvas is actually on,
  which with `auto` running is not always the one on screen.
- **The pane goes on following the wire after a pick**, because a pick POINTS
  the wire: the two agree from that moment. Only a pick the wire could not
  follow is his alone and left where he put it. A wire that moves to a name
  this project has no row for does not end the follow either — the pane waits
  for the next name it can show.
- `new recipe` asks for a name and writes the canvas into it: the same act as
  picking an asset in Task, with the name typed instead of arriving on a wire.
- The project row is the project's settings and sets no slot, so it stays a view.
- **Every category the parsed MONTH holds is a row from the start**, across all
  of its events, marked while nothing is stored for it — you have to go through
  all of them anyway. The month, not the open event: the Task's category view
  walks the whole month, so an asset picked there names a recipe from any event
  in it, and a sidebar holding one event's worth has no row to follow to. Picking
  one points the wire at it and puts shared on the canvas; it becomes a recipe
  the moment something is captured into it, and until then it is never written
  to the file: an empty block per category is a workflow per category at full
  price. Looking at one writes nothing. A category the order stops naming takes
  its empty row with it; one that holds values is a recipe and stays.

## 3b. A project IS its base workflow

- One project per base workflow, named after it: `october/base_example.json` is
  `october-base-example`, folder included, because two bases with the same file
  name in different folders would otherwise share one recipe table. A project is
  resolved by its `template`, never by its name, so a file named some other way
  goes on working.
- `generate workflows` writes one real workflow per recipe BESIDE the base,
  named `<project>-<recipe>.json`, both halves lowercase with dashes. A file
  called `appliance-1x2.json` next to its source says nothing about which
  source made it.
- A project holds its base, `shared` and its recipes. Nothing else: `output`
  and `workflow_prefix` were a second and third knob for one rule, and a value
  left in an older file is ignored and dropped on the next save.
- Opening a generated workflow finds no project, which is right: it is an
  output, not a source.
- A file this project wrote under an older naming rule is NAMED in the generate
  toast, never deleted — it is a workflow in his folder like any other, and a
  name he has been opening all day that quietly stopped being regenerated has
  to be said out loud. Ours is provable: a generated workflow's `id` is uuid5
  over its own name, so one he saved by hand carries the editor's id and is
  left alone.

## 4. Loading puts it back exactly

- Every recorded value is written to its node.
- rgthree groups are written so `toggleRestriction` cannot change the outcome:
  the groups the recipe wants off go first, the ones it wants on go last.
- A wired widget is never written.
- A load never fires because the node forgot where it was. On opening a
  workflow, the canvas **is** the current state of the recipe — auto adopts it.
  Only moving to a different recipe writes to the canvas.

## 5. Nothing is lost

- Saving a project must not drop a key because its node was momentarily out of
  sight — a subgraph open on the canvas, a collapsed node, a graph still
  loading. A key is dropped only when its node is gone from the **root** graph.
- The slot list is always read from the root graph, never from whichever
  subgraph the canvas is showing.
- A cell that does not parse blocks that one cell's save, not the discovery of
  new slots.

## 6. Nothing is refused in silence

- A painted node that did not become a row says why, in the panel.
- A value that could not be written says which node and why.
- A recipe with nothing stored and nothing under it in `shared` writes nothing,
  and says so in the status line. That is a category he has not been through
  yet, not a broken canvas: "No recipe slots on this canvas" is for a
  `match_color` that matches nothing.
- `generate workflows` either writes every slot or names the one it could not,
  including group toggles.
- A capture names what it could NOT keep: a node whose values moved since the
  last load or capture and that carries no paint is listed, rather than
  vanishing.
- Values the SAVED template has no slot for are named in the status line. That
  is a workflow painted and not saved, and generate would otherwise render the
  template's own value at full price.

## 7. The server does what the canvas does

`web/js/recipes.js` and `py/_recipes.py` are the same rules twice. A kind the
canvas can capture (`toggle`, `dict`, `scalar`, rgthree groups) is a kind the
generator can write. They change in one commit.

Two of those rules are only half in the workflow JSON, so the server has to be
told the rest:

- **The key.** A node never retitled is captured under the name the canvas
  DRAWS on it — its display name. A saved workflow stores no title for one, so
  every server-side slot read takes a `display` map built from ComfyUI's
  `NODE_DISPLAY_NAME_MAPPINGS`.
- **The widget positions.** `widgets_values` is positional and is regularly
  longer than the inputs the graph declares, because ComfyUI draws widgets
  nothing declares and records their values with no name. The layout is
  reconstructed by merging the declared names with the captured keys, both of
  which are subsequences of it.

---

## Known breaks, against the above — fixed 2026-09-23

| # | Break | Fix |
|---|---|---|
| H1 | Every save put one more space after each comma inside a dict slot's strings: `cellText` spaced its JSON with a replace over the whole text. His project stored the Prompts text with 6 to 11, and a recipe load put them on the Prompts node, which then read as edited | the spacing goes between tokens only (`spacedJson`) |
| H2 | Clicking or resizing any node saved the recipe: that moves the node to the end of `graph._nodes`, and auto's signature listed the slot values in that order | `slotSignature` keys the values by slot name |

## Known breaks, against the above — fixed 2026-09-21

| # | Break | Fix |
|---|---|---|
| G1 | Picking an ASSET cleared the category, so the `recipe` wire named nothing and a pick stored nothing, silently | `assetRecipeOf` answers from the picked asset's own row |
| G2 | `generate workflows` refused every project holding a KSampler: six declared names against seven widget values | `_widget_positions` merges the declared names with the captured keys |
| G3 | An un-retitled custom node was captured as `Control Image` and read back as `SymbioticaControlImage`; the value had no slot and the next save deleted it | the server is handed the display names |
| G4 | With `auto` running, a sidebar switch wrote the canvas into the row on SCREEN, so `appliance-1x2` came to hold `food`'s values | the column written is the one the canvas is on |
| G5 | `auto`'s save rebuilt the pane a second after an edit, taking the caret out mid-word | it reconciles (`renderAll`) |
| G6 | Picking a recipe left the **Task** node's `category` alone: the labels were read off the widget's combo options, which Task's plain, tree-written widget does not have — so auto read the old name off the wire on the next draw and loaded the old recipe back over the pick | `pointWireAt` reads the node's own category list |
| G7 | The pane stopped following the Task after ANY sidebar click: `choose` armed the follow by comparing the click against where the wire WAS, and a pick MOVES the wire. It then sat on one recipe while the Task walked through the others | armed on `activeColumn() === column`, and a wire naming no row no longer ends the follow |
| G8 | A category picked from another event set `category` and left `feature` behind, so the node sat on `runs 0` and the queue refused naming the event it looked in — reachable from the sidebar and from the Task's own category view | `eventForCategory`, one rule for both sides |
| G9 | "No recipe slots on this canvas" fired on every category with nothing stored: with `shared` empty there was nothing to write either way, so the one click meant to START a recipe answered "your canvas is broken" | an empty value set is named in the status line, and nothing pops |

## Known breaks, against the above — fixed 2026-09-18

| # | Break | Fix |
|---|---|---|
| F1 | A painted node with no title of its own was **not** a slot — painting alone did nothing | `ownTitle` / `slot_key` fall back to the node's type name, and a subgraph instance to the subgraph's name |
| F2 | The slot list came from the open **subgraph**, so entering one collapsed the table and the next save deleted every other recipe's values | `liveGraph()` climbs to `rootGraph`; every caller goes through it |
| F3 | One unparseable cell made every newly painted node fail to appear, silently | `retable` keeps cell text as typed and parses nothing, so it cannot throw |
| F4 | A single-widget node fed by a wire recorded the empty box | `settableWidgets()` drops wired widgets at every widget count, on read and on write |
| F5 | `generate workflows` threw on any project with an rgthree muter slot | `_set_groups` writes the modes of the nodes inside each group; `template_slots` reports one entry per group |
| F6 | Unpainting the last slot left the old rows on screen | `syncSlots` guards on "the graph has no nodes", not "no slots found" |
| F7 | A canvas with nothing painted looked identical to a broken `match_color` | The status line names which of the two it is |

Counts at 2026-09-21: 454 JS, 937 Python. G1-G5 were reproduced against his
own project file and his node shapes; none has been watched on the Modal canvas.
G6-G9 were reproduced and fixed in a real browser on his own workflow and
project file, on the local install, and the canvas half is verified `ok` in the
Modal sandbox.
