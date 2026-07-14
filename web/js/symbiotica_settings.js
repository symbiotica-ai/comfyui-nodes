// ABOUTME: Registers Symbiotica API keys in ComfyUI's Settings UI. Values live
// ABOUTME: in the server's comfy.settings.json — never in workflows, never in git.
import { app } from "../../../scripts/app.js";

const KEYS = [
    ["ANTHROPIC_API_KEY", "Anthropic (Claude) API key"],
    ["OPENAI_API_KEY", "OpenAI API key"],
    ["GEMINI_API_KEY", "Google Gemini API key"],
    ["XAI_API_KEY", "xAI (Grok) API key"],
    ["WAVESPEED_API_KEY", "Wavespeed API key"],
    ["ELEVENLABS_API_KEY", "ElevenLabs API key"],
    ["SUBMAGIC_API_KEY", "Submagic API key"],
];

app.registerExtension({
    name: "symbiotica.settings",
    settings: KEYS.map(([env, label]) => ({
        id: `Symbiotica.${env}`,
        name: label,
        category: ["Symbiotica", "API Keys", env],
        type: "text",
        defaultValue: "",
        attrs: { type: "password" },
        tooltip: "Stored in your ComfyUI user settings on this machine — "
            + "not in workflows, safe to share workflow files.",
    })),
});
