# Changelog

Versions are `YYYY.M.BUILD` — the year, the month, and a build number that
restarts each month. Releases through `2.43.0` used semantic versioning.

Because the version no longer encodes compatibility, any release that changes a
node's inputs, outputs, or id says so at the top of its entry.

## 2026.8.8

**No node change.** No node is added, removed or renamed, and no input or output
changed position or meaning. A saved workflow needs nothing.

### Added

- **A sandbox can say what kind of run it is.** Calls through Cloudflare AI
  Gateway carry a metadata tag that analytics groups by, and the run type in
  that tag was fixed at `order`, because only order sandboxes routed through
  the gateway. That is about to stop being true: a canvas wired to the gateway
  would have its renders counted as orders, under a label that reads correctly,
  which is the kind of wrong number nobody thinks to question.

  `SYMBIOTICA_AIG_SURFACE` now names the run. It sits beside
  `SYMBIOTICA_AIG_BASE` and `ORDER_STUDIO`, set by whoever creates the sandbox,
  and it is optional: unset or blank still reports `order`. Every sandbox that
  exists today sets nothing and reports exactly what it reported before,
  because changing that would relabel the history their spend is compared
  against.

  It has to reach a sandbox before that sandbox starts routing new traffic.
  Spend already tagged cannot be relabelled afterwards.

## 2026.8.7

**Node change, and this one breaks saved workflows.** `Gemini Image
(Symbiotica)` and `Claude (Symbiotica)` move to ComfyUI's V3 schema. Everything
that varies by model now lives inside the model combo and reaches the node
under a dotted name — `model.resolution`, `model.reasoning_effort`,
`model.images.image_1` — and reference images become numbered slots rather than one
batch input. Widget positions are not shifted, they are replaced, so a workflow
carrying either node must be rebuilt. The Gemini node also gains a third
output, `thought_image`. No node is removed or renamed.

### Added

- **Both gateway nodes now offer what ComfyUI's own nodes offer.** An order
  sandbox has no comfy.org account, so the core Gemini and Claude nodes cannot
  run there and the order template has to use these. Until now that meant
  accepting a poorer node: no thinking control, no sampling parameters, and a
  single resolution list that let the Lite model be set to a size it refuses.

  Gemini gains `thinking_level`, `temperature`, `top_p`, a choice of response
  modalities, the four extreme aspect ratios, optional context files, and the
  `thought_image` output that HIGH thinking produces — which was previously
  discarded, and which an unfiltered run could have shipped as the render.
  Claude gains `reasoning_effort` with the whole per-model matrix behind it,
  and `temperature` on the models that still accept one.

  Both keep what they exist for: the studio's own key through Cloudflare AI
  Gateway, the 10 MB request ceiling that keeps spend attributable, and inline
  base64 images rather than an upload through comfy.org.

  The settings were absent because they cannot be expressed against one flat
  model list — thinking is four different behaviours depending on the model,
  and `temperature` is a 400 on four of them. Per-model inputs are what
  retired that constraint rather than any change at the providers.
### Fixed

- **The Claude node could not read its own reference slots.** It declared
  numbered `image_1..20` inputs but its converter still expected a single batch,
  so any wired reference reached it as a slot NAME rather than pixels. Both nodes
  now share one converter, which is what stops them diverging again.
- **Context files crashed every Gemini request that used one.** ComfyUI's Gemini
  Input Files node hands back objects this node posted without converting, so the
  request failed while being encoded — outside the handler that would have named
  the studio and the gateway.
- **A mismatched interim sketch could destroy a finished render.** Nothing
  constrains the model's thinking sketches to a common size, and batching them
  with the render meant a diagnostic output could fail the real one, blaming
  settings that govern the final image.
- **`thought_image` handed the next node nothing.** With thinking at its default
  it produced no sketch on every run, which reached a save or preview node as an
  absent image and failed there instead of here.

## 2026.8.6

