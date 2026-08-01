// ABOUTME: Tests for studio_library.js — the pure selection seam and the
// ABOUTME: node's summary widget behavior under the comfy stub.
import { test } from "node:test";
import assert from "node:assert/strict";

import { calls, create, reset, setResponder, setLatency, fire } from "./comfy_stub.mjs";
import { HUB } from "../../web/js/hub_theme.js";
import "../../web/js/studio_library.js";
import { summaryLabel, applySelection, filterEntries } from "../../web/js/studio_library.js";

const tick = () => new Promise((r) => setTimeout(r, 0));
const settle = (ms) => new Promise((r) => setTimeout(r, ms));

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

test("the model-folder toggle keeps the filter, because it re-reads in place", async () => {
    // The typed query is usually the REASON for the click: the user searched for
    // a lora, got 'No matches', and pressed show to look among the hidden ones.
    reset();
    hiddenModelsResponder();
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    const filter = find(overlay, (n) => n.type === "search");
    filter.value = "lora";
    fire(filter, "input");
    fire(find(overlay, (n) => n.textContent === "show"), "click");
    await tick();
    assert.equal(filter.value, "lora", "the folder did not change, so neither did the query");
    assert.deepEqual(rowLabels(overlay), ["📁  loras"], "and it still narrows the rows");
});

test("a toggle whose listing failed still offers what it has not done", async () => {
    // Flipping the state before the request means a failure leaves the two
    // disagreeing: the label offers 'show' while the state already says shown,
    // so the next click asks for the opposite of what it promises.
    reset();
    const state = { broken: false };
    setResponder((route) => {
        if (route.includes("models=1") && state.broken) {
            return { ok: false, status: 500, body: { error: "studio-assets unreachable" } };
        }
        return route.includes("models=1")
            ? { ok: true, body: { rel: "studios/ggs", parent: null,
                entries: [{ name: "loras", type: "dir", rel: "studios/ggs/loras" }] } }
            : { ok: true, body: { rel: "studios/ggs", parent: null, hidden: 2,
                entries: [{ name: "refs", type: "dir", rel: "studios/ggs/refs" }] } };
    });
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);

    state.broken = true;
    fire(find(overlay, (n) => n.textContent === "show"), "click");
    await tick();
    assert.ok(find(overlay, (n) => n.textContent === "show"),
        "nothing was shown, so the offer stands");

    state.broken = false;
    fire(find(overlay, (n) => n.textContent === "show"), "click");
    await tick();
    assert.match(calls.at(-1), /\bmodels=1\b/, "the retry asks for what the label promised");
    assert.ok(find(overlay, (n) => n.textContent === "hide"));
});

test("a toggle the user navigated away from does not take effect later", async () => {
    // Same shape as a late listing overwriting the pane, but the casualty is
    // state rather than rows: the reply is discarded, so if it had already been
    // adopted the browser would go on asking for model folders on behalf of a
    // press whose result nobody ever saw.
    reset();
    setResponder((route) => {
        if (route.includes("refs")) {
            return { ok: true, body: { rel: "studios/ggs/refs", parent: "studios/ggs",
                entries: [{ name: "a.png", type: "file", rel: "studios/ggs/refs/a.png" }] } };
        }
        const refs = { name: "refs", type: "dir", rel: "studios/ggs/refs" };
        return route.includes("models=1")
            ? { ok: true, body: { rel: "studios/ggs", parent: null,
                entries: [{ name: "loras", type: "dir", rel: "studios/ggs/loras" }, refs] } }
            : { ok: true, body: { rel: "studios/ggs", parent: null, hidden: 2,
                entries: [refs] } };
    });
    setLatency((route) => (route.includes("models=1") ? 40 : 0));
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    node.widgets.find((w) => w.name === "📂 Browse studio library").callback();
    await settle(20);
    const overlay = document.body.children.at(-1);

    fire(find(overlay, (n) => n.textContent === "show"), "click");
    fire(find(overlay, (n) => n.textContent === "📁  refs"), "click");
    await settle(120);
    setLatency(0);

    fire(find(overlay, (n) => n.textContent === "↑  .."), "click");
    await tick();
    assert.ok(!/\bmodels=1\b/.test(calls.at(-1)),
        "the press whose listing was discarded left nothing behind");
    assert.ok(find(overlay, (n) => n.textContent === "show"), "and the offer stands");
});

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

