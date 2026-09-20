// ABOUTME: Tests for the Set/Get Hub seams in find_node.js — which names a
// ABOUTME: canvas publishes, which slot feeds one, and the empty tail slot.
import { test } from "node:test";
import assert from "node:assert/strict";

import "../../web/js/find_node.js";
import {
    ensureTail, findSource, graphScope, nodesOf, publishedNames, slotName,
    typeAccepts, uniqueName,
} from "../../web/js/find_node.js";

const SET_HUB = "SymbioticaSetHub";

// A hub as LiteGraph holds one: named input slots, then the empty tail. `label`
// rather than `name` on some of them, because the frontend's own "Rename Slot"
// writes the label and leaves the name it was created with.
function setHub(slots) {
    return {
        type: SET_HUB,
        inputs: [
            ...slots.map(([name, type, link]) => ({ name, label: name, type, link })),
            { name: "+", type: "*", link: null },
        ],
    };
}

// KJNodes' Set node: the name is on the widget, the value on the only input.
function setNode(name, type, link = 1) {
    return { type: "SetNode", widgets: [{ value: name }],
             inputs: [{ name: type, type, link }] };
}

// Enough of a node for the slot list to be grown and trimmed the way LiteGraph
// does it. Nothing here touches links, which is the point: the tail is decided
// by names and emptiness alone.
function slotHolder(inputs = [], outputs = []) {
    return {
        inputs, outputs,
        addInput(name, type, extra) { this.inputs.push({ name, type, ...extra }); },
        addOutput(name, type, extra) { this.outputs.push({ name, type, links: [], ...extra }); },
        removeInput(i) { this.inputs.splice(i, 1); },
        removeOutput(i) { this.outputs.splice(i, 1); },
        setDirtyCanvas() {},
    };
}

// A node that holds widgets the way LiteGraph does: `addWidget` hands back the
// object it pushed. Nothing here defines `value` as an accessor, which is the
// point -- the row does that for itself.
function widgetHolder(inputs) {
    return {
        inputs, widgets: [],
        addWidget(type, name, value, callback) {
            const widget = { type, name, value, callback };
            this.widgets.push(widget);
            return widget;
        },
        setDirtyCanvas() {},
    };
}

test("a slot's name is its label once it has been renamed", () => {
    assert.equal(slotName({ name: "STRING", label: "asset_name" }), "asset_name");
    assert.equal(slotName({ name: "asset_name" }), "asset_name");
    assert.equal(slotName(undefined), "");
});

test("the canvas publishes hub slots and plain Set nodes as one list", () => {
    const graph = { nodes: [
        setHub([["asset_name", "STRING", 1], ["width", "INT", 2]]),
        setNode("$$client-reference", "IMAGE"),
    ] };
    const names = publishedNames([graph]).map((e) => `${e.name}:${e.type}`);
    assert.deepEqual(names,
        ["asset_name:STRING", "width:INT", "$$client-reference:IMAGE"]);
});

test("the empty tail slot is not a name", () => {
    const graph = { nodes: [setHub([["asset_name", "STRING", 1]])] };
    assert.deepEqual(publishedNames([graph]).map((e) => e.name), ["asset_name"]);
    assert.equal(findSource([graph], "+"), null);
});

test("a name resolves to the slot it is fed through", () => {
    const hub = setHub([["asset_name", "STRING", 1], ["width", "INT", 2]]);
    const kj = setNode("project_path", "STRING", 7);
    const graph = { nodes: [hub, kj] };
    assert.deepEqual(findSource([graph], "width"),
                     { graph, node: hub, index: 1 });
    // A name on a plain Set node answers the same way, which is what lets a
    // Get Hub pull names that were never folded into a hub.
    assert.deepEqual(findSource([graph], "project_path"),
                     { graph, node: kj, index: 0 });
    assert.equal(findSource([graph], "nothing"), null);
});

test("a subgraph looks up its own graph first, then the root", () => {
    const root = { nodes: [setHub([["seed", "INT", 1]])] };
    const inner = { nodes: [] };
    assert.deepEqual(graphScope(inner, root), [inner, root]);
    assert.deepEqual(graphScope(root, root), [root]);
    assert.equal(findSource(graphScope(inner, root), "seed").graph, root);
});

test("a second slot under a taken name gets a suffix", () => {
    const taken = new Set(["width", "width_2"]);
    assert.equal(uniqueName(taken, "height"), "height");
    assert.equal(uniqueName(taken, "width"), "width_3");
    // A wire off an unnamed output would otherwise name the slot "*".
    assert.equal(uniqueName(new Set(), "*"), "value");
});