**Node change.** Eight nodes are added: `Camera Shake`, `Focus Pull`,
`Film Grain`, `Chromatic Aberration`, `Product Gallery Scrape`,
`Product Image Sort`, `Load Text File` and `Load Text List`. None of them is
new work — all eight had been running on the Modal install for weeks and were
missing from this repository. No node is removed or renamed, and no existing
input or output changed position or meaning.

### Added

- **Eight nodes that existed only on a deployed volume are now in git.** A
  second, stale copy of this pack (`comfyui-nodes`, version 2026.7.21) sat
  beside the current one on the Modal volume, and ComfyUI loaded both. That
  collision is what raised the "Extension named … already registered" banner —
  but the stale copy also turned out to be the only place these eight nodes
  existed. `git log --all` found no commit, on any branch, that had ever
  contained them. Version numbers made the directory look like a subset of
  `main`; it was not.

  They arrived with no tests at all. `tests/test_rescued_node_registration.py`
  is the floor for that: `__init__.py` discovers nodes by importing every
  non-underscore module under `py/` and swallowing failures into a printed
  traceback, so a module that stops importing removes its nodes from the menu
  in silence. The guard imports each of the eight and asserts it still
  contributes its keys.

### Fixed

- **A brand logo is found where a filename search cannot see it.** The product
  scrape took the first image whose URL contained "logo", which picked
  `Inele_de_logodna` (Romanian for engagement rings) on teilor.ro and missed
  the real wordmark, and it flattened transparency onto black — burying dark
  lettering that is nearly always drawn for a light background.

  The search is now a cascade, most authoritative first: the logo the site
  declares to Google in JSON-LD, then the largest `apple-touch-icon`, then
  files whose name carries "logo" as a *word* (so `logodna` and `catalogo` no
  longer match), then sized link icons, and finally the favicon service, which
  always answers. Each candidate is downloaded in turn and the first that
  decodes at 64px or better wins; transparency composites onto white. The node
  reports whether it found one, so a summary can say so rather than implying a
  mark it never had.

  This fix was also written weeks ago and lived only on that same volume.

## 2026.8.5

**Node change.** Two nodes are added: `Symbiotica Slice Cells` and `Symbiotica
Asset Refs`. `Symbiotica Dataset Reference` gains a third output, `cell_boxes`,
appended after `reference_names`, so every existing wire keeps its slot and
saved workflows are unaffected. No node is removed or renamed, and no existing
input or output changed position or meaning. Under calendar versioning the
major is the year, so nothing in the version number signals this.

### Added

- **A packed sheet can be cut back into the assets it was packed from.**
  Editing one asset out of a three-icon sheet meant describing it to the model
  in words — "the plate, row 2 column 2" — because nothing downstream knew
  where the cells were. The packer knew: it places every sprite on a grid and
  then discards the boxes. Dataset Reference now reports that grid as
  `cell_boxes`, and Slice Cells cuts an image on it, returning one image per
  cell named by its role. A run that switches asset type re-cuts itself with no
  rewiring — a food sheet gives prep, ready and serving; a chair sheet gives its
  four rotations.

  The grid is derived the way the packer derives it: padding is a gutter counted
  `cols + 1` times, so an interior gap is one padding wide and not two; the
  sheet is centred; and a short row is re-centred, which is what puts food's
  single prep cell over the midpoint of the pair below it. A `_layout.json`
  written beside a type's sheets wins over the computed grid, because it knows
  the sprite aspect and the upscale policy, neither of which is otherwise
  recoverable.

- **Each asset's own client reference, paired with its cell.** Asset Refs hands
  back the reference art the client sent for one asset, in the order the order
  sheet pairs it — prep, ready, serving for a type packed in stages, matching
  the order the cells come out in. One index therefore picks a generated cell
  and the reference belonging to it. Where the two counts disagree the node says
  so on its own body rather than implying a pairing it cannot support, and a
  reference missing from disk is named rather than skipped, since dropping one
  shifts every later index onto the wrong cell.

  References are composited onto a colour rather than converted. These files
  keep live pixels underneath their transparent areas, so discarding alpha
  uncovers that backdrop and turns every soft edge fully opaque — it reads as a
  glow around each asset. The background is selectable to match a generation,
  transparency can be kept instead, and the alpha always comes out as `masks`,
  because ComfyUI carries transparency on a mask wire and never as a fourth
  channel on an image.

