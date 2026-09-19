# Symbiotica

Creative pack for ComfyUI: Claude and Gemini routed through Cloudflare AI Gateway, and the order pipeline that turns a game's asset list into finished renders.

## Install

Via ComfyUI Manager: search **Symbiotica** and click install.

Manual:
```bash
cd ComfyUI/custom_nodes
git clone https://github.com/symbiotica-ai/comfyui-nodes.git symbiotica
pip install -r symbiotica/requirements.txt
```

## What's in the pack

### Text (Anthropic Claude)
- **Claude (Symbiotica)** — a prompt and up to 20 reference images become an
  answer. Claude draws nothing; this belongs in a graph as a prompt author, a
  caption or critique step, or a structured-extraction step feeding an image
  node.

  Models are picked by name, and each one carries only the settings it actually
  accepts: `reasoning_effort` where the model can think, `temperature` where it
  is not removed, and `max_tokens` throughout. Opus 5 and Fable 5 reason
  unconditionally and so are offered no `off`; Haiku 4.5 has no reasoning input
  at all. Reference images fill `image_1` onwards as you wire them.

  Routed the same way as the Gemini node below, on the same two variables. Every
  outcome that is not a complete answer raises rather than returning a string:
  a refusal, an answer cut off at `max_tokens`, inputs too large for the context
  window, and an empty reply are four different errors with four different
  fixes. ComfyUI's own Claude node returns the literal text
  `Empty response from Claude model.` for the last of those, which reaches a
  client looking like an answer.

  Large references are brought down to the model's own ceiling first — 2576px on
  Opus 5, Sonnet 5, Fable 5 and Opus 4.8/4.7, 1568px elsewhere. A batch that
  encodes to more than 8 MB is refused rather than trimmed: Cloudflare stores no
  gateway log above 10 MB, and a call whose log is dropped is spend that never
  reaches the cockpit.

### Image generation (Google Gemini)
- **Gemini Image (Symbiotica)** — a prompt and up to 14 reference images become
  a render, at 1K/2K/4K and any of fifteen aspect ratios. Returns the image,
  whatever the model said about it, and the interim sketch when thinking is set
  to HIGH; when it declines, that sentence is the error.

  Picking Nano Banana 2 Lite offers 1K alone, because that is all it renders.
  `thinking_level`, `temperature` and `top_p` are exposed at ComfyUI's own
  defaults, and reference images fill `image_1` onwards as you wire them.

  Where `SYMBIOTICA_AIG_BASE` is set the call routes through Cloudflare AI
  Gateway on that studio's own stored key, tagged so its spend can be grouped
  per studio — which is how order renders run headless and how their cost
  reaches the cockpit. Anywhere else it calls Google directly on a key from the
  node, the Settings UI or the environment. A gateway that is configured always
  wins, and a gateway URL missing either its token or its studio is an error
  rather than a quiet fall back to a personal or shared key.

### Workflow utilities
- `Load Text File` — one text file as a STRING
- `Load Text List` — one text file's blank-line-separated blocks as a list,
  emitting `(prompts, names, count)`
- `Split Prompts` — one text block split into separate prompt strings

### Modules (linked subgraphs and groups)
- `Module` (Symbiotica) — a subgraph or a group, edited once, updated
  in every workflow that uses it. The node lists every group and subgraph in
  the graph you are looking at, one row each: title, a `folder/name` path,
  the revision, and **Publish**. Press Publish and that row becomes a module,
  or gets a new revision if it already is one. Edit it in any workflow and
  press Publish again: every workflow picks up the new version when opened,
  and **Sync all workflows** rewrites the files on disk right away (including
  ones you have not opened). The **module** dropdown drops a published module
  below the node.
- **folder** is the project name that prefills the path for new rows, so
  with folder `bakery` the Flip group is offered as `bakery/flip`. Type it or
  connect a text node. Slashes in the path are folders on disk under
  `user/default/symbiotica-modules/`.
- **Subgraph modules.** The definition inside plus the promoted values on the
  outside (a LoRA picker, a checkpoint). A promoted value follows the change
  only when the module changed it, so a prompt typed into one workflow
  survives a LoRA change published from another. Nested subgraphs inside a
  module are not supported yet.
- **Group modules.** The nodes inside the frame, their values and the links
  between them. On sync the nodes keep their ids, positions and outside links
  (relinked by slot name; a link whose node or slot is gone is dropped and the
  toast says so). Nodes you add to the module appear everywhere at their
  module position, nodes you remove disappear, and the frame grows to fit.
  Widget values follow the same per-widget rule, so the image in a Load Image
  node or the text in a prompt node changes everywhere when you change it in
  the module.

