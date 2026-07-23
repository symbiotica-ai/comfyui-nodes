# Studio Library Picker node — design

**Status:** approved (decisions locked 2026-07-23); revised 2026-07-23 per the
adversarial review (Appendix B). Plan-ready.

**Goal:** A ComfyUI custom node that browses the active studio's asset library
(a filesystem tree already mounted inside the editor sandbox) and lets a user
pick one **file or folder**, emitting its absolute sandbox path as a `STRING`
(plus an `is_dir` `BOOLEAN`) for any downstream node that takes a path.

**Architecture:** One-repo change in `symbiotica-ai/comfyui-nodes`. A V3
`io.ComfyNode` in the pipeline package holds a hidden `selection` widget storing
a **volume-relative** path (`studios/<slug>/<rel>`); a lazy per-level browse
route (`/symbiotica/studio-library`) lists the confined tree; a `web/js`
extension opens a single-select fullscreen browser that writes the pick into the
widget. `execute()` resolves the widget value against the studio-assets Volume
root **without reading any tenant environment**, confining the result to that
root.

**Tech stack:** Python (ComfyUI V3 node API `io.ComfyNode` + aiohttp
`PromptServer.instance.routes`), vanilla JS (`web/js` ComfyUI extension),
`pytest` + node's built-in test runner. No new dependency, no `services/comfy-modal`
change.

## Global Constraints

- **Studio resolution is tenant-env-free.** The browse route (which always runs
  on the editor sandbox, where `CANVAS_STUDIO` is set) bakes the studio slug into
  the stored path. `execute()` and `fingerprint_inputs()` MUST NOT read
  `CANVAS_STUDIO` — they run wherever the graph runs, and the GPU render sandbox
  has no such env by design (`services/comfy-modal/app.py:849`). The only
  environment value the resolution path consults is `STUDIO_ASSETS_DIR`, which is
  present on both the editor and GPU sandboxes (`app.py:772,920`); it confines to
  the Volume root only.
- **The load-bearing guard is host-path escape, not tenancy.** The whole
  `studio-assets` Volume is mounted read-write in every sandbox and ComfyUI is an
  arbitrary-code-execution surface behind a staff-only key gate, so node-level
  cross-tenant confinement is a UX nicety, not a security boundary. The guard
  that MUST hold is that a graph-serialized `selection` string can never resolve
  to a path **outside** the Volume root (e.g. `/root/...`, the glue's Modal
  tokens). Enforce it with the repo's existing two-arm `realpath` idiom
  (`py/pipeline/files_read.py:63`, `py/pipeline/routes.py:45,300,327`).
- **Volume-relative in the graph, and volume-relative on the wire.** The widget
  stores `studios/<slug>/<rel>` — never an absolute path — so a saved workflow
  carries no host path and re-resolves cleanly (mirrors `parse-order`'s
  "re-derived at execute" discipline). The browse route's `dir` query param and
  every per-entry `rel` use the **same** volume-relative namespace (see
  §"One namespace" below) so a folder expand round-trips.
- **Model kinds are hidden.** The `MODEL_KINDS` the editor already surfaces
  natively via `/comfy-models` are excluded from the browse listing **at the
  studio root**. The real set is **eight** (`services/comfy-modal/canvas_entry.py:14-25`
  is the source of truth), not four. This node's value is the gap: reference
  images, arbitrary files, and folder paths.
- **Bounded volume sync before listing.** A browse-session open syncs the Volume
  view (async `sync <mount>`, short timeout) so freshly uploaded assets appear;
  failure/timeout to sync degrades to a possibly-stale listing, never an error,
  and never blocks the aiohttp event loop.
- **Category `symbiotica/pipeline`**, lowercase — matching the pipeline package
  (confirmed against `SymbioticaFilesRead`, `nodes.py:261`).
- **TDD**, real filesystem in tests (tmp trees), pristine output.

## One namespace (the `rel`/`dir`/`selection` string)

There is exactly **one** representation for a location: a **volume-relative**
path `studios/<slug>[/<sub>/...]`, no leading slash. It is what the widget
stores, what `dir=` carries, what each entry's `rel` is, and what `execute()`
resolves. The only special value is the empty string `""`, a **route-only
sentinel** the route normalizes to `studios/<active-slug>` (the studio root).
The JS never synthesizes a `rel` — it stores verbatim whatever the server
produced — so non-canonical strings never arise from a real pick.

