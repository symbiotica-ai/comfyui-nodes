// ABOUTME: The Task panel — month, event, category and asset as a tree, the
// ABOUTME: client's own reference art beside it, and one click that is the pick.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, fire, reset, setResponder, tick } from "./comfy_stub.mjs";
import "../../web/js/asset_focus.js";

const PROJECT = "/studio-assets/imperia-bakery";
const REFS = "/studio-assets/imperia-bakery/orders/october/references";

// Calendar order, which is NOT alphabetical order: sorted, December leads and
// October is last, and the tree has to read the way the year does.
const MONTHS = ["October 2026", "November 2026", "December 2026"];
const [OCT, NOV, DEC] = MONTHS;
const FEAST = "Mini 3 — Franken-Feast";
const GHOSTS = "Mini 1 — Ghostly Goodies";

// Down the sheet, not down the alphabet, at every level: Mini 3 is the event
// at the top of the October order, Wallpaper is the first category in it, and
// Skull Wallpaper is the first row of that category. Sorted, all three would
// come out the other way round.
const EVENTS = [
    { feature: "Mini 3", eventName: "Franken-Feast", assets: [
        { assetName: "Skull Wallpaper", category: "Wallpaper",
          prompt: "a dusty rose wallpaper, skulls in the pattern",
          refFiles: ["skull-wall-a.png", "skull-wall-b.png"] },
        { assetName: "Tall Oven", category: "Appliance", canvas: "128x256",
          prompt: "a cast-iron oven, two tiles tall",
          refFiles: ["oven.png"] },
        // The padding a real sheet is full of: a row the client left blank.
        { assetName: "", category: "Wallpaper", prompt: "", refFiles: [] },
        { assetName: "Bone Wallpaper", category: "Wallpaper",
          prompt: "", refFiles: [] },
        { assetName: "   ", category: "", prompt: "", refFiles: [] },
    ] },
    { feature: "Mini 1", eventName: "Ghostly Goodies", assets: [
        { assetName: "Ghost Cupcake", category: "Food - 3 stages",
          prompt: "a cupcake with a ghost sitting on it",
          refFiles: ["ghost.png"] },
    ] },
];

// His sheet holds names with slashes in them, and two rows that flatten to the
// same slash-joined key: `Front/Till` filed under `Cashier's Desk`, and `Till`
// filed under `Cashier's Desk/Front`, are the same string and different assets.
const SLASHED = [
    { feature: "Mini 3", eventName: "Franken-Feast", assets: [
        { assetName: "Till", category: "Cashier's Desk" },
        { assetName: "Front/Till", category: "Cashier's Desk" },
        { assetName: "Till", category: "Cashier's Desk/Front" },
    ] },
];

// The two routes the picker reads: the months the project holds, and the one
// month's parse. The month is echoed back rather than switched on — which
// month was asked for is the widget's business, and the tree's.
function router(months, events) {
    return (route) => {
        if (route.startsWith("/symbiotica/list-orders")) {
            return { ok: true,
                     body: { months: months.map((label) => ({ label })) } };
        }
        if (route.startsWith("/symbiotica/parse-order")) {
            return { ok: true, body: { events, refsRoot: REFS } };
        }
        return { ok: false, status: 404, body: { error: "no route" } };
    };
}

const settle = async () => { for (let i = 0; i < 20; i++) await tick(); };

async function taskNode(widgets = {}, events = EVENTS, months = MONTHS) {
    reset();
    app.graph._nodes = [];
    setResponder(router(months, events));
    // The schema's six inputs in the schema's order. There is no `order`
    // socket: this node reads the folder and that is the whole of it.
    const node = await create("SymbioticaTask",
                              { category: "", asset: "",
                                project_path: PROJECT, month: OCT,
                                feature: "", ref: "", ...widgets });
    app.graph._nodes = [node];
    await node.onNodeCreated?.call(node);
    await settle();
    return node;
}

// --- reaching into the panel -------------------------------------------------
const widget = (node, name) => node.widgets.find((w) => w.name === name);
const panel = (node) => widget(node, "task_panel").element;
function descendants(root, out = []) {
    for (const child of root.children ?? []) {
        out.push(child);
        descendants(child, out);
    }
    return out;
}
// The boxes the shell builds, by what they ARE: it nests, so counting children
// from the top breaks the moment a box is added above them.
const part = (node, name) =>
    descendants(panel(node)).find((e) => e._symPart === name);
