// ABOUTME: The Prompts node — a tree of the folder the path names, an editor for
// ABOUTME: the file clicked in it, and the actions in the two headers.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, emit, fire, link, reset, setResponder, tick } from "./comfy_stub.mjs";
import "../../web/js/prompts.js";

const TREE = {
    folders: ["_image", "_rules", "_rules/old"],
    files: ["Chair.md", "_image/01-model.md", "_rules/01-refs.md",
            "_rules/03-light.md", "_rules/old/00-v1.md"],
};

// A folder that remembers what was done to it. A save, a rename or a new file
// is announced on the window, and every panel — including the one that acted —
// re-lists; a router answering from a frozen tree would hand back the names it
// had just been told to change.
function router(seen, tree = TREE) {
    let state = { folders: [...tree.folders], files: [...tree.files] };
    const add = (key, name) => {
        if (!state[key].includes(name)) {
            state = { ...state, [key]: [...state[key], name].sort() };
        }
    };
    return (route, _n, init) => {
        seen.push({ route, init });
        if (route.startsWith("/symbiotica/prompts-list")) {
            return { ok: true, status: 200, body: { ok: true, ...state } };
        }
        if (route.startsWith("/symbiotica/prompts-read")) {
            const name = new URLSearchParams(route.split("?")[1]).get("name");
            return { ok: true, status: 200,
                     body: { ok: true, text: `TEXT OF ${name}` } };
        }
        if (route.startsWith("/symbiotica/prompts-write")) {
            add("files", JSON.parse(init.body).name);
            return { ok: true, status: 200, body: { ok: true, chars: 7 } };
        }
        if (route.startsWith("/symbiotica/prompts-rename")) {
            const { from, to } = JSON.parse(init.body);
            const move = (rel) => (rel === from ? to
                : rel.startsWith(`${from}/`) ? to + rel.slice(from.length) : rel);
            state = { folders: state.folders.map(move).sort(),
                      files: state.files.map(move).sort() };
            return { ok: true, status: 200, body: { ok: true } };
        }
        if (route.startsWith("/symbiotica/prompts-delete")) {
            const { name } = JSON.parse(init.body);
            const under = (rel) => rel === name || rel.startsWith(`${name}/`);
            state = { folders: state.folders.filter((f) => !under(f)),
                      files: state.files.filter((f) => !under(f)) };
            return { ok: true, status: 200, body: { ok: true, name } };
        }
        if (route.startsWith("/symbiotica/prompts-mkdir")) {
            const { name } = JSON.parse(init.body);
            add("folders", name);
            return { ok: true, status: 200, body: { ok: true, name } };
        }
        return { ok: false, status: 404, body: { error: "no route" } };
    };
}

const settle = async () => { for (let i = 0; i < 20; i++) await tick(); };
const widget = (node, name) => node.widgets.find((w) => w.name === name);
const posted = (seen, route) =>
    seen.filter((c) => c.route.startsWith(`/symbiotica/${route}`))
        .map((c) => JSON.parse(c.init.body));

// --- reaching into the panel -------------------------------------------------
// The panel is one DOM widget, so everything a click can land on is inside its
// element. A row carries what it IS on `_sym`; every button carries a title.
const panel = (node) => widget(node, "prompts_panel").element;
function descendants(root, out = []) {
    for (const child of root.children ?? []) {
        out.push(child);
        descendants(child, out);
    }
    return out;
}
const rows = (node) => descendants(panel(node)).filter((e) => e._sym);
// Top to bottom, which is the tree's own order: folders before files, each
// open folder's contents under it.
const tree = (node) => rows(node).map((r) => r._sym.rel);
const rowFor = (node, rel) => rows(node).find((r) => r._sym.rel === rel);
const button = (node, title) =>
    descendants(panel(node)).find((e) => e.title === title);
// By its own placeholder, not by "has one": the search field above the panes
// has one too, and it comes first in the DOM.
const editor = (node) => descendants(panel(node))
    .find((e) => e.placeholder === "Pick a file in the tree.");
const rowAction = (node, rel, title) =>
    descendants(rowFor(node, rel)).find((e) => e.title === title);
// The search field above the two panes, and the rows it lists. A result row
// carries the file it stands for on `_symHit`.
const searchBox = (node) => descendants(panel(node))
    .find((e) => e.placeholder === "Search prompts…");
