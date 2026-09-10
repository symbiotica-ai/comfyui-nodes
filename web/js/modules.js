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
// A group module: every member node carries {name, key, rev, snapshot}. The
// frame is only the rectangle that says which tagged nodes belong together.
const GTAG = "symbiotica_group";
const PICK = "— pick a module —";
const GROUP_SUFFIX = " (group)";

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

// ------------------------------------------------------------ group merge --
// Mirror of py/_modules.py: _apply_group_modules / _replace_group_members.
// The root workflow's links are arrays and its counters are
// last_node_id/last_link_id; a subgraph definition's links are objects and its
// counters sit under state. The helpers below hide that.

const LINK_INDEX = { id: 0, origin_id: 1, origin_slot: 2, target_id: 3, target_slot: 4, type: 5 };

function* allGraphs(workflow) {
    yield workflow;
    for (const def of workflow.definitions?.subgraphs ?? []) if (def && typeof def === "object") yield def;
}

const lk = (link, field) => (Array.isArray(link) ? link[LINK_INDEX[field]] : link?.[field]);
function lkSet(link, field, value) {
    if (Array.isArray(link)) link[LINK_INDEX[field]] = value;
    else link[field] = value;
}

function makeLink(graph, id, originId, originSlot, targetId, targetSlot, type) {
    const links = graph.links ?? [];
    const asObject = links.length ? !Array.isArray(links[0]) : "state" in graph;
    return asObject
        ? { id, origin_id: originId, origin_slot: originSlot, target_id: targetId, target_slot: targetSlot, type }
        : [id, originId, originSlot, targetId, targetSlot, type];
}

const intIds = (values) => values.map(Number).filter((n) => Number.isFinite(n));

function nextNodeId(graph) {
    const state = graph.state && typeof graph.state === "object" ? graph.state : null;
    const current = Math.max(0, ...intIds([...(graph.nodes ?? []).map((n) => n.id),
        graph.last_node_id, state?.lastNodeId]));
    const id = current + 1;
    if (state) state.lastNodeId = id;
    if ("last_node_id" in graph || !state) graph.last_node_id = id;
    return id;
}

function nextLinkId(graph) {
    const state = graph.state && typeof graph.state === "object" ? graph.state : null;
    const current = Math.max(0, ...intIds([...(graph.links ?? []).map((l) => lk(l, "id")),
        graph.last_link_id, state?.lastLinkId]));
    const id = current + 1;
    if (state) state.lastLinkId = id;
    if ("last_link_id" in graph || !state) graph.last_link_id = id;
    return id;
}

function posOf(node) {
    let pos = node.pos;
    if (pos && !Array.isArray(pos) && typeof pos === "object") pos = [pos[0] ?? pos["0"], pos[1] ?? pos["1"]];
    return Array.isArray(pos) && pos.length >= 2 ? [Number(pos[0]), Number(pos[1])] : [0, 0];
}

function sizeOf(node) {
    let size = node.size;
    if (size && !Array.isArray(size) && typeof size === "object") size = [size[0] ?? size["0"], size[1] ?? size["1"]];
    return Array.isArray(size) && size.length >= 2 ? [Number(size[0]), Number(size[1])] : [200, 100];
}

function inside(node, bounding) {
    if (!Array.isArray(bounding) || bounding.length < 4) return false;
    const [x, y] = posOf(node);
    const [bx, by, bw, bh] = bounding.map(Number);
    return bx <= x && x <= bx + bw && by <= y && y <= by + bh;
}

function containingGroup(node, groups) {
    let best = null;
    let bestArea = null;
    groups.forEach((group, index) => {
        if (!inside(node, group.bounding)) return;
        const area = Number(group.bounding[2]) * Number(group.bounding[3]);
        if (bestArea === null || area < bestArea) { best = index; bestArea = area; }
    });
    return best;
}

function slotIndex(node, side, name) {
    const slots = node?.[side] ?? [];
    const index = slots.findIndex((slot) => slot?.name === name);
    return index < 0 ? null : index;
}

function dropLink(graph, link, otherNode, otherSide, otherSlot) {
    const id = lk(link, "id");
    graph.links = (graph.links ?? []).filter((l) => lk(l, "id") !== id);
    if (!otherNode) return;
    const slots = otherNode[otherSide] ?? [];
    if (!Number.isInteger(otherSlot) || otherSlot >= slots.length) return;
    if (otherSide === "inputs") {
        if (slots[otherSlot].link === id) slots[otherSlot].link = null;
    } else {
        slots[otherSlot].links = (slots[otherSlot].links ?? []).filter((l) => l !== id);
    }
}

