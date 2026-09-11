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
import { HUB, ghostButtonCss, injectHubStyles } from "./hub_theme.js";
import { el, pinPanelWidth } from "./browser_chrome.js";

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

// --------------------------------------------------------------- publish --

async function publishSubgraphNode(target, name) {
    const subgraph = target.subgraph;
    if (subgraph.nodes?.some((n) => n.isSubgraphNode?.())) {
        toast("error", "Nested subgraphs not supported", "Unpack the inner subgraph first.");
        return false;
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
        return true;
    } catch (err) {
        toast("error", "Publish failed", String(err?.message ?? err));
        return false;
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

async function publishGroup(group, name) {
    const graph = app.canvas?.graph ?? app.graph;
    const members = groupMembers(group);
    if (!members.length) {
        toast("warn", "Empty group", "The frame has no nodes inside it.");
        return false;
    }
    if (members.some((n) => n.isSubgraphNode?.())) {
        toast("error", "Subgraphs inside a group are not supported", "Unpack them or publish the subgraph on its own.");
        return false;
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
        return true;
    } catch (err) {
        toast("error", "Publish failed", String(err?.message ?? err));
        return false;
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

// The project folder for new modules: typed on the node, or read off the
// text node wired into the `folder` input. A computed string (an LLM output,
// a concat) has no value on the canvas, so only a typed one can be read.
function folderValue(node) {
    const index = node.inputs?.findIndex((i) => i.name === "folder") ?? -1;
    const input = index >= 0 ? node.inputs[index] : null;
    if (input?.link != null) {
        const origin = node.getInputNode?.(index);
        const widget = origin?.widgets?.find((w) => typeof w.value === "string");
        if (widget) return String(widget.value).trim();
        return null;
    }
    return String(node.widgets?.find((w) => w.name === "folder")?.value ?? "").trim();
}

// `Image Model Preamble` -> `image-model-preamble`: the path segment a new
// module gets from its title, editable before publishing.
export function slug(title) {
    return String(title ?? "").toLowerCase().replace(/[^a-z0-9._-]+/g, "-").replace(/^-+|-+$/g, "");
}

export function joinPath(folder, name) {
    const parts = [folder, name].map((p) => String(p ?? "").replace(/^\/+|\/+$/g, "")).filter(Boolean);
    return parts.join("/");
}

// Everything in the graph on screen that can be a module, with its tag if it
// already is one.
function moduleCandidates(graph) {
    const rows = [];
    for (const group of graph?.groups ?? []) {
        const tag = groupMembers(group).map((n) => n.properties?.[GTAG]).find((t) => t?.name);
        rows.push({ kind: "group", item: group, title: String(group.title ?? "Group"),
            name: tag?.name ?? null, rev: tag?.rev ?? null });
    }
    for (const node of graph?.nodes ?? []) {
        if (!node.isSubgraphNode?.()) continue;
        const tag = node.subgraph?.extra?.[TAG];
        rows.push({ kind: "subgraph", item: node, title: String(node.title ?? node.subgraph?.name ?? "Subgraph"),
            name: tag?.name ?? null, rev: tag?.rev ?? null });
    }
    return rows;
}

const rowSignature = (rows, folder) =>
    `${folder}|` + rows.map((r) => `${r.kind}:${r.title}:${r.name}:${r.rev}`).join("|");

function modulePanel(node) {
    injectHubStyles();
    const container = el("div", "box-sizing:border-box;width:100%;height:100%;"
        + "overflow-y:auto;overflow-x:hidden;");
    const list = el("div", "width:100%;box-sizing:border-box;overflow:hidden;"
        + `padding:2px;font:11px ${HUB.font};color:var(--input-text, ${HUB.ink});`);
    container.appendChild(list);
    container.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });
    // No computeSize, a constant floor: anything computeSize returns becomes a
    // minimum height the corner cannot drag past.
    node.addDOMWidget("modules_panel", "sym_modules", container, {
        serialize: false, hideOnZoom: true,
        getMinHeight: () => 44,
    });
    node.size[0] = Math.max(node.size[0], 360);
    const syncPanelWidth = pinPanelWidth(node, container);
    const refit = () => requestAnimationFrame(() => {
        syncPanelWidth();
        node.setDirtyCanvas?.(true, true);
    });

    // The path typed into a row survives re-renders until it is published.
    const drafts = new Map();
    let lastSignature = null;
    let busy = false;

    function render(force = false) {
        const graph = app.canvas?.graph ?? app.graph;
        const folder = folderValue(node);
        const rows = moduleCandidates(graph);
        const signature = rowSignature(rows, folder);
        if (!force && signature === lastSignature) return;
        lastSignature = signature;
        list.replaceChildren();
        if (folder === null) {
            list.appendChild(el("div", `padding:4px 3px;color:${HUB.inkSubtle};`,
                "folder is wired to a node with no typed text — type it or connect a text node."));
        }
        if (!rows.length) {
            list.appendChild(el("div", `padding:6px 3px;color:${HUB.inkSubtle};`,
                "No groups or subgraphs in this graph yet."));
            refit();
            return;
        }
        for (const row of rows) {
            const key = `${row.kind}:${row.title}`;
            const line = el("div", "display:flex;align-items:center;gap:6px;width:100%;"
                + `box-sizing:border-box;padding:3px 2px;border-bottom:1px solid ${HUB.hairline};`);
            const title = el("div", "flex:1 1 30%;min-width:0;overflow:hidden;text-overflow:ellipsis;"
                + "white-space:nowrap;", row.title);
            title.title = row.kind === "group" ? "group" : "subgraph";
            const path = el("input", "flex:1 1 40%;min-width:0;box-sizing:border-box;padding:2px 4px;"
                + `font:11px ${HUB.mono};background:var(--comfy-input-bg, transparent);`
                + `color:var(--input-text, ${HUB.ink});border:1px solid ${HUB.hairline};`
                + `border-radius:${HUB.radius.sm};`);
            path.value = drafts.get(key) ?? row.name ?? joinPath(folder ?? "", slug(row.title));
            path.placeholder = "folder/name";
            path.addEventListener("input", () => drafts.set(key, path.value));
            path.addEventListener("keydown", (e) => { e.stopPropagation(); if (e.key === "Enter") button.click(); });
            path.addEventListener("pointerdown", (e) => e.stopPropagation());
            const status = el("div", `flex:0 0 auto;color:${HUB.inkSubtle};font:11px ${HUB.mono};`,
                row.rev != null ? `r${row.rev}` : "new");
            const button = el("button", ghostButtonCss + "padding:2px 8px;flex:0 0 auto;", "Publish");
            button.addEventListener("pointerdown", (e) => e.stopPropagation());
            button.addEventListener("click", async (e) => {
                e.stopPropagation();
                if (busy) return;
                const name = path.value.trim();
                if (!name) { toast("warn", "Name it first", "Type folder/name in the row."); return; }
                busy = true;
                button.disabled = true;
                try {
                    const ok = row.kind === "group"
                        ? await publishGroup(row.item, name)
                        : await publishSubgraphNode(row.item, name);
                    if (ok) drafts.delete(key);
                } finally {
                    busy = false;
                    button.disabled = false;
                    render(true);
                }
            });
            line.append(title, path, status, button);
            list.appendChild(line);
        }
        refit();
    }

    node._symRenderModules = render;
    render(true);
    // Groups get made, renamed and removed without any event reaching this
    // node; the canvas repaints after each, so a cheap signature check on
    // draw keeps the rows honest.
    const onDrawForeground = node.onDrawForeground;
    node.onDrawForeground = function () {
        render();
        return onDrawForeground?.apply(this, arguments);
    };
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
    const sync = node.addWidget("button", "Sync all workflows", null,
        () => syncAll(), { serialize: false });
    sync.serializeValue = () => undefined;
    modulePanel(node);
    if (node.size[1] < 220) node.setSize?.([Math.max(node.size[0], 360), 220]);
    const onRemoved = node.onRemoved;
    node.onRemoved = function () {
        pickers.delete(picker);
        onRemoved?.apply(this, arguments);
    };
    const onSelected = node.onSelected;
    node.onSelected = function () {
        onSelected?.apply(this, arguments);
        refreshPickers();
    };
    refreshPickers();
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

    afterConfigureGraph() {
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
