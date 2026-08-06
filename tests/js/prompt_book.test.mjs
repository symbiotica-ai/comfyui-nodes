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

// --- the Prompt Recipe panel: the whole book in the one composing node ------

import { RECIPE_SLOTS, slotOf, versionsOf } from "../../web/js/prompt_book.js";

test("versionsOf: top of the file is v1, each marker adds one", () => {
    assert.deepEqual(versionsOf("plain text"), ["1"]);
    assert.deepEqual(
        versionsOf("top\n<!-- version: tighter -->\nbody\n"
                   + "<!--  version:  loose  -->\nmore"),
        ["1", "tighter", "loose"]);
});

test("slotOf maps the book onto the six recipe widgets by position", () => {
    const rules = [{ name: "_rules/01-game.md" }, { name: "_rules/02-inputs.md" },
                   { name: "_rules/03-your-job.md" },
                   { name: "_rules/04-overwrite.md" }];
    assert.equal(slotOf("_rules/01-game.md", rules, "Chair"), "game");
    assert.equal(slotOf("_rules/04-overwrite.md", rules, "Chair"), "overwrite");
    assert.equal(slotOf("_image/01-image-model.md", rules, "Chair"),
                 "image_model");
    assert.equal(slotOf("Chair.md", rules, "Chair"), "asset_type");
    // Another type's file composes nothing until it IS the active type.
    assert.equal(slotOf("Decoration.md", rules, "Chair"), null);
    assert.equal(RECIPE_SLOTS.length, 6);
});

const VERSIONED = "GAME v1\n<!-- version: punchy -->\nGAME v2";

function recipeRouter(seen) {
    return (route, _n, init) => {
        seen.push({ route, init });
        if (route.startsWith("/symbiotica/prompt-book")) {
            return { ok: true, status: 200, body: BOOK };
        }
        if (route.startsWith("/symbiotica/prompt-versions")) {
            return { ok: true, status: 200, body: { ok: true, blocks: [
                { name: "_rules/01-refs.md", versions: ["1", "punchy"] },
                { name: "_rules/03-light.md", versions: ["1"] },
                { name: "Chair.md", versions: ["1"] },
                { name: "Decoration.md", versions: ["1"] },
            ] } };
        }
        if (route.startsWith("/symbiotica/prompt-read")) {
            const name = new URLSearchParams(route.split("?")[1]).get("name");
            return { ok: true, status: 200, body: { ok: true,
                text: name === "_rules/01-refs.md" ? VERSIONED
                                                   : `TEXT OF ${name}` } };
        }
        if (route.startsWith("/symbiotica/prompt-compose")) {
            return { ok: true, status: 200,
                     body: { ok: true, text: "COMPOSED", blocks: [] } };
        }
        return { ok: false, status: 404, body: { error: "no route" } };
    };
}

async function recipeNode(seen) {
    reset();
    app.graph._nodes = [];
    setResponder(recipeRouter(seen));
    const widgets = { project_path: "/p/bakery", category: "Chair" };
    for (const slot of RECIPE_SLOTS) widgets[slot] = 1;
    const node = await create("SymbioticaPromptRecipe", widgets);
    node.inputs = [{ name: "order", link: null }];
    app.graph._nodes = [node];
    await node.onNodeCreated?.call(node);
    for (let i = 0; i < 20; i++) await tick();
    return node;
}

const recipePanelOf = (node) =>
    node.widgets.find((w) => w.name === "prompt_recipe").element;
const recipeParts = (node) => {
    const [bar, blocks, status, chips, editor] = recipePanelOf(node).children;
    return { picker: bar.children[0], save: bar.children[1], blocks, status,
             chips, editor };
};

test("the recipe panel opens on the composed view of the active type", async () => {
    const node = await recipeNode([]);
    const { picker, editor } = recipeParts(node);
    assert.equal(picker.value, "composed:Chair");
    assert.equal(editor.value, "COMPOSED");
    const labels = picker.children.map((g) => g.label);
    assert.ok(labels.some((l) => l?.startsWith("Game rules")));
    assert.ok(labels.some((l) => l?.startsWith("Composed")));
    assert.ok(labels.some((l) => l === "New"));
});

test("a versioned block grows chips, and a chip sets the node's own widget",
     async () => {
    const node = await recipeNode([]);
    const { picker, chips } = recipeParts(node);
    picker.value = "_rules/01-refs.md";
    fire(picker, "change");
    for (let i = 0; i < 10; i++) await tick();
    const texts = chips.children.map((b) => b.textContent);
    assert.ok(texts.some((t) => t.includes("punchy")), `chips were: ${texts}`);
    // Clicking v2 pins the block's slot widget — the value the queue runs.
    const v2 = chips.children.find((b) => b.textContent.includes("punchy"));
    fire(v2, "click");
    const w = node.widgets.find((x) => x.name === "game");
    assert.equal(w.value, 2);
});

test("the composed preview sends the widget recipe to the server", async () => {
    const seen = [];
    const node = await recipeNode(seen);
    node.widgets.find((x) => x.name === "game").value = 2;
    seen.length = 0;
    const { picker } = recipeParts(node);
    picker.value = "composed:Chair";
    fire(picker, "change");
    for (let i = 0; i < 10; i++) await tick();
    const composeCall = seen.find(
        (s) => s.route.startsWith("/symbiotica/prompt-compose"));
    assert.ok(composeCall, "no compose request went out");
    const recipe = new URLSearchParams(composeCall.route.split("?")[1])
        .get("recipe");
    assert.deepEqual(JSON.parse(recipe), { "_rules/01-refs.md": "punchy" });
});
