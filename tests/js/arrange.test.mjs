// ABOUTME: Tests for the arrange section of find_node.js — the layering, the
// ABOUTME: Set/Get hop, the box that grows without moving, and stack-and-align.
import { test } from "node:test";
import assert from "node:assert/strict";

import "./comfy_stub.mjs";
import {
    arrangeEdges, assignLayers, checkArrange, measureNode, orderLayers,
    planArrange, rowOrder, shelfPack, snapValue, stackPlan, tidyLayout,
} from "../../web/js/find_node.js";

// A node as the layout sees it: no canvas, so `measureNode` falls through to
// pos + size and the title bar.
function node(id, type, x, y, w = 200, h = 100, extra = {}) {
    return {
        id, type, pos: [x, y], size: [w, h], flags: {},
        inputs: [], outputs: [], widgets: [], ...extra,
    };
}

function graphOf(nodes, links = {}) {
    return { _nodes: nodes, links, groups: [], extra: {} };
}

function box(id, x, y, w, h, extra = {}) {
    return { id, x, y, w, h, ox: 0, oy: 0, ...extra };
}

// ------------------------------------------------------------------ grid ----

test("a coordinate lands on the grid, and no grid leaves it alone", () => {
    assert.equal(snapValue(1234, 100), 1200);
    assert.equal(snapValue(1250, 100), 1300);
    assert.equal(snapValue(-5830, 100), -5800);
    assert.equal(snapValue(1234, 0), 1234);
});

// -------------------------------------------------------------- layering ----

test("a node sits one column right of everything feeding it", () => {
    const layer = assignLayers(["a", "b", "c"], [["a", "b"], ["b", "c"]]);
    assert.deepEqual([layer.get("a"), layer.get("b"), layer.get("c")], [0, 1, 2]);
});

test("a node with two feeds takes the LONGEST path, not the first", () => {
    // a -> b -> c and a -> c. `c` belongs after `b`, not beside it.
    const layer = assignLayers(["a", "b", "c"], [["a", "b"], ["b", "c"], ["a", "c"]]);
    assert.equal(layer.get("c"), 2);
});

test("a cycle is parked on the right rather than hanging the layout", () => {
    // A subgraph can hold one. Kahn resolves `a`, leaves `b` and `c` behind.
    const layer = assignLayers(["a", "b", "c"], [["a", "b"], ["b", "c"], ["c", "b"]]);
    assert.equal(layer.get("a"), 0);
    assert.equal(layer.get("b"), 1);
    assert.equal(layer.get("c"), 1);
});

test("an edge to a node that is not in this group is ignored", () => {
    const layer = assignLayers(["a", "b"], [["a", "b"], ["outside", "a"]]);
    assert.equal(layer.get("a"), 0);
});

test("the order inside a column is seeded from where the nodes are now", () => {
    // Nothing connects them, so the only thing that can decide is their
    // current Y — which is what keeps the result reading as his workflow.
    const layer = assignLayers(["hi", "lo"], []);
    const seed = new Map([["hi", 900], ["lo", 100]]);
    const [column] = orderLayers(layer, [], seed);
    assert.deepEqual(column, ["lo", "hi"]);
});

test("a node with no neighbour in the next column keeps its place", () => {
    // Sorting it to barycenter 0 would drag every loose node to the top.
    const layer = assignLayers(["a", "b", "loose", "z"], [["a", "z"]]);
    const seed = new Map([["a", 0], ["b", 100], ["loose", 50], ["z", 0]]);
    const layers = orderLayers(layer, [["a", "z"]], seed);
    assert.ok(layers[0].includes("loose"), "loose stays in the first column");
});

// ---------------------------------------------------------------- layout ----

test("a preview nothing reads goes to the rail, at its producer's height", () => {
    const boxes = [
        box("src", 0, 0, 300, 200),
        box("prev", 999, 999, 200, 300, { preview: true }),
    ];
    const { places } = tidyLayout(boxes, [["src", "prev"]], {});
    assert.equal(places.get("src").x, 0);
    // Rail sits past the flow column, not in a column of its own.
    assert.ok(places.get("prev").x > places.get("src").x + 300,
              "the rail is clear of the last column");
    assert.equal(places.get("prev").y, places.get("src").y);
});

