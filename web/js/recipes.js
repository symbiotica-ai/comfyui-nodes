// ABOUTME: Workflow recipes — the Recipes node: pick or start a project, edit its
// ABOUTME: shared values and one recipe per asset type, save, generate.

// A project is one template workflow plus a table of values. The rows come
// from the template itself (every node painted the match colour, its title the
// slot's name; a node titled `recipe:<key>` still counts), so a new slot
// on the canvas is a new row here the next time the project is opened. The
// columns are `shared` (what every recipe takes) and one per recipe. An empty
// cell is an absent key: the recipe then takes the shared value, or the
// template's own.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { HUB, ghostButtonCss, injectHubStyles } from "./hub_theme.js";
import { el, emptyState, iconButton, iconLead, ONE_LINE, pinPanelWidth,
         sidebarShell, treeRow } from "./browser_chrome.js";
import { askForName, findSource, graphScope, slotName } from "./find_node.js";
// The panel hides the widgets its head drives, exactly as the Task node
// does. `hideWidget` is exported from there and imported by three other
// panels; a second copy of it is how they drift.
import { assetRecipeOf, eventForCategory, hideWidget,
         monthCategories } from "./asset_focus.js";

const NODE_CLASS = "SymbioticaRecipe";
const SHARED = "shared";
const WORKFLOWS_PREFIX = "workflows/";

// ---------------------------------------------------------------- server --

async function getJson(path) {
    const res = await api.fetchApi(path);
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body?.error ?? `${res.status} ${res.statusText}`);
    return body;
}

async function postJson(path, payload) {
    const res = await api.fetchApi(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload ?? {}),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body?.error ?? `${res.status} ${res.statusText}`);
    return body;
}

async function deleteJson(path) {
    const res = await api.fetchApi(path, { method: "DELETE" });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body?.error ?? `${res.status} ${res.statusText}`);
    return body;
}

const listProjects = () => getJson("/symbiotica/recipes").then((b) => b.projects ?? []);
const readProject = (name) => getJson(`/symbiotica/recipes/${encodeURIComponent(name)}`);

function toast(severity, summary, detail, life = 5000) {
    app.extensionManager?.toast?.add({ severity, summary, detail, life });
}

const noSlotsToast = (color) => toast("warn", "No recipe slots on this canvas",
    color ? `Paint a node ${color} and it is a slot — under its own title, or under its type's name until you rename it.`
          : "Type a colour in match_color, then paint the nodes a recipe should set.");

const activeWorkflowPath = () => app.extensionManager?.workflow?.activeWorkflow?.path ?? null;

// ------------------------------------------------------------- resolver --

// The recipe name is usually wired: Asset Focus's category joined with a plot
// string. None of that has a value on the canvas until a run, so the name
// is read live by walking the wires back through the nodes whose output is
// a plain function of their widgets. Anything else (an LLM, a file) is null:
// a guess would save a recipe under the wrong name.
const STRING_NODES = new Set(["String", "PrimitiveString", "PrimitiveStringMultiline", "StringConstant",
    "StringConstantMultiline", "easy string", "Text", "CR Text", "Simple String"]);
const PASS_THROUGH = new Set(["Reroute", "PreviewAny", "ShowText|pysssss", "PreviewAsText"]);

function widgetValue(node, name) {
    const widget = node.widgets?.find((w) => w.name === name);
    return widget ? widget.value : undefined;
}

function inputText(graph, node, inputName, depth) {
    const index = node.inputs?.findIndex((i) => i.name === inputName) ?? -1;
    if (index < 0) return undefined;
    return inputTextAt(graph, node, index, depth, inputName);
}

// The same by slot INDEX, which is what a hub lookup hands back: a Set Hub's
// slots are named for their constants and a KJ Set node's only input is named
// after its type, so neither name is worth a second search.
function inputTextAt(graph, node, index, depth, inputName) {
    const input = node.inputs?.[index];
    if (!input) return undefined;
    if (input.link != null) {
        const link = graph.links?.get?.(input.link) ?? graph.links?.[input.link];
        const origin = link ? graph.getNodeById?.(link.origin_id) : null;
        if (!origin) return null;
        return nodeText(graph, origin, link.origin_slot ?? 0, depth + 1);
    }
    const value = widgetValue(node, input.widget?.name ?? inputName ?? input.name);
    return value === undefined ? undefined : String(value);
}

// What a focus/task node's `category` / `category_recipe` output says on the
// canvas. The dropdown holds the recipe label (`Appliance 1x2`); the plain
// `category` output is that without its size, and "All" names nothing. Picking
// an ASSET clears the dropdown, and the asset's own row is what names its
// recipe -- without that fallback, choosing an asset leaves the Recipes node
// with no name and it silently stores nothing.
function categoryOutput(node, output) {
    const picked = String(widgetValue(node, "category") ?? "").trim();
    if (picked && picked !== "All") {
        return output === "category" ? picked.replace(/\s+\d+x\d+$/i, "") : picked;
    }
    const fromAsset = assetRecipeOf(node, widgetValue(node, "asset"));
    if (!fromAsset) return null;
    return (output === "category" ? fromAsset.category : fromAsset.recipe) || null;
}

function nodeText(graph, node, slot, depth) {
    if (depth > 12) return null;
    const type = String(node.type ?? "");
    if (STRING_NODES.has(type)) {
        const widget = node.widgets?.find((w) => typeof w.value === "string");
        return widget ? String(widget.value) : null;
    }
    // Task Specs holds no pick of its own — the Task feeding its `specs`
    // wire made it. Same question, one hop up, and the answer is read off the
    // SAME output name rather than the same slot: the two nodes do not share
    // an output column.
    if (type === "SymbioticaTaskSpecs") {
        const input = node.inputs?.find((i) => i.name === "specs");
        const link = input?.link == null ? null
            : (graph.links?.get?.(input.link) ?? graph.links?.[input.link]);
        const origin = link ? graph.getNodeById?.(link.origin_id) : null;
        if (!origin) return null;
        const wanted = node.outputs?.[slot]?.name;
        if (wanted === "category" || wanted === "category_recipe") {
            return categoryOutput(origin, wanted);
        }
        const value = wanted ? widgetValue(origin, wanted) : undefined;
        return typeof value === "string" ? value : null;
    }
    // Asset Recipe is the same node with widget slots on the end, and it
    // names a recipe the same way. So is Task — the same widgets under a
    // sidebar.
    if (type === "SymbioticaAssetFocus" || type === "SymbioticaAssetRecipe"
            || type === "SymbioticaTask") {
        const output = node.outputs?.[slot]?.name;
        if (output === "category" || output === "category_recipe") {
            return categoryOutput(node, output);
        }
        const value = output ? widgetValue(node, output) : undefined;
        return typeof value === "string" ? value : null;
    }
    if (type === "JoinStrings") {
        const a = inputText(graph, node, "string1", depth);
        const b = inputText(graph, node, "string2", depth);
        if (a == null || b == null) return null;
        return `${a}${inputText(graph, node, "delimiter", depth) ?? ""}${b}`;
    }
    if (type === "JoinStringMulti") {
        const count = Number(widgetValue(node, "inputcount") ?? 2);
        const delimiter = String(widgetValue(node, "delimiter") ?? "");
        const parts = [];
        for (let i = 1; i <= count; i += 1) {
            const part = inputText(graph, node, `string_${i}`, depth);
            if (part == null) return null;
            parts.push(part);
        }
        return parts.join(delimiter);
    }
    // A Get Hub output. The constant's name is the LABEL of the slot the wire
    // left -- one hub stands in for twenty KJ pairs, so the node alone does not
    // say which value this is -- and from there it is the same hop: whatever is
    // wired INTO the slot publishing that name.
    if (type === "SymbioticaGetHub") {
        const source = findSource(graphScope(node.graph, graph),
                                  slotName(node.outputs?.[slot]));
        if (!source) return null;
        return inputTextAt(source.graph ?? graph, source.node, source.index,
                           depth) ?? null;
    }
    // KJNodes' Set/Get pair. A GetNode's only widget holds the NAME of the
    // constant, never its value, so the value is one input back on the SetNode
    // carrying the same name -- a walk the canvas can do without a run.
    if (type === "GetNode" || type === "SetNode") {
        const setter = type === "SetNode" ? node : findSetter(graph, node);
        return setter?.inputs?.[0]
            ? inputTextAt(graph, setter, 0, depth) ?? null : null;
    }
    if (PASS_THROUGH.has(type)) {
        const first = node.inputs?.[0]?.name;
        return first ? inputText(graph, node, first, depth) ?? null : null;
    }
    return null;
}

// The SetNode a GetNode reads: the same constant name, which on both is the
// first widget. An unnamed Get, or one whose Set is gone, matches nothing.
function findSetter(graph, get) {
    const name = String(get.widgets?.[0]?.value ?? "").trim();
    if (!name) return null;
    return (graph?.nodes ?? []).find((n) => String(n.type ?? "") === "SetNode"
        && String(n.widgets?.[0]?.value ?? "").trim() === name) ?? null;
}

// The node whose `category` names the recipe: the same walk `nodeText` makes,
// stopping at the node rather than at its text. Picking a recipe in the sidebar
// sets that widget, so the wire agrees with the panel -- without it, auto reads
// the old name on the next repaint and pulls the canvas straight back.
const FOCUS_TYPES = new Set(["SymbioticaAssetFocus", "SymbioticaAssetRecipe",
                             "SymbioticaTask"]);

function focusBehindAt(graph, node, index, depth) {
    const input = node?.inputs?.[index];
    if (!input || input.link == null || depth > 12) return null;
    const link = graph.links?.get?.(input.link) ?? graph.links?.[input.link];
    const origin = link ? graph.getNodeById?.(link.origin_id) : null;
    if (!origin) return null;
    return focusBehindNode(graph, origin, link.origin_slot ?? 0, depth + 1);
}

function focusBehindNode(graph, node, slot, depth) {
    const type = String(node?.type ?? "");
    if (FOCUS_TYPES.has(type)) return node;
    if (type === "SymbioticaTaskSpecs") {
        const index = (node.inputs ?? []).findIndex((i) => i.name === "specs");
        return index < 0 ? null : focusBehindAt(graph, node, index, depth);
    }
    if (type === "SymbioticaGetHub") {
        const source = findSource(graphScope(node.graph, graph),
                                  slotName(node.outputs?.[slot]));
        return source ? focusBehindAt(source.graph ?? graph, source.node,
                                      source.index, depth) : null;
    }
    if (type === "GetNode" || type === "SetNode") {
        const setter = type === "SetNode" ? node : findSetter(graph, node);
        return setter ? focusBehindAt(graph, setter, 0, depth) : null;
    }
    if (PASS_THROUGH.has(type)) return focusBehindAt(graph, node, 0, depth);
    return null;
}

export function focusBehind(graph, node, inputName) {
    const index = (node?.inputs ?? []).findIndex((i) => i.name === inputName);
    return index < 0 ? null : focusBehindAt(graph, node, index, 0);
}

