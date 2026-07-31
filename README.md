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

### Workflow utilities
- `NS Workflow Model Downloader` — pulls models referenced in a workflow JSON
- `NS Prompt List` — multi-prompt iteration
- `NS Qwen Resolution` — common Qwen-friendly resolutions
- `Symbiotica Seed` — reproducible seeds with optional auto-increment

## Order pipeline (Symbiotica Hub port)

Recreates the hub's Order Read → Specs → Template flow as ComfyUI nodes:

- **Symbiotica Order Read** — parses a monthly order `.xlsx` (Feature / Asset
  Name / Canvas / Prompt columns) plus a folder of reference images
  (`AssetName.png`, `AssetName_2.png`, ...) into events.
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
  a folder.

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
| `ANTHROPIC_API_KEY` | Claude |
| `OPENAI_API_KEY` | GPT |
| `GEMINI_API_KEY` | Gemini |
| `XAI_API_KEY` | Grok |
| `WAVESPEED_API_KEY` | Wavespeed (image + video) |
| `ELEVENLABS_API_KEY` | ElevenLabs (sound effects) |
| `SUBMAGIC_API_KEY` | Submagic (captions) |
| `GOOGLE_API_KEY` | Google Speech-to-Text |

Per-node `api_key` widget overrides the env var.

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
