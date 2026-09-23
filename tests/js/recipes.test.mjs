// ABOUTME: The Recipes node's table — cells are text, the project is JSON, and
// ABOUTME: the two must round-trip without a recipe losing or gaining a key.
import assert from "node:assert/strict";
import { test } from "node:test";

import "./comfy_stub.mjs";
import { cellText, cellValue, generateSummary, projectToTable, tableToProject } from "../../web/js/recipes.js";

const slots = [
    { key: "control_image", kind: "scalar", default: "old.png", widgets: 2 },
    { key: "grid", kind: "scalar", default: 2, widgets: 2 },
    { key: "strength", kind: "scalar", default: 0.5, widgets: 1 },
    { key: "pre_flip", kind: "toggle", default: false, widgets: 1 },
    { key: "render", kind: "dict", default: { lora_name: "old.safetensors", strength_model: 0.5 }, widgets: 2 },
];

// A project as it is written now: the base workflow and the recipes, nothing
// else. `output` and `workflow_prefix` are gone — one rule, beside the base
// and named after it — and a value left in an older file is dropped on save.
const project = () => ({
    template: "recipe-test/bakery-template.json",
    shared: { render: { lora_name: "bakery.safetensors" } },
    recipes: {
        appliance1x1: { control_image: "a.png", grid: [2, 1], pre_flip: false },
        appliance1x2: { control_image: "b.png", pre_flip: true, strength: 0.7 },
    },
});

test("a cell shows a string as itself and anything else as JSON", () => {
    assert.equal(cellText("a.png"), "a.png");
    assert.equal(cellText([2, 1]), "[2, 1]");
    assert.equal(cellText({ lora_name: "x" }), '{"lora_name": "x"}');
    assert.equal(cellText(true), "true");
    assert.equal(cellText(0.7), "0.7");
    assert.equal(cellText(undefined), "");
});

test("a text inside a node's values comes back from its cell exactly as it went in",
     () => {
    // His Prompts node, a dict slot. The spacing between tokens is the cell's,
    // and the commas and colons inside the text are the text's: every trip
    // through the table used to put one more space after each comma.
    const prompts = { kind: "dict", key: "Prompts (Symbiotica)" };
    const held = { folder: "image-model-prompts", file: "nano2-pre-chair.md",
                   text: 'Draw ONE chair, four times, once per slot,x\n"TASK": 1,000' };
    assert.equal(cellText({ a: "x, y", b: [1, 2] }), '{"a": "x, y", "b": [1, 2]}');
    let value = held;
    for (let trip = 0; trip < 11; trip += 1) value = cellValue(prompts, cellText(value));
    assert.deepEqual(value, held);
    // And through the whole table, which is the path a save takes.
    const table = projectToTable({ template: "t.json", shared: {},
                                   recipes: { "decoration-2x2": { [prompts.key]: held } } },
                                 [{ ...prompts, default: {} }]);
    const back = tableToProject({}, table, [{ ...prompts, default: {} }]);
    assert.deepEqual(back.recipes["decoration-2x2"][prompts.key], held);
});

test("an empty cell is an absent key, not an empty value", () => {
    assert.equal(cellValue(slots[0], ""), undefined);
    assert.equal(cellValue(slots[0], "   "), undefined);
});

test("a scalar cell keeps text as text unless the template value is a number or the text is a list", () => {
    assert.equal(cellValue(slots[0], "controlnet/bakery/x.png"), "controlnet/bakery/x.png");
    assert.equal(cellValue(slots[0], "123"), "123");
    assert.equal(cellValue(slots[2], "0.7"), 0.7);
    assert.deepEqual(cellValue(slots[1], "[2, 1]"), [2, 1]);
    assert.throws(() => cellValue(slots[2], "strong"), /strength/);
});

test("a toggle cell is true or false and nothing else", () => {
    assert.equal(cellValue(slots[3], "true"), true);
    assert.equal(cellValue(slots[3], "false"), false);
    assert.throws(() => cellValue(slots[3], "yes"), /pre_flip/);
});

test("a dict cell is a JSON object, and a bare value sets the first widget", () => {
    assert.deepEqual(cellValue(slots[4], '{"lora_name": "x"}'), { lora_name: "x" });
    // The server seeds a multi-widget node's slot with ONE value, and the
    // canvas can call that same slot a dict: refusing the cell walled off
    // every save on his project over a value the server itself wrote.
    assert.equal(cellValue(slots[4], "x.safetensors"), "x.safetensors");
    assert.deepEqual(cellValue(slots[4], "[1]"), [1]);
});

test("the table has a game column, one column per category, and a row per slot", () => {
    const table = projectToTable(project(), slots);
    assert.deepEqual(table.columns, ["shared", "appliance1x1", "appliance1x2"]);
    assert.deepEqual(table.rows.map((r) => r.key), slots.map((s) => s.key));
    const grid = table.rows.find((r) => r.key === "grid");
    assert.deepEqual(grid.cells, { shared: "", appliance1x1: "[2, 1]", appliance1x2: "" });
    const render = table.rows.find((r) => r.key === "render");
    assert.equal(render.cells.shared, '{"lora_name": "bakery.safetensors"}');
});

test("a key a category carries that the canvas has no slot for gets no row, and is dropped on save", () => {
    const r = project();
    r.recipes.appliance1x1.gone = "x";
    const table = projectToTable(r, slots);
    assert.equal(table.rows.find((row) => row.key === "gone"), undefined);
    assert.equal("gone" in tableToProject(r, table, slots).recipes.appliance1x1, false);
});

