// ABOUTME: Linked subgraph modules — the Module node (pick / publish / sync all)
// ABOUTME: and the swap that brings a workflow's stale module copy up to date on open.

// A subgraph published as a module is tagged with a name and a revision in
// its `extra`. On every workflow open, tagged subgraphs older than the library
// are replaced by the library version before the graph is built, and the
// promoted widget values on each instance follow the snapshot rule: a value is
// overwritten only when the module changed it since that instance last synced.
// py/_modules.py applies the same merge to the files on disk. Change both.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";

const NODE_CLASS = "SymbioticaModule";
const TAG = "symbiotica_module";
const PICK = "— pick a module —";

// ---------------------------------------------------------------- server --

async function getJson(path) {
    const res = await api.fetchApi(path);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body?.error ?? `${res.status} ${res.statusText}`);
    return body;
}

async function postJson(path, payload) {
    const res = await api.fetchApi(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload ?? {}),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body?.error ?? `${res.status} ${res.statusText}`);
    return body;
}

const listModules = () => getJson("/symbiotica/modules").then((b) => b.modules ?? []);
const readModule = (name) => getJson(`/symbiotica/modules/${encodeURIComponent(name)}`);

function toast(severity, summary, detail, life = 5000) {
    app.extensionManager?.toast?.add({ severity, summary, detail, life });
}

// ----------------------------------------------------------------- merge --
// Mirror of py/_modules.py: apply_modules / promoted_names / _patch_instance.

export function promotedNames(node) {
    const names = [];
    for (const inp of node.inputs ?? []) {
        const widget = inp.widget;
        if (widget && typeof widget === "object") names.push(widget.name ?? inp.name);
        else if (widget) names.push(inp.name);
    }
    return names;
}

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

function* allNodes(workflow) {
    for (const node of workflow.nodes ?? []) yield node;
    for (const def of workflow.definitions?.subgraphs ?? []) {
        for (const node of def.nodes ?? []) yield node;
    }
}

function patchInstance(node, name, rev, values) {
    node.properties ??= {};
    const snapshot = node.properties[TAG]?.values ?? {};
    const names = promotedNames(node);
    const wv = node.widgets_values;
    let applied = true;
    if (Array.isArray(wv) && wv.length === names.length) {
        names.forEach((widgetName, index) => {
            if (!(widgetName in values)) return;
            const had = widgetName in snapshot;
            if (!had || !same(values[widgetName], snapshot[widgetName])) {
                wv[index] = structuredClone(values[widgetName]);
            }
        });
    } else {
        applied = false;
    }
    node.properties[TAG] = { name, rev, values: structuredClone(values) };
    return applied;
}

export function applyModules(workflow, library) {
    const report = { updated: [], valuesSkipped: [], changed: false };
    const defs = workflow?.definitions?.subgraphs;
    if (!Array.isArray(defs)) return report;
    defs.forEach((def, index) => {
        const tag = def?.extra?.[TAG];
        if (!tag?.name) return;
        const module = library[tag.name];
        if (!module) return;
        const rev = Number(module.rev ?? 0);
        if (rev <= Number(tag.rev ?? 0)) return;
        const fresh = structuredClone(module.subgraph);
        fresh.id = def.id;
        fresh.extra ??= {};
        fresh.extra[TAG] = { name: tag.name, rev };
        defs[index] = fresh;
        const values = module.values ?? {};
        for (const node of allNodes(workflow)) {
            if (node.type !== fresh.id) continue;
            if (!patchInstance(node, tag.name, rev, values)) report.valuesSkipped.push(node.id);
        }
        report.updated.push({ name: tag.name, rev });
        report.changed = true;
    });
    return report;
}

// ------------------------------------------------------------ live graph --

const rootGraph = () => app.graph?.rootGraph ?? app.graph;

function activeWorkflowPath() {
    return app.extensionManager?.workflow?.activeWorkflow?.path ?? null;
}

// The promoted widget values on a live instance, by input name — the same
// names the serialized `widgets_values` are read back under.
function liveValues(node) {
    const values = {};
    for (const inp of node.inputs ?? []) {
        if (!inp.widget) continue;
        const name = inp.widget.name ?? inp.name;
        const widget = node.widgets?.find((w) => w.name === name);
        if (widget) values[name] = widget.value;
    }
    return values;
}

function setLiveValues(node, values, snapshot) {
    for (const [name, value] of Object.entries(values)) {
        if (name in snapshot && same(snapshot[name], value)) continue;
        const widget = node.widgets?.find((w) => w.name === name);
        if (!widget) continue;
        widget.value = structuredClone(value);
        widget.callback?.(widget.value, app.canvas, node, node.pos, {});
    }
}

function instancesOf(subgraph) {
    const found = [];
    const root = rootGraph();
    const graphs = [root, ...(root?.subgraphs?.values?.() ?? [])];
    for (const graph of graphs) {
        for (const node of graph?.nodes ?? []) {
            if (node.subgraph === subgraph || node.type === subgraph.id) found.push(node);
        }
    }
    return found;
}