### Fixed

- **Two nodes could not see the files they read.** ComfyUI runs a node's
  change-check before the upstream outputs exist, so an input arriving on a wire
  reads as unset there. Dataset Reference hashed a folder listing under its
  `project_path` widget — but the project arrives on the order wire, and that
  widget is empty in every graph that uses one, so it resolved a relative
  `dataset`, the walk raised, the raise was swallowed, and the guard was dead in
  exactly the graphs it was written for. Adding a reference to a type did not
  redraw. Both nodes now consult the projects and folders executions register.

  This matters more now that `cell_boxes` shares that key: the boxes come from
  the packer's rules and settings, which no node lists as an input, so re-ruling
  a type changed the grid while every wired value stayed identical and the crop
  went on cutting the old one.

- **A replaced reference image is noticed.** Asset Refs had no change-check at
  all, and both of its file-naming inputs are linked, so a client dropping in a
  corrected reference under the same filename served the cached tensor of the
  old picture indefinitely.

## 2026.8.4

**Node change.** One node is added, `Claude (Symbiotica)`. Nothing existing is
removed or renamed, and no other node's inputs, outputs or id changed, so saved
workflows are unaffected.

**Deployment change, and it is not backward compatible.** The two gateway
environment variables are renamed and their meaning narrows:
`GEMINI_GATEWAY_URL` → `SYMBIOTICA_AIG_BASE` (now **without** the provider
slug), `GEMINI_GATEWAY_TOKEN` → `SYMBIOTICA_AIG_TOKEN`. A box still setting the
old names routes nothing through the gateway. The Modal secret is renamed
`symbiotica-comfy-aigateway` to match; a secret named `…-gemini` holding
Anthropic credentials was the naming problem that prompted this.

A box still carrying the old names now **raises** rather than falling back. On
an order sandbox that was already the behaviour, since `ORDER_STUDIO` with no
gateway base is an error — but a canvas box has neither, and would have gone on
calling Google directly on a personal key with nobody the wiser.

### Features

- **Claude in the canvas and in headless order sandboxes.** A prompt and up to
  20 reference images go in; Claude's answer comes out as a `STRING`. Claude
  draws nothing — this is a prompt author, a caption or critique step, or a
  structured-extraction step feeding an image node. ComfyUI's own Anthropic node
  bills Comfy credits through `api.comfy.org` and needs a key configured by hand
  in the Settings UI; an order sandbox has neither the credits nor a human.

- **One gateway contract for every provider.** The gateway token proved to be a
  single provider-agnostic value, and the base URL differed between providers
  only in its last path segment — so `<PROVIDER>_GATEWAY_URL` plus `_TOKEN` was
  spending two environment variables per provider to encode one and a half
  facts. Each node now owns its slug as a constant, and a third provider costs
  no variable and no secret edit.

### Fixes

- **A refusal, a truncated answer, a context overflow and an empty reply are
  four errors, not one.** Each names its own fix, because they prescribe
  opposite things: raising the token budget fixes the second and makes the third
  worse. ComfyUI's own node returns the literal string
  `Empty response from Claude model.` for the last of them, which flows
  downstream looking like an answer.

- **A refusal is recognised before the reply is read for content**, because a
  refusal can arrive with partial text attached — read content-first, that text
  is handed back as though it were the answer.

- **A reply that is not a Claude reply says what arrived**, rather than being
  reported as a model refusal and sending someone to rewrite a prompt when the
  endpoint is what is wrong.

### Security

- **Anthropic keys are scrubbed from failure messages** alongside Google ones,
  and no Anthropic key is sent on the gateway arm at all. That second point is
  stronger than hygiene: Cloudflare documents that a key sent alongside BYOK
  causes the request to fail, so a key riding along would break every studio
  call rather than merely leaking.

