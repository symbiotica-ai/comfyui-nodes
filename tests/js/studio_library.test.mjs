// ABOUTME: Tests for studio_library.js — the pure selection seam and the
// ABOUTME: node's summary widget behavior under the comfy stub.
import { test } from "node:test";
import assert from "node:assert/strict";

import { create } from "./comfy_stub.mjs";
import "../../web/js/studio_library.js";
import { summaryLabel, applySelection, filterEntries } from "../../web/js/studio_library.js";

const tick = () => new Promise((r) => setTimeout(r, 0));

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
