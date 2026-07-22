// ABOUTME: Frontend for the Symbiotica order pipeline nodes — dynamic event and
// ABOUTME: group combos fed by server pushes, events browser, and the template editor.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { openTemplateEditor } from "./template_editor/editor.js";

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

// Event combo label ("Mini 1 — Ghostly Goodies") vs the stored key ("Mini 1").
// The value may be either form (saved workflows keep the plain feature); the
// key strips the " — <name>" the combo appends.
function eventLabel(e) {
    return e.eventName ? `${e.feature} — ${e.eventName}` : e.feature;
}
function featureKey(value) {
    return String(value ?? "").split(" — ")[0].trim();
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

const SPEC_INPUT_NODES = new Set(["SymbioticaTemplateBuilder", "SymbioticaTemplateEditor"]);

function orderDataFor(node) {
    // Walk up to Order Read: the editor may wire it straight in (events) or go
    // through Event Specs (spec -> events). Try a direct events wire first.
    let cur = node;
    for (let hop = 0; hop < 4 && cur; hop++) {
        if (cur.comfyClass === "SymbioticaOrderRead") return orderCache.get(cur.id);
        cur = upstreamNode(cur, "events") || upstreamNode(cur, "spec");
    }
    return undefined;
}

function pickedEventFor(node) {
    // The upstream Specs node's chosen feature's event, from the order cache.
    const data = orderDataFor(node);
    if (!data) return undefined;
    const specs = upstreamNode(node, "spec");
    const feature = specs?.widgets?.find((w) => w.name === "feature")?.value;
    return data.events.find((e) => e.feature === feature);
}

// --- widget upgrades ---------------------------------------------------------
function comboify(node, widgetName, valuesFn) {
    const i = node.widgets?.findIndex((x) => x.name === widgetName);
    if (i == null || i < 0) return;
    const existing = node.widgets[i];
    if (existing.type === "combo") {
        existing.options = existing.options ?? {};
        existing.options.values = valuesFn; // LiteGraph accepts a function
        return existing;
    }
    // The classic (non-Vue) node UI won't turn a text widget into a dropdown by
    // mutating `.type` — it keeps the text-prompt behavior. Recreate it as a
    // REAL combo widget in the same slot so both UIs show a dropdown. Preserve
    // the value + serialization so the string still reaches the Python node.
    const value = existing.value;
    node.widgets.splice(i, 1);
    const w = node.addWidget("combo", widgetName, value,
                             (v) => { w.value = v; }, { values: valuesFn });
    node.widgets = node.widgets.filter((x) => x !== w); // move it back to slot i
    node.widgets.splice(i, 0, w);
    w.serializeValue = () => w.value;
    return w;
}

// Turn a node's `month` text widget into a dropdown fed by the months found
// under its project_path/orders — and keep it fresh when the path changes.
function wireMonthPicker(node) {
    node._symMonths = [];
    comboify(node, "month", () => node._symMonths);
    const refresh = async () => {
        const project = widgetOf(node, "project_path")?.value?.trim();
        if (!project) { node._symMonths = []; return; }
        try {
            const data = await fetchJson(
                "/symbiotica/list-orders?project=" + encodeURIComponent(project));
            node._symMonths = (data.months ?? []).map((m) => m.label);
            const monthW = widgetOf(node, "month");
            if (monthW && !node._symMonths.includes(monthW.value)) {
                monthW.value = node._symMonths[0] ?? "";
            }
        } catch { node._symMonths = []; }
        node.setDirtyCanvas?.(true, true);
    };
    const projectW = widgetOf(node, "project_path");
    if (projectW) {
        const prev = projectW.callback;
        projectW.callback = function () {
            const r = prev?.apply(this, arguments);
            refresh();
            return r;
        };
    }
    refresh();
}

// Order Specs is a leaf picker (no upstream): it reads its own project + month.
// Parse the order server-side and cache the events on the node, so its own
// `feature` combo and a downstream Auto Packer's `category` combo can read the
// event list synchronously.
async function refreshOrderSpecs(node) {
    const project = widgetOf(node, "project_path")?.value?.trim();
    const month = widgetOf(node, "month")?.value?.trim();
    if (!project) { node._symEvents = []; node.setDirtyCanvas?.(true, true); return; }
    const q = new URLSearchParams({ project });
    if (month) q.set("month", month);
    try {
        const data = await fetchJson(`/symbiotica/parse-order?${q}`);
        node._symEvents = data.events ?? [];
        node._symRefsRoot = data.refsRoot ?? "";
    } catch { node._symEvents = []; }
    // Keep the feature value valid (accept the plain feature OR the labelled
    // form); empty means "the order's first event". Never reset a value that
    // still matches an event by key — that would clobber a saved workflow.
    const featW = widgetOf(node, "feature");
    if (featW && featW.value) {
        const key = featureKey(featW.value);
        if (!node._symEvents.some((e) => e.feature === key)) {
            featW.value = node._symEvents[0] ? eventLabel(node._symEvents[0]) : "";
        }
    }
    // Re-render any downstream Auto Packer asset panels now that the event's
    // assets (and refsRoot) are known.
    for (const ap of downstreamNodes(node, "SymbioticaAutoPacker")) {
        ap._symRenderAssets?.();
    }
    node.setDirtyCanvas?.(true, true);
}

function wireOrderSpecs(node) {
    node._symEvents = [];
    wireMonthPicker(node); // month combo, refreshed on project_path change
    comboify(node, "feature", () => (node._symEvents ?? []).map(eventLabel));
    // Re-parse whenever project OR month changes (chains onto wireMonthPicker's
    // own project_path hook — both fire). `feature` too, so a downstream Auto
    // Packer panel re-renders for the newly picked event.
    for (const name of ["project_path", "month", "feature"]) {
        const w = widgetOf(node, name);
        if (!w) continue;
        const prev = w.callback;
        w.callback = function () {
            const r = prev?.apply(this, arguments);
            refreshOrderSpecs(node);
            return r;
        };
    }
    refreshOrderSpecs(node);
}

// The categories of the event an Auto Packer's upstream Order Specs has picked
// (named assets only), for its `category` combo. Opportunistically re-parses
// upstream when its cache is empty so the next open is populated.
function eventCategoriesFor(node) {
    const specs = upstreamNode(node, "order");
    if (!specs || specs.comfyClass !== "SymbioticaOrderSpecs") return ["All"];
    const events = specs._symEvents ?? [];
    if (!events.length) { refreshOrderSpecs(specs); return ["All"]; }
    const feature = featureKey(widgetOf(specs, "feature")?.value);
    const ev = events.find((e) => e.feature === feature) || events[0];
    const cats = ev
        ? [...new Set(ev.assets.filter((a) => a.assetName).map((a) => a.category))]
              .sort((a, b) => a.localeCompare(b))
        : [];
    return ["All", ...cats];
}

// The selected event's assets + refsRoot for an Auto Packer, filtered to the
// node's chosen `category` (All = every type). Empty when no upstream yet.
function eventAssetsFor(node) {
    const specs = upstreamNode(node, "order");
    if (!specs || specs.comfyClass !== "SymbioticaOrderSpecs")
        return { assets: [], refsRoot: "" };
    const events = specs._symEvents ?? [];
    if (!events.length) refreshOrderSpecs(specs);
    const feature = featureKey(widgetOf(specs, "feature")?.value);
    const ev = events.find((e) => e.feature === feature) || events[0];
    const cat = widgetOf(node, "category")?.value?.trim() || "All";
    const assets = (ev?.assets ?? []).filter(
        (a) => a.assetName && (cat === "All" || a.category === cat));
    return { assets, refsRoot: specs._symRefsRoot ?? "" };
}

function symImg(src, px) {
    const img = document.createElement("img");
    img.src = src;
    img.style.cssText = `width:${px}px;height:${px}px;object-fit:contain;`
        + "background:#111;border-radius:3px;flex:none;";
    return img;
}

// An interactive Assets panel on the Auto Packer: the chosen category's assets
// with thumbnails, a hide toggle per asset, and per-cell reorder arrows for
// multi-reference assets. Drives the hidden `overrides` widget
// ({hidden:[name], reorder:{name:"1,3,2"}}) — supports many hides + reorders.
function assetsPanel(node) {
    const ovW = widgetOf(node, "overrides");
    let state = { hidden: [], cells: {} };
    try { state = { hidden: [], cells: {}, ...JSON.parse(ovW?.value || "{}") }; }
    catch { /* keep default */ }

    const container = document.createElement("div");
    container.style.cssText = "max-height:320px;overflow-y:auto;padding:2px 2px 4px;"
        + "font-size:11px;";
    stopWheel(container);
    node.addDOMWidget("assets_panel", "sym_assets", container,
                      { serialize: false, hideOnZoom: true });
    node.size[0] = Math.max(node.size[0], 320);

    const save = () => {
        if (ovW) ovW.value = JSON.stringify(state);
        node.setDirtyCanvas?.(true, true);
    };

    node._symRenderAssets = () => render();
    function render() {
        container.replaceChildren();
        const { assets, refsRoot } = eventAssetsFor(node);
        if (!assets.length) {
            container.textContent = "Wire an Order Specs and pick an event.";
            container.style.opacity = ".6";
            return;
        }
        container.style.opacity = "1";
        for (const a of assets) {
            const hidden = state.hidden.includes(a.assetName);
            const row = document.createElement("div");
            row.style.cssText = "display:flex;flex-direction:column;gap:3px;"
                + "border:1px solid #3a3a3a;border-radius:6px;padding:4px 5px;"
                + `margin:3px 0;background:${hidden ? "#241a1a" : "#2a2a2a"};`
                + `opacity:${hidden ? ".5" : "1"};`;
            // header: name + hide toggle
            const head = document.createElement("div");
            head.style.cssText = "display:flex;align-items:center;gap:6px;";
            const refs = a.refFiles ?? [];
            if (refs[0] && refsRoot) head.appendChild(symImg(thumbUrl(refsRoot, refs[0]), 18));
            const name = document.createElement("span");
            name.textContent = `${a.assetName} · ${a.canvas}`;
            name.style.cssText = "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
            head.appendChild(name);
            const eye = document.createElement("button");
            eye.textContent = hidden ? "hidden" : "hide";
            eye.style.cssText = "font-size:10px;padding:1px 6px;border-radius:4px;cursor:pointer;"
                + `border:1px solid #555;background:${hidden ? "#7a3a3a" : "#333"};color:#ddd;`;
            eye.addEventListener("pointerdown", (e) => {
                e.stopPropagation();
                state.hidden = hidden ? state.hidden.filter((n) => n !== a.assetName)
                                      : [...state.hidden, a.assetName];
                save(); render();
            });
            head.appendChild(eye);
            row.appendChild(head);
            // cells: reorder arrows for multi-ref assets
            if (!hidden && refs.length > 1 && refsRoot) {
                // Explicit cell list (reorder + drop). If stored, use as-is —
                // do NOT re-add missing indices, or a removed cell comes back.
                const stored = state.cells[a.assetName];
                const order = (stored ? stored.slice()
                    : refs.map((_, i) => i + 1)).filter((i) => i >= 1 && i <= refs.length);
                const commit = () => { state.cells[a.assetName] = order.slice(); save(); render(); };
                const cells = document.createElement("div");
                cells.style.cssText = "display:flex;gap:4px;flex-wrap:wrap;";
                order.forEach((refIdx, pos) => {
                    const cell = document.createElement("div");
                    cell.style.cssText = "display:flex;flex-direction:column;align-items:center;gap:1px;";
                    cell.appendChild(symImg(thumbUrl(refsRoot, refs[refIdx - 1]), 30));
                    const btns = document.createElement("div");
                    btns.style.cssText = "display:flex;gap:2px;";
                    const mk = (txt, fn, danger) => {
                        const b = document.createElement("button");
                        b.textContent = txt;
                        b.style.cssText = "font-size:11px;line-height:1;padding:1px 5px;border-radius:3px;"
                            + `cursor:pointer;border:1px solid #555;color:#ccc;`
                            + `background:${danger ? "#5a2a2a" : "#333"};`;
                        b.addEventListener("pointerdown", (e) => { e.stopPropagation(); fn(); });
                        return b;
                    };
                    btns.append(
                        mk("←", () => { if (pos > 0) { [order[pos], order[pos - 1]] = [order[pos - 1], order[pos]]; commit(); } }),
                        mk("→", () => { if (pos < order.length - 1) { [order[pos], order[pos + 1]] = [order[pos + 1], order[pos]]; commit(); } }),
                        mk("−", () => { if (order.length > 1) { order.splice(pos, 1); commit(); } }, true),
                    );
                    cell.appendChild(btns);
                    cells.appendChild(cell);
                });
                row.appendChild(cells);
            }
            container.appendChild(row);
        }
    }

    // Re-render when the category changes.
    const catW = widgetOf(node, "category");
    if (catW) {
        const prev = catW.callback;
        catW.callback = function () {
            const r = prev?.apply(this, arguments);
            render();
            return r;
        };
    }
    render();
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
    // Keep the /api/ prefix: it works locally (ComfyUI mirrors custom routes
    // under /api/) AND behind the Modal gateway, which proxies /api/* only — a
    // root-level /symbiotica/* never reaches the editor sandbox there, so
    // stripping /api/ blanked every thumbnail on Modal.
    return api.apiURL(
        `/symbiotica/local-image?path=${encodeURIComponent(`${refsRoot}/${file}`)}`
    );
}

function renderBrowser(container, data) {
    container.replaceChildren();
    if (!data) {
        container.textContent = "Queue once to parse the order.";
        container.style.opacity = "0.6";
        return;
    }
    container.style.opacity = "1";
    for (const ev of data.events) {
        const refCount = ev.assets.filter((a) => a.refFiles.length > 0).length;
        const unspecced = ev.assets.every((a) => !a.assetName);

        const card = document.createElement("div");
        card.style.cssText =
            "border:1px solid #444;border-radius:6px;margin:2px 0;padding:4px 6px;" +
            "font-size:11px;cursor:pointer;background:#2a2a2a;";
        const head = document.createElement("div");
        head.style.cssText = "display:flex;justify-content:space-between;gap:6px;";
        const title = document.createElement("span");
        const strong = document.createElement("b");
        strong.textContent = ev.feature;
        title.appendChild(strong);
        title.appendChild(document.createTextNode(` ${ev.eventName ?? ""}`));
        const count = document.createElement("span");
        count.style.opacity = "0.7";
        count.textContent = unspecced
            ? `${ev.assets.length} slots — unspecced`
            : `${ev.assets.length} assets · ${refCount} refs`;
        head.appendChild(title);
        head.appendChild(count);
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
                // Month dropdown filled from the project folder's orders/.
                wireMonthPicker(this);

                const container = document.createElement("div");
                container.style.cssText =
                    "max-height:280px;overflow-y:auto;padding:2px;";
                stopWheel(container);
                this._symbioticaBrowser = container;
                renderBrowser(container, undefined);
                this.addDOMWidget("events_browser", "custom", container,
                                  { serialize: false, hideOnZoom: true });
                this.size[0] = Math.max(this.size[0], 320);
            };
        }

        if (nodeData.name === "SymbioticaOrderSpecs") {
            const orig = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                orig?.apply(this, arguments);
                wireOrderSpecs(this);
            };
        }

        if (nodeData.name === "SymbioticaAutoPacker") {
            const orig = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                orig?.apply(this, arguments);
                // "All" + the categories of the upstream Order Specs' event.
                comboify(this, "category", () => eventCategoriesFor(this));
                // The Assets panel drives the hidden `overrides` widget.
                const ovW = widgetOf(this, "overrides");
                if (ovW) { ovW.hidden = true; ovW.computeSize = () => [0, -4]; }
                assetsPanel(this);
            };
            const origCfg = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function () {
                origCfg?.apply(this, arguments);
                // Migrate pre-v2.40 workflows: the packer's layout widgets
                // moved to the Model Preset node, so old widgets_values map
                // positionally onto [category, overrides] — category gets the
                // old `columns` int, overrides the old `max_rows`. Real
                // categories are never bare numbers and overrides must be a
                // JSON object; anything else is remap debris → reset it.
                const catW = widgetOf(this, "category");
                if (catW && /^\d+$/.test(String(catW.value).trim())) {
                    catW.value = "All";
                }
                const ovW = widgetOf(this, "overrides");
                if (ovW) {
                    try {
                        const v = JSON.parse(ovW.value || "{}");
                        if (typeof v !== "object" || v === null) throw 0;
                    } catch { ovW.value = "{}"; }
                }
                queueMicrotask(() => this._symRenderAssets?.());
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
                    const ev = pickedEventFor(this);
                    return ev ? templateGroups(ev).map((g) => g.template) : [];
                });
            };
        }

        if (nodeData.name === "SymbioticaTemplateEditor") {
            const orig = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                orig?.apply(this, arguments);
                // The editor reads the order itself: project folder + month.
                wireMonthPicker(this);
                comboify(this, "group", () => {
                    const ev = pickedEventFor(this);
                    return ev ? templateGroups(ev).map((g) => g.template) : [];
                });
                setupTemplateEditor(this);
                // The node face is the editor button, nothing else. Every
                // config/state input (project, month, presets, editor-managed
                // regions/sheet/prompt…) stays on the node but hidden, so its
                // value still serializes into the workflow and reaches the
                // Python execute() — the editor owns all of them from inside.
                // The button (a native "button" widget) is the one we keep.
                for (const w of this.widgets ?? []) {
                    if (w.type !== "button") w.hidden = true;
                }
                // Initial size was computed with the widgets visible (core sizes
                // before onNodeCreated); re-fit now that only the button shows.
                this.setSize(this.computeSize());
            };
            const origLoaded = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function () {
                origLoaded?.apply(this, arguments);
                // Workflow load: re-list a previously picked folder.
                queueMicrotask(() => this._symbioticaEditor?.restore());
            };
        }
    },
});
// --- template editor wiring ----------------------------------------------------
async function fetchJson(route) {
    const res = await api.fetchApi(route);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? res.statusText);
    return res.json();
}

