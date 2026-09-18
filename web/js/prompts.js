// ABOUTME: The Prompts node's canvas behaviour — a path, a folder dropdown of
// ABOUTME: its sub-folders, a file dropdown, the text, and save / new / new.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { nodeOutputString, resolveProjectPath } from "./order_source.js";

const NODE = "SymbioticaPromptBlock";
// Prompt Load lives in this file, not beside it: the platform syncs
// CHANGES to a pack file into a running sandbox but never ADDS a new one,
// so a node whose panel ships as its own .js comes up as raw widgets.
const LOAD_NODE = "SymbioticaPromptLoad";

// One node's save is every other node's stale view: two Prompts nodes on the
// same file must agree after either saves. Saves are announced on the window
// and every panel that is not mid-edit re-reads.
const SAVED_EVT = "symbiotica-prompts-saved";

// The path itself, in the folder dropdown. A combo cannot show "", and a
// slash is what a folder called nothing looks like.
const ROOT = "/";

// Dropdown placeholders. Bracketed so a real name can never be confused with
// one, and never sent to the server as a name.
const NO_PATH = "[set path]";
const NO_FILES = "[no files in folder]";
const LOADING = "[loading…]";

function widgetOf(node, name) {
    return (node.widgets ?? []).find((w) => w.name === name);
}

// A widget's value is not always the type its schema promises: a saved graph
// whose node gained a widget deserialises the old list one slot across. Text is
// text; anything else is nothing.
function valueText(widget) {
    return typeof widget?.value === "string" ? widget.value.trim() : "";
}

const isPlaceholder = (v) => !v || v.startsWith("[");

// The folder dropdown's value as a path relative to the root: "" for the root.
const relOf = (v) => (v === ROOT || isPlaceholder(v) ? "" : v.replace(/^\/+|\/+$/g, ""));
const joinRel = (folder, name) => (folder ? `${folder}/${name}` : name);
const dirOf = (rel) => (rel.includes("/") ? rel.slice(0, rel.lastIndexOf("/")) : "");
const baseOf = (rel) => rel.slice(rel.lastIndexOf("/") + 1);

// The path the last run received, kept on the node and saved with the
// workflow so a reload still knows it.
const RAN_PATH = "symbiotica_ran_path";
const ranPath = (node) => {
    const v = node?.properties?.[RAN_PATH];
    return typeof v === "string" ? v.trim() : "";
};

// The path a panel reads: this node's own widget, else the string the node
// wired into `path` outputs — a literal, a switch, a Studio Library path —
// climbing through an order-passing hop (Asset Focus) to the node behind it.
// A wire the canvas cannot read — a Get node, whose only widget holds the
// name of the constant and not its value — is answered by queueing the node:
// what the run received beats what the walk guessed, until the next run.
function pathOf(node, seen = new Set()) {
    if (!node || seen.has(node.id)) return "";
    seen.add(node.id);
    const typed = valueText(widgetOf(node, "path"));
    if (typed) return typed;
    const link = node.inputs?.find((i) => i.name === "path")?.link;
    if (link == null) return "";
    const ran = ranPath(node);
    if (ran) return ran;
    const origin = app.graph.getNodeById(app.graph.links[link]?.origin_id);
    if (!origin) return "";
    let found = resolveProjectPath(origin) || nodeOutputString(origin, new Set());
    if (!found && origin.inputs?.some((i) => i.name === "order")) {
        found = pathOf(origin, seen);
    }
    return found;
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
        return await dlg.prompt({ title: "Prompts", message, defaultValue });
    }
    return prompt(message, defaultValue);
}

async function askConfirm(message) {
    const dlg = app.extensionManager?.dialog;
    if (dlg?.confirm) return await dlg.confirm({ title: "Prompts", message });
    return confirm(message);
}

function toast(severity, summary, detail) {
    app.extensionManager?.toast?.add?.({ severity, summary, detail, life: 3000 });
}

// The classic node UI will not turn a text widget into a dropdown by mutating
// `.type`, so the widget is recreated as a real combo in the same slot — the
// same trick as asset_focus.js. Value and serialisation are preserved, so the
// string still reaches Python and a saved workflow still restores it.
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

