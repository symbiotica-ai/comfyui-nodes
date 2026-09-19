// ABOUTME: The Control Image node — a tree of the image folder the path names,
// ABOUTME: a thumbnail on every row, and the picked image big beside it.
import assert from "node:assert/strict";
import { test } from "node:test";

import { app, create, emit, fire, link, reset, setResponder, tick } from "./comfy_stub.mjs";
import "../../web/js/control_image.js";

const LIB = "/studio-assets/_platform/resources/controlnet-images";
const TREE = {
    folders: ["general", "general/1x1", "general/1x2", "project-specific"],
    images: ["general/1x1/1x1-box.png", "general/1x1/1x1-floor.png",
             "general/1x2/1x2-box-dots.png", "project-specific/chair.png",
             "wall.png"],
};

// A library that remembers what was done to it: an upload, a rename or a
// delete is announced on the window and every panel re-lists, so a router
// answering from a frozen tree would hand back the names it was just told to
// change.
function router(seen, tree = TREE) {
    // A listing with no `folders` key at all is an older server, which is what
    // a pushed sandbox runs until it restarts.
    const sendsFolders = !!tree.folders;
    let state = { folders: [...(tree.folders ?? [])],
                  images: [...tree.images] };
    return (route, _n, init) => {
        seen.push({ route, init });
        if (route.startsWith("/symbiotica/control-images?")) {
            const asked = new URLSearchParams(route.split("?")[1]).get("path");
            if (!asked) {
                return { ok: false, status: 400,
                         body: { error: "no image folder" } };
            }
            const body = { ok: true, library: asked, images: state.images };
            if (sendsFolders) body.folders = state.folders;
            return { ok: true, status: 200, body };
        }
        if (route.startsWith("/symbiotica/control-images-mkdir")) {
            const { name } = JSON.parse(init.body);
            state = { ...state, folders: [...state.folders, name].sort() };
            return { ok: true, status: 200, body: { ok: true, name } };
        }
        if (route.startsWith("/symbiotica/control-images-rename")) {
            const { from, to } = JSON.parse(init.body);
            const move = (rel) => (rel === from ? to
                : rel.startsWith(`${from}/`) ? to + rel.slice(from.length) : rel);
            state = { folders: state.folders.map(move).sort(),
                      images: state.images.map(move).sort() };
            return { ok: true, status: 200, body: { ok: true } };
        }
        if (route.startsWith("/symbiotica/control-images-delete")) {
            const { name } = JSON.parse(init.body);
            const under = (rel) => rel === name || rel.startsWith(`${name}/`);
            state = { folders: state.folders.filter((f) => !under(f)),
                      images: state.images.filter((f) => !under(f)) };
            return { ok: true, status: 200, body: { ok: true, name } };
        }
        if (route.startsWith("/symbiotica/control-images-upload")) {
            const folder = init.body.get("folder");
            const saved = init.body.getAll("files").map((f) => {
                const rel = folder ? `${folder}/${f.name}` : f.name;
                return state.images.includes(rel)
                    ? rel.replace(/\.png$/, "-2.png") : rel;
            });
            state = { ...state,
                      images: [...state.images, ...saved].sort() };
            return { ok: true, status: 200,
                     body: { ok: true, saved, refused: [] } };
        }
        return { ok: false, status: 404, body: { error: "no route" } };
    };
}

const settle = async () => { for (let i = 0; i < 20; i++) await tick(); };
const widget = (node, name) => node.widgets.find((w) => w.name === name);
const posted = (seen, route) =>
    seen.filter((c) => c.route.startsWith(`/symbiotica/${route}`)
                       && typeof c.init?.body === "string")
        .map((c) => JSON.parse(c.init.body));

// --- reaching into the panel -------------------------------------------------
const panel = (node) => widget(node, "images_panel").element;
function descendants(root, out = []) {
    for (const child of root.children ?? []) {
        out.push(child);
        descendants(child, out);
    }
    return out;
}
// The boxes the shell builds, by what they ARE: it nests, so counting children
// from the top breaks the moment a box is added above them.
const part = (node, name) =>
    descendants(panel(node)).find((e) => e._symPart === name);
