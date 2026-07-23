// ABOUTME: Drives the real order_pipeline.js under ComfyUI stubs and asserts a
// ABOUTME: failing parse-order settles instead of looping into a request flood.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
    calls, setResponder, setLatency, reset, create, link, repaint, tick, repaints,
} from "./comfy_stub.mjs";
import "../../web/js/order_pipeline.js";

// A stale local path: it exists on the artist's mac, never inside the hosted
// sandbox, so resolve_month() yields no order_path and the route 400s forever.
//
// The parse cache lives in the module and outlives any one test, so each test
// takes its own path. Sharing one would let a cached answer leak forward and
// quietly turn a later test into an assertion about nothing.
let projectCounter = 0;
const ABSENT_PROJECT = () =>
    `/Users/someone/Google Drive/Clients/Imperia/bakery-${++projectCounter}`;

const ONE_EVENT = {
    feature: "Mini 1",
    eventName: "Ghostly Goodies",
    assets: [{ assetName: "Oven", category: "Appliance", canvas: "512x512",
               prompt: "a midnight oven", refFiles: ["Oven.png"] }],
};

const parseOrderCalls = () =>
    calls.filter((c) => c.startsWith("/symbiotica/parse-order")).length;

// Build the reported graph: one Order Specs feeding `packerCount` Auto Packers,
// then let the canvas repaint while the event loop drains.
async function runGraph({ responder, packerCount = 1, frames = 40 }) {
    reset();
    setLatency(1);
    setResponder(responder);

    const specs = await create("SymbioticaOrderSpecs",
        { project_path: ABSENT_PROJECT(), month: "October", feature: "Mini 1" });
    const packers = [];
    for (let i = 0; i < packerCount; i++) {
        const p = await create("SymbioticaAutoPacker",
            { category: "All", overrides: "{}" });
        link(specs, p, "order");
        packers.push(p);
    }

    specs.onNodeCreated();
    for (const p of packers) p.onNodeCreated();

    for (let f = 0; f < frames; f++) {
        repaint(specs, ...packers);
        await tick();
    }
    return parseOrderCalls();
}

const always = (reply) => () => reply;

test("a permanently failing order parse settles instead of flooding", async () => {
    const n = await runGraph({
        responder: always({ ok: false, status: 400,
                            body: { error: "order_path required" } }),
    });
    // One attempt for the key. A handful of extra requests would mean the
    // guard leaks; hundreds means the loop is back.
    assert.ok(n <= 3, `expected the parse to settle, got ${n} parse-order requests`);
});

test("a successful parse with zero events does not loop either", async () => {
    // An order that parses fine but names no assets leaves the event list
    // empty — the same empty-state that arms the loop, with no error involved.
    const n = await runGraph({
        responder: always({ ok: true, status: 200,
                            body: { events: [], refsRoot: "" } }),
    });
    assert.ok(n <= 3, `expected zero-event parse to settle, got ${n} requests`);
});

test("two Auto Packers do not multiply the request count", async () => {
    // Each resolved parse re-renders every downstream packer, and each render
    // could start another parse: the growth is N^k, not N*k.
    const n = await runGraph({
        responder: always({ ok: false, status: 400,
                            body: { error: "order_path required" } }),
        packerCount: 2,
    });
    assert.ok(n <= 3, `expected fan-out to stay bounded, got ${n} requests`);
});

test("a healthy order is parsed once and reused", async () => {
    const n = await runGraph({
        responder: always({ ok: true, status: 200,
                            body: { events: [ONE_EVENT], refsRoot: "/refs" } }),
    });
    assert.ok(n <= 3, `expected one parse for a healthy order, got ${n} requests`);
});

// The Auto Packer's assets panel is a DOM widget; its children are the asset
// rows, so they say whether a parse actually reached the UI.
const panelOf = (packer) =>
    packer.widgets.find((w) => w.name === "assets_panel").element;