// A button the queue never sees, placed before the widget named `before` so
// each button sits under the field it acts on and the textarea stays last.
function addButton(node, label, before, action) {
    const w = node.addWidget("button", label, null, action, { serialize: false });
    w.serializeValue = () => undefined;
    const i = node.widgets.findIndex((x) => x.name === before);
    if (i >= 0) {
        node.widgets = node.widgets.filter((x) => x !== w);
        node.widgets.splice(i, 0, w);
    }
    return w;
}

// A typed name becomes a prompt file: `.md` unless it already says `.txt`.
function fileName(typed) {
    let name = String(typed ?? "").trim().replace(/\\/g, "/").replace(/^\/+/, "");
    if (!name) return "";
    if (!/\.(md|txt)$/i.test(name)) name += ".md";
    return name;
}

const cleanFolder = (typed) =>
    String(typed ?? "").trim().replace(/\\/g, "/").replace(/^\/+|\/+$/g, "");

function setupPrompts(node) {
    const pathW = widgetOf(node, "path");
    const textW = widgetOf(node, "text");
    if (!pathW || !textW) return;

    // What the panel knows: the tree under the path it last read (every
    // sub-folder and every file, relative to it), the text as it was on disk
    // when loaded (the edit is the difference), and the file it is showing.
    const state = { path: "", folders: null, files: null, error: "",
                    loaded: "", picked: "", everLoaded: false };
    const text = () => (typeof textW.value === "string" ? textW.value : "");
    const dirty = () => text() !== state.loaded;

    const folderW = comboify(node, "folder", () => {
        const held = valueText(folderW);
        const folders = state.folders ?? [];
        const offered = [ROOT, ...folders];
        if (!state.path) return [isPlaceholder(held) ? NO_PATH : held];
        if (state.folders === null) {
            return [state.error ? `[${state.error}]` : LOADING];
        }
        // A held folder gone from disk stays offered rather than silently
        // re-pointing the node at the root.
        const rel = relOf(held);
        return rel && !folders.includes(rel) ? [...offered, rel] : offered;
    });
    const folderRel = () => relOf(valueText(folderW));
    const filesIn = (folder) => (state.files ?? [])
        .filter((f) => dirOf(f) === folder).map(baseOf);

    const fileW = comboify(node, "file", () => {
        const held = valueText(fileW);
        if (!state.path) return [isPlaceholder(held) ? NO_PATH : held];
        if (state.files === null) {
            return [state.error ? `[${state.error}]` : LOADING];
        }
        const files = filesIn(folderRel());
        if (files.length) {
            return isPlaceholder(held) || files.includes(held)
                ? files : [...files, held];
        }
        return isPlaceholder(held) ? [NO_FILES] : [held];
    });
    // The file as the server names it: relative to the path.
    const fileRel = () => {
        const name = valueText(fileW);
        return isPlaceholder(name) ? "" : joinRel(folderRel(), name);
    };

    const repaint = () => node.setDirtyCanvas?.(true, true);

    async function load({ keep = "" } = {}) {
        const rel = fileRel();
        state.picked = rel;
        if (!state.path || !rel) return;
        if (!(state.files ?? []).includes(rel)) {
            state.loaded = "";
            if (!keep) textW.value = "";
            repaint();
            return;
        }
        try {
            const { text: body } = await getJson(
                `/symbiotica/prompts-read?folder=${encodeURIComponent(state.path)}`
                + `&name=${encodeURIComponent(rel)}`);
            state.loaded = body;
            // A workflow restored with an edit that never reached disk keeps
            // the edit; anything else shows the file.
            if (!keep || keep === body) textW.value = body;
        } catch (err) {
            toast("error", "Prompts", String(err.message || err));
        }
        repaint();
    }

    // Show the folder's first file when the held name is not in it — a
    // folder change is a different list. Only a restored workflow keeps a
    // name the folder does not hold: the file may be unsaved, and dropping
    // it would re-point the node. A folder the user just moved to does not.
    function pickFile(keepMissing = false) {
        const files = filesIn(folderRel());
        const held = valueText(fileW);
        if (isPlaceholder(held) || !files.includes(held)) {
            fileW.value = files[0]
                ?? (keepMissing && !isPlaceholder(held) ? held : "");
        }
    }

    // Re-list the tree under the path and show the picked file. The first
    // load keeps any text the widget already holds: a restored workflow
    // carries an edit that may never have reached disk, and the file is read
    // for the baseline only.
    async function refresh() {
        const path = pathOf(node);
        const changed = path !== state.path;
        state.path = path;
        const keep = state.everLoaded ? "" : text();
        if (!path) {
            state.folders = null;
            state.files = null;
            state.error = "";
            repaint();
            return;
        }
        try {
            // A path arrived at for the first time is a browse-session open:
            // refresh the mount, so a file added from the platform's file
            // manager is on it. Later refreshes of the same path list what is
            // already there — the walk is a FUSE traversal, not a free call.
            const { folders, files } = await getJson(
                `/symbiotica/prompts-list?folder=${encodeURIComponent(path)}`
                + (changed ? "&sync=1" : ""));
            state.folders = folders ?? [];
            state.files = files ?? [];
            state.error = "";
        } catch (err) {
            state.folders = null;
            state.files = null;
            state.error = String(err.message || err);
            repaint();
            return;
        }
        if (isPlaceholder(valueText(folderW))) folderW.value = ROOT;
        if (changed || isPlaceholder(valueText(fileW))) {
            pickFile(!state.everLoaded);
        }
        if (!(dirty() && !changed && state.everLoaded)) await load({ keep });
        state.everLoaded = true;
        repaint();
    }

    // One refresh per tick, however many hooks ask for it — a node being
    // restored is created, configured and wired in one go.
    let queued = false;
    node._symRefreshPrompts = () => {
        if (queued) return;
        queued = true;
        queueMicrotask(() => { queued = false; refresh(); });
    };

    const announce = () =>
        window.dispatchEvent(new CustomEvent(SAVED_EVT, { detail: { path: state.path } }));

    // Leaving an unsaved edit is asked about, whichever dropdown moves.
    async function mayLeave() {
        return !dirty() || await askConfirm("Discard your unsaved edit?");
    }

    const folderCb = folderW.callback;
    folderW.callback = async function () {
        const out = folderCb?.apply(this, arguments);
        if (!(await mayLeave())) {
            folderW.value = dirOf(state.picked) || ROOT;
            return out;
        }
        pickFile();
        await load();
        return out;
    };

    const fileCb = fileW.callback;
    fileW.callback = async function () {
        const out = fileCb?.apply(this, arguments);
        if (!(await mayLeave())) {
            fileW.value = baseOf(state.picked);
            return out;
        }
        await load();
        return out;
    };

    const pathCb = pathW.callback;
    pathW.callback = function () {
        const out = pathCb?.apply(this, arguments);
        node._symRefreshPrompts();
        return out;
    };

    // Every name under `from` follows a folder rename, in both listings.
    function moveTree(from, to) {
        const move = (rel) => (rel === from ? to
            : rel.startsWith(`${from}/`) ? to + rel.slice(from.length) : rel);
        state.folders = (state.folders ?? []).map(move).sort();
        state.files = (state.files ?? []).map(move).sort();
        state.picked = move(state.picked);
    }

    addButton(node, "new folder", "file", async () => {
        if (!state.path) { toast("warn", "Prompts", "Set the path first."); return; }
        if (!(await mayLeave())) return;
        const parent = folderRel();
        const typed = await askText(
            `New folder name, inside ${parent || "the path"}:`);
        const name = cleanFolder(typed);
        if (!name) return;
        const rel = joinRel(parent, name);
        try {
            await postJson("/symbiotica/prompts-mkdir",
                           { folder: state.path, name: rel });
            if (!(state.folders ?? []).includes(rel)) {
                state.folders = [...(state.folders ?? []), rel].sort();
            }
            folderW.value = rel;
            pickFile();
            await load();
            toast("success", "Folder created", rel);
        } catch (err) {
            toast("error", "Prompts", String(err.message || err));
        }
    });

    addButton(node, "rename folder", "file", async () => {
        const from = folderRel();
        if (!state.path || !from) {
            toast("warn", "Prompts", "Pick a sub-folder to rename.");
            return;
        }
        const typed = await askText("Rename folder to:", baseOf(from));
        const name = cleanFolder(typed);
        if (!name || name === baseOf(from)) return;
        const to = joinRel(dirOf(from), name);
        try {
            await postJson("/symbiotica/prompts-rename",
                           { folder: state.path, from, to });
            moveTree(from, to);
            folderW.value = to;
            toast("success", "Folder renamed", `${from} → ${to}`);
            announce();
        } catch (err) {
            toast("error", "Prompts", String(err.message || err));
        }
    });

    addButton(node, "new file", "text", async () => {
        if (!state.path) { toast("warn", "Prompts", "Set the path first."); return; }
        if (!(await mayLeave())) return;
        const folder = folderRel();
        const typed = await askText(
            `New file name, inside ${folder || "the path"}:`);
        const name = fileName(typed);
        if (!name) return;
        const rel = joinRel(folder, name);
        try {
            if (!(state.files ?? []).includes(rel)) {
                await postJson("/symbiotica/prompts-write",
                               { folder: state.path, name: rel, text: "" });
                state.files = [...(state.files ?? []), rel].sort();
            }
            fileW.value = name;
            await load();
            announce();
        } catch (err) {
            toast("error", "Prompts", String(err.message || err));
        }
    });

    addButton(node, "rename file", "text", async () => {
        const from = fileRel();
        if (!state.path || !from) {
            toast("warn", "Prompts", "Pick a file to rename.");
            return;
        }
        const typed = await askText("Rename file to:", baseOf(from));
        const name = fileName(typed);
        if (!name || name === baseOf(from)) return;
        const to = joinRel(dirOf(from), name);
        try {
            await postJson("/symbiotica/prompts-rename",
                           { folder: state.path, from, to });
            moveTree(from, to);
            fileW.value = name;
            toast("success", "File renamed", `${from} → ${to}`);
            announce();
        } catch (err) {
            toast("error", "Prompts", String(err.message || err));
        }
    });

    addButton(node, "save file", "text", async () => {
        const rel = fileRel();
        if (!state.path || !rel) {
            toast("warn", "Prompts", "Set the path and pick a file first.");
            return;
        }
        try {
            const body = text();
            const res = await postJson("/symbiotica/prompts-write",
                                       { folder: state.path, name: rel, text: body });
            state.loaded = body;
            if (!(state.files ?? []).includes(rel)) {
                state.files = [...(state.files ?? []), rel].sort();
            }
            toast("success", "Saved", `${rel} — ${res.chars} chars`);
            announce();
        } catch (err) {
            toast("error", "Prompts", String(err.message || err));
        }
    });

    // Another panel saved: re-read unless this one is mid-edit.
    const onSaved = () => { if (!dirty()) node._symRefreshPrompts(); };
    window.addEventListener(SAVED_EVT, onSaved);
    const prevRemoved = node.onRemoved;
    node.onRemoved = function () {
        window.removeEventListener(SAVED_EVT, onSaved);
        prevRemoved?.apply(this, arguments);
    };
}

