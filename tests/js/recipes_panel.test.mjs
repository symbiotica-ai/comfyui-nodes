// ABOUTME: The Recipes panel — shared and the recipes as a sidebar, the picked
// ABOUTME: one's cells as a pane, and a caret that survives a newly painted node.
import assert from "node:assert/strict";
import { after, test } from "node:test";

import { app, calls, create, fire, reset, setResponder, tick } from "./comfy_stub.mjs";
import "../../web/js/recipes.js";

const TEMPLATE = "symtest-fixture.json";
const WORKFLOW = `workflows/${TEMPLATE}`;

// The server's own answer for this template, drift and all: it calls `grid`
// a SCALAR (its first widget is a number) while every recipe stores a dict in
// it. Four of his nineteen slots read like this, and a text box drawn over the
// object flattens it on the first save.
const SLOTS = [
    { key: "KSampler", kind: "scalar", default: 1, widgets: 7 },
    { key: "backdrop", kind: "scalar", default: "floor-1x1.png", widgets: 1 },
    { key: "grid", kind: "scalar", default: 1024, widgets: 3 },
    { key: "pre_flip", kind: "toggle", default: false, widgets: 4 },
    { key: "preamble", kind: "scalar", default: "a bakery", widgets: 1 },
];

const PROJECT = () => ({
    template: TEMPLATE, output: "out", workflow_prefix: "dev-symtest-",
    match_color: "purple",
    shared: { backdrop: "floor-1x1.png", preamble: "a bakery",
              grid: { width: 1024, height: 1024 } },
    recipes: {
        appliance1x2: { backdrop: "floor-1x2.png", pre_flip: true,
                        grid: { width: 1024, height: 2048 } },
        appliance1x1: { backdrop: "floor-1x1.png" },
        zebra: {},
    },
});

const OTHERS = [
    { name: "symtest-fixture", template: TEMPLATE },
    { name: "imperia-bakery", template: "recipe-test/bakery-template-test.json" },
];

// What the routes were asked to write, so a save is judged on the project it
// sent rather than on the fact that it posted something.
const posted = [];
const toasts = [];
// What the name dialog answers when `new recipe` asks.
const asked = { answer: null };

function router({ project = PROJECT(), slots = SLOTS, projects = OTHERS,
                  saveFails = false } = {}) {
    return (route, _n, init) => {
        const body = init?.body ? JSON.parse(init.body) : null;
        if (route === "/symbiotica/recipes") return { ok: true, body: { projects } };
        if (route === "/symbiotica/recipes/save") {
            posted.push(body);
            return saveFails
                ? { ok: false, status: 400, body: { error: "disk is full" } }
                : { ok: true, body: { saved: body.name } };
        }
        if (route === "/symbiotica/recipes/generate") {
            posted.push({ generate: body });
            return { ok: true, body: { template: TEMPLATE, written: [] } };
        }
        if (route === "/symbiotica/recipes/new") {
            posted.push({ "new": body });
            return { ok: true, body: { name: "symtest-fixture",
                                       project: { ...PROJECT(), recipes: {} },
                                       slots } };
        }
        if (route.startsWith("/symbiotica/recipes/")) {
            return { ok: true, body: { project, slots } };
        }
        return { ok: false, status: 404, body: { error: "no route" } };
    };
}

const settle = async () => { for (let i = 0; i < 20; i++) await tick(); };

// A node painted the match colour is a slot, under its own title.
const painted = (title, widgets = [], extra = {}) => ({
    title, mode: 0, color: "#323", bgcolor: "#535", inputs: [],
    widgets: widgets.map(([name, value]) => ({ name, value })), ...extra });

const CANVAS = () => [
    painted("preamble", [["String", "a bakery"]]),
    painted("backdrop", [["String", "floor-1x1.png"]]),
    painted("grid", [["width", 1024], ["height", 1024]]),
    painted("pre_flip?", [["flip", "y"]], { mode: 4 }),
    painted("KSampler", [["seed", 1], ["steps", 20]]),
];

async function recipeNode({ nodes = CANVAS(), path = WORKFLOW,
                            draw = true, ...opts } = {}) {
    reset();
    posted.length = 0;
    toasts.length = 0;
    app.graph.nodes = nodes;
    app.graph._nodes = nodes;
    app.extensionManager = {
        workflow: { activeWorkflow: path ? { path } : null },
        toast: { add: (t) => toasts.push(t) },
        dialog: { prompt: async () => asked.answer },
    };
    setResponder(router(opts));
    const node = await create("SymbioticaRecipe",
                              { recipe: "", match_color: "purple" });
    // The `recipe` name arrives on a wire on his canvas. An input that names
    // the widget is the same read one hop shorter, and it is what lets a test
    // move the wire.
    node.inputs = [{ name: "recipe", widget: { name: "recipe" }, link: null }];
    await node.onNodeCreated?.call(node);
    await settle();
    if (draw) { node.onDrawForeground?.(); await settle(); }
    made.push(node);
    return node;
}

// `auto` defers a save by a second. A test that leaves one pending keeps the
// process alive long past its last assertion, and the runner kills the FILE.
const made = [];
after(() => {
    for (const n of made) {
        if (n._symAuto?.timer) clearTimeout(n._symAuto.timer);
        if (n._symRebuild?.timer) clearTimeout(n._symRebuild.timer);
    }
});

// --- reaching into the panel -------------------------------------------------
const widget = (node, name) => node.widgets.find((w) => w.name === name);
const panel = (node) => widget(node, "recipe_panel").element;
function descendants(root, out = []) {
    for (const child of root.children ?? []) {
        out.push(child);
        descendants(child, out);
    }
    return out;
}
const part = (node, name) =>
    descendants(panel(node)).find((e) => e._symPart === name);
const rows = (node) => descendants(panel(node)).filter((e) => e._sym);
const rowFor = (node, rel) => rows(node).find((r) => r._sym.rel === rel);
// The name cell: a row with a lead (a category with nothing stored) puts the
// mark first, and the mark holds no text.
const labelOf = (row) =>
    [...row.children].find((c) => c.textContent)?.textContent ?? "";
const labels = (node) => rows(node).map(labelOf);
const main = (node) => part(node, "main");
const button = (node, title) =>
    descendants(panel(node)).find((e) => e.title === title);
