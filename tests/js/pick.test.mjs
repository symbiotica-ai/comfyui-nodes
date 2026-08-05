// ABOUTME: The Pick node's panel — it lists the asset's own render folder as
// ABOUTME: numbered tiles, ticks record file names on the node, and nothing it
// ABOUTME: draws is a copy: every tile is a file already on disk.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, emit, fire, reset, setResponder, tick } from "./comfy_stub.mjs";
import "../../web/js/pick.js";

globalThis.window.confirm = () => true;
globalThis.window.open = () => {};

const FOLDER = "/out/Oct/Mini 1 — Ghostly Goodies/Food - 3 stages";
const shot = (name, index) => ({
    id: name, name, index, path: `${FOLDER}/${name}`, w: 1024, h: 1024,
    at: 1785860413,
});
const ONE = shot("Spookies_00001_.png", 1);
const TWO = shot("Spookies_00002_.png", 2);
const THREE = shot("Spookies_00003_.png", 3);

function router(seen, images, folder = `${FOLDER}/Spookies`, shortlist = false) {
    return (route, _n, init) => {
        seen.push({ route, init });
        if (route.startsWith("/symbiotica/pick-discard")) {
            return { ok: true, body: { ok: true,
                discarded: JSON.parse(init?.body ?? "{}").names ?? [] } };
        }
        if (route.startsWith("/symbiotica/pick-list")) {
            return { ok: true, body: { ok: true, folder, images, shortlist } };
        }
        return { ok: false, status: 404, body: { error: "no such route" } };
    };
}

const WIDGET_DEFAULTS = {
    save_path: "", selection: "", view: "", mode: "multiple", stage: "",
};

async function panelNode(seen = [], images = [], values = {},
                         shortlist = false) {
    reset();
    setResponder(router(seen, images, `${FOLDER}/Spookies`, shortlist));
    const node = await create("SymbioticaPick",
                              { ...WIDGET_DEFAULTS, ...values });
    await node.onNodeCreated?.call(node);
    for (let i = 0; i < 20; i++) await tick();
    return node;
}

const widgetOf = (node, name) => node.widgets.find((w) => w.name === name);
const listOf = (node) =>
    node.widgets.find((w) => w.name === "pick_panel").element.children[0];

function walk(root, out = []) {
    for (const child of root.children ?? []) {
        out.push(child);
        walk(child, out);
    }
    return out;
}

const tiles = (node) => walk(listOf(node)).filter((e) => "src" in e);
// A tile: the bordered box a click ticks, i.e. whatever holds an <img>.
const cells = (node) => walk(listOf(node)).filter(
    (e) => (e.children ?? []).some((c) => "src" in c));
const buttonsSaying = (node, text) => walk(listOf(node)).filter(
    (e) => (e.textContent ?? "").includes(text) && e._listeners?.click);
const textOf = (node) => walk(listOf(node)).map((e) => e.textContent).join(" ");

test("it lists the folder the node resolved", async () => {
    const seen = [];
    const node = await panelNode(seen, [ONE, TWO, THREE]);
    assert.equal(tiles(node).length, 3);
    assert.ok(seen.some((c) => c.route.startsWith(
        `/symbiotica/pick-list?node_id=${node.id}`)));
});

test("every tile is numbered, and the number is what you read off the screen",
     async () => {
    const node = await panelNode([], [ONE, TWO, THREE]);
    const badges = walk(listOf(node))
        .filter((e) => ["1", "2", "3"].includes(e.textContent));
    assert.deepEqual(badges.map((b) => b.textContent), ["1", "2", "3"]);
});

test("a tile draws a shrunk copy, not the render itself", async () => {
    // The grid draws every image at once; serving full renders into a strip of
    // tiles is what makes the node feel broken on a slow link.
    const node = await panelNode([], [ONE]);
    assert.ok(tiles(node)[0].src.includes("/symbiotica/pick-thumb"));
    assert.ok(tiles(node)[0].src.includes(encodeURIComponent(ONE.path)));
});

