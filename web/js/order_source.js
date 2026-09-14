// ABOUTME: The order picker — project, month, feature, "Read folder" — plus the
// ABOUTME: graph-walk helpers that resolve a project_path arriving on a wire.

// Its own module because two panels host it: Asset Focus wires the whole picker
// onto its own widgets, and the Prompt Block resolves a project the same way.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { createOrderCache } from "./order_cache.js";

// Order parses are requested from render paths, which LiteGraph re-evaluates on
// every repaint, so the same order would otherwise be re-fetched for every
// frame. Keyed on the request route, which already carries project + month.
const orderParses = createOrderCache({ fetcher: (route) => fetchJson(route) });

// One shared empty list, so "no events" compares identical across calls and a
// node can tell a repeat answer from a new one.
const NO_EVENTS = [];

async function fetchJson(route) {
    const res = await api.fetchApi(route);
    if (!res.ok) {
        const err = new Error(
            (await res.json().catch(() => ({}))).error ?? res.statusText);
        // Callers that cache need to tell "this request will never work" from
        // "the server is having a moment".
        err.status = res.status;
        throw err;
    }
    return res.json();
}

function widgetOf(node, name) {
    return node?.widgets?.find((w) => w.name === name);
}

// Event combo label ("Mini 1 — Ghostly Goodies") vs the stored key ("Mini 1").
// The value may be either form (saved workflows keep the plain feature); the
// key strips the " — <name>" the combo appends.
function eventLabel(e) {
    return e.eventName ? `${e.feature} — ${e.eventName}` : e.feature;
}
function featureKey(value) {
    return String(value ?? "").split(" — ")[0].trim();
}

// Which event a stored feature opens, and whether the order still holds it.
//
// The queue takes the feature literally: it builds the named event or refuses,
// and never answers a name it cannot find with the order's first event. This is
// the panel half of that rule, so the two agree about which event is on screen.
//
// A BLANK feature is not a stale one — it means "whichever this order leads
// with", and the first event is the answer. Neither is an order with no events:
// nothing was substituted because there was nothing to substitute.
export function eventForStoredFeature(events, stored) {
    const list = events ?? [];
    const wanted = featureKey(stored);
    const asked = wanted ? list.find((e) => e.feature === wanted) : null;
    const event = asked ?? list[0] ?? null;
    return { event, stale: Boolean(wanted) && !asked && Boolean(event) };
}

// registration both need the actual path string, which the widget alone can't
// give once the socket is wired.
export function resolveProjectPath(node) {
    const v = widgetOf(node, "project_path")?.value?.trim?.();
    if (v) return v;
    return inputString(node, "project_path", new Set());
}

// A typed project_path is authoritative — the user entered it in the widget. A
// wired one is resolved by a best-effort graph walk, so it must never auto-pick
// a render-feeding widget (month, feature): a wrong-branch guess would reach the
// queued render, where Python silently falls back to the first month/event.
function projectPathTyped(node) {
    return !!widgetOf(node, "project_path")?.value?.trim?.();
}

export function inputString(node, inputName, seen) {
    const input = node?.inputs?.find((i) => i.name === inputName);
    if (!input || input.link == null) return "";
    const link = app.graph.links[input.link];
    const origin = link && app.graph.getNodeById(link.origin_id);
    return nodeOutputString(origin, seen);
}

// Is a switch node's toggle ON? Not `!!value`: a widget's boolean is not always
// a boolean. LazySwitchKJ serialises its `switch` as the STRING "False", and
// `Boolean("False")` is true — so every panel followed the on_true branch
// whatever the toggle said, and the Modal/Local switch did nothing at all.
// Anything a person would read as off is off.
const OFF = new Set(["", "false", "0", "no", "off", "none", "null", "undefined"]);
export function switchIsOn(value) {
    if (typeof value === "string") return !OFF.has(value.trim().toLowerCase());
    if (value == null) return false;
    return !!value;
}

// The string a node's output carries, resolved statically from the graph: a
// switch node (on_true/on_false + a `switch` widget) follows its selected
// branch; a literal/primitive yields its string widget; a lone-input passthrough
// (a Reroute) follows its wire. A node with several wired inputs that we can't
// read as a switch is an ambiguous selector — we refuse to guess a branch, since
// the wrong one silently feeds a wrong project. `seen` guards against a cycle.
export function nodeOutputString(node, seen) {
    if (!node || seen.has(node.id)) return "";
    seen.add(node.id);
    const isSwitch = node.inputs?.some((i) => i.name === "on_true")
                  && node.inputs?.some((i) => i.name === "on_false");
    if (isSwitch) {
        const sw = node.widgets?.find(
            (w) => w.name === "switch" || w.name === "boolean" || w.name === "on");
        return inputString(node, switchIsOn(sw?.value) ? "on_true" : "on_false", seen);
    }
    const strW = node.widgets?.find(
        (w) => typeof w.value === "string" && w.value.trim());
    if (strW) return strW.value.trim();
    const wired = (node.inputs ?? []).filter((i) => i.link != null);
    if (wired.length === 1) return inputString(node, wired[0].name, seen);
    return "";
}

