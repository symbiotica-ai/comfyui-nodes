# Reference Browser — design

**Date:** 2026-07-28
**Replaces:** `SymbioticaFilesRead` (deleted — its fullscreen overlay was the wrong shape)

## Problem

The Auto Packer can only be fed by an Order Specs node, so every template sheet
is tied to a month's client order and carries that order's briefs. The team also
needs *reference* templates: sheets built from the game's existing asset library,
laid out the same way the real sheets are, used later in the pipeline as design
references beside the ones the client's spreadsheet describes.

Files Read tried to cover this with a fullscreen file browser. It hid the folder
tree behind a modal, made the user type the folder path, and grouped by tick
order rather than by the library's own structure. It was not used.

## The node

`SymbioticaReferenceBrowser` — "Symbiotica Reference Browser", `symbiotica/pipeline`.

| Input | Type | Role |
| --- | --- | --- |
| `root_path` | STRING | The library folder. Normally **wired from the Studio Library node's `path`**; a typed absolute path also works. |
| `name` | STRING | Base name for the sheets. Empty = the browsed folder's name. |
| `selection` | STRING (advanced) | Picks, as JSON. Written by the in-node browser. |

Output: `order` — the same Order wire the Auto Packer already eats, so the
packer, Model Preset, and Auto Packer Settings nodes are untouched.

## The library's shape, and what a pick means

The game library nests one level: a category folder holds one folder per item,
and an item folder holds that item's images.

```
reference-assets/
  Minis/                 <- browsing here
    Purrfection Cake/    <- tick this = one sheet ROW
      prep.png           <- its cells
      ready.png
    Spider Doughnuts/
```

- **A ticked folder is one row**; the images inside it are that row's cells.
- **Category is the folder currently being browsed** (`Minis` above), so one
  node produces one category, which is one sheet.
- Ticking individual images groups them under the folder they live in.

## In-node browser

The tree renders **inside the node**, not in an overlay. It is a DOM widget
(`serialize: false`, `hideOnZoom: true`) whose `computeSize` measures an inner
list's `scrollHeight` — the pattern the Auto Packer's Assets panel already uses,
so the node grows with its content and scrolls past a cap instead of running off
the canvas.

Chrome comes from the Studio Library browser (`↑ up`, breadcrumb, "Filter this
folder…", folder-first rows, HUB theme tokens), lifted into a shared
`web/js/browser_chrome.js` — no new visual assets. The Studio Library overlay
keeps its own working copy for now; it moves onto the shared parts the next time
it is touched, rather than being refactored blind here.
Thumbnails use the Auto Packer's `/symbiotica/local-image` URL builder, keeping
the `/api/` prefix that the Modal gateway requires.

Below the tree, a picked-rows panel: row name (editable), its cell thumbnails,
remove, and reorder.

## Server

`GET /symbiotica/browse-refs?root=<path>&dir=<rel>` — one level of `root/rel`:
folders and images, each image with its pixel size. The root is confined by
realpath containment and registered for thumbnail serving. A `studios/...`
volume-relative root (what the Studio Library node stores) is expanded first, so
the same node works on Modal and on the desktop install.

The builder is `files_read.py` renamed to `reference_browser.py`: its grouping
and its hardening (duplicate-name bump, root containment, decompression-bomb
drop, non-object-JSON guard) were never the problem and carry over intact.

## Layout conventions

"Food is three rows, decorations are two per row" is a Model Preset plus Auto
Packer Settings combination. Those already save and reload through the Template
Library, so a category's convention is packed once, saved as a template, and
reloaded — no new registry.

## Phase 2 (not this change)

An optional `order` input puts the node in strict mode: a wired Order Specs
contributes the sheet's *shape* (per row: canvas size and variant rule) with the
client briefs stripped, and picks fill those slots in order. The blank template
then matches the real sheet it accompanies.