const word = (node, text) =>
    descendants(panel(node)).find((e) => e.textContent === text
        && String(e.style.cssText).includes("cursor:pointer"));

// The pane's rows, by the slot key each one is for.
const cells = (node) => descendants(panel(node)).filter((e) => e._symRow);
const cellKeys = (node) => cells(node).map((e) => e._symRow);
const cellFor = (node, key) => cells(node).find((e) => e._symRow === key);
const fieldsOf = (node, key) =>
    descendants(cellFor(node, key) ?? { children: [] }).filter((e) => e._symCell);
const fieldFor = (node, key, name = null) =>
    fieldsOf(node, key).find((e) => e._symCell.name === name);
const headerField = (node, key) =>
    descendants(panel(node)).find((e) => e._symField === key);
// The status line: the one element in the pane's foot.
const statusText = (node) =>
    main(node).children[main(node).children.length - 1].children[0].textContent;
const emptyText = (box) =>
    (box.children ?? []).map((c) => c.textContent).join("");

const click = async (element) => {
    fire(element, "click", { stopPropagation() {} });
    await settle();
};
const type = async (field, value) => {
    fire(field, "focus", {});
    field.value = value;
    fire(field, "input", {});
    await settle();
};
const draw = async (node) => { node.onDrawForeground?.(); await settle(); };

// =============================================================== structure ==

test("the extension registered under its own name", () => {
    assert.ok(app.extensions.some((e) => e.name === "symbiotica.recipes"));
});

test("all eight widgets are still on the node, in order, before and after a render",
     async () => {
    // A saved workflow restores widget values BY POSITION. Drop the buttons
    // and `auto`'s false lands on `match_color`.
    const order = ["recipe", "match_color", "auto", "new project",
                   "capture recipe", "save project", "generate workflows",
                   "delete project", "recipe_panel"];
    const node = await recipeNode();
    assert.deepEqual(node.widgets.map((w) => w.name), order);
    await click(rowFor(node, "appliance1x2"));
    await draw(node);
    assert.deepEqual(node.widgets.map((w) => w.name), order);
    // The ones the head drives are hidden, not removed; `recipe` and
    // `match_color` stay visible — the panel cannot tell you either.
    for (const name of ["auto", "new project", "capture recipe", "save project",
                        "generate workflows", "delete project"]) {
        assert.equal(widget(node, name).hidden, true, `${name} is still drawn`);
    }
    assert.equal(widget(node, "recipe").hidden, undefined);
    assert.equal(widget(node, "match_color").hidden, undefined);
});

test("the buttons still write one null each into the saved values", async () => {
    // `serializeValue` returning undefined is what holds the positions: the
    // options flag is inert, and the pair is not a tidy-up waiting to happen.
    const node = await recipeNode();
    for (const name of ["new project", "capture recipe", "save project",
                        "generate workflows", "delete project"]) {
        const w = widget(node, name);
        assert.equal(w.options.serialize, false);
        assert.equal(w.serializeValue(), undefined);
    }
});

test("the panel does not pin the node's height", async () => {
    // A `computeSize` on a DOM widget becomes a floor the corner cannot drag
    // past. This one has cost days, twice.
    const node = await recipeNode();
    const w = widget(node, "recipe_panel");
    assert.equal(w.computeSize, undefined);
    assert.equal(w.options.getMinHeight(), 60);
    // A constant, and a constant it stays: a floor read off `node.size`,
    // `scrollHeight` or `last_y` is a floor that grows with what is on screen.
    node.size = [1600, 1200];
    node.last_y = 1100;
    assert.equal(w.options.getMinHeight(), 60);
    assert.equal(w.name, "recipe_panel");
    assert.equal(w.type, "sym_recipe");
});

test("no render path writes the node a height", async () => {
    // Redraw, never resize. A render may push the WIDTH back to what this pane
    // needs — never the height it was given.
    const node = await recipeNode();
    const sized = [];
    node.setSize = (size) => { sized.push([...size]); node.size = size; };
    node.size = [300, 420];
    await click(rowFor(node, "appliance1x2"));
    await click(rowFor(node, "shared"));
    await type(fieldFor(node, "preamble"), "x");
    await draw(node);
    assert.ok(sized.length, "the narrowed node was never widened back");
    for (const [, h] of sized) assert.equal(h, 420);
    for (const [w] of sized) assert.equal(w, 760);
});

test("the sidebar's width, its fold and which row is picked ride on properties",
     async () => {
    // A widget for any of them would shift the saved values of every workflow
    // already holding the node.
    const node = await recipeNode();
    const before = node.widgets.map((w) => w.name);

    await click(button(node, "Hide the tree"));
    assert.equal(node.properties.symbiotica_recipes_shut, true);
    assert.equal(part(node, "side").style.width, "22px");
    assert.equal(part(node, "tree").style.display, "none");
    await click(button(node, "Show the tree"));
    assert.equal(part(node, "side").style.width, "180px");

    const grip = button(node, "Drag to resize");
    fire(grip, "pointerdown",
         { clientX: 0, stopPropagation() {}, preventDefault() {} });
    fire(window, "pointermove", { clientX: 40 });
    fire(window, "pointerup", {});
    await settle();
    assert.equal(node.properties.symbiotica_recipes_sidebar, 220);

    await click(rowFor(node, "appliance1x2"));
    assert.equal(node.properties.symbiotica_recipes_pick, "appliance1x2");
    assert.deepEqual(node.widgets.map((w) => w.name), before);
});

// ================================================================= sidebar ==

test("the sidebar is the project, shared pinned, then the recipes sorted",
     async () => {
    const node = await recipeNode();
    assert.deepEqual(labels(node), [
        "symtest-fixture",
        "shared · 3", "appliance1x1 · 1", "appliance1x2 · 3", "zebra · 0",
        "other projects",
        "imperia-bakery — open recipe-test/bakery-template-test.json",
    ]);
    // The count is the recipe's OWN cells, not its resolved total:
    // appliance1x1 overrides one value and takes the other two from shared.
    assert.deepEqual(rows(node).map((r) => r._sym.kind), [
        "project", "shared", "recipe", "recipe", "recipe", "caption", "other"]);
});

