// ABOUTME: Bridge between the Symbiotica Template Editor and ERPK's Regional
// ABOUTME: Prompt Builder — a "Fill from Symbiotica template" button on the ERPK
// ABOUTME: node writes the template's regions into its canvas (regions_data, v2
// ABOUTME: contract), sizes the frame, and wires the editor's base sheet plus
// ABOUTME: one task-sheet crop per region into its image/ref_N sockets. The
// ABOUTME: edit prompt is NOT wired here: it is written by an LLM node from the
// ABOUTME: editor's skeleton and goes straight to the image-edit node.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const BUILDER_TYPE = "RegionalPromptBuilder";
const EDITOR_TYPE = "SymbioticaTemplateEditor";
const RP_TYPE = "SymbioticaRegionalPrompt";
const SPLIT_TYPE = "SymbioticaRefsSplit";
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

// Both node families ship 10 slots' worth of per-region outputs; the template
// decides how many are real. The rest are trimmed off the TAIL — an output's
// slot index is what the API prompt cites, so dropping one from the middle
// would silently remap every wire below it. The editor's refs are a plain
// run of ref_N (stride 1); the legacy Regional Prompt node interleaves
// desc_N/ref_N pairs (stride 2) for exactly this reason.
function syncRegionOutputs(node, count, spec) {
    const n = Math.min(MAX_REFS, count);
    if (!node.outputs || n < 1) return;
    const first = node.outputs.findIndex((o) => o.name === spec.first);
    if (first >= 0) node._symSlotBase = first;
    const base = node._symSlotBase;
    if (base == null) return;
    // A workflow saved before the outputs took this shape carries the old
    // order, where the slots no longer mean what their names say. Rebuilding
    // the family is the only honest repair — pressing fill rewires it.
    const second = node.outputs[base + 1];
    if (spec.stride === 2 && second && second.name !== "ref_1") {
        while (node.outputs.length > base) {
            node.removeOutput(node.outputs.length - 1);
        }
    }
    const want = base + spec.stride * n;
    while (node.outputs.length > want) node.removeOutput(node.outputs.length - 1);
    while (node.outputs.length < want) {
        const slot = node.outputs.length - base;
        const [name, type] = spec.at(slot);
        node.addOutput(name, type);
    }
}

const REF_RUN = {
    first: "ref_1",
    stride: 1,
    at: (slot) => [`ref_${slot + 1}`, "IMAGE"],
};
const DESC_REF_PAIRS = {
    first: "desc_1",
    stride: 2,
    at: (slot) => (slot % 2
        ? [`ref_${Math.floor(slot / 2) + 1}`, "IMAGE"]
        : [`desc_${Math.floor(slot / 2) + 1}`, "STRING"]),
};

// Re-sync only when the template's regions actually changed. Polled rather
// than hooked: the editor writes regions_json from four places (save, close,
// gallery pick, raw edit) and a string compare per node is cheaper than
// keeping a hook on each of them honest.
function syncFromTemplate(node) {
    const isEditor = node.comfyClass === EDITOR_TYPE;
    const editor = isEditor ? node : originNode(node, "template");
    const raw = editor?.comfyClass === EDITOR_TYPE
        ? (widgetByName(editor, "regions_json")?.value ?? "") : "";
    if (raw === node._symRegionsRaw) return;
    node._symRegionsRaw = raw;
    const regions = regionsOf(editor);
    if (!regions.length) return;
    syncRegionOutputs(node, regions.length, isEditor ? REF_RUN : DESC_REF_PAIRS);
    labelRefOutputs(node, regions);
    node.setDirtyCanvas?.(true, true);
}

// Show each ref_N output as its region's asset name (Food, Decoration, the
// asset), so a wired ref is recognizable at a glance instead of "ref_3".
function labelRefOutputs(node, regions) {
    const ordered = [...regions].sort((a, b) => (a.zIndex ?? 0) - (b.zIndex ?? 0));
    for (const output of node.outputs || []) {
        const m = /^ref_(\d+)$/.exec(output.name || "");
        if (!m) continue;
        const region = ordered[+m[1] - 1];
        output.label = region ? (region.name || output.name) : output.name;
    }
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

// Connect one named output to one named input, leaving an existing wire alone.
// The width/height inputs only exist once ComfyUI has promoted those widgets
// to sockets, so a missing input is normal, not an error.
function wireOutput(source, builder, inputName, outputName) {
    const input = builder.inputs?.find((inp) => inp.name === inputName);
    if (!input || input.link != null) return false;
    const outIdx = source.outputs?.findIndex((o) => o.name === outputName);
    if (outIdx == null || outIdx < 0) return false;
    source.connect(outIdx, builder, inputName);
    return true;
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
    // Refs only: the edit prompt is written by the LLM node downstream, so the
    // builder's own prompt — and the desc_N sockets that feed it — go unused.
    builder.properties.erpk_region_ref =
        Array.from({ length: slots }, (_, i) => i + 1);
    const refSource = editor.outputs?.some((o) => o.name === "ref_1")
        ? editor : rp;
    if (refSource) {
        syncRegionOutputs(refSource, slots,
                          refSource === editor ? REF_RUN : DESC_REF_PAIRS);
    }

    // The ERPK editor re-reads regions_data through its own loader so the
    // canvas, sockets, and labels all refresh from the document we just wrote
    // — including the desc_N/ref_N sockets, which it re-adds for exactly the
    // slots exposed above, labelled with each region's real text.
    const erpkEditor = builder._erpkRegionEditor;
    erpkEditor?.loadFromWidget?.();
    erpkEditor?.layout?.();

    let wired = 0;
    if (refSource) {
        // Base sheet in, one task-sheet crop per region — all from the editor.
        wireOutput(refSource, builder, "image",
                   refSource === editor ? "base sheet" : "image");
        wireOutput(refSource, builder, "width", "width");
        wireOutput(refSource, builder, "height", "height");
        wired = wireRefs(refSource, builder, doc.regions.length);
    } else {
        toast("warn", "Refs not wired",
              "The Template Editor has no ref_N outputs — update the Symbiotica "
              + "pack and reload the page.");
    }
    builder.setDirtyCanvas?.(true, true);
    toast("success", "Regions filled",
          `${doc.regions.length} regions from the template`
          + (wired ? `, ${wired} refs wired` : ""));
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
                if (node.comfyClass === EDITOR_TYPE || node.comfyClass === RP_TYPE) {
                    syncFromTemplate(node);
                }
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
