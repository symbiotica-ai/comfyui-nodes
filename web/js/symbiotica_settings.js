// ABOUTME: Registers Symbiotica API keys and the AI Gateway route in ComfyUI's
// ABOUTME: Settings UI. Values live in comfy.settings.json — never in workflows.
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
    ["FAL_KEY", "fal.ai API key"],
];

// Cloudflare AI Gateway, for a box that has no environment to put it in —
// Comfy Desktop launches its own Python, so these three fields are the only
// channel it has. A box with them filled in routes every gateway node through
// the studio's own stored provider key instead of spending a personal one.
//
// All three go together. A base on its own either fails asking for a
// credential this box does not hold, or bills spend that reaches no studio's
// row, so the resolver refuses a half-filled group rather than routing on it.
const GATEWAY = [
    {
        env: "SYMBIOTICA_AIG_BASE",
        name: "Gateway base URL",
        tooltip: "The AI Gateway endpoint, stopping at the gateway name: "
            + "https://gateway.ai.cloudflare.com/v1/<account>/<gateway> — each "
            + "node appends its own provider. NOT the OpenAI-compatibility "
            + "URL Cloudflare's dashboard offers alongside it; anything ending "
            + "in /compat/chat/completions is refused. Leave empty to send "
            + "every call straight to the provider on a personal key instead.",
    },
    {
        env: "SYMBIOTICA_AIG_TOKEN",
        name: "Gateway token",
        secret: true,
        tooltip: "Sent as cf-aig-authorization. This is the gateway token, "
            + "not a provider key — provider keys are stored in the gateway "
            + "as BYOK and injected there, so none is sent from this machine.",
    },
    {
        env: "ORDER_STUDIO",
        name: "Studio slug (BYOK alias)",
        defaultValue: "comfy-desktop",
        tooltip: "Which stored provider key pays, and what the spend is "
            + "tagged with. It must exist in the gateway as a BYOK alias — a "
            + "slug with no key stored under it fails every call with "
            + "internal code 2040 naming the alias.",
    },
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
    settings: [
        ASSET_ROOTS,
        ...GATEWAY.map(({ env, name, tooltip, secret, defaultValue }) => ({
            id: `Symbiotica.${env}`,
            name,
            category: ["Symbiotica", "AI Gateway", env],
            type: "text",
            defaultValue: defaultValue ?? "",
            ...(secret ? { attrs: { type: "password" } } : {}),
            tooltip,
        })),
        ...KEYS.map(([env, label]) => ({
            id: `Symbiotica.${env}`,
            name: label,
            category: ["Symbiotica", "API Keys", env],
            type: "text",
            defaultValue: "",
            attrs: { type: "password" },
            tooltip: "Stored in your ComfyUI user settings on this machine — "
                + "not in workflows, safe to share workflow files. Ignored "
                + "wherever an AI Gateway route is configured, which spends "
                + "the studio's key instead.",
        })),
    ],
});