function widgetOf(node, name) {
    return node?.widgets?.find((w) => w.name === name);
}

function parseJsonWidget(node, name, fallback) {
    try {
        const parsed = JSON.parse(widgetOf(node, name)?.value || "");
        return parsed ?? fallback;
    } catch {
        return fallback;
    }
}

function upstreamOrderRead(node) {
    // Editor -> (events) OrderRead directly, or -> (spec) EventSpecs ->
    // (events) OrderRead. By widgets, not cache.
    let cur = node;
    for (let hop = 0; hop < 4 && cur; hop++) {
        if (cur.comfyClass === "SymbioticaOrderRead") return cur;
        cur = upstreamNode(cur, "events") || upstreamNode(cur, "spec");
    }
    return null;
}

async function taskDataFor(node) {
    // Parse the order server-side from the upstream Order Read's widgets, so
    // the editor works without queueing first. The route resolves project +
    // month (or explicit order/refs paths) and returns the roots it used.
    // The node reads the order itself from its own project_path + month; a
    // legacy upstream Order Read still works as a fallback.
    const q = new URLSearchParams();
    let project = widgetOf(node, "project_path")?.value?.trim();
    let month = widgetOf(node, "month")?.value?.trim();
    if (project) {
        if (project) q.set("project", project);
        if (month) q.set("month", month);
    } else {
        const orderNode = upstreamOrderRead(node);
        if (orderNode) {
            project = widgetOf(orderNode, "project_path")?.value?.trim();
            month = widgetOf(orderNode, "month")?.value?.trim();
            if (project) q.set("project", project);
            if (month) q.set("month", month);
        }
    }
    let refsRoot = "";
    let assetsRoot = "";
    let events = null;
    if ([...q.keys()].length) {
        try {
            const data = await fetchJson(`/symbiotica/parse-order?${q}`);
            events = data.events;
            refsRoot = data.refsRoot ?? "";
            assetsRoot = data.assetsRoot ?? "";
        } catch (e) {
            console.warn("[symbiotica] parse-order failed:", e.message);
        }
    }
    if (!events) {
        const cached = orderDataFor(node);
        events = cached?.events ?? [];
        refsRoot = refsRoot || cached?.refsRoot || "";
        assetsRoot = assetsRoot || cached?.assetsRoot || "";
    }
    // The editor picks its own event (its `feature` widget, set by the in-
    // editor Event selector); fall back to an upstream Event Specs feature,
    // then the first event of the order.
    const ownFeature = widgetOf(node, "feature")?.value?.trim();
    const specFeature = upstreamNode(node, "spec")?.widgets
        ?.find((w) => w.name === "feature")?.value;
    const feature = ownFeature || specFeature || events[0]?.feature || "";
    const ev = events.find((e) => e.feature === feature) || events[0];
    const taskAssets = (ev?.assets ?? []).filter((a) => a.assetName).map((a) => ({
        assetName: a.assetName,
        category: a.category,
        canvas: a.canvas,
        prompt: a.prompt,
        refFiles: a.refFiles ?? [],
    }));
    return { taskAssets, refsRoot, assetsRoot, events,
             feature: ev?.feature ?? feature };
}