test("a preview wired onward is a node in the flow, not a rail row", () => {
    const boxes = [
        box("src", 0, 0, 300, 200),
        box("prev", 0, 0, 200, 200, { preview: true }),
        box("after", 0, 0, 200, 200),
    ];
    const { places } = tidyLayout(boxes, [["src", "prev"], ["prev", "after"]], {});
    assert.ok(places.get("prev").x < places.get("after").x,
              "it kept a column, because something downstream reads it");
});

test("two nodes in one column do not overlap", () => {
    const boxes = [box("a", 0, 0, 300, 200), box("b", 0, 0, 300, 400)];
    const { places, height } = tidyLayout(boxes, [], {});
    const [a, b] = [places.get("a"), places.get("b")];
    assert.ok(Math.abs(a.y - b.y) >= 200, "stacked clear of each other");
    assert.ok(height >= 600, "the box has to hold both plus the gutter");
});

test("an empty group lays out to nothing rather than throwing", () => {
    const { places, width, height } = tidyLayout([], [], {});
    assert.equal(places.size, 0);
    assert.equal(width, 0);
    assert.equal(height, 0);
});

test("a group of nothing but previews still places them", () => {
    const boxes = [
        box("p1", 0, 0, 200, 100, { preview: true }),
        box("p2", 0, 0, 200, 100, { preview: true }),
    ];
    const { places } = tidyLayout(boxes, [], {});
    assert.equal(places.size, 2);
    assert.notEqual(places.get("p1").y, places.get("p2").y);
});

// -------------------------------------------------------------- the edges ---

test("a Get hops to the Set that publishes its name", () => {
    // The whole reason this is not an install: every existing arranger reads
    // `graph.links` alone and sees these two as unconnected litter.
    const setter = node(1, "SetNode", 0, 0, 200, 100, {
        widgets: [{ value: "$$controlnet" }],
    });
    const getter = node(2, "GetNode", 0, 0, 200, 100, {
        widgets: [{ value: "$$controlnet" }],
    });
    const graph = graphOf([setter, getter]);
    assert.deepEqual(arrangeEdges(graph, graph), [[1, 2]]);
});

test("a Get whose name nothing publishes is no edge, and no error", () => {
    const getter = node(2, "GetNode", 0, 0, 200, 100, {
        widgets: [{ value: "/prompts" }],
    });
    const graph = graphOf([getter]);
    assert.deepEqual(arrangeEdges(graph, graph), []);
});

test("a hub is hopped PER SLOT, so one node stands in for many pairs", () => {
    const hub = node(1, "SymbioticaSetHub", 0, 0, 300, 400, {
        inputs: [{ name: "a", label: "paths" }, { name: "b", label: "models" }],
    });
    const getA = node(2, "SymbioticaGetHub", 0, 0, 200, 100, {
        outputs: [{ name: "paths", label: "paths" }],
    });
    const getB = node(3, "SymbioticaGetHub", 0, 0, 200, 100, {
        outputs: [{ name: "models", label: "models" }],
    });
    const graph = graphOf([hub, getA, getB]);
    const edges = arrangeEdges(graph, graph);
    assert.deepEqual(edges.sort(), [[1, 2], [1, 3]]);
});

test("a hub's empty grow slot publishes nothing", () => {
    const hub = node(1, "SymbioticaSetHub", 0, 0, 300, 400, {
        inputs: [{ name: "+", label: "+" }],
    });
    const get = node(2, "SymbioticaGetHub", 0, 0, 200, 100, {
        outputs: [{ name: "+", label: "+" }],
    });
    const graph = graphOf([hub, get]);
    assert.deepEqual(arrangeEdges(graph, graph), []);
});

test("a real wire is an edge, from either links shape", () => {
    // Map on current frontends, a plain object on older ones. Both run here.
    const a = node(1, "A", 0, 0);
    const b = node(2, "B", 0, 0, 200, 100, { inputs: [{ name: "in", link: 7 }] });
    const asMap = graphOf([a, b], new Map([[7, { origin_id: 1 }]]));
    const asObject = graphOf([a, b], { 7: { origin_id: 1 } });
    assert.deepEqual(arrangeEdges(asMap, asMap), [[1, 2]]);
    assert.deepEqual(arrangeEdges(asObject, asObject), [[1, 2]]);
});

// ------------------------------------------------------------- the footprint -

