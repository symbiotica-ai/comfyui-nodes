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
    // Walk up: Specs -> Order Read; Template/Editor -> Specs -> Order Read.
    let cur = node;
    for (let hop = 0; hop < 3 && cur; hop++) {
        if (cur.comfyClass === "SymbioticaOrderRead") return orderCache.get(cur.id);
        cur = upstreamNode(cur, SPEC_INPUT_NODES.has(cur.comfyClass) ? "spec" : "events");
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
    const w = node.widgets?.find((x) => x.name === widgetName);
    if (!w) return;
    w.type = "combo";
    w.options = w.options ?? {};
    w.options.values = valuesFn; // LiteGraph accepts a function — always fresh
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
    return api.apiURL(
        `/symbiotica/local-image?path=${encodeURIComponent(`${refsRoot}/${file}`)}`
    ).replace("/api/", "/"); // route registered at server root, not under /api
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
                comboify(this, "group", () => {
                    const ev = pickedEventFor(this);
                    return ev ? templateGroups(ev).map((g) => g.template) : [];
                });
                setupTemplateEditor(this);
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
    return node.widgets?.find((w) => w.name === name);
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
    // Editor -> (spec) EventSpecs -> (events) OrderRead, by widgets not cache.
    let cur = node;
    for (let hop = 0; hop < 3 && cur; hop++) {
        if (cur.comfyClass === "SymbioticaOrderRead") return cur;
        cur = upstreamNode(cur, SPEC_INPUT_NODES.has(cur.comfyClass) ? "spec" : "events");
    }
    return null;
}

async function taskDataFor(node) {
    // Parse the order server-side from the upstream nodes' widget values, so
    // the editor works without queueing first. Falls back to the push cache.
    const orderNode = upstreamOrderRead(node);
    const orderPath = orderNode && widgetOf(orderNode, "order_path")?.value?.trim();
    const refsRoot = (orderNode && widgetOf(orderNode, "refs_path")?.value?.trim()) ?? "";
    let events = null;
    if (orderPath) {
        try {
            events = (await fetchJson(
                `/symbiotica/parse-order?order_path=${encodeURIComponent(orderPath)}` +
                `&refs_path=${encodeURIComponent(refsRoot)}`)).events;
        } catch (e) {
            console.warn("[symbiotica] parse-order failed:", e.message);
        }
    }
    if (!events) {
        const cached = orderDataFor(node);
        events = cached?.events ?? [];
    }
    const specs = upstreamNode(node, "spec");
    const feature = specs?.widgets?.find((w) => w.name === "feature")?.value;
    const ev = events.find((e) => e.feature === feature);
    const taskAssets = (ev?.assets ?? []).filter((a) => a.assetName).map((a) => ({
        assetName: a.assetName,
        category: a.category,
        canvas: a.canvas,
        prompt: a.prompt,
        refFiles: a.refFiles ?? [],
    }));
    return { taskAssets, refsRoot };
}

async function openEditorForNode(node, uiState) {
    const root = widgetOf(node, "assets_root")?.value?.trim() ?? "";
    const { taskAssets, refsRoot } = await taskDataFor(node);
    if (root && !uiState.images.length) {
        try {
            uiState.images = (await fetchJson(
                `/symbiotica/list-assets?dir=${encodeURIComponent(root)}`)).images;
        } catch { /* tree shows the set-folder hint */ }
    }
    let handle = null;

    const opts = {
        api,
        init: {
            regions: parseJsonWidget(node, "regions_json", []),
            scenePrompt: widgetOf(node, "scene_prompt")?.value ?? "",
            root,
            images: uiState.images,
            taskAssets,
            refsRoot,
            loadedName: (widgetOf(node, "sheet_file")?.value ?? "")
                .split("/").pop()?.replace(/\.png$/, "") ?? "",
        },
        imageUrl: (r, rel) => thumbUrl(r, rel),
        refImageUrl: (file) => (refsRoot ? thumbUrl(refsRoot, file) : null),
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
        saveTemplate: async (name) => {
            const state = handle.state;
            const finalName = (name || state.loadedName || "template").trim();
            // The saved sheet is ALWAYS the base sheet (assigned project art,
            // refs where unassigned) regardless of the preview toggle — the
            // task sheet is composed server-side from the regions at queue time.
            const prevMode = state.refMode;
            state.refMode = "project";
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
            const sheetW = widgetOf(node, "sheet_file");
            if (sheetW) sheetW.value = data.file;
            const regionsW = widgetOf(node, "regions_json");
            if (regionsW) regionsW.value = JSON.stringify(state.regions);
            const sceneW = widgetOf(node, "scene_prompt");
            if (sceneW) sceneW.value = state.scenePrompt;
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
    return handle;
}

function stopWheel(elem) {
    // Scrollable node panels: keep the wheel for the panel's own scroll —
    // without this LiteGraph zooms the whole graph canvas instead.
    elem.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });
}