- **A gateway failure now recognises a third case.** A provider with no stored
  BYOK key at all is the one that does not look like a failure: Cloudflare's
  documented credential precedence is a key on the request, then a stored key by
  alias, then Cloudflare's own credentials billed to the account balance. With
  nothing stored the alias is never consulted, and the call is served on
  Cloudflare's own rail attributed to no studio. It surfaces as an error only
  while that balance is empty.

### Other

- **Reference images are capped by encoded size, not just by count.** Cloudflare
  stores no gateway log above 10 MB and AI Gateway analytics reads the log — so
  a request past that ceiling is spend that never reaches the cockpit, which is
  the entire reason these nodes route through the gateway. A batch over 8 MB is
  refused rather than trimmed: an answer drawn from three of eight references is
  a wrong answer that looks right.

- **Images are resized to each model's own ceiling** — 2576px on Opus 5,
  Sonnet 5, Fable 5 and Opus 4.8/4.7, 1568px elsewhere. Above it the pixels are
  discarded upstream, having already been charged against the log budget.

- No `temperature`, `top_p`, `top_k` or thinking widget. Those parameters are
  removed on Opus 5, Fable 5 and Opus 4.8/4.7 and return 400 there, so a dial
  for them would break the default model.

## 2026.8.3

**Node change.** One node is added, `Gemini Image (Symbiotica)`. Nothing
existing is removed or renamed, and no other node's inputs, outputs or id
changed, so saved workflows are unaffected.

### Added
- **Gemini image generation that works in a headless render.** ComfyUI's own
  Gemini image nodes bill Comfy credits through `api.comfy.org` and need a key
  configured by hand in the Settings UI. An order sandbox has neither a human
  nor a persisted settings file, so those nodes cannot run there at all.

  This one sends the same native `generateContent` request to Cloudflare AI
  Gateway instead, on the studio's key stored there as BYOK, which also puts
  every call in the analytics the cockpit's spend view already reads. A prompt
  and up to 14 reference images go in; the render and the model's own words
  come out.

  Where `GEMINI_GATEWAY_URL` is set the gateway takes the call and a personal
  key never overrides it. Where it is not, the node calls Google directly on a
  key from the widget, the Settings UI or `GEMINI_API_KEY` — the same ladder
  every other provider node uses. A gateway URL set without its token raises
  rather than reaching for a personal key: that call would succeed, and only
  its spend would go missing.

  Each gateway call names the studio twice, from `ORDER_STUDIO`: once to select
  that studio's own stored Google key, and once as a tag the analytics can
  group by. Both are needed and they carry different things — the key alias
  decides who is billed, and no AI Gateway dataset exposes it as a dimension,
  so spend sent without the tag cannot be attributed to anyone. A gateway
  render with no studio raises rather than falling back to the shared key,
  which would bill one studio while the tag claimed another. Every gateway
  failure names the studio and the alias it asked for, whatever went wrong.

  Every failure raises, carrying Gemini's own explanation whenever the reply
  contains one — in a sandbox nobody is watching, the raise is the only
  artifact a human reads, so a generic sentence in place of a specific one is
  the difference between a fixable order and a mystery. A declined generation
  is the case that matters: it comes back as a success, with no image, no
  text, and its whole account of itself in a `finishMessage` field. That is
  what the error reports, rather than this pack's own guess at what went
  wrong. That principle is applied to every path, not only the expected ones: a
  refusal names the reason it stopped for as well as the model's words, a
  reply that is not a Gemini reply at all says what arrived instead of
  reporting a model refusal, an image that will not decode says so, and a
  gateway failure names the studio whose render it was. Credentials are
  scrubbed from all of them, and refused outright when they carry characters
  an HTTP header cannot hold — otherwise the transport library quotes the
  whole header value back in an exception that no scrubber ever sees.

  Misconfigurations that would otherwise be silent are refused: a gateway URL
  that is not `https`, and `ORDER_STUDIO` set with no gateway URL at all. The
  second is the important one — the sandbox launcher sets that variable
  whether or not the secret populated, so its presence without a URL means the
  box was meant to route through the gateway and cannot. Left alone it would
  either fail asking for a key it cannot hold, or succeed on a stray personal
  key with the spend outside the gateway and nobody the wiser.

