// ABOUTME: Left rail of the template editor — prefill/save/load, project asset
// ABOUTME: tree with region assignment checkboxes, and the pack settings panel.
import { prefillRegions, rebuildSpecRegions, MODEL_PRESETS, presetDims, slugify,
         matchCategory, categoryCanvasSizes, flattenSpritePath, canvasSpecOf }
    from "./algos.js";

const THUMB_SIZES = { S: 18, M: 28, L: 44, XL: 64 };

const ALGORITHMS = [
    ["maxrects", "MaxRects"],
    ["shelf", "Shelf ⁄ Strip"],
    ["grid", "Grid"],
];

// --- tiny DOM helpers (house style: textContent only, no innerHTML) ----------
function el(tag, css, text) {
    const node = document.createElement(tag);
    if (css) node.style.cssText = css;
    if (text != null) node.textContent = text;
    return node;
}

function labeledRow(labelText, control) {
    const row = el("div");
    row.className = "row";
    const label = el("label", "", labelText);
    row.append(label, control);
    return row;
}

function numberInput(value, onCommit) {
    const input = el("input", "width:64px;");
    input.type = "number";
    input.min = "0";
    input.value = String(value ?? 0);
    input.addEventListener("change", () => {
        const n = Number(input.value);
        onCommit(Number.isFinite(n) ? Math.max(0, n) : 0);
    });
    return input;
}

function checkboxInput(checked, onCommit) {
    const input = el("input");
    input.type = "checkbox";
    input.checked = Boolean(checked);
    input.addEventListener("change", () => onCommit(input.checked));
    return input;
}

function selectInput(options, value, onCommit) {
    const select = el("select", "flex:1;min-width:0;");
    for (const [val, label] of options) {
        const opt = el("option", "", label);
        opt.value = val;
        select.appendChild(opt);
    }
    select.value = value;
    select.addEventListener("change", () => onCommit(select.value));
    return select;
}

// ------------------------------------------------------------------------------
/**
 * Render the left rail into `host` and keep it live on state events.
 * opts: { imageUrl(root, rel), saveTemplate(name), listSaved(), loadAssets(dir) }
 */
