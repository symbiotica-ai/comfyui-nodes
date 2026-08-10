// ABOUTME: The folder-browser chrome shared by this pack's browsers — nav bar,
// ABOUTME: filter box, folder/file rows — so they look and behave like one tool.

// These are the pieces the Studio Library overlay established (↑ up + breadcrumb,
// "Filter this folder…", a folder-first row list with 📁/🖼 labels). The Reference
// Browser renders them inside a node instead of an overlay, which is a layout
// difference, not a visual one — so the parts live here rather than being drawn
// twice with drifting styles.
import { api } from "../../../scripts/api.js";
import { HUB, ghostButtonCss } from "./hub_theme.js";

// --- image URLs --------------------------------------------------------------
// Keep the /api/ prefix: ComfyUI mirrors custom routes under /api/ locally AND
// the Modal gateway proxies /api/* only, so a root-level /symbiotica/* would
// blank every thumbnail there.
//
// `imageThumbUrl` resizes per request and leaves nothing on disk, so a panel
// drawing thirty tiles asks for thirty small PNGs instead of thirty renders.
// `imageFullUrl` is the same file at full size, for opening or for a hover
// preview's final swap. Both take an ABSOLUTE path the server has registered.
export const imageThumbUrl = (path, px) => api.apiURL(
    `/symbiotica/pick-thumb?px=${px}&path=${encodeURIComponent(path)}`);
export const imageFullUrl = (path) => api.apiURL(
    `/symbiotica/local-image?path=${encodeURIComponent(path)}`);

export function el(tag, style = "", text = "") {
    const d = document.createElement(tag);
    if (style) d.style.cssText = style;
    if (text) d.textContent = text;
    return d;
}

// ↑ up · breadcrumb · (caller's own trailing controls). `onUp` fires only while
// the button is shown; call setUp(canGoUp) after every listing.
export function navBar({ onUp }) {
    const bar = el("div", "display:flex;align-items:center;gap:8px;padding:4px 2px;"
        + `border-bottom:1px solid ${HUB.hairline};margin-bottom:4px;`);
    const up = el("button", ghostButtonCss + "padding:3px 8px;flex:none;", "↑ up");
    up.className = "sym-btn";
    up.addEventListener("click", (e) => { e.stopPropagation(); onUp(); });
    const crumb = el("div",
        `flex:1;min-width:0;font:11px ${HUB.mono};color:${HUB.inkSubtle};`
        + "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;direction:rtl;"
        + "text-align:left;");
    bar.append(up, crumb);
    return {
        bar,
        crumb,
        setUp: (canGoUp) => { up.style.display = canGoUp ? "" : "none"; },
        // The caller appends its own buttons (refresh, counters) to the right.
        append: (...nodes) => bar.append(...nodes),
    };
}

export function filterBox(onInput, placeholder = "Filter this folder…") {
    const input = el("input",
        `width:100%;box-sizing:border-box;padding:4px 8px;background:${HUB.surface1};`
        + `color:${HUB.ink};border:1px solid ${HUB.hairlineStrong};border-radius:6px;`
        + `font:11px ${HUB.font};margin-bottom:4px;`);
    input.className = "sym-input";
    input.type = "search";
    input.placeholder = placeholder;
    // A node's DOM widget sits on the LiteGraph canvas: without this, typing
    // moves the graph (space/arrows) and the canvas steals the keystrokes.
    input.addEventListener("keydown", (e) => e.stopPropagation());
    input.addEventListener("input", () => onInput(input.value));
    return input;
}

// Case-insensitive substring match on `name`, the same rule the Studio Library
// filter uses: it narrows the CURRENT level only, it does not search into
// unopened folders.
export function filterByName(entries, query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return entries;
    return entries.filter((e) => e.name.toLowerCase().includes(q));
}

export function emptyState(text) {
    return el("div",
        `padding:12px 8px;text-align:center;color:${HUB.inkTertiary};font:11px ${HUB.font};`,
        text);
}

export function errorLine(text) {
    return el("div", `padding:6px 8px;color:${HUB.danger};font:11px ${HUB.font};`, text);
}