test("a project this workflow is not the template of is not selectable",
     async () => {
    // The project is RESOLVED, not chosen. The row says which workflow to open
    // instead, and clicking it does nothing at all.
    const node = await recipeNode();
    const other = rowFor(node, "other:imperia-bakery");
    assert.equal(other._listeners?.click, undefined);
    await click(other);
    assert.equal(node.properties.symbiotica_recipes_pick, "shared");
});

test("picking a recipe shows it AND pulls its values onto the canvas",
     async () => {
    // "Clicking any of them should pull the values of that task/recipe" — the
    // same thing the wire does when auto is on, without having to reach for
    // the load button. The `recipe` widget is untouched: the wire owns it.
    const node = await recipeNode();
    const backdropNode = () =>
        app.graph.nodes.find((n) => n.title === "backdrop").widgets[0].value;
    await click(rowFor(node, "appliance1x2"));
    assert.equal(fieldFor(node, "backdrop").value, "floor-1x2.png");
    assert.equal(widget(node, "recipe").value, "");
    assert.equal(backdropNode(), "floor-1x2.png");
    assert.match(statusText(node), /^Loaded appliance1x2 onto the canvas/);
    // The second one, which is where the bug is: switching again must show the
    // OTHER recipe's cells, not the first one's — and pull them too.
    await click(rowFor(node, "appliance1x1"));
    assert.equal(fieldFor(node, "backdrop").value, "floor-1x1.png");
    assert.equal(fieldFor(node, "pre_flip").value, "");
    assert.equal(backdropNode(), "floor-1x1.png");
});

test("the project row is settings, not a column: picking it pulls nothing",
     async () => {
    const node = await recipeNode();
    await click(rowFor(node, "appliance1x2"));
    const pulled = app.graph.nodes.map((n) => n.widgets.map((w) => w.value));
    await click(rowFor(node, ":project"));
    assert.deepEqual(app.graph.nodes.map((n) => n.widgets.map((w) => w.value)),
                     pulled);
});

test("the search finds a recipe the tree would make you scroll for", async () => {
    const node = await recipeNode();
    const box = descendants(panel(node))
        .find((e) => e.placeholder === "Search recipes…");
    box.value = "zeb";
    fire(box, "input", {});
    await settle();
    const hit = descendants(panel(node)).find((e) => e._symHit === "zebra");
    assert.ok(hit, "zebra was not offered");
    await click(hit);
    assert.equal(node.properties.symbiotica_recipes_pick, "zebra");
});

// ==================================================================== pane ==

test("the project row's pane is template, output and prefix over shared's values",
     async () => {
    // `template` is what the project is resolved by, and the only repair after
    // a Save As — so it has to stay reachable.
    const node = await recipeNode();
    await click(rowFor(node, ":project"));
    assert.equal(headerField(node, "template").value, TEMPLATE);
    assert.equal(headerField(node, "output").value, "out");
    assert.equal(headerField(node, "workflow_prefix").value, "dev-symtest-");
    assert.deepEqual(cellKeys(node),
                     ["KSampler", "backdrop", "grid", "pre_flip", "preamble"]);
    assert.equal(fieldFor(node, "backdrop").value, "floor-1x1.png");
    // Typed into, they reach the saved project.
    await type(headerField(node, "template"), "moved/elsewhere.json");
    await click(word(node, "save project"));
    assert.equal(posted.at(-1).project.template, "moved/elsewhere.json");
});

test("the header fields are only on the project row", async () => {
    const node = await recipeNode();
    const box = headerField(node, "template").parent.parent;
    assert.equal(box.style.display, "none");
    await click(rowFor(node, ":project"));
    assert.equal(box.style.display, "");
    await click(rowFor(node, "appliance1x2"));
    assert.equal(box.style.display, "none");
});

test("a recipe shows what it inherits as the placeholder, and an empty cell takes it",
     async () => {
    // Lose this and capture writes every value into every recipe: the file
    // balloons, and a later edit to shared silently stops reaching them.
    const node = await recipeNode();
    await click(rowFor(node, "appliance1x1"));
    const cell = fieldFor(node, "preamble");
    assert.equal(cell.value, "", "appliance1x1 has no preamble of its own");
    assert.equal(cell.placeholder, "a bakery");
    // Shared's own placeholder is the template's value, not itself.
    await click(rowFor(node, "shared"));
    assert.equal(fieldFor(node, "preamble").value, "a bakery");
    assert.equal(fieldFor(node, "preamble").placeholder, "a bakery");
});

test("a row can be cleared back to what it inherits", async () => {
    const node = await recipeNode();
    await click(rowFor(node, "appliance1x2"));
    const wipe = descendants(cellFor(node, "backdrop"))
        .find((e) => String(e.title).startsWith("Clear"));
    assert.equal(wipe.style.visibility, "visible");
    await click(wipe);
    assert.equal(fieldFor(node, "backdrop").value, "");
    assert.equal(fieldFor(node, "backdrop").placeholder, "floor-1x1.png");
    assert.equal(wipe.style.visibility, "hidden");
    await click(word(node, "save project"));
    assert.equal("backdrop" in posted.at(-1).project.recipes.appliance1x2, false);
});

test("a cell that holds an object gets the sub-grid, whatever the slot's kind says",
     async () => {
    // The server calls `grid` a scalar — its first widget is a number — while
    // every recipe stores a dict in it. A text box over that object flattens
    // an 1100-character prompt dict on the first save.
    const node = await recipeNode();
    await click(rowFor(node, "appliance1x2"));
    assert.equal(widget(node, "recipe_panel") && SLOTS[2].kind, "scalar");
    assert.deepEqual(fieldsOf(node, "grid").map((f) => f._symCell.name),
                     ["width", "height"]);
    assert.equal(fieldFor(node, "grid", "width").value, "1024");
    assert.equal(fieldFor(node, "grid", "height").value, "2048");
    // One widget at a time, inside the JSON cell.
    await type(fieldFor(node, "grid", "height"), "3072");
    await click(word(node, "save project"));
    assert.deepEqual(posted.at(-1).project.recipes.appliance1x2.grid,
                     { width: 1024, height: 3072 });
    // And a scalar that really is one keeps its text box.
    assert.deepEqual(fieldsOf(node, "backdrop").map((f) => f._symCell.name),
                     [null]);
});