---

## Components

### 1. `py/pipeline/studio_library.py` — pure logic (new)

The sibling-module half of the node (the `SymbioticaFilesRead ↔ files_read.py`
pattern). No ComfyUI / aiohttp / subprocess imports, so it is unit-testable
directly and is added to `test_shim.py`'s pure-import list.

Constants:

- `STUDIO_ASSETS_DIR = (os.environ.get("STUDIO_ASSETS_DIR") or "").strip() or "/studio-assets"`
  — the Volume mount root (matches `services/comfy-modal/app.py:110`). Trimming +
  the `or` default prevents a set-but-empty/whitespace env from re-anchoring the
  confinement root to the process CWD.
- `MODEL_KINDS = frozenset({"checkpoints", "loras", "vae", "controlnet",
  "upscale_models", "embeddings", "diffusion_models", "text_encoders"})` — the
  eight top-level dirs hidden from the listing at the studio root. **Source of
  truth: `services/comfy-modal/canvas_entry.py:14-25`** (a cross-repo copy; a
  pinned-literal drift test guards it).
- `RESERVED_PREFIX = "studios/"` — the fixed studio namespace
  (`services/comfy-modal/studio_assets.py:7`).
- `_STUDIO_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")` — the **studio** slug
  shape (`services/comfy-modal/studio_fs.py:9`): lowercase kebab-case, **no length
  cap, no underscores**. Applied with `.fullmatch()`. (This is the studio slug,
  not the user-id shape.)

Functions (all coerce `str(x or "")` at their string boundaries so a value wired
from an upstream STRING socket — which can be `None` — never raises
`AttributeError`):

