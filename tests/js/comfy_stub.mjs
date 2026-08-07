// ABOUTME: Stand-ins for ComfyUI's app/api modules and the browser DOM, so the
// ABOUTME: real web/js modules can be imported and driven under plain node.

export const calls = [];
let responder = () => ({ ok: false, status: 400, body: { error: "order_path required" } });
let latencyMs = 0;

export function setResponder(fn) { responder = fn; }
// A number applies to every call; a (route) => ms function lets a test make one
// request outrun another, which is the only way to drive an out-of-order reply.
export function setLatency(ms) { latencyMs = ms; }
export function reset() {
    latencyMs = 0;  // a test that fails mid-way must not slow the next one
    calls.length = 0;
    repaints.count = 0;
    canvasCalls.select.length = 0;
    canvasCalls.center.length = 0;
    canvasCalls.dirty = 0;
    nodes.clear();
    assignedNodes = null;
    app.graph.links = {};
}

// --- DOM ---------------------------------------------------------------------
// addEventListener/removeEventListener actually store listeners (rather than
// no-op) so tests can drive click/keydown-triggered code via fire(); remove()
// unlinks from the parent set by appendChild/append so removal is observable.
function listening() {
    return {
        addEventListener(type, fn) {
            (this._listeners ??= {});
            (this._listeners[type] ??= []).push(fn);
        },
        removeEventListener(type, fn) {
            if (this._listeners?.[type]) {
                this._listeners[type] = this._listeners[type].filter((f) => f !== fn);
            }
        },
    };
}
export function fire(el, type, event = {}) {
    for (const fn of el._listeners?.[type] ?? []) fn(event);
}
function element() {
    return {
        ...listening(),
        style: { cssText: "", display: "", opacity: "" },
        children: [],
        parent: null,
        textContent: "",
        appendChild(c) { this.children.push(c); c.parent = this; return c; },
        append(...cs) { this.children.push(...cs); cs.forEach((c) => { c.parent = this; }); },
        // As in the DOM, this drops every child including any text set through
        // textContent — so a placeholder string does not survive a re-render.
        replaceChildren(...cs) {
            this.children = cs;
            this.textContent = "";
            cs.forEach((c) => { c.parent = this; });
        },
        setAttribute() {},
        // Where the element is ON SCREEN — a hover preview is placed against
        // it, so a test that cannot set this cannot tell "beside the tile"
        // from "off the window". `_rect` is the element's own answer; the
        // default is the origin, as an unlaid-out element reports in a browser.
        getBoundingClientRect() {
            return this._rect
                ?? { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 };
        },
        get parentElement() { return this.parent; },
        remove() {
            if (this.parent) {
                this.parent.children = this.parent.children.filter((c) => c !== this);
                this.parent = null;
            }
        },
        querySelector: () => null, querySelectorAll: () => [],
    };
}
globalThis.document = {
    ...listening(),
    createElement: element,
    createTextNode: (t) => ({ text: t }),
    body: element(),
};
globalThis.window = {
    addEventListener() {},
    devicePixelRatio: 1,
    // A window size, because anything that floats over the canvas is sized and
    // clamped against one.
    innerWidth: 1440,
    innerHeight: 900,
};
globalThis.requestAnimationFrame = (cb) => cb();

// --- api ---------------------------------------------------------------------
// A module registers its execution-message listeners once, at import time, so
// these are deliberately NOT cleared by reset() — dropping them would silently
// disarm every test that runs after the first.
const apiListeners = new Map();

/** Deliver a ComfyUI execution message, as the server's websocket would. */
export function emit(type, detail) {
    for (const fn of apiListeners.get(type) ?? []) fn({ detail });
}

export const api = {
    apiURL: (route) => `/api${route}`,
    addEventListener(type, fn) {
        if (!apiListeners.has(type)) apiListeners.set(type, []);
        apiListeners.get(type).push(fn);
    },
    async fetchApi(route, init) {
        calls.push(route);
        // `init` is passed through so a test can assert what a POST actually
        // sent — without it a save handler could write the wrong file, or the
        // wrong text, and every assertion here would still pass.
        const r = responder(route, calls.length, init);
        const delay = typeof latencyMs === "function" ? latencyMs(route) : latencyMs;
        if (delay) await new Promise((res) => setTimeout(res, delay));
        return {
            ok: r.ok,
            status: r.status ?? (r.ok ? 200 : 400),
            statusText: r.ok ? "OK" : "Error",
            async json() { return r.body; },
        };
    },
};

// --- app / graph -------------------------------------------------------------
const nodes = new Map();
let assignedNodes = null;
export const repaints = { count: 0 };
let nextLink = 1;
let nextId = 1;

