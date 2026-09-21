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

test("a slot named by the wire follows the node feeding it", async () => {
    const { followWireNames } = await import("../../web/js/find_node.js");
    const source = { id: 2, title: "water", outputs: [{ name: "STRING", type: "STRING" }] };
    const graph = {
        links: { 5: { id: 5, origin_id: 2, origin_slot: 0 } },
        getNodeById: (id) => (id === 2 ? source : null),
        nodes: [],
    };
    // `name` and `label` agreeing is what says the WIRE named this slot.
    const auto = { name: "water", label: "water", type: "STRING", link: 5 };
    // A name he typed: `name` still holds what the wire called it.
    const mine = { name: "water", label: "asset_name", type: "STRING", link: 5 };
    const node = slotHolder([auto, mine, { name: "+", type: "*", link: null }]);
    node.graph = graph;
    graph.nodes.push(node);

    source.title = "earth";
    followWireNames(node);
    assert.equal(auto.label, "earth");
    assert.equal(auto.name, "earth");   // still the wire's, so it keeps following
    // His name is his: retitling the source does not take it away.
    assert.equal(mine.label, "asset_name");

    // The suffix a clash gave a slot is not a difference: STRING_3 off a wire
    // that says STRING is already following it, and recomputing that every
    // draw would shuffle names around the node as other names come and go.
    const clashed = { name: "earth_3", label: "earth_3", type: "STRING", link: 5 };
    node.inputs.unshift(clashed);
    followWireNames(node);
    assert.equal(clashed.label, "earth_3");
    node.inputs.shift();

    // An output that says what it carries names the slot, and a retitle of the
    // node behind it changes nothing -- there is nothing better to be called.
    source.outputs[0].name = "asset_name";
    source.title = "somewhere else";
    followWireNames(node);
    assert.equal(auto.label, "asset_name");
});

test("a wire taken off a slot takes the slot with it", async () => {
    const { dropWhenUnwired } = await import("../../web/js/find_node.js");
    const node = slotHolder([
        { name: "asset_name", label: "asset_name", type: "STRING", link: 3 },
        { name: "ref_image", label: "ref_image", type: "IMAGE", link: null },
        { name: "+", type: "*", link: null },
    ]);
    node.widgets = [];
    node.addWidget = function (type, name, value, callback) {
        const w = { type, name, value, callback };
        this.widgets.push(w);
        return w;
    };
    // The tick is what tells a rewire from an abandonment, so the test holds it.
    const queued = [];
    dropWhenUnwired(node, 1, (fn) => queued.push(fn));
    assert.deepEqual(node.inputs.map((s) => s.name), ["asset_name", "ref_image", "+"]);
    queued.pop()();
    assert.deepEqual(node.inputs.map((s) => s.name), ["asset_name", "+"]);

    // Rewiring the same slot is a disconnect and a connect back to back: the
    // slot has a wire again when the tick comes, and the name stays.
    dropWhenUnwired(node, 0, (fn) => queued.push(fn));
    node.inputs[0].link = 9;
    queued.pop()();
    assert.deepEqual(node.inputs.map((s) => s.name), ["asset_name", "+"]);

    // The empty tail is not a name, and is never what a disconnect removes.
    dropWhenUnwired(node, 1, (fn) => queued.push(fn));
    assert.equal(queued.length, 0);
});

