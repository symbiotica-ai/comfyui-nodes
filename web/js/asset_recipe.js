// ABOUTME: Asset Recipe node UI — the widget slots under Asset Focus's own
// ABOUTME: controls. Drag a widget onto the empty slot and its value moves here.
import { app } from "../../../scripts/app.js";
import { registerSymbioticaExtension } from "./register.js";
import { hideWidget } from "./asset_focus.js";

const NODE_CLASS = "SymbioticaAssetRecipe";
// LiteGraph's own: onConnectionsChange is called with 1 for an input and 2 for
// an output, and only the outputs are slots.
const OUTPUT = 2;
// What the slot nothing is wired to yet reads as — the one you drag onto.
const EMPTY_LABEL = "+ widget";
// Python declares a fixed number of `slot_*` outputs (SLOT_COUNT in
// py/pipeline/nodes.py) and every node definition carries them, so the ceiling
// is read off the node. This is only the answer for a definition that arrives
// without any — a node the server never described.
const FALLBACK_MAX = 16;

const WIDGET_KIND = { INT: "number", FLOAT: "number", BOOLEAN: "toggle",
                      COMBO: "combo", STRING: "text" };
// Everything a number widget is told about itself. Cloned from the widget the
// slot was taken from, so a strength that runs 0–1 in steps of 0.01 over there
// runs 0–1 in steps of 0.01 here.
const NUMBER_KEYS = ["min", "max", "step", "step2", "precision", "round"];

const widgetOf = (node, name) => node.widgets?.find((w) => w.name === name);
const isSlotOutput = (o) => /^slot_\d+$/.test(String(o?.name ?? ""));

// Where the slots start in the output column: everything before the first
// `slot_*` is one of Asset Focus's own outputs, and the slot at index i is
// Python's `slot_{i+1}`. Read off the node rather than counted here, so an
// output added to Asset Focus cannot silently repoint every slot.
function slotStart(node) {
    const at = node.outputs?.findIndex(isSlotOutput) ?? -1;
    return at < 0 ? (node.outputs?.length ?? 0) : at;
}

const maxSlots = (node) => node._symMaxSlots || FALLBACK_MAX;

// The slot table lives in ONE hidden string widget, which is what reaches
// Python. The per-slot widgets do not serialise, so adding a slot never shifts
// another widget's saved value.
function readSlots(node) {
    try {
        const rows = JSON.parse(widgetOf(node, "slots")?.value || "[]");
        if (!Array.isArray(rows)) return [];
        return rows.filter((r) => r && typeof r === "object");
    } catch (err) {
        return [];
    }
}

function writeSlots(node, rows) {
    const w = widgetOf(node, "slots");
    if (w) w.value = JSON.stringify(rows);
}

function toast(detail) {
    app.extensionManager?.toast?.add?.({
        severity: "warn", summary: "Asset Recipe", detail, life: 5000,
    });
}

// The node definition as ComfyUI received it — the only place that says INT
// rather than FLOAT, since a litegraph "number" widget is both.
function inputSpec(target, name) {
    const def = target?.constructor?.nodeData?.input ?? {};
    return def.required?.[name] ?? def.optional?.[name] ?? null;
}

function targetType(target, input, widget) {
    const spec = inputSpec(target, widget?.name ?? input?.name);
    if (Array.isArray(spec?.[0])) return "COMBO";
    if (typeof spec?.[0] === "string" && spec[0]) return spec[0].toUpperCase();
    if (Array.isArray(input?.type)) return "COMBO";
    if (typeof input?.type === "string" && input.type && input.type !== "*") {
        return input.type.toUpperCase();
    }
    if (widget?.type === "combo") return "COMBO";
    if (widget?.type === "toggle") return "BOOLEAN";
    if (widget?.type === "number" || widget?.type === "slider") {
        return widget.options?.precision === 0 ? "INT" : "FLOAT";
    }
    return "STRING";
}

