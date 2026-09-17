// ABOUTME: Control Image node — the dropdown lists every image under the node's
// ABOUTME: path, sub-folders included, and the pick is shown on the node.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { nodeOutputString } from "./order_source.js";

const NODE_CLASS = "SymbioticaControlImage";

const widgetOf = (node, name) => node.widgets?.find((w) => w.name === name);

// The path the last run received, kept on the node and saved with the
// workflow so a reload still knows it.
const RAN_PATH = "symbiotica_ran_path";
const ranPath = (node) => {
    const v = node?.properties?.[RAN_PATH];
    return typeof v === "string" ? v.trim().replace(/\/+$/, "") : "";
};

// The folder this node reads: its own widget, else the string the node wired
// into `path` outputs — a literal, a switch, a Studio Library path. A wire the
// canvas cannot read — a Get node, whose only widget holds the NAME of the
// constant and not its value — is answered by queueing the node: what the run
// received beats what the walk guessed, until the next run.
function pathOf(node) {
    const typed = String(widgetOf(node, "path")?.value ?? "").trim();
    if (typed) return typed.replace(/\/+$/, "");
    const link = node.inputs?.find((i) => i.name === "path")?.link;
    if (link == null) return "";
    const ran = ranPath(node);
    if (ran) return ran;
    const origin = app.graph?.getNodeById?.(app.graph.links[link]?.origin_id);
    if (!origin) return "";
    return String(nodeOutputString(origin, new Set()) ?? "").trim()
        .replace(/\/+$/, "");
}

function srcFor(node, value) {
    const rel = String(value ?? "").trim().replace(/^\/+/, "");
    if (!rel || rel.startsWith("[")) return "";
    // The listing registered the folder as servable and handed back the
    // absolute path; without it there is nothing to build a URL from, so the
    // preview waits for the listing.
    const library = listings.get(pathOf(node))?.library;
    if (!library) return "";
    return api.apiURL(`/symbiotica/local-image?${new URLSearchParams({
        path: `${library}/${rel}`, rand: String(Math.random()) })}`);
}

function showImage(node, value) {
    const src = srcFor(node, value);
    if (!src) {
        node.imgs = [];
        app.graph?.setDirtyCanvas(true, true);
        return;
    }
    const img = new Image();
    img.onload = () => {
        if (widgetOf(node, "image")?.value !== value) return;
        node.imgs = [img];
        node.setSizeForImage?.();
        app.graph?.setDirtyCanvas(true, true);
    };
    img.onerror = () => {
        node.imgs = [];
        app.graph?.setDirtyCanvas(true, true);
    };
    img.src = src;
}

// One listing per path for the whole canvas: several Control Image nodes
// reading the same folder must not each cost a request, and the combo asks for
// its values on every repaint.
const listings = new Map();

function listingFor(node) {
    const path = pathOf(node);
    let entry = listings.get(path);
    if (!entry) {
        entry = { images: [], loading: false, library: "" };
        listings.set(path, entry);
    }
    if (!path) {
        entry.loaded = true;
        return entry;
    }
    if (!entry.loading && !entry.loaded) {
        entry.loading = true;
        // `ready` so a caller can redraw once the answer is in: the preview URL
        // is built from the folder the route resolves, so the first paint has
        // nothing to show and must be repeated.
        entry.ready = api.fetchApi(
            `/symbiotica/control-images?path=${encodeURIComponent(path)}`)
            .then((r) => r.json())
            .then((body) => {
                entry.images = body?.images ?? [];
                entry.library = body?.library ?? "";
                entry.error = body?.error ?? "";
            })
            .catch(() => { entry.images = []; })
            .finally(() => {
                entry.loading = false;
                entry.loaded = true;
                app.graph?.setDirtyCanvas(true, true);
            });
    }
    return entry;
}

// The values a combo shows must never be empty — LiteGraph renders an empty
// dropdown as a dead control with no way back to a valid value, and the widget
// may hold a name from a folder that is not listed yet.
function valuesFor(node) {
    const { images, loaded, error } = listingFor(node);
    const current = String(widgetOf(node, "image")?.value ?? "");
    const held = current && !current.startsWith("[") ? current : "";
    if (images.length) {
        // The held value stays offered even when this folder does not list it,
        // so opening the dropdown cannot silently discard a saved workflow's
        // pick — VALIDATE_INPUTS is what rejects it, with a reason.
        return images.includes(held) || !held ? images : [...images, held];
    }
    if (held) return [held];
    if (!pathOf(node)) return ["[set a path]"];
    if (!loaded) return ["[loading…]"];
    if (error) return [`[${error}]`];
    return [`[no images under ${pathOf(node)}]`];
}

function setupControlImage(node) {
    const widget = widgetOf(node, "image");
    if (!widget) return;
    // Nothing could be listed at registration — no node had said where it
    // reads. A function is what LiteGraph re-reads, so the dropdown follows
    // the path.
    widget.options = widget.options ?? {};
    widget.options.values = () => valuesFor(node);

    const callback = widget.callback;
    widget.callback = function (value) {
        const out = callback?.apply(this, arguments);
        showImage(node, value);
        return out;
    };

    // A new path is a different folder: re-list, and drop a preview that
    // belonged to the old one.
    const pathW = widgetOf(node, "path");
    if (pathW) {
        const cb = pathW.callback;
        pathW.callback = function () {
            const out = cb?.apply(this, arguments);
            refresh(node, widget);
            return out;
        };
    }

    // A node restored from a saved workflow gets its value after creation, and
    // a wired path only after the link is back.
    const onConfigure = node.onConfigure;
    node.onConfigure = function () {
        onConfigure?.apply(this, arguments);
        refresh(node, widget);
    };
    const onConnectionsChange = node.onConnectionsChange;
    node.onConnectionsChange = function () {
        onConnectionsChange?.apply(this, arguments);
        refresh(node, widget);
    };
    refresh(node, widget);
}

function refresh(node, widget) {
    const entry = listingFor(node);
    showImage(node, widget.value);
    entry.ready?.then(() => showImage(node, widget.value));
}

registerSymbioticaExtension(app, {
    name: "symbiotica.control_image",

    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            setupControlImage(this);
        };
    },
});

// A run hands back the folder it was given, which is the only way to read one
// that arrives through a Get node. Queue the node on its own and the dropdown
// fills in.
api.addEventListener("symbiotica.control_image", (event) => {
    const detail = event?.detail ?? {};
    if (detail.node_id == null) return;
    const node = app.graph?.getNodeById?.(Number(detail.node_id))
        ?? app.graph?.getNodeById?.(detail.node_id);
    if (!node) return;
    const path = typeof detail.path === "string"
        ? detail.path.trim().replace(/\/+$/, "") : "";
    if (!path || ranPath(node) === path) return;
    node.properties = node.properties ?? {};
    node.properties[RAN_PATH] = path;
    const widget = widgetOf(node, "image");
    if (widget) refresh(node, widget);
});