test("ticking records the FILE NAME on the node", async () => {
    // Not the position: a new render landing in the folder shifts every
    // position after it and would silently re-point every tick.
    const node = await panelNode([], [ONE, TWO]);
    fire(cells(node)[1], "click");
    assert.deepEqual(JSON.parse(widgetOf(node, "selection").value),
                     ["Spookies_00002_.png"]);
});

test("ticking twice unticks", async () => {
    const node = await panelNode([], [ONE]);
    fire(cells(node)[0], "click");
    fire(cells(node)[0], "click");
    assert.deepEqual(JSON.parse(widgetOf(node, "selection").value), []);
});

test("the ticks saved in the workflow come back ticked", async () => {
    const node = await panelNode([], [ONE, TWO], {
        selection: JSON.stringify(["Spookies_00002_.png"]),
    });
    assert.match(textOf(node), /1 ticked/);
});

test("the header says how many are in the folder", async () => {
    const node = await panelNode([], [ONE, TWO, THREE]);
    assert.match(textOf(node), /3 in folder/);
});

test("the folder being listed is on screen", async () => {
    // Which folder a picker landed on is the thing that goes wrong, so it is
    // never something to go and infer from a file browser.
    const node = await panelNode([], [ONE]);
    assert.match(textOf(node), /Food - 3 stages\/Spookies/);
});

test("a tick for a file that is no longer there is offered up to forget",
     async () => {
    const node = await panelNode([], [ONE], {
        selection: JSON.stringify(["Spookies_00001_.png", "gone.png"]),
    });
    assert.match(textOf(node), /1 missing/);
    fire(buttonsSaying(node, "missing")[0], "click");
    assert.deepEqual(JSON.parse(widgetOf(node, "selection").value),
                     ["Spookies_00001_.png"]);
});

test("untick all clears the ticks and touches no files", async () => {
    const seen = [];
    const node = await panelNode(seen, [ONE, TWO], {
        selection: JSON.stringify(["Spookies_00001_.png"]),
    });
    fire(buttonsSaying(node, "untick all")[0], "click");
    assert.deepEqual(JSON.parse(widgetOf(node, "selection").value), []);
    assert.equal(tiles(node).length, 2);
    // Nothing that could remove an image was ever called.
    assert.ok(!seen.some((c) => /clear|delete|remove/.test(c.route)));
});

test("with nothing ticked there is nothing to untick", async () => {
    const node = await panelNode([], [ONE]);
    assert.equal(buttonsSaying(node, "untick all").length, 0);
});

test("an edit picker replaces the tick instead of adding one", async () => {
    // "in edit mode i want to only be able to select one image. i am EDITING
    // so it has to be the one i am working on".
    const node = await panelNode([], [ONE, TWO, THREE], { mode: "single" });
    fire(cells(node)[1], "click");
    fire(cells(node)[2], "click");
    assert.deepEqual(JSON.parse(widgetOf(node, "selection").value),
                     ["Spookies_00003_.png"]);
});

test("an edit picker still lets you untick the one you chose", async () => {
    const node = await panelNode([], [ONE, TWO], { mode: "single" });
    fire(cells(node)[0], "click");
    fire(cells(node)[0], "click");
    assert.deepEqual(JSON.parse(widgetOf(node, "selection").value), []);
});

test("editing drops ticks left over from another asset too", async () => {
    // They are not travelling anywhere either, and "1 ticked · 3 missing" on
    // a node that emits exactly one image is noise.
    const node = await panelNode([], [ONE, TWO], {
        mode: "single",
        selection: JSON.stringify(["gone_a.png", "gone_b.png"]),
    });
    fire(cells(node)[0], "click");
    assert.deepEqual(JSON.parse(widgetOf(node, "selection").value),
                     ["Spookies_00001_.png"]);
});

