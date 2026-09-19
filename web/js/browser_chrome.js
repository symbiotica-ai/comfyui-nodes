// ABOUTME: The folder-browser chrome shared by this pack's browsers — nav bar,
// ABOUTME: filter box, folder/file rows — so they look and behave like one tool.

// These are the pieces the Studio Library overlay established (↑ up + breadcrumb,
// "Filter this folder…", a folder-first row list with 📁/🖼 labels). The Reference
// Browser renders them inside a node instead of an overlay, which is a layout
// difference, not a visual one — so the parts live here rather than being drawn
// twice with drifting styles.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { HUB, ghostButtonCss, injectHubStyles } from "./hub_theme.js";

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

// --- keeping a DOM panel inside its node -------------------------------------
// ComfyUI sizes a DOM widget's WRAPPER from the node width on its own layout
// pass, and that pass follows a WIDENING immediately but lags a SHRINK — it
// only catches up when something else re-lays-out the node. Narrow a node (or
// collapse it into a group) and the wrapper keeps the old width, so every row
// inside it paints over the canvas to the right, however carefully the rows
// themselves are contained.
//
// `width:100%` on the content cannot help: 100% of a wrapper that is too wide
// is too wide. The wrapper is the thing to constrain, and WRITING ITS WIDTH
// does not work: the frontend owns that property and re-writes it from its own
// layout every frame, so whoever writes last wins and it is never us.
//
// `max-width` is the property it does not touch, and CSS resolves it AFTER
// width whatever the order — an inline `width:900px` under an inline
// `max-width:300px` lays out at 300. So cap both boxes and leave `width` to
// the frontend: when its value is right nothing changes, when it lags a shrink
// the cap holds the panel inside the node, and when it culls the node to 0 the
// cap does not force it back open. The inset is a constant 20px at every width
// (320->300, 325->305, 520->500, 600->580).
const PANEL_INSET = 20;

/**
 * Cap `container` and its wrapper to the node's width, now and on every resize.
 * Returns the sync function so a render path can call it too — a re-render
 * inside a node that shrank while the panel was empty needs it.
 */
export function pinPanelWidth(node, container) {
    const sync = () => {
        const want = `${Math.max(0, node.size[0] - PANEL_INSET)}px`;
        // The ELEMENT first. Which box ComfyUI sizes has moved between frontend
        // versions — sometimes a wrapper, sometimes the element itself — so
        // capping only one fixes it on one build and does nothing on another.
        if (container.style.maxWidth !== want) container.style.maxWidth = want;
        // Fill whatever the wrapper gives, up to the cap, and clip our own
        // content rather than letting a wide row push the box open.
        if (container.style.width !== "100%") container.style.width = "100%";
        if (container.style.boxSizing !== "border-box") {
            container.style.boxSizing = "border-box";
        }
        if (container.style.overflowX !== "hidden") {
            container.style.overflowX = "hidden";
        }
        const wrap = container.parentElement;
        if (!wrap) return;
        // The cap first, so it is already in force whenever the frontend's own
        // width lands. Then the width itself, which is what a WIDENING needs:
        // the frontend can lag that too, and a cap alone cannot open a box the
        // frontend is holding narrow. This only ever runs for a node being
        // drawn, so a culled panel keeps the zero width that hides it.
        if (wrap.style.maxWidth !== want) wrap.style.maxWidth = want;
        if (wrap.style.width !== want) wrap.style.width = want;
        if (wrap.style.overflow !== "hidden") wrap.style.overflow = "hidden";
    };
    // onResize fires for a dragged shrink, but it is NOT enough on its own:
    // ComfyUI re-writes the wrapper from its own layout pass, so a one-shot
    // pin set before that pass is simply overwritten and the panel goes back
    // to hanging off the node. Re-asserting every frame is what makes it
    // stick — it is a width comparison against a number already in memory, so
    // the cost is nothing, and it covers every way a node can get narrower:
    // the drag, a group collapse, a workflow load, an undo.
    for (const hook of ["onResize", "onDrawForeground"]) {
        const previous = node[hook];
        node[hook] = function () {
            const answer = previous?.apply(this, arguments);
            sync();
            return answer;
        };
    }
    return sync;
}

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
export const CHECKER = "linear-gradient(45deg,#2a2a2a 25%,transparent 25%),"
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