test("the table writes back the recipe it was read from", () => {
    const r = project();
    const table = projectToTable(r, slots);
    assert.deepEqual(tableToProject(r, table, slots), r);
});

test("edits land in the right column, empty cells drop the key, and a new column is a new category", () => {
    const r = project();
    const table = projectToTable(r, slots);
    table.rows.find((x) => x.key === "control_image").cells.appliance1x2 = "c.png";
    table.rows.find((x) => x.key === "pre_flip").cells.appliance1x1 = "";
    table.columns.push("chair");
    table.rows.find((x) => x.key === "control_image").cells.chair = "chair.png";
    table.header = { template: "t.json" };
    const out = tableToProject(r, table, slots);
    assert.equal(out.recipes.appliance1x2.control_image, "c.png");
    assert.equal("pre_flip" in out.recipes.appliance1x1, false);
    assert.deepEqual(out.recipes.chair, { control_image: "chair.png" });
    assert.equal(out.template, "t.json");
    assert.deepEqual(Object.keys(out.recipes), ["appliance1x1", "appliance1x2", "chair"]);
});

test("a project written before the rule loses its output and prefix on save", () => {
    const old = { ...project(), output: "recipe-test", workflow_prefix: "dev-" };
    const out = tableToProject(old, projectToTable(old, slots), slots);
    assert.equal("output" in out, false);
    assert.equal("workflow_prefix" in out, false);
});

test("a bad cell names its row and column", () => {
    const r = project();
    const table = projectToTable(r, slots);
    table.rows.find((x) => x.key === "pre_flip").cells.appliance1x2 = "maybe";
    assert.throws(() => tableToProject(r, table, slots), /pre_flip.*appliance1x2/);
});

test("the generate toast names every file written and where edits belong", () => {
    const { summary, detail } = generateSummary({
        template: "recipe-test/bakery-template.json",
        written: [{ path: "recipe-test/dev-imperia-bakery-appliance1x1.json" },
                  { path: "recipe-test/dev-imperia-bakery-appliance1x2.json" }],
    });
    assert.equal(summary, "Wrote 2 workflows from recipe-test/bakery-template.json");
    assert.match(detail, /appliance1x1\.json, recipe-test\/dev-imperia-bakery-appliance1x2\.json\./);
    assert.match(detail, /Edits belong in the template or the recipe/);
    assert.equal(generateSummary({ template: "t.json", written: [] }).detail, "The project has no recipes.");
});

test("the summary names the files the old naming left behind", () => {
    const { detail } = generateSummary({
        template: "base_example.json",
        written: [{ path: "base-example-appliance1x2.json", recipe: "appliance1x2" }],
        stale: ["appliance1x2.json"],
    });
    assert.match(detail, /Left from the old naming and no longer written: appliance1x2\.json\./);
    assert.match(detail, /go on holding the graph they froze with/);
    assert.doesNotMatch(
        generateSummary({ template: "t.json", written: [], stale: [] }).detail, /Left from/);
});

test("the summary names the values the template had no slot for", () => {
    const { summary, detail } = generateSummary({
        template: "t.json",
        written: [{ path: "a.json", recipe: "appliance1x1", ignored: ["control_image"] },
                  { path: "b.json", recipe: "table", ignored: [] },
                  { path: "c.json", recipe: "cashier-desk1x1", ignored: ["control_image", "format"] }],
    });
    assert.equal(summary, "Wrote 3 workflows from t.json");
    assert.match(detail, /Ignored, no slot in the template: control_image \(appliance1x1, cashier-desk1x1\), format \(cashier-desk1x1\)\./);
    assert.doesNotMatch(generateSummary({ template: "t.json", written: [{ path: "b.json", recipe: "table", ignored: [] }] }).detail, /Ignored/);
});

import { captureColumn } from "../../web/js/recipes.js";

test("capturing the canvas into a category writes only what differs from the game column", () => {
    const r = project();
    const table = projectToTable(r, slots);
    const live = { control_image: "b.png", grid: [2, 1], strength: 0.5, pre_flip: true,
                   render: { lora_name: "bakery.safetensors" } };
    // game has render = bakery.safetensors already; strength and grid have no game value
    captureColumn(table, slots, "appliance1x2", live);
    const cells = Object.fromEntries(table.rows.map((row) => [row.key, row.cells.appliance1x2]));
    assert.equal(cells.control_image, "b.png");
    assert.equal(cells.render, "");            // same as game
    assert.equal(cells.pre_flip, "true");
    assert.equal(cells.grid, "[2, 1]");
    assert.equal(cells.strength, "0.5");
});

test("capturing into a column that does not exist adds it, and into game writes everything", () => {
    const r = project();
    const table = projectToTable(r, slots);
    captureColumn(table, slots, "chair", { control_image: "chair.png" });
    assert.deepEqual(table.columns, ["shared", "appliance1x1", "appliance1x2", "chair"]);
    assert.equal(table.rows.find((x) => x.key === "control_image").cells.chair, "chair.png");
    captureColumn(table, slots, "shared", { control_image: "g.png", render: { lora_name: "bakery.safetensors" } });
    assert.equal(table.rows.find((x) => x.key === "control_image").cells.shared, "g.png");
    assert.equal(table.rows.find((x) => x.key === "render").cells.shared, '{"lora_name": "bakery.safetensors"}');
});

