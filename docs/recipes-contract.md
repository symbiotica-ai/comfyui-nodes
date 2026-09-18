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

## 3. Loading puts it back exactly

- Every recorded value is written to its node.
- rgthree groups are written so `toggleRestriction` cannot change the outcome:
  the groups the recipe wants off go first, the ones it wants on go last.
- A wired widget is never written.
- A load never fires because the node forgot where it was. On opening a
  workflow, the canvas **is** the current state of the recipe — auto adopts it.
  Only moving to a different recipe writes to the canvas.

## 4. Nothing is lost

- Saving a project must not drop a key because its node was momentarily out of
  sight — a subgraph open on the canvas, a collapsed node, a graph still
  loading. A key is dropped only when its node is gone from the **root** graph.
- The slot list is always read from the root graph, never from whichever
  subgraph the canvas is showing.
- A cell that does not parse blocks that one cell's save, not the discovery of
  new slots.

## 5. Nothing is refused in silence

- A painted node that did not become a row says why, in the panel.
- A value that could not be written says which node and why.
- `generate workflows` either writes every slot or names the one it could not,
  including group toggles.

## 6. The server does what the canvas does

`web/js/recipes.js` and `py/_recipes.py` are the same rules twice. A kind the
canvas can capture (`toggle`, `dict`, `scalar`, rgthree groups) is a kind the
generator can write. They change in one commit.

---

## Known breaks, against the above — all fixed 2026-09-18

| # | Break | Fix |
|---|---|---|
| F1 | A painted node with no title of its own was **not** a slot — painting alone did nothing | `ownTitle` / `slot_key` fall back to the node's type name, and a subgraph instance to the subgraph's name |
| F2 | The slot list came from the open **subgraph**, so entering one collapsed the table and the next save deleted every other recipe's values | `liveGraph()` climbs to `rootGraph`; every caller goes through it |
| F3 | One unparseable cell made every newly painted node fail to appear, silently | `retable` keeps cell text as typed and parses nothing, so it cannot throw |
| F4 | A single-widget node fed by a wire recorded the empty box | `settableWidgets()` drops wired widgets at every widget count, on read and on write |
| F5 | `generate workflows` threw on any project with an rgthree muter slot | `_set_groups` writes the modes of the nodes inside each group; `template_slots` reports one entry per group |
| F6 | Unpainting the last slot left the old rows on screen | `syncSlots` guards on "the graph has no nodes", not "no slots found" |
| F7 | A canvas with nothing painted looked identical to a broken `match_color` | The status line names which of the two it is |

Not verified on the Modal canvas — unit tests only (246 JS, 844 Python).