test("a collapsed node measures as its title bar, not its stored size", () => {
    const collapsed = node(1, "GetNode", 100, 200, 300, 100, {
        flags: { collapsed: true },
    });
    const measured = measureNode(collapsed, null);
    assert.ok(measured.h <= 40, `a title bar, got ${measured.h}`);
    assert.ok(measured.w < 300, "not the 300 its size still claims");
});

test("the measured box starts ABOVE pos, because pos is under the title", () => {
    const plain = node(1, "A", 500, 600, 200, 100);
    const measured = measureNode(plain, null);
    assert.ok(measured.y < 600, "the title bar is part of the footprint");
    // The offset is what puts a placement back through `pos` unchanged.
    assert.equal(measured.y + measured.oy, 600);
    assert.equal(measured.x + measured.ox, 500);
});

// --------------------------------------------------------------- the plan ---

function groupOf(title, x, y, w, h, nodes, extra = {}) {
    return {
        id: title, title, pos: [x, y], size: [w, h], flags: {}, nodes,
        recomputeInsideNodes() {}, ...extra,
    };
}

function tinyGraph() {
    // Two groups, three nodes each, wired in a chain inside each group.
    const mk = (base) => [node(base + 1, "A", 0, 0, 300, 200),
                          node(base + 2, "B", 0, 0, 300, 200),
                          node(base + 3, "PreviewImage", 0, 0, 200, 200)];
    const left = mk(10);
    const right = mk(20);
    const graph = graphOf([...left, ...right], new Map([
        [1, { origin_id: 11 }], [2, { origin_id: 12 }],
        [3, { origin_id: 21 }], [4, { origin_id: 22 }],
    ]));
    left[1].inputs = [{ name: "in", link: 1 }];
    left[2].inputs = [{ name: "in", link: 2 }];
    right[1].inputs = [{ name: "in", link: 3 }];
    right[2].inputs = [{ name: "in", link: 4 }];
    graph.groups = [groupOf("first", 0, 0, 900, 600, left),
                    groupOf("second", 4000, 3000, 900, 600, right)];
    return graph;
}

test("every node ends up inside the box of the group it started in", () => {
    const graph = tinyGraph();
    const plan = planArrange(graph, graph, { grid: 100 });
    const box = new Map(plan.resized.map((r) => [r.group, r]));
    for (const move of plan.moves) {
        const { pos, size } = box.get(move.group);
        const cx = move.x + move.box.w / 2;
        const cy = move.y + move.box.h / 2;
        assert.ok(cx > pos[0] && cx < pos[0] + size[0], `node ${move.id} across`);
        assert.ok(cy > pos[1] && cy < pos[1] + size[1], `node ${move.id} down`);
    }
    assert.deepEqual(checkArrange(plan).problems, []);
});

test("every placed node lands on the grid — its POS, as his file has it", () => {
    // All 119 positions in `bakery-base-arrange-test.json` are multiples of
    // 100. `pos` sits below the title bar, so it is pos that has to snap, not
    // the bounding box.
    const graph = tinyGraph();
    const plan = planArrange(graph, graph, { grid: 100 });
    for (const move of plan.moves) {
        assert.equal(move.px % 100, 0, `pos x ${move.px} is off the grid`);
        assert.equal(move.py % 100, 0, `pos y ${move.py} is off the grid`);
    }
});

test("a second press moves nothing", () => {
    const graph = tinyGraph();
    const first = planArrange(graph, graph, { grid: 100 });
    for (const { group, pos, size } of first.resized) {
        group.pos = pos;
        group.size = size;
    }
    for (const move of first.moves) {
        move.node.pos = [move.x + move.box.ox, move.y + move.box.oy];
    }
    const second = planArrange(graph, graph, { grid: 100 });
    assert.equal(second.touched, 0, "idempotent, so the seed did its job");
});

test("a pinned node rides with its group instead of being laid out", () => {
    const a = node(1, "A", 0, 0, 300, 200);
    const b = node(2, "B", 0, 300, 300, 200);
    const pinned = node(3, "C", 600, 0, 300, 200, { pinned: true });
    const graph = graphOf([a, b, pinned]);
    graph.groups = [groupOf("g", 0, -100, 1200, 800, [a, b, pinned])];
    const plan = planArrange(graph, graph, { grid: 0 });
    const move = plan.moves.find((m) => m.id === 3);
    assert.ok(move?.riding, "it travels with the box, it is not laid out");
    assert.deepEqual(checkArrange(plan).problems, []);
});

