// ABOUTME: The canvas-wide tools, which belong to no one node: "Find node by ID",
// ABOUTME: and the Set/Get Hubs — one node holding many named constants.

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

// ======================================================== Set Hub / Get Hub ==

// Why these exist: a canvas wired through KJNodes' Set/Get grows one node per
// constant — tens of them, each carrying a single name. A hub carries many.
// Wire an output into a hub's empty slot and that slot takes the wire's type
// and the name of the output it came from, then a fresh empty slot appears
// underneath. The Get side grows the same way, one output per name it pulls.
//
// Both are VIRTUAL nodes: no Python class, nothing in the queued prompt. The
// frontend resolves them away — `ExecutableNodeDTO.resolveOutput` asks a
// virtual node for `resolveVirtualOutput(slot)`, then falls back to
// `getInputLink(slot)`, both indexed BY OUTPUT SLOT. That per-slot indexing is
// the whole trick: it is what lets one node stand in for twenty pairs, and it
// is in the 1.48.7 bundle, not just in newer frontends.
//
// A constant's NAME is the slot's label. That is what the frontend's own
// "Rename Slot" writes, so renaming costs no code here, and it rides on the
// slot rather than on a widget — none of this pack's widget-shift traps apply,
// because a hub has no widgets at all.
//
// Names are one flat namespace shared with KJNodes' SetNode: a Get Hub reads a
// name published by a plain Set node just as happily as one on a hub, so a
// canvas can move a handful at a time. It does not work the other way — KJ's
// GetNode looks for `type === 'SetNode'` and cannot see a hub slot.

const SET_HUB = "SymbioticaSetHub";
const GET_HUB = "SymbioticaGetHub";
// The empty slot at the bottom of every hub. No constant may be called this.
const GROW = "+";
const ANY = "*";
// What the Get Hub's picker reads when nothing is picked, and what it goes
// back to after a pick: the widget is a button for choosing, not a value.
const PULL = "value or group…";
const NONE = "(nothing published on this canvas)";
// A Set Hub is a GROUP: its TITLE names the set of constants it holds, and a
// Get Hub can take the whole set in one pick. The group a Get is following
// rides on `properties`, which serialises with the workflow and survives the
// node being retitled by hand.
const GROUP_PROP = "symbiotica_group";
// The Set Hub the group came from. A title is what you read, but it is also
// what he retitles: the id is what carries a following Get across a rename.
const GROUP_ID_PROP = "symbiotica_group_id";
// How a group reads in the picker, beside the plain names.
const groupLabel = (group) => `${group.title}  ·  ${group.names.length} `
    + `name${group.names.length === 1 ? "" : "s"}`;
// The dot on a Get slot pointing at a name that is gone. This pack's danger
// colour, from hub_theme.
const DEAD = "#f2777a";
// One folder for the pack, as everything else here declares.
const CATEGORY = "Symbiotica";
const TITLES = {
    [SET_HUB]: "Set Hub (Symbiotica)",
    [GET_HUB]: "Get Hub (Symbiotica)",
};

// Where the last click was, for placing the name menu. LiteGraph's ContextMenu
// is positioned from an event, and the one that opens the menu (dropping a
// wire) is long gone by the time the connection callback runs.
let lastPointer = null;
if (typeof window !== "undefined" && typeof window.addEventListener === "function") {
    for (const type of ["pointerdown", "pointerup"]) {
        window.addEventListener(type, (e) => { lastPointer = e; }, true);
    }
}

function toast(severity, summary, detail, life = 5000) {
    app.extensionManager?.toast?.add({ severity, summary, detail, life });
}

// A slot's constant name. "Rename Slot" writes `label` and leaves `name` as it
// was, so the label is the answer whenever there is one.
export function slotName(slot) {
    return String(slot?.label ?? slot?.name ?? "").trim();
}

// LiteGraph's link table is a Map on current frontends and a plain object on
// older ones. Both are on canvases this pack runs against.
function getLink(graph, id) {
    if (id == null || !graph) return null;
    return graph.links?.get?.(id) ?? graph.links?.[id] ?? null;
}

export function nodesOf(graph) {
    return graph?._nodes ?? graph?.nodes ?? [];
}

// The graphs a name is looked up in: the one the node sits on, then the root.
// A Set commonly sits on the root graph while the Gets are inside subgraphs,
// and the frontend carries a virtual node's value across that boundary.
export function graphScope(graph, root) {
    return [graph, root].filter((g, i, all) => g && all.indexOf(g) === i);
}

