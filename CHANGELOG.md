# Changelog

Versions are `YYYY.M.BUILD` — the year, the month, and a build number that
restarts each month. Releases through `2.43.0` used semantic versioning.

Because the version no longer encodes compatibility, any release that changes a
node's inputs, outputs, or id says so at the top of its entry.

## 2026.7.23

**Node change.** `SymbioticaTemplateLibrary` gains two inputs, `kind` and
`month`. Saved workflows keep working — an omitted `kind` reads as "All", which
browses every pool, exactly the old behaviour.

### Added
- **Saved templates now have two pools, by where they came from.** The Auto
  Packer already knows its source; now the save follows it:
  - a pack fed by the **Reference Browser** is a *reference* template — a style
    guide built from the game's asset library, valid for any order — and is
    written to `<project>/templates/reference/<name>/`, deliberately month-free;
  - a pack fed by **Order Specs** is an *order* template — the design guide for
    one month — and is written beside that month's order, in
    `<project>/orders/<Client-Month>/templates/<name>/`. When the month has no
    client-refs folder it falls back to `<project>/templates/orders/<month>/`,
    still month-scoped.

  The `💾 Save as template` button names the pool it will write to ("Save as
  reference template" / "Save as order template") and the success toast says
  which pool the sheets landed in.
- **The Template Library browses one pool at a time.** Its new `kind` widget
  picks Reference, Order, or All; with Order it lists the templates of the month
  in its new `month` widget (the same dropdown Order Specs uses; empty = the
  project's first month). Drop two Library nodes — one Reference, one Order — to
  wire a style-guide sheet and a design-guide sheet into the same downstream
  graph. Rows carry a pool badge (`ref` / the month), so the same name in both
  pools is tellable apart, and the browser's crumb shows the folder a save of
  that pool lands in.
- Template ids on the `selected` / `checked` wires are pool-qualified
  (`reference/blossom-tower`), so one slug can exist in both pools without them
  shadowing each other — including on delete. Bare slugs from workflows saved
  before this release still resolve.
- `GET /symbiotica/pack-template-list` and `POST
  /symbiotica/pack-template-delete` take `kind` and `month`; the list response
  adds `dirs` (everything browsed) and each template carries `kind`, `month`,
  and `key`.

### Changed
- Order Specs and the Reference Browser stamp `source` (`order` / `reference`)
  on the `order` wire, and every saved template records its `kind`. A template
  saved before this release has its kind inferred from its frozen order (a month
  or a catalog root means it came from an order) and stays where it is — visible
  under **All**, which also browses the old flat `<project>/templates/`.

## 2026.7.22

**Node change.** `SymbioticaFilesRead` is gone, replaced by
`SymbioticaReferenceBrowser`. A workflow that used Files Read will report the
node as missing; drop a Reference Browser in its place and re-pick.

### Added
- **Symbiotica Reference Browser** — build a template sheet out of the game's
  existing asset library, with no order and no client briefs. Wire the Studio
  Library's `path` into it, browse the library **inside the node**, and tick what
  you want: a folder becomes one sheet row and the images inside it become that
  row's cells; the folder that holds the row is its category. The `order` output
  is the same wire Order Specs emits, so the Auto Packer, Model Preset, and Auto
  Packer Settings nodes work exactly as they do for a month's order — which means
  the Auto Packer can now build templates from scratch, not only from an order.

  A category's layout convention ("food is three rows, decorations are two per
  row") is a Model Preset plus Auto Packer Settings pairing, so save it once with
  `💾 Save as template` and reload it from the Template Library.
- `GET /symbiotica/browse-refs` — one level of a reference root: its folders and
  its images with pixel sizes, confined to the root by realpath containment.

### Removed
- **Files Read.** It put the folder tree behind a fullscreen overlay, made you
  type the folder path, and grouped by tick order rather than by the library's
  own structure. Its builder, hardening, and tests carry over to the Reference
  Browser intact; only the interface was wrong.

## 2026.7.21

A diagnostics release. No node's inputs, outputs, or ids changed.

### Fixed
- **A failed extension registration is no longer silent.** ComfyUI imports every
  file under a pack's `web/` directory in parallel and swallows each import's
  error into a `console.error`, so a module that throws while registering leaves
  its nodes showing only their bare Python widgets — no buttons, no dropdowns, no
  panels — with nothing on the canvas saying why. All seven of the pack's
  extensions now register through a wrapper that catches the failure, logs it
  with the cause, and raises a dismissible banner naming the extension that died
  and what to check.

  This is what hid the real fault behind `2026.7.16`–`2026.7.19`: a stale
  `order_pipeline.v2360.js`, left on a deploy volume by an earlier cache
  workaround, was served alongside the current `order_pipeline.js`. Both called
  `registerExtension` with the name `symbiotica.order_pipeline`, the frontend
  threw `Extension named '…' already registered.` on whichever lost the import
  race, and the loser's nodes — Template Library, Order Specs, Auto Packer — came
  up raw. Because it was a race, it looked intermittent. The wrapper cannot
  prevent a collision; it makes one impossible to miss.

### Added
- **`Trellis 2 Image to 3D (fal)`** — a single image to a 3D mesh via fal.
- **`claude-opus-5`** in the LLM model lists; `claude-opus-4-8` dropped.

## 2026.7.20

**New nodes** — this release adds the **Hypereel** streamer-reel pipeline: 8 new
node ids under `Symbiotica/Hypereel`. No existing node's inputs, outputs, or id
changed.

### Added
- **The Hypereel streamer-reel pipeline**, a node-for-node port of the Symbiotica
  platform's reel workflow: turn a product URL and raw gameplay into a vertical
  facecam-over-gameplay reel.
  - `Hypereel Product Scrape (URL to references)` — a product, app, or app-store
    page becomes a logo + screenshots (IMAGE outputs) and a product summary for the
    script LLM; follows the first app-store link for the curated promo screens and
    refuses non-public targets (the SSRF guard resolves the host before it trusts it).
  - `Hypereel UGC Presets (style · hook · setting)` — the platform's UGC preset
    catalogs as dropdowns, emitting each template plus a combined pre-labeled block.
  - `Hypereel Analysis Prompt (auto duration)` — builds the highlight-analysis
    prompt from the video's real duration, which also feeds Highlight Pick's guard.
  - `Hypereel Highlight Pick` — parses a Gemini highlight list into one highlight's
    start/end/duration plus the text row.
  - `Hypereel Duration Parse (script to prompt + seconds)` — strips the script's
    trailing `DURATION: N` line into a clean prompt plus clamped seconds.
  - `Hypereel Clip (cut by seconds)` — an ffmpeg window cut whose cost is constant
    regardless of source length, clamped inside the source.
  - `Hypereel Screen Glow (light from gameplay)` — screen-blends the gameplay's
    per-frame color onto the facecam as a bottom-up monitor glow; audio untouched.
  - `Hypereel Stack Composite (facecam over gameplay)` — named vertical/PiP layouts,
    a voice+game audio mix, up to 4 hard-cut pairs, and an optional MASK cutout.

### Fixed
- **SSRF hardening in Product Scrape** — the fetch guard now resolves the host
  before judging it, so a public name whose A record points at a private or
  metadata address is rejected; it also normalizes numeric-obfuscated IPs,
  re-checks every redirect hop, and blocks CGNAT/multicast. A timing-out image URL
  degrades to a skipped screenshot instead of crashing the whole node.
- **Stack Composite** — a masked pair no longer lets the facecam's native fps
  override the requested output fps, and a voiceless facecam no longer crashes the
  audio mix.
- **Screen Glow** — falls back to format-level duration so the glow signal can't
  flatten to a single static color.
- **Cancel** — long ffmpeg encodes (composite, glow) now stop promptly on ComfyUI
  Cancel instead of running to completion.
- Clip duration is no longer capped at 600s; clock-mismatched timestamps fail
  loudly instead of silently clamping; scraped names/descriptions decode HTML
  entities and match the platform's product line exactly.

## 2026.7.19

### Added
- **Sheet thumbnails are back on the Template Library node**, as a compact strip
  under the Browse button showing the sheets of the templates in play (the one
  in use plus every checked one), so the node shows what it will output without
  opening the browser. The overlay stays the place to pick, check, and delete.

## 2026.7.18

### Changed
- **The Template Library browses in an overlay now, not an embedded panel.**
  The node carries a native "📂 Browse template library" button (the Studio
  Library pattern) plus a read-only summary of the current pick; clicking it
  opens a centered overlay with the template list — output checkboxes, sheet
  counts, thumbnails, "use", and delete all live there. The embedded DOM panel
  did not reliably render in the Vue UI, which left the node blank on a fresh
  start. No node inputs, outputs, or ids changed; workflows saved with the old
  panel re-fit their height on load.

## 2026.7.17

### Changed
- **Order Specs "📁 Read folder" and Auto Packer "💾 Save as template" are now
  native litegraph buttons** (like the Studio Library's "Browse" button), not
  DOM widgets. Native buttons render in both UIs and are never hidden at low
  zoom, so neither comes up missing on a fresh Comfy start. (The old DOM-widget
  workaround dated from a frontend version that didn't draw native buttons; it
  does now.)

## 2026.7.16

### Fixed
- **Order Specs "📁 Read folder" button no longer disappears on a fresh Comfy
  start.** It's a DOM widget that was flagged `hideOnZoom`, so ComfyUI hid it
  (like the other DOM widgets) whenever the canvas was below the zoom threshold —
  it looked missing at a normal working zoom. It now always renders.

## 2026.7.15

A browse-time fix for wired Studio Library paths. No node's inputs, outputs, or
ids changed — nothing here breaks an existing workflow.

### Fixed
- **Wiring `project_path` from the Symbiotica Studio Library node now fills the
  Order Specs pickers.** The wire carries the node's volume-relative selection
  (`studios/<slug>/...`), which the browse routes' directory checks rejected —
  "Read folder" and the month/feature dropdowns came up empty while execute-time
  rendering worked. The `list-orders`, `parse-order`, `list-assets`, and
  `pack-template-list` routes now resolve that form to its absolute path through
  the Studio Library's confinement resolver; any other path behaves as before.

## 2026.7.14

### Fixed
- **Auto Packer `border` and `padding` now work.** They were ignored by the
  packer's layout (hardcoded 0 cell gap, no box drawn). Now `padding` is the gap
  between a region's cells (an asset and its mirror) as well as between packed
  strips, and `border` draws a frame that many px thick around **each icon cell**
  — the asset and its mirror each get a box ("icon inside a box"), in a color
  that contrasts the sheet background. `border = 0` = no box.

## 2026.7.13

### Fixed
- **Template Library `sheets`/`sheet_prompts` no longer crash a downstream
  Preview / Show Text when nothing is checked.** An empty output list made
  ComfyUI do `v[-1]` on `[]` → `IndexError`. Now the outputs fall back to the
  `use`-selected template when no box is ticked, and never emit an empty list
  (a small placeholder tile + hint prompt when nothing is checked or selected).

## 2026.7.12

Per-size Auto Packer scaling. **Input change:** the Auto Packer Settings node's
`scale` and `scale_max_canvas` widgets are replaced by `scale_target` +
`scale_max` (a stale saved value resets to default; no outputs or ids changed).

### Changed
- **Scaling is now per-size.** Each sprite grows so its longest canvas edge
  reaches ~`scale_target` px, capped at `scale_max`× and never below 1× (never
  shrinks). So `target 512, max 3×` gives a 128 sprite ×3 (capped), a 256 ×2, a
  512 native — small sprites scale more than large ones, and the cap keeps a
  scaled sheet from overflowing. Replaces the old single flat `scale` +
  `scale_max_canvas` cutoff, which scaled every sub-cutoff size by the same
  factor. `scale_target = off` disables scaling; `fit width` is unchanged.

## 2026.7.11

Template Library now carries settings on load and can output saved sheets
directly. **Input/output change (backward compatible):** the Template Library
node gains a `checked` input and two outputs (`sheets`, `sheet_prompts`); the
existing `template` output is unchanged (still slot 0).

### Added
- **Template Library → `sheets` / `sheet_prompts` outputs** + a per-row
  checkbox. Check any templates to stream their *saved* sheets and client
  prompts straight out — no re-render through the Auto Packer. Prompts are now
  stored in `template.json` at save time (older templates emit empty prompts
  until re-saved).
- **Selecting a template now loads its Model Preset + Pack Settings** onto the
  Auto Packer's wired Preset / Settings nodes (reverse-mapped from the saved
  recipe), so those nodes show — and the pack uses — the values the template was
  saved with. Previously a wired Settings node silently overrode the template.

## 2026.7.10

Auto Packer combined/split variant fixes. **Output/naming change:** combined
variant sheets are named differently (see below); no node inputs/outputs/ids
changed.

### Fixed
- **Combined sheets** no longer split a single directional asset's references
  across separate `-v1`/`-v2` sheets. Every reference becomes its own mirror-pair
  region, and a `(category, canvas)` group's regions now paginate by
  `max_rows_per_sheet` — so an asset's refs stay together on one sheet when they
  fit (e.g. a 256 decoration with 2 refs → one combined sheet, both refs). This
  renames combined variant sheets from `<base>-<cat>-v<k>` to
  `<base>-<cat>[-<canvas>][-<page>]`.
- **Split variants** now emits a sheet for a *single-reference* directional
  asset too (its one ref + horizontal flip), not only 2+ ref assets — so every
  directional item gets its per-item ref+flip sheet.

## 2026.7.9

Template Library — save an Auto Packer setup once and reload it after a restart.
**Input change (backward compatible):** the Auto Packer gains an optional
`template` input, a `save_as` field, and its `order` input is now optional;
existing workflows keep working (order still drives it when wired).

### Added
- **Symbiotica Template Library** (new node) — browses a project's saved Auto
  Packer templates as folders with sheet thumbnails and outputs one as a
  `SYMBIOTICA_PACK_TEMPLATE` recipe (frozen order + model preset + pack settings
  + category + per-asset overrides). Wire it into the Auto Packer's `template`
  input to re-pack or edit a saved setup without rebuilding the chain.
- **Auto Packer → "Save as template"** button — writes this run's sheets plus
  the effective recipe to `<project>/templates/<name>/` (sheet PNGs +
  `template.json` together). Falls back to `output/templates/` when the project
  folder is unwritable (read-only Modal Volume) or unset; the Library browses
  both.
- `/symbiotica/pack-template-list` and `/symbiotica/pack-template-delete` routes.

### Changed
- **Symbiotica Order Specs** — the `order` wire now also carries `project_path`
  and `month` (additive) so a template save can reproduce the exact event.
- The Auto Packer `category` default is now empty (the "unset" sentinel that
  defers to a wired template); an explicit "All" is honored as "pack every
  type". A fresh node still shows "All".

## 2026.7.8

Studio Library browser UI polish. No node's inputs, outputs, or ids changed —
nothing here breaks an existing workflow.

### Changed
- **Symbiotica Studio Library** browser is now a centered ~80% modal over a
  dimmed, click-to-close backdrop (was fullscreen), restyled against the
  symbiotica hub design tokens. Clicking a folder row opens it (files select).
- A shared `web/js/hub_theme.js` module now holds the pack's base palette and
  interaction styles for web extensions to build on.

## 2026.7.7

Adds a new node. No existing node's inputs, outputs, or ids changed —
nothing here breaks an existing workflow.

### Added
- **Symbiotica Studio Library** — a single-select browser (with a
  client-side name filter) for the active studio's non-model asset tree —
  reference images, arbitrary files, and folder paths — emitting an absolute
  sandbox path plus `is_dir` for downstream path-consuming nodes. Model
  kinds stay hidden (already native via `/comfy-models`).

## 2026.7.3

Two fixes for the hosted (Modal) canvas and the Prompt Tuner. No node's
inputs, outputs, or ids changed — nothing here breaks an existing workflow.

### Fixes

- **Order Specs works on the hosted canvas when `project_path` is wired.**
  Feeding the path in over a wire (a Local/Modal switch) instead of typing it
  now populates the month and feature dropdowns and loads the Auto Packer
  thumbnails — no more wiring a packer to a Preview and queueing just to fill
  the pickers. A new "📁 Read folder" button on Order Specs resolves the path,
  fills the pickers, and registers the reference root on demand. A wired path
  only ever fills the dropdowns; it never overwrites the month or feature you
  picked, so routing `project_path` through a switch can't silently render the
  wrong order.
- **NS Prompt Tuner no longer records a stray refinement after an interrupted
  queue.** Cancelling a run mid-loop could leave a pending serve that the next
  pinned Load counted as one spurious refinement; the stall guard now abandons
  that pending serve when it halts.

## 2026.7.2

Adds three new nodes (**Symbiotica Files Read**, **NS Prompt Tuner Load**,
**NS Prompt Tuner Save**). No existing node's inputs, outputs, or ids changed —
nothing here breaks an existing workflow.

### Added

- **Symbiotica Files Read** builds template sheets from loose client reference
  folders, without a monthly order spreadsheet. Its face is a reference folder,
  a base name, and a files-browser button; it emits the same `order` wire as
  Order Specs, so it feeds the existing Auto Packer, Model Preset, and Auto
  Packer Settings nodes unchanged. In the browser a folder becomes one sheet
  row and the files you tick become its cells, with a name search and
  pixel-size filters for grouping similar images.
- Nested reference paths now resolve for any sheet draw (a shared exact-rel
  then basename rule), and a new `/symbiotica/ref-image` route makes the canvas
  preview match the queued sheet. Existing spreadsheet orders are unaffected.
- **NS Prompt Tuner Load / NS Prompt Tuner Save — a self-improving
  system-prompt loop.** Each queue run serves the current best system prompt,
  generates, has a refiner LLM critique the result against a design reference,
  and saves the refined prompt as the next version; Auto-Queue iterates
  hands-free. The per-`tuner_id` state file keeps every version and critique,
  the refiner sees the full history plus the user's rough guidance, and the
  loop halts itself on convergence or `max_iterations`. `version_override`
  pins a version for production: recording stops and repeat runs cache fully.
  Malformed or truncated refiner replies are rejected rather than saved. See
  `docs/prompt-tuner.md`.
- **Cancel works on hosted video jobs.** Interrupting a run now actually stops
  Wavespeed and Grok video jobs instead of letting them bill to completion.

### Fixes

- **The tuner cannot re-bill a stalled loop.** A muted or unwired Save node
  used to leave the loop generating (and paying) every queue with no progress;
  it now halts after three unrecorded serves and says which node to fix. Two
  pinned Loads sharing a `tuner_id` no longer churn the state file and re-run
  both branches every queue.
- **NS Music and NS Sound Effects no longer store the ElevenLabs key in the
  workflow**, and the pack reads the Settings-UI keys it already asks users
  for. Workflows stay shareable without leaking credentials.

### Other

- Registry publishing hardened: the publish fires on the release itself, and
  release notes land in the registry changelog automatically.

## 2026.7.1

First release using calendar versions. No node inputs, outputs, or ids changed —
nothing here breaks an existing workflow.

### Fixes

- **Order Specs no longer floods the server with order parses.** The Auto
  Packer's assets panel and its category combo both asked for the order while
  rendering, and the answer they got sent them round again — a request per round
  trip per packer, multiplying with each packer wired up. Worst measured case
  went from 942 requests to 1. A parse that fails is remembered rather than
  retried on sight; a rate limit or server error backs off; wiring the node or
  editing project, month, or feature asks again.

### Other

- The node UI has tests now: `tests/js/`, on node's own runner, no dependency
  added. They drive the shipped `web/js` files through a ComfyUI stub.
- Release process written down in `.claude/release/`, and this changelog.