// --- the drawn icon family ---------------------------------------------------
// One family for every browser in the pack. An emoji and a text glyph never
// agree on size or weight — 📄📁 beside a ⟳ read as two different kinds of
// control — and only a stroked path can take the panel's own colour.
export const ICON = {
    newFile: "M4.3 1.9h4.8L12 4.8v9.3H4.3z M9.1 1.9v2.9H12 M8.2 8.3v3.7"
             + " M6.3 10.1h3.7",
    newFolder: "M2.2 13.2V3.8h4.1l1.2 1.5h6.3v7.9z M8 7.6v3.4 M6.3 8.7h3.4",
    refresh: "M13.3 8A5.3 5.3 0 1 1 11.6 4.1 M13.5 1.9v3h-3",
    rename: "M12 2.1a1.3 1.3 0 0 1 1.9 1.9l-7.5 7.5-2.6.7.7-2.6z",
    remove: "M3.4 4.5h9.2 M6.4 4.5V3.1h3.2v1.4 M4.8 4.5l.6 8.4h5.2l.6-8.4"
            + " M6.9 6.8v3.8 M9.1 6.8v3.8",
    collapse: "M9.8 3.6L5.4 8l4.4 4.4",
    expand: "M6.2 3.6L10.6 8l-4.4 4.4",
    upload: "M8 10.6V2.4 M4.8 5.6L8 2.4l3.2 3.2 M2.6 10.2v3.4h10.8v-3.4",
    search: "M7.2 2.6a4.6 4.6 0 1 0 0 9.2 4.6 4.6 0 0 0 0-9.2z M10.6 10.6l2.8 2.8",
    clear: "M4.2 4.2l7.6 7.6 M11.8 4.2l-7.6 7.6",
};

export const svgIcon = (d, px) =>
    `<svg width="${px}" height="${px}" viewBox="0 0 16 16" fill="none"`
    + ` stroke="currentColor" stroke-width="1.2" stroke-linecap="round"`
    + ` stroke-linejoin="round" style="display:block;pointer-events:none">`
    + `<path d="${d}"/></svg>`;

/** A bare icon button. It swallows its own pointerdown — one that reaches the
 * canvas drags the node out from under the click. */
export function iconButton(name, title, onClick, { px = 14, hover = "" } = {}) {
    const b = el("button",
        "flex:none;display:flex;align-items:center;padding:2px 3px;"
        + "background:transparent;border:0;border-radius:4px;cursor:pointer;"
        + `color:${HUB.inkSubtle};`);
    b.className = "sym-btn";
    b.title = title;
    b.innerHTML = svgIcon(ICON[name], px);
    if (hover) {
        b.addEventListener("pointerenter", () => { b.style.color = hover; });
        b.addEventListener("pointerleave", () => { b.style.color = HUB.inkSubtle; });
    }
    b.addEventListener("pointerdown", (e) => e.stopPropagation());
    b.addEventListener("click", (e) => { e.stopPropagation(); onClick(); });
    return b;
}

// --- a file tree inside a node -----------------------------------------------
export const ONE_LINE = "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;";
const INDENT_PX = 10;

/**
 * One row of a tree: [lead] name [actions]. `lead` is the caller's own leading
 * element — a chevron for a folder, a thumbnail for an image. `actions` appear
 * only while the pointer is on the row: an action on every row at once is a
 * column of clutter. Hidden with `visibility`, not opacity — an invisible
 * button you can still click is worse than none.
 */
export function treeRow({ kind, rel, depth, tone = "", lead, label,
                          labelColour, actions = [], onClick, height = "" }) {
    const row = el("div", "display:flex;align-items:center;gap:3px;"
        + `padding:2px 4px 2px ${4 + depth * INDENT_PX}px;cursor:pointer;`
        + (height ? `min-height:${height};` : "")
        + (tone ? `background:${tone};` : ""));
    row.className = "sym-row";
    // What a row IS, for the tests that click one.
    row._sym = { kind, rel };
    row.addEventListener("pointerdown", (e) => e.stopPropagation());
    if (lead) row.appendChild(lead);
    // A file name reads literally: Inter's contextual alternates turn `1x1`
    // into `1×1`, which is not what the folder is called or what you type to
    // rename it.
    const name = el("div", `flex:1;min-width:0;${ONE_LINE}color:${labelColour};`
        + "font-variant-ligatures:none;font-feature-settings:'calt' 0;",
        label);
    name.title = label;
    row.appendChild(name);
    for (const a of actions) a.style.visibility = "hidden";
    const show = (how) => { for (const a of actions) a.style.visibility = how; };
    if (actions.length) {
        row.addEventListener("pointerenter", () => show("visible"));
        row.addEventListener("pointerleave", () => show("hidden"));
        for (const a of actions) row.appendChild(a);
    }
    if (onClick) row.addEventListener("click", onClick);
    return row;
}