// A serialized copy of the instance with nothing that ties it to this
// workflow: it is what the Module node drops on another canvas.
function instanceTemplate(node) {
    const data = structuredClone(node.serialize());
    delete data.id;
    data.pos = [0, 0];
    data.flags = {};
    data.mode = 0;
    for (const inp of data.inputs ?? []) inp.link = null;
    for (const out of data.outputs ?? []) out.links = [];
    if (data.properties) delete data.properties[TAG];
    return data;
}

// Clicking a button on the Module node selects the Module node, so by the time
// Publish runs the subgraph is no longer selected. Remember the last subgraph
// node the user clicked instead; the button says which one it will publish.
let lastSubgraphNode = null;

function trackSelection(node) {
    if (!node?.isSubgraphNode?.() || node._symModuleTracked) return;
    node._symModuleTracked = true;
    const onSelected = node.onSelected;
    node.onSelected = function () {
        onSelected?.apply(this, arguments);
        lastSubgraphNode = this;
        refreshPublishLabels();
    };
}

function trackAllSubgraphNodes() {
    const root = rootGraph();
    const graphs = [root, ...(root?.subgraphs?.values?.() ?? [])];
    for (const graph of graphs) for (const node of graph?.nodes ?? []) trackSelection(node);
}

function targetSubgraphNode(except) {
    const selected = Object.values(app.canvas?.selected_nodes ?? {})
        .filter((n) => n !== except && n.isSubgraphNode?.());
    if (selected.length === 1) return selected[0];
    if (lastSubgraphNode && lastSubgraphNode.graph) return lastSubgraphNode;
    return null;
}

const publishButtons = new Set();

function refreshPublishLabels() {
    const target = targetSubgraphNode(null);
    const title = target ? String(target.title ?? target.subgraph?.name ?? "subgraph") : "";
    const label = target
        ? `Publish: ${title.length > 28 ? title.slice(0, 27) + "…" : title}`
        : "Publish selected subgraph";
    for (const button of publishButtons) button.name = label;
    app.graph?.setDirtyCanvas(true, false);
}

// --------------------------------------------------------------- publish --

async function publishSelected(moduleNode) {
    const target = targetSubgraphNode(moduleNode);
    if (!target) {
        toast("warn", "No subgraph picked", "Click the subgraph node you want to publish first, then press Publish.");
        return;
    }
    const subgraph = target.subgraph;
    if (subgraph.nodes?.some((n) => n.isSubgraphNode?.())) {
        toast("error", "Nested subgraphs not supported", "Unpack the inner subgraph first.");
        return;
    }
    let name = subgraph.extra?.[TAG]?.name;
    if (!name) {
        name = await app.extensionManager.dialog.prompt({
            title: "Publish module",
            message: "Module name",
            defaultValue: subgraph.name ?? "",
        });
        name = (name ?? "").trim();
        if (!name) return;
    }
    const values = liveValues(target);
    const definition = subgraph.asSerialisable();
    try {
        const result = await postJson("/symbiotica/modules/publish", {
            name,
            subgraph: definition,
            values,
            instance: instanceTemplate(target),
        });
        subgraph.extra ??= {};
        subgraph.extra[TAG] = { name: result.name, rev: result.rev };
        for (const node of instancesOf(subgraph)) {
            node.properties ??= {};
            if (node !== target) setLiveValues(node, values, node.properties[TAG]?.values ?? {});
            node.properties[TAG] = { name: result.name, rev: result.rev, values: structuredClone(values) };
        }
        app.graph?.setDirtyCanvas(true, true);
        await refreshPickers();
        toast("success", `Published "${result.name}" r${result.rev}`,
            "Other workflows update when opened. Sync all workflows writes them now.");
    } catch (err) {
        toast("error", "Publish failed", String(err?.message ?? err));
    }
}

// ---------------------------------------------------------------- insert --

async function insertModule(moduleNode, name) {
    let module;
    try {
        module = await readModule(name);
    } catch (err) {
        toast("error", "Module not found", String(err?.message ?? err));
        return;
    }
    const rev = Number(module.rev ?? 0);
    const values = module.values ?? {};
    const position = [moduleNode.pos[0], moduleNode.pos[1] + moduleNode.size[1] + 40];
    const graph = app.canvas?.graph ?? app.graph;
    const existing = [...(rootGraph()?.subgraphs?.values?.() ?? [])]
        .find((sg) => sg.extra?.[TAG]?.name === name);
    let node = null;
    if (existing) {
        node = LiteGraph.createNode(existing.id);
        if (node) {
            node.pos = position;
            graph.add(node);
            setLiveValues(node, values, {});
        }
    }
    if (!node) {
        const template = module.instance ?? { type: module.subgraph.id, inputs: [], outputs: [] };
        const payload = {
            nodes: [{ ...structuredClone(template), id: 1, type: module.subgraph.id, pos: [0, 0] }],
            links: [],
            groups: [],
            reroutes: [],
            subgraphs: [structuredClone(module.subgraph)],
        };
        const created = app.canvas._deserializeItems(payload, { position })?.created ?? [];
        node = created.find((item) => item.isSubgraphNode?.()) ?? null;
    }
    if (!node) {
        toast("error", "Could not add module", "The canvas refused the subgraph.");
        return;
    }
    node.properties ??= {};
    node.properties[TAG] = { name, rev, values: structuredClone(values) };
    trackSelection(node);
    app.canvas?.deselectAll?.();
    app.canvas?.select?.(node);
    app.graph?.setDirtyCanvas(true, true);
}

