// ABOUTME: Tests for studio_library.js — the pure selection seam and the
// ABOUTME: node's summary widget behavior under the comfy stub.
import { test } from "node:test";
import assert from "node:assert/strict";

import { calls, create, reset, setResponder, fire } from "./comfy_stub.mjs";
import "../../web/js/studio_library.js";
import { summaryLabel, applySelection, filterEntries } from "../../web/js/studio_library.js";

const tick = () => new Promise((r) => setTimeout(r, 0));

// Depth-first search of the stub DOM tree for the first node matching pred.
function find(root, pred) {
    if (!root) return null;
    if (pred(root)) return root;
    for (const child of root.children ?? []) {
        const hit = find(child, pred);
        if (hit) return hit;
    }
    return null;
}

async function openOverlay(node) {
    const browse = node.widgets.find((w) => w.name === "📂 Browse studio library");
    browse.callback();
    await tick();
    return document.body.children.at(-1);
}

test("summaryLabel is prefix-bearing and handles empty", () => {
    assert.equal(summaryLabel(""), "no selection");
    assert.match(summaryLabel("studios/ggs/references/hero.png"), /ggs/);
    assert.equal(summaryLabel("studios/ggs/references/hero.png"), "ggs · references/hero.png");
});

test("filterEntries matches names case-insensitively, empty query passes all", () => {
    const entries = [
        { name: "references", type: "dir" },
        { name: "renders", type: "dir" },
        { name: "brief.txt", type: "file" },
    ];
    assert.deepEqual(filterEntries(entries, "ren").map((e) => e.name), ["references", "renders"]);
    assert.deepEqual(filterEntries(entries, "").map((e) => e.name), ["references", "renders", "brief.txt"]);
    assert.deepEqual(filterEntries(entries, "  ").map((e) => e.name), ["references", "renders", "brief.txt"]);
    assert.deepEqual(filterEntries(entries, "BRIEF").map((e) => e.name), ["brief.txt"]);
    assert.deepEqual(filterEntries(entries, "zzz"), []);
});

test("applySelection writes the rel into the selection widget and summary", async () => {
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    applySelection(node, "studios/ggs/references/hero.png");
    const sel = node.widgets.find((w) => w.name === "selection");
    const summary = node.widgets.find((w) => w.name === "studio_summary");
    assert.equal(sel.value, "studios/ggs/references/hero.png");
    assert.match(summary.value, /ggs/);
    assert.equal(summary.serialize, false);
});

test("summary restores from a loaded workflow via onConfigure", async () => {
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const sel = node.widgets.find((w) => w.name === "selection");
    sel.value = "studios/ggs/brief.txt";  // as if restored by configure()
    node.onConfigure?.();
    await tick();
    const summary = node.widgets.find((w) => w.name === "studio_summary");
    assert.match(summary.value, /brief\.txt/);
});

test("an empty listing renders the empty-state message", async () => {
    reset();
    setResponder(() => ({ ok: true, body: { rel: "studios/ggs", parent: null, entries: [] } }));
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    assert.ok(find(overlay, (n) => n.textContent === "No files in this studio library yet"));
});

test("a thrown fetch renders the inline error", async () => {
    reset();
    setResponder(() => ({ ok: false, status: 500, body: { error: "studio-assets unreachable" } }));
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    assert.ok(find(overlay, (n) => n.textContent === "studio-assets unreachable"));
});

test("the Done button removes the overlay", async () => {
    reset();
    setResponder(() => ({ ok: true, body: { rel: "studios/ggs", parent: null, entries: [] } }));
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    assert.ok(document.body.children.includes(overlay));
    const closeBtn = find(overlay, (n) => n.textContent === "Done");
    assert.ok(closeBtn, "expected a Done button in the overlay");
    fire(closeBtn, "click");
    assert.ok(!document.body.children.includes(overlay));
});

// Every row label in pane order, so a test can pin what is listed AND its order.
function rowLabels(root, out = []) {
    if (root?.className === "sym-name") out.push(root.textContent);
    for (const child of root?.children ?? []) rowLabels(child, out);
    return out;
}

function countText(root, text) {
    let n = root?.textContent === text ? 1 : 0;
    for (const child of root?.children ?? []) n += countText(child, text);
    return n;
}

// A tree with one folder, so a test can drill in and back out.
function twoLevelResponder() {
    setResponder((route) => route.includes("refs")
        ? { ok: true, body: { rel: "studios/ggs/refs", parent: "studios/ggs",
            entries: [{ name: "a.png", type: "file", rel: "studios/ggs/refs/a.png" }] } }
        : { ok: true, body: { rel: "studios/ggs", parent: null,
            entries: [{ name: "refs", type: "dir", rel: "studios/ggs/refs" }] } });
}