test("a slot the canvas did not report keeps its cell", () => {
    const r = project();
    const table = projectToTable(r, slots);
    captureColumn(table, slots, "appliance1x1", { pre_flip: true });
    assert.equal(table.rows.find((x) => x.key === "control_image").cells.appliance1x1, "a.png");
    assert.equal(table.rows.find((x) => x.key === "pre_flip").cells.appliance1x1, "true");
});

import { applyValuesToNodes, columnValues } from "../../web/js/recipes.js";

test("a column's values are its own cells over the game column, parsed", () => {
    const r = project();
    const table = projectToTable(r, slots);
    assert.deepEqual(columnValues(table, slots, "appliance1x2"),
        { render: { lora_name: "bakery.safetensors" }, control_image: "b.png", pre_flip: true, strength: 0.7 });
    assert.deepEqual(columnValues(table, slots, "shared"), { render: { lora_name: "bakery.safetensors" } });
});

function liveNode(title, widgets, extra = {}) {
    return { title, mode: 0, widgets: widgets.map(([name, value]) => ({ name, value })), inputs: [], ...extra };
}

test("loading values onto the canvas sets widgets, modes and promoted widgets by name", () => {
    const image = liveNode("recipe:control_image", [["image", "old.png"], ["upload", "image"]]);
    const grid = liveNode("recipe:grid", [["columns", 2], ["rows", 3]]);
    const flip = liveNode("recipe:pre_flip?", [["flip_method", "y-axis: horizontally"]], { mode: 4 });
    const render = liveNode("recipe:render", [["seed", 7], ["lora_name", "old.safetensors"], ["strength_model", 0.5]],
        { isSubgraphNode: () => true });
    const other = liveNode("User Custom Request", [["String", "leave me"]]);
    const report = applyValuesToNodes([image, grid, flip, render, other], {
        control_image: "b.png", grid: [2, 1], pre_flip: true,
        render: { lora_name: "bakery.safetensors" }, missing: "x",
    });
    assert.equal(image.widgets[0].value, "b.png");
    assert.equal(image.widgets[1].value, "image");
    assert.deepEqual(grid.widgets.map((w) => w.value), [2, 1]);
    assert.equal(flip.mode, 0);
    assert.equal(render.widgets[1].value, "bakery.safetensors");
    assert.equal(render.widgets[0].value, 7);
    assert.equal(other.widgets[0].value, "leave me");
    assert.deepEqual(report, { applied: ["control_image", "grid", "pre_flip", "render"], missing: ["missing"] });
});

import { dictCellUpdate } from "../../web/js/recipes.js";

test("a subgraph row edits one widget at a time inside its JSON cell", () => {
    assert.equal(dictCellUpdate("", "lora_name", "a.safetensors"), '{"lora_name": "a.safetensors"}');
    assert.equal(dictCellUpdate('{"lora_name": "a"}', "strength_model", "0.9"), '{"lora_name": "a", "strength_model": 0.9}');
    assert.equal(dictCellUpdate('{"lora_name": "a"}', "value", "true"), '{"lora_name": "a", "value": true}');
    assert.equal(dictCellUpdate('{"lora_name": "a", "strength_model": 0.9}', "strength_model", ""), '{"lora_name": "a"}');
    assert.equal(dictCellUpdate('{"lora_name": "a"}', "lora_name", ""), "");
    assert.equal(dictCellUpdate("not json", "x", "1"), '{"x": 1}');
});

import { recipeSlug } from "../../web/js/recipes.js";

test("a recipe name is a lowercase file-name suffix: apostrophes dropped, the rest dashed", () => {
    assert.equal(recipeSlug("Cashier's Desk 1x1"), "cashiers-desk-1x1");
    assert.equal(recipeSlug("  Appliance 1×2 "), "appliance-1-2");
    assert.equal(recipeSlug("bakery-Cashier's Desk-1x2"), "bakery-cashiers-desk-1x2");
    assert.equal(recipeSlug("appliance1x2"), "appliance1x2");
    assert.equal(recipeSlug("''"), "");
});

test("recipe sections come sorted by name after shared, however they were captured", () => {
    const p = project();
    p.recipes = { zebra: {}, appliance1x1: {}, "cashier-desk1x1": {} };
    assert.deepEqual(projectToTable(p, slots).columns, ["shared", "appliance1x1", "cashier-desk1x1", "zebra"]);
    const table = projectToTable(project(), slots);
    captureColumn(table, slots, "aaa", { control_image: "a.png" });
    assert.deepEqual(table.columns, ["shared", "aaa", "appliance1x1", "appliance1x2"]);
});

import { autoAdopt, autoDecision, resolveText } from "../../web/js/recipes.js";

// A live-graph stand-in: nodes by id, links by id as {origin_id, origin_slot}.
function graphOf(nodes, links) {
    return { links, getNodeById: (id) => nodes.find((n) => n.id === id) ?? null };
}
const strNode = (id, value, type = "String") => ({ id, type, inputs: [{ name: "String", widget: { name: "String" } }],
    widgets: [{ name: "String", value }], outputs: [{ name: "STRING" }] });

