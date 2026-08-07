// ABOUTME: Symbiotica Pick node UI — the asset's own render folder listed on the
// ABOUTME: node body as numbered thumbnails, ticked to choose which files travel
// ABOUTME: downstream. It holds nothing: every tile is a file already on disk.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { HUB, injectHubStyles, ghostButtonCss } from "./hub_theme.js";
import { attachHoverZoom, el, emptyState, errorLine, hideHoverZoom }
    from "./browser_chrome.js";

const NODE_CLASS = "SymbioticaPick";
// Widgets this node gained after graphs were already saved, with the value each
// falls back to. A saved workflow carries one value per widget it knew about,
// applied by position, so anything appended since comes back unset.
const APPENDED_WIDGETS = [["show", "approved"]];
const MIN_NODE_W = 340;
const PANEL_MIN = 44;        // an empty picker still shows its own message
const DEFAULT_NODE_H = 460;  // only for a node that has never been given a height
const SIZES = { S: 64, M: 108, L: 184 };
const DEFAULT_SIZE = "S";

const widgetOf = (node, name) => node.widgets?.find((w) => w.name === name);

// Keep the /api/ prefix: ComfyUI mirrors custom routes under /api/ locally AND
// the Modal gateway proxies /api/* only, so a root-level /symbiotica/* would
// blank every thumbnail there.
const thumbUrl = (path, px) => api.apiURL(
    `/symbiotica/pick-thumb?px=${px}&path=${encodeURIComponent(path)}`);
const fullUrl = (path) => api.apiURL(
    `/symbiotica/local-image?path=${encodeURIComponent(path)}`);

async function fetchJson(url, options) {
    const res = await api.fetchApi(url, options);
    if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.error ?? res.statusText);
    return res.json();
}

// `single` is for editing: you edit the image you are working on, so ticking
// replaces the previous pick instead of adding to it.
const isSingle = (node) =>
    (widgetOf(node, "mode")?.value?.trim?.() || "multiple") === "single";

// The ticks live on the `selection` widget as a JSON array of FILE NAMES, so
// they are saved with the workflow: reopening a graph shows the same picks the
// run was queued with. Names rather than positions, because a new render
// landing in the folder shifts every position after it and would silently
// re-point every tick at its neighbour.
function readTicks(node) {
    try {
        const raw = JSON.parse(widgetOf(node, "selection")?.value || "[]");
        return new Set(Array.isArray(raw) ? raw.map(String) : []);
    } catch {
        return new Set();
    }
}

function writeTicks(node, ticks) {
    const w = widgetOf(node, "selection");
    if (w) w.value = JSON.stringify([...ticks]);
    node.setDirtyCanvas?.(true, true);
}

function thumbSize(node) {
    const key = node.properties?.symPickThumb;
    return SIZES[key] ? key : DEFAULT_SIZE;
}

