// ABOUTME: Symbiotica Pick node UI — every candidate the node has been handed,
// ABOUTME: drawn as thumbnails on the node body, filtered to the asset being
// ABOUTME: worked on, ticked to choose which ones travel downstream.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { HUB, injectHubStyles, ghostButtonCss } from "./hub_theme.js";
import { el, emptyState, errorLine } from "./browser_chrome.js";

const NODE_CLASS = "SymbioticaPick";
const MIN_NODE_W = 340;
const PANEL_MAX = 720;      // past this the grid scrolls instead of growing the node
const ALL = "__all__";
const SIZES = { S: 64, M: 108, L: 184 };
const DEFAULT_SIZE = "M";

const widgetOf = (node, name) => node.widgets?.find((w) => w.name === name);

// Keep the /api/ prefix: ComfyUI mirrors custom routes under /api/ locally AND
// the Modal gateway proxies /api/* only, so a root-level /symbiotica/* would
// blank every thumbnail there.
const imageUrl = (path) => api.apiURL(
    `/symbiotica/local-image?path=${encodeURIComponent(path)}`);

async function fetchJson(url, options) {
    const res = await api.fetchApi(url, options);
    if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.error ?? res.statusText);
    return res.json();
}

// --- node state --------------------------------------------------------------
// The ticks live on the `selection` widget (a JSON array of candidate ids) and
// the filter on `view`, so both are saved with the workflow: reopening a graph
// has to show the same picks the run was queued with.
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

const readView = (node) => widgetOf(node, "view")?.value ?? "";

function writeView(node, value) {
    const w = widgetOf(node, "view");
    if (w) w.value = value;
    node.setDirtyCanvas?.(true, true);
}

function thumbSize(node) {
    const key = node.properties?.symPickThumb;
    return SIZES[key] ? key : DEFAULT_SIZE;
}