// The text arriving on one of this node's inputs: typed, or resolved live
// through the wire. null when wired to something the resolver cannot read.
export function resolveText(graph, node, inputName) {
    const value = inputText(graph, node, inputName, 0);
    return value == null ? null : String(value).trim();
}

// Always the ROOT graph. `app.canvas.graph` is whatever the canvas is showing,
// which inside a subgraph is that subgraph -- and reading slots from it would
// shrink the table to the subgraph's nodes and delete every other recipe's
// values on the next save.
const liveGraph = () => {
    const shown = app.canvas?.graph ?? app.graph;
    return shown?.rootGraph ?? app.graph ?? shown ?? null;
};
const textValue = (node, name) => resolveText(liveGraph(), node, name);

// What auto does when the name on the wire is `next` and the canvas was on
// `prev` (changed = slot values moved since that recipe was last written):
// save what you leave, then load the recipe you arrive at, or create it.
// The first tick of a session has no memory of where the canvas is. What the
// canvas holds is what he last pressed -- the workflow saved it -- so auto
// takes that as the recipe's current state instead of writing the stored one
// over it. Only a later switch to another recipe writes to the canvas.
export function autoAdopt(last, next, columns) {
    return last.name === null && !!next && columns.includes(next);
}

export function autoDecision(prev, next, columns) {
    const actions = [];
    if (prev.name && prev.changed) actions.push(`save:${prev.name}`);
    if (next && next !== prev.name) actions.push(columns.includes(next) ? `load:${next}` : `create:${next}`);
    return actions;
}