const rows = (node) => descendants(panel(node)).filter((e) => e._sym);
const rowFor = (node, rel) => rows(node).find((r) => r._sym.rel === rel);
// row -> [chevron, name]; the count rides in the label, so this is the whole
// of what a row says on screen.
const labelOf = (row) => row.children[1].textContent;
const labels = (node) => rows(node).map(labelOf);
const kinds = (node) => rows(node).map((r) => r._sym.kind);
// Which level a row is drawn on, read off the indent treeRow gave it.
const depthOf = (row) =>
    (Number(/padding:2px 4px 2px (\d+)px/.exec(row.style.cssText)[1]) - 4) / 10;
const button = (node, title) =>
    descendants(panel(node)).find((e) => e.title === title);

// The pane: [head[crumb, runs], strip, view[shown, …], promptHead, promptBox].
const main = (node) => part(node, "main");
const crumb = (node) => main(node).children[0].children[0].textContent;
const runs = (node) => main(node).children[0].children[1].textContent;
const strip = (node) => main(node).children[1];
const tiles = (node) => strip(node).children.filter((e) => e.src);
const tileFor = (node, file) =>
    tiles(node).find((e) => e.title.split(" — ")[0] === file);
const litTiles = (node) =>
    tiles(node).filter((e) => e.title.endsWith("sent on ref_image"));
const shown = (node) => main(node).children[2].children[0];
const textOf = (box) => (box.children ?? []).map((c) => c.textContent).join("");
const promptHead = (node) => main(node).children[3].textContent;
const promptText = (node) => textOf(main(node).children[4]);

// The search field above both panes, and the rows it lists.
const searchBox = (node) =>
    descendants(panel(node)).find((e) => e.placeholder === "Search assets…");
const hits = (node) =>
    descendants(panel(node)).filter((e) => e._symHit).map((e) => e._symHit);
const hitFor = (node, rel) =>
    descendants(panel(node)).find((e) => e._symHit === rel);

const click = async (element) => {
    fire(element, "click", { stopPropagation() {} });
    await settle();
};
const look = async (node, query) => {
    const box = searchBox(node);
    box.value = query;
    fire(box, "input", {});
    await settle();
};

// --- the node ----------------------------------------------------------------

test("the extension registered under its own name", () => {
    assert.ok(app.extensions.some((e) => e.name === "symbiotica.task"));
});

test("every widget the tree drives is still on the node, and out of the way",
     async () => {
    // The tree is the only way to set them, but they are what Python reads and
    // what a saved workflow restores — removing one shifts every value after
    // it. `project_path` stays visible: it is the one thing the tree cannot
    // tell you.
    const node = await taskNode();
    assert.deepEqual(node.widgets.map((w) => w.name),
                     ["category", "asset", "project_path", "month",
                      "feature", "ref", "📁 Read folder", "task_panel"]);
    for (const name of ["month", "feature", "category", "asset", "ref",
                        "📁 Read folder"]) {
        assert.equal(widget(node, name).hidden, true, `${name} is still drawn`);
    }
    assert.equal(widget(node, "project_path").hidden, undefined);
});

test("the panel does not pin the node's height", async () => {
    // A `computeSize` on a DOM widget becomes a floor the corner cannot drag
    // past. This one has cost days, twice.
    const node = await taskNode();
    const w = widget(node, "task_panel");
    assert.equal(w.computeSize, undefined);
    assert.equal(w.options.getMinHeight(), 60);
    // A constant, and a constant it stays: a floor read off `node.size`,
    // `scrollHeight` or `last_y` is a floor that grows with what is on screen.
    node.size = [1400, 1000];
    node.last_y = 900;
    assert.equal(w.options.getMinHeight(), 60);
});

test("no render path writes the node a height", async () => {
    // Redraw, never resize: the panel's height belongs to his drag. A render
    // may push the WIDTH back to the minimum the tree needs — never the height
    // it was given.
    const node = await taskNode();
    const sized = [];
    node.setSize = (size) => { sized.push([...size]); node.size = size; };
    node.size = [300, 420];
    node._symRenderFocus();
    await settle();
    await click(rowFor(node, `${OCT}/${FEAST}/Wallpaper`));
    assert.ok(sized.length, "the narrowed node was never widened back");
    for (const [, h] of sized) assert.equal(h, 420);
});

