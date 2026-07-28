// ABOUTME: registerExtension wrapper that makes a failed extension registration
// ABOUTME: loud on the canvas instead of a silent console line nobody reads.

// Why this exists: ComfyUI imports every file under a pack's web/ directory in
// parallel and swallows each import's error into a console.error. So when one of
// our modules throws while registering, the pack's nodes simply come up as their
// bare Python widgets — no buttons, no dropdowns, no panels — with nothing on
// screen saying why.
//
// The way that happened for real (2026-07-28): a stale `order_pipeline.v2360.js`
// was left behind on the Modal deploy volume by a cache workaround. ComfyUI globs
// `**/*.js`, so BOTH it and the current `order_pipeline.js` were served, and both
// called registerExtension with the name "symbiotica.order_pipeline". The
// frontend throws `Extension named '<name>' already registered.` on the second
// one — and since the two race, which copy won changed from reload to reload.
// The nodes worked intermittently for a week and four releases were spent
// "fixing" rendering code that was never running.
//
// This wrapper cannot prevent the collision. It makes it impossible to miss.

const BANNER_ID = "symbiotica-extension-error";

// One banner for the whole pack: several modules failing (the usual case when a
// whole directory is stale) should read as one problem, not stack up.
function showFailureBanner(name, err) {
    if (typeof document === "undefined" || !document.body) return;
    const existing = document.getElementById(BANNER_ID);
    if (existing) {
        const more = existing.querySelector("[data-sym-names]");
        if (more && !more.textContent.includes(name)) {
            more.textContent += `, ${name}`;
        }
        return;
    }
    const bar = document.createElement("div");
    bar.id = BANNER_ID;
    bar.style.cssText =
        "position:fixed;top:0;left:0;right:0;z-index:100000;padding:10px 14px;"
        + "background:#5a1f1f;color:#ffe6e6;border-bottom:1px solid #8a3a3a;"
        + "font:13px/1.45 system-ui,sans-serif;display:flex;gap:12px;"
        + "align-items:flex-start;box-shadow:0 2px 12px rgba(0,0,0,.45);";
    const text = document.createElement("div");
    text.style.cssText = "flex:1;min-width:0;";
    const head = document.createElement("div");
    head.style.cssText = "font-weight:600;margin-bottom:2px;";
    head.textContent = "⚠ Symbiotica frontend failed to load";
    const names = document.createElement("div");
    names.dataset.symNames = "1";
    names.style.cssText = "font-family:ui-monospace,monospace;font-size:12px;opacity:.85;";
    names.textContent = name;
    const hint = document.createElement("div");
    hint.style.cssText = "margin-top:4px;opacity:.9;";
    hint.textContent =
        `${err?.message ?? err} — Symbiotica nodes will show only their raw `
        + "widgets (no buttons, dropdowns, or panels). If this says \"already "
        + "registered\", a duplicate copy of the pack's JS is being served: look "
        + "for leftover versioned or backup .js files in the pack's web/ "
        + "directory and delete them. See the console for the full error.";
    text.append(head, names, hint);
    const close = document.createElement("button");
    close.textContent = "✕";
    close.setAttribute("aria-label", "Dismiss");
    close.style.cssText =
        "flex:none;background:transparent;border:0;color:#ffe6e6;cursor:pointer;"
        + "font-size:15px;line-height:1;padding:2px 4px;";
    close.addEventListener("click", () => bar.remove());
    bar.append(text, close);
    document.body.appendChild(bar);
}

// Drop-in for `app.registerExtension(spec)`. Registers as before; on failure
// logs with the pack tag and raises the on-screen banner. Never rethrows: one
// module dying must not take the rest of the pack's extensions with it.
export function registerSymbioticaExtension(app, spec) {
    const name = spec?.name ?? "(unnamed)";
    try {
        app.registerExtension(spec);
        return true;
    } catch (err) {
        console.error(
            `[symbiotica] extension "${name}" failed to register. Its nodes will `
            + "render with raw widgets only. A \"already registered\" error means "
            + "a duplicate copy of this file is being served — remove stale "
            + "versioned/backup .js files from the pack's web/ directory.", err);
        showFailureBanner(name, err);
        return false;
    }
}
