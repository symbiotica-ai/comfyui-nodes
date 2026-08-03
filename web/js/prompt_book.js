// ABOUTME: The Prompt Book node's editor panel — pick a shared rule or a type
// ABOUTME: block, edit it, save it, without leaving the graph.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { resolveProjectPath } from "./order_pipeline.js";

const NODE = "SymbioticaPromptBook";

function widgetOf(node, name) {
    return (node.widgets ?? []).find((w) => w.name === name);
}

// The project the panel edits: this node's own widget, else the one the wired
// order came from.
//
// The upstream Order Specs usually has its OWN project_path wired (a Path Local
// or a Local/Modal switch), so reading that node's widget finds an empty string
// and the panel reports no project while an order is plainly connected. The
// order pipeline already walks the graph for exactly this, so reuse its
// resolver rather than keep a second, weaker copy here.
function projectOf(node) {
    const typed = widgetOf(node, "project_path")?.value?.trim();
    if (typed) return typed;
    const link = node.inputs?.find((i) => i.name === "order")?.link;
    if (link == null) return "";
    const origin = app.graph.getNodeById(app.graph.links[link]?.origin_id);
    return origin ? resolveProjectPath(origin) : "";
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

function promptPanel(node) {
    const container = document.createElement("div");
    container.style.cssText = "box-sizing:border-box;width:100%;display:flex;"
        + "flex-direction:column;gap:4px;font-size:11px;overflow:hidden;";

    const bar = document.createElement("div");
    bar.style.cssText = "display:flex;gap:4px;align-items:center;min-width:0;";
    const picker = document.createElement("select");
    picker.style.cssText = "flex:1;min-width:0;background:#222;color:#ddd;"
        + "border:1px solid #555;border-radius:4px;padding:2px 4px;";
    const saveBtn = document.createElement("button");
    saveBtn.textContent = "Save";
    saveBtn.style.cssText = "padding:2px 10px;border-radius:4px;cursor:pointer;"
        + "border:1px solid #555;background:#333;color:#ddd;";
    bar.append(picker, saveBtn);

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

    container.append(bar, status, editor);
    const w = node.addDOMWidget("prompt_book", "sym_prompt_book", container,
                                { serialize: false, hideOnZoom: true });
    w.computeSize = (width) => [width, 320];

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

    let loaded = { name: "", text: "" };

    const setStatus = (msg, bad) => {
        status.textContent = msg;
        status.style.color = bad ? "#e08585" : "#8fbf8f";
    };

    const dirty = () => editor.value !== loaded.text;

    async function load(name) {
        const project = projectOf(node);
        if (!project || !name) return;
        try {
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
            setStatus("wire an order, or set project_path", true);
            return;
        }
        try {
            const book = await getJson(
                `/symbiotica/prompt-book?project=${encodeURIComponent(project)}`);
            const keep = picker.value;
            picker.replaceChildren();
            const group = (label, rows) => {
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
            };
            // Rules first, in composition order — the same order they appear in
            // the prompt the model receives, so the list reads as the prompt does.
            group("Game rules — apply to every type", book.rules);
            group("Asset type", book.types);
            const names = [...book.rules, ...book.types].map((r) => r.name);
            const pick = names.includes(keep) ? keep : names[0];
            if (pick) { picker.value = pick; await load(pick); }
            else setStatus("no prompts in this project's book", true);
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
        saveBtn.disabled = true;
        try {
            const res = await postJson("/symbiotica/prompt-write", {
                project, name: picker.value, text: editor.value,
            });
            loaded = { name: picker.value, text: editor.value };
            setStatus(`saved — ${res.chars} chars (.bak kept)`);
            await refresh();
        } catch (err) {
            setStatus(String(err.message || err), true);
        } finally {
            saveBtn.disabled = false;
        }
    });

    node._symRefreshBook = refresh;
    queueMicrotask(refresh);
}

registerSymbioticaExtension(app, {
    name: "symbiotica.promptBook",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE) return;
        const orig = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            orig?.apply(this, arguments);
            this.size[0] = Math.max(this.size[0], 420);
            this.size[1] = Math.max(this.size[1], 460);
            promptPanel(this);
        };
        const origCfg = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            origCfg?.apply(this, arguments);
            queueMicrotask(() => this._symRefreshBook?.());
        };
        const origConn = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            origConn?.apply(this, arguments);
            // A newly wired order names the project — reload against ITS book,
            // not the one the panel happened to open with.
            queueMicrotask(() => this._symRefreshBook?.());
        };
    },
});