test("the sidebar's width and its fold ride on properties, not on widgets",
     async () => {
    // A widget for either would shift the saved values of every workflow
    // already holding the node.
    const node = await taskNode();
    const before = node.widgets.map((w) => w.name);

    await click(button(node, "Hide the tree"));
    assert.equal(node.properties.symbiotica_task_shut, true);
    assert.equal(part(node, "side").style.width, "22px");
    assert.equal(part(node, "tree").style.display, "none");
    await click(button(node, "Show the tree"));
    assert.equal(part(node, "side").style.width, "240px");
    assert.ok(rows(node).length > 0);

    const grip = descendants(panel(node)).find((e) => e.title === "Drag to resize");
    fire(grip, "pointerdown",
         { clientX: 0, stopPropagation() {}, preventDefault() {} });
    fire(window, "pointermove", { clientX: 60 });
    fire(window, "pointerup", {});
    await settle();
    assert.equal(node.properties.symbiotica_task_sidebar, 300);
    assert.equal(part(node, "side").style.width, "300px");

    assert.deepEqual(node.widgets.map((w) => w.name), before);
});

// --- the tree ----------------------------------------------------------------

test("the tree reads down the sheet, not down the alphabet", async () => {
    // Months as the server gave them, events and categories in the order they
    // first appear in the order — sorted, this list comes out backwards at
    // every one of the three levels.
    const node = await taskNode();
    assert.deepEqual(labels(node),
                     [OCT, FEAST, "Wallpaper · 2", "Appliance 1x2 · 1",
                      GHOSTS, NOV, DEC]);
});

test("the tree is four levels, each one indented under the last", async () => {
    const node = await taskNode();
    await click(rowFor(node, `${OCT}/${FEAST}/Wallpaper`));
    assert.deepEqual(labels(node),
                     [OCT, FEAST, "Wallpaper · 2", "Skull Wallpaper",
                      "Bone Wallpaper", "Appliance 1x2 · 1", GHOSTS, NOV, DEC]);
    assert.deepEqual(kinds(node),
                     ["month", "feature", "category", "asset", "asset",
                      "category", "feature", "month", "month"]);
    assert.deepEqual(rows(node).map(depthOf),
                     [0, 1, 2, 3, 3, 2, 1, 0, 0]);
});

test("the sheet's unnamed padding rows are not assets", async () => {
    // Nine of them in a real month. `assets_by_category` drops them on the
    // Python side and the panel has to show the run it describes.
    const node = await taskNode();
    await click(rowFor(node, `${OCT}/${FEAST}/Wallpaper`));
    assert.deepEqual(labels(node).filter((l) => l.startsWith("Wallpaper")),
                     ["Wallpaper · 2"]);
    assert.ok(!labels(node).some((l) => l.startsWith("uncategorised")));
    assert.ok(!labels(node).some((l) => !l.trim()));
});

test("two rows that flatten to one path stay two rows, where they belong",
     async () => {
    // This is why `walkTree` is not used here: it derives parentage from a
    // slash-joined key, so `Front/Till` under `Cashier's Desk` would be re-hung
    // under a `Cashier's Desk/Front` that is a different category entirely —
    // or swallowed by it.
    const node = await taskNode({ asset: "Till" }, SLASHED);
    assert.deepEqual(labels(node),
                     [OCT, FEAST, "Cashier's Desk · 2", "Till", "Front/Till",
                      "Cashier's Desk/Front · 1", "Till", NOV, DEC]);
    // `Front/Till` is the second asset of `Cashier's Desk`, at the asset level,
    // above the header of the category whose name its own name spells out.
    assert.deepEqual(rows(node).map(depthOf),
                     [0, 1, 2, 3, 3, 2, 3, 0, 0]);
    const shared = `${OCT}/${FEAST}/Cashier's Desk/Front/Till`;
    assert.equal(rows(node).filter((r) => r._sym.rel === shared).length, 2);
});

// --- the two groupings ---------------------------------------------------------

const groupToggle = (node) =>
    button(node, "Group by category") ?? button(node, "Group by event");

test("grouped by category, the month's events collapse into one list of types",
     async () => {
    // "so it's easier for me to test 10 decorations for example without
    // skipping through events that contain that type of asset".
    const node = await taskNode();
    await click(groupToggle(node));
    assert.deepEqual(labels(node),
                     [OCT, "Wallpaper · 2", "Appliance 1x2 · 1",
                      "Food - 3 stages · 1", NOV, DEC]);
    // No event level: a category sits directly under the month.
    assert.deepEqual(kinds(node),
                     ["month", "category", "category", "category", "month", "month"]);
    assert.deepEqual(rows(node).map(depthOf), [0, 1, 1, 1, 0, 0]);
    assert.equal(button(node, "Group by event")?.title, "Group by event",
                 "and the button says the way back");
});

