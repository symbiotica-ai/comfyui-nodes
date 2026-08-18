# Symbiotica

All-in-one creative pack for ComfyUI. Agents, image and video generation, audio, transcription, captions, and video composition — in one install.

## Install

Via ComfyUI Manager: search **Symbiotica** and click install.

Manual:
```bash
cd ComfyUI/custom_nodes
git clone https://github.com/symbiotica-ai/comfyui-nodes.git symbiotica
pip install -r symbiotica/requirements.txt
```

## What's in the pack

### Agents (LLM)
Stateless agents you wire into workflows. Personality (SOUL), instructions (CLAUDE), skills, and a router across providers.

- `Symbiotica Agent Settings` — load agent definition from disk
- `Symbiotica Agent` — run the agent against a prompt or image
- `Symbiotica Skills` — toggle which skills the agent has access to
- `NS LLM Chat` — single-shot chat completion
- `NS LLM Model Selector` — central model picker for routing
- `NS Prompt Tuner Load` / `NS Prompt Tuner Save` — self-improving system-prompt loop; each queue run refines the prompt against a design reference (see `docs/prompt-tuner.md`)

Supports Claude, Gemini, GPT, Grok.

### Image generation (Wavespeed)
Wrappers around Wavespeed's hosted endpoints.

- **Flux** — Kontext (Dev/Pro/Max), ControlNet Union Pro 2, Image Upscaler
- **Nano Banana** — text-to-image, edit, fast variants, Pro (text-to-image / edit / multi / ultra), Nano Banana 2 (text-to-image, edit, fast)
- **Qwen** — text-to-image (+ LoRA), edit (+ LoRA), edit-plus (+ LoRA)
- **SeedDream V4** — text-to-image, edit, sequential variants
- **Wan 2.5** — text-to-image, image edit
- **Runway** — upscale

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

### Video generation (ByteDance Seedance)
- **Seedance Reference to Video (Symbiotica)** — reference images, clips and
  audio become a video on Seedance 2.5, 2.0, 2.0 Fast or 2.0 Mini, billed
  through Cloudflare AI Gateway rather than to a ComfyUI account.

  Each model offers only the slots it can carry, because the four differ and a
  shared input list could only offer the union: 2.5 takes thirty reference
  images and ten audio tracks, the 2.0 family takes four images, 2.0 Mini alone
  takes one audio track, and 2.0 reaches 4k where the others stop at 720p.

  **Reference videos are not offered on any model.** ByteDance accepts a
  reference video only as a public web URL, and this node sends its references
  inline as base64. Cloudflare's own request validator accepts a `data:video/…`
  URI, which is misleading — the call is then refused upstream with
  `reference_video must be provided as a web url`. A VIDEO socket here would be
  one you could wire and every render would refuse, so there is none. Video
  editing and extension go with it, since both need a source clip.

  Reference images and audio do work inline, verified against the provider
  rather than against that validator. The set is refused above 8 MB, because
  Cloudflare stores no gateway log above 10 MB and a call with no log is spend
  that reaches no cockpit row.

  The counts above are Cloudflare's catalog limits, tighter than ByteDance's own
  — through BytePlus directly the 2.0 family takes nine images each. Routing
  through the gateway is what buys per-studio accounting, and this is what it
  costs.

### Video generation (Wavespeed)
- **Sora 2** — text-to-video, image-to-video, Pro variants
- **Veo 3.1** — text-to-video, image-to-video, reference-to-video, fast variants
- **Wan 2.2 / 2.5** — i2v 720p, animate, image-to-video (+ fast), text-to-video (+ fast)
- **InfiniteTalk** — single and multi-character

### Audio & transcription
- `NS Whisper Transcribe` — local faster-whisper transcription with optional initial-prompt biasing
- `NS Google Transcribe` — Google Speech-to-Text API
- `NS Music` — generated music track sized to your video
- `NS Sound Effects` — ElevenLabs-driven SFX from JSON cue lists
- `NS Voice Atmosphere` — reverb / room tone via scipy fftconvolve
- `NS Submagic Captions` — Submagic-rendered captions

### Captions, overlays, video composition
- `NS Caption Overlay` / `NS Caption Style` — Remotion-rendered captions
- `NS Visual Overlay` — Remotion-rendered Instagram / TikTok / Facebook chrome
- `NS Video Concat Multi` — stitch multiple clips
- `NS Video Effects` — speed, crop, flip, etc.
- `NS Video Overlay` — overlay one video on another
- `NS Get Video Components` / `NS Create Video` — frame ↔ video conversion utilities
- `NS Transition Settings` — transition config between clips