test("a wired recipe name is read live through string, join and asset-focus nodes", () => {
    const focus = { id: 1, type: "SymbioticaAssetFocus", inputs: [], widgets: [{ name: "category", value: "Counter" }, { name: "asset", value: "X" }],
        outputs: [{ name: "asset_name" }, { name: "category" }] };
    const plot = strNode(2, "1x1");
    const join = { id: 3, type: "JoinStringMulti", widgets: [{ name: "inputcount", value: 2 }, { name: "delimiter", value: "" }],
        inputs: [{ name: "string_1", link: 10 }, { name: "string_2", link: 11 }, { name: "inputcount", widget: { name: "inputcount" } }],
        outputs: [{ name: "string" }] };
    const recipes = { id: 4, type: "SymbioticaRecipe", inputs: [{ name: "project", widget: { name: "project" } }, { name: "recipe", link: 12, widget: { name: "recipe" } }],
        widgets: [{ name: "project", value: "p" }, { name: "recipe", value: "" }] };
    const graph = graphOf([focus, plot, join, recipes], {
        10: { origin_id: 1, origin_slot: 1 }, 11: { origin_id: 2, origin_slot: 0 }, 12: { origin_id: 3, origin_slot: 0 },
    });
    assert.equal(resolveText(graph, recipes, "recipe"), "Counter1x1");
});

test("join strings uses its delimiter and a typed value is read as is", () => {
    const a = strNode(1, "a"), b = strNode(2, "b");
    const join = { id: 3, type: "JoinStrings", widgets: [{ name: "delimiter", value: "-" }],
        inputs: [{ name: "string1", link: 10 }, { name: "string2", link: 11 }, { name: "delimiter", widget: { name: "delimiter" } }], outputs: [{ name: "STRING" }] };
    const target = { id: 4, type: "SymbioticaRecipe", inputs: [{ name: "recipe", link: 12, widget: { name: "recipe" } }], widgets: [{ name: "recipe", value: "typed" }] };
    const graph = graphOf([a, b, join, target], { 10: { origin_id: 1, origin_slot: 0 }, 11: { origin_id: 2, origin_slot: 0 }, 12: { origin_id: 3, origin_slot: 0 } });
    assert.equal(resolveText(graph, target, "recipe"), "a-b");
    const typed = { id: 5, type: "SymbioticaRecipe", inputs: [{ name: "recipe", link: null, widget: { name: "recipe" } }], widgets: [{ name: "recipe", value: "typed" }] };
    assert.equal(resolveText(graph, typed, "recipe"), "typed");
});

test("a recipe name arriving through KJNodes Set/Get is read off the Set's input", () => {
    const focus = { id: 1, type: "SymbioticaAssetFocus", inputs: [], widgets: [{ name: "category", value: "Appliance 1x1" }],
        outputs: [{ name: "asset_name" }, { name: "category" }, { name: "client_prompt" }, { name: "category_recipe" }] };
    const set = { id: 2, type: "SetNode", widgets: [{ name: "Constant", value: "category_recipe" }],
        inputs: [{ name: "STRING", link: 10 }], outputs: [{ name: "*" }] };
    const get = { id: 3, type: "GetNode", widgets: [{ name: "Constant", value: "category_recipe" }],
        inputs: [], outputs: [{ name: "*" }] };
    const target = { id: 4, type: "SymbioticaRecipe", inputs: [{ name: "recipe", link: 11, widget: { name: "recipe" } }],
        widgets: [{ name: "recipe", value: "" }] };
    const nodes = [focus, set, get, target];
    const graph = { ...graphOf(nodes, { 10: { origin_id: 1, origin_slot: 3 }, 11: { origin_id: 3, origin_slot: 0 } }), nodes };
    assert.equal(resolveText(graph, target, "recipe"), "Appliance 1x1");
    // A Get whose Set is gone, and an unnamed one, name nothing.
    get.widgets[0].value = "gone";
    assert.equal(resolveText(graph, target, "recipe"), null);
    get.widgets[0].value = "";
    assert.equal(resolveText(graph, target, "recipe"), null);
});

test("a recipe name arriving through a hub is read off the slot it left", () => {
    // Same hop as the KJ pair, except the name rides on the OUTPUT slot the
    // wire left: one hub stands in for twenty pairs, and slot 0 is one of them.
    const focus = { id: 1, type: "SymbioticaAssetFocus", inputs: [],
        widgets: [{ name: "category", value: "Appliance 1x1" }],
        outputs: [{ name: "asset_name" }, { name: "category" },
                  { name: "client_prompt" }, { name: "category_recipe" }] };
    const plot = strNode(2, "not this one");
    const set = { id: 3, type: "SymbioticaSetHub", widgets: [],
        inputs: [{ name: "plot", label: "plot", link: 10 },
                 { name: "category_recipe", label: "category_recipe", link: 11 },
                 { name: "+", type: "*", link: null }], outputs: [] };
    const get = { id: 4, type: "SymbioticaGetHub", widgets: [], inputs: [],
        outputs: [{ name: "plot", label: "plot" },
                  { name: "category_recipe", label: "category_recipe" },
                  { name: "+", type: "*" }] };
    const target = { id: 5, type: "SymbioticaRecipe",
        inputs: [{ name: "recipe", link: 12, widget: { name: "recipe" } }],
        widgets: [{ name: "recipe", value: "" }] };
    const nodes = [focus, plot, set, get, target];
    const graph = { ...graphOf(nodes, {
        10: { origin_id: 2, origin_slot: 0 },
        11: { origin_id: 1, origin_slot: 3 },
        12: { origin_id: 4, origin_slot: 1 } }), nodes };
    assert.equal(resolveText(graph, target, "recipe"), "Appliance 1x1");
    // The other slot is the other constant, not the same answer twice.
    graph.links[12].origin_slot = 0;
    assert.equal(resolveText(graph, target, "recipe"), "not this one");
    // A slot pointing at a name nothing publishes names nothing.
    get.outputs[0].label = "gone";
    assert.equal(resolveText(graph, target, "recipe"), null);
});

