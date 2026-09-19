// ABOUTME: Asset Recipe slots — the widget you drag onto the node becomes a
// ABOUTME: value set here, and the wire out of the slot is what carries it.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, configure, create, link, reset, tick } from "./comfy_stub.mjs";
import "../../web/js/asset_focus.js";
import "../../web/js/asset_recipe.js";

// The node definition as ComfyUI serves it: Asset Focus's own outputs, then
// the wildcard slots Python declares (SLOT_COUNT in py/pipeline/nodes.py).
const FOCUS_OUTPUTS = ["asset_name", "category", "client_prompt", "save_path",
                       "order", "event_order", "bucket", "ref_image",
                       "ref_mask", "ref_name", "category_recipe", "width",
                       "height"];
const SLOT_COUNT = 16;
const OUTPUT_NAMES = [...FOCUS_OUTPUTS,
                      ...Array.from({ length: SLOT_COUNT },
                                    (_, i) => `slot_${i + 1}`)];
const FIRST = FOCUS_OUTPUTS.length;

async function recipeNode(widgets = {}) {
    reset();
    const node = await create("SymbioticaAssetRecipe",
                              { order: null, category: "", asset: "",
                                slots: "[]", ...widgets },
                              { output_name: OUTPUT_NAMES });
    await node.onNodeCreated?.call(node);
    for (let i = 0; i < 3; i++) await tick();
    return node;
}

// A node with real widgets to take a value off: `defs` is its node definition,
// which is the only place that says INT rather than FLOAT.
async function farNode(type, widgets, defs = {}) {
    const node = await create(type, widgets);
    node.constructor = { nodeData: { input: { required: defs } } };
    for (const w of node.widgets) {
        const spec = defs[w.name];
        if (Array.isArray(spec?.[0])) {
            w.type = "combo";
            w.options = { values: spec[0] };
        } else if (spec?.[0] === "INT" || spec?.[0] === "FLOAT") {
            w.type = "number";
            w.options = { ...(spec[1] ?? {}) };
        } else if (spec?.[0] === "BOOLEAN") {
            w.type = "toggle";
            w.options = {};
        }
    }
    return node;
}

function wire(recipe, index, target, inputName) {
    const id = link(recipe, target, inputName, index);
    recipe.onConnectionsChange?.call(recipe, 2, index, true,
                                     app.graph.links[id]);
    return id;
}

// What litegraph does on an unplug: the link goes, the slot forgets it, then
// the node is told.
async function unwire(recipe, index, id) {
    delete app.graph.links[id];
    const out = recipe.outputs[index];
    out.links = (out.links ?? []).filter((l) => l !== id);
    recipe.onConnectionsChange?.call(recipe, 2, index, false, null);
    for (let i = 0; i < 3; i++) await tick();
}

const slots = (node) =>
    JSON.parse(node.widgets.find((w) => w.name === "slots").value);
const labels = (node) => node.outputs.slice(FIRST).map((o) => o.label);
const slotWidgets = (node) => node.widgets.filter((w) => w._symSlot);

const SAMPLER_DEF = {
    seed: ["INT", { min: 0, max: 999, precision: 0 }],
    denoise: ["FLOAT", { min: 0, max: 1, step: 0.01, precision: 2 }],
};

test("a fresh node offers one empty slot and nothing else", async () => {
    const node = await recipeNode();
    assert.equal(node.outputs.length, FIRST + 1);
    assert.deepEqual(labels(node), ["+ widget"]);
    assert.deepEqual(slots(node), []);
    // Asset Focus's own outputs are untouched.
    assert.equal(node.outputs[0].name, "asset_name");
});

test("dragging a widget in takes its name, type and value", async () => {
    const node = await recipeNode();
    const sampler = await farNode("KSampler", { denoise: 0.8 }, SAMPLER_DEF);
    wire(node, FIRST, sampler, "denoise");

    assert.deepEqual(slots(node), [{
        name: "denoise", type: "FLOAT", value: 0.8,
        config: { min: 0, max: 1, step: 0.01, precision: 2 },
    }]);
    const widget = slotWidgets(node)[0];
    assert.equal(widget.name, "denoise");
    assert.equal(widget.type, "number");
    assert.equal(widget.value, 0.8);
    assert.equal(widget.options.max, 1);
});

test("a filled slot opens an empty one under it", async () => {
    const node = await recipeNode();
    const sampler = await farNode("KSampler", { denoise: 0.8 }, SAMPLER_DEF);
    wire(node, FIRST, sampler, "denoise");
    assert.deepEqual(labels(node), ["denoise", "+ widget"]);
    // The name is the slot's POSITION: Python answers `slot_1` with the first
    // row of the table.
    assert.deepEqual(node.outputs.slice(FIRST).map((o) => o.name),
                     ["slot_1", "slot_2"]);
    assert.equal(node.outputs[FIRST].type, "FLOAT");
});