test("a name fits an input when the types meet", () => {
    assert.ok(typeAccepts("STRING", "STRING"));
    assert.ok(typeAccepts("*", "MODEL"));
    assert.ok(typeAccepts("INT,FLOAT", "FLOAT"));
    assert.ok(!typeAccepts("IMAGE", "MASK"));
});

test("the hub always ends in exactly one empty slot", () => {
    const node = slotHolder([{ name: "asset_name", type: "STRING", link: 3 }]);
    assert.equal(ensureTail(node, "in"), true);
    assert.deepEqual(node.inputs.map((s) => s.name), ["asset_name", "+"]);
    // Asserted on every draw, so it has to be a no-op once it holds.
    assert.equal(ensureTail(node, "in"), false);
    assert.equal(node.inputs.length, 2);
});

test("an empty slot above the tail is dropped, a named one is kept", () => {
    const node = slotHolder([
        { name: "+", type: "*", link: null },
        { name: "asset_name", label: "asset_name", type: "STRING", link: null },
        { name: "+", type: "*", link: null },
    ]);
    ensureTail(node, "in");
    // The unwired name survives: every Get on the canvas points at it, so a
    // wire moving off it must not take the name away.
    assert.deepEqual(node.inputs.map((s) => s.name), ["asset_name", "+"]);
});

test("the Get side grows the same way, on its outputs", () => {
    const node = slotHolder([], [{ name: "seed", type: "INT", links: [4] }]);
    assert.equal(ensureTail(node, "out"), true);
    assert.deepEqual(node.outputs.map((s) => s.name), ["seed", "+"]);
    assert.equal(ensureTail(node, "out"), false);
});

test("nodesOf reads either shape of graph", () => {
    assert.deepEqual(nodesOf({ _nodes: [1] }), [1]);
    assert.deepEqual(nodesOf({ nodes: [2] }), [2]);
    assert.deepEqual(nodesOf(null), []);
});

test("a slot is named for what the wire carries, not for its type", async () => {
    const { nameFromWire } = await import("../../web/js/find_node.js");
    // An output that says what it is keeps its name.
    assert.equal(nameFromWire({ name: "asset_name" }, "STRING", { title: "Asset Focus" }),
                 "asset_name");
    // A type name that says what the value is stays: three wires off a
    // checkpoint loader are MODEL, CLIP, VAE, not "Load Checkpoint_2".
    assert.equal(nameFromWire({ name: "MODEL" }, "MODEL", { title: "Load Checkpoint" }),
                 "MODEL");
    assert.equal(nameFromWire({ name: "IMAGE" }, "IMAGE", { title: "Empty Image" }),
                 "IMAGE");
    // A scalar type says nothing, so the node it came from answers instead --
    // STRING, STRING_2, STRING_3 is what a canvas gets otherwise.
    assert.equal(nameFromWire({ name: "STRING" }, "STRING", { title: "client_prompt" }),
                 "client_prompt");
    assert.equal(nameFromWire({ name: "STRING" }, "STRING", null), "STRING");
});

test("a name row reads its slot rather than holding a value", async () => {
    const { addNameRow, namedSlots } = await import("../../web/js/find_node.js");
    const node = widgetHolder([
        { name: "stupid", label: "stupid", type: "STRING", link: 1 },
        { name: "agent", label: "agent", type: "STRING", link: 2 },
        { name: "+", type: "*", link: null },
    ]);
    assert.deepEqual(namedSlots(node).map((s) => s.label), ["stupid", "agent"]);
    const rows = [addNameRow(node, 0), addNameRow(node, 1)];
    // Two rows of one type: what each reads is its own slot, whatever the
    // frontend's widget store remembers under the row's name.
    assert.deepEqual(rows.map((w) => w.value), ["stupid", "agent"]);
    // The type is what you read on the left of the row.
    assert.deepEqual(rows.map((w) => w.label), ["STRING", "STRING"]);
    // A row is positional: rename the second slot and the second row follows.
    node.inputs[1].label = "renamed";
    assert.deepEqual(rows.map((w) => w.value), ["stupid", "renamed"]);
    // And a slot removed under a row leaves it reading the one that moved up.
    node.inputs.splice(0, 1);
    assert.equal(rows[0].value, "renamed");
});