function applyGroupModules(graph, library, report) {
    const nodes = graph.nodes;
    if (!Array.isArray(nodes)) return;
    const tagged = nodes.filter((n) => n?.properties?.[GTAG] && typeof n.properties[GTAG] === "object");
    if (!tagged.length) return;
    const groups = (graph.groups ?? []).filter((g) => g && typeof g === "object");
    const clusters = new Map();
    for (const node of tagged) {
        const key = `${node.properties[GTAG].name}\u0000${containingGroup(node, groups)}`;
        if (!clusters.has(key)) clusters.set(key, { name: node.properties[GTAG].name, group: containingGroup(node, groups), members: [] });
        clusters.get(key).members.push(node);
    }
    for (const { name, group: groupIndex, members } of clusters.values()) {
        const module = library[name];
        if (!module || !Array.isArray(module.nodes)) continue;
        const rev = Number(module.rev ?? 0);
        const current = Math.min(...members.map((m) => Number(m.properties[GTAG].rev ?? 0)));
        if (rev <= current) continue;
        replaceGroupMembers(graph, groupIndex === null ? null : groups[groupIndex], members, module, rev, report);
        report.updated.push({ name, rev });
        report.changed = true;
    }
}

function replaceGroupMembers(graph, group, members, module, rev, report) {
    const name = module.name;
    const nodes = graph.nodes;
    graph.links ??= [];
    let nodeById = new Map(nodes.map((n) => [n.id, n]));
    const oldByKey = new Map(members.map((m) => [String(m.properties[GTAG].key), m]));
    const memberIds = new Set(members.map((m) => m.id));
    const origin = group && Array.isArray(group.bounding)
        ? [Number(group.bounding[0]), Number(group.bounding[1])]
        : [Math.min(...members.map((m) => posOf(m)[0])), Math.min(...members.map((m) => posOf(m)[1]))];

    const internalIds = new Set();
    const incoming = [];
    const outgoing = [];
    for (const link of graph.links) {
        const originId = lk(link, "origin_id");
        const targetId = lk(link, "target_id");
        if (memberIds.has(originId) && memberIds.has(targetId)) {
            internalIds.add(lk(link, "id"));
        } else if (memberIds.has(targetId)) {
            const member = nodeById.get(targetId);
            const slot = lk(link, "target_slot");
            incoming.push([link, String(member.properties[GTAG].key), member.inputs?.[slot]?.name ?? null]);
        } else if (memberIds.has(originId)) {
            const member = nodeById.get(originId);
            const slot = lk(link, "origin_slot");
            outgoing.push([link, String(member.properties[GTAG].key), member.outputs?.[slot]?.name ?? null]);
        }
    }
    graph.links = graph.links.filter((l) => !internalIds.has(lk(l, "id")));

    const newByKey = new Map();
    const freshNodes = [];
    for (const moduleNode of module.nodes) {
        const key = String(moduleNode.id);
        const node = structuredClone(moduleNode);
        for (const inp of node.inputs ?? []) inp.link = null;
        for (const out of node.outputs ?? []) out.links = [];
        const old = oldByKey.get(key);
        const moduleValues = moduleNode.widgets_values;
        if (old) {
            node.id = old.id;
            node.pos = old.pos ?? node.pos;
            if (old.size != null) node.size = old.size;
            const snapshot = old.properties[GTAG].snapshot;
            const oldValues = old.widgets_values;
            if (Array.isArray(moduleValues) && Array.isArray(oldValues) && Array.isArray(snapshot)
                && moduleValues.length === oldValues.length && oldValues.length === snapshot.length) {
                node.widgets_values = moduleValues.map((value, i) =>
                    (same(value, snapshot[i]) ? oldValues[i] : structuredClone(value)));
            } else if (Array.isArray(moduleValues) && Array.isArray(oldValues)) {
                report.valuesSkipped.push(old.id);
                node.widgets_values = oldValues;
            }
        } else {
            node.id = nextNodeId(graph);
            const rel = posOf(moduleNode);
            node.pos = [origin[0] + rel[0], origin[1] + rel[1]];
        }
        node.properties ??= {};
        node.properties[GTAG] = { name, key, rev, snapshot: structuredClone(moduleValues ?? null) };
        newByKey.set(key, node);
        freshNodes.push(node);
    }

    const firstIndex = Math.min(...nodes.map((n, i) => (memberIds.has(n.id) ? i : Infinity)));
    const kept = nodes.filter((n) => !memberIds.has(n.id));
    graph.nodes = [...kept.slice(0, firstIndex), ...freshNodes, ...kept.slice(firstIndex)];
    nodeById = new Map(graph.nodes.map((n) => [n.id, n]));

    for (const moduleLink of module.links ?? []) {
        const originNode = newByKey.get(String(lk(moduleLink, "origin_id")));
        const targetNode = newByKey.get(String(lk(moduleLink, "target_id")));
        const originSlot = lk(moduleLink, "origin_slot");
        const targetSlot = lk(moduleLink, "target_slot");
        if (!originNode || !targetNode) continue;
        if (!Number.isInteger(originSlot) || !Number.isInteger(targetSlot)) continue;
        const outputs = originNode.outputs ?? [];
        const inputs = targetNode.inputs ?? [];
        if (originSlot >= outputs.length || targetSlot >= inputs.length) continue;
        const id = nextLinkId(graph);
        (outputs[originSlot].links ??= []).push(id);
        inputs[targetSlot].link = id;
        graph.links.push(makeLink(graph, id, originNode.id, originSlot, targetNode.id, targetSlot, lk(moduleLink, "type")));
    }

    for (const [link, key, slotName] of incoming) {
        const node = newByKey.get(key);
        const index = node ? slotIndex(node, "inputs", slotName) : null;
        if (index === null) {
            dropLink(graph, link, nodeById.get(lk(link, "origin_id")), "outputs", lk(link, "origin_slot"));
            report.linksDropped.push({ module: name, key, slot: slotName });
            continue;
        }
        lkSet(link, "target_id", node.id);
        lkSet(link, "target_slot", index);
        node.inputs[index].link = lk(link, "id");
    }
    for (const [link, key, slotName] of outgoing) {
        const node = newByKey.get(key);
        const index = node ? slotIndex(node, "outputs", slotName) : null;
        if (index === null) {
            dropLink(graph, link, nodeById.get(lk(link, "target_id")), "inputs", lk(link, "target_slot"));
            report.linksDropped.push({ module: name, key, slot: slotName });
            continue;
        }
        lkSet(link, "origin_id", node.id);
        lkSet(link, "origin_slot", index);
        (node.outputs[index].links ??= []).push(lk(link, "id"));
    }

    if (group && Array.isArray(group.bounding) && freshNodes.length) {
        const pad = 12;
        const title = 40;
        const xs = freshNodes.map((n) => posOf(n)[0]);
        const ys = freshNodes.map((n) => posOf(n)[1]);
        const x2 = freshNodes.map((n) => posOf(n)[0] + sizeOf(n)[0]);
        const y2 = freshNodes.map((n) => posOf(n)[1] + sizeOf(n)[1]);
        const [bx, by, bw, bh] = group.bounding.slice(0, 4).map(Number);
        // Grow only: a side moves when a node crossed it, never to re-pad.
        const nx = Math.min(...xs) < bx ? Math.min(...xs) - pad : bx;
        const ny = Math.min(...ys) < by ? Math.min(...ys) - title : by;
        const right = Math.max(...x2) > bx + bw ? Math.max(...x2) + pad : bx + bw;
        const bottom = Math.max(...y2) > by + bh ? Math.max(...y2) + pad : by + bh;
        group.bounding = [nx, ny, right - nx, bottom - ny];
    }
}