test("a slot widget never takes a position in widgets_values", async () => {
    // It would hand every widget saved after it the value one slot along —
    // the whole block rides in the `slots` string instead.
    const node = await recipeNode();
    const sampler = await farNode("KSampler", { seed: 42 }, SAMPLER_DEF);
    wire(node, FIRST, sampler, "seed");
    assert.equal(slotWidgets(node)[0].serialize, false);
});

test("an INT widget stays an INT", async () => {
    const node = await recipeNode();
    const sampler = await farNode("KSampler", { seed: 42 }, SAMPLER_DEF);
    wire(node, FIRST, sampler, "seed");
    assert.equal(slots(node)[0].type, "INT");
});

test("a combo slot clones the list it was taken from", async () => {
    const node = await recipeNode();
    const loader = await farNode("LoraLoader", { lora_name: "b.safetensors" },
                                 { lora_name: [["a.safetensors",
                                                "b.safetensors"]] });
    wire(node, FIRST, loader, "lora_name");

    assert.equal(slots(node)[0].type, "COMBO");
    assert.deepEqual(slots(node)[0].config.values,
                     ["a.safetensors", "b.safetensors"]);
    const widget = slotWidgets(node)[0];
    assert.equal(widget.type, "combo");
    assert.equal(widget.value, "b.safetensors");
    assert.deepEqual(widget.options.values,
                     ["a.safetensors", "b.safetensors"]);
});

test("typing in a slot writes the value the node will send", async () => {
    const node = await recipeNode();
    const sampler = await farNode("KSampler", { denoise: 0.8 }, SAMPLER_DEF);
    wire(node, FIRST, sampler, "denoise");

    const widget = slotWidgets(node)[0];
    widget.value = 0.35;
    widget.callback(0.35);
    assert.equal(slots(node)[0].value, 0.35);
});

test("a second wire onto a filled slot drives both from the one value",
     async () => {
    const node = await recipeNode();
    const one = await farNode("KSampler", { denoise: 0.8 }, SAMPLER_DEF);
    const two = await farNode("KSampler", { denoise: 0.2 }, SAMPLER_DEF);
    wire(node, FIRST, one, "denoise");
    wire(node, FIRST, two, "denoise");

    assert.equal(slots(node).length, 1);
    assert.deepEqual(labels(node), ["denoise", "+ widget"]);
});

test("a socket that is not a widget is refused, and says so", async () => {
    const node = await recipeNode();
    const sampler = await farNode("KSampler", {}, {});
    const said = [];
    app.extensionManager = { toast: { add: (t) => said.push(t.detail) } };
    try {
        const id = wire(node, FIRST, sampler, "model");
        // The wire is dropped rather than left pointing at a slot that can
        // hold nothing.
        assert.equal(app.graph.links[id], undefined);
    } finally {
        delete app.extensionManager;
    }
    assert.deepEqual(slots(node), []);
    assert.deepEqual(labels(node), ["+ widget"]);
    assert.equal(said.length, 1);
    assert.match(said[0], /widget/);
});

test("unplugging the last wire takes the slot with it", async () => {
    const node = await recipeNode();
    const sampler = await farNode("KSampler", { denoise: 0.8 }, SAMPLER_DEF);
    const id = wire(node, FIRST, sampler, "denoise");
    await unwire(node, FIRST, id);

    assert.deepEqual(slots(node), []);
    assert.deepEqual(labels(node), ["+ widget"]);
    assert.equal(slotWidgets(node).length, 0);
});

test("removing a slot moves the ones under it up, wires and all", async () => {
    // The row and the output have to shift together: Python answers `slot_1`
    // with the first row, so a wire left pointing at the old position would
    // start carrying the wrong value.
    const node = await recipeNode();
    const one = await farNode("KSampler", { denoise: 0.8 }, SAMPLER_DEF);
    const two = await farNode("KSampler", { seed: 42 }, SAMPLER_DEF);
    const first = wire(node, FIRST, one, "denoise");
    const second = wire(node, FIRST + 1, two, "seed");
    assert.deepEqual(labels(node), ["denoise", "seed", "+ widget"]);

    await unwire(node, FIRST, first);

    assert.deepEqual(slots(node).map((r) => r.name), ["seed"]);
    assert.deepEqual(labels(node), ["seed", "+ widget"]);
    assert.deepEqual(slotWidgets(node).map((w) => w.name), ["seed"]);
    assert.equal(app.graph.links[second].origin_slot, FIRST);
});

