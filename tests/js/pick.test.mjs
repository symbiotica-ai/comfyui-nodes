// ABOUTME: The Pick node's panel — it lists the asset's own render folder as
// ABOUTME: numbered tiles, ticks record file names on the node, and nothing it
// ABOUTME: draws is a copy: every tile is a file already on disk.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, emit, fire, reset, setResponder, tick, configure,
} from "./comfy_stub.mjs";
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

// The node's widgets, in the order define_schema declares them — the order is
// what a saved workflow's values are applied by, so this list is the one thing
// here that has to track the Python schema exactly.
const WIDGET_DEFAULTS = {
    save_path: "", selection: "", view: "", mode: "multiple", stage: "",
    names: "", show: "approved", edit_selection: "",
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
    assert.match(textOf(node), /1 ✓/);
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
    configure(node, { widgets_values: [
        false, "Spookies", "Food", '["a.png"]', "", "", "October/Ev/Food",
        "edit", "single", "edits", "",
    ] });
    assert.equal(widgetOf(node, "save_path").value, "October/Ev/Food");
    assert.equal(widgetOf(node, "selection").value, '["a.png"]');
    assert.equal(widgetOf(node, "mode").value, "single");
    assert.equal(widgetOf(node, "stage").value, "edits");
});

test("a widget added after that layout goes back to its own default", async () => {
    // The old values are applied positionally BEFORE onConfigure runs, so a
    // widget appended since then is holding one of them — here the 7th value,
    // the old folder path, lands on the `shortlist` combo. ComfyUI validates a
    // combo against its option list and refuses the whole queue over a value
    // that is not in it, so a graph nobody touched would stop running.
    const node = await panelNode([], [ONE]);
    configure(node, { widgets_values: [
        false, "Spookies", "Food", '["a.png"]', "", "", "October/Ev/Food",
        "edit", "single", "edits", "",
    ] });
    assert.equal(widgetOf(node, "show").value, "approved");
});

test("the panel claims no slot in the saved values", async () => {
    // What actually broke a live graph. `LGraphNode.configure` and `.serialize`
    // read `serialize` ON THE WIDGET; the one passed in addDOMWidget's options
    // is a different flag governing the API prompt, and is not copied across. A
    // panel left serializing takes the last slot and contributes "" (a DOM
    // widget with no getValue reads as that), so the next widget appended to
    // this node takes the position the panel had and inherits its empty string.
    const node = await panelNode([], [ONE]);
    const panel = node.widgets.find((w) => w.name === "pick_panel");
    assert.equal(panel.serialize, false);
});

