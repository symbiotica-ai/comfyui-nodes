# Symbiotica Files Read — design

Date: 2026-07-22. Approved by Razvan in session (option "Build it").

## Goal

Build dataset template sheets from loose client reference folders — no order
xlsx. A new reader node browses a folder tree, the user groups images, and the
existing Auto Packer renders the sheets. Sheets mimic the layouts of the
client's target images so LoRA training learns layouts, not just assets.

## Architecture

```
Symbiotica Files Read (NEW) ──order──▶ Symbiotica Auto Packer ──▶ sheets / sheet_prompts / sheet_names
        │                                    ▲            ▲
   [Open files browser]              Model Preset    Auto Packer Settings
```

The Files Read node emits the same `Order` wire `SymbioticaOrderSpecs` emits
(`{feature, eventName, assets, refsRoot, assetsRoot, guide}`), so the Auto
Packer, Model Preset, Auto Packer Settings, and everything downstream are
untouched. Reuse over new surface, per the pack's minimal-node rule.

## Node: `SymbioticaFilesRead`

- Face: `refs_path` (client reference folder), `name` (base name for sheets,
  default = folder name), "Open files browser" button (JS).
- Advanced: `selection` (String JSON, browser-managed).
- Output: `Order`.
- `fingerprint_inputs`: refs_path + selection + selected files' mtimes.

## Selection model (matches the template editor's project-reference semantics)

One folder = one group = one asset = one sheet row. Files ticked inside the
folder are that group's row cells, in tick order.

`selection` JSON:

```json
{"groups": [{
  "name": "stoves",            // assetName; default folder name, editable
  "category": "Decoration",    // proposed from folder structure, editable
  "files": ["Stoves/stove_red.png", "Stoves/stove_blue.png"],
  "desc": "",                  // optional -> region desc -> sheet_prompts
  "variants": false            // true -> rotation "2" (mirror/split logic)
}]}
```

Asset synthesis (`py/pipeline/files_read.py`, pure, tested):

- `assetName` = group name, `category` = group category
- `canvas` = `"WxH"` from the group's files' max pixel dims (PIL header read)
- `rotation` = `"2"` when variants else `"-"` (stages-together default)
- `refFiles` = the rel paths verbatim (they contain `/`)
- `prompt` = desc

## Packer path fix (the one shared-code change)

Order refFiles are basenames resolved flat under refsRoot. Client folders nest,
so:

- `prefill_regions`: a refFile containing `/` is used verbatim as the member
  path (no `category/assetName/` synthesis).
- `_draw_task_refs`: resolve a path by exact rel under refs_root first, fall
  back to flat basename (today's behavior).
- JS parity: mirror the same try-rel-then-basename rule in
  `resolveMemberUrl` (order_pipeline.js) — parallel draw rules change together.

Both changes are backwards compatible: order-flow paths don't exist as rel
paths, so they fall through to today's basename lookup.

## Files browser (JS overlay, `web/js/files_read.js`)

Referenced from the template editor's project-assets tree (rail.js section 5)
— same trie/checkbox/thumbnail mechanics, new selection model:

- Fetch `/symbiotica/list-assets?dir=<refs_path>` (already returns rel + px
  dims and registers the root for `/symbiotica/local-image` thumbs).
- Tree: folder checkbox = group the whole folder; file checkboxes = refine the
  group's cells (tick order = cell order).
- Filters: name search box + pixel-size chips (buckets from real dims) +
  folder collapse — for sorting similar images fast.
- Right panel: group list — editable name/category/desc, variants toggle,
  cell reorder/remove, live cell count.
- Category proposals: nested folder → parent folder name; top-level folder →
  its own name. Editable per group.
- Writes `selection` to the node widget; node face shows a groups summary.

No template-editor behavior changes; tree code is copied, not extracted.

## Testing / verification

- pytest: files_read builder (selection→assets, canvas derivation, category
  proposals), prefill rel-path passthrough, draw fallback resolution.
- nodes.py is NOT covered by pytest — verify schema live via
  `/api/object_info/SymbioticaFilesRead` after deploy.
- Live target: Razvan's RunPod pod (ComfyUI :8188 proxied); headless harness
  against the proxied URL for the browser UI.