test("an empty slot above the tail is dropped, a named one is kept", () => {
    const node = slotHolder([
        { name: "+", type: "*", link: null },
        { name: "asset_name", label: "asset_name", type: "STRING", link: null },
        { name: "+", type: "*", link: null },
    ]);
    ensureTail(node, "in");
    // The tail is all this decides. A named slot losing its wire is removed by
    // the disconnect above, not by a pass that is run on every draw.
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

test("a Set Hub is a group, named by its title", async () => {
    const { publishedGroups } = await import("../../web/js/find_node.js");
    const paths = setHub([["project", "STRING", 1], ["controlnet", "STRING", 2]]);
    paths.title = "paths";
    const models = setHub([["model", "MODEL", 3]]);
    models.title = "models";
    // A hub holding nothing yet is not a group: there is nothing to take.
    const empty = { type: SET_HUB, title: "empty", inputs: [{ name: "+", type: "*" }] };
    const groups = publishedGroups([{ nodes: [paths, models, empty] }]);
    assert.deepEqual(groups.map((g) => g.title), ["paths", "models"]);
    assert.deepEqual(groups[0].names.map((e) => `${e.name}:${e.type}`),
                     ["project:STRING", "controlnet:STRING"]);
    // An untitled hub still answers, under the name every one is born with.
    delete paths.title;
    assert.equal(publishedGroups([{ nodes: [paths] }])[0].title, "Set Hub");
});

test("a Get Hub following a group grows with it", async () => {
    const { loadGroup, syncGroup, publishedGroups } =
        await import("../../web/js/find_node.js");
    const hub = setHub([["project", "STRING", 1], ["controlnet", "STRING", 2]]);
    hub.title = "paths";
    const graph = { nodes: [hub] };
    const get = slotHolder([], []);
    get.type = "SymbioticaGetHub";
    get.graph = graph;
    graph.nodes.push(get);

    loadGroup(get, publishedGroups([graph])[0]);
    assert.deepEqual(get.outputs.map((s) => s.label ?? s.name),
                     ["project", "controlnet", "+"]);
    // The title says which group -- and which SIDE, so a Set and the Get
    // reading it are never two nodes carrying one name.
    assert.equal(get.title, "Get paths");
    // A name added to the Set Hub arrives here, at the END: a wire holds on to
    // a slot's index, so nothing already on the node may be pushed down.
    hub.inputs.splice(2, 0, { name: "output", label: "output", type: "STRING", link: 3 });
    assert.equal(syncGroup(get), true);
    assert.deepEqual(get.outputs.map((s) => s.label ?? s.name),
                     ["project", "controlnet", "output", "+"]);
    // Asserted on every draw, so it has to be a no-op once it holds.
    assert.equal(syncGroup(get), false);
    // A name that leaves the group leaves the Get -- unless a wire is on it,
    // which is never taken away silently.
    get.outputs[0].links = [9];
    hub.inputs.splice(0, 2);
    assert.equal(syncGroup(get), true);
    assert.deepEqual(get.outputs.map((s) => s.label ?? s.name),
                     ["project", "output", "+"]);
});

test("picking a second group adds it to the first, and both go on following",
     async () => {
    const { loadGroup, syncGroup, publishedGroups } =
        await import("../../web/js/find_node.js");
    const one = setHub([["stupid", "STRING", 1], ["agent", "STRING", 2]]);
    one.id = 1;
    one.title = "settings-01";
    const two = setHub([["incompetent", "STRING", 3], ["claude", "STRING", 4]]);
    two.id = 2;
    two.title = "settings-02";
    const graph = { nodes: [one, two] };
    const get = slotHolder([], []);
    get.type = "SymbioticaGetHub";
    get.graph = graph;
    get.disconnectOutput = () => {};
    graph.nodes.push(get);
    const groups = () => publishedGroups([graph]);

    loadGroup(get, groups()[1]);
    assert.deepEqual(get.outputs.map((s) => s.label ?? s.name),
                     ["incompetent", "claude", "+"]);
    assert.equal(get.title, "Get settings-02");
    // A wire on a name the node already holds is never cut by a pick.
    get.outputs[0].links = [11];
    // The other group now: it lands UNDER what was there, and the node carries
    // both. Nothing he wired goes away because he asked for one more group.
    loadGroup(get, groups()[0]);
    assert.deepEqual(get.outputs.map((s) => s.label ?? s.name),
                     ["incompetent", "claude", "stupid", "agent", "+"]);
    assert.deepEqual(get.outputs[0].links, [11]);
    assert.equal(get.title, "Get settings-02 + settings-01");
    // Both are followed, so a name added to either arrives on the next draw.
    two.inputs.splice(2, 0, { name: "sonnet", label: "sonnet", type: "STRING", link: 5 });
    assert.equal(syncGroup(get), true);
    assert.deepEqual(get.outputs.map((s) => s.label ?? s.name),
                     ["incompetent", "claude", "stupid", "agent", "sonnet", "+"]);
    // Picking one it already follows is a re-assert, not a second copy.
    loadGroup(get, groups()[1]);
    assert.deepEqual(get.properties.symbiotica_group,
                     ["settings-02", "settings-01"]);
    assert.deepEqual(get.outputs.map((s) => s.label ?? s.name),
                     ["incompetent", "claude", "stupid", "agent", "sonnet", "+"]);
    // A title typed by hand is his, and a pick leaves it.
    get.title = "my paths";
    loadGroup(get, groups()[0]);
    assert.equal(get.title, "my paths");
});

test("retitling a Set Hub carries every Get following it", async () => {
    const { loadGroup, syncGroup, groupsOf, publishedGroups } =
        await import("../../web/js/find_node.js");
    const hub = setHub([["model", "MODEL", 1]]);
    hub.id = 7;
    hub.title = "settings-01";
    const graph = { nodes: [hub] };
    const get = slotHolder([], []);
    get.type = "SymbioticaGetHub";
    get.graph = graph;
    get.disconnectOutput = () => {};
    graph.nodes.push(get);

    loadGroup(get, publishedGroups([graph])[0]);
    assert.equal(get.title, "Get settings-01");

    // He retitles the group. The id is what carries the follower over, and the
    // title is healed on the node and in what it remembers.
    hub.title = "models";
    const group = groupsOf(get, [graph])[0];
    assert.equal(group.title, "models");
    assert.equal(get.title, "Get models");
    assert.deepEqual(get.properties.symbiotica_group, ["models"]);
    assert.equal(syncGroup(get), false);
    assert.deepEqual(get.outputs.map((s) => s.label ?? s.name), ["model", "+"]);

    // A title he typed himself is his, and a retitle of the group leaves it.
    get.title = "mine";
    hub.title = "checkpoints";
    assert.equal(groupsOf(get, [graph])[0].title, "checkpoints");
    assert.equal(get.title, "mine");
});

test("a title keeps the side it is on", async () => {
    const { groupNameOf, keepSideInTitle } =
        await import("../../web/js/find_node.js");
    // The group a title names is the title without the side word, so a Set
    // titled `Set _paths` and one titled `_paths` name the same group.
    assert.equal(groupNameOf("Set _paths"), "_paths");
    assert.equal(groupNameOf("_paths"), "_paths");
    assert.equal(groupNameOf("Get _paths"), "_paths");
    // The titles a hub is born with name no group at all.
    assert.equal(groupNameOf("Set Hub (Symbiotica)"), "");
    assert.equal(groupNameOf(""), "");

    // A title he typed takes the side in front of it, once.
    const node = { title: "_paths" };
    assert.equal(keepSideInTitle(node, "Set"), true);
    assert.equal(node.title, "Set _paths");
    assert.equal(keepSideInTitle(node, "Set"), false);
    assert.equal(node.title, "Set _paths");
    // The stock title already says it.
    const fresh = { title: "Get Hub (Symbiotica)" };
    assert.equal(keepSideInTitle(fresh, "Get"), false);
});

test("a value picked on a hub that follows a group lands beside the group",
     async () => {
    const { loadGroup, loadName, syncGroup, publishedGroups, publishedNames,
            titleForGet, groupsOf } = await import("../../web/js/find_node.js");
    const hub = setHub([["asset_name", "STRING", 1], ["client_prompt", "STRING", 2]]);
    hub.id = 3;
    hub.title = "task-specs";
    // The name he wants beside the group lives on another hub he is NOT
    // following -- one value out of it, not the whole thing.
    const sizes = setHub([["sprite_width", "INT", 5], ["sprite_height", "INT", 6]]);
    sizes.id = 4;
    sizes.title = "sizes";
    const graph = { nodes: [hub, sizes] };
    const get = slotHolder([], []);
    get.type = "SymbioticaGetHub";
    get.graph = graph;
    get.disconnectOutput = () => {};
    graph.nodes.push(get);

    loadGroup(get, publishedGroups([graph])[0]);
    assert.deepEqual(get.outputs.map((s) => s.label ?? s.name),
                     ["asset_name", "client_prompt", "+"]);
    assert.equal(get.title, "Get task-specs");

    get.outputs[1].links = [42];
    const width = publishedNames([graph]).find((e) => e.name === "sprite_width");
    loadName(get, width);
    assert.deepEqual(get.outputs.map((s) => s.label ?? s.name),
                     ["asset_name", "client_prompt", "sprite_width", "+"]);
    assert.deepEqual(get.outputs[1].links, [42]);
    assert.equal(get.outputs[2].type, "INT");
    // It still follows the group, and the title says what it carries besides.
    assert.deepEqual(get.properties.symbiotica_group, ["task-specs"]);
    assert.equal(get.title, "Get task-specs +1");
    // A draw does not take the picked name away: the group does not hold it,
    // but the canvas publishes it, which is the whole of what a slot needs.
    assert.equal(syncGroup(get), false);
    assert.deepEqual(get.outputs.map((s) => s.label ?? s.name),
                     ["asset_name", "client_prompt", "sprite_width", "+"]);
    assert.equal(titleForGet(get, groupsOf(get, [graph])), "Get task-specs +1");

    // Following nothing, names are pulled one at a time, as before.
    const solo = slotHolder([], []);
    solo.type = "SymbioticaGetHub";
    solo.graph = graph;
    graph.nodes.push(solo);
    loadName(solo, publishedNames([graph]).find((e) => e.name === "asset_name"));
    assert.equal(solo.title, "Get asset_name");
    loadName(solo, publishedNames([graph]).find((e) => e.name === "client_prompt"));
    assert.deepEqual(solo.outputs.map((s) => s.label ?? s.name),
                     ["asset_name", "client_prompt", "+"]);
    // Two names are not one name, and the title says neither.
    assert.equal(titleForGet(solo), "Get Hub");
});

test("a Get Hub follows no group until it is told to", async () => {
    const { groupsOf, syncGroup } = await import("../../web/js/find_node.js");
    const get = slotHolder([], []);
    get.graph = { nodes: [] };
    assert.deepEqual(groupsOf(get, [get.graph]), []);
    assert.equal(syncGroup(get), false);
    // A group whose Set Hub is gone adds nothing and takes nothing away. The
    // bare string is what a workflow saved before a hub could follow several
    // holds, and it reads as a list of one.
    get.properties = { symbiotica_group: "paths" };
    get.outputs = [{ name: "project", label: "project", links: [] }];
    assert.equal(syncGroup(get), false);
    assert.deepEqual(get.outputs.map((s) => s.label), ["project"]);
});

test("a Get slot whose name is gone from the canvas goes with it", async () => {
    const { dropDeadNames } = await import("../../web/js/find_node.js");
    const { app } = await import("./comfy_stub.mjs");
    const hub = setHub([["category", "STRING", 1]]);
    app.graph._nodes = [hub];
    const get = slotHolder([], [
        { name: "category", label: "category", type: "STRING", links: [],
          color_on: "#f2777a", color_off: "#f2777a" },
        { name: "gone", label: "gone", type: "STRING", links: [7] },
    ]);
    get.graph = app.graph;
    get.disconnectOutput = () => {};

    dropDeadNames(get);
    // The wire on "gone" is no argument for keeping it: it resolved to nothing
    // already, and the run would have failed on a missing input.
    assert.deepEqual(get.outputs.map((s) => s.label ?? s.name), ["category", "+"]);
    // A name that is published again loses the red it was given.
    assert.equal(get.outputs[0].color_on, undefined);

    // A name published where this node's lookup cannot reach -- another
    // subgraph -- still exists. That slot is marked, never removed: deleting
    // over a blind spot would take his wiring with it.
    const inner = { nodes: [setHub([["elsewhere", "STRING", 2]])] };
    app.graph._nodes = [hub, { type: "Subgraph", subgraph: inner }];
    get.outputs.splice(1, 0,
        { name: "elsewhere", label: "elsewhere", type: "STRING", links: [] });
    dropDeadNames(get);
    assert.deepEqual(get.outputs.map((s) => s.label ?? s.name),
                     ["category", "elsewhere", "+"]);
    assert.equal(get.outputs[1].color_on, "#f2777a");
    app.graph._nodes = [];
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