test("a dict row inherits per key, not per cell", async () => {
    const node = await recipeNode();
    await click(rowFor(node, "appliance1x1"));
    // appliance1x1 stores no grid at all, so every key shows shared's.
    assert.equal(fieldFor(node, "grid", "width").value, "");
    assert.equal(fieldFor(node, "grid", "width").placeholder, "1024");
    assert.equal(fieldFor(node, "grid", "height").placeholder, "1024");
});

// ================================================== the caret and the canvas ==

test("painting a node while typing keeps the caret and still grows the row",
     async () => {
    // The panel rebuilt on every draw tick, so a node painted mid-word took
    // the field away with it. The tree and the pane are separate paths now:
    // a new key is INSERTED beside the rows already on screen.
    const node = await recipeNode();
    await click(rowFor(node, "shared"));
    const cell = fieldFor(node, "preamble");
    fire(cell, "focus", {});
    const long = "a hand-painted isometric bakery appliance, ".repeat(48);
    cell.value = long;
    fire(cell, "input", {});
    await settle();

    app.graph.nodes = [...CANVAS(), painted("lighting", [["String", "warm"]])];
    await draw(node);

    assert.equal(fieldFor(node, "preamble"), cell, "the field was re-created");
    assert.equal(cell.value, long);
    assert.ok(cellKeys(node).includes("lighting"), "the painted node got no row");
    // In the slot list's order, not stuck on the end.
    assert.deepEqual(cellKeys(node),
                     ["KSampler", "backdrop", "grid", "lighting", "pre_flip",
                      "preamble"]);
    assert.equal(labels(node).includes("shared · 3"), true);
});

test("unpainting a node takes its row away and leaves the others alone",
     async () => {
    const node = await recipeNode();
    await click(rowFor(node, "shared"));
    const held = fieldFor(node, "backdrop");
    app.graph.nodes = CANVAS().filter((n) => n.title !== "preamble");
    await draw(node);
    assert.equal(cellKeys(node).includes("preamble"), false);
    assert.equal(fieldFor(node, "backdrop"), held, "the other rows were rebuilt");
});

test("the rows are read from the ROOT graph, not from the subgraph on screen",
     async () => {
    // Inside a subgraph the canvas graph IS that subgraph: the table would
    // shrink to its nodes and the next save would write the shrunken table
    // over the file — every other recipe's values gone, silently.
    const node = await recipeNode();
    await click(rowFor(node, "shared"));
    const before = cellKeys(node);
    const inner = { nodes: [painted("inner-only", [["String", "x"]])],
                    rootGraph: app.graph };
    const original = Object.getOwnPropertyDescriptor(app.canvas, "graph");
    Object.defineProperty(app.canvas, "graph",
                          { get: () => inner, configurable: true });
    try {
        await draw(node);
        assert.deepEqual(cellKeys(node), before);
        await click(word(node, "save project"));
        assert.deepEqual(Object.keys(posted.at(-1).project.shared).sort(),
                         ["backdrop", "grid", "preamble"]);
    } finally {
        Object.defineProperty(app.canvas, "graph", original);
    }
});

test("a cell that does not parse still lets a newly painted node become a row",
     async () => {
    // Nothing is parsed on the slot-change path. A round trip through the
    // project threw, and the canvas went unread.
    const node = await recipeNode();
    await click(rowFor(node, "shared"));
    await type(fieldFor(node, "pre_flip"), "maybe");
    app.graph.nodes = [...CANVAS(), painted("lighting", [["String", "warm"]])];
    await draw(node);
    assert.ok(cellKeys(node).includes("lighting"));
    // And the save names the row and the column it could not read.
    await click(word(node, "save project"));
    assert.equal(posted.length, 0, "a bad cell was written to the file");
});

// ============================================================ what it writes ==

test("capture writes only what differs from shared, into the selected recipe",
     async () => {
    const node = await recipeNode();
    await click(rowFor(node, "appliance1x1"));
    app.graph.nodes = [
        painted("preamble", [["String", "a bakery"]]),
        painted("backdrop", [["String", "desk.png"]]),
        painted("grid", [["width", 1024], ["height", 1024]]),
        painted("pre_flip?", [["flip", "y"]]),
        painted("KSampler", [["seed", 1], ["steps", 20]]),
    ];
    await draw(node);
    await click(word(node, "capture"));
    assert.equal(fieldFor(node, "backdrop").value, "desk.png");
    // preamble and grid are the shared values, so the recipe keeps nothing.
    assert.equal(fieldFor(node, "preamble").value, "");
    assert.equal(fieldFor(node, "grid", "width").value, "");
    // A second capture is the one that used to double up.
    await click(word(node, "capture"));
    assert.equal(fieldFor(node, "backdrop").value, "desk.png");
    assert.equal(fieldFor(node, "preamble").value, "");
});

test("load puts the selected recipe onto the canvas and says how many slots",
     async () => {
    const node = await recipeNode();
    await click(rowFor(node, "appliance1x2"));
    await click(word(node, "load"));
    const backdrop = app.graph.nodes.find((n) => n.title === "backdrop");
    const flip = app.graph.nodes.find((n) => n.title === "pre_flip?");
    assert.equal(backdrop.widgets[0].value, "floor-1x2.png");
    assert.equal(flip.mode, 0);
    assert.match(statusText(node), /Loaded appliance1x2 onto the canvas/);
});

test("renaming a recipe carries its cells, re-sorts, and refuses a name taken",
     async () => {
    const node = await recipeNode();
    await click(rowFor(node, "appliance1x2"));
    const name = descendants(panel(node))
        .find((e) => String(e.title).startsWith("Recipe:"));
    name.value = "Cashier's Desk 1x1";
    fire(name, "change", {});
    await settle();
    assert.deepEqual(labels(node).slice(1, 5),
                     ["shared · 3", "appliance1x1 · 1", "cashiers-desk-1x1 · 3",
                      "zebra · 0"]);
    assert.equal(node.properties.symbiotica_recipes_pick, "cashiers-desk-1x1");
    assert.equal(fieldFor(node, "backdrop").value, "floor-1x2.png");

    name.value = "appliance1x1";
    fire(name, "change", {});
    await settle();
    assert.equal(toasts.at(-1).summary, "Name taken");
    assert.equal(name.value, "cashiers-desk-1x1");
});