// A recipe name is the suffix of a workflow file name, so whatever arrives
// on the input is lowercased, loses its apostrophes and gets one dash where
// anything else non-alphanumeric was.
export function recipeSlug(text) {
    return String(text ?? "").toLowerCase().replace(/['’]/g, "")
        .replace(/[^a-z0-9._]+/g, "-").replace(/^-+|-+$/g, "");
}

// ----------------------------------------------------------------- color --

// A slot is a node painted the match colour: type the colour once on the
// Recipes node, paint the slots on the canvas. The name comes from LiteGraph's
// palette (purple, green, blue, pale_blue, cyan, red, brown, yellow, black) or
// is a hex. Matching is by hue, so the light theme's lighter shade of the same
// colour still counts. A node titled `recipe:<key>` is still a slot, so
// templates written before this keep working.
const PALETTE = {
    red: "#533", brown: "#593930", green: "#353", blue: "#335",
    pale_blue: "#3f5159", cyan: "#355", purple: "#535", yellow: "#653", black: "#000",
};
const HUE_TOLERANCE = 12;
const RECIPE_PREFIX = "recipe:";

function hsl(value) {
    let hex = String(value ?? "").trim().replace(/^#/, "");
    if (hex.length === 3) hex = hex.split("").map((c) => c + c).join("");
    if (!/^[0-9a-fA-F]{6}$/.test(hex)) return null;
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
    const max = Math.max(r, g, b);
    const min = Math.min(r, g, b);
    const span = max - min;
    const l = (max + min) / 2;
    const s = span === 0 ? 0 : span / (1 - Math.abs(2 * l - 1));
    let h = 0;
    if (span) {
        if (max === r) h = 60 * (((g - b) / span) % 6);
        else if (max === g) h = 60 * ((b - r) / span + 2);
        else h = 60 * ((r - g) / span + 4);
    }
    return { h: (h + 360) % 360, s, l };
}

// "Is this node painted <token>", or null when nothing was typed.
export function colorMatcher(token) {
    const name = String(token ?? "").trim().toLowerCase().replace(/[\s-]+/g, "_");
    const target = hsl(PALETTE[name] ?? name);
    if (!target) return null;
    return (node) => [node?.bgcolor, node?.color].some((value) => {
        const own = hsl(value);
        if (!own) return false;
        if (target.s < 0.1 || own.s < 0.1) return target.s < 0.1 && own.s < 0.1;
        const diff = Math.abs(own.h - target.h);
        return Math.min(diff, 360 - diff) <= HUE_TOLERANCE;
    });
}

// The name a painted node goes under: its title, which LiteGraph fills with
// the type's name until the node is renamed. Painting is the whole of what
// makes a slot -- a node that has not been retitled is still a slot, under
// `KSampler`, and renaming it later renames the row.
function ownTitle(node) {
    const title = String(node?.title ?? "").trim();
    return title || String(node?.constructor?.title ?? node?.type ?? "").trim();
}

// The recipe key a node carries: its title, without the `recipe:` prefix and
// without a toggle's trailing `?`.
export function slotKey(node, matches) {
    const title = String(node?.title ?? "");
    let key;
    if (title.startsWith(RECIPE_PREFIX)) key = title.slice(RECIPE_PREFIX.length);
    else if (matches && matches(node)) key = ownTitle(node);
    else return null;
    return key.replace(/\?\s*$/, "").trim() || null;
}

const isToggleNode = (node) => String(node?.title ?? "").trimEnd().endsWith("?");

// rgthree's Fast Group Bypasser/Muter: one row per group, every row widget
// named RGTHREE_TOGGLE_AND_NAV and holding `{toggled}`, so the group's title
// is the only thing that tells two rows apart -- read by name they are one
// widget, and the slot recorded the first group's `{"toggled": true}` for the
// whole node. Assigning `.value` is inert on these: `toggle(bool)` is what
// moves the group.
const toggledOf = (widget) => (widget?.value && typeof widget.value === "object"
    && !Array.isArray(widget.value) && "toggled" in widget.value)
    ? !!widget.value.toggled : null;

const groupTitleOf = (widget) => String(widget?.group?.title
    ?? String(widget?.label ?? "").replace(/^Enable\s+/i, "")).trim();

export function groupSwitches(widgets) {
    return (widgets ?? []).filter((w) => toggledOf(w) !== null && groupTitleOf(w));
}

// Every setting a node carries, by widget name: a recipe is the whole node,
// not its first widget. A widget the canvas feeds through a wire is left out
// for the same reason a subgraph's wired input is -- the wire is the value,
// and recording the empty box it sits in would write that emptiness onto
// every recipe.
// The widgets a recipe may read or write: the node's own, without its buttons
// and without any fed by a wire. The wire is the value; recording the empty
// box it sits in would write that emptiness into every recipe, and writing
// one back is a value the canvas throws away.
export function settableWidgets(node) {
    const wired = new Set();
    for (const inp of node?.inputs ?? []) {
        if (inp.widget && inp.link != null) wired.add(inp.widget.name ?? inp.name);
    }
    return (node?.widgets ?? []).filter((w) => w.type !== "button" && !wired.has(w.name));
}

export function widgetValues(node, widgets) {
    const wired = new Set();
    for (const inp of node?.inputs ?? []) {
        if (inp.widget && inp.link != null) wired.add(inp.widget.name ?? inp.name);
    }
    const out = {};
    for (const w of widgets ?? []) {
        if (!w.name || wired.has(w.name) || w.name in out) continue;
        out[w.name] = w.value;
    }
    return out;
}

// ----------------------------------------------------------------- cells --

export function cellText(value) {
    if (value === undefined || value === null) return "";
    if (typeof value === "string") return value;
    return JSON.stringify(value).replace(/,/g, ", ").replace(/":/g, '": ');
}

function parseJson(text) {
    try {
        return { ok: true, value: JSON.parse(text) };
    } catch {
        return { ok: false };
    }
}

// The value a cell's text stands for, by the slot's kind. A scalar stays text
// unless the template's own value is a number (then the cell is a number) or
// the text is a JSON list (then it sets every widget on the node).
export function cellValue(slot, text) {
    const raw = String(text ?? "");
    if (!raw.trim()) return undefined;
    const trimmed = raw.trim();
    if (slot.kind === "toggle") {
        if (trimmed === "true") return true;
        if (trimmed === "false") return false;
        throw new Error(`${slot.key}: a toggle is true or false`);
    }
    if (slot.kind === "dict") {
        const parsed = parseJson(trimmed);
        if (!parsed.ok || !parsed.value || typeof parsed.value !== "object" || Array.isArray(parsed.value)) {
            throw new Error(`${slot.key}: a subgraph's values are a JSON object, like {"lora_name": "…"}`);
        }
        return parsed.value;
    }
    if (trimmed.startsWith("[")) {
        const parsed = parseJson(trimmed);
        if (parsed.ok && Array.isArray(parsed.value)) return parsed.value;
    }
    if (typeof slot.default === "number") {
        const n = Number(trimmed);
        if (!Number.isFinite(n)) throw new Error(`${slot.key}: a number`);
        return n;
    }
    return raw;
}

// One widget of a subgraph row, edited on its own: the cell stays a JSON
// object, this rewrites one key. Numbers and true/false are typed as such,
// an empty field drops the key, and no keys left is an empty cell.
export function dictCellUpdate(cell, name, text) {
    const parsed = parseJson(String(cell ?? "").trim() || "{}");
    const obj = parsed.ok && parsed.value && typeof parsed.value === "object" && !Array.isArray(parsed.value)
        ? parsed.value : {};
    const raw = String(text ?? "");
    if (!raw.trim()) {
        delete obj[name];
    } else if (raw.trim() === "true" || raw.trim() === "false") {
        obj[name] = raw.trim() === "true";
    } else if (raw.trim() !== "" && Number.isFinite(Number(raw.trim()))) {
        obj[name] = Number(raw.trim());
    } else {
        obj[name] = raw;
    }
    return Object.keys(obj).length ? cellText(obj) : "";
}

// ----------------------------------------------------------------- table --

const sortedRecipes = (names) => [...names].sort((a, b) => a.localeCompare(b));

export function projectToTable(project, slots) {
    const recipes = project?.recipes ?? {};
    const columns = [SHARED, ...sortedRecipes(Object.keys(recipes))];
    const valuesOf = (column) => (column === SHARED ? project?.shared ?? {} : recipes[column] ?? {});
    // A row is a slot the canvas has. A key the project still holds for a slot
    // that is gone -- a node unpainted, renamed or deleted -- is not a row, so
    // it leaves the table on sight and the file on the next save.
    const rows = slots.map((s) => ({ key: s.key }));
    for (const row of rows) {
        row.cells = {};
        for (const column of columns) row.cells[column] = cellText(valuesOf(column)[row.key]);
    }
    // The base workflow is the whole header. `output` and `workflow_prefix`
    // were two more knobs for one rule — beside the base, named after it —
    // and are gone; a value left in an old file is ignored on both sides.
    return { header: { template: project?.template ?? "" }, columns, rows };
}

// `offered` names the columns that are only there because the ORDER holds that
// category. One of those is written the moment it has a value and not before:
// an empty block per category would put seventeen recipes in the file and have
// `generate workflows` render a workflow for each at full price. A recipe the
// file already holds is never dropped, empty or not — an empty one is his.
export function tableToProject(base, table, slots, offered = null) {
    const byKey = Object.fromEntries(slots.map((s) => [s.key, s]));
    const out = { ...base, template: table.header.template };
    delete out.output;
    delete out.workflow_prefix;
    const columnValues = {};
    for (const column of table.columns) {
        const values = {};
        for (const row of table.rows) {
            const slot = byKey[row.key] ?? { key: row.key, kind: "scalar", default: "" };
            let value;
            try {
                value = cellValue(slot, row.cells[column]);
            } catch (err) {
                throw new Error(`${row.key} / ${column}: ${String(err?.message ?? err).replace(/^[^:]+: /, "")}`);
            }
            if (value !== undefined) values[row.key] = value;
        }
        columnValues[column] = values;
    }
    out.shared = columnValues[SHARED] ?? {};
    const held = new Set(Object.keys(base?.recipes ?? {}));
    out.recipes = {};
    for (const column of table.columns) {
        if (column === SHARED) continue;
        const values = columnValues[column];
        if (offered?.has(column) && !held.has(column) && !Object.keys(values).length) continue;
        out.recipes[column] = values;
    }
    return out;
}

// The values the open canvas holds for every slot, in the shape a recipe
// stores them: a toggle's on/off, a subgraph instance's promoted widgets (the
// wired ones left out), else the node's first widget.
function liveSlotValues(graph, color) {
    const values = {};
    const matches = colorMatcher(color);
    for (const node of graph?.nodes ?? []) {
        const key = slotKey(node, matches);
        if (!key || key in values) continue;
        if (isToggleNode(node)) {
            values[key] = node.mode === 0;
        } else if (node.isSubgraphNode?.()) {
            const promoted = {};
            for (const inp of node.inputs ?? []) {
                if (!inp.widget || inp.link != null) continue;
                const name = inp.widget.name ?? inp.name;
                const widget = node.widgets?.find((w) => w.name === name);
                if (widget) promoted[name] = widget.value;
            }
            values[key] = promoted;
        } else if (groupSwitches(node.widgets).length) {
            const groups = {};
            for (const w of groupSwitches(node.widgets)) groups[groupTitleOf(w)] = toggledOf(w);
            values[key] = groups;
        } else {
            const widgets = settableWidgets(node);
            if (widgets.length > 1) values[key] = widgetValues(node, widgets);
            else if (widgets.length) values[key] = widgets[0].value;
        }
    }
    return values;
}

// The slots the open canvas carries, in the shape the server describes a
// saved template's: a rename, a painted or an unpainted node shows at
// once instead of after the workflow is saved and the project reopened.
export function liveSlots(graph, color) {
    const out = {};
    const matches = colorMatcher(color);
    for (const node of graph?.nodes ?? []) {
        const key = slotKey(node, matches);
        if (!key || key in out) continue;
        const widgets = settableWidgets(node);
        if (isToggleNode(node)) {
            out[key] = { key, kind: "toggle", default: node.mode === 0, widgets: widgets.length };
        } else if (node.isSubgraphNode?.()) {
            const promoted = {};
            for (const inp of node.inputs ?? []) {
                if (!inp.widget || inp.link != null) continue;
                const name = inp.widget.name ?? inp.name;
                const widget = widgets.find((w) => w.name === name);
                if (widget) promoted[name] = widget.value;
            }
            out[key] = { key, kind: "dict", default: promoted, widgets: widgets.length };
        } else if (groupSwitches(widgets).length) {
            const groups = {};
            for (const w of groupSwitches(widgets)) groups[groupTitleOf(w)] = toggledOf(w);
            out[key] = { key, kind: "dict", default: groups, widgets: widgets.length };
        } else if (widgets.length > 1) {
            out[key] = { key, kind: "dict", default: widgetValues(node, widgets),
                         widgets: widgets.length };
        } else {
            out[key] = { key, kind: "scalar", default: widgets[0]?.value ?? null, widgets: widgets.length };
        }
    }
    return Object.keys(out).sort().map((key) => out[key]);
}

// The table again under a changed slot list, the cell text kept exactly as
// typed. Nothing is parsed here: a cell mid-edit that does not parse yet must
// not stop a newly painted node from appearing as a row, which is what a
// round trip through the project did -- it threw, and the canvas went unread.
export function retable(table, nextSlots) {
    const byKey = Object.fromEntries((table.rows ?? []).map((r) => [r.key, r]));
    const rows = nextSlots.map((slot) => byKey[slot.key] ?? { key: slot.key, cells: {} });
    for (const row of rows) {
        for (const column of table.columns) if (row.cells[column] === undefined) row.cells[column] = "";
    }
    return { ...table, rows };
}

// Columns the table did not have, folded in sorted with empty cells. Two
// callers: a capture into a name that is new, and the CATEGORIES the wired
// order holds — every one of those is a row you can pick before anything is
// stored in it. `tableToProject` is what decides which of them reach the file.
export function ensureColumns(table, names) {
    const missing = [...new Set(names)]
        .filter((n) => n && n !== SHARED && !table.columns.includes(n));
    if (!missing.length) return false;
    table.columns.splice(0, table.columns.length, SHARED,
        ...sortedRecipes([...table.columns.filter((c) => c !== SHARED), ...missing]));
    for (const row of table.rows) {
        for (const name of missing) row.cells[name] = "";
    }
    return true;
}

// The reverse: columns off the table, with their cells. Only ever the offered
// categories that never took a value — a recipe is never dropped from under
// him by the order moving on.
export function dropColumns(table, names) {
    const gone = new Set(names.filter((n) => n !== SHARED));
    if (!gone.size) return false;
    table.columns = table.columns.filter((c) => !gone.has(c));
    for (const row of table.rows) {
        for (const name of gone) delete row.cells[name];
    }
    return true;
}

// Write captured values into one column. A recipe takes only what differs
// from shared, so a later shared edit still reaches it; shared takes
// everything.
export function captureColumn(table, slots, column, values) {
    ensureColumns(table, [column]);
    for (const row of table.rows) {
        if (!(row.key in values)) continue;
        const text = cellText(values[row.key]);
        row.cells[column] = column !== SHARED && text === (row.cells[SHARED] ?? "") ? "" : text;
    }
    return table;
}

// One column as the generator would see it: shared with the column's own
// cells on top, each parsed by its slot.
export function columnValues(table, slots, column) {
    const byKey = Object.fromEntries(slots.map((s) => [s.key, s]));
    const values = {};
    for (const source of column === SHARED ? [SHARED] : [SHARED, column]) {
        for (const row of table.rows) {
            const slot = byKey[row.key] ?? { key: row.key, kind: "scalar", default: "" };
            const value = cellValue(slot, row.cells[source]);
            if (value !== undefined) values[row.key] = value;
        }
    }
    return values;
}

// The reverse of capture: put a value set onto the canvas's slot nodes, so
// the recipe can be adjusted with the nodes' own widgets and captured again.
export function applyValuesToNodes(nodes, values, color) {
    const applied = [];
    const seen = new Set();
    const matches = colorMatcher(color);
    for (const node of nodes ?? []) {
        const key = slotKey(node, matches);
        if (!key || !(key in values)) continue;
        const value = values[key];
        const widgets = settableWidgets(node);
        if (isToggleNode(node)) {
            node.mode = value ? 0 : 4;
        } else if (value && typeof value === "object" && !Array.isArray(value)) {
            const switches = groupSwitches(widgets);
            // rgthree's toggleRestriction turns the other groups OFF when one
            // goes on, so the groups a recipe wants off are written before the
            // ones it wants on. Written the other way round, the last key in
            // the recipe decides what stays on, whatever was recorded.
            const entries = Object.entries(value);
            const ordered = switches.length
                ? [...entries.filter(([, v]) => !v), ...entries.filter(([, v]) => v)]
                : entries;
            for (const [name, item] of ordered) {
                const group = switches.find((w) => groupTitleOf(w) === name);
                if (group) { group.toggle?.(!!item); continue; }
                const widget = widgets.find((w) => w.name === name);
                if (widget) widget.value = item;
            }
        } else if (Array.isArray(value)) {
            value.forEach((item, index) => { if (widgets[index]) widgets[index].value = item; });
        } else if (widgets[0]) {
            widgets[0].value = value;
        }
        // A panel node reads its widgets once and caches what it found; the
        // Prompts node would show the previous file's text under the loaded
        // recipe's file name until something asked it to look again.
        node._symRefreshPrompts?.();
        seen.add(key);
        if (!applied.includes(key)) applied.push(key);
    }
    return { applied, missing: Object.keys(values).filter((k) => !seen.has(k)) };
}

// The project this canvas belongs to: the one whose template is the open
// workflow. A project is a file per game and the template is that game's base
// workflow, so being on the base workflow says which project it is.
export function projectForWorkflow(projects, workflowPath) {
    if (!workflowPath) return null;
    let rel = String(workflowPath).replace(/\\/g, "/").replace(/^\/+/, "");
    if (rel.startsWith(WORKFLOWS_PREFIX)) rel = rel.slice(WORKFLOWS_PREFIX.length);
    const hit = (projects ?? []).find((p) => String(p.template ?? "").replace(/^\/+/, "") === rel);
    return hit ? hit.name : null;
}

export function generateSummary(report) {
    const written = report?.written ?? [];
    const summary = `Wrote ${written.length} workflow${written.length === 1 ? "" : "s"} from ${report?.template ?? "the template"}`;
    const detail = written.length
        ? `${written.map((w) => w.path).join(", ")}. Open them from the workflows sidebar; `
          + "reopen any that is open now. Edits belong in the template or the recipe, not in these files."
        : "The project has no recipes.";
    // Values the template had no slot for, each with the recipes that carry it.
    const ignored = {};
    for (const w of written) for (const key of w.ignored ?? []) (ignored[key] ??= []).push(w.recipe);
    const keys = Object.keys(ignored).sort();
    const note = keys.length
        ? ` Ignored, no slot in the template: ${keys.map((k) => `${k} (${ignored[k].join(", ")})`).join(", ")}.`
        : "";
    // Files this project wrote under the OLD naming and no longer maintains.
    // Nothing is deleted — they are workflows in his folder like any other —
    // but a name he has been opening all day that quietly stopped being
    // regenerated has to be said out loud.
    const stale = report?.stale ?? [];
    const left = stale.length
        ? ` Left from the old naming and no longer written: ${stale.join(", ")}.`
          + " Delete them, or they go on holding the graph they froze with."
        : "";
    return { summary, detail: detail + note + left };
}


// ----------------------------------------------------------------- panel --
// A sidebar of names and a pane of values, the shape the Task node is built
// in: `shared` and the recipes on the left, the selected one's cells on the
// right. The rules above are untouched — this is the view.

const RECIPE_MIN_W = 760;
// The sidebar's width, its fold and which row the pane is showing are VIEW
// state, so they ride on node.properties. A widget for any of them would shift
// the saved values of every workflow already holding this node.
const RECIPE_SIDE = "symbiotica_recipes_sidebar";
const RECIPE_SHUT = "symbiotica_recipes_shut";
const RECIPE_PICK = "symbiotica_recipes_pick";
// The project's own row, above `shared`: `template`, `output` and `prefix`
// live there. `template` is what `projectForWorkflow` matches the open
// workflow against, and the only repair after a Save As, so it has to stay
// reachable. No recipe can be called this — `recipeSlug` turns a colon into a
// dash.
const PROJECT_ROW = ":project";
const LABEL_W = 150;

const inputCss = "box-sizing:border-box;min-width:0;padding:3px 5px;"
    + `font:11px ${HUB.mono};background:var(--comfy-input-bg, transparent);`
    + `color:var(--input-text, ${HUB.ink});border:1px solid ${HUB.hairline};border-radius:${HUB.radius.sm};`;
const cellCss = inputCss + "width:100%;resize:vertical;min-height:24px;line-height:1.35;";
const wordButtonCss = ghostButtonCss + "padding:2px 8px;flex:0 0 auto;"
    + `font:11px ${HUB.font};`;

function stopCanvas(node) {
    node.addEventListener("pointerdown", (e) => e.stopPropagation());
    node.addEventListener("keydown", (e) => e.stopPropagation());
    node.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });
    return node;
}

// The object a cell's text stands for, or null. A cell is text — this only
// asks what shape that text is in.
function objectCell(text) {
    const trimmed = String(text ?? "").trim();
    if (!trimmed.startsWith("{")) return null;
    const parsed = parseJson(trimmed);
    return parsed.ok && parsed.value && typeof parsed.value === "object"
        && !Array.isArray(parsed.value) ? parsed.value : null;
}

const plainObject = (value) => (value && typeof value === "object"
    && !Array.isArray(value) ? value : null);

// Does this row get the sub-grid of one field per key, or one box of text?
// The VALUE decides, and the slot's `kind` only answers when no value does:
// the template's `kind` is read off the SAVED workflow, and on his canvas it
// says `scalar` for slots every recipe stores a dict in. A text box drawn over
// a JSON object is a 1100-character prompt dict flattened on the first save.
export function dictRow(slot, own, inherited) {
    if (objectCell(own)) return true;
    if (objectCell(inherited)) return true;
    if (plainObject(slot?.default)) return true;
    return slot?.kind === "dict";
}

function recipePanel(node) {
    injectHubStyles();
    node.properties = node.properties ?? {};

    // What is on screen: the project as loaded, the template's slots, and the
    // table the person is editing. `dirty` is unsaved edits. `projects` is
    // every project file, so the ones this workflow is not the template of can
    // be named rather than silently missing.
    // `offered` is the columns the CATEGORY sweep put there: rows you can pick
    // before anything is stored in them. They are table columns like any
    // other; what makes them different is that an empty one never reaches the
    // file, and `auto` does not count one as a recipe that exists.
    const state = { name: null, project: null, slots: [], table: null,
                    dirty: false, projects: [], offered: new Set() };
    // The colour that marks a slot: typed on the node, or wired like the name.
    const matchColor = () => {
        const wired = textValue(node, "match_color");
        if (wired) return wired;
        const widget = node.widgets?.find((w) => w.name === "match_color");
        return String(widget?.value ?? "").trim();
    };
    // The recipe the canvas is on -- the category picked in Asset Focus, down
    // the wire. Its row is highlighted, and the pane follows it unless he has
    // picked another by hand.
    let active = "";
    // What the wire put in the pane last, so a pick of his own can be told
    // from one the wire made. Null means the selection is his.
    let autoSelected = SHARED;
    let busy = false;
    // The field the caret is in. Nothing on any render path may replace it:
    // painting a node while typing a 2000-character preamble is exactly when
    // a rebuild happens, and losing the caret mid-word is what the split of
    // the tree from the pane is for.
    let focused = null;
    // A field REMOVED from the page fires no blur — the browser does not send
    // one for an element it took away — so a rebuild would leave this pointing
    // at a field nobody can type in, and every path that waits for the caret to
    // leave would wait for ever.
    const caret = () => {
        if (focused && !focused.parentElement) focused = null;
        return focused;
    };

    // Which row the pane is showing: VIEW state on the node, and a DIFFERENT
    // variable from `active`. Selecting a recipe SHOWS it; the `recipe` wire
    // is still what decides which one is live, and `load` is still explicit.
    const picked = () => String(node.properties?.[RECIPE_PICK] ?? SHARED);
    const pickRow = (row) => { node.properties[RECIPE_PICK] = String(row); };
    // The table column a selected row edits. The project row edits `shared`:
    // its three fields are the project's, its values are the ones every
    // recipe takes.
    const columnOf = (row) => (row === PROJECT_ROW ? SHARED : row);
    const slotOf = (key) => state.slots.find((s) => s.key === key);
    const setCount = (column) => (state.table?.rows ?? [])
        .filter((row) => (row.cells[column] ?? "").trim()).length;
    // A column that is only an OFFER: the order holds that category, the file
    // holds nothing for it, and nothing has been typed into it. It is a row,
    // not a recipe.
    const storedColumns = () => new Set(Object.keys(state.project?.recipes ?? {}));
    const untouched = (column, stored = storedColumns()) =>
        column !== SHARED && state.offered.has(column)
        && !stored.has(column) && !setCount(column);
    // The recipes that EXIST, which is what `auto` decides against: the wire
    // landing on a category with nothing stored must still capture the canvas
    // into it rather than load shared over what he painted.
    const realColumns = () => {
        const stored = storedColumns();
        return (state.table?.columns ?? []).filter((c) => !untouched(c, stored));
    };

    function status(text, subtle = true) {
        statusLine.textContent = text;
        statusLine.style.color = subtle ? HUB.inkSubtle : HUB.ink;
    }

    const statusLine = el("div", `flex:1;min-width:0;${ONE_LINE}`
        + `padding:3px 8px;color:${HUB.inkSubtle};`);

    function collect() {
        const project = tableToProject(state.project, state.table, state.slots,
                                       state.offered);
        const color = matchColor();
        if (color) project.match_color = color; else delete project.match_color;
        return project;
    }

    // --- the shell ---------------------------------------------------------
    const shell = sidebarShell(node, {
        sideProp: RECIPE_SIDE, shutProp: RECIPE_SHUT, sideDefault: 180,
        repaint: () => renderAll(),
        // Above both panes, so it survives the fold — and it answers on the
        // names, which is the one thing the tree cannot scroll to for you once
        // a project has thirty recipes.
        search: {
            placeholder: "Search recipes…",
            list: () => state.table?.columns ?? [],
            onPick: (name) => choose(name),
        },
        headButtons: [
            iconButton("newFile", "Start a project from the open workflow",
                       () => startNew()),
        ],
    });
    const { container, tree } = shell;
    shell.sideTitle.textContent = "recipes";

    // --- the pane ----------------------------------------------------------
    // Built ONCE and updated in place. A render that replaced the head would
    // take the caret out of the name field with it.
    const crumb = el("div", `flex:1;min-width:0;${ONE_LINE}`
        + `font:11px ${HUB.mono};color:${HUB.inkSubtle};`);
    const nameField = stopCanvas(el("input", inputCss + "flex:1 1 160px;"));
    nameField.title = "Recipe: also the suffix of the generated workflow's name.";
    const countBadge = el("div", `flex:0 0 auto;color:${HUB.inkSubtle};`
        + `font:11px ${HUB.mono};`);
    const loadButton = el("button", wordButtonCss, "load");
    const captureButton = el("button", wordButtonCss, "capture");
    // The same act as picking an asset in Task, without the wire: name it, and
    // the canvas as it stands becomes that recipe.
    const newButton = el("button", wordButtonCss, "new recipe");
    const dropButton = iconButton("remove", "Remove this recipe",
                                  () => dropRecipe(), { px: 12, hover: HUB.danger });
    loadButton.className = "sym-btn";
    captureButton.className = "sym-btn";
    newButton.className = "sym-btn";
    const mainHead = el("div", "display:flex;align-items:center;gap:6px;"
        + `padding:3px 6px;flex:none;background:${HUB.surface2};`
        + `border-bottom:1px solid ${HUB.hairline};`);
    mainHead.append(crumb, nameField, countBadge, newButton, loadButton,
                    captureButton, dropButton);

    // The project's own actions, under the row's. `auto` is a control here
    // rather than a widget on the node body — the widget stays, hidden, and
    // this writes it.
    const autoBox = stopCanvas(el("input", "flex:none;margin:0;cursor:pointer;"));
    autoBox.type = "checkbox";
    const autoWrap = el("label", "display:flex;align-items:center;gap:4px;"
        + `flex:0 0 auto;color:${HUB.inkSubtle};cursor:pointer;`);
    autoWrap.title = "Follow the recipe wire: save the one you leave, load the "
        + "one you arrive at.";
    autoWrap.append(autoBox, el("span", "", "auto"));
    const saveButton = el("button", wordButtonCss, "save project");
    const generateButton = el("button", wordButtonCss, "generate workflows");
    const deleteButton = el("button", wordButtonCss, "delete project");
    for (const b of [saveButton, generateButton, deleteButton]) b.className = "sym-btn";
    const actionBar = el("div", "display:flex;align-items:center;gap:6px;"
        + `padding:3px 6px;flex:none;background:${HUB.surface2};`
        + `border-bottom:1px solid ${HUB.hairline};`);
    actionBar.append(autoWrap, el("div", "flex:1;"), saveButton, generateButton,
                     deleteButton);

    // The project's own field — its base workflow — shown under the project
    // row only.
    const headerInputs = {};
    function headerField(label, key, placeholder) {
        const wrap = el("label", "display:flex;align-items:center;gap:6px;"
            + "min-width:0;flex:1 1 30%;");
        wrap.append(el("span", `flex:0 0 auto;color:${HUB.inkSubtle};`, label));
        const input = stopCanvas(el("input", inputCss + "flex:1 1 auto;width:100%;"));
        input.placeholder = placeholder;
        input._symField = key;
        input.addEventListener("focus", () => { focused = input; });
        input.addEventListener("blur", () => { if (focused === input) focused = null; });
        input.addEventListener("input", () => {
            if (!state.table) return;
            state.table.header[key] = input.value;
            touched();
        });
        wrap.appendChild(input);
        headerInputs[key] = input;
        return wrap;
    }
    const headerBox = el("div", "display:flex;gap:8px;flex-wrap:wrap;flex:none;"
        + `padding:6px 8px;border-bottom:1px solid ${HUB.hairline};`);
    // The base workflow this project belongs to, and the only repair after a
    // Save As: `projectForWorkflow` matches the open workflow against it.
    headerBox.append(headerField("base workflow", "template", "folder/base_example.json"));

    const rowsBox = el("div", "flex:1;min-height:0;overflow:auto;padding:2px 8px 8px;");
    rowsBox.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });
    const paneFoot = el("div", "display:flex;align-items:center;flex:none;"
        + `border-top:1px solid ${HUB.hairline};background:${HUB.surface2};`);
    // The status line is re-anchored ONCE, into a foot that no render path
    // replaces — the old panel re-appended it at the end of the body on every
    // draw, and a persistent shell has nowhere to do that.
    paneFoot.appendChild(statusLine);
    shell.main.append(mainHead, actionBar, headerBox, rowsBox, paneFoot);

    // No `computeSize`: LiteGraph builds a node's MINIMUM height by summing
    // its widgets and prefers `computeSize` over `computeLayoutSize`, so
    // anything returned there becomes a floor the corner cannot drag past.
    node.addDOMWidget("recipe_panel", "sym_recipe", container, {
        serialize: false, hideOnZoom: true,
        getMinHeight: () => 60,
    });
    node.size[0] = Math.max(node.size[0], RECIPE_MIN_W);
    const syncPanelWidth = pinPanelWidth(node, container);
    // Redraw, never resize: the panel's height belongs to his drag. A render
    // may push the WIDTH back to what this pane needs — never the height.
    const refit = () => requestAnimationFrame(() => {
        if (node.size[0] < RECIPE_MIN_W) node.setSize?.([RECIPE_MIN_W, node.size[1]]);
        syncPanelWidth();
        node.setDirtyCanvas?.(true, true);
    });

    // --- the server --------------------------------------------------------
    // Which project this canvas is: looked up by the open workflow's path,
    // again whenever that path changes (a Save As, another tab).
    let resolvedFor = undefined;
    async function resolveProject() {
        const path = activeWorkflowPath();
        if (path === resolvedFor) return;
        resolvedFor = path;
        let projects = [];
        let name = null;
        try {
            projects = await listProjects();
            name = projectForWorkflow(projects, path);
        } catch (err) {
            status(`Could not list projects: ${String(err?.message ?? err)}`, false);
            return;
        }
        state.projects = projects;
        if (!name) {
            state.name = null; state.project = null; state.slots = [];
            state.templateSlots = []; state.table = null; state.dirty = false;
            state.offered = new Set(); categorySig = null;
            renderFull();
            status(path ? "No project has this workflow as its template. Press new project." : "Save the workflow first.", false);
            return;
        }
        if (name !== state.name) await load(name); else renderAll();
    }

    async function load(name) {
        try {
            const { project, slots } = await readProject(name);
            const saved = String(project?.match_color ?? "");
            const widget = node.widgets?.find((w) => w.name === "match_color");
            if (saved && widget && widget.value !== saved) widget.value = saved;
            state.name = name;
            state.project = project;
            state.slots = slots;
            // What the TEMPLATE FILE on disk declares, kept while `state.slots`
            // follows the canvas: the difference between the two is what a
            // workflow he has painted but not saved would lose on generate.
            state.templateSlots = slots;
            state.table = projectToTable(project, slots);
            state.dirty = false;
            slotSig = null;
            // The offers belong to the table they were folded into; the sweep
            // on the next draw puts them back against this one.
            state.offered = new Set(); categorySig = null;
            auto.last = { name: null, sig: null };
            takeShot();
            active = "";
            // The row he was on, if the project still has it. A selection that
            // names nothing goes back to shared.
            const held = picked();
            pickRow(held === PROJECT_ROW || state.table.columns.includes(held)
                ? held : SHARED);
            // Nothing picked by hand YET, so the wire may take the pane: on
            // opening a workflow the wire names the recipe the canvas is on,
            // and that is the one to be looking at.
            autoSelected = picked();
            renderFull();
        } catch (err) {
            toast("error", `Could not open "${name}"`, String(err?.message ?? err));
        }
    }

    async function save() {
        if (!state.name) { toast("warn", "Nothing to save", "No project for this workflow; press new project."); return false; }
        let project;
        try {
            project = collect();
        } catch (err) {
            toast("error", "Fix the cell first", String(err?.message ?? err), 8000);
            return false;
        }
        try {
            await postJson("/symbiotica/recipes/save", { name: state.name, project });
            state.project = project;
            state.dirty = false;
            status(`Saved ${state.name}.`);
            rebuildWorkflow(auto.last.name);
            return true;
        } catch (err) {
            toast("error", "Save failed", String(err?.message ?? err));
            return false;
        }
    }

    // The recipe's own workflow file, rewritten after the project is saved, so
    // what is on disk is the recipe rather than whatever generate last wrote.
    // Debounced, and only the recipe that moved: auto saves a second after a
    // value changes, and one 250KB workflow per keystroke is churn, not a file.
    const rebuild = { timer: null, name: null };
    function rebuildWorkflow(column) {
        if (!state.name || !column || column === SHARED) return;
        rebuild.name = column;
        if (rebuild.timer) return;
        rebuild.timer = setTimeout(async () => {
            rebuild.timer = null;
            const recipe = rebuild.name;
            try {
                await postJson("/symbiotica/recipes/generate", { name: state.name, recipe });
            } catch (err) {
                status(`${recipe}: its workflow was not written — ${String(err?.message ?? err)}`, false);
            }
        }, 2000);
    }

    async function generate() {
        if (busy) return;
        busy = true;
        try {
            // The route re-reads the project FROM DISK, so an unsaved edit
            // would generate the last saved values without saying so.
            if (!(await save())) return;
            const report = await postJson("/symbiotica/recipes/generate", { name: state.name });
            const { summary, detail } = generateSummary(report);
            toast("success", summary, detail, 10000);
            status(summary);
        } catch (err) {
            toast("error", "Generate failed", String(err?.message ?? err));
        } finally {
            busy = false;
        }
    }

    // Two presses within a few seconds, so a stray click cannot remove a
    // project; the generated workflows are left where they are.
    let armed = null;
    async function remove() {
        if (!state.name) { toast("warn", "Nothing to delete", "No project for this workflow."); return; }
        if (armed !== state.name) {
            armed = state.name;
            status(`Press delete project again to remove "${state.name}". Its generated workflows stay.`, false);
            setTimeout(() => { if (armed === state.name) { armed = null; status(""); } }, 6000);
            return;
        }
        armed = null;
        const name = state.name;
        try {
            await deleteJson(`/symbiotica/recipes/${encodeURIComponent(name)}`);
            state.name = null;
            state.project = null;
            state.slots = []; state.templateSlots = [];
            state.table = null;
            state.dirty = false;
            state.offered = new Set(); categorySig = null;
            resolvedFor = undefined;
            renderFull();
            toast("info", `Deleted project "${name}"`, "Its generated workflows are still in the workflows folder.");
        } catch (err) {
            toast("error", "Delete failed", String(err?.message ?? err));
        }
    }

    async function startNew() {
        const template = activeWorkflowPath();
        if (!template) { toast("warn", "Save the workflow first", "A new project takes the open, saved workflow as its template."); return; }
        try {
            const { name, project, slots } = await postJson("/symbiotica/recipes/new", { template, match_color: matchColor() });
            state.name = name;
            state.project = project;
            state.slots = slots;
            state.templateSlots = slots;
            state.table = projectToTable(project, slots);
            state.dirty = false;
            slotSig = null;
            state.offered = new Set(); categorySig = null;
            active = ""; autoSelected = SHARED;
            pickRow(SHARED);
            resolvedFor = template;
            // The list it is not on yet: the sidebar names every other project
            // under this one, and a project just started must not be one of
            // them.
            listProjects().then((projects) => { state.projects = projects; renderTree(); })
                          .catch(() => {});
            renderFull();
            toast("success", `Started project "${name}"`, `Template: ${project.template}. Set the canvas, name a recipe, press Capture.`);
        } catch (err) {
            toast("error", "Could not start the project", String(err?.message ?? err));
        }
    }

    function loadColumn(column) {
        let values;
        try {
            values = columnValues(state.table, state.slots, column);
        } catch (err) {
            toast("error", "Fix the cell first", String(err?.message ?? err), 8000);
            return;
        }
        // A recipe with nothing stored and nothing under it in `shared` has
        // nothing to write, and that is not a broken canvas: it is a category
        // he has not been through yet. The toast is for a `match_color` that
        // matches nothing, and firing it here reads as "your canvas is broken"
        // on the one click that is meant to START a recipe.
        if (!Object.keys(values).length) {
            status(`${column} holds nothing yet — set the canvas and press capture.`, false);
            return;
        }
        const report = applyValuesToNodes(liveGraph()?.nodes ?? [], values, matchColor());
        if (!report.applied.length) {
            noSlotsToast(matchColor());
            return;
        }
        liveGraph()?.setDirtyCanvas?.(true, true);
        auto.last = { name: column, sig: slotSignature(liveSlotValues(liveGraph(), matchColor())) };
        takeShot();
        const missing = report.missing.length ? ` Not on this canvas: ${report.missing.join(", ")}.` : "";
        status(`Loaded ${column} onto the canvas (${report.applied.length} slots).${missing}`, false);
    }

    // ------------------------------------------------------------ auto --
    // Watched on every repaint, like the Module node's rows. `last` is the
    // recipe the canvas is on and the slot signature it was last written with.
    // It is written by every path that puts a recipe on the canvas or takes
    // the canvas into one, auto or not, so a switch by hand knows what it is
    // leaving behind.
    const auto = { last: { name: null, sig: null }, timer: null, busy: false, on: false };
    const slotSignature = (values) => JSON.stringify(values);

    // What every node on the canvas held the last time a recipe was put on it
    // or read off it, by node id. A node that has moved since and carries no
    // paint is a change with nowhere to go, and the panel says so rather than
    // letting it vanish.
    let canvasShot = new Map();
    function shotOf(graph) {
        const shot = new Map();
        for (const node of graph?.nodes ?? []) {
            const widgets = settableWidgets(node);
            if (!widgets.length) continue;
            shot.set(node.id, JSON.stringify(widgets.map((w) => w.value)));
        }
        return shot;
    }
    function takeShot() { canvasShot = shotOf(liveGraph()); }

    // The nodes whose values moved since that snapshot and that no recipe can
    // hold, newest first. `slotKey` answers null for anything unpainted.
    function strayChanges() {
        const matches = colorMatcher(matchColor());
        const out = [];
        for (const node of liveGraph()?.nodes ?? []) {
            if (slotKey(node, matches)) continue;
            const was = canvasShot.get(node.id);
            if (was === undefined) continue;
            const widgets = settableWidgets(node);
            if (!widgets.length) continue;
            if (JSON.stringify(widgets.map((w) => w.value)) !== was) {
                out.push(String(node.title ?? node.type ?? node.id));
            }
        }
        return out;
    }

    // What the SAVED template has no slot for: the keys generate would drop.
    // The slot list comes off the template FILE, so this is also how a
    // workflow he has not saved since painting announces itself.
    // What the SAVED template has no slot for: the keys `generate` would drop.
    // Both sides are read off DISK -- the project file as it was last written,
    // the slot list off the template workflow -- because that is the pair the
    // generator sees. A canvas painted since and not saved shows up here.
    function strandedKeys() {
        if (!state.project || !state.templateSlots?.length) return [];
        const known = new Set(state.templateSlots.map((s) => s.key));
        const out = new Set();
        const blocks = [state.project.shared ?? {},
                        ...Object.values(state.project.recipes ?? {})];
        for (const block of blocks) {
            for (const key of Object.keys(block ?? {})) if (!known.has(key)) out.add(key);
        }
        return [...out].sort();
    }

    async function autoTick() {
        if (!auto.on || auto.busy || !state.table) return;
        const graph = liveGraph();
        const values = liveSlotValues(graph, matchColor());
        if (!Object.keys(values).length) return;
        const sig = slotSignature(values);
        const raw = textValue(node, "recipe");
        const next = raw ? recipeSlug(raw) : "";
        if (autoAdopt(auto.last, next, realColumns())) {
            auto.last = { name: next, sig };
            return;
        }
        const prev = { name: auto.last.name, changed: auto.last.sig !== null && auto.last.sig !== sig };
        const actions = autoDecision(prev, next, realColumns());
        if (!actions.length) return;
        // A value edit settles for a second before it is written; a name
        // change acts at once, so the recipe you leave is saved as it was.
        const onlySave = actions.length === 1 && actions[0] === `save:${prev.name}` && next === prev.name;
        if (onlySave) {
            if (auto.timer) return;
            auto.timer = setTimeout(() => { auto.timer = null; autoRun(actions, values, sig); }, 1000);
            return;
        }
        if (auto.timer) { clearTimeout(auto.timer); auto.timer = null; }
        await autoRun(actions, values, sig);
    }

    async function autoRun(actions, values, sig) {
        auto.busy = true;
        try {
            for (const action of actions) {
                const [verb, name] = action.split(/:(.*)/s);
                if (verb === "save" || verb === "create") {
                    captureColumn(state.table, state.slots, name, values);
                    state.dirty = true;
                    // On a failed save the signature is still recorded, so the
                    // same values do not retry on every repaint; the toast said why.
                    auto.last = { name, sig };
                    if (!(await save())) return;
                    // RECONCILED, not rebuilt: auto fires a second after an
                    // edit, which is while he is still typing the next one.
                    renderAll();
                    status(`auto: ${verb === "save" ? "saved" : "created"} ${name}`, false);
                } else if (verb === "load") {
                    loadColumn(name);
                    auto.last = { name, sig: slotSignature(liveSlotValues(liveGraph(), matchColor())) };
                    status(`auto: loaded ${name} onto the canvas`, false);
                }
            }
        } finally {
            auto.busy = false;
        }
    }

    // The slot list follows the canvas; the saved template's stands in only
    // while the canvas has no slot nodes (or a cell cannot be parsed).
    let slotSig = null;
    let colorSig = null;
    function syncSlots() {
        if (!state.table) return;
        const graph = liveGraph();
        // No nodes at all is a graph still loading, not a canvas with nothing
        // painted on it. Nothing painted IS a real answer: the rows go.
        if (!graph?.nodes?.length) return;
        const color = matchColor();
        const live = liveSlots(graph, color);
        const sig = JSON.stringify(live);
        // The colour is half of that answer. A typo in `match_color` empties
        // the table without changing the slot list the last one produced, and
        // the panel would go on naming the reason before it.
        if (sig === slotSig && color === colorSig) return;
        slotSig = sig;
        colorSig = color;
        // NOTHING is parsed here. A cell mid-edit that does not parse yet must
        // not stop a newly painted node from becoming a row.
        if (sig !== JSON.stringify(state.slots)) {
            state.table = retable(state.table, live);
            state.slots = live;
        }
        // The tree's counts moved. The pane keeps every row it already has —
        // one of them is holding the caret — and only grows the new one.
        renderTree();
        renderPane();
        drawStatus();
        refit();
    }

    // Every CATEGORY the order holds is a row, whether or not the project has
    // stored anything for it: "i need to test and edit all categories anyway
    // so there is no point in not having them there". The list comes off the
    // node feeding `recipe` — the same list that names a pick — and the
    // sentinel at its head ("All") names no recipe.
    //
    // An offered row that never took a value leaves again when the order moves
    // to another event. One that did is a recipe by then, and stays.
    let categorySig = null;
    function syncCategories() {
        if (!state.table) return;
        const source = focusBehind(liveGraph(), node, "recipe");
        const names = (source ? monthCategories(source) : [])
            .map((label) => recipeSlug(label))
            .filter(Boolean);
        const sig = names.join("\u0000");
        if (sig === categorySig) return;
        categorySig = sig;
        const wanted = new Set(names);
        const stored = storedColumns();
        const gone = state.table.columns.filter(
            (c) => !wanted.has(c) && untouched(c, stored));
        for (const c of gone) state.offered.delete(c);
        const left = dropColumns(state.table, gone);
        const grew = ensureColumns(state.table, names);
        for (const name of names) {
            if (!stored.has(name) && !setCount(name)) state.offered.add(name);
        }
        if (!left && !grew) return;
        // A row that went cannot stay selected; nothing was stored in it, so
        // there is nothing to lose by falling back to shared.
        if (gone.includes(picked())) pickRow(SHARED);
        renderTree();
        drawHead();
        renderPane();
        drawStatus();
        refit();
    }

    // The name on the `recipe` wire, as a recipe key. "" when nothing is
    // picked, or when the wire runs through a node the resolver cannot read.
    function activeColumn() {
        const raw = textValue(node, "recipe");
        return raw ? recipeSlug(raw) : "";
    }

    function syncActive() {
        if (!state.table) return;
        const next = activeColumn();
        if (next === active) return;
        // A wire that moves while he is typing must not take the pane with
        // it. The wire is still there on the next frame.
        if (caret()) return;
        active = next;
        // The pane follows the wire while it is on `shared` — nothing chosen —
        // or while it is still showing what the wire put there. A recipe he
        // picked by hand is his, and the wire leaves it alone.
        const follows = picked() === SHARED
            || (autoSelected !== null && picked() === autoSelected);
        // A name this project has no row for does not END the follow: the pane
        // stays where it is until the wire names one it can show. Dropping the
        // arm there is how one hop past an unlisted category left the pane
        // behind for the rest of the session.
        if (follows && next && state.table.columns.includes(next)) {
            pickRow(next);
            autoSelected = next;
        } else if (!follows) {
            autoSelected = null;
        }
        renderAll();
    }

    node._symAuto = auto;
    node._symRebuild = rebuild;
    const onDrawForeground = node.onDrawForeground;
    node.onDrawForeground = function () {
        resolveProject();
        syncSlots();
        syncCategories();
        syncActive();
        autoTick();
        return onDrawForeground?.apply(this, arguments);
    };

    // --- what a click does -------------------------------------------------
    // Point the wire at the recipe he picked. The `category` widget on the
    // node feeding `recipe` is what names it, so the label whose slug matches
    // goes in and the asset narrowing comes out -- a name chosen decides
    // nothing once the category is the pick. Answers what it did, for the
    // status line.
    function pointWireAt(column) {
        const source = focusBehind(liveGraph(), node, "recipe");
        if (!source) return "";
        const widget = source.widgets?.find((w) => w.name === "category");
        if (!widget) return "";
        // The labels come from the node's own list, never from the widget's
        // options: Task's `category` is a plain text widget its tree writes,
        // so reading options there found no label and the pick set nothing —
        // then auto read the old name off the wire and pulled the canvas back.
        // The MONTH's list, which is the one the sidebar's rows come from: a
        // row it offers has to be a row it can point the wire at.
        const label = monthCategories(source).find((l) => recipeSlug(l) === column);
        if (!label) return ` Nothing on ${source.title ?? source.type} is called ${column}.`;
        // A run is ONE event, and the rows are the whole MONTH's categories —
        // so a pick can name one the node's event does not hold. It moves to
        // the event that does, the same hop the tree makes: without it the
        // node sits on `runs 0` and the queue dies naming the event it looked
        // in. Checked before the `value !== label` guard below, because the
        // category can already be right while the event is not.
        const event = eventForCategory(source, label);
        if (event) {
            const feature = source.widgets?.find((w) => w.name === "feature");
            if (feature) {
                // The value, never the callback: the combo's own chained one
                // reaches the parse directly and answers without telling the
                // panel. `_symRefreshOrder` is the one path in.
                feature.value = event;
                source._symFocusAssets = [];
                source._symFocusCategories = [];
                source._symRefreshOrder?.({ explicit: true });
            }
        }
        if (widget.value !== label) {
            widget.value = label;
            widget.callback?.(label, undefined, source);
            // And the reference under it: a filename belongs to ONE asset, so
            // one left behind has the node naming a file it is not sending.
            // The tree clears both on every category it sets (`chooseCategory`)
            // — this is the one way in that does not go through the tree, and
            // on Task there is no combo callback to drop it for us.
            for (const name of ["asset", "ref"]) {
                const w = source.widgets?.find((x) => x.name === name);
                if (w && w.value) { w.value = ""; w.callback?.("", undefined, source); }
            }
        }
        if (event || widget.value === label) {
            source._symRenderFocus?.();
            source.setDirtyCanvas?.(true, true);
        }
        return "";
    }

    function choose(row) {
        const column = state.table && row !== PROJECT_ROW ? columnOf(row) : null;
        // What the canvas is actually ON, which is not always what is picked:
        // auto loads from the WIRE, and writing the picked column with values
        // the wire put there is how appliance-1x2 came to hold food's.
        const leaving = auto.last.name;
        // Before anything is drawn: `captureInto` would move the pick out from
        // under us, and a load would take the edits with it.
        if (column && leaving && leaving !== column) saveLeaving(leaving);
        pickRow(row);
        // Taking the recipe the wire names re-arms the follow; taking any
        // other one is his, and the wire leaves the pane where he put it.
        autoSelected = row === active ? row : null;
        renderFull();
        // Picking a recipe PULLS it: its values go onto the canvas, which is
        // the same thing the wire does when auto is on. The project row is the
        // project's own settings -- template, output, prefix -- and sets no
        // slot, so it stays a view. Last, so its status line is the one left.
        if (!column) return;
        const note = column === SHARED ? "" : pointWireAt(column);
        loadColumn(column);
        // The wire names this row now, so the canvas IS this recipe as far as
        // auto is concerned. `loadColumn` says so when it wrote something, but
        // a category with nothing stored and an empty `shared` has nothing to
        // write — and auto then reads the wire as a name it has never seen and
        // captures the canvas into it on the spot. Browsing the categories
        // would write one recipe per click.
        auto.last = { name: column,
                      sig: slotSignature(liveSlotValues(liveGraph(), matchColor())) };
        // And the pane goes on following the wire. `active` above is where the
        // wire WAS, and a pick MOVES it — so comparing against it disarmed the
        // follow on every click and the pane then sat on one recipe while the
        // Task walked through the others. What matters is whether the wire
        // names this row now: if it does, the two agree and the pane keeps up.
        if (activeColumn() === column) autoSelected = row;
        if (note) status(statusLine.textContent + note, false);
    }

    function captureInto(column) {
        const values = liveSlotValues(liveGraph(), matchColor());
        const found = Object.keys(values).length;
        if (!found) { noSlotsToast(matchColor()); return; }
        // Read BEFORE the snapshot moves: a node he changed and never painted
        // is a value going nowhere, and the capture is the moment to say so.
        const stray = strayChanges();
        captureColumn(state.table, state.slots, column, values);
        state.dirty = true;
        auto.last = { name: column, sig: slotSignature(values) };
        takeShot();
        if (picked() !== PROJECT_ROW) pickRow(column);
        renderAll();
        const kept = `Captured ${found} slots from the canvas into ${column}.`;
        status(stray.length
            ? `${kept} Not painted, so not kept: ${stray.join(", ")}.` : kept, false);
    }

    // The canvas WAS that column. If its slots have moved since, write them
    // back before another recipe lands on top of them -- the same thing auto
    // does on the way past, for a switch made by hand.
    function saveLeaving(column) {
        if (!state.table || !column || auto.last.name !== column) return;
        const values = liveSlotValues(liveGraph(), matchColor());
        if (!Object.keys(values).length) return;
        if (slotSignature(values) === auto.last.sig) return;
        captureColumn(state.table, state.slots, column, values);
        state.dirty = true;
        auto.last = { name: column, sig: slotSignature(values) };
        takeShot();
        save();
    }

    // A recipe named by hand: the same act as picking an asset in Task, with
    // the name typed instead of arriving on the wire.
    async function newRecipe() {
        if (!state.table) {
            toast("warn", "No project for this workflow", "Press new project first.");
            return;
        }
        const name = recipeSlug(await askForName("New recipe", ""));
        if (!name) return;
        if (state.table.columns.includes(name)) {
            toast("warn", `"${name}" is already a recipe`,
                  "Pick it in the sidebar, or give this one another name.");
            return;
        }
        saveLeaving(columnOf(picked()));
        captureInto(name);
        if (picked() !== name) { pickRow(name); autoSelected = null; renderFull(); }
        if (await save()) status(`Created ${name} from this canvas.`, false);
    }

    // In memory until save, exactly as the old `×` was: the file still holds
    // the recipe until `save project`.
    function dropRecipe() {
        const column = columnOf(picked());
        if (!state.table || column === SHARED) return;
        const { columns, rows } = state.table;
        const at = columns.indexOf(column);
        if (at < 0) return;
        columns.splice(at, 1);
        for (const row of rows) delete row.cells[column];
        if (autoSelected === column) autoSelected = null;
        pickRow(SHARED);
        state.dirty = true;
        renderFull();
        status(`Removed ${column}. Press save project to write it.`, false);
    }

    function renameRecipe() {
        const column = columnOf(picked());
        if (!state.table || column === SHARED) return;
        const { columns, rows } = state.table;
        const next = recipeSlug(nameField.value);
        if (!next || next === column) { nameField.value = column; return; }
        if (columns.includes(next)) {
            toast("warn", "Name taken", `There is already a "${next}" recipe.`);
            nameField.value = column;
            return;
        }
        columns[columns.indexOf(column)] = next;
        columns.splice(0, columns.length, SHARED,
                       ...sortedRecipes(columns.filter((c) => c !== SHARED)));
        for (const row of rows) { row.cells[next] = row.cells[column]; delete row.cells[column]; }
        if (autoSelected === column) autoSelected = next;
        pickRow(next);
        nameField.value = next;
        state.dirty = true;
        renderFull();
    }

    nameField.addEventListener("focus", () => { focused = nameField; });
    nameField.addEventListener("blur", () => { if (focused === nameField) focused = null; });
    nameField.addEventListener("change", () => renameRecipe());
    stopCanvas(loadButton).addEventListener("click", (e) => {
        e.stopPropagation();
        if (state.table) loadColumn(columnOf(picked()));
    });
    stopCanvas(captureButton).addEventListener("click", (e) => {
        e.stopPropagation();
        if (state.table) captureInto(columnOf(picked()));
    });
    stopCanvas(newButton).addEventListener("click", (e) => {
        e.stopPropagation();
        newRecipe();
    });
    stopCanvas(saveButton).addEventListener("click", (e) => { e.stopPropagation(); save(); });
    stopCanvas(generateButton).addEventListener("click", (e) => { e.stopPropagation(); generate(); });
    stopCanvas(deleteButton).addEventListener("click", (e) => { e.stopPropagation(); remove(); });
    autoBox.addEventListener("change", () => {
        const widget = node.widgets?.find((w) => w.name === "auto");
        if (!widget) return;
        widget.value = !!autoBox.checked;
        widget.callback?.(widget.value);
    });

    // An edit changes a count and the status line, and nothing else. Rebuilding
    // the pane here is what took the caret out mid-word. `drawHead` writes no
    // field that has the caret in it.
    function touched() {
        state.dirty = true;
        renderTree();
        drawHead();
        drawStatus();
    }

    // --- the tree ----------------------------------------------------------
    // Rows are built here rather than by `walkTree`: that function sorts every
    // level and derives parentage by splitting a slash-joined key, which is
    // right for a filesystem and wrong for hand-typed recipe names.
    function sidebarRows() {
        const rows = [];
        if (state.table) {
            rows.push({ kind: "project", rel: PROJECT_ROW, depth: 0,
                        label: state.name, hint: "The project: its base "
                            + "workflow, and the values every recipe takes. "
                            + "Its workflows are written beside the base, "
                            + "named after it." });
            const stored = storedColumns();
            for (const column of state.table.columns) {
                const shared = column === SHARED;
                const empty = untouched(column, stored);
                rows.push({
                    kind: shared ? "shared" : "recipe", rel: column, depth: 1,
                    label: column, count: setCount(column),
                    unit: shared ? "values" : "own", empty,
                    hint: shared ? "What every recipe takes unless it sets its own."
                        : empty ? `${column}: a category in the order, with nothing `
                            + "stored for it yet. Pick it, set the canvas, and it is a recipe."
                        : `${column}: only what differs from shared is stored.`,
                });
            }
        }
        // Every OTHER project, named with the workflow to open instead. A
        // project is RESOLVED, not chosen: this one is not the open workflow's
        // template, so it is not this canvas's to edit.
        const others = (state.projects ?? []).filter((p) => p.name !== state.name);
        if (others.length) {
            rows.push({ kind: "caption", rel: "other:", depth: 0,
                        label: "other projects" });
            for (const p of others) {
                rows.push({ kind: "other", rel: `other:${p.name}`, depth: 1,
                            label: `${p.name} — open ${p.template ?? "its template"}`,
                            hint: `Open ${p.template} to edit ${p.name}.` });
            }
        }
        return rows;
    }

    function renderTree() {
        const folded = shell.layout();
        tree.replaceChildren();
        if (folded) { refit(); return; }
        const rows = sidebarRows();
        if (!state.table) {
            tree.appendChild(emptyState(activeWorkflowPath()
                ? "No project has this workflow as its template."
                : "Save the workflow first."));
        }
        const held = picked();
        for (const row of rows) {
            const dim = row.kind === "other" || row.kind === "caption";
            const on = !dim && row.rel === held;
            const line = treeRow({
                kind: row.kind, rel: row.rel, depth: row.depth,
                tone: on ? HUB.selBg : "",
                // A category with nothing stored says so with a mark rather
                // than only a `· 0`: the list is the order's categories now,
                // and which of them you have been through is the one thing
                // you read it for.
                lead: row.empty
                    ? iconLead("newFile", { px: 11, color: on ? HUB.selInk : HUB.inkTertiary })
                    : undefined,
                labelColour: on ? HUB.selInk
                    : dim || row.empty ? HUB.inkTertiary
                    : `var(--input-text, ${HUB.ink})`,
                // The count rides in the label: `treeRow` hides its `actions`
                // until the pointer is on the row, and a badge you have to
                // hover for is a badge nobody reads.
                label: row.count === undefined ? row.label
                    : `${row.label} · ${row.count}`,
                onClick: dim ? undefined : () => choose(row.rel),
            });
            if (row.hint) line.title = row.hint;
            tree.appendChild(line);
        }
        // A rename or a removal must not leave the open hit list offering a
        // name that is gone.
        shell.search?.refresh?.();
        refit();
    }

    // --- the pane's head ---------------------------------------------------
    function drawHead() {
        const held = picked();
        const column = columnOf(held);
        const isProject = held === PROJECT_ROW;
        const isShared = !isProject && column === SHARED;
        const isRecipe = !isProject && !isShared;
        const have = !!state.table;

        nameField.style.display = have && isRecipe ? "" : "none";
        crumb.style.display = have && isRecipe ? "none" : "";
        // Nothing to remove on a category the file holds nothing for — the row
        // is the order's, and it goes when the order stops naming it.
        dropButton.style.display = have && isRecipe && !untouched(column)
            ? "" : "none";
        loadButton.style.display = have ? "" : "none";
        captureButton.style.display = have ? "" : "none";
        newButton.style.display = have ? "" : "none";
        headerBox.style.display = have && isProject ? "" : "none";
        countBadge.textContent = have
            ? `${setCount(column)} ${isShared || isProject ? "values" : "own"}` : "";

        if (!have) {
            crumb.textContent = "no project";
        } else if (isProject) {
            crumb.textContent = `${state.name} · project`;
        } else if (isShared) {
            crumb.textContent = "shared · what every recipe takes";
        } else if (nameField !== caret() && nameField.value !== column) {
            nameField.value = column;
        }
        loadButton.title = isShared || isProject
            ? "Put the shared values onto this canvas."
            : `Put ${column} onto this canvas (its own values over shared), to `
              + "adjust with the nodes' widgets and capture again.";
        captureButton.title = isShared || isProject
            ? "Read every slot off this canvas into shared."
            : `Read the slots off this canvas into ${column}: only what differs `
              + "from shared is kept.";

        const autoWidget = node.widgets?.find((w) => w.name === "auto");
        autoBox.checked = !!autoWidget?.value;
        for (const key of ["template"]) {
            const input = headerInputs[key];
            const value = state.table?.header?.[key] ?? "";
            if (input !== caret() && input.value !== value) input.value = value;
        }
    }

    // --- the pane's rows ---------------------------------------------------
    // The rows on screen, by slot key. A newly painted node is INSERTED beside
    // them and a gone one is taken out; every other row keeps the element it
    // had, because one of them is holding the caret.
    let paneFor = null;
    let paneRows = new Map();

    function buildRow(row, column) {
        const label = el("div", `flex:0 0 ${LABEL_W}px;min-width:0;${ONE_LINE}`
            + `padding:4px 0 0;color:${HUB.inkSubtle};`
            + "font-variant-ligatures:none;font-feature-settings:'calt' 0;",
            row.key);
        const box = el("div", "flex:1 1 auto;min-width:0;");
        const tools = el("div", "flex:0 0 auto;display:flex;align-items:center;"
            + "padding-top:2px;");
        const wrap = el("div", "display:flex;gap:8px;align-items:flex-start;"
            + `padding:3px 0;border-bottom:1px solid ${HUB.hairline};`);
        wrap._symRow = row.key;
        wrap.append(label, box, tools);

        const wipe = iconButton("clear", "Clear — take the inherited value", () => {
            row.cells[column] = "";
            touched();
            fill();
        }, { px: 11 });
        tools.appendChild(wipe);

        // What is drawn right now, so a refresh can tell "the same fields with
        // new text" from "a different editor entirely".
        let shape = "";
        let fields = [];

        const inherited = () => (column === SHARED ? "" : (row.cells[SHARED] ?? ""));

        function shapeNow() {
            const slot = slotOf(row.key);
            const own = row.cells[column] ?? "";
            if (!dictRow(slot, own, inherited())) return "text";
            return `dict:${dictNames(slot, own, inherited()).join("\u0000")}`;
        }

        function dictNames(slot, own, inh) {
            const ownObj = objectCell(own) ?? {};
            const baseObj = objectCell(inh) ?? {};
            const names = Object.keys(plainObject(slot?.default) ?? {});
            for (const name of Object.keys({ ...ownObj, ...baseObj })) {
                if (!names.includes(name)) names.push(name);
            }
            return names;
        }

        function fill() {
            const slot = slotOf(row.key);
            fields = [];
            box.replaceChildren();
            shape = shapeNow();
            label.title = slot?.kind === "toggle" ? "true or false"
                : `Template: ${cellText(slot?.default)}`
                  + (slot?.widgets > 1 && !shape.startsWith("dict")
                      ? ` (a JSON list sets all ${slot.widgets} widgets)` : "");
            if (shape.startsWith("dict")) {
                const grid = el("div", "display:grid;"
                    + "grid-template-columns:minmax(90px, 0.45fr) 1fr;gap:3px;"
                    + "align-items:center;");
                for (const name of dictNames(slot, row.cells[column] ?? "", inherited())) {
                    grid.appendChild(el("div", `padding:2px 3px;color:${HUB.inkSubtle};`
                        + `font:11px ${HUB.mono};`, name));
                    const field = stopCanvas(el("input", inputCss + "width:100%;"));
                    field._symCell = { key: row.key, name };
                    const read = () => {
                        const own = objectCell(row.cells[column]) ?? {};
                        const base = objectCell(inherited()) ?? {};
                        const def = plainObject(slotOf(row.key)?.default) ?? {};
                        return {
                            value: name in own ? cellText(own[name]) : "",
                            placeholder: name in base ? cellText(base[name])
                                : cellText(def[name]),
                        };
                    };
                    const at = read();
                    field.value = at.value;
                    field.placeholder = at.placeholder;
                    field.addEventListener("focus", () => { focused = field; });
                    field.addEventListener("blur", () => { if (focused === field) focused = null; });
                    field.addEventListener("input", () => {
                        row.cells[column] = dictCellUpdate(row.cells[column], name, field.value);
                        touched();
                        arm();
                    });
                    fields.push({ el: field, read });
                    grid.appendChild(field);
                }
                box.appendChild(grid);
            } else {
                const cell = stopCanvas(el("textarea", cellCss));
                cell.rows = 1;
                cell._symCell = { key: row.key, name: null };
                const read = () => ({
                    value: row.cells[column] ?? "",
                    placeholder: inherited() || cellText(slotOf(row.key)?.default) || "",
                });
                const at = read();
                cell.value = at.value;
                cell.placeholder = at.placeholder;
                cell.addEventListener("input", () => {
                    row.cells[column] = cell.value;
                    touched();
                    arm();
                });
                cell.addEventListener("focus", () => {
                    focused = cell;
                    if (cell.value.length > 60 || cell.placeholder.length > 60) cell.rows = 4;
                });
                cell.addEventListener("blur", () => {
                    if (focused === cell) focused = null;
                    cell.rows = 1;
                });
                fields.push({ el: cell, read });
                box.appendChild(cell);
            }
            arm();
        }

        // The clear button is only a control while there is something of its
        // own to clear; an empty cell already takes the inherited value.
        function arm() {
            const own = String(row.cells[column] ?? "").trim();
            wipe.style.visibility = own ? "visible" : "hidden";
            wipe.title = column === SHARED
                ? "Clear — take the template's own value"
                : "Clear — take the shared value";
        }

        function holdsFocus() {
            const at = caret();
            return !!at && fields.some((f) => f.el === at);
        }

        function refresh() {
            if (shapeNow() !== shape) {
                // Never pull the editor out from under the caret; the shape
                // is re-read on the next refresh.
                if (!holdsFocus()) fill();
                else arm();
                return;
            }
            for (const field of fields) {
                if (field.el === caret()) continue;
                const at = field.read();
                if (field.el.value !== at.value) field.el.value = at.value;
                if (field.el.placeholder !== at.placeholder) {
                    field.el.placeholder = at.placeholder;
                }
            }
            arm();
        }

        fill();
        return { wrap, refresh, holdsFocus };
    }

    // Why the table is empty, rather than an empty table: a colour that is not
    // a colour and a canvas with nothing painted look the same.
    function paintProblem() {
        const color = matchColor();
        if (!color) return "match_color is empty — type a colour, then paint the nodes a recipe should set.";
        if (!colorMatcher(color)) return `match_color is "${color}", which is not a colour. Use a palette name or a hex.`;
        if (!state.table?.rows?.length) return `Nothing on this canvas is painted ${color}. Paint a node and it becomes a row.`;
        return "";
    }

    // Every row goes. The caret's field is one of them, and nothing else will
    // tell us it left.
    function dropRows() {
        if (focused && [...paneRows.values()].some((b) => b.holdsFocus())) {
            focused = null;
        }
        paneRows = new Map();
    }

    function renderPane(rebuild = false) {
        const held = picked();
        const column = columnOf(held);
        if (!state.table) {
            paneFor = null;
            dropRows();
            // The panel cannot capture into a project it does not have, and
            // saying so is what `capture recipe` reads off this.
            node._symCapture = null;
            rowsBox.replaceChildren(emptyState(activeWorkflowPath()
                ? "No project for this workflow yet. Press new project."
                : "Save the workflow first — a project takes it as its template."));
            return;
        }
        // Set AFTER the no-table return: that is what makes `capture recipe`
        // say "No project for this workflow" instead of doing nothing.
        node._symCapture = (col) => captureInto(col);

        const rows = state.table.rows;
        if (!rows.length) {
            paneFor = held;
            dropRows();
            rowsBox.replaceChildren(emptyState(paintProblem()
                || "Nothing painted on this canvas is a slot."));
            return;
        }
        if (rebuild || paneFor !== held || !paneRows.size) {
            paneFor = held;
            dropRows();
            rowsBox.replaceChildren();
            for (const row of rows) {
                const built = buildRow(row, column);
                paneRows.set(row.key, built);
                rowsBox.appendChild(built.wrap);
            }
            return;
        }
        // Same row selected: keep every field that is still a field. A slot
        // that came or went moves one row; it must not move the others.
        const want = rows.map((r) => r.key);
        for (const [key, built] of [...paneRows]) {
            if (want.includes(key)) continue;
            built.wrap.remove();
            paneRows.delete(key);
        }
        for (let i = 0; i < rows.length; i += 1) {
            const built = paneRows.get(rows[i].key);
            if (built) { built.refresh(); continue; }
            // Before the first row after this one that is already drawn, so a
            // new slot lands where the slot list puts it.
            let before = null;
            for (let j = i + 1; j < rows.length && !before; j += 1) {
                before = paneRows.get(rows[j].key)?.wrap ?? null;
            }
            const made = buildRow(rows[i], column);
            paneRows.set(rows[i].key, made);
            if (before) rowsBox.insertBefore(made.wrap, before);
            else rowsBox.appendChild(made.wrap);
        }
    }

    function drawStatus() {
        if (!state.table) return;
        const { columns, rows } = state.table;
        // The categories the order holds are rows, not recipes: counted apart,
        // so "3 recipes" still means three blocks in the file.
        const real = realColumns().filter((c) => c !== SHARED);
        const waiting = columns.length - 1 - real.length;
        const activeNote = !active ? ""
            : real.includes(active) ? ` · on ${active}` : ` · ${active} has no recipe yet`;
        const emptyNote = waiting
            ? ` · ${waiting} ${waiting === 1 ? "category" : "categories"} empty` : "";
        const paint = paintProblem();
        const stranded = strandedKeys();
        const note = stranded.length
            ? ` The saved template has no slot for ${stranded.join(", ")} — save the workflow,`
              + " or generate drops them."
            : "";
        if (paint) status(paint, false);
        else status(state.dirty ? `Unsaved edits.${activeNote}${note}`
            : `${state.name}: ${real.length} recipes, ${rows.length} slots.`
              + `${activeNote}${emptyNote}${note}`,
            !stranded.length);
        if (!state.dirty && !real.length) {
            status(columns.length === 1
                ? "No recipes yet. Set the canvas, name a recipe, press Capture."
                : "No recipes yet. Pick a category, set the canvas, press capture.");
        }
    }

    // The tree and the pane are separate paths on purpose: a slot-list change
    // redraws the tree and RECONCILES the pane, a change of which row is
    // selected rebuilds it.
    function renderAll() {
        renderTree();
        drawHead();
        renderPane();
        drawStatus();
        refit();
    }

    function renderFull() {
        renderTree();
        drawHead();
        renderPane(true);
        drawStatus();
        refit();
    }

    node._symRecipe = { load, save, generate, startNew, remove, resolveProject,
                        render: renderFull, choose };
    renderFull();
    resolveProject();
}