const hits = (node) =>
    descendants(panel(node)).filter((e) => e._symHit).map((e) => e._symHit);
const hitFor = (node, rel) =>
    descendants(panel(node)).find((e) => e._symHit === rel);
const look = async (node, query, key = null) => {
    const box = searchBox(node);
    if (key) fire(box, "keydown", { key, stopPropagation() {}, preventDefault() {} });
    else { box.value = query; fire(box, "input", {}); }
    await settle();
};
const click = async (element) => {
    fire(element, "click", { stopPropagation() {} });
    await settle();
};
const type = async (node, body) => {
    const area = editor(node);
    area.value = body;
    fire(area, "input", {});
    await settle();
};

async function promptsNode(seen, widgets = {}, tree = TREE) {
    reset();
    app.graph._nodes = [];
    setResponder(router(seen, tree));
    const node = await create("SymbioticaPromptBlock",
                              { path: "/p/bakery/prompts", folder: "_rules",
                                file: "01-refs.md", text: "", ...widgets });
    node.inputs = [];
    app.graph._nodes = [node];
    await node.onNodeCreated?.call(node);
    await settle();
    return node;
}

// Answer the next dialog the panel opens, the way ComfyUI's dialog service
// would.
function answer({ text = null, confirm = true } = {}) {
    app.extensionManager = {
        dialog: { prompt: async () => text, confirm: async () => confirm },
        toast: { add() {} },
    };
}

test("the node is a path, a tree and an editor — nothing else on screen", async () => {
    // "this is pretty idiotic to have hege buttons the intire width of the
    // node": every action is an icon in one of the two headers now.
    const node = await promptsNode([]);
    assert.deepEqual(node.widgets.map((w) => w.name),
                     ["path", "folder", "file", "text", "prompts_panel"]);
    // The three the tree and the editor drive stay on the node — Python reads
    // them and a saved workflow restores them — but they take no room.
    assert.equal(widget(node, "path").hidden, undefined);
    for (const name of ["folder", "file", "text"]) {
        assert.equal(widget(node, name).hidden, true, `${name} is still drawn`);
    }
    for (const title of ["New file", "New folder", "Re-read the folder"]) {
        assert.ok(button(node, title), `no ${title} button`);
    }
});

test("the panel does not pin the node's height", async () => {
    // A `computeSize` on a DOM widget becomes a floor the corner cannot drag
    // past. This one has cost days, twice.
    const node = await promptsNode([]);
    const w = widget(node, "prompts_panel");
    assert.equal(w.computeSize, undefined);
    assert.equal(w.options.getMinHeight(), 60);
});

test("the tree is the folder on disk: sub-folders first, then files", async () => {
    // "me having to guess-type folder names" — the tree is what is there.
    const seen = [];
    const node = await promptsNode(seen);
    const listed = seen.find((c) => c.route.startsWith("/symbiotica/prompts-list"));
    assert.match(listed.route, /folder=%2Fp%2Fbakery%2Fprompts/);
    // `_rules` is open because the file on screen is in it.
    assert.deepEqual(tree(node),
                     ["_image", "_rules", "_rules/old",
                      "_rules/01-refs.md", "_rules/03-light.md", "Chair.md"]);
    assert.equal(widget(node, "text").value, "TEXT OF _rules/01-refs.md");
    assert.equal(editor(node).value, "TEXT OF _rules/01-refs.md");
});

test("clicking a folder opens it, clicking it again closes it", async () => {
    const node = await promptsNode([]);
    await click(rowFor(node, "_image"));
    assert.deepEqual(tree(node),
                     ["_image", "_image/01-model.md", "_rules", "_rules/old",
                      "_rules/01-refs.md", "_rules/03-light.md", "Chair.md"]);
    await click(rowFor(node, "_image"));
    assert.ok(!tree(node).includes("_image/01-model.md"));
    // Opening a folder does not move the file being edited.
    assert.equal(widget(node, "text").value, "TEXT OF _rules/01-refs.md");
});

test("clicking a file opens it in the editor", async () => {
    const node = await promptsNode([]);
    await click(rowFor(node, "_rules/03-light.md"));
    assert.equal(widget(node, "text").value, "TEXT OF _rules/03-light.md");
    assert.equal(editor(node).value, "TEXT OF _rules/03-light.md");
    // What Python reads and what the workflow saves, both still set.
    assert.equal(widget(node, "folder").value, "_rules");
    assert.equal(widget(node, "file").value, "03-light.md");
});