test("a parsed order reaches the downstream assets panel", async () => {
    // The guard suppresses repeat answers. It must still deliver new ones —
    // otherwise the panel sits on its placeholder after a perfectly good parse
    // and nothing in a request count would notice.
    reset();
    setLatency(1);
    setResponder(always({ ok: true, status: 200,
                          body: { events: [ONE_EVENT], refsRoot: "/refs" } }));

    const specs = await create("SymbioticaOrderSpecs",
        { project_path: ABSENT_PROJECT(), month: "October", feature: "Mini 1" });
    const packer = await create("SymbioticaAutoPacker",
        { category: "All", overrides: "{}" });
    link(specs, packer, "order");
    specs.onNodeCreated();
    packer.onNodeCreated();
    for (let f = 0; f < 20; f++) await tick();

    const panel = panelOf(packer);
    assert.equal(panel.children.length, 1,
                 "the assets panel never rendered the parsed asset");
    assert.notEqual(panel.textContent, "Wire an Order Specs and pick an event.",
                    "the panel is still showing its placeholder");
});

test("picking a different feature re-renders the packer", async () => {
    // `feature` is part of the change comparison for this reason: the order
    // behind it is identical, so an identity check on the parse alone would
    // treat a new pick as nothing to do.
    reset();
    setLatency(1);
    const second = {
        feature: "Mini 2", eventName: "Frosted",
        assets: [{ assetName: "Cake", category: "Dessert", canvas: "512x512",
                   prompt: "a cake", refFiles: ["Cake.png"] }],
    };
    setResponder(always({ ok: true, status: 200,
                          body: { events: [ONE_EVENT, second], refsRoot: "/refs" } }));

    const specs = await create("SymbioticaOrderSpecs",
        { project_path: ABSENT_PROJECT(), month: "October", feature: "Mini 1" });
    const packer = await create("SymbioticaAutoPacker",
        { category: "All", overrides: "{}" });
    link(specs, packer, "order");
    specs.onNodeCreated();
    packer.onNodeCreated();
    for (let f = 0; f < 20; f++) await tick();

    const featureWidget = specs.widgets.find((w) => w.name === "feature");
    featureWidget.value = "Mini 2 — Frosted";
    featureWidget.callback.call(featureWidget, "Mini 2 — Frosted");
    for (let f = 0; f < 20; f++) await tick();

    assert.equal(specs._symEvents.length, 2);
    assert.equal(panelOf(packer).children.length, 1,
                 "the packer did not re-render for the new feature");
});

test("a 400 is still not retried once a backoff would have elapsed", async () => {
    // Real time, deliberately: this is the one place the whole chain is
    // exercised end to end — fetchJson labelling the error with its status, the
    // cache reading that status, and a 400 being kept rather than deferred. A
    // failure that loses its status is retried on the backoff instead, which
    // reads as fixed for the first second and floods slowly forever after.
    reset();
    setLatency(1);
    setResponder(always({ ok: false, status: 400,
                          body: { error: "order_path required" } }));

    const specs = await create("SymbioticaOrderSpecs",
        { project_path: ABSENT_PROJECT(), month: "October", feature: "Mini 1" });
    const packer = await create("SymbioticaAutoPacker",
        { category: "All", overrides: "{}" });
    link(specs, packer, "order");
    specs.onNodeCreated();
    packer.onNodeCreated();

    // Past the 1000ms first backoff window, repainting throughout.
    const until = Date.now() + 1_400;
    while (Date.now() < until) {
        repaint(specs, packer);
        await new Promise((r) => setTimeout(r, 10));
    }

    assert.equal(parseOrderCalls(), 1,
                 "the 400 was retried, so it was not classified as final");
});

test("a settled order stops marking the canvas dirty", async () => {
    // Marking the canvas dirty schedules the repaint that paints the category
    // combo, which asks for the order again. If that keeps firing on an
    // unchanged answer the loop is still running — just without the requests,
    // so no request count would show it.
    reset();
    setLatency(1);
    setResponder(always({ ok: false, status: 400,
                          body: { error: "order_path required" } }));

    const specs = await create("SymbioticaOrderSpecs",
        { project_path: ABSENT_PROJECT(), month: "October", feature: "Mini 1" });
    const packer = await create("SymbioticaAutoPacker",
        { category: "All", overrides: "{}" });
    link(specs, packer, "order");
    specs.onNodeCreated();
    packer.onNodeCreated();
    for (let f = 0; f < 20; f++) { repaint(specs, packer); await tick(); }

    const settled = repaints.count;
    for (let f = 0; f < 60; f++) { repaint(specs, packer); await tick(); }

    assert.equal(repaints.count, settled,
                 `canvas kept being dirtied: ${repaints.count - settled} more `
                 + "over 60 idle frames");
});

