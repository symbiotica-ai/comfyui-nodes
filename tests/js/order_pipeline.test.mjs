// ABOUTME: Drives the real order_pipeline.js under ComfyUI stubs and asserts a
// ABOUTME: failing parse-order settles instead of looping into a request flood.
import { test } from "node:test";
import assert from "node:assert/strict";

import {
    calls, setResponder, setLatency, reset, create, link, repaint, tick,
} from "./comfy_stub.mjs";
import "../../web/js/order_pipeline.js";

// A stale local path: it exists on the artist's mac, never inside the hosted
// sandbox, so resolve_month() yields no order_path and the route 400s forever.
const ABSENT_PROJECT = "/Users/someone/Google Drive/Clients/Imperia/bakery";

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
        { project_path: ABSENT_PROJECT, month: "October", feature: "Mini 1" });
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

test("two Order Specs sharing a project and month both get their events", async () => {
    // Sharing one request between them must not mean only one of them is
    // filled in — the other node's feature combo would stay empty forever.
    reset();
    setLatency(1);
    setResponder(always({ ok: true, status: 200,
                          body: { events: [ONE_EVENT], refsRoot: "/refs" } }));

    const a = await create("SymbioticaOrderSpecs",
        { project_path: ABSENT_PROJECT, month: "October", feature: "Mini 1" });
    const b = await create("SymbioticaOrderSpecs",
        { project_path: ABSENT_PROJECT, month: "October", feature: "Mini 1" });
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
        { project_path: ABSENT_PROJECT, month: "October", feature: "Mini 1" });
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
        { project_path: ABSENT_PROJECT, month: "October", feature: "Mini 1" });
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
        { project_path: ABSENT_PROJECT, month: "October", feature: "Mini 1" });
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
