# Modal Sync: Agents & Skills from GitHub

## Goal

Keep `/vol/symbiotica/agents/` and `/vol/symbiotica/skills/` on Modal's network volume in sync with their GitHub repos. ComfyUI reads from these paths at runtime.

## Flow

```
Workspace (local) → GitHub → Modal (pulls on schedule) → ComfyUI (reads at runtime)
```

## Repos to sync

| Repo | Sync to |
|------|---------|
| `symbiotica-ai/agents` | `/vol/symbiotica/agents/` |
| `symbiotica-ai/skills` | `/vol/symbiotica/skills/` |

## What to build

A Modal function that runs on a cron (every 5 minutes or on webhook trigger) and does:

```python
# Pseudocode
git clone --depth 1 https://github.com/symbiotica-ai/agents.git /tmp/agents
git clone --depth 1 https://github.com/symbiotica-ai/skills.git /tmp/skills
rsync /tmp/agents/ → /vol/symbiotica/agents/
rsync /tmp/skills/ → /vol/symbiotica/skills/
```

Use `--depth 1` — we only need the latest state, not history.

## ComfyUI env vars

Set these in the ComfyUI Modal app:

```
SYMBIOTICA_AGENTS_DIR=/vol/symbiotica/agents
SYMBIOTICA_SKILLS_DIR=/vol/symbiotica/skills
```

## Option A: Cron sync

Modal scheduled function. Runs every N minutes, pulls latest from both repos.

## Option B: GitHub webhook

GitHub sends a webhook on push → Modal endpoint triggers sync immediately. Faster, no polling. Set up a webhook on both repos pointing to a Modal web endpoint.

## Notes

- The repos contain only markdown files. Syncs are fast and lightweight.
- No build step. The files ARE the config — ComfyUI reads them directly.
- If a sync fails, the previous version stays on the volume. No downtime.
- To test locally: set the env vars to point at your local clones of the repos.