// --- widget upgrades ---------------------------------------------------------
function comboify(node, widgetName, valuesFn) {
    const i = node.widgets?.findIndex((x) => x.name === widgetName);
    if (i == null || i < 0) return;
    const existing = node.widgets[i];
    if (existing.type === "combo") {
        existing.options = existing.options ?? {};
        existing.options.values = valuesFn; // LiteGraph accepts a function
        return existing;
    }
    // The classic (non-Vue) node UI won't turn a text widget into a dropdown by
    // mutating `.type` — it keeps the text-prompt behavior. Recreate it as a
    // REAL combo widget in the same slot so both UIs show a dropdown. Preserve
    // the value + serialization so the string still reaches the Python node.
    const value = existing.value;
    node.widgets.splice(i, 1);
    const w = node.addWidget("combo", widgetName, value,
                             (v) => { w.value = v; }, { values: valuesFn });
    node.widgets = node.widgets.filter((x) => x !== w); // move it back to slot i
    node.widgets.splice(i, 0, w);
    w.serializeValue = () => w.value;
    return w;
}

// Turn a node's `month` text widget into a dropdown fed by the months found
// under its project_path/orders — and keep it fresh when the path changes.
function wireMonthPicker(node) {
    node._symMonths = [];
    comboify(node, "month", () => node._symMonths);
    const refresh = async () => {
        const project = resolveProjectPath(node);
        if (!project) { node._symMonths = []; return; }
        try {
            const data = await fetchJson(
                "/symbiotica/list-orders?project=" + encodeURIComponent(project));
            node._symMonths = (data.months ?? []).map((m) => m.label);
            // A wired path populates the dropdown but never re-picks the month —
            // only a typed project_path is authoritative enough for that.
            const monthW = widgetOf(node, "month");
            if (projectPathTyped(node) && monthW
                && !node._symMonths.includes(monthW.value)) {
                monthW.value = node._symMonths[0] ?? "";
            }
        } catch { node._symMonths = []; }
        node.setDirtyCanvas?.(true, true);
    };
    const projectW = widgetOf(node, "project_path");
    if (projectW) {
        const prev = projectW.callback;
        projectW.callback = function () {
            const r = prev?.apply(this, arguments);
            refresh();
            return r;
        };
    }
    node._symRefreshMonths = refresh; // the Read-folder button calls this
    refresh();
}

// The node is a leaf picker (no upstream): it reads its own project + month.
// Parse the order server-side and cache the events on the node, so its own
// `feature` combo and any downstream panel can read the event list
// synchronously.
// `explicit` marks a deliberate request — the node being wired, or the user
// editing project/month/feature. Those re-ask the server even for inputs that
// failed before, so a path that starts working again can be picked up without a
// page reload. The opportunistic callers below (a panel rendering, a combo being
// painted) always take the cached answer.
async function refreshOrderSpecs(node, { explicit = false } = {}) {
    const project = resolveProjectPath(node);
    const month = widgetOf(node, "month")?.value?.trim();
    if (!project) { publishOrder(node, null, NO_EVENTS, ""); return; }
    const q = new URLSearchParams({ project });
    if (month) q.set("month", month);
    const route = `/symbiotica/parse-order?${q}`;
    if (explicit) orderParses.invalidate(route);
    const result = await orderParses.get(route);
    publishOrder(node, result,
                 (result.ok && result.data.events) || NO_EVENTS,
                 (result.ok && result.data.refsRoot) || "");
}

