// ABOUTME: Frontend for the Symbiotica order pipeline nodes — dynamic event and
// ABOUTME: group combos fed by server pushes, plus an events browser on Order Read.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// node.id -> {events, refFileCount, refsRoot} (last parse per Order Read node)
const orderCache = new Map();

// --- mirrors of py/pipeline/order_sheet.py (keep in sync) -------------------
function slugify(s) {
    return s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

function templateGroups(event) {
    const groups = new Map();
    for (const a of event.assets) {
        if (!a.assetName) continue;
        const key = `${a.category}|${a.canvas}`;
        if (!groups.has(key)) {
            groups.set(key, {
                template: slugify(`${event.feature}-${a.category}-${a.canvas}`),
                category: a.category,
                canvas: a.canvas,
                assets: [],
            });
        }
        groups.get(key).assets.push(a);
    }
    return [...groups.values()];
}

// --- graph helpers -----------------------------------------------------------
function upstreamNode(node, inputName) {
    const input = node.inputs?.find((i) => i.name === inputName);
    if (!input || input.link == null) return null;
    const link = app.graph.links[input.link];
    return link ? app.graph.getNodeById(link.origin_id) : null;
}

function downstreamNodes(node, type) {
    const out = [];
    for (const output of node.outputs ?? []) {
        for (const linkId of output.links ?? []) {
            const link = app.graph.links[linkId];
            const target = link && app.graph.getNodeById(link.target_id);
            if (target && target.comfyClass === type) out.push(target);
        }
    }
    return out;
}

function orderDataFor(node) {
    // Walk up: Specs -> Order Read; Template -> Specs -> Order Read.
    let cur = node;
    for (let hop = 0; hop < 3 && cur; hop++) {
        if (cur.comfyClass === "SymbioticaOrderRead") return orderCache.get(cur.id);
        cur = upstreamNode(cur, cur.comfyClass === "SymbioticaTemplateBuilder" ? "spec" : "events");
    }
    return undefined;
}

// --- widget upgrades ---------------------------------------------------------
function comboify(node, widgetName, valuesFn) {
    const w = node.widgets?.find((x) => x.name === widgetName);
    if (!w) return;
    w.type = "combo";
    w.options = w.options ?? {};
    w.options.values = valuesFn; // LiteGraph accepts a function — always fresh
}

function refreshCombos(node) {
    for (const specs of downstreamNodes(node, "SymbioticaEventSpecs")) {
        specs.setDirtyCanvas(true, true);
        for (const tpl of downstreamNodes(specs, "SymbioticaTemplateBuilder")) {
            tpl.setDirtyCanvas(true, true);
        }
    }
}

// --- events browser ----------------------------------------------------------
function thumbUrl(refsRoot, file) {
    return api.apiURL(
        `/symbiotica/local-image?path=${encodeURIComponent(`${refsRoot}/${file}`)}`
    ).replace("/api/", "/"); // route registered at server root, not under /api
}

function renderBrowser(container, data) {
    container.innerHTML = "";
    if (!data) {
        container.textContent = "Queue once to parse the order.";
        container.style.opacity = "0.6";
        return;
    }
    container.style.opacity = "1";
    for (const ev of data.events) {
        const named = ev.assets.filter((a) => a.assetName);
        const refCount = ev.assets.filter((a) => a.refFiles.length > 0).length;
        const unspecced = ev.assets.every((a) => !a.assetName);

        const card = document.createElement("div");
        card.style.cssText =
            "border:1px solid #444;border-radius:6px;margin:2px 0;padding:4px 6px;" +
            "font-size:11px;cursor:pointer;background:#2a2a2a;";
        const head = document.createElement("div");
        head.style.cssText = "display:flex;justify-content:space-between;gap:6px;";
        head.innerHTML =
            `<span><b>${ev.feature}</b> ${ev.eventName ?? ""}</span>` +
            `<span style="opacity:.7">${unspecced
                ? `${ev.assets.length} slots — unspecced`
                : `${ev.assets.length} assets · ${refCount} refs`}</span>`;
        card.appendChild(head);

        const body = document.createElement("div");
        body.style.display = "none";
        for (const g of templateGroups(ev)) {
            const gh = document.createElement("div");
            gh.style.cssText = "margin-top:4px;opacity:.7;text-transform:uppercase;font-size:10px;";
            gh.textContent = `${g.template} · ${g.assets.length}`;
            body.appendChild(gh);
            for (const a of g.assets) {
                const row = document.createElement("div");
                row.style.cssText = "display:flex;align-items:center;gap:4px;margin:2px 0;";
                const label = document.createElement("span");
                label.style.cssText = "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
                label.textContent = `${a.assetName} · ${a.canvas}`;
                row.appendChild(label);
                if (!a.refFiles.length) {
                    const chip = document.createElement("span");
                    chip.style.opacity = "0.5";
                    chip.textContent = "no refs";
                    row.appendChild(chip);
                } else if (data.refsRoot) {
                    for (const f of a.refFiles.slice(0, 5)) {
                        const img = document.createElement("img");
                        img.src = thumbUrl(data.refsRoot, f);
                        img.style.cssText =
                            "width:22px;height:22px;object-fit:contain;background:#111;border-radius:3px;";
                        row.appendChild(img);
                    }
                    if (a.refFiles.length > 5) {
                        const more = document.createElement("span");
                        more.textContent = `+${a.refFiles.length - 5}`;
                        row.appendChild(more);
                    }
                }
                body.appendChild(row);
            }
        }
        card.appendChild(body);
        head.addEventListener("click", () => {
            body.style.display = body.style.display === "none" ? "block" : "none";
        });
        container.appendChild(card);
    }
}

// --- extension ---------------------------------------------------------------
app.registerExtension({
    name: "symbiotica.order_pipeline",

    setup() {
        api.addEventListener("symbiotica.order_events", ({ detail }) => {
            const nodeId = Number(detail.node_id);
            orderCache.set(nodeId, detail);
            const node = app.graph.getNodeById(nodeId);
            if (!node) return;
            if (node._symbioticaBrowser) renderBrowser(node._symbioticaBrowser, detail);
            refreshCombos(node);
        });
    },

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "SymbioticaOrderRead") {
            const orig = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                orig?.apply(this, arguments);
                const container = document.createElement("div");
                container.style.cssText =
                    "max-height:280px;overflow-y:auto;padding:2px;";
                this._symbioticaBrowser = container;
                renderBrowser(container, undefined);
                this.addDOMWidget("events_browser", "custom", container,
                                  { serialize: false, hideOnZoom: true });
                this.size[0] = Math.max(this.size[0], 320);
            };
        }

        if (nodeData.name === "SymbioticaEventSpecs") {
            const orig = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                orig?.apply(this, arguments);
                comboify(this, "feature", () => {
                    const data = orderDataFor(this);
                    return data ? data.events.map((e) => e.feature) : [];
                });
            };
        }

        if (nodeData.name === "SymbioticaTemplateBuilder") {
            const orig = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                orig?.apply(this, arguments);
                comboify(this, "group", () => {
                    const data = orderDataFor(this);
                    if (!data) return [];
                    const specs = upstreamNode(this, "spec");
                    const feature = specs?.widgets?.find((w) => w.name === "feature")?.value;
                    const ev = data.events.find((e) => e.feature === feature);
                    return ev ? templateGroups(ev).map((g) => g.template) : [];
                });
            };
        }
    },
});
