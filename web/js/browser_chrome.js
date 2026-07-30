// ABOUTME: The folder-browser chrome shared by this pack's browsers — nav bar,
// ABOUTME: filter box, folder/file rows — so they look and behave like one tool.

// These are the pieces the Studio Library overlay established (↑ up + breadcrumb,
// "Filter this folder…", a folder-first row list with 📁/🖼 labels). The Reference
// Browser renders them inside a node instead of an overlay, which is a layout
// difference, not a visual one — so the parts live here rather than being drawn
// twice with drifting styles.
import { HUB, ghostButtonCss } from "./hub_theme.js";

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
