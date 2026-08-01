// ABOUTME: Single-select studio asset library browser — a lazy per-level overlay
// ABOUTME: that writes a volume-relative pick into the node's selection widget.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { HUB, injectHubStyles, ghostButtonCss } from "./hub_theme.js";
import { registerSymbioticaExtension } from "./register.js";

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
    injectHubStyles();
    const ghostCss = ghostButtonCss;

    const overlay = document.createElement("div");
    overlay.className = "symbiotica-studio-library";
    overlay.style.cssText =
        "position:fixed;inset:0;z-index:10000;background:rgba(1,1,2,.66);" +
        "display:flex;align-items:center;justify-content:center;";
    const panel = document.createElement("div");
    panel.style.cssText =
        `width:min(80vw,1000px);height:80vh;background:${HUB.surface2};color:${HUB.ink};` +
        `font:13px/1.5 ${HUB.font};display:flex;flex-direction:column;` +
        `border:1px solid ${HUB.hairline};border-radius:12px;overflow:hidden;` +
        "box-shadow:0 16px 48px rgba(0,0,0,.55);";

    const bar = document.createElement("div");
    bar.style.cssText =
        `display:flex;align-items:center;gap:10px;padding:12px 16px;` +
        `border-bottom:1px solid ${HUB.hairline};`;
    const upBtn = document.createElement("button");
    upBtn.textContent = "↑ up";
    upBtn.className = "sym-btn";
    upBtn.style.cssText = ghostCss + "display:none;";
    const crumb = document.createElement("div");
    crumb.style.cssText =
        `flex:1;font:12px ${HUB.mono};color:${HUB.inkSubtle};` +
        "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
    const closeBtn = document.createElement("button");
    closeBtn.textContent = "Done";
    closeBtn.className = "sym-btn";
    closeBtn.style.cssText = ghostCss + "margin-left:auto;";
    const refreshBtn = document.createElement("button");
    refreshBtn.textContent = "⟳";
    refreshBtn.className = "sym-btn";
    refreshBtn.title = "Re-read this folder";
    refreshBtn.style.cssText = ghostCss + "padding:6px 10px;flex:none;";
    refreshBtn.addEventListener("click", () => show(currentRel, { sync: true }));
    // closeBtn carries margin-left:auto, so refresh lands to the left of Done.
    bar.append(upBtn, crumb, refreshBtn, closeBtn);

    const filterBar = document.createElement("div");
    filterBar.style.cssText = `padding:10px 16px;border-bottom:1px solid ${HUB.hairline};`;
    const filter = document.createElement("input");
    filter.type = "search";
    filter.className = "sym-input";
    filter.placeholder = "Filter this folder…";
    filter.style.cssText =
        `width:100%;box-sizing:border-box;padding:7px 10px;background:${HUB.surface1};` +
        `color:${HUB.ink};border:1px solid ${HUB.hairlineStrong};border-radius:8px;` +
        `font:13px ${HUB.font};`;
    filterBar.appendChild(filter);

    const errline = document.createElement("div");
    errline.style.cssText = `padding:10px 16px;color:${HUB.danger};font:12px ${HUB.font};`;

    const pane = document.createElement("div");
    pane.style.cssText = "flex:1;overflow:auto;padding:8px;";

    panel.append(bar, filterBar, errline, pane);
    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    let firstOpen = true;
    let currentEntries = [];
    let currentParent = null;
    let currentRel = "";  // what the refresh control re-reads

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

    const emptyState = (text) => {
        const d = document.createElement("div");
        d.style.cssText = `padding:28px 16px;text-align:center;color:${HUB.inkTertiary};font:13px ${HUB.font};`;
        d.textContent = text;
        return d;
    };
    // The way out, rendered as the first row rather than only as the header
    // button. It is synthesised here and never joins currentEntries, so it
    // cannot be filtered away with the folder's own contents and cannot be
    // handed a select control — picking it would write the parent folder into
    // the node's value while the user thought they were navigating.
    const upRow = (parentRel) => {
        const row = document.createElement("div");
        row.className = "sym-row";
        row.style.cssText = "display:flex;align-items:center;gap:10px;padding:9px 10px;";
        const label = document.createElement("span");
        label.className = "sym-name";
        label.style.cssText = `flex:1;color:${HUB.inkSubtle};cursor:pointer;`;
        label.textContent = "↑  ..";
        label.addEventListener("click", () => show(parentRel));
        row.appendChild(label);
        return row;
    };
    function renderRows() {
        pane.replaceChildren();
        if (currentParent !== null) pane.appendChild(upRow(currentParent));
        if (currentEntries.length === 0) {
            pane.appendChild(emptyState("No files in this studio library yet"));
            return;
        }
        const shown = filterEntries(currentEntries, filter.value);
        if (shown.length === 0) {
            pane.appendChild(emptyState("No matches"));
            return;
        }
        for (const entry of shown) {
            const row = document.createElement("div");
            row.className = "sym-row";
            row.style.cssText = "display:flex;align-items:center;gap:10px;padding:9px 10px;";
            const label = document.createElement("span");
            label.className = "sym-name";
            label.style.cssText =
                `flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:${HUB.ink};`;
            label.textContent = (entry.type === "dir" ? "📁  " : "📄  ") + entry.name;
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
                pick.className = "sym-btn sym-btn-accent";
                pick.style.cssText =
                    `padding:5px 12px;background:${HUB.accent};color:${HUB.onAccent};` +
                    `border:0;border-radius:8px;cursor:pointer;font:12px ${HUB.font};`;
                pick.addEventListener("click", () => { applySelection(node, entry.rel); close(); });
                row.appendChild(pick);
            }
            pane.appendChild(row);
        }
    }

    filter.addEventListener("input", renderRows);

    // `sync` forces a volume refresh — the browse-session open does it once, and
    // the refresh control does it on demand. Without it a re-read redraws the
    // same rows off the same mount and reads as proof the folder is not there.
    async function show(dir, { sync = false } = {}) {
        errline.textContent = "";
        let data;
        try {
            const q = new URLSearchParams({ dir });
            if (sync || firstOpen) q.set("sync", "1");
            data = await fetchJson(`${ROUTE}?${q.toString()}`);
        } catch (e) {
            errline.textContent = e.message || "studio library unavailable";
            return;
        }
        firstOpen = false;  // spent only once a listing has actually arrived
        currentRel = data.rel ?? "";
        crumb.textContent = data.rel || "studios";
        // Only sent when the refresh did not happen, so its mere presence is the
        // signal. The rows still render: the mount is older than the user thinks,
        // not unreadable.
        errline.textContent = data.sync
            ? "Could not refresh the studio volume — this listing may be out of date."
            : "";
        currentEntries = data.entries || [];
        currentParent = data.parent ?? null;
        upBtn.style.display = currentParent !== null ? "" : "none";
        // Re-reading in place is not navigation: the filter is still describing
        // the folder the user is looking at.
        if (!sync) filter.value = "";
        renderRows();
    }
    show("");
}

registerSymbioticaExtension(app, {
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
