# Per-Category System Prompts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One queue press renders a whole order, each sheet using the architect system prompt written for its asset type.

**Architecture:** Per-type prompts live as `<project>/prompts/<slug>.md`. A pure module resolves categories to file contents; a thin node wraps it and emits one prompt per sheet, index-aligned with the packer's `sheets` so ComfyUI pairs them element-wise. The packer gains a per-sheet category list to feed it.

**Tech Stack:** Python 3.10+, ComfyUI V3 `comfy_api.latest.io`, pytest, node:test for the JS extension.

## Global Constraints

- Slug is `order_sheet.slugify(category)` — the same function that names sheets. `Food - 3 stages` → `food-3-stages`.
- New node declares `Schema(is_input_list=True)`. Without it ComfyUI maps execute per category and the batch error is unimplementable.
- `fingerprint_inputs` may only read **widget** values. ComfyUI passes every link-fed input as `None` (execution.py:88-89).
- New packer outputs are **appended**. Links address an output by slot index.
- No generic default prompt. A missing, empty, or whitespace-only file is an error naming every offender at once.
- Mismatched list lengths clamp silently (execution.py:250-252) — never rely on the engine to catch a wrong wire.

---

### Task 1: The prompt book (pure module)

**Files:**
- Create: `py/pipeline/prompt_book.py`
- Test: `tests/test_prompt_book.py`

**Interfaces:**
- Produces: `prompts_dir(project_path) -> str`, `resolve_category_prompts(project_path, categories) -> list[str]`, `MissingPromptsError(Exception)` with `.missing: list[tuple[str, str]]`.

- [ ] **Step 1: Write the failing tests**

```python
import pytest
from pipeline.prompt_book import (MissingPromptsError, prompts_dir,
                                  resolve_category_prompts)


def _book(tmp_path, **files):
    d = tmp_path / "prompts"
    d.mkdir()
    for stem, text in files.items():
        (d / f"{stem}.md").write_text(text)
    return str(tmp_path)


def test_resolves_each_category_to_its_file(tmp_path):
    p = _book(tmp_path, decoration="DECO", **{"food-3-stages": "FOOD"})
    assert resolve_category_prompts(
        p, ["Decoration", "Food - 3 stages"]) == ["DECO", "FOOD"]


def test_repeats_resolve_identically_and_read_once(tmp_path):
    p = _book(tmp_path, **{"food-3-stages": "FOOD"})
    cats = ["Food - 3 stages"] * 3
    assert resolve_category_prompts(p, cats) == ["FOOD"] * 3


def test_missing_files_are_reported_together(tmp_path):
    p = _book(tmp_path, decoration="DECO")
    with pytest.raises(MissingPromptsError) as e:
        resolve_category_prompts(p, ["Decoration", "Signage",
                                     "Building - 4 stages"])
    assert [c for c, _ in e.value.missing] == ["Signage", "Building - 4 stages"]
    assert "building-4-stages.md" in str(e.value)
    assert "signage.md" in str(e.value)


def test_empty_file_counts_as_missing(tmp_path):
    p = _book(tmp_path, decoration="   \n  ")
    with pytest.raises(MissingPromptsError):
        resolve_category_prompts(p, ["Decoration"])


def test_blank_category_is_its_own_error(tmp_path):
    p = _book(tmp_path, decoration="DECO")
    with pytest.raises(ValueError, match="blank asset type"):
        resolve_category_prompts(p, ["Decoration", "  "])


def test_slug_collision_is_an_error(tmp_path):
    p = _book(tmp_path, **{"food-3-stages": "FOOD"})
    with pytest.raises(ValueError, match="same prompt file"):
        resolve_category_prompts(p, ["Food - 3 stages", "Food – 3 stages"])


def test_prompts_dir_is_under_the_project(tmp_path):
    assert prompts_dir("/a/b") == "/a/b/prompts"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_prompt_book.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'pipeline.prompt_book'`

- [ ] **Step 3: Implement**

