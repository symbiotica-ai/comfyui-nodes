// ABOUTME: Workflow recipes — the Recipes node: pick or start a project, edit its
// ABOUTME: shared values and one recipe per asset type, save, generate.

// A project is one template workflow plus a table of values. The rows come
// from the template itself (every node titled `recipe:<key>`), so a new slot
// on the canvas is a new row here the next time the project is opened. The
// columns are `shared` (what every recipe takes) and one per recipe. An empty
// cell is an absent key: the recipe then takes the shared value, or the
// template's own.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { HUB, ghostButtonCss, injectHubStyles } from "./hub_theme.js";
import { el, pinPanelWidth } from "./browser_chrome.js";

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
    const input = index >= 0 ? node.inputs[index] : null;
    if (!input) return undefined;
    if (input.link != null) {
        const link = graph.links?.[input.link];
        const origin = link ? graph.getNodeById?.(link.origin_id) : null;
        if (!origin) return null;
        return nodeText(graph, origin, link.origin_slot ?? 0, depth + 1);
    }
    const value = widgetValue(node, input.widget?.name ?? inputName);
    return value === undefined ? undefined : String(value);
}

function nodeText(graph, node, slot, depth) {
    if (depth > 12) return null;
    const type = String(node.type ?? "");
    if (STRING_NODES.has(type)) {
        const widget = node.widgets?.find((w) => typeof w.value === "string");
        return widget ? String(widget.value) : null;
    }
    if (type === "SymbioticaAssetFocus") {
        const output = node.outputs?.[slot]?.name;
        // The dropdown holds the recipe label (`Appliance 1x2`); the plain
        // `category` output is that without its size, and "All" names nothing.
        if (output === "category" || output === "category_recipe") {
            const picked = String(widgetValue(node, "category") ?? "").trim();
            if (!picked || picked === "All") return null;
            return output === "category" ? picked.replace(/\s+\d+x\d+$/i, "") : picked;
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
    if (PASS_THROUGH.has(type)) {
        const first = node.inputs?.[0]?.name;
        return first ? inputText(graph, node, first, depth) ?? null : null;
    }
    return null;
}

// The text arriving on one of this node's inputs: typed, or resolved live
// through the wire. null when wired to something the resolver cannot read.
export function resolveText(graph, node, inputName) {
    const value = inputText(graph, node, inputName, 0);
    return value == null ? null : String(value).trim();
}

const liveGraph = () => app.canvas?.graph ?? app.graph;
const textValue = (node, name) => resolveText(liveGraph(), node, name);

// What auto does when the name on the wire is `next` and the canvas was on
// `prev` (changed = slot values moved since that recipe was last written):
// save what you leave, then load the recipe you arrive at, or create it.
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
    const keys = slots.map((s) => s.key);
    const orphans = [];
    for (const column of columns) {
        for (const key of Object.keys(valuesOf(column))) {
            if (!keys.includes(key) && !orphans.includes(key)) orphans.push(key);
        }
    }
    const rows = [...keys.map((key) => ({ key, orphan: false })), ...orphans.map((key) => ({ key, orphan: true }))];
    for (const row of rows) {
        row.cells = {};
        for (const column of columns) row.cells[column] = cellText(valuesOf(column)[row.key]);
    }
    return {
        header: {
            template: project?.template ?? "",
            output: project?.output ?? "",
            workflow_prefix: project?.workflow_prefix ?? "",
        },
        columns,
        rows,
    };
}

export function tableToProject(base, table, slots) {
    const byKey = Object.fromEntries(slots.map((s) => [s.key, s]));
    const out = { ...base, template: table.header.template, workflow_prefix: table.header.workflow_prefix };
    if (table.header.output) out.output = table.header.output;
    else delete out.output;
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
    out.recipes = {};
    for (const column of table.columns) if (column !== SHARED) out.recipes[column] = columnValues[column];
    return out;
}

// The values the open canvas holds for every slot, in the shape a recipe
// stores them: a toggle's on/off, a subgraph instance's promoted widgets (the
// wired ones left out), else the node's first widget.
function liveSlotValues(graph) {
    const values = {};
    for (const node of graph?.nodes ?? []) {
        const title = String(node.title ?? "");
        if (!title.startsWith("recipe:")) continue;
        const key = title.slice("recipe:".length).replace(/\?\s*$/, "").trim();
        if (!key || key in values) continue;
        if (title.trimEnd().endsWith("?")) {
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
        } else {
            const widget = (node.widgets ?? []).find((w) => w.type !== "button");
            if (widget) values[key] = widget.value;
        }
    }
    return values;
}

// The slots the open canvas carries, in the shape the server describes a
// saved template's: a rename, an added or a deleted recipe: node shows at
// once instead of after the workflow is saved and the project reopened.
export function liveSlots(graph) {
    const out = {};
    for (const node of graph?.nodes ?? []) {
        const title = String(node.title ?? "");
        if (!title.startsWith("recipe:")) continue;
        const key = title.slice("recipe:".length).replace(/\?\s*$/, "").trim();
        if (!key || key in out) continue;
        const widgets = (node.widgets ?? []).filter((w) => w.type !== "button");
        if (title.trimEnd().endsWith("?")) {
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
        } else {
            out[key] = { key, kind: "scalar", default: widgets[0]?.value ?? null, widgets: widgets.length };
        }
    }
    return Object.keys(out).sort().map((key) => out[key]);
}

// The table again under a changed slot list, the edits in progress kept.
export function retable(project, table, slots, nextSlots) {
    return projectToTable(tableToProject(project, table, slots), nextSlots);
}

// Write captured values into one column. A recipe takes only what differs
// from shared, so a later shared edit still reaches it; shared takes
// everything.
export function captureColumn(table, slots, column, values) {
    if (!table.columns.includes(column)) {
        table.columns.splice(0, table.columns.length,
            SHARED, ...sortedRecipes([...table.columns.filter((c) => c !== SHARED), column]));
        for (const row of table.rows) row.cells[column] = "";
    }
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
export function applyValuesToNodes(nodes, values) {
    const applied = [];
    const seen = new Set();
    for (const node of nodes ?? []) {
        const title = String(node.title ?? "");
        if (!title.startsWith("recipe:")) continue;
        const key = title.slice("recipe:".length).replace(/\?\s*$/, "").trim();
        if (!key || !(key in values)) continue;
        const value = values[key];
        const widgets = (node.widgets ?? []).filter((w) => w.type !== "button");
        if (title.trimEnd().endsWith("?")) {
            node.mode = value ? 0 : 4;
        } else if (value && typeof value === "object" && !Array.isArray(value)) {
            for (const [name, item] of Object.entries(value)) {
                const widget = widgets.find((w) => w.name === name);
                if (widget) widget.value = item;
            }
        } else if (Array.isArray(value)) {
            value.forEach((item, index) => { if (widgets[index]) widgets[index].value = item; });
        } else if (widgets[0]) {
            widgets[0].value = value;
        }
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
    return { summary, detail: detail + note };
}

// ----------------------------------------------------------------- panel --


const inputCss = "box-sizing:border-box;min-width:0;padding:3px 5px;"
    + `font:11px ${HUB.mono};background:var(--comfy-input-bg, transparent);`
    + `color:var(--input-text, ${HUB.ink});border:1px solid ${HUB.hairline};border-radius:${HUB.radius.sm};`;
const cellCss = inputCss + "width:100%;resize:vertical;min-height:24px;line-height:1.35;";

function stopCanvas(node) {
    node.addEventListener("pointerdown", (e) => e.stopPropagation());
    node.addEventListener("keydown", (e) => e.stopPropagation());
    node.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });
    return node;
}

function recipePanel(node) {
    injectHubStyles();
    const container = el("div", "box-sizing:border-box;width:100%;height:100%;overflow:auto;");
    const body = el("div", `box-sizing:border-box;padding:2px;font:11px ${HUB.font};color:var(--input-text, ${HUB.ink});`);
    container.appendChild(body);
    container.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });
    node.addDOMWidget("recipe_panel", "sym_recipe", container, {
        serialize: false, hideOnZoom: true,
        getMinHeight: () => 60,
    });
    node.size[0] = Math.max(node.size[0], 560);
    const syncPanelWidth = pinPanelWidth(node, container);
    const refit = () => requestAnimationFrame(() => {
        syncPanelWidth();
        node.setDirtyCanvas?.(true, true);
    });

    // What is on screen: the project as loaded, the template's slots, and the
    // table the person is editing. `dirty` is unsaved edits.
    const state = { name: null, project: null, slots: [], table: null, dirty: false };
    // Which sections are open. A freshly opened project shows its headers only.
    const expanded = new Set();
    let busy = false;

    function status(text, subtle = true) {
        statusLine.textContent = text;
        statusLine.style.color = subtle ? HUB.inkSubtle : HUB.ink;
    }

    const statusLine = el("div", `padding:4px 3px;color:${HUB.inkSubtle};`);

    function collect() {
        return tableToProject(state.project, state.table, state.slots);
    }

    // Which project this canvas is: looked up by the open workflow's path,
    // again whenever that path changes (a Save As, another tab).
    let resolvedFor = undefined;
    async function resolveProject() {
        const path = activeWorkflowPath();
        if (path === resolvedFor) return;
        resolvedFor = path;
        let name = null;
        try {
            name = projectForWorkflow(await listProjects(), path);
        } catch (err) {
            status(`Could not list projects: ${String(err?.message ?? err)}`, false);
            return;
        }
        if (!name) {
            state.name = null; state.project = null; state.slots = []; state.table = null; state.dirty = false;
            render();
            status(path ? "No project has this workflow as its template. Press new project." : "Save the workflow first.", false);
            return;
        }
        if (name !== state.name) await load(name);
    }

    async function load(name) {
        try {
            const { project, slots } = await readProject(name);
            state.name = name;
            state.project = project;
            state.slots = slots;
            state.table = projectToTable(project, slots);
            state.dirty = false;
            slotSig = null;
            expanded.clear();
            render();
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
            return true;
        } catch (err) {
            toast("error", "Save failed", String(err?.message ?? err));
            return false;
        }
    }

    async function generate() {
        if (busy) return;
        busy = true;
        try {
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
            state.slots = [];
            state.table = null;
            state.dirty = false;
            resolvedFor = undefined;
            render();
            toast("info", `Deleted project "${name}"`, "Its generated workflows are still in the workflows folder.");
        } catch (err) {
            toast("error", "Delete failed", String(err?.message ?? err));
        }
    }

    async function startNew() {
        const template = activeWorkflowPath();
        if (!template) { toast("warn", "Save the workflow first", "A new project takes the open, saved workflow as its template."); return; }
        try {
            const { name, project, slots } = await postJson("/symbiotica/recipes/new", { template });
            state.name = name;
            state.project = project;
            state.slots = slots;
            state.table = projectToTable(project, slots);
            state.dirty = false;
            slotSig = null;
            expanded.clear();
            expanded.add(SHARED);
            resolvedFor = template;
            render();
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
        const graph = app.canvas?.graph ?? app.graph;
        const report = applyValuesToNodes(graph?.nodes ?? [], values);
        if (!report.applied.length) {
            toast("warn", "No recipe slots on this canvas", "Open the template workflow, the one with recipe: nodes.");
            return;
        }
        app.graph?.setDirtyCanvas(true, true);
        const missing = report.missing.length ? ` Not on this canvas: ${report.missing.join(", ")}.` : "";
        status(`Loaded ${column} onto the canvas (${report.applied.length} slots).${missing}`, false);
    }

    // ------------------------------------------------------------ auto --
    // Watched on every repaint, like the Module node's rows. `last` is the
    // recipe the canvas is on and the slot signature it was last written with.
    const auto = { last: { name: null, sig: null }, timer: null, busy: false, on: false };
    const slotSignature = (values) => JSON.stringify(values);

    async function autoTick() {
        if (!auto.on || auto.busy || !state.table) return;
        const graph = liveGraph();
        const values = liveSlotValues(graph);
        if (!Object.keys(values).length) return;
        const sig = slotSignature(values);
        const raw = textValue(node, "recipe");
        const next = raw ? recipeSlug(raw) : "";
        const prev = { name: auto.last.name, changed: auto.last.sig !== null && auto.last.sig !== sig };
        const actions = autoDecision(prev, next, state.table.columns);
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
                    render();
                    status(`auto: ${verb === "save" ? "saved" : "created"} ${name}`, false);
                } else if (verb === "load") {
                    loadColumn(name);
                    auto.last = { name, sig: slotSignature(liveSlotValues(liveGraph())) };
                    status(`auto: loaded ${name} onto the canvas`, false);
                }
            }
        } finally {
            auto.busy = false;
        }
    }

    // The slot list follows the canvas; the saved template's stands in only
    // while the canvas has no recipe: nodes (or a cell cannot be parsed).
    let slotSig = null;
    function syncSlots() {
        if (!state.table) return;
        const live = liveSlots(liveGraph());
        if (!live.length) return;
        const sig = JSON.stringify(live);
        if (sig === slotSig) return;
        slotSig = sig;
        if (sig === JSON.stringify(state.slots)) return;
        try {
            state.table = retable(state.project, state.table, state.slots, live);
        } catch {
            return;
        }
        state.slots = live;
        render();
    }

    node._symAuto = auto;
    const onDrawForeground = node.onDrawForeground;
    node.onDrawForeground = function () {
        resolveProject();
        syncSlots();
        autoTick();
        return onDrawForeground?.apply(this, arguments);
    };

    function headerField(label, key, placeholder) {
        const wrap = el("label", "display:flex;align-items:center;gap:6px;min-width:0;flex:1 1 30%;");
        wrap.append(el("span", `flex:0 0 auto;color:${HUB.inkSubtle};`, label));
        const input = stopCanvas(el("input", inputCss + "flex:1 1 auto;width:100%;"));
        input.value = state.table.header[key] ?? "";
        input.placeholder = placeholder;
        input.addEventListener("input", () => { state.table.header[key] = input.value; state.dirty = true; });
        wrap.appendChild(input);
        return wrap;
    }

    function render() {
        body.replaceChildren();
        if (!state.table) {
            body.appendChild(el("div", `padding:6px 3px;color:${HUB.inkSubtle};`,
                "No project for this workflow yet. Open the base workflow and press new project."));
            body.appendChild(statusLine);
            refit();
            return;
        }

        const header = el("div", "display:flex;gap:8px;flex-wrap:wrap;padding:2px 0 6px;"
            + `border-bottom:1px solid ${HUB.hairline};margin-bottom:6px;`);
        header.append(headerField("template", "template", "folder/template.json"),
            headerField("output", "output", "folder (default: the template's)"),
            headerField("prefix", "workflow_prefix", "dev-imperia-bakery-"));
        body.appendChild(header);

        const { columns, rows } = state.table;
        const byKey = Object.fromEntries(state.slots.map((s) => [s.key, s]));
        const setCount = (column) => rows.filter((row) => (row.cells[column] ?? "").trim()).length;

        const parsedDict = (text) => {
            const parsed = parseJson(String(text ?? "").trim() || "{}");
            return parsed.ok && parsed.value && typeof parsed.value === "object" && !Array.isArray(parsed.value)
                ? parsed.value : {};
        };

        // One slot inside a section: a label and the value field. A subgraph
        // slot gets one field per widget; the rest a single field. The
        // placeholder is what the recipe inherits (shared, else template).
        function slotRows(section, column, row) {
            const slot = byKey[row.key];
            const inherited = column === SHARED ? "" : (row.cells[SHARED] ?? "");
            const label = el("div", "padding:4px 3px 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;"
                + (row.orphan ? `color:${HUB.inkSubtle};text-decoration:line-through;` : ""), row.key);
            label.title = row.orphan
                ? "The template has no slot with this name any more; the value is ignored."
                : slot?.kind === "toggle" ? "true or false"
                : `Template: ${cellText(slot?.default)}${slot?.widgets > 1 && slot?.kind !== "dict" ? ` (a JSON list sets all ${slot.widgets} widgets)` : ""}`;
            section.appendChild(label);
            if (slot?.kind === "dict") {
                const own = parsedDict(row.cells[column]);
                const base = parsedDict(inherited);
                const names = Object.keys(slot.default ?? {});
                for (const name of Object.keys({ ...own, ...base })) if (!names.includes(name)) names.push(name);
                const sub = el("div", "display:grid;grid-template-columns:minmax(90px, 0.5fr) 1fr;gap:3px;align-items:center;");
                for (const name of names) {
                    sub.appendChild(el("div", `padding:2px 3px;color:${HUB.inkSubtle};font:11px ${HUB.mono};`, name));
                    const field = stopCanvas(el("input", inputCss + "width:100%;"));
                    field.value = name in own ? cellText(own[name]) : "";
                    field.placeholder = name in base ? cellText(base[name]) : cellText(slot.default?.[name]);
                    field.addEventListener("input", () => {
                        row.cells[column] = dictCellUpdate(row.cells[column], name, field.value);
                        state.dirty = true;
                    });
                    sub.appendChild(field);
                }
                section.appendChild(sub);
                return;
            }
            const cell = stopCanvas(el("textarea", cellCss));
            cell.rows = 1;
            cell.value = row.cells[column] ?? "";
            cell.placeholder = inherited || cellText(slot?.default) || "";
            cell.addEventListener("input", () => { row.cells[column] = cell.value; state.dirty = true; });
            cell.addEventListener("focus", () => { if (cell.value.length > 60 || cell.placeholder.length > 60) cell.rows = 4; });
            cell.addEventListener("blur", () => { cell.rows = 1; });
            section.appendChild(cell);
        }

        node._symCapture = (column) => captureInto(column);

        function captureInto(column) {
            const values = liveSlotValues(app.canvas?.graph ?? app.graph);
            const found = Object.keys(values).length;
            if (!found) { toast("warn", "No recipe slots on this canvas", "Open the template workflow, the one with recipe: nodes."); return; }
            captureColumn(state.table, state.slots, column, values);
            state.dirty = true;
            expanded.add(column);
            render();
            status(`Captured ${found} slots from the canvas into ${column}.`, false);
        }

        columns.forEach((column, index) => {
            const isShared = column === SHARED;
            const open = expanded.has(column);
            const box = el("div", `border:1px solid ${HUB.hairline};border-radius:${HUB.radius.md};margin:0 0 6px;`);
            const head = el("div", "display:flex;align-items:center;gap:6px;padding:4px 6px;min-width:0;");
            const toggle = el("button", ghostButtonCss + "padding:1px 6px;flex:0 0 auto;border:none;", open ? "▾" : "▸");
            toggle.title = open ? "Collapse" : "Expand";
            stopCanvas(toggle).addEventListener("click", (e) => {
                e.stopPropagation();
                if (open) expanded.delete(column); else expanded.add(column);
                render();
            });
            head.appendChild(toggle);
            if (isShared) {
                const title = el("div", "flex:1 1 auto;min-width:0;", "shared");
                title.title = "What every recipe takes unless it sets its own.";
                head.appendChild(title);
            } else {
                const name = stopCanvas(el("input", inputCss + "flex:1 1 120px;"));
                name.value = column;
                name.title = "Recipe: also the suffix of the generated workflow's name.";
                name.addEventListener("change", () => {
                    const next = recipeSlug(name.value);
                    if (!next || next === column) { name.value = column; return; }
                    if (columns.includes(next)) { toast("warn", "Name taken", `There is already a "${next}" recipe.`); name.value = column; return; }
                    columns[index] = next;
                    columns.splice(0, columns.length, SHARED, ...sortedRecipes(columns.filter((c) => c !== SHARED)));
                    for (const row of rows) { row.cells[next] = row.cells[column]; delete row.cells[column]; }
                    if (expanded.delete(column)) expanded.add(next);
                    state.dirty = true;
                    render();
                });
                head.appendChild(name);
            }
            const count = setCount(column);
            head.appendChild(el("div", `flex:0 0 auto;color:${HUB.inkSubtle};font:11px ${HUB.mono};`,
                isShared ? `${count} values` : `${count} own`));
            const load = el("button", ghostButtonCss + "padding:1px 6px;flex:0 0 auto;", "load");
            load.title = isShared ? "Put the shared values onto this canvas."
                : `Put ${column} onto this canvas (its own values over shared), to adjust with the nodes' widgets and capture again.`;
            stopCanvas(load).addEventListener("click", (e) => { e.stopPropagation(); loadColumn(column); });
            const capture = el("button", ghostButtonCss + "padding:1px 6px;flex:0 0 auto;", "capture");
            capture.title = isShared ? "Read every slot off this canvas into shared."
                : `Read the slots off this canvas into ${column}: only what differs from shared is kept.`;
            stopCanvas(capture).addEventListener("click", (e) => { e.stopPropagation(); captureInto(column); });
            head.append(load, capture);
            if (!isShared) {
                const remove = el("button", ghostButtonCss + "padding:1px 6px;flex:0 0 auto;", "×");
                remove.title = `Remove ${column}`;
                stopCanvas(remove).addEventListener("click", (e) => {
                    e.stopPropagation();
                    columns.splice(index, 1);
                    for (const row of rows) delete row.cells[column];
                    expanded.delete(column);
                    state.dirty = true;
                    render();
                });
                head.appendChild(remove);
            }
            box.appendChild(head);
            if (open) {
                const section = el("div", "display:grid;grid-template-columns:minmax(110px, 0.35fr) 1fr;gap:3px;"
                    + `align-items:start;padding:2px 6px 6px;border-top:1px solid ${HUB.hairline};`);
                for (const row of rows) slotRows(section, column, row);
                box.appendChild(section);
            }
            body.appendChild(box);
        });

        body.appendChild(statusLine);
        status(state.dirty ? "Unsaved edits." : `${state.name}: ${columns.length - 1} recipes, ${rows.length} slots.`);
        if (!state.dirty && columns.length === 1) status("No recipes yet. Set the canvas, name a recipe, press Capture.");
        refit();
    }

    node._symRecipe = { load, save, generate, startNew, remove, resolveProject };
    render();
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
    recipePanel(node);
    const applyToggle = () => { if (node._symAuto) node._symAuto.on = !!autoToggle.value; };
    applyToggle();
    const onConfigure = node.onConfigure;
    node.onConfigure = function () {
        onConfigure?.apply(this, arguments);
        applyToggle();
    };
    if (node.size[1] < 320) node.setSize?.([Math.max(node.size[0], 560), 320]);
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