test("clicking '..' opens the parent", async () => {
    // The row's whole purpose. Asserting only that it does not touch the
    // selection is satisfied by a dead label, which is the shape the naive
    // version of this row would ship as.
    reset();
    subfolderResponder();
    const { overlay } = await drillIntoRefs();
    fire(find(overlay, (n) => n.textContent === "↑  .."), "click");
    await tick();
    assert.deepEqual(rowLabels(overlay), ["📁  refs"], "back at the studio root");
});

test("hiding the model folders puts them back", async () => {
    reset();
    hiddenModelsResponder();
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    fire(find(overlay, (n) => n.textContent === "show"), "click");
    await tick();
    fire(find(overlay, (n) => n.textContent === "hide"), "click");
    await tick();
    assert.ok(!/\bmodels=1\b/.test(calls.at(-1)), "the listing stops asking for them");
    assert.deepEqual(rowLabels(overlay), ["📁  refs"]);
});

test("navigating to another folder drops the filter", async () => {
    // The other half of the in-place rule. A query carried into a folder it was
    // never typed for renders 'No matches' over a folder that has contents —
    // the same 'the folder is empty' lie this browser exists to avoid.
    reset();
    subfolderResponder();
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    const filter = find(overlay, (n) => n.type === "search");
    filter.value = "refs";
    fire(filter, "input");
    fire(find(overlay, (n) => n.textContent === "📁  refs"), "click");
    await tick();
    assert.equal(filter.value, "", "a different folder, so a query that was never about it");
    assert.deepEqual(rowLabels(overlay), ["↑  ..", "📁  nested", "📄  a.png"]);
});