test("removing a recipe takes it out in memory until save", async () => {
    const node = await recipeNode();
    await click(rowFor(node, "zebra"));
    await click(button(node, "Remove this recipe"));
    assert.equal(rowFor(node, "zebra"), undefined);
    assert.equal(node.properties.symbiotica_recipes_pick, "shared");
    await click(word(node, "save project"));
    assert.deepEqual(Object.keys(posted.at(-1).project.recipes),
                     ["appliance1x1", "appliance1x2"]);
});

test("delete project takes two presses", async () => {
    // An icon with no confirm deletes a 22 KB project on one mis-click.
    const node = await recipeNode();
    const button2 = word(node, "delete project");
    await click(button2);
    assert.match(statusText(node), /Press delete project again/);
    assert.ok(!calls.some((c) => c.startsWith("/symbiotica/recipes/symtest-fixture")
                                 && c !== "/symbiotica/recipes/symtest-fixture"));
    const before = calls.length;
    await click(button2);
    assert.ok(calls.length > before, "the second press deleted nothing");
    assert.equal(toasts.at(-1).summary, 'Deleted project "symtest-fixture"');
});

test("generate saves first, because the route re-reads the project from disk",
     async () => {
    const node = await recipeNode();
    await click(rowFor(node, "shared"));
    await type(fieldFor(node, "preamble"), "a changed bakery");
    await click(word(node, "generate workflows"));
    assert.equal(posted[0].project.shared.preamble, "a changed bakery");
    assert.ok(posted[1].generate, "generate ran without a save");
});

test("a failed save stops generate", async () => {
    const node = await recipeNode({ saveFails: true });
    await click(word(node, "generate workflows"));
    assert.equal(posted.filter((p) => p.generate).length, 0);
    assert.equal(toasts.at(-1).summary, "Save failed");
});

// ================================================================= the wire ==

test("the wire takes the pane with it until he picks one himself", async () => {
    const node = await recipeNode();
    widget(node, "recipe").value = "appliance1x2";
    await draw(node);
    assert.equal(node.properties.symbiotica_recipes_pick, "appliance1x2");
    assert.match(statusText(node), / · on appliance1x2/);

    // A pick of his own is his: the wire moving again leaves it alone.
    await click(rowFor(node, "zebra"));
    widget(node, "recipe").value = "appliance1x1";
    await draw(node);
    assert.equal(node.properties.symbiotica_recipes_pick, "zebra");
    // Taking the one the wire names re-arms the follow.
    await click(rowFor(node, "appliance1x1"));
    widget(node, "recipe").value = "appliance1x2";
    await draw(node);
    assert.equal(node.properties.symbiotica_recipes_pick, "appliance1x2");
});

test("the wire does not take the pane while he is typing in it", async () => {
    const node = await recipeNode();
    await click(rowFor(node, "shared"));
    const cell = fieldFor(node, "preamble");
    fire(cell, "focus", {});
    cell.value = "half a sen";
    fire(cell, "input", {});
    widget(node, "recipe").value = "appliance1x2";
    await draw(node);
    assert.equal(node.properties.symbiotica_recipes_pick, "shared");
    assert.equal(fieldFor(node, "preamble").value, "half a sen");
    // Once he is out of the field, the wire is still there.
    fire(cell, "blur", {});
    await draw(node);
    assert.equal(node.properties.symbiotica_recipes_pick, "appliance1x2");
});

test("auto is a head control that writes the widget the node saves", async () => {
    const node = await recipeNode();
    const box = descendants(panel(node)).find((e) => e.type === "checkbox");
    assert.equal(box.checked, false);
    box.checked = true;
    fire(box, "change", {});
    await settle();
    assert.equal(widget(node, "auto").value, true);
    assert.equal(node._symAuto.on, true);
    box.checked = false;
    fire(box, "change", {});
    await settle();
    assert.equal(widget(node, "auto").value, false);
    assert.equal(node._symAuto.on, false);
});

// ========================================================== nothing in silence ==

test("each empty names which empty it is", async () => {
    // An empty match_color, a colour that is not one, and a canvas with
    // nothing painted are three different states, and none of them is "the
    // node is broken".
    const node = await recipeNode();
    const pane = () => String(descendants(panel(node))
        .find((e) => String(e.style.cssText).includes("text-align:center"))
        ?.textContent ?? "");

    widget(node, "match_color").value = "";
    await draw(node);
    assert.match(statusText(node), /match_color is empty/);

    widget(node, "match_color").value = "chartreuse";
    await draw(node);
    assert.match(statusText(node), /not a colour/);

    widget(node, "match_color").value = "purple";
    app.graph.nodes = [painted("unpainted", [["a", 1]], { color: "#232", bgcolor: "#353" })];
    await draw(node);
    assert.match(statusText(node), /Nothing on this canvas is painted purple/);
    assert.match(pane(), /Nothing on this canvas is painted purple/);
});

test("a workflow no project is the template of says so, in the tree and the pane",
     async () => {
    const node = await recipeNode({ projects: [OTHERS[1]] });
    assert.match(emptyText(part(node, "tree")),
                 /No project has this workflow as its template/);
    assert.match(statusText(node), /Press new project/);
    // And the other project is still named, with the workflow to open for it.
    assert.deepEqual(labels(node),
                     ["other projects",
                      "imperia-bakery — open recipe-test/bakery-template-test.json"]);
    // `capture recipe` has to SAY there is no project rather than do nothing.
    widget(node, "recipe").value = "chair";
    widget(node, "capture recipe").callback();
    await settle();
    assert.equal(toasts.at(-1).summary, "No project for this workflow");
});

test("an unsaved workflow is told to save, not shown an empty table", async () => {
    const node = await recipeNode({ path: null, projects: [] });
    assert.match(emptyText(part(node, "tree")), /Save the workflow first/);
});

test("the status line survives every re-render", async () => {
    // It used to be one element re-appended at the end of the body, which a
    // persistent shell has nowhere to do.
    const node = await recipeNode();
    const line = main(node).children[main(node).children.length - 1].children[0];
    await click(rowFor(node, "appliance1x2"));
    await click(rowFor(node, ":project"));
    app.graph.nodes = [...CANVAS(), painted("lighting", [["String", "warm"]])];
    await draw(node);
    assert.equal(main(node).children[main(node).children.length - 1].children[0],
                 line);
    assert.ok(statusText(node).length);
});