function slotConfig(type, target, widget) {
    if (type === "COMBO") {
        const values = widget?.options?.values;
        const list = typeof values === "function" ? values(widget, target) : values;
        return { values: (Array.isArray(list) ? list : []).map(String) };
    }
    if (type === "STRING" || type === "BOOLEAN") return {};
    const config = {};
    for (const key of NUMBER_KEYS) {
        const value = widget?.options?.[key];
        if (typeof value === "number") config[key] = value;
    }
    return config;
}

function uniqueName(rows, base) {
    const taken = new Set(rows.map((r) => String(r.name ?? "")));
    if (!taken.has(base)) return base;
    for (let n = 2; n < 100; n += 1) {
        if (!taken.has(`${base} ${n}`)) return `${base} ${n}`;
    }
    return base;
}

// One new slot, read off the far end of the wire that was just made. Null when
// the wire came from a socket rather than a widget: a slot holds a value you
// can type, and a MODEL or an IMAGE is not one.
function describe(node, rows, link) {
    const target = app.graph?.getNodeById?.(link?.target_id);
    const input = target?.inputs?.[link?.target_slot];
    if (!target || !input) return null;
    const name = String(input.widget?.name ?? input.name ?? "");
    const widget = target.widgets?.find((w) => w.name === name);
    if (!widget) return null;
    const type = targetType(target, input, widget);
    return {
        name: uniqueName(rows, name || "value"),
        type,
        value: widget.value,
        config: slotConfig(type, target, widget),
    };
}

// The output column, brought in line with the table: one output per slot, one
// empty one under them, and nothing past that.
function syncOutputs(node) {
    const rows = readSlots(node);
    const start = slotStart(node);
    const want = start + Math.min(rows.length + 1, maxSlots(node));
    while ((node.outputs?.length ?? 0) > want) {
        const last = node.outputs.length - 1;
        // Only ever the tail, and only while nothing hangs off it — removing a
        // slot in the middle repoints every wire below it.
        if (node.outputs[last]?.links?.length) break;
        node.removeOutput?.(last);
    }
    while ((node.outputs?.length ?? 0) < want) {
        node.addOutput?.(`slot_${node.outputs.length - start + 1}`, "*");
    }
    for (let i = start; i < node.outputs.length; i += 1) {
        const row = rows[i - start];
        const out = node.outputs[i];
        // The NAME is the slot's position — Python answers `slot_3` with the
        // third row of the table — and the label is what you read on the node.
        out.name = `slot_${i - start + 1}`;
        out.label = row ? String(row.name ?? "") : EMPTY_LABEL;
        out.type = row?.type || "*";
    }
}

function rebuildWidgets(node) {
    node.widgets = (node.widgets ?? []).filter((w) => !w._symSlot);
    readSlots(node).forEach((row, index) => {
        const kind = WIDGET_KIND[String(row.type).toUpperCase()] ?? "text";
        const options = { ...(row.config ?? {}), serialize: false };
        const widget = node.addWidget(kind, String(row.name ?? ""), row.value,
            (value) => {
                const rows = readSlots(node);
                if (!rows[index]) return;
                rows[index].value = value;
                writeSlots(node, rows);
            }, options);
        if (!widget) return;
        // The whole block rides in the `slots` string. A slot widget that
        // serialised would take a position in widgets_values and hand every
        // widget after it the value saved one slot along.
        widget._symSlot = true;
        widget.serialize = false;
    });
}

// A slot added under the panel needs the room for its widget. Growth only, and
// only when a slot arrives or leaves — no redraw path sets a height, which is
// what keeps the corner draggable.
function fitHeight(node) {
    const min = node.computeSize?.();
    if (min && Array.isArray(node.size) && node.size[1] < min[1]) {
        node.setSize?.([node.size[0], min[1]]);
    }
}

function apply(node) {
    node._symSyncing = true;
    try {
        syncOutputs(node);
        rebuildWidgets(node);
    } finally {
        node._symSyncing = false;
    }
    fitHeight(node);
    node.setDirtyCanvas?.(true, true);
}