test("a category gathers its assets from every event, each saying which",
     async () => {
    const node = await taskNode();
    await click(groupToggle(node));
    await click(rowFor(node, `${OCT}/Food - 3 stages`));
    assert.deepEqual(labels(node).filter((l) => l.includes("Cupcake")),
                     ["Ghost Cupcake · Mini 1"]);
});

test("taking an asset from another event moves the node to that event",
     async () => {
    // The tree does not move under him — the category view shows every event
    // at once — but the widgets do, or the queue would build the wrong one.
    const node = await taskNode({ feature: FEAST });
    await click(groupToggle(node));
    await click(rowFor(node, `${OCT}/Food - 3 stages`));
    await click(rowFor(node, `${OCT}/Food - 3 stages/${GHOSTS}/Ghost Cupcake`));
    assert.equal(widget(node, "feature").value, GHOSTS);
    assert.equal(widget(node, "asset").value, "Ghost Cupcake");
    assert.equal(widget(node, "category").value, "", "a name decides it now");
    assert.equal(crumb(node), `${OCT} / ${GHOSTS} / Food - 3 stages / Ghost Cupcake`);
});

test("an asset in the event the tree is already on is not a hop", async () => {
    const node = await taskNode({ feature: FEAST });
    await click(groupToggle(node));
    await click(rowFor(node, `${OCT}/Wallpaper`));
    await click(rowFor(node, `${OCT}/Wallpaper/${FEAST}/Skull Wallpaper`));
    assert.equal(widget(node, "feature").value, FEAST);
    assert.equal(widget(node, "asset").value, "Skull Wallpaper");
    // Clicking it again clears it, the same as in the event view.
    await click(rowFor(node, `${OCT}/Wallpaper/${FEAST}/Skull Wallpaper`));
    assert.equal(widget(node, "asset").value, "");
    assert.equal(widget(node, "category").value, "Wallpaper");
});

test("the grouping rides on a property, so a saved workflow reopens on it",
     async () => {
    const node = await taskNode();
    await click(groupToggle(node));
    assert.equal(node.properties.symbiotica_task_by_category, true);
    assert.ok(!node.widgets.some((w) => w.name?.includes("categor")
                                     && w.name !== "category"),
              "a widget here would shift every saved value after it");
    await click(groupToggle(node));
    assert.equal(node.properties.symbiotica_task_by_category, false);
    assert.deepEqual(labels(node),
                     [OCT, FEAST, "Wallpaper · 2", "Appliance 1x2 · 1", GHOSTS,
                      NOV, DEC]);
});

// --- what a click writes ------------------------------------------------------

test("clicking an event moves to it and drops everything chosen in the last one",
     async () => {
    // A category and an asset from the previous event name nothing in this
    // one, and a reference belongs to the asset it was clicked on.
    const node = await taskNode({ category: "Wallpaper",
                                  asset: "Skull Wallpaper",
                                  ref: "skull-wall-b.png" });
    await click(rowFor(node, `${OCT}/${GHOSTS}`));
    assert.equal(widget(node, "feature").value, GHOSTS);
    assert.equal(widget(node, "category").value, "");
    assert.equal(widget(node, "asset").value, "");
    assert.equal(widget(node, "ref").value, "");
    assert.deepEqual(labels(node),
                     [OCT, FEAST, GHOSTS, "Food - 3 stages · 1", NOV, DEC]);
});

test("clicking a category is the 'all assets of this type' run", async () => {
    // The label it writes is the RECIPE — the category split by its canvas —
    // because that is the name of the workflow that builds them.
    const node = await taskNode({ asset: "Skull Wallpaper" });
    await click(rowFor(node, `${OCT}/${FEAST}/Appliance 1x2`));
    assert.equal(widget(node, "category").value, "Appliance 1x2");
    assert.equal(widget(node, "asset").value, "");
    assert.equal(runs(node), "runs 1");
    assert.equal(crumb(node), "Appliance 1x2 · every asset");
});

