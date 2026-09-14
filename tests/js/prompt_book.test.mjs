// ABOUTME: The Prompt Block panel — that it loads the picked block, saves what
// ABOUTME: the user typed to the right file, and finds the project on the wire.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, emit, fire, link, reset, setResponder, tick } from "./comfy_stub.mjs";
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


async function blockNode(seen, { subfolder = "prompts" } = {}) {
    reset();
    app.graph._nodes = [];
    setResponder(router(seen));
    const block = await create("SymbioticaPromptBlock",
                               { project_path: "/p/bakery", block: "Chair.md",
                                 slot: "1", subfolder });
    block.inputs = [];
    app.graph._nodes = [block];
    await block.onNodeCreated?.call(block);
    for (let i = 0; i < 20; i++) await tick();
    return block;
}

const slotOf = (node) => node.widgets.find((w) => w.name === "slot")?.value;

// The Block's panel widget is `prompt_block`, not the Book's `prompt_book` —
// same chrome, different node.
const blockParts = (node) => {
    const [bar, blocks, status, editor] =
        node.widgets.find((w) => w.name === "prompt_block").element.children;
    return { picker: bar.children[0], save: bar.children[1], blocks, status,
             editor };
};

test("the block keeps the slot its widget names", async () => {
    // Wiring used to set this — the Prompt Recipe's `text_3` output SAID "this
    // edits slot 3". With that node gone the widget is the only statement.
    const node = await blockNode([]);
    assert.equal(slotOf(node), "1");
});

test("the block panel follows the block the run served", async () => {
    // With a category wired the recipe names the block, in Python, at run
    // time: without the push the panel sits on the pick made by hand.
    const seen = [];
    const node = await blockNode(seen);
    emit("symbiotica.block", { node_id: String(node.id),
                               name: "_rules/03-light.md" });
    for (let i = 0; i < 20; i++) await tick();
    assert.equal(blockParts(node).picker.value, "_rules/03-light.md");
    assert.equal(blockParts(node).editor.value, "TEXT OF _rules/03-light.md");
    assert.equal(node.widgets.find((w) => w.name === "block").value,
                 "_rules/03-light.md");
});

test("a served block nobody has written yet stays pickable", async () => {
    const node = await blockNode([]);
    emit("symbiotica.block", { node_id: String(node.id),
                               name: "_flip/09-flip-wallpaper.md" });
    for (let i = 0; i < 20; i++) await tick();
    assert.equal(blockParts(node).picker.value, "_flip/09-flip-wallpaper.md");
    assert.match(blockParts(node).status.textContent, /new block/);
});

test("an unsaved edit is not overwritten by the run's block", async () => {
    const node = await blockNode([]);
    const { editor } = blockParts(node);
    editor.value = "MY UNSAVED REWRITE";
    emit("symbiotica.block", { node_id: String(node.id),
                               name: "_rules/03-light.md" });
    for (let i = 0; i < 20; i++) await tick();
    assert.equal(blockParts(node).editor.value, "MY UNSAVED REWRITE");
    assert.match(blockParts(node).status.textContent, /save or discard/);
});

// --- the book's subfolder -----------------------------------------------------
// `prompts` is a default, not a constant: the Block node carries a `subfolder`
// widget and every request the panel makes has to name the same folder, or the
// panel lists one book and the queue reads another.

const listings = (seen) =>
    seen.filter((c) => c.route.startsWith("/symbiotica/prompt-book"));

test("an untouched node still names the default book", async () => {
    // The widget shows `prompts` rather than sitting empty, so the folder it
    // reads is on screen — and that is the value the request carries.
    const seen = [];
    await blockNode(seen);
    const listed = listings(seen);
    assert.ok(listed.length, "the panel lists the book");
    assert.ok(listed[0].route.includes("subfolder=prompts"),
              `expected subfolder=prompts in ${listed[0].route}`);
});