// --- Prompt Load ------------------------------------------------------------
// The same folder, read-only: one dropdown of every prompt file under the path,
// flat, because there is no second dropdown here to split the sub-folder out.
function setupPromptLoad(node) {
    const state = { path: "", files: null, error: "", everLoaded: false };
    const repaint = () => node.setDirtyCanvas?.(true, true);

    const fileW = comboify(node, "file", () => {
        const held = valueText(fileW);
        if (!state.path) return [isPlaceholder(held) ? NO_PATH : held];
        if (state.files === null) {
            return [state.error ? `[${state.error}]` : LOADING];
        }
        if (!state.files.length) return isPlaceholder(held) ? [NO_FILES] : [held];
        // A held name gone from disk stays offered rather than silently
        // re-pointing the node at another prompt.
        return isPlaceholder(held) || state.files.includes(held)
            ? state.files : [...state.files, held];
    });
    if (!fileW) return;

    async function refresh() {
        const path = pathOf(node);
        const changed = path !== state.path;
        state.path = path;
        if (!path) {
            state.files = null;
            state.error = "";
            repaint();
            return;
        }
        try {
            const { files } = await getJson(
                `/symbiotica/prompts-list?folder=${encodeURIComponent(path)}`
                + (changed ? "&sync=1" : ""));
            state.files = files ?? [];
            state.error = "";
        } catch (err) {
            state.files = null;
            state.error = String(err.message || err);
            repaint();
            return;
        }
        if (changed || isPlaceholder(valueText(fileW))) {
            const held = valueText(fileW);
            // A restored workflow keeps a name the listing does not hold: the
            // file may be gone for a moment, and re-pointing the node at
            // another prompt would quietly load the wrong text on the next
            // queue. A path the user has just changed does not.
            const keep = !state.everLoaded && !isPlaceholder(held);
            if (!keep && (isPlaceholder(held) || !state.files.includes(held))) {
                fileW.value = state.files[0] ?? "";
            }
        }
        state.everLoaded = true;
        repaint();
    }

    let queued = false;
    node._symRefreshPromptLoad = () => {
        if (queued) return;
        queued = true;
        queueMicrotask(() => { queued = false; refresh(); });
    };

    const pathW = widgetOf(node, "path");
    if (pathW) {
        const pathCb = pathW.callback;
        pathW.callback = function () {
            const out = pathCb?.apply(this, arguments);
            node._symRefreshPromptLoad();
            return out;
        };
    }

    // A Prompts panel wrote a file: nobody should have to reload to load the
    // prompt they just saved.
    const onSaved = () => node._symRefreshPromptLoad();
    window.addEventListener(SAVED_EVT, onSaved);
    const prevRemoved = node.onRemoved;
    node.onRemoved = function () {
        window.removeEventListener(SAVED_EVT, onSaved);
        prevRemoved?.apply(this, arguments);
    };
}

