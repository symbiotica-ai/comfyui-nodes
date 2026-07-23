// ABOUTME: Tests for studio_library.js — the pure selection seam and the
// ABOUTME: node's summary widget behavior under the comfy stub.
import { test } from "node:test";
import assert from "node:assert/strict";

import { create, reset, setResponder, fire } from "./comfy_stub.mjs";
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
        && n.textContent.includes("📁 Export JPG NoResize"));
    assert.ok(folderLabel, "expected the folder row label");
    fire(folderLabel, "click");
    await tick();
    assert.ok(find(overlay, (n) => n.textContent && n.textContent.includes("a.jpg")),
        "clicking the folder row should navigate into it");
});
