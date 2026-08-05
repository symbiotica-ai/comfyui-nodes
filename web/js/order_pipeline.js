// ABOUTME: Frontend for the Symbiotica order pipeline nodes — dynamic event and
// ABOUTME: group combos fed by server pushes, events browser, and the template editor.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { openTemplateEditor } from "./template_editor/editor.js";
import { createOrderCache } from "./order_cache.js";
import { HUB, injectHubStyles, ghostButtonCss } from "./hub_theme.js";
import { registerSymbioticaExtension } from "./register.js";

// node.id -> {events, refFileCount, refsRoot} (last parse per Order Read node)
const orderCache = new Map();

// Order parses are requested from render paths — the Auto Packer's assets panel
// and the category combo, which LiteGraph re-evaluates on every repaint — so the
// same order would otherwise be re-fetched for every frame. Keyed on the request
// route, which already carries project + month.
const orderParses = createOrderCache({ fetcher: (route) => fetchJson(route) });

// One shared empty list, so "no events" compares identical across calls and a
// node can tell a repeat answer from a new one.
const NO_EVENTS = [];

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
// Canvas-level notice. Saving a template piggybacks on a normal queue of the
// WHOLE graph, so it fails for reasons that have nothing to do with the packer
// (a missing model three nodes away, no output node). Those failures used to go
// to console.error only, which reads as "the button does nothing".
function toast(severity, summary, detail) {
    try {
        app.extensionManager.toast.add({ severity, summary, detail, life: 6000 });
    } catch {
        console[severity === "error" ? "error" : "log"](
            `[symbiotica] ${summary}: ${detail}`);
    }
}

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

// Reverse-map a saved template's preset/settings dicts back onto the Auto
// Packer's WIRED Model Preset / Settings nodes, so selecting a template makes
// those nodes SHOW (and pack with) the values it was saved with. A no-op when
// the packer has no such node wired — then the template dict drives at execute.
function setNodeWidget(node, name, val) {
    const w = node?.widgets?.find((x) => x.name === name);
    if (w && val !== undefined && val !== null) w.value = val;
}
const _CAP_LABEL = { 2: "2x", 3: "3x", 4: "4x", 6: "6x", 8: "8x" };
function applyPresetToNode(packer, preset) {
    if (!preset) return;
    const n = upstreamNode(packer, "preset");
    if (n?.comfyClass !== "SymbioticaModelPreset") return;
    setNodeWidget(n, "preset_model", preset.model);
    setNodeWidget(n, "resolution", preset.tier);
    setNodeWidget(n, "aspect_ratio", preset.ar);
    setNodeWidget(n, "columns", preset.columns);
    setNodeWidget(n, "max_rows_per_sheet", preset.max_rows);
    setNodeWidget(n, "background", preset.background);
    n.setDirtyCanvas?.(true, true);
}
function applySettingsToNode(packer, s) {
    if (!s) return;
    const n = upstreamNode(packer, "settings");
    if (n?.comfyClass !== "SymbioticaAutoPackerSettings") return;
    setNodeWidget(n, "scale_target",
                  s.fit_width ? "fit width"
                  : (!s.scale_target ? "off" : String(s.scale_target)));
    setNodeWidget(n, "scale_max", _CAP_LABEL[s.scale_max] ?? "3x");
    setNodeWidget(n, "algorithm", s.algorithm);
    setNodeWidget(n, "distribute_by_folder", s.distribute_by_folder);
    setNodeWidget(n, "padding", s.padding);
    setNodeWidget(n, "border", s.border);
    setNodeWidget(n, "combined_sheet", s.combined_sheet);
    setNodeWidget(n, "split_variants", s.split_variants);
    setNodeWidget(n, "max_refs", s.max_refs == null ? "all" : String(s.max_refs));
    n.setDirtyCanvas?.(true, true);
}

// Resolve project_path even when it is a WIRED input (a Local/Modal switch, a
// String literal, a chain of them). The combos and the thumbnail route's root
// registration both need the actual path string, which the widget alone can't
// give once the socket is wired.
export function resolveProjectPath(node) {
    const v = widgetOf(node, "project_path")?.value?.trim?.();
    if (v) return v;
    return inputString(node, "project_path", new Set());
}

// A typed project_path is authoritative — the user entered it in the widget. A
// wired one is resolved by a best-effort graph walk, so it must never auto-pick
// a render-feeding widget (month, feature): a wrong-branch guess would reach the
// queued render, where Python silently falls back to the first month/event.
function projectPathTyped(node) {
    return !!widgetOf(node, "project_path")?.value?.trim?.();
}

export function inputString(node, inputName, seen) {
    const input = node?.inputs?.find((i) => i.name === inputName);
    if (!input || input.link == null) return "";
    const link = app.graph.links[input.link];
    const origin = link && app.graph.getNodeById(link.origin_id);
    return nodeOutputString(origin, seen);
}