// Every graph on the canvas, root first, subgraphs through the nodes that hold
// them. Used to reach Get Hubs that need a type refreshed, which can be
// anywhere, unlike a lookup, which only ever looks up.
function everyGraph(root) {
    const seen = new Set();
    const out = [];
    const walk = (graph) => {
        if (!graph || seen.has(graph)) return;
        seen.add(graph);
        out.push(graph);
        for (const node of nodesOf(graph)) walk(node.subgraph);
    };
    walk(root);
    return out;
}

// Every name published in scope and the type it carries. A Set Hub publishes
// one per named input; a KJNodes SetNode publishes the one on its widget.
export function publishedNames(graphs) {
    const out = [];
    const seen = new Set();
    for (const graph of graphs) {
        for (const node of nodesOf(graph)) {
            const type = String(node.type ?? "");
            if (type === SET_HUB) {
                for (const slot of node.inputs ?? []) {
                    const name = slotName(slot);
                    if (!name || name === GROW || seen.has(name)) continue;
                    seen.add(name);
                    out.push({ name, type: String(slot.type ?? ANY), node, graph });
                }
            } else if (type === "SetNode") {
                const name = String(node.widgets?.[0]?.value ?? "").trim();
                if (!name || seen.has(name)) continue;
                seen.add(name);
                out.push({ name, type: String(node.inputs?.[0]?.type ?? ANY),
                           node, graph });
            }
        }
    }
    return out;
}

// Every Set Hub on the canvas, as a group: the node's TITLE names it and its
// named slots are what it holds, in slot order. A hub holding nothing yet is
// not a group -- there would be nothing to load.
export function publishedGroups(graphs) {
    const out = [];
    for (const graph of graphs) {
        for (const node of nodesOf(graph)) {
            if (String(node.type ?? "") !== SET_HUB) continue;
            const names = (node.inputs ?? [])
                .filter((slot) => slotName(slot) && slotName(slot) !== GROW)
                .map((slot) => ({ name: slotName(slot),
                                  type: String(slot.type ?? ANY) }));
            if (!names.length) continue;
            out.push({ title: String(node.title ?? "").trim() || "Set Hub",
                       names, node, graph });
        }
    }
    return out;
}

// The group a Get Hub is following, and what it holds now. Null when the node
// follows none, or when the Set Hub it named is gone -- the slots it already
// has stay either way; `dropDeadNames` is what takes the ones behind them.
//
// The Set Hub's ID answers before its title, so retitling a group carries
// every Get following it -- the same rule as renaming a slot. The title is
// healed on the way past, here and on the node, so the canvas never reads one
// name while the node holds another.
export function groupOf(node, graphs) {
    const props = node?.properties ?? {};
    const title = String(props[GROUP_PROP] ?? "").trim();
    const id = props[GROUP_ID_PROP];
    if (!title && id == null) return null;
    const groups = publishedGroups(graphs);
    const byId = id == null ? null
        : groups.find((g) => String(g.node?.id) === String(id));
    const group = byId ?? groups.find((g) => g.title === title) ?? null;
    if (!group) return null;
    if (group.title !== title) {
        if (String(node.title ?? "").trim() === title) node.title = group.title;
        props[GROUP_PROP] = group.title;
    }
    if (group.node?.id != null) props[GROUP_ID_PROP] = group.node.id;
    return group;
}

// The slot a name is fed through: `{graph, node, index}`, on a hub or on a
// plain SetNode. A Get reads whatever is wired INTO that slot, never the name.
export function findSource(graphs, name) {
    if (!name || name === GROW) return null;
    for (const graph of graphs) {
        for (const node of nodesOf(graph)) {
            const type = String(node.type ?? "");
            if (type === SET_HUB) {
                const index = (node.inputs ?? [])
                    .findIndex((slot) => slotName(slot) === name);
                if (index >= 0) return { graph, node, index };
            } else if (type === "SetNode"
                    && String(node.widgets?.[0]?.value ?? "").trim() === name) {
                return { graph, node, index: 0 };
            }
        }
    }
    return null;
}

// A name nothing else in scope is using: two slots under one name would make
// which of them a Get reads a matter of node order.
export function uniqueName(taken, base) {
    const clean = String(base ?? "").trim().replace(/^[+*]+$/, "") || "value";
    if (!taken.has(clean)) return clean;
    for (let n = 2; n < 999; n += 1) {
        if (!taken.has(`${clean}_${n}`)) return `${clean}_${n}`;
    }
    return `${clean}_${Date.now()}`;
}

// Whether a published name can be dropped on an input. `*` on either side
// takes anything, and a comma list is the frontend's own way of writing "one
// of these".
export function typeAccepts(target, offered) {
    const wanted = String(target ?? ANY).trim();
    const has = String(offered ?? ANY).trim();
    if (!wanted || !has || wanted === ANY || has === ANY) return true;
    const wantedList = wanted.split(",").map((t) => t.trim());
    return has.split(",").some((t) => wantedList.includes(t.trim()));
}

