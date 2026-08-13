// ABOUTME: The Prompt Book panel — that it lists rules before types, loads the
// ABOUTME: picked block, and saves what the user typed to the right file.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, fire, link, reset, setResponder, tick } from "./comfy_stub.mjs";
import "../../web/js/prompt_book.js";

const BOOK = {
    ok: true,
    rules: [{ name: "_rules/01-refs.md", title: "01-refs", chars: 10 },
            { name: "_rules/03-light.md", title: "03-light", chars: 20 }],
    types: [{ name: "Chair.md", title: "Chair", chars: 30 },
            { name: "Decoration.md", title: "Decoration", chars: 40 }],
};

function router(seen) {
    return (route, _n, init) => {
        seen.push({ route, init });
        if (route.startsWith("/symbiotica/prompt-book")) {
            return { ok: true, status: 200, body: BOOK };
        }
        if (route.startsWith("/symbiotica/prompt-read")) {
            const name = new URLSearchParams(route.split("?")[1]).get("name");
            return { ok: true, status: 200,
                     body: { ok: true, text: `TEXT OF ${name}` } };
        }
        if (route.startsWith("/symbiotica/prompt-write")) {
            return { ok: true, status: 200, body: { ok: true, chars: 7 } };
        }
        return { ok: false, status: 404, body: { error: "no route" } };
    };
}

async function panelNode(seen, project = "/p/bakery") {
    reset();
    app.graph._nodes = [];
    setResponder(router(seen));
    const node = await create("SymbioticaPromptBook", { project_path: project });
    node.inputs = [{ name: "order", link: null }];
    app.graph._nodes = [node];
    await node.onNodeCreated?.call(node);
    for (let i = 0; i < 20; i++) await tick();
    return node;
}

const panelOf = (node) =>
    node.widgets.find((w) => w.name === "prompt_book").element;
const parts = (node) => {
    // container.append(bar, blocksBar, status, editor) — destructured rather
    // than indexed one by one, so a row added to the panel shifts the names
    // together instead of silently handing back the element next door.
    const [bar, blocks, status, editor] = panelOf(node).children;
    return { picker: bar.children[0], save: bar.children[1], blocks, status,
             editor };
};

test("the picker lists shared rules before the type blocks", async () => {
    const node = await panelNode([]);
    const { picker } = parts(node);
    assert.deepEqual(picker.children.map((g) => g.label),
                     ["Game rules — apply to every type",
                      "Image model — style, light, camera",
                      "Asset type",
                      "Composed — what the LLM receives"]);
    const group = (label) =>
        picker.children.find((g) => g.label.startsWith(label));
    assert.deepEqual(group("Game rules").children.map((o) => o.value),
                     ["_rules/01-refs.md", "_rules/03-light.md"]);
    assert.deepEqual(group("Asset type").children.map((o) => o.value),
                     ["Chair.md", "Decoration.md"]);
});

test("opening the panel loads the first block's text", async () => {
    const node = await panelNode([]);
    assert.equal(parts(node).editor.value, "TEXT OF _rules/01-refs.md");
});

test("save posts the edited text for the picked block", async () => {
    const seen = [];
    const node = await panelNode(seen);
    const { editor, save } = parts(node);
    editor.value = "TIGHTER LIGHTING RULE";
    fire(save, "click", {});
    for (let i = 0; i < 20; i++) await tick();
    const write = seen.find((c) => c.route === "/symbiotica/prompt-write");
    assert.ok(write, "no save request was made");
    const sent = JSON.parse(write.init.body);
    assert.equal(sent.name, "_rules/01-refs.md");
    assert.equal(sent.text, "TIGHTER LIGHTING RULE");
    assert.equal(sent.project, "/p/bakery");
});

test("no project asks for one instead of requesting a book", async () => {
    // Without the guard the panel asks with project="" and shows the server's
    // 400 as if the user had done something wrong.
    const seen = [];
    const node = await panelNode(seen, "");
    assert.equal(seen.filter((c) => c.route.includes("prompt-book")).length, 0,
                 "asked the server for a book with no project");
    assert.match(parts(node).status.textContent, /wire an order|project_path/);
});