function installPromptLoad(nodeType) {
    const orig = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
        orig?.apply(this, arguments);
        try {
            setupPromptLoad(this);
            this._symRefreshPromptLoad?.();
        } catch (err) {
            console.error("[Symbiotica] Prompt Load setup failed", err);
        }
    };
    const origCfg = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
        origCfg?.apply(this, arguments);
        this._symRefreshPromptLoad?.();
    };
    const origConn = nodeType.prototype.onConnectionsChange;
    nodeType.prototype.onConnectionsChange = function () {
        origConn?.apply(this, arguments);
        // A newly wired path is a different folder.
        this._symRefreshPromptLoad?.();
    };
}

registerSymbioticaExtension(app, {
    name: "symbiotica.prompts",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData?.name === LOAD_NODE) { installPromptLoad(nodeType); return; }
        if (nodeData.name !== NODE) return;
        const orig = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            orig?.apply(this, arguments);
            this.size[0] = Math.max(this.size[0], 380);
            this.size[1] = Math.max(this.size[1], 340);
            setupPrompts(this);
            this._symRefreshPrompts?.();
        };
        const origCfg = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            origCfg?.apply(this, arguments);
            this._symRefreshPrompts?.();
        };
        const origConn = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            origConn?.apply(this, arguments);
            // A newly wired path is a different tree.
            this._symRefreshPrompts?.();
        };
    },
});

