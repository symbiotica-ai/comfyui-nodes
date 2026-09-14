// ABOUTME: The prompt book's canvas UI — the Book panel, single-Block editor
// ABOUTME: nodes, and the composed-prompt node, all over <project>/prompts/.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { nodeOutputString, resolveProjectPath } from "./order_source.js";
import { pinPanelWidth } from "./browser_chrome.js";
import { HUB, injectHubStyles } from "./hub_theme.js";

const BLOCK = "SymbioticaPromptBlock";

// Picker entries that are a composed VIEW of an asset type rather than a file.
// A prefix, not a separate control, so switching between "the block I edit" and
// "what the model gets" is one click in the list already in front of you.
const COMPOSED = "composed:";

// A book with no image block yet still offers one to write into: the folder is
// created by the first save, and without this entry there is nothing in the
// picker to select, so the feature would be unreachable from the panel that
// owns it.
const NEW_IMAGE = "_image/01-image-model.md";

// The Block node's "+ new block…" picker entry: a sentinel, not a filename —
// choosing it asks for a name instead of loading anything.
const NEW_BLOCK = "__new-block__";

// One panel's save is every other panel's stale view: a Block node saving a
// shared rule changes what the Compose node should be previewing. Saves are
// announced on the window and every prompt panel refreshes, whichever node
// performed the write.
const SAVED_EVT = "symbiotica-prompt-book-saved";

function widgetOf(node, name) {
    return (node.widgets ?? []).find((w) => w.name === name);
}

// A widget's value is not always the type its schema promises. Wiring an input
// leaves a number behind in the widget it replaced, and a saved graph whose node
// gained a widget deserialises the old list one slot across — his Prompt Recipe
// came back with `project_path = 1`. `.trim()` on that throws, and the throw
// killed the whole refresh, so the panel just sat there empty with the reason
// only in the console. Text is text; anything else is nothing.
function valueText(widget) {
    return typeof widget?.value === "string" ? widget.value.trim() : "";
}

// The project a panel edits: this node's own widget, else the node feeding its
// project_path or order input.
//
// Our own prompt nodes are followed by recursion, not by the order pipeline's
// generic resolver: that resolver reads "the first string widget with a value",
// which on a Block node is the block NAME — a chained block would resolve its
// neighbour's project to "_rules/02-inputs.md". For everything else (Order
// Specs, switches, literals) the generic graph walk is the right tool, same as
// before.
function projectOf(node, seen = new Set()) {
    if (!node || seen.has(node.id)) return "";
    seen.add(node.id);
    const typed = valueText(widgetOf(node, "project_path"));
    if (typed) return typed;
    const OURS = new Set([BLOCK]);
    for (const name of ["project_path", "order"]) {
        const link = node.inputs?.find((i) => i.name === name)?.link;
        if (link == null) continue;
        const origin = app.graph.getNodeById(app.graph.links[link]?.origin_id);
        if (!origin) continue;
        // `resolveProjectPath` answers for pipeline nodes, which name their
        // project in a `project_path` widget. A plain String node holding the
        // path has no such widget and answered "" — so wiring a literal into
        // `project_path`, which is the obvious way to point the book at a
        // local folder, silently resolved to nothing and the panel showed an
        // empty book. Fall through to "what string does this node output".
        let found = OURS.has(origin.comfyClass)
            ? projectOf(origin, seen)
            : (resolveProjectPath(origin)
               || nodeOutputString(origin, new Set()));
        // An order-passing node with no project of its own (Asset Focus) is a
        // hop, not a dead end — climb through it to the node behind.
        if (!found && origin.inputs?.some((i) => i.name === "order")) {
            found = projectOf(origin, seen);
        }
        if (found) return found;
    }
    return "";
}

// The book's subfolder is the node's OWN widget, never inherited down a wire:
// `project_path` is the only thing that chains, and a block reading a different
// folder from the one it was wired to is a silent disagreement rather than an
// error. A node without the widget sends nothing and the server uses the
// default, which is every panel that is not a Prompt Block.
function bookOf(node) {
    return valueText(widgetOf(node, "subfolder"));
}

const bookQuery = (node) => {
    const book = bookOf(node);
    return book ? `&subfolder=${encodeURIComponent(book)}` : "";
};

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

// Stop the canvas from eating scroll/drag inside the panel — without this a
// wheel over the textarea zooms the graph instead of scrolling the prompt.
function keepEvents(el) {
    for (const type of ["wheel", "pointerdown", "keydown"]) {
        el.addEventListener(type, (e) => e.stopPropagation());
    }
}

