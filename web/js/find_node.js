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
const PULL = "add value or group…";
const NONE = "(nothing published on this canvas)";
// A Set Hub is a GROUP: its TITLE names the set of constants it holds, and a
// Get Hub can take the whole set in one pick. The groups a Get follows ride on
// `properties`, which serialises with the workflow and survives the node being
// retitled by hand.
//
// A LIST of them, because a pick ADDS: a hub carries a group AND a name off
// another group AND a value on its own, which is how a canvas actually reads
// -- six paths plus the one size you are testing against. Nothing a pick does
// takes a slot away.
const GROUP_PROP = "symbiotica_group";
// The Set Hubs those groups came from, in the same order. A title is what you
// read, but it is also what he retitles: the id is what carries a following
// Get across a rename.
const GROUP_ID_PROP = "symbiotica_group_id";
// A Get Hub told to pull everything: every name the canvas publishes, off Set
// Hubs and KJNodes Set nodes alike, followed the way a group is -- so a name
// published after the pick arrives too, and the hub stays fully loaded.
const ALL_PROP = "symbiotica_all";
// The last title this node wrote for itself. A title it still carries is one
// it may replace; anything else on the node is a title HE typed, and stays.
const TITLE_PROP = "symbiotica_title";
// A title the node wrote for itself, and may write over. What he typed is his.
export function setOwnTitle(node, title) {
    node.properties ??= {};
    const showing = String(node.title ?? "").trim();
    const mine = String(node.properties[TITLE_PROP] ?? "");
    if (showing && !STOCK_TITLES.has(showing) && showing !== mine) return false;
    if (showing === title) return false;
    node.title = title;
    node.properties[TITLE_PROP] = title;
    return true;
}

// The groups a Get Hub follows, as `{title, id}` pairs. Two parallel lists on
// the node, read as one here so they cannot fall out of step. A workflow saved
// when a hub could follow only one group holds a bare string, and reads as a
// list of one.
export function followed(node) {
    const props = node?.properties ?? {};
    const asList = (v) => (Array.isArray(v) ? v : [v]);
    const ids = asList(props[GROUP_ID_PROP]);
    const out = [];
    asList(props[GROUP_PROP]).forEach((raw, i) => {
        const title = String(raw ?? "").trim();
        const id = ids[i] ?? null;
        if (title || id != null) out.push({ title, id });
    });
    return out;
}

// Both lists at once, and both gone when nothing is followed: a node carrying
// an empty group list would read as following something.
export function setFollowed(node, list) {
    node.properties ??= {};
    if (!list.length) {
        delete node.properties[GROUP_PROP];
        delete node.properties[GROUP_ID_PROP];
        return;
    }
    node.properties[GROUP_PROP] = list.map((g) => g.title);
    node.properties[GROUP_ID_PROP] = list.map((g) => g.id ?? null);
}

export function followsAll(node) {
    return node?.properties?.[ALL_PROP] === true;
}

// Gone rather than `false` when off, like the group lists.
export function setFollowsAll(node, on) {
    node.properties ??= {};
    if (on) node.properties[ALL_PROP] = true;
    else delete node.properties[ALL_PROP];
}

// What a Get Hub is: everything, the groups it follows and how much it carries
// beside them, the one name it holds, or neither. The extras can only be
// counted against what the groups hold right now, so they are counted when the
// caller has already resolved them and left out when it has not.
export function titleForGet(node, groups = null) {
    if (followsAll(node)) return "Get all";
    const titles = followed(node).map((g) => g.title).filter(Boolean);
    const names = (node?.outputs ?? []).map(slotName)
        .filter((n) => n && n !== GROW);
    if (!titles.length) return names.length === 1 ? `Get ${names[0]}` : "Get Hub";
    const held = new Set((groups ?? []).flatMap((g) => g.names.map((e) => e.name)));
    const extra = groups ? names.filter((n) => !held.has(n)).length : 0;
    return `Get ${titles.join(" + ")}${extra ? ` +${extra}` : ""}`;
}

// How a group reads in the picker, beside the plain names.
const groupLabel = (group) => `${group.title}  ·  ${group.names.length} `
    + `name${group.names.length === 1 ? "" : "s"}`;
// The row above every group: all of them, and every plain Set node too.
export const allLabel = (count) => `pull all  ·  ${count} `
    + `name${count === 1 ? "" : "s"}`;
// The dot on a Get slot pointing at a name that is gone. This pack's danger
// colour, from hub_theme.
const DEAD = "#f2777a";
// One folder for the pack, as everything else here declares.
const CATEGORY = "Symbiotica";
const TITLES = {
    [SET_HUB]: "Set Hub (Symbiotica)",
    [GET_HUB]: "Get Hub (Symbiotica)",
};

// The titles a hub is born with, which name no group.
const STOCK_TITLES = new Set(["", "Set Hub", "Get Hub",
                              TITLES[SET_HUB], TITLES[GET_HUB]]);
// Which side of the pair you are looking at, kept at the front of the title so
// that a Set and the Get reading it are never two nodes with one name.
const SIDE = /^(set|get)\s+/i;

// The group a title names: the title without the word that says which side it
// is. `Set _paths` and `_paths` name the same group, and `Get _paths` reads it.
export function groupNameOf(title) {
    const clean = String(title ?? "").trim();
    if (STOCK_TITLES.has(clean)) return "";
    return clean.replace(SIDE, "").trim() || clean;
}

// A title he typed keeps the side in front of it. The stock titles already say
// it, and a title that says it once is left exactly as it is.
export function keepSideInTitle(node, side) {
    const title = String(node?.title ?? "").trim();
    if (!title || STOCK_TITLES.has(title) || SIDE.test(title)) return false;
    node.title = `${side} ${title}`;
    return true;
}

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
            out.push({ title: groupNameOf(node.title) || "Set Hub",
                       names, node, graph });
        }
    }
    return out;
}