const dirOf = (rel) => (rel.includes("/") ? rel.slice(0, rel.lastIndexOf("/")) : "");
const baseOf = (rel) => rel.slice(rel.lastIndexOf("/") + 1);

/**
 * Every visible row, top to bottom: sub-folders before files at each level,
 * an open folder's contents under it. `make(kind, rel, depth)` builds each one.
 */
export function walkTree({ folders = [], files = [], open }, make) {
    const byName = (a, b) =>
        baseOf(a).localeCompare(baseOf(b), undefined, { sensitivity: "base" });
    const out = [];
    const walk = (parent, depth) => {
        for (const rel of folders.filter((f) => dirOf(f) === parent).sort(byName)) {
            out.push(make("folder", rel, depth));
            if (open.has(rel)) walk(rel, depth + 1);
        }
        for (const rel of files.filter((f) => dirOf(f) === parent).sort(byName)) {
            out.push(make("file", rel, depth));
        }
    };
    walk("", 0);
    return out;
}

// --- searching the whole tree ------------------------------------------------
// The tree answers "what is in this folder". A name you half-remember is a
// different question, and the fold that makes these nodes usable once a file is
// open takes the tree away with it. So the search sits ABOVE both panes, where
// the fold cannot reach it, and answers in a list of its own rather than by
// narrowing rows nobody can see.
const HIT_MAX = 40;
const MENU_MAX_PX = 220;

/**
 * Every file whose name or folder holds `query`, best first: the name STARTS
 * with it, then the name contains it, then only the folder does. Alphabetical
 * within a rank, and capped — a query of one letter must not draw the library.
 */
export function searchTree(files, query) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return [];
    const hits = [];
    for (const rel of files ?? []) {
        const at = baseOf(rel).toLowerCase().indexOf(q);
        const rank = at === 0 ? 0
            : at > 0 ? 1
            : rel.toLowerCase().includes(q) ? 2 : -1;
        if (rank >= 0) hits.push({ rel, rank });
    }
    hits.sort((a, b) => a.rank - b.rank
        || a.rel.localeCompare(b.rel, undefined, { sensitivity: "base" }));
    return hits.slice(0, HIT_MAX).map((h) => h.rel);
}

/**
 * The search box and the list of matches under it.
 *
 * `list()` is read at every keystroke, so a rename or a re-read lands in the
 * results without the field knowing anything happened; `lead(rel)` is the
 * caller's own leading element per row (a thumbnail); `onPick(rel)` is handed
 * the file and does whatever opening one means for that node.
 */