// --- hover zoom --------------------------------------------------------------
// A tile small enough that forty fit on a node is too small to judge a render
// by, and the only way to see one bigger was to open a browser tab and lose the
// grid. Hovering one floats it, big, next to the grid it came from.
//
// The frame lives on `document.body`, NOT inside the node: the panel is a
// scroll box that clips its own children, and the canvas scales the DOM-widget
// layer, so a preview drawn inside the node would be clipped by the first and
// shrunk with the second — a zoomed-out graph would zoom the preview out too.
// Fixed positioning also means the preview is the same size at every canvas
// zoom, which is the point of it.
const ZOOM_DELAY_MS = 130;   // sweeping across a grid must not flash previews
const ZOOM_MAX_PX = 720;
const ZOOM_GAP = 10;         // between the tile and the frame
const ZOOM_EDGE = 8;         // and between the frame and the window edge

// Alpha is a thing being judged here: a background-removed render shown on
// solid black reads as approved when it is not. The frame checkers behind it.
const CHECKER = "linear-gradient(45deg,#2a2a2a 25%,transparent 25%),"
    + "linear-gradient(-45deg,#2a2a2a 25%,transparent 25%),"
    + "linear-gradient(45deg,transparent 75%,#2a2a2a 75%),"
    + "linear-gradient(-45deg,transparent 75%,#2a2a2a 75%)";

let zoomFrame = null;
let zoomTimer = null;

function zoomBox() {
    // One frame for the whole app, reused: N tiles must not mean N nodes on
    // the body, and a re-render of a grid must not orphan the one on screen.
    if (zoomFrame?.parentElement) return zoomFrame;
    zoomFrame = el("div",
        "position:fixed;left:0;top:0;z-index:1500;display:none;"
        + "pointer-events:none;border-radius:6px;overflow:hidden;"
        + `border:1px solid ${HUB.hairlineStrong};`
        + "box-shadow:0 10px 30px rgba(0,0,0,.55);");
    zoomFrame.appendChild(el("img", "display:block;width:100%;height:100%;"
        + "object-fit:contain;"));
    // The caption IS the tooltip: the frame beats the browser's own title box
    // to the screen by most of a second, and that box would land on top of the
    // image being judged. Centred under it, so it reads as part of the frame
    // rather than a label stuck in a corner.
    const caption = el("div",
        "position:absolute;left:0;right:0;bottom:0;padding:4px 8px;"
        + "background:rgba(0,0,0,.62);text-align:center;");
    const oneLine = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
    caption.appendChild(el("div",
        `font:11px ${HUB.font};color:${HUB.ink};${oneLine}`));
    caption.appendChild(el("div",
        `font:10px ${HUB.font};color:${HUB.inkTertiary};${oneLine}`));
    zoomFrame.appendChild(caption);
    document.body.appendChild(zoomFrame);
    return zoomFrame;
}

export function hideHoverZoom() {
    clearTimeout(zoomTimer);
    zoomTimer = null;
    if (zoomFrame) {
        zoomFrame.style.display = "none";
        // Drop the image: a hidden frame holding a 720px PNG keeps it decoded,
        // and the next hover would flash the previous render for a frame.
        zoomFrame.children[0].src = "";
        zoomFrame.style.backgroundImage = "";
    }
}

// The box the preview is drawn at: the tile's own aspect, as large as fits in
// the window, so nothing letterboxes and the frame never jumps once the full
// image lands.
function zoomFit(w, h) {
    const vw = (window.innerWidth || 1280) - ZOOM_EDGE * 2;
    const vh = (window.innerHeight || 800) - ZOOM_EDGE * 2;
    const cap = Math.max(160, Math.min(ZOOM_MAX_PX, vw, vh));
    if (!w || !h) return { w: cap, h: cap };
    const scale = Math.min(cap / w, cap / h);
    return { w: Math.round(w * scale), h: Math.round(h * scale) };
}

