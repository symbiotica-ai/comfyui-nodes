// ABOUTME: Control Image node — a tree of the image folder the path names, with
// ABOUTME: a thumbnail on every row, and the picked image big beside it.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { nodeOutputString } from "./order_source.js";
import { hideWidget } from "./asset_focus.js";
import { HUB } from "./hub_theme.js";
import { CHECKER, el, emptyState, errorLine, iconButton, imageFullUrl,
         imageThumbUrl, ONE_LINE, pinPanelWidth, sidebarShell, treeRow,
         walkTree } from "./browser_chrome.js";

const NODE_CLASS = "SymbioticaControlImage";

// One node's upload is every other node's stale tree: two Control Image nodes
// on the same folder must agree after either writes.
const CHANGED_EVT = "symbiotica-control-images-changed";

const MIN_NODE_W = 460;
// The sidebar's width and its fold ride on the node's properties, not in
// widgets: they are view preferences, and a widget for either would shift the
// saved values of every workflow already holding this node.
const SIDE_PROP = "symbiotica_images_sidebar";
const SIDE_SHUT_PROP = "symbiotica_images_shut";
// Big enough to tell two masks apart at a glance, small enough that the name
// still owns the row.
const THUMB_PX = 18;
const ROW_H = "22px";

const widgetOf = (node, name) => node.widgets?.find((w) => w.name === name);
const valueText = (w) => (typeof w?.value === "string" ? w.value.trim() : "");
const isPlaceholder = (v) => !v || v.startsWith("[");
const dirOf = (rel) => (rel.includes("/") ? rel.slice(0, rel.lastIndexOf("/")) : "");
const baseOf = (rel) => rel.slice(rel.lastIndexOf("/") + 1);
const joinRel = (folder, name) => (folder ? `${folder}/${name}` : name);

// The path the last run received, kept on the node and saved with the
// workflow so a reload still knows it.
const RAN_PATH = "symbiotica_ran_path";
const ranPath = (node) => {
    const v = node?.properties?.[RAN_PATH];
    return typeof v === "string" ? v.trim().replace(/\/+$/, "") : "";
};

// The folder this node reads: its own widget, else the string the node wired
// into `path` outputs — a literal, a switch, a Studio Library path. A wire the
// canvas cannot read — a Get node, whose only widget holds the NAME of the
// constant and not its value — is answered by queueing the node: what the run
// received beats what the walk guessed, until the next run.
function pathOf(node) {
    const typed = valueText(widgetOf(node, "path"));
    if (typed) return typed.replace(/\/+$/, "");
    const link = node.inputs?.find((i) => i.name === "path")?.link;
    if (link == null) return "";
    const ran = ranPath(node);
    if (ran) return ran;
    const wire = app.graph.links[link];
    const origin = app.graph?.getNodeById?.(wire?.origin_id);
    if (!origin) return "";
    // The slot the wire left, not just the node: a Get Hub carries one constant
    // per output, so the node alone does not say which folder this is.
    return String(nodeOutputString(origin, new Set(), wire?.origin_slot ?? 0) ?? "")
        .trim().replace(/\/+$/, "");
}

async function getJson(route) {
    const r = await api.fetchApi(route);
    const body = await r.json().catch(() => ({}));
    if (!r.ok || body.error) throw new Error(body.error || `HTTP ${r.status}`);
    return body;
}

async function postJson(route, payload) {
    const r = await api.fetchApi(route, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
    });
    const body = await r.json().catch(() => ({}));
    if (!r.ok || body.error) throw new Error(body.error || `HTTP ${r.status}`);
    return body;
}

// ComfyUI's own dialogs and toasts where available, the native ones otherwise.
async function askText(message, defaultValue = "") {
    const dlg = app.extensionManager?.dialog;
    if (dlg?.prompt) {
        return await dlg.prompt({ title: "Control Image", message, defaultValue });
    }
    return prompt(message, defaultValue);
}

async function askConfirm(message) {
    const dlg = app.extensionManager?.dialog;
    if (dlg?.confirm) return await dlg.confirm({ title: "Control Image", message });
    return confirm(message);
}

