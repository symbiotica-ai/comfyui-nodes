// ABOUTME: The Grid Layout node's picker — the project's layout files as a
// ABOUTME: dropdown, with "(follow category)" as the default that needs no pick.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { nodeOutputString, resolveProjectPath } from "./order_pipeline.js";

const NODE_CLASS = "SymbioticaGridLayout";

// The `layout` widget's empty value, spelled out. A dropdown cannot offer a
// blank label — "" reads as a bug rather than as a choice — and this is the
// value the node is expected to sit on, so it says what it does.
const FOLLOW = "(follow category)";

const widgetOf = (node, name) => (node.widgets ?? []).find((w) => w.name === name);

// The project this node reads layouts from: its own widget, else whatever is
// wired into `project_path` or `order`. The same walk the prompt panels use,
// so a Local/Modal switch or a plain String node resolves here too.
function projectOf(node, seen = new Set()) {
    if (!node || seen.has(node.id)) return "";
    seen.add(node.id);
    const typed = widgetOf(node, "project_path")?.value;
    if (typeof typed === "string" && typed.trim()) return typed.trim();
    for (const name of ["project_path", "order"]) {
        const link = node.inputs?.find((i) => i.name === name)?.link;
        if (link == null) continue;
        const origin = app.graph.getNodeById(app.graph.links[link]?.origin_id);
        if (!origin) continue;
        let found = resolveProjectPath(origin) || nodeOutputString(origin, new Set());
        // An order-passing node with no project of its own (Asset Focus) is a
        // hop, not a dead end — climb through it to the Order Specs behind.
        if (!found && origin.inputs?.some((i) => i.name === "order")) {
            found = projectOf(origin, seen);
        }
        if (found) return found;
    }
    return "";
}

// A real combo in the same slot: the classic node UI will not turn a text
// widget into a dropdown by mutating `.type`, and the value still has to reach
// Python as the string it always was.
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
    // "(follow category)" is a LABEL for the empty value, never a filename —
    // Python decides by category when `layout` is blank, and sending the label
    // through would have it hunt for a file called "(follow category)".
    w.serializeValue = () => (w.value === FOLLOW ? "" : w.value);
    return w;
}

function wireLayoutPicker(node) {
    node._symLayouts = [];
    const w = comboify(node, "layout", () => [FOLLOW, ...(node._symLayouts ?? [])]);
    if (w && !String(w.value ?? "").trim()) w.value = FOLLOW;

    const refresh = async () => {
        const project = projectOf(node);
        if (!project) { node._symLayouts = []; return; }
        try {
            const r = await api.fetchApi(
                `/symbiotica/layouts?project=${encodeURIComponent(project)}`);
            const body = await r.json().catch(() => ({}));
            node._symLayouts = Array.isArray(body.layouts) ? body.layouts : [];
        } catch { node._symLayouts = []; }
        node.setDirtyCanvas?.(true, true);
    };
    node._symRefreshLayouts = refresh;
    refresh();
    // A wired project is not resolvable until the graph's links are restored,
    // so a graph opening on this node would offer an empty dropdown forever.
    if (!projectOf(node)) setTimeout(refresh, 400);
}

// Which file the run actually used. A wired category picks it in Python, so
// the canvas has no way to know it — the node says so and titles itself with
// the answer, which is the whole point of being queueable on its own.
api.addEventListener("symbiotica.layout", (event) => {
    const detail = event?.detail ?? {};
    if (detail.node_id == null || !detail.name) return;
    const node = app.graph?.getNodeById?.(Number(detail.node_id))
        ?? app.graph?.getNodeById?.(detail.node_id);
    if (!node) return;
    if (Array.isArray(detail.layouts)) node._symLayouts = detail.layouts;
    node.title = `Grid — ${String(detail.name).replace(/\.[^.]+$/, "")}`;
    node.setDirtyCanvas?.(true, true);
});

registerSymbioticaExtension(app, {
    name: "symbiotica.gridLayout",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            wireLayoutPicker(this);
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            onConfigure?.apply(this, arguments);
            // A saved graph restores the widget AFTER creation, and an empty
            // one has to read as the label again rather than as a blank row.
            queueMicrotask(() => {
                const w = widgetOf(this, "layout");
                if (w && !String(w.value ?? "").trim()) w.value = FOLLOW;
                this._symRefreshLayouts?.();
            });
        };

        // Wiring the project in is the moment the choices become knowable.
        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            onConnectionsChange?.apply(this, arguments);
            queueMicrotask(() => this._symRefreshLayouts?.());
        };
    },
});
