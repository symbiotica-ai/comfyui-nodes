// ABOUTME: Tests for the order/reference template split in order_pipeline.js —
// ABOUTME: which pool the Library browses, and which pool a save says it targets.
import { test } from "node:test";
import assert from "node:assert/strict";

import { calls, create, link, reset, setResponder, fire } from "./comfy_stub.mjs";
import "../../web/js/order_pipeline.js";

const tick = () => new Promise((r) => setTimeout(r, 0));

function find(root, pred) {
    if (!root) return null;
    if (pred(root)) return root;
    for (const child of root.children ?? []) {
        const hit = find(child, pred);
        if (hit) return hit;
    }
    return null;
}

function findAll(root, pred, out = []) {
    if (!root) return out;
    if (pred(root)) out.push(root);
    for (const child of root.children ?? []) findAll(child, pred, out);
    return out;
}

const listCalls = () =>
    calls.filter((c) => c.startsWith("/symbiotica/pack-template-list"));

// Two templates that share a slug — one per pool. This is the case the split
// exists for: the same feature has a style guide AND a design guide.
const BOTH_POOLS = {
    templates: [
        { name: "food", key: "order/food", kind: "order", month: "October",
          sheetCount: 1, sheets: ["sheet-000.png"], sheetPaths: ["/p/o/food/sheet-000.png"],
          order: { feature: "Mini 1", assets: [] } },
        { name: "food", key: "reference/food", kind: "reference", month: "",
          sheetCount: 1, sheets: ["sheet-000.png"], sheetPaths: ["/p/r/food/sheet-000.png"],
          order: { feature: "Food", assets: [] } },
    ],
    dir: "/p/templates/reference",
};

async function library(widgets) {
    const node = await create("SymbioticaTemplateLibrary", {
        project_path: "/p", kind: "All", month: "", selected: "", checked: "[]",
        ...widgets,
    });
    node.onNodeCreated();
    for (let i = 0; i < 5; i++) await tick();
    return node;
}

const openOverlay = async (node) => {
    node.widgets.find((w) => w.name === "📂 Browse template library").callback();
    await tick();
    return document.body.children.at(-1);
};

test("the Library asks for the reference pool, month-free", async () => {
    reset();
    setResponder(() => ({ ok: true, body: BOTH_POOLS }));
    await library({ kind: "Reference", month: "October" });
    const [route] = listCalls();
    assert.ok(route, "expected a pack-template-list request");
    assert.match(route, /kind=reference/);
    // A reference template applies to every order — a month would be a lie.
    assert.ok(!route.includes("month="), `month leaked into ${route}`);
});

test("the Library scopes the order pool to its month", async () => {
    reset();
    setResponder(() => ({ ok: true, body: BOTH_POOLS }));
    await library({ kind: "Order", month: "October" });
    const [route] = listCalls();
    assert.match(route, /kind=order/);
    assert.match(route, /month=October/);
});

test("kind All asks for every pool", async () => {
    reset();
    setResponder(() => ({ ok: true, body: BOTH_POOLS }));
    await library({ kind: "All" });
    const [route] = listCalls();
    assert.ok(!route.includes("kind="), `All should not narrow: ${route}`);
});

test("switching pool re-lists", async () => {
    reset();
    setResponder(() => ({ ok: true, body: BOTH_POOLS }));
    const node = await library({ kind: "All" });
    const before = listCalls().length;
    const kindW = node.widgets.find((w) => w.name === "kind");
    kindW.value = "Reference";
    kindW.callback?.(kindW.value);
    for (let i = 0; i < 3; i++) await tick();
    const after = listCalls();
    assert.ok(after.length > before, "changing kind should re-list");
    assert.match(after.at(-1), /kind=reference/);
});

test("the same slug in both pools stays two rows, ticked by qualified id", async () => {
    reset();
    setResponder(() => ({ ok: true, body: BOTH_POOLS }));
    const node = await library({ kind: "All" });
    const overlay = await openOverlay(node);
    const labels = findAll(overlay, (n) => n.textContent === "📁  food");
    assert.equal(labels.length, 2, "expected one row per pool");
    // Both pools are named on screen, so the rows are tellable apart.
    assert.ok(find(overlay, (n) => n.textContent === "ref"), "no reference badge");
    assert.ok(find(overlay, (n) => n.textContent === "October"), "no order badge");

    const boxes = findAll(overlay, (n) => n.type === "checkbox");
    assert.equal(boxes.length, 2);
    boxes[1].checked = true;               // the reference row (sorted after order)
    fire(boxes[1], "click");
    const checked = JSON.parse(node.widgets.find((w) => w.name === "checked").value);
    assert.deepEqual(checked, ["reference/food"],
                     "the wire must carry the pool, not just the slug");
});

test("'use' puts the qualified id on the selected widget", async () => {
    reset();
    setResponder(() => ({ ok: true, body: BOTH_POOLS }));
    const node = await library({ kind: "All" });
    const overlay = await openOverlay(node);
    const useBtns = findAll(overlay, (n) => n.textContent === "use");
    assert.equal(useBtns.length, 2);
    fire(useBtns[0], "click");             // the order row
    assert.equal(node.widgets.find((w) => w.name === "selected").value, "order/food");
});

// --- the Auto Packer's save button names its destination pool ----------------

async function packerWith(sourceClass) {
    const src = await create(sourceClass, { project_path: "/p", month: "October" });
    const packer = await create("SymbioticaAutoPacker",
                                { category: "All", overrides: "{}", save_as: "" });
    link(src, packer, "order");
    packer.onNodeCreated();
    await tick();
    return packer;
}

const saveLabel = (packer) =>
    packer.widgets.find((w) => typeof w.name === "string" && w.name.includes("Save as")).name;

test("a Reference Browser source labels the save as a reference template", async () => {
    reset();
    setResponder(() => ({ ok: true, body: { events: [], refsRoot: "" } }));
    const packer = await packerWith("SymbioticaReferenceBrowser");
    assert.match(saveLabel(packer), /reference template/);
});

test("an Order Specs source labels the save as an order template", async () => {
    reset();
    setResponder(() => ({ ok: true, body: { events: [], refsRoot: "" } }));
    const packer = await packerWith("SymbioticaOrderSpecs");
    assert.match(saveLabel(packer), /order template/);
});

test("re-wiring the source re-labels the button", async () => {
    reset();
    setResponder(() => ({ ok: true, body: { events: [], refsRoot: "" } }));
    const packer = await create("SymbioticaAutoPacker",
                                { category: "All", overrides: "{}", save_as: "" });
    packer.onNodeCreated();
    await tick();
    assert.equal(saveLabel(packer), "💾 Save as template");   // nothing wired yet
    const browser = await create("SymbioticaReferenceBrowser", {});
    link(browser, packer, "order");
    packer.onConnectionsChange?.();
    assert.match(saveLabel(packer), /reference template/);
});
