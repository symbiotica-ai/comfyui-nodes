// ABOUTME: Registers Symbiotica API keys in ComfyUI's Settings UI. Values live
// ABOUTME: in the server's comfy.settings.json — never in workflows, never in git.
import { app } from "../../../scripts/app.js";
import { registerSymbioticaExtension } from "./register.js";

const KEYS = [
    ["ANTHROPIC_API_KEY", "Anthropic (Claude) API key"],
    ["OPENAI_API_KEY", "OpenAI API key"],
    ["GEMINI_API_KEY", "Google Gemini API key"],
    ["XAI_API_KEY", "xAI (Grok) API key"],
    ["WAVESPEED_API_KEY", "Wavespeed API key"],
    ["ELEVENLABS_API_KEY", "ElevenLabs API key"],
    ["SUBMAGIC_API_KEY", "Submagic API key"],
];

// Folders outside ComfyUI's own input/output that the asset and template
// browsers may read. A request cannot name its own folder, so a project kept
// elsewhere is declared here once.
const ASSET_ROOTS = {
    id: "Symbiotica.SYMBIOTICA_ASSET_ROOTS",
    name: "Asset folders",
    category: ["Symbiotica", "Paths", "SYMBIOTICA_ASSET_ROOTS"],
    type: "text",
    defaultValue: "",
    tooltip: "Absolute paths, separated by commas, semicolons or newlines. "
        + "The asset and template browsers may read these folders in addition "
        + "to ComfyUI's own. Also settable as the SYMBIOTICA_ASSET_ROOTS "
        + "environment variable.",
};

registerSymbioticaExtension(app, {
    name: "symbiotica.settings",
    settings: [ASSET_ROOTS, ...KEYS.map(([env, label]) => ({
        id: `Symbiotica.${env}`,
        name: label,
        category: ["Symbiotica", "API Keys", env],
        type: "text",
        defaultValue: "",
        attrs: { type: "password" },
        tooltip: "Stored in your ComfyUI user settings on this machine — "
            + "not in workflows, safe to share workflow files.",
    }))],
});
