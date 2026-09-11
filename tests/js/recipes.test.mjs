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

const project = () => ({
    template: "recipe-test/bakery-template.json", output: "recipe-test", workflow_prefix: "dev-imperia-bakery-",
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

test("a dict cell is a JSON object", () => {
    assert.deepEqual(cellValue(slots[4], '{"lora_name": "x"}'), { lora_name: "x" });
    assert.throws(() => cellValue(slots[4], "x.safetensors"), /render/);
    assert.throws(() => cellValue(slots[4], "[1]"), /render/);
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

test("a key a category carries that the template no longer has still gets a row, marked", () => {
    const r = project();
    r.recipes.appliance1x1.gone = "x";
    const table = projectToTable(r, slots);
    const row = table.rows.find((r) => r.key === "gone");
    assert.equal(row.orphan, true);
    assert.equal(row.cells.appliance1x1, "x");
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
    table.header = { template: "t.json", output: "out", workflow_prefix: "p-" };
    const out = tableToProject(r, table, slots);
    assert.equal(out.recipes.appliance1x2.control_image, "c.png");
    assert.equal("pre_flip" in out.recipes.appliance1x1, false);
    assert.deepEqual(out.recipes.chair, { control_image: "chair.png" });
    assert.equal(out.template, "t.json");
    assert.equal(out.output, "out");
    assert.equal(out.workflow_prefix, "p-");
    assert.deepEqual(Object.keys(out.recipes), ["appliance1x1", "appliance1x2", "chair"]);
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
