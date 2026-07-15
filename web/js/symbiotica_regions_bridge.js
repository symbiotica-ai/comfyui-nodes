// ABOUTME: Bridge between the Symbiotica template pipeline and ERPK's Regional
// ABOUTME: Prompt Builder — a "Fill from Symbiotica template" button on the ERPK
// ABOUTME: node writes the template's regions into its canvas (regions_data, v2
// ABOUTME: contract), sizes the frame, exposes ref sockets, and auto-wires
// ABOUTME: per-region reference crops through a Symbiotica Refs Split node.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const BUILDER_TYPE = "RegionalPromptBuilder";
const EDITOR_TYPE = "SymbioticaTemplateEditor";
const RP_TYPE = "SymbioticaRegionalPrompt";
const SPLIT_TYPE = "SymbioticaRefsSplit";
const PROMPTS_SPLIT_TYPE = "SymbioticaPromptsSplit";
const ENHANCER_TYPE = "SymbioticaPromptEnhancer";
const MAX_REFS = 10; // ERPK's ref_N / desc_N socket family caps
const FAMILY_RE = /^(desc|ref)_(\d+)$/;

function toast(severity, summary, detail) {
    try {
        app.extensionManager.toast.add({ severity, summary, detail, life: 5000 });
    } catch (_) {
        console.log(`[symbiotica] ${summary}: ${detail}`);
    }
}