test("multiple takes a set", async () => {
    const node = await panelNode([], [ONE, TWO, THREE], { mode: "multiple" });
    fire(cells(node)[0], "click");
    fire(cells(node)[2], "click");
    assert.equal(JSON.parse(widgetOf(node, "selection").value).length, 2);
});

test("the chip says what is listed and how many it takes", async () => {
    const node = await panelNode([], [ONE], { mode: "single", stage: "edits" });
    assert.match(textOf(node), /edits · one/);
});

test("with no stage the chip says it is the asset's own renders", async () => {
    const node = await panelNode([], [ONE]);
    assert.match(textOf(node), /renders/);
});

test("a picker fed by another says it is showing a shortlist", async () => {
    // "521 reads the indexed 3 images from 518" — the approved set is the
    // upstream picker's ticks, not a folder of copies.
    const node = await panelNode([], [ONE], {}, true);
    assert.match(textOf(node), /shortlist/);
});

test("an empty shortlist points upstream, not at this node", async () => {
    // Queueing this node again cannot help: what is missing is a tick on the
    // picker above.
    const node = await panelNode([], [], {}, true);
    assert.match(textOf(node), /picker above/);
});

test("an empty folder says what to do about it", async () => {
    const node = await panelNode([], []);
    assert.match(textOf(node), /queue this node/);
});

test("a failing list shows the server's reason", async () => {
    reset();
    setResponder(() => ({ ok: false, status: 403,
                          body: { error: "not inside a folder this install serves" } }));
    const node = await create("SymbioticaPick", { ...WIDGET_DEFAULTS });
    await node.onNodeCreated?.call(node);
    for (let i = 0; i < 20; i++) await tick();
    assert.match(textOf(node), /not inside a folder/);
});

