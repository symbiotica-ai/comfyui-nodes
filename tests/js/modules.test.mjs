// ABOUTME: The module merge in the browser — a stale tagged subgraph is swapped
// ABOUTME: for the library copy and promoted values follow the snapshot rule.
// Mirrors tests/test_modules.py; the two implementations must agree.
import assert from "node:assert/strict";
import { test } from "node:test";

import "./comfy_stub.mjs";
import { applyModules, promotedNames } from "../../web/js/modules.js";

const TAG = "symbiotica_module";
const SG_ID = "4ea6e827-ec92-4fdc-8d87-a021f5d6fb0a";

function subgraph({ lora = "old.safetensors", rev = null, id = SG_ID } = {}) {
    const def = {
        id, version: 1, name: "Image Edit",
        inputs: [{ name: "prompt", type: "STRING" }, { name: "lora_name", type: "COMBO" }],
        outputs: [{ name: "IMAGE", type: "IMAGE" }],
        nodes: [{ id: 1, type: "LoraLoaderModelOnly", widgets_values: [lora, 1.0] }],
        links: [],
        extra: { workflowRendererVersion: "LG" },
    };
    if (rev !== null) def.extra[TAG] = { name: "edit", rev };
    return def;
}

function instance({ id = 770, prompt = "make it bigger", lora = "old.safetensors",
                    snapshot = null, type = SG_ID } = {}) {
    const node = {
        id, type, pos: [0, 0],
        inputs: [
            { name: "image", type: "IMAGE", link: null },
            { name: "prompt", type: "STRING", widget: { name: "prompt" }, link: null },
            { name: "lora_name", type: "COMBO", widget: { name: "lora_name" }, link: null },
        ],
        outputs: [], properties: {},
        widgets_values: [prompt, lora],
    };
    if (snapshot) node.properties[TAG] = { name: "edit", rev: 1, values: snapshot };
    return node;
}

const workflow = (def, ...nodes) =>
    ({ nodes, links: [], definitions: { subgraphs: [def] }, extra: {} });

const module = ({ rev = 2, lora = "new.safetensors", prompt = "module prompt" } = {}) => ({
    name: "edit", rev, subgraph: subgraph({ lora, rev }),
    values: { prompt, lora_name: lora },
});

test("promoted names are the inputs that carry a widget, in order", () => {
    assert.deepEqual(promotedNames(instance()), ["prompt", "lora_name"]);
});

test("a stale definition is replaced and keeps the workflow's id", () => {
    const w = workflow(subgraph({ rev: 1 }), instance({
        snapshot: { prompt: "module prompt", lora_name: "old.safetensors" } }));
    const report = applyModules(w, { edit: module() });
    const def = w.definitions.subgraphs[0];
    assert.equal(report.changed, true);
    assert.deepEqual(report.updated, [{ name: "edit", rev: 2 }]);
    assert.equal(def.id, SG_ID);
    assert.equal(def.nodes[0].widgets_values[0], "new.safetensors");
    assert.deepEqual(def.extra[TAG], { name: "edit", rev: 2 });
});

test("a value the module changed lands; one the workflow typed survives", () => {
    const w = workflow(subgraph({ rev: 1 }), instance({
        prompt: "my own prompt",
        snapshot: { prompt: "module prompt", lora_name: "old.safetensors" } }));
    applyModules(w, { edit: module() });
    assert.deepEqual(w.nodes[0].widgets_values, ["my own prompt", "new.safetensors"]);
    assert.deepEqual(w.nodes[0].properties[TAG], {
        name: "edit", rev: 2, values: { prompt: "module prompt", lora_name: "new.safetensors" } });
});

test("no snapshot means every module value lands", () => {
    const w = workflow(subgraph({ rev: 1 }), instance({ prompt: "my own prompt" }));
    applyModules(w, { edit: module() });
    assert.deepEqual(w.nodes[0].widgets_values, ["module prompt", "new.safetensors"]);
});

test("a widget count mismatch leaves the values alone but bumps the snapshot", () => {
    const node = instance();
    node.widgets_values.push("randomize");
    const w = workflow(subgraph({ rev: 1 }), node);
    const report = applyModules(w, { edit: module() });
    assert.deepEqual(w.nodes[0].widgets_values, ["make it bigger", "old.safetensors", "randomize"]);
    assert.deepEqual(report.valuesSkipped, [770]);
    assert.equal(w.nodes[0].properties[TAG].rev, 2);
});

test("an instance inside another subgraph is patched too", () => {
    const outer = subgraph({ id: "outer-id" });
    outer.nodes = [instance({ id: 5 })];
    const w = workflow(subgraph({ rev: 1 }), instance({ id: 1 }));
    w.definitions.subgraphs.push(outer);
    applyModules(w, { edit: module() });
    assert.equal(w.definitions.subgraphs[1].nodes[0].widgets_values[1], "new.safetensors");
});

test("a current revision, an untagged subgraph and an unknown module are left alone", () => {
    const current = workflow(subgraph({ rev: 2 }), instance());
    const before = structuredClone(current);
    assert.equal(applyModules(current, { edit: module({ rev: 2 }) }).changed, false);
    assert.deepEqual(current, before);

    const untagged = workflow(subgraph(), instance());
    assert.equal(applyModules(untagged, { edit: module() }).changed, false);

    const other = workflow(subgraph({ rev: 1 }), instance());
    other.definitions.subgraphs[0].extra[TAG].name = "other";
    assert.equal(applyModules(other, { edit: module() }).changed, false);
    assert.equal(applyModules({ nodes: [] }, { edit: module() }).changed, false);
});
