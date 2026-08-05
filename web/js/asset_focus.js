// ABOUTME: Asset Focus node UI — the event's assets listed on the node body,
// ABOUTME: click one to work on it. The index that used to be held by hand
// ABOUTME: across a dozen index nodes is this click.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { HUB, injectHubStyles, ghostButtonCss } from "./hub_theme.js";
import { el, emptyState } from "./browser_chrome.js";

const NODE_CLASS = "SymbioticaAssetFocus";
const MIN_NODE_W = 300;
const PANEL_MAX = 460;

const widgetOf = (node, name) => node.widgets?.find((w) => w.name === name);

function upstreamNode(node, inputName) {
    const input = node?.inputs?.find((i) => i.name === inputName);
    if (!input || input.link == null) return null;
    const link = app.graph.links[input.link];
    return link ? app.graph.getNodeById(link.origin_id) : null;
}

// The feature combo reads "Mini 3 — Franken-Feast" while the event is keyed on
// "Mini 3"; order_pipeline.js splits the same way.
const featureKey = (value) => String(value ?? "").split(" — ")[0].trim();

// The assets the wired source has ALREADY published to the canvas, so the list
// exists before anything is queued. Order Specs keeps its parsed events on the
// node and a Reference Browser publishes its picks in the same shape, which is
// how the Auto Packer's panel fills without a run either.
// Walk up the order wire. More than one hop because the wire commonly passes
// through a reroute, and a node in between that simply forwards the order is
// not a reason to stop looking for who produced it.
function orderSource(node) {
    let cur = upstreamNode(node, "order");
    for (let hop = 0; hop < 6 && cur; hop++) {
        if (cur.comfyClass === "SymbioticaOrderSpecs"
            || cur.comfyClass === "SymbioticaReferenceBrowser") {
            return cur;
        }
        const next = upstreamNode(cur, "order");
        if (next) { cur = next; continue; }
        // A reroute names its input whatever it likes; one wired input is
        // unambiguous, several are not worth guessing between.
        const wired = (cur.inputs ?? []).filter((i) => i.link != null);
        if (wired.length !== 1) return null;
        cur = upstreamNode(cur, wired[0].name);
    }
    return null;
}

// Asking the source to parse, once, when it has nothing yet. A saved workflow
// restores Order Specs' month and feature widgets without parsing anything, so
// the node looks configured while holding no events at all — which is exactly
// the state a freshly reopened graph is in.
function askSource(node, source) {
    if (node._symAskedOrder || !source?._symRefreshOrder) return;
    node._symAskedOrder = true;
    Promise.resolve(source._symRefreshOrder())
        .then(() => node._symRenderFocus?.())
        .catch(() => {});
}

function publishedAssets(node) {
    const source = orderSource(node);
    if (!source) return null;
    let event = null;
    if (source.comfyClass === "SymbioticaOrderSpecs") {
        const events = source._symEvents ?? [];
        const want = featureKey(widgetOf(source, "feature")?.value);
        event = events.find((e) => featureKey(e.feature) === want) || events[0] || null;
    } else if (source.comfyClass === "SymbioticaReferenceBrowser") {
        event = source._symPickedEvent ?? null;
    }
    const assets = event?.assets ?? null;
    if (!Array.isArray(assets) || !assets.length) {
        askSource(node, source);
        return null;
    }
    return assets
        .filter((a) => String(a.assetName ?? "").trim())
        .map((a) => ({ name: a.assetName, category: a.category ?? "" }));
}

// A text box you cannot be told what to type is not an input. The classic node
// UI will not turn a text widget into a dropdown by mutating `.type`, so the
// widget is recreated as a real combo in the same slot — same approach as
// order_pipeline.js's `comboify`, kept here because that module exports
// nothing. Value and serialisation are preserved, so the string still reaches
// the Python node and a saved workflow still restores it.
const ALL_CATEGORIES = "All";

function comboify(node, widgetName, valuesFn) {
    const i = node.widgets?.findIndex((x) => x.name === widgetName);
    if (i == null || i < 0) return null;
    const existing = node.widgets[i];
    if (existing.type === "combo") {
        existing.options = existing.options ?? {};
        existing.options.values = valuesFn;
        return existing;
    }
    const value = existing.value;
    node.widgets.splice(i, 1);
    const w = node.addWidget("combo", widgetName, value,
                             (v) => { w.value = v; }, { values: valuesFn });
    node.widgets = node.widgets.filter((x) => x !== w);
    node.widgets.splice(i, 0, w);
    w.serializeValue = () => w.value;
    return w;
}