// One empty slot at the bottom, always, and never two. Asserted on draw as
// well as on every wire change, because the frontend's own "Remove Slot" takes
// a slot off the node without any event reaching it.
export function ensureTail(node, kind) {
    const list = (kind === "in" ? node.inputs : node.outputs) ?? [];
    const isEmpty = (slot) => (kind === "in"
        ? slot.link == null : !(slot.links?.length));
    for (let i = list.length - 2; i >= 0; i -= 1) {
        if (slotName(list[i]) !== GROW || !isEmpty(list[i])) continue;
        if (kind === "in") node.removeInput(i); else node.removeOutput(i);
    }
    const last = list[list.length - 1];
    if (last && slotName(last) === GROW && isEmpty(last)) return false;
    if (kind === "in") node.addInput(GROW, ANY, { removable: true });
    else node.addOutput(GROW, ANY, { removable: true });
    return true;
}

// The output slot a wire leaves. `resolve` is the frontend's own reader and
// handles a wire coming out of a subgraph input; the link's own ids are the
// fallback for anything that does not carry it.
function originSlot(graph, linkInfo) {
    const resolved = linkInfo?.resolve?.(graph);
    const found = resolved?.subgraphInput ?? resolved?.output;
    if (found) return found;
    const source = graph?.getNodeById?.(linkInfo?.origin_id);
    return source?.outputs?.[linkInfo?.origin_slot] ?? null;
}

// The types whose NAME carries no meaning. `MODEL`, `VAE`, `CONTROL_NET` say
// exactly what the value is and make good names; `STRING` says nothing, and
// three of them become STRING, STRING_2, STRING_3 -- which is what he got.
const NAMELESS_TYPES = new Set(["STRING", "INT", "FLOAT", "BOOLEAN", "BOOL",
                                "NUMBER", "COMBO", ANY]);

// What to call a slot a wire just landed on. An output named for what it
// carries -- `asset_name`, `save_path`, `MODEL` -- is already the name you
// would have typed. One named after a type that says nothing falls back to the
// node it came from. Rename takes it from there either way.
export function nameFromWire(origin, type, sourceNode) {
    const slot = String(origin?.label ?? origin?.name ?? "").trim();
    const kind = String(type ?? ANY).trim();
    const sameAsType = slot.toUpperCase() === kind.toUpperCase();
    if (slot && (!sameAsType || !NAMELESS_TYPES.has(kind.toUpperCase()))) {
        return slot === ANY ? kind : slot;
    }
    const title = String(sourceNode?.title ?? "").trim();
    if (title && title.toUpperCase() !== kind.toUpperCase()) return title;
    return slot || kind;
}

// A wire landed on a hub input. An unnamed slot takes the name of the output
// feeding it — nearly always what you would have typed into a SetNode anyway —
// and a slot that already has a name keeps it: the name is what every Get on
// the canvas points at, so rewiring one changes the value, never the contract.
function adoptInput(node, index, linkInfo) {
    const slot = node.inputs?.[index];
    if (!slot) return;
    const origin = originSlot(node.graph, linkInfo);
    const type = String(origin?.type ?? ANY);
    if (slotName(slot) === GROW || slotName(slot) === "") {
        const taken = new Set(
            publishedNames(graphScope(node.graph, app.graph)).map((e) => e.name));
        const from = node.graph?.getNodeById?.(linkInfo?.origin_id);
        const name = uniqueName(taken, nameFromWire(origin, type, from));
        slot.name = name;
        slot.label = name;
    }
    slot.type = type;
    retypeGetters(slotName(slot), type);
}

// A wire taken off a Set Hub input takes the slot with it. A name with nothing
// behind it publishes nothing -- the Gets pulling it get "nothing is wired into
// X" and the row for it is a promise the node cannot keep.
//
// Deferred by a tick, because REWIRING a slot is a disconnect and a connect
// back to back: a slot that has a wire again by the time the tick comes is
// being rewired, not abandoned. The slot OBJECT is what is held onto, never its
// index -- anything else removed meanwhile would move it.
export function dropWhenUnwired(node, index, defer = setTimeout) {
    const slot = node.inputs?.[index];
    if (!slot || slotName(slot) === GROW) return;
    defer(() => {
        const at = (node.inputs ?? []).indexOf(slot);
        if (at < 0 || slot.link != null || slotName(slot) === GROW) return;
        node.removeInput(at);
        ensureTail(node, "in");
        syncNameWidgets(node);
        node.setDirtyCanvas?.(true, true);
    }, 0);
}

