// ABOUTME: Inspector panel (right column) of the template editor — reference-mode
// ABOUTME: toggle, selected-region editor (name/kind/desc/refs), and the region stack list.

const PALETTE = ["#e6c229", "#4caf7d", "#5b7fd4", "#3fbf9f", "#7ec4e8", "#b06ad4", "#e08a4a"];

function regionColor(zIndex) {
    return PALETTE[((zIndex % PALETTE.length) + PALETTE.length) % PALETTE.length];
}

function el(tag, style, text) {
    const node = document.createElement(tag);
    if (style) node.style.cssText = style;
    if (text != null) node.textContent = text;
    return node;
}

function badge(zIndex) {
    const b = el(
        "span",
        "display:inline-flex;align-items:center;justify-content:center;" +
            "width:18px;height:18px;border-radius:50%;font-size:10px;font-weight:700;" +
            "color:#111;flex:none;",
        String(zIndex + 1)
    );
    b.style.background = regionColor(zIndex);
    return b;
}

function sectionTitle(text) {
    const t = el("div", null, text);
    t.className = "section-title";
    return t;
}

function basename(p) {
    return String(p).split("/").pop();
}

export function renderInspector(state, host, opts) {
    const expanded = new Set(); // assetName folders open in the task-references tree
    let muted = false; // suppress re-render while a text field we own is being typed in

    const guardedUpdate = (id, patch) => {
        muted = true;
        try {
            state.updateRegion(id, patch);
        } finally {
            muted = false;
        }
    };

    // (reference-mode toggle lives in the editor top bar, above the canvas)
    function buildRefToggle() {
        return document.createDocumentFragment();
    }

    // ---- section 3: selected region editor ----------------------------------
    function buildRegionEditor(region) {
        const frag = document.createDocumentFragment();

        // header: badge + name + delete
        const head = el("div", "display:flex;align-items:center;gap:6px;margin:2px 0 6px;");
        head.appendChild(badge(region.zIndex));
        const name = document.createElement("input");
        name.type = "text";
        name.placeholder = "region name";
        name.value = region.name ?? "";
        name.style.flex = "1";
        name.style.minWidth = "0";
        name.addEventListener("input", () => guardedUpdate(region.id, { name: name.value }));
        const del = el("button", "flex:none;", "🗑");
        del.title = "Delete region";
        del.addEventListener("click", () => state.deleteRegion(region.id));
        head.append(name, del);
        frag.appendChild(head);

        // SKILL line
        const skill = el("div", "display:flex;align-items:center;gap:6px;margin:2px 0;");
        const skillLabel = el("span", "font-size:10px;text-transform:uppercase;letter-spacing:.06em;opacity:.6;", "Skill");
        const skillVal = el(
            "span",
            "flex:1;text-align:right;opacity:.55;",
            region.assetType ?? "—"
        );
        skill.append(skillLabel, skillVal);
        frag.appendChild(skill);

        // SCALE row: double or halve the region and its cells in place
        // (use case: 128px food icons rendered at 256).
        const scaleRow = el("div", "display:flex;align-items:center;gap:6px;margin:2px 0;");
        scaleRow.appendChild(el("span",
            "font-size:10px;text-transform:uppercase;letter-spacing:.06em;opacity:.6;flex:1;",
            "Scale"));
        for (const [factor, label] of [[0.5, "×½"], [2, "×2"]]) {
            const btn = el("button", "flex:none;", label);
            btn.title = factor === 2
                ? "Double the region and its sprites"
                : "Halve the region and its sprites";
            btn.addEventListener("click", () => state.scaleRegion(region.id, factor));
            scaleRow.appendChild(btn);
        }
        frag.appendChild(scaleRow);

        // CELLS strip: reorder the items of a multi-cell region (visual
        // left-to-right order; arrows swap the content mapping, cells stay put).
        const members = region.members ?? [];
        if (members.length > 1) {
            frag.appendChild(sectionTitle(`Cells · ${members.length} — reorder items`));
            const strip = el("div", "display:flex;gap:6px;flex-wrap:wrap;margin:2px 0 6px;");
            const visual = members
                .map((m, idx) => ({ m, idx }))
                .sort((a, b) => (a.m.y - b.m.y) || (a.m.x - b.m.x));
            visual.forEach((entry, vi) => {
                const cell = el("div",
                    "display:flex;flex-direction:column;align-items:center;gap:2px;" +
                    "border:1px solid #333;border-radius:5px;padding:3px;");
                const resolved = opts.resolveMemberUrl?.(region, entry.m);
                const url = typeof resolved === "string" ? resolved : resolved?.url;
                const img = el("img",
                    "width:40px;height:40px;object-fit:contain;background:#111;border-radius:3px;");
                if (url) img.src = url;
                cell.appendChild(img);
                const arrows = el("div", "display:flex;gap:2px;");
                const mk = (txt, delta) => {
                    const b = el("button", "padding:0 5px;font-size:10px;", txt);
                    const target = visual[vi + delta];
                    b.disabled = !target;
                    b.addEventListener("click", () => {
                        if (target) state.swapMemberContent(region.id, entry.idx, target.idx);
                    });
                    return b;
                };
                arrows.append(mk("←", -1), mk("→", 1));
                cell.appendChild(arrows);
                strip.appendChild(cell);
            });
            frag.appendChild(strip);
        }

        // KIND segmented control
        frag.appendChild(sectionTitle("Kind"));
        const seg = el("div", "display:flex;gap:6px;margin:2px 0 6px;");
        for (const [kind, label] of [["object", "Object"], ["text", "Text"]]) {
            const btn = el("button", "flex:1;", label);
            if (region.kind === kind) btn.classList.add("active");
            btn.addEventListener("click", () => state.updateRegion(region.id, { kind }));
            seg.appendChild(btn);
        }
        frag.appendChild(seg);

        // DESCRIPTION / TEXT
        const isText = region.kind === "text";
        frag.appendChild(sectionTitle(isText ? "Text" : "Description"));
        const ta = document.createElement("textarea");
        ta.rows = 5;
        ta.value = (isText ? region.text : region.desc) ?? "";
        ta.placeholder = isText
            ? "The exact text this region should render."
            : "What should appear in this region.";
        ta.addEventListener("input", () => {
            guardedUpdate(region.id, isText ? { text: ta.value } : { desc: ta.value });
        });
        frag.appendChild(ta);

        // REFERENCE IMAGE preview
        frag.appendChild(sectionTitle("Reference image"));
        const box = el(
            "div",
            "border:1px solid #333;border-radius:6px;padding:6px;display:flex;" +
                "flex-direction:column;align-items:center;gap:4px;min-height:40px;" +
                "justify-content:center;background:#141414;"
        );
        let previewUrl = null;
        let previewCaption = null;
        if (region.projectPaths?.[0]) {
            previewUrl = opts.imageUrl?.(state.root, region.projectPaths[0]) ?? null;
            previewCaption = basename(region.projectPaths[0]);
            if (region.projectPaths.length > 1) {
                previewCaption += ` (+${region.projectPaths.length - 1} more)`;
            }
        } else if (region.taskRefs?.paths?.length) {
            previewUrl = opts.refImageUrl?.(basename(region.taskRefs.paths[0])) ?? null;
            previewCaption = `${basename(region.taskRefs.paths[0])} (${region.taskRefs.paths.length} refs)`;
        }
        if (previewCaption) {
            if (previewUrl) {
                const img = document.createElement("img");
                img.src = previewUrl;
                img.style.cssText = "max-width:100%;max-height:120px;border-radius:4px;";
                box.appendChild(img);
            }
            box.appendChild(el("div", "font-size:10px;opacity:.7;word-break:break-all;", previewCaption));
        } else {
            box.appendChild(el("div", "opacity:.5;", "no reference"));
        }
        frag.appendChild(box);
        frag.appendChild(el(
            "div",
            "color:#d9a23a;font-size:10px;margin:4px 0 6px;line-height:1.4;",
            "Description wins over the reference — keep it consistent with the attached image, or clear one of them."
        ));

        // Rebuild a region's cells from its ticked task-ref paths. With
        // mirrorPair on, ONE ref makes a two-cell pair — cell 1 the ref, cell 2
        // its horizontal mirror; the 2-cell / 1-path shape is exactly what makes
        // both the canvas preview and the baked sheet flip the second cell.
        const cellsFor = (reg, paths) => {
            const cw = reg.members?.[0]?.w
                ?? (reg.cellPx ? reg.cellPx.w / state.sheetW : reg.w);
            const ch = reg.members?.[0]?.h ?? reg.h;
            if (reg.mirrorPair && paths.length) {
                const spriteId = paths[0];
                return {
                    members: [
                        { spriteId, x: reg.x, y: reg.y, w: cw, h: ch },
                        { spriteId, flipX: true, x: reg.x + cw, y: reg.y, w: cw, h: ch },
                    ],
                    paths: [spriteId], w: 2 * cw, h: ch,
                };
            }
            return {
                members: paths.map((spriteId, i) => ({
                    spriteId, x: reg.x + i * cw, y: reg.y, w: cw, h: ch,
                })),
                paths, w: paths.length ? paths.length * cw : reg.w, h: ch,
            };
        };
        const applyRefs = (reg, paths) => {
            const c = cellsFor(reg, paths);
            state.updateRegion(reg.id, {
                taskRefs: c.paths.length ? { paths: c.paths, mode: "meta" } : undefined,
                members: c.members, w: c.w, h: c.h,
            });
        };

        // Mirror-pair toggle: use one decoration image as a flipped pair instead
        // of needing a pre-mirrored second reference.
        const mirrorRow = el("div",
            "display:flex;align-items:center;gap:6px;margin:2px 0 6px;");
        const mirrorCb = document.createElement("input");
        mirrorCb.type = "checkbox";
        mirrorCb.checked = !!region.mirrorPair;
        mirrorCb.style.flex = "none";
        mirrorCb.addEventListener("change", () => {
            const reg = state.selectedRegion();
            if (!reg) return;
            const paths = reg.taskRefs?.paths ?? [];
            const c = cellsFor({ ...reg, mirrorPair: mirrorCb.checked }, paths);
            state.updateRegion(reg.id, {
                mirrorPair: mirrorCb.checked,
                taskRefs: c.paths.length ? { paths: c.paths, mode: "meta" } : undefined,
                members: c.members, w: c.w, h: c.h,
            });
        });
        mirrorRow.append(mirrorCb,
            el("span", "font-size:11px;", "Mirror pair — flip a single ref"));
        frag.appendChild(mirrorRow);

        // TASK REFERENCES tree
        const assets = state.taskAssets ?? [];
        const totalRefs = assets.reduce((n, a) => n + (a.refFiles?.length ?? 0), 0);
        const trTitle = sectionTitle(`Task references · ${totalRefs}`);
        frag.appendChild(trTitle);
        const currentPaths = region.taskRefs?.paths ?? [];
        for (const asset of assets) {
            const files = asset.refFiles ?? [];
            const prefix = `${asset.category}/${asset.assetName}/`;
            const checkedCount = currentPaths.filter((p) => p.startsWith(prefix)).length;
            const isOpen = expanded.has(asset.assetName);

            const folder = el(
                "div",
                "display:flex;align-items:center;gap:6px;padding:3px 4px;cursor:pointer;" +
                    "border-radius:4px;"
            );
            folder.appendChild(el("span", "opacity:.7;width:12px;flex:none;", isOpen ? "▾" : "▸"));
            folder.appendChild(el("span", "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;", asset.assetName));
            folder.appendChild(el("span", "opacity:.55;font-size:10px;flex:none;", `${checkedCount}/${files.length}`));
            folder.addEventListener("click", () => {
                if (isOpen) expanded.delete(asset.assetName);
                else expanded.add(asset.assetName);
                render();
            });
            frag.appendChild(folder);

            if (!isOpen) continue;
            for (const file of files) {
                const path = `${asset.category}/${asset.assetName}/${file}`;
                const row = el(
                    "div",
                    "display:flex;align-items:center;gap:6px;padding:2px 4px 2px 18px;"
                );
                const cb = document.createElement("input");
                cb.type = "checkbox";
                cb.checked = currentPaths.includes(path);
                cb.style.flex = "none";
                cb.addEventListener("change", () => {
                    const reg = state.selectedRegion();
                    if (!reg) return;
                    if (reg.mirrorPair) {
                        // Mirror mode: one ref drives the pair — this click picks
                        // it (or clears the region).
                        applyRefs(reg, cb.checked ? [path] : []);
                        return;
                    }
                    // Which refs are ticked now — kept in this asset's ref order
                    // (the region is one asset) so cells stay left-to-right.
                    const checked = new Set(reg.taskRefs?.paths ?? []);
                    if (cb.checked) checked.add(path); else checked.delete(path);
                    const owner = (state.taskAssets ?? [])
                        .find((a) => a.assetName === reg.name);
                    const ordered = owner
                        ? owner.refFiles
                            .map((f) => `${owner.category}/${owner.assetName}/${f}`)
                            .filter((p) => checked.has(p))
                        : [...checked];
                    applyRefs(reg, ordered);
                });
                row.appendChild(cb);
                const thumbUrl = opts.refImageUrl?.(file) ?? null;
                if (thumbUrl) {
                    const img = document.createElement("img");
                    img.src = thumbUrl;
                    img.style.cssText =
                        "width:28px;height:28px;object-fit:cover;border-radius:4px;flex:none;" +
                        "border:1px solid #333;";
                    row.appendChild(img);
                }
                row.appendChild(el(
                    "span",
                    "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;opacity:.85;",
                    file
                ));
                frag.appendChild(row);
            }
        }
        return frag;
    }

    // ---- section 4: regions list --------------------------------------------
    function buildRegionsList() {
        const frag = document.createDocumentFragment();
        const ordered = [...state.regions].sort((a, b) => a.zIndex - b.zIndex);

        const header = el("div", "display:flex;align-items:baseline;gap:8px;");
        header.appendChild(sectionTitle("Regions"));
        header.appendChild(el("span", "font-size:10px;opacity:.5;", `${ordered.length} · back → front`));
        frag.appendChild(header);

        ordered.forEach((region, i) => {
            const row = el(
                "div",
                "display:flex;align-items:center;gap:6px;padding:3px 6px;margin:2px 0;" +
                    "border:1px solid #2a2a2a;border-radius:5px;cursor:pointer;"
            );
            if (state.isSelected(region.id) || region.id === state.selectedRegionId) {
                row.style.borderColor = "#c33";
                row.style.background = "#1c1414";
            }
            row.appendChild(badge(region.zIndex));
            row.appendChild(el(
                "span",
                "flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;",
                region.name || `region …${region.id.slice(-6)}`
            ));

            const move = (delta) => {
                const j = i + delta;
                if (j < 0 || j >= ordered.length) return;
                const ids = ordered.map((r) => r.id);
                [ids[i], ids[j]] = [ids[j], ids[i]];
                state.restackRegions(ids);
            };
            const up = el("button", "padding:1px 6px;flex:none;", "↑");
            up.title = "Move toward back";
            up.disabled = i === 0;
            up.addEventListener("click", (e) => { e.stopPropagation(); move(-1); });
            const down = el("button", "padding:1px 6px;flex:none;", "↓");
            down.title = "Move toward front";
            down.disabled = i === ordered.length - 1;
            down.addEventListener("click", (e) => { e.stopPropagation(); move(1); });
            row.append(up, down);

            row.addEventListener("click", (e) => {
                if (e.shiftKey) state.toggleSelect(region.id);
                else state.selectRegion(region.id);
            });
            frag.appendChild(row);
        });
        return frag;
    }

    // ---- render ---------------------------------------------------------------
    function buildMultiEditor() {
        const frag = document.createDocumentFragment();
        const n = state.selectedRegionIds.size;
        frag.appendChild(el("div", "text-align:center;opacity:.8;padding:8px 0 4px;",
            `${n} regions selected`));
        const row = el("div", "display:flex;justify-content:center;gap:6px;margin:4px 0 8px;");
        for (const [factor, label] of [[0.5, "×½ all"], [2, "×2 all"]]) {
            const b = el("button", null, label);
            b.addEventListener("click", () => {
                for (const id of [...state.selectedRegionIds]) state.scaleRegion(id, factor);
            });
            row.appendChild(b);
        }
        const del = el("button", null, "🗑 Delete all");
        del.addEventListener("click", () => {
            for (const id of [...state.selectedRegionIds]) state.deleteRegion(id);
        });
        row.appendChild(del);
        frag.appendChild(row);
        return frag;
    }

    function render() {
        if (muted) return;
        const parts = [buildRefToggle()];
        const region = state.selectedRegion();
        if (state.selectedRegionIds.size > 1) {
            parts.push(buildMultiEditor());
        } else if (region) {
            parts.push(buildRegionEditor(region));
        } else {
            parts.push(el(
                "div",
                "text-align:center;opacity:.5;padding:14px 10px;line-height:1.5;",
                "Select a region on the canvas or in the list to edit its description, kind, and reference image."
            ));
        }
        parts.push(buildRegionsList());
        host.replaceChildren(...parts);
    }

    state.on("selection", () => {
        // Focus: expand only the selected region's asset in the task-refs
        // tree, collapse the others.
        const sel = state.selectedRegion();
        if (sel?.name) {
            expanded.clear();
            expanded.add(sel.name);
        }
        render();
    });
    state.on("regions", render);
    render();
}