test("clicking an asset clears the narrowing rather than setting it", async () => {
    // With a name chosen the narrowing decides nothing, and a stale one that
    // excludes the name is a hard refusal at queue time.
    const node = await taskNode({ category: "Wallpaper" });
    const rel = `${OCT}/${FEAST}/Wallpaper/Skull Wallpaper`;
    await click(rowFor(node, rel));
    assert.equal(widget(node, "asset").value, "Skull Wallpaper");
    assert.equal(widget(node, "category").value, "");
    // The level stays open on the pick alone, so the row is still on screen.
    assert.ok(rowFor(node, rel), "the row clicked went off the screen");
    assert.equal(runs(node), "runs 1");
});

test("clicking the chosen asset again falls back to its category, not to nothing",
     async () => {
    // How you get back to "all of them" without knowing what the first is
    // called — and an EMPTY narrowing would close the level the row is on,
    // taking the row you just clicked off the screen.
    const node = await taskNode({ category: "Wallpaper" });
    const rel = `${OCT}/${FEAST}/Wallpaper/Skull Wallpaper`;
    await click(rowFor(node, rel));
    await click(rowFor(node, rel));
    assert.equal(widget(node, "asset").value, "");
    assert.equal(widget(node, "category").value, "Wallpaper");
    assert.ok(rowFor(node, rel), "the row clicked went off the screen");
    assert.equal(runs(node), "runs 2");
});

test("moving to another asset drops the reference that belonged to the last one",
     async () => {
    // A filename belongs to ONE asset: carried over it would name nothing in
    // the new one's list and silently mean "the first".
    const node = await taskNode({ category: "Wallpaper",
                                  asset: "Skull Wallpaper",
                                  ref: "skull-wall-b.png" });
    await click(rowFor(node, `${OCT}/${FEAST}/Wallpaper/Bone Wallpaper`));
    assert.equal(widget(node, "asset").value, "Bone Wallpaper");
    assert.equal(widget(node, "ref").value, "");
});

// --- the pane -----------------------------------------------------------------

test("the pane is the client's own brief: the art they sent and what they wrote",
     async () => {
    const node = await taskNode({ category: "Wallpaper",
                                  asset: "Skull Wallpaper" });
    assert.equal(crumb(node), `${OCT} / ${FEAST} / Wallpaper / Skull Wallpaper`);
    assert.deepEqual(tiles(node).map((t) => t.title.split(" — ")[0]),
                     ["skull-wall-a.png", "skull-wall-b.png"]);
    assert.equal(promptText(node),
                 "a dusty rose wallpaper, skulls in the pattern");
});

test("the prompt header says the canvas the client asked for", async () => {
    const node = await taskNode({ asset: "Tall Oven" });
    assert.equal(promptHead(node), "client prompt · 128x256");
    assert.equal(promptText(node), "a cast-iron oven, two tiles tall");
});

test("an asset the client sent nothing for says so rather than drawing nothing",
     async () => {
    // An empty strip over an empty frame reads as a node that has broken.
    const node = await taskNode({ category: "Wallpaper",
                                  asset: "Bone Wallpaper" });
    assert.equal(textOf(strip(node)), "no client reference for this asset");
    assert.equal(shown(node).style.display, "none");
    assert.equal(textOf(main(node).children[2]), "nothing to show");
    assert.equal(promptText(node), "no prompt on this row");
});

test("with nothing picked the pane claims no reference", async () => {
    // The whole event is what runs, and no one file is being sent — a lit tile
    // or an image in the frame would name art `ref_image` is not carrying.
    const node = await taskNode();
    assert.equal(crumb(node), "every asset in the event");
    assert.equal(tiles(node).length, 0);
    assert.equal(shown(node).style.display, "none");
});

test("the count is the event's, not the rows that happen to be open",
     async () => {
    // A category has to be OPEN to have asset rows under it, and on a node
    // nothing is picked on, none is. Counting the rows on screen read `runs`
    // as blank and the frame as "No assets to show yet." beside a tree full of
    // categories — a node that looks like it failed to read the folder.
    const node = await taskNode();
    assert.equal(rows(node).filter((r) => r._sym.kind === "asset").length, 0);
    assert.equal(runs(node), "runs 3");
    assert.equal(textOf(main(node).children[2]), "Pick an asset in the tree.");
});

