# Roadmap

Ideas queued for the pack. One block per idea, numbered by its GitHub issue —
refer to an entry as #N. Move a block to the CHANGELOG when it ships.

## [#71](https://github.com/symbiotica-ai/comfyui-nodes/issues/71) — Approved assets go back into the dataset

An approved render should land back in the project's `dataset/` under its
category and asset name, so it can be picked as the base for a future
generation — this month's approved crate becomes next month's reference.

- Today the approve lane stops at the save path; `dataset/<Category>/` is
  seeded by hand and never learns what was accepted.
- Once it does, `Dataset Reference` and `Pick Similar Asset From Project` offer
  approved work like any seeded reference, and the style loop is closed.
- Open: copy or reference in place; write from the Pick node at approve time or
  from its own node in the lane; what a re-approval does to the earlier version.

## [#66](https://github.com/symbiotica-ai/comfyui-nodes/issues/66) — Render lane: use / don't use reference image

Generate with or without a client reference. The architect chat's `image`
comes from the Pick Client Reference node; an asset with no client refs (or a
deliberately empty pick) should still compose and render — a use/don't-use
switch, or an empty pick simply meaning "no reference".

![pick client reference](assets/roadmap/pick-client-reference-required.png)

## [#67](https://github.com/symbiotica-ai/comfyui-nodes/issues/67) — Preload models at workflow start

Load the diffusion model, VAE, controlnets, CLIP and loras at workflow start
instead of at first queue — the GPU is paid for whether it renders or not, so
warm it while the user is still picking assets and writing prompts. First
generation should not carry the cold-load penalty.

## Pack and distribution — open threads (no issue filed yet)

Left open on 2026-09-19. One line each, the decision still open.

- Every release since `2026.8.30` (19 Aug) is `NodeVersionStatusFlagged` on the
  Comfy registry — 21 of them, `2026.9.1` through `2026.9.21`. The node and the
  publisher are Active; `api.comfy.org/nodes/symbiotica/versions` gives no
  reason. So the registry's latest installable version is three weeks behind
  the tree, and nothing published since August can be installed by anyone.
  Unchased: what changed at `2026.9.1`, and what the publisher dashboard says.
- ComfyUI Manager on Modal shows the pack as **Install**, never "Try update":
  it is volume-mounted at `custom_nodes/symbiotica`, and `push.sh` uploads no
  git remote and no Manager tracking record, so Manager has nothing to manage.
  Pressing Install there would drop `2026.8.30` beside the mounted copy — two
  copies of every `web/js` file, the failure `web/js/register.js` exists for.
  Open: live with the Volume lane, or move Modal to a registry install and drop
  `push.sh`.
- Ten display names are still off the `Node Name (Symbiotica)` pattern:
  `Symbiotica Asset Focus`, `Symbiotica Asset Recipe`, `Symbiotica Order
  Tracker`, `Symbiotica Studio Library`, `Control Image`, `Module`, `Recipes`,
  `Split Prompts`, `Load Text File`, `Load Text List`. Offered and not taken;
  a node already on a canvas keeps the title it was saved with either way.
- `chore/internal-pack-cleanup` holds four commits that are not on main — the
  category-tree lock, the 82-node cull, the module-merge docs. Left alone when
  the branches were collapsed to `main` on 2026-09-19; merge or delete.

## Set Hub / Get Hub — open threads (no issue filed yet)

One node holding many named constants, replacing a canvas full of KJNodes
Set/Get pairs. Both are frontend-only virtual nodes in `web/js/find_node.js`
(a NEW web file never reaches the Modal sandbox, which is why they live in that
file rather than their own). Nothing is pushed: local tree only.

- Groups are built: a Set Hub's title names the set it holds and a Get Hub
  takes the whole set in one pick, then follows it. What is NOT built is the
  reverse — nothing folds an existing canvas INTO a group for you.
