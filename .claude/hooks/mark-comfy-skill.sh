#!/usr/bin/env bash
# ABOUTME: PostToolUse hook on the Skill tool — records which comfyui-* skills
# ABOUTME: this session has loaded, for require-comfy-skill.sh to check.
set -u
command -v jq >/dev/null 2>&1 || exit 0
INPUT=$(cat)
SESSION=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
SKILL=$(echo "$INPUT" | jq -r '.tool_input.skill // ""')
case "$SKILL" in
  comfyui-*|*:comfyui-*)
    DIR="${TMPDIR:-/tmp}/comfy-skills-$(id -u)"
    mkdir -p "$DIR"
    echo "$SKILL" >> "$DIR/$SESSION"
    ;;
esac
exit 0