test("a node the resolver does not understand yields null, never a guess", () => {
    const llm = { id: 1, type: "SymbioticaClaude", inputs: [{ name: "prompt", link: null, widget: { name: "prompt" } }], widgets: [{ name: "prompt", value: "hi" }], outputs: [{ name: "text" }] };
    const target = { id: 2, type: "SymbioticaRecipe", inputs: [{ name: "recipe", link: 10, widget: { name: "recipe" } }], widgets: [{ name: "recipe", value: "" }] };
    const graph = graphOf([llm, target], { 10: { origin_id: 1, origin_slot: 0 } });
    assert.equal(resolveText(graph, target, "recipe"), null);
});

test("a node brought to the front is not an edit", async () => {
    const { slotSignature } = await import("../../web/js/recipes.js");
    // Clicking or resizing a node moves it to the end of the canvas's list,
    // which is the order the slot values are read in. Same values, same
    // answer -- or auto saves the recipe on every click.
    const before = { KSampler: { seed: 2 }, "Prompts (Symbiotica)": { text: "a, b" },
                     "Control Image": "door.png" };
    const after = { KSampler: { seed: 2 }, "Control Image": "door.png",
                    "Prompts (Symbiotica)": { text: "a, b" } };
    assert.equal(slotSignature(before), slotSignature(after));
    assert.notEqual(slotSignature(before),
                    slotSignature({ ...after, "Control Image": "wall.png" }));
});

test("auto adopts the canvas it opens on instead of writing the recipe over it", () => {
    const columns = ["shared", "counter1x1"];
    // Nothing remembered yet: the canvas is what was saved with the workflow.
    assert.equal(autoAdopt({ name: null, sig: null }, "counter1x1", columns), true);
    // A name with no recipe is created from the canvas, not adopted.
    assert.equal(autoAdopt({ name: null, sig: null }, "chair1x1", columns), false);
    assert.equal(autoAdopt({ name: null, sig: null }, "", columns), false);
    // Once auto knows where it is, a switch loads as before.
    assert.equal(autoAdopt({ name: "counter1x1", sig: "x" }, "chair1x1", columns), false);
});

test("auto decides: save the recipe you leave, then load an existing one or create a new one", () => {
    const columns = ["shared", "counter1x1"];
    assert.deepEqual(autoDecision({ name: "counter1x1", changed: true }, "chair1x1", columns), ["save:counter1x1", "create:chair1x1"]);
    assert.deepEqual(autoDecision({ name: "chair1x1", changed: false }, "counter1x1", columns), ["load:counter1x1"]);
    assert.deepEqual(autoDecision({ name: "counter1x1", changed: true }, "counter1x1", columns), ["save:counter1x1"]);
    assert.deepEqual(autoDecision({ name: "counter1x1", changed: false }, "counter1x1", columns), []);
    assert.deepEqual(autoDecision({ name: null, changed: false }, "counter1x1", columns), ["load:counter1x1"]);
    assert.deepEqual(autoDecision({ name: "counter1x1", changed: true }, "", columns), ["save:counter1x1"]);
});

test("a recipe writes rgthree's groups off-first, so a max-one node lands on what was recorded", () => {
    const calls = [];
    const row = (title, toggled) => ({
        name: "RGTHREE_TOGGLE_AND_NAV", value: { toggled }, group: { title },
        toggle(v) { calls.push([title, v]); this.value.toggled = v; },
    });
    const muter = { title: "Fast Groups Muter (rgthree)", color: "#323", bgcolor: "#535",
        widgets: [row("render-engine-nano2", false), row("render-engine-qwen", true)] };
    const report = applyValuesToNodes([muter], {
        "Fast Groups Muter (rgthree)": { "render-engine-nano2": true, "render-engine-qwen": false },
    }, "purple");
    assert.deepEqual(report.applied, ["Fast Groups Muter (rgthree)"]);
    assert.deepEqual(calls, [["render-engine-qwen", false], ["render-engine-nano2", true]]);
});

import { projectForWorkflow } from "../../web/js/recipes.js";

test("the project is the one whose template is the open workflow", () => {
    const projects = [{ name: "imperia-bakery", template: "recipe-test/bakery-template-test.json" },
                      { name: "imperia-restaurant", template: "restaurant/base.json" }];
    assert.equal(projectForWorkflow(projects, "workflows/recipe-test/bakery-template-test.json"), "imperia-bakery");
    assert.equal(projectForWorkflow(projects, "recipe-test/bakery-template-test.json"), "imperia-bakery");
    assert.equal(projectForWorkflow(projects, "workflows/recipe-test/dev-imperia-counter1x1.json"), null);
    assert.equal(projectForWorkflow(projects, null), null);
});