test("a group muter is not laid out into the group it controls", () => {
    // His bypasser 3818 sits flush against where `edit-sketch` starts, so
    // `containsCentre` adopts it. The rule is the TYPE, not the geometry.
    const muter = node(1, "Fast Groups Bypasser (rgthree)", 0, 0, 300, 200);
    const a = node(2, "A", 0, 300, 300, 200);
    const b = node(3, "B", 0, 600, 300, 200);
    const graph = graphOf([muter, a, b]);
    graph.groups = [groupOf("edit-sketch", -50, -100, 500, 1100, [muter, a, b])];
    const plan = planArrange(graph, graph, { grid: 0 });
    assert.ok(plan.moves.find((m) => m.id === 1)?.riding, "it rides, not laid out");
    assert.ok(plan.moves.filter((m) => !m.riding).length === 2);
});

// ------------------------------------------------------------ the shelves ---

test("boxes go onto shelves in the order they arrive", () => {
    const items = [
        { key: "a", w: 400, h: 300 }, { key: "b", w: 400, h: 300 },
        { key: "c", w: 400, h: 300 }, { key: "d", w: 400, h: 300 },
    ];
    const out = shelfPack(items, {});
    assert.deepEqual(out.map((o) => o.key), ["a", "b", "c", "d"]);
    // Shelf-mates share one top edge; a later shelf is strictly lower.
    const rows = new Map();
    for (const o of out) rows.set(o.y, [...(rows.get(o.y) ?? []), o.x]);
    for (const xs of rows.values()) {
        assert.deepEqual(xs, [...xs].sort((p, q) => p - q), "x ascends on a shelf");
    }
});

test("rgthree reads the packed order back unchanged, by construction", () => {
    // Its key is floor(y/30) then floor(x/30). Shelf-mates share the first and
    // ascend on the second; a later shelf's first is strictly greater.
    const items = Array.from({ length: 9 }, (_, i) =>
        ({ key: `g${i}`, w: 300 + i * 120, h: 200 + (i % 3) * 400 }));
    const out = shelfPack(items, {});
    const readBack = [...out]
        .sort((a, b) => Math.floor(a.y / 30) - Math.floor(b.y / 30)
            || Math.floor(a.x / 30) - Math.floor(b.x / 30))
        .map((o) => o.key);
    assert.deepEqual(readBack, items.map((i) => i.key));
});

test("the arranged canvas reads its groups back in the same order", () => {
    const graph = tinyGraph();
    const was = rowOrder(graph.groups).map((g) => g.title);
    const plan = planArrange(graph, graph, { grid: 100 });
    const now = [...plan.resized]
        .sort((a, b) => Math.floor(a.pos[1] / 30) - Math.floor(b.pos[1] / 30)
            || Math.floor(a.pos[0] / 30) - Math.floor(b.pos[0] / 30))
        .map((r) => r.group.title);
    assert.deepEqual(now, was);
});

test("a reordered toggler row is a refusal", () => {
    const one = groupOf("a", 0, 0, 100, 100, []);
    const two = groupOf("b", 0, 900, 100, 100, []);
    const plan = {
        moves: [], owner: new Map(),
        // Packed the wrong way round: `b` now reads first.
        resized: [{ group: one, pos: [0, 900], size: [100, 100] },
                  { group: two, pos: [0, 0], size: [100, 100] }],
    };
    assert.ok(checkArrange(plan).problems.some((p) => p.includes("reordered")));
});

test("two boxes sitting on each other is a refusal", () => {
    const one = groupOf("a", 0, 0, 100, 100, []);
    const two = groupOf("b", 0, 900, 100, 100, []);
    const plan = {
        moves: [], owner: new Map(),
        resized: [{ group: one, pos: [0, 0], size: [500, 500] },
                  { group: two, pos: [100, 100], size: [500, 500] }],
    };
    assert.ok(checkArrange(plan).problems.some((p) => p.includes("sit on")));
});

test("a node standing still is checked too, not only the ones that move", () => {
    // A box packing onto a node that did not move changes its group just as
    // surely as moving the node would.
    const one = groupOf("a", 0, 0, 400, 400, []);
    const plan = {
        moves: [], owner: new Map(),
        boxes: new Map([[9, { x: 100, y: 100, w: 50, h: 50 }]]),
        resized: [{ group: one, pos: [0, 0], size: [400, 400] }],
    };
    assert.ok(checkArrange(plan).problems.some((p) => p.includes("change group")));
});