### Asset Focus, by canvas
- The `category` dropdown splits a category by its canvas in tiles:
  `Appliance 1x1` (128x128) and `Appliance 1x2` (128x256) are two entries,
  since they are two drawings and two recipes. Picking one narrows to that
  canvas; a plain name on the wire still keeps every canvas. Three outputs
  after `ref_name`: `category_recipe` (the label, `Appliance 1x2`; a canvas
  with no whole-tile grid carries its pixels, `Crate Icon 200x200`) and
  `width` / `height` in pixels for saving at the game's size. `category`
  stays the plain sheet name.

### Control images
- `Control Image` (Symbiotica) — Load Image scoped to a shared library,
  named by two widgets. `root` is the directory it sits in: empty means
  ComfyUI's own input directory, and the shared library is
  `/studio-assets/_platform/resources`, which the canvas editor and the
  per-user render sandboxes mount whole. (The ENGINE tier mounts
  `/studio-assets` at its own studio's subtree, so `_platform` is not visible
  there.) `folder` is the library inside it, `controlnet` by default — a name,
  never a path out of the root. The dropdown lists every image under that
  folder, subfolders included, as `folder/name.png`, and re-lists whenever
  either widget changes; outputs IMAGE and MASK. On the input directory it
  reads through ComfyUI's own `LoadImage`; on any other mount it reads the
  file directly, to the same conventions (mask is `1 - alpha`, and a file with
  no alpha gets the 64x64 all-zero stand-in). Title it `control_image` and
  paint it the recipe match colour, and a recipe stores the relative path.

