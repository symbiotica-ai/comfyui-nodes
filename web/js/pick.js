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

function upstreamNode(node, inputName) {
    const input = node?.inputs?.find((i) => i.name === inputName);
    if (!input || input.link == null) return null;
    const link = app.graph.links[input.link];
    return link ? app.graph.getNodeById(link.origin_id) : null;
}

// The asset an upstream Asset Focus is set to. The `asset` input is wired, so
// it has no widget value of its own to read — but the node feeding it does,
// and reading it there is what lets the grid follow a change immediately
// rather than only after the next run.
function focusAsset(node) {
    let cur = upstreamNode(node, "asset");
    for (let hop = 0; hop < 6 && cur; hop++) {
        if (cur.comfyClass === "SymbioticaAssetFocus") {
            return widgetOf(cur, "asset")?.value?.trim?.() || "";
        }
        const wired = (cur.inputs ?? []).filter((i) => i.link != null);
        if (wired.length !== 1) return "";
        cur = upstreamNode(cur, wired[0].name);
    }
    return "";
}

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
    // What the last folder read did. Separate from `error` so a successful
    // import is not reported in the red the failures use.
    let notice = "";
    let loading = false;

    // The group the node opens on when `view` is empty: whatever arrived last.
    // Derived from the buffer rather than by reading the wired asset/category
    // widgets, because those are normally WIRED — a wired input has no widget
    // value to read, and the tag recorded on the newest candidate is the same
    // context by construction.
    const newestGroup = () => {
        const pool = inPhase();
        return pool.length ? pool[pool.length - 1].group : "";
    };

    function visibleGroups() {
        const counted = [];
        for (const im of inPhase()) {
            const found = counted.find((g) => g.key === im.group);
            if (found) found.count += 1;
            else counted.push({ key: im.group, count: 1 });
        }
        return counted;
    }

    // In auto mode, follow the asset being worked on. The upstream Asset Focus
    // answers immediately when it changes; the last run's own group is the
    // authority when there is no Focus to read. Newest-arrival is the fallback
    // for a picker wired to neither.
    function autoGroup() {
        const pool = visibleGroups();
        const asset = focusAsset(node);
        if (asset) {
            const match = pool.find((g) => g.key === asset
                || g.key.endsWith(` / ${asset}`));
            if (match) return match.key;
        }
        const current = node._symPickCurrent;
        if (current && pool.some((g) => g.key === current)) return current;
        return newestGroup() || ALL;
    }

    function effectiveView() {
        const stored = readView(node);
        if (stored === ALL) return ALL;
        if (stored && visibleGroups().some((g) => g.key === stored)) return stored;
        return autoGroup();
    }

    // The pass this picker is pinned to. Filtering here as well as at import
    // matters for candidates collected before the pin was set.
    const phaseOf = (n) => widgetOf(n, "phase")?.value?.trim?.() || "";

    const inPhase = () => {
        const phase = phaseOf(node);
        return phase ? images.filter((i) => (i.phase || "") === phase) : images;
    };

    const shown = () => {
        const view = effectiveView();
        const pool = inPhase();
        return view === ALL ? pool : pool.filter((i) => i.group === view);
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

        const phase = phaseOf(node);
        if (phase) {
            const chip = el("div",
                `flex:none;padding:1px 6px;border-radius:3px;font:10px ${HUB.font};`
                + `background:${HUB.surface1};color:${HUB.inkSubtle};`
                + `border:1px solid ${HUB.hairline};`, phase);
            chip.title = `this picker only takes in and shows ${phase} images`;
            bar.appendChild(chip);
        }

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

        const pool = visibleGroups();
        const optAll = el("option", "", `All (${inPhase().length})`);
        optAll.value = ALL;
        select.appendChild(optAll);
        for (const g of pool) {
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
        const list = shown();
        // One row per stage when the candidates carry roles, so a prep is
        // compared against the other preps rather than against a serving. Row
        // order is arrival order — the order the sheet was cut in — because
        // alphabetically "prep" would follow "ready".
        const order = [];
        for (const im of list) {
            const role = im.role || "";
            if (!order.includes(role)) order.push(role);
        }
        if (!order.some((r) => r)) return tileStrip(list, ticks);

        const wrap = el("div", "padding:2px;");
        for (const role of order) {
            const row = el("div", "margin-bottom:5px;");
            row.appendChild(el("div",
                `color:${HUB.inkSubtle};font:10px ${HUB.font};`
                + "text-transform:uppercase;letter-spacing:.06em;margin:0 0 2px 1px;",
                role || "unlabelled"));
            row.appendChild(tileStrip(list.filter((i) => (i.role || "") === role),
                                      ticks));
            wrap.appendChild(row);
        }
        return wrap;
    }

    function tileStrip(items, ticks) {
        const px = SIZES[thumbSize(node)];
        const grid = el("div", "display:flex;flex-wrap:wrap;gap:4px;padding:2px;");
        for (const im of items) {
            const on = ticks.has(im.id);
            const cell = el("div", `position:relative;width:${px}px;flex:none;cursor:pointer;`);
            cell.title = `${im.group}${im.role ? ` · ${im.role}` : ""}`
                + `${im.w ? ` · ${im.w}×${im.h}` : ""}`
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
        if (notice) {
            list.appendChild(el("div",
                `color:${HUB.inkTertiary};font:10px ${HUB.font};padding:0 3px 3px;`,
                notice));
        }
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
        if (!inPhase().length) {
            list.appendChild(emptyState(
                `${images.length} candidates here, none of them ${phaseOf(node)}`));
            refit();
            return;
        }
        if (visibleGroups().length > 1) list.appendChild(renderFilter());
        const visible = shown();
        if (!visible.length) {
            list.appendChild(emptyState("nothing recorded for this asset yet"));
        } else {
            list.appendChild(renderGrid(ticks));
        }
        refit();
    }

    // Reading a folder of renders that already exist, so a picker added after
    // the work was generated does not have to re-render it to have something
    // to choose from. A NATIVE litegraph button with serialize off: it adds no
    // widgets_values entry, so it cannot shift the positions of the widgets
    // saved in someone's workflow the way a new input would.
    let reading = false;
    const readBtn = node.addWidget("button", "📁 Read folder", null, async () => {
        if (reading) return;
        const folder = widgetOf(node, "folder")?.value?.trim?.();
        if (!folder) {
            error = "type a folder into the node's `folder` field first";
            render();
            return;
        }
        reading = true;
        readBtn.name = "⏳ Reading…";
        node.setDirtyCanvas?.(true, true);
        try {
            const body = { node_id: String(node.id), folder };
            const phase = phaseOf(node);
            if (phase) body.phase = phase;
            // Only unwired values are readable from the canvas; a wired input
            // has no widget value, and the route falls back to the folder's
            // own name for the asset.
            for (const name of ["asset", "category", "role"]) {
                const value = widgetOf(node, name)?.value?.trim?.();
                if (value) body[name] = value;
            }
            const res = await fetchJson("/symbiotica/pick-import", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            notice = res.added || res.skipped || res.failed
                ? `read ${res.folder}: ${res.added} added`
                    + `${res.skipped ? `, ${res.skipped} already here` : ""}`
                    + `${res.failed ? `, ${res.failed} unreadable` : ""}`
                    + `${res.truncated ? `, ${res.truncated} beyond the limit` : ""}`
                : "no images in that folder";
            error = "";
            await load();
        } catch (e) {
            error = e.message || "could not read that folder";
            render();
        } finally {
            reading = false;
            readBtn.name = "📁 Read folder";
            node.setDirtyCanvas?.(true, true);
        }
    });
    readBtn.serialize = false;

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
    const detail = event?.detail ?? {};
    if (detail.node_id == null) return;
    const node = app.graph?.getNodeById?.(Number(detail.node_id))
        ?? app.graph?.getNodeById?.(detail.node_id);
    if (!node) return;
    if (typeof detail.current === "string") node._symPickCurrent = detail.current;
    node._symReloadPick?.();
});