// A name that changed type has to reach the Get Hubs pulling it, or their
// outputs keep advertising the old type and the next wire off them is refused.
function retypeGetters(name, type) {
    if (!name || name === GROW) return;
    for (const graph of everyGraph(app.graph)) {
        for (const node of nodesOf(graph)) {
            if (String(node.type ?? "") !== GET_HUB) continue;
            for (const slot of node.outputs ?? []) {
                if (slotName(slot) === name) slot.type = type;
            }
        }
    }
}

// The name menu: every constant in scope, the ones that fit the input the wire
// landed on first. Dismissing it without picking has to undo the wire, so the
// slot is never left connected under the placeholder name — the menu has no
// cancel callback, so its element going away is what we watch.
function pickName(node, index, wantedType, onPick) {
    const all = publishedNames(graphScope(node.graph, app.graph));
    const fits = all.filter((e) => typeAccepts(wantedType, e.type));
    const list = fits.length ? fits : all;
    if (!list.length) {
        toast("warn", "Nothing to get",
              "No Set Hub slot or Set node on this canvas has a name yet.");
        onPick(null);
        return;
    }
    const labels = list.map((e) => (e.type && e.type !== ANY
        ? `${e.name}   ·   ${e.type}` : e.name));
    let picked = false;
    const menu = new LiteGraph.ContextMenu(labels, {
        event: lastPointer,
        title: "Get",
        className: "dark",
        scale: Math.max(1, app.canvas?.ds?.scale ?? 1),
        callback: (label) => {
            picked = true;
            onPick(list[labels.indexOf(label)] ?? null);
        },
    });
    const root = menu?.root;
    if (!root) return;
    const watch = () => {
        if (picked) return;
        if (root.isConnected === false || !root.parentElement) { onPick(null); return; }
        setTimeout(watch, 150);
    };
    setTimeout(watch, 150);
}

// A picked name on a Get Hub output. The link already on the slot survives a
// type change, so a name that does not fit what it was dropped on is dropped
// instead of quietly sitting there as a wire the backend will refuse.
function assignGetSlot(node, index, entry) {
    const slot = node.outputs?.[index];
    if (!slot || !entry) return;
    slot.name = entry.name;
    slot.label = entry.name;
    slot.type = entry.type && entry.type !== ANY ? entry.type : ANY;
    for (const id of [...(slot.links ?? [])]) {
        const link = getLink(node.graph, id);
        const target = node.graph?.getNodeById?.(link?.target_id);
        const input = target?.inputs?.[link?.target_slot];
        if (input && !typeAccepts(input.type, slot.type)) {
            target.disconnectInput?.(link.target_slot, true);
        }
    }
    ensureTail(node, "out");
    node.setDirtyCanvas?.(true, true);
}

// A name picked off the node's own list: it lands on the empty tail slot, the
// same place a dropped wire would have named.
function addGetSlot(node, name) {
    const entry = publishedNames(graphScope(node.graph, app.graph))
        .find((e) => e.name === name);
    if (!entry) return;
    if ((node.outputs ?? []).some((s) => slotName(s) === name)) {
        toast("info", "Get Hub", `"${name}" is already on this node.`);
        return;
    }
    ensureTail(node, "out");
    assignGetSlot(node, node.outputs.length - 1, entry);
}

// A whole group, taken at once. The node BECOMES that group: picking
// `settings-01` means the node holds settings-01 and nothing else, not
// settings-02 with settings-01 added underneath it. Everything it was
// carrying goes first, wires and all -- there is no slot to keep a wire on
// once the name behind it is not in the group you asked for.
export function loadGroup(node, group) {
    if (!group) return;
    node.properties ??= {};
    const was = String(node.properties[GROUP_PROP] ?? "").trim();
    node.properties[GROUP_PROP] = group.title;
    node.properties[GROUP_ID_PROP] = group.node?.id ?? null;
    for (let i = (node.outputs?.length ?? 0) - 1; i >= 0; i -= 1) {
        if (slotName(node.outputs[i]) === GROW) continue;
        node.disconnectOutput?.(i);
        node.removeOutput(i);
    }
    // The title follows the group -- while it is still the name every Get Hub
    // is born with, or the group it was showing a second ago. A title typed by
    // hand is his and stays.
    const stock = ["", "Get Hub", TITLES[GET_HUB], was];
    if (stock.includes(String(node.title ?? "").trim())) node.title = group.title;
    syncGroup(node);
    node.setDirtyCanvas?.(true, true);
}

