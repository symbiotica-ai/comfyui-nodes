// ABOUTME: The prompt book's canvas UI — the Book panel, single-Block editor
// ABOUTME: nodes, and the composed-prompt node, all over <project>/prompts/.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { resolveProjectPath } from "./order_pipeline.js";

const BOOK = "SymbioticaPromptBook";
const BLOCK = "SymbioticaPromptBlock";
const COMPOSE = "SymbioticaPromptCompose";

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
    const typed = widgetOf(node, "project_path")?.value?.trim();
    if (typed) return typed;
    const OURS = new Set([BOOK, BLOCK, COMPOSE]);
    for (const name of ["project_path", "order"]) {
        const link = node.inputs?.find((i) => i.name === name)?.link;
        if (link == null) continue;
        const origin = app.graph.getNodeById(app.graph.links[link]?.origin_id);
        if (!origin) continue;
        const found = OURS.has(origin.comfyClass)
            ? projectOf(origin, seen)
            : resolveProjectPath(origin);
        if (found) return found;
    }
    return "";
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
    const container = document.createElement("div");
    container.style.cssText = "box-sizing:border-box;width:100%;height:100%;"
        + "display:flex;flex-direction:column;gap:4px;font-size:11px;"
        + "overflow:hidden;";

    const bar = document.createElement("div");
    bar.style.cssText = "display:flex;gap:4px;align-items:center;min-width:0;";
    const picker = document.createElement("select");
    picker.style.cssText = "flex:1;min-width:0;background:#222;color:#ddd;"
        + "border:1px solid #555;border-radius:4px;padding:2px 4px;";
    bar.append(picker);
    let saveBtn = null;
    if (save) {
        saveBtn = document.createElement("button");
        saveBtn.textContent = "Save";
        saveBtn.style.cssText = "padding:2px 10px;border-radius:4px;"
            + "cursor:pointer;border:1px solid #555;background:#333;color:#ddd;";
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
        + "background:#1b1b1b;color:#ddd;border:1px solid #444;border-radius:4px;"
        + "padding:5px;font-family:ui-monospace,monospace;font-size:11px;"
        + "line-height:1.35;";
    keepEvents(editor);
    keepEvents(picker);

    container.append(bar, blocksBar, status, editor);
    const w = node.addDOMWidget(widgetName, `sym_${widgetName}`, container,
                                { serialize: false, hideOnZoom: true });
    // The editor follows the NODE, like a string literal's textarea: drag the
    // corner, the text grows — and shrinks all the way down to a literal-sized
    // strip, so a saved block can be parked small on the canvas. The panel
    // takes everything below its own start — measured from the widget's
    // laid-out position (`last_y`), not guessed, so no grey band is left at
    // the bottom whatever the node's slot count is.
    const ABOVE_FALLBACK = 110;   // first layout runs before last_y exists
    w.computeSize = (width) => {
        const top = typeof w.last_y === "number" && w.last_y > 0
            ? w.last_y : ABOVE_FALLBACK;
        return [width, Math.max(60, node.size[1] - top - 12)];
    };
    // The first draw measures last_y; redraw once so the height computed from
    // the fallback is corrected before the user notices it.
    requestAnimationFrame(() => node.setDirtyCanvas?.(true, true));

    // The wrapper ComfyUI sizes from the node width follows a widening at once
    // but lags a shrink, leaving the panel hanging off the node's right edge —
    // same trap as the Auto Packer's assets panel. Pin it instead of waiting.
    const PANEL_INSET = 20;
    const syncWidth = () => {
        const wrap = container.parentElement;
        if (!wrap) return;
        const want = Math.max(0, node.size[0] - PANEL_INSET);
        if (parseFloat(wrap.style.width) !== want) wrap.style.width = `${want}px`;
    };
    const prevResize = node.onResize;
    node.onResize = function () {
        prevResize?.apply(this, arguments);
        syncWidth();
    };

    const setStatus = (msg, bad) => {
        status.textContent = msg;
        status.style.color = bad ? "#e08585" : "#8fbf8f";
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
        editor.style.background = on ? "#1b1b1b" : "#171a17";
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

// --- the Prompt Book node: the whole book in one panel -----------------------
function bookPanel(node) {
    const ui = panelChrome(node, "prompt_book");
    const { picker, saveBtn, blocksBar, editor, setStatus, setEditable } = ui;

    let loaded = { name: "", text: "" };
    // The blocks that exist on disk, as of the last refresh. A picked name that
    // is not among them is a block being created, not a read that failed.
    let existing = new Set();

    const dirty = () => editor.value !== loaded.text;

    async function loadComposed(project, category) {
        const { text, blocks } = await getJson(
            `/symbiotica/prompt-compose?project=${encodeURIComponent(project)}`
            + `&category=${encodeURIComponent(category)}`);
        loaded = { name: COMPOSED + category, text };
        editor.value = text;
        setEditable(false);
        blocksBar.textContent = blocks
            .map((b) => `${b.name} (${b.chars})`).join("  +  ");
        setStatus(`${blocks.length} blocks · ${text.length} chars — read-only,`
                  + " this is what the LLM receives");
    }

    async function load(name) {
        const project = projectOf(node);
        if (!project || !name) return;
        try {
            if (name.startsWith(COMPOSED)) {
                await loadComposed(project, name.slice(COMPOSED.length));
                return;
            }
            if (!existing.has(name)) {
                loaded = { name, text: "" };
                editor.value = "";
                setEditable(true);
                setStatus(`${name} — new block, Save creates it`);
                return;
            }
            const { text } = await getJson(
                `/symbiotica/prompt-read?project=${encodeURIComponent(project)}`
                + `&name=${encodeURIComponent(name)}`);
            loaded = { name, text };
            editor.value = text;
            setEditable(true);
            setStatus(`${text.length} chars`);
        } catch (err) {
            // Leave the editor holding whatever failed to load rather than
            // blanking it — a composed view that errors on one missing type
            // must not look like an empty prompt book.
            setStatus(String(err.message || err), true);
        }
    }

    async function refresh() {
        const project = projectOf(node);
        if (!project) {
            picker.replaceChildren();
            editor.value = "";
            setStatus("wire an order, or set project_path", true);
            return;
        }
        try {
            const book = await getJson(
                `/symbiotica/prompt-book?project=${encodeURIComponent(project)}`);
            const keep = picker.value;
            picker.replaceChildren();
            // Rules first, in composition order — the same order they appear in
            // the prompt the model receives, so the list reads as the prompt does.
            groupInto(picker, "Game rules — apply to every type", book.rules);
            const image = book.image ?? [];
            groupInto(picker, "Image model — style, light, camera",
                      image.length ? image
                                   : [{ name: NEW_IMAGE, title: "01-image-model",
                                        chars: "new" }]);
            groupInto(picker, "Asset type", book.types);
            // Composed last, because it is where you go after an edit rather
            // than before one: same types again, this time assembled.
            groupInto(picker, "Composed — what the LLM receives",
                      (book.types ?? []).map(
                (row) => ({ name: COMPOSED + row.title, title: row.title,
                            chars: "rules + type" })));
            const names = [...book.rules, ...image, ...book.types]
                .map((r) => r.name);
            existing = new Set(names);
            if (!image.length) names.push(NEW_IMAGE);   // pickable, not on disk
            // Keep a composed selection across a reload too — it is not in
            // `names` (it is a view, not a file), and dropping back to the
            // first rule every time the panel refreshes loses your place.
            const selectable = [...names, ...(book.types ?? []).map(
                (r) => COMPOSED + r.title)];
            const pick = selectable.includes(keep) ? keep : names[0];
            if (!pick) { setStatus("no prompts in this project's book", true); return; }
            picker.value = pick;
            // A refresh fired by ANOTHER panel's save must not clobber an edit
            // in progress here — reload the list, keep the text being typed.
            if (!(dirty() && loaded.name === pick)) await load(pick);
        } catch (err) {
            setStatus(String(err.message || err), true);
        }
    }

    picker.addEventListener("change", () => {
        // An unsaved edit is a tuned rule the user would have to retype; ask
        // rather than silently discard it on a stray click.
        if (dirty() && !confirm(
            `Discard your unsaved changes to ${loaded.name}?`)) {
            picker.value = loaded.name;
            return;
        }
        load(picker.value);
    });

    saveBtn.addEventListener("click", async () => {
        const project = projectOf(node);
        if (!project || !picker.value) return;
        if (picker.value.startsWith(COMPOSED)) return;   // a view, not a file
        saveBtn.disabled = true;
        try {
            const res = await postJson("/symbiotica/prompt-write", {
                project, name: picker.value, text: editor.value,
            });
            loaded = { name: picker.value, text: editor.value };
            setStatus(`saved — ${res.chars} chars (.bak kept)`);
            announceSaved(project);
            await refresh();
        } catch (err) {
            setStatus(String(err.message || err), true);
        } finally {
            saveBtn.disabled = false;
        }
    });

    node._symRefreshBook = refresh;
    onBookSaved(node, refresh);
    queueMicrotask(refresh);
}

// --- the Prompt Block node: one block, big on the canvas ---------------------
function blockPanel(node) {
    const blockW = hideBackingWidget(node, "block");
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
                + `&name=${encodeURIComponent(name)}`);
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
            setStatus("wire the Prompt Book's project output, or set "
                      + "project_path", true);
            return;
        }
        try {
            const book = await getJson(
                `/symbiotica/prompt-book?project=${encodeURIComponent(project)}`);
            const keep = blockW?.value?.trim() || picker.value;
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

    picker.addEventListener("change", () => {
        if (dirty() && !confirm(
            `Discard your unsaved changes to ${loaded.name}?`)) {
            picker.value = loaded.name;
            return;
        }
        if (picker.value === NEW_BLOCK) {
            const typed = prompt(
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
            });
            loaded = { name: picker.value, text: editor.value };
            setStatus(`saved — ${res.chars} chars (.bak kept)`);
            announceSaved(project);
        } catch (err) {
            setStatus(String(err.message || err), true);
        } finally {
            saveBtn.disabled = false;
        }
    });

    node._symRefreshBook = refresh;
    onBookSaved(node, refresh);
    queueMicrotask(refresh);
}