test("a node that would change group is a refusal", () => {
    const one = groupOf("a", 0, 0, 400, 400, []);
    const two = groupOf("b", 1000, 0, 400, 400, []);
    const plan = {
        moves: [{ id: 7, group: one, x: 1100, y: 100,
                  box: { w: 100, h: 100, ox: 0, oy: 0 } }],
        boxes: new Map([[7, { x: 100, y: 100, w: 100, h: 100 }]]),
        owner: new Map([[7, one]]),
        resized: [{ group: one, pos: [0, 0], size: [400, 400] },
                  { group: two, pos: [1000, 0], size: [400, 400] }],
    };
    assert.ok(checkArrange(plan).problems.some((p) => p.includes("change group")));
});

// ------------------------------------------------------- stack and align ----

test("the axis comes from the selection's own spread", () => {
    const down = [box("a", 0, 0, 200, 100), box("b", 40, 900, 200, 100)];
    assert.equal(stackPlan(down, {}).axis, "column");
    const across = [box("a", 0, 0, 200, 100), box("b", 900, 40, 200, 100)];
    assert.equal(stackPlan(across, {}).axis, "row");
});

test("a column aligns the left edge and spaces evenly, on the grid", () => {
    const boxes = [box("a", 137, 0, 200, 100), box("b", 260, 900, 300, 100)];
    const { places } = stackPlan(boxes, { grid: 100 });
    assert.equal(places.get("a").x, places.get("b").x, "one leading edge");
    assert.equal(places.get("a").x % 100, 0);
    assert.equal(places.get("b").y % 100, 0);
    assert.ok(places.get("b").y > places.get("a").y, "in the order they were in");
});

test("widths match the widest, but never a collapsed node or a panel", () => {
    const boxes = [
        box("plain", 0, 0, 200, 100),
        box("wide", 0, 300, 400, 100),
        box("folded", 0, 600, 80, 30, { collapsed: true }),
        box("panel", 0, 900, 900, 800, { panel: true }),
    ];
    const { widths } = stackPlan(boxes, { grid: 100 });
    assert.equal(widths.get("plain"), 400);
    assert.equal(widths.has("folded"), false, "its width is its title");
    assert.equal(widths.has("panel"), false, "writing a panel's box is the bug class");
});

test("a pinned node is not stacked and does not count toward the axis", () => {
    const boxes = [
        box("a", 0, 0, 200, 100),
        box("b", 900, 0, 200, 100),
        box("pin", 0, 9000, 200, 100, { pinned: true }),
    ];
    const { places, axis } = stackPlan(boxes, {});
    assert.equal(axis, "row", "the pinned outlier did not swing the axis");
    assert.equal(places.has("pin"), false);
});

test("one node, or none, is nothing to stack", () => {
    assert.equal(stackPlan([box("a", 0, 0, 200, 100)], {}).places.size, 0);
    assert.equal(stackPlan([], {}).places.size, 0);
});

test("a row stacks left to right without overlapping", () => {
    const boxes = [box("a", 0, 0, 300, 100), box("b", 500, 10, 200, 100)];
    const { places } = stackPlan(boxes, { grid: 100 });
    assert.equal(places.get("a").y, places.get("b").y, "one top edge");
    assert.ok(places.get("b").x >= places.get("a").x + 300, "clear of each other");
});

test("a stacked node's POS lands on the grid, title offset and all", () => {
    // pos sits below the title bar, so snapping the bounding box leaves pos
    // at an offset — and every position in his file is a multiple of 100.
    const boxes = [
        { id: "a", x: 137, y: 0, w: 200, h: 130, ox: 0, oy: 30 },
        { id: "b", x: 260, y: 900, w: 300, h: 130, ox: 0, oy: 30 },
    ];
    const { places } = stackPlan(boxes, { grid: 100 });
    for (const box of boxes) {
        const at = places.get(box.id);
        assert.equal((at.x + box.ox) % 100, 0, `pos x off the grid: ${at.x + box.ox}`);
        assert.equal((at.y + box.oy) % 100, 0, `pos y off the grid: ${at.y + box.oy}`);
    }
});