test("two Order Specs sharing a project and month both get their events", async () => {
    // Sharing one request between them must not mean only one of them is
    // filled in — the other node's feature combo would stay empty forever.
    reset();
    setLatency(1);
    setResponder(always({ ok: true, status: 200,
                          body: { events: [ONE_EVENT], refsRoot: "/refs" } }));

    const shared = ABSENT_PROJECT(); // the whole point: one key, two nodes
    const a = await create("SymbioticaOrderSpecs",
        { project_path: shared, month: "October", feature: "Mini 1" });
    const b = await create("SymbioticaOrderSpecs",
        { project_path: shared, month: "October", feature: "Mini 1" });
    a.onNodeCreated();
    b.onNodeCreated();
    for (let f = 0; f < 10; f++) await tick();

    assert.equal(a._symEvents.length, 1, "first Order Specs has no events");
    assert.equal(b._symEvents.length, 1, "second Order Specs has no events");
});

test("editing a widget retries a project that previously failed", async () => {
    // Remembering the 400 is what stops the flood, but it must not outlive the
    // user's next deliberate action — otherwise a path that starts working
    // needs a page reload to be seen.
    reset();
    setLatency(1);
    let healthy = false;
    setResponder(() => healthy
        ? { ok: true, status: 200, body: { events: [ONE_EVENT], refsRoot: "/refs" } }
        : { ok: false, status: 400, body: { error: "order_path required" } });

    const specs = await create("SymbioticaOrderSpecs",
        { project_path: ABSENT_PROJECT(), month: "October", feature: "Mini 1" });
    specs.onNodeCreated();
    for (let f = 0; f < 10; f++) await tick();
    assert.equal(specs._symEvents.length, 0, "expected the first parse to fail");

    healthy = true;
    const monthWidget = specs.widgets.find((w) => w.name === "month");
    monthWidget.callback.call(monthWidget, "October");
    for (let f = 0; f < 10; f++) await tick();

    assert.equal(specs._symEvents.length, 1,
                 "a widget edit did not re-ask the server");
});

test("clearing the project path keeps the picked feature", async () => {
    // Clearing the field to paste a new path must not throw away the chosen
    // event — there is no order to reconcile against while it is blank, so
    // there is nothing to say the pick is invalid.
    reset();
    setLatency(1);
    setResponder(always({ ok: true, status: 200,
                          body: { events: [ONE_EVENT], refsRoot: "/refs" } }));

    const specs = await create("SymbioticaOrderSpecs",
        { project_path: ABSENT_PROJECT(), month: "October", feature: "Mini 1" });
    specs.onNodeCreated();
    for (let f = 0; f < 10; f++) await tick();

    const projectWidget = specs.widgets.find((w) => w.name === "project_path");
    projectWidget.value = "";
    projectWidget.callback.call(projectWidget, "");
    for (let f = 0; f < 10; f++) await tick();

    const feature = specs.widgets.find((w) => w.name === "feature").value;
    assert.notEqual(feature, "", "blanking the project wiped the feature");
});

test("repainting the category combo alone does not fetch", async () => {
    // The combo's values function runs on every repaint, and it asks for the
    // order when the event list is empty — a request source that never touches
    // the assets panel.
    reset();
    setLatency(1);
    setResponder(always({ ok: false, status: 400,
                          body: { error: "order_path required" } }));

    const specs = await create("SymbioticaOrderSpecs",
        { project_path: ABSENT_PROJECT(), month: "October", feature: "Mini 1" });
    const packer = await create("SymbioticaAutoPacker",
        { category: "All", overrides: "{}" });
    link(specs, packer, "order");
    specs.onNodeCreated();
    packer.onNodeCreated();
    for (let f = 0; f < 10; f++) await tick();

    const settled = parseOrderCalls();
    for (let f = 0; f < 60; f++) { repaint(packer); await tick(); }

    assert.equal(parseOrderCalls(), settled,
                 "60 repaints issued fresh parse-order requests");
});

