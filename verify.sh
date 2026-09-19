#!/usr/bin/env bash
# Read-only checks against the running Modal editor. No cURL paste: the sandbox
# host and its canvas key come from the Modal token in ~/.modal.toml.
#
#   ./verify.sh              every web/js file: what the editor serves vs the tree
#   ./verify.sh js <file>    one file, with the first line that differs
#   ./verify.sh node <Class> that node's schema as the editor reports it
#   ./verify.sh url          the sandbox host (the key is never printed)
#   ./verify.sh api <path>   GET any read-only editor route, body to stdout
#
# Nothing here queues a prompt or writes to the sandbox.
set -euo pipefail
cd "$(dirname "$0")"
MODAL_CLI="$(command -v modal || true)"
[ -n "$MODAL_CLI" ] || { echo "modal CLI not on PATH"; exit 1; }
MODAL_PY="$(sed -n '1s/^#!//p' "$MODAL_CLI")"
[ -x "$MODAL_PY" ] || { echo "no python behind $MODAL_CLI"; exit 1; }

# -I keeps the repo's own modal/ directory from shadowing the SDK.
exec "$MODAL_PY" -I - "$@" <<'PY'
import hashlib, json, pathlib, sys, urllib.error, urllib.request

APP, ENV, PROXY_PORT = "symbiotica-comfy", "dev", 8899
ROOT = pathlib.Path.cwd()  # the wrapper cd'd to the repo root


def target():
    """The running editor's host and key, off his Modal token."""
    import modal

    app = modal.App.lookup(APP, environment_name=ENV, create_if_missing=False)
    boxes = list(modal.Sandbox.list(app_id=app.app_id))
    if not boxes:
        sys.exit("no editor sandbox is running — open the canvas from the hub first")
    canvas = [sb for sb in boxes if (sb.get_tags() or {}).get("tier") == "canvas"]
    sb = (canvas or boxes)[0]
    url = sb.tunnels(timeout=30)[PROXY_PORT].url
    key = sb.exec("printenv", "CANVAS_SANDBOX_KEY").stdout.read().strip()
    if not key:
        sys.exit(f"{sb.object_id} holds no canvas key")
    return url, key


def get(url, key, path):
    req = urllib.request.Request(url + path, headers={"x-canvas-key": key})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def served_js(url, key, name):
    path = f"/extensions/symbiotica/js/{name}"
    code, body = get(url, key, path)
    # The gateway 404s a file it does hold often enough to have reported two
    # of them missing once; a second ask settles which it is.
    if code != 200:
        code, body = get(url, key, path)
    return code, body


def sha(b):
    return hashlib.sha256(b).hexdigest()[:12]


def check_all(url, key):
    bad = 0
    for f in sorted((ROOT / "web/js").glob("*.js")):
        local = f.read_bytes()
        code, body = served_js(url, key, f.name)
        if code == 404:
            print(f"  MISSING  {f.name}  — the sandbox never got this file")
            bad += 1
        elif code != 200:
            print(f"  HTTP {code}  {f.name}")
            bad += 1
        elif sha(body) != sha(local):
            print(f"  STALE    {f.name}  served {len(body)}B {sha(body)} / tree {len(local)}B {sha(local)}")
            bad += 1
        else:
            print(f"  ok       {f.name}")

    code, body = get(url, key, "/object_info")
    if code != 200:
        print(f"\n  object_info: HTTP {code}")
        return 1
    live = {k for k in json.loads(body) if k.startswith("Symbiotica")}
    declared = set()
    for py in (ROOT / "py").rglob("*.py"):
        for line in py.read_text(errors="replace").splitlines():
            if 'node_id="Symbiotica' in line:
                declared.add(line.split('node_id="')[1].split('"')[0])
    missing = sorted(declared - live)
    print(f"\n  nodes: {len(live)} registered", end="")
    print(f" — NOT REGISTERED: {', '.join(missing)}" if missing else "")
    return bad + len(missing)


def check_js(url, key, name):
    f = ROOT / "web/js" / name
    if not f.exists():
        sys.exit(f"{f} is not in the tree")
    code, body = served_js(url, key, name)
    if code != 200:
        sys.exit(f"HTTP {code} for {name}")
    local, remote = f.read_text(errors="replace"), body.decode(errors="replace")
    if local == remote:
        print(f"ok  {name}  {len(body)}B {sha(body)}")
        return 0
    a, b = local.splitlines(), remote.splitlines()
    for i in range(max(len(a), len(b))):
        if a[i : i + 1] != b[i : i + 1]:
            print(f"differs at line {i + 1}")
            print(f"  tree:   {(a[i] if i < len(a) else '<end of file>')[:100]}")
            print(f"  served: {(b[i] if i < len(b) else '<end of file>')[:100]}")
            break
    return 1


def check_node(url, key, cls):
    code, body = get(url, key, f"/object_info/{cls}")
    if code != 200 or not json.loads(body):
        sys.exit(f"{cls} is not registered on the editor (HTTP {code})")
    spec = json.loads(body)[cls]
    req = spec["input"].get("required", {})
    opt = spec["input"].get("optional", {})
    print(f"{cls}")
    for where, group in (("required", req), ("optional", opt)):
        for name, t in group.items():
            kind = t[0] if isinstance(t[0], str) else "COMBO"
            print(f"  {where:8} {name:20} {kind}")
    print(f"  outputs  {', '.join(spec.get('output_name') or spec.get('output') or [])}")
    return 0


args = sys.argv[1:]
url, key = target()
if args and args[0] == "url":
    print(url)
    sys.exit(0)
if args and args[0] == "api" and len(args) == 2:
    code, body = get(url, key, args[1] if args[1].startswith("/") else "/" + args[1])
    sys.stdout.write(body.decode(errors="replace"))
    sys.exit(0 if code == 200 else 1)
print(f"editor {url}\n")
if not args:
    sys.exit(1 if check_all(url, key) else 0)
if args[0] == "js" and len(args) == 2:
    sys.exit(check_js(url, key, args[1]))
if args[0] == "node" and len(args) == 2:
    sys.exit(check_node(url, key, args[1]))
sys.exit("usage: ./verify.sh [js <file> | node <Class> | url]")
PY
