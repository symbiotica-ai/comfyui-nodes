// ABOUTME: Asset Focus node UI — the event's assets listed on the node body,
// ABOUTME: click one to work on it. The index that used to be held by hand
// ABOUTME: across a dozen index nodes is this click.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { HUB, injectHubStyles, ghostButtonCss } from "./hub_theme.js";
import { attachHoverZoom, CHECKER, el, emptyState, hideHoverZoom, ICON,
         iconButton, imageFullUrl, imageThumbUrl, ONE_LINE, pinPanelWidth,
         sidebarShell, svgIcon, treeRow } from "./browser_chrome.js";
// The order picker — project, month, feature, "Read folder". This node hosts
// the whole selection: "order specs and asset focus are 2 nodes
// that are doing one thing… i select month and feature in specs and asset in
// asset focus. this doesn't make any sense".
import { resolveProjectPath, wireOrderSpecs } from "./order_source.js";

const NODE_CLASS = "SymbioticaAssetFocus";
// Asset Recipe IS this node with widget slots on the end of its output
// column, so the selection widgets, the panel and the run's push serve
// both classes. `web/js/asset_recipe.js` adds only the slots.
export const FOCUS_CLASSES = [NODE_CLASS, "SymbioticaAssetRecipe"];
// Every class that HOLDS a parsed order and can stand at the top of an order
// wire. `orderSource` walks up to one of these, so a Task between two Focus
// nodes has to be here or the panel below it reads "wire an order in" until
// the graph is queued.
const ORDER_SOURCES = [...FOCUS_CLASSES, "SymbioticaTask"];
const MIN_NODE_W = 300;
// The client's own reference art for an asset, at the size the cell strips
// use, so every panel that lists these assets reads alike.
const THUMB_PX = 30;

const widgetOf = (node, name) => node.widgets?.find((w) => w.name === name);

function upstreamNode(node, inputName) {
    const input = node?.inputs?.find((i) => i.name === inputName);
    if (!input || input.link == null) return null;
    const link = app.graph.links[input.link];
    return link ? app.graph.getNodeById(link.origin_id) : null;
}

// The feature combo reads "Mini 3 — Franken-Feast" while the event is keyed on
// "Mini 3"; order_source.js splits the same way.
const featureKey = (value) => String(value ?? "").split(" — ")[0].trim();