// The DOM every prompt panel shares: a picker/save bar, the composed-blocks
// line, a status line, and the editor. State (what is loaded, what is dirty)
// stays with each panel — this is chrome only.
function panelChrome(node, widgetName, { save = true } = {}) {
    injectHubStyles();
    const container = document.createElement("div");
    container.style.cssText = "box-sizing:border-box;width:100%;height:100%;"
        + "display:flex;flex-direction:column;gap:4px;font-size:11px;"
        + "overflow:hidden;";

    const bar = document.createElement("div");
    bar.style.cssText = "display:flex;gap:4px;align-items:center;min-width:0;";
    const picker = document.createElement("select");
    picker.style.cssText = `flex:1;min-width:0;background:${HUB.surface1};`
        + `color:${HUB.ink};border:1px solid ${HUB.hairlineStrong};`
        + "border-radius:4px;padding:2px 4px;";
    bar.append(picker);
    let saveBtn = null;
    if (save) {
        saveBtn = document.createElement("button");
        saveBtn.textContent = "Save";
        saveBtn.style.cssText = "padding:2px 10px;border-radius:4px;cursor:pointer;"
            + `border:1px solid ${HUB.hairlineStrong};background:${HUB.surface2};`
            + `color:${HUB.ink};`;
        saveBtn.className = "sym-btn";
        bar.append(saveBtn);
    }

    // The blocks a composed view was built from, in composition order. Kept
    // OUTSIDE the text: the preview has to stay byte-exact to what the model
    // receives, so no separators or headings may be injected into it.
    const blocksBar = document.createElement("div");
    blocksBar.style.cssText = "display:none;opacity:.65;line-height:1.45;"
        + "font-family:ui-monospace,monospace;";

    const status = document.createElement("div");
    status.style.cssText = "min-height:13px;opacity:.7;";

    const editor = document.createElement("textarea");
    editor.spellcheck = false;
    editor.style.cssText = "width:100%;box-sizing:border-box;flex:1;resize:none;"
        + `background:${HUB.surface1};color:${HUB.ink};`
        + `border:1px solid ${HUB.hairline};border-radius:4px;`
        + "padding:5px;font-family:ui-monospace,monospace;font-size:11px;"
        + "line-height:1.35;";
    keepEvents(editor);
    keepEvents(picker);

    container.append(bar, blocksBar, status, editor);
    // The editor follows the NODE, like a string literal's textarea: drag the
    // corner, the text grows — and shrinks all the way down to a literal-sized
    // strip, so a saved block can be parked small on the canvas. It takes
    // everything below its own start, measured from the widget's laid-out
    // position (`last_y`) rather than guessed, so no grey band is left at the
    // bottom whatever the node's slot count is.
    //
    // LiteGraph builds a node's MINIMUM height by summing its widgets, and per
    // widget it prefers `computeSize` over `computeLayoutSize`:
    //
    //     if (w.computeSize) t += w.computeSize(width)[1]
    //     else if (w.computeLayoutSize) t += w.computeLayoutSize(node).minHeight
    //
    // So a `computeSize` answering with "everything below me" makes the
    // minimum equal the node's current height: the corner drags taller and
    // never shorter. This editor had exactly that, which is why the node could
    // not be shrunk. A constant floor and NO computeSize: the layout hands the
    // widget the rest of the body, and the textarea fills it.
    const w = node.addDOMWidget(widgetName, `sym_${widgetName}`, container, {
        serialize: false, hideOnZoom: true,
        getMinHeight: () => 60,
    });
    // The wrapper ComfyUI sizes for this widget lags a SHRINK, so pin it or the
    // editor paints over the canvas beside a narrowed node.
    const syncPanelWidth = pinPanelWidth(node, container);
    requestAnimationFrame(syncPanelWidth);
    // The first draw measures last_y; redraw once so the height computed from
    // the fallback is corrected before the user notices it.
    requestAnimationFrame(() => node.setDirtyCanvas?.(true, true));

    const setStatus = (msg, bad) => {
        status.textContent = msg;
        status.style.color = bad ? HUB.danger : HUB.ok;
    };

    // Read-only is enforced on the widget, not just by hiding Save: a composed
    // document saved back would overwrite the type block with the rules baked
    // into it, and the next compose would then repeat every shared rule twice.
    const setEditable = (on) => {
        editor.readOnly = !on;
        if (saveBtn) {
            saveBtn.disabled = !on;
            saveBtn.style.opacity = on ? "1" : ".4";
        }
        editor.style.background = on ? HUB.surface1 : HUB.surface2;
        blocksBar.style.display = on ? "none" : "block";
    };

    return { picker, saveBtn, blocksBar, editor, setStatus, setEditable };
}

// A serialized widget the panel drives instead of the user: the picked block
// name has to reach Python and survive a workflow reload, but two controls for
// one choice would fight, so the raw text widget is folded away.
function hideBackingWidget(node, name) {
    const w = widgetOf(node, name);
    if (!w) return null;
    w.hidden = true;
    w.computeSize = () => [0, -4];
    return w;
}

