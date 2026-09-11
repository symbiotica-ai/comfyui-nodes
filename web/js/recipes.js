// ABOUTME: Workflow recipes — the Recipe node: pick or start a recipe, edit it as
// ABOUTME: a table (a row per template slot, a column per category), save, generate.

// A recipe is one template workflow plus a table of values. The rows come from
// the template itself (every node titled `recipe:<key>`), so a new slot on the
// canvas is a new row here the next time the recipe is opened. The columns are
// `game` (what every category shares) and one per category. An empty cell is
// an absent key: the category then takes the game value, or the template's own.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { HUB, ghostButtonCss, injectHubStyles } from "./hub_theme.js";
import { el, pinPanelWidth } from "./browser_chrome.js";

const NODE_CLASS = "SymbioticaRecipe";
const PICK = "— pick a recipe —";
const GAME = "game";

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

const listRecipes = () => getJson("/symbiotica/recipes").then((b) => b.recipes ?? []);
const readRecipe = (name) => getJson(`/symbiotica/recipes/${encodeURIComponent(name)}`);

function toast(severity, summary, detail, life = 5000) {
    app.extensionManager?.toast?.add({ severity, summary, detail, life });
}

const activeWorkflowPath = () => app.extensionManager?.workflow?.activeWorkflow?.path ?? null;

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

// ----------------------------------------------------------------- table --

export function recipeToTable(recipe, slots) {
    const categories = recipe?.categories ?? {};
    const columns = [GAME, ...Object.keys(categories)];
    const valuesOf = (column) => (column === GAME ? recipe?.game ?? {} : categories[column] ?? {});
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
            template: recipe?.template ?? "",
            output: recipe?.output ?? "",
            workflow_prefix: recipe?.workflow_prefix ?? "",
        },
        columns,
        rows,
    };
}

export function tableToRecipe(base, table, slots) {
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
    out.game = columnValues[GAME] ?? {};
    out.categories = {};
    for (const column of table.columns) if (column !== GAME) out.categories[column] = columnValues[column];
    return out;
}

export function generateSummary(report) {
    const written = report?.written ?? [];
    const summary = `Wrote ${written.length} workflow${written.length === 1 ? "" : "s"} from ${report?.template ?? "the template"}`;
    const detail = written.length
        ? `${written.map((w) => w.path).join(", ")}. Open them from the workflows sidebar; `
          + "reopen any that is open now. Edits belong in the template or the recipe, not in these files."
        : "The recipe has no categories.";
    return { summary, detail };
}

// ----------------------------------------------------------------- panel --

const pickers = new Set();