test("the pane says the project's shape when nothing is wrong", async () => {
    const node = await recipeNode();
    assert.equal(statusText(node), "symtest-fixture: 3 recipes, 5 slots.");
    await type(fieldFor(node, "preamble"), "edited");
    assert.match(statusText(node), /^Unsaved edits\./);
});

// ================================================== a caret that goes missing ==

test("a rebuild that takes the focused field away does not wedge the wire",
     async () => {
    // The browser fires NO blur for an element it removed, so a render that
    // replaces the rows leaves the panel believing the caret is still in one.
    // Every path that waits for the caret to leave then waits for ever — the
    // wire stops moving the pane, and nothing on screen says why.
    const node = await recipeNode();
    await click(rowFor(node, "shared"));
    const cell = fieldFor(node, "preamble");
    fire(cell, "focus", {});
    // Any full render: onConfigure's, a project re-resolve, delete, new.
    node._symRecipe.render();
    await settle();
    assert.notEqual(fieldFor(node, "preamble"), cell, "no rebuild happened");
    widget(node, "recipe").value = "appliance1x2";
    await draw(node);
    assert.equal(node.properties.symbiotica_recipes_pick, "appliance1x2");
});

test("auto's own save does not rebuild the pane under the caret", async () => {
    // auto fires a second after an edit — which is while he is typing the next
    // one. It saves and re-draws, and a rebuild there is the caret gone.
    const node = await recipeNode();
    widget(node, "auto").value = true;
    widget(node, "auto").callback(true);
    widget(node, "recipe").value = "appliance1x2";
    await draw(node);
    assert.equal(node.properties.symbiotica_recipes_pick, "appliance1x2");
    const cell = fieldFor(node, "backdrop");
    fire(cell, "focus", {});
    const long = "controlnet/bakery/".repeat(60);
    cell.value = long;
    fire(cell, "input", {});
    await settle();
    // The canvas moves on its own — a seed bumped by a queue — and auto saves.
    app.graph.nodes[4].widgets[0].value = 2;
    await draw(node);
    await new Promise((r) => setTimeout(r, 1200));
    await settle();
    assert.ok(posted.length, "auto never saved");
    assert.ok(fieldFor(node, "backdrop") === cell, "the field was re-created");
    assert.equal(cell.value, long, "the typed text was replaced");
});

test("the name field shows the slug it was given, not the words typed in",
     async () => {
    const node = await recipeNode();
    await click(rowFor(node, "zebra"));
    const name = descendants(panel(node))
        .find((e) => String(e.title).startsWith("Recipe:"));
    fire(name, "focus", {});
    name.value = "Cashier's Desk 1x1";
    fire(name, "change", {});
    await settle();
    assert.equal(name.value, "cashiers-desk-1x1");
    assert.equal(node.properties.symbiotica_recipes_pick, "cashiers-desk-1x1");
});

test("the head's count follows an edit, the way the tree's does", async () => {
    // A node has to show what it holds: a badge that says "1 own" over a recipe
    // with two is a badge that has to be checked against the tree to be read.
    const node = await recipeNode();
    await click(rowFor(node, "appliance1x1"));
    const badge = descendants(panel(node))
        .find((e) => /^\d+ (values|own)$/.test(String(e.textContent ?? "")));
    assert.equal(badge.textContent, "1 own");
    await type(fieldFor(node, "preamble"), "a desk");
    assert.equal(badge.textContent, "2 own");
    assert.ok(labels(node).includes("appliance1x1 · 2"));
});

// ========================= new recipe, and leaving one ======================

test("new recipe asks for a name and writes the canvas into it", async () => {
    const node = await recipeNode();
    asked.answer = "Cashier's Desk 1x1";
    await click(word(node, "new recipe"));
    await settle();
    const project = posted.filter((p) => p.project).at(-1).project;
    assert.ok("cashiers-desk-1x1" in project.recipes, "the recipe reached the server");
    assert.equal(node.properties.symbiotica_recipes_pick, "cashiers-desk-1x1");
    assert.ok(labels(node).some((l) => l.startsWith("cashiers-desk-1x1 ·")));
    assert.equal(statusText(node), "Created cashiers-desk-1x1 from this canvas.");
});

test("new recipe refuses a name a recipe already has", async () => {
    const node = await recipeNode();
    asked.answer = "appliance1x2";
    await click(word(node, "new recipe"));
    await settle();
    assert.equal(posted.filter((p) => p.project).length, 0);
    assert.match(toasts.at(-1).summary, /already a recipe/);
});

test("an empty name leaves the project alone", async () => {
    const node = await recipeNode();
    asked.answer = "";
    await click(word(node, "new recipe"));
    await settle();
    assert.equal(posted.filter((p) => p.project).length, 0);
});

test("switching rows writes the recipe you are leaving", async () => {
    const node = await recipeNode();
    await click(rowFor(node, "appliance1x2"));      // the canvas is now this one
    const backdrop = app.graph.nodes.find((n) => n.title === "backdrop");
    backdrop.widgets[0].value = "gargoyle.png";     // he changes a slot
    await click(rowFor(node, "appliance1x1"));      // and picks another
    const project = posted.filter((p) => p.project).at(-1).project;
    assert.equal(project.recipes.appliance1x2.backdrop, "gargoyle.png",
                 "the edit was written into the recipe he left");
    assert.equal(backdrop.widgets[0].value, "floor-1x1.png",
                 "and the one he picked is on the canvas");
});

test("a row that has not moved is not written on the way past", async () => {
    const node = await recipeNode();
    await click(rowFor(node, "appliance1x2"));
    posted.length = 0;
    await click(rowFor(node, "appliance1x1"));
    assert.deepEqual(posted.filter((p) => p.project), []);
});

// ===================== what the capture could not keep ======================

test("capture names the nodes that changed and carry no paint", async () => {
    const node = await recipeNode();
    const stray = { title: "CLIP Text Encode", mode: 0, inputs: [],
                    widgets: [{ name: "text", value: "a bakery" }] };
    app.graph.nodes = [...app.graph.nodes, stray];
    app.graph._nodes = app.graph.nodes;
    await click(rowFor(node, "appliance1x2"));      // baseline
    stray.widgets[0].value = "a gargoyle";          // changed, never painted
    await click(word(node, "capture"));
    assert.match(statusText(node), /Not painted, so not kept: CLIP Text Encode\./);
});

