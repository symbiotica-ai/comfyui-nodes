// ABOUTME: Pure algorithm ports of the Python pipeline (texture_pack / model_presets /
// ABOUTME: prefill / order_sheet helpers) — behavior-matched, no DOM, no side effects.

// ---------------------------------------------------------------------------
// model_presets.py
// ---------------------------------------------------------------------------

export const TIER_PX = { "0.5K": 512, "1K": 1024, "2K": 2048, "4K": 4096 };

export const MODEL_PRESETS = [
    {
        id: "nano-banana-pro",
        label: "Nano Banana Pro",
        endpoint: "fal-ai/nano-banana-pro",
        tiers: ["1K", "2K", "4K"],
        aspectRatios: ["21:9", "16:9", "3:2", "4:3", "5:4", "1:1", "4:5", "3:4",
            "2:3", "9:16"],
    },
    {
        id: "nano-banana-2",
        label: "Nano Banana 2",
        endpoint: "fal-ai/nano-banana-2",
        tiers: ["0.5K", "1K", "2K", "4K"],
        aspectRatios: ["21:9", "16:9", "3:2", "4:3", "5:4", "1:1", "4:5", "3:4",
            "2:3", "9:16", "4:1", "1:4", "8:1", "1:8"],
    },
    {
        id: "imagen-4",
        label: "Imagen 4",
        endpoint: "fal-ai/imagen4",
        tiers: ["1K", "2K"],
        aspectRatios: ["1:1", "16:9", "9:16", "4:3", "3:4"],
    },
];

function round8(n) {
    return Math.max(8, Math.round(n / 8) * 8);
}

function parseIntStrict(s) {
    // Mirrors Python int(str): optional sign, digits only (whitespace tolerated).
    const t = String(s).trim();
    if (!/^[+-]?\d+$/.test(t)) return null;
    return parseInt(t, 10);
}

// Pixel dimensions for an aspect ratio at a resolution tier.
export function aspectDims(ar, tier) {
    const longEdge = TIER_PX[tier];
    const parts = String(ar).split(":");
    const square = { w: longEdge, h: longEdge };
    if (parts.length !== 2) return square; // py: unpacking error -> fallback
    const a = parseIntStrict(parts[0]);
    const b = parseIntStrict(parts[1]);
    if (a === null || b === null) return square; // py: int() ValueError
    if (!a || !b) return square;
    if (a >= b) return { w: longEdge, h: round8(longEdge * b / a) };
    return { w: round8(longEdge * a / b), h: longEdge };
}

// Resolve a stored selection {model, tier, ar} to exact pixel dims (or null).
export function presetDims(sel) {
    if (!sel) return null;
    const model = MODEL_PRESETS.find((m) => m.id === sel.model) ?? null;
    if (model === null
        || !model.tiers.includes(sel.tier)
        || !model.aspectRatios.includes(sel.ar)) {
        return null;
    }
    return aspectDims(sel.ar, sel.tier);
}

// ---------------------------------------------------------------------------
// texture_pack.py  (settings = DEFAULT_SETTINGS shape from ./state.js;
// background is ignored by pack())
// ---------------------------------------------------------------------------

export function effectiveMax(settings) {
    const dims = presetDims(settings.preset);
    if (dims) return dims;
    return { w: settings.maxWidth, h: settings.maxHeight };
}

function boxesFor(sprites, padding) {
    return sprites.map((s) => ({ id: s.id, w: s.width + padding, h: s.height + padding }));
}

function intersects(a, b) {
    return a.x < b.x + b.w && a.x + a.w > b.x
        && a.y < b.y + b.h && a.y + a.h > b.y;
}

function contains(a, b) {
    return b.x >= a.x && b.y >= a.y
        && b.x + b.w <= a.x + a.w
        && b.y + b.h <= a.y + a.h;
}

function prune(rects) {
    const out = rects.slice();
    let i = 0;
    while (i < out.length) {
        let j = i + 1;
        let removedI = false;
        while (j < out.length) {
            if (contains(out[j], out[i])) {
                out.splice(i, 1);
                removedI = true;
                break;
            }
            if (contains(out[i], out[j])) {
                out.splice(j, 1);
                continue;
            }
            j += 1;
        }
        if (!removedI) i += 1;
    }
    return out;
}