### Docs
- **The README lists the five nodes `2026.8.2` shipped.** `Order Assets`,
  `Save Render`, `Dataset Reference`, `Category Prompts` and `Prompt Book`
  landed without an entry, so the pack's documentation did not match its
  contents.

## 2026.8.2

**Node change.** Five nodes are added: `Symbiotica Order Assets`, `Symbiotica
Category Prompts`, `Symbiotica Prompt Book`, `Symbiotica Dataset Reference` and
`Symbiotica Save Render`. `Symbiotica Auto Packer` gains a `categories` output,
appended after `sheet_categories`, so every existing wire keeps its slot and
saved workflows are unaffected. No node is removed or renamed, and no existing
input or output changed position or meaning. Under calendar versioning the
major is the year, so nothing in the version number signals this — hence the
note.

### Added
- **A whole feature renders in one pass, per asset and per category.** The
  eight duplicated render groups collapse into one lane: `Order Assets` emits
  one item per asset, index-aligned across names, categories and save paths,
  and ComfyUI's own list fan-out runs the lane once per item. `Save Render`
  files each result under month/feature/category/asset. `Dataset Reference`
  picks a reference per category, seeded per `(seed, category)` so adding a
  type does not reshuffle a pick you already approved.
- **Architect prompts compose from shared game rules.** A project's
  `prompts/_rules/*.md` are read in filename order and prepended to the
  category's own `prompts/<Category>.md`, which stays last because the tail of
  a prompt carries the most weight. A project with no `_rules/` folder behaves
  exactly as before.
- **The prompt book is editable in the graph.** `Prompt Book` reads and writes
  those blocks from the canvas, and every render records which blocks composed
  its prompt — per block, not one hash of the whole thing, so a change to
  lighting is distinguishable from a change to negatives.

### Fixed
- **The auto-packer named a cause it could not know.** When every group
  rendered empty it blamed missing reference files; a missing ref actually
  packs as a blank cell and never reaches that branch. It now reports the
  types it saw and leaves the cause unstated rather than sending you after the
  wrong one.

## 2026.8.1

**Node change.** `Symbiotica Auto Packer` gains a fourth output,
`sheet_categories`. It is appended rather than inserted, so every existing wire
keeps its slot and saved workflows are unaffected. No node is added, removed or
renamed, and no other node's inputs, outputs or id changed. The
`/symbiotica/studio-library` route's reply gained a `sync` field, which only
this pack's own browser reads.

### Added
- **The Auto Packer says what each sheet holds.** It reported which sheets it
  drew and what to call them, but not their asset type, so a graph that wanted
  to file or label sheets per type had to re-derive it by string-matching the
  slug in `sheet_names` — which only works while the slug format holds. Each
  sheet now carries its category, and `sheet_categories` exposes it in the form
  the order writes it ("Food - 3 stages"), index-aligned with `sheets`.

### Fixed
- **The auto-packer left you to guess which switch emptied it.** When a
  combination of settings left it with nothing to draw, it said so without
  saying which setting was responsible.
- **The Studio Library browser could not be refreshed, and could not tell you
  when a refresh had failed.** The volume sync it runs before a listing threw
  away its own outcome three ways: a failure to start returned silently, the
  exit code was never read, and a sync that ran out of time was killed and fell
  through. All three produced the same reply as a sync that worked, so a folder
  created a minute ago and a folder that was never there looked identical. The
  reply now says what the sync did, the panel says so when it did not happen,
  and that warning stands until a sync actually succeeds — every folder opened
  in between comes off the same unrefreshed volume and is exactly as old.

  This is what makes a studio that looks out of date diagnosable. It is not a
  guarantee that it will not happen.
- **Nothing in the browser re-read a folder.** The sync ran once, when the
  browser opened, so a folder created after that could not be reached without
  closing and re-opening. There is a ⟳ control now. It forces the sync rather
  than only re-listing, which would have redrawn the same rows off the same
  volume and read as proof the folder was not there, and it is held while the
  sync runs so that pressing it again cannot queue another.