const treeEl = (node) => part(node, "tree");
const rows = (node) => descendants(panel(node)).filter((e) => e._sym);
const tree = (node) => rows(node).map((r) => r._sym.rel);
const rowFor = (node, rel) => rows(node).find((r) => r._sym.rel === rel);
const button = (node, title) =>
    descendants(panel(node)).find((e) => e.title === title);
const rowAction = (node, rel, title) =>
    descendants(rowFor(node, rel)).find((e) => e.title === title);
const preview = (node) => descendants(panel(node)).find((e) => e.alt === "preview");
// The search field above the two panes, and the rows it lists. A result row
// carries the image it stands for on `_symHit`.
const searchBox = (node) => descendants(panel(node))
    .find((e) => e.placeholder === "Search images…");
const hits = (node) =>
    descendants(panel(node)).filter((e) => e._symHit).map((e) => e._symHit);
const hitFor = (node, rel) =>
    descendants(panel(node)).find((e) => e._symHit === rel);
const look = async (node, query) => {
    const box = searchBox(node);
    box.value = query;
    fire(box, "input", {});
    await settle();
};
const click = async (element) => {
    fire(element, "click", { stopPropagation() {} });
    await settle();
};

async function imageNode(seen, widgets = {}, listing = TREE) {
    reset();
    app.graph._nodes = [];
    setResponder(router(seen, listing));
    const node = await create("SymbioticaControlImage",
                              { image: "general/1x1/1x1-box.png", path: LIB,
                                ...widgets });
    node.inputs = [];
    app.graph._nodes = [node];
    await node.onNodeCreated?.call(node);
    await settle();
    return node;
}

function answer({ text = null, confirm = true } = {}) {
    app.extensionManager = {
        dialog: { prompt: async () => text, confirm: async () => confirm },
        toast: { add() {} },
    };
}

test("the node is a path, a tree and a preview — the dropdown is gone", async () => {
    const node = await imageNode([]);
    assert.deepEqual(node.widgets.map((w) => w.name),
                     ["image", "path", "images_panel"]);
    // The pick stays on the node — Python loads it and a saved workflow
    // restores it — but it takes no room.
    assert.equal(widget(node, "image").hidden, true);
    assert.equal(widget(node, "path").hidden, undefined);
    for (const title of ["New folder", "Re-read the folder", "Hide the tree"]) {
        assert.ok(button(node, title), `no ${title} button`);
    }
});

test("the panel does not pin the node's height", async () => {
    const node = await imageNode([]);
    const w = widget(node, "images_panel");
    assert.equal(w.computeSize, undefined);
    assert.equal(w.options.getMinHeight(), 60);
});

test("the tree is the library on disk: sub-folders first, then images", async () => {
    const seen = [];
    const node = await imageNode(seen);
    assert.match(seen[0].route, /control-images\?path=/);
    // `general/1x1` is open because the image on screen is in it.
    assert.deepEqual(tree(node),
                     ["general", "general/1x1", "general/1x1/1x1-box.png",
                      "general/1x1/1x1-floor.png", "general/1x2",
                      "project-specific", "wall.png"]);
});

test("a server that does not send folders still draws a tree", async () => {
    // A push lands new JS in a sandbox whose Python is still the one it booted
    // with; an empty tree would read as a node that has broken.
    const seen = [];
    const node = await imageNode(seen, {}, { images: TREE.images });
    assert.deepEqual(tree(node),
                     ["general", "general/1x1", "general/1x1/1x1-box.png",
                      "general/1x1/1x1-floor.png", "general/1x2",
                      "project-specific", "wall.png"]);
});

test("every image row carries a thumbnail of itself", async () => {
    // "i want to see the images in the folders/subfolders" — two masks with
    // the same prefix are one glance apart, not one click.
    const node = await imageNode([]);
    const thumb = rowFor(node, "general/1x1/1x1-floor.png").children[0];
    assert.equal(thumb.alt, "1x1-floor.png");
    assert.match(thumb.src, /\/symbiotica\/pick-thumb\?px=36/);
    assert.match(thumb.src,
                 new RegExp(encodeURIComponent(`${LIB}/general/1x1/1x1-floor.png`)));
    // A folder row has a chevron there instead, the same width, so the names
    // line up.
    assert.equal(rowFor(node, "general/1x2").children[0].src, undefined);
});

