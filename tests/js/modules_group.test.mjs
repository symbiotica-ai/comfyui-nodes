// ABOUTME: The group-module merge in the browser — tagged member nodes are
// ABOUTME: replaced by the library version, links relinked by slot name, ids kept.
// Mirrors tests/test_modules_group.py; the two implementations must agree.
import assert from "node:assert/strict";
import { test } from "node:test";

import "./comfy_stub.mjs";
import { applyModules } from "../../web/js/modules.js";

const GTAG = "symbiotica_group";
const NAME = "controlnet";

function node(id, type, pos, { inputs = [], outputs = [], values = [], key = null, rev = 1, snapshot = null } = {}) {
    const n = {
        id, type, pos: [...pos], size: [200, 100], flags: {}, order: 0, mode: 0,
        inputs: inputs.map((name) => ({ name, type: "IMAGE", link: null })),
        outputs: outputs.map((name) => ({ name, type: "IMAGE", links: [] })),
        properties: {},
        widgets_values: [...values],
    };
    if (key !== null) n.properties[GTAG] = { name: NAME, key: String(key), rev, snapshot: [...(snapshot ?? values)] };
    return n;
}

function connect(graph, id, a, aSlot, b, bSlot, asObject = false) {
    graph.links.push(asObject
        ? { id, origin_id: a.id, origin_slot: aSlot, target_id: b.id, target_slot: bSlot, type: "IMAGE" }
        : [id, a.id, aSlot, b.id, bSlot, "IMAGE"]);
    a.outputs[aSlot].links.push(id);
    b.inputs[bSlot].link = id;
}

function publishedModule({ rev = 2, padding = 100, extraNode = false, dropPad = false } = {}) {
    const nodes = [
        node(1, "LoadImage", [10, 40], { outputs: ["IMAGE", "MASK"], values: ["ref.png", "image"] }),
        node(3, "PreviewImage", [500, 40], { inputs: ["images"] }),
    ];
    let links;
    if (!dropPad) {
        nodes.splice(1, 0, node(2, "Padding", [250, 40], { inputs: ["image"], outputs: ["image"], values: [padding, "0, 0, 0", "color"] }));
        links = [{ id: 1, origin_id: 1, origin_slot: 0, target_id: 2, target_slot: 0, type: "IMAGE" },
                 { id: 2, origin_id: 2, origin_slot: 0, target_id: 3, target_slot: 0, type: "IMAGE" }];
    } else {
        links = [{ id: 1, origin_id: 1, origin_slot: 0, target_id: 3, target_slot: 0, type: "IMAGE" }];
    }
    if (extraNode) {
        nodes.push(node(4, "ImageBlur", [250, 200], { inputs: ["image"], outputs: ["image"], values: [3] }));
        links.push({ id: 3, origin_id: 1, origin_slot: 0, target_id: 4, target_slot: 0, type: "IMAGE" });
    }
    return { name: NAME, rev, kind: "group", group: { title: "Controlnet", flags: {} }, nodes, links };
}

function workflowWithGroup(asDef = false) {
    const load = node(2999, "LoadImage", [1010, 1040], { outputs: ["IMAGE", "MASK"], values: ["cube.png", "image"], key: 1, snapshot: ["ref.png", "image"] });
    const pad = node(3270, "Padding", [1250, 1040], { inputs: ["image"], outputs: ["image"], values: [50, "0, 0, 0", "color"], key: 2 });
    const prev = node(3236, "PreviewImage", [1500, 1040], { inputs: ["images"], key: 3 });
    const source = node(10, "LoadImage", [100, 100], { outputs: ["IMAGE", "MASK"], values: ["src.png", "image"] });
    const sink = node(11, "ImageUpscale", [2000, 100], { inputs: ["image"] });
    const graph = { nodes: [source, load, pad, prev, sink], links: [],
        groups: [{ id: 7, title: "Controlnet", bounding: [1000, 1000, 800, 300], flags: {} }] };
    connect(graph, 100, load, 0, pad, 0, asDef);
    connect(graph, 101, pad, 0, prev, 0, asDef);
    connect(graph, 102, pad, 0, sink, 0, asDef);
    if (asDef) {
        Object.assign(graph, { id: "def-id", version: 1, state: { lastNodeId: 3270, lastLinkId: 103 } });
        return { nodes: [], links: [], last_node_id: 0, last_link_id: 0, definitions: { subgraphs: [graph] }, extra: {} };
    }
    Object.assign(graph, { last_node_id: 3270, last_link_id: 103, extra: {} });
    return graph;
}