test("finds the project through an Order Specs whose path is itself wired", async () => {
    // His real graph: Prompt Book <- Order Specs <- Path Local. Reading the
    // Order Specs' own widget finds "" and the panel reports no project while
    // an order is plainly connected — so the walk has to continue upstream.
    const seen = [];
    reset();
    app.graph._nodes = [];
    setResponder(router(seen));
    const pathNode = await create("String", { value: "/p/bakery" });
    pathNode.outputs = [{ name: "STRING", links: [] }];
    const specs = await create("SymbioticaOrderSpecs", { project_path: "" });
    specs.outputs = [{ name: "order", links: [] }];
    link(pathNode, specs, "project_path");
    const book = await create("SymbioticaPromptBook", { project_path: "" });
    link(specs, book, "order");
    app.graph._nodes = [pathNode, specs, book];
    await book.onNodeCreated?.call(book);
    for (let i = 0; i < 20; i++) await tick();

    const asked = seen.find((c) => c.route.includes("prompt-book"));
    assert.ok(asked, "never asked for the book — the project did not resolve");
    assert.match(asked.route, /project=%2Fp%2Fbakery/);
});

// --- the Prompt Recipe panel: a saved SET of blocks, one picker to swap -----

function recipeRouter(seen, recipes) {
    return (route, _n, init) => {
        seen.push({ route, init });
        if (route.startsWith("/symbiotica/prompt-versions")) {
            return { ok: true, status: 200, body: { ok: true, blocks: [
                { name: "_rules/01-llm-prompt.md", versions: ["", "punchy"] },
                { name: "_image/01-image-model.md", versions: [""] },
                { name: "_flip/01-flip.md", versions: [""] },
                { name: "Chair.md", versions: [""] },
            ] } };
        }
        if (route.startsWith("/symbiotica/recipe-list")) {
            return { ok: true, status: 200,
                     body: { ok: true, recipes: recipes ?? [] } };
        }
        if (route.startsWith("/symbiotica/recipe-write")) {
            return { ok: true, status: 200,
                     body: { ok: true, name: "Decoration",
                             slots: JSON.parse(init.body).slots } };
        }
        return { ok: false, status: 404, body: { error: "no route" } };
    };
}

const DECO = [{ name: "Decoration", slots: [
    { block: "_rules/01-llm-prompt.md", version: "" },
    { block: "_image/01-image-model.md", version: "" },
    { block: "_flip/01-flip.md", version: "" },
] }];

async function recipeNode(seen, recipes = DECO) {
    reset();
    app.graph._nodes = [];
    setResponder(recipeRouter(seen, recipes));
    const node = await create("SymbioticaPromptRecipe",
                              { project_path: "/p/bakery", recipe: "", slots: 3 });
    node.inputs = [{ name: "order", link: null }];
    app.graph._nodes = [node];
    await node.onNodeCreated?.call(node);
    for (let i = 0; i < 20; i++) await tick();
    return node;
}

const recipePanelOf = (node) =>
    node.widgets.find((w) => w.name === "prompt_recipe").element;
const recipeParts = (node) => {
    const [bar, blocks, status, rows] = recipePanelOf(node).children;
    return { picker: bar.children[0], save: bar.children[1],
             del: bar.children[2], blocks, status, rows };
};

test("the panel opens on a saved recipe and shows one row per slot", async () => {
    const node = await recipeNode([]);
    const { picker, rows } = recipeParts(node);
    assert.equal(picker.value, "Decoration");
    assert.equal(rows.children.length, 3);
    const first = rows.children[0].children[1];
    assert.equal(first.value, "_rules/01-llm-prompt.md");
    // Every folder of the book is offered, `_flip` included.
    const labels = first.children.filter((c) => c.label).map((g) => g.label);
    assert.ok(labels.includes("Mirror / standalone"), `groups: ${labels}`);
});