// The categories the wired order actually holds, in the order they appear in
// it — the same first-appearance order `assets_by_category` groups by, so the
// dropdown reads down the order sheet rather than alphabetically.
function categoriesOf(node) {
    const out = [ALL_CATEGORIES];
    for (const asset of publishedAssets(node) ?? []) {
        const category = String(asset.category ?? "").trim();
        if (category && !out.includes(category)) out.push(category);
    }
    return out;
}

function focusPanel(node) {
    injectHubStyles();

    const container = el("div", "box-sizing:border-box;width:100%;"
        + "overflow-y:auto;overflow-x:hidden;");
    // Every level gets an explicit width and border-box sizing. A flex row
    // whose content is wider than the node otherwise resolves its width
    // against a shrink-to-fit parent and paints outside the node, over
    // whatever is behind it.
    const list = el("div", "width:100%;box-sizing:border-box;overflow:hidden;"
        + `padding:2px;font:11px ${HUB.font};color:${HUB.ink};`);
    container.appendChild(list);
    container.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });

    const panelW = node.addDOMWidget("focus_panel", "sym_focus", container,
                                     { serialize: false, hideOnZoom: true });
    panelW.computeSize = function (width) {
        const h = list.scrollHeight;
        return [width, Math.min(Math.max(h ? h + 8 : 34, 34), PANEL_MAX)];
    };
    const refit = () => requestAnimationFrame(() => {
        node.setSize?.([Math.max(node.size[0], MIN_NODE_W), node.computeSize()[1]]);
        node.setDirtyCanvas?.(true, true);
    });
    node.size[0] = Math.max(node.size[0], MIN_NODE_W);

    const chosen = () => widgetOf(node, "asset")?.value?.trim?.() || "";
    // "All" is the label for no narrowing; the Python node reads an empty
    // string, and every other value passes through untouched.
    const narrowed = () => {
        const value = widgetOf(node, "category")?.value?.trim?.() || "";
        return value === ALL_CATEGORIES ? "" : value;
    };

    function choose(name) {
        const w = widgetOf(node, "asset");
        // Clicking the current one clears it, which is how you get back to
        // "the first" without knowing what the first is called.
        if (w) w.value = w.value === name ? "" : name;
        node.setDirtyCanvas?.(true, true);
        render();
    }

    function render() {
        list.replaceChildren();
        // What a run reported wins — it is the list the node actually chose
        // from, already narrowed by `category`. Otherwise fall back to what the
        // wired source published, so the choices are there before any run.
        const narrow = narrowed().toLowerCase();
        // Narrow whichever list is in use. A run's list already arrives
        // narrowed by the same widget, but between runs the widget can move
        // and the panel must not keep showing what it would no longer choose.
        const assets = (node._symFocusAssets?.length
            ? node._symFocusAssets : (publishedAssets(node) ?? [])).filter(
                (a) => !narrow || String(a.category ?? "").toLowerCase() === narrow);
        // A saved workflow restores the widget AFTER onNodeCreated ran, so the
        // normalising done there is overwritten by the empty value on disk.
        const categoryW = widgetOf(node, "category");
        if (categoryW && !categoryW.value) categoryW.value = ALL_CATEGORIES;

        let pick = chosen();
        // Switching the feature upstream replaces the whole list, and a name
        // from the previous event survives on the widget — highlighting
        // nothing while still being what the node would render, which is a
        // refusal on the next run. Drop it here rather than let the graph
        // carry a choice the panel is not showing.
        if (pick && assets.length && !assets.some((a) => a.name === pick)) {
            const w = widgetOf(node, "asset");
            if (w) w.value = "";
            pick = "";
            node.setDirtyCanvas?.(true, true);
        }

        if (!assets.length) {
            list.appendChild(emptyState(
                upstreamNode(node, "order")
                    ? "no assets from the wired order yet — pick a feature on "
                      + "Order Specs, or queue this node once"
                    : "wire an Order Specs (or a Reference Browser) into order"));
            refit();
            return;
        }

        const head = el("div",
            "display:flex;align-items:center;gap:6px;width:100%;"
            + "box-sizing:border-box;overflow:hidden;"
            + `padding:2px 3px 4px;color:${HUB.inkSubtle};`);
        // Say what the node will actually emit, not just what is listed.
        head.append(el("span",
            "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;"
            + "white-space:nowrap;",
            `${assets.length} asset${assets.length === 1 ? "" : "s"}`
            + `${narrowed() ? ` · ${narrowed()}` : ""}`
            + ` · runs ${pick ? "1" : assets.length}`));
        if (pick) {
            const clear = el("button", ghostButtonCss + "padding:1px 7px;flex:none;",
                             "all");
            clear.className = "sym-btn";
            clear.title = assets.length === 1
                ? "Emit the whole event instead of this one asset"
                : `Emit all ${assets.length} assets instead of this one`;
            clear.addEventListener("pointerdown", (e) => e.stopPropagation());
            clear.addEventListener("click", () => choose(pick));
            head.appendChild(clear);
        }
        list.appendChild(head);

        for (const asset of assets) {
            const on = asset.name === pick;
            const row = el("div",
                "display:flex;align-items:center;gap:6px;width:100%;"
                + "box-sizing:border-box;overflow:hidden;"
                + "padding:3px 5px;margin:2px 0;"
                + `border:1px solid ${on ? HUB.accent : HUB.hairline};`
                + `border-radius:5px;cursor:pointer;`
                + (on ? "" : "opacity:.75;"));
            row.append(el("span", "flex:1;min-width:0;overflow:hidden;"
                + "text-overflow:ellipsis;white-space:nowrap;", asset.name));
            row.appendChild(el("span",
                "flex:0 1 auto;min-width:0;overflow:hidden;text-overflow:ellipsis;"
                + `white-space:nowrap;color:${HUB.inkTertiary};`,
                asset.category || ""));
            row.title = `${asset.name}${asset.category ? ` · ${asset.category}` : ""}`;
            row.addEventListener("pointerdown", (e) => e.stopPropagation());
            row.addEventListener("click", () => choose(asset.name));
            list.appendChild(row);
        }
        refit();
    }

    // Choosing a category re-lists, and an asset hidden by the new one would
    // otherwise stay chosen invisibly — and be what the node renders.
    const categoryWidget = comboify(node, "category", () => categoriesOf(node));
    if (categoryWidget) {
        if (!categoryWidget.value) categoryWidget.value = ALL_CATEGORIES;
        const previous = categoryWidget.callback;
        categoryWidget.callback = function (value) {
            previous?.apply(this, arguments);
            const pool = node._symFocusAssets?.length
                ? node._symFocusAssets : (publishedAssets(node) ?? []);
            const keep = pool.some(
                (a) => a.name === chosen()
                    && (!narrowed() || a.category === narrowed()));
            if (!keep) {
                const w = widgetOf(node, "asset");
                if (w) w.value = "";
            }
            render();
        };
    }

    node._symRenderFocus = render;

    // The order upstream changed — a different feature, a different month, a
    // re-parse. "why doesn't the asset focus node change the category when i
    // change it in order specs? i have to manually click in 494 on all to see
    // the categories": the `category` dropdown rebuilds its options when it is
    // opened, so clicking it looked like the fix, but nothing had told the
    // panel to re-list.
    node._symOrderChanged = (source) => {
        if (!source || orderSource(node) !== source) return;
        // The list a run reported belongs to the event that ran. Keeping it
        // would show the previous feature's assets over the new one's — and it
        // is the list that wins in `render`.
        node._symFocusAssets = [];
        // A feature whose events are not parsed yet is worth asking about
        // again; `publishOrder` repeats itself only when something changed, so
        // an ask that answers the same thing does not come back round.
        node._symAskedOrder = false;
        // A category the new event does not have narrows the list to nothing,
        // which reads as "this node is broken" rather than as "Decoration is
        // not in this feature". Fall back to everything, the same way a chosen
        // asset that is no longer listed is dropped in `render`.
        const categoryW = widgetOf(node, "category");
        if (categoryW && !categoriesOf(node).includes(categoryW.value)) {
            categoryW.value = ALL_CATEGORIES;
        }
        render();
    };

    render();
}

registerSymbioticaExtension(app, {
    name: "symbiotica.asset_focus",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            // The chosen name is the panel's storage. It stays typeable — a
            // name pasted in still works — but it is not where you look to
            // find out what the choices are.
            focusPanel(this);
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            onConfigure?.apply(this, arguments);
            queueMicrotask(() => this._symRenderFocus?.());
        };

        // Wiring the order in is the moment the choices become knowable.
        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (type, index, connected,
                                                            link, ioSlot) {
            onConnectionsChange?.apply(this, arguments);
            if (ioSlot?.name === "order") {
                // A different source is a different question, so it may be
                // asked again.
                this._symAskedOrder = false;
                queueMicrotask(() => this._symRenderFocus?.());
            }
        };
    },
});

// The order arrives on a wire the canvas cannot read, so the node hands its
// asset list over when it runs.
api.addEventListener("symbiotica.focus", (event) => {
    const detail = event?.detail ?? {};
    if (detail.node_id == null) return;
    const node = app.graph?.getNodeById?.(Number(detail.node_id))
        ?? app.graph?.getNodeById?.(detail.node_id);
    if (!node) return;
    node._symFocusAssets = Array.isArray(detail.assets) ? detail.assets : [];
    node._symRenderFocus?.();
});