const byId = (graph, id) => graph.nodes.find((n) => n.id === id);
const linksOf = (graph) => new Set(graph.links.map((l) => (Array.isArray(l)
    ? `${l[1]}:${l[2]}>${l[3]}:${l[4]}` : `${l.origin_id}:${l.origin_slot}>${l.target_id}:${l.target_slot}`)));

test("a value the module changed lands; a local value survives", () => {
    const w = workflowWithGroup();
    const report = applyModules(w, { [NAME]: publishedModule({ padding: 100 }) });
    assert.deepEqual(report.updated, [{ name: NAME, rev: 2 }]);
    assert.equal(byId(w, 3270).widgets_values[0], 100);
    assert.equal(byId(w, 2999).widgets_values[0], "cube.png");
    assert.deepEqual(byId(w, 2999).properties[GTAG], { name: NAME, key: "1", rev: 2, snapshot: ["ref.png", "image"] });
});

test("ids, positions and outside links are kept; inside links are rebuilt", () => {
    const w = workflowWithGroup();
    applyModules(w, { [NAME]: publishedModule() });
    assert.deepEqual(w.nodes.map((n) => n.id).sort((a, b) => a - b), [10, 11, 2999, 3236, 3270]);
    assert.deepEqual(byId(w, 3270).pos, [1250, 1040]);
    assert.deepEqual(linksOf(w), new Set(["2999:0>3270:0", "3270:0>3236:0", "3270:0>11:0"]));
    assert.equal(byId(w, 11).inputs[0].link, 102);
    assert.ok(byId(w, 3270).outputs[0].links.includes(102));
    assert.ok(w.last_link_id >= 105);
});

test("a node added to the module appears at its relative position and the frame grows", () => {
    const w = workflowWithGroup();
    applyModules(w, { [NAME]: publishedModule({ extraNode: true }) });
    const blur = w.nodes.find((n) => n.type === "ImageBlur");
    assert.equal(blur.id, 3271);
    assert.equal(w.last_node_id, 3271);
    assert.deepEqual(blur.pos, [1250, 1200]);
    assert.equal(blur.properties[GTAG].key, "4");
    assert.ok(linksOf(w).has("2999:0>3271:0"));
    const [x, y, , h] = w.groups[0].bounding;
    assert.ok(y + h >= 1300);
    assert.equal(x, 1000);
    assert.equal(y, 1000);
});

test("a node removed from the module drops its outside link and says so", () => {
    const w = workflowWithGroup();
    const report = applyModules(w, { [NAME]: publishedModule({ dropPad: true }) });
    assert.ok(w.nodes.every((n) => n.type !== "Padding"));
    assert.deepEqual(linksOf(w), new Set(["2999:0>3236:0"]));
    assert.equal(byId(w, 11).inputs[0].link, null);
    assert.deepEqual(report.linksDropped, [{ module: NAME, key: "2", slot: "image" }]);
});

test("an instance inside a subgraph definition uses object links and state counters", () => {
    const w = workflowWithGroup(true);
    applyModules(w, { [NAME]: publishedModule({ extraNode: true }) });
    const d = w.definitions.subgraphs[0];
    assert.equal(byId(d, 3270).widgets_values[0], 100);
    assert.ok(d.links.every((l) => !Array.isArray(l)));
    assert.equal(d.state.lastNodeId, 3271);
    assert.ok(linksOf(d).has("2999:0>3271:0"));
});

test("a current revision and a foreign name are left alone", () => {
    const w = workflowWithGroup();
    const before = structuredClone(w);
    assert.equal(applyModules(w, { [NAME]: publishedModule({ rev: 1 }) }).changed, false);
    assert.equal(applyModules(w, { other: publishedModule() }).changed, false);
    assert.deepEqual(w, before);
});

test("a widget count mismatch keeps the local values", () => {
    const w = workflowWithGroup();
    byId(w, 3270).widgets_values.push("extra");
    const report = applyModules(w, { [NAME]: publishedModule() });
    assert.deepEqual(byId(w, 3270).widgets_values, [50, "0, 0, 0", "color", "extra"]);
    assert.deepEqual(report.valuesSkipped, [3270]);
});