test("a saved graph comes back with its slots, and adopts nothing", async () => {
    const node = await recipeNode();
    const saved = JSON.stringify([
        { name: "denoise", type: "FLOAT", value: 0.35,
          config: { min: 0, max: 1, step: 0.01 } },
        { name: "lora-strength", type: "FLOAT", value: 0.7, config: {} },
    ]);
    // Exactly what a save writes: one entry per widget that serialises, in
    // the order they sit on the node.
    const values = [];
    for (const w of node.widgets) {
        if (w.serialize === false) continue;
        values.push(w.name === "slots" ? saved : (w.value ?? null));
    }
    configure(node, { widgets_values: values });
    for (let i = 0; i < 3; i++) await tick();

    assert.deepEqual(labels(node), ["denoise", "lora-strength", "+ widget"]);
    assert.deepEqual(slotWidgets(node).map((w) => w.value), [0.35, 0.7]);
    assert.deepEqual(slots(node).map((r) => r.name), ["denoise", "lora-strength"]);
});

test("the node never shows more slots than Python declares", async () => {
    const node = await recipeNode();
    const rows = Array.from({ length: SLOT_COUNT }, (_, i) => ({
        name: `w${i}`, type: "FLOAT", value: i, config: {},
    }));
    node.widgets.find((w) => w.name === "slots").value = JSON.stringify(rows);
    node.onConfigure?.call(node, {});
    for (let i = 0; i < 3; i++) await tick();

    assert.equal(node.outputs.length, FIRST + SLOT_COUNT);
    assert.equal(labels(node).includes("+ widget"), false);
});

test("unreadable slot JSON leaves the node usable", async () => {
    const node = await recipeNode({ slots: "{oops" });
    assert.deepEqual(labels(node), ["+ widget"]);
    assert.equal(slotWidgets(node).length, 0);
});

// What litegraph hands the hook when you right-click an output dot.
const slotMenu = (node, index) =>
    node.getExtraSlotMenuOptions?.call(
        node, { output: node.outputs[index], slot: index }) ?? [];
const entry = (menu, content) => menu.find((e) => e?.content === content);

test("a slot is taken off by hand from its right-click menu", async () => {
    const node = await recipeNode();
    const one = await farNode("KSampler", { denoise: 0.8 }, SAMPLER_DEF);
    const two = await farNode("KSampler", { seed: 42 }, SAMPLER_DEF);
    wire(node, FIRST, one, "denoise");
    const second = wire(node, FIRST + 1, two, "seed");

    entry(slotMenu(node, FIRST), "Remove slot").callback();
    for (let i = 0; i < 3; i++) await tick();

    assert.deepEqual(slots(node).map((r) => r.name), ["seed"]);
    assert.deepEqual(labels(node), ["seed", "+ widget"]);
    assert.deepEqual(slotWidgets(node).map((w) => w.name), ["seed"]);
    assert.equal(app.graph.links[second].origin_slot, FIRST);
});

test("the empty slot and the focus outputs offer no removal", async () => {
    const node = await recipeNode();
    assert.equal(entry(slotMenu(node, FIRST), "Remove slot"), undefined);
    assert.equal(entry(slotMenu(node, 0), "Remove slot"), undefined);
});

test("a wired slot that never became a row is still removable", async () => {
    // The state on the canvas when adoption failed: the wire landed, the table
    // stayed empty, and there was no way back out of it.
    const node = await recipeNode();
    const far = await farNode("KSampler", { seed: 42 }, SAMPLER_DEF);
    link(node, far, "seed", FIRST);
    assert.equal(slots(node).length, 0);

    entry(slotMenu(node, FIRST), "Remove slot").callback();
    for (let i = 0; i < 3; i++) await tick();

    assert.deepEqual(labels(node), ["+ widget"]);
    assert.equal(node.outputs.length, FIRST + 1);
});

test("a reopened node shows the value each slot holds", async () => {
    // ComfyUI remembers widget values by name: re-adding a widget under a name
    // this node has carried hands back what it held before and drops the value
    // passed. The table is the value, so a rebuild has to write it — his bakery
    // node came back with an empty lora slot on every reopen.
    const row = (value) => JSON.stringify(
        [{ name: "steps", type: "INT", value, config: { min: 1, max: 100 } }]);
    const node = await recipeNode({ slots: row(20) });
    assert.equal(slotWidgets(node)[0].value, 20);

    // The same node reopened on a recipe that sets it to 30.
    node.widgets.find((w) => w.name === "slots").value = row(30);
    node.onConfigure?.call(node, {});
    for (let i = 0; i < 3; i++) await tick();

    assert.equal(slotWidgets(node)[0].value, 30);
});