test("a named subfolder rides on every listing request", async () => {
    const seen = [];
    await blockNode(seen, { subfolder: "briefs" });
    for (const call of listings(seen)) {
        assert.ok(call.route.includes("subfolder=briefs"),
                  `expected subfolder=briefs in ${call.route}`);
    }
});

test("a save names the subfolder it was read from", async () => {
    const seen = [];
    const node = await blockNode(seen, { subfolder: "briefs" });
    const { picker, save, editor } = blockParts(node);
    picker.value = "Chair.md";
    editor.value = "NEW TEXT";
    fire(save, "click");
    for (let i = 0; i < 20; i++) await tick();
    const write = seen.find((c) => c.route.startsWith("/symbiotica/prompt-write"));
    assert.ok(write, "the save posted");
    assert.equal(JSON.parse(write.init.body).subfolder, "briefs");
});

test("retyping the subfolder re-lists the book", async () => {
    const seen = [];
    const node = await blockNode(seen);
    const before = listings(seen).length;
    const w = node.widgets.find((x) => x.name === "subfolder");
    w.value = "briefs";
    w.callback?.call(w, "briefs");
    for (let i = 0; i < 20; i++) await tick();
    const after = listings(seen);
    assert.ok(after.length > before, "the panel re-listed");
    assert.ok(after[after.length - 1].route.includes("subfolder=briefs"));
});

// --- which project the panel reads --------------------------------------------
// `projectOf` walks the graph rather than reading one widget: the path commonly
// arrives on a wire, through a switch or a literal, and a panel that gave up at
// the first empty widget reported "no project" on a plainly wired graph.

async function wiredBlock(seen, build) {
    reset();
    app.graph._nodes = [];
    setResponder(router(seen));
    const block = await create("SymbioticaPromptBlock",
                               { project_path: "", block: "Chair.md",
                                 slot: "1", subfolder: "prompts" });
    block.inputs = [];
    app.graph._nodes = await build(block);
    await block.onNodeCreated?.call(block);
    for (let i = 0; i < 20; i++) await tick();
    return block;
}

test("a plain String node wired into project_path names the book", async () => {
    // The obvious way to point the book at a local folder: a literal holding
    // the path. It resolved to nothing, and the panel showed an empty book.
    const seen = [];
    await wiredBlock(seen, async (block) => {
        const literal = await create("String", { value: "/p/bakery" });
        literal.outputs = [{ name: "STRING", links: [] }];
        link(literal, block, "project_path");
        return [literal, block];
    });
    const asked = seen.find((c) => c.route.includes("prompt-book"));
    assert.ok(asked, "never asked for the book — the literal did not resolve");
    assert.match(asked.route, /project=%2Fp%2Fbakery/);
});

test("a project arriving through a passthrough still names the book", async () => {
    // His real graph puts a reroute (or a Local/Modal switch) between the path
    // and the panel. Reading the neighbour's own widget finds "" and the panel
    // reports no project while a path is plainly connected — so the walk has to
    // continue upstream through the node that only forwards it.
    const seen = [];
    await wiredBlock(seen, async (block) => {
        const literal = await create("String", { value: "/p/bakery" });
        literal.outputs = [{ name: "STRING", links: [] }];
        const hop = await create("Reroute", {});
        hop.inputs = [];
        hop.outputs = [{ name: "", links: [] }];
        link(literal, hop, "value");
        link(hop, block, "project_path");
        return [literal, hop, block];
    });
    const asked = seen.find((c) => c.route.includes("prompt-book"));
    assert.ok(asked, "never asked for the book — the walk stopped at the hop");
    assert.match(asked.route, /project=%2Fp%2Fbakery/);
});

test("no project asks for one instead of requesting a book", async () => {
    const seen = [];
    const node = await wiredBlock(seen, async (block) => [block]);
    assert.ok(!seen.some((c) => c.route.includes("prompt-book")),
              "asked the server for a book with no project");
    assert.match(blockParts(node).status.textContent, /project_path/);
});