- The fold/explode command is not built. Folding a canvas by hand means wiring
  each source into a Set Hub and pulling each name on a Get Hub; every KJ
  Set/Get already on the canvas keeps working meanwhile, and a Get Hub can pull
  a name published by a plain `SetNode`. The reverse does not work — KJ's
  `GetNode` looks for `type === 'SetNode'` and cannot see a hub slot — so a
  name moves to a hub only when its Gets move with it.
- The two static walks now hop a Get Hub as well as a KJ pair, by the OUTPUT
  SLOT the wire left (`nodeOutputString` in `web/js/order_source.js`, `nodeText`
  in `web/js/recipes.js`, and the `origin_slot` both panels now pass in).
  Verified on a real canvas: the Control Image panel asks the server for the
  folder behind the hub's SECOND name, not its first.
- Auto-naming a slot from a ComfyLiterals `String` node still lands on
  `STRING`, `STRING_2`: the node's title is "String", which is the type, so the
  fallback has nothing better to offer. Renaming is the answer, not more
  guessing.
- Muting or bypassing a hub drops every value on it — no crash, the downstream
  node just reports a missing input. Not guarded, and probably should not be.
- A name row on the Set Hub holds no value of its own: it reads the slot it
  sits against and renames it on write. The frontend's widget store keys a
  remembered value by widget NAME, so the two rows of a hub with two STRING
  slots were handed one state between them and drew the same name twice —
  which is what the slots never said. Nothing to keep in sync now.
- Verified by driving a real canvas (playwright, `--front-end-root` against the
  1.48.7 build on disk, and the default 1.52.7): wiring names a slot and grows
  the next, the name rows rename in place and carry the Gets with them, the
  queued prompt resolves straight to the source with no hub in it, slots
  survive save and reopen, a Get Hub inside a subgraph reads a Set Hub on the
  root graph. `--front-end-version` silently falls back to the default when
  GitHub rate-limits it — check `__COMFYUI_FRONTEND_VERSION__` in the page, not
  the flag.

## The two file browsers — open threads (no issue filed yet)

- Prompts and Control Image were driven on the LOCAL install, on frontend
  1.48.7 as well as 1.52.7, against real files. Neither has been watched on the
  Modal canvas since the restart that picked them up.
- The Control Image upload route takes whatever the browser hands it — no size
  cap, and the whole part is read into memory before it is written. Fine for a
  mask, never tried with a folder of 4K plates.
- The thumbnail cost was measured server-side only (6 ms, 4 KB per row at
  px=36, `Cache-Control` 600 s). Nobody has measured the canvas frame rate
  while panning a graph with an expanded tree on screen.
- `pick-thumb` is asked for `THUMB_PX * 2`; on a 3x display the rows are
  softer than they could be. Untouched deliberately — one more request size to
  cache per image.

## Recipes and Asset Focus — open threads (no issue filed yet)

Left open on 2026-09-11 after the recipes build; one line each, the decision
still open. Move to an issue when one is picked up.

- Both Asset Recipe threads from 2026-09-18 — adoption writing no row, and the
  queue dying in `graphToPrompt` on a null text widget — were the one cause:
  `readBtn.serialize = false` shifted every saved value one widget left, so
  `slots` loaded as `null`. Fixed and verified on frontend 1.48.7 with his own
  `dev-node-asset-recipes-base.json`; the slot widgets also needed their value
  written after `addWidget` (see CLAUDE.md). A workflow he saved while it was
  broken keeps whatever `ref` lost.
- Asset Recipe's slot outputs are `*` on the Python side. The server accepts it
  (`validate_node_input` returns true when either side is `*`); what the
  FRONTEND does when a `*` output is dropped on a typed widget input has never
  been watched.
- The `auto` toggle on the Recipes node (save on edit, load/create on a name
  change) has unit tests only; nobody has watched it on a canvas.