```python
# ABOUTME: Resolves an order's asset types to the architect system prompts
# ABOUTME: stored one-per-type under <project>/prompts/<slug>.md.
import os

from .order_sheet import slugify


class MissingPromptsError(Exception):
    """Types with no usable prompt file. `missing` is [(category, path), ...]."""

    def __init__(self, missing):
        self.missing = missing
        lines = "\n".join(f"  {c}  ->  {p}" for c, p in missing)
        super().__init__(
            f"no architect prompt for {len(missing)} asset "
            f"{'type' if len(missing) == 1 else 'types'} in this order:\n{lines}")


def prompts_dir(project_path):
    return os.path.join(project_path, "prompts")


def resolve_category_prompts(project_path, categories):
    """One prompt text per category, in the order given. Each file is read once
    however many sheets share the type. Raises rather than substituting a
    default: a wrong-style render costs real credits and looks plausible."""
    blank = [c for c in categories if not (c or "").strip()]
    if blank:
        raise ValueError(
            f"{len(blank)} sheet(s) carry a blank asset type — the order sheet "
            "has rows with no category, so there is nothing to look up")
    by_slug = {}
    for cat in categories:
        by_slug.setdefault(slugify(cat), set()).add(cat)
    clashes = {s: sorted(c) for s, c in by_slug.items() if len(c) > 1}
    if clashes:
        detail = "; ".join(f"{' / '.join(v)} -> {k}.md" for k, v in clashes.items())
        raise ValueError(
            f"two asset types resolve to the same prompt file: {detail}")
    root = prompts_dir(project_path)
    cache, missing = {}, []
    for slug in by_slug:
        path = os.path.join(root, f"{slug}.md")
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            text = ""
        if text.strip():
            cache[slug] = text
        else:
            missing.append((sorted(by_slug[slug])[0], path))
    if missing:
        raise MissingPromptsError(missing)
    return [cache[slugify(c)] for c in categories]
```

- [ ] **Step 4: Run to verify they pass**

Run: `.venv/bin/pytest tests/test_prompt_book.py -q`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add py/pipeline/prompt_book.py tests/test_prompt_book.py
git commit -m "feat: resolve an order's asset types to per-type prompt files"
```

---

### Task 2: Per-sheet categories out of the packer, and into saved templates

**Files:**
- Modify: `py/pipeline/nodes.py` (SymbioticaAutoPacker schema outputs; execute return; `_save_template` sidecar)
- Test: `tests/test_nodes_autopacker_outputs.py`

**Interfaces:**
- Consumes: `autopack.packed_categories` (already present), each packed dict's `"category"` key (already present).
- Produces: packer output slot 4 `sheet_categories` (STRING list, one per sheet); sidecar key `sheetCategories`.

- [ ] **Step 1: Write the failing tests**

```python
def test_output_slots_keep_their_order(nodes_mod):
    schema = nodes_mod.SymbioticaAutoPacker.define_schema()
    assert [o.display_name for o in schema.outputs] == [
        "sheets", "sheet_prompts", "sheet_names", "categories",
        "sheet_categories"]
    assert all(getattr(o, "is_output_list", False) for o in schema.outputs)


def test_execute_emits_both_category_lists(nodes_mod, tmp_path):
    assets = [_asset(n, "Food - 3 stages", ["s0.png", "s1.png", "s2.png"])
              for n in ("Spookies", "Spooky Stack Popsicle",
                        "Ghostly Jelly Cake")]
    out = nodes_mod.SymbioticaAutoPacker.execute(
        order=_order(tmp_path, assets), category="Food - 3 stages",
        preset={"model": "qwen-image", "tier": "1K", "ar": "1:1",
                "columns": 1, "max_rows": 1})
    sheets, _prompts, _names, categories, sheet_categories = out.args
    assert categories == ["Food - 3 stages"]                 # one per type
    assert sheet_categories == ["Food - 3 stages"] * 3       # one per sheet
    assert len(sheet_categories) == len(sheets)