async function openEditorForNode(node, uiState) {
    const { taskAssets, refsRoot, assetsRoot, events, feature } = await taskDataFor(node);
    // One path in: the sprite catalog is the project's reference-assets/,
    // derived from project_path — no separate folder field.
    const root = assetsRoot || "";
    let handle = null;

    const opts = {
        api,
        init: {
            regions: parseJsonWidget(node, "regions_json", []),
            scenePrompt: widgetOf(node, "scene_prompt")?.value ?? "",
            root,
            // Open with whatever catalog we already have; a fresh open loads it
            // below AFTER the overlay is up, so the button never hangs.
            images: uiState.imagesRoot === root ? (uiState.images ?? []) : [],
            taskAssets,
            refsRoot,
            events: events ?? [],
            feature: feature ?? "",
            project: widgetOf(node, "project_path")?.value ?? "",
            month: widgetOf(node, "month")?.value ?? "",
            selectedSheets: parseJsonWidget(node, "selected_sheets", []),
            loadedName: (widgetOf(node, "sheet_file")?.value ?? "")
                .split("/").pop()?.replace(/\.png$/, "") ?? "",
        },
        // The in-editor Event selector persists its choice on the node, so a
        // queued run (and the next open) build the same event.
        onEventChange: (feat) => {
            const w = widgetOf(node, "feature");
            if (w) w.value = feat;
        },
        // The editor's saved-sheet ticks persist to the node so the 'sheets'
        // output emits them on a queued run.
        onSelectedSheets: (files) => {
            const w = widgetOf(node, "selected_sheets");
            if (w) w.value = JSON.stringify(files);
        },
        // Project/month set from inside the editor: persist on the node, then
        // reopen so the catalog, refs, and event list all reload cleanly.
        listMonths: async (project) => {
            if (!project?.trim()) return [];
            try {
                return ((await fetchJson("/symbiotica/list-orders?project="
                    + encodeURIComponent(project.trim()))).months ?? [])
                    .map((m) => m.label);
            } catch { return []; }
        },
        reloadProject: async (project, month) => {
            const pw = widgetOf(node, "project_path");
            if (pw) pw.value = project;
            const mw = widgetOf(node, "month");
            if (mw) mw.value = month;
            uiState.imagesRoot = null;
            uiState.images = [];
            handle?.close?.();
            await openEditorForNode(node, uiState);
        },
        imageUrl: (r, rel) => thumbUrl(r, rel),
        refImageUrl: (file) => (refsRoot ? thumbUrl(refsRoot, file) : null),
        // A saved sheet ("templates/<name>.png") served from the output dir,
        // for the editor's saved-sheets thumbnail grid. Uses the pack's own
        // /symbiotica route (served at server root, hence the /api strip) rather
        // than /view?type=output: behind the Modal canvas proxy an output view
        // is routed to the GPU sandbox and stubbed empty, blanking the grid.
        sheetThumbUrl: (file) => {
            if (!file) return "";
            return api.apiURL(
                `/symbiotica/template-image?file=${encodeURIComponent(file)}`
            ); // /api/-prefixed so the Modal gateway (proxies /api/* only) serves it
        },
        resolveMemberUrl: (region, member) => {
            // Which image fills a member cell depends on the reference mode:
            // Project reference -> the assigned game asset; Task reference ->
            // the CHECKED task refs. Returns {url, flip}: whenever ONE
            // effective image fills a two-cell region, the second cell mirrors
            // it (the in-game pair convention) — regardless of whether the
            // region was born single-ref or the user narrowed it to one.
            const mode = handle?.state?.refMode ?? "task";
            const members = region.members ?? [];
            const i = Math.max(0, members.indexOf(member));
            const pairFlip = members.length === 2 && i === 1;
            const projectRels = region.projectPaths ?? [];

            if (mode === "project" && projectRels.length && root) {
                if (projectRels.length === 1) {
                    return { url: thumbUrl(root, projectRels[0]), flip: pairFlip };
                }
                // One picked sprite per cell, in click order. Explicit per-cell
                // picks are final art (often pre-mirrored pairs): never apply
                // the baked pair flip on top.
                const rel = projectRels[Math.min(i, projectRels.length - 1)];
                return { url: thumbUrl(root, rel), flip: false };
            }
            const paths = region.taskRefs?.paths;
            if (paths?.length && refsRoot) {
                if (paths.length === 1) {
                    const file = paths[0].split("/").pop();
                    return { url: thumbUrl(refsRoot, file), flip: pairFlip };
                }
                // Multiple checked refs are explicit per-cell art — no baked flip.
                const file = paths[Math.min(i, paths.length - 1)].split("/").pop();
                return { url: thumbUrl(refsRoot, file), flip: false };
            }
            if (member.spriteId && refsRoot) {
                return { url: thumbUrl(refsRoot, member.spriteId.split("/").pop()),
                         flip: Boolean(member.flipX) };
            }
            if (projectRels.length && root) {
                const rel = projectRels[Math.min(i, projectRels.length - 1)];
                return { url: thumbUrl(root, rel),
                         flip: projectRels.length === 1 ? pairFlip : Boolean(member.flipX) };
            }
            return null;
        },
        loadAssets: (dir) => fetchJson(`/symbiotica/list-assets?dir=${encodeURIComponent(dir)}`),
        listSaved: async () => (await fetchJson("/symbiotica/template-list")).templates ?? [],
        deleteTemplate: async (file) => {
            const res = await api.fetchApi("/symbiotica/template-delete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ file }),
            });
            if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? "delete failed");
            return res.json();
        },
        // refMode: "project" (default) exports the base sheet — assigned game
        // art, client refs where unassigned. "task" exports the client refs
        // laid out, the task-sheet-only deliverable (no project reference).
        // bindNode=false skips pointing the node's sheet_file at this save,
        // so a batch ("Save all types") writes many sheets without hijacking
        // which one the node loads.
        saveTemplate: async (name, { refMode = "project", bindNode = true } = {}) => {
            const state = handle.state;
            const finalName = (name || state.loadedName || "template").trim();
            const prevMode = state.refMode;
            state.refMode = refMode;
            let png;
            try {
                png = await handle.exportSheet();
            } finally {
                state.refMode = prevMode;
                state.emit("regions"); // restore the on-screen preview
            }
            const resp = await api.fetchApi("/symbiotica/template-save", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    name: finalName,
                    png,
                    regions: state.regions,
                    settings: state.settings,
                    size: { w: state.sheetW, h: state.sheetH },
                    scenePrompt: state.scenePrompt,
                }),
            });
            const data = await resp.json();
            if (!resp.ok || !data.ok) throw new Error(data.error ?? "save failed");
            if (bindNode) {
                const sheetW = widgetOf(node, "sheet_file");
                if (sheetW) sheetW.value = data.file;
                const regionsW = widgetOf(node, "regions_json");
                if (regionsW) regionsW.value = JSON.stringify(state.regions);
                const sceneW = widgetOf(node, "scene_prompt");
                if (sceneW) sceneW.value = state.scenePrompt;
            }
            uiState.refreshGallery?.();
            return { name: data.name, file: data.file };
        },
        onClose: (state) => {
            // Persist in-progress edits on the node even without a save.
            const regionsW = widgetOf(node, "regions_json");
            if (regionsW) regionsW.value = JSON.stringify(state.regions);
            const sceneW = widgetOf(node, "scene_prompt");
            if (sceneW) sceneW.value = state.scenePrompt;
            uiState.render?.();
        },
    };
    handle = openTemplateEditor(opts);
    // The overlay is up — now load the sprite catalog (a big folder off a FUSE
    // Volume, slow) and refresh the asset tree when it lands. On a fresh open the
    // rail shows "loading…" until then instead of the whole editor hanging.
    if (root && uiState.imagesRoot !== root) {
        handle.state.assetsLoading = true;
        opts.rerenderRail?.();
        fetchJson(`/symbiotica/list-assets?dir=${encodeURIComponent(root)}`)
            .then((data) => {
                uiState.images = data.images ?? [];
                uiState.imagesRoot = root;
                handle.state.images = uiState.images;
            })
            .catch(() => { /* tree keeps the set-folder hint */ })
            .finally(() => {
                handle.state.assetsLoading = false;
                opts.rerenderRail?.();
            });
    }
    return handle;
}

function stopWheel(elem) {
    // Scrollable node panels: keep the wheel for the panel's own scroll —
    // without this LiteGraph zooms the whole graph canvas instead.
    elem.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });
}

function setupTemplateEditor(node) {
    // openEditorForNode caches the loaded sprite catalog across opens.
    const uiState = { images: [], imagesRoot: null };

    // Everything the editor needs — project, month, saved-sheet picking,
    // presets — lives inside the editor now. onConfigure still calls restore();
    // there is nothing on the node face to re-list, so it is a no-op.
    node._symbioticaEditor = { restore() {} };
    uiState.render = () => {};

    // A native LiteGraph button, NOT a DOM widget: a DOM widget's element
    // mis-sizes when the node is part of a multi-select drag (it grows wide and
    // never resets on resize). Native buttons are canvas-drawn, so LiteGraph
    // owns their width and that bug can't happen. This node needs only the one.
    const btn = node.addWidget("button", "Template Editor", null,
                               () => openEditorForNode(node, uiState));
    btn.serialize = false;
    node.size[0] = Math.max(node.size[0], 240);
}
