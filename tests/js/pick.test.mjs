// ABOUTME: The Pick node's panel — that it draws a tile per candidate, opens on
// ABOUTME: the asset being worked on, and that ticking one records it on the node.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, fire, reset, setResponder, tick } from "./comfy_stub.mjs";
import "../../web/js/pick.js";

globalThis.window.confirm = () => true;
globalThis.window.open = () => {};

const CAKE_A = {
    id: "aaa", path: "/out/aaa.png", thumb: "/out/aaa_thumb.png",
    group: "Halloween / Food / cake", w: 1024, h: 1024, at: "2026-08-04 10:00:00",
};
const CAKE_B = { ...CAKE_A, id: "bbb", path: "/out/bbb.png", thumb: "/out/bbb_thumb.png" };
const PIE = {
    ...CAKE_A, id: "ccc", path: "/out/ccc.png", thumb: "/out/ccc_thumb.png",
    group: "Halloween / Food / pie",
};

function router(seen, images) {
    return (route, _n, init) => {
        seen.push({ route, init });
        if (route.startsWith("/symbiotica/pick-list")) {
            const groups = [];
            for (const im of images) {
                const g = groups.find((x) => x.key === im.group);
                if (g) g.count += 1;
                else groups.push({ key: im.group, count: 1 });
            }
            return { ok: true, status: 200, body: { ok: true, images, groups } };
        }
        if (route.startsWith("/symbiotica/pick-clear")) {
            return { ok: true, status: 200, body: { ok: true, removed: 1 } };
        }
        return { ok: false, status: 404, body: { error: "no route" } };
    };
}

async function panelNode(seen, images, widgets = {}) {
    reset();
    setResponder(router(seen, images));
    const node = await create("SymbioticaPick",
                              { selection: "", view: "", ...widgets });
    await node.onNodeCreated?.call(node);
    for (let i = 0; i < 20; i++) await tick();
    return node;
}

const listOf = (node) =>
    node.widgets.find((w) => w.name === "pick_panel").element.children[0];

function walk(elem, out = []) {
    for (const child of elem.children ?? []) {
        out.push(child);
        walk(child, out);
    }
    return out;
}

const tiles = (node) => walk(listOf(node)).filter((e) => "src" in e);
const buttonsSaying = (node, text) =>
    walk(listOf(node)).filter((e) => e.textContent === text);
const widgetOf = (node, name) => node.widgets.find((w) => w.name === name);
const ticksOf = (node) => JSON.parse(widgetOf(node, "selection").value || "[]");

test("the panel mounts and the state widgets are collapsed off the node", async () => {
    // They hold the ticks and the filter so the workflow saves them — they are
    // storage, not fields to type JSON into.
    const node = await panelNode([], [CAKE_A]);
    assert.ok(widgetOf(node, "pick_panel"));
    for (const name of ["selection", "view"]) {
        assert.equal(widgetOf(node, name).hidden, true);
        assert.deepEqual(widgetOf(node, name).computeSize(), [0, -4]);
    }
});

test("it asks for its own buffer, by node id", async () => {
    const seen = [];
    const node = await panelNode(seen, [CAKE_A]);
    assert.ok(seen.some((c) =>
        c.route === `/symbiotica/pick-list?node_id=${node.id}`));
});

test("one tile per candidate, drawn from the thumbnail", async () => {
    // The full renders are what the double-click opens; filling a strip of
    // 100px tiles with them is what makes a node feel broken.
    const node = await panelNode([], [CAKE_A, CAKE_B]);
    const srcs = tiles(node).map((t) => t.src);
    assert.equal(srcs.length, 2);
    assert.ok(srcs[0].includes(encodeURIComponent("/out/aaa_thumb.png")));
    assert.ok(!srcs[0].includes(encodeURIComponent("/out/aaa.png")));
});

test("an empty buffer says how to fill it rather than showing nothing", async () => {
    const node = await panelNode([], []);
    const text = walk(listOf(node)).map((e) => e.textContent).join(" ");
    assert.match(text, /queue this node to collect candidates/);
    assert.equal(tiles(node).length, 0);
});

test("a failed listing is shown on the node instead of only the console", async () => {
    reset();
    setResponder(() => ({ ok: false, status: 500, body: { error: "buffer is gone" } }));
    const node = await create("SymbioticaPick", { selection: "", view: "" });
    await node.onNodeCreated?.call(node);
    for (let i = 0; i < 20; i++) await tick();
    const text = walk(listOf(node)).map((e) => e.textContent).join(" ");
    assert.match(text, /buffer is gone/);
});

test("clicking a tile ticks it, and clicking again unticks it", async () => {
    const node = await panelNode([], [CAKE_A, CAKE_B]);
    fire(tiles(node)[1], "click");
    assert.deepEqual(ticksOf(node), ["bbb"]);
    fire(tiles(node)[1], "click");
    assert.deepEqual(ticksOf(node), []);
});

test("ticks accumulate across candidates", async () => {
    const node = await panelNode([], [CAKE_A, CAKE_B]);
    fire(tiles(node)[0], "click");
    fire(tiles(node)[1], "click");
    assert.deepEqual(ticksOf(node).sort(), ["aaa", "bbb"]);
});