export function applyModules(workflow, library) {
    const report = { updated: [], valuesSkipped: [], linksDropped: [], changed: false };
    for (const graph of allGraphs(workflow ?? {})) applyGroupModules(graph, library, report);
    const defs = workflow?.definitions?.subgraphs;
    if (!Array.isArray(defs)) return report;
    defs.forEach((def, index) => {
        const tag = def?.extra?.[TAG];
        if (!tag?.name) return;
        const module = library[tag.name];
        if (!module?.subgraph) return;
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
// Publish runs the subgraph or group is no longer selected. Remember the last
// one the user clicked instead; the button says which one it will publish.
let lastTarget = null;

const isGroup = (item) => typeof item?.recomputeInsideNodes === "function";

function graphsOf(root) {
    return [root, ...(root?.subgraphs?.values?.() ?? [])];
}

function targetAlive(target) {
    if (!target) return false;
    if (target.kind === "subgraph") return Boolean(target.item.graph);
    return graphsOf(rootGraph()).some((graph) => graph?.groups?.includes?.(target.item));
}

function noteTarget(kind, item) {
    if (lastTarget?.item === item) return;
    lastTarget = { kind, item };
    refreshPublishLabels();
}

function trackSelection(node) {
    if (!node?.isSubgraphNode?.() || node._symModuleTracked) return;
    node._symModuleTracked = true;
    const onSelected = node.onSelected;
    node.onSelected = function () {
        onSelected?.apply(this, arguments);
        noteTarget("subgraph", this);
    };
}

function trackAllSubgraphNodes() {
    for (const graph of graphsOf(rootGraph())) for (const node of graph?.nodes ?? []) trackSelection(node);
}

// Groups have no selection callback; the canvas repaints after every
// selection change, so the Module node looks at the selection when it draws.
function noteSelectedItems() {
    const items = app.canvas?.selectedItems;
    if (!items) return;
    for (const item of items) {
        if (isGroup(item)) return noteTarget("group", item);
        if (item?.isSubgraphNode?.()) return noteTarget("subgraph", item);
    }
}

function publishTarget(except) {
    for (const item of app.canvas?.selectedItems ?? []) {
        if (item === except) continue;
        if (isGroup(item)) return { kind: "group", item };
        if (item?.isSubgraphNode?.()) return { kind: "subgraph", item };
    }
    return targetAlive(lastTarget) ? lastTarget : null;
}

const publishButtons = new Set();

function refreshPublishLabels() {
    const target = publishTarget(null);
    const title = target ? String(target.item.title ?? target.item.subgraph?.name ?? target.kind) : "";
    const short = title.length > 24 ? title.slice(0, 23) + "…" : title;
    const label = target
        ? `Publish: ${short}${target.kind === "group" ? " (group)" : ""}`
        : "Publish selected subgraph or group";
    for (const button of publishButtons) button.name = label;
    app.graph?.setDirtyCanvas(true, false);
}

// --------------------------------------------------------------- publish --

async function askName(defaultValue) {
    const name = await app.extensionManager.dialog.prompt({
        title: "Publish module",
        message: "Module name",
        defaultValue: defaultValue ?? "",
    });
    return (name ?? "").trim();
}

async function publishSelected(moduleNode) {
    const picked = publishTarget(moduleNode);
    if (!picked) {
        toast("warn", "Nothing picked", "Click the subgraph node or the group title you want to publish, then press Publish.");
        return;
    }
    if (picked.kind === "group") return publishGroup(picked.item);
    const target = picked.item;
    const subgraph = target.subgraph;
    if (subgraph.nodes?.some((n) => n.isSubgraphNode?.())) {
        toast("error", "Nested subgraphs not supported", "Unpack the inner subgraph first.");
        return;
    }
    let name = subgraph.extra?.[TAG]?.name;
    if (!name) {
        name = await askName(subgraph.name);
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

// ---------------------------------------------------------- group publish --

function graphLink(graph, id) {
    return graph?.getLink?.(id) ?? graph?.links?.get?.(id) ?? graph?.links?.[id] ?? graph?._links?.get?.(id) ?? null;
}

function groupMembers(group) {
    group.recomputeInsideNodes?.();
    const members = group._nodes ?? [...(group._children ?? [])].filter((c) => c?.inputs);
    return members.filter((n) => n.comfyClass !== NODE_CLASS && n.type !== NODE_CLASS);
}

async function publishGroup(group) {
    const graph = app.canvas?.graph ?? app.graph;
    const members = groupMembers(group);
    if (!members.length) {
        toast("warn", "Empty group", "The frame has no nodes inside it.");
        return;
    }
    if (members.some((n) => n.isSubgraphNode?.())) {
        toast("error", "Subgraphs inside a group are not supported", "Unpack them or publish the subgraph on its own.");
        return;
    }
    let name = members.map((n) => n.properties?.[GTAG]?.name).find(Boolean);
    if (!name) {
        name = await askName(group.title);
        if (!name) return;
    }
    const memberIds = new Set(members.map((n) => n.id));
    const [gx, gy] = [Number(group.pos?.[0] ?? 0), Number(group.pos?.[1] ?? 0)];
    const nodes = [];
    const links = [];
    const seen = new Set();
    for (const member of members) {
        const data = structuredClone(member.serialize());
        data.pos = [Number(data.pos[0]) - gx, Number(data.pos[1]) - gy];
        for (const inp of data.inputs ?? []) {
            const link = inp.link != null ? graphLink(graph, inp.link) : null;
            if (link && memberIds.has(link.origin_id) && !seen.has(link.id)) {
                seen.add(link.id);
                links.push({ id: link.id, origin_id: link.origin_id, origin_slot: link.origin_slot,
                    target_id: link.target_id, target_slot: link.target_slot, type: link.type });
            }
        }
        nodes.push(data);
    }
    try {
        const result = await postJson("/symbiotica/modules/publish", {
            name,
            kind: "group",
            group: { title: group.title, color: group.color, font_size: group.font_size, flags: group.flags ?? {} },
            nodes,
            links,
        });
        members.forEach((member, i) => {
            member.properties ??= {};
            member.properties[GTAG] = { name: result.name, key: String(member.id), rev: result.rev,
                snapshot: structuredClone(nodes[i].widgets_values ?? null) };
        });
        app.graph?.setDirtyCanvas(true, true);
        await refreshPickers();
        toast("success", `Published "${result.name}" r${result.rev} (group)`,
            "Other workflows update when opened. Sync all workflows writes them now.");
    } catch (err) {
        toast("error", "Publish failed", String(err?.message ?? err));
    }
}

function insertGroup(moduleNode, module) {
    const rev = Number(module.rev ?? 0);
    const position = [moduleNode.pos[0], moduleNode.pos[1] + moduleNode.size[1] + 40];
    const pad = 12;
    const nodes = module.nodes.map((n) => ({ ...structuredClone(n), pos: posOf(n) }));
    const width = Math.max(...nodes.map((n) => posOf(n)[0] + sizeOf(n)[0])) + pad;
    const height = Math.max(...nodes.map((n) => posOf(n)[1] + sizeOf(n)[1])) + pad;
    const payload = {
        nodes,
        links: (module.links ?? []).map((l) => ({ ...l })),
        groups: [{ id: -1, title: module.group?.title ?? module.name, bounding: [0, 0, width, height],
            color: module.group?.color, font_size: module.group?.font_size, flags: module.group?.flags ?? {} }],
        reroutes: [],
        subgraphs: [],
    };
    const created = app.canvas._deserializeItems(payload, { position })?.created ?? [];
    const createdNodes = created.filter((item) => item?.inputs && !isGroup(item));
    if (createdNodes.length !== nodes.length) {
        toast("error", "Could not add module", "The canvas refused part of the group.");
        return;
    }
    createdNodes.forEach((node, i) => {
        node.properties ??= {};
        node.properties[GTAG] = { name: module.name, key: String(module.nodes[i].id), rev,
            snapshot: structuredClone(module.nodes[i].widgets_values ?? null) };
    });
    app.graph?.setDirtyCanvas(true, true);
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
    if (module.kind === "group" || Array.isArray(module.nodes)) return insertGroup(moduleNode, module);
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

const pickerLabel = (m) => (m.kind === "group" ? `${m.name}${GROUP_SUFFIX}` : m.name);
const pickerName = (label) => (label.endsWith(GROUP_SUFFIX) ? label.slice(0, -GROUP_SUFFIX.length) : label);

async function refreshPickers() {
    let names = [];
    try {
        names = (await listModules()).map(pickerLabel);
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
        insertModule(node, pickerName(String(value)));
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
    const onDrawForeground = node.onDrawForeground;
    node.onDrawForeground = function () {
        noteSelectedItems();
        return onDrawForeground?.apply(this, arguments);
    };
    refreshPickers();
    refreshPublishLabels();
}

// ---------------------------------------------------------- sync on open --

let pendingReport = null;

async function syncGraphData(graphData) {
    const defs = graphData?.definitions?.subgraphs ?? [];
    const tagged = defs.map((d) => d?.extra?.[TAG]).filter((t) => t?.name);
    for (const graph of allGraphs(graphData ?? {})) {
        for (const node of graph.nodes ?? []) {
            const tag = node?.properties?.[GTAG];
            if (tag?.name) tagged.push({ name: tag.name, rev: tag.rev });
        }
    }
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
        lastTarget = null;
        trackAllSubgraphNodes();
        refreshPublishLabels();
        const report = pendingReport;
        pendingReport = null;
        if (!report) return;
        const names = report.updated.map((u) => `${u.name} r${u.rev}`).join(", ");
        const skipped = report.valuesSkipped.length
            ? ` Values on ${report.valuesSkipped.length} node(s) left as they were.` : "";
        const dropped = report.linksDropped.length
            ? ` ${report.linksDropped.length} link(s) dropped: ${report.linksDropped.map((d) => d.slot).join(", ")}.` : "";
        toast("info", "Modules updated", `${names}.${skipped}${dropped}`, 8000);
    },
});