function packMaxrects(boxes, maxW, maxH) {
    const order = boxes.slice().sort((a, b) =>
        (Math.max(b.w, b.h) - Math.max(a.w, a.h)) || (b.w * b.h - a.w * a.h));
    let free = [{ x: 0, y: 0, w: maxW, h: maxH }];
    const placed = [];
    const overflow = [];
    let usedW = 0;
    let usedH = 0;
    for (const box of order) {
        let best = null; // [x, y, shortSide, longSide]
        for (const f of free) {
            if (box.w <= f.w && box.h <= f.h) {
                const leftoverH = f.w - box.w;
                const leftoverV = f.h - box.h;
                const shortSide = Math.min(leftoverH, leftoverV);
                const longSide = Math.max(leftoverH, leftoverV);
                if (best === null || shortSide < best[2]
                    || (shortSide === best[2] && longSide < best[3])) {
                    best = [f.x, f.y, shortSide, longSide];
                }
            }
        }
        if (best === null) {
            overflow.push(box.id);
            continue;
        }
        const node = { x: best[0], y: best[1], w: box.w, h: box.h };
        placed.push({ id: box.id, x: node.x, y: node.y, width: box.w, height: box.h });
        usedW = Math.max(usedW, node.x + box.w);
        usedH = Math.max(usedH, node.y + box.h);
        const nxt = [];
        for (const f of free) {
            if (!intersects(f, node)) {
                nxt.push(f);
                continue;
            }
            if (f.x < node.x && node.x < f.x + f.w) {
                nxt.push({ x: f.x, y: f.y, w: node.x - f.x, h: f.h });
            }
            if (node.x + node.w < f.x + f.w) {
                nxt.push({ x: node.x + node.w, y: f.y,
                    w: f.x + f.w - (node.x + node.w), h: f.h });
            }
            if (f.y < node.y && node.y < f.y + f.h) {
                nxt.push({ x: f.x, y: f.y, w: f.w, h: node.y - f.y });
            }
            if (node.y + node.h < f.y + f.h) {
                nxt.push({ x: f.x, y: node.y + node.h, w: f.w,
                    h: f.y + f.h - (node.y + node.h) });
            }
        }
        free = prune(nxt);
    }
    return { placed, overflow, width: usedW, height: usedH };
}

function packShelf(boxes, maxW, maxH) {
    const order = boxes.slice().sort((a, b) => b.h - a.h); // stable
    const placed = [];
    const overflow = [];
    let shelfX = 0;
    let shelfY = 0;
    let shelfH = 0;
    let usedW = 0;
    for (const box of order) {
        if (box.w > maxW || box.h > maxH) {
            overflow.push(box.id);
            continue;
        }
        if (shelfX + box.w > maxW) {
            shelfY += shelfH;
            shelfX = 0;
            shelfH = 0;
        }
        if (shelfY + box.h > maxH) {
            overflow.push(box.id);
            continue;
        }
        placed.push({ id: box.id, x: shelfX, y: shelfY, width: box.w, height: box.h });
        shelfX += box.w;
        shelfH = Math.max(shelfH, box.h);
        usedW = Math.max(usedW, shelfX);
    }
    return { placed, overflow, width: usedW, height: shelfY + shelfH };
}

function packGrid(boxes, maxW, maxH, cell) {
    const biggest = boxes.length
        ? Math.max(...boxes.map((b) => Math.max(b.w, b.h)))
        : 1;
    const c = cell > 0 ? cell : Math.max(1, biggest);
    const cols = Math.max(1, Math.floor(maxW / c));
    const placed = [];
    const overflow = [];
    let usedW = 0;
    let usedH = 0;
    boxes.forEach((box, i) => {
        const col = i % cols;
        const row = Math.floor(i / cols);
        const cx = col * c;
        const cy = row * c;
        if (cy + c > maxH) {
            overflow.push(box.id);
            return;
        }
        placed.push({
            id: box.id,
            x: cx + Math.max(0, (c - box.w) / 2),
            y: cy + Math.max(0, (c - box.h) / 2),
            width: box.w,
            height: box.h,
        });
        usedW = Math.max(usedW, cx + c);
        usedH = Math.max(usedH, cy + c);
    });
    return { placed, overflow, width: usedW, height: usedH };
}