function groupInto(picker, label, rows) {
    if (!rows.length) return;
    const g = document.createElement("optgroup");
    g.label = label;
    for (const row of rows) {
        const o = document.createElement("option");
        o.value = row.name;
        o.textContent = `${row.title}  (${row.chars})`;
        g.appendChild(o);
    }
    picker.appendChild(g);
}

// Refresh when any prompt panel saves, and stop listening when the node goes —
// a removed node's refresh would fetch against a dead panel forever.
function onBookSaved(node, handler) {
    window.addEventListener(SAVED_EVT, handler);
    const prevRemoved = node.onRemoved;
    node.onRemoved = function () {
        window.removeEventListener(SAVED_EVT, handler);
        prevRemoved?.apply(this, arguments);
    };
}

function announceSaved(project) {
    window.dispatchEvent(new CustomEvent(SAVED_EVT, { detail: { project } }));
}

// ComfyUI's own dialogs and toasts where available (see the frontend skill),
// falling back to the native ones so the panel still works on older frontends.
async function askText(message) {
    const dlg = app.extensionManager?.dialog;
    if (dlg?.prompt) {
        return await dlg.prompt({ title: "Prompt book", message });
    }
    return prompt(message);
}

async function askConfirm(message) {
    const dlg = app.extensionManager?.dialog;
    if (dlg?.confirm) {
        return await dlg.confirm({ title: "Prompt book", message });
    }
    return confirm(message);
}

function toastSaved(detail) {
    app.extensionManager?.toast?.add?.({
        severity: "success", summary: "Prompt saved", detail, life: 2500,
    });
}


// --- the Prompt Block node: one block, big on the canvas ---------------------
function blockPanel(node) {
    const blockW = hideBackingWidget(node, "block");
    // `slot` stays a visible widget. It used to be derived from the wire — the
    // Prompt Recipe's `text_3` output SAID "this edits slot 3" — and with that
    // node gone the only thing that can name the slot is the picker itself.
    const ui = panelChrome(node, "prompt_block");
    const { picker, saveBtn, editor, setStatus, setEditable } = ui;
    setEditable(true);

    let loaded = { name: "", text: "" };
    let existing = new Set();
    const dirty = () => editor.value !== loaded.text;

    async function load(name) {
        const project = projectOf(node);
        if (!project || !name) return;
        try {
            if (!existing.has(name)) {
                loaded = { name, text: "" };
                editor.value = "";
                setStatus(`${name} — new block, Save creates it`);
                return;
            }
            const { text } = await getJson(
                `/symbiotica/prompt-read?project=${encodeURIComponent(project)}`
                + `&name=${encodeURIComponent(name)}` + bookQuery(node));
            loaded = { name, text };
            editor.value = text;
            setStatus(`${text.length} chars`);
        } catch (err) {
            setStatus(String(err.message || err), true);
        }
    }

    async function refresh() {
        const project = projectOf(node);
        if (!project) {
            picker.replaceChildren();
            editor.value = "";
            setStatus("set project_path, or wire a neighbouring block's "
                      + "passthrough", true);
            return;
        }
        try {
            const book = await getJson(
                `/symbiotica/prompt-book?project=${encodeURIComponent(project)}`
                + bookQuery(node));
            const keep = valueText(blockW) || picker.value;
            picker.replaceChildren();
            groupInto(picker, "Game rules — apply to every type", book.rules);
            const image = book.image ?? [];
            groupInto(picker, "Image model — style, light, camera",
                      image.length ? image
                                   : [{ name: NEW_IMAGE, title: "01-image-model",
                                        chars: "new" }]);
            groupInto(picker, "Asset type", book.types);
            const names = [...book.rules, ...image, ...book.types]
                .map((r) => r.name);
            existing = new Set(names);
            if (!image.length) names.push(NEW_IMAGE);   // pickable, not on disk
            // A remembered block that is gone from disk stays selectable: the
            // node still points at it, and Save recreates it — dropping to the
            // first rule would silently re-point the node.
            if (keep && keep !== NEW_BLOCK && !names.includes(keep)) {
                groupInto(picker, "Not on disk",
                          [{ name: keep, title: keep, chars: "new" }]);
                names.push(keep);
            }
            // Always offered, even over a full book — an empty book otherwise
            // has nothing to pick and no way to write its first block.
            groupInto(picker, "New",
                      [{ name: NEW_BLOCK, title: "+ new block…", chars: "?" }]);
            const pick = names.includes(keep) ? keep : names[0];
            if (!pick) {
                picker.value = NEW_BLOCK;
                setStatus("empty book — pick “+ new block…” to write the "
                          + "first one", true);
                return;
            }
            picker.value = pick;
            if (blockW) blockW.value = pick;
            if (!(dirty() && loaded.name === pick)) await load(pick);
        } catch (err) {
            setStatus(String(err.message || err), true);
        }
    }

    picker.addEventListener("change", async () => {
        if (dirty() && !(await askConfirm(
            `Discard your unsaved changes to ${loaded.name}?`))) {
            picker.value = loaded.name;
            return;
        }
        if (picker.value === NEW_BLOCK) {
            const typed = await askText(
                "New block name — a shared rule (_rules/01-style.md), an image "
                + "block (_image/01-image-model.md), or an asset type exactly "
                + "as the order sheet spells it (Food - 3 stages.md):");
            if (!typed?.trim()) { picker.value = loaded.name; return; }
            let name = typed.trim();
            if (!name.endsWith(".md")) name += ".md";
            groupInto(picker, "Not on disk",
                      [{ name, title: name, chars: "new" }]);
            picker.value = name;
        }
        if (blockW) blockW.value = picker.value;
        // Name the node after its block — five of these side by side must read
        // like the string literals they replace, not five identical titles.
        const title = picker.selectedOptions[0]?.textContent
            ?.replace(/\s*\(.*\)\s*$/, "") ?? picker.value;
        node.title = `Block — ${title}`;
        node.setDirtyCanvas?.(true, true);
        load(picker.value);
    });

    saveBtn.addEventListener("click", async () => {
        const project = projectOf(node);
        if (!project || !picker.value) return;
        saveBtn.disabled = true;
        try {
            const res = await postJson("/symbiotica/prompt-write", {
                project, name: picker.value, text: editor.value,
                subfolder: bookOf(node),
            });
            loaded = { name: picker.value, text: editor.value };
            setStatus(`saved — ${res.chars} chars (.bak kept)`);
            toastSaved(`${picker.value} — ${res.chars} chars`);
            announceSaved(project);
        } catch (err) {
            setStatus(String(err.message || err), true);
        } finally {
            saveBtn.disabled = false;
        }
    });

    node._symRefreshBook = refresh;
    // Which block the last run actually edited. With a category wired the
    // recipe names it, and that name is only known in Python at run time — so
    // the panel is told rather than guessing, and stops showing the block that
    // was last picked by hand while serving a different one.
    node._symShowServed = async (name) => {
        if (!name || name === picker.value) return;
        // An unsaved edit is his typing; the served name is only a view of the
        // file, so it waits rather than overwriting him.
        if (dirty()) {
            setStatus(`the run served ${name} — save or discard your edit to `
                      + `${loaded.name} to follow it`, true);
            return;
        }
        // Selectable even when the recipe names a block nobody has written
        // yet: `load` then offers it as a new block, which is the only way to
        // create the file the recipe is already asking for.
        if (!existing.has(name)) {
            groupInto(picker, "Not on disk",
                      [{ name, title: name, chars: "new" }]);
        }
        picker.value = name;
        if (blockW) blockW.value = name;
        node.title = `Block — ${name.replace(/\.md$/, "")}`;
        node.setDirtyCanvas?.(true, true);
        await load(name);
    };
    onBookSaved(node, refresh);
    queueMicrotask(refresh);
}

