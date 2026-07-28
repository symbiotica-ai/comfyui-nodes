// ABOUTME: Reference Browser node UI — the game library's folder tree rendered
// ABOUTME: INSIDE the node: tick a folder to make it a sheet row, tick images to
// ABOUTME: make its cells, and the picks become the Auto Packer's order wire.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { HUB, injectHubStyles, ghostButtonCss } from "./hub_theme.js";
import {
    el, emptyState, errorLine, filterBox, filterByName, folderRow, navBar,
} from "./browser_chrome.js";

const NODE_CLASS = "SymbioticaReferenceBrowser";
const MIN_NODE_W = 380;
const PANEL_MAX = 620;   // past this the panel scrolls instead of growing the node
const THUMB_PX = 54;

const widgetOf = (node, name) => node.widgets?.find((w) => w.name === name);

// Keep the /api/ prefix: ComfyUI mirrors custom routes under /api/ locally AND
// the Modal gateway proxies /api/* only, so a root-level /symbiotica/* would
// blank every thumbnail there.
const thumbUrl = (root, rel) => api.apiURL(
    `/symbiotica/local-image?path=${encodeURIComponent(`${root}/${rel}`)}`);

async function fetchJson(url) {
    const res = await api.fetchApi(url);
    if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.error ?? res.statusText);
    return res.json();
}

// --- root resolution ---------------------------------------------------------
// root_path is normally WIRED (from the Studio Library node), and a wired input
// has no widget value to read — so fall back to a one-hop walk up the link and
// take the origin's first non-empty string widget. That is the Studio Library's
// `selection` (a volume-relative studios/… rel), which the browse route expands
// exactly as the node's Python does.
function upstreamString(node, inputName, seen = new Set()) {
    const input = node?.inputs?.find((i) => i.name === inputName);
    if (!input || input.link == null) return "";
    const link = app.graph.links[input.link];
    const origin = link && app.graph.getNodeById(link.origin_id);
    if (!origin || seen.has(origin.id)) return "";
    seen.add(origin.id);
    const strW = origin.widgets?.find(
        (w) => typeof w.value === "string" && w.value.trim());
    if (strW) return strW.value.trim();
    const wired = (origin.inputs ?? []).filter((i) => i.link != null);
    if (wired.length === 1) return upstreamString(origin, wired[0].name, seen);
    return "";
}

function rootPathOf(node) {
    const typed = widgetOf(node, "root_path")?.value?.trim?.();
    return typed || upstreamString(node, "root_path");
}

// --- selection state ---------------------------------------------------------
// { dir: "<rel the browser is showing>", groups: [ { name, category, dir,
//   files: ["<rel>", …], variants } ] }. One group is one sheet row; its files
// are that row's cells. Stored on the node's `selection` widget, so picks are
// saved with the workflow.
function readState(node) {
    try {
        const raw = JSON.parse(widgetOf(node, "selection")?.value || "{}");
        const groups = Array.isArray(raw.groups) ? raw.groups : [];
        return { dir: typeof raw.dir === "string" ? raw.dir : "", groups };
    } catch {
        return { dir: "", groups: [] };
    }
}

function writeState(node, state) {
    const w = widgetOf(node, "selection");
    if (w) w.value = JSON.stringify({ dir: state.dir, groups: state.groups });
    node.setDirtyCanvas?.(true, true);
}

const baseName = (rel) => (rel || "").split("/").filter(Boolean).pop() || "";
const parentRel = (rel) => (rel || "").split("/").slice(0, -1).join("/");

// The row is the folder that holds the images; the CATEGORY is the folder that
// holds the row — browse `Minis/`, tick the recipes inside it, and every row
// lands in category "Minis". Ticking images while inside `Minis/Cupcake` makes
// the same row, so both ways of picking agree. Rows made of loose images at the
// library root fall back to the root's own name.
function categoryFor(groupDir, rootName) {
    return baseName(parentRel(groupDir)) || rootName || "Assets";
}

function groupAt(state, dir) {
    return state.groups.find((g) => g.dir === dir);
}