test("the controls and the folder stay put while the grid scrolls", async () => {
    // With 85 thumbnails the size buttons are otherwise a scroll away from the
    // images they act on, and the folder scrolls out of sight entirely.
    const node = await panelNode([], [ONE, TWO, THREE]);
    const top = listOf(node).children[0];
    assert.match(top.style.cssText, /position:sticky/);
    assert.match(top.style.cssText, /top:0/);
    // Opaque, or the thumbnails show through the counts as they pass under.
    assert.match(top.style.cssText, /background:#/);
    const stuck = walk(top).map((e) => e.textContent).join(" ");
    assert.match(stuck, /3 in folder/);
    assert.match(stuck, /Food - 3 stages\/Spookies/);
    // The tiles are NOT in the pinned part — they are what moves.
    assert.equal(walk(top).filter((e) => "src" in e).length, 0);
});

test("the thumb size buttons change the tile size", async () => {
    const node = await panelNode([], [ONE]);
    fire(buttonsSaying(node, "L")[0], "click");
    assert.equal(node.properties.symPickThumb, "L");
    assert.match(cells(node)[0].style.cssText, /width:184px/);
});

test("a run re-lists the folder, so a new render appears", async () => {
    const seen = [];
    const node = await panelNode(seen, [ONE]);
    const before = seen.filter((c) => c.route.startsWith("/symbiotica/pick-list")).length;
    emit("symbiotica.pick", { node_id: String(node.id), count: 2 });
    await tick();
    const after = seen.filter((c) => c.route.startsWith("/symbiotica/pick-list")).length;
    assert.ok(after > before);
});

test("the state widgets are hidden", async () => {
    const node = await panelNode([], [ONE]);
    for (const name of ["selection", "view"]) {
        assert.equal(widgetOf(node, name).hidden, true, name);
    }
});

test("a graph saved before the one-wire layout keeps its values", async () => {
    // Ten-plus positional values from the old layout [get_new, asset,
    // category, selection, view, role, folder, phase, mode, stage] land on
    // the five surviving widgets by position unless onConfigure puts each
    // back on its own widget.
    const node = await panelNode([], [ONE]);
    node.onConfigure?.call(node, { widgets_values: [
        false, "Spookies", "Food", '["a.png"]', "", "", "October/Ev/Food",
        "edit", "single", "edits", "",
    ] });
    assert.equal(widgetOf(node, "save_path").value, "October/Ev/Food");
    assert.equal(widgetOf(node, "selection").value, '["a.png"]');
    assert.equal(widgetOf(node, "mode").value, "single");
    assert.equal(widgetOf(node, "stage").value, "edits");
});

test("it registers under one extension name", async () => {
    assert.ok(app.extensions.some((e) => e.name === "symbiotica.pick"));
});

test("role-named files row themselves with the role as the label", async () => {
    // `<asset>_<role>_00001_.png` groups by stem-minus-counter; the label is
    // what the keys do not share, so the asset's own name stays out of it.
    const node = await panelNode([], [
        shot("Spookies_prep_00001_.png", 1),
        shot("Spookies_ready_00001_.png", 2),
        shot("Spookies_serving_00001_.png", 3),
    ]);
    const text = textOf(node);
    for (const label of ["prep · 1", "ready · 1", "serving · 1"]) {
        assert.ok(text.includes(label), label);
    }
});

test("a single group renders flat, with no row label", async () => {
    const node = await panelNode([], [ONE, TWO]);
    assert.ok(!textOf(node).includes("base"));
});

test("a finished queue re-lists even a picker that did not run", async () => {
    // The picker's change-check answers only for its emission, so a cached
    // picker skips execution entirely — the fresh renders a queue wrote have
    // to reach the panel from the queue ending, not from the node running.
    const seen = [];
    const node = await panelNode(seen, [ONE]);
    const count = () => seen.filter(
        (c) => c.route.startsWith("/symbiotica/pick-list")).length;
    const before = count();
    emit("execution_success", {});
    for (let i = 0; i < 5; i++) await tick();
    assert.ok(count() > before);
});

test("a folder of unrelated names draws one grid, not one row each", async () => {
    // A dataset reference folder is 57 differently-named files. Rowing by role
    // gave each its own row, labelled with its own name — a list pretending to
    // be a grid. Names that merely start alike do not make an asset.
    const node = await panelNode([], [
        shot("Art Student.png", 1),
        shot("Baking Class.png", 2),
        shot("Baking With Mom Statue.png", 3),
    ]);
    const text = textOf(node);
    for (const label of ["Art Student", "Baking Class", "base"]) {
        assert.ok(!text.includes(label), `row label leaked: ${label}`);
    }
});

test("roles still row when one of them is the bare asset name", async () => {
    // `<asset>_00001_.png` beside `<asset>_prep_00001_.png`: the stem IS one of
    // the keys, and that pair is still one asset's roles.
    const node = await panelNode([], [
        shot("Spookies_00001_.png", 1),
        shot("Spookies_prep_00001_.png", 2),
    ]);
    const text = textOf(node);
    assert.ok(text.includes("base · 1"), text);
    assert.ok(text.includes("prep · 1"), text);
});

test("discard takes two clicks and posts the ticked names", async () => {
    const seen = [];
    const node = await panelNode(seen, [ONE, TWO]);
    fire(cells(node)[0], "click");
    fire(buttonsSaying(node, "discard")[0], "click");
    await tick();
    // Armed, not fired: nothing has touched the disk yet.
    assert.equal(seen.filter((c) => c.route.includes("pick-discard")).length, 0);
    fire(buttonsSaying(node, "discard 1?")[0], "click");
    for (let i = 0; i < 10; i++) await tick();
    const call = seen.find((c) => c.route.includes("pick-discard"));
    assert.ok(call, "no discard call");
    assert.deepEqual(JSON.parse(call.init.body).names, [ONE.name]);
    // A discarded file must not stay ticked — it would read as missing.
    assert.deepEqual(JSON.parse(widgetOf(node, "selection").value), []);
});

test("discard is offered only once something ticked is on screen", async () => {
    const node = await panelNode([], [ONE, TWO]);
    assert.equal(buttonsSaying(node, "discard").length, 0);
});