test("the picked image is the one shown, at full size", async () => {
    const node = await imageNode([]);
    assert.match(preview(node).src, /\/symbiotica\/local-image\?/);
    assert.match(preview(node).src,
                 new RegExp(encodeURIComponent(`${LIB}/general/1x1/1x1-box.png`)));
    assert.equal(preview(node).style.display, "");
});

test("clicking an image picks it and shows it", async () => {
    const node = await imageNode([]);
    await click(rowFor(node, "wall.png"));
    assert.equal(widget(node, "image").value, "wall.png");
    assert.match(preview(node).src,
                 new RegExp(encodeURIComponent(`${LIB}/wall.png`)));
});

test("clicking a folder opens it and leaves the pick alone", async () => {
    const node = await imageNode([]);
    await click(rowFor(node, "project-specific"));
    assert.ok(tree(node).includes("project-specific/chair.png"));
    assert.equal(widget(node, "image").value, "general/1x1/1x1-box.png");
    await click(rowFor(node, "project-specific"));
    assert.ok(!tree(node).includes("project-specific/chair.png"));
});

test("with no path the tree says so and nothing is fetched", async () => {
    const seen = [];
    const node = await imageNode(seen, { path: "", image: "" });
    assert.equal(seen.length, 0);
    assert.deepEqual(rows(node), []);
    assert.equal(preview(node).style.display, "none");
    assert.match(descendants(panel(node)).map((e) => e.textContent).join(" "),
                 /Set the path/);
});

test("a saved pick the library does not list is kept, not re-pointed", async () => {
    // Loading another image would quietly send the wrong control to a billed
    // render.
    const node = await imageNode([], { image: "gone/old.png" });
    assert.equal(widget(node, "image").value, "gone/old.png");
    assert.ok(widget(node, "image").options.values().includes("gone/old.png"));
});

test("new folder lands in the folder last clicked", async () => {
    const seen = [];
    const node = await imageNode(seen);
    answer({ text: "3x3" });
    await click(rowFor(node, "general"));
    await click(button(node, "New folder"));
    assert.deepEqual(posted(seen, "control-images-mkdir"),
                     [{ path: LIB, name: "general/3x3" }]);
    assert.ok(tree(node).includes("general/3x3"));
    assert.equal(widget(node, "image").value, "general/1x1/1x1-box.png");
});

test("rename on an image row keeps the pick on it", async () => {
    const seen = [];
    const node = await imageNode(seen);
    answer({ text: "box" });
    await click(rowAction(node, "general/1x1/1x1-box.png", "Rename"));
    // A name typed without an extension becomes a .png, or the tree would
    // lose the file it just renamed.
    assert.deepEqual(posted(seen, "control-images-rename"),
                     [{ path: LIB, from: "general/1x1/1x1-box.png",
                        to: "general/1x1/box.png" }]);
    assert.equal(widget(node, "image").value, "general/1x1/box.png");
    assert.ok(tree(node).includes("general/1x1/box.png"));
});

test("rename on a folder row moves everything under it", async () => {
    const seen = [];
    const node = await imageNode(seen);
    answer({ text: "shared" });
    await click(rowAction(node, "general", "Rename"));
    assert.deepEqual(posted(seen, "control-images-rename"),
                     [{ path: LIB, from: "general", to: "shared" }]);
    assert.equal(widget(node, "image").value, "shared/1x1/1x1-box.png");
    assert.ok(tree(node).includes("shared/1x1"));
});

test("delete asks first, and a no leaves the image where it was", async () => {
    const seen = [];
    const node = await imageNode(seen);
    answer({ confirm: false });
    await click(rowAction(node, "wall.png", "Delete"));
    assert.deepEqual(posted(seen, "control-images-delete"), []);
    assert.ok(tree(node).includes("wall.png"));
});

