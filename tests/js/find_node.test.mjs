// ABOUTME: Tests for find_node.js — the id lookup seam, and the box's behaviour
// ABOUTME: on a hit, a miss, Escape and a click outside, under the comfy stub.
import { test } from "node:test";
import assert from "node:assert/strict";

import { app, canvasCalls, create, fire, reset } from "./comfy_stub.mjs";
import "../../web/js/find_node.js";
import { describe as describeNode, lookup } from "../../web/js/find_node.js";

const OVERLAY_ID = "symbiotica-find-node";

const spec = () => app.extensions.find((e) => e.name === "symbiotica.find_node");
const command = () => spec().commands[0];

// The stub's querySelector always returns null, so the box is read positionally:
// body -> layer -> panel -> [input, hint], which is the order openBox builds.
const overlay = () => document.body.children.find((c) => c.id === OVERLAY_ID) ?? null;
const inputEl = () => overlay()?.children[0]?.children[0] ?? null;
const hintEl = () => overlay()?.children[0]?.children[1] ?? null;

// Open a box with nothing left over from the previous test: the module keeps a
// reference to the open one, so a second press refocuses rather than rebuilds.
function open() {
    const already = overlay();
    if (already) fire(already, "pointerdown");
    command().function();
    return overlay();
}

function type(text) {
    const input = inputEl();
    input.value = text;
    fire(input, "input");
}

function press(key) {
    const event = {
        key,
        prevented: false,
        stopped: false,
        preventDefault() { this.prevented = true; },
        stopPropagation() { this.stopped = true; },
    };
    fire(inputEl(), "keydown", event);
    return event;
}

// A node with an id the test can name, since the stub numbers them itself.
async function node(comfyClass, title) {
    const n = await create(comfyClass);
    if (title) n.title = title;
    return n;
}

test("registers a command and a bare-f keybinding for it", () => {
    const command = spec().commands[0];
    assert.equal(command.id, "Symbiotica.FindNodeById");
    assert.equal(command.label, "Find node by ID");
    assert.equal(typeof command.function, "function");

    const binding = spec().keybindings[0];
    assert.equal(binding.commandId, command.id);
    // Bare, so Settings -> Keybindings shows it unmodified and the frontend's
    // own guard keeps it from firing while you are typing in a field.
    assert.deepEqual(binding.combo, { key: "f" });
});

test("lookup says which of the four things it is", async () => {
    reset();
    const ksampler = await node("KSampler", "refine pass");

    assert.equal(lookup("").state, "empty");
    assert.equal(lookup("   ").state, "empty");
    assert.equal(lookup("abc").state, "invalid");
    assert.equal(lookup("-4").state, "invalid");
    assert.deepEqual(lookup("99999"), { state: "missing", id: "99999" });
    assert.deepEqual(lookup(String(ksampler.id)), { state: "found", node: ksampler });
});

test("describe does not repeat a title nobody changed", () => {
    assert.equal(describeNode({ comfyClass: "KSampler", title: "refine pass" }),
                 "KSampler · refine pass");
    assert.equal(describeNode({ comfyClass: "LoadImage", title: "LoadImage" }),
                 "LoadImage");
    assert.equal(describeNode({ comfyClass: "LoadImage", title: "  " }), "LoadImage");
    // A frontend-only node has no comfyClass; its litegraph type still names it.
    assert.equal(describeNode({ type: "Reroute" }), "Reroute");
});

test("the empty box says what to type", () => {
    reset();
    open();
    assert.ok(overlay());
    assert.match(hintEl().textContent, /ID badge/);
});

test("a second press does not stack a second box", () => {
    reset();
    open();
    command().function();
    assert.equal(document.body.children.filter((c) => c.id === OVERLAY_ID).length, 1);
});

test("the box reports the node while you type", async () => {
    reset();
    const ksampler = await node("KSampler", "refine pass");
    const loader = await node("LoadImage");
    open();

    type(String(ksampler.id));
    assert.equal(hintEl().textContent, "→ KSampler · refine pass");

    type(String(loader.id));
    assert.equal(hintEl().textContent, "→ LoadImage");

    type("99999");
    assert.equal(hintEl().textContent, "no node 99999 in this graph");
});

test("pasted junk keeps the number instead of refusing it", async () => {
    reset();
    const ksampler = await node("KSampler", "refine pass");
    open();

    type(`#${ksampler.id} `);
    assert.equal(inputEl().value, String(ksampler.id));
    assert.equal(hintEl().textContent, "→ KSampler · refine pass");
});

test("Enter on a hit selects and centres that node, then closes", async () => {
    reset();
    const ksampler = await node("KSampler", "refine pass");
    open();

    type(String(ksampler.id));
    const event = press("Enter");

    assert.deepEqual(canvasCalls.select, [ksampler.id]);
    assert.deepEqual(canvasCalls.center, [ksampler.id]);
    assert.ok(canvasCalls.dirty > 0);
    assert.equal(overlay(), null);
    assert.ok(event.prevented);
});

test("Enter on a miss moves nothing and keeps what you typed", () => {
    reset();
    open();

    type("99999");
    press("Enter");

    assert.deepEqual(canvasCalls.center, []);
    assert.deepEqual(canvasCalls.select, []);
    assert.ok(overlay(), "the box closed on a miss");
    assert.equal(inputEl().value, "99999");
    assert.equal(hintEl().textContent, "no node 99999 in this graph");
});

test("Escape closes it and is consumed", () => {
    reset();
    open();
    const event = press("Escape");
    assert.equal(overlay(), null);
    assert.ok(event.prevented);
});

test("a click outside closes it, a click inside does not", () => {
    reset();
    const layer = open();
    const panel = layer.children[0];

    fire(panel, "pointerdown", { stopPropagation() {} });
    assert.ok(overlay(), "a click on the box itself closed it");

    fire(layer, "pointerdown");
    assert.equal(overlay(), null);
});

test("typing in the box does not reach the canvas", () => {
    reset();
    open();
    // Without this the graph acts on every digit: the canvas listens on the
    // document, and bare keys are how its own commands are bound.
    assert.ok(press("4").stopped);
    press("Escape");
});
