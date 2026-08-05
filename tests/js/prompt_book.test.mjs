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
