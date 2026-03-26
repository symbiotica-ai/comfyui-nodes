# Symbiotica ComfyUI Nodes

Custom nodes that bring agent-based LLM interactions into ComfyUI visual workflows.

## Nodes

### Symbiotica Agent Settings

Loads an agent definition from disk: CLAUDE.md + SOUL.md from the agent directory, plus shared SOUL.md and USER.md from the agents root. All fields pre-filled and editable.

Accepts up to 5 skill nodes wired in as optional inputs.

**Inputs:**
- `agent` — Dropdown of discovered agents, or `(custom)` for manual entry
- `soul` — Personality, values, boundaries (from shared + agent SOUL.md)
- `instructions` — Identity and operating instructions (from agent CLAUDE.md)
- `user_context` (optional) — Who the agent serves (from shared USER.md)
- `model` (optional) — LLM model
- `api_key` (optional) — Falls back to environment variable
- `skills` (optional) — Wire from Symbiotica Skills node

**Output:** `AGENT_SETTINGS`

### Symbiotica Skills

Scans the skills directory and shows each discovered skill as a toggle. Enable the ones you want, wire the output into Agent Settings.

**Inputs:**
- One BOOLEAN toggle per discovered skill (from `SYMBIOTICA_SKILLS_DIR`)

**Output:** `AGENT_SKILLS` (list of enabled skill definitions)

### Symbiotica Agent

Executes a stateless LLM agent. Every execution is the agent's entire lifecycle: born, briefed, does one job, done.

**Inputs:**
- `agent_settings` — Wire from Symbiotica Agent Settings
- `prompt` — The task or question
- `max_tokens`, `temperature`, `seed`, `timeout` — API parameters
- `api_key` (optional) — Overrides agent settings
- `model_override` (optional) — Overrides agent settings model
- `image` (optional) — For vision tasks

**Output:** `response` (STRING)

## Installation

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/symbiotica-ai/comfyui-nodes.git
pip install -r comfyui-nodes/requirements.txt
```

## Configuration

### Agent and skill directories

The nodes scan directories on disk for agent and skill definitions.

**Environment variables:**
- `SYMBIOTICA_AGENTS_DIR` — Path to agent directories (from [symbiotica-ai/agents](https://github.com/symbiotica-ai/agents))
- `SYMBIOTICA_SKILLS_DIR` — Path to skill directories (from [symbiotica-ai/skills](https://github.com/symbiotica-ai/skills))

**Or via config.ini** in the repo root:
```ini
[agents]
agents_dir = /path/to/agents

[skills]
skills_dir = /path/to/skills
```

### API keys

Set via environment variables:
- `ANTHROPIC_API_KEY` — Claude
- `GEMINI_API_KEY` — Gemini
- `OPENAI_API_KEY` — GPT
- `XAI_API_KEY` — Grok

## Agent directory structure

```
agents/
├── SOUL.md            — Shared behavioral rules (all agents inherit)
├── USER.md            — Shared user profile (all agents read)
└── lens/
    ├── CLAUDE.md      — Identity + operating instructions
    ├── SOUL.md        — Agent-specific personality (layered on shared)
    └── memory/        — Per-agent memory
```

## Skill directory structure

Each skill is a directory with a SKILL.md:

```
analyze-link/
└── SKILL.md       — What the skill does, process, rules
```

## Supported Models

Claude, Gemini, GPT, and Grok. The agent node routes to the correct provider based on model name.
