// ABOUTME: The Control Image node's preview — the dropdown value names a file
// ABOUTME: under input/controlnet, and the view URL must point at exactly that.
import assert from "node:assert/strict";
import { test } from "node:test";

import "./comfy_stub.mjs";
import { viewParams } from "../../web/js/control_image.js";

test("a relative name splits into the controlnet subfolder and the file", () => {
    assert.deepEqual(viewParams("1x1-floor.png"), { filename: "1x1-floor.png", subfolder: "controlnet", type: "input" });
    assert.deepEqual(viewParams("bakery/counter.png"), { filename: "counter.png", subfolder: "controlnet/bakery", type: "input" });
    assert.deepEqual(viewParams("a/b/c.png"), { filename: "c.png", subfolder: "controlnet/a/b", type: "input" });
    assert.equal(viewParams(""), null);
    assert.equal(viewParams("[no images under input/controlnet]"), null);
});