test("asset focus's category_recipe output is the picked label, and category the plain name", () => {
    const focus = { id: 1, type: "SymbioticaAssetFocus", inputs: [], widgets: [{ name: "category", value: "Appliance 1x2" }],
        outputs: [{ name: "asset_name" }, { name: "category" }, { name: "client_prompt" }, { name: "category_recipe" }] };
    const target = (slot) => ({ id: 2, type: "SymbioticaRecipe", inputs: [{ name: "recipe", link: 10, widget: { name: "recipe" } }], widgets: [{ name: "recipe", value: "" }],
        _slot: slot });
    const graphFor = (slot) => graphOf([focus, target(slot)], { 10: { origin_id: 1, origin_slot: slot } });
    assert.equal(resolveText(graphFor(3), target(3), "recipe"), "Appliance 1x2");
    assert.equal(resolveText(graphFor(1), target(1), "recipe"), "Appliance");
    focus.widgets[0].value = "All";
    assert.equal(resolveText(graphFor(3), target(3), "recipe"), null);
});

// Picking an asset EMPTIES the category (`chooseAsset`, asset_focus.js): with a
// name chosen the narrowing decides nothing, and a stale one is a hard refusal
// at queue time. The recipe still has to be named, or the Recipes node stores
// nothing for the asset he just picked.
const GARGOYLE = () => ([
    { name: "category", value: "" },
    { name: "asset", value: "Gargoyle Drink Machine" },
    { name: "feature", value: "QE 2 — Coven of Shadows" },
]);
const EVENTS = () => ([{ feature: "QE 2 — Coven of Shadows", assets: [
    { assetName: "Gargoyle Drink Machine", category: "Appliance", canvas: "128x256" },
    { assetName: "Spider Mosaic Counter", category: "Counter", canvas: "128x128" }] }]);
const FOCUS_OUTS = [{ name: "asset_name" }, { name: "category" },
                    { name: "client_prompt" }, { name: "category_recipe" }];

test("an asset picked with no category names the recipe from the asset's own row", () => {
    const focus = { id: 1, type: "SymbioticaAssetFocus", inputs: [],
                    widgets: GARGOYLE(), _symEvents: EVENTS(), outputs: FOCUS_OUTS };
    const target = (slot) => ({ id: 2, type: "SymbioticaRecipe",
        inputs: [{ name: "recipe", link: 10, widget: { name: "recipe" } }],
        widgets: [{ name: "recipe", value: "" }] });
    const graphFor = (slot) => graphOf([focus, target(slot)],
                                       { 10: { origin_id: 1, origin_slot: slot } });
    assert.equal(resolveText(graphFor(3), target(3), "recipe"), "Appliance 1x2");
    assert.equal(resolveText(graphFor(1), target(1), "recipe"), "Appliance");
    // A category typed by hand still wins over the asset's own.
    focus.widgets[0].value = "Counter 1x1";
    assert.equal(resolveText(graphFor(3), target(3), "recipe"), "Counter 1x1");
    // A name the order does not hold names nothing, rather than guessing.
    focus.widgets[0].value = "";
    focus.widgets[1].value = "Not In The Order";
    assert.equal(resolveText(graphFor(3), target(3), "recipe"), null);
    // And neither does an empty node: no category, no asset, no order.
    focus.widgets[1].value = "";
    assert.equal(resolveText(graphFor(3), target(3), "recipe"), null);
});

test("Task Specs answers the same way — the Task feeding it holds the asset", () => {
    const task = { id: 1, type: "SymbioticaTask", inputs: [],
                   widgets: GARGOYLE(), _symEvents: EVENTS(),
                   outputs: [{ name: "specs" }] };
    const NAMES = ["asset_name", "category", "client_prompt", "save_path", "order",
                   "event_order", "bucket", "ref_image", "ref_mask", "ref_name",
                   "category_recipe", "width", "height"];
    const specs = { id: 2, type: "SymbioticaTaskSpecs",
                    inputs: [{ name: "specs", link: 6 }],
                    outputs: NAMES.map((name) => ({ name })) };
    const target = { id: 3, type: "SymbioticaRecipe",
        inputs: [{ name: "recipe", link: 10, widget: { name: "recipe" } }],
        widgets: [{ name: "recipe", value: "" }] };
    const graphFor = (slot) => graphOf([task, specs, target], {
        6: { origin_id: 1, origin_slot: 0 },
        10: { origin_id: 2, origin_slot: slot },
    });
    assert.equal(resolveText(graphFor(10), target, "recipe"), "Appliance 1x2");
    assert.equal(resolveText(graphFor(1), target, "recipe"), "Appliance");
    task.widgets[1].value = "Spider Mosaic Counter";
    assert.equal(resolveText(graphFor(10), target, "recipe"), "Counter 1x1");
});

import { liveSlots, retable } from "../../web/js/recipes.js";

const canvas = () => ({ nodes: [
    { title: "recipe:render", isSubgraphNode: () => true,
      inputs: [{ name: "lora_name", widget: { name: "lora_name" }, link: null },
               { name: "seed", widget: { name: "seed" }, link: 3 }],
      widgets: [{ name: "lora_name", value: "x.safetensors" }, { name: "seed", value: 1 }] },
    { title: "recipe:pre_flip?", mode: 4, widgets: [] },
    { title: "recipe:control_image", widgets: [{ name: "image", value: "a.png" }, { name: "upload", type: "button" }] },
    { title: "recipe:grid", widgets: [{ name: "columns", value: 2 }, { name: "rows", value: 1 }] },
    { title: "Load Image", widgets: [{ name: "image", value: "b.png" }] },
] });