test("deleting the picked image moves the node on to one that is there", async () => {
    const node = await imageNode([]);
    answer();
    await click(rowAction(node, "general/1x1/1x1-box.png", "Delete"));
    assert.ok(!tree(node).includes("general/1x1/1x1-box.png"));
    assert.equal(widget(node, "image").value, "general/1x1/1x1-floor.png");
});

test("the folder's confirmation says how many images go with it", async () => {
    const node = await imageNode([]);
    const asked = [];
    app.extensionManager = {
        dialog: { confirm: async ({ message }) => { asked.push(message); return false; },
                  prompt: async () => null },
        toast: { add() {} },
    };
    await click(rowAction(node, "general", "Delete"));
    assert.match(asked[0], /folder general and the 3 images in it/);
    assert.match(asked[0], /cannot be undone/);
});

test("files dropped on a folder row are uploaded into it", async () => {
    const seen = [];
    const node = await imageNode(seen);
    const file = new File([new Uint8Array([1, 2, 3])], "mask.png",
                          { type: "image/png" });
    fire(treeEl(node), "drop", {
        preventDefault() {}, stopPropagation() {},
        target: rowFor(node, "project-specific"),
        dataTransfer: { files: [file] },
    });
    await settle();
    const sent = seen.find((c) => c.route.includes("control-images-upload"));
    assert.ok(sent, "nothing was uploaded");
    assert.equal(sent.init.body.get("folder"), "project-specific");
    assert.equal(sent.init.body.get("path"), LIB);
    assert.deepEqual(sent.init.body.getAll("files").map((f) => f.name),
                     ["mask.png"]);
    // The server names what it wrote, and that is what the node picks up.
    assert.ok(tree(node).includes("project-specific/mask.png"));
    assert.equal(widget(node, "image").value, "project-specific/mask.png");
});

test("a drop with no row under it lands in the folder last clicked", async () => {
    const seen = [];
    const node = await imageNode(seen);
    await click(rowFor(node, "general/1x2"));
    fire(treeEl(node), "drop", {
        preventDefault() {}, stopPropagation() {},
        target: treeEl(node),
        dataTransfer: { files: [new File(["x"], "dots.png")] },
    });
    await settle();
    const sent = seen.find((c) => c.route.includes("control-images-upload"));
    assert.equal(sent.init.body.get("folder"), "general/1x2");
});

test("anything that is not an image is never sent", async () => {
    const seen = [];
    const node = await imageNode(seen);
    answer();
    fire(treeEl(node), "drop", {
        preventDefault() {}, stopPropagation() {},
        target: treeEl(node),
        dataTransfer: { files: [new File(["x"], "notes.txt")] },
    });
    await settle();
    assert.ok(!seen.some((c) => c.route.includes("control-images-upload")));
});

test("nothing is dropped into a node with no path", async () => {
    const seen = [];
    const node = await imageNode(seen, { path: "", image: "" });
    let stopped = false;
    fire(treeEl(node), "drop", {
        preventDefault() { stopped = true; }, stopPropagation() {},
        target: treeEl(node),
        dataTransfer: { files: [new File(["x"], "a.png")] },
    });
    await settle();
    // Not even swallowed: with nowhere to put it, the canvas's own answer to a
    // dropped image is better than none.
    assert.equal(stopped, false);
    assert.equal(seen.length, 0);
});

test("the tree folds away to a rail that can reopen it", async () => {
    const node = await imageNode([]);
    await click(button(node, "Hide the tree"));
    assert.equal(node.properties.symbiotica_images_shut, true);
    assert.equal(part(node, "side").style.width, "22px");
    assert.deepEqual(rows(node), []);
    await click(button(node, "Show the tree"));
    assert.equal(part(node, "side").style.width, "210px");
    assert.ok(rows(node).length > 0);
});

test("retyping the path re-lists against the new library", async () => {
    const seen = [];
    const node = await imageNode(seen);
    const w = widget(node, "path");
    w.value = "/other/lib";
    await w.callback?.call(w, "/other/lib");
    await settle();
    const listed = seen.filter((c) => c.route.includes("control-images?")).pop();
    assert.match(listed.route, /path=%2Fother%2Flib/);
});