// What following a group means, re-asserted on every draw: the Set Hub's names
// are all here. Asserted rather than copied once, because a group whose new
// third name never reaches the Gets is the stale copy this node exists to
// replace.
export function syncGroup(node) {
    const scope = graphScope(node.graph, app.graph);
    const group = groupOf(node, scope);
    if (!group) return false;
    const wanted = new Set(group.names.map((e) => e.name));
    let changed = false;
    // A name that has left the group and that nothing else publishes is
    // litter. A slot with a WIRE on it is never taken away silently, whatever
    // its name says -- it stays, and goes red.
    for (let i = (node.outputs?.length ?? 0) - 1; i >= 0; i -= 1) {
        const slot = node.outputs[i];
        const name = slotName(slot);
        if (!name || name === GROW || wanted.has(name)) continue;
        if (slot.links?.length || findSource(scope, name)) continue;
        node.removeOutput(i);
        changed = true;
    }
    const have = new Set((node.outputs ?? []).map(slotName));
    for (const entry of group.names) {
        if (have.has(entry.name)) continue;
        // Appended, never inserted: a wire holds on to a slot's INDEX, so
        // making room in the middle would move every wire below it.
        ensureTail(node, "out");
        assignGetSlot(node, node.outputs.length - 1, entry);
        changed = true;
    }
    return changed;
}

// The named slots, in order. The rows below are a positional view of this
// list, so index 3 means "whatever the fourth constant is right now".
export function namedSlots(node) {
    return (node.inputs ?? []).filter((s) => slotName(s) !== GROW);
}

// The name of every constant on the node, typed in place. A Set node's whole
// point is that you name the thing, so the names are rows you can edit, not a
// dialog behind a right-click: one text field per named slot, in slot order,
// labelled with the type the slot carries.
//
// Only the COUNT is maintained here. A row holds no value of its own -- see
// below -- so there is nothing to write back, nothing to keep in step with the
// slots, and no rebuild to time against a draw.
function syncNameWidgets(node) {
    const named = namedSlots(node);
    node.widgets ??= [];
    while (node.widgets.length > named.length) node.widgets.pop();
    while (node.widgets.length < named.length) addNameRow(node, node.widgets.length);
    node.serialize_widgets = false;
}

// One row, bound to the slot at `index` for as long as it lives.
//
// `value` and `label` are OWN properties, which shadow the accessors the
// frontend's BaseWidget backs with its widget store. That store keys a
// remembered value by (graph, node, widget NAME) and hands any widget under a
// name it has seen the state it already holds -- two rows called "STRING" were
// handed ONE state between them and drew the same name twice, whatever the
// slots said. A row that reads the slot cannot drift from it, and a row that
// renames on write cannot hold a name the slot refused.
export function addNameRow(node, index) {
    const widget = node.addWidget("text", `name_${index + 1}`, "",
        (value) => renameTo(node, index, value));
    Object.defineProperty(widget, "value", {
        configurable: true,
        enumerable: true,
        get: () => slotName(namedSlots(node)[index]),
        set: (value) => renameTo(node, index, value),
    });
    // The type is what you read on the left of the row, and it changes when the
    // slot is rewired, so it is read live as well.
    Object.defineProperty(widget, "label", {
        configurable: true,
        enumerable: true,
        get: () => String(namedSlots(node)[index]?.type ?? ANY),
        set: () => {},
    });
    widget.serializeValue = () => undefined;
    return widget;
}

// A name typed into one of those fields. Same rules as the menu's rename: a
// clash is resolved rather than allowed, and every Get pulling the old name
// follows it over.
function renameTo(node, index, value) {
    const slot = namedSlots(node)[index];
    if (!slot) return;
    const was = slotName(slot);
    const wanted = String(value ?? "").trim();
    // Reached twice for one edit -- the row's setter renames, then the widget's
    // own callback arrives carrying what the slot now says. The second pass is
    // this line.
    if (!wanted || wanted === was) return;
    const taken = new Set(publishedNames(graphScope(node.graph, app.graph))
        .map((e) => e.name).filter((n) => n !== was));
    const name = uniqueName(taken, wanted);
    slot.name = name;
    slot.label = name;
    repointGetters(was, name);
    node.setDirtyCanvas?.(true, true);
}

// Renaming a constant on the Set side has to carry every Get that pulls it, or
// the rename silently unplugs them. KJNodes' Set does the same thing when its
// widget changes; here the old name is known because the slot held it.
function repointGetters(was, now) {
    if (!was || was === now) return;
    for (const graph of everyGraph(app.graph)) {
        for (const node of nodesOf(graph)) {
            if (String(node.type ?? "") !== GET_HUB) continue;
            for (const slot of node.outputs ?? []) {
                if (slotName(slot) !== was) continue;
                slot.name = now;
                slot.label = now;
            }
        }
    }
}