// A run hands back the path it was given, which is the only way to read one
// that arrives through a Get node. Queue the node on its own and the tree
// below it fills in.
api.addEventListener("symbiotica.prompts", (event) => {
    const detail = event?.detail ?? {};
    if (detail.node_id == null) return;
    const node = app.graph?.getNodeById?.(Number(detail.node_id))
        ?? app.graph?.getNodeById?.(detail.node_id);
    if (!node) return;
    const path = typeof detail.path === "string" ? detail.path.trim() : "";
    if (!path || ranPath(node) === path) return;
    node.properties = node.properties ?? {};
    node.properties[RAN_PATH] = path;
    node._symRefreshPrompts?.();
});

// The same for Prompt Load: one queue and the dropdown knows the folder.
api.addEventListener("symbiotica.prompt_load", (event) => {
    const detail = event?.detail ?? {};
    if (detail.node_id == null) return;
    const node = app.graph?.getNodeById?.(Number(detail.node_id))
        ?? app.graph?.getNodeById?.(detail.node_id);
    if (!node) return;
    const path = typeof detail.path === "string" ? detail.path.trim() : "";
    if (!path || ranPath(node) === path) return;
    node.properties = node.properties ?? {};
    node.properties[RAN_PATH] = path;
    node._symRefreshPromptLoad?.();
});