test("a root hiding exactly one model folder says so in the singular", async () => {
    reset();
    setResponder(() => ({ ok: true, body: { rel: "studios/ggs", parent: null, hidden: 1,
        entries: [{ name: "refs", type: "dir", rel: "studios/ggs/refs" }] } }));
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    assert.ok(find(overlay, (n) => /\b1 model folder hidden\b/.test(n.textContent ?? "")),
        "expected 'folder', not 'folders'");
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

test("a slow refresh reply does not overwrite where the user has since gone", async () => {
    // The forced sync is the slow case by construction: the server waits on the
    // volume walk, and a degraded mount takes the whole budget. The pane stays
    // usable meanwhile, so the user navigates — and the refresh reply, when it
    // finally lands, is a listing of a folder they have already left.
    reset();
    subfolderResponder();
    setLatency((route) => (route.includes("sync=1") ? 40 : 0));
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const browse = node.widgets.find((w) => w.name === "📂 Browse studio library");
    browse.callback();
    await settle(80);
    const overlay = document.body.children.at(-1);

    fire(find(overlay, (n) => n.title === "Re-read this folder"), "click");
    fire(find(overlay, (n) => n.textContent === "📁  refs"), "click");
    await settle(120);

    setLatency(0);
    assert.deepEqual(rowLabels(overlay), ["↑  ..", "📁  nested", "📄  a.png"],
        "the folder the user opened must win over the reply they stopped waiting for");
});

test("the refresh control is held while its volume walk runs", async () => {
    // The walk can take the server's whole budget. A control that looks inert
    // for that long gets pressed again, and each press is another walk on the
    // container the editor is running in.
    reset();
    subfolderResponder();
    setLatency((route) => (route.includes("sync=1") ? 40 : 0));
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    node.widgets.find((w) => w.name === "📂 Browse studio library").callback();
    await settle(80);
    const overlay = document.body.children.at(-1);
    const refresh = find(overlay, (n) => n.title === "Re-read this folder");

    fire(refresh, "click");
    await tick();
    assert.equal(refresh.disabled, true, "held while the walk runs");
    assert.ok(find(overlay, (n) => /refreshing/i.test(n.textContent ?? "")),
        "and says why it is unavailable");
    const before = calls.length;
    fire(refresh, "click");
    assert.equal(calls.length, before, "a press while held starts no second walk");

    await settle(80);
    setLatency(0);
    assert.equal(refresh.disabled, false, "released once the reply lands");
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

test("the stale warning survives navigation until a refresh actually works", async () => {
    // Drilling in does not sync, so the subfolder comes off the same mount that
    // failed to refresh and is exactly as old. Dropping the warning there is
    // worse than never showing it: the user is now a level deeper, looking for
    // something recent, and has been told everything is fine.
    reset();
    const state = { degraded: true };
    walkResponder(state);
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    const warned = () => !!find(overlay, (n) => /out of date/.test(n.textContent ?? ""));
    assert.ok(warned(), "the open could not refresh");

    fire(find(overlay, (n) => n.textContent === "📁  refs"), "click");
    await tick();
    assert.ok(warned(), "and the folder inside it is off the same unrefreshed mount");

    state.degraded = false;
    fire(find(overlay, (n) => n.title === "Re-read this folder"), "click");
    await tick();
    assert.ok(!warned(), "only a refresh that worked earns a clean listing");
});

// A tree plus a switchable mount state, for the cases where a walk's verdict
// arrives after the user has moved on.
function walkResponder(state) {
    setResponder((route) => {
        // The route reports what the walk did on every path, success included:
        // see test_a_clean_sync_says_so in tests/test_routes_studio_library.py.
        const verdict = route.includes("sync=1")
            ? { sync: state.degraded ? "timeout" : "refreshed" } : {};
        return route.includes("refs")
            ? { ok: true, body: { rel: "studios/ggs/refs", parent: "studios/ggs", ...verdict,
                entries: [{ name: "a.png", type: "file", rel: "studios/ggs/refs/a.png" }] } }
            : { ok: true, body: { rel: "studios/ggs", parent: null, ...verdict,
                entries: [{ name: "refs", type: "dir", rel: "studios/ggs/refs" }] } };
    });
}

test("a refresh that failed is reported even if the user moved on meanwhile", async () => {
    // The verdict is about the MOUNT, so it outlives the pane it arrived for.
    // Dropping it with the rows is the worst of both: the user asked whether the
    // studio was up to date, it was not, and nothing said so.
    reset();
    const state = { degraded: false };
    walkResponder(state);
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    const warned = () => !!find(overlay, (n) => /out of date/.test(n.textContent ?? ""));
    assert.ok(!warned(), "the open refreshed cleanly");

    state.degraded = true;
    setLatency((route) => (route.includes("sync=1") ? 40 : 0));
    fire(find(overlay, (n) => n.title === "Re-read this folder"), "click");
    fire(find(overlay, (n) => n.textContent === "📁  refs"), "click");
    await settle(120);
    setLatency(0);
    assert.ok(warned(), "the walk failed, whichever folder the user ended up in");
});

test("a refresh that worked clears the warning even if the user moved on meanwhile", async () => {
    reset();
    const state = { degraded: true };
    walkResponder(state);
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    const warned = () => !!find(overlay, (n) => /out of date/.test(n.textContent ?? ""));
    assert.ok(warned(), "the open could not refresh");

    state.degraded = false;
    setLatency((route) => (route.includes("sync=1") ? 40 : 0));
    fire(find(overlay, (n) => n.title === "Re-read this folder"), "click");
    fire(find(overlay, (n) => n.textContent === "📁  refs"), "click");
    await settle(120);
    setLatency(0);
    assert.ok(!warned(), "the mount is fresh, so nothing is out of date");
});

test("the refresh control keeps its explanation while the user browses around it", async () => {
    // The control stays held for the whole walk, so the line explaining why must
    // last as long. A greyed control with nothing next to it reads as broken.
    reset();
    walkResponder({ degraded: false });
    setLatency((route) => (route.includes("sync=1") ? 60 : 0));
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    node.widgets.find((w) => w.name === "📂 Browse studio library").callback();
    await settle(100);
    const overlay = document.body.children.at(-1);
    const refresh = find(overlay, (n) => n.title === "Re-read this folder");

    fire(refresh, "click");
    await tick();
    fire(find(overlay, (n) => n.textContent === "📁  refs"), "click");
    await tick();
    assert.equal(refresh.disabled, true, "still held");
    assert.ok(find(overlay, (n) => /refreshing/i.test(n.textContent ?? "")),
        "and still saying why");
    await settle(100);
    setLatency(0);
});

test("a failure shows through even while a walk is still running", async () => {
    // The two can overlap: the walk holds the control, the user opens something
    // in the meantime, and that fails. A progress note sitting on top of the
    // failure is the message line telling the user everything is fine.
    reset();
    setResponder((route) => (route.includes("refs")
        ? { ok: false, status: 500, body: { error: "studio-assets unreachable" } }
        : { ok: true, body: { rel: "studios/ggs", parent: null,
            entries: [{ name: "refs", type: "dir", rel: "studios/ggs/refs" }] } }));
    setLatency((route) => (route.includes("sync=1") ? 60 : 0));
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    node.widgets.find((w) => w.name === "📂 Browse studio library").callback();
    await settle(100);
    const overlay = document.body.children.at(-1);

    fire(find(overlay, (n) => n.title === "Re-read this folder"), "click");
    await tick();
    fire(find(overlay, (n) => n.textContent === "📁  refs"), "click");
    await tick();
    assert.ok(find(overlay, (n) => n.textContent === "studio-assets unreachable"),
        "the failure is what the user has to act on");
    await settle(100);
    setLatency(0);
});

test("a walk that worked clears the warning even when its listing was refused", async () => {
    // The two outcomes are independent, and this pairing is the ordinary one:
    // the folder is gone BECAUSE the view of it was stale. Learning only from
    // listings that succeeded means the warning outlives the staleness.
    reset();
    walkResponder({ degraded: true });
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    const warned = () => !!find(overlay, (n) => /out of date/.test(n.textContent ?? ""));
    assert.ok(warned(), "the open could not refresh");

    // The refresh runs a clean walk and then finds the folder is not there.
    setResponder(() => ({ ok: false, status: 400,
        body: { error: "not a directory", sync: "refreshed" } }));
    fire(find(overlay, (n) => n.title === "Re-read this folder"), "click");
    await tick();
    assert.ok(find(overlay, (n) => n.textContent === "not a directory"),
        "the folder is what failed");

    // Read the mount's state only once the refusal has stopped covering it: an
    // ordinary navigation runs no walk, so it says nothing about the volume and
    // whatever shows now is what the refresh taught us.
    setResponder(() => ({ ok: true, body: { rel: "studios/ggs/refs", parent: "studios/ggs",
        entries: [{ name: "a.png", type: "file", rel: "studios/ggs/refs/a.png" }] } }));
    fire(find(overlay, (n) => n.textContent === "📁  refs"), "click");
    await tick();
    assert.ok(!warned(), "the volume is current, so nothing is out of date");
});

test("a failure clears once something works", async () => {
    // The message line is derived from state now, and nothing but the next
    // request resets the error. Leaving it set makes one transient failure
    // permanent, over every listing that follows it.
    reset();
    const state = { broken: true };
    setResponder(() => (state.broken
        ? { ok: false, status: 500, body: { error: "studio-assets unreachable" } }
        : { ok: true, body: { rel: "studios/ggs", parent: null, sync: "refreshed",
            entries: [{ name: "refs", type: "dir", rel: "studios/ggs/refs" }] } }));
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    assert.ok(find(overlay, (n) => n.textContent === "studio-assets unreachable"));

    state.broken = false;
    fire(find(overlay, (n) => n.title === "Re-read this folder"), "click");
    await tick();
    assert.ok(!find(overlay, (n) => n.textContent === "studio-assets unreachable"),
        "the listing on screen is not the one that failed");
    assert.deepEqual(rowLabels(overlay), ["📁  refs"]);
});

test("a failure the user moved on from does not paint over what they opened", async () => {
    // The same rule the rows follow. A refusal for a folder nobody is looking at
    // is an answer to a question nobody is still asking.
    reset();
    setResponder((route) => (route.includes("sync=1") && route.includes("dir=studios%2Fggs&")
        ? { ok: false, status: 500, body: { error: "studio-assets unreachable" } }
        : route.includes("refs")
            ? { ok: true, body: { rel: "studios/ggs/refs", parent: "studios/ggs",
                entries: [{ name: "a.png", type: "file", rel: "studios/ggs/refs/a.png" }] } }
            : { ok: true, body: { rel: "studios/ggs", parent: null, sync: "refreshed",
                entries: [{ name: "refs", type: "dir", rel: "studios/ggs/refs" }] } }));
    setLatency((route) => (route.includes("sync=1") ? 40 : 0));
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    node.widgets.find((w) => w.name === "📂 Browse studio library").callback();
    await settle(80);
    const overlay = document.body.children.at(-1);

    fire(find(overlay, (n) => n.title === "Re-read this folder"), "click");
    fire(find(overlay, (n) => n.textContent === "📁  refs"), "click");
    await settle(120);
    setLatency(0);
    assert.deepEqual(rowLabels(overlay), ["↑  ..", "📄  a.png"], "the folder they opened");
    assert.ok(!find(overlay, (n) => n.textContent === "studio-assets unreachable"),
        "and no refusal from the request they stopped waiting for");
});

test("a walk in progress outranks the warning it is trying to clear", async () => {
    // The states overlap by construction: pressing refresh is what a stale
    // warning is for. Repeating the accusation while acting on it leaves the
    // held control unexplained, which is what the holding message is for.
    reset();
    const state = { degraded: true };
    walkResponder(state);
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    assert.ok(find(overlay, (n) => /out of date/.test(n.textContent ?? "")));

    setLatency((route) => (route.includes("sync=1") ? 60 : 0));
    fire(find(overlay, (n) => n.title === "Re-read this folder"), "click");
    await tick();
    assert.ok(find(overlay, (n) => /refreshing/i.test(n.textContent ?? "")),
        "we are doing something about it");
    assert.ok(!find(overlay, (n) => /out of date/.test(n.textContent ?? "")));
    await settle(100);
    setLatency(0);
});

test("a failure is shown in the danger tone, a note is not", async () => {
    reset();
    const state = { broken: true };
    setResponder(() => (state.broken
        ? { ok: false, status: 500, body: { error: "studio-assets unreachable" } }
        : { ok: true, body: { rel: "studios/ggs", parent: null, sync: "timeout",
            entries: [{ name: "refs", type: "dir", rel: "studios/ggs/refs" }] } }));
    const node = await create("SymbioticaStudioLibrary", { selection: "" });
    node.onNodeCreated?.();
    const overlay = await openOverlay(node);
    const line = find(overlay, (n) => n.textContent === "studio-assets unreachable");
    assert.equal(line.style.color, HUB.danger, "a failure the user must act on");

    state.broken = false;
    fire(find(overlay, (n) => n.title === "Re-read this folder"), "click");
    await tick();
    assert.ok(/out of date/.test(line.textContent));
    assert.equal(line.style.color, HUB.inkSubtle, "a note about how much to trust the rows");
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