test("a file in a closed folder is one click away", async () => {
    const node = await promptsNode([]);
    await click(rowFor(node, "_rules/old"));
    await click(rowFor(node, "_rules/old/00-v1.md"));
    assert.equal(widget(node, "folder").value, "_rules/old");
    assert.equal(widget(node, "file").value, "00-v1.md");
    assert.equal(widget(node, "text").value, "TEXT OF _rules/old/00-v1.md");
});

test("the root's own files sit at the top level", async () => {
    const node = await promptsNode([], { folder: "/", file: "Chair.md" });
    assert.equal(widget(node, "text").value, "TEXT OF Chair.md");
    assert.ok(tree(node).includes("Chair.md"));
});

test("with no path the tree says so and nothing is fetched", async () => {
    const seen = [];
    const node = await promptsNode(seen, { path: "", folder: "", file: "" });
    assert.equal(seen.length, 0);
    assert.deepEqual(rows(node), []);
    assert.match(descendants(panel(node)).map((e) => e.textContent).join(" "),
                 /Set the path/);
});

test("a picked file gone from disk keeps its name and empties the editor", async () => {
    // Loading another file would silently re-point the node.
    const node = await promptsNode([], { folder: "_gone", file: "x.md" });
    assert.equal(widget(node, "file").value, "x.md");
    assert.equal(widget(node, "text").value, "");
});

test("an unsaved edit is not thrown away without asking", async () => {
    const node = await promptsNode([]);
    answer({ confirm: false });
    await type(node, "MY EDIT");
    await click(rowFor(node, "_rules/03-light.md"));
    assert.equal(widget(node, "text").value, "MY EDIT");
    assert.equal(widget(node, "file").value, "01-refs.md");
});

test("save posts the text to the file on screen", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    answer();
    await type(node, "NEW TEXT");
    await click(button(node, "Save this file (⌘S)"));
    assert.deepEqual(posted(seen, "prompts-write"),
                     [{ folder: "/p/bakery/prompts", name: "_rules/01-refs.md",
                        text: "NEW TEXT" }]);
});

test("⌘S in the editor saves, without reaching the canvas", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    answer();
    await type(node, "SAVED BY KEY");
    let reachedCanvas = true;
    fire(editor(node), "keydown", {
        key: "s", metaKey: true,
        stopPropagation() { reachedCanvas = false; },
        preventDefault() {},
    });
    await settle();
    assert.equal(reachedCanvas, false);
    assert.deepEqual(posted(seen, "prompts-write"),
                     [{ folder: "/p/bakery/prompts", name: "_rules/01-refs.md",
                        text: "SAVED BY KEY" }]);
});

test("new file lands in the folder last clicked, and opens", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    answer({ text: "09-new" });
    await click(rowFor(node, "_image"));
    await click(button(node, "New file"));
    assert.deepEqual(posted(seen, "prompts-write"),
                     [{ folder: "/p/bakery/prompts", name: "_image/09-new.md",
                        text: "" }]);
    assert.equal(widget(node, "folder").value, "_image");
    assert.equal(widget(node, "file").value, "09-new.md");
    assert.ok(tree(node).includes("_image/09-new.md"));
});

test("with no folder clicked, a new file joins the one being edited", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    answer({ text: "09-new" });
    await click(button(node, "New file"));
    assert.deepEqual(posted(seen, "prompts-write"),
                     [{ folder: "/p/bakery/prompts", name: "_rules/09-new.md",
                        text: "" }]);
});

test("new folder lands inside the folder last clicked and opens it", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    answer({ text: "drafts" });
    await click(button(node, "New folder"));
    assert.deepEqual(posted(seen, "prompts-mkdir"),
                     [{ folder: "/p/bakery/prompts", name: "_rules/drafts" }]);
    assert.ok(tree(node).includes("_rules/drafts"));
    // Making somewhere to put the next file does not close the one open.
    assert.equal(widget(node, "file").value, "01-refs.md");
    assert.equal(widget(node, "text").value, "TEXT OF _rules/01-refs.md");
});

test("rename on a file row renames it and keeps it open", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    answer({ text: "01-references" });
    await click(descendants(rowFor(node, "_rules/01-refs.md"))
                    .find((e) => e.title === "Rename"));
    assert.deepEqual(posted(seen, "prompts-rename"),
                     [{ folder: "/p/bakery/prompts", from: "_rules/01-refs.md",
                        to: "_rules/01-references.md" }]);
    assert.equal(widget(node, "file").value, "01-references.md");
    assert.ok(tree(node).includes("_rules/01-references.md"));
});