function toast(severity, summary, detail) {
    app.extensionManager?.toast?.add?.({ severity, summary, detail, life: 3000 });
}

// A typed name becomes an image name: the extension it already carries, else
// `.png` — the only one you can rename INTO without the tree losing the file.
function imageName(typed) {
    const name = String(typed ?? "").trim().replace(/\\/g, "/")
        .replace(/^\/+/, "");
    if (!name) return "";
    return /\.(png|jpe?g|webp)$/i.test(name) ? name : `${name}.png`;
}

const cleanFolder = (typed) =>
    String(typed ?? "").trim().replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");

// The branches a flat list of files implies. Only for a server that does not
// send `folders` yet — a push lands new JS in a sandbox whose Python is still
// the one it booted with, and a tree with no branches would read as a node
// that has broken rather than one waiting for a restart. An empty folder is
// the only thing missing from what this derives.
function foldersFrom(files) {
    const out = new Set();
    for (const f of files) {
        for (let d = dirOf(f); d; d = dirOf(d)) out.add(d);
    }
    return [...out].sort();
}

function setupControlImage(node) {
    const imageW = widgetOf(node, "image");
    const pathW = widgetOf(node, "path");
    if (!imageW || !pathW) return;

    // The pick stays on the node — it is what Python loads and what a saved
    // workflow restores — but a dropdown for a choice the tree already makes
    // is the same control twice.
    hideWidget(imageW);

    // What the panel knows: the tree under the path it last read, the absolute
    // folder the server resolved (every preview URL is built from it), which
    // folders are open, and which row was last clicked.
    const state = { path: "", library: "", folders: null, files: null,
                    error: "", everLoaded: false, open: new Set(),
                    cursor: null, stamp: 0 };

    const picked = () => {
        const v = valueText(imageW);
        return isPlaceholder(v) ? "" : v.replace(/^\/+/, "");
    };
    // Where `new folder` and a drop with no row under it land: the folder last
    // clicked in the tree, else the one holding the picked image. `null` is
    // "nothing clicked", `""` is the library itself.
    const targetFolder = () => (state.cursor === null
        ? dirOf(picked())
        : state.cursor);
    const openAncestors = (rel) => {
        for (let dir = dirOf(rel); dir; dir = dirOf(dir)) state.open.add(dir);
    };
    // A listing is the only thing that can tell the panel a file changed under
    // it, so the URLs carry which listing they came from and a re-read is what
    // gets the browser to fetch again.
    const bust = (url) => `${url}&v=${state.stamp}`;
    const thumbFor = (rel) =>
        bust(imageThumbUrl(`${state.library}/${rel}`, THUMB_PX * 2));
    const fullFor = (rel) => bust(imageFullUrl(`${state.library}/${rel}`));

    // The dropdown is hidden, but the value still has to survive a repaint:
    // LiteGraph re-reads a combo's options, and a value absent from them is a
    // value it may drop.
    imageW.options = imageW.options ?? {};
    imageW.options.values = () => {
        const held = picked();
        const files = state.files ?? [];
        if (!files.length) return [held || "[set a path]"];
        return held && !files.includes(held) ? [...files, held] : files;
    };

    // --- the DOM -------------------------------------------------------------
    const shell = sidebarShell(node, {
        sideProp: SIDE_PROP, shutProp: SIDE_SHUT_PROP,
        repaint: () => repaint(),
        // Above both panes, so it is still there with the tree folded away —
        // which is how this node sits once an image is picked. Each result
        // carries its own thumbnail: a list of names is not how you tell two
        // renders of the same asset apart.
        search: {
            placeholder: "Search images…",
            list: () => state.files ?? [],
            lead: (rel) => {
                const t = el("img", `flex:none;width:${THUMB_PX}px;`
                    + `height:${THUMB_PX}px;object-fit:contain;border-radius:2px;`
                    + `background:${HUB.mat};`);
                t.loading = "lazy";
                t.alt = baseOf(rel);
                if (state.library) t.src = thumbFor(rel);
                return t;
            },
            onPick: (rel) => { pick(rel); },
        },
        headButtons: [
            iconButton("newFolder", "New folder", () => { void newFolder(); }),
            iconButton("refresh", "Re-read the folder",
                       () => node._symRefreshImages?.()),
        ],
    });
    const { container, tree } = shell;

    const crumb = el("div", `flex:1;min-width:0;${ONE_LINE}`
        + `font:11px ${HUB.mono};color:${HUB.inkSubtle};`);
    const dims = el("div", `flex:none;font:10px ${HUB.mono};`
        + `color:${HUB.inkTertiary};`);
    const mainHead = el("div", "display:flex;align-items:center;gap:6px;"
        + `padding:3px 6px;flex:none;background:${HUB.surface2};`
        + `border-bottom:1px solid ${HUB.hairline};`);
    mainHead.append(crumb, dims);

    const view = el("div", "flex:1;min-height:0;display:flex;padding:6px;"
        + "align-items:center;justify-content:center;overflow:hidden;"
        + `background:${HUB.surface1};`);
    // Alpha is a thing being judged here: a mask shown on flat grey reads as
    // solid when it is not, so the checker sits behind the image itself.
    const shown = el("img", "max-width:100%;max-height:100%;object-fit:contain;"
        + `display:none;background-image:${CHECKER};background-size:16px 16px;`
        + "background-position:0 0,0 8px,8px -8px,-8px 0;");
    shown.alt = "preview";
    const blank = emptyState("Pick an image in the tree.");
    view.append(shown, blank);
    shell.main.append(mainHead, view);

    // No `computeSize`: LiteGraph builds the node's MINIMUM height by summing
    // its widgets and prefers `computeSize` over `computeLayoutSize`, so
    // anything returned there becomes a floor the corner cannot drag past.
    node.addDOMWidget("images_panel", "sym_images", container, {
        serialize: false, hideOnZoom: true,
        getMinHeight: () => 60,
    });
    const syncPanelWidth = pinPanelWidth(node, container);
    node.size[0] = Math.max(node.size[0], MIN_NODE_W);

    // --- files dropped from the desktop --------------------------------------
    // The canvas has its own answer to a dropped image (it makes a Load Image
    // node), so every one of these stops where it lands.
    const dropRow = (target) => {
        for (let n = target; n && n !== tree; n = n.parentElement) {
            if (n._sym) return n._sym;
        }
        return null;
    };
    const dropFolder = (target) => {
        const row = dropRow(target);
        if (!row) return targetFolder();
        return row.kind === "folder" ? row.rel : dirOf(row.rel);
    };
    let litRow = null;
    const unlight = () => {
        if (litRow) litRow.style.outline = "";
        litRow = null;
    };
    // Which folder the drop will land in, lit while the pointer is over it:
    // the folder row under the cursor, or the whole tree when there is none.
    tree.addEventListener("dragover", (e) => {
        if (!state.path) return;
        e.preventDefault();
        e.stopPropagation();
        if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
        unlight();
        for (let n = e.target; n && n !== tree; n = n.parentElement) {
            if (n._sym?.kind === "folder") {
                n.style.outline = `1px solid ${HUB.accent}`;
                litRow = n;
                break;
            }
        }
        tree.style.outline = litRow ? "" : `1px solid ${HUB.accent}`;
    });
    tree.addEventListener("dragleave", () => {
        unlight();
        tree.style.outline = "";
    });
    tree.addEventListener("drop", (e) => {
        if (!state.path) return;
        e.preventDefault();
        e.stopPropagation();
        const folder = dropFolder(e.target);
        unlight();
        tree.style.outline = "";
        void upload(folder, [...(e.dataTransfer?.files ?? [])]);
    });

    // --- rendering -----------------------------------------------------------
    function makeRow(kind, rel, depth) {
        const actions = (onRename, onDelete) => [
            iconButton("rename", "Rename", onRename, { px: 12 }),
            iconButton("remove", "Delete", onDelete,
                       { px: 12, hover: HUB.danger }),
        ];
        if (kind === "folder") {
            const isOpen = state.open.has(rel);
            return treeRow({
                kind, rel, depth, height: ROW_H,
                tone: state.cursor === rel ? HUB.rowHover : "",
                lead: el("span", `flex:none;width:${THUMB_PX}px;`
                    + `text-align:center;color:${HUB.inkTertiary};`,
                    isOpen ? "▾" : "▸"),
                label: baseOf(rel), labelColour: HUB.ink,
                actions: actions(() => { void renameEntry(rel, "folder"); },
                                 () => { void deleteFolder(rel); }),
                onClick: () => {
                    state.cursor = rel;
                    if (isOpen) state.open.delete(rel); else state.open.add(rel);
                    render();
                },
            });
        }
        const lit = rel === picked();
        const thumb = el("img", `flex:none;width:${THUMB_PX}px;`
            + `height:${THUMB_PX}px;object-fit:contain;border-radius:2px;`
            + `background:${HUB.mat};`);
        thumb.loading = "lazy";
        thumb.alt = baseOf(rel);
        thumb.src = thumbFor(rel);
        return treeRow({
            kind, rel, depth, height: ROW_H, tone: lit ? HUB.selBg : "",
            lead: thumb,
            label: baseOf(rel), labelColour: lit ? HUB.selInk : HUB.ink,
            actions: actions(() => { void renameEntry(rel, "file"); },
                             () => { void deleteFile(rel); }),
            onClick: () => { pick(rel); },
        });
    }

    function rows() {
        if (!state.path) return [emptyState("Set the path, or wire one in.")];
        if (state.error) return [errorLine(state.error)];
        if (state.folders === null || state.files === null) {
            return [emptyState("reading the folder…")];
        }
        const out = walkTree({ folders: state.folders, files: state.files,
                               open: state.open }, makeRow);
        return out.length
            ? out : [emptyState("no images here — drop some in")];
    }

    function showImage() {
        const rel = picked();
        const src = rel && state.library ? fullFor(rel) : "";
        crumb.textContent = rel;
        crumb.title = rel && state.library ? `${state.library}/${rel}` : "";
        if (!src) {
            shown.style.display = "none";
            blank.style.display = "";
            dims.textContent = "";
            return;
        }
        shown.style.display = "";
        blank.style.display = "none";
        dims.textContent = "…";
        shown.onload = () => {
            dims.textContent = `${shown.naturalWidth} × ${shown.naturalHeight}`;
        };
        shown.onerror = () => { dims.textContent = "cannot read"; };
        if (shown.src !== src) shown.src = src;
    }

    function render() {
        const closed = shell.layout();
        const root = String(state.path || "").replace(/\/+$/, "");
        shell.sideTitle.textContent = root ? baseOf(root) || root : "no path";
        shell.sideTitle.title = state.path || "";
        // Nothing is built for a tree nobody can see; reopening rebuilds it.
        tree.replaceChildren(...(closed ? [] : rows()));
        // A listing that changed under an open result list re-matches against it.
        shell.search?.refresh();
        showImage();
        syncPanelWidth();
    }
    node._symRenderImages = render;

    const repaint = () => { render(); node.setDirtyCanvas?.(true, true); };

    const announce = () => window.dispatchEvent(
        new CustomEvent(CHANGED_EVT, { detail: { path: state.path } }));

    // --- reading and writing -------------------------------------------------
    function pick(rel) {
        if (rel === picked()) return;
        imageW.value = rel;
        imageW.callback?.call(imageW, rel);
        state.cursor = null;
        openAncestors(rel);
        repaint();
    }

    async function refresh() {
        const path = pathOf(node);
        const changed = path !== state.path;
        state.path = path;
        if (!path) {
            state.folders = null;
            state.files = null;
            state.library = "";
            state.error = "";
            repaint();
            return;
        }
        try {
            const body = await getJson(
                `/symbiotica/control-images?path=${encodeURIComponent(path)}`);
            state.folders = body.folders ?? foldersFrom(body.images ?? []);
            state.files = body.images ?? [];
            state.library = body.library ?? "";
            state.error = "";
            state.stamp += 1;
        } catch (err) {
            state.folders = null;
            state.files = null;
            state.error = String(err.message || err);
            repaint();
            return;
        }
        // A restored workflow keeps a name the listing does not hold: the file
        // may be gone for a moment, and re-pointing the node at another image
        // would quietly load the wrong one on the next queue. A path the user
        // has just changed does not.
        if (changed && state.everLoaded && !state.files.includes(picked())) {
            imageW.value = state.files[0] ?? "";
        }
        openAncestors(picked());
        state.everLoaded = true;
        repaint();
    }

    // One refresh per tick, however many hooks ask for it — a node being
    // restored is created, configured and wired in one go.
    let queued = false;
    node._symRefreshImages = () => {
        if (queued) return;
        queued = true;
        queueMicrotask(() => { queued = false; refresh(); });
    };

    // Everything at or under `rel` leaves the panel: the two listings, the
    // open folders, the cursor — and the pick, when what it named is gone.
    function dropTree(rel) {
        const under = (x) => x === rel || x.startsWith(`${rel}/`);
        state.folders = (state.folders ?? []).filter((f) => !under(f));
        state.files = (state.files ?? []).filter((f) => !under(f));
        state.open = new Set([...state.open].filter((f) => !under(f)));
        if (state.cursor !== null && under(state.cursor)) state.cursor = null;
        if (picked() && under(picked())) {
            // The first image left in whatever held the one deleted, so the
            // node is never pointed at a file that is not on disk.
            const parent = dirOf(rel);
            imageW.value = (state.files ?? [])
                .find((f) => dirOf(f) === parent) ?? state.files?.[0] ?? "";
        }
    }

    // Every name under `from` follows a rename: both listings, the open
    // folders, the cursor, and the pick.
    function moveTree(from, to) {
        const move = (rel) => (rel === from ? to
            : rel.startsWith(`${from}/`) ? to + rel.slice(from.length) : rel);
        state.folders = (state.folders ?? []).map(move).sort();
        state.files = (state.files ?? []).map(move).sort();
        state.open = new Set([...state.open].map(move));
        if (state.cursor) state.cursor = move(state.cursor);
        if (picked()) imageW.value = move(picked());
    }

    async function newFolder() {
        if (!state.path) { toast("warn", "Control Image", "Set the path first."); return; }
        const parent = targetFolder();
        const typed = await askText(
            `New folder name, inside ${parent || "the library"}:`);
        const name = cleanFolder(typed);
        if (!name) return;
        const rel = joinRel(parent, name);
        try {
            await postJson("/symbiotica/control-images-mkdir",
                           { path: state.path, name: rel });
            if (!(state.folders ?? []).includes(rel)) {
                state.folders = [...(state.folders ?? []), rel].sort();
            }
            state.cursor = rel;
            state.open.add(rel);
            openAncestors(rel);
            toast("success", "Folder created", rel);
            announce();
        } catch (err) {
            toast("error", "Control Image", String(err.message || err));
        }
        repaint();
    }

    async function renameEntry(from, kind) {
        if (!state.path || !from) return;
        const typed = await askText(
            kind === "folder" ? "Rename folder to:" : "Rename image to:",
            baseOf(from));
        const name = kind === "folder" ? cleanFolder(typed) : imageName(typed);
        if (!name || name === baseOf(from)) return;
        const to = joinRel(dirOf(from), name);
        try {
            await postJson("/symbiotica/control-images-rename",
                           { path: state.path, from, to });
            moveTree(from, to);
            toast("success", "Renamed", `${from} → ${to}`);
            announce();
        } catch (err) {
            toast("error", "Control Image", String(err.message || err));
        }
        repaint();
    }

    async function remove(rel, question) {
        if (!state.path || !rel) return;
        if (!(await askConfirm(question))) return;
        try {
            await postJson("/symbiotica/control-images-delete",
                           { path: state.path, name: rel });
            dropTree(rel);
            toast("success", "Deleted", rel);
            announce();
        } catch (err) {
            toast("error", "Control Image", String(err.message || err));
        }
        repaint();
    }

    const deleteFile = (rel) =>
        remove(rel, `Delete ${rel}?\n\nThis cannot be undone.`);

    // How much goes is the whole question: a folder row says nothing about
    // what is folded up inside it.
    function deleteFolder(rel) {
        const held = (state.files ?? [])
            .filter((f) => f.startsWith(`${rel}/`)).length;
        return remove(rel, `Delete the folder ${rel} and the ${held} image`
            + `${held === 1 ? "" : "s"} in it?\n\nThis cannot be undone.`);
    }

    async function upload(folder, files) {
        const images = files.filter((f) => /\.(png|jpe?g|webp)$/i.test(f.name));
        if (!images.length) {
            if (files.length) {
                toast("warn", "Control Image", "Only png, jpg and webp.");
            }
            return;
        }
        const form = new FormData();
        form.append("path", state.path);
        form.append("folder", folder);
        for (const f of images) form.append("files", f, f.name);
        try {
            const r = await api.fetchApi("/symbiotica/control-images-upload",
                                         { method: "POST", body: form });
            const body = await r.json().catch(() => ({}));
            if (!r.ok || body.error) {
                throw new Error(body.error || `HTTP ${r.status}`);
            }
            const saved = body.saved ?? [];
            state.files = [...new Set([...(state.files ?? []), ...saved])].sort();
            if (saved.length) {
                openAncestors(saved[0]);
                state.open.add(folder);
                imageW.value = saved[0];
                toast("success", `Added ${saved.length}`, saved.join(", "));
            }
            if (body.refused?.length) {
                toast("warn", "Not added", body.refused.join(", "));
            }
            announce();
        } catch (err) {
            toast("error", "Control Image", String(err.message || err));
        }
        // The names are the server's answer, so the tree is re-read rather
        // than guessed at: a drop of five files that collided is five names
        // nobody on this side chose.
        node._symRefreshImages?.();
    }

    const pathCb = pathW.callback;
    pathW.callback = function () {
        const out = pathCb?.apply(this, arguments);
        node._symRefreshImages();
        return out;
    };

    // Another panel wrote into the same folder.
    const onChanged = () => node._symRefreshImages();
    window.addEventListener(CHANGED_EVT, onChanged);
    const prevRemoved = node.onRemoved;
    node.onRemoved = function () {
        window.removeEventListener(CHANGED_EVT, onChanged);
        prevRemoved?.apply(this, arguments);
    };
    render();
}

