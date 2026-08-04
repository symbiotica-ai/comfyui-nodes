// ABOUTME: Asset Focus panel — the event's assets on the node body, and the
// ABOUTME: click that replaces a dozen index nodes held at the same position.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, fire, reset, tick } from "./comfy_stub.mjs";
import "../../web/js/asset_focus.js";

const ASSETS = [
    { name: "Frankencrisps", category: "Food - 3 stages" },
    { name: "Frankenstein Pops", category: "Food - 3 stages" },
    { name: "Bunting", category: "Decoration" },
];

async function focusNode(widgets = {}, assets = ASSETS) {
    reset();
    const node = await create("SymbioticaAssetFocus",
                              { order: null, category: "", asset: "", ...widgets });
    await node.onNodeCreated?.call(node);
    node._symFocusAssets = assets;
    node._symRenderFocus?.();
    for (let i = 0; i < 5; i++) await tick();
    return node;
}

const listOf = (node) =>
    node.widgets.find((w) => w.name === "focus_panel").element.children[0];

function walk(elem, out = []) {
    for (const child of elem.children ?? []) {
        out.push(child);
        walk(child, out);
    }
    return out;
}

const widgetOf = (node, name) => node.widgets.find((w) => w.name === name);
const rows = (node) => listOf(node).children.slice(1);

test("every asset in the event is listed", async () => {
    const node = await focusNode();
    assert.equal(rows(node).length, 3);
    assert.deepEqual(rows(node).map((r) => r.children[0].textContent),
                     ["Frankencrisps", "Frankenstein Pops", "Bunting"]);
});

test("clicking an asset writes it to the widget", async () => {
    // This click IS the index that used to be held by hand across a dozen
    // index nodes.
    const node = await focusNode();
    fire(rows(node)[1], "click");
    assert.equal(widgetOf(node, "asset").value, "Frankenstein Pops");
});

test("clicking the chosen one again clears it", async () => {
    // How you get back to "the first" without knowing what the first is called.
    const node = await focusNode({ asset: "Bunting" });
    const bunting = rows(node).find((r) => r.children[0].textContent === "Bunting");
    fire(bunting, "click");
    assert.equal(widgetOf(node, "asset").value, "");
});

test("the chosen asset is the one drawn as selected", async () => {
    const node = await focusNode({ asset: "Bunting" });
    const drawn = rows(node).map((r) => [r.children[0].textContent,
                                         !/opacity:\.75/.test(r.style.cssText)]);
    assert.deepEqual(drawn, [["Frankencrisps", false],
                             ["Frankenstein Pops", false],
                             ["Bunting", true]]);
});

test("before a run it says how to fill the list", async () => {
    // The order arrives on a wire the canvas cannot read.
    const node = await focusNode({}, []);
    const text = walk(listOf(node)).map((e) => e.textContent).join(" ");
    assert.match(text, /queue this node once/);
});

test("the category being narrowed to is shown", async () => {
    const node = await focusNode({ category: "Decoration" });
    assert.match(listOf(node).children[0].textContent
                 + walk(listOf(node).children[0]).map((e) => e.textContent).join(" "),
                 /Decoration/);
});

test("the extension registered", () => {
    assert.ok(app.extensions.some((e) => e.name === "symbiotica.asset_focus"));
});