// -------------------------------------------------------------- sync all --

async function syncAll() {
    try {
        const report = await postJson("/symbiotica/modules/sync", {});
        const files = report.updated ?? [];
        const errors = report.errors ?? [];
        const names = files.map((u) => u.path).join(", ");
        const detail = files.length
            ? `${names}. Reopen any of these that are open now.`
            : "Every workflow on disk already has the latest modules.";
        toast(files.length ? "success" : "info",
            `Synced ${files.length} of ${report.scanned ?? 0} workflows`, detail, 8000);
        if (errors.length) {
            toast("warn", `${errors.length} files skipped`,
                errors.map((e) => `${e.path}: ${e.error}`).join("\n"), 10000);
        }
    } catch (err) {
        toast("error", "Sync failed", String(err?.message ?? err));
    }
}

// ----------------------------------------------------------- Module node --

const pickers = new Set();

async function refreshPickers() {
    let names = [];
    try {
        names = (await listModules()).map((m) => m.name);
    } catch {
        return;
    }
    for (const widget of pickers) {
        widget.options.values = [PICK, ...names];
        if (!widget.options.values.includes(widget.value)) widget.value = PICK;
    }
    app.graph?.setDirtyCanvas(true, false);
}

function setupModuleNode(node) {
    node.isVirtualNode = true;
    const picker = node.widgets?.find((w) => w.name === "module");
    if (!picker) return;
    pickers.add(picker);
    picker.value = PICK;
    picker.callback = (value) => {
        if (!value || value === PICK) return;
        picker.value = PICK;
        insertModule(node, value);
    };
    const publish = node.addWidget("button", "Publish selected subgraph", null,
        () => publishSelected(node), { serialize: false });
    publish.serializeValue = () => undefined;
    publishButtons.add(publish);
    const sync = node.addWidget("button", "Sync all workflows", null,
        () => syncAll(), { serialize: false });
    sync.serializeValue = () => undefined;
    const onRemoved = node.onRemoved;
    node.onRemoved = function () {
        pickers.delete(picker);
        publishButtons.delete(publish);
        onRemoved?.apply(this, arguments);
    };
    const onSelected = node.onSelected;
    node.onSelected = function () {
        onSelected?.apply(this, arguments);
        refreshPickers();
        refreshPublishLabels();
    };
    refreshPickers();
    refreshPublishLabels();
}

// ---------------------------------------------------------- sync on open --

let pendingReport = null;

async function syncGraphData(graphData) {
    const defs = graphData?.definitions?.subgraphs;
    if (!Array.isArray(defs)) return null;
    const tagged = defs.map((d) => d?.extra?.[TAG]).filter((t) => t?.name);
    if (!tagged.length) return null;
    const listed = await listModules();
    const byName = Object.fromEntries(listed.map((m) => [m.name, m]));
    const stale = tagged.filter((t) => Number(byName[t.name]?.rev ?? 0) > Number(t.rev ?? 0));
    if (!stale.length) return null;
    const library = {};
    for (const t of new Set(stale.map((t) => t.name))) library[t] = await readModule(t);
    return applyModules(graphData, library);
}

registerSymbioticaExtension(app, {
    name: "symbiotica.modules",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            setupModuleNode(this);
        };
    },

    async beforeConfigureGraph(graphData) {
        pendingReport = null;
        try {
            const report = await syncGraphData(graphData);
            if (!report?.changed) return;
            pendingReport = report;
            const path = activeWorkflowPath();
            if (path) postJson("/symbiotica/modules/sync", { path }).catch(() => {});
        } catch (err) {
            console.warn("[symbiotica] module sync on open failed", err);
        }
    },

    nodeCreated(node) {
        trackSelection(node);
    },

    loadedGraphNode(node) {
        trackSelection(node);
    },

    afterConfigureGraph() {
        lastSubgraphNode = null;
        trackAllSubgraphNodes();
        refreshPublishLabels();
        const report = pendingReport;
        pendingReport = null;
        if (!report) return;
        const names = report.updated.map((u) => `${u.name} r${u.rev}`).join(", ");
        const skipped = report.valuesSkipped.length
            ? ` Values on ${report.valuesSkipped.length} node(s) left as they were.` : "";
        toast("info", "Modules updated", `${names}.${skipped}`, 7000);
    },
});
