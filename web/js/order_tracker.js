// ABOUTME: Order Tracker panel — one slot per asset the order asks for, filled
// ABOUTME: with the approved render or left empty. The month's work at a glance,
// ABOUTME: read off the same folders the Pick node lists.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { HUB, injectHubStyles } from "./hub_theme.js";
import { attachHoverZoom, el, emptyState, hideHoverZoom, imageFullUrl,
         imageThumbUrl, pinPanelWidth } from "./browser_chrome.js";

const NODE_CLASS = "SymbioticaOrderTracker";
const MIN_NODE_W = 320;
const SLOT_PX = 72;
// What a filled slot sits on. These renders are background-removed, so the
// backing IS visible through them: on near-black a pale asset reads as a
// silhouette and a dark one disappears into it. Mid grey shows both.
const SLOT_BACKING = "#808080";

async function fetchJson(url, options) {
    const res = await api.fetchApi(url, options);
    if (!res.ok) {
        throw new Error((await res.json().catch(() => ({})))?.error
                        ?? res.statusText);
    }
    return res.json();
}

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
    // The wrapper ComfyUI gives this widget lags a SHRINK, so pin it or the
    // slots paint over the canvas to the right of a narrowed node.
    const syncPanelWidth = pinPanelWidth(node, container);
    const refit = () => requestAnimationFrame(() => {
        syncPanelWidth();
        node.setDirtyCanvas?.(true, true);
    });

    // Send one approved render back for another try. It MOVES the `_final`
    // into `discarded/` under the same folder rather than deleting it — the
    // same thing the picker's ✕ does, and for the same reason: several of
    // these cost real money and the board exists to judge them.
    //
    // Two clicks: the first arms, the second does it. A single click on a
    // tile-sized target is too easy to hit by accident, and this one empties a
    // slot that took a render to fill.
    function rejectButton(slot) {
        let armed = false;
        const button = el("button",
            "position:absolute;top:2px;right:2px;padding:0 4px;line-height:14px;"
            + `border:1px solid ${HUB.hairlineStrong};border-radius:3px;`
            + `background:rgba(0,0,0,.55);color:${HUB.ink};cursor:pointer;`
            + "font:10px " + HUB.font + ";", "✕");
        button.style.display = "none";
        button.title = "Reject — move this approval to discarded/";
        const arm = () => {
            armed = true;
            button.textContent = "✕?";
            button.style.background = HUB.danger;
        };
        button.addEventListener("pointerdown", (e) => e.stopPropagation());
        button.addEventListener("click", async (e) => {
            e.stopPropagation();
            if (!armed) { arm(); return; }
            button.disabled = true;
            try {
                await fetchJson("/symbiotica/tracker-reject", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ path: slot.image }),
                });
                // The board is a reading of disk, and disk just changed —
                // empty the slot here rather than make him re-queue to see it.
                slot.image = null;
                const board = node._symBoard;
                if (board) board.done = board.slots.filter((s) => s.image).length;
                render();
            } catch (err) {
                button.disabled = false;
                button.title = err.message || "could not reject that";
                button.style.background = HUB.danger;
            }
        });
        return button;
    }

    function slotTile(slot) {
        const cell = el("div", "display:flex;flex-direction:column;gap:3px;"
            + `width:${SLOT_PX}px;flex:none;`);
        // An empty slot is work left, so it must not paint like a render that
        // came out black: `HUB.surface1` is a dark-theme token and fills the
        // tile solid on ComfyUI's light palette. Only a filled slot gets a
        // backing, and it gets it behind an image.
        const frame = el("div",
            `width:${SLOT_PX}px;height:${SLOT_PX}px;border-radius:5px;`
            + "display:flex;align-items:center;justify-content:center;"
            + `border:1px solid ${slot.image ? HUB.accent : HUB.hairline};`
            + (slot.image
                ? `background:${SLOT_BACKING};`
                : "border-style:dashed;background:transparent;"));
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
            frame.style.position = "relative";
            frame.appendChild(rejectButton(slot));
        }
        cell.appendChild(frame);
        if (slot.image) {
            // Shown on hover only: nine ✕ buttons on a full board is a wall of
            // controls over the work they describe.
            const reject = frame.children[1];
            cell.addEventListener("mouseenter",
                                  () => { reject.style.display = "block"; });
            cell.addEventListener("mouseleave",
                                  () => { reject.style.display = "none"; });
        }
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
        // The count and the bar stay put while the slots scroll under them —
        // they answer "how far in am I", which is the question you are still
        // asking on the fortieth asset. Opaque, or the tiles read through it.
        const head = el("div",
            "position:sticky;top:0;z-index:2;"
            + "width:100%;box-sizing:border-box;overflow:hidden;"
            + `background:var(--comfy-menu-bg, ${HUB.surface1});`
            + "padding:2px 3px 4px;");
        head.appendChild(el("div",
            "width:100%;box-sizing:border-box;overflow:hidden;"
            + `color:${HUB.inkSubtle};`,
            `${done}/${total} done · ${percent}%`
            + `${board.feature ? ` · ${board.feature}` : ""}`));
        // The bar IS the progress: a rectangle as wide as the work that is
        // finished, over one as wide as the work there is.
        const track = el("div", "width:100%;box-sizing:border-box;height:4px;"
            + `border-radius:2px;background:${HUB.hairline};overflow:hidden;`
            + "margin:2px 0 0;");
        track.appendChild(el("div",
            `width:${percent}%;height:100%;background:${HUB.accent};`));
        head.appendChild(track);
        list.appendChild(head);

        // Grouped by category, first-appearance order — the same shape the
        // Asset Focus list reads in, and the order the run itself is grouped
        // in, so the two panels describe one order the same way.
        const groups = new Map();
        for (const slot of slots) {
            const key = String(slot.category ?? "").trim();
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(slot);
        }
        for (const [category, members] of groups) {
            const filled = members.filter((s) => s.image).length;
            list.appendChild(el("div",
                "display:flex;align-items:baseline;gap:6px;width:100%;"
                + "box-sizing:border-box;overflow:hidden;text-overflow:ellipsis;"
                + "white-space:nowrap;padding:6px 3px 3px;"
                + `border-bottom:1px solid ${HUB.hairline};margin-bottom:4px;`
                + `color:${HUB.inkSubtle};`,
                `${category || "uncategorised"} · ${filled}/${members.length}`));
            const grid = el("div", "display:flex;flex-wrap:wrap;gap:8px;"
                + "width:100%;box-sizing:border-box;overflow:hidden;"
                + "margin-bottom:6px;");
            for (const slot of members) grid.appendChild(slotTile(slot));
            list.appendChild(grid);
        }
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
