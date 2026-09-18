// ABOUTME: The project_path walk — what the canvas can read off a wire before
// ABOUTME: anything is queued, including one that arrives through a Set/Get pair.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, link, reset } from "./comfy_stub.mjs";
import { resolveProjectPath } from "../../web/js/order_source.js";

const PROJECT = "studios/imperia/bakery";

// The nodes as litegraph holds them: `type` is what the walk reads, and the
// stub builds `comfyClass`, so a test says which is which.
async function node(type, widgets = {}) {
    const n = await create(type, widgets);
    n.type = type;
    return n;
}

// Asset Focus (or any panel) with `project_path` on a socket, not typed.
async function reader() {
    const n = await node("SymbioticaAssetFocus", { project_path: "" });
    return n;
}

test("a typed project_path is the answer, wires or not", async () => {
    reset();
    const focus = await reader();
    focus.widgets[0].value = PROJECT;
    assert.equal(resolveProjectPath(focus), PROJECT);
});

test("a wired project_path is read off the node feeding it", async () => {
    reset();
    const focus = await reader();
    const library = await node("SymbioticaStudioLibrary", { selection: PROJECT });
    link(library, focus, "project_path");
    assert.equal(resolveProjectPath(focus), PROJECT);
});

test("a project_path arriving through a Set/Get pair resolves", async () => {
    // The GetNode's only widget holds the NAME of the constant. Reading it as a
    // string gave every panel a folder called `_project_path`, and the pickers
    // came up empty on a canvas where the value was sitting one hop away.
    reset();
    const library = await node("SymbioticaStudioLibrary", { selection: PROJECT });
    const setter = await node("SetNode", { previousName: "_project_path" });
    link(library, setter, "STRING");
    const getter = await node("GetNode", { value: "_project_path" });
    const focus = await reader();
    link(getter, focus, "project_path");

    assert.equal(resolveProjectPath(focus), PROJECT);
});

test("a Get with no Set of that name resolves to nothing, not to its name",
     async () => {
    // A folder called `_project_path` does not exist; asking for one reads as
    // "this project is empty" rather than "this wire cannot be read here".
    reset();
    const getter = await node("GetNode", { value: "_project_path" });
    const focus = await reader();
    link(getter, focus, "project_path");

    assert.equal(resolveProjectPath(focus), "");
});

test("a Set with nothing wired in resolves to nothing", async () => {
    reset();
    const setter = await node("SetNode", { previousName: "_project_path" });
    const getter = await node("GetNode", { value: "_project_path" });
    const focus = await reader();
    link(getter, focus, "project_path");

    assert.equal(setter.type, "SetNode");
    assert.equal(resolveProjectPath(focus), "");
});

test("the pair is matched by name, not by being the only one", async () => {
    reset();
    const other = await node("SymbioticaStudioLibrary", { selection: "studios/other" });
    const otherSet = await node("SetNode", { previousName: "_controlnet-images" });
    link(other, otherSet, "STRING");
    const library = await node("SymbioticaStudioLibrary", { selection: PROJECT });
    const setter = await node("SetNode", { previousName: "_project_path" });
    link(library, setter, "STRING");
    const getter = await node("GetNode", { value: "_project_path" });
    const focus = await reader();
    link(getter, focus, "project_path");

    assert.equal(resolveProjectPath(focus), PROJECT);
});

test("a Get pointing at itself through a Set does not hang", async () => {
    reset();
    const setter = await node("SetNode", { previousName: "loop" });
    const getter = await node("GetNode", { value: "loop" });
    link(getter, setter, "STRING");
    const focus = await reader();
    link(getter, focus, "project_path");

    assert.equal(resolveProjectPath(focus), "");
});