```

Replace the existing `test_output_slots_keep_their_order` and add the second test.

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_nodes_autopacker_outputs.py -q`
Expected: FAIL — 4 display names, and `out.args` unpacks to 4 values

- [ ] **Step 3: Implement**

In `define_schema`, after the `categories` output:

```python
                io.String.Output(display_name="sheet_categories",
                                 is_output_list=True,
                                 tooltip="Asset type of sheet i — ONE PER "
                                         "SHEET, index-aligned with sheets. "
                                         "This is the one to wire into "
                                         "Category Prompts; `categories` above "
                                         "is the deduped label list."),
```

In `execute`'s return, after `packed_categories(packed)`:

```python
            [p.get("category", "") for p in packed],
```

In `_save_template`'s sidecar, after `"sheetPrompts"`:

```python
            # Per-sheet asset type, so a Library replay can drive the
            # Category Prompts node without re-packing. Unrecoverable if
            # omitted at save time.
            "sheetCategories": [p.get("category", "") for p in packed],
```

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: PASS, all tests

- [ ] **Step 5: Commit**

```bash
git add py/pipeline/nodes.py tests/test_nodes_autopacker_outputs.py
git commit -m "feat: emit a per-sheet asset type beside the deduped list"
```

---

### Task 3: The Category Prompts node

**Files:**
- Modify: `py/pipeline/nodes.py` (new class, registered via the existing mapping)
- Test: `tests/test_nodes_category_prompts.py`

**Interfaces:**
- Consumes: `prompt_book.resolve_category_prompts`, `prompt_book.prompts_dir`, `project_layout.project_root_of`.
- Produces: node id `SymbioticaCategoryPrompts`, output `system_prompts` (STRING list).

- [ ] **Step 1: Write the failing tests**

```python
def test_declares_whole_list_input(nodes_mod):
    schema = nodes_mod.SymbioticaCategoryPrompts.define_schema()
    assert schema.is_input_list is True
    assert [o.display_name for o in schema.outputs] == ["system_prompts"]


def test_one_prompt_per_sheet_in_order(nodes_mod, tmp_path):
    proj = _project_with_prompts(tmp_path, decoration="DECO",
                                 **{"food-3-stages": "FOOD"})
    out = nodes_mod.SymbioticaCategoryPrompts.execute(
        sheet_categories=["Decoration", "Food - 3 stages", "Food - 3 stages"],
        project_path=[str(proj)])
    assert out.args[0] == ["DECO", "FOOD", "FOOD"]


def test_project_comes_from_the_order_wire(nodes_mod, tmp_path):
    proj = _project_with_prompts(tmp_path, decoration="DECO")
    out = nodes_mod.SymbioticaCategoryPrompts.execute(
        sheet_categories=["Decoration"], project_path=[""],
        order=[{"project_path": str(proj)}])
    assert out.args[0] == ["DECO"]


def test_reference_order_falls_back_to_the_refs_root(nodes_mod, tmp_path):
    # A Reference Browser order carries no project_path at all.
    proj = _project_with_prompts(tmp_path, decoration="DECO")
    (proj / "reference-assets").mkdir(exist_ok=True)
    out = nodes_mod.SymbioticaCategoryPrompts.execute(
        sheet_categories=["Decoration"], project_path=[""],
        order=[{"refsRoot": str(proj / "reference-assets")}])
    assert out.args[0] == ["DECO"]


def test_no_project_says_so_rather_than_naming_a_junk_path(nodes_mod):
    with pytest.raises(ValueError, match="names no project folder"):
        nodes_mod.SymbioticaCategoryPrompts.execute(
            sheet_categories=["Decoration"], project_path=[""], order=[{}])


def test_fingerprint_changes_when_a_prompt_is_edited(nodes_mod, tmp_path):
    proj = _project_with_prompts(tmp_path, decoration="A")
    fp = nodes_mod.SymbioticaCategoryPrompts.fingerprint_inputs
    before = fp(project_path=[str(proj)])
    (proj / "prompts" / "decoration.md").write_text("B")
    os.utime(proj / "prompts" / "decoration.md", (10**9, 10**9))
    assert fp(project_path=[str(proj)]) != before


def test_fingerprint_changes_when_a_missing_prompt_is_created(nodes_mod, tmp_path):
    proj = _project_with_prompts(tmp_path, decoration="A")
    fp = nodes_mod.SymbioticaCategoryPrompts.fingerprint_inputs
    before = fp(project_path=[str(proj)])
    (proj / "prompts" / "signage.md").write_text("S")
    assert fp(project_path=[str(proj)]) != before
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/pytest tests/test_nodes_category_prompts.py -q`
Expected: FAIL, `AttributeError: SymbioticaCategoryPrompts`

