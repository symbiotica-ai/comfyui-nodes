// ABOUTME: Template editor dialog shell — full-screen overlay with hub layout:
// ABOUTME: left rail / top bar / center canvas / right inspector, open/save/close glue.
import { createEditorState } from "./state.js";
import { createCanvasPanel } from "./canvas.js";
import { renderRail } from "./rail.js";
import { renderInspector } from "./inspector.js";
import { presetDims } from "./algos.js";

const CSS = `
.sym-editor-overlay { position:fixed; inset:0; z-index:10000; background:#0a0a0a;
  color:#ddd; display:flex; flex-direction:column; font-size:12px;
  font-family:ui-sans-serif,system-ui,sans-serif; }
.sym-editor-header { display:flex; align-items:center; gap:12px; padding:8px 14px;
  border-bottom:1px solid #222; }
.sym-editor-header .title { font-size:15px; font-weight:600; }
.sym-editor-header .subtitle { opacity:.55; }
.sym-editor-header .close { margin-left:auto; cursor:pointer; font-size:18px;
  background:none; border:none; color:#ddd; }
.sym-editor-topbar { display:flex; gap:8px; padding:6px 14px; border-bottom:1px solid #222;
  align-items:center; }
.sym-editor-topbar input[type=text] { flex:1; background:#1a1a1a; border:1px solid #333;
  border-radius:6px; color:#ddd; padding:6px 10px; }
.sym-editor-body { flex:1; display:grid; grid-template-columns:300px 1fr 320px; min-height:0; }
.sym-editor-rail { border-right:1px solid #222; overflow-y:auto; padding:8px; }
.sym-editor-center { position:relative; overflow:hidden; background:#161616; }
.sym-editor-inspector { border-left:1px solid #222; overflow-y:auto; padding:8px; }
.sym-editor button { background:#2a2a2a; border:1px solid #444; border-radius:6px;
  color:#ddd; padding:4px 10px; cursor:pointer; font-size:12px; }
.sym-editor button:hover { background:#333; }
.sym-editor button.primary { border-color:#c33; color:#f66; }
.sym-editor button.active { background:#c33; border-color:#c33; color:#fff; }
.sym-editor .section-title { text-transform:uppercase; font-size:10px; opacity:.6;
  margin:10px 0 4px; letter-spacing:.06em; }
.sym-editor input, .sym-editor select, .sym-editor textarea { background:#1a1a1a;
  border:1px solid #333; border-radius:5px; color:#ddd; padding:3px 6px; font-size:12px; }
.sym-editor textarea { width:100%; resize:vertical; }
.sym-editor .row { display:flex; align-items:center; gap:6px; margin:3px 0; }
.sym-editor .row label { flex:1; opacity:.85; }
.sym-editor .footerbar { position:absolute; bottom:8px; left:50%; transform:translateX(-50%);
  background:#000a; padding:3px 12px; border-radius:6px; font-size:10px; opacity:.75;
  white-space:nowrap; }
`;

let styleInjected = false;

function ensureStyle() {
    if (styleInjected) return;
    const style = document.createElement("style");
    style.textContent = CSS;
    document.head.appendChild(style);
    styleInjected = true;
}

/**
 * Open the template editor.
 * opts: {
 *   api,                — ComfyUI api module (fetchApi, apiURL)
 *   init,               — createEditorState() init payload
 *   imageUrl(root,rel), — thumbnail/full image URL builder
 *   onSave(payload),    — async ({name, pngDataUrl, regions, settings, size, scenePrompt}) => savedRelKey
 *   listSaved(),        — async () => [{name, file, size, regions, settings}]
 *   loadAssets(dir),    — async => {root, images}
 * }
 */
export function openTemplateEditor(opts) {
    ensureStyle();
    const state = createEditorState(opts.init ?? {});
    const overlay = document.createElement("div");
    overlay.className = "sym-editor-overlay sym-editor";

    // ---- header ----
    const header = document.createElement("div");
    header.className = "sym-editor-header";
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = "TEMPLATE EDITOR";
    const name = document.createElement("span");
    name.className = "subtitle";
    const syncName = () => {
        name.textContent = state.loadedName
            ? `templates/${state.loadedName}.png`
            : "(unsaved template)";
    };
    syncName();
    state.on("template", syncName);
    const hint = document.createElement("span");
    hint.className = "subtitle";
    hint.textContent = "Regions come from the template's sprite frames — adjust, or draw extra ones.";
    const close = document.createElement("button");
    close.className = "close";
    close.textContent = "✕";
    close.addEventListener("click", () => {
        overlay.remove();
        opts.onClose?.(state);
    });
    header.append(title, name, hint, close);

    // ---- top bar ----
    const topbar = document.createElement("div");
    topbar.className = "sym-editor-topbar";
    const scene = document.createElement("input");
    scene.type = "text";
    scene.placeholder = "Scene prompt — the whole picture (empty → use the upstream text)";
    scene.value = state.scenePrompt;
    scene.addEventListener("input", () => { state.scenePrompt = scene.value; });
    const addRegion = document.createElement("button");
    addRegion.textContent = "+ Add region";
    addRegion.addEventListener("click", () => state.addRegion());
    const promptToggle = document.createElement("button");
    const syncPrompt = () => {
        promptToggle.textContent = state.promptHidden ? "🚫 Prompt" : "👁 Prompt";
    };
    syncPrompt();
    promptToggle.addEventListener("click", () => {
        state.promptHidden = !state.promptHidden;
        syncPrompt();
        state.emit("regions"); // canvas hides labels
    });
    topbar.append(scene, addRegion, promptToggle);

    // ---- body ----
    const body = document.createElement("div");
    body.className = "sym-editor-body";
    const rail = document.createElement("div");
    rail.className = "sym-editor-rail";
    const center = document.createElement("div");
    center.className = "sym-editor-center";
    const inspector = document.createElement("div");
    inspector.className = "sym-editor-inspector";
    body.append(rail, center, inspector);

    overlay.append(header, topbar, body);
    document.body.appendChild(overlay);

    // sheet size follows the preset
    const applyPreset = () => {
        const dims = presetDims(state.settings.preset);
        if (dims) state.setSheetSize(dims.w, dims.h);
        else state.setSheetSize(state.settings.maxWidth, state.settings.maxHeight);
    };
    state.on("settings", applyPreset);
    applyPreset();

    const canvas = createCanvasPanel(state, center, {
        resolveMemberUrl: opts.resolveMemberUrl,
    });
    renderRail(state, rail, opts);
    renderInspector(state, inspector, opts);

    // esc closes
    const onKey = (e) => {
        if (e.key === "Escape") {
            overlay.remove();
            document.removeEventListener("keydown", onKey);
            opts.onClose?.(state);
        }
    };
    document.addEventListener("keydown", onKey);

    return { state, overlay, exportSheet: () => canvas.exportSheet() };
}