// A slot taken off on demand: right-click its dot on the node and pick
// "Remove slot". Unplugging a wire does the same for a slot that HAS one, and
// a slot whose wire never became a row has nothing to unplug.
function removeSlot(node, index) {
    const at = index - slotStart(node);
    if (at < 0) return;
    const rows = readSlots(node);
    if (at < rows.length) {
        rows.splice(at, 1);
        writeSlots(node, rows);
    }
    node._symSyncing = true;
    try {
        // litegraph's own removeOutput disconnects the slot first and repoints
        // the wires of every slot below it, so the table and the output column
        // come out of this still pointing at the same values.
        node.removeOutput?.(index);
    } finally {
        node._symSyncing = false;
    }
    apply(node);
}

function refuse(node, index, detail) {
    node._symSyncing = true;
    try {
        node.disconnectOutput?.(index);
    } finally {
        node._symSyncing = false;
    }
    toast(detail);
}

registerSymbioticaExtension(app, {
    name: "symbiotica.asset_recipe",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            // Python's ceiling, taken before the unused outputs come off the
            // canvas: the node can never show more slots than it declares.
            this._symMaxSlots = Math.max(
                0, (this.outputs?.length ?? 0) - slotStart(this));
            // The slot table is written by this file and read by Python. It is
            // not something to type at.
            hideWidget(widgetOf(this, "slots"));
            apply(this);
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            // Restoring a saved graph re-makes the wires by index, and those
            // connections must not read as new slots being dragged in.
            this._symLoading = true;
            onConfigure?.apply(this, arguments);
            queueMicrotask(() => {
                this._symLoading = false;
                apply(this);
            });
        };

        // litegraph builds the slot's right-click menu itself and offers
        // "Remove Slot" only for an output flagged `removable`; these are not,
        // and flagging them would call removeOutput behind the table's back.
        // `getExtraSlotMenuOptions` appends to that menu instead, so Disconnect
        // Links and Rename Slot stay where they were.
        const getExtraSlotMenuOptions = nodeType.prototype.getExtraSlotMenuOptions;
        nodeType.prototype.getExtraSlotMenuOptions = function (slotInfo) {
            const extra = getExtraSlotMenuOptions?.apply(this, arguments) ?? [];
            const index = slotInfo?.slot;
            if (!slotInfo?.output || typeof index !== "number") return extra;
            const at = index - slotStart(this);
            if (at < 0) return extra;
            // The foot of the column is the one you drag onto, not a slot.
            if (at >= readSlots(this).length
                && !this.outputs?.[index]?.links?.length) return extra;
            return [...extra, null,
                    { content: "Remove slot", className: "danger",
                      callback: () => removeSlot(this, index) }];
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (type, index, connected,
                                                           link) {
            onConnectionsChange?.apply(this, arguments);
            if (type !== OUTPUT || this._symLoading || this._symSyncing) return;
            const start = slotStart(this);
            // Asset Focus's own outputs are wired like any other node's.
            if (index < start) return;
            const at = index - start;
            const rows = readSlots(this);
            if (connected) {
                // An existing slot taking a second wire drives both from the
                // one value; only the empty one at the foot adopts.
                if (at !== rows.length) return;
                const row = describe(this, rows, link);
                if (!row) {
                    refuse(this, index,
                           "A slot holds a value you can type. Wire it to a "
                           + "widget — a lora, a strength, a seed — not to a "
                           + "model or an image socket.");
                    return;
                }
                rows.push(row);
                writeSlots(this, rows);
                apply(this);
            } else if (at < rows.length && !this.outputs?.[index]?.links?.length) {
                // The last wire off a slot takes the slot with it, the way a
                // subgraph input goes when you unplug it.
                rows.splice(at, 1);
                writeSlots(this, rows);
                // After litegraph has finished its own disconnect: removing an
                // output from under it re-enters this handler.
                queueMicrotask(() => {
                    this._symSyncing = true;
                    try {
                        this.removeOutput?.(index);
                    } finally {
                        this._symSyncing = false;
                    }
                    apply(this);
                });
            }
        };
    },
});