### Recipes (one template, one workflow per recipe)
- `Recipes` (Symbiotica) — a **project** is one template workflow,
  a block of **shared** values and one **recipe** per asset type; Generate
  writes one workflow per recipe. The project is the one whose template is
  the open workflow, so on a base workflow the node opens its project by
  itself, as collapsible sections: shared, then one per recipe,
  each listing the template's slots with **load** (put its values onto the
  canvas), **capture** (read the canvas into it) and ×. To add or refill a
  recipe, set the values on the template's own nodes, put its name in the
  **recipe** input (typed, or a wired text node; `Cashier's Desk 1x1`
  becomes `cashiers-desk-1x1`) and press **capture recipe**; a
  recipe keeps what differs from shared, shared keeps everything. **Save**
  writes the project; **Generate** saves and writes prefix + recipe `.json`
  files into the output folder (default: the template's folder), overwriting
  the last run. **New** starts a project from the open, saved workflow, named
  from its `library` slot (`studios/imperia/bakery` gives
  `imperia-bakery`). **Delete**, pressed twice, removes the picked project;
  its generated workflows stay.
- The **recipe** input reads a wired name live: through String, Join
  Strings, Join String Multi and Asset Focus's `category` output, so a name
  built from the picked category changes as you pick. With the **auto**
  toggle on, the node watches the canvas: a value edit is captured and
  saved a second later, and a name change saves the recipe you leave, then
  loads the one you arrive at onto the canvas, or creates it from the canvas
  if it is new.
- A node painted the colour in the **match_color** input is a slot, and the
  node's title is the key: type the colour once here, paint the slots on the
  canvas. The colour is a LiteGraph palette name (`purple`, `green`, `blue`,
  `pale_blue`, `cyan`, `red`, `brown`, `yellow`, `black`) or a hex, and it is
  matched by hue, so the light theme's lighter shade of the same colour counts.
  A painted node still carrying its type's own name is not a slot — the key is
  the title. A node titled `recipe:<key>` is a slot whatever its colour, so
  templates written before this keep working. The colour is saved with the
  project as `match_color`, which is what Generate matches on the server. A
  cell sets the node's first widget; a JSON list (`[2, 1]`) sets every widget;
  a subgraph instance shows one field per promoted widget; a title ending in
  `?` (`pre_flip?`) is a toggle that takes `true` (active) or `false`
  (bypassed). An empty cell is an absent key: the recipe takes the shared
  value, else the template's own. A key no slot carries refuses the run.
  Projects are files in `user/default/recipes/<name>.json`.
- The generated files are output: edits belong in the template (the
  pipeline, for every recipe) or in the project (one recipe's values).

### Canvas
- **Find node by ID** — press `Ctrl+Shift+0`, or pick **Find node by ID** at the
  top of the canvas right-click menu. Type the number on the node's ID badge,
  press Enter: the canvas centres on that node with it selected, at the
  zoom you were already at. A number that matches nothing says so and leaves the
  box open. It searches the graph you are looking at, so inside a subgraph it
  finds that subgraph's ids. Rebind or clear the key in **Settings →
  Keybindings → Find node by ID**; a bare letter is a bad idea there, since
  other packs claim them (`f` is already KJNodes'). This is a canvas command,
  not a node — there is nothing to add to a workflow.

## Order pipeline (Symbiotica Hub port)

What is left of the hub's order flow, once the reading, packing and template
nodes came out: one node reads the order and picks the asset, and the rest
watch or edit what that asset needs.

- **Symbiotica Asset Focus** — the whole selection in one node. Project folder,
  month, event, category and asset are picked here — **📁 Read folder** fills
  the month and event dropdowns without a queue — and the asset's record comes
  out on separate outputs: name, category, client prompt, save path, the
  category plus its canvas in tiles, that canvas in pixels, and the client
  reference you clicked (image, mask, filename). `order` is the incoming order
  narrowed to the focused asset; `event_order` is the whole event, unnarrowed,
  for the Order Tracker. Pick nothing and it emits every asset in the event, so
  the same node covers the one-asset loop and a run over everything.
- **Symbiotica Order Tracker** — the order as a board: one slot per asset it
  asks for, filled with the approved render or left empty, with a count and a
  percent for the event. It is a picker pointed at every asset at once — the
  same folders, the same `names` tag, the same thumbnails — so nothing is
  tracked that is not already on disk and there is no bookkeeping to drift.
  Wire an Asset Focus's `event_order` into `order`; `names` defaults to
  `_final`, and any other save prefix asks the board a different question
  ("which assets have a `_base` at all") without a code change. Queue it on its
  own to re-read the folders.
- **Symbiotica Prompt Block** — one block of the prompt book, edited on the
  canvas: a shared rule (`_rules/02-inputs.md`), an image-model block
  (`_image/01-image-model.md`) or an asset type (`Chair.md`). Several side by
  side ARE the book, and a save lands in `<project>/<subfolder>/` where every
  queue reads it. Chain block to block through `project_path` so one wire feeds
  the row; wire Asset Focus's `category` in and the node becomes a window onto
  whatever `_recipes/<category>.json` names in `slot` — switch asset type and
  the block on screen follows, with nothing to pick. A block file may hold up
  to three versions, split by `<!-- version: name -->` markers; the top of the
  file stays the default.
- **Symbiotica Studio Library** — pick a file or folder from the active
  studio's asset library; outputs its absolute sandbox path and whether it is
  a folder. The browser refreshes the studio volume when it opens and whenever
  you press ⟳, and says so when that refresh did not happen, since a folder
  nobody went to look for and a folder that is not there otherwise look the
  same. Every folder below the studio root lists `..` as its first row.
  The studio root leaves out the eight model-kind folders
  (`checkpoints`, `loras`, `vae`, `controlnet`, `upscale_models`,
  `embeddings`, `diffusion_models`, `text_encoders`) because models are picked
  in the model loader node, not by path; it says how many it left out and
  `show` lists them anyway.

## Configuration

### API keys

Two ways, checked in this order (after any per-node `api_key` widget):

1. **Settings UI (recommended):** ComfyUI Settings → search "Symbiotica" →
   paste your keys. They are stored in your user's `comfy.settings.json` on
   the machine — never inside workflow files, so workflows stay safe to
   share and commit.
2. **Environment variables** — no key is ever required for the package to
   load, only at the moment a node calls a provider.

| Variable | Provider |
|---|---|
| `ANTHROPIC_API_KEY` | Claude, including the Claude node's direct arm |
| `GEMINI_API_KEY` | Gemini |
| `GOOGLE_API_KEY` | The Gemini image node's second choice after `GEMINI_API_KEY` |

Per-node `api_key` widget overrides the env var.

**The Claude and Gemini nodes are the exception.** On a box that carries
these, every one of their calls goes through the gateway and no personal key
is consulted:

| Variable | Content |
|---|---|
| `SYMBIOTICA_AIG_BASE` | Cloudflare AI Gateway base, stopping at the gateway name and **without** a provider slug, e.g. `https://gateway.ai.cloudflare.com/v1/<account>/<gateway>`. Each node appends its own provider. Not the OpenAI-compatibility URL the dashboard shows beside it — a base ending in `/compat/chat/completions` is refused by name, because sent as it stands the gateway answers internal code 2019 naming the compatibility endpoint rather than the base. Must be `https` — the token is a bearer credential for the studio's whole spend. |
| `SYMBIOTICA_AIG_TOKEN` | AI Gateway token, sent as `cf-aig-authorization`. Not a provider key — provider keys are stored in the gateway as BYOK and injected there. |
| `ORDER_STUDIO` | The studio slug. Selects that studio's own stored provider key (`cf-aig-byok-alias`) and tags the call so its spend can be grouped (`cf-aig-metadata`). Already set in order sandboxes. |
| `SYMBIOTICA_AIG_SURFACE` | What kind of run this is, tagged alongside the studio. Optional, and `order` when unset, which is what every existing sandbox reports. A box that is not running orders should set its own value, or its spend joins the order totals under a label that reads correctly. |

### On Comfy Desktop, where there is no environment

Comfy Desktop is an Electron app that launches its own Python, so there is
nowhere to put any of the variables above. **Settings → Symbiotica → AI
Gateway** holds the same three — base URL, token, studio slug — and a box with
them filled in routes every gateway node exactly as a sandbox does. The studio
slug defaults to `comfy-desktop`; whatever it says must exist in the gateway as
a BYOK alias, or every call fails with internal code 2040 naming it.

The three are read as a group and only when the environment says nothing about
the gateway at all:

- An environment carrying `SYMBIOTICA_AIG_BASE` is used whole. A Settings token
  pairing with a sandbox's base fails as code 2009, which reads as the gateway
  rejecting our own credential and sends the reader to the wrong system.
- An environment carrying `ORDER_STUDIO` and no base is a sandbox whose secret
  did not populate, and still says so. Answering it with a desktop's own
  credentials would let the render succeed while the studio's spend left its
  own key.
- A base filled in with either of the other two left empty is refused by name,
  rather than routed on.

Runs from here are tagged `surface: canvas` rather than `order`, so canvas
spend does not join the order totals under a label that reads correctly. The
per-provider keys in **Settings → Symbiotica → API Keys** are ignored wherever
a gateway route is configured.

Setting the base without the token is an error, not a fall back: a call that
succeeds on somebody's personal key while its spend leaves the gateway is a
failure nobody can detect afterwards.

`ORDER_STUDIO` set with no gateway URL is an error too, and the most useful one:
the sandbox launcher sets it whether or not the secret populated, so its
presence without a URL means the secret is broken. Left to fall through, that
box would either fail asking for a key it cannot hold, or succeed on a stray
personal key and take the spend out of the gateway without anyone noticing.

A gateway render with no `ORDER_STUDIO` is an error for the same reason. The
alias picks which studio's key pays; the metadata tag is what the analytics can
group by, because no AI Gateway dataset exposes the key alias as a dimension.
Falling back to the shared `default` key would bill one studio while the tag
named another, and nothing short of reconciling the Google bill against gateway
analytics would ever show it. A studio's key must be provisioned in the gateway
before that studio's first render, per provider — a studio with a Google key
and no Anthropic one fails on the Claude node alone.

A provider with **no** stored key at all is the case worth knowing about,
because it does not look like a failure. Cloudflare's credential precedence is
a key on the request, then a stored key by alias, then Cloudflare's own
credentials billed to the account balance — so with nothing stored, the alias
is never consulted and the call is served on Cloudflare's rail and attributed
to nobody. It surfaces as `internalCode` 2021 only while that balance is
empty; funded, the same call succeeds silently.

### Asset folders

The asset and template browsers read ComfyUI's own `input/` and `output/`, the
studio-assets volume, and any folder a running graph pointed them at. A project
kept somewhere else — `~/games/my-game` rather than under ComfyUI — is declared
once, either in **Settings → Symbiotica → Paths → Asset folders** or as an env
var:

```bash
export SYMBIOTICA_ASSET_ROOTS="/Users/me/games/my-game, /Volumes/art"
```

Absolute paths, separated by commas, semicolons or newlines. Without this a
project outside those folders browses empty: a request cannot make a folder
readable by naming it, or asking to browse a folder would be what grants access
to it.

## Tests

Python — the pipeline logic that runs without ComfyUI:

```bash
pytest tests/
```

Run it as `pytest`, not `python -m pytest`: the latter puts the repo root on
`sys.path`, where the `py/` package shadows the `py` module pytest itself
imports.

JavaScript — the node UI logic, on node's built-in runner (no dependencies):

```bash
node --import ./tests/js/register_hooks.mjs --test 'tests/js/*.test.mjs'
```

`tests/js/register_hooks.mjs` points ComfyUI's `scripts/app.js` and
`scripts/api.js` imports at `tests/js/comfy_stub.mjs`, so files under `web/js`
are tested as they ship, unmodified.

## License

MIT — see `LICENSE`.