test("picking a category shows its first asset, without picking it", async () => {
    // "there is no point in showing an empty screen". The run is still every
    // asset in the category — the preview moves no widget.
    const node = await taskNode();
    await click(rowFor(node, `${OCT}/${FEAST}/Wallpaper`));
    assert.equal(widget(node, "category").value, "Wallpaper");
    assert.equal(widget(node, "asset").value, "", "a preview is not a pick");
    assert.equal(runs(node), "runs 2", "and the run is still the category's");
    assert.equal(crumb(node), "Wallpaper · every asset");
    assert.match(shown(node).src,
                 new RegExp(encodeURIComponent(`${REFS}/skull-wall-a.png`)));
    assert.equal(promptHead(node), "client prompt · Skull Wallpaper");
    assert.match(promptText(node), /dusty rose wallpaper/);
});

test("clicking a reference on a previewed asset is what picks it", async () => {
    const node = await taskNode();
    await click(rowFor(node, `${OCT}/${FEAST}/Wallpaper`));
    await click(tileFor(node, "skull-wall-b.png"));
    assert.equal(widget(node, "asset").value, "Skull Wallpaper");
    assert.equal(widget(node, "ref").value, "skull-wall-b.png");
    assert.equal(runs(node), "runs 1");
});

test("a category with nothing under it still says so", async () => {
    // The preview only stands in for a category that HAS an asset; the empty
    // state is still the answer when there is nothing to stand in.
    const node = await taskNode({ category: "Nothing Like This" });
    assert.equal(textOf(main(node).children[2]), "No assets to show yet.");
});

// --- the reference is the pick -------------------------------------------------

test("an unarmed pick lights the first reference — the one ref_image sends",
     async () => {
    const node = await taskNode({ category: "Wallpaper",
                                  asset: "Skull Wallpaper" });
    assert.deepEqual(litTiles(node).map((t) => t.title),
                     ["skull-wall-a.png — sent on ref_image"]);
    assert.match(shown(node).src,
                 new RegExp(encodeURIComponent(`${REFS}/skull-wall-a.png`)));
});

test("clicking a reference tile is the whole pick — the asset and the file",
     async () => {
    // "i click on the thing in asset focus? and it sends the freaking image
    // too" — so the thumbnail is the pick, on one click, from any row.
    const node = await taskNode({ category: "Wallpaper",
                                  asset: "Skull Wallpaper" });
    await click(tileFor(node, "skull-wall-b.png"));
    assert.equal(widget(node, "ref").value, "skull-wall-b.png");
    assert.equal(widget(node, "asset").value, "Skull Wallpaper");
    assert.equal(widget(node, "category").value, "");
    // Exactly one tile is lit, and it is the one the big view is showing.
    assert.deepEqual(litTiles(node).map((t) => t.title),
                     ["skull-wall-b.png — sent on ref_image"]);
    assert.match(shown(node).src,
                 new RegExp(encodeURIComponent(`${REFS}/skull-wall-b.png`)));
});

// --- the search ----------------------------------------------------------------

test("the search finds an asset in an event the tree is not showing", async () => {
    // The tree answers "what is in this event". A name you half-remember is a
    // different question, and the event holding it is closed.
    const node = await taskNode();
    assert.ok(!labels(node).includes("Ghost Cupcake"));
    await look(node, "cupcake");
    assert.deepEqual(hits(node),
                     [`${GHOSTS}/Food - 3 stages/Ghost Cupcake`]);
});

test("taking a search hit moves the event too, not just the asset", async () => {
    // Otherwise the node holds an asset the chosen event does not have, which
    // is a refusal at queue time.
    const node = await taskNode();
    await look(node, "cupcake");
    await click(hitFor(node, `${GHOSTS}/Food - 3 stages/Ghost Cupcake`));
    assert.equal(widget(node, "feature").value, GHOSTS);
    assert.equal(widget(node, "asset").value, "Ghost Cupcake");
    assert.equal(widget(node, "category").value, "");
    assert.equal(crumb(node),
                 `${OCT} / ${GHOSTS} / Food - 3 stages / Ghost Cupcake`);
    assert.ok(rowFor(node, `${OCT}/${GHOSTS}/Food - 3 stages/Ghost Cupcake`),
              "the tree did not follow the hit");
});

test("the search survives the fold that takes the tree away", async () => {
    // It sits ABOVE both panes, which is how this node sits once an asset is
    // picked and the pane is the whole of it.
    const node = await taskNode();
    await click(button(node, "Hide the tree"));
    assert.equal(part(node, "tree").style.display, "none");
    assert.ok(searchBox(node), "the search field went with the tree");
    await look(node, "cupcake");
    await click(hitFor(node, `${GHOSTS}/Food - 3 stages/Ghost Cupcake`));
    assert.equal(widget(node, "asset").value, "Ghost Cupcake");
});
