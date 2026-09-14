// ABOUTME: The Control Image node's preview — the dropdown value names a file
// ABOUTME: under the folder widget's folder, and the view URL must match it.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, images, reset, setResponder, tick } from "./comfy_stub.mjs";
import { viewParams } from "../../web/js/control_image.js";

test("a relative name splits into the controlnet subfolder and the file", () => {
    assert.deepEqual(viewParams("1x1-floor.png"), { filename: "1x1-floor.png", subfolder: "controlnet", type: "input" });
    assert.deepEqual(viewParams("bakery/counter.png"), { filename: "counter.png", subfolder: "controlnet/bakery", type: "input" });
    assert.deepEqual(viewParams("a/b/c.png"), { filename: "c.png", subfolder: "controlnet/a/b", type: "input" });
    assert.equal(viewParams(""), null);
    assert.equal(viewParams("[no images under input/controlnet]"), null);
});

test("the folder widget's value is what the subfolder is built from", () => {
    assert.deepEqual(viewParams("wall.png", "guides"),
                     { filename: "wall.png", subfolder: "guides", type: "input" });
    assert.deepEqual(viewParams("a/b.png", "guides"),
                     { filename: "b.png", subfolder: "guides/a", type: "input" });
});

// --- the dropdown follows the folder widget -----------------------------------
// INPUT_TYPES is built once, at registration, against the DEFAULT folder — a
// classmethod cannot read a sibling widget. So the listing is asked for here,
// and the combo's values have to be a function or the dropdown keeps showing
// the folder the node was registered with.

const LIBRARIES = {
    controlnet: ["1x1-box.png", "1x2-box-dots.png"],
    guides: ["wall.png"],
};

// The listing is cached per root+folder for the whole canvas and that cache
// outlives reset() — it is module state in the extension, not the stub's. A
// test that wants to observe the REQUEST has to ask for a library no other
// test has named.
let unique = 0;
const freshFolder = () => {
    const name = `lib${++unique}`;
    LIBRARIES[name] = ["1x1-box.png"];
    return name;
};

async function imageNode(seen, folder = "controlnet", root = "") {
    reset();
    app.graph._nodes = [];
    setResponder((route) => {
        seen.push(route);
        if (route.startsWith("/symbiotica/control-images")) {
            const q = new URLSearchParams(route.split("?")[1]);
            const asked = q.get("folder");
            const base = q.get("root") ?? "";
            return { ok: true, status: 200,
                     body: { ok: true, folder: asked,
                             library: `${base || "/input"}/${asked}`,
                             images: LIBRARIES[asked] ?? [] } };
        }
        return { ok: false, status: 404, body: { error: "no route" } };
    });
    const node = await create("SymbioticaControlImage",
                              { root, folder, image: "" });
    app.graph._nodes = [node];
    await node.onNodeCreated?.call(node);
    for (let i = 0; i < 20; i++) await tick();
    return node;
}

const valuesOf = (node) => {
    const w = node.widgets.find((x) => x.name === "image");
    return typeof w.options.values === "function"
        ? w.options.values() : w.options.values;
};

test("the dropdown lists the folder the widget names", async () => {
    const seen = [];
    const node = await imageNode(seen, "guides");
    assert.ok(seen.some((r) => r.includes("folder=guides")),
              `expected a listing for guides, got ${seen.join(", ")}`);
    assert.deepEqual(valuesOf(node), ["wall.png"]);
});

test("retyping the folder re-lists the dropdown", async () => {
    const seen = [];
    const node = await imageNode(seen);
    assert.deepEqual(valuesOf(node), LIBRARIES.controlnet);
    const w = node.widgets.find((x) => x.name === "folder");
    w.value = "guides";
    w.callback?.call(w, "guides");
    for (let i = 0; i < 20; i++) await tick();
    assert.deepEqual(valuesOf(node), ["wall.png"]);
});

test("a saved pick the folder does not list is still offered", async () => {
    // VALIDATE_INPUTS is what rejects it, with a reason — the dropdown quietly
    // dropping it would lose a workflow's value on the first click.
    const seen = [];
    const node = await imageNode(seen, "guides");
    const w = node.widgets.find((x) => x.name === "image");
    w.value = "gone.png";
    assert.deepEqual(valuesOf(node), ["wall.png", "gone.png"]);
});

test("an empty folder says so rather than going blank", async () => {
    const seen = [];
    const node = await imageNode(seen, "empty");
    assert.deepEqual(valuesOf(node), ["[no images under input/empty]"]);
});

// --- the library moved off ComfyUI's input directory --------------------------
// It lives on the studio-assets mount now, which `/view` cannot serve and
// LoadImage cannot reach — so the root is a widget and the preview changes door.

const RESOURCES = "/studio-assets/_platform/resources";

test("a named root rides on the listing request", async () => {
    const seen = [];
    await imageNode(seen, freshFolder(), RESOURCES);
    const listing = seen.find((r) => r.startsWith("/symbiotica/control-images"));
    assert.ok(listing.includes(`root=${encodeURIComponent(RESOURCES)}`),
              `expected the root in ${listing}`);
});

test("no root sends none", async () => {
    const seen = [];
    await imageNode(seen, freshFolder());
    const listing = seen.find((r) => r.startsWith("/symbiotica/control-images"));
    assert.ok(!listing.includes("root="), `expected no root in ${listing}`);
});

test("changing the root re-lists against the new mount", async () => {
    const seen = [];
    const node = await imageNode(seen, freshFolder());
    const w = node.widgets.find((x) => x.name === "root");
    w.value = RESOURCES;
    w.callback?.call(w, RESOURCES);
    for (let i = 0; i < 20; i++) await tick();
    const last = seen.filter(
        (r) => r.startsWith("/symbiotica/control-images")).pop();
    assert.ok(last.includes(`root=${encodeURIComponent(RESOURCES)}`),
              `expected the new root in ${last}`);
});

test("a file on another mount previews through local-image, not /view", async () => {
    const folder = freshFolder();
    const node = await imageNode([], folder, RESOURCES);
    const w = node.widgets.find((x) => x.name === "image");
    w.value = "1x1-box.png";
    w.callback?.call(w, "1x1-box.png");
    for (let i = 0; i < 20; i++) await tick();
    const src = images[images.length - 1] ?? "";
    assert.ok(src.includes("/symbiotica/local-image"), `got ${src}`);
    assert.ok(decodeURIComponent(src).includes(
        `${RESOURCES}/${folder}/1x1-box.png`), `got ${src}`);
});

test("a file in the input directory still previews through /view", async () => {
    const folder = freshFolder();
    const node = await imageNode([], folder);
    const w = node.widgets.find((x) => x.name === "image");
    w.value = "1x1-box.png";
    w.callback?.call(w, "1x1-box.png");
    for (let i = 0; i < 20; i++) await tick();
    const src = images[images.length - 1] ?? "";
    assert.ok(src.includes("/view?"), `got ${src}`);
    assert.ok(src.includes(`subfolder=${folder}`), `got ${src}`);
});
