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

    // The rail re-renders in place when the event changes, so drop the prior
    // render's state subscriptions first — `on()` re-registers them fresh.
    (host._railUnsub || []).forEach((off) => off());
    host._railUnsub = [];
    const on = (event, cb) => host._railUnsub.push(state.on(event, cb));

    host.replaceChildren();

    // --- -1. event picker ------------------------------------------------------
    // The whole order (Order Read -> Editor) lets you pick which event to build
    // right here. Switching loads that event's assets and clears the canvas —
    // save first. Hidden when a single Event Specs spec feeds the node.
    function selectEvent(feature) {
        const ev = (state.events || []).find((e) => e.feature === feature);
        if (!ev) return;
        state.feature = feature;
        state.taskAssets = (ev.assets || [])
            .filter((a) => a.assetName)
            .map((a) => ({
                assetName: a.assetName, category: a.category, canvas: a.canvas,
                prompt: a.prompt, refFiles: a.refFiles || [],
            }));
        state.categoryFilter = null;
        state.setRegions([]);            // a new event is a fresh canvas
        opts.onEventChange?.(feature);   // persist the choice on the node
        opts.rerenderRail?.();           // rebuild the rail for the new assets
    }

    if ((state.events || []).length > 1) {
        const evWrap = el("div", "margin:2px 0 8px;");
        evWrap.appendChild(el("div", "opacity:.55;font-size:11px;margin-bottom:3px;",
                              "Event"));
        const options = state.events.map((e) => [e.feature,
            `${e.feature}${e.eventName ? ` — ${e.eventName}` : ""}`]);
        const cur = state.events.some((e) => e.feature === state.feature)
            ? state.feature : state.events[0].feature;
        evWrap.appendChild(selectInput(options, cur, selectEvent));
        host.appendChild(evWrap);
    }

    // --- 0. asset-type filter --------------------------------------------------
    // Chips gate everything below: pick a type and Prefill / the canvas / Save
    // all use only that type. "All" (null filter) is the whole order.
    const filterCats = orderCategories();
    if (filterCats.length > 1) {
        const filterWrap = el("div", "margin:2px 0 8px;");
        filterWrap.appendChild(el("div", "opacity:.55;font-size:11px;margin-bottom:3px;",
                                  "Asset type"));
        const chipRow = el("div", "display:flex;flex-wrap:wrap;gap:4px;");
        const chips = [];
        function paintChips() {
            for (const { btn, value } of chips) {
                const on = state.categoryFilter === value;
                btn.style.background = on ? "#3a5bd0" : "#1e1e1e";
                btn.style.borderColor = on ? "#5a7bf0" : "#3a3a3a";
                btn.style.color = on ? "#fff" : "#bbb";
            }
        }
        for (const [label, value] of [["All", null], ...filterCats.map((c) => [c, c])]) {
            const btn = el("button",
                "padding:2px 10px;font-size:11px;border:1px solid #3a3a3a;" +
                "border-radius:12px;cursor:pointer;background:#1e1e1e;color:#bbb;",
                label);
            btn.addEventListener("click", () => {
                state.categoryFilter = value;
                state.emit("categoryFilter");
                paintChips();
                // Switching type is a different region set, so relay the canvas
                // to it immediately — the point of the chip is to SEE that type.
                runPrefill();
                syncActionButtons();
            });
            chips.push({ btn, value });
            chipRow.appendChild(btn);
        }
        paintChips();
        filterWrap.appendChild(chipRow);
        host.appendChild(filterWrap);
    }

    // --- 1. prefill ------------------------------------------------------------
    // Full reset: drop everything, lay out the current filter's assets fresh.
    function runPrefill() {
        const assets = taskAssetsWithRefs();
        if (!assets.length) return;
        const out = prefillRegions(assets, state.sheetW, state.sheetH, undefined,
                                   state.settings);
        state.setRegions(out.regions);
    }

    const prefillBtn = el("button", "width:100%;margin-bottom:6px;", "⟳ Prefill from specs");
    prefillBtn.className = "primary";
    prefillBtn.addEventListener("click", runPrefill);
    host.appendChild(prefillBtn);

    // Rearrange: relayout the regions ALREADY on the canvas under the pack
    // settings, keeping their edits and scales. Unlike Prefill it never brings
    // a deleted region back — delete two of five, rearrange the other three.
    const repackBtn = el("button", "width:100%;margin-bottom:6px;", "⟲ Rearrange regions");
    repackBtn.title = "Redistribute the regions on the canvas under the current "
        + "pack settings. Deleted regions stay deleted — use Prefill from specs "
        + "to start over from the order.";
    repackBtn.addEventListener("click", () => {
        state.setRegions(rebuildSpecRegions(state));
    });
    host.appendChild(repackBtn);

    // Prefill follows the filter (only that type's assets); Rearrange follows
    // the canvas (are there spec regions to move). Re-run on filter/region
    // change so a chip click or an edit updates the buttons live.
    function syncActionButtons() {
        prefillBtn.disabled = taskAssetsWithRefs().length === 0;
        repackBtn.disabled = !state.regions.some(
            (r) => String(r.id).startsWith("region:spec:"));
    }
    syncActionButtons();
    on("regions", syncActionButtons);

    // Assets that can be laid out: named, with refs. `category` narrows to one
    // asset type; null (the default) keeps them all. Prefill and the canvas
    // read the live state.categoryFilter, so picking a chip and pressing
    // Prefill lays out just that type.
    function taskAssetsWithRefs(category = state.categoryFilter) {
        return state.taskAssets.filter(
            (a) => a.assetName && (a.refFiles?.length ?? 0) > 0
                   && (!category || a.category === category));
    }

    function orderCategories() {
        return [...new Set(taskAssetsWithRefs(null).map((a) => a.category)
                                                   .filter(Boolean))];
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

    // "Save all types": one task sheet per asset type plus the whole order,
    // auto-named <base>-all / <base>-<type>. Each is laid out fresh from that
    // type's assets and exported in task mode (client art, no project ref).
    if (orderCategories().length > 1) {
        const saveAllBtn = el("button", "width:100%;margin:2px 0 6px;",
                              "💾 Save all types (separate sheets)");
        saveAllBtn.title = "Write one task sheet per asset type — food, "
            + "decorations, wallpaper — and one for the whole order, named from "
            + "the box above.";
        saveAllBtn.addEventListener("click", async () => {
            if (local.saving) return;
            const base = slugify(nameInput.value.trim()) || slugify(state.feature)
                         || state.loadedName || "order";
            const jobs = [["all", null],
                          ...orderCategories().map((c) => [slugify(c), c])];
            local.saving = true;
            saveAllBtn.disabled = true;
            saveBtn.disabled = true;
            saveError.style.color = "#e66";
            saveError.style.display = "none";
            const prevRegions = state.regions;
            const prevFilter = state.categoryFilter;
            const saved = [];
            try {
                for (const [suffix, cat] of jobs) {
                    const assets = taskAssetsWithRefs(cat);
                    if (!assets.length) continue;
                    const { regions } = prefillRegions(
                        assets, state.sheetW, state.sheetH, undefined, state.settings);
                    state.setRegions(regions);
                    const res = await opts.saveTemplate(
                        `${base}-${suffix}`, { refMode: "task", bindNode: false });
                    saved.push(res.name);
                }
                if (!saved.length) throw new Error("no assets with references to save");
            } catch (e) {
                saveError.textContent = `Save all failed: ${e.message ?? e}`;
                saveError.style.display = "";
            } finally {
                state.setRegions(prevRegions);
                state.categoryFilter = prevFilter;
                state.emit("template");
                local.saving = false;
                saveAllBtn.disabled = false;
                saveBtn.disabled = false;
            }
            if (saved.length) {
                saveError.style.color = "#6c6";
                saveError.style.display = "";
                saveError.textContent = `Saved ${saved.length}: ${saved.join(", ")}`;
            }
        });
        host.appendChild(saveAllBtn);
    }

    const loadPanel = el("div",
        "border:1px solid #333;border-radius:6px;margin:4px 0;padding:4px;" +
        "background:#141414;max-height:180px;overflow-y:auto;display:none;");
    host.appendChild(loadPanel);

    function syncTemplateRow() {
        nameInput.placeholder = state.loadedName
            ? `${state.loadedName} (current)`
            : (slugify(state.feature) || "template name");
    }
    syncTemplateRow();
    on("template", syncTemplateRow);

    saveBtn.addEventListener("click", async () => {
        if (local.saving) return;
        const typed = nameInput.value.trim();
        const name = typed ? slugify(typed) : (state.loadedName || slugify(state.feature));
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
        // Assignment targets: the whole multi-selection (checking an asset or
        // folder assigns it to every selected region at once).
        const targets = state.regions.filter(
            (r) => state.isSelected(r.id) || r.id === sel?.id);
        const px = THUMB_SIZES[local.thumb];

        function applyToTargets(fn) {
            for (const region of targets) fn(region);
        }

        function fileRow(entry, depth) {
            const rel = entry.rel;
            const row = el("div",
                `display:flex;align-items:center;gap:6px;padding:1px 0 1px ${12 * depth}px;`);
            const check = el("input");
            check.type = "checkbox";
            check.checked = targets.length > 0 &&
                targets.every((r) => r.projectPaths?.includes(rel));
            check.disabled = !targets.length;
            check.addEventListener("change", () => {
                // Applies to EVERY selected region. Multi-cell regions take one
                // sprite per cell (click order, capped at the cell count);
                // checking beyond the cap replaces the last pick.
                applyToTargets((region) => {
                    const cap = Math.max(1, region.members?.length ?? 1);
                    let paths = (region.projectPaths ?? []).filter((p) => p !== rel);
                    if (check.checked) {
                        if (paths.length >= cap) paths = paths.slice(0, cap - 1);
                        paths.push(rel);
                    }
                    state.updateRegion(region.id, { projectPaths: paths });
                });
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
                const partial = nChecked > 0 && nChecked < rels.length;
                const check = el("input");
                check.type = "checkbox";
                check.checked = nChecked > 0 && nChecked === rels.length;
                check.indeterminate = partial;
                check.disabled = !targets.length;
                check.addEventListener("click", (e) => e.stopPropagation());
                check.addEventListener("change", () => {
                    // A partially-assigned folder clears on click (the browser
                    // flips indeterminate -> checked, which read as a no-op).
                    // Applies to every selected region: check REPLACES each
                    // region's assignment with this folder's sprites.
                    const clearing = partial || !check.checked;
                    applyToTargets((region) => {
                        const cap = Math.max(1, region.members?.length ?? 1);
                        const paths = clearing
                            ? (region.projectPaths ?? []).filter((p) => !rels.includes(p))
                            : rels.slice(0, cap);
                        state.updateRegion(region.id, { projectPaths: paths });
                    });
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
    on("selection", focusSelection);
    on("regions", renderTree);

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
            : model.tiers.includes("1K") ? "1K" : model.tiers[0];
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
    on("settings", renderPack);

    // --- 7. relayout spec regions on any settings change ------------------------------
    let suppressRelayout = false;
    on("settings", () => {
        if (suppressRelayout) return;
        if (state.regions.some((r) => String(r.id).startsWith("region:spec:"))) {
            state.setRegions(rebuildSpecRegions(state));
        }
    });
}
