// ABOUTME: Every extension must import ComfyUI's app/api at the right depth.
// ABOUTME: The wrong depth 404s the whole module and the node loses its panel.
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

const ROOT = new URL("../../web/js/", import.meta.url).pathname;

function jsFiles(dir, prefix = "") {
    return readdirSync(dir).flatMap((name) => {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) return jsFiles(path, `${prefix}${name}/`);
        return name.endsWith(".js") ? [{ rel: `${prefix}${name}`, path }] : [];
    });
}

// web/js/x.js is served at /extensions/symbiotica/js/x.js, so reaching
// /scripts/app.js is three levels up; a file one directory deeper needs four.
const expectedDepth = (rel) => "../".repeat(3 + (rel.split("/").length - 1));

test("every module imports scripts/app.js at the depth ComfyUI serves it", () => {
    const wrong = [];
    for (const { rel, path } of jsFiles(ROOT)) {
        const src = readFileSync(path, "utf8");
        for (const m of src.matchAll(/from\s+"((?:\.\.\/)+)scripts\/(app|api)\.js"/g)) {
            if (m[1] !== expectedDepth(rel)) {
                wrong.push(`${rel}: "${m[1]}scripts/${m[2]}.js" should be `
                           + `"${expectedDepth(rel)}scripts/${m[2]}.js"`);
            }
        }
    }
    // The test harness rewrites ANY scripts/app.js path onto its stub, so a
    // wrong depth passes every other test and only fails in the browser — as a
    // node that comes up with bare widgets and no panel.
    assert.deepEqual(wrong, [], `wrong import depth:\n${wrong.join("\n")}`);
});
