// ABOUTME: Order Tracker panel — a slot per asset, filled or empty, and the
// ABOUTME: count that says how much of the order is done.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, fire, link, reset, tick } from "./comfy_stub.mjs";
import "../../web/js/order_tracker.js";

const BOARD = {
    node_id: "7", feature: "Mini 3", done: 1, total: 3,
    slots: [
        { asset: "Bat Brew", category: "Decoration",
          image: "/out/Bat Brew/_final_from._base_00007__00001_.png", count: 1 },
        { asset: "Bat Bookshelf", category: "Decoration", image: null, count: 0 },
        { asset: "Spookies", category: "Food - 3 stages", image: null, count: 0 },
    ],
};

async function trackerNode(board = BOARD) {
    reset();
    const node = await create("SymbioticaOrderTracker",
                              { order: null, category: "", names: "_final" });
    await node.onNodeCreated?.call(node);
    if (board) node._symBoard = board;
    node._symRenderTracker?.();
    for (let i = 0; i < 5; i++) await tick();
    return node;
}

const listOf = (node) =>
    node.widgets.find((w) => w.name === "tracker_panel").element.children[0];
// header, bar, grid
const gridOf = (node) => listOf(node).children[2];
const tiles = (node) => [...(gridOf(node)?.children ?? [])];
const tileName = (tile) => tile.children[1].textContent;
const tileImage = (tile) => tile.children[0].children[0];

function walk(elem, out = []) {
    for (const child of elem.children ?? []) {
        out.push(child);
        walk(child, out);
    }
    return out;
}

test("a slot per asset the order asks for", async () => {
    const node = await trackerNode();
    assert.equal(tiles(node).length, 3);
    assert.deepEqual(tiles(node).map(tileName),
                     ["Bat Brew", "Bat Bookshelf", "Spookies"]);
});

test("a filled slot shows the approved render", async () => {
    const node = await trackerNode();
    const img = tileImage(tiles(node)[0]);
    assert.match(img.src, /pick-thumb/);
    assert.match(img.src,
                 new RegExp(encodeURIComponent("_final_from._base_00007_")));
});

test("an empty slot is work left, and holds no image", async () => {
    const node = await trackerNode();
    assert.equal(tiles(node)[1].children[0].children.length, 0);
    // Dashed, so "nothing here yet" reads differently from a black tile.
    assert.match(tiles(node)[1].children[0].style.cssText, /border-style:dashed/);
});

test("the header counts what is done", async () => {
    const node = await trackerNode();
    assert.match(listOf(node).children[0].textContent, /1\/3 done · 33%/);
});

test("the bar is as wide as the work that is finished", async () => {
    const node = await trackerNode();
    const fill = listOf(node).children[1].children[0];
    assert.match(fill.style.cssText, /width:33%/);
});

test("an untouched order reads 0%", async () => {
    const node = await trackerNode({
        ...BOARD, done: 0,
        slots: BOARD.slots.map((s) => ({ ...s, image: null })),
    });
    assert.match(listOf(node).children[0].textContent, /0\/3 done · 0%/);
    assert.match(listOf(node).children[1].children[0].style.cssText, /width:0%/);
});

test("a finished order reads 100%", async () => {
    const node = await trackerNode({
        ...BOARD, done: 3,
        slots: BOARD.slots.map((s) => ({ ...s, image: "/out/x.png" })),
    });
    assert.match(listOf(node).children[0].textContent, /3\/3 done · 100%/);
});

test("with nothing wired it says what to wire", async () => {
    const node = await trackerNode(null);
    const text = walk(listOf(node)).map((e) => e.textContent).join(" ");
    assert.match(text, /wire an Order Specs/);
});

test("wired but never queued says so", async () => {
    reset();
    const specs = await create("SymbioticaOrderSpecs", { feature: "Mini 3" });
    specs.comfyClass = "SymbioticaOrderSpecs";
    const node = await create("SymbioticaOrderTracker",
                              { order: null, category: "", names: "_final" });
    await node.onNodeCreated?.call(node);
    link(specs, node, "order");
    node._symRenderTracker();
    for (let i = 0; i < 5; i++) await tick();
    const text = walk(listOf(node)).map((e) => e.textContent).join(" ");
    assert.match(text, /queue this node once/);
});

test("re-wiring the order drops the board it produced", async () => {
    // The slots on screen belong to the order that produced them.
    const node = await trackerNode();
    node.onConnectionsChange?.call(node, 1, 0, true, null, { name: "order" });
    for (let i = 0; i < 5; i++) await tick();
    assert.equal(node._symBoard, null);
    assert.equal(tiles(node).length, 0);
});

test("nothing in the panel is allowed to paint outside the node", async () => {
    const node = await trackerNode();
    for (const box of [listOf(node), listOf(node).children[0], gridOf(node)]) {
        assert.match(box.style.cssText, /width:100%/);
        assert.match(box.style.cssText, /box-sizing:border-box/);
        assert.match(box.style.cssText, /overflow:hidden/);
    }
});

test("the panel does not pin the node's height", async () => {
    // A computeSize that answers with the content becomes a floor the corner
    // cannot drag past — the trap this pack has paid for twice.
    const node = await trackerNode();
    const widget = node.widgets.find((w) => w.name === "tracker_panel");
    assert.equal(widget.computeSize, undefined);
    assert.equal(widget.options.getMinHeight(), 34);
});

test("the extension registered", () => {
    assert.ok(app.extensions.some((e) => e.name === "symbiotica.order_tracker"));
});