function setupTemplateEditor(node) {
    const container = document.createElement("div");
    container.style.cssText = "max-height:340px;overflow-y:auto;padding:2px;font-size:11px;";
    stopWheel(container);
    const uiState = { images: [], browsing: false, templates: [] };

    node._symbioticaEditor = {
        restore() {
            const root = widgetOf(node, "assets_root")?.value?.trim();
            if (root) {
                fetchJson(`/symbiotica/list-assets?dir=${encodeURIComponent(root)}`)
                    .then((d) => { uiState.images = d.images; render(); })
                    .catch(() => render());
            }
            refreshGallery();
        },
    };

    async function refreshGallery() {
        try {
            uiState.templates = (await fetchJson("/symbiotica/template-list")).templates ?? [];
        } catch {
            uiState.templates = [];
        }
        render();
    }
    uiState.refreshGallery = refreshGallery;
    uiState.render = () => render();

    async function renderFolderBrowser(parent) {
        const panel = document.createElement("div");
        panel.style.cssText =
            "border:1px solid #666;border-radius:6px;margin:4px 0;padding:4px;background:#222;";
        parent.appendChild(panel);

        async function show(path) {
            let info;
            try {
                info = await fetchJson(
                    `/symbiotica/browse-dirs?path=${encodeURIComponent(path ?? "")}`);
            } catch (e) {
                panel.textContent = `Browse failed: ${e.message}`;
                return;
            }
            panel.replaceChildren();
            const cur = document.createElement("div");
            cur.style.cssText = "opacity:.8;margin-bottom:4px;word-break:break-all;";
            cur.textContent = info.path;
            panel.appendChild(cur);
            const list = document.createElement("div");
            list.style.cssText = "max-height:180px;overflow-y:auto;";
            if (info.parent) {
                const up = document.createElement("div");
                up.textContent = "⬑ ..";
                up.style.cssText = "cursor:pointer;padding:1px 4px;";
                up.addEventListener("click", () => show(info.parent));
                list.appendChild(up);
            }
            for (const d of info.dirs) {
                const row = document.createElement("div");
                row.textContent = `📁 ${d}`;
                row.style.cssText = "cursor:pointer;padding:1px 4px;white-space:nowrap;" +
                    "overflow:hidden;text-overflow:ellipsis;";
                row.addEventListener("click", () => show(`${info.path}/${d}`));
                list.appendChild(row);
            }
            panel.appendChild(list);
            const actions = document.createElement("div");
            actions.style.cssText = "display:flex;gap:6px;margin-top:4px;";
            const use = document.createElement("button");
            use.textContent = "Use this folder";
            use.addEventListener("click", async () => {
                const w = widgetOf(node, "assets_root");
                if (w) w.value = info.path;
                uiState.browsing = false;
                try {
                    const d = await fetchJson(
                        `/symbiotica/list-assets?dir=${encodeURIComponent(info.path)}`);
                    uiState.images = d.images;
                } catch {
                    uiState.images = [];
                }
                render();
            });
            const cancel = document.createElement("button");
            cancel.textContent = "Cancel";
            cancel.addEventListener("click", () => {
                uiState.browsing = false;
                render();
            });
            actions.appendChild(use);
            actions.appendChild(cancel);
            panel.appendChild(actions);
        }
        await show(widgetOf(node, "assets_root")?.value?.trim() || undefined);
    }

    function render() {
        container.replaceChildren();

        const bar = document.createElement("div");
        bar.style.cssText = "display:flex;gap:6px;align-items:center;flex-wrap:wrap;";
        const open = document.createElement("button");
        open.textContent = "↗ Open template editor";
        open.style.cssText =
            "border:1px solid #c33;color:#f66;background:#2a2a2a;border-radius:6px;" +
            "padding:4px 10px;cursor:pointer;";
        open.addEventListener("click", () => openEditorForNode(node, uiState));
        bar.appendChild(open);
        const browse = document.createElement("button");
        const root = widgetOf(node, "assets_root")?.value?.trim();
        browse.textContent = root ? "Change project folder…" : "Set project folder…";
        browse.addEventListener("click", () => {
            uiState.browsing = !uiState.browsing;
            render();
        });
        bar.appendChild(browse);
        container.appendChild(bar);

        if (root) {
            const path = document.createElement("div");
            path.style.cssText =
                "opacity:.6;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" +
                "direction:rtl;margin:2px 0;";
            path.textContent = root;
            path.title = root;
            container.appendChild(path);
        }
        if (uiState.browsing) {
            renderFolderBrowser(container);
            return;
        }

        const sheetFile = widgetOf(node, "sheet_file")?.value;
        const cur = document.createElement("div");
        cur.style.cssText = "margin:4px 0;opacity:.8;";
        cur.textContent = sheetFile
            ? `current: ${sheetFile}`
            : "no saved template — open the editor, prefill from specs, save";
        container.appendChild(cur);

        const gh = document.createElement("div");
        gh.style.cssText = "margin:6px 0 2px;opacity:.7;text-transform:uppercase;font-size:10px;";
        gh.textContent = `saved templates · ${uiState.templates.length}`;
        container.appendChild(gh);
        for (const t of uiState.templates) {
            const row = document.createElement("div");
            const active = sheetFile === t.file;
            row.style.cssText =
                "display:flex;gap:6px;align-items:center;padding:2px 4px;cursor:pointer;" +
                `border-radius:4px;border:1px solid ${active ? "#c33" : "transparent"};`;
            const label = document.createElement("span");
            label.style.cssText = "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
            label.textContent = t.name;
            const count = document.createElement("span");
            count.style.opacity = "0.6";
            count.textContent = `${t.spriteCount ?? (t.regions?.length ?? 0)} regions`;
            row.append(label, count);
            row.addEventListener("click", () => {
                const sheetW = widgetOf(node, "sheet_file");
                if (sheetW) sheetW.value = t.file;
                const regionsW = widgetOf(node, "regions_json");
                if (regionsW) regionsW.value = JSON.stringify(t.regions ?? []);
                const sceneW = widgetOf(node, "scene_prompt");
                if (sceneW && t.scenePrompt) sceneW.value = t.scenePrompt;
                render();
            });
            container.appendChild(row);
        }
    }

    render();
    refreshGallery();
    node.addDOMWidget("template_editor", "custom", container,
                      { serialize: false, hideOnZoom: true });
    node.size[0] = Math.max(node.size[0], 380);
}