function parentFolder(path) {
    const parts = String(path).split("/").filter((p) => p);
    if (parts.length >= 2) return parts[parts.length - 2];
    return parts.length ? parts[0] : path;
}

function packByFolder(sprites, padding, maxW, maxH, columns) {
    const placed = [];
    const overflow = [];
    const groups = new Map(); // folder -> boxes (insertion order, like py dict)
    for (const s of sprites) {
        const box = { id: s.id, w: s.width + padding, h: s.height + padding };
        const key = parentFolder(s.path);
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(box);
    }

    const rows = [];
    for (const boxes of groups.values()) {
        let row = [];
        let rowW = 0;
        for (const box of boxes) {
            if (box.w > maxW || box.h > maxH) {
                overflow.push(box.id);
                continue;
            }
            const wrapByCount = columns > 0 && row.length >= columns;
            const wrapByWidth = row.length > 0 && rowW + box.w > maxW;
            if (wrapByCount || wrapByWidth) {
                rows.push(row);
                row = [];
                rowW = 0;
            }
            row.push(box);
            rowW += box.w;
        }
        if (row.length) rows.push(row);
    }

    if (!rows.length) {
        return { placed, overflow, width: maxW, height: maxH };
    }

    const rowH = rows.map((r) => Math.max(...r.map((b) => b.h)));
    const totalH = rowH.reduce((a, b) => a + b, 0);
    const fits = totalH <= maxH;
    const gap = fits ? (maxH - totalH) / (rows.length + 1) : 0;

    let y = gap;
    let r = 0;
    while (r < rows.length) {
        const row = rows[r];
        const h = rowH[r];
        if (!fits && y + h > maxH) break;
        const rowW = row.reduce((a, b) => a + b.w, 0);
        let x = Math.max(0, (maxW - rowW) / 2);
        for (const box of row) {
            placed.push({ id: box.id, x, y: y + Math.max(0, (h - box.h) / 2),
                width: box.w, height: box.h });
            x += box.w;
        }
        y += h + gap;
        r += 1;
    }
    while (r < rows.length) {
        for (const b of rows[r]) overflow.push(b.id);
        r += 1;
    }
    return { placed, overflow, width: maxW, height: maxH };
}

// Dispatch to the chosen algorithm. Sprites must already be the enabled set.
// sprites: [{id, name, path, width, height}] ->
// {placed: [{id, x, y, width, height}], overflow: [ids], width, height}
export function pack(sprites, settings) {
    if (!sprites || !sprites.length) {
        return { placed: [], overflow: [], width: 0, height: 0 };
    }
    const padding = settings.padding ?? 0;
    const border = settings.border ?? 0;
    const boxes = boxesFor(sprites, padding);
    const mx = effectiveMax(settings);
    const usableW = Math.max(1, mx.w - border * 2);
    const usableH = Math.max(1, mx.h - border * 2);

    let res;
    if (settings.distributeByFolder) {
        res = packByFolder(sprites, padding, usableW, usableH, settings.columns ?? 0);
    } else if (settings.algorithm === "shelf") {
        res = packShelf(boxes, usableW, usableH);
    } else if (settings.algorithm === "grid") {
        res = packGrid(boxes, usableW, usableH, settings.gridCell ?? 0);
    } else {
        res = packMaxrects(boxes, usableW, usableH);
    }

    if (border > 0) {
        res.placed = res.placed.map((p) => ({ ...p, x: p.x + border, y: p.y + border }));
        res.width += border * 2;
        res.height += border * 2;
    }
    return res;
}

function nextPow2(n) {
    let p = 1;
    while (p < n) p *= 2;
    return p;
}

// Final sheet size: preset locks native pixels; else content bounds rounded
// by force-square / power-of-two.
export function sheetSize(width, height, settings) {
    const dims = presetDims(settings.preset);
    if (dims) return dims;
    let w = width;
    let h = height;
    if (settings.forceSquare) {
        w = h = Math.max(w, h);
    }
    if (settings.powerOfTwo) {
        w = nextPow2(w);
        h = nextPow2(h);
    }
    return { w: Math.max(1, Math.trunc(w)), h: Math.max(1, Math.trunc(h)) };
}

// ---------------------------------------------------------------------------
// order_sheet.py helpers (templateGroups lives in ../order_pipeline.js)
// ---------------------------------------------------------------------------