export function searchField({ placeholder = "Search…", list, lead, onPick }) {
    const row = el("div", "position:relative;display:flex;align-items:center;"
        + `gap:5px;flex:none;padding:3px 6px;background:${HUB.surface2};`
        + `border-bottom:1px solid ${HUB.hairline};`);
    const glass = el("span", `flex:none;display:flex;color:${HUB.inkTertiary};`);
    glass.innerHTML = svgIcon(ICON.search, 12);
    const input = el("input", "flex:1;min-width:0;padding:2px 0;"
        + "background:transparent;border:0;outline:none;"
        + `color:var(--input-text, ${HUB.ink});font:11px ${HUB.font};`);
    input.className = "sym-input";
    input.type = "text";
    input.placeholder = placeholder;
    const wipe = iconButton("clear", "Clear the search", () => {
        input.value = "";
        match();
        input.focus?.();
    }, { px: 11 });
    wipe.style.display = "none";
    // The list floats over the panes rather than pushing them down: a panel
    // that reflows while you type moves the thing you are aiming at.
    const menu = el("div", "position:absolute;left:6px;right:6px;top:100%;"
        + `z-index:5;display:none;max-height:${MENU_MAX_PX}px;overflow:auto;`
        + `background:${HUB.surface2};border:1px solid ${HUB.hairlineStrong};`
        + `border-radius:${HUB.radius.sm};box-shadow:0 8px 20px rgba(0,0,0,.45);`);
    menu.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });
    row._symPart = "search";
    menu._symPart = "hits";
    row.append(glass, input, wipe, menu);

    let hits = [];
    let at = 0;

    function close() {
        menu.style.display = "none";
        menu.replaceChildren();
        hits = [];
        at = 0;
    }

    function take(rel) {
        input.value = "";
        wipe.style.display = "none";
        close();
        onPick?.(rel);
    }

    function hitRow(rel, i) {
        const line = el("div", "display:flex;align-items:center;gap:6px;"
            + "padding:3px 6px;cursor:pointer;"
            + (i === at ? `background:${HUB.rowHover};` : ""));
        line.className = "sym-row";
        // What a row IS, for the tests that click one.
        line._symHit = rel;
        line.title = rel;
        const head = lead?.(rel);
        if (head) line.appendChild(head);
        // The name reads literally, as it does in the tree: Inter turns `1x1`
        // into `1×1`, which is not what you typed to find it.
        line.append(
            el("div", `flex:1;min-width:0;${ONE_LINE}color:${HUB.ink};`
                + "font-variant-ligatures:none;font-feature-settings:'calt' 0;",
                baseOf(rel)),
            el("div", `flex:none;max-width:45%;${ONE_LINE}`
                + `color:${HUB.inkTertiary};font:10px ${HUB.font};`, dirOf(rel)));
        line.addEventListener("pointerdown", (e) => e.stopPropagation());
        line.addEventListener("click", (e) => { e.stopPropagation(); take(rel); });
        return line;
    }

    function draw() {
        if (!input.value.trim()) { close(); return; }
        menu.replaceChildren(...(hits.length
            ? hits.map(hitRow) : [emptyState("no match")]));
        menu.style.display = "";
    }

    // `keep` holds the highlight on the row it was on — a re-read under an
    // open list must not move the target out from under the next Enter.
    function match({ keep = false } = {}) {
        const held = keep ? hits[at] : null;
        wipe.style.display = input.value ? "flex" : "none";
        hits = searchTree(list?.() ?? [], input.value);
        at = Math.max(0, hits.indexOf(held));
        draw();
    }

    input.addEventListener("pointerdown", (e) => e.stopPropagation());
    input.addEventListener("input", () => match());
    // A DOM widget sits on the LiteGraph canvas: without this, typing moves the
    // graph and the arrows that walk this list pan it instead.
    input.addEventListener("keydown", (e) => {
        e.stopPropagation();
        const key = String(e.key ?? "");
        if (key === "Escape") {
            input.value = "";
            match();
        } else if (key === "ArrowDown" || key === "ArrowUp") {
            if (!hits.length) return;
            e.preventDefault?.();
            at = Math.min(hits.length - 1,
                          Math.max(0, at + (key === "ArrowDown" ? 1 : -1)));
            draw();
        } else if (key === "Enter" && hits[at]) {
            e.preventDefault?.();
            take(hits[at]);
        }
    });

    return { row, input, close, refresh: () => { if (hits.length) match({ keep: true }); } };
}

const SIDE_MIN = 110;
// Shut, the sidebar keeps a rail wide enough for the one button that reopens
// it: a toggle you can only undo from a menu is a one-way door.
const SIDE_RAIL = 22;

/**
 * The two-pane panel this pack's file browsers share: a tree on the left under
 * a header of icons, a divider you can drag, a pane of the caller's own on the
 * right, and a toggle at the foot of the tree that folds it to a rail.
 *
 * The caller appends its own head and body to `main`, fills `tree` on every
 * render, and calls `layout()` first — it answers `true` while the tree is
 * shut, which is a tree there is no point building.
 *
 * `sideProp`/`shutProp` are node properties, not widgets: the width and the
 * fold are view preferences, and a widget for either would shift the saved
 * values of every workflow already holding the node.
 */