### Camera and film look
- `Camera Shake` — seeded Perlin handheld wiggle on a VIDEO
- `Focus Pull` — animated depth-of-field rack between two focus points
- `Film Grain` — analog grain, with per-channel weighting
- `Chromatic Aberration` — corner-weighted RGB split

### Product research
- `Product Gallery Scrape` — an e-commerce product page's gallery, split into
  product-only / on-model / other IMAGE batches
- `Product Image Sort` — orders a gallery batch by category

### Workflow utilities
- `NS Workflow Model Downloader` — pulls models referenced in a workflow JSON
- `NS Prompt List` — multi-prompt iteration
- `NS Qwen Resolution` — common Qwen-friendly resolutions
- `Symbiotica Seed` — reproducible seeds with optional auto-increment
- `Load Text File` — one text file as a STRING
- `Load Text List` — one text file's blank-line-separated blocks as a list,
  emitting the same `(prompts, names, count)` contract as `NS Prompt List`

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

Recreates the hub's Order Read → Specs → Template flow as ComfyUI nodes:

- **Symbiotica Order Read** — parses a monthly order `.xlsx` (Feature / Asset
  Name / Canvas / Prompt columns) plus a folder of reference images
  (`AssetName.png`, `AssetName_2.png`, ...) into events. A blank `month` means
  "whichever this project has" and reads the first one; a NAMED month the
  project holds no order for raises, rather than reading the first one under
  the name that was asked for. The same split applies to `feature` on Order
  Specs and the Template Editor — over the API a substituted answer renders,
  bills, and reports success indistinguishably from the one requested.
- **Symbiotica Event Specs** — picks one event (feature) and emits its spec:
  template groups by category + canvas with per-asset prompts and refs.
- **Symbiotica Template Builder** — composes a template sheet: either
  `prefill_from_specs` (reference strips packed onto the sheet — single-ref
  assets get a flipped pair, multi-ref assets one cell per stage) or
  `catalog_grid` (existing game art matched by category). Sheets save to
  `output/templates/<name>.png` with a JSON region sidecar, and the bundle
  output feeds the Template Prompt node.
- **Symbiotica Template Prompt** — turns the bundle's regions into an edit
  prompt for the Nano Banana edit nodes.
- **Symbiotica Regional Prompt** — turns the template bundle into a
  layout-aware edit prompt (ERPK Regional Prompt Builder format): numbered
  `box_2d` placements per region, base sheet as image 1, per-region reference
  images (task-sheet crops by default) numbered from 2. Outputs
  `ERPK_IMAGE_REFS` for the ERPK Gemini edit nodes plus a plain IMAGE refs
  batch, pixel bboxes, and per-region masks.
- **Symbiotica Template Editor** — the full template editor / texture packer
  as an in-Comfy app: "Open template editor" launches a full-screen editor
  (hub layout) with a zoom/pan canvas, draggable/resizable numbered regions,
  prefill-from-specs, a project-assets tree with per-region base assignment,
  per-region task references, kind/description editing, full pack settings
  (model presets, MaxRects/Shelf/Grid, distribute-by-folder, snap, smart
  guides, background), scene prompt, and save/load of named templates
  (stored under `output/templates/`). The node executes from the saved
  template: base sheet + task-reference sheet sharing one region layout —
  wire both into an img2img edit node.
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
- **Symbiotica Refs Folder** — load every image in one folder, in filename
  order, from an absolute path and nothing else. No browsing and no picking, so
  a dispatcher can bind the path and run the graph headless over the API.
  Outputs the images, their filenames index-aligned, and a count; `max_count`
  caps how many come back. A file that will not decode is skipped, but a
  missing folder — or one where nothing decodes — raises rather than handing
  the graph zero references in silence.
- **Symbiotica Order Assets** — emits one item per asset in a feature, with
  names, categories and save paths index-aligned, so ComfyUI's own list
  fan-out runs a single render lane once per asset instead of eight duplicated
  groups.
- **Symbiotica Save Render** — files each result under
  month/feature/category/asset, and declares what it wrote as the run's output
  images. An API caller reads a run's renders from `/history`, and only what a
  node declares gets there — a save that declares nothing finishes green with
  nothing to show for it.
