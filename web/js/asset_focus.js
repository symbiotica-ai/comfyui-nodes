// ABOUTME: Asset Focus node UI — the event's assets listed on the node body,
// ABOUTME: click one to work on it. The index that used to be held by hand
// ABOUTME: across a dozen index nodes is this click.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { HUB, injectHubStyles, ghostButtonCss } from "./hub_theme.js";
import { el, emptyState } from "./browser_chrome.js";

const NODE_CLASS = "SymbioticaAssetFocus";
const MIN_NODE_W = 300;
const PANEL_MAX = 460;

const widgetOf = (node, name) => node.widgets?.find((w) => w.name === name);

function focusPanel(node) {
    injectHubStyles();

    const container = el("div", "box-sizing:border-box;width:100%;"
        + "overflow-y:auto;overflow-x:hidden;");
    const list = el("div", `padding:2px;font:11px ${HUB.font};color:${HUB.ink};`);
    container.appendChild(list);
    container.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });

    const panelW = node.addDOMWidget("focus_panel", "sym_focus", container,
                                     { serialize: false, hideOnZoom: true });
    panelW.computeSize = function (width) {
        const h = list.scrollHeight;
        return [width, Math.min(Math.max(h ? h + 8 : 34, 34), PANEL_MAX)];
    };
    const refit = () => requestAnimationFrame(() => {
        node.setSize?.([Math.max(node.size[0], MIN_NODE_W), node.computeSize()[1]]);
        node.setDirtyCanvas?.(true, true);
    });
    node.size[0] = Math.max(node.size[0], MIN_NODE_W);

    const chosen = () => widgetOf(node, "asset")?.value?.trim?.() || "";
    const narrowed = () => widgetOf(node, "category")?.value?.trim?.() || "";

    function choose(name) {
        const w = widgetOf(node, "asset");
        // Clicking the current one clears it, which is how you get back to
        // "the first" without knowing what the first is called.
        if (w) w.value = w.value === name ? "" : name;
        node.setDirtyCanvas?.(true, true);
        render();
    }

    function render() {
        list.replaceChildren();
        const assets = node._symFocusAssets ?? [];
        const pick = chosen();

        if (!assets.length) {
            list.appendChild(emptyState(
                "queue this node once to list the event's assets"));
            refit();
            return;
        }

        const head = el("div",
            `display:flex;align-items:center;gap:6px;padding:2px 3px 4px;color:${HUB.inkSubtle};`);
        head.append(el("span", "flex:1;min-width:0;",
                       `${assets.length} asset${assets.length === 1 ? "" : "s"}`
                       + `${narrowed() ? ` · ${narrowed()}` : ""}`));
        if (pick) {
            const clear = el("button", ghostButtonCss + "padding:1px 7px;flex:none;",
                             "all");
            clear.className = "sym-btn";
            clear.title = "Go back to the first asset";
            clear.addEventListener("pointerdown", (e) => e.stopPropagation());
            clear.addEventListener("click", () => choose(pick));
            head.appendChild(clear);
        }
        list.appendChild(head);

        for (const asset of assets) {
            const on = asset.name === pick;
            const row = el("div",
                "display:flex;align-items:center;gap:6px;padding:3px 5px;margin:2px 0;"
                + `border:1px solid ${on ? HUB.accent : HUB.hairline};`
                + `border-radius:5px;cursor:pointer;`
                + (on ? "" : "opacity:.75;"));
            row.append(el("span", "flex:1;min-width:0;overflow:hidden;"
                + "text-overflow:ellipsis;white-space:nowrap;", asset.name));
            row.appendChild(el("span", `flex:none;color:${HUB.inkTertiary};`,
                               asset.category || ""));
            row.title = `${asset.name}${asset.category ? ` · ${asset.category}` : ""}`;
            row.addEventListener("pointerdown", (e) => e.stopPropagation());
            row.addEventListener("click", () => choose(asset.name));
            list.appendChild(row);
        }
        refit();
    }

    node._symRenderFocus = render;
    render();
}

registerSymbioticaExtension(app, {
    name: "symbiotica.asset_focus",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            // The chosen name is the panel's storage. It stays typeable — a
            // name pasted in still works — but it is not where you look to
            // find out what the choices are.
            focusPanel(this);
        };

        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            onConfigure?.apply(this, arguments);
            queueMicrotask(() => this._symRenderFocus?.());
        };
    },
});

// The order arrives on a wire the canvas cannot read, so the node hands its
// asset list over when it runs.
api.addEventListener("symbiotica.focus", (event) => {
    const detail = event?.detail ?? {};
    if (detail.node_id == null) return;
    const node = app.graph?.getNodeById?.(Number(detail.node_id))
        ?? app.graph?.getNodeById?.(detail.node_id);
    if (!node) return;
    node._symFocusAssets = Array.isArray(detail.assets) ? detail.assets : [];
    node._symRenderFocus?.();
});
