# Per-category system prompts — design

**Date:** 2026-08-02
**Status:** proposed — revised after validation against the running instance

## The problem

Rendering one month's order takes one manual pass per asset type. The Auto Packer
emits every sheet in the order, but the *architect* system prompt that turns a
sheet into a Nano Banana prompt is a different document per type: decorations
want the 2×2 isometric sprite-grid brief, food wants the PREP / READY / SERVING
recipe brief. Today those live in two `String` nodes wired to two `NSLLMChat`
lanes, so shipping a feature means setting the packer's category to `Decoration`,
running that group, setting it to `Food - 3 stages`, running the other group.

The order sheet already knows each asset's type. Nothing should need saying twice.

## How the current graph is shaped

Read from the running instance (`/history` returns the executed API graph):

- `SymbioticaAutoPacker #31` → `sheet_prompts` → `ShowText #28` → the **user**
  prompt of both LLM lanes.
- `NSLLMChat #11` ← `String #12`: the Decoration architect, 5,513 chars.
- `NSLLMChat #15` ← `String #18`: the Food architect, 5,890 chars.
- Both → `GeminiImage2Node` (Nano Banana Pro). Its own `system_prompt` is a
  generic constant — **the per-type text is NSLLMChat's, not Gemini's.**

## The mechanism this rests on — verified

`sheets` is declared `is_output_list`, so ComfyUI runs each downstream node once
per sheet. Verified against the running engine (ComfyUI 0.29.2,
`execution.py:241-316`, `_async_map_node_over_list`): a node without
`INPUT_IS_LIST` is executed once per index, and equal-length list inputs pair
element-wise. `NSLLMChat` reports `is_input_list: false`, so sheet *i* is rendered
with architect prompt *i*, in one queue press. Its per-index results are
re-gathered by `merge_result_data` (execution.py:320-338), so the fan-out
continues into Gemini.

The intermediate `ShowText|pysssss` does not disturb this: it declares
`INPUT_IS_LIST = True` / `OUTPUT_IS_LIST = (True,)` and returns the list unchanged.

**Mismatched lengths do not fail — they clamp.** `slice_dict` is
`v[i if len(v) > i else -1]`, commented "repeat last input when list isn't long
enough" (execution.py:250-252). Wiring a 2-entry list into a 12-sheet run renders
sheets 3-12 with the *last* prompt, silently, spending Gemini credits on
wrong-style output. No error is ever raised. This is the single most dangerous
property of the whole design and it drives two decisions below: the deduped and
per-sheet category lists must not be easy to confuse, and the wiring is done by
the extension rather than by hand.

## Storage

One file per asset type, under the client project:

```
<project>/prompts/decoration.md
<project>/prompts/food-3-stages.md
```

The stem is `slugify(category)` — the same function that names sheets, so
`Food - 3 stages` → `food-3-stages`. The file holds the architect prompt verbatim,
no frontmatter. It sits beside `orders/`, `templates/` and `reference-assets/`,
syncs on Drive, and stays the client's.

## The node

`SymbioticaCategoryPrompts` — display name **Symbiotica Category Prompts**.

Declared `Schema(is_input_list=True)`. This is not optional: without it ComfyUI
maps execute once per category, which makes "read each file once per run"
impossible and makes the batch error below unimplementable — the first missing
file would raise alone, producing exactly the fail-fix-fail-again loop the error
design exists to prevent. Every input therefore arrives as a list, `order` included
(as `[order]`), and `fingerprint_inputs` takes the same shapes.

| | |
|---|---|
| inputs | `sheet_categories` (STRING, list), `project_path` (STRING widget), `order` (ORDER wire, optional), `template` (PACK_TEMPLATE wire, optional) |
| output | `system_prompts` (STRING, list) — one per input category, same order |

`project_path` is a **widget, not only a wire** — see caching. The extension
auto-fills it using the same Local/Modal string resolver the order lane already
uses (`nodeOutputString`, web/js/order_pipeline.js:160-175). Execute prefers the
project on the `order`/`template` wire when present and uses the widget otherwise.

### Caching

