// ABOUTME: Maps ComfyUI's ../../../scripts/{app,api}.js onto the test stub so
// ABOUTME: web/js modules import unmodified. Loaded via `node --import`.
import { registerHooks } from "node:module";

const STUB = new URL("./comfy_stub.mjs", import.meta.url).href;

registerHooks({
    resolve(specifier, context, nextResolve) {
        if (/(^|\/)scripts\/(app|api)\.js$/.test(specifier)) {
            return { url: STUB, format: "module", shortCircuit: true };
        }
        return nextResolve(specifier, context);
    },
});