test("rename on a folder row moves everything under it", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    answer({ text: "rules" });
    await click(descendants(rowFor(node, "_rules"))
                    .find((e) => e.title === "Rename"));
    assert.deepEqual(posted(seen, "prompts-rename"),
                     [{ folder: "/p/bakery/prompts", from: "_rules", to: "rules" }]);
    assert.deepEqual(tree(node),
                     ["_image", "rules", "rules/old",
                      "rules/01-refs.md", "rules/03-light.md", "Chair.md"]);
    // The same file, under its new name — the rename does not empty the editor.
    assert.equal(widget(node, "folder").value, "rules");
    assert.equal(widget(node, "text").value, "TEXT OF rules/01-refs.md");
});

test("delete asks first, and a no leaves the file where it was", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    answer({ confirm: false });
    await click(rowAction(node, "_rules/03-light.md", "Delete"));
    assert.deepEqual(posted(seen, "prompts-delete"), []);
    assert.ok(tree(node).includes("_rules/03-light.md"));
});

test("deleting a file takes it out of the tree", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    answer();
    await click(rowAction(node, "_rules/03-light.md", "Delete"));
    assert.deepEqual(posted(seen, "prompts-delete"),
                     [{ folder: "/p/bakery/prompts", name: "_rules/03-light.md" }]);
    assert.ok(!tree(node).includes("_rules/03-light.md"));
    // The file being edited was not the one deleted, so it stays open.
    assert.equal(widget(node, "file").value, "01-refs.md");
    assert.equal(widget(node, "text").value, "TEXT OF _rules/01-refs.md");
});

test("deleting the open file moves the editor on to what is left", async () => {
    const node = await promptsNode([]);
    answer();
    await click(rowAction(node, "_rules/01-refs.md", "Delete"));
    assert.ok(!tree(node).includes("_rules/01-refs.md"));
    assert.equal(widget(node, "file").value, "03-light.md");
    assert.equal(widget(node, "text").value, "TEXT OF _rules/03-light.md");
});

test("deleting a folder takes everything under it", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    answer();
    await click(rowAction(node, "_rules", "Delete"));
    assert.deepEqual(posted(seen, "prompts-delete"),
                     [{ folder: "/p/bakery/prompts", name: "_rules" }]);
    assert.deepEqual(tree(node), ["_image", "Chair.md"]);
    // What the editor was showing went with it; nothing under a dead folder
    // stays named on the node.
    assert.equal(widget(node, "file").value, "Chair.md");
});

test("the folder's confirmation says how many prompts go with it", async () => {
    // A folder row says nothing about what is folded up inside it.
    const node = await promptsNode([]);
    const asked = [];
    app.extensionManager = {
        dialog: { confirm: async ({ message }) => { asked.push(message); return false; },
                  prompt: async () => null },
        toast: { add() {} },
    };
    await click(rowAction(node, "_rules", "Delete"));
    assert.match(asked[0], /folder _rules and the 3 prompts in it/);
    assert.match(asked[0], /cannot be undone/);
});

test("a same name is a no-op", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    answer({ text: "01-refs" });
    await click(descendants(rowFor(node, "_rules/01-refs.md"))
                    .find((e) => e.title === "Rename"));
    answer({ text: "_rules" });
    await click(descendants(rowFor(node, "_rules"))
                    .find((e) => e.title === "Rename"));
    assert.deepEqual(posted(seen, "prompts-rename"), []);
});

test("the tree folds away to a rail that can reopen it", async () => {
    const node = await promptsNode([]);
    const side = () => descendants(panel(node))
        .find((e) => e._symPart === "side");
    await click(button(node, "Hide the tree"));
    assert.equal(node.properties.symbiotica_prompts_shut, true);
    assert.equal(side().style.width, "22px");
    // The rows go, the one button that brings them back does not.
    assert.deepEqual(rows(node).length, 0);
    const back = button(node, "Show the tree");
    assert.ok(back, "no way back once it is shut");
    await click(back);
    assert.equal(node.properties.symbiotica_prompts_shut, false);
    assert.equal(side().style.width, "210px");
    assert.ok(rows(node).length > 0);
});

