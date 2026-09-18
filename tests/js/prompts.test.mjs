// ABOUTME: The Prompts node — the folder dropdown lists the path's sub-folders,
// ABOUTME: the file dropdown the folder's files, and the buttons hit the routes.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, emit, link, reset, setResponder, tick } from "./comfy_stub.mjs";
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
const values = (node, name) => widget(node, name).options.values();
const posted = (seen, route) =>
    seen.filter((c) => c.route.startsWith(`/symbiotica/${route}`))
        .map((c) => JSON.parse(c.init.body));

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

async function pick(node, name, value) {
    const w = widget(node, name);
    w.value = value;
    await w.callback.call(w, value);
    await settle();
}

test("each button sits under the field it acts on, the text last", async () => {
    const node = await promptsNode([]);
    assert.deepEqual(node.widgets.map((w) => w.name),
                     ["path",
                      "folder", "new folder", "rename folder",
                      "file", "new file", "rename file", "save file",
                      "text"]);
    assert.equal(widget(node, "folder").type, "combo");
    assert.equal(widget(node, "file").type, "combo");
});

test("the folder dropdown is the path's sub-folders, read from disk", async () => {
    // "me having to guess-type folder names": the list is what is there.
    const seen = [];
    const node = await promptsNode(seen);
    const listed = seen.find((c) => c.route.startsWith("/symbiotica/prompts-list"));
    assert.match(listed.route, /folder=%2Fp%2Fbakery%2Fprompts/);
    assert.deepEqual(values(node, "folder"),
                     ["/", "_image", "_rules", "_rules/old"]);
});

test("the file dropdown is the files in the picked folder only", async () => {
    const node = await promptsNode([]);
    assert.deepEqual(values(node, "file"), ["01-refs.md", "03-light.md"]);
    assert.equal(widget(node, "text").value, "TEXT OF _rules/01-refs.md");
});

test("the root is a folder too", async () => {
    const node = await promptsNode([], { folder: "/", file: "Chair.md" });
    assert.deepEqual(values(node, "file"), ["Chair.md"]);
    assert.equal(widget(node, "text").value, "TEXT OF Chair.md");
});

test("picking a folder shows its first file", async () => {
    const node = await promptsNode([]);
    await pick(node, "folder", "_image");
    assert.equal(widget(node, "file").value, "01-model.md");
    assert.equal(widget(node, "text").value, "TEXT OF _image/01-model.md");
    await pick(node, "folder", "_rules/old");
    assert.deepEqual(values(node, "file"), ["00-v1.md"]);
    assert.equal(widget(node, "text").value, "TEXT OF _rules/old/00-v1.md");
});

test("an empty folder says so", async () => {
    const node = await promptsNode([], { folder: "_flip", file: "" },
                                   { folders: ["_flip"], files: [] });
    assert.deepEqual(values(node, "file"), ["[no files in folder]"]);
});

test("with no path both dropdowns say so and nothing is fetched", async () => {
    const seen = [];
    const node = await promptsNode(seen, { path: "", folder: "", file: "" });
    assert.equal(seen.length, 0);
    assert.deepEqual(values(node, "folder"), ["[set path]"]);
    assert.deepEqual(values(node, "file"), ["[set path]"]);
});

test("a picked folder and file gone from disk stay offered", async () => {
    // Dropping to the root would silently re-point the node.
    const node = await promptsNode([], { folder: "_gone", file: "x.md" });
    assert.equal(widget(node, "folder").value, "_gone");
    assert.ok(values(node, "folder").includes("_gone"));
    assert.deepEqual(values(node, "file"), ["x.md"]);
    assert.equal(widget(node, "text").value, "");
});

test("picking another file loads it", async () => {
    const node = await promptsNode([]);
    await pick(node, "file", "03-light.md");
    assert.equal(widget(node, "text").value, "TEXT OF _rules/03-light.md");
});