- [ ] **Step 3: Implement**

```python
class SymbioticaCategoryPrompts(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaCategoryPrompts",
            display_name="Symbiotica Category Prompts",
            category="symbiotica/pipeline",
            description="One architect system prompt per sheet, picked by the "
                        "sheet's asset type from <project>/prompts/<type>.md. "
                        "Wire the Auto Packer's sheet_categories in and "
                        "system_prompts into your LLM node's system prompt: "
                        "one queue press then covers every type in the order.",
            # The whole list at once: per-category mapping would read each file
            # once per sheet and report missing prompts one at a time.
            is_input_list=True,
            inputs=[
                io.String.Input("sheet_categories", force_input=True,
                                tooltip="Per-sheet asset type — the Auto "
                                        "Packer's sheet_categories output, NOT "
                                        "its deduped categories list."),
                io.String.Input("project_path", default="",
                                tooltip="Client project folder. Filled in for "
                                        "you from the order; holds the prompt "
                                        "book at <project>/prompts/."),
                Order.Input("order", optional=True),
            ],
            outputs=[
                io.String.Output(display_name="system_prompts",
                                 is_output_list=True,
                                 tooltip="Architect prompt for sheet i — "
                                         "index-aligned with the packer's "
                                         "sheets."),
            ],
        )

    @staticmethod
    def _first(v, default=""):
        """is_input_list hands every input in as a list, widgets included."""
        if isinstance(v, list):
            return v[0] if v else default
        return v if v is not None else default

    @classmethod
    def _project(cls, project_path, order):
        """The order's project, then a Reference Browser order's refs root, then
        the widget. A reference order carries no project_path at all."""
        o = cls._first(order, {}) or {}
        for cand in (str(o.get("project_path", "") or "").strip(),
                     project_root_of(str(o.get("refsRoot", "") or "").strip()),
                     str(cls._first(project_path)).strip()):
            if cand and os.path.isdir(cand):
                return cand
        return ""

    @classmethod
    def fingerprint_inputs(cls, sheet_categories=None, project_path="",
                           order=None):
        # Only widget values are real here — ComfyUI passes every LINKED input
        # as None, so the order wire and the categories cannot be read. Hash the
        # whole prompt book from the widget: that catches an edited file AND a
        # missing one being created.
        root = prompts_dir(str(cls._first(project_path)).strip())
        h = hashlib.sha256(root.encode())
        try:
            for name in sorted(os.listdir(root)):
                st = os.stat(os.path.join(root, name))
                h.update(f"{name}:{st.st_mtime_ns}:{st.st_size}".encode())
        except OSError:
            pass
        return h.hexdigest()

    @classmethod
    def execute(cls, sheet_categories=None, project_path="",
                order=None) -> io.NodeOutput:
        cats = sheet_categories if isinstance(sheet_categories, list) else []
        cats = [c for c in cats]
        if not cats:
            raise ValueError("no sheets to prompt for — wire the Auto Packer's "
                             "sheet_categories into this node")
        project = cls._project(project_path, order)
        if not project:
            raise ValueError(
                "this order names no project folder, so there is nowhere to "
                "read the prompt book from — set project_path on this node")
        return io.NodeOutput(resolve_category_prompts(project, cats))
```

Add the imports at the top of the module's existing import block:

```python
from .project_layout import project_root_of
from .prompt_book import prompts_dir, resolve_category_prompts
```

