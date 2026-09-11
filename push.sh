#!/usr/bin/env bash
# ABOUTME: Push the working tree straight onto the platform's custom-nodes Volume,
# ABOUTME: skipping the release and the registry. For dev iteration on Modal only.
#
# The editor syncs that Volume after every ComfyUI Manager request, so after a
# push: open Manager once (any click), then hard-reload the tab for a JS change
# or press Manager's Restart for a Python change. Files removed here are
# removed there too — a stale copy of a web/js file is the one failure this
# pack has already paid for (see web/js/register.js).
set -euo pipefail
cd "$(dirname "$0")"

VOLUME="${SYM_NODES_VOLUME:-symbiotica-comfy-custom-nodes}"
REMOTE="${SYM_NODES_PATH:-symbiotica}"
ENV_FLAG=()
[ -n "${MODAL_ENVIRONMENT:-}" ] && ENV_FLAG=(-e "$MODAL_ENVIRONMENT")

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
rsync -a --exclude '__pycache__' --exclude '.pytest_cache' \
  py web __init__.py pyproject.toml README.md CHANGELOG.md "$stage/"

# Remove remote files that no longer exist locally, in the two dirs ComfyUI
# imports from. Listing is one call per dir; rm is one call per stray file.
for dir in py web/js; do
  remote_list=$(modal volume ls "${ENV_FLAG[@]}" "$VOLUME" "$REMOTE/$dir" 2>/dev/null | awk '{print $NF}' | grep -E '\.(py|js|mjs)$' || true)
  for f in $remote_list; do
    rel="${f#"$REMOTE/"}"
    if [ ! -e "$stage/$rel" ]; then
      echo "rm stale $rel"
      modal volume rm "${ENV_FLAG[@]}" "$VOLUME" "$f"
    fi
  done
done

for item in py web __init__.py pyproject.toml README.md CHANGELOG.md; do
  modal volume put "${ENV_FLAG[@]}" "$VOLUME" "$stage/$item" "$REMOTE/$item" --force >/dev/null
  echo "put $item"
done

version=$(grep -E '^version = ' pyproject.toml | sed 's/version = "\(.*\)"/\1/')
echo "pushed $(git rev-parse --short HEAD) (pyproject $version) to $VOLUME:$REMOTE"
echo "in the editor: open Manager once, then hard-reload (JS) or Manager > Restart (Python)"
