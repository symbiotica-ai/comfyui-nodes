// ABOUTME: Shared design tokens for this pack's web/js, lifted from the symbiotica
// ABOUTME: hub (apps/web DESIGN.md), in a dark and a light set that follow ComfyUI.

// The two palettes. surface-1/2 stack above the ComfyUI canvas; coral is the
// single brand accent (used only on the primary action + focus ring); the ink
// levels are the text hierarchy; hairlines separate. DARK is the hub's own set
// and is what these panels have always looked like; LIGHT is the same structure
// inverted, so a panel on ComfyUI's light palette stops being a black island.
const DARK = {
    ink: "#f7f8f8", inkSubtle: "#8a8f98", inkTertiary: "#62666d",
    surface1: "#0f1011", surface2: "#141516", rowHover: "#1c1d20",
    accent: "#f86145", onAccent: "#ffffff", danger: "#f2777a", ok: "#8fbf8f",
    hairline: "#23252a", hairlineStrong: "#34343a",
    // The "this one is picked" fill, for chips and toggles, and the "this one
    // is off/removed" fill beside it.
    selLine: "#7aa2e8", selBg: "#24406b", selInk: "#dbe6ff",
    dangerBg: "#4a2626", mat: "#111213",
};
const LIGHT = {
    ink: "#1c1e21", inkSubtle: "#5b6169", inkTertiary: "#8a8f98",
    surface1: "#ffffff", surface2: "#f2f3f5", rowHover: "#e9ebee",
    accent: "#f86145", onAccent: "#ffffff", danger: "#c0392b", ok: "#2e7d32",
    hairline: "#d9dce1", hairlineStrong: "#bcc1c9",
    selLine: "#3b6fb5", selBg: "#dbe7f8", selInk: "#123a68",
    dangerBg: "#f7dede", mat: "#e4e6ea",
};

// Every colour token is handed out as a `var()`, never as a hex. A panel builds
// its style string once, at render, but the palette can change under it at any
// time — switching ComfyUI's theme rewrites CSS variables and repaints nothing
// else. Referencing a variable means the browser repaints our panels too,
// with no reload and no re-render path to remember to call.
// The fallback is the dark hex, so a panel rendered before the stylesheet lands
// — or in a test DOM that has no head — looks exactly as it always has.
const colorTokens = Object.fromEntries(
    Object.entries(DARK).map(([k, v]) => [k, `var(--sym-${k}, ${v})`]));

export const HUB = {
    ...colorTokens,
    radius: { sm: "6px", md: "8px", lg: "12px" },
    font: "'Inter', system-ui, -apple-system, sans-serif",
    mono: "'Geist Mono', ui-monospace, SFMono-Regular, monospace",
};

// The raw sets, for the rare caller that needs a real colour (a canvas fill,
// a computed contrast) rather than a variable reference.
export const HUB_PALETTES = { dark: DARK, light: LIGHT };

// The tokens ComfyUI already has an answer for, mapped onto its own variables.
// A widget in one of our panels should look like a widget in any other node —
// same fill, same text, same border — and the only way that holds through a
// palette change, a user theme or a future ComfyUI restyle is to take the value
// from ComfyUI rather than to publish a second opinion about it. The sets above
// stay as the fallback for an install that does not define one.
const COMFY_VARS = {
    ink: "--input-text",
    inkSubtle: "--descrip-text",
    inkTertiary: "--drag-text",
    surface1: "--comfy-input-bg",        // the widget fill — the grey pill
    surface2: "--comfy-menu-secondary-bg",
    rowHover: "--comfy-menu-bg",
    hairline: "--border-color",
    hairlineStrong: "--border-color",
};

const asDeclarations = (set) => Object.entries(set)
    .map(([k, v]) => `--sym-${k}:`
        + (COMFY_VARS[k] ? `var(${COMFY_VARS[k]}, ${v})` : v) + ";")
    .join("");

// ComfyUI does not announce its palette, so read it off the canvas: every theme
// sets --bg-color, and its luminance is the one thing a light theme and a dark
// theme cannot agree on. Anything brighter than mid-grey is a light theme.
function isLightPalette() {
    const root = document.documentElement;
    if (!root || typeof getComputedStyle !== "function") return false;
    const cs = getComputedStyle(root);
    const raw = (cs.getPropertyValue("--bg-color")
        || cs.getPropertyValue("--comfy-menu-bg") || "").trim();
    const rgb = parseColor(raw);
    if (!rgb) return false;
    // Rec. 601 luma is enough to separate #DDD from #202020.
    return (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) > 140;
}

function parseColor(value) {
    if (!value) return null;
    const hex = value.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
    if (hex) {
        const h = hex[1].length === 3
            ? hex[1].split("").map((c) => c + c).join("") : hex[1];
        return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
    }
    const rgb = value.match(/rgba?\(([^)]+)\)/i);
    if (rgb) {
        const parts = rgb[1].split(",").map((n) => parseFloat(n));
        if (parts.length >= 3 && parts.every((n) => !Number.isNaN(n))) {
            return parts.slice(0, 3);
        }
    }
    return null;
}

// Write the active set onto :root. Called on injection and again whenever
// ComfyUI rewrites its own variables, which is how a theme switch reaches us.
function applyPalette() {
    const holder = document.getElementById("symbiotica-hub-palette");
    if (!holder) return;
    const set = isLightPalette() ? LIGHT : DARK;
    const next = `:root{${asDeclarations(set)}}`;
    if (holder.textContent !== next) holder.textContent = next;
}

// Interaction states (:hover/:focus/::placeholder) that inline styles can't
// express, as reusable utility classes. Call once per overlay/panel. Guarded on
// document.head so a test DOM stub without a head simply skips it — inline styles
// still render. Idempotent: the stylesheet is injected at most once.
//   sym-row / sym-name   list rows and their clickable label
//   sym-btn / sym-btn-accent   ghost and accent buttons
//   sym-input   text/search inputs
export function injectHubStyles() {
    if (!document.head || document.getElementById("symbiotica-hub-theme")) return;
    const palette = document.createElement("style");
    palette.id = "symbiotica-hub-palette";
    document.head.appendChild(palette);
    const s = document.createElement("style");
    s.id = "symbiotica-hub-theme";
    s.textContent = `
.sym-row{border-radius:${HUB.radius.md};transition:background .1s ease;}
.sym-row:hover{background:${HUB.rowHover};}
.sym-name{cursor:pointer;}
.sym-btn{transition:border-color .1s ease,color .1s ease;}
.sym-btn:hover{border-color:${HUB.hairlineStrong};color:${HUB.ink};}
.sym-btn-accent:hover{filter:brightness(1.08);}
.sym-input::placeholder{color:${HUB.inkTertiary};}
.sym-input:focus{outline:none;border-color:${HUB.accent};}`;
    document.head.appendChild(s);
    applyPalette();
    // The palette lives in inline variables on :root, so its own mutation is
    // the switch signal — no ComfyUI event to subscribe to, and none needed.
    if (typeof MutationObserver === "function") {
        new MutationObserver(applyPalette).observe(document.documentElement, {
            attributes: true, attributeFilter: ["style", "class"],
        });
    }
}

// A ghost button's inline style (transparent, hairline border). Pair with the
// `sym-btn` class for hover. Kept as a string so callers assign it to cssText.
export const ghostButtonCss =
    `padding:6px 12px;background:transparent;color:${HUB.inkSubtle};` +
    `border:1px solid ${HUB.hairline};border-radius:${HUB.radius.md};` +
    `cursor:pointer;font:12px ${HUB.font};`;