and add `SymbioticaCategoryPrompts` to `PIPELINE_NODE_CLASSES`.

- [ ] **Step 4: Run the whole suite**

Run: `.venv/bin/pytest -q`
Expected: PASS

- [ ] **Step 5: Verify the flag on the live server** (the test stub cannot)

Run: `curl -s http://127.0.0.1:8000/api/object_info/SymbioticaCategoryPrompts`
Expected: `"is_input_list": true` after a Comfy restart.

- [ ] **Step 6: Commit**

```bash
git add py/pipeline/nodes.py tests/test_nodes_category_prompts.py
git commit -m "feat: add the Category Prompts node"
```

---

### Task 4: Auto-wire the node

**Files:**
- Modify: `web/js/order_pipeline.js`
- Test: `tests/js/category_prompts.test.mjs`

**Interfaces:**
- Consumes: the packer's `sheet_categories` output (slot 4), `project_path` resolution already used by the order lane.

- [ ] **Step 1: Write the failing test**

```javascript
import { test } from "node:test";
import assert from "node:assert";
import { wireCategoryPrompts } from "../../web/js/order_pipeline.js";

test("wires the packer's per-sheet list, not the deduped one", () => {
    const packer = {
        comfyClass: "SymbioticaAutoPacker",
        outputs: [{ name: "sheets" }, { name: "sheet_prompts" },
                  { name: "sheet_names" }, { name: "categories" },
                  { name: "sheet_categories" }],
        connect: (slot, target, input) => { packer.wired = [slot, input]; },
    };
    const node = { comfyClass: "SymbioticaCategoryPrompts",
                   inputs: [{ name: "sheet_categories" }] };
    wireCategoryPrompts(node, [packer]);
    assert.deepStrictEqual(packer.wired, [4, 0]);
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `node --import ./tests/js/register_hooks.mjs --test 'tests/js/category_prompts.test.mjs'`
Expected: FAIL, `wireCategoryPrompts is not exported`

- [ ] **Step 3: Implement** — export a `wireCategoryPrompts(node, nodes)` that finds the upstream packer, looks the slot up **by name** (`outputs.findIndex(o => o.name === "sheet_categories")`, never a hard-coded 4), and connects it. Call it from the node's `onNodeCreated`, and fill `project_path` from the same resolver the order lane uses.

- [ ] **Step 4: Run both suites**

Run: `.venv/bin/pytest -q && node --import ./tests/js/register_hooks.mjs --test 'tests/js/*.test.mjs'`

- [ ] **Step 5: Commit**

```bash
git add web/js/order_pipeline.js tests/js/category_prompts.test.mjs
git commit -m "feat: auto-wire Category Prompts to the packer's per-sheet types"
```

---

### Task 5: Seed the bakery prompt book and verify end to end

**Files:**
- Create (outside the repo): `<bakery>/prompts/decoration.md`, `<bakery>/prompts/food-3-stages.md`

- [ ] **Step 1: Write the two current architect prompts to disk**

Read them from the live graph (`String #12` = decoration, `String #18` = food) and write verbatim — the first run must reproduce today's output, not a rewrite.

- [ ] **Step 2: Copy the changed Python into the install**

```bash
cp py/pipeline/prompt_book.py py/pipeline/autopack.py py/pipeline/nodes.py /Users/razvanmatei/Documents/ComfyUI/custom_nodes/symbiotica/py/pipeline/
cp web/js/order_pipeline.js /Users/razvanmatei/Documents/ComfyUI/custom_nodes/symbiotica/web/js/
```

- [ ] **Step 3: Restart Comfy Desktop, then confirm the schema**

Run: `curl -s http://127.0.0.1:8000/api/object_info/SymbioticaCategoryPrompts`
Expected: `is_input_list: true`, one `system_prompts` output.

- [ ] **Step 4: Confirm on a real order** — packer category `All` on Mini 1, node wired, one queue press: decoration sheets carry the decoration brief and food sheets the food brief.
