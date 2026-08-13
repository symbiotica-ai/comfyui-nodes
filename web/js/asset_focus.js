// ABOUTME: Asset Focus node UI — the event's assets listed on the node body,
// ABOUTME: click one to work on it. The index that used to be held by hand
// ABOUTME: across a dozen index nodes is this click.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { HUB, injectHubStyles, ghostButtonCss } from "./hub_theme.js";
import { attachHoverZoom, el, emptyState, hideHoverZoom, imageFullUrl,
         imageThumbUrl, pinPanelWidth } from "./browser_chrome.js";
// The Order Specs front end — project, month, feature, "Read folder" — hosted
// here rather than reimplemented: "order specs and asset focus are 2 nodes
// that are doing one thing… i select month and feature in specs and asset in
// asset focus. this doesn't make any sense".
import { wireOrderSpecs } from "./order_pipeline.js";

const NODE_CLASS = "SymbioticaAssetFocus";
const MIN_NODE_W = 300;
// The client's own reference art for an asset, at the size the Auto Packer's
// cell strip uses — the two panels list the same assets and must read alike.
const THUMB_PX = 30;

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
    // Remembered PER SOURCE, not per node: this node asks ITSELF while nothing
    // is wired, and a plain "already asked" flag then swallowed the first ask
    // of the Order Specs that arrived afterwards.
    if (node._symAskedFor === source || !source?._symRefreshOrder) return;
    node._symAskedFor = source;
    Promise.resolve(source._symRefreshOrder())
        .then(() => node._symRenderFocus?.())
        .catch(() => {});
}

// `{ assets, refsRoot }` — the reference files ride along with the names, and
// the root they are relative to comes off the same source node the Auto Packer
// reads (`_symRefsRoot`, set by the order parse that also registers the folder
// with the server, which is what makes the thumbnails loadable at all).
function publishedAssets(node) {
    // Nothing wired in means this node is its own source: it hosts the same
    // project/month/feature front end, so it holds `_symEvents` and knows how
    // to refresh them. Returning null here instead is what left the panel
    // saying "wire an Order Specs" on a node that reads the folder itself.
    const source = orderSource(node) ?? node;
    let event = null;
    if (Array.isArray(source._symEvents)) {
        const events = source._symEvents;
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
    return {
        refsRoot: source._symRefsRoot ?? "",
        assets: assets
            .filter((a) => String(a.assetName ?? "").trim())
            .map((a) => ({ name: a.assetName, category: a.category ?? "",
                           canvas: a.canvas ?? "", refs: a.refFiles ?? [] })),
    };
}

// A text box you cannot be told what to type is not an input. The classic node
// UI will not turn a text widget into a dropdown by mutating `.type`, so the
// widget is recreated as a real combo in the same slot — same approach as
// order_pipeline.js's `comboify`, kept here because that module exports
// nothing. Value and serialisation are preserved, so the string still reaches
// the Python node and a saved workflow still restores it.
const ALL_CATEGORIES = "All";
// The `asset` combo cannot offer an empty label, so "no narrowing" is
// spelled out on screen and emptied on the way to the node.
const ALL_ASSETS = "All assets";

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
    for (const asset of publishedAssets(node)?.assets ?? []) {
        const category = String(asset.category ?? "").trim();
        if (category && !out.includes(category)) out.push(category);
    }
    return out;
}

// Put the order-reading widgets above the ones that narrow it. Order on screen
// is the order of `node.widgets`, and it is free to differ from the schema's —
// which is fixed by what saved graphs restore positionally, not by what reads
// well.
const SELECTION_ORDER = ["project_path", "month", "feature", "📁 Read folder"];

function hoistSelectionWidgets(node) {
    const wanted = SELECTION_ORDER
        .map((name) => node.widgets?.find(
            (w) => w.name === name || w.name?.endsWith("Read folder")))
        .filter((w, i, all) => w && all.indexOf(w) === i);
    if (!wanted.length) return;
    node.widgets = [...wanted,
                    ...node.widgets.filter((w) => !wanted.includes(w))];
}

