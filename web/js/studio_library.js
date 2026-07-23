// ABOUTME: Single-select studio asset library browser — a lazy per-level overlay
// ABOUTME: that writes a volume-relative pick into the node's selection widget.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const ROUTE = "/symbiotica/studio-library";

export function summaryLabel(selection) {
    const rel = String(selection || "");
    const m = rel.match(/^studios\/([^/]+)\/(.+)$/);
    if (m) return `${m[1]} · ${m[2]}`;
    const root = rel.match(/^studios\/([^/]+)\/?$/);
    if (root) return `${root[1]} · (studio root)`;
    return "no selection";
}

export function filterEntries(entries, query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((e) => e.name.toLowerCase().includes(q));
}

export function applySelection(node, entryRel) {
    const sel = node.widgets?.find((w) => w.name === "selection");
    if (sel) sel.value = entryRel;
    const summary = node.widgets?.find((w) => w.name === "studio_summary");
    if (summary) summary.value = summaryLabel(entryRel);
    node.setDirtyCanvas?.(true, true);
}

async function fetchJson(url) {
    const res = await api.fetchApi(url);
    if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.error ?? res.statusText);
    return res.json();
}

function refreshSummary(node) {
    const sel = node.widgets?.find((w) => w.name === "selection");
    const summary = node.widgets?.find((w) => w.name === "studio_summary");
    if (summary) summary.value = summaryLabel(sel?.value ?? "");
}

function openBrowser(node) {
    // A centered modal (~80% of the viewport) over a dimmed backdrop: breadcrumb
    // + up-nav + a client-side name filter + a single lazy tree pane. Folders
    // expand by fetching ROUTE?dir=<rel>; the first open passes sync=1. Clicking
    // a row's select control calls applySelection(node, entry.rel) and closes. A
    // non-ok fetch throws in fetchJson and renders inline; an empty listing shows
    // a distinct empty state. The filter narrows the CURRENT pane by name (it does
    // not search into unopened folders). Done/✕, Escape, and a backdrop click are
    // always-available closes, independent of whether the pane has any rows.
    const overlay = document.createElement("div");
    overlay.className = "symbiotica-studio-library";
    overlay.style.cssText =
        "position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.6);" +
        "display:flex;align-items:center;justify-content:center;";
    const panel = document.createElement("div");
    panel.style.cssText =
        "width:80%;height:80%;max-width:1100px;background:#161616;color:#ddd;" +
        "display:flex;flex-direction:column;font:12px sans-serif;" +
        "border:1px solid #333;border-radius:8px;overflow:hidden;" +
        "box-shadow:0 8px 40px rgba(0,0,0,.5);";

    const bar = document.createElement("div");
    bar.style.cssText =
        "display:flex;align-items:center;gap:10px;padding:8px 12px;" +
        "background:#202020;border-bottom:1px solid #333;";
    const upBtn = document.createElement("button");
    upBtn.textContent = "⬆ up";
    upBtn.style.cssText = "display:none;";
    const crumb = document.createElement("div");
    crumb.style.cssText =
        "flex:1;font-weight:bold;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
    const closeBtn = document.createElement("button");
    closeBtn.textContent = "Done";
    closeBtn.style.cssText = "margin-left:auto;";
    bar.append(upBtn, crumb, closeBtn);

    const filterBar = document.createElement("div");
    filterBar.style.cssText =
        "display:flex;align-items:center;gap:6px;padding:6px 12px;" +
        "background:#1b1b1b;border-bottom:1px solid #2a2a2a;";
    const filter = document.createElement("input");
    filter.type = "search";
    filter.placeholder = "🔎 filter this folder…";
    filter.style.cssText =
        "flex:1;max-width:320px;padding:4px 6px;background:#111;color:#ddd;" +
        "border:1px solid #333;border-radius:4px;";
    filterBar.appendChild(filter);

    const errline = document.createElement("div");
    errline.style.cssText = "padding:6px 12px;color:#f66;";

    const pane = document.createElement("div");
    pane.style.cssText = "flex:1;overflow:auto;padding:6px 12px;";

    panel.append(bar, filterBar, errline, pane);
    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    let firstOpen = true;
    let currentEntries = [];
    let currentParent = null;

    function onKeydown(e) {
        if (e.key === "Escape") close();
    }
    const close = () => {
        overlay.remove();
        document.removeEventListener("keydown", onKeydown);
    };
    document.addEventListener("keydown", onKeydown);
    closeBtn.addEventListener("click", close);
    overlay.addEventListener("click", (e) => {
        if (e.target === overlay) close();  // backdrop click (not a click inside the panel)
    });
    upBtn.addEventListener("click", () => {
        if (currentParent !== null) show(currentParent);
    });

    function renderRows() {
        pane.replaceChildren();
        if (currentEntries.length === 0) {
            pane.textContent = "No files in this studio library yet";
            return;
        }
        const shown = filterEntries(currentEntries, filter.value);
        if (shown.length === 0) {
            pane.textContent = "No matches";
            return;
        }
        for (const entry of shown) {
            const row = document.createElement("div");
            row.style.cssText =
                "display:flex;align-items:center;gap:8px;padding:6px 4px;" +
                "border-bottom:1px solid #262626;";
            const label = document.createElement("span");
            label.style.cssText =
                "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;cursor:pointer;";
            label.textContent = (entry.type === "dir" ? "📁 " : "📄 ") + entry.name;
            // Clicking the row is the default action: a folder opens (drill in),
            // a file is selected.
            label.addEventListener("click", () => {
                if (entry.type === "dir") show(entry.rel);
                else { applySelection(node, entry.rel); close(); }
            });
            row.appendChild(label);
            if (entry.type === "dir") {
                // A folder can also be picked as the value itself, not just opened.
                const pick = document.createElement("button");
                pick.textContent = "select";
                pick.addEventListener("click", () => { applySelection(node, entry.rel); close(); });
                row.appendChild(pick);
            }
            pane.appendChild(row);
        }
    }

    filter.addEventListener("input", renderRows);

    async function show(dir) {
        errline.textContent = "";
        let data;
        try {
            const q = new URLSearchParams({ dir });
            if (firstOpen) q.set("sync", "1");
            firstOpen = false;
            data = await fetchJson(`${ROUTE}?${q.toString()}`);
        } catch (e) {
            errline.textContent = e.message || "studio library unavailable";
            return;
        }
        crumb.textContent = data.rel || "studios";
        currentEntries = data.entries || [];
        currentParent = data.parent ?? null;
        upBtn.style.cssText = currentParent !== null ? "" : "display:none;";
        filter.value = "";
        renderRows();
    }
    show("");
}

app.registerExtension({
    name: "symbiotica.studio_library",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SymbioticaStudioLibrary") return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            this.addWidget("button", "📂 Browse studio library", null, () => openBrowser(this));
            const summary = this.addWidget("text", "studio_summary", "", () => {});
            summary.disabled = true;
            summary.serialize = false;
            refreshSummary(this);
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            onConfigure?.apply(this, arguments);
            queueMicrotask(() => refreshSummary(this));
        };
    },
});