// --- the panel ---------------------------------------------------------------
function referencePanel(node) {
    injectHubStyles();

    const container = el("div", "box-sizing:border-box;width:100%;"
        + "overflow-y:auto;overflow-x:hidden;");
    // ComfyUI sizes the container from computeSize, so its scrollHeight only
    // echoes its own box. Measure this inner list — its natural height IS the
    // content height.
    const list = el("div", `padding:2px;font:11px ${HUB.font};color:${HUB.ink};`);
    container.appendChild(list);
    container.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });

    const panelW = node.addDOMWidget("reference_panel", "sym_reference_browser",
                                     container, { serialize: false, hideOnZoom: true });
    panelW.computeSize = function (width) {
        const h = list.scrollHeight;
        return [width, Math.min(Math.max(h ? h + 8 : 44, 44), PANEL_MAX)];
    };
    const refit = () => requestAnimationFrame(() => {
        node.setSize?.([Math.max(node.size[0], MIN_NODE_W), node.computeSize()[1]]);
        node.setDirtyCanvas?.(true, true);
    });
    node.size[0] = Math.max(node.size[0], MIN_NODE_W);

    let level = null;      // last browse-refs response
    let error = "";
    let filter = "";
    let loading = false;

    const state = () => readState(node);
    const save = (s) => writeState(node, s);

    async function load(dir) {
        const root = rootPathOf(node);
        if (!root) {
            level = null;
            error = "wire the Studio Library's path into root_path (or type a folder)";
            render();
            return;
        }
        loading = true;
        render();
        try {
            const q = new URLSearchParams({ root, dir: dir || "" });
            level = await fetchJson(`/symbiotica/browse-refs?${q.toString()}`);
            error = "";
            const s = state();
            s.dir = level.rel || "";
            save(s);
        } catch (e) {
            level = null;
            error = e.message || "could not read that folder";
        } finally {
            loading = false;
            filter = "";
            render();
        }
    }
    node._symReloadBrowser = () => load(readState(node).dir);

    // Ticking a folder makes it a row: its images (one level, the folder's own
    // files) become the cells. Unticking drops the row.
    async function toggleFolder(dirRel, on) {
        const s = state();
        if (!on) {
            s.groups = s.groups.filter((g) => g.dir !== dirRel);
            save(s);
            render();
            return;
        }
        const root = rootPathOf(node);
        let data;
        try {
            const q = new URLSearchParams({ root, dir: dirRel });
            data = await fetchJson(`/symbiotica/browse-refs?${q.toString()}`);
        } catch (e) {
            error = `${baseName(dirRel)}: ${e.message}`;
            render();
            return;
        }
        // The library keeps a `thumbNNNN.png` catalogue tile beside an item's
        // real art (smaller, and not a stage of the item) — ticking the folder
        // should not turn that into a cell. It is still listed in the grid, so
        // it can be added back by hand.
        const all = (data.images ?? []).map((i) => i.rel);
        const art = all.filter((rel) => !baseName(rel).toLowerCase().startsWith("thumb"));
        const files = art.length ? art : all;
        if (!files.length) {
            error = `${baseName(dirRel)} has no images directly inside it`;
            render();
            return;
        }
        s.groups = [...s.groups.filter((g) => g.dir !== dirRel), {
            name: baseName(dirRel),
            category: categoryFor(dirRel, baseName(level?.root ?? "")),
            dir: dirRel,
            files,
            variants: false,
        }];
        error = "";
        save(s);
        render();
    }

    // Ticking an image edits the row for the folder being browsed: it is created
    // on the first tick and removed when its last cell is unticked.
    function toggleImage(rel, on) {
        const s = state();
        const dir = parentRel(rel);
        let g = groupAt(s, dir);
        if (on) {
            if (!g) {
                g = {
                    name: baseName(dir) || baseName(level?.root ?? "") || "row",
                    category: categoryFor(dir, baseName(level?.root ?? "")),
                    dir,
                    files: [],
                    variants: false,
                };
                s.groups = [...s.groups, g];
            }
            if (!g.files.includes(rel)) g.files.push(rel);
        } else if (g) {
            g.files = g.files.filter((f) => f !== rel);
            if (!g.files.length) s.groups = s.groups.filter((x) => x !== g);
        }
        save(s);
        render();
    }

    function renderPicked(s) {
        const wrap = el("div", `margin-top:6px;border-top:1px solid ${HUB.hairline};padding-top:5px;`);
        const cells = s.groups.reduce((n, g) => n + (g.files?.length ?? 0), 0);
        const head = el("div",
            `display:flex;align-items:center;gap:6px;color:${HUB.inkSubtle};margin-bottom:3px;`);
        head.append(el("span", "flex:1;", s.groups.length
            ? `${s.groups.length} row${s.groups.length === 1 ? "" : "s"} · ${cells} cells`
            : "nothing picked yet"));
        if (s.groups.length) {
            const clear = el("button", ghostButtonCss + "padding:2px 8px;", "clear");
            clear.className = "sym-btn";
            clear.addEventListener("pointerdown", (e) => e.stopPropagation());
            clear.addEventListener("click", () => {
                const cur = state();
                cur.groups = [];
                save(cur);
                render();
            });
            head.appendChild(clear);
        }
        wrap.appendChild(head);

        for (const g of s.groups) {
            const card = el("div", "display:flex;align-items:center;gap:6px;padding:3px 4px;"
                + `border:1px solid ${HUB.hairline};border-radius:6px;margin:3px 0;`);
            if (g.files?.[0] && level?.root) {
                const img = el("img", "width:22px;height:22px;object-fit:contain;"
                    + "background:#111;border-radius:3px;flex:none;");
                img.src = thumbUrl(level.root, g.files[0]);
                card.appendChild(img);
            }
            const nameIn = el("input",
                `flex:1;min-width:0;background:${HUB.surface1};color:${HUB.ink};`
                + `border:1px solid ${HUB.hairline};border-radius:4px;padding:2px 5px;`
                + `font:11px ${HUB.font};`);
            nameIn.className = "sym-input";
            nameIn.value = g.name;
            nameIn.title = `${g.category} · ${g.files.length} cells · ${g.dir}`;
            nameIn.addEventListener("pointerdown", (e) => e.stopPropagation());
            nameIn.addEventListener("keydown", (e) => e.stopPropagation());
            nameIn.addEventListener("change", () => {
                const cur = state();
                const target = groupAt(cur, g.dir);
                if (target) target.name = nameIn.value.trim() || target.name;
                save(cur);
                render();
            });
            card.appendChild(nameIn);
            card.appendChild(el("span", `flex:none;color:${HUB.inkTertiary};`,
                                `${g.category} · ${g.files.length}`));

            // Mirrored variants: the packer splits this row into rotations.
            const varWrap = el("label",
                `flex:none;display:flex;align-items:center;gap:3px;color:${HUB.inkSubtle};cursor:pointer;`);
            const varBox = el("input", "margin:0;cursor:pointer;");
            varBox.type = "checkbox";
            varBox.checked = !!g.variants;
            varBox.title = "Variants: let the packer mirror/rotate this row";
            varBox.addEventListener("pointerdown", (e) => e.stopPropagation());
            varBox.addEventListener("change", () => {
                const cur = state();
                const target = groupAt(cur, g.dir);
                if (target) target.variants = varBox.checked;
                save(cur);
            });
            varWrap.append(varBox, el("span", "", "var"));
            card.appendChild(varWrap);

            const del = el("button", ghostButtonCss + "padding:1px 6px;flex:none;", "✕");
            del.className = "sym-btn";
            del.addEventListener("pointerdown", (e) => e.stopPropagation());
            del.addEventListener("click", () => {
                const cur = state();
                cur.groups = cur.groups.filter((x) => x.dir !== g.dir);
                save(cur);
                render();
            });
            card.appendChild(del);
            wrap.appendChild(card);
        }
        return wrap;
    }

    function render() {
        const s = state();
        list.replaceChildren();

        const nav = navBar({ onUp: () => load(level?.parent ?? "") });
        nav.setUp(level?.parent != null);
        nav.crumb.textContent = level
            ? (level.rel || baseName(level.root) || "/")
            : "—";
        const reload = el("button", ghostButtonCss + "padding:3px 8px;flex:none;", "⟳");
        reload.className = "sym-btn";
        reload.title = "Re-read this folder";
        reload.addEventListener("pointerdown", (e) => e.stopPropagation());
        reload.addEventListener("click", () => load(readState(node).dir));
        nav.append(reload);
        list.appendChild(nav.bar);

        if (error) list.appendChild(errorLine(error));

        if (loading) {
            list.appendChild(emptyState("reading…"));
            list.appendChild(renderPicked(s));
            refit();
            return;
        }
        if (!level) {
            list.appendChild(renderPicked(s));
            refit();
            return;
        }

        list.appendChild(filterBox((v) => { filter = v; renderBody(state()); }));
        const body = el("div", "");
        body.dataset.symBody = "1";
        list.appendChild(body);
        list.appendChild(renderPicked(s));
        renderBody(s, body);
        refit();
    }

    // The current level's folders and images. Split out so typing in the filter
    // redraws only the listing, leaving the input focused.
    function renderBody(s, bodyEl) {
        const body = bodyEl ?? list.querySelector("[data-sym-body]");
        if (!body || !level) return;
        body.replaceChildren();
        const dirs = filterByName(level.dirs ?? [], filter);
        const images = filterByName(level.images ?? [], filter);

        if (!dirs.length && !images.length) {
            body.appendChild(emptyState(
                (level.dirs?.length || level.images?.length)
                    ? "no matches in this folder"
                    : "this folder is empty"));
            return;
        }

        for (const d of dirs) {
            body.appendChild(folderRow({
                name: d.name,
                checked: !!groupAt(s, d.rel),
                onToggle: (on) => toggleFolder(d.rel, on),
                onOpen: () => load(d.rel),
            }));
        }

        if (images.length) {
            const grid = el("div", "display:flex;flex-wrap:wrap;gap:4px;padding:4px 2px 0;");
            const picked = new Set(groupAt(s, level.rel)?.files ?? []);
            for (const im of images) {
                const cell = el("div",
                    `position:relative;width:${THUMB_PX}px;flex:none;cursor:pointer;`);
                cell.title = `${im.name}${im.w ? ` · ${im.w}×${im.h}` : ""}`;
                const img = el("img",
                    `width:${THUMB_PX}px;height:${THUMB_PX}px;object-fit:contain;`
                    + "background:#111;border-radius:4px;display:block;"
                    + `border:2px solid ${picked.has(im.rel) ? HUB.accent : "transparent"};`
                    + "box-sizing:border-box;");
                img.src = thumbUrl(level.root, im.rel);
                img.loading = "lazy";
                const box = el("input", "position:absolute;top:2px;left:2px;margin:0;cursor:pointer;");
                box.type = "checkbox";
                box.checked = picked.has(im.rel);
                box.addEventListener("pointerdown", (e) => e.stopPropagation());
                box.addEventListener("change", () => toggleImage(im.rel, box.checked));
                img.addEventListener("pointerdown", (e) => e.stopPropagation());
                img.addEventListener("click", () => toggleImage(im.rel, !picked.has(im.rel)));
                cell.append(img, box);
                grid.appendChild(cell);
            }
            body.appendChild(grid);
        }
    }

    // First paint: show whatever was picked before the reload, then list the
    // folder the workflow was saved on.
    render();
    load(readState(node).dir);
}

registerSymbioticaExtension(app, {
    name: "symbiotica.reference_browser",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            const selW = widgetOf(this, "selection");
            // The picks live in this widget, but it is the panel's storage, not
            // a thing to type into: collapse it (a bare .hidden is ignored by
            // the classic canvas widgets).
            if (selW) { selW.hidden = true; selW.computeSize = () => [0, -4]; }
            referencePanel(this);
        };

        // A saved workflow restores root_path/selection AFTER creation, and a
        // freshly wired root only exists once the links are in — re-list then.
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            onConfigure?.apply(this, arguments);
            queueMicrotask(() => this._symReloadBrowser?.());
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (type, index, connected, link, ioSlot) {
            onConnectionsChange?.apply(this, arguments);
            if (ioSlot?.name === "root_path") {
                queueMicrotask(() => this._symReloadBrowser?.());
            }
        };
    },
});