- Slot matching by colour (2026-09-17) has unit tests only; not yet watched on
  the Modal canvas, and no template has been converted from `recipe:` titles.
- A Recipes node saved before `match_color` existed loads it with the old
  `auto` boolean (widget values land positionally, so they shift one across).
  Retyping the colour fixes that node; a reset-to-`purple` on configure was
  written and rejected, so the decision is retype vs. migrate in code.
- Two painted nodes sharing a title are one slot, silently, the way two
  `recipe:<key>` nodes always were; a colour is easier to repeat by accident
  than a title, and nothing warns.
- `CHANGELOG.md` stops at 2026.9.21; everything since shipped by `push.sh`
  (live name resolver, auto toggle, project resolved from the open workflow,
  two-word buttons, Asset Focus categories split by canvas tiles with
  `category_recipe`/`width`/`height`). The next release needs one entry for it.
- A `recipe:<key>?` toggle writes active or bypassed only; muted (mode 2) is
  not offered.
- The bakery template still carries a `recipe:plot` String and a Join String
  Multi to build the recipe name; Asset Focus's `category_recipe` output makes
  both redundant.
- The ten older bakery categories are not captured as recipes yet, and the
  engine pins on the studio-assets Volume are the old 80-node exports — every
  generated workflow needs re-export, one bindings file, re-pin.
- `push.sh` removed `py/audio_duration.py` and `py/prompt_speech_split.py`
  from the Volume (on it, in no release); confirm no workflow used their nodes.
- The Control Image preview (`web/js/control_image.js`) draws through
  `node.imgs`; only its URL builder is unit-tested.
- Hub side: the module library dir `user/default/symbiotica-modules` is not
  symlinked to the shared Volume (`canvas_entry.user_tree`), so published
  modules stay per user.

Added 2026-09-17, from the Control Image / Prompts / switch-render-engine work.
Nothing below was watched on the Modal canvas except where it says otherwise.

- Control Image is now `image` + `path` (`root`/`folder` and the joined default
  folder are gone). Widget values restore positionally, so `path` inherits what
  `root` held — every saved Control Image node needs its path looked at once.
- `/symbiotica/local-image` is restored (it had been deleted in `0a4f14d` while
  two panels still fetched it; confirmed 404 on the live editor). The restore
  itself is not verified — it needs a ComfyUI restart.
- Control Image and Prompts are output nodes that push back the path a run
  received. Verified on the live editor for Control Image with a TYPED path;
  the Get-node case has unit tests only.
- `workflows/_switch-render-engine.json` is now one subgraph (`render-engine`)
  holding both engine groups, the LazySwitchKJ and one Image Comparer after the
  switch. Two "missing connection" errors on the switch's branch inputs were
  answered by matching KJNodes' wildcard slot types; never confirmed on the
  canvas. The version before the subgraphs is in
  `workflows/_superseded/_switch-render-engine-before-subgraphs.json`.
- `Set_$$reference` and `Set_$$controlnet` now sit INSIDE that subgraph. Whether
  a KJNodes Set inside a subgraph is visible to a Get outside it is untested —
  if a `Get_$$reference` elsewhere comes up empty, that is why.
- The Prompts folder listing refreshes the studio-assets mount on the first
  listing of a path (`prompts-list?sync=1`, the walk the Studio Library browse
  makes). Unit tests only.
- `prompt_store` lists a file with NO extension as a prompt. That was inferred
  from a Volume copy named `llm-sp-chair` — the local file was always
  `llm-sp-chair.md` and a bad upload dropped the suffix. The rule stands, but
  the thing that actually fixed it was pushing the resources folder.
- `~/projects/symbiotica/resources/push.sh` (not this repo) uploads that folder
  to `symbiotica-comfy-studio-assets:_platform/resources`. One stray is still
  up there — `prompt-templates/llm-prompts/llm-sp-chair`, the extensionless
  copy; `./push.sh --prune` deletes it.