async function refreshPickers() {
    let names;
    try {
        names = (await listRecipes()).map((r) => r.name);
    } catch {
        return;
    }
    for (const widget of pickers) {
        widget.options.values = [PICK, ...names];
        if (!widget.options.values.includes(widget.value)) widget.value = PICK;
    }
    app.graph?.setDirtyCanvas(true, false);
}

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

    // What is on screen: the recipe as loaded, the template's slots, and the
    // table the person is editing. `dirty` is unsaved edits.
    const state = { name: null, recipe: null, slots: [], table: null, dirty: false };
    let busy = false;

    function status(text, subtle = true) {
        statusLine.textContent = text;
        statusLine.style.color = subtle ? HUB.inkSubtle : HUB.ink;
    }

    const statusLine = el("div", `padding:4px 3px;color:${HUB.inkSubtle};`);

    function collect() {
        return tableToRecipe(state.recipe, state.table, state.slots);
    }

    async function load(name) {
        try {
            const { recipe, slots } = await readRecipe(name);
            state.name = name;
            state.recipe = recipe;
            state.slots = slots;
            state.table = recipeToTable(recipe, slots);
            state.dirty = false;
            render();
        } catch (err) {
            toast("error", `Could not open "${name}"`, String(err?.message ?? err));
        }
    }

    async function save() {
        if (!state.name) { toast("warn", "Nothing to save", "Pick a recipe or start one first."); return false; }
        let recipe;
        try {
            recipe = collect();
        } catch (err) {
            toast("error", "Fix the cell first", String(err?.message ?? err), 8000);
            return false;
        }
        try {
            await postJson("/symbiotica/recipes/save", { name: state.name, recipe });
            state.recipe = recipe;
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

    async function startNew(name) {
        const template = activeWorkflowPath();
        if (!template) { toast("warn", "Save the workflow first", "A new recipe takes the open, saved workflow as its template."); return; }
        if (!name) { toast("warn", "Name it first", "Type a name for the new recipe."); return; }
        try {
            const { recipe, slots } = await postJson("/symbiotica/recipes/new", { name, template });
            state.name = name;
            state.recipe = recipe;
            state.slots = slots;
            state.table = recipeToTable(recipe, slots);
            state.dirty = false;
            await refreshPickers();
            const picker = node.widgets?.find((w) => w.name === "recipe");
            if (picker) picker.value = name;
            render();
            toast("success", `Started "${name}"`, `Template: ${recipe.template}. Add a category column, fill the cells, Save.`);
        } catch (err) {
            toast("error", "Could not start the recipe", String(err?.message ?? err));
        }
    }

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
        const top = el("div", "display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:2px 0 6px;");
        const newName = stopCanvas(el("input", inputCss + "flex:1 1 140px;"));
        newName.placeholder = "new recipe name, e.g. imperia-restaurant";
        const newButton = el("button", ghostButtonCss + "padding:2px 8px;flex:0 0 auto;", "New from this workflow");
        stopCanvas(newButton).addEventListener("click", (e) => { e.stopPropagation(); startNew(newName.value.trim()); });
        newName.addEventListener("keydown", (e) => { if (e.key === "Enter") newButton.click(); });
        top.append(newName, newButton);
        body.appendChild(top);

        if (!state.table) {
            body.appendChild(el("div", `padding:6px 3px;color:${HUB.inkSubtle};`,
                "Pick a recipe above, or open the template workflow and start a new one."));
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
        const grid = el("div", `display:grid;gap:3px;align-items:start;`
            + `grid-template-columns:minmax(90px, 0.6fr) repeat(${columns.length}, minmax(140px, 1fr)) 28px;`);
        grid.appendChild(el("div", `padding:3px;color:${HUB.inkSubtle};`, "slot"));
        columns.forEach((column, index) => {
            if (column === GAME) {
                const head = el("div", `padding:3px;color:${HUB.inkSubtle};`, "game (every category)");
                head.title = "A value here applies to every category that leaves the cell empty.";
                grid.appendChild(head);
                return;
            }
            const head = el("div", "display:flex;align-items:center;gap:4px;min-width:0;");
            const name = stopCanvas(el("input", inputCss + "flex:1 1 auto;width:100%;"));
            name.value = column;
            name.title = "Category: also the suffix of the generated workflow's name.";
            name.addEventListener("change", () => {
                const next = name.value.trim();
                if (!next || next === column) { name.value = column; return; }
                if (columns.includes(next)) { toast("warn", "Name taken", `There is already a "${next}" column.`); name.value = column; return; }
                columns[index] = next;
                for (const row of rows) { row.cells[next] = row.cells[column]; delete row.cells[column]; }
                state.dirty = true;
                render();
            });
            const remove = el("button", ghostButtonCss + "padding:1px 6px;flex:0 0 auto;", "×");
            remove.title = `Remove the ${column} column`;
            stopCanvas(remove).addEventListener("click", (e) => {
                e.stopPropagation();
                columns.splice(index, 1);
                for (const row of rows) delete row.cells[column];
                state.dirty = true;
                render();
            });
            head.append(name, remove);
            grid.appendChild(head);
        });
        const add = el("button", ghostButtonCss + "padding:1px 6px;", "+");
        add.title = "Add a category column";
        stopCanvas(add).addEventListener("click", (e) => {
            e.stopPropagation();
            let n = 1;
            while (columns.includes(`category${n}`)) n += 1;
            const column = `category${n}`;
            columns.push(column);
            for (const row of rows) row.cells[column] = "";
            state.dirty = true;
            render();
        });
        grid.appendChild(add);

        const byKey = Object.fromEntries(state.slots.map((s) => [s.key, s]));
        for (const row of rows) {
            const slot = byKey[row.key];
            const label = el("div", `padding:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;`
                + (row.orphan ? `color:${HUB.inkSubtle};text-decoration:line-through;` : ""), row.key);
            label.title = row.orphan
                ? "The template has no slot with this name any more; the value is ignored."
                : slot?.kind === "toggle" ? "true or false"
                : slot?.kind === "dict" ? `JSON object of widget values. Template: ${cellText(slot.default)}`
                : `Template: ${cellText(slot?.default)}${slot?.widgets > 1 ? ` (a JSON list sets all ${slot.widgets} widgets)` : ""}`;
            grid.appendChild(label);
            for (const column of columns) {
                const cell = stopCanvas(el("textarea", cellCss));
                cell.rows = 1;
                cell.value = row.cells[column] ?? "";
                cell.placeholder = column === GAME ? "" : (row.cells[GAME] || cellText(slot?.default) || "");
                cell.addEventListener("input", () => { row.cells[column] = cell.value; state.dirty = true; });
                cell.addEventListener("focus", () => { if (cell.value.length > 60) cell.rows = 4; });
                cell.addEventListener("blur", () => { cell.rows = 1; });
                grid.appendChild(cell);
            }
            grid.appendChild(el("div"));
        }
        body.appendChild(grid);

        const actions = el("div", "display:flex;align-items:center;gap:6px;padding:8px 0 2px;");
        const saveButton = el("button", ghostButtonCss + "padding:3px 10px;", "Save");
        stopCanvas(saveButton).addEventListener("click", (e) => { e.stopPropagation(); save(); });
        const generateButton = el("button", ghostButtonCss + "padding:3px 10px;", "Save and generate workflows");
        stopCanvas(generateButton).addEventListener("click", (e) => { e.stopPropagation(); generate(); });
        actions.append(saveButton, generateButton, statusLine);
        body.appendChild(actions);
        status(state.dirty ? "Unsaved edits." : `${state.name}: ${columns.length - 1} categories, ${rows.length} slots.`);
        refit();
    }

    node._symRecipeLoad = load;
    render();
}

function setupRecipeNode(node) {
    node.isVirtualNode = true;
    const picker = node.widgets?.find((w) => w.name === "recipe");
    if (!picker) return;
    pickers.add(picker);
    picker.value = PICK;
    picker.callback = (value) => {
        if (!value || value === PICK) return;
        node._symRecipeLoad?.(String(value));
    };
    recipePanel(node);
    if (node.size[1] < 320) node.setSize?.([Math.max(node.size[0], 560), 320]);
    const onRemoved = node.onRemoved;
    node.onRemoved = function () {
        pickers.delete(picker);
        onRemoved?.apply(this, arguments);
    };
    const onSelected = node.onSelected;
    node.onSelected = function () {
        onSelected?.apply(this, arguments);
        refreshPickers();
    };
    refreshPickers();
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
