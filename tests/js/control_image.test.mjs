// ABOUTME: The Control Image node — the dropdown lists every image under the
// ABOUTME: node's path, and the preview is fetched from the folder it resolved.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, emit, images, link, reset, setResponder, tick } from "./comfy_stub.mjs";
import "../../web/js/control_image.js";

const LIB = "/studio-assets/_platform/resources/controlnet-images";
const IMAGES = {
    [LIB]: ["general/1x1/1x1-box.png", "general/1x1/1x1-floor.png",
            "project-specific/chair/Loveletter Lounge Chair.png"],
    "/other/lib": ["wall.png"],
};

const settle = async () => { for (let i = 0; i < 20; i++) await tick(); };
const widget = (node, name) => node.widgets.find((w) => w.name === name);
const valuesOf = (node) => {
    const w = widget(node, "image");
    return typeof w.options.values === "function"
        ? w.options.values() : w.options.values;
};

// The listing is cached per path for the whole canvas and that cache outlives
// reset() — it is module state in the extension, not the stub's. A test that
// wants to observe the REQUEST has to name a folder no other test has.
let unique = 0;
const freshPath = () => {
    const name = `/lib${++unique}`;
    IMAGES[name] = ["a.png"];
    return name;
};

function router(seen) {
    return (route) => {
        seen.push(route);
        if (route.startsWith("/symbiotica/control-images")) {
            const asked = new URLSearchParams(route.split("?")[1]).get("path");
            if (!asked) {
                return { ok: false, status: 400,
                         body: { error: "no image folder" } };
            }
            return { ok: true, status: 200,
                     body: { ok: true, library: asked,
                             images: IMAGES[asked] ?? [] } };
        }
        return { ok: false, status: 404, body: { error: "no route" } };
    };
}

async function imageNode(seen, path = LIB, image = "") {
    reset();
    app.graph._nodes = [];
    setResponder(router(seen));
    const node = await create("SymbioticaControlImage", { image, path });
    node.inputs = [];
    app.graph._nodes = [node];
    await node.onNodeCreated?.call(node);
    await settle();
    return node;
}

test("the dropdown lists every image under the path, sub-folders in the value", async () => {
    const seen = [];
    const node = await imageNode(seen);
    assert.deepEqual(valuesOf(node), IMAGES[LIB]);
    assert.ok(seen.some((r) => r.includes(encodeURIComponent(LIB))),
              `expected a listing for ${LIB}, got ${seen.join(", ")}`);
});

test("with no path the dropdown says so and nothing is fetched", async () => {
    const seen = [];
    const node = await imageNode(seen, "");
    assert.deepEqual(valuesOf(node), ["[set a path]"]);
    assert.equal(seen.filter((r) => r.includes("control-images")).length, 0);
});

test("retyping the path re-lists against the new folder", async () => {
    const seen = [];
    const node = await imageNode(seen);
    const w = widget(node, "path");
    w.value = "/other/lib";
    await w.callback?.call(w, "/other/lib");
    await settle();
    assert.deepEqual(valuesOf(node), ["wall.png"]);
});

test("a saved pick the folder does not list is still offered", async () => {
    // VALIDATE_INPUTS is what rejects it, with a reason — the dropdown quietly
    // dropping it would lose a workflow's value on the first click.
    const seen = [];
    const node = await imageNode(seen, LIB, "gone/old.png");
    assert.ok(valuesOf(node).includes("gone/old.png"));
});

test("an empty folder says so rather than going blank", async () => {
    const seen = [];
    const path = freshPath();
    IMAGES[path] = [];
    const node = await imageNode(seen, path);
    assert.deepEqual(valuesOf(node), [`[no images under ${path}]`]);
});

test("a String node wired into path names the folder", async () => {
    const seen = [];
    reset();
    app.graph._nodes = [];
    setResponder(router(seen));
    const node = await create("SymbioticaControlImage", { image: "", path: "" });
    node.inputs = [];
    const literal = await create("String", { value: LIB });
    literal.outputs = [{ name: "STRING", links: [] }];
    link(literal, node, "path");
    app.graph._nodes = [literal, node];
    await node.onNodeCreated?.call(node);
    await settle();
    assert.deepEqual(valuesOf(node), IMAGES[LIB]);
});

test("the preview is fetched from the folder the listing resolved", async () => {
    const seen = [];
    const path = freshPath();
    const node = await imageNode(seen, path);
    const w = widget(node, "image");
    w.value = "a.png";
    await w.callback?.call(w, "a.png");
    await settle();
    // A preview is an Image src, not a fetch: the URL it reached for is the
    // whole observable behaviour.
    const wanted = `path=${encodeURIComponent(`${path}/a.png`)}`;
    assert.ok(images.some((src) => src.includes("/symbiotica/local-image")
                                && src.includes(wanted)),
              `expected a local-image preview for ${path}/a.png, got ${images.join(", ")}`);
});

test("a placeholder is never fetched", async () => {
    const seen = [];
    const path = freshPath();
    const node = await imageNode(seen, path);
    const w = widget(node, "image");
    const before = images.length;
    w.value = "[set a path]";
    await w.callback?.call(w, "[set a path]");
    await settle();
    assert.deepEqual(images.slice(before), []);
});

test("a run hands back a path the canvas cannot read, and the dropdown fills in", async () => {
    const seen = [];
    reset();
    app.graph._nodes = [];
    setResponder(router(seen));
    const node = await create("SymbioticaControlImage", { image: "", path: "" });
    node.inputs = [];
    // A Get node: its only widget holds the NAME of the constant, so the
    // static walk reads "$$controlnet" as if it were a folder.
    const getter = await create("GetNode", { Constant: "$$controlnet" });
    getter.outputs = [{ name: "STRING", links: [] }];
    link(getter, node, "path");
    app.graph._nodes = [getter, node];
    await node.onNodeCreated?.call(node);
    await settle();
    assert.deepEqual(valuesOf(node), ["[no images under $$controlnet]"]);

    emit("symbiotica.control_image", { node_id: node.id, path: LIB });
    await settle();
    assert.deepEqual(valuesOf(node), IMAGES[LIB]);
});

test("the run path is saved with the workflow, so a reload still knows it", async () => {
    const seen = [];
    reset();
    app.graph._nodes = [];
    setResponder(router(seen));
    const node = await create("SymbioticaControlImage", { image: "", path: "" });
    node.inputs = [];
    const getter = await create("GetNode", { Constant: "$$controlnet" });
    getter.outputs = [{ name: "STRING", links: [] }];
    link(getter, node, "path");
    app.graph._nodes = [getter, node];
    await node.onNodeCreated?.call(node);
    await settle();
    emit("symbiotica.control_image", { node_id: node.id, path: LIB });
    await settle();
    assert.equal(node.properties.symbiotica_ran_path, LIB);
});

test("a typed path still beats what the last run received", async () => {
    const seen = [];
    const node = await imageNode(seen, "/other/lib");
    node.properties = { symbiotica_ran_path: LIB };
    assert.deepEqual(valuesOf(node), ["wall.png"]);
});
