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
    // Deep copy: rejecting mutates the board it was handed, and the
    // fixture is shared by every test in this file.
    if (board) node._symBoard = JSON.parse(JSON.stringify(board));
    node._symRenderTracker?.();
    for (let i = 0; i < 5; i++) await tick();
    return node;
}

const listOf = (node) =>
    node.widgets.find((w) => w.name === "tracker_panel").element.children[0];
// [0] is the sticky head (count + bar); then a (category header, grid) pair
// per category.
const headOf = (node) => listOf(node).children[0];
const body = (node) => [...listOf(node).children].slice(1);
const grids = (node) => body(node).filter((_, i) => i % 2 === 1);
const gridOf = (node) => grids(node)[0];
const groupHeaders = (node) =>
    body(node).filter((_, i) => i % 2 === 0).map((c) => c.textContent);
const tiles = (node) => grids(node).flatMap((g) => [...(g.children ?? [])]);
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

test("a filled slot backs the render with mid grey", async () => {
    // These renders are background-removed, so the backing shows THROUGH them:
    // on near-black a pale asset reads as a silhouette and a dark one vanishes.
    const node = await trackerNode();
    assert.match(tiles(node)[0].children[0].style.cssText, /background:#808080/);
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

test("an empty slot paints no backing", async () => {
    // HUB.surface1 is a dark-theme token: on the light palette it fills the
    // tile solid black, which reads as a render that came out wrong.
    const node = await trackerNode();
    assert.match(tiles(node)[1].children[0].style.cssText,
                 /background:transparent/);
    assert.doesNotMatch(tiles(node)[1].children[0].style.cssText,
                        new RegExp("background:#0f1011"));
});

test("the slots group under a header per category", async () => {
    // The same shape the Asset Focus list reads in, so the two panels describe
    // one order the same way.
    const node = await trackerNode();
    assert.deepEqual(groupHeaders(node),
                     ["Decoration · 1/2", "Food - 3 stages · 0/1"]);
});

test("each group holds only its own assets", async () => {
    const node = await trackerNode();
    assert.deepEqual(grids(node).map((g) => [...g.children].map(tileName)),
                     [["Bat Brew", "Bat Bookshelf"], ["Spookies"]]);
});

test("a group header counts what is done in it", async () => {
    const node = await trackerNode({
        ...BOARD, done: 2,
        slots: BOARD.slots.map((s) => ({ ...s, image: "/out/x.png" })),
    });
    assert.deepEqual(groupHeaders(node),
                     ["Decoration · 2/2", "Food - 3 stages · 1/1"]);
});

test("an asset with no category still gets a group", async () => {
    const node = await trackerNode({
        ...BOARD, done: 0, total: 1,
        slots: [{ asset: "Loose", category: "", image: null, count: 0 }],
    });
    assert.deepEqual(groupHeaders(node), ["uncategorised · 0/1"]);
});

test("the header counts what is done", async () => {
    const node = await trackerNode();
    assert.match(headOf(node).children[0].textContent, /1\/3 done · 33%/);
});

test("the bar is as wide as the work that is finished", async () => {
    const node = await trackerNode();
    const fill = headOf(node).children[1].children[0];
    assert.match(fill.style.cssText, /width:33%/);
});

test("an untouched order reads 0%", async () => {
    const node = await trackerNode({
        ...BOARD, done: 0,
        slots: BOARD.slots.map((s) => ({ ...s, image: null })),
    });
    assert.match(headOf(node).children[0].textContent, /0\/3 done · 0%/);
    assert.match(headOf(node).children[1].children[0].style.cssText, /width:0%/);
});

test("a finished order reads 100%", async () => {
    const node = await trackerNode({
        ...BOARD, done: 3,
        slots: BOARD.slots.map((s) => ({ ...s, image: "/out/x.png" })),
    });
    assert.match(headOf(node).children[0].textContent, /3\/3 done · 100%/);
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
    for (const box of [listOf(node), headOf(node), gridOf(node)]) {
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

// --- reject -----------------------------------------------------------------
import { setResponder } from "./comfy_stub.mjs";

const rejectOf = (tile) => tile.children[0].children[1];

test("a filled slot carries a reject button, an empty one does not", async () => {
    const node = await trackerNode();
    assert.ok(rejectOf(tiles(node)[0]));
    assert.equal(tiles(node)[1].children[0].children.length, 0);
});

test("it is hidden until the slot is hovered", async () => {
    // Nine ✕ buttons on a full board is a wall of controls over the work.
    const node = await trackerNode();
    assert.equal(rejectOf(tiles(node)[0]).style.display, "none");
    fire(tiles(node)[0], "mouseenter");
    assert.equal(rejectOf(tiles(node)[0]).style.display, "block");
});

test("the first click arms, it does not reject", async () => {
    const seen = [];
    setResponder((route, _n, init) => {
        seen.push({ route, init });
        return { ok: true, body: { ok: true, moved: ["x.png"] } };
    });
    const node = await trackerNode();
    fire(rejectOf(tiles(node)[0]), "click", { stopPropagation() {} });
    for (let i = 0; i < 5; i++) await tick();
    assert.equal(seen.length, 0);
    assert.equal(rejectOf(tiles(node)[0]).textContent, "✕?");
});

test("the second click moves the approval and empties the slot", async () => {
    const seen = [];
    setResponder((route, _n, init) => {
        seen.push({ route, init });
        return { ok: true, body: { ok: true, moved: ["x.png"] } };
    });
    const node = await trackerNode();
    const button = rejectOf(tiles(node)[0]);
    fire(button, "click", { stopPropagation() {} });
    fire(button, "click", { stopPropagation() {} });
    for (let i = 0; i < 10; i++) await tick();
    assert.equal(seen.length, 1);
    assert.match(seen[0].route, /tracker-reject/);
    assert.equal(JSON.parse(seen[0].init.body).path,
                 "/out/Bat Brew/_final_from._base_00007__00001_.png");
    // The board is a reading of disk, and disk just changed.
    assert.equal(tiles(node)[0].children[0].children.length, 0);
    assert.match(headOf(node).children[0].textContent, /0\/3 done/);
});

test("a refused reject leaves the slot filled", async () => {
    setResponder(() => ({ ok: false, status: 403,
                          body: { error: "not inside a folder this install serves" } }));
    const node = await trackerNode();
    const button = rejectOf(tiles(node)[0]);
    fire(button, "click", { stopPropagation() {} });
    fire(button, "click", { stopPropagation() {} });
    for (let i = 0; i < 10; i++) await tick();
    assert.equal(tiles(node)[0].children[0].children.length, 2);
    assert.match(headOf(node).children[0].textContent, /1\/3 done/);
});

test("the panel's wrapper is pinned to the node width", async () => {
    const node = await trackerNode();
    const container = node.widgets.find((w) => w.name === "tracker_panel").element;
    const wrap = { style: { width: "900px" } };
    container.parent = wrap;
    node.size[0] = 400;
    node.onResize();
    assert.equal(wrap.style.width, "380px");
});

test("the count and bar stay put while the slots scroll", async () => {
    // "progress bar should be visible all the time, when i scroll it get
    // hidden" — it answers "how far in am I", which you are still asking on
    // the fortieth asset.
    const node = await trackerNode();
    const head = headOf(node);
    assert.match(head.style.cssText, /position:sticky/);
    assert.match(head.style.cssText, /top:0/);
    // Opaque, or the tiles read through it as they pass under.
    assert.match(head.style.cssText, /background:/);
    // The bar is inside the sticky block, not left behind in the scroll.
    assert.match(head.children[1].children[0].style.cssText, /width:33%/);
});