test("ticks saved with the workflow are restored on the tiles", async () => {
    const node = await panelNode([], [CAKE_A, CAKE_B],
                                 { selection: JSON.stringify(["bbb"]) });
    // The ticked tile is the fully opaque one; the rest are dimmed.
    const [first, second] = tiles(node);
    assert.match(first.style.cssText, /opacity:\.72/);
    assert.doesNotMatch(second.style.cssText, /opacity:\.72/);
});

test("the panel opens on the asset that arrived last, not on everything", async () => {
    // "We are working on this asset and I need to see stuff related to it."
    const node = await panelNode([], [CAKE_A, CAKE_B, PIE]);
    assert.equal(tiles(node).length, 1);
    assert.ok(tiles(node)[0].src.includes(encodeURIComponent("/out/ccc_thumb.png")));
});

test("choosing All shows every candidate the node holds", async () => {
    const node = await panelNode([], [CAKE_A, CAKE_B, PIE]);
    const select = listOf(node).children[1].children[0];
    select.value = "__all__";
    fire(select, "change");
    assert.equal(widgetOf(node, "view").value, "__all__");
    assert.equal(tiles(node).length, 3);
});

test("pinning one group shows only that group", async () => {
    const node = await panelNode([], [CAKE_A, CAKE_B, PIE]);
    const select = listOf(node).children[1].children[0];
    select.value = "Halloween / Food / cake";
    fire(select, "change");
    assert.equal(tiles(node).length, 2);
});

test("a single group needs no filter row at all", async () => {
    const node = await panelNode([], [CAKE_A, CAKE_B]);
    // head, then the grid — nothing in between.
    assert.equal(listOf(node).children.length, 2);
    assert.equal(tiles(node).length, 2);
});

test("a pinned group that no longer exists falls back rather than showing blank",
     async () => {
         const node = await panelNode([], [CAKE_A, PIE],
                                      { view: "Halloween / Food / gone" });
         assert.equal(tiles(node).length, 1);
     });

test("deleting one candidate posts its id and drops its tick", async () => {
    const seen = [];
    const node = await panelNode(seen, [CAKE_A, CAKE_B],
                                 { selection: JSON.stringify(["aaa", "bbb"]) });
    const cross = buttonsSaying(node, "✕")[0];
    fire(cross, "click", { stopPropagation() {} });
    for (let i = 0; i < 20; i++) await tick();
    const post = seen.find((c) => c.route === "/symbiotica/pick-clear");
    assert.deepEqual(JSON.parse(post.init.body).ids, ["aaa"]);
    // A tick with no image behind it would claim a pick the node cannot serve.
    assert.deepEqual(ticksOf(node), ["bbb"]);
});

test("clear sends no ids, which the route reads as the whole buffer", async () => {
    const seen = [];
    const node = await panelNode(seen, [CAKE_A, CAKE_B],
                                 { selection: JSON.stringify(["aaa"]) });
    fire(buttonsSaying(node, "clear")[0], "click");
    for (let i = 0; i < 20; i++) await tick();
    const post = seen.find((c) => c.route === "/symbiotica/pick-clear");
    assert.equal(JSON.parse(post.init.body).ids, null);
    assert.deepEqual(ticksOf(node), []);
});

test("the node says so when it is not collecting", async () => {
    // A run that adds nothing looks exactly like a generator that failed.
    const on = await panelNode([], [CAKE_A], { collect: true });
    assert.equal(buttonsSaying(on, "not collecting").length, 0);
    const off = await panelNode([], [CAKE_A], { collect: false });
    assert.equal(buttonsSaying(off, "not collecting").length, 1);
});

test("the thumbnail size buttons change the tiles", async () => {
    const node = await panelNode([], [CAKE_A]);
    assert.match(tiles(node)[0].style.cssText, /width:108px/);
    fire(buttonsSaying(node, "L")[0], "click");
    assert.match(tiles(node)[0].style.cssText, /width:184px/);
    assert.equal(node.properties.symPickThumb, "L");
});

test("reloading after a run re-reads the buffer", async () => {
    const seen = [];
    const node = await panelNode(seen, [CAKE_A]);
    const before = seen.filter((c) => c.route.startsWith("/symbiotica/pick-list")).length;
    await node._symReloadPick();
    const after = seen.filter((c) => c.route.startsWith("/symbiotica/pick-list")).length;
    assert.equal(after, before + 1);
});

test("a workflow load re-reads the buffer once the node id is final", async () => {
    const seen = [];
    const node = await panelNode(seen, [CAKE_A]);
    const before = seen.filter((c) => c.route.startsWith("/symbiotica/pick-list")).length;
    node.onConfigure?.call(node);
    for (let i = 0; i < 20; i++) await tick();
    const after = seen.filter((c) => c.route.startsWith("/symbiotica/pick-list")).length;
    assert.equal(after, before + 1);
});

test("the extension registered", () => {
    assert.ok(app.extensions.some((e) => e.name === "symbiotica.pick"));
});
