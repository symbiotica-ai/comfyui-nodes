// ABOUTME: Control Image node — shows the picked control image on the node, the
// ABOUTME: way Load Image does, from input/controlnet.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";

const NODE_CLASS = "SymbioticaControlImage";
const CONTROL_DIR = "controlnet";

// The /view query for a dropdown value: `bakery/counter.png` is the file
// `counter.png` in subfolder `controlnet/bakery` of the input directory.
export function viewParams(value) {
    const rel = String(value ?? "").trim().replace(/^\/+/, "");
    if (!rel || rel.startsWith("[")) return null;
    const parts = rel.split("/");
    const filename = parts.pop();
    if (!filename) return null;
    return { filename, subfolder: [CONTROL_DIR, ...parts].join("/"), type: "input" };
}

function showImage(node, value) {
    const params = viewParams(value);
    if (!params) {
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
    const query = new URLSearchParams({ ...params, rand: String(Math.random()) });
    img.src = api.apiURL(`/view?${query}`);
}

function setupControlImage(node) {
    const widget = node.widgets?.find((w) => w.name === "image");
    if (!widget) return;
    const callback = widget.callback;
    widget.callback = function (value) {
        const out = callback?.apply(this, arguments);
        showImage(node, value);
        return out;
    };
    // A node restored from a saved workflow gets its value after creation.
    const onConfigure = node.onConfigure;
    node.onConfigure = function () {
        onConfigure?.apply(this, arguments);
        showImage(node, widget.value);
    };
    showImage(node, widget.value);
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