test("picking a recipe writes the node's own widget — that is what the queue "
     + "serves", async () => {
    const node = await recipeNode([], [...DECO, { name: "Chair", slots: [
        { block: "Chair.md", version: "" }] }]);
    const { picker } = recipeParts(node);
    picker.value = "Chair";
    fire(picker, "change");
    for (let i = 0; i < 10; i++) await tick();
    assert.equal(node.widgets.find((w) => w.name === "recipe").value, "Chair");
    assert.equal(recipeParts(node).rows.children[0].children[1].value,
                 "Chair.md");
});

test("Save posts the rows as the recipe's slots", async () => {
    const seen = [];
    const node = await recipeNode(seen);
    const { rows, save } = recipeParts(node);
    rows.children[2].children[1].value = "Chair.md";
    seen.length = 0;
    fire(save, "click");
    for (let i = 0; i < 10; i++) await tick();
    const call = seen.find((s) => s.route.startsWith("/symbiotica/recipe-write"));
    assert.ok(call, "no save request went out");
    const body = JSON.parse(call.init.body);
    assert.equal(body.name, "Decoration");
    assert.deepEqual(body.slots.map((s) => s.block),
                     ["_rules/01-llm-prompt.md", "_image/01-image-model.md",
                      "Chair.md"]);
});

test("the slot-count widget adds and removes rows", async () => {
    const node = await recipeNode([]);
    const w = node.widgets.find((x) => x.name === "slots");
    w.value = 5;
    w.callback?.call(node, 5);
    for (let i = 0; i < 10; i++) await tick();
    assert.equal(recipeParts(node).rows.children.length, 5);
});

test("a version can be pinned per slot", async () => {
    const node = await recipeNode([]);
    const version = recipeParts(node).rows.children[0].children[2];
    const names = version.children.map((o) => o.value);
    assert.deepEqual(names, ["", "punchy"]);
});

test("a plain String node wired into project_path names the book", async () => {
    // The obvious way to point the book at a local folder: a literal holding
    // the path. It resolved to nothing, and the panel showed an empty book.
    const seen = [];
    reset();
    app.graph._nodes = [];
    setResponder(router(seen));
    const literal = await create("String", { value: "/p/bakery" });
    const book = await create("SymbioticaPromptBook", { project_path: "" });
    book.inputs = [];
    app.graph._nodes = [literal, book];
    link(literal, book, "project_path");
    await book.onNodeCreated?.call(book);
    for (let i = 0; i < 20; i++) await tick();
    const asked = seen.find((c) => c.route.includes("prompt-book"));
    assert.ok(asked, "never asked for the book — the literal did not resolve");
    assert.match(asked.route, /project=%2Fp%2Fbakery/);
});

test("switching to a shorter recipe drops the longer one's leftover rows",
     async () => {
    // A 2-block recipe was showing the 3-block recipe's third block — an
    // appliance flip sitting in the food recipe.
    const node = await recipeNode([], [...DECO, { name: "Food", slots: [
        { block: "_rules/01-llm-prompt.md", version: "" },
        { block: "_image/01-image-model.md", version: "" }] }]);
    const { picker } = recipeParts(node);
    picker.value = "Food";
    fire(picker, "change");
    for (let i = 0; i < 10; i++) await tick();
    const rows = recipeParts(node).rows.children;
    assert.equal(rows.length, 2, "slot count did not follow the recipe");
    // `slots` is a dropdown, and a combo's value is its option — a string.
    assert.equal(node.widgets.find((w) => w.name === "slots").value, "2");
    assert.deepEqual(rows.map((r) => r.children[1].value),
                     ["_rules/01-llm-prompt.md", "_image/01-image-model.md"]);
});

test("changing a row writes the recipe — the node serves the file, not the DOM",
     async () => {
    const seen = [];
    const node = await recipeNode(seen);
    const { rows } = recipeParts(node);
    seen.length = 0;
    rows.children[2].children[1].value = "Chair.md";
    fire(rows.children[2].children[1], "change");
    for (let i = 0; i < 10; i++) await tick();
    const call = seen.find((s) => s.route.startsWith("/symbiotica/recipe-write"));
    assert.ok(call, "a row change did not write the recipe");
    assert.equal(JSON.parse(call.init.body).slots[2].block, "Chair.md");
});