// Beside the tile if there is room, otherwise the other side, otherwise pinned
// to the edge — a preview half off the window is not a preview.
function zoomPlace(rect, box) {
    const vw = window.innerWidth || 1280;
    const vh = window.innerHeight || 800;
    const clamp = (v, max) => Math.max(ZOOM_EDGE, Math.min(v, max - ZOOM_EDGE));
    let left = rect.right + ZOOM_GAP;
    if (left + box.w > vw - ZOOM_EDGE) {
        const leftSide = rect.left - ZOOM_GAP - box.w;
        left = leftSide >= ZOOM_EDGE ? leftSide : clamp(left, vw - box.w);
    }
    // Centred on the tile vertically, so the eye does not have to travel.
    const top = clamp(rect.top + rect.height / 2 - box.h / 2, vh - box.h);
    return { left: Math.round(left), top: Math.round(top) };
}

/**
 * Show `spec()` big while the pointer rests on `anchor`.
 *
 * `spec()` is read at hover time and returns
 * `{ w, h, label, hint, placeholder, src(px) }`: `label` and the dimmer `hint`
 * are the two centred lines under the image, `w`/`h` are the image's own pixel
 * size (the frame takes its aspect), `src(px)` is asked for the frame's longest
 * side in device pixels, and `placeholder` is the grid thumbnail the browser
 * already holds — it fills the frame instantly, soft, so the hover answers at
 * once and the sharp image swaps in over it.
 */
export function attachHoverZoom(anchor, spec) {
    anchor.addEventListener("pointerenter", () => {
        clearTimeout(zoomTimer);
        zoomTimer = setTimeout(() => {
            const rect = anchor.getBoundingClientRect?.();
            const detail = spec();
            if (!rect || !detail?.src) return;
            const box = zoomFit(detail.w, detail.h);
            const dpr = Math.min(2, window.devicePixelRatio || 1);
            // The route caps at 1024 and resizes per request, so asking for
            // exactly what is drawn costs one cached PNG per image per session.
            const src = detail.src(Math.min(1024,
                Math.round(Math.max(box.w, box.h) * dpr)));
            if (!src) return;
            const frame = zoomBox();
            const at = zoomPlace(rect, box);
            frame.style.width = `${box.w}px`;
            frame.style.height = `${box.h}px`;
            frame.style.left = `${at.left}px`;
            frame.style.top = `${at.top}px`;
            frame.style.backgroundImage = detail.placeholder
                ? `url("${detail.placeholder}"),${CHECKER}` : CHECKER;
            frame.style.backgroundSize = `contain,16px 16px,16px 16px,`
                + "16px 16px,16px 16px";
            frame.style.backgroundPosition = "center,0 0,0 8px,8px -8px,-8px 0";
            frame.style.backgroundRepeat = "no-repeat,repeat,repeat,repeat,repeat";
            frame.style.backgroundColor = HUB.surface1;
            frame.children[0].src = src;
            frame.children[1].children[0].textContent = detail.label ?? "";
            frame.children[1].children[1].textContent = detail.hint ?? "";
            frame.style.display = "block";
        }, ZOOM_DELAY_MS);
    });
    anchor.addEventListener("pointerleave", hideHoverZoom);
    // Anything that moves the tile out from under the frame closes it: a click
    // (which ticks, and re-renders the grid), a wheel (the panel scrolls, the
    // canvas zooms), a drag of the node itself.
    anchor.addEventListener("pointerdown", hideHoverZoom);
    anchor.addEventListener("wheel", hideHoverZoom, { passive: true });
}

// One folder row: [tick] 📁 name — the tick picks the folder, the name opens it.
export function folderRow({ name, checked, onToggle, onOpen }) {
    const row = el("div", "display:flex;align-items:center;gap:6px;padding:3px 4px;");
    row.className = "sym-row";
    const box = el("input", "flex:none;margin:0;cursor:pointer;");
    box.type = "checkbox";
    box.checked = !!checked;
    box.addEventListener("pointerdown", (e) => e.stopPropagation());
    box.addEventListener("change", () => onToggle(box.checked));
    const label = el("div",
        `flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;`
        + `color:${HUB.ink};font:11px ${HUB.font};`, `📁  ${name}`);
    label.className = "sym-name";
    label.addEventListener("pointerdown", (e) => e.stopPropagation());
    label.addEventListener("click", onOpen);
    row.append(box, label);
    return row;
}