// The groups a Get Hub is following, and what each holds now. A group whose
// Set Hub is gone is left out rather than dropped from the list -- the slots
// it put here stay either way, and `dropDeadNames` is what takes the ones
// behind them.
//
// A group's Set Hub ID answers before its title, so retitling a group carries
// every Get following it -- the same rule as renaming a slot. The title is
// healed on the way past, in what the node remembers and on the node itself,
// so the canvas never reads one name while the node holds another.
export function groupsOf(node, graphs) {
    const following = followed(node);
    if (!following.length) return [];
    const published = publishedGroups(graphs);
    const out = [];
    let healed = !Array.isArray(node?.properties?.[GROUP_PROP]);
    for (const want of following) {
        const byId = want.id == null ? null
            : published.find((g) => String(g.node?.id) === String(want.id));
        const group = byId ?? published.find((g) => g.title === want.title) ?? null;
        if (!group) continue;
        if (group.title !== want.title) {
            want.title = group.title;
            healed = true;
        }
        if (group.node?.id != null && String(group.node.id) !== String(want.id)) {
            want.id = group.node.id;
            healed = true;
        }
        out.push(group);
    }
    if (healed) {
        setFollowed(node, following);
        setOwnTitle(node, titleForGet(node, out));
    }
    return out;
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
        // Both halves: a slot whose `name` and `label` agree is one the WIRE
        // named, and it goes on following the node feeding it.
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

// A whole group, taken at once and ADDED to what the node already carries.
// Picking `settings-01` on a hub holding `paths` leaves it holding both, and
// the node follows both from then on. A pick never removes a slot and never
// cuts a wire: what leaves a Get Hub is what he takes off it, or a name that
// has left the canvas.
export function loadGroup(node, group) {
    if (!group) return;
    const following = followed(node);
    const id = group.node?.id ?? null;
    // Already followed: the pick is a re-assert, which adds any name the group
    // has grown since and is otherwise a no-op.
    const has = following.some((g) => (id != null && String(g.id) === String(id))
                                      || (!!g.title && g.title === group.title));
    if (!has) following.push({ title: group.title, id });
    setFollowed(node, following);
    const groups = groupsOf(node, graphScope(node.graph, app.graph));
    syncGroup(node, groups);
    setOwnTitle(node, titleForGet(node, groups));
    node.setDirtyCanvas?.(true, true);
}

// One name off the picker, added beside whatever the node holds. A hub
// following a group goes on following it -- a single name is the other half of
// what this picker is for: the six paths of a group, plus the one size you are
// testing against, on one node.
export function loadName(node, entry) {
    if (!entry) return;
    addGetSlot(node, entry.name);
    const groups = groupsOf(node, graphScope(node.graph, app.graph));
    setOwnTitle(node, titleForGet(node, groups));
    node.setDirtyCanvas?.(true, true);
}

// Every name the canvas publishes, added beside whatever the node holds and
// followed from then on. The groups it already follows stay followed, so
// stopping the pull leaves the node where it was before it.
export function loadAll(node) {
    setFollowsAll(node, true);
    const groups = groupsOf(node, graphScope(node.graph, app.graph));
    syncGroup(node, groups);
    setOwnTitle(node, titleForGet(node, groups));
    node.setDirtyCanvas?.(true, true);
}

// What following a group means, re-asserted on every draw: the Set Hub's names
// are all here. Asserted rather than copied once, because a group whose new
// third name never reaches the Gets is the stale copy this node exists to
// replace. Several groups is the same rule read over the union of them, and a
// name picked on its own is in none of them -- see the removal loop, which
// leaves any name the canvas still publishes exactly where it is. Pulling all
// is the same rule again, read over every name in scope.
export function syncGroup(node, groups = null) {
    const scope = graphScope(node.graph, app.graph);
    const following = groups ?? groupsOf(node, scope);
    const entries = following.flatMap((g) => g.names);
    if (followsAll(node)) entries.push(...publishedNames(scope));
    if (!entries.length) return false;
    const wanted = new Set(entries.map((e) => e.name));
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
    for (const entry of entries) {
        if (have.has(entry.name)) continue;
        // Appended, never inserted: a wire holds on to a slot's INDEX, so
        // making room in the middle would move every wire below it.
        ensureTail(node, "out");
        assignGetSlot(node, node.outputs.length - 1, entry);
        have.add(entry.name);
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
function renameTo(node, index, value, fromWire = false) {
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
    slot.label = name;
    // `name` keeps what the WIRE called the slot and `label` what it is called.
    // The two of them differing is the whole record that he took the name over
    // by hand -- and they are two of the eleven fields a slot saves, where
    // anything else hung on the slot would be dropped on the next reopen.
    if (fromWire) slot.name = name;
    repointGetters(was, name);
    node.setDirtyCanvas?.(true, true);
}

// A slot named after the node feeding it follows that node's name. He names
// the source -- `cats`, `water` -- and the slot IS that name, so retitling the
// source and leaving the slot behind would have the canvas saying two
// different things about one value. A slot he renamed himself is his and is
// left alone, and the Gets follow either way.
export function followWireNames(node) {
    for (const slot of [...(node.inputs ?? [])]) {
        const was = slotName(slot);
        if (slot.link == null || !was || was === GROW) continue;
        if (slot.name !== slot.label) continue;
        const link = getLink(node.graph, slot.link);
        if (!link) continue;
        const origin = originSlot(node.graph, link);
        const from = node.graph?.getNodeById?.(link.origin_id);
        const wanted = nameFromWire(origin,
            String(origin?.type ?? slot.type ?? ANY), from);
        // Only a real change of the source's name moves the slot. A slot
        // carrying the suffix a clash gave it -- STRING_3 off a wire that says
        // STRING -- is already following: recomputing it every draw would
        // shuffle names around the node as other names come and go.
        if (!wanted || was === wanted || was.replace(/_\d+$/, "") === wanted) continue;
        renameTo(node, namedSlots(node).indexOf(slot), wanted, true);
    }
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
export async function askForName(title, current) {
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
        slot.label = name;
        // An input's `name` is left holding what the wire called it: a name he
        // typed is his, and stops following the node feeding the slot.
        if (kind !== "in") slot.name = name;
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
            keepSideInTitle(this, kind === "in" ? "Set" : "Get");
            if (kind === "in") {
                followWireNames(this);
                syncNameWidgets(this);
            } else {
                const groups = groupsOf(this, graphScope(this.graph, app.graph));
                syncGroup(this, groups);
                dropDeadNames(this);
                setOwnTitle(this, titleForGet(this, groups));
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
                // this node exists to save. Above them, one pick for all of it.
                const options = {};
                Object.defineProperty(options, "values", {
                    get: () => {
                        const scope = graphScope(this.graph, app.graph);
                        const names = publishedNames(scope);
                        const rows = names.length
                            ? [{ label: allLabel(names.length), all: true }] : [];
                        for (const group of publishedGroups(scope)) {
                            rows.push({ label: groupLabel(group), group });
                        }
                        for (const entry of names) {
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
                    if (row?.all) loadAll(this);
                    else if (row?.group) loadGroup(this, row.group);
                    else if (row?.entry) loadName(this, row.entry);
                    else addGetSlot(this, String(value));
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
                const groups = followed(this).map((g) => g.title).filter(Boolean);
                const all = followsAll(this);
                if (all) {
                    options.push({
                        content: "Stop pulling all",
                        callback: () => {
                            setFollowsAll(this, false);
                            toast("info", "Get Hub",
                                  "The slots stay; new names no longer arrive.");
                            this.setDirtyCanvas(true, true);
                        },
                    });
                }
                // One row per group, because a hub can follow several: dropping
                // all of them to stop following one is the wiring he did not
                // ask to lose.
                for (const title of groups) {
                    options.push({
                        content: `Stop following "${title}"`,
                        callback: () => {
                            setFollowed(this, followed(this)
                                .filter((g) => g.title !== title));
                            toast("info", "Get Hub",
                                  `The slots stay; "${title}" no longer adds to them.`);
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
                        if (groups.length) setFollowed(this, []);
                        if (all) setFollowsAll(this, false);
                        const n = dropUnusedSlots(this, "out");
                        const stopped = [...groups.map((t) => `"${t}"`),
                                         ...(all ? ["pull all"] : [])];
                        toast("info", "Get Hub",
                              (n ? `${n} slot${n === 1 ? "" : "s"} removed.`
                                 : "Every slot is wired.")
                              + (stopped.length
                                 ? ` ${stopped.join(", ")} no longer `
                                   + `${stopped.length === 1 ? "adds" : "add"} to them.`
                                 : ""));
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
                : "Reads named constants. Every pick ADDS: take a Set Hub's "
                  + "whole group by its title, then a name off another group "
                  + "or a value on its own beside it.";
        }
    },
});

// ================================================================ Arrange ==

// Why this exists: his canvas is 119 nodes in 13 groups he drew himself, and
// the mess is not the grouping — 104 of those nodes are already in exactly one
// group, none in two, and 96 of the 128 wires never leave the group they start
// in. The mess is geometry: 91 pairs of nodes overlapping each other, 32 nodes
// hanging outside the box they belong to, and boxes too small to hold what is
// in them. So this lays out INSIDE the groups he has and never re-clusters,
// never renames.
//
// It moves the boxes too, and that was not the first plan. Keeping every box
// where it was and only tidying its insides is safer on paper, and it was
// tried against his real file first: a group laid out properly needs MORE room
// than one whose nodes overlap, his groups sit tens of pixels apart, so nine
// of the thirteen had to be skipped to stop a grown box covering its
// neighbour's nodes. A tidy that declines two thirds of the canvas is not a
// tidy. Moving the boxes is what makes the room.
//
// Which runs straight into rgthree. Its Fast Groups Muter/Bypasser reads its
// row order off group POSITION — `floor(y/30)` then `floor(x/30)` — so moving
// groups reshuffles the rows he clicks, and two of his three carry
// `toggleRestriction: "always one"`, where the wrong row is a different
// render. `shelfPack` is the answer: boxes go onto shelves, left to right,
// every box on a shelf sharing one top edge, in the order the rows are in now.
// Shelf-mates then share `floor(y/30)` with ascending x, and a later shelf is
// strictly greater, so the order reads back identical BY CONSTRUCTION rather
// than by a check that hopes.
//
// And the reason this is not an install. Every tool that already does layout
// for ComfyUI — phazei's Enhancement-Utils, and pysssss's own two Arrange rows
// sitting in this very menu — builds its edge list from `graph.links`, where
// his Set/Get pairs do not appear. That reads his root graph as 21
// disconnected islands instead of 8 and gutters half of it. `arrangeEdges`
// hops the pair, which is the one piece none of them can be handed.

const ARRANGE_ID = "Symbiotica.ArrangeWorkflow";
const RESTORE_ID = "Symbiotica.RestoreLayout";
const STACK_ID = "Symbiotica.StackAndAlign";
const ARRANGE_LABEL = "Arrange workflow (Symbiotica)";
const RESTORE_LABEL = "Restore previous layout (Symbiotica)";
const STACK_LABEL = "Stack and align (Symbiotica)";

// `(Symbiotica)` rides in the label because pysssss's Custom Scripts already
// puts "Arrange (float left)" and "Arrange (float right)" on this same menu,
// and both of those are group-blind: one click flattens all 13 of his groups.
// A row that cannot be told apart from that one is a trap, not a feature.
const ARRANGE_COMBO = { key: "9", ctrl: true, alt: false, shift: true };
// Shift+A, not a bare letter: the keybinding store keys the full modifier set,
// so this does not collide with anything bound to `a`.
const STACK_COMBO = { key: "a", ctrl: false, alt: false, shift: true };

// Where the undo snapshot lives. `graph.extra` serialises with the workflow,
// which is the point: `Comfy.Workflow.AutoSave` is "after delay" on his
// install, so the new layout is on disk about a second after the click, and
// the frontend's own undo at this scale is a full `loadGraphData` that tears
// down and rebuilds every DOM panel this pack draws.
const UNDO_KEY = "symbiotica_arrange_undo";

const LAYER_GAP = 120;   // between one column of nodes and the next
const ROW_GAP = 40;      // between two nodes stacked in the same column
const RAIL_GAP = 60;     // between the last column and the preview rail
const BOX_PAD = 30;      // inside a group box, left/right/bottom
const TITLE_PAD = 60;    // the group's title bar, above its contents
const SHELF_GAP_X = 200; // between two boxes on a shelf
const SHELF_GAP_Y = 250; // between one shelf and the next

// Nodes that end a branch and are read, not wired onward. Parked on a rail
// down the right edge of their group at their producer's height instead of
// taking a column of their own: 50 of the 105 overlapping pairs on his canvas
// involve one of these.
const PREVIEW_TYPES = new Set([
    "PreviewImage", "PreviewAny", "SaveImage", "PreviewVideo", "PreviewAudio",
    "SaveAnimatedWEBP", "SaveAnimatedPNG", "Image Comparer (rgthree)",
    "ShowText|pysssss", "PreviewMask", "SaveVideo", "PreviewText",
]);

// Never laid out into a group, decided by TYPE and not by geometry. His
// bypasser 3818 sits at y −5830..−5700 and `edit-sketch` starts at exactly
// −5700 — flush, so `containsCentre` adopts it, and it would be laid out into
// the group it is the control panel FOR. It still RIDES with that group when
// the box moves, at the offset it has now.
const NEVER_GROUPED = new Set([
    "Fast Groups Muter (rgthree)", "Fast Groups Bypasser (rgthree)",
    "Fast Bypasser (rgthree)", "Fast Muter (rgthree)", "Note", "MarkdownNote",
]);

// ---------------------------------------------------------------- geometry --

export function snapValue(value, grid) {
    return grid > 0 ? Math.round(value / grid) * grid : value;
}

function snapUp(value, grid) {
    return grid > 0 ? Math.ceil(value / grid) * grid : value;
}

function overlaps(a, b) {
    return a.x < b.x + b.w && b.x < a.x + a.w
        && a.y < b.y + b.h && b.y < a.y + a.h;
}

// What the node actually occupies on screen, which is not `pos` and `size`.
// `boundingRect` includes the title bar and is the only thing that reads a
// COLLAPSED node right — 34 of his 119 are collapsed Set/Get, drawn as a title
// bar of about 210×30 while `size` still says 300×100. It is a per-frame cache
// rather than a getter, so `updateArea` has to run first, and reading it back
// after a `pos` write hands you the stale box.
export function measureNode(node, ctx) {
    try { node.updateArea?.(ctx); } catch { /* stub canvas, fall through */ }
    const pos = node.pos ?? [0, 0];
    const rect = node.boundingRect;
    if (rect && rect.length >= 4 && (rect[2] > 0 || rect[3] > 0)) {
        return {
            id: node.id, node,
            x: rect[0], y: rect[1], w: rect[2], h: rect[3],
            // Kept so a placement can be written back through `pos`, which
            // points at the body's top-left, not the box's.
            ox: pos[0] - rect[0], oy: pos[1] - rect[1],
        };
    }
    const size = node.size ?? [200, 100];
    const title = node.constructor?.title_height ?? 30;
    const collapsed = !!node.flags?.collapsed;
    return {
        id: node.id, node,
        x: pos[0], y: pos[1] - title,
        w: collapsed ? 80 : size[0],
        h: (collapsed ? 0 : size[1]) + title,
        ox: 0, oy: title,
    };
}

// --------------------------------------------------------------- the edges --

function realEdges(graph) {
    const out = [];
    for (const node of nodesOf(graph)) {
        for (const input of node.inputs ?? []) {
            const link = getLink(graph, input.link);
            if (!link || link.origin_id == null) continue;
            out.push([link.origin_id, node.id]);
        }
    }
    return out;
}

// The wires that are not in the links table: a Get reading a name a Set
// publishes. `findSource` already resolves both shapes — KJNodes' SetNode,
// whose name is its widget, and this pack's Set Hub, whose names are its input
// SLOT LABELS, one per Get Hub output. Only pairs that are both on this graph
// become an edge; a Set on the root feeding a Get inside a subgraph is a real
// dependency but not one this layout can express.
export function arrangeEdges(graph, root) {
    const out = realEdges(graph);
    const scope = graphScope(graph, root);
    const here = new Set(nodesOf(graph).map((n) => n.id));
    const link = (source, node) => {
        const from = source?.node;
        if (!from || from.id == null || !here.has(from.id)) return;
        if (from.id === node.id) return;
        out.push([from.id, node.id]);
    };
    for (const node of nodesOf(graph)) {
        const type = String(node.type ?? "");
        if (type === GET_HUB) {
            for (const slot of node.outputs ?? []) {
                const name = slotName(slot);
                if (!name || name === GROW) continue;
                link(findSource(scope, name), node);
            }
        } else if (type === "GetNode") {
            const name = String(node.widgets?.[0]?.value ?? "").trim();
            if (name) link(findSource(scope, name), node);
        }
    }
    return out;
}

// ---------------------------------------------------------------- layering --

// Longest-path layering. A node sits one column to the right of everything
// that feeds it. Kahn rather than a recursive walk because a subgraph can hold
// a cycle: whatever does not resolve is parked in a column of its own on the
// right instead of hanging the layout.
export function assignLayers(ids, edges) {
    const present = new Set(ids);
    const next = new Map();
    const indeg = new Map();
    const layer = new Map();
    for (const id of ids) { next.set(id, []); indeg.set(id, 0); layer.set(id, 0); }
    const seen = new Set();
    for (const [from, to] of edges) {
        if (from === to || !present.has(from) || !present.has(to)) continue;
        const key = `${from}\u0000${to}`;
        if (seen.has(key)) continue;
        seen.add(key);
        next.get(from).push(to);
        indeg.set(to, indeg.get(to) + 1);
    }
    const queue = ids.filter((id) => indeg.get(id) === 0);
    for (let head = 0; head < queue.length; head++) {
        const id = queue[head];
        for (const to of next.get(id)) {
            layer.set(to, Math.max(layer.get(to), layer.get(id) + 1));
            indeg.set(to, indeg.get(to) - 1);
            if (indeg.get(to) === 0) queue.push(to);
        }
    }
    const resolved = new Set(queue);
    let last = 0;
    for (const id of resolved) last = Math.max(last, layer.get(id));
    for (const id of ids) if (!resolved.has(id)) layer.set(id, last + 1);
    return layer;
}

// Barycenter ordering, SEEDED FROM WHERE THE NODES ARE NOW. That seed is what
// makes the result recognisable as his workflow rather than a fresh drawing of
// the same graph, and what makes a second press move nothing.
export function orderLayers(layerOf, edges, seedY, sweeps = 8) {
    let last = 0;
    for (const v of layerOf.values()) last = Math.max(last, v);
    const layers = [];
    for (let i = 0; i <= last; i++) layers.push([]);
    for (const [id, layer] of layerOf) layers[layer].push(id);
    const seed = (id) => seedY.get(id) ?? 0;
    for (const layer of layers) {
        layer.sort((a, b) => seed(a) - seed(b) || String(a).localeCompare(String(b)));
    }

    const up = new Map();
    const down = new Map();
    for (const [from, to] of edges) {
        if (!layerOf.has(from) || !layerOf.has(to)) continue;
        if (!up.has(to)) up.set(to, []);
        if (!down.has(from)) down.set(from, []);
        up.get(to).push(from);
        down.get(from).push(to);
    }

    for (let sweep = 0; sweep < sweeps; sweep++) {
        const forward = sweep % 2 === 0;
        const order = forward
            ? layers.map((_, i) => i).slice(1)
            : layers.map((_, i) => i).slice(0, -1).reverse();
        for (const i of order) {
            const ref = new Map();
            layers[forward ? i - 1 : i + 1].forEach((id, k) => ref.set(id, k));
            const rank = new Map();
            layers[i].forEach((id, k) => rank.set(id, k));
            const bary = new Map();
            for (const id of layers[i]) {
                const near = (forward ? up.get(id) : down.get(id)) ?? [];
                const ranks = near.map((n) => ref.get(n)).filter((v) => v != null);
                // A node with nothing in the neighbouring column keeps the
                // place it has. Sorting it to 0 drags every loose node to the
                // top of every column.
                bary.set(id, ranks.length
                    ? ranks.reduce((a, b) => a + b, 0) / ranks.length
                    : rank.get(id));
            }
            layers[i].sort((a, b) => bary.get(a) - bary.get(b)
                || rank.get(a) - rank.get(b));
        }
    }
    return layers;
}

// ------------------------------------------------------------ the layout ----

// Lays one group's nodes out relative to (0,0) and answers where each one goes
// plus how big its box has to be. Pure over plain boxes, so the tests never
// need a canvas.
export function tidyLayout(boxes, edges, opts = {}) {
    const {
        layerGap = LAYER_GAP, rowGap = ROW_GAP, railGap = RAIL_GAP, grid = 0,
    } = opts;
    const places = new Map();
    if (!boxes.length) return { places, width: 0, height: 0 };

    const byId = new Map(boxes.map((b) => [b.id, b]));
    const feeds = new Set();
    for (const [from, to] of edges) {
        if (byId.has(from) && byId.has(to)) feeds.add(from);
    }
    // A preview earns the rail only if nothing downstream reads it. One wired
    // onward is a node in the flow like any other.
    const rail = boxes.filter((b) => b.preview && !feeds.has(b.id));
    const railIds = new Set(rail.map((b) => b.id));
    const flow = boxes.filter((b) => !railIds.has(b.id));

    if (!flow.length) {
        let y = 0;
        for (const b of rail) {
            places.set(b.id, { x: 0, y });
            y += snapUp(b.h + rowGap, grid);
        }
        return {
            places,
            width: Math.max(0, ...rail.map((b) => b.w)),
            height: Math.max(0, y - rowGap),
        };
    }

    const ids = flow.map((b) => b.id);
    const inner = edges.filter(([f, t]) => !railIds.has(f) && !railIds.has(t));
    const layerOf = assignLayers(ids, inner);
    const seedY = new Map(flow.map((b) => [b.id, b.y]));
    const layers = orderLayers(layerOf, inner, seedY);

    const colH = layers.map((layer) => layer.reduce(
        (sum, id) => sum + byId.get(id).h + rowGap, 0) - rowGap);
    const tallest = Math.max(0, ...colH);

    let x = 0;
    layers.forEach((layer, i) => {
        // Columns centred against each other: a two-node column beside a
        // ten-node one reads as part of the same flow rather than as a
        // fragment stuck to the top.
        let y = snapValue((tallest - colH[i]) / 2, grid);
        for (const id of layer) {
            places.set(id, { x, y });
            // A WHOLE number of grid steps, never the raw gap. At his grid of
            // 100 a 40 px gutter rounds away and the two nodes it separated
            // end up touching — which the overlap check then refuses, so the
            // press did nothing at all on the one canvas it was written for.
            y += snapUp(byId.get(id).h + rowGap, grid);
        }
        x += snapUp(Math.max(0, ...layer.map((id) => byId.get(id).w)) + layerGap, grid);
    });

    let width = Math.max(0, ...flow.map((b) => places.get(b.id).x + b.w));
    let height = Math.max(0, ...flow.map((b) => places.get(b.id).y + b.h));

    if (rail.length) {
        // Each preview sits at the height of whatever feeds it, and slides
        // down only as far as the one above it forces.
        const producerY = (id) => {
            for (const [from, to] of edges) {
                if (to === id && places.has(from)) return places.get(from).y;
            }
            return Number.MAX_SAFE_INTEGER;
        };
        const ordered = rail
            .map((b) => ({ b, at: producerY(b.id) }))
            .sort((p, q) => p.at - q.at || String(p.b.id).localeCompare(String(q.b.id)));
        const railX = snapUp(width + railGap, grid);
        let floor = 0;
        for (const { b, at } of ordered) {
            const y = snapValue(
                Math.max(floor, at === Number.MAX_SAFE_INTEGER ? floor : at), grid);
            places.set(b.id, { x: railX, y });
            floor = y + snapUp(b.h + rowGap, grid);
            width = Math.max(width, railX + b.w);
            height = Math.max(height, y + b.h);
        }
    }
    return { places, width, height };
}

// ------------------------------------------------------------ the shelves ---

// Boxes onto shelves, IN THE ORDER THEY ARRIVE, which is the order rgthree
// reads them in now. Left to right, every box on a shelf sharing one top edge,
// a new shelf once the row runs past `maxWidth`.
//
// This is the whole guarantee, and it is arithmetic rather than a check that
// hopes: shelf-mates share a `y` so their `floor(y/30)` is equal and their `x`
// ascends; a later shelf starts at least `SHELF_GAP_Y` lower, which is more
// than 30, so its `floor(y/30)` is strictly greater. Read back through
// rgthree's own key the order is the one that went in.
export function shelfPack(items, opts = {}) {
    const { gapX = SHELF_GAP_X, gapY = SHELF_GAP_Y, grid = 0 } = opts;
    const widest = Math.max(0, ...items.map((i) => i.w));
    const area = items.reduce((sum, i) => sum + i.w * i.h, 0);
    // Wide enough that the shelves read as a row of stages, not a tower, and
    // derived from the boxes alone so a second press packs the same way.
    const maxWidth = Math.max(widest, Math.round(Math.sqrt(area) * 1.6));
    const out = [];
    let x = 0;
    let y = 0;
    let shelf = 0;
    for (const item of items) {
        if (x > 0 && x + item.w > maxWidth) {
            x = 0;
            y += snapUp(shelf + gapY, grid || 1);
            shelf = 0;
        }
        out.push({ key: item.key, x, y, w: item.w, h: item.h });
        x += snapUp(item.w + gapX, grid || 1);
        shelf = Math.max(shelf, item.h);
    }
    return out;
}

// --------------------------------------------------------------- the plan ---

// rgthree's own sort key, so the order a pack has to preserve is read the way
// the node that cares about it reads it.
function rowKey(group) {
    return [Math.floor(group.pos[1] / 30), Math.floor(group.pos[0] / 30)];
}

export function rowOrder(groups) {
    return [...groups]
        .map((group) => ({ group, key: rowKey(group) }))
        .sort((a, b) => a.key[0] - b.key[0] || a.key[1] - b.key[1])
        .map((row) => row.group);
}

// Everything the press would do, as numbers, with nothing written. The checks
// run on this, and a refusal leaves the canvas untouched — there is no
// half-moved graph to undo.
export function planArrange(graph, root, opts = {}) {
    const { ctx = null, grid = 0, pack = true } = opts;
    const groups = [...(graph?.groups ?? graph?._groups ?? [])];
    const boxes = new Map();
    for (const node of nodesOf(graph)) boxes.set(node.id, measureNode(node, ctx));
    const edges = arrangeEdges(graph, root ?? graph);

    // Membership is frozen HERE and used as an input from here on.
    // `recomputeInsideNodes` sorts `graph.groups` in place, so a group is
    // remembered by identity, never by index.
    const owner = new Map();
    for (const group of groups) {
        try { group.recomputeInsideNodes?.(); } catch { /* older shapes */ }
        for (const node of group.nodes ?? group._nodes ?? []) {
            if (boxes.has(node.id)) owner.set(node.id, group);
        }
    }

    // Each group laid out against its own origin, and how big that makes it.
    const inner = new Map();
    for (const group of groups) {
        const held = (group.nodes ?? group._nodes ?? [])
            .filter((n) => n && boxes.has(n.id));
        const members = held.filter((node) => !node.pinned
            && !NEVER_GROUPED.has(String(node.type ?? "")));
        const input = members.map((node) => ({
            ...boxes.get(node.id),
            preview: PREVIEW_TYPES.has(String(node.type ?? "")),
        }));
        const laid = group.pinned || members.length < 2
            ? { places: new Map(), width: 0, height: 0 }
            : tidyLayout(input, edges, { grid });

        // A node this pass does not lay out — the group muter sitting over the
        // box, a Note — gets a strip of its own down the LEFT of the group
        // rather than the offset it happens to have now. Keeping the offset
        // was tried against his file: the layout moves out from under it and
        // his `Fast Bypasser` 4343 came to rest on top of two nodes.
        const riders = held.filter((node) => !laid.places.has(node.id));
        const strip = Math.max(0, ...riders.map((n) => boxes.get(n.id).w));
        const shift = strip ? snapUp(strip + LAYER_GAP, grid) : 0;
        const pad = snapUp(BOX_PAD, grid);
        const head = snapUp(TITLE_PAD, grid);
        const rides = [];
        let at = head;
        for (const node of riders) {
            const box = boxes.get(node.id);
            rides.push({ node, box, dx: pad, dy: at });
            at += snapUp(box.h + ROW_GAP, grid);
        }
        let right = shift + laid.width + pad;
        let bottom = Math.max(at, laid.height + head);
        // Measured off the SNAPPED placements, so rounding a node onto the
        // grid can never end past the box's edge.
        for (const box of input) {
            const place = laid.places.get(box.id);
            if (!place) continue;
            right = Math.max(right, pad + shift + place.x + box.w);
            bottom = Math.max(bottom, head + place.y + box.h);
        }
        inner.set(group, {
            laid, input, rides, shift, pad, head,
            size: [Math.max(140, snapUp(right + pad, grid)),
                   Math.max(80, snapUp(bottom + pad, grid))],
        });
    }

    // The boxes onto shelves, in the order rgthree reads them now. A pinned
    // group is not packed — it keeps its place, and its row key with it.
    const ordered = rowOrder(groups);
    const movable = ordered.filter((group) => !group.pinned);
    const anchor = [Math.min(...groups.map((g) => g.pos[0])),
                    Math.min(...groups.map((g) => g.pos[1]))];
    const packed = new Map();
    if (pack && movable.length) {
        const shelved = shelfPack(
            movable.map((group) => ({ key: group, ...boxOf(inner, group) })),
            { grid });
        for (const slot of shelved) {
            packed.set(slot.key, [snapValue(anchor[0] + slot.x, grid),
                                  snapValue(anchor[1] + slot.y, grid)]);
        }
    }
    const originOf = (group) => packed.get(group) ?? [group.pos[0], group.pos[1]];

    const moves = [];
    const resized = [];
    for (const group of groups) {
        const cell = inner.get(group);
        const [gx, gy] = originOf(group);
        for (const box of cell.input) {
            const at = cell.laid.places.get(box.id);
            if (!at) continue;
            moves.push(place(box.node, box.id, group, box,
                             gx + cell.pad + cell.shift + at.x,
                             gy + cell.head + at.y, grid));
        }
        for (const ride of cell.rides) {
            moves.push(place(ride.node, ride.node.id, group, ride.box,
                             gx + ride.dx, gy + ride.dy, grid, true));
        }
        resized.push({ group, pos: [gx, gy], size: cell.size });
    }

    // The nodes in no group at all — his control head, a stray Get, the Seed,
    // a Note — move as ONE BLOCK to a band above the first shelf, keeping the
    // positions they have relative to each other. They cannot be left where
    // they are: a box that packs onto that spot would adopt them, and
    // membership is what his group togglers switch.
    const loose = [...boxes.values()].filter((b) => !owner.has(b.id));
    if (loose.length && resized.length) {
        const top = Math.min(...resized.map((r) => r.pos[1]));
        const left = Math.min(...resized.map((r) => r.pos[0]));
        const was = {
            x: Math.min(...loose.map((b) => b.x)),
            y: Math.min(...loose.map((b) => b.y)),
            bottom: Math.max(...loose.map((b) => b.y + b.h)),
        };
        const dx = left - was.x;
        const dy = top - SHELF_GAP_Y - was.bottom;
        for (const box of loose) {
            moves.push(place(box.node, box.id, null, box,
                             box.x + dx, box.y + dy, grid, true));
        }
    }

    const touched = moves.filter((m) => m.px !== m.box.x + m.box.ox
        || m.py !== m.box.y + m.box.oy).length;
    return { moves, resized, owner, boxes, edges, touched,
             groups: groups.length };
}

// One placement. The node's POS is what lands on the grid, not its bounding
// box: pos sits below the title bar, so snapping the box leaves pos at an
// offset — and every one of the 119 positions in his file is a multiple of
// 100. `x`/`y` stay the bounding coordinates, which is what the checks read.
function place(node, id, group, box, atX, atY, grid, riding = false) {
    const px = snapValue(atX + box.ox, grid);
    const py = snapValue(atY + box.oy, grid);
    return { node, id, group, box, riding,
             px, py, x: px - box.ox, y: py - box.oy };
}

function boxOf(inner, group) {
    const size = inner.get(group)?.size ?? group.size;
    return { w: size[0], h: size[1] };
}

// Four questions asked of the plan rather than of the canvas.
export function checkArrange(plan) {
    const problems = [];
    const warnings = [];

    const placed = plan.moves.map((m) => ({
        id: m.id, x: m.x, y: m.y, w: m.box.w, h: m.box.h, group: m.group,
    }));
    let collisions = 0;
    for (let i = 0; i < placed.length; i++) {
        for (let j = i + 1; j < placed.length; j++) {
            if (placed[i].group && placed[i].group === placed[j].group
                && overlaps(placed[i], placed[j])) collisions++;
        }
    }
    if (collisions) problems.push(`${collisions} nodes would still overlap`);

    // Membership is `containsCentre` and 36 of his nodes are muted or
    // bypassed, so a node drifting between groups changes what runs.
    const boxes = plan.resized.map(({ group, pos, size }) => ({
        group, x: pos[0], y: pos[1], w: size[0], h: size[1],
    }));
    // Every node, not just the ones that move: a node standing still while a
    // box packs on top of it changes group just as surely.
    const moved = new Map(plan.moves.map((m) => [m.id, m]));
    for (const [id, box] of plan.boxes ?? []) {
        const move = moved.get(id);
        const cx = (move ? move.x : box.x) + box.w / 2;
        const cy = (move ? move.y : box.y) + box.h / 2;
        const holder = boxes.find(({ x, y, w, h }) =>
            cx > x && cx < x + w && cy > y && cy < y + h);
        const was = plan.owner.get(id) ?? null;
        if ((holder?.group ?? null) !== was) {
            problems.push(`node ${id} would change group`);
            break;
        }
    }

    for (let i = 0; i < boxes.length; i++) {
        for (let j = i + 1; j < boxes.length; j++) {
            if (overlaps(boxes[i], boxes[j])) {
                problems.push(`"${boxes[i].group.title}" would sit on `
                    + `"${boxes[j].group.title}"`);
                break;
            }
        }
        if (problems.length) break;
    }

    // The one rgthree cares about, checked as rgthree reads it.
    const before = plan.resized.map(({ group }) => group);
    const after = [...plan.resized]
        .sort((a, b) => Math.floor(a.pos[1] / 30) - Math.floor(b.pos[1] / 30)
            || Math.floor(a.pos[0] / 30) - Math.floor(b.pos[0] / 30))
        .map(({ group }) => group);
    const was = rowOrder(before);
    if (was.length !== after.length || was.some((g, i) => g !== after[i])) {
        problems.push("the group toggler rows would be reordered");
    }
    return { problems, warnings };
}

// ------------------------------------------------------------ stack + align --

// One selection, one key. The axis comes from the selection's OWN spread, so
// there is nothing to choose: nodes strung out down the canvas stack into a
// column, nodes strung out across it into a row.
export function stackPlan(boxes, opts = {}) {
    const { grid = 0, gutter = ROW_GAP } = opts;
    const places = new Map();
    const widths = new Map();
    const live = boxes.filter((b) => !b.pinned);
    if (live.length < 2) return { places, widths, axis: null };

    const cx = live.map((b) => b.x + b.w / 2);
    const cy = live.map((b) => b.y + b.h / 2);
    const column = (Math.max(...cy) - Math.min(...cy))
        >= (Math.max(...cx) - Math.min(...cx));

    const order = [...live].sort(column
        ? (a, b) => a.y - b.y || a.x - b.x
        : (a, b) => a.x - b.x || a.y - b.y);

    // Placements come out in POS coordinates, snapped there. `pos` sits below
    // the title bar, so snapping the bounding box leaves pos at an offset —
    // and pos is what his canvas keeps on the grid.
    const put = (box, x, y) => places.set(box.id, {
        x: snapValue(x + (box.ox ?? 0), grid) - (box.ox ?? 0),
        y: snapValue(y + (box.oy ?? 0), grid) - (box.oy ?? 0),
    });

    if (column) {
        const x = snapValue(Math.min(...live.map((b) => b.x)), grid);
        // Width matched to the widest, but never onto a collapsed node (its
        // drawn width is its title) and never onto a node carrying a DOM
        // panel — writing a panel's box is this repo's most expensive bug.
        const fixed = live.filter((b) => !b.collapsed && !b.panel);
        const wide = fixed.length ? snapUp(Math.max(...fixed.map((b) => b.w)), grid) : 0;
        let y = snapValue(Math.min(...live.map((b) => b.y)), grid);
        for (const box of order) {
            put(box, x, y);
            const w = box.collapsed || box.panel ? box.w : wide;
            if (w && w !== box.w) widths.set(box.id, w);
            y += snapUp(box.h + gutter, grid);
        }
    } else {
        const y = snapValue(Math.min(...live.map((b) => b.y)), grid);
        let x = snapValue(Math.min(...live.map((b) => b.x)), grid);
        for (const box of order) {
            put(box, x, y);
            x += snapUp(box.w + gutter, grid);
        }
    }
    return { places, widths, axis: column ? "column" : "row" };
}

// ------------------------------------------------------------ the commands --

function canvasCtx() {
    try { return app.canvas?.canvas?.getContext?.("2d") ?? null; } catch { return null; }
}

function gridSize(graph) {
    try {
        const size = graph?.getSnapToGridSize?.() ?? app.graph?.getSnapToGridSize?.();
        return Number.isFinite(size) && size > 0 ? size : 0;
    } catch { return 0; }
}

function rootGraph() {
    return app.graph?.rootGraph ?? app.graph ?? null;
}

// One undo step for the whole move. The bracket is what makes the frontend's
// Ctrl+Z see a single change rather than two hundred.
function commit(graph, write) {
    const canvas = app.canvas;
    try {
        canvas?.emitBeforeChange?.();
        graph?.beforeChange?.();
        write();
    } finally {
        graph?.afterChange?.();
        canvas?.emitAfterChange?.();
        canvas?.setDirty?.(true, true);
        canvas?.setDirtyCanvas?.(true, true);
    }
}

function snapshot(graph, plan) {
    graph.extra ??= {};
    graph.extra[UNDO_KEY] = {
        nodes: plan.moves.map((m) => [m.id, m.node.pos[0], m.node.pos[1]]),
        // By group ID, never by index: `recomputeInsideNodes` sorts
        // `graph.groups` in place, so the index a snapshot was taken at is not
        // the index it would be read back at.
        groups: plan.resized.map(({ group }) => [
            group.id, group.pos[0], group.pos[1], group.size[0], group.size[1],
        ]),
    };
}

function runArrange() {
    const graph = app.canvas?.graph ?? app.graph;
    if (!graph) return;
    const grid = gridSize(graph);
    const plan = planArrange(graph, rootGraph(), { ctx: canvasCtx(), grid });
    if (!plan.groups) {
        toast("warn", ARRANGE_LABEL, "This graph has no groups to arrange.");
        return;
    }
    const { problems } = checkArrange(plan);
    if (problems.length) {
        toast("error", ARRANGE_LABEL,
              `Nothing moved — ${problems.slice(0, 2).join("; ")}.`);
        return;
    }
    if (!plan.touched) {
        toast("info", ARRANGE_LABEL, "Already arranged — nothing moved.");
        return;
    }
    commit(graph, () => {
        // Only when something actually moves. A second press that changes
        // nothing must not overwrite the snapshot with the arranged layout,
        // or the way back is gone.
        snapshot(graph, plan);
        for (const { group, pos, size } of plan.resized) {
            group.pos = pos;
            group.size = size;
        }
        for (const move of plan.moves) move.node.pos = [move.px, move.py];
        for (const group of graph.groups ?? []) group.recomputeInsideNodes?.();
    });
    toast("success", ARRANGE_LABEL,
          `${plan.groups} groups · ${plan.touched} nodes moved`, 6000);
}

function runRestore() {
    const graph = app.canvas?.graph ?? app.graph;
    const saved = graph?.extra?.[UNDO_KEY];
    if (!saved?.nodes?.length) {
        toast("warn", RESTORE_LABEL, "Nothing to restore on this graph.");
        return;
    }
    const groups = graph.groups ?? graph._groups ?? [];
    commit(graph, () => {
        for (const [id, x, y, w, h] of saved.groups ?? []) {
            const group = groups.find((g) => g.id === id);
            if (!group) continue;
            group.pos = [x, y];
            group.size = [w, h];
        }
        for (const [id, x, y] of saved.nodes) {
            const node = graph.getNodeById?.(id) ?? graph.getNodeById?.(Number(id));
            if (node) node.pos = [x, y];
        }
        for (const group of groups) group.recomputeInsideNodes?.();
        delete graph.extra[UNDO_KEY];
    });
    toast("success", RESTORE_LABEL, `${saved.nodes.length} nodes put back.`);
}

// What the key acts on, in order: what is selected, then the nodes of a
// selected group, then the group under the pointer.
function stackTarget(graph) {
    const canvas = app.canvas;
    const selected = Object.values(canvas?.selected_nodes ?? {});
    if (selected.length >= 2) return selected;
    const items = [...(canvas?.selectedItems ?? [])];
    const group = items.find((item) => item?.recomputeInsideNodes);
    if (group) {
        group.recomputeInsideNodes();
        return [...(group.nodes ?? [])];
    }
    const at = canvas?.graph_mouse;
    const under = at ? graph?.getGroupOnPos?.(at[0], at[1]) : null;
    if (under) {
        under.recomputeInsideNodes?.();
        return [...(under.nodes ?? [])];
    }
    return selected;
}

function runStack() {
    const graph = app.canvas?.graph ?? app.graph;
    if (!graph) return;
    const nodes = stackTarget(graph);
    if (nodes.length < 2) {
        toast("warn", STACK_LABEL, "Select two or more nodes, or point at a group.");
        return;
    }
    const ctx = canvasCtx();
    const grid = gridSize(graph);
    const boxes = nodes.map((node) => ({
        ...measureNode(node, ctx),
        pinned: !!node.pinned,
        collapsed: !!node.flags?.collapsed,
        panel: !!node.widgets?.some?.((w) => w?.element),
    }));
    const { places, widths, axis } = stackPlan(boxes, { grid });
    if (!places.size) {
        toast("warn", STACK_LABEL, "Nothing to stack — every node is pinned.");
        return;
    }
    commit(graph, () => {
        for (const box of boxes) {
            const at = places.get(box.id);
            if (!at) continue;
            const width = widths.get(box.id);
            if (width) box.node.size = [width, box.node.size[1]];
            box.node.pos = [at.x + box.ox, at.y + box.oy];
        }
        for (const group of graph.groups ?? []) group.recomputeInsideNodes?.();
    });
    toast("success", STACK_LABEL, `${places.size} nodes in a ${axis}.`);
}

// A second marker and a second patch: this menu section must not ride on the
// finder's, or removing one would silently take the other's rows away.
const ARRANGE_PATCHED = "symbioticaArrange";

function prependArrangeMenu(canvasClass) {
    const proto = canvasClass?.prototype;
    const original = proto?.getCanvasMenuOptions;
    if (typeof original !== "function" || original[ARRANGE_PATCHED]) return false;
    function withArrange() {
        const options = original.apply(this, arguments) ?? [];
        const graph = this.graph ?? app.graph;
        const rows = [{
            content: `${ARRANGE_LABEL} (${comboLabel(ARRANGE_COMBO)})`,
            callback: runArrange,
        }, {
            content: `${STACK_LABEL} (${comboLabel(STACK_COMBO)})`,
            callback: runStack,
        }];
        if (graph?.extra?.[UNDO_KEY]?.nodes?.length) {
            rows.push({ content: RESTORE_LABEL, callback: runRestore });
        }
        options.unshift(...rows);
        return options;
    }
    withArrange[ARRANGE_PATCHED] = true;
    proto.getCanvasMenuOptions = withArrange;
    return true;
}

// Its OWN extension spec, not three more commands on the finder's. A
// keybinding collision hard-refuses the whole spec it arrives in, and a clash
// on Shift+A with some pack installed later must not take "Find node by ID"
// and both hubs off the canvas with it.
registerSymbioticaExtension(app, {
    name: "symbiotica.arrange",
    setup() { prependArrangeMenu(globalThis.LGraphCanvas); },
    commands: [
        { id: ARRANGE_ID, label: ARRANGE_LABEL, icon: "pi pi-th-large",
          function: runArrange },
        { id: STACK_ID, label: STACK_LABEL, icon: "pi pi-bars", function: runStack },
        { id: RESTORE_ID, label: RESTORE_LABEL, icon: "pi pi-undo",
          function: runRestore },
    ],
    keybindings: [
        { commandId: ARRANGE_ID, combo: ARRANGE_COMBO },
        { commandId: STACK_ID, combo: STACK_COMBO },
    ],
    // The same button beside the frontend's own Arrange when two or more
    // things are selected.
    getSelectionToolboxCommands() { return [STACK_ID]; },
});