- **A slow refresh could pull you back to a folder you had left.** The sync
  waits on the volume while the panel stays usable, so its reply could arrive
  after you had already opened something else and quietly replace it. The panel
  now belongs to whatever was asked for last.
- **Repeated refreshes each walked the volume separately.** One walk runs at a
  time per volume now, as the studio service does for the same mechanism. A
  browser arriving while one is in flight waits for that one; a finished walk is
  never reused, so a browse after somebody else's upload still gets a walk that
  can see it.
- **The way out of a folder was a button above the filter box, away from the
  rows.** There is a `..` row at the top of every listing below the studio root.
  It is drawn rather than listed, so it cannot be filtered away with the
  folder's contents, cannot hide the "no files here" message, and carries no
  select control — picking it would have written the parent folder into the
  node's value on what looks like navigation.
- **The studio root left out eight folders without saying so.** It omits the
  model-kind folders (`checkpoints`, `loras`, `vae`, `controlnet`,
  `upscale_models`, `embeddings`, `diffusion_models`, `text_encoders`) because
  models are picked in the model loader node rather than by path. Nothing said
  they existed, and the studio's own web view lists them, so the two disagreed
  by exactly those rows with no way to tell a hidden folder from an absent one.
  The root now says how many it left out, and `show` lists them. A file that
  merely shares one of those names is an ordinary asset and is listed: before,
  it was hidden and then counted as a folder that was not there.

### Other
- The listing route reports the volume sync's outcome on every reply, including
  a refused one. Reporting only failure meant a caller could never learn the
  volume was current again: refreshing inside a folder that had since vanished —
  which is what a stale view produces — ran a clean sync, got a refusal for the
  folder, and left the warning standing over a volume that had just refreshed.

## 2026.7.25

**Node change.** One node is added, `Symbiotica Refs Folder`
(`SymbioticaRefsFolder`). No existing node's inputs, outputs or id changed, so
saved workflows are unaffected.

### Added
- **`Symbiotica Refs Folder`, for handing a graph a folder of images by path.**
  It takes an absolute folder path and a `max_count`, and returns every image in
  that folder in filename order, with the filenames index-aligned beside them
  and a count. There is no browsing and no picking, so a dispatcher can bind
  the path and run the workflow headless over the API. The Reference Browser
  cannot do this, because its selection is authored by its own browser widget
  and it emits an order rather than images.

  A relative or empty path is refused before the folder is looked at: it would
  resolve against wherever the ComfyUI process was started, so a folder that
  merely happens to sit under that directory would bind the graph to it. A
  missing folder, a folder with no images, and a folder where nothing decodes
  all raise, rather than handing the graph zero references in silence. One
  corrupt file is skipped instead, and `max_count` counts what comes back, so
  a skipped file never costs a caller one of its slots.

  Ordering is by lowercased filename, then the raw name, so the sequence does
  not depend on the filesystem's own enumeration order and `max_count` is a
  stable selection rather than an arbitrary sample. Naming files `01_`, `02_`
  makes the cap a priority list.

  The node registers nothing. The other pipeline nodes record the folder they
  ran against so the template browser may list it and the image routes may
  serve from it; this one returns pixels and serves no files, so binding a
  folder to it does not widen what any browser may read.

### Fixed
- **A folder of GIFs came back silently short.** GIF's decoder keeps its file
  handle open for frame seeking, so loading a folder of them held one handle
  per image. Past the process limit the next open failed with an error that
  read exactly like a corrupt file, and the folder was reported with only the
  images that fit: 80 GIFs under a 60-handle limit returned 55 and reported
  55 as the folder's contents. Handles are released as each image is read now,
  and running out of them is reported rather than counted as corruption.
- **A project folder could be swapped between the check and the use.** The
  check that decides whether a caller may browse or delete within a project
  answered yes or no and discarded the path it had resolved, so the routes
  went on to build their folders from the caller's original string. A symlink
  replaced in between pointed the listing and the delete somewhere else. The
  check returns the resolved path now, and the routes use exactly that.