test("the first listing of every browse session requests a volume sync", async () => {
    // The mount this lists is only as fresh as its last sync, so a browse that
    // skipped the sync would show the studio as of the sandbox's boot and look
    // like a missing folder. Nothing else in the suite pins the flag: the route
    // tests build the query themselves, so a client that stopped sending it
    // leaves every one of them green.
    reset();
    twoLevelResponder();
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();

    const overlay = await openOverlay(node);
    const folder = find(overlay, (n) => n.textContent === "📁  refs");
    fire(folder, "click");
    await tick();
    fire(find(overlay, (n) => n.textContent === "Done"), "click");
    await openOverlay(node);

    assert.match(calls[0], /\bsync=1\b/, "opening the browser must sync first");
    assert.ok(!/\bsync=1\b/.test(calls[1]), "drilling in re-uses the sync we just did");
    assert.match(calls[2], /\bsync=1\b/, "re-opening the browser must sync again");
});

// A sub-listing holding both a folder and a file, so a test can tell a real
// folder row apart from the synthesised '..'.
function subfolderResponder(body = {}) {
    setResponder((route) => route.includes("refs")
        ? { ok: true, body: { rel: "studios/ggs/refs", parent: "studios/ggs",
            entries: [{ name: "nested", type: "dir", rel: "studios/ggs/refs/nested" },
                      { name: "a.png", type: "file", rel: "studios/ggs/refs/a.png" }],
            ...body } }
        : { ok: true, body: { rel: "studios/ggs", parent: null,
            entries: [{ name: "refs", type: "dir", rel: "studios/ggs/refs" }] } });
}

async function drillIntoRefs() {
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    fire(find(overlay, (n) => n.textContent === "📁  refs"), "click");
    await tick();
    return { node, overlay };
}

test("a subfolder listing puts '..' above every folder", async () => {
    reset();
    subfolderResponder();
    const { overlay } = await drillIntoRefs();
    assert.deepEqual(rowLabels(overlay), ["↑  ..", "📁  nested", "📄  a.png"]);
});

test("'..' carries no select control", async () => {
    // Every dir row gets a 'select' button that writes its rel into the node's
    // serialised widget. On '..' that silently sets the node to the parent
    // folder and closes — a navigation affordance that changes the value.
    reset();
    subfolderResponder();
    const { node, overlay } = await drillIntoRefs();
    assert.equal(countText(overlay, "select"), 1, "only the real folder is selectable");
    fire(find(overlay, (n) => n.textContent === "↑  .."), "click");
    await tick();
    assert.equal(node.widgets.find((w) => w.name === "selection").value, "",
        "navigating up must not touch the selection");
});

test("'..' does not mask the empty state", async () => {
    reset();
    setResponder((route) => route.includes("refs")
        ? { ok: true, body: { rel: "studios/ggs/refs", parent: "studios/ggs", entries: [] } }
        : { ok: true, body: { rel: "studios/ggs", parent: null,
            entries: [{ name: "refs", type: "dir", rel: "studios/ggs/refs" }] } });
    const { overlay } = await drillIntoRefs();
    assert.ok(find(overlay, (n) => n.textContent === "No files in this studio library yet"),
        "an empty subfolder still says it is empty");
    assert.ok(find(overlay, (n) => n.textContent === "↑  .."),
        "and can still be left");
});

test("'..' survives a filter that matches nothing", async () => {
    // The filter narrows the folder's own entries. Dropping the way out along
    // with them strands the user exactly when they are deepest in the tree.
    reset();
    subfolderResponder();
    const { overlay } = await drillIntoRefs();
    const filter = find(overlay, (n) => n.type === "search");
    filter.value = "zzz";
    fire(filter, "input");
    assert.ok(find(overlay, (n) => n.textContent === "↑  .."));
    assert.ok(find(overlay, (n) => n.textContent === "No matches"));
});

function hiddenModelsResponder() {
    setResponder((route) => route.includes("models=1")
        ? { ok: true, body: { rel: "studios/ggs", parent: null,
            entries: [{ name: "loras", type: "dir", rel: "studios/ggs/loras" },
                      { name: "refs", type: "dir", rel: "studios/ggs/refs" }] } }
        : { ok: true, body: { rel: "studios/ggs", parent: null, hidden: 2,
            entries: [{ name: "refs", type: "dir", rel: "studios/ggs/refs" }] } });
}

test("the root says how many model folders it is not showing", async () => {
    // The studio's own web view lists these. Without a line saying they exist,
    // the two views disagree and the browse node looks like it lost a folder.
    reset();
    hiddenModelsResponder();
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    assert.ok(find(overlay, (n) => /2 model folders/.test(n.textContent ?? "")),
        "expected the root to account for the folders it hid");
});

test("showing model folders re-lists them", async () => {
    reset();
    hiddenModelsResponder();
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    fire(find(overlay, (n) => n.textContent === "show"), "click");
    await tick();
    assert.match(calls.at(-1), /\bmodels=1\b/);
    assert.deepEqual(rowLabels(overlay), ["📁  loras", "📁  refs"]);
    assert.ok(find(overlay, (n) => n.textContent === "hide"), "and can be put back");
});