// Put a parse result on the node, then re-render downstream ONLY if the answer
// differs from the one the node already holds.
//
// That guard is what bounds the work. Both the Auto Packer's assets panel and
// its `category` combo ask for the order while they render, and re-rendering
// them — or marking the canvas dirty, which schedules the repaint that paints
// the combo — calls straight back into here. Repeating the same answer means
// repeating it forever: with a stale project path that was a request per round
// trip per packer, and without the round trip to throttle it, an unbroken
// recursion.
function publishOrder(node, result, events, refsRoot) {
    node._symEvents = events;
    node._symRefsRoot = refsRoot;
    // Keep the feature value valid (accept the plain feature OR the labelled
    // form); empty means "the order's first event". Never reset a value that
    // still matches an event by key — that would clobber a saved workflow.
    // `result` is null when there is no project to parse: nothing was asked, so
    // nothing says the current pick is wrong, and clearing the path to type a
    // new one must not throw the pick away. Only a typed project_path re-picks:
    // a wired resolution is a graph-walk guess and must not overwrite feature.
    const featW = widgetOf(node, "feature");
    if (projectPathTyped(node) && result !== null && featW && featW.value) {
        const key = featureKey(featW.value);
        if (!events.some((e) => e.feature === key)) {
            featW.value = events[0] ? eventLabel(events[0]) : "";
        }
    }
    // The cache hands back one object per set of inputs, so identity answers
    // "is this the same order I already published?" exactly. `feature` rides
    // along because picking a different event has to re-render the packers even
    // though the order behind it never changed.
    const feature = featW?.value ?? "";
    const last = node._symPublished;
    node._symPublished = { result, events, feature };
    if (last && last.result === result && last.events === events
        && last.feature === feature) return;
    // Tell everything that reads an order it has changed. Announced to
    // the whole graph rather than to the nodes one hop down: the order wire
    // commonly runs through a reroute, and a panel that follows the wire up
    // six hops to find its source cannot be found by looking one hop down.
    // Each listener decides for itself whether THIS node is its source, which
    // keeps the knowledge of what counts as one in the module that already has
    // it. LiteGraph gives no event for "a widget upstream changed", so without
    // this a downstream panel keeps showing the previous event until something
    // else happens to re-render it.
    for (const other of app.graph?._nodes ?? []) {
        if (other !== node) other._symOrderChanged?.(node);
    }
    node.setDirtyCanvas?.(true, true);
}

// Exported so Asset Focus can host the whole selection — project, month,
// feature, Read folder — rather than a second implementation of it that
// drifts. It assumes only that the node carries `project_path`, `month` and
// `feature` widgets.
export function wireOrderSpecs(node) {
    node._symEvents = [];
    // Parsing on demand, the way `_symRefreshMonths` exposes the month parse.
    // A panel downstream that needs the event list has no other way to ask for
    // it: `refreshOrderSpecs` is private to this module.
    node._symRefreshOrder = (opts) => refreshOrderSpecs(node, opts);
    wireMonthPicker(node); // month combo, refreshed on project_path change
    comboify(node, "feature", () => (node._symEvents ?? []).map(eventLabel));
    // "Read folder" — resolve project_path (even a wired Local/Modal switch),
    // fill the month + feature dropdowns, and hit parse-order so the server
    // registers the refs root (that is what lets the Auto Packer thumbnails
    // load). No need to wire + queue a packer just to populate the pickers.
    //
    // A NATIVE litegraph button (like the Studio Library's "Browse" button):
    // it renders in both UIs and — unlike a DOM widget — is never hidden below
    // the zoom threshold, so it can't come up missing on a fresh Comfy start.
    let reading = false;
    const readBtn = node.addWidget("button", "📁 Read folder", null, async () => {
        if (reading) return;
        reading = true;
        readBtn.name = "⏳ Reading…";
        node.setDirtyCanvas?.(true, true);
        try {
            await node._symRefreshMonths?.();
            await refreshOrderSpecs(node, { explicit: true });
        } finally {
            reading = false;
            readBtn.name = "📁 Read folder";
            node.setDirtyCanvas?.(true, true);
        }
    });
    readBtn.serialize = false;
    // Re-parse whenever project OR month changes (chains onto wireMonthPicker's
    // own project_path hook — both fire). `feature` too, so a downstream panel
    // re-renders for the newly picked event.
    for (const name of ["project_path", "month", "feature"]) {
        const w = widgetOf(node, name);
        if (!w) continue;
        const prev = w.callback;
        w.callback = function () {
            const r = prev?.apply(this, arguments);
            refreshOrderSpecs(node, { explicit: true });
            return r;
        };
    }
    // Fire now, and — only while the project cannot be resolved yet — again on
    // a backing-off ladder: on load a wired project_path (a Local/Modal switch)
    // is not resolvable until the links are restored, and how long that takes
    // is not ours to know. One deferred pass at 400 ms was a guess, and when it
    // missed nothing retried — which is the whole reason "Read folder" had to
    // be pressed by hand ("Asset focus should read the folder without me
    // clicking on it mate"). Four attempts, 400/800/1200 ms, stopping the
    // moment the project resolves. When it already resolved the settled parse
    // stands — re-asking would reopen a cached failure and reflood.
    refreshOrderSpecs(node, { explicit: true });
    let tries = 0;
    const settle = () => {
        if (resolveProjectPath(node) || tries >= 3) return;
        tries += 1;
        setTimeout(() => {
            if (resolveProjectPath(node)) {
                node._symRefreshMonths?.();
                refreshOrderSpecs(node, { explicit: true });
                return;
            }
            settle();
        }, 400 * tries);
    };
    settle();
}