test("an unsaved edit is not thrown away without asking", async () => {
    const node = await promptsNode([]);
    answer({ confirm: false });
    widget(node, "text").value = "MY EDIT";
    await pick(node, "file", "03-light.md");
    assert.equal(widget(node, "text").value, "MY EDIT");
    assert.equal(widget(node, "file").value, "01-refs.md");
    await pick(node, "folder", "_image");
    assert.equal(widget(node, "text").value, "MY EDIT");
    assert.equal(widget(node, "folder").value, "_rules");
});

test("save file posts the text to the folder and file on screen", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    answer();
    widget(node, "text").value = "NEW TEXT";
    await widget(node, "save file").callback();
    await settle();
    assert.deepEqual(posted(seen, "prompts-write"),
                     [{ folder: "/p/bakery/prompts", name: "_rules/01-refs.md",
                        text: "NEW TEXT" }]);
});

test("new file is created in the picked folder and selected", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    answer({ text: "09-new" });
    await widget(node, "new file").callback();
    await settle();
    assert.deepEqual(posted(seen, "prompts-write"),
                     [{ folder: "/p/bakery/prompts", name: "_rules/09-new.md",
                        text: "" }]);
    assert.equal(widget(node, "file").value, "09-new.md");
    assert.ok(values(node, "file").includes("09-new.md"));
});

test("new folder is created inside the picked folder and picked", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    answer({ text: "drafts" });
    await widget(node, "new folder").callback();
    await settle();
    assert.deepEqual(posted(seen, "prompts-mkdir"),
                     [{ folder: "/p/bakery/prompts", name: "_rules/drafts" }]);
    assert.equal(widget(node, "folder").value, "_rules/drafts");
    assert.ok(values(node, "folder").includes("_rules/drafts"));
    assert.deepEqual(values(node, "file"), ["[no files in folder]"]);
});

test("rename file renames the picked file in its folder and keeps it picked", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    answer({ text: "01-references" });
    await widget(node, "rename file").callback();
    await settle();
    assert.deepEqual(posted(seen, "prompts-rename"),
                     [{ folder: "/p/bakery/prompts", from: "_rules/01-refs.md",
                        to: "_rules/01-references.md" }]);
    assert.equal(widget(node, "file").value, "01-references.md");
    assert.deepEqual(values(node, "file"), ["01-references.md", "03-light.md"]);
});

test("rename folder renames the picked folder and everything under it", async () => {
    const seen = [];
    const node = await promptsNode(seen);
    answer({ text: "rules" });
    await widget(node, "rename folder").callback();
    await settle();
    assert.deepEqual(posted(seen, "prompts-rename"),
                     [{ folder: "/p/bakery/prompts", from: "_rules", to: "rules" }]);
    assert.equal(widget(node, "folder").value, "rules");
    assert.deepEqual(values(node, "folder"),
                     ["/", "_image", "rules", "rules/old"]);
    assert.deepEqual(values(node, "file"), ["01-refs.md", "03-light.md"]);
    // The same file, under its new name — the rename does not empty the editor.
    assert.equal(widget(node, "text").value, "TEXT OF rules/01-refs.md");
});

test("the path itself cannot be renamed, and a same name is a no-op", async () => {
    const seen = [];
    const node = await promptsNode(seen, { folder: "/", file: "Chair.md" });
    answer({ text: "x" });
    await widget(node, "rename folder").callback();
    answer({ text: "Chair" });
    await widget(node, "rename file").callback();
    await settle();
    assert.deepEqual(posted(seen, "prompts-rename"), []);
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
    // A Get node: its only widget holds the NAME of the constant, so the
    // static walk reads "platform_path" as if it were a folder.
    const getter = await create("GetNode", { Constant: "platform_path" });
    getter.outputs = [{ name: "STRING", links: [] }];
    link(getter, node, "path");
    app.graph._nodes = [getter, node];
    await node.onNodeCreated?.call(node);
    await settle();

    emit("symbiotica.prompts",
         { node_id: node.id, path: "/studio-assets/_platform/resources" });
    await settle();

    const listed = seen.filter((c) => c.route.includes("prompts-list")).pop();
    assert.match(listed.route,
                 /folder=%2Fstudio-assets%2F_platform%2Fresources/);
    assert.deepEqual(values(node, "folder"),
                     ["/", "_image", "_rules", "_rules/old"]);
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
