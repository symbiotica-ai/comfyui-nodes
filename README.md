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

The web extension adds an events browser on Order Read and populates the
feature/group dropdowns after the first queue.

## Configuration

### API keys

Set via environment variables — no key is ever required for the package to load, only at the moment a node calls a provider.

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

## License

MIT — see `LICENSE`.