function focusPanel(node) {
    injectHubStyles();

    const container = el("div", "box-sizing:border-box;width:100%;height:100%;"
        + "overflow-y:auto;overflow-x:hidden;");
    // Every level gets an explicit width and border-box sizing. A flex row
    // whose content is wider than the node otherwise resolves its width
    // against a shrink-to-fit parent and paints outside the node, over
    // whatever is behind it.
    // HUB.ink is a dark-theme token (#f7f8f8): on ComfyUI's LIGHT palette the
    // node body is white and every asset name painted in it is invisible —
    // measured at rgb(247,248,248) on white. ComfyUI's own text colour follows
    // the palette both ways, with the hub ink as the fallback.
    const list = el("div", "width:100%;box-sizing:border-box;overflow:hidden;"
        + `padding:2px;font:11px ${HUB.font};`
        + `color:var(--input-text, ${HUB.ink});`);
    container.appendChild(list);
    container.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });

    // LiteGraph sums widgets for the node's MINIMUM height and prefers
    // `computeSize` over `computeLayoutSize` — so a computeSize that answers
    // with the content, or with the space below itself, pins the minimum to
    // whatever is on screen and the corner will not drag shorter. A constant
    // floor and no computeSize: the layout hands this widget the rest of the
    // node's body, the element fills it, and the list scrolls inside.
    node.addDOMWidget("focus_panel", "sym_focus", container, {
        serialize: false, hideOnZoom: true,
        getMinHeight: () => 34,
    });
    // Redraw, never resize: with the panel's height now decided by the layout,
    // re-listing must not push the node back to any height of its own — his
    // drag is the only thing that sets it.
    // The wrapper ComfyUI gives this widget lags a SHRINK, so pin it or every
    // row paints over the canvas to the right of a narrowed node.
    const syncPanelWidth = pinPanelWidth(node, container);
    const refit = () => requestAnimationFrame(() => {
        if (node.size[0] < MIN_NODE_W) node.setSize?.([MIN_NODE_W, node.size[1]]);
        syncPanelWidth();
        node.setDirtyCanvas?.(true, true);
    });
    node.size[0] = Math.max(node.size[0], MIN_NODE_W);

    const chosen = () => {
        const value = widgetOf(node, "asset")?.value?.trim?.() || "";
        return value === ALL_ASSETS ? "" : value;
    };
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

    // One reference image, at strip size, big under the pointer. The tile is
    // the asset's own art, so hovering it is how you tell two similar assets
    // apart without leaving the node.
    function refThumb(asset, refsRoot, file) {
        const path = `${refsRoot}/${file}`;
        const img = el("img",
            `width:${THUMB_PX}px;height:${THUMB_PX}px;object-fit:contain;`
            + `background:${HUB.surface1};border-radius:3px;flex:none;`
            + `border:1px solid ${HUB.hairline};`);
        img.src = imageThumbUrl(path, THUMB_PX * 2);   // crisp on a retina panel
        img.loading = "lazy";
        img.draggable = false;
        img.title = file;
        // A missing or unreadable reference must not leave a broken-image glyph
        // sitting in the strip; an empty slot reads as "no art for this one".
        img.addEventListener("error", () => { img.style.visibility = "hidden"; });
        attachHoverZoom(img, () => ({
            w: img.naturalWidth, h: img.naturalHeight,
            label: asset.name,
            hint: file,
            placeholder: img.src,       // already fetched: the frame fills now
            src: () => imageFullUrl(path),
        }));
        return img;
    }

    function assetRow(asset, refsRoot, pick) {
        const on = asset.name === pick;
        const row = el("div",
            "display:flex;flex-direction:column;gap:3px;width:100%;"
            + "box-sizing:border-box;overflow:hidden;"
            + "padding:4px 5px;margin:2px 0;"
            + `border:1px solid ${on ? HUB.accent : HUB.hairline};`
            + "border-radius:5px;cursor:pointer;"
            + (on ? "" : "opacity:.75;"));
        const head = el("div",
            "display:flex;align-items:center;gap:6px;min-width:0;");
        head.append(el("span", "flex:1;min-width:0;overflow:hidden;"
            + "text-overflow:ellipsis;white-space:nowrap;",
            `${asset.name}${asset.canvas ? ` · ${asset.canvas}` : ""}`));
        const refs = asset.refs ?? [];
        if (refs.length) {
            head.appendChild(el("span",
                `flex:none;color:${HUB.inkTertiary};`,
                `${refs.length} ref${refs.length === 1 ? "" : "s"}`));
        }
        row.appendChild(head);
        if (refs.length && refsRoot) {
            const strip = el("div",
                "display:flex;gap:4px;flex-wrap:wrap;min-width:0;");
            for (const file of refs) strip.appendChild(refThumb(asset, refsRoot, file));
            row.appendChild(strip);
        }
        row.title = `${asset.name}${asset.category ? ` · ${asset.category}` : ""}`;
        row.addEventListener("pointerdown", (e) => e.stopPropagation());
        row.addEventListener("click", () => { hideHoverZoom(); choose(asset.name); });
        return row;
    }

    // The category name over the assets that belong to it, for the "All" view.
    // Narrowed to one category there is nothing to separate, and the widget
    // already says which one it is.
    function groupHeader(category, count) {
        return el("div",
            "display:flex;align-items:baseline;gap:6px;width:100%;"
            + "box-sizing:border-box;overflow:hidden;text-overflow:ellipsis;"
            + "white-space:nowrap;padding:6px 3px 3px;"
            + `border-bottom:1px solid ${HUB.hairline};margin-bottom:2px;`
            + `color:${HUB.inkSubtle};`,
            `${category || "uncategorised"} · ${count}`);
    }

    function render() {
        list.replaceChildren();
        // A preview left floating over a list that is being replaced points at
        // a tile that no longer exists.
        hideHoverZoom();
        // The pick he made last session, put back now that there is something
        // to pick FROM. `category` and `asset` are combos whose choices only
        // exist once the order has been read, and a combo restored with a
        // value outside its options does not survive the load — so every
        // restart lost the narrowing and he re-clicked the same widgets. The
        // wanted values are snapshotted off the saved graph in onConfigure and
        // only dropped once a list has arrived to look in.
        const wanted = node._symWanted;
        if (wanted) {
            const categories = categoriesOf(node);
            const cw = widgetOf(node, "category");
            if (cw && wanted.category && categories.includes(wanted.category)) {
                cw.value = wanted.category;
            }
            const offered = new Set([
                ...(publishedAssets(node)?.assets ?? []),
                ...(node._symFocusAssets ?? []),
            ].map((a) => a.name));
            const aw = widgetOf(node, "asset");
            if (aw && wanted.asset && offered.has(wanted.asset)) {
                aw.value = wanted.asset;
            }
            // Give up only once the choices are known: before that, "not in
            // the list" means the list has not arrived, not that the pick is
            // stale — which is the whole bug, one layer down.
            if (offered.size) node._symWanted = null;
        }

        // What a run reported wins — it is the list the node actually chose
        // from, already narrowed by `category`. Otherwise fall back to what the
        // wired source published, so the choices are there before any run.
        const narrow = narrowed().toLowerCase();
        const published = publishedAssets(node);
        // A run reports the names it chose from; the source publishes the
        // reference files. Merge by name so the thumbnails are there either
        // way — a run's own payload carries them too, and whichever list is in
        // use, the fuller record wins.
        const known = new Map((published?.assets ?? []).map((a) => [a.name, a]));
        const fromRun = node._symFocusAssets?.length ? node._symFocusAssets : null;
        const refsRoot = (fromRun ? node._symFocusRefsRoot : "")
            || published?.refsRoot || "";
        // Narrow whichever list is in use. A run's list already arrives
        // narrowed by the same widget, but between runs the widget can move
        // and the panel must not keep showing what it would no longer choose.
        const assets = (fromRun ?? published?.assets ?? [])
            .filter((a) => !narrow
                || String(a.category ?? "").toLowerCase() === narrow)
            .map((a) => ({
                ...a,
                canvas: a.canvas || known.get(a.name)?.canvas || "",
                refs: known.get(a.name)?.refs?.length
                    ? known.get(a.name).refs : (a.refs ?? []),
            }));
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
            const wired = upstreamNode(node, "order");
            const project = widgetOf(node, "project_path");
            const hasProject = Boolean(project?.value?.trim?.())
                || node.inputs?.some((i) => i.name === "project_path"
                                         && i.link != null);
            list.appendChild(emptyState(
                wired
                    ? "no assets from the wired order yet — pick a feature "
                      + "upstream, or queue this node once"
                    : hasProject
                        ? "click 📁 Read folder to read this project's order"
                        : "set project_path (and month), or wire an order in"));
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

        if (narrowed()) {
            for (const asset of assets) list.appendChild(assetRow(asset, refsRoot, pick));
        } else {
            // First-appearance order, the same order `assets_by_category`
            // groups by on the Python side — so the panel reads down the order
            // sheet rather than alphabetically, and the run order it describes
            // is the order it shows.
            const groups = new Map();
            for (const asset of assets) {
                const key = String(asset.category ?? "").trim();
                if (!groups.has(key)) groups.set(key, []);
                groups.get(key).push(asset);
            }
            for (const [category, members] of groups) {
                list.appendChild(groupHeader(category, members.length));
                for (const asset of members) {
                    list.appendChild(assetRow(asset, refsRoot, pick));
                }
            }
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
                ? node._symFocusAssets : (publishedAssets(node)?.assets ?? []);
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

    // "make asset a dropdown, it doesnt make sense to be text input field".
    // The panel is still the fast way to pick one, but a combo says what the
    // choices ARE without reading the list, and it is the widget a saved
    // workflow shows before anything has rendered. `""` is first and means
    // "every asset in the narrowing", which is what the panel's `all` does.
    const assetWidget = comboify(node, "asset", () => [
        ALL_ASSETS,
        ...(node._symFocusAssets?.length
            ? node._symFocusAssets : (publishedAssets(node)?.assets ?? []))
            .filter((a) => !narrowed() || a.category === narrowed())
            .map((a) => a.name),
    ]);
    if (assetWidget) {
        const previous = assetWidget.callback;
        assetWidget.callback = function (value) {
            previous?.apply(this, arguments);
            // The combo cannot hold "" as a label, so the sentinel is spelled
            // out on screen and emptied on the way to the node.
            if (assetWidget.value === ALL_ASSETS) assetWidget.value = "";
            render();
        };
        // What reaches the node is the empty string the sentinel stands for.
        assetWidget.serializeValue = () =>
            (assetWidget.value === ALL_ASSETS ? "" : assetWidget.value);
        // A saved graph restores the empty string; show the sentinel instead
        // of a blank row.
        if (!assetWidget.value) assetWidget.value = ALL_ASSETS;
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
        node._symAskedFor = null;
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
            // The same project/month/feature front end Order Specs has, so the
            // whole selection is made here. It only acts when `project_path`
            // has something in it, so a node fed by a wire is unaffected.
            wireOrderSpecs(this);
            // The schema APPENDS those three (a saved workflow restores widget
            // values by position), so on screen they arrive under `asset`.
            // Selection reads top-down: project, month, feature, then the two
            // that narrow it.
            hoistSelectionWidgets(this);
            // The chosen name is the panel's storage. It stays typeable — a
            // name pasted in still works — but it is not where you look to
            // find out what the choices are.
            focusPanel(this);
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            // Snapshot the saved narrowing BEFORE it is applied. `category`
            // and `asset` are combos fed by the order, which has not been read
            // yet at this point, so what lands on the widget does not stay
            // there — the panel puts it back once the choices exist.
            const saved = info?.widgets_values;
            if (Array.isArray(saved)) {
                const at = (name) =>
                    this.widgets?.findIndex((w) => w.name === name) ?? -1;
                const value = (name) => {
                    const i = at(name);
                    return i >= 0 ? String(saved[i] ?? "").trim() : "";
                };
                this._symWanted = { category: value("category"),
                                    asset: value("asset") };
            }
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
                this._symAskedFor = null;
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
    // The run's own reference root, so the thumbnails load from a graph whose
    // source node has published nothing to the canvas.
    node._symFocusRefsRoot = String(detail.refs_root ?? "");
    node._symRenderFocus?.();
});