// --- the Prompt Compose node: what the LLM receives, live --------------------
function composePanel(node) {
    const catW = hideBackingWidget(node, "category");
    const ui = panelChrome(node, "prompt_compose", { save: false });
    const { picker, blocksBar, editor, setStatus, setEditable } = ui;
    setEditable(false);

    async function load(category) {
        const project = projectOf(node);
        if (!project || !category) return;
        try {
            const { text, blocks } = await getJson(
                `/symbiotica/prompt-compose?project=`
                + `${encodeURIComponent(project)}`
                + `&category=${encodeURIComponent(category)}`);
            editor.value = text;
            blocksBar.textContent = blocks
                .map((b) => `${b.name} (${b.chars})`).join("  +  ");
            setStatus(`${blocks.length} blocks · ${text.length} chars — `
                      + "read-only, this is what the LLM receives");
        } catch (err) {
            setStatus(String(err.message || err), true);
        }
    }

    async function refresh() {
        const project = projectOf(node);
        if (!project) {
            picker.replaceChildren();
            editor.value = "";
            setStatus("wire the Prompt Book's project output, or set "
                      + "project_path", true);
            return;
        }
        try {
            const book = await getJson(
                `/symbiotica/prompt-book?project=${encodeURIComponent(project)}`);
            const keep = catW?.value?.trim() || picker.value;
            picker.replaceChildren();
            groupInto(picker, "Asset type", (book.types ?? []).map(
                (row) => ({ name: row.title, title: row.title,
                            chars: "rules + type" })));
            const names = (book.types ?? []).map((r) => r.title);
            const pick = names.includes(keep) ? keep : names[0];
            if (!pick) { setStatus("no type blocks in this project's book", true); return; }
            picker.value = pick;
            if (catW) catW.value = pick;
            await load(pick);
        } catch (err) {
            setStatus(String(err.message || err), true);
        }
    }

    picker.addEventListener("change", () => {
        if (catW) catW.value = picker.value;
        node.title = `Compose — ${picker.value}`;
        node.setDirtyCanvas?.(true, true);
        load(picker.value);
    });

    node._symRefreshBook = refresh;
    onBookSaved(node, refresh);
    queueMicrotask(refresh);
}

const PANELS = {
    [BOOK]: { build: bookPanel, minW: 420, minH: 460 },
    [BLOCK]: { build: blockPanel, minW: 380, minH: 400 },
    [COMPOSE]: { build: composePanel, minW: 420, minH: 460 },
};

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
