// ABOUTME: Control Image node — lists the folder its `folder` widget names and
// ABOUTME: shows the picked image on the node, the way Load Image does.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";

const NODE_CLASS = "SymbioticaControlImage";
const CONTROL_DIR = "controlnet";

const folderOf = (node) => {
    const raw = node.widgets?.find((w) => w.name === "folder")?.value;
    return String(raw ?? "").trim().replace(/^\/+|\/+$/g, "") || CONTROL_DIR;
};

// Empty means ComfyUI's own input directory, which `/view` already serves. Any
// other mount has to be previewed through `local-image` instead, against the
// absolute folder the listing route hands back.
const rootOf = (node) =>
    String(node.widgets?.find((w) => w.name === "root")?.value ?? "").trim()
        .replace(/\/+$/, "");

const keyOf = (node) => `${rootOf(node)}\u0000${folderOf(node)}`;

// The /view query for a dropdown value: `bakery/counter.png` is the file
// `counter.png` in subfolder `<folder>/bakery` of the input directory.
export function viewParams(value, folder = CONTROL_DIR) {
    const rel = String(value ?? "").trim().replace(/^\/+/, "");
    if (!rel || rel.startsWith("[")) return null;
    const parts = rel.split("/");
    const filename = parts.pop();
    if (!filename) return null;
    return { filename, subfolder: [folder, ...parts].join("/"), type: "input" };
}

function srcFor(node, value) {
    const rel = String(value ?? "").trim().replace(/^\/+/, "");
    if (!rel || rel.startsWith("[")) return "";
    const rand = String(Math.random());
    if (!rootOf(node)) {
        const params = viewParams(value, folderOf(node));
        if (!params) return "";
        return api.apiURL(`/view?${new URLSearchParams({ ...params, rand })}`);
    }
    // The listing route resolved the folder; without it there is nothing to
    // build an absolute path from, so the preview waits for the listing.
    const library = listings.get(keyOf(node))?.library;
    if (!library) return "";
    return api.apiURL(`/symbiotica/local-image?${new URLSearchParams({
        path: `${library}/${rel}`, rand })}`);
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
        if (node.widgets?.find((w) => w.name === "image")?.value !== value) return;
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

// One listing per root+folder for the whole canvas: several Control Image nodes
// reading the same library must not each cost a request, and the combo asks for
// its values on every repaint.
const listings = new Map();

function listingFor(node) {
    const key = keyOf(node);
    let entry = listings.get(key);
    if (!entry) {
        entry = { images: [], loading: false, library: "" };
        listings.set(key, entry);
    }
    if (!entry.loading && !entry.loaded) {
        entry.loading = true;
        const query = new URLSearchParams({ folder: folderOf(node) });
        if (rootOf(node)) query.set("root", rootOf(node));
        // `ready` so a caller can redraw once the answer is in: on another
        // mount the preview URL is built from the folder the route resolves,
        // so the first paint has nothing to show and must be repeated.
        entry.ready = api.fetchApi(`/symbiotica/control-images?${query}`)
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
    const current = String(
        node.widgets?.find((w) => w.name === "image")?.value ?? "");
    const held = current && !current.startsWith("[") ? current : "";
    if (images.length) {
        // The held value stays offered even when this folder does not list it,
        // so opening the dropdown cannot silently discard a saved workflow's
        // pick — VALIDATE_INPUTS is what rejects it, with a reason.
        return images.includes(held) || !held ? images : [...images, held];
    }
    if (held) return [held];
    if (!loaded) return ["[loading…]"];
    if (error) return [`[${error}]`];
    return [`[no images under ${rootOf(node) || "input"}/${folderOf(node)}]`];
}

function setupControlImage(node) {
    const widget = node.widgets?.find((w) => w.name === "image");
    if (!widget) return;
    // The Python list was built at registration against the DEFAULT folder, so
    // it is only right until this node's folder says otherwise. A function is
    // what LiteGraph re-reads, so the dropdown follows the widget.
    widget.options = widget.options ?? {};
    widget.options.values = () => valuesFor(node);

    const callback = widget.callback;
    widget.callback = function (value) {
        const out = callback?.apply(this, arguments);
        showImage(node, value);
        return out;
    };

    // A new root or folder is a different library: re-list, and drop a preview
    // that belonged to the old one.
    for (const name of ["root", "folder"]) {
        const w = node.widgets?.find((x) => x.name === name);
        if (!w) continue;
        const cb = w.callback;
        w.callback = function () {
            const out = cb?.apply(this, arguments);
            // Cached per root+folder, so this lists the new one and keeps the
            // old one's answer for a node still on it. A file added since the
            // page loaded needs a reload, as it always did.
            refresh(node, widget);
            return out;
        };
    }

    // A node restored from a saved workflow gets its value after creation.
    const onConfigure = node.onConfigure;
    node.onConfigure = function () {
        onConfigure?.apply(this, arguments);
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