test("the canvas describes its own slots the way the saved template does, in key order", () => {
    assert.deepEqual(liveSlots(canvas()), [
        { key: "control_image", kind: "scalar", default: "a.png", widgets: 1 },
        // Every widget, not the first: a recipe is the whole node.
        { key: "grid", kind: "dict", default: { columns: 2, rows: 1 }, widgets: 2 },
        { key: "pre_flip", kind: "toggle", default: false, widgets: 0 },
        // `seed` arrives on a wire, so it is neither counted nor recorded.
        { key: "render", kind: "dict", default: { lora_name: "x.safetensors" }, widgets: 1 },
    ]);
    assert.deepEqual(liveSlots({ nodes: [] }), []);
});

test("re-tabling on a slot change keeps unsaved cells, adds the new slot and drops the gone one", () => {
    const table = projectToTable(project(), slots);
    table.rows.find((row) => row.key === "strength").cells.appliance1x1 = "0.9";
    const renamed = slots.filter((s) => s.key !== "control_image")
        .concat([{ key: "controlnet", kind: "scalar", default: "floor.png", widgets: 1 }]);
    const next = retable(table, renamed);
    assert.deepEqual(next.rows.map((row) => row.key), ["grid", "strength", "pre_flip", "render", "controlnet"]);
    assert.equal(next.rows.find((row) => row.key === "strength").cells.appliance1x1, "0.9");
});

test("a cell that does not parse still lets a newly painted node become a row", () => {
    const table = projectToTable(project(), slots);
    table.rows.find((row) => row.key === "render").cells.shared = "{not json";
    const next = retable(table, slots.concat([{ key: "backdrop", kind: "scalar", default: "", widgets: 1 }]));
    assert.ok(next.rows.some((row) => row.key === "backdrop"));
    assert.equal(next.rows.find((row) => row.key === "render").cells.shared, "{not json");
});

import { colorMatcher, slotKey } from "../../web/js/recipes.js";

const painted = (title, color = "#323", bgcolor = "#535", extra = {}) =>
    ({ title, color, bgcolor, widgets: [], ...extra });

test("a painted node is a slot named by its title", () => {
    const matches = colorMatcher("purple");
    assert.equal(slotKey(painted("llm-prompt"), matches), "llm-prompt");
    assert.equal(slotKey(painted("pre_flip?"), matches), "pre_flip");
    assert.equal(slotKey(painted("llm-prompt", "#232", "#353"), matches), null);
    assert.equal(slotKey({ title: "llm-prompt" }, matches), null);
});

test("painting is the whole of it: a node never retitled is a slot under its type's name", () => {
    const node = painted("Prompts");
    node.constructor = { title: "Prompts" };
    assert.equal(slotKey(node, colorMatcher("purple")), "Prompts");
    // Nothing on the node at all but the paint still names it.
    assert.equal(slotKey({ title: "", type: "KSampler", color: "#323", bgcolor: "#535" },
        colorMatcher("purple")), "KSampler");
    // Unpainted stays unpainted.
    assert.equal(slotKey({ title: "KSampler" }, colorMatcher("purple")), null);
});

test("the recipe: prefix marks a slot whatever the colour, and is dropped from a painted one", () => {
    assert.equal(slotKey({ title: "recipe:grid" }, colorMatcher("purple")), "grid");
    assert.equal(slotKey({ title: "recipe:grid" }, null), "grid");
    assert.equal(slotKey({ title: "grid" }, null), null);
    assert.equal(slotKey(painted("recipe:grid"), colorMatcher("purple")), "grid");
});

test("a hex matches, a lighter shade of the same hue matches, another palette colour does not", () => {
    assert.ok(colorMatcher("#535")(painted("x")));
    assert.ok(colorMatcher("purple")(painted("x", "#9b7f9b", "#b39bb3")));
    assert.ok(colorMatcher("pale blue")({ bgcolor: "#3f5159" }));
    assert.ok(!colorMatcher("cyan")({ bgcolor: "#3f5159" }));
    assert.equal(colorMatcher(""), null);
    assert.equal(colorMatcher("chartreuse"), null);
});

test("the canvas describes painted slots the way it describes titled ones", () => {
    const nodes = canvas().nodes.map((n) => (n.title.startsWith("recipe:")
        ? { ...n, title: n.title.slice("recipe:".length), color: "#323", bgcolor: "#535" }
        : n));
    assert.deepEqual(liveSlots({ nodes }, "purple"), liveSlots(canvas()));
    assert.deepEqual(liveSlots({ nodes }, ""), []);
});

// rgthree's Fast Group Bypasser: every row widget carries the SAME name and a
// `{toggled}` value, so the group title is the only thing that tells two rows
// apart, and `.value = ` is inert -- `toggle(bool)` moves the group.
function groupBypasser(title, groups) {
    const widgets = groups.map(([name, on]) => ({
        name: "RGTHREE_TOGGLE_AND_NAV", type: "custom", label: `Enable ${name}`,
        group: { title: name }, value: { toggled: on },
        toggle(v) { this.value.toggled = v; this.moved = true; },
    }));
    // painted the match colour, which is what makes it a slot
    return { title, mode: 0, widgets, inputs: [], color: "#323", bgcolor: "#535" };
}

