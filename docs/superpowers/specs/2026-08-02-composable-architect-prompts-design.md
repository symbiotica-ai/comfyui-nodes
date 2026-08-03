# Composable architect prompts — design

**Date:** 2026-08-02
**Status:** approved — step 1 of three
**Scope:** composition and migration only. Provenance and the LLM feedback loop
are steps 2 and 3, specced separately.

## The problem

The architect system prompt that turns an asset brief into a Nano Banana prompt
is one document per asset type, at `<project>/prompts/<Exact Category>.md`. There
are eight, each 5,500–8,800 characters, and they were produced by asking an LLM
to rewrite one type's prompt for another type. So the same rules exist eight
times in eight wordings.

Measured across the bakery project's eight prompts:

| Rule heading | Present in |
| --- | --- |
| `REFERENCE USAGE SPLIT` | 8/8 |
| `STYLE LOCK` | 8/8 |
| `UNIFIED LIGHTING` | 8/8 |
| `CREATIVE BRIEF` | 6/8 |
| `NEGATIVES` | 6/8 |
| `FOOTPRINT LOCK` / `& SCALE` / `& ANCHOR` | 8/8 across three names |
| `TWO` / `THREE` / `FOUR` / `N UNIQUE RENDERS` | type-specific by nature |

Exactly **one line** is byte-identical across all eight files. The taxonomy is
shared; the text has drifted.

The consequence is that improving generation quality is not currently possible in
one place. Tightening a lighting rule means editing eight files, or editing one
and letting the other seven rot. The user's stated goal — "system prompts should
be composed of game related rules (lighting, style adherence to reference)" — is
a request to stop storing the same rule eight times.

## The design

### Layout

```
<project>/prompts/
  _rules/                          game-wide, edited once, applied everywhere
    01-reference-usage-split.md
    02-style-lock.md
    03-unified-lighting.md
    04-negatives.md
  Food - 3 stages.md               what is genuinely type-specific
  Chair.md
  ...
```

The composed system prompt for a type is the `_rules/*.md` files in filename
order, then that type's own file. The type block goes **last**: it is the most
specific instruction, and the end of a long prompt is where a model weights most
heavily. Filename prefixes (`01-`, `02-`) make the order explicit and editable
without touching code.

### What moves, and what does not

**Shared** (`_rules/`): `REFERENCE USAGE SPLIT`, `STYLE LOCK`, `UNIFIED
LIGHTING`, `NEGATIVES`. These are properties of the game's art, not of a chair.

**Type-specific** (`<Category>.md`): the role and sheet layout, `N UNIQUE
RENDERS`, and `FOOTPRINT LOCK`.

Footprint is the interesting exclusion. It reads 8/8, but only across three
different names — `FOOTPRINT LOCK`, `FOOTPRINT & SCALE LOCK` (appliances, food),
`FOOTPRINT & ANCHOR LOCK` (wall decoration) — because what a type anchors to
genuinely differs. Sharing it would force one anchor rule onto types that need
another, which is a subtler failure than leaving it duplicated.

`CREATIVE BRIEF` (6/8) also stays type-specific: it describes how to read the
brief *for that sheet layout*.

### Composition

`resolve_category_prompts` composes instead of reading a single file:

1. Read `_rules/*.md` in sorted filename order; skip any that are empty.
2. Read `<Category>.md` as today — absent or blank still raises
   `MissingPromptsError` naming the exact path, because a type with no block of
   its own has nothing to say.
3. Join with a blank line between blocks.

**Backwards compatibility:** when `_rules/` does not exist or holds no usable
files, the result is the type file alone — byte-identical to today's behaviour.
So the node keeps working between shipping this and running the migration, and a
project that never migrates is unaffected.

### Cache invalidation

`SymbioticaCategoryPrompts.fingerprint_inputs` currently lists `prompts/` one
level deep. Left alone, editing a shared rule in `_rules/` would not change the
fingerprint, ComfyUI would reuse the cached result, and the next queue would
render with the old composed prompt while showing the new file on disk. That is
the worst class of bug here — silent, and it looks like the edit did nothing.

The fingerprint must walk `prompts/` recursively, hashing each file's path,
mtime and size. It must still never raise: a raise sets `is_changed` to NaN,
which folds into every descendant's cache key and re-bills the LLM and Gemini on
every queue press.

## The migration

A one-time script, run against a project, that:

1. For each shared rule, takes the **most complete existing wording** as the
   starting text — not a merge of eight. Measured from the current files:

   | Rule | Taken from | Length |
   | --- | --- | --- |
   | `REFERENCE USAGE SPLIT` | Wall Decoration | 989 chars |
   | `STYLE LOCK` | Table | 355 chars |
   | `UNIFIED LIGHTING` | Wall Decoration | 675 chars |
   | `NEGATIVES` | Counter | 2,305 chars |

2. Writes those four files into `_rules/`.
3. Removes those sections from all eight type files, renumbering what remains.
4. Prints which file each rule came from and the before/after size of every type
   file.

It does not merge wordings. Merging eight variants of a rule is an editorial
judgement that would be invisible in the diff, and the four resulting files are
small enough to edit by hand afterwards.

The script writes a backup copy of every file it modifies before touching it, and
refuses to run if `_rules/` already exists, so a second run cannot double-strip.

## Testing

Pure-function tests in `tests/test_prompt_book.py`:

- composition order: shared blocks in filename order, type block last
- no `_rules/` directory → type file alone, byte-identical to today
- empty or whitespace-only rule files are skipped, not emitted as blank blocks
- a missing type file still raises `MissingPromptsError` with the exact path
- two types share the same `_rules/` but differ by their own block

Node-face tests in `tests/test_nodes_category_prompts.py`:

- the fingerprint changes when a file inside `_rules/` is edited
- the fingerprint changes when a rule file is added or removed
- the fingerprint still never raises when linked inputs arrive as `None`

Migration tests in `tests/test_prompt_migration.py`:

- the four shared rules are extracted and the type files shrink
- a rule absent from a type file (`NEGATIVES`, 6/8) is not required to be there
- running twice is refused rather than double-stripping
- backups are written before any modification

## What this is not

No block markers in the composed text, no versioning, no LLM involvement. Those
belong to the feedback loop and composition does not need them. Adding them later
does not change anything specified here.