test("the divider sets the sidebar's width, and it rides on the node", async () => {
    const node = await promptsNode([]);
    const grip = button(node, "Drag to resize");
    fire(grip, "pointerdown",
         { clientX: 200, stopPropagation() {}, preventDefault() {} });
    fire(globalThis.window, "pointermove", { clientX: 260 });
    fire(globalThis.window, "pointerup", {});
    assert.equal(node.properties.symbiotica_prompts_sidebar, 270);
    // A second drag starts from where the first left off, not from the default.
    fire(grip, "pointerdown",
         { clientX: 0, stopPropagation() {}, preventDefault() {} });
    fire(globalThis.window, "pointermove", { clientX: -60 });
    fire(globalThis.window, "pointerup", {});
    assert.equal(node.properties.symbiotica_prompts_sidebar, 210);
});

test("retyping the path re-lists it", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    const before = seen.filter((c) => c.route.includes("prompts-list")).length;
    const w = widget(node, "path");
    w.value = "/p/other";
    w.callback?.call(w, "/p/other");
    await settle();
    const after = seen.filter((c) => c.route.includes("prompts-list"));
    assert.ok(after.length > before, "the panel re-listed");
    assert.match(after[after.length - 1].route, /folder=%2Fp%2Fother/);
});

test("a restored edit that never reached disk is kept", async () => {
    // The workflow carries the text widget; on load the file is read for the
    // baseline, but a differing edit stays on screen.
    const seen = [];
    reset();
    app.graph._nodes = [];
    setResponder(router(seen));
    const node = await create("SymbioticaPromptBlock",
                              { path: "/p/bakery/prompts", folder: "_rules",
                                file: "01-refs.md", text: "EDITED, UNSAVED" });
    node.inputs = [];
    app.graph._nodes = [node];
    await node.onNodeCreated?.call(node);
    await node.onConfigure?.call(node, {});
    await settle();
    assert.equal(widget(node, "text").value, "EDITED, UNSAVED");
    assert.equal(editor(node).value, "EDITED, UNSAVED");
});

test("a String node wired into path names the path", async () => {
    const seen = [];
    reset();
    app.graph._nodes = [];
    setResponder(router(seen));
    const node = await create("SymbioticaPromptBlock",
                              { path: "", folder: "/", file: "Chair.md", text: "" });
    node.inputs = [];
    const literal = await create("String", { value: "/p/bakery/prompts" });
    literal.outputs = [{ name: "STRING", links: [] }];
    link(literal, node, "path");
    app.graph._nodes = [literal, node];
    await node.onNodeCreated?.call(node);
    await settle();
    const listed = seen.find((c) => c.route.includes("prompts-list"));
    assert.ok(listed, "never listed — the literal did not resolve");
    assert.match(listed.route, /folder=%2Fp%2Fbakery%2Fprompts/);
});

test("a run hands back a path the canvas cannot read, and the tree fills in", async () => {
    const seen = [];
    reset();
    app.graph._nodes = [];
    setResponder(router(seen));
    const node = await create("SymbioticaPromptBlock",
                              { path: "", folder: "/", file: "Chair.md", text: "" });
    node.inputs = [];
    // A Get node with no Set of that name on the canvas: there is nothing for
    // the walk to follow, and the constant's NAME is never the answer.
    const getter = await create("GetNode", { Constant: "platform_path" });
    getter.type = "GetNode";
    getter.outputs = [{ name: "STRING", links: [] }];
    link(getter, node, "path");
    app.graph._nodes = [getter, node];
    await node.onNodeCreated?.call(node);
    await settle();
    assert.deepEqual(rows(node), []);

    emit("symbiotica.prompts",
         { node_id: node.id, path: "/studio-assets/_platform/resources" });
    await settle();

    const listed = seen.filter((c) => c.route.includes("prompts-list")).pop();
    assert.match(listed.route,
                 /folder=%2Fstudio-assets%2F_platform%2Fresources/);
    assert.deepEqual(tree(node), ["_image", "_rules", "Chair.md"]);
});

