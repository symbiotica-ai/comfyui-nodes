# Which Symbiotica nodes are still earning their place

Counted 2026-08-13 against **115 workflows** — 82 on the desktop install
(`~/Documents/ComfyUI/user/default/workflows`) and 33 live + 30 archived on the
Modal volume `symbiotica-comfy-workflows` (`_obsolete/` and `_superseded/`
count as archived). A node is "used" if it appears in a workflow's node list,
regardless of whether that workflow still runs.

The pack registers **131 nodes**: 45 `Symbiotica*`, and 86 from the `NS*` /
`Hypereel*` / video-FX arc (see the last section).

The four workflows treated as the current pipeline: `bakery-final-01`,
`imperia-bakery-dev-08`, `imperia-bakery-single-04`,
`imperia-bakery-prompts-manager`.

---

## A. Dead — no workflow anywhere has ever held one

Zero hits across all 115 workflows, live or archived. Nothing to migrate.

| Node | Lines | Where | Why it exists |
|---|---:|---|---|
| `SymbioticaRegionalPrompt` | 268 | `py/pipeline/nodes.py` | The ERPK regional arc (2026-07-15), abandoned |
| `SymbioticaRegionalEdit` | 144 | `py/pipeline/nodes.py` | same arc |
| `SymbioticaPromptEnhancer` | 211 | `py/pipeline/nodes.py` | same arc — the LLM rewriter stage |
| `SymbioticaRefsSplit` | 40 | `py/pipeline/nodes.py` | same arc — fan-out helper |
| `SymbioticaPromptsSplit` | 34 | `py/pipeline/nodes.py` | same arc — fan-out helper |
| `SymbioticaTemplateBuilder` | 219 | `py/pipeline/nodes.py` | pre-AutoPacker sheet packer |
| `SymbioticaTemplatePrompt` | 38 | `py/pipeline/nodes.py` | its prompt side |
| `SymbioticaSaveRender` | 116 | `py/pipeline/nodes.py` | superseded by the Pick node's own save |
| `SymbioticaRefsFolder` | 50 | `py/pipeline/nodes.py` | superseded by Studio Library |
| `SymbioticaClaude` | 187 + 380 | `py/claude_text.py`, `py/pipeline/claude_text.py` | standalone Claude text node |
| `SymbioticaTrellis2` | 131 | `py/trellis2_fal.py` | fal image→3D, one-off trial |
| `SymbioticaWavespeedNanoBanana2` ×4 | 326 | `py/wavespeed_nano_banana_2.py` | duplicated by the `NSWaveSpeedNanoBanana*` family |

Also falling out with the regional arc: **`web/js/symbiotica_regions_bridge.js`
(375 lines)** — it exists only to drive `SymbioticaRegionalPrompt`.

**Removing block A: 15 node classes, ~1 400 lines of `nodes.py`, 5 standalone
modules, 1 JS extension.**

---

## B. Retire after a swap — only in old or `_dev` workflows

Each has a named replacement already carrying the work. Nothing here is in the
four current workflows.

| Node | Uses | Newest workflow | Replaced by |
|---|---:|---|---|
| `SymbioticaPromptCompose` | 1 live, 14 archived | `imperia-bakery-prompts-manager` | `SymbioticaPromptRecipe` — the node's own display name already says deprecated |
| `SymbioticaTemplateEditor` (+ `web/js/template_editor/`, 3 408 lines) | 2 `_dev` | `_dev/auto-packer` | `SymbioticaOrderSpecs` + `SymbioticaAutoPacker` |
| `SymbioticaOrderRead` | 1 local | 2026-07-22 | `SymbioticaOrderSpecs` |
| `SymbioticaEventSpecs` | 1 local | 2026-07-22 | `SymbioticaOrderSpecs` |
| `SymbioticaCategoryPrompts` | 3 local, 0 live | 2026-08-07 | `SymbioticaPromptBook` / `PromptRecipe` |
| `SymbioticaOrderAssets` | 2 `_dev` | `_dev/imperia-bakery-flow3-aigateway` | `SymbioticaDatasetReference` |
| `SymbioticaTemplateLibrary` | 3 `_dev` | `_dev/imperia-bakery-platform-test` | `SymbioticaStudioLibrary` |
| `SymbioticaReferenceBrowser` | 3 `_dev` | `_dev/imperia-bakery-platform-test` | `SymbioticaStudioLibrary` + `Pick` |
| `SymbioticaReconstructCells` | 4 live | `_dev` sheets | still wired in a few dev graphs — check before cutting |
| `SymbioticaGeminiImage` | 3 `_dev` | `_dev/…gemini-only` | the WaveSpeed / Nano Banana path |
| `SymbioticaAgent`, `AgentSettings`, `Skills`, `Seed` (+ `web/js/seed.js`) | 1 local each | 2026-04-04 `SYM logo3` | the agent arc, pre-pipeline |

**Removing block B: 14 more node classes, ~1 300 lines of `nodes.py`, 4
standalone modules, ~3 600 lines of JS.**

---

## C. Keep — the live pipeline

`StudioLibrary`, `OrderSpecs`, `AssetFocus`, `AssetRefs`, `DatasetReference`,
`Pick`, `OrderTracker`, `SliceCells`, `CompareSheet`, `PromptBook`,
`PromptBlock`, `PromptRecipe`, `ClientExamples`, `AutoPacker`,
`AutoPackerSettings`, `ModelPreset`.

Sixteen nodes, and every one of them appears in a workflow touched this month.

---

## D. The other 86 nodes in this pack

`NS*` (72), `Hypereel*` (8), and the video-FX set (`CameraShake`, `FilmGrain`,
`FocusPull`, `ChromaticAberration`) are a different product line living in the
same repo. Only `LoadTextFile` and `LoadTextList` show up in the workflows
counted here — the rest are at zero, but these workflows are the bakery arc's,
not that arc's, so **zero here is not evidence they are unused**. Ask whoever
owns the Hypereel/NS work before treating that block as dead.