function pickPanel(node) {
    injectHubStyles();

    // height:100% — the layout gives the widget a box, this fills it, and the
    // grid scrolls inside. Sizing to content instead is what used to drive the
    // node's height.
    const container = el("div", "box-sizing:border-box;width:100%;height:100%;"
        + "overflow-y:auto;overflow-x:hidden;");
    // ComfyUI sizes the container from computeSize, so its scrollHeight only
    // echoes its own box. Measure this inner list — its natural height IS the
    // content height.
    const list = el("div", `padding:2px;font:11px ${HUB.font};color:${HUB.ink};`);
    container.appendChild(list);
    container.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });

    // THE NODE'S HEIGHT IS HIS, AND IT MUST BE DRAGGABLE BOTH WAYS.
    //
    // LiteGraph derives a node's MINIMUM height by summing its widgets, and
    // for each widget it prefers `computeSize` over `computeLayoutSize`:
    //
    //     if (w.computeSize) t += w.computeSize(width)[1]
    //     else if (w.computeLayoutSize) t += w.computeLayoutSize(node).minHeight
    //
    // So a `computeSize` that answers with the space currently below the panel
    // makes the minimum equal the current height, and the node can be dragged
    // taller but never shorter. That is what "i am pulling on the corner and
    // it cannot be made smaller" was, here and in the prompt editor.
    //
    // The panel therefore declares a small CONSTANT floor and no computeSize
    // at all: the layout hands it whatever is left of the node's body, the
    // element fills that box, and the grid scrolls inside it.
    node.addDOMWidget("pick_panel", "sym_pick", container, {
        serialize: false,
        hideOnZoom: true,
        getMinHeight: () => PANEL_MIN,
    });
    // Redraw, never resize. The only thing this may change is a node so narrow
    // that a tile cannot fit, and a node that has never been given a height.
    const refit = () => requestAnimationFrame(() => {
        if (node.size[0] < MIN_NODE_W) {
            node.setSize?.([MIN_NODE_W, node.size[1]]);
        }
        node.setDirtyCanvas?.(true, true);
    });
    node.size[0] = Math.max(node.size[0], MIN_NODE_W);
    // A starting height for a node that has never had one. Never a floor: a
    // graph reopening keeps whatever height it was saved at, and dragging goes
    // all the way down to the widgets plus PANEL_MIN.
    if (!node.size[1] || node.size[1] < PANEL_MIN) {
        node.size[1] = DEFAULT_NODE_H;
    }

    let images = [];
    let folder = "";
    // Listing another picker's approvals rather than a folder of its own.
    let shortlist = false;
    let error = "";
    let notice = "";
    let loading = false;
    // A first load can land before the graph has finished configuring, while
    // the node still carries a placeholder id — and the server answers by node
    // id, so that reads as "no folder". Retry a few times rather than sit on
    // that answer forever, with the images right there on disk.
    let loads = 0;
    let loadedOk = false;

    async function load(explicitFolder = "") {
        loading = true;
        loads += 1;
        render();
        try {
            const q = new URLSearchParams({ node_id: String(node.id) });
            if (explicitFolder) q.set("folder", explicitFolder);
            const data = await fetchJson(`/symbiotica/pick-list?${q.toString()}`);
            images = Array.isArray(data.images) ? data.images : [];
            folder = data.folder || "";
            shortlist = Boolean(data.shortlist);
            loadedOk = images.length > 0;
            error = "";
        } catch (e) {
            error = e.message || "could not list that folder";
        } finally {
            loading = false;
            render();
        }
        if (!loadedOk && !error && loads < 4) {
            setTimeout(() => { if (!loadedOk) load(explicitFolder); }, 400 * loads);
        }
    }
    node._symReloadPick = load;
    node._symPickNote = (text) => { notice = String(text || ""); render(); };

    const stageOf = () => widgetOf(node, "stage")?.value?.trim?.() || "";

    // A stage names a different folder, so the list has to be fetched again.
    const stageWidget = widgetOf(node, "stage");
    if (stageWidget) {
        const previous = stageWidget.callback;
        stageWidget.callback = function () {
            previous?.apply(this, arguments);
            load();
        };
    }
    const oneAtATime = () => isSingle(node);

    function toggle(name) {
        const ticks = readTicks(node);
        if (ticks.has(name)) {
            // Clicking the chosen one clears it, which is how you change your
            // mind without having to pick something else first.
            ticks.delete(name);
        } else if (oneAtATime()) {
            // Replace rather than add — including ticks left over from another
            // asset, which are not travelling anywhere either.
            ticks.clear();
            ticks.add(name);
        } else {
            ticks.add(name);
        }
        writeTicks(node, ticks);
        render();
    }

    // --- header ------------------------------------------------------------
    function renderHead(ticks) {
        const bar = el("div",
            `display:flex;align-items:center;gap:6px;padding:2px 2px 4px;color:${HUB.inkSubtle};`);
        const here = images.filter((i) => ticks.has(i.id)).length;
        bar.append(el("span", "flex:1;min-width:0;overflow:hidden;"
            + "text-overflow:ellipsis;white-space:nowrap;",
            images.length
                ? `${images.length} in folder · ${here} ticked`
                : `nothing listed yet (node ${node.id})`));

        // A tick whose file is no longer in the folder is not sent on, and is
        // invisible here — saying so beats a count that does not add up.
        const missing = ticks.size - here;
        if (missing > 0) {
            const drop = el("button", ghostButtonCss + "padding:1px 7px;flex:none;",
                            `${missing} missing ✕`);
            drop.className = "sym-btn";
            drop.title = `${missing} tick(s) name files that are not in this `
                + "folder, so they are not sent on. Click to forget them.";
            drop.addEventListener("pointerdown", (e) => e.stopPropagation());
            drop.addEventListener("click", () => {
                const present = new Set(images.map((i) => i.id));
                writeTicks(node, new Set([...ticks].filter((t) => present.has(t))));
                render();
            });
            bar.appendChild(drop);
        }

        // What this picker is looking at, and how many it takes. Both are
        // widgets, but a widget is a thing to read; a chip is a thing you see.
        const label = shortlist ? "shortlist" : (stageOf() || "renders");
        const chip = el("div",
            `flex:none;padding:1px 6px;border-radius:3px;font:10px ${HUB.font};`
            + `background:${HUB.surface1};color:${HUB.inkSubtle};`
            + `border:1px solid ${HUB.hairline};`,
            oneAtATime() ? `${label} · one` : label);
        chip.title = (shortlist
            ? "listing exactly what the picker upstream approved"
            : `listing ${stageOf() ? `this asset's \`${stageOf()}\` step`
                                   : "this asset's own renders"}`)
            + (oneAtATime()
                ? "\nsingle: ticking replaces the previous pick"
                : "");
        bar.appendChild(chip);

        for (const key of Object.keys(SIZES)) {
            const b = el("button", ghostButtonCss + "padding:1px 6px;flex:none;"
                + (thumbSize(node) === key ? `border-color:${HUB.accent};color:${HUB.ink};` : ""),
                         key);
            b.className = "sym-btn";
            b.title = `${SIZES[key]}px thumbnails`;
            b.addEventListener("pointerdown", (e) => e.stopPropagation());
            b.addEventListener("click", () => {
                node.properties = node.properties ?? {};
                node.properties.symPickThumb = key;
                render();
            });
            bar.appendChild(b);
        }

        const reload = el("button", ghostButtonCss + "padding:1px 6px;flex:none;", "⟳");
        reload.className = "sym-btn";
        reload.title = "Re-read the folder";
        reload.addEventListener("pointerdown", (e) => e.stopPropagation());
        reload.addEventListener("click", () => load());
        bar.appendChild(reload);

        if (here) {
            // Never delete: the tiles ARE the renders, several of them paid
            // for and unrepeatable, so the worst this button may do is file
            // them one folder deeper. Two clicks, because it is the only
            // control here that touches the disk at all.
            const armed = node._symDiscardArmed;
            const bin = el("button", ghostButtonCss + "padding:1px 8px;flex:none;"
                + (armed ? `border-color:${HUB.accent};color:${HUB.ink};` : ""),
                           armed ? `discard ${here}?` : "discard");
            bin.className = "sym-btn";
            bin.title = `Move the ${here} ticked file(s) into \`discarded/\` `
                + "under this folder. They leave the grid, not the disk — drag "
                + "them back to undo.";
            bin.addEventListener("pointerdown", (e) => e.stopPropagation());
            bin.addEventListener("click", async () => {
                if (!node._symDiscardArmed) {
                    node._symDiscardArmed = true;
                    render();
                    setTimeout(() => {
                        if (node._symDiscardArmed) {
                            node._symDiscardArmed = false;
                            render();
                        }
                    }, 4000);
                    return;
                }
                node._symDiscardArmed = false;
                const gone = images.filter((i) => ticks.has(i.id))
                                   .map((i) => i.id);
                try {
                    const res = await fetchJson("/symbiotica/pick-discard", {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ node_id: String(node.id),
                                               names: gone }),
                    });
                    // A discarded file must not stay ticked: the tick would
                    // read as "missing" forever and never travel anywhere.
                    const dropped = new Set(gone);
                    writeTicks(node, new Set([...readTicks(node)]
                        .filter((t) => !dropped.has(t))));
                    notice = `${(res.discarded || []).length} moved to `
                        + "discarded/";
                } catch (e) {
                    error = e.message || "could not discard those";
                }
                await load();
            });
            bar.appendChild(bin);
        }

        if (ticks.size) {
            const clear = el("button", ghostButtonCss + "padding:1px 8px;flex:none;",
                             "untick all");
            clear.className = "sym-btn";
            clear.title = "Clear every tick. The images on disk are untouched.";
            clear.addEventListener("pointerdown", (e) => e.stopPropagation());
            clear.addEventListener("click", () => { writeTicks(node, new Set()); render(); });
            bar.appendChild(clear);
        }
        return bar;
    }

    // --- grid --------------------------------------------------------------
    // Files saved as `<asset>_<role>_00001_.png` carry their role in the
    // name, so the grid can row itself by it — one row per role makes "one of
    // each, none twice" readable at a glance. The group key is the stem minus
    // ComfyUI's counter; the label is what the keys do not share.
    const groupOf = (name) =>
        name.replace(/\.[^.]+$/, "").replace(/_\d+_?$/, "");

    function renderRow(ticks, rowImages) {
        const px = SIZES[thumbSize(node)];
        const grid = el("div", "display:flex;flex-wrap:wrap;gap:4px;"
            + "width:100%;box-sizing:border-box;");
        for (const image of rowImages) {
            const on = ticks.has(image.id);
            const cell = el("div",
                `position:relative;width:${px}px;height:${px}px;flex:none;`
                + `border:2px solid ${on ? HUB.accent : HUB.hairline};`
                + `border-radius:4px;overflow:hidden;cursor:pointer;`
                + `background:${HUB.surface1};box-sizing:border-box;`);
            const caption = `${image.index} · ${image.name}`
                + (image.w ? ` · ${image.w}×${image.h}` : "");
            // No `title`: the browser's own tooltip lands a second later, on
            // top of the render being judged, saying what the preview's own
            // caption already says. The frame is the tooltip.

            const img = el("img", "width:100%;height:100%;object-fit:cover;"
                + "display:block;pointer-events:none;");
            img.src = thumbUrl(image.path, px * 2);
            img.loading = "lazy";
            cell.appendChild(img);

            // The number is how a pick is named out loud — "take 3, 7 and 12".
            const badge = el("div",
                `position:absolute;left:0;top:0;min-width:14px;padding:0 3px;`
                + `font:10px ${HUB.font};text-align:center;`
                + `background:${on ? HUB.accent : "rgba(0,0,0,.55)"};`
                + `color:${on ? "#000" : HUB.ink};border-radius:0 0 4px 0;`,
                String(image.index));
            cell.appendChild(badge);

            // S tiles are 64px: too small to tell two renders apart, which is
            // the whole job of this node. Resting on one floats it big beside
            // the grid, off the same resize route the tile came from.
            attachHoverZoom(cell, () => ({
                w: image.w,
                h: image.h,
                label: caption,
                hint: "click to tick · double-click to open full size",
                placeholder: img.src,   // already fetched: the frame fills now
                src: (zoomPx) => thumbUrl(image.path, zoomPx),
            }));

            cell.addEventListener("pointerdown", (e) => e.stopPropagation());
            cell.addEventListener("click", () => toggle(image.id));
            cell.addEventListener("dblclick", (e) => {
                e.stopPropagation();
                window.open(fullUrl(image.path), "_blank");
            });
            grid.appendChild(cell);
        }
        return grid;
    }

    function renderGrid(ticks) {
        const groups = new Map();
        for (const image of images) {
            const key = groupOf(image.name);
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(image);
        }
        if (groups.size <= 1) return renderRow(ticks, images);

        // The shared start of every key is the asset's own name — the label
        // is the part that differs, which is the role.
        const keys = [...groups.keys()];
        let shared = keys[0];
        for (const key of keys) {
            while (shared && !key.startsWith(shared)) {
                shared = shared.slice(0, -1);
            }
        }
        // Rows are for the ROLES OF ONE ASSET — `<asset>_<role>_00001_.png`.
        // A folder of unrelated names has no asset in common, so every file
        // became its own row: a dataset folder of 57 references drew as 57
        // one-tile rows labelled with their own filenames, which is a list
        // pretending to be a grid. Row only when every key is the shared stem
        // or a `_`-suffixed extension of it; otherwise the names merely start
        // alike ("Baking Class", "Baking With Mom Statue") and the grid is the
        // honest layout.
        const stem = shared.replace(/_+$/, "");
        const rowed = stem && keys.every(
            (key) => key === stem || key.startsWith(`${stem}_`));
        if (!rowed) return renderRow(ticks, images);

        const wrap = el("div", "width:100%;box-sizing:border-box;");
        for (const [key, rowImages] of groups) {
            const label = key.slice(stem.length).replace(/^_/, "") || "base";
            const here = rowImages.filter((i) => ticks.has(i.id)).length;
            wrap.appendChild(el("div",
                `padding:5px 3px 2px;font:10px ${HUB.font};`
                + `color:${here ? HUB.ink : HUB.inkSubtle};`,
                `${label} · ${rowImages.length}${here ? ` · ${here} ✓` : ""}`));
            wrap.appendChild(renderRow(ticks, rowImages));
        }
        return wrap;
    }

    function render() {
        const ticks = readTicks(node);
        // The tile a preview belongs to is about to be thrown away — a frame
        // left up would be floating beside nothing.
        hideHoverZoom();
        list.replaceChildren();
        // The counts, the sizes and the folder stay put while the grid moves
        // under them: with 85 thumbnails the controls are otherwise a scroll
        // away from the images they act on, and the folder a picker landed on
        // is the thing worth being able to read at any time.
        const top = el("div", "position:sticky;top:0;z-index:2;"
            + `background:${HUB.surface1};padding-bottom:2px;`);
        top.appendChild(renderHead(ticks));
        if (folder) {
            top.appendChild(el("div",
                `color:${HUB.inkTertiary};font:10px ${HUB.font};padding:0 3px 3px;`
                + "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;",
                folder));
        }
        if (error) top.appendChild(errorLine(error));
        if (notice) {
            top.appendChild(el("div",
                `color:${HUB.inkTertiary};font:10px ${HUB.font};padding:0 3px 3px;`,
                notice));
        }
        list.appendChild(top);
        if (loading && !images.length) {
            list.appendChild(emptyState("reading…"));
        } else if (!images.length) {
            list.appendChild(emptyState(shortlist
                ? "the picker above has nothing ticked yet — approve some "
                  + "there and they appear here"
                : "queue this node once — it works out which folder this "
                  + "asset's images are in from the wires, then lists them "
                  + "here"));
        } else {
            list.appendChild(renderGrid(ticks));
        }
        refit();
    }

    render();
    load();
}