test("the run path is saved with the workflow, so a reload still knows it", async () => {
    const seen = [];
    reset();
    app.graph._nodes = [];
    setResponder(router(seen));
    const node = await create("SymbioticaPromptBlock",
                              { path: "", folder: "/", file: "Chair.md", text: "" });
    node.inputs = [];
    const getter = await create("GetNode", { Constant: "platform_path" });
    getter.outputs = [{ name: "STRING", links: [] }];
    link(getter, node, "path");
    app.graph._nodes = [getter, node];
    await node.onNodeCreated?.call(node);
    await settle();
    emit("symbiotica.prompts",
         { node_id: node.id, path: "/studio-assets/_platform/resources" });
    await settle();
    assert.equal(node.properties.symbiotica_ran_path,
                 "/studio-assets/_platform/resources");
});

test("arriving at a path refreshes the mount, and re-listing the same one does not", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    const listings = () => seen.filter((c) => c.route.includes("prompts-list"));
    assert.equal(listings().length, 1);
    assert.match(listings()[0].route, /sync=1/);

    // Same path again: the walk is a FUSE traversal, not a free call.
    node._symRefreshPrompts();
    await settle();
    assert.equal(listings().length, 2);
    assert.doesNotMatch(listings()[1].route, /sync=1/);

    // A different path is a new browse session.
    widget(node, "path").value = "/p/other/prompts";
    node._symRefreshPrompts();
    await settle();
    assert.match(listings()[2].route, /sync=1/);
});


// --- the search field --------------------------------------------------------
// "let's add search field to Prompts and Control Image nodes so i can type the
// name of the prompt" (2026-09-19): the tree answers what is in a folder, not
// where a half-remembered name lives.
test("typing a name lists every file that holds it, wherever it sits", async () => {
    const node = await promptsNode([]);
    await look(node, "01");
    // Both, from two different folders, without either being open in the tree.
    assert.deepEqual(hits(node), ["_image/01-model.md", "_rules/01-refs.md"]);
    // A name that only the FOLDER holds still answers.
    await look(node, "old");
    assert.deepEqual(hits(node), ["_rules/old/00-v1.md"]);
    await look(node, "zzz");
    assert.deepEqual(hits(node), []);
});

test("a name that starts a file beats one that only appears in it", async () => {
    const node = await promptsNode([], {}, {
        folders: ["a"],
        files: ["a/old-chair.md", "chair.md", "a/chair-back.md"],
    });
    await look(node, "chair");
    assert.deepEqual(hits(node),
                     ["a/chair-back.md", "chair.md", "a/old-chair.md"]);
});

test("picking a result opens that file and empties the box", async () => {
    const node = await promptsNode([]);
    await look(node, "light");
    await click(hitFor(node, "_rules/03-light.md"));
    assert.equal(widget(node, "folder").value, "_rules");
    assert.equal(widget(node, "file").value, "03-light.md");
    assert.equal(editor(node).value, "TEXT OF _rules/03-light.md");
    // The list goes with the pick: a result list still up over the file it
    // just opened is a list you have to dismiss before you can read anything.
    assert.equal(searchBox(node).value, "");
    assert.deepEqual(hits(node), []);
});

test("enter opens the highlighted result, arrows move the highlight", async () => {
    const node = await promptsNode([]);
    await look(node, "01");
    await look(node, "", "ArrowDown");
    await look(node, "", "Enter");
    assert.equal(widget(node, "file").value, "01-refs.md");
    assert.equal(widget(node, "folder").value, "_rules");
});

test("escape drops the list without opening anything", async () => {
    const node = await promptsNode([]);
    const before = widget(node, "file").value;
    await look(node, "light");
    await look(node, "", "Escape");
    assert.deepEqual(hits(node), []);
    assert.equal(searchBox(node).value, "");
    assert.equal(widget(node, "file").value, before);
});

test("the search survives the fold that takes the tree away", async () => {
    // "i want the search field to be visible when the sidebar is collapsed":
    // it sits ABOVE both panes, so folding the tree cannot reach it.
    const node = await promptsNode([]);
    await click(button(node, "Hide the tree"));
    assert.deepEqual(rows(node), []);
    assert.ok(searchBox(node), "the search field went with the tree");
    await look(node, "light");
    await click(hitFor(node, "_rules/03-light.md"));
    assert.equal(widget(node, "file").value, "03-light.md");
    assert.equal(editor(node).value, "TEXT OF _rules/03-light.md");
});

test("a file renamed under an open list leaves it by its new name", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    await look(node, "light");
    answer({ text: "07-lighting.md" });
    await click(rowAction(node, "_rules/03-light.md", "Rename"));
    assert.deepEqual(hits(node), ["_rules/07-lighting.md"]);
});