export function slugify(s) {
    return String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

// Parse "128x128" (case/space tolerant) into {w, h}; null otherwise.
export function canvasSpecOf(canvas) {
    const m = /^(\d+)x(\d+)$/.exec(String(canvas).toLowerCase().replace(/\s+/g, ""));
    return m ? { w: parseInt(m[1], 10), h: parseInt(m[2], 10) } : null;
}

// ---------------------------------------------------------------------------
// prefill.py
// ---------------------------------------------------------------------------

export const PAD_PX = 16;
export const FALLBACK_CELL = 256;

function cellCount(row) {
    return row.flip ? 2 : row.paths.length;
}

function rowW(row) {
    const n = cellCount(row);
    return n * row.cellW + (n - 1) * PAD_PX;
}

function regionAt(row, xPx, yPx, sheetW, sheetH) {
    const cellPaths = row.flip ? [row.paths[0], row.paths[0]] : row.paths;
    let x = xPx;
    const members = [];
    cellPaths.forEach((spriteId, i) => {
        const m = { spriteId, x: x / sheetW, y: yPx / sheetH,
            w: row.cellW / sheetW, h: row.cellH / sheetH };
        if (row.flip && i === 1) m.flipX = true;
        members.push(m);
        x += row.cellW + PAD_PX;
    });
    const x0 = members[0].x;
    const last = members[members.length - 1];
    return {
        id: `region:spec:${row.asset.assetName}`,
        name: row.asset.assetName,
        x: x0,
        y: yPx / sheetH,
        w: last.x + last.w - x0,
        h: row.cellH / sheetH,
        kind: "object",
        desc: row.asset.prompt || "",
        text: "",
        zIndex: 0,
        assetType: row.asset.category,
        members,
        taskRefs: { paths: row.paths, mode: "meta" },
    };
}

// One region per asset. Single-ref assets show the ref plus a flipped copy
// (the in-game pair convention); multi-ref assets one cell per ref. With
// settings, strips run through the packer (overflow stacks below, visible);
// without, strips stack as centered rows distributed evenly down the sheet.
// orderAssets: [{assetName, category, canvas, prompt, refFiles}]
export function prefillRegions(orderAssets, sheetW, sheetH, chosen = null, settings = null) {
    const rows = [];
    for (const asset of orderAssets) {
        const picked = (chosen ?? {})[asset.assetName];
        const paths = (picked && picked.length)
            ? picked
            : asset.refFiles.map((f) => `${asset.category}/${asset.assetName}/${f}`);
        if (!paths.length) continue;
        const spec = canvasSpecOf(asset.canvas);
        rows.push({
            asset,
            cellW: spec?.w ?? FALLBACK_CELL,
            cellH: spec?.h ?? FALLBACK_CELL,
            paths,
            flip: paths.length === 1,
        });
    }
    if (!rows.length) return { regions: [], overflow: [] };

    if (settings !== null) {
        const byName = new Map(rows.map((r) => [r.asset.assetName, r]));
        const pseudo = rows.map((r) => ({
            id: r.asset.assetName,
            name: r.asset.assetName,
            path: `${r.asset.category}/${r.asset.assetName}`,
            width: rowW(r),
            height: r.cellH,
        }));
        const result = pack(pseudo, { ...settings, preset: null, maxWidth: sheetW,
            maxHeight: sheetH, forceSquare: false, powerOfTwo: false });
        const regions = [];
        for (const p of result.placed) {
            const row = byName.get(p.id);
            if (row) regions.push(regionAt(row, p.x, p.y, sheetW, sheetH));
        }
        const overflow = [];
        let yPx = regions.length
            ? Math.max(...regions.map((r) => (r.y + r.h) * sheetH)) + PAD_PX
            : PAD_PX;
        for (const oid of result.overflow) {
            const row = byName.get(oid);
            if (!row) continue;
            overflow.push(row.asset.assetName);
            // floor at 0 — oversized strips clamp to the top edge instead of going out of bounds
            const y = Math.max(0, Math.min(yPx, sheetH - row.cellH));
            regions.push(regionAt(row, PAD_PX, y, sheetW, sheetH));
            yPx = y + row.cellH + PAD_PX;
        }
        regions.sort((a, b) => (a.y - b.y) || (a.x - b.x));
        regions.forEach((r, i) => { r.zIndex = i; });
        return { regions, overflow };
    }

    // No settings: rows top-to-bottom in order-sheet order, each centered,
    // distributed space-evenly, fit-scaled together when they'd overflow.
    const totalH = rows.reduce((a, r) => a + r.cellH, 0) + (rows.length + 1) * PAD_PX;
    const maxW = Math.max(...rows.map((r) => rowW(r))) + 2 * PAD_PX;
    const scale = Math.min(1, sheetH / totalH, sheetW / maxW);
    const rowsH = rows.reduce((a, r) => a + r.cellH * scale, 0);
    const gap = Math.max(0, (sheetH - rowsH) / (rows.length + 1));
    const regions = [];
    let yPx = gap;
    rows.forEach((row, index) => {
        const scaled = { ...row, cellW: row.cellW * scale, cellH: row.cellH * scale };
        const stripW = rowW(scaled);
        const xPx = Math.max(0, (sheetW - stripW) / 2);
        const region = regionAt(scaled, xPx, yPx, sheetW, sheetH);
        region.zIndex = index;
        regions.push(region);
        yPx += scaled.cellH + gap;
    });
    return { regions, overflow: [] };
}

// ---------------------------------------------------------------------------
// rebuildSpecRegions — re-run prefill at current sheet size/settings while
// preserving per-region user edits from the existing regions (matched by id).
// Returns the new regions array; does not mutate state.
// ---------------------------------------------------------------------------

const PRESERVED_KEYS = ["desc", "kind", "text", "taskRefs", "projectPaths", "assetType"];

export function rebuildSpecRegions(state) {
    const assets = (state.taskAssets ?? []).filter(
        (a) => Array.isArray(a.refFiles) && a.refFiles.length > 0);
    const { regions } = prefillRegions(assets, state.sheetW, state.sheetH, null, state.settings);
    const oldById = new Map((state.regions ?? []).map((r) => [r.id, r]));
    for (const region of regions) {
        const old = oldById.get(region.id);
        if (!old) continue;
        for (const key of PRESERVED_KEYS) {
            if (old[key] !== undefined) region[key] = old[key];
        }
    }
    return regions;
}

// --- task-driven asset filtering (port of hub flows/template-filter.ts) --------

/** Bidirectional-prefix rule: folder/category match when either prefixes the
 *  other — "Decoration"/"Decorations", folder "Food" under "Food - 3 stages",
 *  without "Wall Decoration" leaking into "Decoration". */
function prefixPair(folderLower, categoryLower) {
    return folderLower.startsWith(categoryLower) || categoryLower.startsWith(folderLower);
}

/** The order category (original case) `folder` matches, or undefined. */
export function matchCategory(folder, categories) {
    const fl = folder.toLowerCase();
    for (const c of categories) {
        if (prefixPair(fl, c.toLowerCase())) return c;
    }
    return undefined;
}

/** Canvas sizes the order asks for per category (lowercased key) — the
 *  spec-driven resolution filter ("decoration" -> Set{"256x256"}). */
export function categoryCanvasSizes(assets) {
    const out = new Map();
    for (const a of assets) {
        const canvas = (a.canvas ?? "").toLowerCase().replace(/\s+/g, "");
        if (!/^\d+x\d+$/.test(canvas)) continue;
        const key = a.category.toLowerCase();
        if (!out.has(key)) out.set(key, new Set());
        out.get(key).add(canvas);
    }
    return out;
}

/** Display path for the filtered rail, grouped under the ORDER category:
 *  `<Category>/<W×H>/<deepest non-category folder>/<file>`. Unmatched sprites
 *  keep their deepest folder with no category prefix. */
export function flattenSpritePath(path, categories, size) {
    const parts = path.split("/");
    const file = parts.pop();
    let matched;
    const folders = parts.filter((f) => {
        const m = matchCategory(f, categories);
        if (m) {
            matched = matched ?? m;
            return false;
        }
        return true;
    });
    const kept = folders.length > 0 ? folders[folders.length - 1] : undefined;
    const tail = kept ? `${kept}/${file}` : file;
    if (matched) {
        const sizeLevel = size?.w && size?.h ? `${size.w}×${size.h}/` : "";
        return `${matched}/${sizeLevel}${tail}`;
    }
    const fallback = kept ?? parts[parts.length - 1];
    return fallback ? `${fallback}/${file}` : file;
}
