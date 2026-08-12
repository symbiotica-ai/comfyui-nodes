// ABOUTME: The shared palette — tokens are variables, and the set behind them
// ABOUTME: follows ComfyUI's theme instead of being dark forever.
import test from "node:test";
import assert from "node:assert/strict";

import { HUB, HUB_PALETTES, injectHubStyles } from "../../web/js/hub_theme.js";

// A document just deep enough for the injector: a head that collects styles and
// a documentElement whose computed --bg-color decides the palette.
function fakeDocument(bgColor) {
    const styles = [];
    const doc = {
        head: {
            appendChild(node) { styles.push(node); return node; },
        },
        documentElement: { _bg: bgColor },
        createElement: () => ({ id: "", textContent: "" }),
        getElementById: (id) => styles.find((s) => s.id === id) ?? null,
    };
    return { doc, styles };
}

function withDocument(bgColor, fn) {
    const previous = { doc: globalThis.document, gcs: globalThis.getComputedStyle };
    const { doc, styles } = fakeDocument(bgColor);
    globalThis.document = doc;
    globalThis.getComputedStyle = (el) => ({
        getPropertyValue: (name) => (name === "--bg-color" ? el._bg : ""),
    });
    try {
        return fn(styles);
    } finally {
        globalThis.document = previous.doc;
        globalThis.getComputedStyle = previous.gcs;
    }
}

const paletteText = (styles) =>
    styles.find((s) => s.id === "symbiotica-hub-palette")?.textContent ?? "";

test("a colour token is a variable with the dark value as its fallback", () => {
    // The fallback is what a panel rendered before the stylesheet lands — or in
    // a test DOM with no head — paints with, so it must stay the hub's dark set.
    assert.equal(HUB.ink, `var(--sym-ink, ${HUB_PALETTES.dark.ink})`);
    assert.equal(HUB.surface1, `var(--sym-surface1, ${HUB_PALETTES.dark.surface1})`);
    assert.match(HUB.hairline, /^var\(--sym-hairline, #/);
    // Non-colour tokens are still plain values.
    assert.equal(HUB.radius.md, "8px");
});

test("a widget token takes its value from ComfyUI's own variable", () => {
    // A field in one of our panels has to look like a field in any other node,
    // so the fill, the text and the border come from ComfyUI, not from us.
    withDocument("#DDD", (styles) => {
        injectHubStyles();
        const css = paletteText(styles);
        assert.match(css, /--sym-surface1:var\(--comfy-input-bg, /);
        assert.match(css, /--sym-ink:var\(--input-text, /);
        assert.match(css, /--sym-hairline:var\(--border-color, /);
        // The brand tokens are ours — ComfyUI has no opinion about them.
        assert.match(css, new RegExp(`--sym-accent:${HUB_PALETTES.light.accent};`));
    });
});

test("ComfyUI's light canvas selects the light fallbacks", () => {
    withDocument("#DDD", (styles) => {
        injectHubStyles();
        const css = paletteText(styles);
        assert.match(css, /--sym-surface1:var\(--comfy-input-bg, #ffffff\);/);
        assert.match(css, new RegExp(`--sym-ink:var\\(--input-text, ${HUB_PALETTES.light.ink}\\);`));
    });
});

test("ComfyUI's dark canvas keeps the hub's own set", () => {
    withDocument("#202020", (styles) => {
        injectHubStyles();
        const css = paletteText(styles);
        assert.match(css,
            new RegExp(`--sym-surface1:var\\(--comfy-input-bg, ${HUB_PALETTES.dark.surface1}\\);`));
        assert.match(css,
            new RegExp(`--sym-ink:var\\(--input-text, ${HUB_PALETTES.dark.ink}\\);`));
    });
});

test("an rgb() canvas colour is read as well as a hex one", () => {
    withDocument("rgb(240, 240, 240)", (styles) => {
        injectHubStyles();
        assert.match(paletteText(styles), /--sym-surface1:var\(--comfy-input-bg, #ffffff\);/);
    });
});

test("a head-less DOM skips injection instead of throwing", () => {
    const previous = globalThis.document;
    globalThis.document = { body: {} };
    try {
        assert.doesNotThrow(() => injectHubStyles());
    } finally {
        globalThis.document = previous;
    }
});