test("the model-folder note stays at the root once they are shown", async () => {
    // The omission is a studio-root rule, so the note has nothing to say about
    // a subfolder — but the toggle it carries is sticky across navigation, so
    // the note follows the user down unless the level is what gates it.
    reset();
    setResponder((route) => {
        if (route.includes("refs")) {
            return { ok: true, body: { rel: "studios/ggs/refs", parent: "studios/ggs",
                entries: [{ name: "a.png", type: "file", rel: "studios/ggs/refs/a.png" }] } };
        }
        const entries = [{ name: "refs", type: "dir", rel: "studios/ggs/refs" }];
        return route.includes("models=1")
            ? { ok: true, body: { rel: "studios/ggs", parent: null,
                entries: [{ name: "loras", type: "dir", rel: "studios/ggs/loras" }, ...entries] } }
            : { ok: true, body: { rel: "studios/ggs", parent: null, hidden: 2, entries } };
    });
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    fire(find(overlay, (n) => n.textContent === "show"), "click");
    await tick();
    assert.ok(find(overlay, (n) => n.textContent === "hide"), "the root is showing them");

    fire(find(overlay, (n) => n.textContent === "📁  refs"), "click");
    await tick();
    assert.ok(!find(overlay, (n) => /model folder/i.test(n.textContent ?? "")),
        "a subfolder hides nothing, so it has nothing to account for");
});

test("the studio root has no '..' row", async () => {
    reset();
    subfolderResponder();
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    assert.deepEqual(rowLabels(overlay), ["📁  refs"]);
});

test("the refresh control re-reads the current folder with a forced sync", async () => {
    // A refresh that re-listed without syncing would redraw the same rows off
    // the same stale mount and look like proof the folder is not there.
    reset();
    twoLevelResponder();
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    fire(find(overlay, (n) => n.textContent === "📁  refs"), "click");
    await tick();

    const refresh = find(overlay, (n) => n.title === "Re-read this folder");
    assert.ok(refresh, "expected a refresh control in the overlay");
    fire(refresh, "click");
    await tick();

    assert.match(calls.at(-1), /\bsync=1\b/, "a refresh must force the volume sync");
    assert.match(calls.at(-1), /dir=studios%2Fggs%2Frefs/,
        "a refresh must re-read where the user is, not the studio root");
});

test("the up control keeps its theming once it becomes visible", async () => {
    // It starts hidden, so showing it is the first write to its style. Writing
    // cssText there replaces the hub tokens set at build time and the button
    // renders unstyled for the whole rest of the session.
    reset();
    twoLevelResponder();
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    const up = find(overlay, (n) => n.textContent === "↑ up");
    fire(find(overlay, (n) => n.textContent === "📁  refs"), "click");
    await tick();
    assert.equal(up.style.display, "", "the up control shows below the root");
    assert.match(up.style.cssText, /cursor:pointer/, "hub button tokens survive");
});

test("a refresh keeps the filter the user typed", async () => {
    reset();
    twoLevelResponder();
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    const filter = find(overlay, (n) => n.type === "search");
    filter.value = "re";
    fire(filter, "input");
    fire(find(overlay, (n) => n.title === "Re-read this folder"), "click");
    await tick();
    assert.equal(filter.value, "re", "re-reading in place is not navigation");
});

test("a degraded sync warns in the panel without hiding the listing", async () => {
    // The rows are still the best answer available — the mount is simply older
    // than the user thinks. Replacing them with an error would cost a browse
    // over a listing that is probably right.
    reset();
    setResponder(() => ({ ok: true, body: { rel: "studios/ggs", parent: null, sync: "timeout",
        entries: [{ name: "refs", type: "dir", rel: "studios/ggs/refs" }] } }));
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    assert.ok(find(overlay, (n) => /out of date/.test(n.textContent ?? "")),
        "expected an inline warning that the listing may be stale");
    assert.ok(find(overlay, (n) => n.textContent === "📁  refs"),
        "the warning must not replace the rows");
});

test("clicking a folder row opens it (the default action)", async () => {
    reset();
    setResponder((route) => route.includes("Export")
        ? { ok: true, body: { rel: "studios/ggs/Export JPG NoResize", parent: "studios/ggs",
            entries: [{ name: "a.jpg", type: "file", rel: "studios/ggs/Export JPG NoResize/a.jpg" }] } }
        : { ok: true, body: { rel: "studios/ggs", parent: null,
            entries: [{ name: "Export JPG NoResize", type: "dir", rel: "studios/ggs/Export JPG NoResize" }] } });
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    const folderLabel = find(overlay, (n) => typeof n.textContent === "string"
        && n.textContent.includes("Export JPG NoResize"));
    assert.ok(folderLabel, "expected the folder row label");
    fire(folderLabel, "click");
    await tick();
    assert.ok(find(overlay, (n) => n.textContent && n.textContent.includes("a.jpg")),
        "clicking the folder row should navigate into it");
});