// The assets the wired source has ALREADY published to the canvas, so the list
// exists before anything is queued: a node that read the folder keeps its
// parsed events on itself, which is how the panel fills without a run.
// Walk up the order wire. More than one hop because the wire commonly passes
// through a reroute, and a node in between that simply forwards the order is
// not a reason to stop looking for who produced it.
function orderSource(node) {
    let cur = upstreamNode(node, "order");
    for (let hop = 0; hop < 6 && cur; hop++) {
        if (ORDER_SOURCES.includes(cur.comfyClass)) return cur;
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
// restores the month and feature widgets without parsing anything, so the node
// looks configured while holding no events at all — which is exactly the state
// a freshly reopened graph is in.
function askSource(node, source) {
    // Remembered PER SOURCE, not per node: this node asks ITSELF while nothing
    // is wired, and a plain "already asked" flag then swallowed the first ask
    // of the source that arrived afterwards.
    if (node._symAskedFor === source || !source?._symRefreshOrder) return;
    node._symAskedFor = source;
    Promise.resolve(source._symRefreshOrder())
        .then(() => node._symRenderFocus?.())
        .catch(() => {});
}

// `{ assets, refsRoot }` — the reference files ride along with the names, and
// the root they are relative to comes off the source node (`_symRefsRoot`, set
// by the order parse that also registers the folder with the server, which is
// what makes the thumbnails loadable at all).
function publishedAssets(node) {
    // Nothing wired in means this node is its own source: it hosts the same
    // project/month/feature front end, so it holds `_symEvents` and knows how
    // to refresh them. Returning null here instead is what left the panel
    // saying "wire an order in" on a node that reads the folder itself.
    const source = orderSource(node) ?? node;
    let event = null;
    if (Array.isArray(source._symEvents)) {
        const events = source._symEvents;
        const want = featureKey(widgetOf(source, "feature")?.value);
        event = events.find((e) => featureKey(e.feature) === want) || events[0] || null;
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
// order_source.js's `comboify`, kept here because that module does not export
// it. Value and serialisation are preserved, so the string still reaches
// the Python node and a saved workflow still restores it.
export const ALL_CATEGORIES = "All";
// The `asset` combo cannot offer an empty label, so "no narrowing" is
// spelled out on screen and emptied on the way to the node.
const ALL_ASSETS = "All assets";
// Same trick for the reference: "" means the asset's first, which is also what
// every other asset gets in an all-assets run.
const FIRST_REF = "First reference";

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

// A canvas in floor tiles — `128x256` is `1x2` — or "" when it is not a whole
// number of tiles. Mirrors order_sheet.canvas_tiles.
const TILE_PX = 128;
export function tilesOf(canvas) {
    const m = /^(\d+)x(\d+)$/.exec(String(canvas ?? "").toLowerCase().replace(/\s+/g, ""));
    if (!m) return "";
    const w = Number(m[1]), h = Number(m[2]);
    if (!w || !h || w % TILE_PX || h % TILE_PX) return "";
    return `${w / TILE_PX}x${h / TILE_PX}`;
}

// The category as a workflow is named: the category plus its canvas in tiles
// (`Appliance 1x2`), the raw pixels when there is no whole-tile grid, the
// plain category when the row names no canvas. Mirrors order_sheet.category_recipe.
export function categoryRecipeOf(asset) {
    const category = String(asset?.category ?? "").trim();
    const canvas = String(asset?.canvas ?? "").replace(/\s+/g, "");
    const size = tilesOf(canvas) || canvas;
    return size ? `${category} ${size}`.trim() : category;
}

// The recipe an ASSET belongs to, for a node whose `category` is empty. Picking
// an asset CLEARS the category on purpose (`chooseAsset` below), so with a name
// chosen the category output would answer nothing and the Recipes node could
// never name the recipe it is meant to store the canvas into. The asset's own
// row answers instead, read off the order the node ALREADY holds: no request,
// no run, and `null` when this node has no order or the name is not in it.
export function assetRecipeOf(node, assetName) {
    const want = String(assetName ?? "").trim();
    if (!want) return null;
    const source = orderSource(node) ?? node;
    if (!Array.isArray(source?._symEvents)) return null;
    const key = featureKey(widgetOf(source, "feature")?.value);
    const event = source._symEvents.find((e) => featureKey(e.feature) === key)
        || source._symEvents[0] || null;
    const asset = (event?.assets ?? []).find(
        (a) => String(a.assetName ?? "").trim() === want);
    if (!asset) return null;
    return { category: String(asset.category ?? "").trim(),
             recipe: categoryRecipeOf(asset) };
}

// Does an asset fall under a dropdown pick? The pick is a recipe label
// (`Appliance 1x2`, one canvas) or a plain category (every canvas).
function inCategory(asset, pick) {
    const want = String(pick ?? "").trim().toLowerCase();
    if (!want) return true;
    return String(asset?.category ?? "").trim().toLowerCase() === want
        || categoryRecipeOf(asset).toLowerCase() === want;
}

// The categories the wired order actually holds, split by canvas, A-Z under
// "All". A dropdown is read by hunting for a name, and seventeen of them in
// the order the spreadsheet happens to list them is a list you have to scan
// every time. Compared with `localeCompare` so "Cashier's Desk" files where a
// person looks for it rather than where its apostrophe's code point puts it.
//
// Two sources, merged: the folder parse the canvas made itself, and the list
// the last run pushed. A wired project the canvas cannot read leaves the parse
// empty while the run knows every category — and the run's list is what the
// panel is already showing, so the dropdown has to agree with it.
//
// Exported because the Recipes node sets this same widget when you pick a
// recipe, and has to turn the recipe's slug back into the label that made it.
// It cannot read the labels off the widget: on Asset Focus `category` is a
// combo whose options ARE this list, but on Task it is a plain text widget the
// tree writes — a combo drops a value that is not among its options, and until
// the first parse lands that is every value.
export function categoriesOf(node) {
    const found = [];
    for (const asset of publishedAssets(node)?.assets ?? []) {
        const category = categoryRecipeOf(asset);
        if (category && !found.includes(category)) found.push(category);
    }
    for (const category of node._symFocusCategories ?? []) {
        if (category && !found.includes(category)) found.push(category);
    }
    return [ALL_CATEGORIES,
            ...found.sort((a, b) => a.localeCompare(b, undefined,
                                                    { sensitivity: "base" }))];
}

// Put the order-reading widgets above the ones that narrow it, and the button
// under all of them — a button between two dropdowns reads as a break in the
// form. Order on screen is the order of `node.widgets`, and it is free to
// differ from the schema's — which is fixed by what saved graphs restore
// positionally, not by what reads well.
const SELECTION_ORDER = ["project_path", "month", "feature", "category", "asset",
                         "📁 Read folder"];

function hoistSelectionWidgets(node) {
    const wanted = SELECTION_ORDER
        .map((name) => node.widgets?.find(
            (w) => w.name === name || w.name?.endsWith("Read folder")))
        .filter((w, i, all) => w && all.indexOf(w) === i);
    if (!wanted.length) return;
    node.widgets = [...wanted,
                    ...node.widgets.filter((w) => !wanted.includes(w))];
}

// `ref` is set by clicking a tile, and a second control for the same choice is
// the same thing twice. The widget stays — it is how the file reaches Python
// and a saved workflow — but it takes no room on the canvas.
export function hideWidget(w) {
    if (!w) return;
    w.hidden = true;
    w.computeSize = () => [0, -4];
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

    // Every reference filename one named asset has, from whichever list holds
    // them: a run's payload carries them and so does the source's publish, and
    // between a restart and the first queue only one of the two exists.
    const refsOf = (name) => {
        if (!name) return [];
        for (const pool of [node._symFocusAssets ?? [],
                            publishedAssets(node)?.assets ?? []]) {
            const hit = pool.find((a) => a.name === name);
            if (hit?.refs?.length) return hit.refs.map(String);
        }
        return [];
    };

    // Which reference file is armed. "" is the asset's first.
    const armed = () => {
        const value = widgetOf(node, "ref")?.value?.trim?.() || "";
        return value === FIRST_REF ? "" : value;
    };
    // A filename belongs to ONE asset, so it cannot survive leaving that
    // asset — carried over, it would name nothing in the new one's list and
    // silently mean "the first" while the tile it points at is still lit.
    function dropRef() {
        const w = widgetOf(node, "ref");
        if (w && armed()) w.value = FIRST_REF;
    }

    function choose(name) {
        const w = widgetOf(node, "asset");
        // Clicking the current one clears it, which is how you get back to
        // "the first" without knowing what the first is called.
        if (w) w.value = w.value === name ? "" : name;
        dropRef();
        node.setDirtyCanvas?.(true, true);
        render();
    }

    // One click does the whole selection: the asset AND which of its
    // references. "i select the category, the asset and then i have to select
    // the asset again in Pick. this is an extra click that is not necessary.
    // how about i click on the thing in asset focus? and it sends the freaking
    // image too" — so the thumbnail is the pick, and `ref_image` carries it.
    function chooseRef(assetName, file) {
        const w = widgetOf(node, "asset");
        if (w) w.value = assetName;
        const rw = widgetOf(node, "ref");
        if (rw) rw.value = file;
        node.setDirtyCanvas?.(true, true);
        render();
    }

    // One reference image, at strip size, big under the pointer. The tile is
    // the asset's own art, so hovering it is how you tell two similar assets
    // apart without leaving the node.
    function refThumb(asset, refsRoot, file, lit) {
        const path = `${refsRoot}/${file}`;
        const img = el("img",
            `width:${THUMB_PX}px;height:${THUMB_PX}px;object-fit:contain;`
            + `background:${HUB.surface1};border-radius:3px;flex:none;`
            + `border:1px solid ${lit ? HUB.accent : HUB.hairline};`
            + (lit ? `outline:1px solid ${HUB.accent};outline-offset:1px;` : ""));
        img.src = imageThumbUrl(path, THUMB_PX * 2);   // crisp on a retina panel
        img.loading = "lazy";
        img.draggable = false;
        img.title = lit ? `${file} — sent on ref_image` : file;
        // A missing or unreadable reference must not leave a broken-image glyph
        // sitting in the strip; an empty slot reads as "no art for this one".
        img.addEventListener("error", () => { img.style.visibility = "hidden"; });
        // Stopped from reaching the row, which picks the asset and CLEARS the
        // reference — the two handlers would otherwise undo each other.
        img.addEventListener("pointerdown", (e) => e.stopPropagation());
        img.addEventListener("click", (e) => {
            e.stopPropagation();
            hideHoverZoom();
            chooseRef(asset.name, file);
        });
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
            // Lit only on the picked asset: `ref` is a filename, and the same
            // one on a row that is not what runs would claim an image nothing
            // is going to send. Its first is what an unarmed pick emits, so
            // that is the one lit.
            const chosenFile = armed() || refs[0];
            for (const file of refs) {
                strip.appendChild(refThumb(asset, refsRoot, file,
                                           on && file === chosenFile));
            }
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
            // The reference rides with the asset it belongs to — the tile he
            // left lit is part of the pick, not a separate setting.
            const rw = widgetOf(node, "ref");
            if (rw && wanted.ref && refsOf(wanted.asset).includes(wanted.ref)) {
                rw.value = wanted.ref;
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
            .map((a) => ({
                ...a,
                canvas: a.canvas || known.get(a.name)?.canvas || "",
                refs: known.get(a.name)?.refs?.length
                    ? known.get(a.name).refs : (a.refs ?? []),
            }))
            .filter((a) => inCategory(a, narrow));
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
        // And the same for the reference under it: a filename the picked asset
        // does not have means the first anyway, so leaving it on the widget
        // only makes the node claim a file it is not sending.
        const listedRefs = assets.find((a) => a.name === pick)?.refs ?? [];
        if (armed() && listedRefs.length && !listedRefs.includes(armed())) {
            dropRef();
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
                const key = categoryRecipeOf(asset);
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
                (a) => a.name === chosen() && inCategory(a, narrowed()));
            if (!keep) {
                const w = widgetOf(node, "asset");
                if (w) w.value = "";
                dropRef();
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
            .filter((a) => inCategory(a, narrowed()))
            .map((a) => a.name),
    ]);
    if (assetWidget) {
        const previous = assetWidget.callback;
        assetWidget.callback = function (value) {
            previous?.apply(this, arguments);
            // The combo cannot hold "" as a label, so the sentinel is spelled
            // out on screen and emptied on the way to the node.
            if (assetWidget.value === ALL_ASSETS) assetWidget.value = "";
            // A reference belongs to the asset it was clicked on.
            dropRef();
            render();
        };
        // What reaches the node is the empty string the sentinel stands for.
        assetWidget.serializeValue = () =>
            (assetWidget.value === ALL_ASSETS ? "" : assetWidget.value);
        // A saved graph restores the empty string; show the sentinel instead
        // of a blank row.
        if (!assetWidget.value) assetWidget.value = ALL_ASSETS;
    }

    // Which reference the click armed, said in words. The tile is how you pick
    // one, but a lit border on a 30px thumbnail is not a filename — and this is
    // the only widget that says which image `ref_image` is about to send.
    const refWidget = comboify(node, "ref",
                               () => [FIRST_REF, ...refsOf(chosen())]);
    if (refWidget) {
        const previous = refWidget.callback;
        refWidget.callback = function (value) {
            previous?.apply(this, arguments);
            // Kept as the label rather than emptied on the spot: this widget
            // is read to find out what is armed, and a blank row answers
            // nothing. `serializeValue` is where it becomes "".
            if (!refWidget.value) refWidget.value = FIRST_REF;
            render();
        };
        refWidget.serializeValue = () =>
            (refWidget.value === FIRST_REF ? "" : refWidget.value);
        if (!refWidget.value) refWidget.value = FIRST_REF;
        hideWidget(refWidget);
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
        node._symFocusCategories = [];
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
        if (!FOCUS_CLASSES.includes(nodeData.name)) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            // The same project/month/feature front end the order read has, so the
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
                                    asset: value("asset"),
                                    ref: value("ref") };
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
    node._symFocusCategories = Array.isArray(detail.categories)
        ? detail.categories.map(String) : [];
    // Which event those assets came from. The focus panel reads the widget,
    // but a Task fed by a WIRE has no feature of its own — the run is the only
    // thing that can say what it was given.
    node._symFocusFeature = String(detail.feature ?? "");
    // The run's own reference root, so the thumbnails load from a graph whose
    // source node has published nothing to the canvas.
    node._symFocusRefsRoot = String(detail.refs_root ?? "");
    node._symRenderFocus?.();
});


// ===========================================================================
// Task — the browser.
//
// The same selection Asset Focus makes, made in a SIDEBAR instead of four
// dropdowns: month, event, category and asset as a tree, the client's own
// reference art in the pane beside it, and the prompt they wrote under it.
// The node emits the pick on ONE wire (`specs`) plus the two things you are
// looking at while you browse, and a Task Specs on the end of that wire fans
// the rest back out — so the node you browse on is not thirteen sockets tall.
//
// It lives in THIS file, not a new one: a new `web/js` file never reaches the
// Modal sandbox (the Volume sync updates files a running sandbox already has
// and never creates one), and `hideWidget` is exported from here and imported
// by three other panels.
// ===========================================================================
export const TASK_CLASS = "SymbioticaTask";
const TASK_MIN_W = 560;
// The sidebar's width and fold are VIEW state, so they ride on properties.
// Widgets would shift the saved values of every workflow holding the node.
const TASK_SIDE = "symbiotica_task_sidebar";
const TASK_SHUT = "symbiotica_task_shut";
// The strip under the big view. Two-up on a retina panel, same as the focus
// panel's rows, so a reference reads the same size wherever it is drawn.
const STRIP_PX = 40;

// The tree's four levels as one flat list of rows, top to bottom, in the order
// the ORDER gives them: months calendar-wise from the server, events and
// categories in first-appearance order down the sheet. Never alphabetical —
// `walkTree` sorts, and the sheet's order is the order he reads.
//
// Rows are built here rather than by `walkTree` for a second reason: that
// function derives parentage from a slash-joined key, and his sheet holds
// names with slashes in them and two rows that flatten to the same key. A row
// is its own object; nothing is looked up by its path.
function taskRows(node, state) {
    const rows = [];
    const month = state.month || (state.months[0] ?? "");
    for (const m of state.months) {
        const openMonth = m === month;
        rows.push({ kind: "month", label: m, month: m, open: openMonth,
                    rel: m });
        if (!openMonth) continue;
        const wantFeature = featureKey(widgetOf(node, "feature")?.value);
        for (const event of state.events) {
            const key = featureKey(event.feature);
            const label = event.eventName
                ? `${event.feature} — ${event.eventName}` : event.feature;
            const openEvent = key === wantFeature
                || (!wantFeature && event === state.events[0]);
            rows.push({ kind: "feature", label, month: m, feature: label,
                        open: openEvent, rel: `${m}/${label}` });
            if (!openEvent) continue;
            // Named assets only, and grouped the way `assets_by_category`
            // groups them — the panel has to show the run order it describes.
            // The nine unnamed padding rows in a real sheet are dropped here,
            // exactly as Python drops them.
            const groups = new Map();
            for (const a of event.assets ?? []) {
                const name = String(a.assetName ?? "").trim();
                if (!name) continue;
                const key2 = categoryRecipeOf(a) || "uncategorised";
                if (!groups.has(key2)) groups.set(key2, []);
                groups.get(key2).push({
                    name,
                    category: a.category ?? "",
                    canvas: a.canvas ?? "",
                    prompt: String(a.prompt ?? ""),
                    refs: (a.refFiles ?? []).map(String),
                });
            }
            const pick = String(widgetOf(node, "category")?.value ?? "").trim();
            const chosen = String(widgetOf(node, "asset")?.value ?? "").trim();
            for (const [recipe, members] of groups) {
                const holdsPick = members.some((a) => a.name === chosen);
                const openCat = holdsPick
                    || recipe.toLowerCase() === pick.toLowerCase();
                rows.push({ kind: "category", label: recipe, count: members.length,
                            month: m, feature: label, category: recipe,
                            open: openCat, rel: `${m}/${label}/${recipe}` });
                if (!openCat) continue;
                for (const a of members) {
                    rows.push({ kind: "asset", label: a.name, asset: a,
                                month: m, feature: label, category: recipe,
                                rel: `${m}/${label}/${recipe}/${a.name}` });
                }
            }
        }
    }
    return rows;
}

function taskPanel(node) {
    injectHubStyles();

    // Everything the tree draws, re-read from the node on every render: the
    // month list the project holds, and the events of the ONE month the
    // widget names. One month is parsed at a time — the `month` widget is
    // what Python reads, so expanding another month IS picking it, and there
    // is never a second references root to confuse a thumbnail with.
    const state = { months: [], events: [], month: "" };
    const readState = () => {
        // The month this tree is SHOWING: the one picked, else the one the
        // parse actually read, else the first the project holds. The parse is
        // what carries the order, and the month list is a separate, smaller
        // request — so the tree must never wait on the list to draw what the
        // parse already gave it. It did, and the pane counted nine assets
        // beside a tree with no month to hang them on.
        state.month = String(widgetOf(node, "month")?.value ?? "").trim()
            || String(node._symOrderMonth ?? "").trim()
            || String((node._symMonths ?? [])[0] ?? "");
        // Every month the project holds, with the one on screen in it whether
        // the list has arrived or not.
        state.months = (node._symMonths ?? []).map(String);
        if (state.month && !state.months.includes(state.month)) {
            state.months = [state.month, ...state.months];
        }
        state.events = Array.isArray(node._symEvents) ? node._symEvents : [];
        // Nothing parsed on the canvas, but a RUN reported what it chose from:
        // the only list this node has when the path resolves on the SERVER and
        // not here. It arrives flat, so it stands in as the event it came from.
        if (!state.events.length && node._symFocusAssets?.length) {
            state.events = [{
                feature: featureKey(node._symFocusFeature) || "the wired event",
                eventName: "",
                assets: node._symFocusAssets.map((a) => ({
                    assetName: a.name, category: a.category ?? "",
                    canvas: a.canvas ?? "", prompt: String(a.prompt ?? ""),
                    refFiles: a.refs ?? [],
                })),
            }];
            if (!state.months.length) state.months = [state.month || "this order"];
        }
    };

    // Every asset in the MONTH, by its display path — what the search box
    // offers. Read off the parse rather than off the drawn rows: the tree only
    // builds rows under an open category, and a search that can only find what
    // is already on screen is not a search. A duplicate name resolves to the
    // last one, which is what Python's own `raw` map does with the same sheet.
    const searchable = () => {
        const out = new Map();
        const month = String(widgetOf(node, "month")?.value ?? "").trim();
        for (const event of state.events) {
            const feature = event.eventName
                ? `${event.feature} — ${event.eventName}` : event.feature;
            for (const a of event.assets ?? []) {
                const name = String(a.assetName ?? "").trim();
                if (!name) continue;
                const category = categoryRecipeOf(a) || "uncategorised";
                out.set(`${feature}/${category}/${name}`, {
                    kind: "asset", label: name, month, feature, category,
                    asset: { name, category: a.category ?? "",
                             canvas: a.canvas ?? "",
                             prompt: String(a.prompt ?? ""),
                             refs: (a.refFiles ?? []).map(String) },
                });
            }
        }
        return out;
    };

    // A search hit can be in an event the tree is not showing, so taking one
    // moves the whole selection there — the same act as clicking down to it.
    function chooseFound(row) {
        const held = featureKey(widgetOf(node, "feature")?.value);
        if (featureKey(row.feature) !== held) {
            put("feature", row.feature);
            node._symFocusAssets = [];
            node._symFocusCategories = [];
            node._symRefreshOrder?.({ explicit: true });
        }
        put("asset", row.label);
        put("category", "");
        put("ref", "");
        node.setDirtyCanvas?.(true, true);
        render();
    }

    const shell = sidebarShell(node, {
        sideProp: TASK_SIDE, shutProp: TASK_SHUT, sideDefault: 240,
        repaint: () => render(),
        // Above both panes, so it survives the fold — which is how this node
        // sits once an asset is picked and the pane is the whole of it.
        search: {
            placeholder: "Search assets…",
            list: () => [...searchable().keys()],
            onPick: (rel) => {
                const row = searchable().get(rel);
                if (row) chooseFound(row);
            },
        },
        headButtons: [
            iconButton("refresh", "Re-read this project's orders", () => {
                // The button, not a second fetch: it is a real widget holding
                // a saved slot, it renames itself while it reads, and two
                // paths into the same parse is two answers to keep in step.
                const btn = node.widgets?.find(
                    (w) => w.name?.endsWith?.("Read folder"));
                btn?.callback?.();
            }),
        ],
    });
    const { container, tree } = shell;

    // --- the pane -----------------------------------------------------------
    const crumb = el("div", `flex:1;min-width:0;${ONE_LINE}`
        + `font:11px ${HUB.mono};color:${HUB.inkSubtle};`);
    const runs = el("div", `flex:none;font:10px ${HUB.mono};`
        + `color:${HUB.inkTertiary};`);
    const mainHead = el("div", "display:flex;align-items:center;gap:6px;"
        + `padding:3px 6px;flex:none;background:${HUB.surface2};`
        + `border-bottom:1px solid ${HUB.hairline};`);
    mainHead.append(crumb, runs);

    // The reference: a strip of every file the client sent for this asset,
    // and the armed one big underneath. Clicking a tile is the whole pick —
    // the asset AND which of its art `ref_image` carries.
    const strip = el("div", "display:flex;gap:4px;flex-wrap:wrap;flex:none;"
        + `padding:5px 6px;border-bottom:1px solid ${HUB.hairline};`
        + "max-height:96px;overflow-y:auto;");
    const view = el("div", "flex:1;min-height:60px;display:flex;padding:6px;"
        + "align-items:center;justify-content:center;overflow:hidden;"
        + `background:${HUB.surface1};`);
    const shown = el("img", "max-width:100%;max-height:100%;object-fit:contain;"
        + `display:none;background-image:${CHECKER};background-size:16px 16px;`
        + "background-position:0 0,0 8px,8px -8px,-8px 0;");
    shown.alt = "the client reference";
    // What the client wrote, under the art they sent — the two halves of the
    // brief, on screen together. Read-only: the order sheet is theirs.
    const promptHead = el("div", `flex:none;padding:3px 6px;`
        + `font:10px ${HUB.font};letter-spacing:.06em;text-transform:uppercase;`
        + `color:${HUB.inkSubtle};background:${HUB.surface2};`
        + `border-top:1px solid ${HUB.hairline};`, "client prompt");
    const promptBox = el("div", "flex:none;max-height:38%;min-height:42px;"
        + `overflow:auto;padding:6px 8px;font:11px ${HUB.font};`
        + `color:var(--input-text, ${HUB.ink});white-space:pre-wrap;`
        + `background:${HUB.surface1};`);
    promptBox.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });
    shell.main.append(mainHead, strip, view, promptHead, promptBox);

    // No `computeSize`: LiteGraph builds a node's MINIMUM height by summing
    // its widgets and prefers `computeSize` over `computeLayoutSize`, so
    // anything returned there becomes a floor the corner cannot drag past.
    node.addDOMWidget("task_panel", "sym_task", container, {
        serialize: false, hideOnZoom: true,
        getMinHeight: () => 60,
    });
    const syncPanelWidth = pinPanelWidth(node, container);
    node.size[0] = Math.max(node.size[0], TASK_MIN_W);

    // --- what the tree writes ------------------------------------------------
    // The widgets are the storage and what Python reads; the tree is the only
    // way to set them. They stay plain text widgets — a combo drops a value
    // that is not among its options, and hiding one does not stop it.
    const put = (name, value) => {
        const w = widgetOf(node, name);
        if (w) w.value = value;
    };

    function chooseMonth(row) {
        if (String(widgetOf(node, "month")?.value ?? "") === row.month) {
            render();
            return;
        }
        put("month", row.month);
        // A new month is a new order: nothing chosen in the old one survives.
        put("feature", "");
        put("category", "");
        put("asset", "");
        put("ref", "");
        node._symFocusAssets = [];
        node._symFocusCategories = [];
        // ONE path into the parse: the wrapper below, which re-draws when it
        // lands. The widget's own chained callback reaches `refreshOrderSpecs`
        // directly and would answer without telling the panel.
        node._symRefreshOrder?.({ explicit: true });
        render();
    }

    function chooseFeature(row) {
        put("feature", row.feature);
        put("category", "");
        put("asset", "");
        put("ref", "");
        node._symFocusAssets = [];
        node._symFocusCategories = [];
        node._symRefreshOrder?.({ explicit: true });
        render();
    }

    // A category row is the "all assets of this type" run — what the old
    // panel's `all` button said. `runs N` in the pane header is where you read
    // what that means before you queue it.
    function chooseCategory(row) {
        const held = String(widgetOf(node, "category")?.value ?? "").trim();
        put("category", held === row.category ? "" : row.category);
        put("asset", "");
        put("ref", "");
        render();
    }

    // An asset row is one asset. `category` is CLEARED rather than set to the
    // asset's own: with a name chosen the narrowing decides nothing, and a
    // stale one that excludes the name is a hard refusal at queue time.
    //
    // Clicking the chosen one again clears it — how you get back to "all of
    // them" without knowing what the first is called — and the narrowing then
    // becomes its CATEGORY rather than nothing: an empty one closes the level
    // the row is on, which takes the row you just clicked off the screen.
    function chooseAsset(row) {
        const held = String(widgetOf(node, "asset")?.value ?? "").trim();
        const same = held === row.label;
        put("asset", same ? "" : row.label);
        put("category", same ? row.category : "");
        // A filename belongs to ONE asset: carried over it would name nothing
        // in the new one's list and silently mean "the first" while the tile
        // it points at is still lit.
        put("ref", "");
        node.setDirtyCanvas?.(true, true);
        render();
    }

    function chooseRef(row, file) {
        put("asset", row.label);
        put("category", "");
        put("ref", file);
        node.setDirtyCanvas?.(true, true);
        render();
    }

    // --- drawing -------------------------------------------------------------
    // A chevron on the three container levels, an empty box of the same width
    // on an asset row, so every name in a level starts at the same x.
    function chevron(row) {
        const box = el("span", "flex:none;display:flex;width:12px;"
            + `color:${HUB.inkTertiary};`);
        if (row.kind !== "asset") {
            box.innerHTML = svgIcon(row.open ? ICON.collapse : ICON.expand, 11);
            box.style.transform = row.open ? "rotate(90deg)" : "";
        }
        return box;
    }

    function refTile(row, file, lit) {
        const path = `${refsRoot()}/${file}`;
        const img = el("img",
            `width:${STRIP_PX}px;height:${STRIP_PX}px;object-fit:contain;`
            + `background:${HUB.mat};border-radius:3px;flex:none;cursor:pointer;`
            + `border:1px solid ${lit ? HUB.accent : HUB.hairline};`
            + (lit ? `outline:1px solid ${HUB.accent};outline-offset:1px;` : ""));
        img.src = imageThumbUrl(path, STRIP_PX * 2);
        img.loading = "lazy";
        img.draggable = false;
        img.title = lit ? `${file} — sent on ref_image` : file;
        // A reference the disk has lost must not leave a broken-image glyph in
        // the strip; an empty slot reads as "no art for this one".
        img.addEventListener("error", () => { img.style.visibility = "hidden"; });
        img.addEventListener("pointerdown", (e) => e.stopPropagation());
        img.addEventListener("click", (e) => {
            e.stopPropagation();
            hideHoverZoom();
            chooseRef(row, file);
        });
        return img;
    }

    const refsRoot = () => (node._symFocusAssets?.length
        ? node._symFocusRefsRoot : "") || node._symRefsRoot || "";

    // The reference files for one asset, from whichever list holds them: a run
    // pushes them and the canvas parse publishes them, and between a restart
    // and the first queue only one of the two exists.
    function refsFor(row) {
        if (row.asset?.refs?.length) return row.asset.refs;
        const hit = (node._symFocusAssets ?? []).find((a) => a.name === row.label);
        return (hit?.refs ?? []).map(String);
    }

    function promptFor(row) {
        if (row.asset?.prompt) return row.asset.prompt;
        const hit = (node._symFocusAssets ?? []).find((a) => a.name === row.label);
        return String(hit?.prompt ?? "");
    }

    function selectedRow(rows) {
        const chosen = String(widgetOf(node, "asset")?.value ?? "").trim();
        if (!chosen) return null;
        return rows.find((r) => r.kind === "asset" && r.label === chosen) ?? null;
    }

    // What the node would emit right now: the open event's named assets,
    // narrowed by `category` — the list `_focus_items` builds on the Python
    // side. NOT the rows on screen: a category has to be OPEN to have asset
    // rows under it, so counting those read `runs` as nothing and the pane as
    // "no assets" on a node that is showing two categories an inch to the
    // left. A node has to show what it holds.
    function runList() {
        const wantFeature = featureKey(widgetOf(node, "feature")?.value)
            || featureKey(node._symFocusFeature);
        const event = state.events.find(
            (e) => featureKey(e.feature) === wantFeature) ?? state.events[0];
        const narrow = String(widgetOf(node, "category")?.value ?? "").trim();
        return (event?.assets ?? [])
            .filter((a) => String(a.assetName ?? "").trim())
            .filter((a) => inCategory({ category: a.category, canvas: a.canvas },
                                      narrow));
    }

    function drawPane(rows) {
        const row = selectedRow(rows);
        const inRun = runList();
        const narrow = String(widgetOf(node, "category")?.value ?? "").trim();
        // Say what the node will actually emit, not just what is listed.
        runs.textContent = inRun.length
            ? `runs ${row ? 1 : inRun.length}` : "";
        crumb.textContent = row
            ? `${row.month} / ${row.feature} / ${row.category} / ${row.label}`
            : (narrow ? `${narrow} · every asset` : "every asset in the event");

        strip.replaceChildren();
        shown.style.display = "none";
        view.replaceChildren(shown);
        promptBox.replaceChildren();

        if (!row) {
            view.appendChild(emptyState(inRun.length
                ? "Pick an asset in the tree."
                : "No assets to show yet."));
            promptBox.appendChild(emptyState("—"));
            return;
        }

        const files = refsFor(row);
        const armed = String(widgetOf(node, "ref")?.value ?? "").trim();
        const lit = files.includes(armed) ? armed : files[0];
        if (!files.length || !refsRoot()) {
            strip.appendChild(emptyState("no client reference for this asset"));
            view.appendChild(emptyState("nothing to show"));
        } else {
            for (const file of files) strip.appendChild(refTile(row, file, file === lit));
            const path = `${refsRoot()}/${lit}`;
            shown.src = imageFullUrl(path);
            shown.style.display = "";
            shown.title = lit;
            attachHoverZoom(shown, () => ({
                w: shown.naturalWidth, h: shown.naturalHeight,
                label: row.label, hint: lit,
                placeholder: shown.src,
                src: () => imageFullUrl(path),
            }));
        }
        promptHead.textContent = `client prompt${row.asset?.canvas
            ? ` · ${row.asset.canvas}` : ""}`;
        const text = promptFor(row);
        promptBox.appendChild(text
            ? el("div", "", text)
            : emptyState("no prompt on this row"));
    }

    function render() {
        readState();
        hideHoverZoom();
        // Ask for whichever half has not arrived. Both are one-shot at node
        // creation and only a TYPED project_path re-fires them; a path that
        // comes in on a wire — a Local Path node, a Local/Modal switch, a Get
        // Hub — resolves later than that, and nothing asked again.
        ensureRead();
        const folded = shell.layout();
        const rows = taskRows(node, state);

        tree.replaceChildren();
        if (!folded) {
            if (!rows.length) {
                const project = widgetOf(node, "project_path");
                // A path can still ARRIVE on a wire — a Local/Modal switch,
                // a Get Hub — which `resolveProjectPath` walks. Empty on both
                // counts is the only case with nothing to say.
                const hasProject = Boolean(project?.value?.trim?.())
                    || node.inputs?.some((i) => i.name === "project_path"
                                             && i.link != null);
                tree.appendChild(emptyState(hasProject
                    ? "reading this project's orders…"
                    : "set project_path — the folder with an orders/ subfolder"));
            }
            const chosen = String(widgetOf(node, "asset")?.value ?? "").trim();
            const narrow = String(widgetOf(node, "category")?.value ?? "").trim();
            for (const row of rows) {
                const on = (row.kind === "asset" && row.label === chosen)
                    || (row.kind === "category" && !chosen
                        && row.category.toLowerCase() === narrow.toLowerCase());
                tree.appendChild(treeRow({
                    kind: row.kind, rel: row.rel,
                    depth: ["month", "feature", "category", "asset"].indexOf(row.kind),
                    tone: on ? HUB.selBg : "",
                    labelColour: on ? HUB.selInk : `var(--input-text, ${HUB.ink})`,
                    lead: chevron(row),
                    // The count rides in the label: `treeRow` hides its
                    // `actions` until the pointer is on the row, and a badge
                    // you have to hover for is a badge nobody reads.
                    label: row.count ? `${row.label} · ${row.count}` : row.label,
                    onClick: () => {
                        if (row.kind === "month") chooseMonth(row);
                        else if (row.kind === "feature") chooseFeature(row);
                        else if (row.kind === "category") chooseCategory(row);
                        else chooseAsset(row);
                    },
                }));
            }
        }
        drawPane(rows);
        shell.search?.refresh?.();
        // Redraw, never resize: the panel's height belongs to his drag.
        requestAnimationFrame(() => {
            if (node.size[0] < TASK_MIN_W) node.setSize?.([TASK_MIN_W, node.size[1]]);
            syncPanelWidth();
            node.setDirtyCanvas?.(true, true);
        });
    }

    // Both halves of the read, once per project: the ORDER (`parse-order`,
    // which is where every asset, prompt and reference comes from) and the
    // MONTH LIST (`list-orders`, which only names the other months you can
    // switch to). Guarded on the resolved path, so the render that follows
    // each answer does not ask again.
    let readFor = null;
    function ensureRead() {
        const project = resolveProjectPath(node);
        if (!project || readFor === project) return;
        if (state.events.length && state.months.length) { readFor = project; return; }
        readFor = project;
        Promise.resolve(node._symRefreshMonths?.()).catch(() => {});
        Promise.resolve(node._symRefreshOrder?.({ explicit: true })).catch(() => {});
    }

    node._symRenderFocus = render;
    // Every parse re-draws the tree. `publishOrder` announces a new order to
    // every node BUT the one that read it — and this node reads its own, so
    // the announcement never comes back round. Chaining the parse itself
    // covers every way into it at once: the month and feature widgets, the
    // "Read folder" button, and the ladder that retries while a wired
    // project_path is still resolving.
    const parse = node._symRefreshOrder;
    node._symRefreshOrder = (opts) =>
        Promise.resolve(parse?.(opts)).then((r) => { render(); return r; })
                                      .catch(() => { render(); });
    // And the month list, which is a second request with a second answer: the
    // tree's top level is drawn from it.
    const months = node._symRefreshMonths;
    node._symRefreshMonths = () =>
        Promise.resolve(months?.()).then((r) => { render(); return r; })
                                   .catch(() => { render(); });
    render();
}

registerSymbioticaExtension(app, {
    name: "symbiotica.task",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== TASK_CLASS) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            // The project/month/feature front end, the "Read folder" button
            // and the auto-read ladder that fills the pickers without a
            // click. It only acts once `project_path` resolves, so a node fed
            // by a wire is unaffected.
            wireOrderSpecs(this);
            // Every widget the tree drives is hidden but PRESENT: they are
            // what Python reads and what a saved workflow restores, and
            // removing one would shift every value after it. `project_path`
            // stays visible and typeable — it is the one thing the tree
            // cannot tell you.
            for (const name of ["month", "feature", "category", "asset", "ref"]) {
                hideWidget(widgetOf(this, name));
            }
            hideWidget(this.widgets?.find((w) => w.name?.endsWith?.("Read folder")));
            // `month` and `feature` were made combos by `wireOrderSpecs`, and
            // a combo drops a value that is not among its options — which is
            // every value, until the first parse lands. Hold the value open.
            for (const name of ["month", "feature"]) {
                const w = widgetOf(this, name);
                if (!w?.options) continue;
                const inner = w.options.values;
                w.options.values = () => {
                    const list = (typeof inner === "function" ? inner() : inner) ?? [];
                    const held = String(w.value ?? "");
                    return held && !list.includes(held) ? [...list, held] : list;
                };
            }
            taskPanel(this);
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            onConfigure?.apply(this, arguments);
            queueMicrotask(() => this._symRenderFocus?.());
        };

        // Wiring a path IN is the moment the project becomes knowable.
        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (type, index, connected,
                                                            link, ioSlot) {
            onConnectionsChange?.apply(this, arguments);
            if (ioSlot?.name === "project_path") {
                this._symAskedFor = null;
                queueMicrotask(() => this._symRefreshOrder?.({ explicit: true }));
            }
        };
    },
});