test("a wired project_path never overwrites the picked month", async () => {
    // A WIRED project_path is resolved by walking the graph — a best-effort
    // guess, since the real branch is chosen at execution in Python. That guess
    // must never overwrite `month`, which feeds the queued render: a wrong month
    // makes resolve_month() silently fall back to months[0] and render the wrong
    // order. Only a typed project_path is authoritative enough to re-pick month.
    reset();
    setLatency(1);
    const wiredProject = ABSENT_PROJECT();
    setResponder((route) => {
        if (route.includes("list-orders")) {
            return route.includes(encodeURIComponent(wiredProject))
                ? { ok: true, body: { months: [{ label: "March" }] } }
                : { ok: true, body: { months: [] } };
        }
        return { ok: false, status: 400, body: { error: "order_path required" } };
    });

    // A String literal carries the path into a wired project_path socket.
    const literal = await create("StringLiteral", { value: wiredProject });
    const specs = await create("SymbioticaOrderSpecs",
        { project_path: "", month: "October", feature: "Mini 1" });
    link(literal, specs, "project_path");

    specs.onNodeCreated();
    for (let f = 0; f < 10; f++) await tick();

    const month = specs.widgets.find((w) => w.name === "month").value;
    assert.equal(month, "October",
                 "a wired-path resolution clobbered the render-feeding month");
});

test("an unrecognized multi-input switch resolves to no project, not a guess", async () => {
    // The resolver only understands an on_true/on_false switch. A third-party
    // switch (rgthree any_01/any_02, Impact select+input1/2) has several wired
    // inputs and no recognizable selector, so following "first wired input" can
    // pick the branch the server did NOT. Refuse to guess: resolve to empty so
    // the month dropdown blanks rather than showing a wrong project's months.
    reset();
    setLatency(1);
    const branchA = ABSENT_PROJECT(); // the branch a naive "first input" walk hits
    let listOrdersForA = 0;
    setResponder((route) => {
        if (route.includes("list-orders")) {
            if (route.includes(encodeURIComponent(branchA))) listOrdersForA++;
            return { ok: true, body: { months: [{ label: "March" }] } };
        }
        return { ok: false, status: 400, body: { error: "order_path required" } };
    });

    const litA = await create("StringLiteral", { value: branchA });
    const litB = await create("StringLiteral", { value: ABSENT_PROJECT() });
    const sw = await create("ImpactSwitch", { select: 2 }); // INT selector, no on_true/on_false
    link(litA, sw, "input1");
    link(litB, sw, "input2");
    const specs = await create("SymbioticaOrderSpecs",
        { project_path: "", month: "October", feature: "Mini 1" });
    link(sw, specs, "project_path");

    specs.onNodeCreated();
    for (let f = 0; f < 10; f++) await tick();

    assert.equal(listOrdersForA, 0,
                 "the resolver guessed a switch branch instead of refusing");
    assert.deepEqual(specs._symMonths, [],
                     "an unresolvable switch left a wrong project's month options");
});

test("a wired project_path never clobbers the picked feature", async () => {
    // The same invariant as month, on the other render-feeding widget: a wired
    // resolution must not overwrite `feature`. Regression: publishOrder blanked
    // feature to "", and Python's `feature = feature or events[0]` then rendered
    // the first event of the real project — a silently wrong render.
    reset();
    setLatency(1);
    const wiredProject = ABSENT_PROJECT();
    setResponder((route) => {
        if (route.includes("list-orders"))
            return { ok: true, body: { months: [{ label: "October" }] } };
        // parse-order fails -> events empty -> the pre-fix path blanks feature.
        return { ok: false, status: 400, body: { error: "order_path required" } };
    });

    const literal = await create("StringLiteral", { value: wiredProject });
    const specs = await create("SymbioticaOrderSpecs",
        { project_path: "", month: "October", feature: "Mini 1" });
    link(literal, specs, "project_path");

    specs.onNodeCreated();
    for (let f = 0; f < 10; f++) await tick();

    const feature = specs.widgets.find((w) => w.name === "feature").value;
    assert.equal(feature, "Mini 1",
                 "a wired-path resolution clobbered the render-feeding feature");
});
