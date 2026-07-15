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
    if (!builder.properties) builder.properties = {};
    builder.properties.erpk_region_ref =
        doc.regions.slice(0, MAX_REFS).map((_, i) => i + 1);

    // The ERPK editor re-reads regions_data through its own loader so the
    // canvas, sockets, and labels all refresh from the document we just wrote.
    const erpkEditor = builder._erpkRegionEditor;
    erpkEditor?.setup?.();
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
    },
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== BUILDER_TYPE) return;
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const r = onNodeCreated?.apply(this, arguments);
            this.addWidget("button", "⇪ Fill from Symbiotica template", null,
                           () => fillBuilder(this));
            return r;
        };
    },
});