const PANELS = {
    [BLOCK]: { build: blockPanel, minW: 380, minH: 400 },
};

// The block a Prompt Block actually edited. Same reason as the recipe push
// above: with a `category` wired the recipe names the block, in Python, at run
// time — the panel has no way to know it and would sit on a stale pick.
api.addEventListener("symbiotica.block", (event) => {
    const detail = event?.detail ?? {};
    if (detail.node_id == null || !detail.name) return;
    const node = app.graph?.getNodeById?.(Number(detail.node_id))
        ?? app.graph?.getNodeById?.(detail.node_id);
    node?._symShowServed?.(String(detail.name));
});

registerSymbioticaExtension(app, {
    name: "symbiotica.promptBook",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const spec = PANELS[nodeData.name];
        if (!spec) return;
        const orig = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            orig?.apply(this, arguments);
            this.size[0] = Math.max(this.size[0], spec.minW);
            this.size[1] = Math.max(this.size[1], spec.minH);
            spec.build(this);
            const self = this;
            // Retyping the subfolder points the panel at a different book, so
            // it has to re-list — the same reason a rewired project does.
            const book = this.widgets?.find((w) => w.name === "subfolder");
            if (book) {
                const cb = book.callback;
                book.callback = function () {
                    const out = cb?.apply(this, arguments);
                    queueMicrotask(() => self._symRefreshBook?.());
                    return out;
                };
            }
        };
        const origCfg = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            origCfg?.apply(this, arguments);
            queueMicrotask(() => this._symRefreshBook?.());
        };
        const origConn = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            origConn?.apply(this, arguments);
            // A newly wired project names the book — reload against ITS book,
            // not the one the panel happened to open with.
            queueMicrotask(() => this._symRefreshBook?.());
        };
    },
});