// --- the panel ---------------------------------------------------------------
function pickPanel(node) {
    injectHubStyles();

    const container = el("div", "box-sizing:border-box;width:100%;"
        + "overflow-y:auto;overflow-x:hidden;");
    // ComfyUI sizes the container from computeSize, so its scrollHeight only
    // echoes its own box. Measure this inner list — its natural height IS the
    // content height.
    const list = el("div", `padding:2px;font:11px ${HUB.font};color:${HUB.ink};`);
    container.appendChild(list);
    container.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });

    const panelW = node.addDOMWidget("pick_panel", "sym_pick", container,
                                     { serialize: false, hideOnZoom: true });
    panelW.computeSize = function (width) {
        const h = list.scrollHeight;
        return [width, Math.min(Math.max(h ? h + 8 : 44, 44), PANEL_MAX)];
    };
    const refit = () => requestAnimationFrame(() => {
        node.setSize?.([Math.max(node.size[0], MIN_NODE_W), node.computeSize()[1]]);
        node.setDirtyCanvas?.(true, true);
    });
    node.size[0] = Math.max(node.size[0], MIN_NODE_W);

    let images = [];
    let groups = [];
    let error = "";
    let loading = false;

    // The group the node opens on when `view` is empty: whatever arrived last.
    // Derived from the buffer rather than by reading the wired asset/category
    // widgets, because those are normally WIRED — a wired input has no widget
    // value to read, and the tag recorded on the newest candidate is the same
    // context by construction.
    const newestGroup = () => images.length ? images[images.length - 1].group : "";

    function effectiveView() {
        const stored = readView(node);
        if (stored === ALL) return ALL;
        if (stored && groups.some((g) => g.key === stored)) return stored;
        return newestGroup() || ALL;
    }

    const shown = () => {
        const view = effectiveView();
        return view === ALL ? images : images.filter((i) => i.group === view);
    };

    async function load() {
        loading = true;
        render();
        try {
            const q = new URLSearchParams({ node_id: String(node.id) });
            const data = await fetchJson(`/symbiotica/pick-list?${q.toString()}`);
            images = Array.isArray(data.images) ? data.images : [];
            groups = Array.isArray(data.groups) ? data.groups : [];
            error = "";
        } catch (e) {
            images = [];
            groups = [];
            error = e.message || "could not read this node's buffer";
        } finally {
            loading = false;
            render();
        }
    }
    node._symReloadPick = load;

    async function remove(ids) {
        try {
            await fetchJson("/symbiotica/pick-clear", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ node_id: String(node.id), ids }),
            });
        } catch (e) {
            error = e.message || "could not clear";
            render();
            return;
        }
        // A dropped candidate must lose its tick too, or the node keeps
        // claiming picks that no longer have an image behind them.
        const ticks = readTicks(node);
        const gone = new Set((ids ?? images.map((i) => i.id)).map(String));
        writeTicks(node, new Set([...ticks].filter((t) => !gone.has(t))));
        await load();
    }

    function toggle(id) {
        const ticks = readTicks(node);
        if (ticks.has(id)) ticks.delete(id);
        else ticks.add(id);
        writeTicks(node, ticks);
        render();
    }

    // --- header: counts, thumb size, clear ----------------------------------
    function renderHead(ticks) {
        const bar = el("div",
            `display:flex;align-items:center;gap:6px;padding:2px 2px 4px;color:${HUB.inkSubtle};`);
        const visible = shown().length;
        const tickedHere = shown().filter((i) => ticks.has(i.id)).length;
        bar.append(el("span", "flex:1;min-width:0;",
                      images.length
                          ? `${visible} shown · ${tickedHere} ticked`
                          + (ticks.size > tickedHere ? ` (${ticks.size} total)` : "")
                          : "no candidates yet"));

        // With collecting off the wire above is never evaluated, so a run adds
        // nothing here. Say so on the node: silence looks identical to a
        // generator that failed.
        if (widgetOf(node, "collect")?.value === false) {
            const chip = el("div",
                `flex:none;padding:1px 6px;border-radius:3px;font:10px ${HUB.font};`
                + `background:${HUB.surface1};color:${HUB.inkTertiary};`
                + `border:1px solid ${HUB.hairline};`, "not collecting");
            chip.title = "collect is off — running this adds no candidates and "
                + "nothing upstream is asked for";
            bar.appendChild(chip);
        }

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
        reload.title = "Re-read this node's buffer";
        reload.addEventListener("pointerdown", (e) => e.stopPropagation());
        reload.addEventListener("click", load);
        bar.appendChild(reload);

        if (images.length) {
            const clear = el("button", ghostButtonCss + "padding:1px 8px;flex:none;", "clear");
            clear.className = "sym-btn";
            clear.title = "Delete every candidate in this node's buffer";
            clear.addEventListener("pointerdown", (e) => e.stopPropagation());
            clear.addEventListener("click", () => {
                if (window.confirm(`Delete all ${images.length} candidates from this picker?`)) {
                    remove(null);
                }
            });
            bar.appendChild(clear);
        }
        return bar;
    }

    // --- filter: one asset at a time, or everything --------------------------
    function renderFilter() {
        const row = el("div", "display:flex;align-items:center;gap:5px;padding:0 2px 4px;");
        const select = el("select",
            `flex:1;min-width:0;background:${HUB.surface1};color:${HUB.ink};`
            + `border:1px solid ${HUB.hairline};border-radius:4px;padding:2px 4px;`
            + `font:11px ${HUB.font};`);
        select.className = "sym-input";
        const view = effectiveView();

        const optAll = el("option", "", `All (${images.length})`);
        optAll.value = ALL;
        select.appendChild(optAll);
        for (const g of groups) {
            const o = el("option", "", `${g.key} (${g.count})`);
            o.value = g.key;
            select.appendChild(o);
        }
        select.value = view;
        select.title = readView(node)
            ? "Showing a pinned group — pick All to see everything"
            : "Following the asset this node was last handed";
        select.addEventListener("pointerdown", (e) => e.stopPropagation());
        select.addEventListener("change", () => {
            writeView(node, select.value);
            render();
        });
        row.appendChild(select);

        // Empty `view` means "follow whatever arrives" — worth being able to
        // get back to once a group has been pinned by hand.
        if (readView(node)) {
            const auto = el("button", ghostButtonCss + "padding:2px 7px;flex:none;", "auto");
            auto.className = "sym-btn";
            auto.title = "Follow the asset being worked on";
            auto.addEventListener("pointerdown", (e) => e.stopPropagation());
            auto.addEventListener("click", () => { writeView(node, ""); render(); });
            row.appendChild(auto);
        }
        return row;
    }

    // --- the grid ------------------------------------------------------------
    function renderGrid(ticks) {
        const px = SIZES[thumbSize(node)];
        const grid = el("div", "display:flex;flex-wrap:wrap;gap:4px;padding:2px;");
        for (const im of shown()) {
            const on = ticks.has(im.id);
            const cell = el("div", `position:relative;width:${px}px;flex:none;cursor:pointer;`);
            cell.title = `${im.group}${im.w ? ` · ${im.w}×${im.h}` : ""}`
                + `${im.at ? ` · ${im.at}` : ""}\nclick to tick · double-click opens full size`;

            const img = el("img",
                `width:${px}px;height:${px}px;object-fit:contain;display:block;`
                + "background:#111;border-radius:4px;box-sizing:border-box;"
                + `border:2px solid ${on ? HUB.accent : "transparent"};`
                + (on ? "" : "opacity:.72;"));
            img.src = imageUrl(im.thumb || im.path);
            img.loading = "lazy";
            img.addEventListener("pointerdown", (e) => e.stopPropagation());
            img.addEventListener("click", () => toggle(im.id));
            img.addEventListener("dblclick", (e) => {
                e.stopPropagation();
                window.open(imageUrl(im.path), "_blank", "noopener");
            });

            const badge = el("div",
                "position:absolute;top:3px;left:3px;width:14px;height:14px;"
                + "border-radius:3px;display:flex;align-items:center;justify-content:center;"
                + `font:10px/1 ${HUB.font};pointer-events:none;`
                + (on ? `background:${HUB.accent};color:#0b0b0b;`
                      : "background:rgba(0,0,0,.55);color:#bbb;"),
                on ? "✓" : "");

            const del = el("button",
                "position:absolute;top:2px;right:2px;border:0;cursor:pointer;"
                + "background:rgba(0,0,0,.55);color:#ddd;border-radius:3px;"
                + `font:10px/1 ${HUB.font};padding:2px 4px;`, "✕");
            del.title = "Delete this candidate";
            del.addEventListener("pointerdown", (e) => e.stopPropagation());
            del.addEventListener("click", (e) => {
                e.stopPropagation();
                remove([im.id]);
            });

            cell.append(img, badge, del);
            grid.appendChild(cell);
        }
        return grid;
    }

    function render() {
        const ticks = readTicks(node);
        list.replaceChildren();
        list.appendChild(renderHead(ticks));
        if (error) list.appendChild(errorLine(error));
        if (loading && !images.length) {
            list.appendChild(emptyState("reading…"));
            refit();
            return;
        }
        if (!images.length) {
            list.appendChild(emptyState(
                "queue this node to collect candidates — every image wired in "
                + "lands here"));
            refit();
            return;
        }
        if (groups.length > 1) list.appendChild(renderFilter());
        const visible = shown();
        if (!visible.length) {
            list.appendChild(emptyState("nothing recorded for this asset yet"));
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
            // Canvas state, not things to type into: collapse them (a bare
            // .hidden is ignored by the classic canvas widgets).
            for (const name of ["selection", "view"]) {
                const w = widgetOf(this, name);
                if (w) { w.hidden = true; w.computeSize = () => [0, -4]; }
            }
            pickPanel(this);
        };

        // A saved workflow restores the ticks AFTER creation, and the node id
        // the buffer is keyed by is only final once the graph is configured.
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            onConfigure?.apply(this, arguments);
            queueMicrotask(() => this._symReloadPick?.());
        };
    },
});

// A run just filed new candidates — redraw the node that received them rather
// than making the user press reload to find out the render finished.
api.addEventListener("symbiotica.pick", (event) => {
    const nodeId = event?.detail?.node_id;
    if (nodeId == null) return;
    const node = app.graph?.getNodeById?.(Number(nodeId))
        ?? app.graph?.getNodeById?.(nodeId);
    node?._symReloadPick?.();
});