### Other
- The release preflight's review audit listed merge commits only, so a branch
  that was squash-merged appeared as nothing to review. It reads every commit
  now.

## 2026.7.24

A fix for one defect in 2026.7.23. No node's inputs, outputs, or id changed.

### Fixed
- **An empty project folder made ComfyUI's own working directory browsable.**
  The Order Read node records its project before it checks that an order file
  exists, and an empty path resolved to the process working directory, so
  queueing that node with its project widget left at the default added ComfyUI's
  folder to the set the template browser may read and delete within. Only an
  absolute path is recorded now.

## 2026.7.23

**Node change.** `SymbioticaTemplateLibrary` gains two inputs, `kind` and
`month`, **appended after** `selected`/`checked` — ComfyUI restores a saved
workflow's widget values by position, so a new input ahead of them would drop
the saved template pick onto the wrong widget. Saved workflows keep their pick,
and an omitted `kind` reads as "All", which browses every pool: the old
behaviour.

**Node change.** `Hypereel UGC Presets` no longer carries its preset templates
in the published pack, so its `style`, `hook` and `setting` dropdowns hold one
placeholder entry instead of the catalog. **A saved workflow using this node
will fail to run**: ComfyUI validates a combo value against the node's current
list and rejects one that is no longer in it. The other Hypereel nodes are
unaffected. The templates were the platform's own, and a published pack is a
world-readable archive. The node stays, so the graph shape is preserved.

**Where assets may be read from.** A folder outside ComfyUI's `input/` and
`output/` is no longer readable just because a request names it. A project kept
elsewhere is declared once, in **Settings → Symbiotica → Paths → Asset folders**
or `SYMBIOTICA_ASSET_ROOTS`. A folder a running graph pointed at stays readable
as before. Without this a project outside those folders browses empty.

### Security
- **A request could name any folder and then read it.** Four routes registered
  the directory the caller asked about into the process-wide allowlist that
  guards image serving, so asking to browse a folder was what granted access to
  it. Registration is now confined to folders already declared, and the routes
  that took a path refuse one they cannot place instead of reading or listing
  it.
- **One request could delete a folder anywhere on the host.** The template name
  was slugified and confined, but the project folder it was joined to was
  whatever the caller sent, and the result went to a recursive delete. A project
  is admitted only when a running graph named it or it lies in a declared
  folder. A pool directory is never treated as a template either, so a pool
  name cannot take the pool.
- `GET /symbiotica/parse-order` read any file the caller named and returned the
  contents of any zip container, and its three failure shapes made it an
  existence oracle for arbitrary paths. It refuses an unplaceable path now, so
  all three answer alike.
- `/symbiotica/browse-dirs`, which listed any directory on the host, is gone.
  Nothing had called it since the folder-browser button was removed.

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
- A month is now resolved to one canonical name before it names a folder, so
  "", "October" and "Bakery October Art.xlsx" — three ways to say the same order
  — no longer file that month's templates in three different places.
  `resolve_month` returns that name as `month`.
- **All** browses every month's order pool, not only the one in the Library's
  `month` widget: the save follows the ORDER's month, so a template packed for
  November has to be findable from a Library sitting on October.

### Fixed
- Deleting a template saved before the split did nothing: the delete searched
  only the pool folders for the kind the browser sent, and a pre-split template
  lives in neither. The delete now scans every pool and lets the pool-qualified
  name keep it scoped.
- `POST /symbiotica/pack-template-delete` never expanded a volume-relative
  `studios/<slug>/…` project path, so on Modal it removed nothing.
- A save with no project folder (a Reference Browser rooted outside a project)
  reported as if it had been filed. It lands in `output/templates/reference/`
  and now says so.
- **The Submagic captions node could hang forever.** None of its four requests
  carried a timeout, and `requests` waits indefinitely without one, so an
  unresponsive host held the node until ComfyUI itself was restarted. Every call
  is bounded now, and the poll between stages notices Cancel within half a
  second instead of sleeping through it.
- Long ffmpeg work in the Hypereel composite and glow nodes stops on Cancel
  rather than running to completion.

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