test("an empty value is unset too, not a choice the widget offers", async () => {
    // What the live sandbox actually sent: `shortlist: '' not in
    // ['approved','edits']`. The restore leaves the widget holding an empty
    // string rather than nothing, and an empty string is not one of the
    // options, so ComfyUI refuses the queue exactly as it does for no value.
    const node = await panelNode([], [ONE]);
    configure(node, { widgets_values: [
        "Oct/Food/Spookies", "[]", "", "single", "edits", "", "",
    ] });
    assert.equal(widgetOf(node, "show").value, "approved");
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

test("discard takes two clicks and posts the checked names", async () => {
    const seen = [];
    const node = await panelNode(seen, [ONE, TWO]);
    // Tick tile 1 (approve), then checkbox-select it for the batch bar.
    fire(cells(node)[0], "click");
    fire(buttonsSaying(node, "\u2610")[0], "click");
    fire(buttonsSaying(node, "\u2715 discard 1")[0], "click");
    await tick();
    // Armed, not fired: nothing has touched the disk yet.
    assert.equal(seen.filter((c) => c.route.includes("pick-discard")).length, 0);
    fire(buttonsSaying(node, "\u2715 discard 1?")[0], "click");
    for (let i = 0; i < 10; i++) await tick();
    const call = seen.find((c) => c.route.includes("pick-discard"));
    assert.ok(call, "no discard call");
    assert.deepEqual(JSON.parse(call.init.body).names, [ONE.name]);
    // A discarded file must not stay in either set — it would read as missing.
    assert.deepEqual(JSON.parse(widgetOf(node, "selection").value), []);
});

test("the batch bar appears only once something is checkbox-selected", async () => {
    const node = await panelNode([], [ONE, TWO]);
    assert.equal(buttonsSaying(node, "discard").length, 0);
    fire(buttonsSaying(node, "\u2610")[0], "click");
    assert.equal(buttonsSaying(node, "\u2715 discard 1").length, 1);
    assert.equal(buttonsSaying(node, "\u2713 approve 1").length, 1);
    assert.equal(buttonsSaying(node, "\u270e edit 1").length, 1);
});

test("the per-tile edit button records the file on edit_selection", async () => {
    const node = await panelNode([], [ONE, TWO]);
    const pens = walk(listOf(node)).filter(
        (e) => e.textContent === "\u270e" && e._listeners?.click);
    fire(pens[1], "click");
    assert.deepEqual(JSON.parse(widgetOf(node, "edit_selection").value),
                     ["Spookies_00002_.png"]);
    // Independent fates: the approve set is untouched.
    assert.deepEqual(JSON.parse(widgetOf(node, "selection").value || "[]"), []);
});

test("batch approve ticks every checked tile at once", async () => {
    const node = await panelNode([], [ONE, TWO, THREE]);
    // Re-query after each click: a checked box redraws as \u2714, so the
    // remaining \u2610 list shifts.
    fire(buttonsSaying(node, "\u2610")[0], "click");
    fire(buttonsSaying(node, "\u2610")[0], "click");
    fire(buttonsSaying(node, "\u2713 approve 2")[0], "click");
    assert.deepEqual(JSON.parse(widgetOf(node, "selection").value).sort(),
                     ["Spookies_00001_.png", "Spookies_00002_.png"]);
});

test("the panel declares its height the way the frontend actually asks", async () => {
    // ComfyUI 1.4x lays a DOM widget out through `computeLayoutSize`, which
    // reads ONLY these options. The legacy `computeSize` is ignored there, so
    // a panel that sets nothing else reports a 50px minimum and no maximum:
    // the element keeps its content size and draws outside the node, which is
    // fifty tiles spilling across his canvas.
    const node = await panelNode([], [ONE, TWO]);
    const panel = node.widgets.find((w) => w.name === "pick_panel");
    assert.equal(typeof panel.options.getMinHeight, "function");
});

test("the panel never pins the node's minimum height", async () => {
    // LiteGraph builds a node's MINIMUM height by summing its widgets, and per
    // widget it prefers `computeSize` over `computeLayoutSize`:
    //     if (w.computeSize) t += w.computeSize(width)[1]
    //     else if (w.computeLayoutSize) t += computeLayoutSize(node).minHeight
    // So a DOM panel that answers computeSize with its content — or with the
    // space below itself — makes the minimum equal what is on screen, and the
    // corner drags taller but never shorter. It must declare a small constant
    // floor and no computeSize at all.
    const node = await panelNode([], [ONE, TWO, THREE]);
    const panel = node.widgets.find((w) => w.name === "pick_panel");
    const list = panel.element.children[0];
    list.scrollHeight = 5000;              // a folder of fifty images

    assert.equal(panel.computeSize, undefined,
                 "computeSize overrides the layout and pins the minimum");
    const floor = panel.options.getMinHeight();
    assert.ok(floor <= 60, `floor ${floor} is not a small constant`);
    // …and it stays the floor whatever the node or the listing does.
    node.size[1] = 900;
    assert.equal(panel.options.getMinHeight(), floor);
    node.size[1] = 200;
    assert.equal(panel.options.getMinHeight(), floor);
});

// --- hover preview -----------------------------------------------------------
// A 64px tile cannot be judged, and opening a tab per render loses the grid.
const frames = () => globalThis.document.body.children.filter(
    (c) => (c.children ?? []).some((k) => "src" in k));
const shown = () => frames().find((f) => f.style.display === "block");
// The hover is deliberately delayed so sweeping across a grid does not flash a
// preview per tile; the tests have to outwait that.
const rest = () => new Promise((r) => setTimeout(r, 220));

async function hover(cell, rect = { left: 100, top: 400, right: 164,
                                    bottom: 464, width: 64, height: 64 }) {
    cell._rect = rect;
    fire(cell, "pointerenter");
    await rest();
}

test("resting on a tile floats a bigger copy of it", async () => {
    const node = await panelNode([], [ONE, TWO]);
    assert.equal(shown(), undefined, "nothing floats before a hover");
    await hover(cells(node)[1]);

    const frame = shown();
    assert.ok(frame, "hovering a tile shows no preview");
    const img = frame.children[0];
    assert.ok(img.src.includes(encodeURIComponent(TWO.path)),
              "the preview is not the image being hovered");
    // Big enough to judge by: the grid tiles are 64–184px.
    const px = Number(new URLSearchParams(img.src.split("?")[1]).get("px"));
    assert.ok(px >= 512, `preview asked for ${px}px, which is still a thumbnail`);
    // The caption is the tooltip, centred under the image: the browser's own
    // title box arrives a second later and lands ON the render being judged.
    const caption = frame.children[1];
    assert.match(caption.style.cssText, /text-align:center/);
    assert.match(caption.children[0].textContent, /Spookies_00002_\.png/);
    assert.match(caption.children[1].textContent, /double-click to open full size/);
    assert.equal(cells(node)[1].title, undefined,
                 "a title tooltip would cover the preview it duplicates");
});

test("the preview is a resize, never the full render", async () => {
    // Same rule as the grid: /symbiotica/local-image on hover would pull a
    // 20MB PNG per tile the pointer crosses.
    const node = await panelNode([], [ONE]);
    await hover(cells(node)[0]);
    const img = shown().children[0];
    assert.ok(img.src.includes("/symbiotica/pick-thumb"));
    assert.ok(!img.src.includes("/symbiotica/local-image"));
});

test("the thumbnail already on screen fills the frame while the big one loads",
     async () => {
    const node = await panelNode([], [ONE]);
    const tileSrc = tiles(node)[0].src;
    await hover(cells(node)[0]);
    assert.ok(shown().style.backgroundImage.includes(tileSrc),
              "the frame is empty until the full-size image lands");
});

test("the frame is drawn beside the tile, and flips when there is no room",
     async () => {
    const node = await panelNode([], [ONE]);
    await hover(cells(node)[0]);
    const right = Number.parseInt(shown().style.left, 10);
    assert.ok(right > 164, `frame at ${right} overlaps the tile it came from`);

    fire(cells(node)[0], "pointerleave");
    // Hard against the right edge of a 1440px window: beside it would be off
    // the screen, so it goes to the other side.
    await hover(cells(node)[0], { left: 1400, top: 400, right: 1430,
                                  bottom: 464, width: 30, height: 64 });
    const flipped = Number.parseInt(shown().style.left, 10);
    assert.ok(flipped >= 8 && flipped < 1400,
              `frame at ${flipped} is off the right of the window`);
});

test("the frame never draws off the window", async () => {
    const node = await panelNode([], [ONE]);
    await hover(cells(node)[0], { left: 100, top: 880, right: 164,
                                  bottom: 900, width: 64, height: 20 });
    const frame = shown();
    const top = Number.parseInt(frame.style.top, 10);
    const height = Number.parseInt(frame.style.height, 10);
    assert.ok(top >= 8, `frame top ${top} is above the window`);
    assert.ok(top + height <= 900 - 8 || height >= 900 - 16,
              `frame bottom ${top + height} is below the window`);
});

test("leaving the tile takes the preview away", async () => {
    const node = await panelNode([], [ONE]);
    await hover(cells(node)[0]);
    assert.ok(shown());
    fire(cells(node)[0], "pointerleave");
    assert.equal(shown(), undefined);
});

test("ticking takes the preview away with the tile it belonged to", async () => {
    // The click re-renders the grid, so the tile under the frame is thrown
    // away — the frame would be left floating beside nothing.
    const node = await panelNode([], [ONE]);
    await hover(cells(node)[0]);
    fire(cells(node)[0], "click");
    assert.equal(shown(), undefined);
});

test("a preview is not shown until the pointer rests", async () => {
    const node = await panelNode([], [ONE, TWO, THREE]);
    for (const cell of cells(node)) fire(cell, "pointerenter");
    assert.equal(shown(), undefined, "sweeping the grid flashed a preview");
    await rest();
});

test("one frame is reused, however many tiles are hovered", async () => {
    // Every tile attaching its own body-level node is how a grid leaks a
    // hundred orphans onto the page.
    const node = await panelNode([], [ONE, TWO, THREE]);
    for (const cell of cells(node)) {
        await hover(cell);
        fire(cell, "pointerleave");
    }
    assert.equal(frames().length, 1);
});


// --- nothing paints outside the node ----------------------------------------
// A flex row whose content is wider than the node resolves its width against a
// shrink-to-fit parent and paints over the canvas behind it. This has now been
// fixed in three panels; the test is here so it stops coming back.

const CONTAINED = [/width:100%/, /box-sizing:border-box/, /overflow:hidden/];

test("the panel and every band across it stay inside the node", async () => {
    const node = await panelNode([], [ONE, TWO, THREE]);
    const list = listOf(node);
    const bands = [list, ...list.children];          // sticky header, grid rows
    for (const band of bands) {
        for (const rule of CONTAINED) {
            assert.match(band.style.cssText, rule);
        }
    }
});

test("the header row wraps rather than pushing the node wide", async () => {
    // Its content is a count, a chip, three size buttons, a reload and two
    // more — more than fits a narrow picker.
    const node = await panelNode([], [ONE], { selection: JSON.stringify([ONE.name]) });
    const head = listOf(node).children[0].children[0];
    assert.match(head.style.cssText, /flex-wrap:wrap/);
    for (const rule of CONTAINED) assert.match(head.style.cssText, rule);
});

test("the batch bar is contained too", async () => {
    const node = await panelNode([], [ONE, TWO]);
    // Tick a tile's checkbox to summon the bar.
    const cells = walk(listOf(node)).filter((e) => e.className === "sym-pick-cell");
    const box = walk(cells[0]).find((e) => e.type === "checkbox");
    if (box) {
        box.checked = true;
        fire(box, "change", { target: box });
        for (let i = 0; i < 5; i++) await tick();
    }
    const bars = walk(listOf(node)).filter(
        (e) => /border-top/.test(e.style?.cssText ?? ""));
    for (const bar of bars) {
        for (const rule of CONTAINED) assert.match(bar.style.cssText, rule);
    }
});
