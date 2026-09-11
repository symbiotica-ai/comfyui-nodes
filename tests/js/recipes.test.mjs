// ABOUTME: The Recipe node's table — cells are text, the recipe is JSON, and the
// ABOUTME: two must round-trip without a category losing or gaining a key.
import assert from "node:assert/strict";
import { test } from "node:test";

import "./comfy_stub.mjs";
import { cellText, cellValue, generateSummary, recipeToTable, tableToRecipe } from "../../web/js/recipes.js";

const slots = [
    { key: "control_image", kind: "scalar", default: "old.png", widgets: 2 },
    { key: "grid", kind: "scalar", default: 2, widgets: 2 },
    { key: "strength", kind: "scalar", default: 0.5, widgets: 1 },
    { key: "pre_flip", kind: "toggle", default: false, widgets: 1 },
    { key: "render", kind: "dict", default: { lora_name: "old.safetensors", strength_model: 0.5 }, widgets: 2 },
];

const recipe = () => ({
    template: "recipe-test/bakery-template.json", output: "recipe-test", workflow_prefix: "dev-imperia-bakery-",
    game: { render: { lora_name: "bakery.safetensors" } },
    categories: {
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
    const table = recipeToTable(recipe(), slots);
    assert.deepEqual(table.columns, ["game", "appliance1x1", "appliance1x2"]);
    assert.deepEqual(table.rows.map((r) => r.key), slots.map((s) => s.key));
    const grid = table.rows.find((r) => r.key === "grid");
    assert.deepEqual(grid.cells, { game: "", appliance1x1: "[2, 1]", appliance1x2: "" });
    const render = table.rows.find((r) => r.key === "render");
    assert.equal(render.cells.game, '{"lora_name": "bakery.safetensors"}');
});

test("a key a category carries that the template no longer has still gets a row, marked", () => {
    const r = recipe();
    r.categories.appliance1x1.gone = "x";
    const table = recipeToTable(r, slots);
    const row = table.rows.find((r) => r.key === "gone");
    assert.equal(row.orphan, true);
    assert.equal(row.cells.appliance1x1, "x");
});

test("the table writes back the recipe it was read from", () => {
    const r = recipe();
    const table = recipeToTable(r, slots);
    assert.deepEqual(tableToRecipe(r, table, slots), r);
});

test("edits land in the right column, empty cells drop the key, and a new column is a new category", () => {
    const r = recipe();
    const table = recipeToTable(r, slots);
    table.rows.find((x) => x.key === "control_image").cells.appliance1x2 = "c.png";
    table.rows.find((x) => x.key === "pre_flip").cells.appliance1x1 = "";
    table.columns.push("chair");
    table.rows.find((x) => x.key === "control_image").cells.chair = "chair.png";
    table.header = { template: "t.json", output: "out", workflow_prefix: "p-" };
    const out = tableToRecipe(r, table, slots);
    assert.equal(out.categories.appliance1x2.control_image, "c.png");
    assert.equal("pre_flip" in out.categories.appliance1x1, false);
    assert.deepEqual(out.categories.chair, { control_image: "chair.png" });
    assert.equal(out.template, "t.json");
    assert.equal(out.output, "out");
    assert.equal(out.workflow_prefix, "p-");
    assert.deepEqual(Object.keys(out.categories), ["appliance1x1", "appliance1x2", "chair"]);
});

test("a bad cell names its row and column", () => {
    const r = recipe();
    const table = recipeToTable(r, slots);
    table.rows.find((x) => x.key === "pre_flip").cells.appliance1x2 = "maybe";
    assert.throws(() => tableToRecipe(r, table, slots), /pre_flip.*appliance1x2/);
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
    assert.equal(generateSummary({ template: "t.json", written: [] }).detail, "The recipe has no categories.");
});
