// ABOUTME: Frontend for the Symbiotica order pipeline nodes — dynamic event and
// ABOUTME: group combos fed by server pushes, plus an events browser on Order Read.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

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

// --- template editor ----------------------------------------------------------
const THUMB_SIZES = { S: 18, M: 28, L: 44 };

function localImageUrl(root, rel) {
    return thumbUrl(root, rel);
}

async function fetchJson(route) {
    const res = await api.fetchApi(route);
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error ?? res.statusText);
    return res.json();
}

function widgetOf(node, name) {
    return node.widgets?.find((w) => w.name === name);
}

function readAssignments(node) {
    try {
        const parsed = JSON.parse(widgetOf(node, "assignments")?.value || "{}");
        return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
        return {};
    }
}

function writeAssignments(node, assignments) {
    const w = widgetOf(node, "assignments");
    if (w) w.value = JSON.stringify(assignments);
}

function setupTemplateEditor(node) {
    const container = document.createElement("div");
    container.style.cssText = "max-height:420px;overflow-y:auto;padding:2px;font-size:11px;";

    const state = {
        root: "",          // picked project reference folder
        images: [],        // rel paths under root
        thumb: "M",
        selectedTask: "",  // task asset name awaiting an assignment
        expanded: new Set(),
        browsing: false,
    };

    const editor = {
        restore() {
            const root = widgetOf(node, "assets_root")?.value?.trim();
            if (root && root !== state.root) {
                state.root = root;
                listAssets();
            } else {
                render();
            }
        },
    };
    node._symbioticaEditor = editor;

    async function listAssets() {
        try {
            const data = await fetchJson(
                `/symbiotica/list-assets?dir=${encodeURIComponent(state.root)}`);
            state.root = data.root;
            state.images = data.images;
        } catch (e) {
            state.images = [];
            state.error = `Could not list folder: ${e.message}`;
        }
        render();
    }

    // --- folder browser (inline panel) ---
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
            use.addEventListener("click", () => {
                state.root = info.path;
                const w = widgetOf(node, "assets_root");
                if (w) w.value = info.path;
                state.browsing = false;
                listAssets();
            });
            const cancel = document.createElement("button");
            cancel.textContent = "Cancel";
            cancel.addEventListener("click", () => {
                state.browsing = false;
                render();
            });
            actions.appendChild(use);
            actions.appendChild(cancel);
            panel.appendChild(actions);
        }
        await show(state.root || undefined);
    }

    // --- task assets (assignment targets) ---
    function renderTasks(parent) {
        const ev = pickedEventFor(node);
        const head = document.createElement("div");
        head.style.cssText = "margin:6px 0 2px;opacity:.7;text-transform:uppercase;font-size:10px;";
        head.textContent = "task assets — select one, then tick its base below";
        parent.appendChild(head);
        if (!ev) {
            const hint = document.createElement("div");
            hint.style.opacity = "0.6";
            hint.textContent = "Queue Order Read + pick a feature on Event Specs first.";
            parent.appendChild(hint);
            return;
        }
        const assignments = readAssignments(node);
        for (const a of ev.assets) {
            if (!a.assetName || !a.refFiles.length) continue;
            const row = document.createElement("div");
            const selected = state.selectedTask === a.assetName;
            row.style.cssText =
                "display:flex;gap:6px;align-items:center;padding:2px 4px;cursor:pointer;" +
                `border-radius:4px;${selected ? "background:#4a6;color:#000;" : ""}`;
            const label = document.createElement("span");
            label.style.cssText = "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
            label.textContent = a.assetName;
            row.appendChild(label);
            const assigned = document.createElement("span");
            assigned.style.cssText = "opacity:.7;max-width:45%;overflow:hidden;" +
                "text-overflow:ellipsis;white-space:nowrap;";
            const rel = assignments[a.assetName];
            assigned.textContent = rel ? rel.split("/").pop() : "— unassigned";
            row.appendChild(assigned);
            row.addEventListener("click", () => {
                state.selectedTask = selected ? "" : a.assetName;
                render();
            });
            parent.appendChild(row);
        }
    }

    // --- project assets tree ---
    function renderTree(parent) {
        const assignments = readAssignments(node);
        const head = document.createElement("div");
        head.style.cssText =
            "display:flex;justify-content:space-between;align-items:center;margin:6px 0 2px;";
        const title = document.createElement("span");
        title.style.cssText = "opacity:.7;text-transform:uppercase;font-size:10px;";
        title.textContent = `project assets · ${state.images.length}`;
        head.appendChild(title);
        const sizes = document.createElement("span");
        for (const s of Object.keys(THUMB_SIZES)) {
            const b = document.createElement("a");
            b.textContent = s;
            b.style.cssText = `cursor:pointer;margin-left:6px;${state.thumb === s ? "" : "opacity:.5;"}`;
            b.addEventListener("click", () => { state.thumb = s; render(); });
            sizes.appendChild(b);
        }
        head.appendChild(sizes);
        parent.appendChild(head);

        const byFolder = new Map();
        for (const rel of state.images) {
            const top = rel.includes("/") ? rel.split("/")[0] : "(root)";
            if (!byFolder.has(top)) byFolder.set(top, []);
            byFolder.get(top).push(rel);
        }
        const px = THUMB_SIZES[state.thumb];
        for (const [folder, rels] of byFolder) {
            const fh = document.createElement("div");
            fh.style.cssText = "cursor:pointer;padding:2px 0;";
            const open = state.expanded.has(folder);
            fh.textContent = `${open ? "▾" : "▸"} ${folder} · ${rels.length}`;
            fh.addEventListener("click", () => {
                state.expanded[open ? "delete" : "add"](folder);
                render();
            });
            parent.appendChild(fh);
            if (!open) continue;
            for (const rel of rels) {
                const row = document.createElement("div");
                row.style.cssText =
                    "display:flex;align-items:center;gap:6px;padding:1px 0 1px 12px;";
                const check = document.createElement("input");
                check.type = "checkbox";
                const owner = Object.keys(assignments).find((k) => assignments[k] === rel);
                check.checked = state.selectedTask
                    ? assignments[state.selectedTask] === rel
                    : Boolean(owner);
                check.disabled = !state.selectedTask && !owner;
                check.addEventListener("change", () => {
                    const a = readAssignments(node);
                    if (check.checked && state.selectedTask) {
                        a[state.selectedTask] = rel;
                    } else {
                        const key = state.selectedTask || owner;
                        if (key) delete a[key];
                    }
                    writeAssignments(node, a);
                    render();
                });
                row.appendChild(check);
                const img = document.createElement("img");
                img.src = localImageUrl(state.root, rel);
                img.loading = "lazy";
                img.style.cssText =
                    `width:${px}px;height:${px}px;object-fit:contain;background:#111;border-radius:3px;`;
                row.appendChild(img);
                const label = document.createElement("span");
                label.style.cssText =
                    "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
                label.textContent = rel.split("/").slice(1).join("/") || rel;
                if (owner) label.textContent += `  → ${owner}`;
                row.appendChild(label);
                parent.appendChild(row);
            }
        }
    }

    function render() {
        container.replaceChildren();
        state.error = undefined;

        const bar = document.createElement("div");
        bar.style.cssText = "display:flex;gap:6px;align-items:center;";
        const browse = document.createElement("button");
        browse.textContent = state.root ? "Change folder…" : "Browse project folder…";
        browse.addEventListener("click", () => {
            state.browsing = !state.browsing;
            render();
        });
        bar.appendChild(browse);
        if (state.root) {
            const path = document.createElement("span");
            path.style.cssText =
                "opacity:.7;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;direction:rtl;";
            path.textContent = state.root;
            path.title = state.root;
            bar.appendChild(path);
        }
        container.appendChild(bar);

        if (state.browsing) {
            renderFolderBrowser(container);
            return;
        }
        if (state.error) {
            const err = document.createElement("div");
            err.style.cssText = "color:#e66;";
            err.textContent = state.error;
            container.appendChild(err);
        }
        renderTasks(container);
        if (state.root) renderTree(container);
    }

    render();
    node.addDOMWidget("template_editor", "custom", container,
                      { serialize: false, hideOnZoom: true });
    node.size[0] = Math.max(node.size[0], 380);
}
