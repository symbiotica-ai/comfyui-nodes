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
    nodes.clear();
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
globalThis.window = { addEventListener() {}, devicePixelRatio: 1 };
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
export const repaints = { count: 0 };
let nextLink = 1;
let nextId = 1;

export const app = {
    extensions: [],
    registerExtension(ext) { this.extensions.push(ext); },
    graph: { links: {}, getNodeById: (id) => nodes.get(id) ?? null },
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
