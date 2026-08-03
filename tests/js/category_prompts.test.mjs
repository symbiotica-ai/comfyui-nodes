// ABOUTME: The Category Prompts node must attach itself to the packer's
// ABOUTME: PER-SHEET type list — the wrong slot fails silently, not loudly.
import { test } from "node:test";
import assert from "node:assert/strict";

import { app, create, reset, tick } from "./comfy_stub.mjs";
import "../../web/js/order_pipeline.js";

// The packer's real output order. `categories` (deduped) sits immediately
// before `sheet_categories` (per-sheet), which is exactly why this is looked up
// by name and asserted here.
const PACKER_OUTPUTS = ["sheets", "sheet_prompts", "sheet_names", "categories",
                        "sheet_categories"];

async function packer(outputs = PACKER_OUTPUTS) {
    const n = await create("SymbioticaAutoPacker");
    n.outputs = outputs.map((name) => ({ name, links: [] }));
    app.graph._nodes = [...(app.graph._nodes ?? []), n];
    return n;
}

async function prompts() {
    const n = await create("SymbioticaCategoryPrompts", { project_path: "" });
    n.inputs = [{ name: "sheet_categories", link: null }];
    app.graph._nodes = [...(app.graph._nodes ?? []), n];
    await n.onNodeCreated?.call(n);
    await tick();
    return n;
}

test("attaches to sheet_categories, not the deduped categories beside it", async () => {
    reset();
    app.graph._nodes = [];
    const p = await packer();
    const node = await prompts();
    assert.equal(p.connected?.slot, 4, "must pick the per-sheet list");
    assert.equal(p.connected?.target, node);
    assert.equal(p.connected?.input, 0);
});

test("finds the slot by name, not by a hard-coded index", async () => {
    reset();
    app.graph._nodes = [];
    // A future packer with one more output ahead of sheet_categories: index 4
    // would now be the wrong wire, so the lookup must follow the name.
    const p = await packer(["sheets", "sheet_prompts", "sheet_names",
                            "categories", "sheet_guides", "sheet_categories"]);
    await prompts();
    assert.equal(p.connected?.slot, 5);
});

test("does not guess when two packers could be the source", async () => {
    reset();
    app.graph._nodes = [];
    const a = await packer();
    const b = await packer();
    await prompts();
    assert.equal(a.connected, undefined);
    assert.equal(b.connected, undefined);
});

test("leaves an already-wired input alone", async () => {
    reset();
    app.graph._nodes = [];
    const p = await packer();
    const n = await create("SymbioticaCategoryPrompts", { project_path: "" });
    n.inputs = [{ name: "sheet_categories", link: 99 }];   // user wired it
    app.graph._nodes = [...app.graph._nodes, n];
    await n.onNodeCreated?.call(n);
    await tick();
    assert.equal(p.connected, undefined);
});
