// ABOUTME: Bridge between the Symbiotica template pipeline and ERPK's Regional
// ABOUTME: Prompt Builder — a "Fill from Symbiotica template" button on the ERPK
// ABOUTME: node writes the template's regions into its canvas (regions_data, v2
// ABOUTME: contract), sizes the frame, exposes ref sockets, and auto-wires
// ABOUTME: per-region reference crops through a Symbiotica Refs Split node.
import { app } from "../../../scripts/app.js";

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

// Route rp.image_refs through a (found or created) Symbiotica Refs Split and
// wire its per-region outputs onto the builder's ref_N sockets.
function wireRefs(rp, builder, count) {
    const graph = app.graph;
    const LG = window.LiteGraph;
    let split = (graph._nodes || []).find(
        (n) => n.comfyClass === SPLIT_TYPE && originNode(n, "image_refs") === rp);
    if (!split) {
        split = LG?.createNode?.(SPLIT_TYPE);
        if (!split) {
            toast("warn", "Refs not wired",
                  "SymbioticaRefsSplit node unavailable — update the pack and reboot.");
            return 0;
        }
        split.pos = [builder.pos[0] - 300, builder.pos[1] + 120];
        graph.add(split);
        const outIdx = rp.outputs.findIndex((o) => o.name === "image_refs");
        if (outIdx >= 0) rp.connect(outIdx, split, 0);
    }
    let wired = 0;
    for (let i = 0; i < Math.min(count, MAX_REFS); i++) {
        const inputName = `ref_${i + 1}`;
        if (!builder.inputs?.some((inp) => inp.name === inputName)) {
            builder.addInput(inputName, "IMAGE");
        }
        const input = builder.inputs.find((inp) => inp.name === inputName);
        if (input.link == null) {
            split.connect(i, builder, inputName);
            wired++;
        }
    }
    return wired;
}

// Wire a desc source's desc_N outputs onto the builder's desc_N sockets —
// each overrides its region's description with the LLM-enhanced prompt.
// Prefers a Symbiotica Prompt Enhancer (self-contained LLM node), falls back
// to a Prompts Split; both are user-placed, so never auto-created.
function wireDescs(builder, count) {
    const all = app.graph._nodes || [];
    const source =
        all.find((n) => n.comfyClass === ENHANCER_TYPE) ||
        all.find((n) => n.comfyClass === PROMPTS_SPLIT_TYPE);
    if (!source) return 0;
    if (!builder.properties) builder.properties = {};
    builder.properties.erpk_region_desc =
        Array.from({ length: Math.min(count, MAX_REFS) }, (_, i) => i + 1);
    let wired = 0;
    for (let i = 0; i < Math.min(count, MAX_REFS); i++) {
        const inputName = `desc_${i + 1}`;
        const outIdx = source.outputs?.findIndex((o) => o.name === inputName);
        if (outIdx == null || outIdx < 0) continue;
        if (!builder.inputs?.some((inp) => inp.name === inputName)) {
            builder.addInput(inputName, "STRING");
        }
        const input = builder.inputs.find((inp) => inp.name === inputName);
        if (input.link == null) {
            source.connect(outIdx, builder, inputName);
            wired++;
        }
    }
    return wired;
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
        wired = wireRefs(rp, builder, doc.regions.length);
    } else {
        toast("warn", "Refs not wired",
              "No Symbiotica Regional Prompt node found — regions filled without "
              + "reference images.");
    }
    const descsWired = wireDescs(builder, doc.regions.length);
    builder.setDirtyCanvas?.(true, true);
    toast("success", "Regions filled",
          `${doc.regions.length} regions from the template`
          + (wired ? `, ${wired} refs wired` : "")
          + (descsWired ? `, ${descsWired} enhanced prompts wired` : ""));
}

app.registerExtension({
    name: "symbiotica.regionsBridge",
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