registerSymbioticaExtension(app, {
    name: "symbiotica.control_image",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            // A first size for a node that has none; a saved workflow restores
            // its own over this, on configure.
            this.size[0] = Math.max(this.size[0], 620);
            this.size[1] = Math.max(this.size[1], 380);
            setupControlImage(this);
            this._symRefreshImages?.();
        };
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            onConfigure?.apply(this, arguments);
            this._symRefreshImages?.();
        };
        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            onConnectionsChange?.apply(this, arguments);
            // A newly wired path is a different library.
            this._symRefreshImages?.();
        };
    },
});

// A run hands back the folder it was given, which is the only way to read one
// that arrives through a Get node. Queue the node on its own and the tree
// fills in.
api.addEventListener("symbiotica.control_image", (event) => {
    const detail = event?.detail ?? {};
    if (detail.node_id == null) return;
    const node = app.graph?.getNodeById?.(Number(detail.node_id))
        ?? app.graph?.getNodeById?.(detail.node_id);
    if (!node) return;
    const path = typeof detail.path === "string"
        ? detail.path.trim().replace(/\/+$/, "") : "";
    if (!path || ranPath(node) === path) return;
    node.properties = node.properties ?? {};
    node.properties[RAN_PATH] = path;
    node._symRefreshImages?.();
});