test("a painted node that changed is kept, and named nowhere", async () => {
    const node = await recipeNode();
    await click(rowFor(node, "appliance1x2"));
    app.graph.nodes.find((n) => n.title === "backdrop").widgets[0].value = "x.png";
    await click(word(node, "capture"));
    assert.doesNotMatch(statusText(node), /Not painted/);
});

// ===================== what the saved template has no slot for ==============

test("the status names the keys the saved template would drop", async () => {
    // His case: the workflow was painted and captured, then never saved, so
    // the template FILE the generator reads declares fewer slots than the
    // project file holds values for, and generate renders the template's own.
    const project = PROJECT();
    project.recipes.appliance1x2["Control Image"] = "1x2-box-dots.png";
    const node = await recipeNode({ project });
    assert.match(statusText(node),
                 /The saved template has no slot for Control Image — save the workflow/);
});

test("nothing stranded, nothing said", async () => {
    const node = await recipeNode();
    assert.doesNotMatch(statusText(node), /no slot for/);
});

// ================= the recipe's own workflow, kept on disk ==================

test("a save rewrites that recipe's workflow, once the typing stops", async () => {
    const node = await recipeNode();
    await click(rowFor(node, "appliance1x2"));
    app.graph.nodes.find((n) => n.title === "backdrop").widgets[0].value = "x.png";
    await click(word(node, "capture"));
    await click(word(node, "save project"));
    await settle();
    assert.deepEqual(posted.filter((p) => p.generate), [],
                     "not one workflow written per keystroke");
    await new Promise((r) => setTimeout(r, 2200));
    await settle();
    const wrote = posted.filter((p) => p.generate).at(-1);
    assert.equal(wrote.generate.recipe, "appliance1x2", "only the recipe that moved");
    assert.equal(wrote.generate.name, "symtest-fixture");
});

test("shared is not a workflow, so saving it writes none", async () => {
    const node = await recipeNode();
    await click(rowFor(node, "shared"));
    await click(word(node, "capture"));
    await click(word(node, "save project"));
    await new Promise((r) => setTimeout(r, 2200));
    await settle();
    assert.deepEqual(posted.filter((p) => p.generate), []);
});

// ============== the wire and the sidebar, pointing the same way =============

// Named so their slugs are the fixture's recipe keys, the way his
// "Food - 3 stages 1x1" slugs to food-3-stages-1x1.
const CATEGORIES = ["Appliance1x1", "Appliance1x2", "Food - 3 stages 1x1"];

// His canvas: Task -> Task Specs -> the `recipe` input, with auto on.
//
// `category` is a PLAIN text widget here because that is what the real Task
// node carries: its tree writes the widget, and a combo would drop every
// value until the first parse lands. Giving the fixture options it does not
// have is what let the label lookup pass in here while his pick set nothing.
// The labels live on the node's parsed order, which is where they come from.
function taskChain(node, category = "All") {
    const task = {
        id: 8, type: "SymbioticaTask", mode: 0, title: "Task", inputs: [],
        widgets: [{ name: "category", value: category },
                  { name: "asset", value: "Gargoyle Drink Machine" },
                  { name: "ref", value: "GargoyleDrinkMachine_2.png" }],
        outputs: [{ name: "specs" }], setDirtyCanvas() {},
        _symEvents: [{
            feature: "QE 2", eventName: "Coven of Shadows",
            assets: CATEGORIES.map((c, i) => ({
                assetName: `asset ${i}`, category: c, canvas: "" })),
        }],
    };
    const specs = {
        id: 14, type: "SymbioticaTaskSpecs", mode: 0, widgets: [],
        inputs: [{ name: "specs", link: 6 }],
        outputs: [...Array(10).fill(0).map((_, i) => ({ name: `o${i}` })),
                  { name: "category_recipe" }],
    };
    node.inputs = [{ name: "recipe", widget: { name: "recipe" }, link: 10 }];
    const nodes = [...app.graph.nodes, task, specs];
    app.graph.nodes = nodes;
    app.graph._nodes = nodes;
    app.graph.links = { 6: { origin_id: 8, origin_slot: 0 },
                        10: { origin_id: 14, origin_slot: 10 } };
    app.graph.getNodeById = (id) => nodes.find((n) => n.id === id) ?? null;
    return task;
}

const autoOn = async (node) => {
    widget(node, "auto").value = true;
    widget(node, "auto").callback(true);
    await draw(node);
};

test("picking a recipe points the wire at it, and drops the asset narrowing",
     async () => {
    const node = await recipeNode();
    const task = taskChain(node, "Appliance1x1");
    assert.equal(task.widgets[0].options, undefined,
                 "the real node's category has no options to read labels off");
    await click(rowFor(node, "appliance1x2"));
    assert.equal(task.widgets[0].value, "Appliance1x2", "the Task node followed");
    assert.equal(task.widgets[1].value, "", "one asset would decide it instead");
    assert.equal(task.widgets[2].value, "",
                 "and a reference belongs to the asset that just went");
});

test("a recipe whose key is not its label still points the wire at it", async () => {
    // His own: `Food - 3 stages 1x1` slugs to food-3-stages-1x1, and the LABEL
    // is the only thing the category widget can be set to. Picking it left the
    // widget on Appliance 1x1, so auto read the old name off the wire on the
    // next draw and pulled the canvas straight back.
    const project = PROJECT();
    project.recipes["food-3-stages-1x1"] = { backdrop: "floor-food.png" };
    const node = await recipeNode({ project });
    const task = taskChain(node, "Appliance1x1");
    await click(rowFor(node, "food-3-stages-1x1"));
    assert.equal(task.widgets[0].value, "Food - 3 stages 1x1",
                 "the label whose slug is the recipe");
    assert.equal(app.graph.nodes.find((n) => n.title === "backdrop").widgets[0].value,
                 "floor-food.png", "and its values are on the canvas");
});

test("a recipe no category is named after says so and still loads", async () => {
    const node = await recipeNode();
    const task = taskChain(node, "Appliance1x1");
    await click(rowFor(node, "zebra"));
    assert.equal(task.widgets[0].value, "Appliance1x1", "nothing was guessed at");
    assert.match(statusText(node), /Nothing on Task is called zebra\./);
});

