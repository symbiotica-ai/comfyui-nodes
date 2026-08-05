// ABOUTME: Tests for find_node.js — the id lookup seam, and the box's behaviour
// ABOUTME: on a hit, a miss, Escape and a click outside, under the comfy stub.
import { test } from "node:test";
import assert from "node:assert/strict";

import { app, canvasCalls, create, fire, reset } from "./comfy_stub.mjs";
import "../../web/js/find_node.js";
import { comboLabel, describe as describeNode, lookup } from "../../web/js/find_node.js";

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

test("registers a command and a modified keybinding for it", () => {
    const command = spec().commands[0];
    assert.equal(command.id, "Symbiotica.FindNodeById");
    assert.equal(command.label, "Find node by ID");
    assert.equal(typeof command.function, "function");

    const binding = spec().keybindings[0];
    assert.equal(binding.commandId, command.id);
    // Modified on purpose. A bare letter collides with an installed pack —
    // `f` is KJNodes' fillConnectSelected — and the frontend then refuses the
    // binding outright rather than taking the loser's place.
    assert.deepEqual(binding.combo, { key: "0", ctrl: true, alt: false, shift: true });
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

// A stand-in for the frontend's canvas class. Extensions reach it as a global
// and patch its prototype; each test gets a fresh one so the module's
// don't-patch-twice guard is exercised where it is meant to be and nowhere else.
function canvasClass(coreOptions) {
    globalThis.LGraphCanvas = {
        prototype: { getCanvasMenuOptions() { return [...coreOptions]; } },
    };
    return globalThis.LGraphCanvas;
}

const menuContents = (LGraphCanvas) =>
    LGraphCanvas.prototype.getCanvasMenuOptions.call({}).map((o) => o?.content ?? null);

// Spelled out rather than rebuilt from the module's own pieces: a row assembled
// the same way the code assembles it would agree with any spelling it produced.
const MENU_ROW = "Find node by ID (Ctrl+Shift+0)";

test("the canvas menu entry comes before what the core offers", () => {
    const LGraphCanvas = canvasClass([{ content: "Add Node" }, { content: "Add Group" }]);
    spec().setup();

    // First, because that is the whole point of prepending rather than using
    // the supported hook — which appends and cannot say where it lands.
    assert.deepEqual(menuContents(LGraphCanvas),
                     [MENU_ROW, "Add Node", "Add Group"]);
});

test("the menu entry opens the same box the key does", () => {
    reset();
    const LGraphCanvas = canvasClass([]);
    spec().setup();

    LGraphCanvas.prototype.getCanvasMenuOptions.call({})[0].callback();
    assert.ok(overlay(), "the menu entry did not open the box");
    press("Escape");
});

test("loading the pack twice does not list the entry twice", () => {
    // Not hypothetical: a stale duplicate of a pack .js served alongside the
    // current one is the incident register.js exists for. Two registrations
    // would otherwise prepend two identical rows.
    const LGraphCanvas = canvasClass([{ content: "Add Node" }]);
    spec().setup();
    spec().setup();

    assert.deepEqual(menuContents(LGraphCanvas), [MENU_ROW, "Add Node"]);
});

test("a frontend without the old menu hook is left alone", () => {
    // The hook is deprecated. When it goes, install nothing rather than a
    // replacement that calls an original which is no longer there.
    globalThis.LGraphCanvas = { prototype: {} };
    spec().setup();
    assert.equal(globalThis.LGraphCanvas.prototype.getCanvasMenuOptions, undefined);

    delete globalThis.LGraphCanvas;
    assert.doesNotThrow(() => spec().setup());
});

test("comboLabel names the keys the way the settings page does", () => {
    assert.equal(comboLabel({ key: "0", ctrl: true, alt: false, shift: true }),
                 "Ctrl+Shift+0");
    assert.equal(comboLabel({ key: "0", ctrl: true, alt: true, shift: true }),
                 "Ctrl+Alt+Shift+0");
    assert.equal(comboLabel({ key: "f" }), "F");
    assert.equal(comboLabel(null), "");
});

test("the menu row shows the shortcut, the command label does not", () => {
    const LGraphCanvas = canvasClass([{ content: "Add Node" }]);
    spec().setup();

    // The row is where the shortcut has to be readable: it is the only place a
    // staffer meets this feature without already knowing it exists.
    assert.equal(menuContents(LGraphCanvas)[0], MENU_ROW);
    // The command keeps its bare name — Settings → Keybindings renders the combo
    // in its own column, so a suffix here would print the keys twice.
    assert.equal(spec().commands[0].label, "Find node by ID");
});
