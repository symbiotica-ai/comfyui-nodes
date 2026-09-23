// ABOUTME: The Prompts node's canvas behaviour — a file tree of the folder the
// ABOUTME: path names beside an editor for the file clicked in it.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { nodeOutputString, resolveProjectPath } from "./order_source.js";
import { hideWidget } from "./asset_focus.js";
import { HUB, ghostButtonCss } from "./hub_theme.js";
import { el, emptyState, errorLine, iconButton, ONE_LINE, pinPanelWidth,
         sidebarShell, treeRow, walkTree } from "./browser_chrome.js";

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
    const wire = app.graph.links[link];
    const origin = app.graph.getNodeById(wire?.origin_id);
    if (!origin) return "";
    // The slot the wire left, not just the node: a Get Hub carries one constant
    // per output, so the node alone does not say which path this is.
    let found = resolveProjectPath(origin)
        || nodeOutputString(origin, new Set(), wire?.origin_slot ?? 0);
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

// ComfyUI's own textarea for `text` is the editor's twin: the value has to stay
// on the widget — it is what Python reads and what the workflow saves — but the
// box belongs in the panel, beside the tree. `hidden` takes it out of the node's
// layout; the element is hidden too, because a DOM widget's element is not the
// layout's to remove.
function hideTextWidget(w) {
    if (!w) return;
    hideWidget(w);
    if (w.element?.style) w.element.style.display = "none";
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

// --- the file browser --------------------------------------------------------
// This node manages a library of prompt files, so it is laid out like an editor
// for one: the tree on the left, the open file on the right, the actions as
// icons in the two headers. What this replaces was five full-width buttons
// stacked down the node — more of the node spent on `rename folder` than on the
// prompt being written.

const MIN_NODE_W = 460;
// The sidebar's width and its fold ride on the node's properties, not in
// widgets: they are view preferences, and a widget for either would shift the
// saved values of every workflow already holding this node.
const SIDE_PROP = "symbiotica_prompts_sidebar";
const SIDE_SHUT_PROP = "symbiotica_prompts_shut";

function setupPrompts(node) {
    const pathW = widgetOf(node, "path");
    const textW = widgetOf(node, "text");
    const folderW = widgetOf(node, "folder");
    const fileW = widgetOf(node, "file");
    if (!pathW || !textW || !folderW || !fileW) return;

    // The three the browser now drives. They stay on the node — they are what
    // Python reads and what a saved workflow restores, and removing one would
    // shift every value saved after it — but a dropdown for a choice the tree
    // already makes is the same control twice.
    hideWidget(folderW);
    hideWidget(fileW);
    hideTextWidget(textW);

    // What the panel knows: the tree under the path it last read (every
    // sub-folder and every file, relative to it), the text as it was on disk
    // when loaded (the edit is the difference), the file it is showing, which
    // folders are open, and which row was last clicked.
    const state = { path: "", folders: null, files: null, error: "",
                    loaded: "", everLoaded: false,
                    open: new Set(), cursor: null };
    const text = () => (typeof textW.value === "string" ? textW.value : "");
    const dirty = () => text() !== state.loaded;

    const folderRel = () => relOf(valueText(folderW));
    const filesIn = (folder) => (state.files ?? [])
        .filter((f) => dirOf(f) === folder).map(baseOf);
    // The open file as the server names it: relative to the path.
    const fileRel = () => {
        const name = valueText(fileW);
        return isPlaceholder(name) ? "" : joinRel(folderRel(), name);
    };
    // Where `new file` and `new folder` land: the folder last clicked in the
    // tree, else the one holding the open file. `null` is "nothing clicked",
    // `""` is the path itself — a folder you can deliberately be in.
    const targetFolder = () => (state.cursor === null
        ? dirOf(fileRel())
        : state.cursor);
    const openAncestors = (rel) => {
        for (let dir = dirOf(rel); dir; dir = dirOf(dir)) state.open.add(dir);
    };

    // --- the DOM -------------------------------------------------------------
    const shell = sidebarShell(node, {
        sideProp: SIDE_PROP, shutProp: SIDE_SHUT_PROP,
        repaint: () => repaint(),
        // Above both panes, so it is still there with the tree folded away —
        // which is how this node sits once a prompt is open.
        search: {
            placeholder: "Search prompts…",
            list: () => state.files ?? [],
            onPick: (rel) => { void openFile(rel); },
        },
        headButtons: [
            iconButton("newFile", "New file", () => { void newFile(); }),
            iconButton("newFolder", "New folder", () => { void newFolder(); }),
            iconButton("refresh", "Re-read the folder",
                       () => node._symRefreshPrompts?.()),
        ],
    });
    const { container, tree } = shell;

    const crumb = el("div", `flex:1;min-width:0;${ONE_LINE}`
        + `font:11px ${HUB.mono};color:${HUB.inkSubtle};`);
    // The unsaved dot, where an editor puts it: on the name of the file that
    // has one.
    const dot = el("span", "flex:none;width:6px;height:6px;border-radius:50%;"
        + `background:${HUB.accent};display:none;`);
    // A button that is off does nothing, whatever reaches it: `disabled`
    // stops a real click, and the guard stops one fired any other way.
    const headButton = (label, title, onClick) => {
        const b = el("button",
            ghostButtonCss + "padding:2px 8px;flex:none;font-size:11px;", label);
        b.className = "sym-btn";
        b.title = title;
        b.addEventListener("pointerdown", (e) => e.stopPropagation());
        b.addEventListener("click", (e) => {
            e.stopPropagation();
            if (!b.disabled) void onClick();
        });
        return b;
    };
    const discardBtn = headButton("discard",
        "Discard your edits and show the file as it is on disk", () => discard());
    const saveAsBtn = headButton("save as",
        "Save as a new file; this one stays as it is on disk", () => saveAs());
    const saveBtn = headButton("save", "Save this file (⌘S)", () => save());
    const mainHead = el("div", "display:flex;align-items:center;gap:6px;"
        + `padding:3px 6px;flex:none;background:${HUB.surface2};`
        + `border-bottom:1px solid ${HUB.hairline};`);
    mainHead.append(dot, crumb, discardBtn, saveAsBtn, saveBtn);

    const area = el("textarea", "flex:1;min-height:0;width:100%;"
        + "box-sizing:border-box;resize:none;border:0;outline:none;"
        + `padding:6px 8px;background:${HUB.surface1};`
        + `color:var(--input-text, ${HUB.ink});font:12px/1.5 ${HUB.mono};`);
    area.className = "sym-input";
    area.spellcheck = false;
    area.placeholder = "Pick a file in the tree.";
    // A DOM widget sits on the LiteGraph canvas: without this, typing moves the
    // graph and the canvas eats the keystrokes.
    area.addEventListener("keydown", (e) => {
        e.stopPropagation();
        const key = String(e.key ?? "").toLowerCase();
        if (key === "s" && (e.metaKey || e.ctrlKey)) {
            e.preventDefault?.();
            void save();
        }
    });
    area.addEventListener("pointerdown", (e) => e.stopPropagation());
    area.addEventListener("input", () => {
        textW.value = area.value;
        paintDirty();
    });
    shell.main.append(mainHead, area);

    // No `computeSize`: LiteGraph builds the node's MINIMUM height by summing
    // its widgets and prefers `computeSize` over `computeLayoutSize`, so
    // anything returned there becomes a floor the corner cannot drag past. A
    // constant floor, and the layout hands this widget the rest of the body.
    node.addDOMWidget("prompts_panel", "sym_prompts", container, {
        serialize: false, hideOnZoom: true,
        getMinHeight: () => 60,
    });
    // The wrapper ComfyUI gives a DOM widget lags a SHRINK, so pin it or the
    // panel paints over the canvas to the right of a narrowed node.
    const syncPanelWidth = pinPanelWidth(node, container);
    node.size[0] = Math.max(node.size[0], MIN_NODE_W);

    // --- rendering -----------------------------------------------------------
    // Two tones, never one: the OPEN file is filled (it is what the editor and
    // the node's output are showing) and the folder last clicked is only
    // shaded — a second full highlight reads as a second open file.
    function makeRow(kind, rel, depth) {
        const actions = (onRename, onDelete) => [
            iconButton("rename", "Rename", onRename, { px: 12 }),
            iconButton("remove", "Delete", onDelete,
                       { px: 12, hover: HUB.danger }),
        ];
        if (kind === "folder") {
            const isOpen = state.open.has(rel);
            return treeRow({
                kind, rel, depth,
                tone: state.cursor === rel ? HUB.rowHover : "",
                lead: el("span", `flex:none;width:9px;color:${HUB.inkTertiary};`,
                         isOpen ? "▾" : "▸"),
                label: baseOf(rel), labelColour: HUB.ink,
                actions: actions(() => { void renameFolder(rel); },
                                 () => { void deleteFolder(rel); }),
                onClick: () => {
                    state.cursor = rel;
                    if (isOpen) state.open.delete(rel); else state.open.add(rel);
                    render();
                },
            });
        }
        const lit = rel === fileRel();
        return treeRow({
            kind, rel, depth, tone: lit ? HUB.selBg : "",
            lead: el("span", "flex:none;width:9px;"),
            label: baseOf(rel), labelColour: lit ? HUB.selInk : HUB.ink,
            actions: actions(() => { void renameFile(rel); },
                             () => { void deleteFile(rel); }),
            onClick: () => { void openFile(rel); },
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
        return out.length ? out : [emptyState("no prompt files here")];
    }

    // What the head offers is what the file's state allows. `save` and
    // `discard` only mean something while the editor differs from disk, and
    // `save` is then the one filled control on the panel. `save as` works on
    // a clean file too: it is how one prompt becomes the start of the next.
    const enable = (b, on) => {
        b.disabled = !on;
        b.style.opacity = on ? "" : "0.4";
        b.style.cursor = on ? "pointer" : "default";
    };
    function paintDirty() {
        const open = !!fileRel();
        const has = open && dirty();
        dot.style.display = has ? "" : "none";
        enable(discardBtn, has);
        enable(saveAsBtn, open);
        enable(saveBtn, has);
        saveBtn.style.background = has ? HUB.accent : "transparent";
        saveBtn.style.color = has ? HUB.onAccent : HUB.inkSubtle;
        saveBtn.style.borderColor = has ? HUB.accent : HUB.hairline;
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
        const open = fileRel();
        crumb.textContent = open || "";
        crumb.title = open ? `${state.path}/${open}` : "";
        // Never over the user's own typing: the input handler already wrote
        // what they typed onto the widget, so these differ only when a load,
        // an undo or a restore changed it underneath.
        if (area.value !== text()) area.value = text();
        area.disabled = !open;
        paintDirty();
        syncPanelWidth();
    }
    // The render belongs to the node, so a refresh from anywhere reaches it.
    node._symRenderPrompts = render;

    const repaint = () => { render(); node.setDirtyCanvas?.(true, true); };

    // --- reading and writing -------------------------------------------------
    async function load({ keep = "" } = {}) {
        const rel = fileRel();
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

    // Show the folder's first file when the held name is not in it — a folder
    // change is a different list. Only a restored workflow keeps a name the
    // folder does not hold: the file may be unsaved, and dropping it would
    // re-point the node.
    function pickFile(keepMissing = false) {
        const files = filesIn(folderRel());
        const held = valueText(fileW);
        if (isPlaceholder(held) || !files.includes(held)) {
            fileW.value = files[0]
                ?? (keepMissing && !isPlaceholder(held) ? held : "");
        }
    }

    // Re-list the tree under the path and show the picked file. The first load
    // keeps any text the widget already holds: a restored workflow carries an
    // edit that may never have reached disk, and the file is read for the
    // baseline only.
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
        // The open file is visible in the tree without hunting for it.
        openAncestors(fileRel());
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

    // Leaving an unsaved edit is asked about, whatever the click was.
    async function mayLeave() {
        return !dirty() || await askConfirm("Discard your unsaved edit?");
    }

    async function openFile(rel) {
        if (rel === fileRel() || !(await mayLeave())) return;
        folderW.value = dirOf(rel) || ROOT;
        fileW.value = baseOf(rel);
        state.cursor = null;
        openAncestors(rel);
        await load();
        repaint();
    }

    // Every name under `from` follows a rename: both listings, the open
    // folders, the cursor, and the file on screen.
    function moveTree(from, to) {
        const move = (rel) => (rel === from ? to
            : rel.startsWith(`${from}/`) ? to + rel.slice(from.length) : rel);
        state.folders = (state.folders ?? []).map(move).sort();
        state.files = (state.files ?? []).map(move).sort();
        state.open = new Set([...state.open].map(move));
        if (state.cursor) state.cursor = move(state.cursor);
        const open = fileRel();
        if (open && move(open) !== open) {
            folderW.value = dirOf(move(open)) || ROOT;
            fileW.value = baseOf(move(open));
        }
    }

    async function save() {
        const rel = fileRel();
        if (!state.path || !rel) {
            toast("warn", "Prompts", "Pick a file first.");
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
        repaint();
    }

    // Back to the file as it is on disk -- read again rather than the copy
    // taken at load, because a panel mid-edit is the one that skipped the
    // re-read when another panel saved the same file.
    async function discard() {
        const rel = fileRel();
        if (!rel || !dirty()) return;
        if (!(await askConfirm(`Discard your edits to ${rel}?`))) return;
        textW.value = state.loaded;
        await load();
    }

    // The editor written to a NEW file beside this one, which the node then
    // shows; the file it came from stays as it is on disk. A name that is
    // taken is asked about, never replaced quietly.
    async function saveAs() {
        const from = fileRel();
        if (!state.path || !from) {
            toast("warn", "Prompts", "Pick a file first.");
            return;
        }
        const folder = dirOf(from);
        const base = baseOf(from);
        const ext = base.match(/\.(md|txt)$/i)?.[0] ?? "";
        const stem = ext ? base.slice(0, -ext.length) : base;
        const typed = await askText(`Save as, inside ${folder || "the path"}:`,
                                    `${stem}-copy${ext || ".md"}`);
        const name = fileName(typed);
        if (!name) return;
        const rel = joinRel(folder, name);
        if (rel === from) { await save(); return; }
        if ((state.files ?? []).includes(rel)
            && !(await askConfirm(`${rel} already exists. Replace it?`))) return;
        try {
            const body = text();
            await postJson("/symbiotica/prompts-write",
                           { folder: state.path, name: rel, text: body });
            if (!(state.files ?? []).includes(rel)) {
                state.files = [...(state.files ?? []), rel].sort();
            }
            folderW.value = dirOf(rel) || ROOT;
            fileW.value = baseOf(rel);
            state.loaded = body;
            state.cursor = null;
            openAncestors(rel);
            toast("success", "Saved as", rel);
            announce();
        } catch (err) {
            toast("error", "Prompts", String(err.message || err));
        }
        repaint();
    }

    async function newFile() {
        if (!state.path) { toast("warn", "Prompts", "Set the path first."); return; }
        if (!(await mayLeave())) return;
        const folder = targetFolder();
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
            folderW.value = folder || ROOT;
            fileW.value = name;
            state.cursor = null;
            openAncestors(rel);
            await load();
            announce();
        } catch (err) {
            toast("error", "Prompts", String(err.message || err));
        }
        repaint();
    }

    // A new folder does not close the file you are in: it is a place to put
    // the next one.
    async function newFolder() {
        if (!state.path) { toast("warn", "Prompts", "Set the path first."); return; }
        const parent = targetFolder();
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
            state.cursor = rel;
            state.open.add(rel);
            openAncestors(rel);
            toast("success", "Folder created", rel);
        } catch (err) {
            toast("error", "Prompts", String(err.message || err));
        }
        repaint();
    }

    // Everything at or under `rel` leaves the panel: the two listings, the open
    // folders, the cursor — and the editor, when what it was showing is gone.
    function dropTree(rel) {
        const under = (x) => x === rel || x.startsWith(`${rel}/`);
        state.folders = (state.folders ?? []).filter((f) => !under(f));
        state.files = (state.files ?? []).filter((f) => !under(f));
        state.open = new Set([...state.open].filter((f) => !under(f)));
        if (state.cursor !== null && under(state.cursor)) state.cursor = null;
        if (fileRel() && under(fileRel())) {
            // Up to whatever held what was deleted, and empty: the next
            // listing picks the first file there rather than leaving the node
            // pointed at a folder that is not on disk any more.
            folderW.value = dirOf(rel) || ROOT;
            fileW.value = "";
            textW.value = "";
            state.loaded = "";
        }
    }

    async function remove(rel, question) {
        if (!state.path || !rel) return;
        if (!(await askConfirm(question))) return;
        try {
            await postJson("/symbiotica/prompts-delete",
                           { folder: state.path, name: rel });
            dropTree(rel);
            toast("success", "Deleted", rel);
            announce();
        } catch (err) {
            toast("error", "Prompts", String(err.message || err));
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
        return remove(rel, `Delete the folder ${rel} and the ${held} prompt`
            + `${held === 1 ? "" : "s"} in it?\n\nThis cannot be undone.`);
    }

    async function renameFile(from) {
        if (!state.path || !from) return;
        const typed = await askText("Rename file to:", baseOf(from));
        const name = fileName(typed);
        if (!name || name === baseOf(from)) return;
        const to = joinRel(dirOf(from), name);
        try {
            await postJson("/symbiotica/prompts-rename",
                           { folder: state.path, from, to });
            moveTree(from, to);
            toast("success", "File renamed", `${from} → ${to}`);
            announce();
        } catch (err) {
            toast("error", "Prompts", String(err.message || err));
        }
        repaint();
    }

    async function renameFolder(from) {
        if (!state.path || !from) return;
        const typed = await askText("Rename folder to:", baseOf(from));
        const name = cleanFolder(typed);
        if (!name || name === baseOf(from)) return;
        const to = joinRel(dirOf(from), name);
        try {
            await postJson("/symbiotica/prompts-rename",
                           { folder: state.path, from, to });
            moveTree(from, to);
            toast("success", "Folder renamed", `${from} → ${to}`);
            announce();
        } catch (err) {
            toast("error", "Prompts", String(err.message || err));
        }
        repaint();
    }

    const pathCb = pathW.callback;
    pathW.callback = function () {
        const out = pathCb?.apply(this, arguments);
        node._symRefreshPrompts();
        return out;
    };

    // Another panel saved: re-read unless this one is mid-edit.
    const onSaved = () => { if (!dirty()) node._symRefreshPrompts(); };
    window.addEventListener(SAVED_EVT, onSaved);
    const prevRemoved = node.onRemoved;
    node.onRemoved = function () {
        window.removeEventListener(SAVED_EVT, onSaved);
        prevRemoved?.apply(this, arguments);
    };
    render();
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
            // A first size for a node that has none; a saved workflow
            // restores its own over this, on configure.
            this.size[0] = Math.max(this.size[0], 620);
            this.size[1] = Math.max(this.size[1], 380);
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
