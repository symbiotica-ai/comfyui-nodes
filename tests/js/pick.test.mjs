// ABOUTME: The Pick node's panel — that it draws a tile per candidate, opens on
// ABOUTME: the asset being worked on, and that ticking one records it on the node.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, fire, link, reset, setResponder, tick } from "./comfy_stub.mjs";
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
        if (route.startsWith("/symbiotica/pick-import")) {
            return { ok: true, status: 200,
                     body: { ok: true, folder: "/out/renders/cake", asset: "cake",
                             added: 4, skipped: 1, failed: 0, found: 5,
                             truncated: 0 } };
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
    assert.match(text, /queue this node/);
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

test("ticks belonging to another asset are shown as not being sent", async () => {
    // Three ticked thumbnails turning into six images is what this prevents.
    const node = await panelNode([], [CAKE_A, CAKE_B, PIE],
                                 { selection: JSON.stringify(["aaa", "bbb", "ccc"]) });
    // The panel opens on PIE's group, so aaa and bbb are ticked elsewhere.
    assert.equal(buttonsSaying(node, "2 elsewhere ✕").length, 1);
    fire(buttonsSaying(node, "2 elsewhere ✕")[0], "click");
    assert.deepEqual(ticksOf(node), ["ccc"]);
});

test("no stray ticks means no such button", async () => {
    const node = await panelNode([], [CAKE_A, CAKE_B],
                                 { selection: JSON.stringify(["aaa"]) });
    assert.equal(walk(listOf(node)).filter(
        (e) => /elsewhere/.test(String(e.textContent))).length, 0);
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

const PREP = { ...CAKE_A, id: "p1", thumb: "/out/p1_thumb.png", role: "prep" };
const READY = { ...CAKE_A, id: "r1", thumb: "/out/r1_thumb.png", role: "ready" };
const SERVING = { ...CAKE_A, id: "s1", thumb: "/out/s1_thumb.png", role: "serving" };
const PREP2 = { ...CAKE_A, id: "p2", thumb: "/out/p2_thumb.png", role: "prep" };

const rowLabels = (node) =>
    walk(listOf(node))
        .filter((e) => ["PREP", "READY", "SERVING"].includes(String(e.textContent).toUpperCase()))
        .map((e) => e.textContent);

test("stages are laid out one row per stage, in the order the sheet was cut", async () => {
    // A prep should be compared against the other preps, not against a serving.
    const node = await panelNode([], [PREP, READY, SERVING, PREP2]);
    assert.deepEqual(rowLabels(node), ["prep", "ready", "serving"]);
    assert.equal(tiles(node).length, 4);
});

test("the two preps sit together in the first row", async () => {
    const node = await panelNode([], [PREP, READY, SERVING, PREP2]);
    // Each row is [label, strip]; the strip's children are the tiles.
    const rows = walk(listOf(node))
        .filter((e) => e.children.length === 2
            && ["prep", "ready", "serving"].includes(e.children[0].textContent));
    assert.deepEqual(rows.map((r) => r.children[0].textContent),
                     ["prep", "ready", "serving"]);
    assert.deepEqual(rows.map((r) => r.children[1].children.length), [2, 1, 1]);
});

test("candidates with no stage keep the flat grid", async () => {
    const node = await panelNode([], [CAKE_A, CAKE_B]);
    assert.deepEqual(rowLabels(node), []);
    assert.equal(tiles(node).length, 2);
});

test("ticking still works inside a stage row", async () => {
    const node = await panelNode([], [PREP, READY, SERVING]);
    fire(tiles(node)[2], "click");
    assert.deepEqual(ticksOf(node), ["s1"]);
});

test("Read folder posts the node's folder and reloads the buffer", async () => {
    // The buffer is per node, so a picker added after the work was generated
    // starts empty; re-running the generator to fill it pays twice.
    const seen = [];
    const node = await panelNode(seen, [], { folder: "/out/renders/cake" });
    const btn = node.widgets.find((w) => w.name === "📁 Read folder");
    assert.ok(btn);
    assert.equal(btn.serialize, false, "a serialised button shifts widgets_values");
    await btn.callback();
    for (let i = 0; i < 20; i++) await tick();
    const post = seen.find((c) => c.route === "/symbiotica/pick-import");
    assert.deepEqual(JSON.parse(post.init.body),
                     { node_id: String(node.id), folder: "/out/renders/cake" });
    // It re-lists afterwards, or the new candidates would not appear.
    assert.ok(seen.filter((c) => c.route.startsWith("/symbiotica/pick-list")).length > 1);
});

test("Read folder sends the tags that are typed, and omits the wired ones", async () => {
    const seen = [];
    const node = await panelNode(seen, [], {
        folder: "/out/renders", asset: "cake", category: "", role: "prep" });
    await node.widgets.find((w) => w.name === "📁 Read folder").callback();
    for (let i = 0; i < 20; i++) await tick();
    const body = JSON.parse(seen.find((c) => c.route === "/symbiotica/pick-import").init.body);
    assert.equal(body.asset, "cake");
    assert.equal(body.role, "prep");
    assert.ok(!("category" in body), "an empty widget must not overwrite the fallback");
});

test("Read folder with no folder explains that it is not needed", async () => {
    // The node reads this asset's own folder while it executes; the button is
    // only for pointing at some OTHER folder.
    const seen = [];
    const node = await panelNode(seen, [], { folder: "" });
    await node.widgets.find((w) => w.name === "📁 Read folder").callback();
    assert.equal(seen.filter((c) => c.route === "/symbiotica/pick-import").length, 0);
    const text = walk(listOf(node)).map((e) => e.textContent).join(" ");
    assert.match(text, /leave `folder` empty/);
});

test("an empty buffer with get_new off says that is why", async () => {
    const node = await panelNode([], [], { get_new: false });
    const text = walk(listOf(node)).map((e) => e.textContent).join(" ");
    assert.match(text, /get_new is off/);
});

const EXPORTED = { ...CAKE_A, id: "e1", thumb: "/out/e1_thumb.png", phase: "export" };
const EDITED = { ...CAKE_A, id: "d1", thumb: "/out/d1_thumb.png", phase: "edit" };

test("a picker pinned to a pass shows only that pass", async () => {
    // A 128px cutout with alpha is not an alternative to a full render.
    const node = await panelNode([], [EXPORTED, EDITED, CAKE_B],
                                 { phase: "export" });
    assert.equal(tiles(node).length, 1);
    assert.ok(tiles(node)[0].src.includes(encodeURIComponent("/out/e1_thumb.png")));
});

test("an unpinned picker shows every pass", async () => {
    const node = await panelNode([], [EXPORTED, EDITED, CAKE_B], { phase: "" });
    const select = listOf(node).children[1].children[0];
    select.value = "__all__";
    fire(select, "change");
    assert.equal(tiles(node).length, 3);
});

test("the pass is shown on the node body", async () => {
    // Three pickers in three groups otherwise look identical.
    const node = await panelNode([], [EXPORTED], { phase: "export" });
    assert.equal(buttonsSaying(node, "export").length, 1);
});

test("a buffer with nothing in this pass says so, and offers a way out", async () => {
    // Images collected before the picker was pinned carry no pass at all, so
    // this must not read as an empty buffer.
    const node = await panelNode([], [EDITED, CAKE_B], { phase: "export" });
    const text = walk(listOf(node)).map((e) => e.textContent).join(" ");
    assert.match(text, /none tagged "export"/);
    assert.equal(buttonsSaying(node, "show all 2").length, 1);
    fire(buttonsSaying(node, "show all 2")[0], "click");
    assert.equal(widgetOf(node, "phase").value, "");
    assert.equal(tiles(node).length, 2);
});

test("Read folder tells the server which pass this picker is", async () => {
    const seen = [];
    const node = await panelNode(seen, [], { folder: "/out/x", phase: "export" });
    await node.widgets.find((w) => w.name === "📁 Read folder").callback();
    for (let i = 0; i < 20; i++) await tick();
    const body = JSON.parse(seen.find((c) => c.route === "/symbiotica/pick-import").init.body);
    assert.equal(body.phase, "export");
});

const SPOOKIES = { ...CAKE_A, id: "s1", thumb: "/out/s1_thumb.png",
                   group: "Mini 1 / Food - 3 stages / Spookies" };
const POPSICLE = { ...CAKE_A, id: "s2", thumb: "/out/s2_thumb.png",
                   group: "Mini 1 / Food - 3 stages / Spooky Stack Popsicle" };

async function pickWithFocus(images, assetValue) {
    reset();
    setResponder(router([], images));
    const focus = await create("SymbioticaAssetFocus", { asset: assetValue });
    focus.comfyClass = "SymbioticaAssetFocus";
    const node = await create("SymbioticaPick", { selection: "", view: "" });
    await node.onNodeCreated?.call(node);
    link(focus, node, "asset");
    for (let i = 0; i < 20; i++) await tick();
    node._symReloadPick && await node._symReloadPick();
    for (let i = 0; i < 20; i++) await tick();
    return node;
}

test("the grid follows the asset the upstream Asset Focus is set to", async () => {
    // The `asset` input is wired, so it has no widget value of its own — but
    // the node feeding it does.
    const node = await pickWithFocus([SPOOKIES, POPSICLE], "Spooky Stack Popsicle");
    assert.equal(tiles(node).length, 1);
    assert.ok(tiles(node)[0].src.includes(encodeURIComponent("/out/s2_thumb.png")));
});

test("switching the asset upstream switches the grid, with no run", async () => {
    const node = await pickWithFocus([SPOOKIES, POPSICLE], "Spookies");
    assert.ok(tiles(node)[0].src.includes(encodeURIComponent("/out/s1_thumb.png")));
    const focus = app.graph.getNodeById(node.id - 1);
    focus.widgets.find((w) => w.name === "asset").value = "Spooky Stack Popsicle";
    node._symReloadPick && await node._symReloadPick();
    for (let i = 0; i < 20; i++) await tick();
    assert.ok(tiles(node)[0].src.includes(encodeURIComponent("/out/s2_thumb.png")));
});

test("an asset with no candidates yet does not hide everything", async () => {
    // Falling through to the newest arrival beats showing an empty grid for a
    // group that does not exist.
    const node = await pickWithFocus([SPOOKIES], "Ghostly Jelly Cake");
    assert.equal(tiles(node).length, 1);
});

test("the run's own group is used when there is no Focus to read", async () => {
    const seen = [];
    const node = await panelNode(seen, [SPOOKIES, POPSICLE]);
    node._symPickCurrent = "Mini 1 / Food - 3 stages / Spookies";
    await node._symReloadPick();
    for (let i = 0; i < 20; i++) await tick();
    assert.ok(tiles(node)[0].src.includes(encodeURIComponent("/out/s1_thumb.png")));
});

test("a pinned group still beats both", async () => {
    // Auto is a default, not an override of what was chosen by hand.
    const node = await pickWithFocus([SPOOKIES, POPSICLE], "Spookies");
    widgetOf(node, "view").value = "Mini 1 / Food - 3 stages / Spooky Stack Popsicle";
    node._symReloadPick && await node._symReloadPick();
    for (let i = 0; i < 20; i++) await tick();
    assert.ok(tiles(node)[0].src.includes(encodeURIComponent("/out/s2_thumb.png")));
});

test("an empty first load is retried rather than left standing", async () => {
    // A first load can land before the graph has finished configuring, when
    // the node still carries a placeholder id and its buffer reads as empty.
    reset();
    let calls = 0;
    setResponder((route) => {
        if (route.startsWith("/symbiotica/pick-list")) {
            calls += 1;
            const images = calls > 1 ? [CAKE_A] : [];
            return { ok: true, status: 200,
                     body: { ok: true, images, groups: images.length
                         ? [{ key: CAKE_A.group, count: 1 }] : [] } };
        }
        return { ok: false, status: 404, body: { error: "no route" } };
    });
    const node = await create("SymbioticaPick", { selection: "", view: "" });
    await node.onNodeCreated?.call(node);
    for (let i = 0; i < 40; i++) await tick();
    await new Promise((r) => setTimeout(r, 600));
    for (let i = 0; i < 20; i++) await tick();
    assert.ok(calls > 1, "it should have asked again");
    assert.equal(tiles(node).length, 1);
});

test("a load that keeps coming back empty stops asking", async () => {
    // Retrying forever would hammer the server for a node whose buffer really
    // is empty, which is every picker before its first run.
    reset();
    let calls = 0;
    setResponder((route) => {
        if (route.startsWith("/symbiotica/pick-list")) {
            calls += 1;
            return { ok: true, status: 200, body: { ok: true, images: [], groups: [] } };
        }
        return { ok: false, status: 404, body: { error: "no route" } };
    });
    const node = await create("SymbioticaPick", { selection: "", view: "" });
    await node.onNodeCreated?.call(node);
    await new Promise((r) => setTimeout(r, 2600));
    for (let i = 0; i < 20; i++) await tick();
    assert.ok(calls <= 4, `asked ${calls} times`);
});