// Ask for a name. The frontend's dialog when there is one -- there is on every
// version this pack runs against -- and the browser's as the last resort, so
// the entry is never a menu row that does nothing.
async function askForName(title, current) {
    const dialog = app.extensionManager?.dialog;
    if (dialog?.prompt) {
        return await dialog.prompt({ title, message: "Name", defaultValue: current });
    }
    if (typeof window !== "undefined" && window.prompt) {
        return window.prompt(title, current);
    }
    return null;
}

// The constant a slot carries, renamed in place. The name is the contract, so
// a clash is resolved rather than allowed, and the Gets follow it over.
function renameSlot(node, kind, index) {
    const list = (kind === "in" ? node.inputs : node.outputs) ?? [];
    const slot = list[index];
    if (!slot || slotName(slot) === GROW) return;
    const was = slotName(slot);
    askForName(`Rename "${was}"`, was).then((answer) => {
        const wanted = String(answer ?? "").trim();
        if (!wanted || wanted === was) return;
        const taken = new Set(publishedNames(graphScope(node.graph, app.graph))
            .map((e) => e.name).filter((n) => n !== was));
        const name = uniqueName(taken, wanted);
        slot.name = name;
        slot.label = name;
        if (kind === "in") repointGetters(was, name);
        node.setDirtyCanvas?.(true, true);
    });
}

// The slot's own right-click menu, written out here rather than left to the
// frontend's default: the default differs by version -- it hangs rename off a
// `nameLocked` flag and remove off `removable` -- and a rename that is there on
// one canvas and missing on the next is the same as not having one.
function slotMenu(node, kind, slotInfo, extra) {
    const index = slotInfo?.slot ?? 0;
    const list = (kind === "in" ? node.inputs : node.outputs) ?? [];
    const slot = list[index];
    const options = [];
    if (slot && slotName(slot) !== GROW) options.push(...extra(index, slot));
    const connected = kind === "in" ? slot?.link != null : !!slot?.links?.length;
    if (connected) {
        options.push({
            content: "Disconnect",
            callback: () => {
                if (kind === "in") node.disconnectInput(index, true);
                else node.disconnectOutput(index);
                ensureTail(node, kind);
                node.setDirtyCanvas?.(true, true);
            },
        });
    }
    if (slot && slotName(slot) !== GROW) {
        options.push(null, {
            content: "Remove",
            className: "danger",
            callback: () => {
                if (kind === "in") node.removeInput(index);
                else node.removeOutput(index);
                ensureTail(node, kind);
                node.setDirtyCanvas?.(true, true);
            },
        });
    }
    return options;
}

// Slots carrying a name that nothing feeds and nothing reads. Wiring a hub is
// additive by design, so this is the only way a row leaves it besides the
// frontend's own "Remove Slot".
function dropUnusedSlots(node, kind) {
    const list = (kind === "in" ? node.inputs : node.outputs) ?? [];
    let removed = 0;
    for (let i = list.length - 1; i >= 0; i -= 1) {
        const slot = list[i];
        if (slotName(slot) === GROW) continue;
        const used = kind === "in" ? slot.link != null : !!slot.links?.length;
        if (used) continue;
        if (kind === "in") node.removeInput(i); else node.removeOutput(i);
        removed += 1;
    }
    ensureTail(node, kind);
    node.setDirtyCanvas?.(true, true);
    return removed;
}

// The tail has to be re-asserted outside the wire callbacks, because a slot
// removed through the frontend's own menu fires nothing this node can hear.
function assertTailOnDraw(node, kind) {
    const onDrawForeground = node.onDrawForeground;
    node.onDrawForeground = function () {
        if (!app.configuringGraph) {
            ensureTail(this, kind);
            if (kind === "in") {
                syncNameWidgets(this);
            } else {
                syncGroup(this);
                dropDeadNames(this);
            }
        }
        return onDrawForeground?.apply(this, arguments);
    };
}

// A Get slot whose name nothing publishes any more -- the Set it read was
// deleted, or the wire behind it was taken off. There is no value left for it
// to carry, so the slot goes, and the wire off it with it: that wire resolved
// to nothing already, and the run would have failed on a missing input.
//
// Two questions, and only one of them removes anything. A name nothing on the
// CANVAS publishes is gone: drop it. A name published somewhere this node's
// lookup cannot reach -- another subgraph -- still exists, so that slot is
// marked red and left alone. Deleting a slot over a lookup's blind spot would
// take his wiring with it.
export function dropDeadNames(node) {
    const scope = graphScope(node.graph, app.graph);
    const everywhere = everyGraph(app.graph);
    for (let i = (node.outputs?.length ?? 0) - 1; i >= 0; i -= 1) {
        const slot = node.outputs[i];
        const name = slotName(slot);
        if (!name || name === GROW) continue;
        if (findSource(scope, name)) {
            if (slot.color_on === DEAD) {
                delete slot.color_on;
                delete slot.color_off;
            }
            continue;
        }
        if (!findSource(everywhere, name)) {
            node.disconnectOutput?.(i);
            node.removeOutput(i);
            continue;
        }
        slot.color_on = DEAD;
        slot.color_off = DEAD;
    }
    ensureTail(node, "out");
}

