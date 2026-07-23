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