- `resolve_studio_path(base_dir: str, rel: str) -> str`
  The **studio-path resolver** (the two-arm confinement idiom; not a shared
  extraction — see Appendix B #20).
  - Coerce `rel = str(rel or "")`; reject empty/whitespace with a distinct
    `ValueError("no selection")`.
  - Guard the base: `ValueError` unless `os.path.isabs(base_dir)`;
    `root = os.path.realpath(base_dir)`; `ValueError` unless `os.path.isdir(root)`.
  - Reject a `rel` whose first two segments are not `studios/<valid-slug>` (slug
    by `_STUDIO_SLUG.fullmatch`) — this rejects absolute input (a leading `/`
    fails the prefix) and enforces the namespace. `studios/<slug>` exactly is
    valid (the studio root).
  - `path = os.path.realpath(os.path.join(root, rel))`.
  - Require `path == root or path.startswith(root + os.sep)` else
    `ValueError("outside the studio library")` — the load-bearing guard, catching
    symlink-escape and `..` after canonicalization. (Confinement is to the
    **Volume root**, per the Global Constraint — a `..` that stays inside the
    Volume but crosses into another studio is not a security failure.)
  - Require `os.path.exists(path)` else `ValueError("not found: <rel>")`.
  - Return the absolute `path`.
- `resolve_selection(base_dir: str, selection: str) -> tuple[str, bool]`
  `path = resolve_studio_path(base_dir, selection); return path, os.path.isdir(path)`.
  The env-free resolution `execute()` delegates to.
- `selection_fingerprint(base_dir: str, selection: str) -> str`
  `sha256(str(selection or "").encode())`, then — inside `try/except (ValueError,
  OSError)` that appends `b"unresolved"` on failure — resolve and mix in change
  evidence: for a **file**, `f"{st.st_mtime_ns}:{st.st_size}"`; for a **folder**,
  the sorted direntry-name set (`"\x00".join(sorted(os.listdir(path)))`).
  **Documented limitation:** a folder pick is fingerprinted on its direntry *set*
  only — an in-place rewrite of a file *under* a selected folder does NOT
  invalidate downstream caches (see Appendix B #8). File picks re-run on
  re-upload as before.
- `list_studio_dir(base_dir: str, studio: str, rel: str = "") -> dict`
  Confined lazy per-level lister for the route (impure fs read; no env / no
  subprocess — those live in the route handler). **Never raises** — the entire
  body is wrapped in `except (ValueError, OSError): return {"error": ...}`
  (mirroring `routes.py:48-50`).
  - Validate `studio` with `_STUDIO_SLUG.fullmatch` → `{"error": ...}` if bad.
  - `studio_root = os.path.realpath(os.path.join(base_dir, "studios", studio))`.
    If it does not exist, return a **normal empty listing** (`entries: []`,
    `studio`, `rel="studios/<studio>"`, `parent=None`) — an unprovisioned studio
    is normal, not an error (matches `app.py:491-502`).
  - Normalize `rel`: `""` → `studios/<studio>`; otherwise it must begin with
    `studios/<studio>` (else `{"error": ...}` — a cross-studio `dir`).
  - `target = os.path.realpath(os.path.join(base_dir, rel))`; confine to
    `studio_root` with the two-arm idiom else `{"error": ...}`. A `dir` pointing
    at a **file** (`not os.path.isdir(target)`) → `{"error": ...}`. A NUL byte or
    backslash in `rel` raises inside `os.path.join`/`realpath` → caught → `{error}`.
  - `os.scandir(target)`, skip dotfiles; **hide `MODEL_KINDS` only when
    `target == studio_root`** (not by `rel == ""` — the target-is-root test is the
    correct one), never in nested dirs (a `references/loras/` folder is a
    legitimate asset name).
  - Type each child with `os.path.isdir(child)` (follows symlinks) so the
    browser's `type` matches `execute()`'s `is_dir`; `size` = `entry.stat().st_size`
    for files, else `None`. An in-tree symlinked dir lists as `"dir"`; an
    out-of-tree symlink is show-then-reject (the resolver fails it at execute).
  - Return `{"studio", "rel", "parent", "entries": [{"name", "rel", "type":
    "dir"|"file", "size"}]}`, entries sorted dirs-first then case-insensitive by
    name. Each entry's `rel` is the volume-relative `studios/<studio>/<...>`; the
    top-level `parent` is the volume-relative parent, or `None` at the studio root
    (never above `studios/<studio>`).

  **v1 lists a single level without a cap** — studio libraries are expected small;
  pagination/virtualization is an explicit non-goal (YAGNI). If a wide
  `references/` dump ever becomes a real concern, add a cap + an "N more" flag and
  a wide-dir test then.

### 2. `SymbioticaStudioLibrary` node — in `py/pipeline/nodes.py` (new class)

Registered by appending it to `PIPELINE_NODE_CLASSES` (`nodes.py:1708`, consumed
by `symbiotica_pipeline.py:5-14`). The class is a thin delegator, exactly like
`SymbioticaFilesRead` (`nodes.py:257-308`) — all logic lives in the pure module,
so it is testable there.

```python
class SymbioticaStudioLibrary(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaStudioLibrary",
            display_name="Symbiotica Studio Library",
            category="symbiotica/pipeline",
            description="Pick a file or folder from the studio asset library; "
                        "outputs its absolute sandbox path (and whether it is a "
                        "folder). Open the browser, click one entry.",
            inputs=[
                io.String.Input("selection", default="", advanced=True,
                                tooltip="Volume-relative pick, set by the "
                                        "studio-library browser"),
            ],
            outputs=[
                io.String.Output(display_name="path"),
                io.Boolean.Output(display_name="is_dir"),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, selection=""):
        from .studio_library import STUDIO_ASSETS_DIR, selection_fingerprint
        return selection_fingerprint(STUDIO_ASSETS_DIR, selection)

    @classmethod
    def execute(cls, selection="") -> io.NodeOutput:
        from .studio_library import STUDIO_ASSETS_DIR, resolve_selection
        path, is_dir = resolve_selection(STUDIO_ASSETS_DIR, selection)  # raises on bad pick
        return io.NodeOutput(path, is_dir)
```

- `execute()`/`fingerprint_inputs()` read **no tenant env** — the pinned
  invariant (Appendix B #11). Both are 3-line delegations to the env-free pure
  functions.
- At implement time, verify whether the installed `comfy_api.latest` accepts
  `socketless=True` on `io.String.Input` (it is **not** used anywhere in this repo
  today). If supported, add it so the frontend offers no input socket; if not, the
  `str(... or "")` coercion in the pure module is the sufficient fix for a
  socket-wired `None`. The coercion is load-bearing; `socketless` is a nicety.

### 3. Browse route — in `py/pipeline/routes.py` (new handler)

```python
@PromptServer.instance.routes.get("/symbiotica/studio-library")
async def studio_library(request):
    """Lazy per-level listing of the active studio's asset tree, confined to the
    studio-assets Volume root. `dir` is a volume-relative rel `studios/<slug>[/...]`
    (or '' for the studio root). A browse-session open (`sync=1`) refreshes the
    v2 mount first."""
    from .studio_library import STUDIO_ASSETS_DIR, list_studio_dir
    studio = (os.environ.get("CANVAS_STUDIO") or "").strip()
    if not studio:
        return web.json_response(
            {"error": "studio library not available"}, status=503)
    if request.query.get("sync") == "1":
        await _sync_studio_assets(STUDIO_ASSETS_DIR)  # async, bounded, best-effort
    result = list_studio_dir(STUDIO_ASSETS_DIR, studio, request.query.get("dir", ""))
    status = 400 if "error" in result else 200
    return web.json_response(result, status=status)
```

- `CANVAS_STUDIO` is read **here** (editor-only route, always has it) — the one
  place the env is legitimately consulted, selecting the studio subtree so the
  browser only ever shows the active tenant.
- **Real HTTP statuses, not 200+`{error}`.** No active studio → `503`; an escaping
  or malformed `dir` → `400`; a valid (possibly empty) listing → `200`. This is
  what the inherited `fetchJson` helper expects: it throws only on `!res.ok`
  (`files_read.js:17-21`), and the overlay renders the thrown message inline. A
  200+`{error}` body would flow into `.entries.map()` and blank the pane (Appendix
  B #5). A fresh, unprovisioned studio is **not** an error — it is a `200` with
  `entries: []`, which the overlay renders as an empty state (Appendix B #21).
- `_sync_studio_assets()` (in `routes.py`, impure) mirrors
  `services/comfy-modal/symbiotica_platform/route.py:206-213` — **async**, so it
  never blocks the aiohttp event loop:

  ```python
  SYNC_TIMEOUT_S = 10  # best-effort; a stale listing is acceptable, so we
                       # time out and PROCEED (unlike refresh-inputs' 30s, where a
                       # GPU prompt's correctness depends on the sync completing).

  async def _sync_studio_assets(root: str) -> None:
      try:
          proc = await asyncio.create_subprocess_exec("sync", root)
      except OSError:
          return
      try:
          await asyncio.wait_for(proc.wait(), timeout=SYNC_TIMEOUT_S)
      except asyncio.TimeoutError:
          proc.kill()
  ```

  Only on `sync=1` (browse-session open), not on every folder expand. **Not** a
  call to `/platform/refresh-models`: that endpoint lives in the hub deploy
  artifact (`symbiotica_platform`), is dormant, and coupling our node's runtime to
  a route defined in another repo is rejected (Appendix B #4). The ~10-line idiom
  is duplicated locally instead (its first instance in this repo; no cross-repo
  import is possible).

### 4. `web/js/studio_library.js` — the browser (new)

Modeled on `files_read.js` but **single-select** and **lazy** (no groups, no
thumbnails in v1; a **client-side name filter** narrows the current pane).
Registered via `app.registerExtension` gated on
`nodeData.name === "SymbioticaStudioLibrary"`, chaining the original
`onNodeCreated`/`onConfigure` (preserve-and-call, per `files_read.js:394` /
`order_pipeline.js:729-733`).

A **pure selection seam** is exported so the click-flow is testable without a DOM
event (the test stub's `addEventListener` is a no-op with no `dispatchEvent`,
Appendix B #9):

- `applySelection(node, entryRel)` — sets the `selection` widget to `entryRel`,
  updates the summary, marks the canvas dirty. Unit-tested directly.
- `summaryLabel(selection)` — the **prefix-bearing** summary text. From
  `studios/ggs/references/hero_pose.png` it yields `ggs · references/hero_pose.png`
  (studio slug retained, so a cross-studio pick is distinguishable — Appendix B
  #18); empty → `"no selection"`. Pure, unit-tested.
- `filterEntries(entries, query)` — case-insensitive name filter over the current
  pane's entries (empty/whitespace query passes all). Pure, unit-tested; wired to a
  search box that re-renders the current pane. Does not search unopened folders
  (server-side recursive search stays out of scope).

Behavior:

- `onNodeCreated`: add a `button` widget "📂 Browse studio library" and a
  `disabled`, `serialize = false` summary widget reflecting `summaryLabel(selection)`.
- `onConfigure`: chain the original, then in a `queueMicrotask` re-run
  `summaryLabel` from the restored `selection` so a reopened workflow shows the
  stored pick (Appendix B #17).
- Button opens a fullscreen overlay: a breadcrumb + a single tree pane whose
  folders expand lazily by fetching `/symbiotica/studio-library?dir=<rel>` (the
  first open passes `sync=1`). Each row is a folder or file; clicking a row's
  select control calls `applySelection(node, entry.rel)` and closes (or a "Done"
  button closes). Folders have both an expand toggle and a select control (both
  files and folders are selectable).
- **Empty state:** a valid listing with `entries: []` renders a distinct message
  ("No files in this studio library yet"), not a blank pane (Appendix B #21).
- **Error state:** a non-`ok` fetch throws in `fetchJson`; the overlay catches and
  renders the message inline (Appendix B #5).
- A "route not yet live on this sandbox" `404` (a warm editor predating this
  release, Appendix B #12) surfaces through the same inline error path.

### 5. Tests

- `tests/test_studio_library.py` (pytest, real tmp trees; every absolute-path
  expectation compared against `os.path.realpath(...)` / `tmp_path.resolve()` to
  survive macOS `/private` symlinks — Appendix B #19):
  - `resolve_studio_path`: valid file → absolute; valid folder → absolute; the
    studio root itself; **empty selection → ValueError**; **absolute selection
    (`/etc/passwd`) → ValueError**; **`..` escape → ValueError**; **in-tree symlink
    pointing outside → ValueError**; non-`studios/` prefix → ValueError; invalid
    slug (`Bad_Slug`, trailing junk) → ValueError; **a >32-char kebab slug
    resolves** (proves the studio, not user-id, shape); missing path → ValueError;
    **`base_dir=""` and `base_dir="relative"` → ValueError** (no CWD re-anchor).
  - `resolve_selection`: folder → `is_dir True`; file → `is_dir False`.
  - `selection_fingerprint`: changes on file mtime and on file size; **changes when
    a direntry is added/removed under a selected folder**; **does NOT change on an
    in-place file rewrite under a selected folder** (the documented limitation);
    stable across unchanged calls; stable (`"unresolved"`) for an unresolvable
    selection; a `None` selection does not raise.
  - **CANVAS_STUDIO invariance:** with `studios/ggs/x.png` present and no
    `studios/imperia`, `resolve_selection`/`selection_fingerprint` return the ggs
    result with `CANVAS_STUDIO=imperia`, with it unset, and identically across both.
  - `list_studio_dir`: lists dirs-first then case-insensitive; hides `MODEL_KINDS`
    at the studio root but **not** nested; per-entry `rel` is `studios/<studio>/<...>`;
    `parent` is `None` at the root; a `dir` escaping the studio root → `{"error"}`,
    not a raise; a `dir` pointing at a **file** → `{"error"}`; a NUL byte in `dir`
    → `{"error"}`, not a raise; a **missing studio root → empty listing** (not
    error); a prefix-collision sibling root (`studios/ggs-2` when browsing
    `studios/ggs`) is not treated as inside; dotfiles skipped; an in-tree symlinked
    dir types as `"dir"`; **round-trip:** list root → take the first dir entry's
    `rel` → list *that* → assert its children (proves the namespace round-trips).
- `tests/test_routes_studio_library.py` (pytest): a **capturing** `json_response`
  stub (records `(body, status)`, returns a sentinel) driven via
  `asyncio.run(studio_library(req))` with a `SimpleNamespace(query={...})` request;
  `monkeypatch.setattr(studio_library, "STUDIO_ASSETS_DIR", tmp)` (late-bound in the
  handler) and `monkeypatch.delenv("CANVAS_STUDIO", raising=False)`:
  - no `CANVAS_STUDIO` → `503` + error payload (not a stubbed-call assertion).
  - a real tmp tree → `200` + payload whose `entries`/per-entry `rel` match the
    tree (a **real** delegation assertion, not "the mock was called" — Appendix B
    #10).
  - an escaping `dir` → `400` + `{error}`.
  - **sync path** (patch `asyncio.create_subprocess_exec`): `sync=1` spawns and
    the listing still returns; a timed-out sync (patched `wait_for`) still returns
    a listing and calls `proc.kill()`; a `FileNotFoundError`/non-zero exit still
    lists; `sync` absent (no `sync=1`) → no spawn.
- `tests/js/studio_library.test.mjs` (node's runner + `comfy_stub.mjs`):
  - `applySelection` writes the entry's `rel` into the `selection` widget and the
    summary widget reflects `summaryLabel`; the summary widget is `serialize:false`.
  - `summaryLabel` is prefix-bearing (`studios/ggs/...` → contains `ggs`); empty →
    `"no selection"`.
  - `onConfigure` (create with `selection:""` → summary empty; set the widget
    value; call `onConfigure()`; `await tick()`; summary shows the stored pick).
  - a valid empty listing renders the empty-state message; a thrown fetch renders
    the inline error.
- **`tests/test_shim.py`:** add `pipeline.studio_library` to the pure-import list
  (it imports with no ComfyUI present). `pipeline.nodes` still raises `ImportError`
  outside ComfyUI, unchanged.
- **Node-class assertion (stretch, if cheap):** stand up the erpk `comfy_api`
  stub pattern (a ~10-line `sys.modules` shim, per the session narrative's proven
  experiment) in a dedicated test so `SymbioticaStudioLibrary.define_schema()`
  runs — asserting the two outputs, the `selection` input's position/advanced flag
  (and `socketless` if adopted), and that `execute()`/`fingerprint_inputs` ignore
  `CANVAS_STUDIO`. This pins the node face itself, not only the pure functions; it
  is additive and never weakens `test_shim.py`.

---

## Data flow

```
studio upload (hub) ──► R2 studios/<slug>/… ──► symbiotica-comfy-studio-assets Volume
                                                          │  (mounted /studio-assets on editor+GPU)
browser open (sync=1) ─► route: await sync mount ─► list_studio_dir(root, CANVAS_STUDIO, "")
   click entry ─► applySelection ─► selection := "studios/<slug>/references/hero_pose.png"  (widget, in graph)
   queue ─► execute(selection) ─► resolve_selection("/studio-assets", selection)
          ─► ("/studio-assets/studios/<slug>/references/hero_pose.png", is_dir=False)
```

## Error / state handling

| Condition | Behavior |
|---|---|
| No `CANVAS_STUDIO` (route) | `503` `{error:"studio library not available"}`; JS inline error |
| Escaping / malformed `dir` (route) | `400` `{error}`; JS inline error |
| Route not yet live on a warm sandbox | `404`; JS inline error (see Rollout) |
| Valid but empty studio (route) | `200` `{entries:[]}`; JS empty-state message |
| `sync` fails/times out | Best-effort; list the (possibly stale) mount anyway; loop never blocked |
| Empty selection at execute | `ValueError("no selection")` → ComfyUI surfaces the node error |
| Absolute / `..` / symlink-escape selection | `ValueError` — fail closed, never returns an out-of-root path |
| Selection resolves but file gone | `ValueError("not found: <rel>")` |
| `list_studio_dir` target escapes / file-as-dir / NUL | `{error}` payload, never a raise |
| Non-string `selection` (socket-wired `None`) | Coerced to `""`; no crash, treated as no selection |

## Rollout

The node is **not** live merely because this repo's `main` moved:

- **Distribution.** Users get the node via a ComfyUI-registry release (a version
  bump + a published GitHub release), not from a raw `main` push — the feature PR
  itself does not bump the version (see Appendix B #13 and "Release deliverables").
- **Hosted canvas.** The Modal editor exposes the new route/node only after the
  released pack syncs onto the NODES_DIR Volume **and** the sandbox recycles —
  aiohttp freezes its router at boot, so a **warm editor sandbox will 404 the
  `/symbiotica/studio-library` fetch** and omit the node from `/object_info` until
  it reboots. The JS treats that 404 as an inline error state.
- **Prod Volume.** The prod `studio-assets` Volume is a separate namespace from
  dev; it needs its own populated `studios/<slug>/…` tree before the picker shows
  anything there.

## Release deliverables

Shipped **in the feature PR**:

- **README.md** — a bullet for **Symbiotica Studio Library** under the Order
  pipeline section (`- **Symbiotica Studio Library** — …`), matching the existing
  node-list format.
- **CHANGELOG.md** — a `### Added` bullet under the next unreleased version
  heading (format per the `## 2026.7.2` `### Added` block that documents Files
  Read).

Deferred to the separate **release step** (NOT the feature PR):

- **`pyproject.toml` version bump + registry publish.** `main` is at `2026.7.6`
  with parallel release PRs in flight; bumping the version in a feature branch
  risks a publish collision (the ordering hazard the session already learned).
  The release flow (`/claude-release:release`) owns the bump and the CHANGELOG
  heading finalization once this merges.

## Out of scope (YAGNI)

- Image thumbnails in the browser (add later via `register_root` + the existing
  `/symbiotica/local-image` route if wanted).
- Refactoring the four existing containment call sites onto a shared resolver —
  the new node + route use `resolve_studio_path`; the existing sites
  (`files_read.py:63`, `routes.py:45,300,327`) each have incompatible policy
  (return-None / skip-continue / output-dir) and keep their working code (a
  separate, optional consolidation — Appendix B #20).
- Multi-select, a configurable model-kind toggle, listing pagination, and
  **server-side recursive search** (v1 ships a client-side name filter over the
  current pane only — added per Alex's request during the build).

---

## Appendix A — Fable pre-build validation dispositions

Fable validated the design against actual source (2026-07-23). Dispositions:

| # | Finding | Disposition |
|---|---------|-------------|
| 1 | `CANVAS_STUDIO` is editor-only, absent on GPU sandbox by design → env-based execute() breaks in split mode | **Adopted.** Env-free execute; studio baked in at browse time; store volume-relative; confine to Volume root. |
| 2 | v2 mount is stale until an `/object_info`-triggered sync | **Adopted.** Bounded `sync` on browse-session open. |
| 3 | Model files already native via `/comfy-models` → node duplicates a shipped feature for models | **Adopted.** Hide `MODEL_KINDS`; node targets non-model assets + folders. |
| 4 | Empty/absolute selection need distinct rejections; route needs realpath rule too; add mtime/size fingerprint | **Adopted** across `resolve_studio_path`, the route, and `fingerprint_inputs`. |
| 5 | Category should be lowercase `symbiotica*`; prefer V3 pipeline style | **Adopted.** `symbiotica/pipeline`, `io.ComfyNode`. |
| — | Second output `is_dir` to avoid downstream `isdir` | **Adopted** per Alex (`path` + `is_dir`). |
| — | Fullscreen overlay vs cascading combo | Minimal single-select overlay (not the files_read group machinery). |
| — | Reuse `is_allowed`/`register_root` for thumbnails | Deferred (thumbnails out of scope v1). |

## Appendix B — Adversarial review dispositions

A 7-lens Workflow reviewed this spec against real source before any code
(2026-07-23): **48 findings raised → 38 confirmed** under refute-by-default
verification, **+ 4 completeness findings**, deduplicated to **23 distinct
defects**. The load-bearing security design (realpath host-path-escape guard) and
every locked decision survived; the defects below were spec-level and are applied
above. Two facts were re-verified directly against `services/comfy-modal` before
adopting: `MODEL_KINDS` is 8 (`canvas_entry.py:14-25`) and the volume-sync idiom
is `await asyncio.create_subprocess_exec("sync", …) + wait_for + kill`
(`symbiotica_platform/route.py:206-213`, `canvas_glue.py:1681`).

| # | Sev | Defect | Disposition |
|---|-----|--------|-------------|
| 1 | important | `rel`/`dir` namespace mismatch (studio-relative vs volume-relative) — every folder expand double-prefixed; `parent` unfloored; no round-trip test | **ADOPT.** One volume-relative namespace everywhere; `""` a route-only sentinel; hide-`MODEL_KINDS` keyed on target-is-root; `parent:None` at studio root; round-trip test. (§"One namespace", §1) |
| 2 | important | `list_studio_dir` could raise a 500 (missing/unprovisioned root, NUL, file-as-dir, FUSE `OSError`) | **ADOPT.** Wrap body `except (ValueError, OSError)→{error}`; missing root → empty listing; tests for each. (§1) |
| 3 | important | `MODEL_KINDS` is 4 of the real 8 → leaks model dirs; tautological drift test; false prose | **ADOPT.** 8-name frozenset w/ `canvas_entry.py:14-25` source-of-truth comment; pinned-literal drift test. Registry-derivation deferred. (§1) |
| 4 | important | Blocking `subprocess.run("sync")` in an `async def` stalls the event loop; cited precedent is async | **ADOPT.** `async` `create_subprocess_exec` + `wait_for` + `kill`; timeout-and-proceed; sync tests. Reject `/platform/refresh-models` reuse (cross-repo coupling). (§3) |
| 5 | important | `200 + {error}` blanks the pane under `fetchJson` (throws only on `!res.ok`); untested | **ADOPT.** Real statuses (`503`/`400`); reuse `fetchJson`; JS inline-error test. (§3, §4) |
| 6 | important | Slug regex is the user-id shape (`[a-z0-9_-]{1,32}`), not the studio shape | **ADOPT.** `[a-z0-9]+(?:-[a-z0-9]+)*` (`studio_fs.py:9`), `.fullmatch()`; >32-char-kebab test. (§1) |
| 7 | important | Node class untested; new logic placed in the one module the suite can't import | **ADOPT.** Move logic to pure `studio_library.py` (`resolve_selection`, `selection_fingerprint`); add to `test_shim.py`. (§1, §2, §5) |
| 8 | important | mtime+size fingerprint misses folder-content changes | **ADOPT (option b).** Folder → direntry-set hash; document that in-place rewrites under a folder don't invalidate; test. (§1) |
| 9 | important | JS click-flow untestable (`comfy_stub` `addEventListener` no-op, no `dispatchEvent`) | **ADOPT.** Export pure `applySelection`/`summaryLabel`; test those; scope DOM test to stub capabilities. (§4, §5) |
| 10 | important | Route tests unwritable (`_load_routes` stubs `json_response→None`, no async) + one tests mocked behavior | **ADOPT.** Capturing `json_response` stub + `asyncio.run`; real-tree payload assertion. (§5) |
| 11 | important | Headline invariant "execute() ignores `CANVAS_STUDIO`" untested; L16 self-contradiction | **ADOPT.** Reword L16 (tenant-env-free); CANVAS_STUDIO-invariance test on the pure funcs (+ node-class stretch test). (Global Constraints, §2, §5) |
| 12 | important | Rollout silent — warm editor 404s the new route; how it reaches a sandbox unstated | **ADOPT.** Rollout section; 404 inline-error state. (§Rollout, §4) |
| 13 | important | Release deliverables omitted (README, version bump, CHANGELOG) | **ADOPT + ADAPT.** README + CHANGELOG in the feature PR; version bump deferred to the release step (main at 2026.7.6 with parallel release PRs → collision risk). (§"Release deliverables") |
| 14 | minor | `fingerprint_inputs` crashes on a non-string (socket-wired `None`) `selection` | **ADOPT.** `str(x or "")` coercion at the pure-function boundaries; `socketless=True` if the installed `comfy_api` supports it (verify — unused in repo). (§1, §2) |
| 15 | minor | Empty/relative `STUDIO_ASSETS_DIR` re-anchors the confinement root to CWD | **ADOPT.** `(env or "").strip() or "/studio-assets"`; refuse non-absolute / non-existing base; tests. (§1) |
| 16 | minor | `os.scandir(follow_symlinks=…)` invalid signature; symlink typing inconsistent listing vs node | **ADOPT.** `os.scandir(target)` + `entry.is_dir(...)`; type children with `os.path.isdir` (follow) so listing matches `execute`; symlinked-dir test. (§1) |
| 17 | minor | Summary widget never re-syncs after workflow load | **ADOPT.** Chain `onConfigure` + `queueMicrotask` re-label; reload test. (§4, §5) |
| 18 | minor | Cross-studio stored selection unlabeled (summary strips slug) | **ADOPT.** Prefix-bearing `summaryLabel` (`ggs · …`); pin "a stored selection pins its studio". (§4) |
| 19 | minor | Path assertions red-local/green-CI on macOS (`realpath` base) | **ADOPT.** Compare against `os.path.realpath` / `.resolve()` in tests. (§5) |
| 20 | minor | `resolve_studio_path` mislabeled "shared containment resolver (extracted)"; "three" sites is four; nothing adopts it | **ADOPT (prose).** Rename to studio-path resolver; "four" sites listed; extraction stays optional/out-of-scope. (§1, §"Out of scope") |
| 21 | minor | No empty-state UX for a valid-but-empty listing | **ADOPT.** Distinct JS empty state; pairs with #2 (`entries:[]`). (§4) |
| 22 | minor | Single-level listing unbounded, no cap | **ADOPT (state the decision).** v1 accepts unbounded (small libraries, YAGNI); documented non-goal. (§1) |
| 23 | minor | Canonical-form rule for `selection` (slash-only, no trailing sep) | **REJECT** — refuted by the data flow: the server is the sole `rel` producer and the JS stores it verbatim, so non-canonical rels never arise from a real pick; hand-edited ones already fail closed. (The non-string half is adopted as #14.) |