// The string a node's output carries, resolved statically from the graph: a
// switch node (on_true/on_false + a `switch` widget) follows its selected
// branch; a literal/primitive yields its string widget; a lone-input passthrough
// (a Reroute) follows its wire. A node with several wired inputs that we can't
// read as a switch is an ambiguous selector — we refuse to guess a branch, since
// the wrong one silently feeds a wrong project. `seen` guards against a cycle.
function nodeOutputString(node, seen) {
    if (!node || seen.has(node.id)) return "";
    seen.add(node.id);
    const isSwitch = node.inputs?.some((i) => i.name === "on_true")
                  && node.inputs?.some((i) => i.name === "on_false");
    if (isSwitch) {
        const sw = node.widgets?.find((w) => w.name === "switch");
        return inputString(node, sw?.value ? "on_true" : "on_false", seen);
    }
    const strW = node.widgets?.find(
        (w) => typeof w.value === "string" && w.value.trim());
    if (strW) return strW.value.trim();
    const wired = (node.inputs ?? []).filter((i) => i.link != null);
    if (wired.length === 1) return inputString(node, wired[0].name, seen);
    return "";
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
        const project = resolveProjectPath(node);
        if (!project) { node._symMonths = []; return; }
        try {
            const data = await fetchJson(
                "/symbiotica/list-orders?project=" + encodeURIComponent(project));
            node._symMonths = (data.months ?? []).map((m) => m.label);
            // A wired path populates the dropdown but never re-picks the month —
            // only a typed project_path is authoritative enough for that.
            const monthW = widgetOf(node, "month");
            if (projectPathTyped(node) && monthW
                && !node._symMonths.includes(monthW.value)) {
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
    node._symRefreshMonths = refresh; // the Read-folder button calls this
    refresh();
}

// Order Specs is a leaf picker (no upstream): it reads its own project + month.
// Parse the order server-side and cache the events on the node, so its own
// `feature` combo and a downstream Auto Packer's `category` combo can read the
// event list synchronously.
// `explicit` marks a deliberate request — the node being wired, or the user
// editing project/month/feature. Those re-ask the server even for inputs that
// failed before, so a path that starts working again can be picked up without a
// page reload. The opportunistic callers below (a panel rendering, a combo being
// painted) always take the cached answer.
async function refreshOrderSpecs(node, { explicit = false } = {}) {
    const project = resolveProjectPath(node);
    const month = widgetOf(node, "month")?.value?.trim();
    if (!project) { publishOrder(node, null, NO_EVENTS, ""); return; }
    const q = new URLSearchParams({ project });
    if (month) q.set("month", month);
    const route = `/symbiotica/parse-order?${q}`;
    if (explicit) orderParses.invalidate(route);
    const result = await orderParses.get(route);
    publishOrder(node, result,
                 (result.ok && result.data.events) || NO_EVENTS,
                 (result.ok && result.data.refsRoot) || "");
}

// Put a parse result on the node, then re-render downstream ONLY if the answer
// differs from the one the node already holds.
//
// That guard is what bounds the work. Both the Auto Packer's assets panel and
// its `category` combo ask for the order while they render, and re-rendering
// them — or marking the canvas dirty, which schedules the repaint that paints
// the combo — calls straight back into here. Repeating the same answer means
// repeating it forever: with a stale project path that was a request per round
// trip per packer, and without the round trip to throttle it, an unbroken
// recursion.
function publishOrder(node, result, events, refsRoot) {
    node._symEvents = events;
    node._symRefsRoot = refsRoot;
    // Keep the feature value valid (accept the plain feature OR the labelled
    // form); empty means "the order's first event". Never reset a value that
    // still matches an event by key — that would clobber a saved workflow.
    // `result` is null when there is no project to parse: nothing was asked, so
    // nothing says the current pick is wrong, and clearing the path to type a
    // new one must not throw the pick away. Only a typed project_path re-picks:
    // a wired resolution is a graph-walk guess and must not overwrite feature.
    const featW = widgetOf(node, "feature");
    if (projectPathTyped(node) && result !== null && featW && featW.value) {
        const key = featureKey(featW.value);
        if (!events.some((e) => e.feature === key)) {
            featW.value = events[0] ? eventLabel(events[0]) : "";
        }
    }
    // The cache hands back one object per set of inputs, so identity answers
    // "is this the same order I already published?" exactly. `feature` rides
    // along because picking a different event has to re-render the packers even
    // though the order behind it never changed.
    const feature = featW?.value ?? "";
    const last = node._symPublished;
    node._symPublished = { result, events, feature };
    if (last && last.result === result && last.events === events
        && last.feature === feature) return;
    // Re-render any downstream Auto Packer asset panels now that the event's
    // assets (and refsRoot) are known.
    for (const ap of downstreamNodes(node, "SymbioticaAutoPacker")) {
        ap._symRenderAssets?.();
    }
    // And tell everything else that reads an order it has changed. Announced to
    // the whole graph rather than to the nodes one hop down: the order wire
    // commonly runs through a reroute, and a panel that follows the wire up
    // six hops to find its source cannot be found by looking one hop down.
    // Each listener decides for itself whether THIS node is its source, which
    // keeps the knowledge of what counts as one in the module that already has
    // it. LiteGraph gives no event for "a widget upstream changed", so without
    // this a downstream panel keeps showing the previous event until something
    // else happens to re-render it.
    for (const other of app.graph?._nodes ?? []) {
        if (other !== node) other._symOrderChanged?.(node);
    }
    node.setDirtyCanvas?.(true, true);
}

function wireOrderSpecs(node) {
    node._symEvents = [];
    // Parsing on demand, the way `_symRefreshMonths` exposes the month parse.
    // A panel downstream that needs the event list has no other way to ask for
    // it: the Auto Packer reaches `refreshOrderSpecs` because it lives in this
    // module, and nothing outside it does.
    node._symRefreshOrder = (opts) => refreshOrderSpecs(node, opts);
    wireMonthPicker(node); // month combo, refreshed on project_path change
    comboify(node, "feature", () => (node._symEvents ?? []).map(eventLabel));
    // "Read folder" — resolve project_path (even a wired Local/Modal switch),
    // fill the month + feature dropdowns, and hit parse-order so the server
    // registers the refs root (that is what lets the Auto Packer thumbnails
    // load). No need to wire + queue a packer just to populate the pickers.
    //
    // A NATIVE litegraph button (like the Studio Library's "Browse" button):
    // it renders in both UIs and — unlike a DOM widget — is never hidden below
    // the zoom threshold, so it can't come up missing on a fresh Comfy start.
    let reading = false;
    const readBtn = node.addWidget("button", "📁 Read folder", null, async () => {
        if (reading) return;
        reading = true;
        readBtn.name = "⏳ Reading…";
        node.setDirtyCanvas?.(true, true);
        try {
            await node._symRefreshMonths?.();
            await refreshOrderSpecs(node, { explicit: true });
        } finally {
            reading = false;
            readBtn.name = "📁 Read folder";
            node.setDirtyCanvas?.(true, true);
        }
    });
    readBtn.serialize = false;
    // Re-parse whenever project OR month changes (chains onto wireMonthPicker's
    // own project_path hook — both fire). `feature` too, so a downstream Auto
    // Packer panel re-renders for the newly picked event.
    for (const name of ["project_path", "month", "feature"]) {
        const w = widgetOf(node, name);
        if (!w) continue;
        const prev = w.callback;
        w.callback = function () {
            const r = prev?.apply(this, arguments);
            refreshOrderSpecs(node, { explicit: true });
            return r;
        };
    }
    // Fire now, and — only if the project could not be resolved yet — once more
    // after the graph settles: on load a wired project_path (a Local/Modal
    // switch) is not resolvable until the links are restored, so this deferred
    // pass populates the month + feature dropdowns and registers the refs root
    // without needing the button. When the project already resolved, the settled
    // parse stands — re-asking would reopen a cached failure and reflood.
    refreshOrderSpecs(node, { explicit: true });
    if (!resolveProjectPath(node)) {
        setTimeout(() => {
            node._symRefreshMonths?.();
            refreshOrderSpecs(node, { explicit: true });
        }, 400);
    }
}

// The Auto Packer's asset source: its upstream Order Specs (wired on `order`),
// OR a Template Library (wired on `template`, carrying a frozen order). Both
// stash the picked event on _symEvents / _symRefsRoot — Order Specs picks by
// its `feature` widget; the Library exposes exactly the selected template's one
// event. Opportunistically re-parses an Order Specs whose cache is still empty.
// When both are wired, `order` (the live pick) wins.
function assetSourceFor(node) {
    const specs = upstreamNode(node, "order");
    if (specs?.comfyClass === "SymbioticaOrderSpecs") {
        const events = specs._symEvents ?? [];
        if (!events.length) refreshOrderSpecs(specs);
        const feature = featureKey(widgetOf(specs, "feature")?.value);
        const ev = events.find((e) => e.feature === feature) || events[0] || null;
        return { event: ev, refsRoot: specs._symRefsRoot ?? "" };
    }
    // A Reference Browser feeds the same `order` wire from the asset library.
    // It publishes its picks in the event shape (see reference_browser.js), so
    // the Assets panel, the category combo, and the per-asset hide/reorder all
    // work on library rows exactly as they do on an order's.
    if (specs?.comfyClass === "SymbioticaReferenceBrowser") {
        return { event: specs._symPickedEvent ?? null,
                 refsRoot: specs._symRefsRoot ?? "" };
    }
    const lib = upstreamNode(node, "template");
    if (lib?.comfyClass === "SymbioticaTemplateLibrary") {
        return { event: (lib._symEvents ?? [])[0] || null,
                 refsRoot: lib._symRefsRoot ?? "" };
    }
    return { event: null, refsRoot: "" };
}

// The categories of that source's picked event (named assets only), for the
// Auto Packer's `category` combo.
function eventCategoriesFor(node) {
    const { event: ev } = assetSourceFor(node);
    if (!ev) return ["All"];
    const cats = [...new Set(
        ev.assets.filter((a) => a.assetName).map((a) => a.category))]
        .sort((a, b) => a.localeCompare(b));
    return ["All", ...cats];
}

// The picked event's assets + refsRoot for an Auto Packer, filtered to the
// node's chosen `category` (All = every type). Empty when no source is wired.
function eventAssetsFor(node) {
    const { event: ev, refsRoot } = assetSourceFor(node);
    const cat = widgetOf(node, "category")?.value?.trim() || "All";
    const assets = (ev?.assets ?? []).filter(
        (a) => a.assetName && (cat === "All" || a.category === cat));
    return { assets, refsRoot };
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

    // The outer container is the scroll VIEWPORT: ComfyUI sets its height from
    // computeSize below. Rows live in an inner `list` whose natural height IS the
    // content height. Measure the LIST, never the container: the container fills
    // its allocated box, so container.scrollHeight just echoes the box height and
    // feeds the size back into itself, running the node off the canvas.
    // box-sizing/width:100%/overflow-x:hidden keep the panel inside the node
    // width; the flex children get min-width:0 so long names ellipsis.
    const container = document.createElement("div");
    container.style.cssText = "box-sizing:border-box;width:100%;"
        + "overflow-y:auto;overflow-x:hidden;font-size:11px;";
    const list = document.createElement("div");
    list.style.cssText = "padding:2px 2px 4px;";
    container.appendChild(list);
    stopWheel(container);
    // Height fits the CONTENT (the selected event's asset rows) so the node
    // auto-grows to fit the assets and shrinks for a smaller category, capped so
    // a huge event scrolls instead of running off the canvas.
    const PANEL_MAX = 760;
    const panelHeight = () => {
        const h = list.scrollHeight;
        return Math.min(Math.max(h ? h + 8 : 44, 44), PANEL_MAX);
    };
    // The 1.4x frontend lays a DOM widget out from `computeLayoutSize`, which
    // reads these three and ignores `computeSize` — and a widget that declares
    // neither a height nor a maximum is never bounded, so the element paints
    // its whole content outside the node.
    const panelW = node.addDOMWidget("assets_panel", "sym_assets", container, {
        serialize: false, hideOnZoom: true,
        getMinHeight: () => 44,
        getMaxHeight: () => PANEL_MAX,
        getHeight: () => `${panelHeight()}px`,
    });
    panelW.computeSize = function (width) {
        return [width, panelHeight()];
    };
    // ComfyUI sizes the DOM wrapper from the node width on its own layout pass,
    // and that pass follows a WIDENING immediately but lags a SHRINK — it only
    // catches up when something else re-lays-out the node. Narrow a packer whose
    // panel has rows and nothing does, so the wrapper keeps the old width and the
    // rows visibly hang off the right edge of the node. Pin it ourselves instead
    // of waiting: the inset is a constant 20px at every width (320->300,
    // 325->305, 520->500, 600->580).
    const PANEL_INSET = 20;
    const syncPanelWidth = () => {
        const wrap = container.parentElement;
        if (!wrap) return;
        const want = Math.max(0, node.size[0] - PANEL_INSET);
        if (parseFloat(wrap.style.width) !== want) wrap.style.width = `${want}px`;
    };
    // Re-fit the node to the new content after each render (scrollHeight is only
    // valid once the rows are in the DOM).
    const refit = () => requestAnimationFrame(() => {
        node.setSize?.([node.size[0], node.computeSize()[1]]);
        syncPanelWidth();
        node.setDirtyCanvas?.(true, true);
    });
    // The dragged-edge case: onResize is the one signal that fires for a shrink.
    const prevResize = node.onResize;
    node.onResize = function () {
        prevResize?.apply(this, arguments);
        syncPanelWidth();
    };
    node.size[0] = Math.max(node.size[0], 320);

    const save = () => {
        if (ovW) ovW.value = JSON.stringify(state);
        node.setDirtyCanvas?.(true, true);
    };

    node._symRenderAssets = () => render();
    function render() {
        list.replaceChildren();
        // The asset source just changed (or first resolved) — so may the pool
        // the Save button writes to.
        node._symRefreshSaveLabel?.();
        const { assets, refsRoot } = eventAssetsFor(node);
        if (!assets.length) {
            list.textContent = "Wire an Order Specs (and pick an event), a "
                + "Reference Browser, or a Template Library.";
            list.style.opacity = ".6";
            refit();
            return;
        }
        list.style.opacity = "1";
        for (const a of assets) {
            const hidden = state.hidden.includes(a.assetName);
            const row = document.createElement("div");
            row.style.cssText = "display:flex;flex-direction:column;gap:3px;min-width:0;"
                + "border:1px solid #3a3a3a;border-radius:6px;padding:4px 5px;"
                + `margin:3px 0;background:${hidden ? "#241a1a" : "#2a2a2a"};`
                + `opacity:${hidden ? ".5" : "1"};`;
            // header: name + hide toggle
            const head = document.createElement("div");
            head.style.cssText = "display:flex;align-items:center;gap:6px;min-width:0;";
            const refs = a.refFiles ?? [];
            if (refs[0] && refsRoot) head.appendChild(symImg(thumbUrl(refsRoot, refs[0]), 18));
            const name = document.createElement("span");
            name.textContent = `${a.assetName} · ${a.canvas}`;
            name.style.cssText = "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
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
            list.appendChild(row);
        }
        refit();
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

// Ask for the template name. ComfyUI's own dialog (frontend 1.45+) rather than
// window.prompt(): Chrome permanently suppresses window.prompt in a tab once
// "prevent this page from creating additional dialogs" is armed, and it then
// returns null with nothing on screen — a dead Save button with no explanation.
//
// Returns the typed name, "" for an empty answer, or null when cancelled. If the
// frontend has no dialog service, window.prompt is tried, and if that is the
// suppressed one, the node's own `template name` field carries the answer.
async function askName(suggested) {
    const dialog = app.extensionManager?.dialog;
    if (typeof dialog?.prompt === "function") {
        const answer = await dialog.prompt({
            title: "Save as template",
            message: "Name this template:",
            defaultValue: suggested,
        });
        return answer == null ? null : String(answer).trim();
    }
    let answer;
    try {
        answer = window.prompt("Save this pack as a template named:", suggested);
    } catch {
        answer = undefined;
    }
    if (answer == null) return suggested ? suggested : null;
    return String(answer).trim();
}

// The API-format prompt reduced to `rootId` and everything it feeds from, plus
// a preview terminal so the run has an output node.
//
// Saving used to queue the WHOLE graph, which drags in everything DOWNSTREAM of
// the packer — image models, API nodes — none of which the pack needs. That
// made a save fail on unrelated errors (a missing checkpoint), pop ComfyUI's
// "Sign In Required to Use API Nodes" dialog when an API node was present, and
// pay for a full generation just to write a template. The ancestor closure
// keeps the order/preset/settings/library feeding this packer and nothing else.
function packOnlyPrompt(output, rootId) {
    const keep = new Set();
    const walk = (id) => {
        if (keep.has(id) || !output[id]) return;
        keep.add(id);
        for (const value of Object.values(output[id].inputs ?? {})) {
            // A wired input is [originNodeId, slot]; widgets are plain values.
            if (Array.isArray(value) && value.length === 2) walk(String(value[0]));
        }
    };
    walk(String(rootId));
    const pruned = {};
    for (const id of keep) pruned[id] = output[id];
    // The packer is not an output node, and a prompt with no outputs is
    // rejected before anything runs — so terminate the pruned graph with a
    // preview of the sheets being saved.
    pruned["symbiotica-save-preview"] = {
        class_type: "PreviewImage",
        inputs: { images: [String(rootId), 0] },
    };
    return pruned;
}

// The default template name: what is being packed (the order's event or the
// library folder) plus the picked category, slugified.
function suggestedName(node) {
    const { event: ev } = assetSourceFor(node);
    const cat = widgetOf(node, "category")?.value?.trim() || "All";
    return slugify([ev?.feature || "template", cat === "All" ? "" : cat]
        .filter(Boolean).join("-"));
}

// Which pool this packer's save writes to, read off its asset source — the same
// answer Python derives from the order's `source`, shown BEFORE the click so the
// destination is never a surprise:
//   Reference Browser -> "reference" (universal: <project>/templates/reference)
//   Order Specs       -> "order"     (that month: <...>/orders/<Month>/templates)
//   Template Library  -> whatever pool the template came from
// "" when nothing is wired yet (the button stays generic).
function packKindFor(node) {
    const specs = upstreamNode(node, "order");
    if (specs?.comfyClass === "SymbioticaReferenceBrowser") return "reference";
    if (specs?.comfyClass === "SymbioticaOrderSpecs") return "order";
    const lib = upstreamNode(node, "template");
    if (lib?.comfyClass === "SymbioticaTemplateLibrary") {
        const picked = String(widgetOf(lib, "kind")?.value ?? "").trim().toLowerCase();
        if (picked === "order" || picked === "reference") return picked;
        // kind "All": the pool is the selected template's own.
        const sel = widgetOf(lib, "selected")?.value ?? "";
        const t = (lib._symTemplates ?? []).find(
            (x) => sel === (x.key ?? x.name) || sel === x.name);
        return t?.kind || "";
    }
    return "";
}

const KIND_LABEL = { order: "order", reference: "reference" };

// "💾 Save as template" on the Auto Packer: takes the name from the node's own
// `save_as` field, queues once so Python writes the sheets + recipe to the
// project's templates/ folder, then clears the field so the next run does not
// re-save.
//
// The name used to come from window.prompt(). Chrome permanently suppresses
// dialogs in a tab once "prevent this page from creating additional dialogs" is
// ticked — prompt() then returns null with nothing on screen, so the button
// looked dead and no template was ever written. The field is on the node now:
// no dialog, and the name is visible before the click.
function wireSaveButton(node) {
    const saveW = widgetOf(node, "save_as");
    // Left EMPTY on purpose: a non-empty save_as makes Python save on any run,
    // so a prefilled field would write a template every time the graph is
    // queued. Empty + Save uses the suggested name instead.
    if (saveW) saveW.label = "template name (blank = auto)";
    // A native litegraph button (like Order Specs' Read-folder): renders in both
    // UIs and never hides at low zoom, unlike the DOM widget it replaces.
    let saving = false;
    // The label names the destination pool — a save from the Reference Browser
    // is universal, one from an order belongs to that month only.
    const idleLabel = () => {
        const kind = KIND_LABEL[packKindFor(node)];
        return kind ? `💾 Save as ${kind} template` : "💾 Save as template";
    };
    const btn = node.addWidget("button", idleLabel(), null, async () => {
        if (saving) return;
        const name = await askName(
            (saveW?.value ?? "").trim() || suggestedName(node));
        if (name === null) return;                 // cancelled
        if (!name) {
            toast("warn", "Name the template first",
                  "Give it a name in the dialog, or type one in this node's "
                  + "'template name' field.");
            return;
        }
        saving = true;
        btn.name = "⏳ Saving…";
        node.setDirtyCanvas?.(true, true);
        if (saveW) saveW.value = name;
        try {
            // Serialize NOW so save_as is captured, THEN clear + queue the
            // captured prompt. app.queuePrompt only serializes when no run is in
            // flight, so relying on it drops save_as under auto-queue or a long
            // downstream run. graphToPrompt snapshots the graph synchronously.
            const prompt = await app.graphToPrompt();
            if (saveW) saveW.value = "";
            await api.queuePrompt(0, {
                output: packOnlyPrompt(prompt.output, node.id),
                workflow: prompt.workflow,
            });
        } catch (err) {
            console.error("[symbiotica] template save queue failed", err);
            toast("error", "Template not saved",
                  `${err?.message ?? err} — saving queues the whole graph, so a `
                  + "node error anywhere in it (a missing model, no output node) "
                  + "blocks the save. Fix the run, then press Save again.");
        } finally {
            if (saveW) saveW.value = "";
            saving = false;
            btn.name = idleLabel();
            node.setDirtyCanvas?.(true, true);
        }
    });
    btn.serialize = false;
    // Keep the label honest as the graph is rewired (Reference Browser swapped
    // for an Order Specs, a Library's kind changed). The assets panel calls this
    // on every re-render, i.e. whenever an upstream publishes.
    node._symRefreshSaveLabel = () => {
        if (saving) return;
        const next = idleLabel();
        if (btn.name === next) return;
        btn.name = next;
        node.setDirtyCanvas?.(true, true);
    };
    const prevConnChange = node.onConnectionsChange;
    node.onConnectionsChange = function () {
        const r = prevConnChange?.apply(this, arguments);
        node._symRefreshSaveLabel();
        return r;
    };
}

// The Template Library node: a native "Browse" button (the Studio Library
// pattern — a DOM panel embedded in the node does not reliably render in the
// Vue UI) that opens a full-screen overlay listing the project's saved Auto
// Packer templates (checkbox · name · sheet count · thumbnails · use · delete).
// A hidden `selected` slug is the output; on "use" the node drives any
// downstream Auto Packer: exposes the template's frozen order as its one event
// (so the packer's Assets panel + category combo light up, via assetSourceFor)
// and preloads the packer's category + overrides widgets so a re-pack matches
// and stays editable. A disabled summary widget mirrors the current pick, and a
// thumbnail strip under the button shows the sheets of the templates in play.
function wireTemplateLibrary(node) {
    node._symEvents = [];
    node._symRefsRoot = "";
    node._symTemplates = [];
    const selW = widgetOf(node, "selected");
    if (selW) { selW.hidden = true; selW.computeSize = () => [0, -4]; }
    // Multi-select checkboxes: which templates' saved sheets/prompts to output.
    const chkW = widgetOf(node, "checked");
    if (chkW) { chkW.hidden = true; chkW.computeSize = () => [0, -4]; }
    const readChecked = () => {
        try { return new Set(JSON.parse(chkW?.value || "[]")); }
        catch { return new Set(); }
    };

    // Which pool this node browses. Reference templates are universal (built
    // from the game's asset library, valid for any order); order templates
    // belong to ONE month and live beside that month's order — so `month` only
    // matters for the order pool and hides for Reference.
    const KIND_VALUES = ["All", "Order", "Reference"];
    const kindW = comboify(node, "kind", () => KIND_VALUES)
        ?? widgetOf(node, "kind");
    if (kindW && !KIND_VALUES.includes(kindW.value)) kindW.value = "All";
    const kindOf = () => String(kindW?.value ?? "All").trim().toLowerCase();
    const kindParam = () => (kindOf() === "all" ? "" : kindOf());
    wireMonthPicker(node);   // month dropdown, filled from <project>/orders
    const monthW = widgetOf(node, "month");
    const monthOf = () => (widgetOf(node, "month")?.value?.trim()
                           || inputString(node, "month", new Set()));
    const syncMonthVisibility = () => {
        if (!monthW) return;
        const hide = kindOf() === "reference";
        monthW.hidden = hide;
        monthW.computeSize = hide ? () => [0, -4] : undefined;
    };

    // A template's id on the wire is kind-qualified ("reference/blossom-tower"),
    // so the same slug can exist in both pools. Workflows saved before the split
    // hold a bare slug — still matched, first pool wins (what Python does too).
    const idOf = (t) => t.key ?? t.name;
    // A bare slug is ambiguous once the same name lives in both pools, so bind
    // it to the FIRST listed row of that name — the one Python resolves it to.
    // Matching every pool would tick rows the queue never emits, and one untick
    // would then clear them all.
    const bareOwner = (name) => (node._symTemplates ?? []).find(
        (x) => x.name === name);
    const isId = (t, v) => !!v && (v === idOf(t)
                                   || (v === t.name && bareOwner(v) === t));
    const badgeOf = (t) => (t.kind === "reference" ? "ref"
                            : t.kind === "order" ? (t.month || "order") : "");

    // While the overlay is open this re-renders its rows; null when closed.
    let paneRender = null;

    const browseBtn = node.addWidget("button", "📂 Browse template library",
                                     null, () => openBrowser());
    browseBtn.serialize = false;
    const summary = node.addWidget("text", "library_summary", "", () => {});
    summary.disabled = true;
    summary.serialize = false;

    // A compact always-visible strip under the button: the sheet thumbnails of
    // the templates currently in play (the "use"d one plus every checked one),
    // so the node shows what it will output without opening the browser. Rows
    // live in an INNER div so computeSize can measure real content height
    // (measuring the scroll container itself feeds back and grows forever).
    const strip = document.createElement("div");
    strip.style.cssText = "box-sizing:border-box;width:100%;"
        + "overflow-y:auto;overflow-x:hidden;font-size:11px;";
    const stripList = document.createElement("div");
    stripList.style.cssText = "padding:2px 2px 4px;";
    strip.appendChild(stripList);
    stopWheel(strip);
    const stripW = node.addDOMWidget("library_thumbs", "sym_library_thumbs",
                                     strip, { serialize: false });
    const STRIP_MAX = 420;
    stripW.computeSize = function (width) {
        const h = stripList.scrollHeight;
        return [width, Math.min(Math.max(h ? h + 8 : 24, 24), STRIP_MAX)];
    };
    const refit = () => requestAnimationFrame(() => {
        node.setSize?.([node.size[0], node.computeSize()[1]]);
        node.setDirtyCanvas?.(true, true);
    });
    node.size[0] = Math.max(node.size[0], 340);

    const renderStrip = () => {
        stripList.replaceChildren();
        const checkedSet = readChecked();
        const shown = (node._symTemplates ?? []).filter(
            (t) => isId(t, selW?.value)
                || [...checkedSet].some((v) => isId(t, v)));
        if (!shown.length) {
            stripList.textContent = "No template in use — 📂 Browse to pick one.";
            stripList.style.opacity = ".6";
            refit();
            return;
        }
        stripList.style.opacity = "1";
        for (const t of shown) {
            const row = document.createElement("div");
            row.style.cssText = "margin:3px 0;min-width:0;";
            const head = document.createElement("div");
            head.style.cssText = "display:flex;align-items:center;gap:5px;"
                + "min-width:0;opacity:.75;font-size:10px;";
            const tag = document.createElement("span");
            const badge = badgeOf(t);
            tag.textContent = (isId(t, selW?.value) ? "✓ " : "▦ ") + t.name
                + (badge ? `  · ${badge}` : "");
            tag.style.cssText = "flex:1;min-width:0;overflow:hidden;"
                + "text-overflow:ellipsis;white-space:nowrap;";
            head.appendChild(tag);
            row.appendChild(head);
            const sheets = document.createElement("div");
            sheets.style.cssText = "display:flex;gap:4px;flex-wrap:wrap;"
                + "padding:2px 0 3px;";
            const paths = t.sheetPaths ?? [];
            if (!paths.length) {
                const none = document.createElement("span");
                none.textContent = "(no sheet images)";
                none.style.cssText = "opacity:.5;font-size:10px;";
                sheets.appendChild(none);
            }
            for (const p of paths) sheets.appendChild(symImg(localImageUrl(p), 54));
            row.appendChild(sheets);
            stripList.appendChild(row);
        }
        refit();
    };

    const refreshSummary = () => {
        const n = readChecked().size;
        const pool = kindOf() === "order" ? `order · ${monthOf() || "first month"}`
            : kindOf() === "reference" ? "reference" : "all pools";
        summary.value = (selW?.value ? `use: ${selW.value}` : "no template")
            + (n ? ` · out: ${n} ▦` : "") + ` · ${pool}`;
        renderStrip();
        node.setDirtyCanvas?.(true, true);
    };

    // Expose the selected template's frozen order as this node's one event so a
    // downstream Auto Packer's Assets panel + category combo light up
    // (assetSourceFor treats a Library like an Order Specs). Runs on EVERY
    // refresh/load — so it must NOT write the packer's category/overrides
    // widgets, or it would clobber the user's edits on reload and after a save.
    const exposeEvent = (tpl) => {
        const order = tpl?.order || {};
        node._symEvents = tpl ? [{
            feature: order.feature || "",
            eventName: order.eventName || "",
            assets: order.assets || [],
        }] : [];
        node._symRefsRoot = order.refsRoot || "";
        for (const ap of downstreamNodes(node, "SymbioticaAutoPacker")) {
            ap._symRenderAssets?.();
        }
        node.setDirtyCanvas?.(true, true);
    };

    // Prime a downstream packer's category + overrides FROM the template — only
    // on an explicit "use" click, so a re-pack matches the saved recipe. After
    // that the packer's own widgets are the source of truth (they survive
    // reloads/saves), matching resolve_pack_inputs' "widget wins" contract.
    const primePackers = (tpl) => {
        for (const ap of downstreamNodes(node, "SymbioticaAutoPacker")) {
            const catW = widgetOf(ap, "category");
            if (catW) catW.value = tpl?.category || "All";
            const ovW = widgetOf(ap, "overrides");
            if (ovW) ovW.value = JSON.stringify(tpl?.overrides || {});
            // Push the saved model preset + pack settings onto the packer's
            // wired Preset / Settings nodes so they show and drive the saved
            // values (a wired node otherwise overrides the template at execute).
            applyPresetToNode(ap, tpl?.preset);
            applySettingsToNode(ap, tpl?.settings);
        }
    };

    const select = (tpl) => {
        if (selW) selW.value = tpl ? idOf(tpl) : "";
        primePackers(tpl);
        exposeEvent(tpl); // relights + re-renders packers with the primed values
        refreshSummary();
        paneRender?.();
    };

    const doDelete = async (tpl) => {
        const project = resolveProjectPath(node) || "";
        try {
            // The qualified id keeps the delete inside one pool — removing an
            // order template must not take the same-named reference one.
            await postJson("/symbiotica/pack-template-delete",
                           { project, name: idOf(tpl), kind: tpl.kind ?? "",
                             month: tpl.month ?? monthOf() });
        } catch (err) { console.error("[symbiotica] delete failed", err); }
        if (isId(tpl, selW?.value)) { selW.value = ""; exposeEvent(null); }
        await refresh();
    };

    const refresh = async () => {
        // Fetch even with an empty project — the route also lists
        // output/templates (fallback saves live there).
        const project = resolveProjectPath(node) || "";
        const q = new URLSearchParams({ project });
        if (kindParam()) q.set("kind", kindParam());
        // The reference pool is month-free by design — sending a month there
        // would suggest it scopes something.
        if (monthOf() && kindOf() !== "reference") q.set("month", monthOf());
        try {
            const data = await fetchJson("/symbiotica/pack-template-list?" + q);
            node._symTemplates = data.templates ?? [];
            node._symTemplateDir = data.dir ?? "";
        } catch { node._symTemplates = []; }
        // Re-expose the selected template's event — its data may only arrive now
        // — WITHOUT re-priming the packer's widgets (those are the user's now).
        const cur = node._symTemplates.find((t) => isId(t, selW?.value));
        if (cur) exposeEvent(cur);
        syncMonthVisibility();
        refreshSummary();
        paneRender?.();
    };
    node._symRefreshTemplates = refresh;

    // Switching pool (or month) re-lists — and a downstream packer's Save button
    // names the new pool.
    for (const name of ["kind", "month", "project_path"]) {
        const w = widgetOf(node, name);
        if (!w) continue;
        const prev = w.callback;
        w.callback = function () {
            const r = prev?.apply(this, arguments);
            refresh();
            for (const ap of downstreamNodes(node, "SymbioticaAutoPacker")) {
                ap._symRefreshSaveLabel?.();
            }
            return r;
        };
    }
    syncMonthVisibility();

    // The overlay browser — the Studio Library's modal chrome (centered panel
    // over a dimmed backdrop; Done/✕, Escape, and backdrop click all close),
    // listing this node's templates instead of a directory tree.
    function openBrowser() {
        injectHubStyles();

        const overlay = document.createElement("div");
        overlay.className = "symbiotica-template-library";
        overlay.style.cssText =
            "position:fixed;inset:0;z-index:10000;background:rgba(1,1,2,.66);" +
            "display:flex;align-items:center;justify-content:center;";
        const panel = document.createElement("div");
        panel.style.cssText =
            `width:min(80vw,1000px);height:80vh;background:${HUB.surface2};color:${HUB.ink};` +
            `font:13px/1.5 ${HUB.font};display:flex;flex-direction:column;` +
            `border:1px solid ${HUB.hairline};border-radius:12px;overflow:hidden;` +
            "box-shadow:0 16px 48px rgba(0,0,0,.55);";

        const bar = document.createElement("div");
        bar.style.cssText =
            `display:flex;align-items:center;gap:10px;padding:12px 16px;` +
            `border-bottom:1px solid ${HUB.hairline};`;
        const crumb = document.createElement("div");
        crumb.style.cssText =
            `flex:1;font:12px ${HUB.mono};color:${HUB.inkSubtle};` +
            "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
        // The folder a save of this pool lands in — the answer to "where did my
        // template go?", which now depends on the kind AND the month.
        crumb.textContent = node._symTemplateDir
            || resolveProjectPath(node) || "output/templates";
        const closeBtn = document.createElement("button");
        closeBtn.textContent = "Done";
        closeBtn.className = "sym-btn";
        closeBtn.style.cssText = ghostButtonCss + "margin-left:auto;";
        bar.append(crumb, closeBtn);

        const pane = document.createElement("div");
        pane.style.cssText = "flex:1;overflow:auto;padding:8px;";

        panel.append(bar, pane);
        overlay.appendChild(panel);
        document.body.appendChild(overlay);

        function onKeydown(e) {
            if (e.key === "Escape") close();
        }
        const close = () => {
            paneRender = null;
            overlay.remove();
            document.removeEventListener("keydown", onKeydown);
        };
        document.addEventListener("keydown", onKeydown);
        closeBtn.addEventListener("click", close);
        overlay.addEventListener("click", (e) => {
            if (e.target === overlay) close();  // backdrop click, not the panel
        });

        const emptyState = (text) => {
            const d = document.createElement("div");
            d.style.cssText =
                `padding:28px 16px;text-align:center;color:${HUB.inkTertiary};font:13px ${HUB.font};`;
            d.textContent = text;
            return d;
        };

        paneRender = () => {
            pane.replaceChildren();
            const templates = node._symTemplates ?? [];
            if (!templates.length) {
                const pool = kindOf() === "reference"
                    ? "No reference templates yet — pack one from a Reference "
                      + "Browser and press 💾."
                    : kindOf() === "order"
                    ? `No order templates for ${monthOf() || "this month"} yet — `
                      + "pack one from an Order Specs and press 💾."
                    : "No templates yet — save one from the Auto Packer (💾).";
                pane.appendChild(emptyState(resolveProjectPath(node)
                    ? pool
                    : "Set the project folder to browse its templates."));
                return;
            }
            const checkedSet = readChecked();
            for (const t of templates) {
                const sel = isId(t, selW?.value);
                const row = document.createElement("div");
                row.className = "sym-row";
                row.style.cssText = "padding:6px 10px;min-width:0;"
                    + (sel ? `background:${HUB.rowHover};` : "");
                const head = document.createElement("div");
                head.style.cssText =
                    "display:flex;align-items:center;gap:10px;min-width:0;";
                // Output checkbox (multi-select) — drives the sheets /
                // sheet_prompts outputs; independent of "use" (the single
                // config selection).
                const chk = document.createElement("input");
                chk.type = "checkbox";
                chk.checked = [...checkedSet].some((v) => isId(t, v));
                chk.title = "Output this template's saved sheets + prompts";
                chk.style.cssText = "flex:none;cursor:pointer;margin:0;";
                chk.addEventListener("click", () => {
                    const s = readChecked();
                    // Drop any legacy bare-slug entry for this template as well,
                    // so unticking really unticks.
                    for (const v of [...s]) if (isId(t, v)) s.delete(v);
                    if (chk.checked) s.add(idOf(t));
                    if (chkW) chkW.value = JSON.stringify([...s]);
                    refreshSummary();
                });
                head.appendChild(chk);
                const label = document.createElement("span");
                label.style.cssText = "flex:1;min-width:0;overflow:hidden;"
                    + `text-overflow:ellipsis;white-space:nowrap;color:${HUB.ink};`;
                label.textContent = "📁  " + t.name;
                head.appendChild(label);
                // Which pool the row is from — the only thing telling an order
                // template apart from a reference one of the same name.
                const badge = badgeOf(t);
                if (badge) {
                    const b = document.createElement("span");
                    b.textContent = badge;
                    b.style.cssText =
                        `font:11px ${HUB.mono};color:${HUB.inkSubtle};flex:none;`
                        + `border:1px solid ${HUB.hairline};border-radius:6px;`
                        + "padding:1px 6px;";
                    head.appendChild(b);
                }
                const count = document.createElement("span");
                count.textContent = (t.sheetCount ?? (t.sheets?.length || 0)) + " ▦";
                count.style.cssText =
                    `font:12px ${HUB.mono};color:${HUB.inkSubtle};flex:none;`;
                head.appendChild(count);
                const use = document.createElement("button");
                use.textContent = sel ? "✓ in use" : "use";
                use.className = "sym-btn sym-btn-accent";
                use.style.cssText =
                    `padding:5px 12px;background:${sel ? HUB.surface1 : HUB.accent};` +
                    `color:${sel ? HUB.inkSubtle : HUB.onAccent};` +
                    `border:0;border-radius:8px;cursor:pointer;font:12px ${HUB.font};flex:none;`;
                use.addEventListener("click", () => { select(t); close(); });
                head.appendChild(use);
                const del = document.createElement("button");
                del.textContent = "×";
                del.className = "sym-btn";
                del.style.cssText = ghostButtonCss
                    + `color:${HUB.danger};flex:none;line-height:1;`;
                del.addEventListener("click", () => doDelete(t));
                head.appendChild(del);
                row.appendChild(head);
                const paths = t.sheetPaths ?? [];
                if (paths.length) {
                    const sheets = document.createElement("div");
                    sheets.style.cssText =
                        "display:flex;gap:6px;flex-wrap:wrap;padding:6px 0 2px 26px;";
                    for (const p of paths) {
                        sheets.appendChild(symImg(localImageUrl(p), 54));
                    }
                    row.appendChild(sheets);
                }
                pane.appendChild(row);
            }
        };
        paneRender();
    }

    // Refresh on project change (chain onto the widget callback) + on load. A
    // wired project_path (Local/Modal switch) is only resolvable once the links
    // restore, so a deferred pass covers that case without a manual refresh.
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
    if (!resolveProjectPath(node)) setTimeout(() => refresh(), 400);
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

function refUrl(refsRoot, rel) {
    // Task-ref cells resolve through /symbiotica/ref-image, which applies the
    // SAME rule as the Python compositor (exact rel under refsRoot, else flat
    // basename) — the canvas preview and the queued sheet cannot disagree.
    return api.apiURL(
        `/symbiotica/ref-image?root=${encodeURIComponent(refsRoot)}&rel=${encodeURIComponent(rel)}`
    );
}

// Thumbnail URL for an ABSOLUTE image path (a saved template sheet). Same route
// and /api/ prefix rule as thumbUrl — only the path is already absolute.
function localImageUrl(path) {
    return api.apiURL(
        `/symbiotica/local-image?path=${encodeURIComponent(path)}`);
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
registerSymbioticaExtension(app, {
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
        // A pack save (Auto Packer 💾) landed — refresh every Template Library so
        // the new/updated folder shows up with its sheet thumbnails.
        api.addEventListener("symbiotica.pack_template_saved", ({ detail }) => {
            if (detail?.error) {
                console.error("[symbiotica] template save:", detail.error);
                toast("error", "Template not saved", detail.error);
                return;
            }
            if (detail?.fellBack) {
                console.warn("[symbiotica] template '" + detail.name
                    + "' saved to output/templates (project folder unwritable "
                    + "or unset) — still browsable in the Library.");
                toast("warn", `Saved “${detail.name}” to the output fallback`,
                      "No project folder on this order (or it is not writable), "
                      + `so it went to ${detail.dir}. The Library browses that `
                      + "folder too, so it is still reloadable.");
            } else {
                // Name the pool: an order template is that month's design guide,
                // a reference one is universal — the dir alone doesn't say it.
                const pool = detail?.kind === "reference"
                    ? "reference template (any order)"
                    : detail?.kind === "order"
                    ? `order template · ${detail?.month || "this month"}`
                    : "";
                toast("success", `Saved “${detail?.name}”`,
                      [pool, detail?.dir ?? ""].filter(Boolean).join(" — "));
            }
            for (const n of app.graph?._nodes ?? []) {
                if (n.comfyClass === "SymbioticaTemplateLibrary") {
                    n._symRefreshTemplates?.();
                }
            }
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

        if (nodeData.name === "SymbioticaOrderAssets") {
            const orig = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                orig?.apply(this, arguments);
                // "All" + the wired event's own types, so the pick can only be
                // a type this event actually has — the same combo the Auto
                // Packer gets, from the same source.
                comboify(this, "category", () => eventCategoriesFor(this));
                // Schema default is "" (unset). A fresh node should still SHOW
                // "All"; onConfigure restores a saved pick over this.
                const w = widgetOf(this, "category");
                if (w && !w.value) w.value = "All";
            };
        }

        if (nodeData.name === "SymbioticaAutoPacker") {
            const orig = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                orig?.apply(this, arguments);
                // "All" + the categories of the upstream Order Specs' event.
                comboify(this, "category", () => eventCategoriesFor(this));
                // Schema default is "" (the unset sentinel Python uses to defer
                // to a wired template). A fresh interactive node should still
                // SHOW "All" — a concrete pick Python honors as "pack every
                // type". onConfigure restores a saved value over this.
                const cw0 = widgetOf(this, "category");
                if (cw0 && !cw0.value) cw0.value = "All";
                // The Assets panel drives the hidden `overrides` widget.
                const ovW = widgetOf(this, "overrides");
                if (ovW) { ovW.hidden = true; ovW.computeSize = () => [0, -4]; }
                assetsPanel(this);
                // "💾 Save as template" — snapshots this pack to the library.
                wireSaveButton(this);
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

        if (nodeData.name === "SymbioticaCategoryPrompts") {
            const orig = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                orig?.apply(this, arguments);
                // Deferred: at onNodeCreated the node is not on the graph yet,
                // so the packer lookup would run against a graph without it.
                queueMicrotask(() => wireCategoryPrompts(this));
            };
        }

        if (nodeData.name === "SymbioticaAutoPackerSettings") {
            const origCfg = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function () {
                origCfg?.apply(this, arguments);
                // Migrate pre-scale_target workflows: the `scale` /
                // `scale_max_canvas` widgets were replaced by scale_target /
                // scale_max, so a restored value ("3x"/"256") is no longer a
                // valid option for its slot — reset those to the default.
                const fix = (name, opts, def) => {
                    const w = widgetOf(this, name);
                    if (w && !opts.includes(w.value)) w.value = def;
                };
                fix("scale_target",
                    ["off", "256", "384", "512", "768", "1024", "fit width"],
                    "off");
                fix("scale_max", ["2x", "3x", "4x", "6x", "8x"], "3x");
            };
        }

        if (nodeData.name === "SymbioticaTemplateLibrary") {
            const orig = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                orig?.apply(this, arguments);
                wireTemplateLibrary(this);
            };
            const origCfg = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function () {
                origCfg?.apply(this, arguments);
                // A workflow saved before `kind`/`month` existed restores three
                // values onto five widgets; LiteGraph stops at the third, so the
                // new two keep whatever they were created with. Normalise them
                // anyway — a restored null would render as a "null" pool and
                // reach Python as one.
                const kw = widgetOf(this, "kind");
                if (kw && !["All", "Order", "Reference"].includes(kw.value)) {
                    kw.value = "All";
                }
                const mw = widgetOf(this, "month");
                if (mw && typeof mw.value !== "string") mw.value = "";
                // Workflow load: re-list the project's templates and re-drive
                // any downstream Auto Packer from the saved `selected` template.
                // Also re-fit the height: workflows saved before the overlay
                // browser serialized a node tall enough for the old embedded
                // panel, which no longer exists.
                queueMicrotask(() => {
                    this._symRefreshTemplates?.();
                    this.setSize?.([this.size[0], this.computeSize()[1]]);
                });
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
    if (!res.ok) {
        const err = new Error(
            (await res.json().catch(() => ({}))).error ?? res.statusText);
        // Callers that cache need to tell "this request will never work" from
        // "the server is having a moment".
        err.status = res.status;
        throw err;
    }
    return res.json();
}

async function postJson(route, body) {
    const res = await api.fetchApi(route, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error ?? res.statusText);
    return data;
}

// Connect an Auto Packer's PER-SHEET asset types to a Category Prompts node,
// and fill in its project folder. Done by the extension rather than by hand
// because the packer's two category outputs are adjacent STRING lists and
// picking the wrong one does not fail: ComfyUI repeats a short list's last
// entry (execution.py slice_dict), so a deduped list would render every sheet
// after the first few with someone else's architect prompt, silently.
//
// The slot is looked up BY NAME. Hard-coding its index would rot the first time
// an output is added to the packer.
function wireCategoryPrompts(node) {
    if (!node || node.inputs?.find((i) => i.name === "sheet_categories")?.link
        != null) return;
    const packers = (app.graph?._nodes ?? [])
        .filter((n) => n.comfyClass === "SymbioticaAutoPacker");
    // Two packers and no way to tell which one is meant: leave it alone rather
    // than guess wrong and have it look connected.
    if (packers.length !== 1) return;
    const packer = packers[0];
    const slot = (packer.outputs ?? [])
        .findIndex((o) => (o.name ?? o.label) === "sheet_categories");
    const input = node.inputs?.findIndex((i) => i.name === "sheet_categories");
    if (slot < 0 || input == null || input < 0) return;
    packer.connect?.(slot, node, input);
    // Resolve the packer's own project source the same way the rest of the
    // order lane does — it follows a Local/Modal switch and reroutes, and
    // refuses to guess when a branch is ambiguous.
    const pw = widgetOf(node, "project_path");
    if (pw && !String(pw.value ?? "").trim()) {
        const resolved = inputString(packer, "order", new Set());
        if (resolved) pw.value = resolved;
    }
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
                    return { url: refUrl(refsRoot, paths[0]), flip: pairFlip };
                }
                // Multiple checked refs are explicit per-cell art — no baked flip.
                const rel = paths[Math.min(i, paths.length - 1)];
                return { url: refUrl(refsRoot, rel), flip: false };
            }
            if (member.spriteId && refsRoot) {
                return { url: refUrl(refsRoot, member.spriteId),
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