function widgetByName(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

function originNode(node, inputName) {
    const input = node.inputs?.find((i) => i.name === inputName);
    if (input?.link == null) return null;
    const link = app.graph.links[input.link];
    return link ? app.graph.getNodeById(link.origin_id) : null;
}

// The template editor (regions_json source) and the Symbiotica Regional Prompt
// (image_refs source) that feed this builder. The builder's image input is the
// deterministic path; unique-in-graph is the fallback.
function resolveSources(builder) {
    let rp = null;
    let editor = null;
    const img = originNode(builder, "image");
    if (img?.comfyClass === RP_TYPE) {
        rp = img;
        editor = originNode(rp, "template");
    } else if (img?.comfyClass === EDITOR_TYPE) {
        editor = img;
    }
    const all = app.graph._nodes || [];
    if (!editor) {
        const editors = all.filter((n) => n.comfyClass === EDITOR_TYPE);
        if (editors.length === 1) editor = editors[0];
    }
    if (!rp && editor) {
        rp = all.find((n) => n.comfyClass === RP_TYPE &&
                             originNode(n, "template") === editor) || null;
    }
    if (!rp) {
        const rps = all.filter((n) => n.comfyClass === RP_TYPE);
        if (rps.length === 1) rp = rps[0];
    }
    return { rp, editor };
}

// The template editor's regions, or [] when the count can't be known here
// (no editor upstream — e.g. a Template Builder feeds the bundle instead).
function regionsOf(editor) {
    if (!editor) return [];
    try {
        const parsed = JSON.parse(widgetByName(editor, "regions_json")?.value || "[]");
        return Array.isArray(parsed) ? parsed : [];
    } catch (_) {
        return [];
    }
}

// The Regional Prompt node ships 10 desc_N/ref_N output pairs; the template
// decides how many are real. Trailing pairs are removed so the node face — and
// every wire the fill button can draw — matches the region count. Only the
// tail may go: an output's slot index is what the API prompt cites, so
// dropping a pair from the middle would silently remap the wires below it.
function syncRegionOutputs(rp, count) {
    const n = Math.min(MAX_REFS, count);
    if (!rp.outputs || n < 1) return;
    const first = rp.outputs.findIndex((o) => o.name === "desc_1");
    if (first >= 0) rp._symPairBase = first;
    const base = rp._symPairBase;
    if (base == null) return;
    // A workflow saved before desc_N/ref_N were paired carries the old flat
    // output order, where the slots no longer mean what their names say.
    // Rebuilding the whole family is the only honest repair — pressing fill
    // rewires it.
    if (rp.outputs[base + 1] && rp.outputs[base + 1].name !== "ref_1") {
        while (rp.outputs.length > base) rp.removeOutput(rp.outputs.length - 1);
    }
    const want = base + 2 * n;
    while (rp.outputs.length > want) rp.removeOutput(rp.outputs.length - 1);
    while (rp.outputs.length < want) {
        const slot = rp.outputs.length - base;
        const pair = Math.floor(slot / 2) + 1;
        rp.addOutput(slot % 2 ? `ref_${pair}` : `desc_${pair}`,
                     slot % 2 ? "IMAGE" : "STRING");
    }
}

// Re-sync only when the upstream template's regions actually changed. Polled
// rather than hooked: the editor writes regions_json from four places (save,
// close, gallery pick, raw edit) and a string compare per node is cheaper than
// keeping a hook on each of them honest.
function syncFromTemplate(rp) {
    const editor = originNode(rp, "template");
    const raw = editor?.comfyClass === EDITOR_TYPE
        ? (widgetByName(editor, "regions_json")?.value ?? "") : "";
    if (raw === rp._symRegionsRaw) return;
    rp._symRegionsRaw = raw;
    const count = regionsOf(editor).length;
    if (!count) return;
    syncRegionOutputs(rp, count);
    rp.setDirtyCanvas?.(true, true);
}

// Template regions (flat editor shape) -> ERPK regions_data v2 document.
// bind.slot pins region N to socket ref_N/desc_N so canvas reorders in the
// ERPK editor never remap the wires' meaning on the Python side.
function toErpkDoc(regions) {
    const ordered = [...regions].sort((a, b) => (a.zIndex ?? 0) - (b.zIndex ?? 0));
    const out = ordered.map((r, i) => {
        const name = (r.name || "").trim();
        const desc = (r.desc || "").trim();
        return {
            id: r.id || `sym-r${i}`,
            kind: "object",
            box: { x: r.x, y: r.y, w: r.w, h: r.h },
            content: { desc: name && desc ? `${name}: ${desc}` : (desc || name), text: "" },
            op: "normal",
            edit_by: "model",
            bind: { slot: i + 1 },
            ui: { parent: null, hidden: false, collapsed: false },
        };
    });
    return { version: 2, order: out.map((r) => r.id), regions: out };
}

// Wire a source node's <prefix>_N outputs onto the builder's same-named
// sockets, adding builder inputs as needed. Returns how many links were made.
function wireFamily(source, builder, prefix, ioType, count) {
    let wired = 0;
    for (let i = 0; i < Math.min(count, MAX_REFS); i++) {
        const name = `${prefix}_${i + 1}`;
        const outIdx = source.outputs?.findIndex((o) => o.name === name);
        if (outIdx == null || outIdx < 0) continue;
        if (!builder.inputs?.some((inp) => inp.name === name)) {
            builder.addInput(name, ioType);
        }
        const input = builder.inputs.find((inp) => inp.name === name);
        if (input.link == null) {
            source.connect(outIdx, builder, name);
            wired++;
        }
    }
    return wired;
}

// Refs come straight off the Regional Prompt node's ref_N outputs; the
// legacy Refs Split route stays as a fallback for older graphs.
function wireRefs(rp, builder, count) {
    if (rp.outputs?.some((o) => o.name === "ref_1")) {
        return wireFamily(rp, builder, "ref", "IMAGE", count);
    }
    const graph = app.graph;
    const LG = window.LiteGraph;
    let split = (graph._nodes || []).find(
        (n) => n.comfyClass === SPLIT_TYPE && originNode(n, "image_refs") === rp);
    if (!split) {
        split = LG?.createNode?.(SPLIT_TYPE);
        if (!split) return 0;
        split.pos = [builder.pos[0] - 300, builder.pos[1] + 120];
        graph.add(split);
        const outIdx = rp.outputs.findIndex((o) => o.name === "image_refs");
        if (outIdx >= 0) rp.connect(outIdx, split, 0);
    }
    return wireFamily(split, builder, "ref", "IMAGE", count);
}

// Descs come straight off the Regional Prompt node's desc_N outputs
// (LLM-enhanced when its enhance_prompts toggle is on); legacy Enhancer /
// Prompts Split nodes remain as fallbacks for older graphs.
function wireDescs(rp, builder, count) {
    const all = app.graph._nodes || [];
    const source =
        (rp?.outputs?.some((o) => o.name === "desc_1") ? rp : null) ||
        all.find((n) => n.comfyClass === ENHANCER_TYPE) ||
        all.find((n) => n.comfyClass === PROMPTS_SPLIT_TYPE);
    if (!source) return 0;
    if (!builder.properties) builder.properties = {};
    builder.properties.erpk_region_desc =
        Array.from({ length: Math.min(count, MAX_REFS) }, (_, i) => i + 1);
    return wireFamily(source, builder, "desc", "STRING", count);
}

// ERPK only drops a desc_N/ref_N socket that is neither exposed nor wired, so
// a fill from a smaller template would otherwise keep the previous template's
// sockets and wires alive. Clearing the families first makes every fill
// rebuild them from scratch at exactly the new region count.
function resetFamilies(builder) {
    for (let i = (builder.inputs?.length ?? 0) - 1; i >= 0; i--) {
        if (!FAMILY_RE.test(builder.inputs[i].name || "")) continue;
        if (builder.inputs[i].link != null) builder.disconnectInput(i);
        builder.removeInput(i);
    }
    if (!builder.properties) builder.properties = {};
    builder.properties.erpk_region_desc = [];
    builder.properties.erpk_region_ref = [];
}

function fillBuilder(builder) {
    const { rp, editor } = resolveSources(builder);
    if (!editor) {
        toast("error", "No template found",
              "Wire the base sheet (or the Symbiotica Regional Prompt image) into "
              + "this node's image input, or keep one Template Editor in the graph.");
        return;
    }
    let regions = [];
    try {
        regions = JSON.parse(widgetByName(editor, "regions_json")?.value || "[]");
    } catch (_) { /* fall through to the empty check */ }
    if (!Array.isArray(regions) || !regions.length) {
        toast("error", "Template has no regions",
              "Open the Template Editor, prefill/save regions first.");
        return;
    }
    const doc = toErpkDoc(regions);
    const regionsWidget = widgetByName(builder, "regions_data");
    if (!regionsWidget) {
        toast("error", "Fill failed", "regions_data widget missing on this node.");
        return;
    }
    regionsWidget.value = JSON.stringify(doc);
    const w = Number(widgetByName(editor, "max_width")?.value) || 2048;
    const h = Number(widgetByName(editor, "max_height")?.value) || 2048;
    const widthWidget = widgetByName(builder, "width");
    const heightWidget = widgetByName(builder, "height");
    if (widthWidget) widthWidget.value = w;
    if (heightWidget) heightWidget.value = h;
    const slots = Math.min(doc.regions.length, MAX_REFS);
    resetFamilies(builder);
    const family = Array.from({ length: slots }, (_, i) => i + 1);
    builder.properties.erpk_region_ref = family;
    builder.properties.erpk_region_desc = [...family];
    if (rp) syncRegionOutputs(rp, slots);

    // The ERPK editor re-reads regions_data through its own loader so the
    // canvas, sockets, and labels all refresh from the document we just wrote
    // — including the desc_N/ref_N sockets, which it re-adds for exactly the
    // slots exposed above, labelled with each region's real text.
    const erpkEditor = builder._erpkRegionEditor;
    erpkEditor?.loadFromWidget?.();
    erpkEditor?.layout?.();

    let wired = 0;
    if (rp) {
        // Base sheet in, refs and descs per region — all from the one node.
        const imgInput = builder.inputs?.find((inp) => inp.name === "image");
        if (imgInput && imgInput.link == null) {
            const outIdx = rp.outputs.findIndex((o) => o.name === "image");
            if (outIdx >= 0) rp.connect(outIdx, builder, "image");
        }
        wired = wireRefs(rp, builder, doc.regions.length);
    } else {
        toast("warn", "Refs not wired",
              "No Symbiotica Regional Prompt node found — regions filled without "
              + "reference images.");
    }
    const descsWired = wireDescs(rp, builder, doc.regions.length);
    builder.setDirtyCanvas?.(true, true);
    toast("success", "Regions filled",
          `${doc.regions.length} regions from the template`
          + (wired ? `, ${wired} refs wired` : "")
          + (descsWired ? `, ${descsWired} prompts wired` : ""));
}

// After each run, mirror the Regional Prompt node's FINAL per-region prompts
// (LLM-enhanced) into any builder canvas wired to it, so hovering a region
// shows what actually executes — not the raw spreadsheet text.
function applyDescsToBuilders(rpId, descs) {
    for (const builder of app.graph._nodes || []) {
        if (builder.comfyClass !== BUILDER_TYPE) continue;
        const src = originNode(builder, "desc_1") || originNode(builder, "image");
        if (!src || String(src.id) !== String(rpId)) continue;
        const widget = widgetByName(builder, "regions_data");
        if (!widget) continue;
        let doc;
        try { doc = JSON.parse(widget.value || "{}"); } catch (_) { continue; }
        const regions = Array.isArray(doc?.regions) ? doc.regions : null;
        if (!regions) continue;
        regions.forEach((region, i) => {
            if (descs[i]) region.content = { ...region.content, desc: descs[i] };
        });
        widget.value = JSON.stringify(doc);
        const ed = builder._erpkRegionEditor;
        ed?.loadFromWidget?.();
        ed?.layout?.();
        builder.setDirtyCanvas?.(true, true);
    }
}

app.registerExtension({
    name: "symbiotica.regionsBridge",
    setup() {
        api.addEventListener("symbiotica.region_descs", ({ detail }) => {
            if (detail?.node_id != null && Array.isArray(detail.descs)) {
                applyDescsToBuilders(detail.node_id, detail.descs);
            }
        });
        setInterval(() => {
            for (const node of app.graph?._nodes || []) {
                if (node.comfyClass === RP_TYPE) syncFromTemplate(node);
            }
        }, 500);
    },
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === BUILDER_TYPE) {
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                const r = onNodeCreated?.apply(this, arguments);
                this.addWidget("button", "⇪ Fill from Symbiotica template", null,
                               () => fillBuilder(this));
                return r;
            };
            return;
        }
        if (nodeData.name !== RP_TYPE) return;
        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const r = onConnectionsChange?.apply(this, arguments);
            // A new template upstream means a new region count; the cached
            // regions_json is stale by definition.
            this._symRegionsRaw = undefined;
            return r;
        };
    },
});
