// ABOUTME: Order Tracker panel — one slot per asset the order asks for, filled
// ABOUTME: with the approved render or left empty. The month's work at a glance,
// ABOUTME: read off the same folders the Pick node lists.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { HUB, injectHubStyles } from "./hub_theme.js";
import { attachHoverZoom, el, emptyState, hideHoverZoom, imageFullUrl,
         imageThumbUrl } from "./browser_chrome.js";

const NODE_CLASS = "SymbioticaOrderTracker";
const MIN_NODE_W = 320;
const SLOT_PX = 72;

function trackerPanel(node) {
    injectHubStyles();

    const container = el("div", "box-sizing:border-box;width:100%;height:100%;"
        + "overflow-y:auto;overflow-x:hidden;");
    const list = el("div", "width:100%;box-sizing:border-box;overflow:hidden;"
        + `padding:2px;font:11px ${HUB.font};`
        + `color:var(--input-text, ${HUB.ink});`);
    container.appendChild(list);
    container.addEventListener("wheel", (e) => e.stopPropagation(),
                               { passive: true });

    // No computeSize, a constant floor: anything computeSize returns becomes a
    // minimum height the corner cannot drag past.
    node.addDOMWidget("tracker_panel", "sym_tracker", container, {
        serialize: false, hideOnZoom: true,
        getMinHeight: () => 34,
    });
    node.size[0] = Math.max(node.size[0], MIN_NODE_W);
    const refit = () => requestAnimationFrame(() => {
        node.setDirtyCanvas?.(true, true);
    });

    function slotTile(slot) {
        const cell = el("div", "display:flex;flex-direction:column;gap:3px;"
            + `width:${SLOT_PX}px;flex:none;`);
        const frame = el("div",
            `width:${SLOT_PX}px;height:${SLOT_PX}px;border-radius:5px;`
            + "display:flex;align-items:center;justify-content:center;"
            + `background:${HUB.surface1};`
            + `border:1px solid ${slot.image ? HUB.accent : HUB.hairline};`
            + (slot.image ? "" : "border-style:dashed;"));
        if (slot.image) {
            const img = el("img", `width:100%;height:100%;object-fit:contain;`);
            img.src = imageThumbUrl(slot.image, SLOT_PX * 2);
            img.loading = "lazy";
            img.draggable = false;
            attachHoverZoom(img, () => ({
                w: img.naturalWidth, h: img.naturalHeight,
                label: slot.asset, hint: slot.category,
                placeholder: img.src,
                src: () => imageFullUrl(slot.image),
            }));
            frame.appendChild(img);
        }
        cell.appendChild(frame);
        const name = el("div",
            "width:100%;overflow:hidden;text-overflow:ellipsis;"
            + "white-space:nowrap;"
            + (slot.image ? "" : `color:${HUB.inkTertiary};`),
            slot.asset);
        name.title = `${slot.asset}${slot.category ? ` · ${slot.category}` : ""}`;
        cell.appendChild(name);
        return cell;
    }

    function render() {
        list.replaceChildren();
        hideHoverZoom();
        const board = node._symBoard;
        if (!board?.slots?.length) {
            list.appendChild(emptyState(
                node.inputs?.find((i) => i.name === "order")?.link != null
                    ? "queue this node once to read the board"
                    : "wire an Order Specs (or an Asset Focus) into order"));
            refit();
            return;
        }
        const { done, total, slots } = board;
        const percent = total ? Math.round((done / total) * 100) : 0;
        list.appendChild(el("div",
            "width:100%;box-sizing:border-box;overflow:hidden;"
            + `padding:2px 3px 4px;color:${HUB.inkSubtle};`,
            `${done}/${total} done · ${percent}%`
            + `${board.feature ? ` · ${board.feature}` : ""}`));
        // The bar IS the progress: a rectangle as wide as the work that is
        // finished, over one as wide as the work there is.
        const track = el("div", "width:100%;box-sizing:border-box;height:4px;"
            + `border-radius:2px;background:${HUB.hairline};overflow:hidden;`
            + "margin:0 0 6px;");
        track.appendChild(el("div",
            `width:${percent}%;height:100%;background:${HUB.accent};`));
        list.appendChild(track);

        const grid = el("div", "display:flex;flex-wrap:wrap;gap:8px;"
            + "width:100%;box-sizing:border-box;overflow:hidden;");
        for (const slot of slots) grid.appendChild(slotTile(slot));
        list.appendChild(grid);
        refit();
    }

    node._symRenderTracker = render;
    render();
}

registerSymbioticaExtension(app, {
    name: "symbiotica.order_tracker",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            trackerPanel(this);
        };

        const onConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function (type, index,
                                                           connected, link,
                                                           ioSlot) {
            onConnectionsChange?.apply(this, arguments);
            if (ioSlot?.name === "order") {
                // A different order is a different board, and the one on
                // screen belongs to the order that produced it.
                this._symBoard = null;
                queueMicrotask(() => this._symRenderTracker?.());
            }
        };
    },
});

// The order arrives on a wire the canvas cannot read, so the run hands the
// board over — the same way Asset Focus hands over its choices.
api.addEventListener("symbiotica.tracker", (event) => {
    const detail = event?.detail ?? {};
    if (detail.node_id == null) return;
    const node = app.graph?.getNodeById?.(Number(detail.node_id))
        ?? app.graph?.getNodeById?.(detail.node_id);
    if (!node) return;
    node._symBoard = detail;
    node._symRenderTracker?.();
});