export function sidebarShell(node, { headButtons = [], sideProp, shutProp,
                                     sideDefault = 210, repaint, search }) {
    node.properties = node.properties ?? {};
    injectHubStyles();
    // A column, not a row: the search bar spans the whole panel above the two
    // panes, which is what keeps it on screen when the tree is folded away.
    const container = el("div", "box-sizing:border-box;width:100%;height:100%;"
        + "display:flex;flex-direction:column;overflow:hidden;"
        + `font:11px ${HUB.font};color:var(--input-text, ${HUB.ink});`
        + `background:${HUB.surface1};border-radius:${HUB.radius.sm};`);
    // Over a scrolling panel the wheel scrolls the panel; the canvas must not
    // zoom out from under it.
    container.addEventListener("wheel", (e) => e.stopPropagation(),
                               { passive: true });

    const side = el("div", "display:flex;flex-direction:column;min-width:0;"
        + `flex:none;overflow:hidden;background:${HUB.surface2};`
        + `border-right:1px solid ${HUB.hairline};`);
    const sideTitle = el("div", `flex:1;min-width:0;${ONE_LINE}`
        + `color:${HUB.inkSubtle};font-size:10px;letter-spacing:.06em;`
        + "text-transform:uppercase;");
    const sideHead = el("div", "display:flex;align-items:center;gap:1px;"
        + `padding:3px 4px;flex:none;background:${HUB.surface2};`
        + `border-bottom:1px solid ${HUB.hairline};`);
    sideHead.append(sideTitle, ...headButtons);
    const tree = el("div", "flex:1;min-height:0;overflow:auto;padding:2px 0;");

    const shut = () => !!node.properties?.[shutProp];
    const toggle = iconButton("collapse", "Hide the tree", () => {
        node.properties[shutProp] = !shut();
        repaint?.();
    }, { px: 12 });
    // `margin-top:auto` holds it at the bottom in BOTH states: with the tree
    // hidden there is nothing above it to push it down, and a button that
    // jumps to the top of the rail is one you have to hunt for to undo.
    const foot = el("div", "display:flex;align-items:center;flex:none;"
        + "margin-top:auto;"
        + `padding:2px 3px;border-top:1px solid ${HUB.hairline};`);
    foot.appendChild(toggle);
    side.append(sideHead, tree, foot);

    // The divider: drag it and the sidebar follows. The canvas can be zoomed,
    // so screen pixels are divided by its scale before they become node pixels.
    const grip = el("div", "flex:none;width:5px;margin:0 -2px;cursor:col-resize;"
        + "background:transparent;z-index:1;");
    grip.title = "Drag to resize";
    grip.addEventListener("pointerdown", (e) => {
        e.stopPropagation();
        e.preventDefault?.();
        const startX = e.clientX ?? 0;
        const startW = sideWidth();
        const scale = app.canvas?.ds?.scale || 1;
        const onMove = (ev) => {
            node.properties[sideProp] = startW + ((ev.clientX ?? 0) - startX) / scale;
            repaint?.();
        };
        const onUp = () => {
            window.removeEventListener("pointermove", onMove);
            window.removeEventListener("pointerup", onUp);
        };
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
    });

    const main = el("div", "flex:1;min-width:0;display:flex;"
        + "flex-direction:column;overflow:hidden;");
    const body = el("div", "flex:1;min-height:0;display:flex;"
        + "align-items:stretch;overflow:hidden;");
    body.append(side, grip, main);
    // What each box IS, for the tests that measure one — the shell is nested
    // now, and counting children from the top breaks on the next box added.
    side._symPart = "side";
    tree._symPart = "tree";
    main._symPart = "main";
    const finder = search ? searchField(search) : null;
    container.append(...(finder ? [finder.row] : []), body);

    function sideWidth() {
        if (shut()) return SIDE_RAIL;
        const held = Number(node.properties?.[sideProp]);
        const want = Number.isFinite(held) && held > 0 ? held : sideDefault;
        // Never wider than the node can show, and never so narrow it stops
        // being a tree.
        const room = Math.max(node.size[0] - PANEL_INSET, SIDE_MIN * 2);
        return Math.round(Math.max(SIDE_MIN, Math.min(want, room * 0.6)));
    }

    function layout() {
        const closed = shut();
        side.style.width = `${sideWidth()}px`;
        // Shut, the column is the toggle and nothing else — and the divider
        // goes with the tree, because there is no longer a width to drag.
        sideHead.style.display = closed ? "none" : "flex";
        tree.style.display = closed ? "none" : "";
        grip.style.display = closed ? "none" : "";
        foot.style.justifyContent = closed ? "center" : "flex-end";
        toggle.innerHTML = svgIcon(ICON[closed ? "expand" : "collapse"], 12);
        toggle.title = closed ? "Show the tree" : "Hide the tree";
        return closed;
    }

    return { container, side, sideTitle, sideHead, tree, grip, main, layout,
             search: finder };
}
