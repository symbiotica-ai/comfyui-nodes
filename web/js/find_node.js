// ABOUTME: "Find node by ID" — a shortcut opens a small box, type the number the
// ABOUTME: node's ID badge shows, and the canvas jumps to that node, selected.

// Why this exists: an error message, a log line and the node badge all name a
// node by its id, and on a graph of two hundred nodes there is no way to get
// from that number to the node except panning around looking for it. The
// frontend has the jump itself (`goToNode` in its dialog service, used when you
// click an error) but never exposes it — there is no command, so there is
// nothing to bind a key to. This registers the command; ComfyUI's
// Settings → Keybindings does the rest.
import { app } from "../../../scripts/app.js";
import { registerSymbioticaExtension } from "./register.js";
import { HUB, injectHubStyles } from "./hub_theme.js";
import { el } from "./browser_chrome.js";

const COMMAND_ID = "Symbiotica.FindNodeById";
const OVERLAY_ID = "symbiotica-find-node";
// One string for the command palette, the keybinding list and the canvas menu,
// so a row nobody can find is not a row whose name drifted from the others.
const LABEL = "Find node by ID";

// Not a bare letter. The core defaults leave most of the alphabet free, but
// installed packs take them without anyone being able to see it from here —
// `f` is KJNodes' `fillConnectSelected`, and the frontend refuses the whole
// binding with "Keybinding on f already exists on …". A modified combo is
// out of that contested space. Rebind or clear it in Settings → Keybindings.
const COMBO = { key: "0", ctrl: true, alt: false, shift: true };

// The shortcut as the settings page writes it: modifiers in a fixed order, then
// the key. Built from the combo this pack registers rather than read back from
// the frontend, so what the menu row promises is what the pack asked for — a
// staffer who rebinds it in Settings is the one person who already knows.
export function comboLabel(combo) {
    if (!combo?.key) return "";
    const parts = [];
    if (combo.ctrl) parts.push("Ctrl");
    if (combo.alt) parts.push("Alt");
    if (combo.shift) parts.push("Shift");
    parts.push(combo.key.length === 1 ? combo.key.toUpperCase() : combo.key);
    return parts.join("+");
}

// The graph on screen, which is not `app.graph` once you have stepped into a
// subgraph. Ids are scoped to their own graph, so searching the one being
// looked at is the only reading of "node 42" that can be acted on.
function activeGraph() {
    return app.canvas?.graph ?? app.graph ?? null;
}

// A node id is a number on the root graph and a string inside a subgraph, and
// `getNodeById` does not coerce, so ask both ways rather than guess.
function nodeById(text) {
    const graph = activeGraph();
    if (!graph?.getNodeById) return null;
    return graph.getNodeById(Number(text)) ?? graph.getNodeById(text) ?? null;
}

// What the box says under the input. Kept separate from the DOM so the rules —
// digits only, and a number that matches nothing is not an error you have to
// dismiss — are readable in one place.
export function lookup(raw) {
    const text = String(raw ?? "").trim();
    if (!text) return { state: "empty" };
    if (!/^\d+$/.test(text)) return { state: "invalid" };
    const node = nodeById(text);
    return node ? { state: "found", node } : { state: "missing", id: text };
}

// Type plus title, unless the title is still the type — a node nobody renamed
// would otherwise read "KSampler · KSampler".
export function describe(node) {
    const type = node?.comfyClass ?? node?.type ?? "node";
    const title = String(node?.title ?? "").trim();
    return title && title !== type ? `${type} · ${title}` : type;
}

// Centre on it and select it, leaving the zoom alone: you asked to be taken to
// a node, not to have your view of the graph rescaled. `centerOnNode` is the
// canvas' own move and keeps `ds.scale` untouched; selecting is what makes the
// node the target of everything that acts on a selection next.
function goTo(node) {
    const canvas = app.canvas;
    if (!canvas || !node) return false;
    canvas.selectNode?.(node);
    canvas.centerOnNode?.(node);
    canvas.setDirty?.(true, true);
    return true;
}

// The box while it is open, so a second press of the key can reach its input
// without going back through the document to look for it.
let box = null;

function closeBox() {
    box?.layer?.remove?.();
    box = null;
}