test("the recipe the WIRE loaded is the one a switch writes back, not the picked one",
     async () => {
    // How appliance-1x2 came to hold food's values: auto loads from the wire
    // while the pane shows another recipe, and the switch wrote the canvas
    // into whatever happened to be selected.
    const node = await recipeNode();
    const task = taskChain(node, "Appliance1x1");
    await autoOn(node);
    await draw(node);                       // auto adopts appliance1x1... 
    node.properties.symbiotica_recipes_pick = "appliance1x2";   // ...the pane shows another
    await draw(node);
    const before = state(node).appliance1x2;
    app.graph.nodes.find((n) => n.title === "backdrop").widgets[0].value = "wire.png";
    await click(rowFor(node, "zebra"));
    assert.deepEqual(state(node).appliance1x2, before,
                     "the recipe that was merely on screen was not written");
    assert.notEqual(state(node).appliance1x2.backdrop, "wire.png");
});

// =========== the order's categories, as rows before they are recipes =========

test("every category the order holds is a row, stored or not", async () => {
    const node = await recipeNode();
    taskChain(node, "Appliance1x1");
    await draw(node);
    assert.deepEqual(labels(node), [
        "symtest-fixture",
        "shared \u00b7 3", "appliance1x1 \u00b7 1", "appliance1x2 \u00b7 3",
        "food-3-stages-1x1 \u00b7 0", "zebra \u00b7 0",
        "other projects",
        "imperia-bakery \u2014 open recipe-test/bakery-template-test.json",
    ]);
    // The mark is what tells the two apart: `zebra` is an empty recipe the
    // file holds, `food-3-stages-1x1` is a category nothing is stored for.
    assert.equal(rowFor(node, "food-3-stages-1x1").children.length, 2, "a lead");
    assert.equal(rowFor(node, "zebra").children.length, 1, "no lead");
    assert.equal(statusText(node),
                 "symtest-fixture: 3 recipes, 5 slots. \u00b7 on appliance1x1"
                 + " \u00b7 1 category empty");
});

test("an empty category is not written to the file, and an empty recipe is",
     async () => {
    const node = await recipeNode();
    taskChain(node, "Appliance1x1");
    await draw(node);
    await click(word(node, "save project"));
    const written = posted.filter((p) => p.project).at(-1).project.recipes;
    assert.deepEqual(Object.keys(written).sort(),
                     ["appliance1x1", "appliance1x2", "zebra"],
                     "seventeen empty blocks is seventeen workflows at full price");
});

test("picking an empty category loads shared and points the wire at it",
     async () => {
    const node = await recipeNode();
    const task = taskChain(node, "Appliance1x1");
    await draw(node);
    await click(rowFor(node, "food-3-stages-1x1"));
    assert.equal(task.widgets[0].value, "Food - 3 stages 1x1", "the Task followed");
    assert.equal(app.graph.nodes.find((n) => n.title === "backdrop").widgets[0].value,
                 "floor-1x1.png", "shared is what a recipe starts from");
});

test("capturing into an empty category is what makes it a recipe", async () => {
    const node = await recipeNode();
    taskChain(node, "Appliance1x1");
    await draw(node);
    await click(rowFor(node, "food-3-stages-1x1"));
    app.graph.nodes.find((n) => n.title === "backdrop").widgets[0].value = "floor-food.png";
    await click(word(node, "capture"));
    await click(word(node, "save project"));
    const written = posted.filter((p) => p.project).at(-1).project.recipes;
    assert.equal(written["food-3-stages-1x1"]?.backdrop, "floor-food.png");
    assert.equal(rowFor(node, "food-3-stages-1x1").children.length, 1,
                 "and the mark is gone");
});

test("the wire landing on an empty category still captures, never loads over it",
     async () => {
    // The row exists now, but it is not a recipe until something is stored in
    // it — so auto must not answer the wire by writing shared over the canvas
    // he has just painted.
    const node = await recipeNode();
    const task = taskChain(node, "Appliance1x1");
    await draw(node);
    await autoOn(node);
    app.graph.nodes.find((n) => n.title === "backdrop").widgets[0].value = "floor-food.png";
    task.widgets[0].value = "Food - 3 stages 1x1";
    await draw(node);
    await settle();
    assert.equal(app.graph.nodes.find((n) => n.title === "backdrop").widgets[0].value,
                 "floor-food.png", "the canvas was captured, not overwritten");
    assert.equal(state(node)["food-3-stages-1x1"]?.backdrop, "floor-food.png");
});

test("browsing the categories with auto on writes nothing", async () => {
    // A click points the wire at a name auto has never seen. Without adopting
    // the row, that reads as "a recipe that does not exist yet" and the canvas
    // is captured into it on the spot — one recipe per click down the list.
    const node = await recipeNode({
        project: { ...PROJECT(), shared: {}, recipes: { appliance1x1: {} } },
    });
    taskChain(node, "Appliance1x1");
    await draw(node);
    await autoOn(node);
    await click(rowFor(node, "food-3-stages-1x1"));
    await draw(node);
    await settle();
    assert.equal(state(node)["food-3-stages-1x1"], undefined,
                 "looking at a category is not capturing it");
    assert.ok(rowFor(node, "food-3-stages-1x1").children.length === 2,
              "and it is still marked empty");
});

test("an empty category leaves when the order stops naming it; a captured one stays",
     async () => {
    const node = await recipeNode();
    const task = taskChain(node, "Appliance1x1");
    await draw(node);
    assert.ok(rowFor(node, "food-3-stages-1x1"), "offered while the order holds it");
    task._symEvents[0].assets = [{ assetName: "a", category: "Appliance1x2", canvas: "" }];
    await draw(node);
    assert.equal(rowFor(node, "food-3-stages-1x1"), undefined, "and gone with it");
    assert.ok(rowFor(node, "appliance1x1"), "a recipe the file holds is not the order's to remove");
    assert.ok(rowFor(node, "zebra"));
});

// The project as the panel currently holds it.
function state(node) {
    const posts = posted.filter((p) => p.project);
    return posts.length ? posts.at(-1).project.recipes : PROJECT().recipes;
}