test("a String node wired into path names the library", async () => {
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
    assert.ok(tree(node).includes("wall.png"));
});

test("a run hands back a path the canvas cannot read, and the tree fills in", async () => {
    const seen = [];
    reset();
    app.graph._nodes = [];
    setResponder(router(seen));
    const node = await create("SymbioticaControlImage", { image: "", path: "" });
    node.inputs = [];
    // A Get node with no Set of that name on the canvas: there is nothing for
    // the walk to follow, and the constant's NAME is never the answer.
    const getter = await create("GetNode", { Constant: "$$controlnet" });
    getter.type = "GetNode";
    getter.outputs = [{ name: "STRING", links: [] }];
    link(getter, node, "path");
    app.graph._nodes = [getter, node];
    await node.onNodeCreated?.call(node);
    await settle();
    assert.deepEqual(rows(node), []);

    emit("symbiotica.control_image", { node_id: node.id, path: LIB });
    await settle();
    assert.ok(tree(node).includes("wall.png"));
    assert.equal(node.properties.symbiotica_ran_path, LIB);
});

test("a typed path still beats what the last run received", async () => {
    const seen = [];
    const node = await imageNode(seen, { path: "/other/lib", image: "" });
    node.properties.symbiotica_ran_path = LIB;
    node._symRefreshImages();
    await settle();
    const listed = seen.filter((c) => c.route.includes("control-images?")).pop();
    assert.match(listed.route, /path=%2Fother%2Flib/);
});


// --- the search field --------------------------------------------------------
// "let's add search field to Prompts and Control Image nodes so i can type the
// name of the image" (2026-09-19): the tree answers what is in a folder, not
// which sub-folder a half-remembered name lives in.
test("typing a name lists every image that holds it, wherever it sits", async () => {
    const node = await imageNode([]);
    await look(node, "box");
    assert.deepEqual(hits(node), ["general/1x1/1x1-box.png",
                                  "general/1x2/1x2-box-dots.png"]);
    // A name only the FOLDER holds still answers.
    await look(node, "project");
    assert.deepEqual(hits(node), ["project-specific/chair.png"]);
    await look(node, "zzz");
    assert.deepEqual(hits(node), []);
});

test("a result carries its own thumbnail", async () => {
    // A column of file names is not how you tell two renders of the same asset
    // apart — the tree rows earned their thumbnails for the same reason.
    const node = await imageNode([]);
    await look(node, "floor");
    const thumb = hitFor(node, "general/1x1/1x1-floor.png").children[0];
    assert.equal(thumb.alt, "1x1-floor.png");
    assert.match(thumb.src,
                 new RegExp(encodeURIComponent(`${LIB}/general/1x1/1x1-floor.png`)));
});

test("picking a result picks that image and empties the box", async () => {
    const node = await imageNode([]);
    await look(node, "chair");
    await click(hitFor(node, "project-specific/chair.png"));
    assert.equal(widget(node, "image").value, "project-specific/chair.png");
    assert.match(preview(node).src,
                 new RegExp(encodeURIComponent(`${LIB}/project-specific/chair.png`)));
    assert.equal(searchBox(node).value, "");
    assert.deepEqual(hits(node), []);
});

test("the search survives the fold that takes the tree away", async () => {
    // "i want the search field to be visible when the sidebar is collapsed":
    // it sits ABOVE both panes, so folding the tree cannot reach it.
    const node = await imageNode([]);
    await click(button(node, "Hide the tree"));
    assert.deepEqual(rows(node), []);
    assert.ok(searchBox(node), "the search field went with the tree");
    await look(node, "chair");
    await click(hitFor(node, "project-specific/chair.png"));
    assert.equal(widget(node, "image").value, "project-specific/chair.png");
});

test("an image renamed under an open list leaves it by its new name", async () => {
    const node = await imageNode([]);
    await look(node, "floor");
    answer({ text: "1x1-floorboards.png" });
    await click(rowAction(node, "general/1x1/1x1-floor.png", "Rename"));
    assert.deepEqual(hits(node), ["general/1x1/1x1-floorboards.png"]);
});