registerSymbioticaExtension(app, {
    name: "symbiotica.set_get_hub",
    registerCustomNodes() {
        class SetHub extends LGraphNode {
            static title = "Set Hub";
            static category = "Symbiotica";

            constructor(title) {
                super(title);
                this.isVirtualNode = true;
                this.properties ??= {};
                this.properties["Node name for S&R"] = SET_HUB;
                this.addInput(GROW, ANY, { removable: true });
                assertTailOnDraw(this, "in");
            }

            onConnectionsChange(slotType, slot, isChangeConnect, linkInfo) {
                // Loading a graph restores slots wholesale; the side effects
                // here would rename them against a half-built canvas.
                if (app.configuringGraph) return;
                if (slotType !== LiteGraph.INPUT) return;
                if (isChangeConnect && linkInfo) adoptInput(this, slot, linkInfo);
                else if (!isChangeConnect) dropWhenUnwired(this, slot);
                ensureTail(this, "in");
                syncNameWidgets(this);
                this.setDirtyCanvas(true, true);
            }

            getSlotMenuOptions(slotInfo) {
                return slotMenu(this, "in", slotInfo, (index) => [{
                    content: "Rename…",
                    callback: () => renameSlot(this, "in", index),
                }]);
            }

            getExtraMenuOptions(_canvas, options) {
                options.push({
                    content: "Remove unused slots",
                    callback: () => {
                        const n = dropUnusedSlots(this, "in");
                        toast("info", "Set Hub",
                              n ? `${n} slot${n === 1 ? "" : "s"} removed.`
                                : "Every slot is wired.");
                    },
                });
                return options;
            }
        }
        LiteGraph.registerNodeType(SET_HUB, SetHub);
        // registerNodeType writes the category from the TYPE string it was
        // handed -- everything before the last "/", so an unslashed name lands
        // the node in "__frontend_only__" and its own `static category` is
        // overwritten. Putting the folder in the type string instead would put
        // it in what a saved workflow records as the node's identity, so the
        // category goes back on afterwards.
        SetHub.category = CATEGORY;

        class GetHub extends LGraphNode {
            static title = "Get Hub";
            static category = "Symbiotica";

            constructor(title) {
                super(title);
                this.isVirtualNode = true;
                this.properties ??= {};
                this.properties["Node name for S&R"] = GET_HUB;
                this.addOutput(GROW, ANY, { removable: true });
                // Nothing on the node said what it could pull: a name only
                // arrived by dragging a wire onto an input, so a Get Hub
                // sitting on its own read as empty and broken. This is the
                // list, on the node, always. The values are read live rather
                // than stored, because a name published a minute ago has to be
                // in it without the node having heard anything.
                //
                // The groups come first: a Set Hub holding six paths is one
                // pick here, and pulling its names one at a time is the work
                // this node exists to save.
                const options = {};
                Object.defineProperty(options, "values", {
                    get: () => {
                        const scope = graphScope(this.graph, app.graph);
                        const rows = publishedGroups(scope)
                            .map((group) => ({ label: groupLabel(group), group }));
                        for (const entry of publishedNames(scope)) {
                            rows.push({ label: entry.name, entry });
                        }
                        // Kept for the callback: a row is picked by the label
                        // the menu drew, and a group's label is not a name.
                        this._symPullRows = rows;
                        return rows.length ? rows.map((r) => r.label) : [NONE];
                    },
                    enumerable: true,
                    configurable: true,
                });
                const pull = this.addWidget("combo", "pull", PULL, (value) => {
                    pull.value = PULL;
                    if (!value || value === PULL || value === NONE) return;
                    const row = (this._symPullRows ?? [])
                        .find((r) => r.label === value);
                    if (row?.group) loadGroup(this, row.group);
                    else addGetSlot(this, String(row?.entry?.name ?? value));
                }, options);
                // The picker is a button, not a value: saving it would restore
                // a name into a node whose slots already say which they are.
                this.serialize_widgets = false;
                assertTailOnDraw(this, "out");
            }

            onConnectionsChange(slotType, slot, isChangeConnect, linkInfo) {
                if (app.configuringGraph) return;
                if (slotType !== LiteGraph.OUTPUT) return;
                const out = this.outputs?.[slot];
                // Only a wire off the empty slot asks a question: it is the
                // one that has no name yet.
                if (isChangeConnect && linkInfo && out && slotName(out) === GROW) {
                    const resolved = linkInfo.resolve?.(this.graph);
                    const target = resolved?.input
                        ?? this.graph?.getNodeById?.(linkInfo.target_id)
                            ?.inputs?.[linkInfo.target_slot];
                    pickName(this, slot, target?.type, (entry) => {
                        if (entry) assignGetSlot(this, slot, entry);
                        else this.disconnectOutput(slot);
                        ensureTail(this, "out");
                        this.setDirtyCanvas(true, true);
                    });
                    return;
                }
                ensureTail(this, "out");
                this.setDirtyCanvas(true, true);
            }

            // Same graph: hand back the link feeding the named slot, exactly
            // as the frontend expects — it resolves that link's TARGET (the
            // hub holding the name) and walks on from there.
            getInputLink(slot) {
                const name = slotName(this.outputs?.[slot]);
                if (!name || name === GROW) return null;
                const source = findSource([this.graph], name);
                if (!source) {
                    if (!findSource(graphScope(this.graph, app.graph), name)) {
                        toast("error", "Get Hub",
                              `Nothing on this canvas publishes "${name}".`);
                    }
                    return null;
                }
                const input = source.node.inputs?.[source.index];
                if (!input || input.link == null) {
                    toast("error", "Get Hub", `Nothing is wired into "${name}".`);
                    return null;
                }
                return getLink(this.graph, input.link);
            }

            // Across graphs the link ids mean nothing to the caller, so the
            // source node and slot go back instead.
            resolveVirtualOutput(slot) {
                const name = slotName(this.outputs?.[slot]);
                if (!name || name === GROW) return undefined;
                const source = findSource(graphScope(this.graph, app.graph), name);
                if (!source || source.graph === this.graph) return undefined;
                const input = source.node.inputs?.[source.index];
                if (!input || input.link == null) return undefined;
                const link = getLink(source.graph, input.link);
                const origin = source.graph.getNodeById?.(link?.origin_id);
                if (!origin) return undefined;
                return { node: origin, slot: link.origin_slot };
            }

            // A Get slot does not get a free-text name: it points at one that
            // exists, so the entry is the same list the `pull` widget shows.
            getSlotMenuOptions(slotInfo) {
                return slotMenu(this, "out", slotInfo, (index) => [{
                    content: "Point at…",
                    callback: () => pickName(this, index, null, (entry) => {
                        if (entry) assignGetSlot(this, index, entry);
                    }),
                }]);
            }

            getExtraMenuOptions(_canvas, options) {
                const group = String(this.properties?.[GROUP_PROP] ?? "").trim();
                if (group) {
                    options.push({
                        content: `Stop following "${group}"`,
                        callback: () => {
                            delete this.properties[GROUP_PROP];
                            delete this.properties[GROUP_ID_PROP];
                            toast("info", "Get Hub",
                                  `The slots stay; "${group}" no longer adds to them.`);
                            this.setDirtyCanvas(true, true);
                        },
                    });
                }
                options.push({
                    content: "Remove unused slots",
                    callback: () => {
                        // Curating the list by hand makes it yours: a hub that
                        // kept following would put every removed slot back on
                        // the next draw, and the menu row would read as broken.
                        const followed = group && this.properties[GROUP_PROP];
                        if (followed) {
                            delete this.properties[GROUP_PROP];
                            delete this.properties[GROUP_ID_PROP];
                        }
                        const n = dropUnusedSlots(this, "out");
                        toast("info", "Get Hub",
                              (n ? `${n} slot${n === 1 ? "" : "s"} removed.`
                                 : "Every slot is wired.")
                              + (followed ? ` "${group}" no longer adds to them.` : ""));
                    },
                });
                return options;
            }
        }
        LiteGraph.registerNodeType(GET_HUB, GetHub);
        GetHub.category = CATEGORY;
    },

    // A node registered on the canvas alone has no Python schema, so the
    // frontend invents one -- named after the class, described as "Frontend
    // only node". This is the hook that runs before those reach the node
    // library and the search box.
    beforeRegisterVueAppNodeDefs(defs) {
        for (const def of defs ?? []) {
            const name = TITLES[def?.name];
            if (!name) continue;
            def.display_name = name;
            def.category = CATEGORY;
            // The badge beside the row in the search box, which otherwise
            // reads "frontend_only" while every other node here says the pack.
            def.python_module = "custom_nodes.symbiotica";
            def.description = def.name === SET_HUB
                ? "Holds many named constants. Wire an output into its empty "
                  + "slot and the slot takes that name; a Get Hub reads it. "
                  + "Its title names the GROUP a Get Hub can take whole."
                : "Reads named constants. Pick a Set Hub's title to take its "
                  + "whole group at once, or drag from its empty slot onto an "
                  + "input and pick one name.";
        }
    },
});