// What the canvas was asked to do, recorded rather than simulated: a command
// that moves the view is judged on WHICH node it selected and centred, not on
// where the viewport ended up.
export const canvasCalls = { select: [], center: [], dirty: 0 };

export const app = {
    extensions: [],
    registerExtension(ext) { this.extensions.push(ext); },
    graph: {
        links: {},
        getNodeById: (id) => nodes.get(id) ?? null,
        // LiteGraph keeps every node on the graph in `_nodes`, which is how
        // code broadcasts to the canvas rather than walking wires. Without it
        // a broadcast reaches nothing and its test passes for the wrong
        // reason. Every created node is on it by default; a test that builds a
        // graph by hand can still assign the list outright, and then that is
        // exactly what it gets — assigning a subset is how the "two possible
        // sources" cases are set up.
        get _nodes() { return assignedNodes ?? [...nodes.values()]; },
        set _nodes(value) { assignedNodes = value; },
    },
    canvas: {
        // LiteGraph's canvas holds the graph being drawn, which is the subgraph
        // once you have stepped into one — not always `app.graph`.
        get graph() { return app.graph; },
        selectNode(node) { canvasCalls.select.push(node?.id ?? null); },
        centerOnNode(node) { canvasCalls.center.push(node?.id ?? null); },
        setDirty() { canvasCalls.dirty += 1; },
    },
};

function makeNode(comfyClass, widgets) {
    const node = {
        id: nextId++,
        comfyClass,
        size: [200, 100],
        inputs: [],
        outputs: [],
        widgets: Object.entries(widgets).map(([name, value]) => ({
            name, value, type: "text", callback: null,
        })),
        addWidget(type, name, value, callback, options) {
            const w = { type, name, value, callback, options };
            this.widgets.push(w);
            return w;
        },
        addDOMWidget(name, type, elem, options) {
            // ComfyUI puts the element inside a wrapper div it sizes from the
            // node width; code that keeps the panel inside the node has to
            // reach that wrapper, so the stub has to have one too.
            element().appendChild(elem);
            const w = { name, type, element: elem, options };
            this.widgets.push(w);
            return w;
        },
        // LiteGraph marks the canvas dirty, which schedules a repaint.
        setDirtyCanvas() { repaints.count++; },
        setSize() {}, computeSize: () => [200, 100],
        // LiteGraph's own signature: connect(outputSlot, targetNode, inputSlot).
        // Recorded rather than simulated — tests assert WHICH slot was picked.
        connect(slot, target, input) {
            this.connected = { slot, target, input };
            const inp = target.inputs?.[input];
            if (inp) inp.link = nextLink++;
            return true;
        },
    };
    nodes.set(node.id, node);
    return node;
}

export function link(from, to, inputName) {
    const id = nextLink++;
    app.graph.links[id] = { origin_id: from.id, target_id: to.id, id };
    to.inputs.push({ name: inputName, link: id });
    const out = from.outputs[0] ?? (from.outputs[0] = { links: [] });
    out.links.push(id);
    return id;
}

// Build a node the way ComfyUI does: run every registered extension's
// beforeRegisterNodeDef for this class, then invoke onNodeCreated.
export async function create(comfyClass, widgets = {}) {
    const proto = {};
    for (const ext of app.extensions) {
        await ext.beforeRegisterNodeDef?.({ prototype: proto }, { name: comfyClass });
    }
    const node = makeNode(comfyClass, widgets);
    node.onNodeCreated = proto.onNodeCreated;
    node.onConfigure = proto.onConfigure;
    // ComfyUI calls this on every wire change; without it a test that rewires
    // is driving nothing and passes for the wrong reason.
    node.onConnectionsChange = proto.onConnectionsChange;
    return node;
}

// Restore a saved node the way ComfyUI does: `widgets_values` is applied
// POSITIONALLY over the node's widgets, and only then is onConfigure called.
//
// The positional part is what a migration has to repair. A widget added since
// the workflow was saved sits past the end of that array and comes back with
// no value at all — not its declared default — and ComfyUI refuses to queue a
// combo that holds no value. Driving onConfigure without this models a restore
// that cannot fail, and a test written against it passes on a graph the real
// frontend rejects.
export function configure(node, info) {
    const v = info?.widgets_values;
    if (Array.isArray(v)) node.widgets.forEach((w, i) => { w.value = v[i]; });
    node.onConfigure?.call(node, info);
    return node;
}

// One LiteGraph repaint: every combo widget whose values is a function has it
// invoked, exactly as ComboWidget._displayValue does per frame.
export function repaint(...targets) {
    for (const node of targets) {
        for (const w of node.widgets ?? []) {
            if (w.type === "combo" && typeof w.options?.values === "function") {
                w.options.values(w, node);
            }
        }
    }
}

export const tick = () => new Promise((r) => setTimeout(r, 0));
