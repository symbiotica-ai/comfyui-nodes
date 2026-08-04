// ABOUTME: Asset Focus panel — the event's assets on the node body, and the
// ABOUTME: click that replaces a dozen index nodes held at the same position.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, fire, link, reset, tick } from "./comfy_stub.mjs";
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

test("the category being narrowed to is shown", async () => {
    const node = await focusNode({ category: "Decoration" });
    assert.match(listOf(node).children[0].textContent
                 + walk(listOf(node).children[0]).map((e) => e.textContent).join(" "),
                 /Decoration/);
});

test("the extension registered", () => {
    assert.ok(app.extensions.some((e) => e.name === "symbiotica.asset_focus"));
});

test("the assets appear from the wired source, with no run at all", async () => {
    // Nothing downstream is wired when the node is first dropped, so waiting
    // for a run means waiting forever.
    reset();
    const specs = await create("SymbioticaOrderSpecs", { feature: "Mini 3 — Franken-Feast" });
    specs.comfyClass = "SymbioticaOrderSpecs";
    specs._symEvents = [{ feature: "Mini 3", assets: [
        { assetName: "Frankencrisps", category: "Food - 3 stages" },
        { assetName: "Bunting", category: "Decoration" },
        { assetName: "", category: "Decoration" },
    ] }];
    const node = await create("SymbioticaAssetFocus",
                              { order: null, category: "", asset: "" });
    await node.onNodeCreated?.call(node);
    link(specs, node, "order");
    node._symRenderFocus();
    for (let i = 0; i < 5; i++) await tick();
    // The nameless row is spreadsheet padding, not an asset.
    assert.deepEqual(rows(node).map((r) => r.children[0].textContent),
                     ["Frankencrisps", "Bunting"]);
});

test("the category widget narrows the published list too", async () => {
    reset();
    const specs = await create("SymbioticaOrderSpecs", { feature: "Mini 3" });
    specs.comfyClass = "SymbioticaOrderSpecs";
    specs._symEvents = [{ feature: "Mini 3", assets: [
        { assetName: "Frankencrisps", category: "Food - 3 stages" },
        { assetName: "Bunting", category: "Decoration" },
    ] }];
    const node = await create("SymbioticaAssetFocus",
                              { order: null, category: "Decoration", asset: "" });
    await node.onNodeCreated?.call(node);
    link(specs, node, "order");
    node._symRenderFocus();
    for (let i = 0; i < 5; i++) await tick();
    assert.deepEqual(rows(node).map((r) => r.children[0].textContent), ["Bunting"]);
});

test("with nothing wired it says what to wire", async () => {
    const node = await focusNode({}, []);
    const text = walk(listOf(node)).map((e) => e.textContent).join(" ");
    assert.match(text, /wire an Order Specs/);
});

test("what a run reported wins over what was published", async () => {
    // The run's list is what the node actually chose from, already narrowed.
    reset();
    const specs = await create("SymbioticaOrderSpecs", { feature: "Mini 3" });
    specs.comfyClass = "SymbioticaOrderSpecs";
    specs._symEvents = [{ feature: "Mini 3", assets: [
        { assetName: "Stale", category: "Food" }] }];
    const node = await create("SymbioticaAssetFocus",
                              { order: null, category: "", asset: "" });
    await node.onNodeCreated?.call(node);
    link(specs, node, "order");
    node._symFocusAssets = [{ name: "FromTheRun", category: "Food" }];
    node._symRenderFocus();
    for (let i = 0; i < 5; i++) await tick();
    assert.deepEqual(rows(node).map((r) => r.children[0].textContent),
                     ["FromTheRun"]);
});

test("the order is followed through a reroute", async () => {
    // The wire commonly passes through one; a node in between that forwards
    // the order is not a reason to stop looking for who produced it.
    reset();
    const specs = await create("SymbioticaOrderSpecs", { feature: "Mini 3" });
    specs.comfyClass = "SymbioticaOrderSpecs";
    specs._symEvents = [{ feature: "Mini 3", assets: [
        { assetName: "Frankencrisps", category: "Food - 3 stages" }] }];
    const hop = await create("Reroute", {});
    hop.comfyClass = "Reroute";
    const node = await create("SymbioticaAssetFocus",
                              { order: null, category: "", asset: "" });
    await node.onNodeCreated?.call(node);
    link(specs, hop, "in");
    link(hop, node, "order");
    node._symRenderFocus();
    for (let i = 0; i < 5; i++) await tick();
    assert.deepEqual(rows(node).map((r) => r.children[0].textContent),
                     ["Frankencrisps"]);
});

test("an ambiguous hop is not guessed at", async () => {
    reset();
    const specs = await create("SymbioticaOrderSpecs", { feature: "Mini 3" });
    specs.comfyClass = "SymbioticaOrderSpecs";
    specs._symEvents = [{ feature: "Mini 3", assets: [
        { assetName: "Frankencrisps", category: "Food" }] }];
    const other = await create("SomethingElse", {});
    const merge = await create("Merge", {});
    merge.comfyClass = "Merge";
    const node = await create("SymbioticaAssetFocus",
                              { order: null, category: "", asset: "" });
    await node.onNodeCreated?.call(node);
    link(specs, merge, "a");
    link(other, merge, "b");
    link(merge, node, "order");
    node._symRenderFocus();
    for (let i = 0; i < 5; i++) await tick();
    const text = walk(listOf(node)).map((e) => e.textContent).join(" ");
    assert.match(text, /no assets from the wired order yet/);
});

test("a source holding no events yet is asked to parse, once", async () => {
    // A saved workflow restores Order Specs' month and feature without parsing
    // anything, so the node looks configured while holding no events at all.
    reset();
    let asked = 0;
    const specs = await create("SymbioticaOrderSpecs", { feature: "Mini 3" });
    specs.comfyClass = "SymbioticaOrderSpecs";
    specs._symEvents = [];
    specs._symRefreshOrder = async () => {
        asked += 1;
        specs._symEvents = [{ feature: "Mini 3", assets: [
            { assetName: "Frankencrisps", category: "Food - 3 stages" }] }];
    };
    const node = await create("SymbioticaAssetFocus",
                              { order: null, category: "", asset: "" });
    await node.onNodeCreated?.call(node);
    link(specs, node, "order");
    node._symRenderFocus();
    for (let i = 0; i < 10; i++) await tick();
    assert.equal(asked, 1);
    assert.deepEqual(rows(node).map((r) => r.children[0].textContent),
                     ["Frankencrisps"]);
    // Re-rendering must not ask again — the render is called on every repaint.
    node._symRenderFocus();
    node._symRenderFocus();
    for (let i = 0; i < 10; i++) await tick();
    assert.equal(asked, 1);
});

test("re-wiring the order lets it ask the new source", async () => {
    reset();
    const specs = await create("SymbioticaOrderSpecs", { feature: "Mini 3" });
    specs.comfyClass = "SymbioticaOrderSpecs";
    specs._symEvents = [];
    let asked = 0;
    specs._symRefreshOrder = async () => { asked += 1; };
    const node = await create("SymbioticaAssetFocus",
                              { order: null, category: "", asset: "" });
    await node.onNodeCreated?.call(node);
    link(specs, node, "order");
    node._symRenderFocus();
    for (let i = 0; i < 10; i++) await tick();
    node.onConnectionsChange?.call(node, 1, 0, true, null, { name: "order" });
    for (let i = 0; i < 10; i++) await tick();
    assert.equal(asked, 2);
});