registerSymbioticaExtension(app, {
    name: "symbiotica.pick",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            // Canvas state: collapse it (a bare .hidden is ignored by the
            // classic canvas widgets).
            for (const name of ["selection", "view"]) {
                const w = widgetOf(this, name);
                if (w) { w.hidden = true; w.computeSize = () => [0, -4]; }
            }
            pickPanel(this);
        };

        // A saved workflow restores the ticks AFTER creation, and the node id
        // the listing is keyed by is only final once the graph is configured.
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            onConfigure?.apply(this, arguments);
            // Graphs saved before the node was stripped to one wire carry ten
            // widget values, applied positionally onto the five widgets that
            // remain — which lands the ticks on `mode` and the stage nowhere.
            // Put each surviving value back on its own widget, by the position
            // it held in the old layout: [get_new, asset, category, selection,
            // view, role, folder, phase, mode, stage].
            const v = info?.widgets_values;
            if (Array.isArray(v) && v.length >= 10) {
                for (const [name, i] of [["save_path", 6], ["selection", 3],
                                         ["view", 4], ["mode", 8],
                                         ["stage", 9]]) {
                    const w = widgetOf(this, name);
                    if (w) w.value = v[i];
                }
                // Every widget added since that layout is holding one of its
                // values by now, so each goes back to its own default.
                for (const [name, value] of APPENDED_WIDGETS) {
                    const w = widgetOf(this, name);
                    if (w) w.value = value;
                }
            }
            // Whatever the layout, a widget added after a workflow was saved
            // sits past the end of its `widgets_values` and comes back unset
            // rather than holding its declared default. Unset arrives as an
            // empty string as readily as as nothing at all, and neither is one
            // of a combo's options, so ComfyUI refuses the whole queue over it
            // — `Value not in list: shortlist: '' not in [...]`. Anything the
            // widget does not actually offer goes back to its default.
            for (const [name, value] of APPENDED_WIDGETS) {
                const w = widgetOf(this, name);
                if (!w) continue;
                const offered = w.options?.values;
                const known = Array.isArray(offered)
                    ? offered.includes(w.value)
                    : w.value !== undefined && w.value !== null && w.value !== "";
                if (!known) w.value = value;
            }
            queueMicrotask(() => this._symReloadPick?.());
        };
    },
});

// A run just resolved the folder — list it, rather than making the user press
// reload to find out which one the node landed on.
api.addEventListener("symbiotica.pick", (event) => {
    const detail = event?.detail ?? {};
    if (detail.node_id == null) return;
    const node = app.graph?.getNodeById?.(Number(detail.node_id))
        ?? app.graph?.getNodeById?.(detail.node_id);
    if (!node) return;
    node._symReloadPick?.();
});

// A cached picker does not execute, and its change-check only answers for
// what it EMITS — so a queue that wrote new renders can finish without the
// node running at all. The re-list comes from here instead: every picker on
// the canvas refreshes when a queue ends.
api.addEventListener("execution_success", () => {
    for (const node of app.graph?._nodes ?? []) node._symReloadPick?.();
});