export function renderRail(state, host, opts) {
    const local = {
        thumb: "M",
        expanded: new Set(),
        loadOpen: false,
        packOpen: true,
        saving: false,
        error: "",
    };

    host.replaceChildren();

    // --- 1. prefill ------------------------------------------------------------
    const prefillBtn = el("button", "width:100%;margin-bottom:6px;", "⟳ Prefill from specs");
    prefillBtn.className = "primary";
    prefillBtn.disabled = state.taskAssets.length === 0;
    prefillBtn.addEventListener("click", () => {
        const assets = taskAssetsWithRefs();
        if (!assets.length) return;
        // Full reset (rebuildSpecRegions-style): drop everything, lay out fresh.
        const out = prefillRegions(assets, state.sheetW, state.sheetH, undefined,
                                   state.settings);
        state.setRegions(out.regions);
    });
    host.appendChild(prefillBtn);

    function taskAssetsWithRefs() {
        return state.taskAssets.filter(
            (a) => a.assetName && (a.refFiles?.length ?? 0) > 0);
    }

    // --- 2. name / save / load ---------------------------------------------------
    const nameRow = el("div");
    nameRow.className = "row";
    const nameInput = el("input", "flex:1;min-width:0;");
    nameInput.type = "text";
    const saveBtn = el("button", "", "Save");
    const loadBtn = el("button", "", "Load…");
    nameRow.append(nameInput, saveBtn, loadBtn);
    host.appendChild(nameRow);

    const saveError = el("div", "color:#e66;font-size:11px;margin:2px 0;display:none;");
    host.appendChild(saveError);

    const loadPanel = el("div",
        "border:1px solid #333;border-radius:6px;margin:4px 0;padding:4px;" +
        "background:#141414;max-height:180px;overflow-y:auto;display:none;");
    host.appendChild(loadPanel);

    function syncTemplateRow() {
        nameInput.placeholder = state.loadedName
            ? `${state.loadedName} (current)`
            : "template name";
    }
    syncTemplateRow();
    state.on("template", syncTemplateRow);

    saveBtn.addEventListener("click", async () => {
        if (local.saving) return;
        const typed = nameInput.value.trim();
        const name = typed ? slugify(typed) : state.loadedName;
        if (!name) {
            saveError.textContent = "Give the template a name first.";
            saveError.style.display = "";
            return;
        }
        local.saving = true;
        saveBtn.disabled = true;
        saveError.style.display = "none";
        try {
            const res = await opts.saveTemplate(name);
            state.loadedName = res.name;
            state.templateName = res.name;
            nameInput.value = "";
            state.emit("template");
        } catch (e) {
            saveError.textContent = `Save failed: ${e.message ?? e}`;
            saveError.style.display = "";
        } finally {
            local.saving = false;
            saveBtn.disabled = false;
        }
    });

    loadBtn.addEventListener("click", async () => {
        local.loadOpen = !local.loadOpen;
        loadPanel.style.display = local.loadOpen ? "" : "none";
        if (!local.loadOpen) return;
        loadPanel.replaceChildren(el("div", "opacity:.6;", "Loading…"));
        let items;
        try {
            items = await opts.listSaved();
        } catch (e) {
            loadPanel.replaceChildren(
                el("div", "color:#e66;", `List failed: ${e.message ?? e}`));
            return;
        }
        loadPanel.replaceChildren();
        if (!items.length) {
            loadPanel.appendChild(el("div", "opacity:.6;", "No saved templates."));
            return;
        }
        for (const item of items) {
            const row = el("div",
                "display:flex;justify-content:space-between;gap:6px;padding:2px 4px;" +
                "cursor:pointer;border-radius:4px;");
            row.addEventListener("mouseenter", () => { row.style.background = "#2a2a2a"; });
            row.addEventListener("mouseleave", () => { row.style.background = ""; });
            const label = el("span",
                "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;", item.name);
            const count = el("span", "opacity:.6;white-space:nowrap;",
                             `${item.regions?.length ?? 0} regions`);
            row.append(label, count);
            row.addEventListener("click", () => applySaved(item));
            loadPanel.appendChild(row);
        }
    });

    function applySaved(item) {
        suppressRelayout = true;
        try {
            if (item.settings) {
                Object.assign(state.settings, item.settings);
                state.emit("settings");
            }
            state.setRegions(structuredClone(item.regions ?? []));
        } finally {
            suppressRelayout = false;
        }
        state.loadedName = item.name;
        state.templateName = item.name;
        if (typeof item.scenePrompt === "string" && !state.scenePrompt) {
            state.scenePrompt = item.scenePrompt;
        }
        state.emit("template");
        local.loadOpen = false;
        loadPanel.style.display = "none";
    }

    // --- 3. hint -----------------------------------------------------------------
    host.appendChild(el("div", "opacity:.55;font-size:11px;margin:6px 0;",
        "Select a region, then check an asset to make it the region's base. " +
        "Checks show what's assigned; uncheck to go back to the reference."));

    // --- 4. task assets chip -------------------------------------------------------
    const categories = [...new Set(
        state.taskAssets.map((a) => a.category).filter(Boolean))];
    const chipLine = el("div", "margin:4px 0;");
    const chip = el("span",
        "display:inline-block;border:1px solid #c33;color:#f66;border-radius:10px;" +
        "padding:1px 8px;font-size:10px;",
        `Task assets (${categories.join(", ")})`);
    chipLine.appendChild(chip);
    host.appendChild(chipLine);

    // --- 5. project assets tree ------------------------------------------------------
    const treeHead = el("div");
    treeHead.className = "section-title";
    treeHead.style.display = "flex";
    treeHead.style.justifyContent = "space-between";
    treeHead.style.alignItems = "center";
    const treeTitle = el("span");
    const sizeBar = el("span");
    for (const s of Object.keys(THUMB_SIZES)) {
        const link = el("a", "cursor:pointer;margin-left:6px;", s);
        link.addEventListener("click", () => {
            local.thumb = s;
            renderSizeBar();
            renderTree();
        });
        sizeBar.appendChild(link);
    }
    function renderSizeBar() {
        [...sizeBar.children].forEach((a) => {
            a.style.opacity = a.textContent === local.thumb ? "1" : "0.5";
        });
    }
    renderSizeBar();
    treeHead.append(treeTitle, sizeBar);
    host.appendChild(treeHead);

    const treeBody = el("div");
    host.appendChild(treeBody);

    function assignmentsByRel() {
        // rel path -> region assigned to it (first wins per hub semantics).
        // A region may hold several paths (multi-cell assets pick one per cell).
        const map = new Map();
        for (const r of state.regions) {
            for (const rel of r.projectPaths ?? []) {
                if (rel && !map.has(rel)) map.set(rel, r);
            }
        }
        return map;
    }

    function taskCategories() {
        return [...new Set(state.taskAssets.map((a) => a.category).filter(Boolean))];
    }

    function displayEntries() {
        // Filtered rail entries (hub template-filter): each image reorganized
        // under its ORDER category with a resolution level; sprites matching no
        // task category are hidden, and per-category resolutions are limited to
        // the ordered canvas (and its 2x variant). No task context -> show all.
        const categories = taskCategories();
        const sizesByCat = categoryCanvasSizes(state.taskAssets);
        const entries = [];
        for (const img of state.images) {
            const rel = typeof img === "string" ? img : img.rel;
            const size = typeof img === "string" ? null : { w: img.w, h: img.h };
            if (!categories.length) {
                entries.push({ display: rel, rel });
                continue;
            }
            const display = flattenSpritePath(rel, categories, size);
            const cat = matchCategory(display.split("/")[0], categories);
            if (!cat) continue; // not an asset type this task asks for
            const wanted = sizesByCat.get(cat.toLowerCase());
            if (wanted?.size && size?.w && size?.h) {
                const ok = [...wanted].some((c) => {
                    const spec = canvasSpecOf(c);
                    return spec && ((size.w === spec.w && size.h === spec.h) ||
                                    (size.w === spec.w * 2 && size.h === spec.h * 2));
                });
                if (!ok) continue; // resolution the order doesn't ask for
            }
            entries.push({ display, rel });
        }
        return entries;
    }

    function buildTree(entries) {
        // Trie of display-path segments: {folders: Map<name, node>, files: [entry]}
        const rootNode = { folders: new Map(), files: [], count: 0 };
        for (const entry of entries) {
            const parts = entry.display.split("/");
            let node = rootNode;
            node.count++;
            for (let i = 0; i < parts.length - 1; i++) {
                if (!node.folders.has(parts[i])) {
                    node.folders.set(parts[i], { folders: new Map(), files: [], count: 0 });
                }
                node = node.folders.get(parts[i]);
                node.count++;
            }
            node.files.push(entry);
        }
        return rootNode;
    }

    function renderTree() {
        treeBody.replaceChildren();
        if (!state.root) {
            treeBody.appendChild(el("div", "opacity:.6;font-size:11px;",
                "Set the project folder on the node first."));
            return;
        }
        const assigned = assignmentsByRel();
        const sel = state.selectedRegion();
        const px = THUMB_SIZES[local.thumb];

        function fileRow(entry, depth) {
            const rel = entry.rel;
            const row = el("div",
                `display:flex;align-items:center;gap:6px;padding:1px 0 1px ${12 * depth}px;`);
            const check = el("input");
            check.type = "checkbox";
            check.checked = Boolean(sel?.projectPaths?.includes(rel));
            check.disabled = !sel;
            check.addEventListener("change", () => {
                if (!sel) return;
                // Multi-cell regions take one sprite per cell (check several,
                // in click order, capped at the cell count); checking beyond
                // the cap replaces the last pick.
                const cap = Math.max(1, sel.members?.length ?? 1);
                let paths = (sel.projectPaths ?? []).filter((p) => p !== rel);
                if (check.checked) {
                    if (paths.length >= cap) paths = paths.slice(0, cap - 1);
                    paths.push(rel);
                }
                state.updateRegion(sel.id, { projectPaths: paths });
            });
            row.appendChild(check);

            const img = el("img",
                `width:${px}px;height:${px}px;object-fit:contain;background:#111;` +
                "border-radius:3px;flex:none;");
            img.loading = "lazy";
            img.src = opts.imageUrl(state.root, rel);
            row.appendChild(img);

            const label = el("span",
                "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;");
            let text = rel.split("/").pop();
            const owner = assigned.get(rel);
            if (owner) text += `  → ${owner.name || owner.id}`;
            label.textContent = text;
            label.title = rel;
            row.appendChild(label);
            return row;
        }

        function countAssigned(node) {
            let n = node.files.filter((e) => assigned.has(e.rel)).length;
            for (const child of node.folders.values()) n += countAssigned(child);
            return n;
        }

        function filesUnder(node) {
            const rels = node.files.map((e) => e.rel);
            for (const child of node.folders.values()) rels.push(...filesUnder(child));
            return rels;
        }

        function renderNode(node, prefix, depth) {
            for (const [name, child] of node.folders) {
                const key = prefix ? `${prefix}/${name}` : name;
                const open = local.expanded.has(key);
                const fh = el("div",
                    `display:flex;align-items:center;gap:4px;padding:2px 0 2px ${12 * depth}px;` +
                    "white-space:nowrap;overflow:hidden;text-overflow:ellipsis;");

                // Folder checkbox: one click assigns the whole folder's sprites
                // to the selected region (tree order, capped at the cell count);
                // uncheck removes them all.
                const rels = filesUnder(child);
                const inSel = (p) => Boolean(sel?.projectPaths?.includes(p));
                const nChecked = rels.filter(inSel).length;
                const check = el("input");
                check.type = "checkbox";
                check.checked = nChecked > 0 && nChecked === rels.length;
                check.indeterminate = nChecked > 0 && nChecked < rels.length;
                check.disabled = !sel;
                check.addEventListener("click", (e) => e.stopPropagation());
                check.addEventListener("change", () => {
                    if (!sel) return;
                    const cap = Math.max(1, sel.members?.length ?? 1);
                    let paths = (sel.projectPaths ?? []).filter((p) => !rels.includes(p));
                    if (check.checked) {
                        for (const rel of rels) {
                            if (paths.length >= cap) break;
                            paths.push(rel);
                        }
                    }
                    state.updateRegion(sel.id, { projectPaths: paths });
                });
                fh.appendChild(check);

                const label = el("span",
                    "flex:1;cursor:pointer;overflow:hidden;text-overflow:ellipsis;" +
                    "white-space:nowrap;");
                label.textContent =
                    `${open ? "▾" : "▸"} 📁 ${name}  ${countAssigned(child)}/${child.count}`;
                label.title = key;
                label.addEventListener("click", () => {
                    local.expanded[open ? "delete" : "add"](key);
                    renderTree();
                });
                fh.appendChild(label);
                treeBody.appendChild(fh);
                if (open) renderNode(child, key, depth + 1);
            }
            for (const entry of node.files) {
                treeBody.appendChild(fileRow(entry, depth));
            }
        }
        const entries = displayEntries();
        treeTitle.textContent = `Project assets · ${entries.length}`;
        renderNode(buildTree(entries), "", 0);
    }

    function focusSelection() {
        // Click a region -> expand exactly the folders it needs (its category
        // and the canvas-matching resolution levels), collapse the rest.
        const sel = state.selectedRegion();
        if (sel?.assetType) {
            const categories = taskCategories();
            const cat = matchCategory(sel.assetType, categories) ?? sel.assetType;
            local.expanded = new Set([cat]);
            const asset = state.taskAssets.find((a) => a.assetName === sel.name);
            const spec = asset && canvasSpecOf(asset.canvas ?? "");
            if (spec) {
                local.expanded.add(`${cat}/${spec.w}×${spec.h}`);
                local.expanded.add(`${cat}/${spec.w * 2}×${spec.h * 2}`);
            } else {
                // No parseable canvas: open every resolution level under it.
                for (const img of state.images) {
                    const rel = typeof img === "string" ? img : img.rel;
                    const size = typeof img === "string" ? null : { w: img.w, h: img.h };
                    const display = flattenSpritePath(rel, categories, size);
                    const parts = display.split("/");
                    if (parts[0] === cat && parts.length > 2) {
                        local.expanded.add(`${cat}/${parts[1]}`);
                    }
                }
            }
        }
        renderTree();
    }

    renderTree();
    state.on("selection", focusSelection);
    state.on("regions", renderTree);

    // --- 6. pack settings ------------------------------------------------------------
    const packHead = el("div");
    packHead.className = "section-title";
    packHead.style.cursor = "pointer";
    host.appendChild(packHead);
    const packBody = el("div");
    host.appendChild(packBody);
    packHead.addEventListener("click", () => {
        local.packOpen = !local.packOpen;
        renderPack();
    });

    function pickPreset(modelId, prev) {
        const model = MODEL_PRESETS.find((m) => m.id === modelId);
        if (!model) return null;
        const tier = model.tiers.includes(prev?.tier) ? prev.tier
            : model.tiers.includes("2K") ? "2K" : model.tiers[0];
        const ar = model.aspectRatios.includes(prev?.ar) ? prev.ar
            : model.aspectRatios.includes("1:1") ? "1:1" : model.aspectRatios[0];
        return { model: modelId, tier, ar };
    }

    function renderPack() {
        const s = state.settings;
        packHead.textContent = `${local.packOpen ? "▾" : "▸"} Pack settings`;
        packBody.style.display = local.packOpen ? "" : "none";
        packBody.replaceChildren();
        if (!local.packOpen) return;

        // -- model preset --
        packBody.appendChild(el("div",
            "opacity:.5;font-size:10px;text-transform:uppercase;margin:4px 0 2px;" +
            "letter-spacing:.06em;", "Model preset"));

        const modelOptions = MODEL_PRESETS.map((m) => [m.id, m.label]);
        modelOptions.push(["custom", "Custom"]);
        packBody.appendChild(labeledRow("model",
            selectInput(modelOptions, s.preset?.model ?? "custom", (val) => {
                state.updateSettings({
                    preset: val === "custom" ? null : pickPreset(val, s.preset),
                });
            })));

        if (s.preset) {
            const model = MODEL_PRESETS.find((m) => m.id === s.preset.model);
            if (model) {
                packBody.appendChild(labeledRow("resolution",
                    selectInput(model.tiers.map((t) => [t, t]), s.preset.tier, (val) => {
                        state.updateSettings({ preset: { ...s.preset, tier: val } });
                    })));
                packBody.appendChild(labeledRow("aspect",
                    selectInput(model.aspectRatios.map((a) => [a, a]), s.preset.ar,
                        (val) => {
                            state.updateSettings({ preset: { ...s.preset, ar: val } });
                        })));
            }
            const dims = presetDims(s.preset);
            if (dims) {
                packBody.appendChild(el("div", "opacity:.6;font-size:11px;margin:2px 0;",
                    `Native size ${dims.w}×${dims.h}`));
            }
        } else {
            packBody.appendChild(labeledRow("max width",
                numberInput(s.maxWidth, (n) => state.updateSettings({ maxWidth: n }))));
            packBody.appendChild(labeledRow("max height",
                numberInput(s.maxHeight, (n) => state.updateSettings({ maxHeight: n }))));
        }

        // -- layout --
        packBody.appendChild(el("div",
            "opacity:.5;font-size:10px;text-transform:uppercase;margin:8px 0 2px;" +
            "letter-spacing:.06em;", "Layout"));
        packBody.appendChild(labeledRow("algorithm",
            selectInput(ALGORITHMS, s.algorithm,
                (val) => state.updateSettings({ algorithm: val }))));
        packBody.appendChild(labeledRow("Distribute by folder",
            checkboxInput(s.distributeByFolder,
                (v) => state.updateSettings({ distributeByFolder: v }))));
        packBody.appendChild(labeledRow("columns",
            numberInput(s.columns, (n) => state.updateSettings({ columns: n }))));
        packBody.appendChild(labeledRow("padding",
            numberInput(s.padding, (n) => state.updateSettings({ padding: n }))));
        packBody.appendChild(labeledRow("border",
            numberInput(s.border, (n) => state.updateSettings({ border: n }))));
        packBody.appendChild(labeledRow("force square",
            checkboxInput(s.forceSquare,
                (v) => state.updateSettings({ forceSquare: v }))));
        packBody.appendChild(labeledRow("power of two",
            checkboxInput(s.powerOfTwo,
                (v) => state.updateSettings({ powerOfTwo: v }))));
        packBody.appendChild(labeledRow("grid cell",
            numberInput(s.gridCell, (n) => state.updateSettings({ gridCell: n }))));
        packBody.appendChild(labeledRow("snap",
            numberInput(s.snap, (n) => state.updateSettings({ snap: n }))));
        packBody.appendChild(labeledRow("Smart guides",
            checkboxInput(s.smartGuides,
                (v) => state.updateSettings({ smartGuides: v }))));

        // -- background --
        packBody.appendChild(el("div",
            "opacity:.5;font-size:10px;text-transform:uppercase;margin:8px 0 2px;" +
            "letter-spacing:.06em;", "Background"));
        packBody.appendChild(labeledRow("mode",
            selectInput([["transparent", "transparent"], ["color", "color"]],
                s.background?.mode ?? "transparent", (val) => {
                    state.updateSettings({
                        background: { ...s.background, mode: val },
                    });
                })));
        if ((s.background?.mode ?? "transparent") === "color") {
            const color = el("input");
            color.type = "color";
            color.value = s.background?.color ?? "#808080";
            color.addEventListener("change", () => {
                state.updateSettings({
                    background: { ...s.background, color: color.value },
                });
            });
            packBody.appendChild(labeledRow("color", color));
        }
    }
    renderPack();
    state.on("settings", renderPack);

    // --- 7. relayout spec regions on any settings change ------------------------------
    let suppressRelayout = false;
    state.on("settings", () => {
        if (suppressRelayout) return;
        if (state.regions.some((r) => String(r.id).startsWith("region:spec:"))) {
            state.setRegions(rebuildSpecRegions(state));
        }
    });
}