function openBox() {
    injectHubStyles();

    // Already open: a second press should put the cursor back in the box with
    // the old number selected, so retyping is one keystroke — not stack a
    // second overlay on the first. `parentElement` is the check rather than
    // `box` itself, because anything that clears the page out from under us
    // leaves the reference pointing at an element nobody can see.
    if (box?.layer?.parentElement) {
        box.input.focus?.();
        box.input.select?.();
        return;
    }
    closeBox();

    // A full-screen layer so a click anywhere outside the box closes it. It
    // paints nothing: the graph stays visible and untinted, because the box is
    // a lookup, not a modal step you are being held in.
    const layer = el("div",
        "position:fixed;inset:0;z-index:10000;background:transparent;");
    layer.id = OVERLAY_ID;

    const panel = el("div",
        "position:absolute;left:50%;top:18%;transform:translateX(-50%);"
        + `width:300px;box-sizing:border-box;padding:10px;background:${HUB.surface2};`
        + `border:1px solid ${HUB.hairlineStrong};border-radius:${HUB.radius.lg};`
        + "box-shadow:0 12px 32px rgba(0,0,0,.5);");

    const input = el("input",
        `width:100%;box-sizing:border-box;padding:7px 10px;background:${HUB.surface1};`
        + `color:${HUB.ink};border:1px solid ${HUB.hairlineStrong};`
        + `border-radius:${HUB.radius.md};font:13px ${HUB.mono};`);
    input.className = "sym-input";
    input.type = "text";
    input.inputMode = "numeric";
    input.autocomplete = "off";
    input.placeholder = "Node ID…";

    const hint = el("div",
        `margin-top:6px;min-height:15px;font:11px ${HUB.font};color:${HUB.inkSubtle};`
        + "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;");

    function render() {
        const result = lookup(input.value);
        if (result.state === "found") {
            hint.style.color = HUB.ink;
            hint.textContent = `→ ${describe(result.node)}`;
        } else if (result.state === "missing") {
            hint.style.color = HUB.danger;
            hint.textContent = `no node ${result.id} in this graph`;
        } else if (result.state === "invalid") {
            hint.style.color = HUB.danger;
            hint.textContent = "digits only";
        } else {
            hint.style.color = HUB.inkSubtle;
            hint.textContent = "type the number on the node's ID badge · Enter to go";
        }
    }

    function submit() {
        const result = lookup(input.value);
        // A miss leaves the box open holding what you typed. Closing on a wrong
        // number would make you reopen it and retype the part you got right.
        if (result.state !== "found" || !goTo(result.node)) {
            render();
            input.select?.();
            return;
        }
        closeBox();
    }

    // The canvas listens on the document for its own keys; without this, typing
    // a digit here also fires whatever that digit is bound to on the graph.
    input.addEventListener("keydown", (e) => {
        e.stopPropagation();
        if (e.key === "Enter") { e.preventDefault(); submit(); }
        else if (e.key === "Escape") { e.preventDefault(); closeBox(); }
    });
    input.addEventListener("input", () => {
        // Paste "#42" or "node 42" and keep the number rather than being told off.
        const digits = input.value.replace(/\D+/g, "");
        if (digits !== input.value) input.value = digits;
        render();
    });

    // Clicks inside are not "outside". Default-prevented everywhere except on
    // the input, so the box's own chrome cannot take focus off it: Escape and
    // the key guard are both bound to the input, and once it is blurred the box
    // stops closing on Escape while the digits typed at it reach the canvas.
    // The input is exempt because preventing its default is what would stop the
    // click placing the caret.
    panel.addEventListener("pointerdown", (e) => {
        e.stopPropagation();
        if (e.target !== input) e.preventDefault();
    });

    layer.addEventListener("pointerdown", () => closeBox());

    panel.append(input, hint);
    layer.appendChild(panel);
    document.body.appendChild(layer);
    box = { layer, input, hint };
    render();
    input.focus?.();
}

// Marks the function this module installed, so a second registration finds its
// own work rather than the core's. Not hypothetical: a stale duplicate of a
// pack's .js served alongside the current one is the incident register.js exists
// for, and two registrations would otherwise put two identical rows in the menu.
const PATCHED = "symbioticaFindNode";

// The canvas right-click menu, ahead of everything the core offers.
//
// `getCanvasMenuOptions` is deprecated in favour of the `getCanvasMenuItems`
// extension hook, and that hook is the reason this is not written with it: it
// returns items for the frontend to merge and has no way to say WHERE they go,
// so an entry added through it lands under the core's own. Prepending is the
// only way to be first, and being first is the request.
//
// Two consequences worth knowing. Other packs prepend the same way — whoever
// registers last ends up on top, so "first" is first among ours, not a claim on
// the row. And when the deprecated hook is finally removed this stops being
// called rather than failing, so the entry will go missing quietly; the item to
// look at then is `getCanvasMenuItems`.
function prependCanvasMenuItem(canvasClass) {
    const proto = canvasClass?.prototype;
    const original = proto?.getCanvasMenuOptions;
    if (typeof original !== "function" || original[PATCHED]) return false;
    function withFinder() {
        const options = original.apply(this, arguments) ?? [];
        // The shortcut rides the row here and nowhere else: this is the only
        // place the feature is met by someone not already looking for it.
        options.unshift({ content: `${LABEL} (${comboLabel(COMBO)})`, callback: openBox });
        return options;
    }
    withFinder[PATCHED] = true;
    proto.getCanvasMenuOptions = withFinder;
    return true;
}

registerSymbioticaExtension(app, {
    name: "symbiotica.find_node",
    // The canvas class is a global the frontend puts there, not something this
    // pack can import: litegraph is not on the public module surface.
    setup() { prependCanvasMenuItem(globalThis.LGraphCanvas); },
    commands: [{
        id: COMMAND_ID,
        label: LABEL,
        icon: "pi pi-search",
        function: openBox,
    }],
    keybindings: [{ commandId: COMMAND_ID, combo: COMBO }],
});
