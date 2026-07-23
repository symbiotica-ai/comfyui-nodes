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
    if (!res.ok) throw new Error((await res.json())?.error ?? res.statusText);
    return res.json();
}

function refreshSummary(node) {
    const sel = node.widgets?.find((w) => w.name === "selection");
    const summary = node.widgets?.find((w) => w.name === "studio_summary");
    if (summary) summary.value = summaryLabel(sel?.value ?? "");
}

function openBrowser(node) {
    // Fullscreen overlay: breadcrumb + a client-side name filter + a single lazy
    // tree pane. Folders expand by fetching ROUTE?dir=<rel>; the first open passes
    // sync=1. Clicking a row's select control calls applySelection(node, entry.rel)
    // and closes. A non-ok fetch throws in fetchJson and renders inline; an empty
    // listing shows a distinct empty state. The filter narrows the CURRENT pane by
    // name (it does not search into unopened folders).
    const overlay = document.createElement("div");
    overlay.className = "symbiotica-studio-library";
    const crumb = document.createElement("div");
    const filter = document.createElement("input");
    filter.type = "search";
    filter.placeholder = "🔎 filter this folder…";
    const errline = document.createElement("div");
    const pane = document.createElement("div");
    overlay.appendChild(crumb);
    overlay.appendChild(filter);
    overlay.appendChild(errline);
    overlay.appendChild(pane);
    document.body.appendChild(overlay);

    let firstOpen = true;
    let currentEntries = [];
    const close = () => overlay.remove();

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
            row.textContent = (entry.type === "dir" ? "📁 " : "📄 ") + entry.name;
            const pick = document.createElement("button");
            pick.textContent = "select";
            pick.addEventListener("click", () => { applySelection(node, entry.rel); close(); });
            if (entry.type === "dir") {
                const expand = document.createElement("button");
                expand.textContent = "open";
                expand.addEventListener("click", () => show(entry.rel));
                row.appendChild(expand);
            }
            row.appendChild(pick);
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