function setupRecipeNode(node) {
    node.isVirtualNode = true;
    const autoToggle = node.addWidget("toggle", "auto", false, (value) => {
        const auto = node._symAuto;
        if (!auto) return;
        auto.on = !!value;
        auto.last = { name: null, sig: null };
        if (auto.timer) { clearTimeout(auto.timer); auto.timer = null; }
    });
    const button = (label, action) => {
        const widget = node.addWidget("button", label, null, action, { serialize: false });
        widget.serializeValue = () => undefined;
    };
    button("new project", () => node._symRecipe?.startNew());
    button("capture recipe", () => {
        const raw = textValue(node, "recipe");
        if (raw === null) { toast("warn", "recipe is wired to a node with no typed text", "Type it, or connect a text node."); return; }
        const column = recipeSlug(raw);
        if (!column) { toast("warn", "Name the recipe first", "Type it in recipe, or connect a text node."); return; }
        if (!node._symCapture) { toast("warn", "No project for this workflow", "Press new project first."); return; }
        node._symCapture(column);
    });
    button("save project", () => node._symRecipe?.save());
    button("generate workflows", () => node._symRecipe?.generate());
    button("delete project", () => node._symRecipe?.remove());
    // Every widget the panel's head drives is hidden but PRESENT: a saved
    // workflow restores widget values BY POSITION, and dropping one would land
    // `auto`'s false on `match_color`. `recipe` and `match_color` stay
    // visible — they are what the panel cannot tell you.
    hideWidget(autoToggle);
    for (const name of ["new project", "capture recipe", "save project",
                        "generate workflows", "delete project"]) {
        hideWidget(node.widgets?.find((w) => w.name === name));
    }
    recipePanel(node);
    const applyToggle = () => { if (node._symAuto) node._symAuto.on = !!autoToggle.value; };
    applyToggle();
    // A workflow saved before match_color existed has one widget value fewer,
    // so the values land one slot across and match_color gets the old toggle's
    // boolean. Anything that is not a colour goes back to the default.
    const fixColor = () => {
        const widget = node.widgets?.find((w) => w.name === "match_color");
        if (!widget) return;
        const value = widget.value;
        if (value === "" || (typeof value === "string" && colorMatcher(value))) return;
        widget.value = "purple";
    };
    fixColor();
    const onConfigure = node.onConfigure;
    node.onConfigure = function () {
        onConfigure?.apply(this, arguments);
        applyToggle();
        fixColor();
        node._symRecipe?.render?.();
    };
    if (node.size[1] < 320) node.setSize?.([Math.max(node.size[0], RECIPE_MIN_W), 320]);
}

registerSymbioticaExtension(app, {
    name: "symbiotica.recipes",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            setupRecipeNode(this);
        };
    },
});
