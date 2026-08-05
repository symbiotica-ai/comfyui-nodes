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

test("the header says how many the node will emit", async () => {
    // "all" emits every listed asset now, so the count has to be visible.
    const none = await focusNode({ asset: "" });
    assert.match(listOf(none).children[0].children[0].textContent, /runs 3/);
    const one = await focusNode({ asset: "Bunting" });
    assert.match(listOf(one).children[0].children[0].textContent, /runs 1/);
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

test("changing the feature upstream re-lists without touching this node", async () => {
    // "why doesn't the asset focus node change the category when i change it
    // in order specs? i have to manually click in 494 on all to see the
    // categories". LiteGraph has no event for "a widget upstream changed", so
    // the source announces it and every order reader decides if it cares.
    reset();
    const specs = await create("SymbioticaOrderSpecs", { feature: "Mini 1" });
    specs.comfyClass = "SymbioticaOrderSpecs";
    specs._symEvents = [
        { feature: "Mini 1", assets: [
            { assetName: "Skull Rose Cupcake", category: "Food - 3 stages" }] },
        { feature: "Mini 3", assets: [
            { assetName: "Bunting", category: "Decoration" }] },
    ];
    const node = await create("SymbioticaAssetFocus",
                              { order: null, category: "", asset: "" });
    await node.onNodeCreated?.call(node);
    link(specs, node, "order");
    node._symRenderFocus();
    for (let i = 0; i < 5; i++) await tick();
    assert.deepEqual(rows(node).map((r) => r.children[0].textContent),
                     ["Skull Rose Cupcake"]);

    widgetOf(specs, "feature").value = "Mini 3";
    node._symOrderChanged(specs);
    for (let i = 0; i < 5; i++) await tick();
    assert.deepEqual(rows(node).map((r) => r.children[0].textContent),
                     ["Bunting"]);
});

test("a run's list does not survive the feature changing under it", async () => {
    // What a run reported wins over what the source published, so leaving it
    // in place shows the PREVIOUS event's assets and emits them too.
    reset();
    const specs = await create("SymbioticaOrderSpecs", { feature: "Mini 3" });
    specs.comfyClass = "SymbioticaOrderSpecs";
    specs._symEvents = [{ feature: "Mini 3", assets: [
        { assetName: "Bunting", category: "Decoration" }] }];
    const node = await create("SymbioticaAssetFocus",
                              { order: null, category: "", asset: "" });
    await node.onNodeCreated?.call(node);
    link(specs, node, "order");
    node._symFocusAssets = [{ name: "Frankencrisps", category: "Food - 3 stages" }];
    node._symRenderFocus();
    for (let i = 0; i < 5; i++) await tick();
    assert.deepEqual(rows(node).map((r) => r.children[0].textContent),
                     ["Frankencrisps"]);

    node._symOrderChanged(specs);
    for (let i = 0; i < 5; i++) await tick();
    assert.deepEqual(rows(node).map((r) => r.children[0].textContent),
                     ["Bunting"]);
});

test("a category the new feature does not have falls back to All", async () => {
    // Narrowing to nothing reads as "this node is broken" rather than as
    // "Decoration is not in this feature".
    reset();
    const specs = await create("SymbioticaOrderSpecs", { feature: "Mini 1" });
    specs.comfyClass = "SymbioticaOrderSpecs";
    specs._symEvents = [
        { feature: "Mini 1", assets: [
            { assetName: "Bunting", category: "Decoration" }] },
        { feature: "Mini 3", assets: [
            { assetName: "Frankencrisps", category: "Food - 3 stages" }] },
    ];
    const node = await create("SymbioticaAssetFocus",
                              { order: null, category: "Decoration", asset: "" });
    await node.onNodeCreated?.call(node);
    link(specs, node, "order");
    node._symRenderFocus();
    for (let i = 0; i < 5; i++) await tick();

    widgetOf(specs, "feature").value = "Mini 3";
    node._symOrderChanged(specs);
    for (let i = 0; i < 5; i++) await tick();
    assert.equal(widgetOf(node, "category").value, "All");
    assert.deepEqual(rows(node).map((r) => r.children[0].textContent),
                     ["Frankencrisps"]);
});

test("an order change from somewhere else is ignored", async () => {
    // Two orders on one canvas is ordinary; a picker must not re-list because
    // the OTHER one moved.
    reset();
    const mine = await create("SymbioticaOrderSpecs", { feature: "Mini 3" });
    mine.comfyClass = "SymbioticaOrderSpecs";
    mine._symEvents = [{ feature: "Mini 3", assets: [
        { assetName: "Bunting", category: "Decoration" }] }];
    const other = await create("SymbioticaOrderSpecs", { feature: "Mini 9" });
    other.comfyClass = "SymbioticaOrderSpecs";
    const node = await create("SymbioticaAssetFocus",
                              { order: null, category: "", asset: "" });
    await node.onNodeCreated?.call(node);
    link(mine, node, "order");
    node._symFocusAssets = [{ name: "Frankencrisps", category: "Food - 3 stages" }];
    node._symRenderFocus();
    for (let i = 0; i < 5; i++) await tick();

    node._symOrderChanged(other);
    for (let i = 0; i < 5; i++) await tick();
    // Still the run's list: nothing about this node's own order changed.
    assert.deepEqual(rows(node).map((r) => r.children[0].textContent),
                     ["Frankencrisps"]);
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

test("category is a dropdown of what the order actually holds", async () => {
    // A text box you cannot be told what to type is not an input.
    reset();
    const specs = await create("SymbioticaOrderSpecs", { feature: "Mini 3" });
    specs.comfyClass = "SymbioticaOrderSpecs";
    specs._symEvents = [{ feature: "Mini 3", assets: [
        { assetName: "Frankenstein Date", category: "Decoration" },
        { assetName: "Frankencrisps", category: "Food - 3 stages" },
        { assetName: "Franken-Scream Cones", category: "Food - 3 stages" },
        { assetName: "Black Marble Stove", category: "Appliance" },
    ] }];
    const node = await create("SymbioticaAssetFocus",
                              { order: null, category: "", asset: "" });
    await node.onNodeCreated?.call(node);
    link(specs, node, "order");
    node._symRenderFocus();
    for (let i = 0; i < 5; i++) await tick();
    const w = node.widgets.find((x) => x.name === "category");
    assert.equal(w.type, "combo");
    // First-appearance order, the way the order sheet reads.
    assert.deepEqual(w.options.values(),
                     ["All", "Decoration", "Food - 3 stages", "Appliance"]);
});

test("All means no narrowing", async () => {
    const node = await focusNode({ category: "All" });
    assert.equal(rows(node).length, 3);
});

test("choosing a category narrows the rows", async () => {
    const node = await focusNode({ category: "All" });
    const w = node.widgets.find((x) => x.name === "category");
    w.value = "Decoration";
    w.callback("Decoration");
    for (let i = 0; i < 5; i++) await tick();
    assert.deepEqual(rows(node).map((r) => r.children[0].textContent), ["Bunting"]);
});

test("a chosen asset the new category hides is dropped, not left chosen invisibly", async () => {
    // Otherwise the node renders an asset that is not on screen.
    const node = await focusNode({ category: "All", asset: "Bunting" });
    const w = node.widgets.find((x) => x.name === "category");
    w.value = "Food - 3 stages";
    w.callback("Food - 3 stages");
    for (let i = 0; i < 5; i++) await tick();
    assert.equal(node.widgets.find((x) => x.name === "asset").value, "");
});

test("a chosen asset the new category still shows is kept", async () => {
    const node = await focusNode({ category: "All", asset: "Frankencrisps" });
    const w = node.widgets.find((x) => x.name === "category");
    w.value = "Food - 3 stages";
    w.callback("Food - 3 stages");
    for (let i = 0; i < 5; i++) await tick();
    assert.equal(node.widgets.find((x) => x.name === "asset").value, "Frankencrisps");
});

test("switching the event drops a choice that event does not have", async () => {
    // The name survives on the widget, highlighting nothing while still being
    // what the node would render — which is a refusal on the next run.
    const node = await focusNode({ asset: "Frankenstein Pops" }, [
        { name: "Spookies", category: "Food - 3 stages" },
        { name: "Ghost Bakery Queue", category: "Decoration" },
    ]);
    assert.equal(node.widgets.find((x) => x.name === "asset").value, "");
    assert.equal(rows(node).length, 2);
});

test("a choice the event still has survives", async () => {
    const node = await focusNode({ asset: "Bunting" });
    assert.equal(node.widgets.find((x) => x.name === "asset").value, "Bunting");
});

test("an empty list does not clear the choice", async () => {
    // Nothing is known yet; forgetting the pick would lose it on every reload.
    const node = await focusNode({ asset: "Bunting" }, []);
    assert.equal(node.widgets.find((x) => x.name === "asset").value, "Bunting");
});

test("a saved empty category is normalised to All", async () => {
    // onConfigure restores the widget AFTER onNodeCreated normalised it.
    const node = await focusNode({ category: "" });
    assert.equal(node.widgets.find((x) => x.name === "category").value, "All");
    assert.equal(rows(node).length, 3);
});

test("nothing in the panel is allowed to paint outside the node", async () => {
    // A flex row whose content is wider than the node resolves its width
    // against a shrink-to-fit parent and paints over whatever is behind it.
    const node = await focusNode({}, [
        { name: "A Very Long Asset Name That Would Otherwise Widen The Row",
          category: "A Very Long Category Name As Well" },
    ]);
    const boxes = [listOf(node), ...rows(node)];
    for (const box of boxes) {
        assert.match(box.style.cssText, /width:100%/);
        assert.match(box.style.cssText, /box-sizing:border-box/);
        assert.match(box.style.cssText, /overflow:hidden/);
    }
    // Both texts must be able to shrink, or one of them forces the row wide.
    const [name, category] = rows(node)[0].children;
    assert.match(name.style.cssText, /min-width:0/);
    assert.match(category.style.cssText, /min-width:0/);
});
