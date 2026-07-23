// ABOUTME: Shared dark-theme design tokens for this pack's web/js, lifted from the
// ABOUTME: symbiotica hub (apps/web DESIGN.md) so nodes read as native hub surfaces.

// The base palette every node extension styles against. surface-1/2 stack above
// the ComfyUI canvas; coral is the single brand accent (used only on the primary
// action + focus ring); the ink levels are the text hierarchy; hairlines separate.
export const HUB = {
    ink: "#f7f8f8", inkSubtle: "#8a8f98", inkTertiary: "#62666d",
    surface1: "#0f1011", surface2: "#141516", rowHover: "#1c1d20",
    accent: "#f86145", onAccent: "#ffffff", danger: "#f2777a",
    hairline: "#23252a", hairlineStrong: "#34343a",
    radius: { sm: "6px", md: "8px", lg: "12px" },
    font: "'Inter', system-ui, -apple-system, sans-serif",
    mono: "'Geist Mono', ui-monospace, SFMono-Regular, monospace",
};

// Interaction states (:hover/:focus/::placeholder) that inline styles can't
// express, as reusable utility classes. Call once per overlay/panel. Guarded on
// document.head so a test DOM stub without a head simply skips it — inline styles
// still render. Idempotent: the stylesheet is injected at most once.
//   sym-row / sym-name   list rows and their clickable label
//   sym-btn / sym-btn-accent   ghost and accent buttons
//   sym-input   text/search inputs
export function injectHubStyles() {
    if (!document.head || document.getElementById("symbiotica-hub-theme")) return;
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
}

// A ghost button's inline style (transparent, hairline border). Pair with the
// `sym-btn` class for hover. Kept as a string so callers assign it to cssText.
export const ghostButtonCss =
    `padding:6px 12px;background:transparent;color:${HUB.inkSubtle};` +
    `border:1px solid ${HUB.hairline};border-radius:${HUB.radius.md};` +
    `cursor:pointer;font:12px ${HUB.font};`;
