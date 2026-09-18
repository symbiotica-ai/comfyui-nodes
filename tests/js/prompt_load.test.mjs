// ABOUTME: The Prompt Load node — one dropdown of every file under the path,
// ABOUTME: filled from a typed path, a wired one, or the path a run handed back.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, emit, link, reset, setResponder, tick } from "./comfy_stub.mjs";
import "../../web/js/prompts.js";

const FILES = ["Chair.md", "_image/01-model.md", "_rules/01-refs.md",
               "_rules/03-light.md"];

function router(seen, files = FILES) {
    return (route, _n, init) => {
        seen.push({ route, init });
        if (route.startsWith("/symbiotica/prompts-list")) {
            return { ok: true, status: 200,
                     body: { ok: true, folders: ["_image", "_rules"], files } };
        }
        return { ok: false, status: 404, body: { error: "no route" } };
    };
}

const settle = async () => { for (let i = 0; i < 20; i++) await tick(); };
const widget = (node, name) => node.widgets.find((w) => w.name === name);
const values = (node, name) => widget(node, name).options.values();

async function loadNode(seen, widgets = {}, files = FILES) {
    reset();
    app.graph._nodes = [];
    setResponder(router(seen, files));
    const node = await create("SymbioticaPromptLoad",
                              { path: "/p/bakery/prompts", file: "", ...widgets });
    node.inputs = [];
    app.graph._nodes = [node];
    await node.onNodeCreated?.call(node);
    await settle();
    return node;
}

test("the dropdown is every prompt file under the path, sub-folders included", async () => {
    const node = await loadNode([]);
    assert.equal(widget(node, "file").type, "combo");
    assert.deepEqual(values(node, "file"), FILES);
});

test("it is a path and a file, and nothing else", async () => {
    // No root_dir, no text area, and no button: a button widget shifts every
    // widget saved after it.
    const node = await loadNode([]);
    assert.deepEqual(node.widgets.map((w) => w.name), ["path", "file"]);
});

test("with no path the dropdown says so and asks for nothing", async () => {
    const seen = [];
    const node = await loadNode(seen, { path: "" });
    assert.deepEqual(values(node, "file"), ["[set path]"]);
    assert.equal(seen.length, 0);
});

test("nothing picked takes the first file", async () => {
    const node = await loadNode([]);
    assert.equal(widget(node, "file").value, "Chair.md");
});

test("a saved pick is kept, not re-pointed at the first file", async () => {
    const node = await loadNode([], { file: "_rules/03-light.md" });
    assert.equal(widget(node, "file").value, "_rules/03-light.md");
});

test("a saved pick the listing does not hold stays offered", async () => {
    // The file may be gone for a moment. Silently loading another prompt on
    // the next queue is worse than showing a name that is not there.
    const node = await loadNode([], { file: "Sofa.md" });
    assert.equal(widget(node, "file").value, "Sofa.md");
    assert.ok(values(node, "file").includes("Sofa.md"));
});

test("a path typed after the fact fills the dropdown", async () => {
    const seen = [];
    const node = await loadNode(seen, { path: "" });
    const pathW = widget(node, "path");
    pathW.value = "/p/bakery/prompts";
    await pathW.callback?.call(pathW, pathW.value);
    await settle();
    assert.deepEqual(values(node, "file"), FILES);
});

test("a path that changes drops a pick the new folder does not hold", async () => {
    const node = await loadNode([], { file: "_rules/03-light.md" });
    setResponder(router([], ["only.md"]));
    const pathW = widget(node, "path");
    pathW.value = "/p/other/prompts";
    await pathW.callback?.call(pathW, pathW.value);
    await settle();
    assert.equal(widget(node, "file").value, "only.md");
});

test("the first listing of a path refreshes the mount, later ones do not", async () => {
    // A file written by the platform's file manager is not on the mount until
    // something goes and looks; the walk is a FUSE traversal, not a free call.
    const seen = [];
    const node = await loadNode(seen);
    const lists = () => seen.filter((c) => c.route.startsWith("/symbiotica/prompts-list"));
    assert.equal(lists().length, 1);
    assert.ok(lists()[0].route.includes("sync=1"));
    node._symRefreshPromptLoad();
    await settle();
    assert.equal(lists().length, 2);
    assert.ok(!lists()[1].route.includes("sync=1"));
});

test("a path on a wire is read from the node behind it", async () => {
    const seen = [];
    const node = await loadNode(seen, { path: "" });
    const source = await create("PrimitiveString", { value: "/p/wired/prompts" });
    source.addOutput("STRING", "STRING");
    app.graph._nodes = [node, source];
    link(source, node, "path");
    await node.onConnectionsChange?.call(node);
    await settle();
    assert.deepEqual(values(node, "file"), FILES);
});

test("a path only a run knows fills the dropdown after one queue", async () => {
    // A Get node's widget holds the NAME of the constant. The run is what
    // knows the path, and it hands it back.
    const seen = [];
    const node = await loadNode(seen, { path: "" });
    node.inputs = [{ name: "path", link: 99 }];
    emit("symbiotica.prompt_load",
         { node_id: node.id, path: "/p/from-the-run/prompts" });
    await settle();
    assert.equal(node.properties.symbiotica_ran_path, "/p/from-the-run/prompts");
    assert.deepEqual(values(node, "file"), FILES);
    assert.ok(seen.some((c) => c.route.includes(encodeURIComponent("/p/from-the-run/prompts"))));
});

test("a Prompts panel's save puts the new file in the dropdown", async () => {
    const seen = [];
    const node = await loadNode(seen, {}, FILES);
    setResponder(router(seen, [...FILES, "Sofa.md"]));
    window.dispatchEvent(new CustomEvent("symbiotica-prompts-saved",
                                         { detail: { path: "/p/bakery/prompts" } }));
    await settle();
    assert.ok(values(node, "file").includes("Sofa.md"));
});

test("a listing that fails says what went wrong instead of an empty list", async () => {
    reset();
    app.graph._nodes = [];
    setResponder(() => ({ ok: false, status: 500, body: { error: "no such folder" } }));
    const node = await create("SymbioticaPromptLoad",
                              { path: "/p/gone", file: "" });
    node.inputs = [];
    app.graph._nodes = [node];
    await node.onNodeCreated?.call(node);
    await settle();
    assert.deepEqual(values(node, "file"), ["[no such folder]"]);
});