test("a fast group bypasser is one row per group, not the first group's toggled", () => {
    const node = groupBypasser("$$render-engine", [
        ["render-engine-nano2", true], ["render-engine-qwen-t2i-ctrlnet-lora", false]]);
    assert.deepEqual(liveSlots({ nodes: [node] }, "purple"), [{
        key: "$$render-engine", kind: "dict", widgets: 2,
        default: { "render-engine-nano2": true, "render-engine-qwen-t2i-ctrlnet-lora": false },
    }]);
});

test("loading a fast group bypasser's row toggles the group instead of setting a dead value", () => {
    const node = groupBypasser("$$render-engine", [
        ["render-engine-nano2", true], ["render-engine-qwen-t2i-ctrlnet-lora", false]]);
    const report = applyValuesToNodes([node], {
        "$$render-engine": { "render-engine-nano2": false,
                             "render-engine-qwen-t2i-ctrlnet-lora": true },
    }, "purple");
    assert.deepEqual(node.widgets.map((w) => w.value.toggled), [false, true]);
    assert.deepEqual(node.widgets.map((w) => w.moved), [true, true]);
    assert.deepEqual(report.applied, ["$$render-engine"]);
});

test("a Prompts slot captures folder, file and text, and leaves the wired path out", () => {
    const node = {
        title: "recipe:LLM-prompt", mode: 0, color: "#323", bgcolor: "#535",
        inputs: [{ name: "path", widget: { name: "path" }, link: 7 }],
        widgets: [{ name: "path", value: "" }, { name: "folder", value: "llm-prompts" },
                  { name: "new folder", type: "button" },
                  { name: "file", value: "llm-sp-chair.md" },
                  { name: "save file", type: "button" },
                  { name: "text", value: "SYSTEM PROMPT" }],
    };
    assert.deepEqual(liveSlots({ nodes: [node] }, "purple"), [{
        // Three: the wired `path` is not a widget a recipe may set.
        key: "LLM-prompt", kind: "dict", widgets: 3,
        default: { folder: "llm-prompts", file: "llm-sp-chair.md", text: "SYSTEM PROMPT" },
    }]);
});

test("loading a Prompts slot sets its widgets and tells the panel to re-read", () => {
    let refreshed = 0;
    const node = {
        title: "recipe:LLM-prompt", mode: 0, color: "#323", bgcolor: "#535",
        inputs: [{ name: "path", widget: { name: "path" }, link: 7 }],
        widgets: [{ name: "path", value: "" }, { name: "folder", value: "llm-prompts" },
                  { name: "file", value: "old.md" }, { name: "text", value: "OLD" }],
        _symRefreshPrompts: () => { refreshed += 1; },
    };
    applyValuesToNodes([node], {
        "LLM-prompt": { folder: "llm-prompts", file: "llm-sp-chair.md", text: "NEW" },
    }, "purple");
    assert.deepEqual(node.widgets.map((w) => w.value),
                     ["", "llm-prompts", "llm-sp-chair.md", "NEW"]);
    assert.equal(refreshed, 1);
});

// ---------------------------------------------------------------------------
// His `$$controlnet-image` on 2026-09-21: a Control Image node painted as a
// slot, its `path` wired and its own DOM panel in `node.widgets`. The panel is
// not a setting, and counting it made the canvas call the slot a `dict` while
// the server called it a `scalar` — the project file the server had seeded was
// then refused by the panel on open, and every save with it.
import { dictRow } from "../../web/js/recipes.js";

test("a node's own panel is not one of its settings", () => {
    const node = {
        title: "$$controlnet-image", mode: 0, color: "#323", bgcolor: "#535",
        inputs: [{ name: "image", widget: { name: "image" }, link: null },
                 { name: "path", widget: { name: "path" }, link: 5553 }],
        widgets: [{ name: "image", value: "general/1x1/1x1-box.png" },
                  { name: "path", value: "" },
                  { name: "images_panel", value: undefined,
                    options: { serialize: false, hideOnZoom: true } }],
    };
    assert.deepEqual(liveSlots({ nodes: [node] }, "purple"), [{
        key: "$$controlnet-image", kind: "scalar", widgets: 1,
        default: "general/1x1/1x1-box.png",
    }]);
});

test("a display-only widget is not a setting either", () => {
    // Studio Library draws what it holds in a `text` widget the workflow never
    // saves (`widget.serialize = false`), beside the browse button.
    const node = {
        title: "path-project", mode: 0, color: "#323", bgcolor: "#535",
        inputs: [{ name: "selection", widget: { name: "selection" }, link: null }],
        widgets: [{ name: "selection", value: "studios/imperia/bakery" },
                  { name: "📂 Browse studio library", type: "button" },
                  { name: "studio_summary", value: "12 files", serialize: false }],
    };
    assert.deepEqual(liveSlots({ nodes: [node] }, "purple"), [{
        key: "path-project", kind: "scalar", widgets: 1,
        default: "studios/imperia/bakery",
    }]);
});

test("a cell holding plain text draws as text, whatever the slot's kind", () => {
    const slot = { key: "$$controlnet-image", kind: "dict", default: {} };
    // The sub-grid has no field for a bare string: drawn as a dict row, the
    // only copy of his value was on screen nowhere.
    assert.equal(dictRow(slot, "general/1x1/1x1-box.png", ""), false);
    assert.equal(dictRow(slot, '{"image": "x"}', ""), true);
    assert.equal(dictRow(slot, "", ""), true);
});
