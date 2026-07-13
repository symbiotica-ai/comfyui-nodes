// ABOUTME: Center canvas panel of the template editor — renders the sheet,
// ABOUTME: member images and region overlays; handles zoom/pan/draw/move/resize.

const PALETTE = ["#e6c229", "#4caf7d", "#5b7fd4", "#3fbf9f", "#7ec4e8", "#b06ad4", "#e08a4a"];
const FIT_MARGIN = 40;
const SNAP_TOL_SCREEN = 6; // px in screen space for smart guides
const MIN_SIZE_PX = 8;     // min region size in sheet px
const HANDLE = 7;          // corner handle size (screen px)

export function createCanvasPanel(state, host, opts) {
    const canvas = document.createElement("canvas");
    canvas.style.position = "absolute";
    canvas.style.inset = "0";
    canvas.style.width = "100%";
    canvas.style.height = "100%";
    canvas.style.touchAction = "none";
    canvas.style.cursor = "crosshair";
    host.appendChild(canvas);
    const ctx = canvas.getContext("2d");

    const footer = document.createElement("div");
    footer.className = "footerbar";
    host.appendChild(footer);
    const syncFooter = () => {
        footer.textContent =
            `${state.sheetW}×${state.sheetH} px · scroll to zoom · ` +
            `space-drag to pan · drag empty to draw · click select · ` +
            `drag move · corner resize`;
    };
    syncFooter();

    // ---- image cache ---------------------------------------------------------
    const imageCache = new Map(); // url -> {img, promise}
    function loadImage(url) {
        let entry = imageCache.get(url);
        if (entry) return entry;
        const img = new Image();
        entry = {
            img,
            promise: new Promise((resolve, reject) => {
                img.onload = () => { requestRedraw(); resolve(img); };
                img.onerror = () => reject(new Error(`image failed: ${url}`));
            }),
        };
        img.src = url;
        imageCache.set(url, entry);
        return entry;
    }

    // ---- view transform ------------------------------------------------------
    let cssW = 0, cssH = 0, fitted = false;
    const view = state.view;

    function fitView() {
        if (!cssW || !cssH) return;
        const zoom = Math.min(
            (cssW - FIT_MARGIN * 2) / state.sheetW,
            (cssH - FIT_MARGIN * 2) / state.sheetH,
        );
        view.zoom = clampZoom(zoom > 0 ? zoom : 1);
        view.panX = (cssW - state.sheetW * view.zoom) / 2;
        view.panY = (cssH - state.sheetH * view.zoom) / 2;
    }
    const clampZoom = (z) => Math.min(20, Math.max(0.05, z));
    const sheetToScreen = (x, y) => ({ x: x * view.zoom + view.panX, y: y * view.zoom + view.panY });
    const screenToSheet = (x, y) => ({ x: (x - view.panX) / view.zoom, y: (y - view.panY) / view.zoom });

    // region rect in sheet px
    const regionPx = (r) => ({
        x: r.x * state.sheetW, y: r.y * state.sheetH,
        w: r.w * state.sheetW, h: r.h * state.sheetH,
    });

    // ---- redraw (rAF-throttled) ----------------------------------------------
    let rafPending = false;
    function requestRedraw() {
        if (rafPending) return;
        rafPending = true;
        requestAnimationFrame(() => { rafPending = false; draw(); });
    }

    let checkerPattern = null;
    function getCheckerPattern() {
        if (checkerPattern) return checkerPattern;
        const tile = document.createElement("canvas");
        tile.width = 16; tile.height = 16;
        const tctx = tile.getContext("2d");
        tctx.fillStyle = "#333";
        tctx.fillRect(0, 0, 16, 16);
        tctx.fillStyle = "#3c3c3c";
        tctx.fillRect(0, 0, 8, 8);
        tctx.fillRect(8, 8, 8, 8);
        checkerPattern = ctx.createPattern(tile, "repeat");
        return checkerPattern;
    }

    // Draw all member images in sheet-px space (shared by screen render + export).
    function drawMembers(c) {
        c.imageSmoothingEnabled = false;
        const regions = [...state.regions].sort((a, b) => a.zIndex - b.zIndex);
        for (const region of regions) {
            for (const member of region.members ?? []) {
                const resolved = opts.resolveMemberUrl(region, member);
                const url = typeof resolved === "string" ? resolved : resolved?.url;
                if (!url) continue;
                // The resolver may override the flip (dynamic pair convention:
                // one effective image in a two-cell region mirrors cell 2).
                const flip = typeof resolved === "object" && resolved !== null
                    ? Boolean(resolved.flip) : Boolean(member.flipX);
                const { img } = loadImage(url);
                if (!img.complete || !img.naturalWidth) continue;
                const cell = {
                    x: member.x * state.sheetW, y: member.y * state.sheetH,
                    w: member.w * state.sheetW, h: member.h * state.sheetH,
                };
                const scale = Math.min(cell.w / img.naturalWidth, cell.h / img.naturalHeight);
                const dw = img.naturalWidth * scale, dh = img.naturalHeight * scale;
                const dx = cell.x + (cell.w - dw) / 2, dy = cell.y + (cell.h - dh) / 2;
                if (flip) {
                    c.save();
                    c.translate(dx + dw, dy);
                    c.scale(-1, 1);
                    c.drawImage(img, 0, 0, dw, dh);
                    c.restore();
                } else {
                    c.drawImage(img, dx, dy, dw, dh);
                }
            }
        }
    }

    function draw() {
        const dpr = window.devicePixelRatio || 1;
        if (!cssW || !cssH) return;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, cssW, cssH);

        const tl = sheetToScreen(0, 0);
        const sw = state.sheetW * view.zoom, sh = state.sheetH * view.zoom;

        // sheet background
        ctx.save();
        ctx.beginPath();
        ctx.rect(tl.x, tl.y, sw, sh);
        ctx.clip();
        if (state.settings.background.mode === "color") {
            ctx.fillStyle = state.settings.background.color || "#808080";
            ctx.fillRect(tl.x, tl.y, sw, sh);
        } else {
            ctx.fillStyle = getCheckerPattern();
            ctx.fillRect(tl.x, tl.y, sw, sh);
        }
        // members (sheet-px space)
        ctx.translate(view.panX, view.panY);
        ctx.scale(view.zoom, view.zoom);
        drawMembers(ctx);
        ctx.restore();

        // sheet border
        ctx.strokeStyle = "rgba(204,51,51,0.4)";
        ctx.lineWidth = 1;
        ctx.strokeRect(tl.x, tl.y, sw, sh);

        // region overlays, zIndex ascending
        const regions = [...state.regions].sort((a, b) => a.zIndex - b.zIndex);
        for (const region of regions) {
            const px = regionPx(region);
            const p = sheetToScreen(px.x, px.y);
            const w = px.w * view.zoom, h = px.h * view.zoom;
            const color = PALETTE[((region.zIndex % PALETTE.length) + PALETTE.length) % PALETTE.length];
            const selected = region.id === state.selectedRegionId;

            ctx.fillStyle = color + "1f"; // ~12% alpha
            ctx.fillRect(p.x, p.y, w, h);
            ctx.strokeStyle = color;
            ctx.lineWidth = selected ? 2.5 : 1.5;
            ctx.strokeRect(p.x, p.y, w, h);

            if (!state.promptHidden) {
                // numbered badge
                ctx.fillStyle = color;
                ctx.fillRect(p.x, p.y, 13, 13);
                ctx.fillStyle = "#000";
                ctx.font = "bold 10px ui-sans-serif, system-ui, sans-serif";
                ctx.textAlign = "center";
                ctx.textBaseline = "middle";
                ctx.fillText(String(region.zIndex + 1), p.x + 6.5, p.y + 7);
                // name label
                if (region.name) {
                    ctx.save();
                    ctx.font = "10px ui-sans-serif, system-ui, sans-serif";
                    ctx.textAlign = "left";
                    ctx.fillStyle = "#fff";
                    ctx.shadowColor = "#000";
                    ctx.shadowBlur = 3;
                    ctx.fillText(region.name, p.x + 17, p.y + 7);
                    ctx.restore();
                }
            }

            if (selected) {
                for (const [cx, cy] of [[p.x, p.y], [p.x + w, p.y], [p.x, p.y + h], [p.x + w, p.y + h]]) {
                    ctx.fillStyle = "#fff";
                    ctx.strokeStyle = "#000";
                    ctx.lineWidth = 1;
                    ctx.fillRect(cx - HANDLE / 2, cy - HANDLE / 2, HANDLE, HANDLE);
                    ctx.strokeRect(cx - HANDLE / 2, cy - HANDLE / 2, HANDLE, HANDLE);
                }
            }
        }

        // smart-guide lines (sheet px -> screen)
        if (drag && (drag.guides.xs.length || drag.guides.ys.length)) {
            ctx.strokeStyle = "#0ff";
            ctx.lineWidth = 1;
            for (const gx of drag.guides.xs) {
                const a = sheetToScreen(gx, 0), b = sheetToScreen(gx, state.sheetH);
                ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
            }
            for (const gy of drag.guides.ys) {
                const a = sheetToScreen(0, gy), b = sheetToScreen(state.sheetW, gy);
                ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
            }
        }

        // rubber band
        if (drag && drag.mode === "draw" && drag.band) {
            const a = sheetToScreen(drag.band.x, drag.band.y);
            ctx.save();
            ctx.strokeStyle = "#fff";
            ctx.setLineDash([4, 3]);
            ctx.lineWidth = 1;
            ctx.strokeRect(a.x, a.y, drag.band.w * view.zoom, drag.band.h * view.zoom);
            ctx.restore();
        }
    }

    // ---- resize observer / DPR -----------------------------------------------
    const ro = new ResizeObserver(() => {
        const rect = host.getBoundingClientRect();
        cssW = rect.width; cssH = rect.height;
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.max(1, Math.round(cssW * dpr));
        canvas.height = Math.max(1, Math.round(cssH * dpr));
        if (!fitted && cssW && cssH) { fitView(); fitted = true; }
        requestRedraw();
    });
    ro.observe(host);

    // ---- hit testing -----------------------------------------------------------
    function regionAt(sheetPt) {
        const sorted = [...state.regions].sort((a, b) => b.zIndex - a.zIndex);
        for (const r of sorted) {
            const px = regionPx(r);
            if (sheetPt.x >= px.x && sheetPt.x <= px.x + px.w &&
                sheetPt.y >= px.y && sheetPt.y <= px.y + px.h) return r;
        }
        return null;
    }

    // corner index: 0=tl 1=tr 2=bl 3=br; returns null if not on a handle
    function handleAt(screenPt) {
        const region = state.selectedRegion();
        if (!region) return null;
        const px = regionPx(region);
        const p = sheetToScreen(px.x, px.y);
        const w = px.w * view.zoom, h = px.h * view.zoom;
        const corners = [[p.x, p.y], [p.x + w, p.y], [p.x, p.y + h], [p.x + w, p.y + h]];
        const slack = HANDLE / 2 + 3;
        for (let i = 0; i < 4; i++) {
            if (Math.abs(screenPt.x - corners[i][0]) <= slack &&
                Math.abs(screenPt.y - corners[i][1]) <= slack) return i;
        }
        return null;
    }

    // ---- snapping ---------------------------------------------------------------
    function snapTargets(excludeId) {
        const xs = [0, state.sheetW / 2, state.sheetW];
        const ys = [0, state.sheetH / 2, state.sheetH];
        for (const r of state.regions) {
            if (r.id === excludeId) continue;
            const px = regionPx(r);
            xs.push(px.x, px.x + px.w / 2, px.x + px.w);
            ys.push(px.y, px.y + px.h / 2, px.y + px.h);
        }
        return { xs, ys };
    }

    // Snap a set of values (edges/centers) on one axis; returns {delta, guide} or null.
    function snapAxis(values, targets, tol) {
        let best = null;
        for (const v of values) {
            for (const t of targets) {
                const d = t - v;
                if (Math.abs(d) <= tol && (!best || Math.abs(d) < Math.abs(best.delta))) {
                    best = { delta: d, guide: t };
                }
            }
        }
        return best;
    }

    // ---- pointer interactions -----------------------------------------------
    let drag = null;      // active drag descriptor
    let spaceDown = false;

    function localPoint(e) {
        const rect = canvas.getBoundingClientRect();
        return { x: e.clientX - rect.left, y: e.clientY - rect.top };
    }

    canvas.addEventListener("wheel", (e) => {
        e.preventDefault();
        const pt = localPoint(e);
        const factor = Math.pow(1.1, -e.deltaY / 100);
        const newZoom = clampZoom(view.zoom * factor);
        // keep the sheet point under the cursor fixed
        const before = screenToSheet(pt.x, pt.y);
        view.zoom = newZoom;
        view.panX = pt.x - before.x * view.zoom;
        view.panY = pt.y - before.y * view.zoom;
        requestRedraw();
    }, { passive: false });

    canvas.addEventListener("pointerdown", (e) => {
        if (e.button !== 0 && e.button !== 1) return;
        e.preventDefault();
        canvas.setPointerCapture(e.pointerId);
        const pt = localPoint(e);
        const sp = screenToSheet(pt.x, pt.y);
        const insideSheet = sp.x >= 0 && sp.x <= state.sheetW && sp.y >= 0 && sp.y <= state.sheetH;

        if (e.button === 1 || spaceDown || !insideSheet) {
            drag = { mode: "pan", start: pt, startPan: { x: view.panX, y: view.panY }, guides: { xs: [], ys: [] } };
            canvas.style.cursor = "grabbing";
            return;
        }

        const corner = handleAt(pt);
        if (corner !== null) {
            const region = state.selectedRegion();
            const px = regionPx(region);
            drag = {
                mode: "resize", id: region.id, corner,
                fixed: {
                    x: corner === 0 || corner === 2 ? px.x + px.w : px.x,
                    y: corner === 0 || corner === 1 ? px.y + px.h : px.y,
                },
                guides: { xs: [], ys: [] },
            };
            return;
        }

        const hit = regionAt(sp);
        if (hit) {
            if (hit.id !== state.selectedRegionId) state.selectRegion(hit.id);
            const px = regionPx(hit);
            drag = {
                mode: "move", id: hit.id, start: pt, startSheet: sp,
                origin: { x: px.x, y: px.y, w: px.w, h: px.h },
                moved: false, guides: { xs: [], ys: [] },
            };
            return;
        }

        drag = { mode: "draw", start: pt, startSheet: sp, band: null, guides: { xs: [], ys: [] } };
    });

    canvas.addEventListener("pointermove", (e) => {
        if (!drag) return;
        const pt = localPoint(e);
        const sp = screenToSheet(pt.x, pt.y);
        const tol = SNAP_TOL_SCREEN / view.zoom;

        if (drag.mode === "pan") {
            view.panX = drag.startPan.x + (pt.x - drag.start.x);
            view.panY = drag.startPan.y + (pt.y - drag.start.y);
            requestRedraw();
            return;
        }

        if (drag.mode === "draw") {
            drag.band = {
                x: Math.min(drag.startSheet.x, sp.x),
                y: Math.min(drag.startSheet.y, sp.y),
                w: Math.abs(sp.x - drag.startSheet.x),
                h: Math.abs(sp.y - drag.startSheet.y),
            };
            requestRedraw();
            return;
        }

        if (drag.mode === "move") {
            if (!drag.moved &&
                Math.abs(pt.x - drag.start.x) < 3 && Math.abs(pt.y - drag.start.y) < 3) return;
            drag.moved = true;
            let nx = drag.origin.x + (sp.x - drag.startSheet.x);
            let ny = drag.origin.y + (sp.y - drag.startSheet.y);
            const snap = state.settings.snap;
            if (snap > 0) {
                nx = Math.round(nx / snap) * snap;
                ny = Math.round(ny / snap) * snap;
            }
            drag.guides = { xs: [], ys: [] };
            if (state.settings.smartGuides) {
                const targets = snapTargets(drag.id);
                const bx = snapAxis([nx, nx + drag.origin.w / 2, nx + drag.origin.w], targets.xs, tol);
                const by = snapAxis([ny, ny + drag.origin.h / 2, ny + drag.origin.h], targets.ys, tol);
                if (bx) { nx += bx.delta; drag.guides.xs.push(bx.guide); }
                if (by) { ny += by.delta; drag.guides.ys.push(by.guide); }
            }
            state.updateRegion(drag.id, { x: nx / state.sheetW, y: ny / state.sheetH });
            return;
        }

        if (drag.mode === "resize") {
            let mx = sp.x, my = sp.y;
            const snap = state.settings.snap;
            if (snap > 0) {
                mx = Math.round(mx / snap) * snap;
                my = Math.round(my / snap) * snap;
            }
            drag.guides = { xs: [], ys: [] };
            if (state.settings.smartGuides) {
                const targets = snapTargets(drag.id);
                const bx = snapAxis([mx], targets.xs, tol);
                const by = snapAxis([my], targets.ys, tol);
                if (bx) { mx += bx.delta; drag.guides.xs.push(bx.guide); }
                if (by) { my += by.delta; drag.guides.ys.push(by.guide); }
            }
            // enforce min size, preserving which side of the fixed corner we're on
            if (mx >= drag.fixed.x) mx = Math.max(drag.fixed.x + MIN_SIZE_PX, mx);
            else mx = Math.min(drag.fixed.x - MIN_SIZE_PX, mx);
            if (my >= drag.fixed.y) my = Math.max(drag.fixed.y + MIN_SIZE_PX, my);
            else my = Math.min(drag.fixed.y - MIN_SIZE_PX, my);
            const rx = Math.min(drag.fixed.x, mx), ry = Math.min(drag.fixed.y, my);
            state.updateRegion(drag.id, {
                x: rx / state.sheetW, y: ry / state.sheetH,
                w: Math.abs(mx - drag.fixed.x) / state.sheetW,
                h: Math.abs(my - drag.fixed.y) / state.sheetH,
            });
        }
    });

    function endDrag(e) {
        if (!drag) return;
        const d = drag;
        drag = null;
        canvas.style.cursor = spaceDown ? "grab" : "crosshair";
        if (d.mode === "draw") {
            const pt = localPoint(e);
            const dxPx = Math.abs(pt.x - d.start.x), dyPx = Math.abs(pt.y - d.start.y);
            if (d.band && dxPx > 8 && dyPx > 8) {
                state.addRegion({
                    x: d.band.x / state.sheetW, y: d.band.y / state.sheetH,
                    w: d.band.w / state.sheetW, h: d.band.h / state.sheetH,
                });
            } else {
                state.selectRegion(null);
            }
        }
        requestRedraw();
    }
    canvas.addEventListener("pointerup", endDrag);
    canvas.addEventListener("pointercancel", endDrag);

    // ---- keyboard --------------------------------------------------------------
    function editableTarget(e) {
        const t = e.target;
        return t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
    }
    function onKeyDown(e) {
        if (!host.isConnected) return;
        if (editableTarget(e)) return;
        if (e.code === "Space") {
            spaceDown = true;
            if (!drag) canvas.style.cursor = "grab";
            e.preventDefault();
            return;
        }
        if ((e.key === "Delete" || e.key === "Backspace") && state.selectedRegionId) {
            e.preventDefault();
            state.deleteRegion(state.selectedRegionId);
        }
    }
    function onKeyUp(e) {
        if (e.code === "Space") {
            spaceDown = false;
            if (!drag) canvas.style.cursor = "crosshair";
        }
    }
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", () => { spaceDown = false; });

    // ---- state subscriptions -----------------------------------------------
    state.on("change", requestRedraw);
    state.on("sheet", () => { syncFooter(); fitView(); requestRedraw(); });

    // ---- export ------------------------------------------------------------
    async function exportSheet() {
        const out = document.createElement("canvas");
        out.width = state.sheetW;
        out.height = state.sheetH;
        const octx = out.getContext("2d");
        if (state.settings.background.mode === "color") {
            octx.fillStyle = state.settings.background.color || "#808080";
            octx.fillRect(0, 0, out.width, out.height);
        }
        // await every member image (tolerate failures)
        const waits = [];
        for (const region of state.regions) {
            for (const member of region.members ?? []) {
                const resolved = opts.resolveMemberUrl(region, member);
                const url = typeof resolved === "string" ? resolved : resolved?.url;
                if (url) waits.push(loadImage(url).promise.catch(() => null));
            }
        }
        await Promise.all(waits);
        drawMembers(octx);
        return out.toDataURL("image/png");
    }

    return { exportSheet, redraw: requestRedraw };
}