- **Symbiotica Dataset Reference** — picks a reference per category, seeded per
  `(seed, category)` so adding a type does not reshuffle a pick already
  approved. Also reports `cell_boxes`: where each asset sits inside its type's
  packed sheet, so a render of that sheet can be cut back up on the grid it was
  packed to — and `save_path`, the type folder the reference was drawn from.
  Wire that into a Pick node's `save_path` to see every reference of that type
  in a grid and choose by eye instead of by seed. Wire Asset Focus's `order`
  output in and the `categories` wire is unneeded.
- **Symbiotica Slice Cells** — cuts a generated sheet into one image per asset
  on those boxes, each named by its role, so an edit addresses "serving" rather
  than "the third one" and a run that switches asset type re-cuts itself with
  no rewiring.
- **Symbiotica Asset Focus** — one asset out of the order, chosen on the
  node, with its whole record on separate outputs: name, category, client
  prompt, save path — and `order`, the incoming order narrowed to each focused
  asset. That one wire feeds Dataset Reference, Asset Refs and Prompt Recipe
  everything the string outputs carry, so the strings are left for core nodes
  (a save's filename_prefix, string joins). Order Assets is
  still the node for rendering a whole event in one press; this is the one for
  iterating on one asset.
- **Symbiotica Pick** — the triage step between two stages: every image wired
  into it is filed in that node's own buffer and drawn as a thumbnail on the
  node body, so three separate runs of the same generator stack up as three
  candidates instead of overwriting each other. Tick the ones worth keeping and
  only those leave the node. `images` is optional on purpose — once the picks
  are made the generator branch can be muted and the node still serves them
  from disk, so queueing the edit stage does not re-fire a paid render. Wire
  the asset and category being worked on and candidates are tagged with it; the
  node then opens on that asset rather than on everything ever generated. Drop
  one after each stage — generate → pick → edit → pick → background removal.
  `names` narrows the listing to exactly those filenames — wire Asset Refs'
  `ref_names` to tick only the references the client sent for this asset — and
  resting on a thumbnail floats it big beside the grid, so a render can be
  judged without opening it in a tab.
  To review the EDITS of one approval rather than the approval itself, wire this
  node's `edit_save_path` into the Save Image that writes them and set the next
  picker's `show` to `edits`. `edit_save_path` is `save_path` marked with
  the render that was picked, so each edit records what it came from in its own
  name — which is the only place that link can live, since an edit is named by
  the save node long after the tick was made and can never appear in a set of
  ticks. A file written without the mark simply has no parent, so nothing
  already on disk needs renaming. The edits land wherever `save_path` points, so
  give the picker a `stage` to keep them in their own step folder rather than
  beside the renders they came from.
  Approving a tile also writes it: `_final_from.<render>_00001_.png` lands beside
  the render, and un-approving deletes it. A tick lives on the `selection`
  widget — workflow JSON, which nothing else on the canvas can read — so an
  approval that another node has to see has to be a file. `_final` is a stage
  like `_base`, so `names="_final"` lists exactly the approved renders through
  the machinery that was already here, and the render itself is copied rather
  than renamed: a rename would break the tick pointing at it and orphan any edit
  whose name carries `_from.<it>`.
- **Symbiotica Order Tracker** — the order as a board: one slot per asset it
  asks for, filled with the approved render or left empty, with a count and a
  percent for the event. It is a Pick node pointed at every asset at once —
  the same folders, the same `names` tag, the same thumbnails — so nothing is
  tracked that is not already on disk and there is no bookkeeping to drift.
  Wire an Order Specs or an Asset Focus into `order`; `names` defaults to
  `_final`, and any other save prefix asks the board a different question
  ("which assets have a `_base` at all") without a code change. Queue it on its
  own to re-read the folders.
- **Symbiotica Asset Refs** — the client's own reference art for one asset, in
  the order the order sheet pairs it, so the index that picks a cell picks the
  reference belonging to it. References with transparency are composited onto a
  chosen background rather than flattened, and their alpha comes out as `masks`.
  It also emits `folder`, the references root they were read from, which a Pick
  node takes as its `save_path` to tick the client's references by eye.
- **Symbiotica Client Examples** — every client brief of one type in a feature,
  numbered, as ONE string, so an LLM downstream runs once and sees the whole
  set rather than a brief at a time. `limit` truncates and the header says so,
  because a text showing three of eight examples that does not admit it reads
  as the whole population.
- **Symbiotica Reconstruct Cells** — the inverse of Slice Cells: edited cells go
  back onto the grid they were cut from, on the same `cell_boxes`, so a sheet
  survives a per-asset edit intact. The canvas is measured from the boxes, which
  record the grid rather than the sheet, so the outer margin is recovered from
  the centring rather than lost.
- **Symbiotica Compare Sheet** — a row of references over a row of results in one
  image, so an asset and the art it was drawn from can be read in a glance
  instead of flipped between. Cell size, spacing and background are settable, and
  a reference can be drawn smaller than its cell.
- **Symbiotica Category Prompts** — composes a category's architect prompt from
  the project's shared `prompts/_rules/*.md` (filename order) followed by
  `prompts/<Category>.md`, which stays last because the tail of a prompt
  carries the most weight.
- **Symbiotica Prompt Book** — reads and writes those prompt blocks from the
  canvas; every render records which blocks composed its prompt, per block
  rather than one hash of the whole, so a lighting change is distinguishable
  from a negatives change. A block file may hold up to three versions, split by
  `<!-- version: name -->` markers; the top of the file stays the default.
- **Symbiotica Prompt Recipe** — composes the architect (`system_prompt`) and
  image (`image_prompt`) prompts in one node, with a version slot (1–3) per
  rules / image / type block, so two phrasings of the same block can be
  compared without editing the file between runs. A slot with no such version
  falls back to the top of its file.

The web extension adds an events browser on Order Read and populates the
feature/group dropdowns after the first queue. On a fully cached run the
browser panel is not re-pushed — change any input (or re-parse) to
repopulate it after a page reload.

## Hypereel (streamer-reel pipeline)

The Hypereel product ported node for node from the Symbiotica platform: find viral
moments in gameplay, cut them, animate a consistent streamer facecam (Seedance 2.0
partner node), and stack facecam over real gameplay into a vertical reel.

- `Hypereel Product Scrape (URL to references)` — scrapes a product, app, or
  app-store page into a logo + screenshots (IMAGE outputs) and a product summary for
  the script LLM; follows the first app-store link for the curated promo screens,
  promotes the AppIcon to logo, drops badges and template URLs, and refuses
  non-public targets (SSRF-guarded — the host is resolved before it is trusted)
- `Hypereel UGC Presets (style · hook · setting)` — the platform's UGC preset
  catalogs as dropdowns: pick a style, hook and setting by name and get each template
  plus a combined pre-labeled block (STYLE NOTE / HOOK PATTERN / SETTING NOTE) ready
  to concatenate after the product summary
- `Hypereel Analysis Prompt (auto duration)` — builds the highlight-analysis prompt
  from the video itself: the real duration becomes the timestamp boundary line and
  the same number feeds Highlight Pick's `source_duration` guard, so the prompt and
  the guard can never disagree
- `Hypereel Highlight Pick` — parses a Gemini highlight list (`HIGHLIGHT n |
  start=.. | end=.. | label | WHY: .. | MOOD: ..`, seconds or MM:SS) and exposes one
  highlight's start/end/duration plus the text row for the script LLM
- `Hypereel Duration Parse (script to prompt + seconds)` — reads the script LLM's
  output, strips the trailing `DURATION: N` line and returns the clean prompt plus
  the clamped seconds (4–15, default 12 when the line is missing); wire the prompt
  onward and the seconds into the video node's duration input
- `Hypereel Clip (cut by seconds)` — cuts a `[start, start+duration]` window out of a
  VIDEO with ffmpeg. No frame tensors: a 7-minute or 7-hour source costs the same.
  The window is clamped inside the source, so a highlight near EOF still yields a
  full slice
- `Hypereel Screen Glow (light from gameplay)` — samples the gameplay's per-frame
  mean color (an explosion flashes orange, a dark corridor goes dim) and
  screen-blends it onto the facecam as a bottom-up monitor glow, frame-locked to the
  footage; the facecam's own audio passes through untouched
- `Hypereel Stack Composite (facecam over gameplay)` — named layout templates:
  vertical facecam-top 40/60 (the platform's Modal geometry), vertical half/half,
  and gameplay-full layouts (vertical or horizontal) with the facecam PiP in a
  chosen corner. Voice at full volume with game audio mixed at a gain only when the
  gameplay has an audio track (`amix ... normalize=0` so the voice is never
  halved), up to 4 pairs hard-cut-concatenated in order. Wire a keyer's MASK into a
  pair to drop the facecam in as a cutout silhouette instead of a rectangle

Runs anywhere ffmpeg exists — local mac (Homebrew) or a Modal image with
`apt_install("ffmpeg")`.

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
| `OPENAI_API_KEY` | GPT |
| `GEMINI_API_KEY` | Gemini |
| `XAI_API_KEY` | Grok |
| `WAVESPEED_API_KEY` | Wavespeed (image + video) |
| `ELEVENLABS_API_KEY` | ElevenLabs (sound effects) |
| `SUBMAGIC_API_KEY` | Submagic (captions) |
| `GOOGLE_API_KEY` | Google Speech-to-Text, and the Gemini image node's second choice after `GEMINI_API_KEY` |

Per-node `api_key` widget overrides the env var.

**The Gemini and Claude nodes are the exception.** On a box that carries
these two, every one of their calls goes through the gateway and no personal
key is consulted:

| Variable | Content |
|---|---|
| `SYMBIOTICA_AIG_BASE` | Cloudflare AI Gateway base, **without** a provider slug, e.g. `https://gateway.ai.cloudflare.com/v1/<account>/<gateway>`. Each node appends its own provider. Must be `https` — the token is a bearer credential for the studio's whole spend. |
| `SYMBIOTICA_AIG_TOKEN` | AI Gateway token, sent as `cf-aig-authorization`. Not a provider key — provider keys are stored in the gateway as BYOK and injected there. |
| `ORDER_STUDIO` | The studio slug. Selects that studio's own stored provider key (`cf-aig-byok-alias`) and tags the call so its spend can be grouped (`cf-aig-metadata`). Already set in order sandboxes. |
| `SYMBIOTICA_AIG_SURFACE` | What kind of run this is, tagged alongside the studio. Optional, and `order` when unset, which is what every existing sandbox reports. A box that is not running orders should set its own value, or its spend joins the order totals under a label that reads correctly. |

The Seedance node reaches the gateway a different way, because ByteDance has no
provider-passthrough slug on AI Gateway at all — its models live in
Cloudflare's own catalog, and the call goes to the account's `/ai/run`:

| Variable | Content |
|---|---|
| `SYMBIOTICA_CF_ACCOUNT_ID` | The Cloudflare account tag whose `/ai/run` is called. |
| `SYMBIOTICA_CF_API_TOKEN` | A Cloudflare API token, sent as `Authorization: Bearer`. **This is not the AI Gateway token and is a much broader credential** — it authenticates to the Cloudflare account rather than to one model vendor. Scope it to the minimum the catalog needs. |
| `SYMBIOTICA_AIG_GATEWAY_ID` | Which gateway to route through, sent as `cf-aig-gateway-id`. Without it the call takes the account's default gateway, where its log lands somewhere nobody reads and the studio tag with it. |

`ORDER_STUDIO` and `SYMBIOTICA_AIG_SURFACE` mean the same thing on this path and
are equally required. All three of the variables above are required together;
there is no personal-key fall back, because a catalog model has no provider
endpoint of its own to call.

**Spend on this path is not separable by studio.** Cloudflare consults only the
`default` BYOK alias on its own AI endpoints, so whichever single ByteDance key
is stored there pays for every studio. The `cf-aig-metadata` tag still rides on
every call, so spend remains *attributable* in analytics — it is the paying key
that is shared, not the accounting. That is a narrower gap than it sounds, but
it is a real one, and it does not apply to the Gemini or Claude nodes.

Every reply names the key that paid, and until a ByteDance key is stored under
the gateway's `default` alias the answer is `keySource: Unified` — Cloudflare's
own balance, outside the BYOK boundary entirely. The node logs a warning saying
so on any render billed that way, because nothing else in the system would
mention it and the render itself looks perfect.

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

### Agent and skill directories

The Agent nodes scan disk for agent and skill definitions.

```ini
# config.ini in the package root
[agents]
agents_dir = /path/to/agents

[skills]
skills_dir = /path/to/skills
```

Or environment variables `SYMBIOTICA_AGENTS_DIR` and `SYMBIOTICA_SKILLS_DIR`. The `agents_path` / `skills_path` widgets on the nodes also override at the node level.

Agents repo: [symbiotica-ai/agents](https://github.com/symbiotica-ai/agents). Skills repo: [symbiotica-ai/skills](https://github.com/symbiotica-ai/skills).

## Heads up

- **`faster-whisper`** is in the deps. First run of `NS Whisper Transcribe` downloads model weights — can be a few GB depending on the model size you pick.
- **Remotion-rendered nodes** (captions, overlays) need Node.js installed system-wide. The package ships a pre-built Remotion bundle so no `npm install` is needed at install time, but the renderer subprocess still requires `node` on `PATH`.

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