`fingerprint_inputs` **never sees link-fed inputs.** ComfyUI calls it with
`execution_list=None` and every linked input arrives as `(None,)`
(execution.py:88-89, get_input_data at 172-186; the comment reads "Intentionally
do not use cached outputs here. We only want constants in IS_CHANGED"). A
fingerprint that tried to stat files resolved from the wired `order` would get
`None`, and both outcomes are bad: raising sets `is_changed` to NaN, which
`caching.py:116` folds into every *descendant's* cache key — so NSLLMChat and
Gemini would miss cache on every queue press and re-bill both APIs — while
defensively returning a constant serves stale prompts, the exact failure the
fingerprint exists to prevent.

So the fingerprint is computed from the `project_path` **widget constant**: a
sorted listing of `<project>/prompts/` with each entry's `st_mtime_ns` and size.
Hashing the listing (not just the files a given run resolves) means creating a
previously-missing file also invalidates. This matches the existing fingerprints
on `SymbioticaOrderRead` and `SymbioticaOrderSpecs` (nodes.py:136-149, 221-235),
which work for the same reason: they key off widget constants.

### Resolving the project

Three sources, in order:

1. `order["project_path"]` when the wire carries one.
2. `project_root_of(order["refsRoot"])` — **Reference Browser orders carry no
   `project_path` at all** (`build_reference_order`, reference_browser.py:71-131),
   and the repo already solves this by walking up to the folder containing
   `orders/` or `reference-assets/` (project_layout.py:37-52, used at
   nodes.py:344-350).
3. The `project_path` widget.

If none names a directory that exists, raise *"this order names no project
folder"* — not a missing-file error quoting a garbage path like
`/prompts/signage.md`, which is what an empty project_path would otherwise
produce.

## Packer change

Add the per-sheet list as a fifth output, `sheet_categories`, appended after the
deduped `categories`:

| slot | output | cardinality |
|---|---|---|
| 0 | `sheets` | one per sheet |
| 1 | `sheet_prompts` | one per sheet |
| 2 | `sheet_names` | one per sheet |
| 3 | `categories` | one per **distinct type** |
| 4 | `sheet_categories` | one per sheet |

Slot 3 changed meaning once already: commit `0442286` shipped it as the per-sheet
list, and the working tree redefines it as the deduped list. That swap is safe
only because `0442286` never reached a release — the newest tag, `v2026.7.25`,
predates it, so no registry install has a 4th output at all, and the only graph
affected is the local nightly, where slot 3 feeds a `ShowText` for display. **Both
changes must ship in the same release**, or a version exists in which slot 3 means
something a saved workflow will read wrongly.

Residual risk: slots 3 and 4 are adjacent, both STRING lists, and confusing them
fails silently by clamping. Mitigated by the extension wiring slot 4 itself, by
names that state cardinality, and by tooltips that say which is which — not by
anything the engine will enforce.

Also add `sheetCategories` to the template sidecar written by `_save_template`
(nodes.py:753-756). Templates saved without it can never drive this node on
replay, and the field is unrecoverable after the fact — three lines now.

## Wiring

The extension wires `packer.sheet_categories` → `prompts.sheet_categories` and
fills `prompts.project_path`, following the `wireOutput` / `wireFamily` pattern in
web/js/symbiotica_regions_bridge.js:175-204 (order_pipeline.js only *reads* links
— this lane's auto-wiring is new code). One link is left to the user:
`system_prompts` → `NSLLMChat.system_prompt`. After that the packer's category
picker can sit on `All` and one queue press covers the order.

## When a prompt is missing

Raise before any LLM or Gemini call, naming **every** missing type at once with
the exact path to create:

```
no architect prompt for 2 asset types in this order:
  Building - 4 stages  →  <project>/prompts/building-4-stages.md
  Signage              →  <project>/prompts/signage.md
```

An empty or whitespace-only file is the same error: a blank system prompt degrades
output silently. A blank category (an xlsx row with no type — these flow through
as `""`, autopack.py:18/135) is its own error naming the offending assets, because
it would otherwise resolve to `<project>/prompts/.md`. Two distinct raw categories
whose slugs collide (`slugify` maps `Décor` → `d-cor`, and an en-dash `Food – 3
stages` onto the hyphen form) is also an error rather than a silent shared prompt.

No generic default. A default renders plausible assets in the wrong style and
spends credits doing it.

Known limitation, not solved here: on a Modal deploy the project volume can be
read-only from the Comfy box (the reason pack_library.py:88-91 exists), so the
"create this file" instruction is one the user cannot follow from there.

## Seeding

The two prompts currently in `String #12` and `String #18` are written to
`bakery/prompts/decoration.md` and `bakery/prompts/food-3-stages.md` verbatim, so
the first run through the new node reproduces today's output rather than starting
from a rewrite.

## Tests

- `slugify` mapping for every category in the bakery order; collision detection
- missing files: the error names all of them, with paths; empty file; blank
  category
- output length equals input length, order preserved, repeats resolve identically
- project resolution: order wire, Reference Browser fallback via `refsRoot`, widget,
  and the no-project error
- fingerprint changes when a prompt file is edited, and when a missing one is created
- node-face: the packer's five output slots in order, and `is_input_list: true` on
  the new node — asserted against `/api/object_info`, because the test stub's
  Schema swallows unknown kwargs (tests/comfy_api_stub.py:18-25) and cannot catch
  a missing flag

## Deliberately not in scope

- An in-Comfy editor panel for the prompts. It layers on top without changing
  anything downstream.
- A studio-wide fallback for prompts the client project lacks.
- Anything that changes what `sheet_prompts` contains.
