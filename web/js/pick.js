// ABOUTME: Symbiotica Pick node UI — the asset's own render folder listed on the
// ABOUTME: node body as numbered thumbnails, ticked to choose which files travel
// ABOUTME: downstream. It holds nothing: every tile is a file already on disk.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { HUB, injectHubStyles, ghostButtonCss } from "./hub_theme.js";
import { el, emptyState, errorLine } from "./browser_chrome.js";

const NODE_CLASS = "SymbioticaPick";
const MIN_NODE_W = 340;
const PANEL_MAX = 720;      // past this the grid scrolls instead of growing the node
const SIZES = { S: 64, M: 108, L: 184 };
const DEFAULT_SIZE = "M";

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
    let folder = "";
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

    // Editing is done to ONE image: "i am EDITING so it has to be the one i am
    // working on". Every other pass chooses a set.
    const phaseOf = () => widgetOf(node, "phase")?.value?.trim?.() || "";
    const oneAtATime = () => phaseOf() === "edit";

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

        const phase = phaseOf();
        if (phase) {
            const chip = el("div",
                `flex:none;padding:1px 6px;border-radius:3px;font:10px ${HUB.font};`
                + `background:${HUB.surface1};color:${HUB.inkSubtle};`
                + `border:1px solid ${HUB.hairline};`,
                oneAtATime() ? `${phase} · one` : phase);
            chip.title = `ticked images are kept in …/${phase} under this asset`
                + (oneAtATime()
                    ? "\nediting is done to one image, so ticking replaces the "
                      + "previous pick"
                    : "");
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
        reload.title = "Re-read the folder";
        reload.addEventListener("pointerdown", (e) => e.stopPropagation());
        reload.addEventListener("click", () => load());
        bar.appendChild(reload);

        if (ticks.size) {
            // Untick, never delete. The tiles are the renders themselves, so a
            // node that could delete them would be a node that can destroy the
            // work it exists to choose between.
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
    function renderGrid(ticks) {
        const px = SIZES[thumbSize(node)];
        const grid = el("div", "display:flex;flex-wrap:wrap;gap:4px;"
            + "width:100%;box-sizing:border-box;");
        for (const image of images) {
            const on = ticks.has(image.id);
            const cell = el("div",
                `position:relative;width:${px}px;height:${px}px;flex:none;`
                + `border:2px solid ${on ? HUB.accent : HUB.hairline};`
                + `border-radius:4px;overflow:hidden;cursor:pointer;`
                + `background:${HUB.surface1};box-sizing:border-box;`);
            cell.title = `${image.index} · ${image.name}`
                + (image.w ? ` · ${image.w}×${image.h}` : "")
                + "\nclick to tick · double-click to open full size";

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

    function render() {
        const ticks = readTicks(node);
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
            list.appendChild(emptyState(
                "queue this node once — it works out which folder this asset's "
                + "renders are in from the wires, then lists them here"));
        } else {
            list.appendChild(renderGrid(ticks));
        }
        refit();
    }

    // Browsing a folder other than this asset's own. The node lists its own
    // folder by itself on every run, so this is only for looking elsewhere.
    let reading = false;
    const readBtn = node.addWidget("button", "📁 Read folder", null, async () => {
        if (reading) return;
        const typed = widgetOf(node, "folder")?.value?.trim?.();
        if (!typed) {
            notice = "leave `folder` empty and queue this node — it lists this "
                + "asset's own renders. Set `folder` only to browse another one.";
            error = "";
            render();
            return;
        }
        reading = true;
        readBtn.name = "⏳ Reading…";
        node.setDirtyCanvas?.(true, true);
        try {
            await load(typed);
            notice = images.length ? "" : "no images in that folder";
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
            // Canvas state and dead widgets kept for their positions: collapse
            // them (a bare .hidden is ignored by the classic canvas widgets).
            for (const name of ["selection", "view", "get_new", "role"]) {
                const w = widgetOf(this, name);
                if (w) { w.hidden = true; w.computeSize = () => [0, -4]; }
            }
            pickPanel(this);
        };

        // A saved workflow restores the ticks AFTER creation, and the node id
        // the listing is keyed by is only final once the graph is configured.
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            onConfigure?.apply(this, arguments);
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
    // Ticked images are copied to the delivery folder, which is not somewhere
    // the node can show — so it says where they went rather than leaving it to
    // be discovered in a file browser.
    node._symPickNote?.(detail.kept
        ? `kept ${detail.kept} in ${detail.kept_in || "the asset's folder"}`
        : "");
    node._symReloadPick?.();
});
