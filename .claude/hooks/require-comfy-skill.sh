#!/usr/bin/env bash
# ABOUTME: PreToolUse hook on Edit/Write — blocks node-code edits until the
# ABOUTME: session has loaded the matching comfyui-* skill (see CLAUDE.md).
set -u
# Fail open without jq: an unenforced edit beats a repo nobody can edit.
command -v jq >/dev/null 2>&1 || exit 0
INPUT=$(cat)
SESSION=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""')
MARKER="${TMPDIR:-/tmp}/comfy-skills-$(id -u)/$SESSION"

need=""
case "$FILE" in
  */web/js/*.js) need="comfyui-node-frontend" ;;
  */py/*.py)     need="comfyui-nodes-dev" ;;
  *) exit 0 ;;
esac

# Tests and stubs are plain pytest — no ComfyUI API knowledge required.
case "$FILE" in */tests/*) exit 0 ;; esac

if [ -f "$MARKER" ] && grep -q "comfyui-" "$MARKER" 2>/dev/null; then
  exit 0
fi

echo "This repo requires loading the ComfyUI skill before editing node code:" >&2
echo "run the Skill tool with '$need' (see CLAUDE.md's table for the full" >&2
echo "mapping), then retry this edit. One load per session is enough." >&2
exit 2
