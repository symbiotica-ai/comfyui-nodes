// ABOUTME: Shared editor state + event bus for the template editor dialog.
// ABOUTME: Single source of truth; modules mutate through methods and re-render on "change".

export const DEFAULT_SETTINGS = {
    algorithm: "shelf", // 'maxrects' | 'shelf' | 'grid'
    preset: { model: "nano-banana-pro", tier: "2K", ar: "1:1" }, // null = custom
    maxWidth: 2048,
    maxHeight: 2048,
    padding: 0,
    border: 0,
    forceSquare: false,
    powerOfTwo: false,
    gridCell: 0,
    distributeByFolder: true,
    columns: 0,
    snap: 0,
    smartGuides: true,
    background: { mode: "color", color: "#808080" }, // 'transparent' | 'color'
};

let regionSeq = 0;

export function createEditorState(init = {}) {
    const listeners = new Map(); // event -> Set<cb>
    const state = {
        // sheet + regions (AtlasRegion dicts, camelCase, normalized 0-1 coords)
        sheetW: init.sheetW ?? 2048,
        sheetH: init.sheetH ?? 2048,
        settings: structuredClone({ ...DEFAULT_SETTINGS, ...(init.settings ?? {}) }),
        regions: init.regions ?? [],
        selectedRegionId: null,          // primary selection (last clicked)
        selectedRegionIds: new Set(),    // full multi-selection
        addRegionMode: false,            // "+ Add region" armed: next drag draws

        // template identity
        templateName: init.templateName ?? "",
        loadedName: init.loadedName ?? "",
        scenePrompt: init.scenePrompt ?? "",
        promptHidden: false,

        // reference data
        refMode: "task", // 'project' | 'task' — which reference tab is active
        root: init.root ?? "",           // project reference folder (abs)
        images: init.images ?? [],       // rel image paths under root
        taskAssets: init.taskAssets ?? [], // [{assetName, category, canvas, prompt, refFiles}]
        refsRoot: init.refsRoot ?? "",   // order refs folder (abs)
        assignments: init.assignments ?? {}, // assetName/regionId -> project rel path

        // viewport
        view: { zoom: 1, panX: 0, panY: 0 },

        // double-click member-edit mode: region whose cells drag individually
        memberEditRegionId: null,

        // events -------------------------------------------------------------
        on(event, cb) {
            if (!listeners.has(event)) listeners.set(event, new Set());
            listeners.get(event).add(cb);
            return () => listeners.get(event)?.delete(cb);
        },
        emit(event, payload) {
            for (const cb of listeners.get(event) ?? []) cb(payload);
            if (event !== "change") for (const cb of listeners.get("change") ?? []) cb(payload);
        },

        // region ops ----------------------------------------------------------
        selectRegion(id) {
            state.selectedRegionId = id;
            state.selectedRegionIds = new Set(id ? [id] : []);
            state.emit("selection");
        },
        toggleSelect(id) {
            // shift-click: add/remove one region from the multi-selection
            const set = state.selectedRegionIds;
            if (set.has(id)) {
                set.delete(id);
                if (state.selectedRegionId === id) {
                    state.selectedRegionId = set.values().next().value ?? null;
                }
            } else {
                set.add(id);
                state.selectedRegionId = id;
            }
            state.emit("selection");
        },
        selectMany(ids) {
            state.selectedRegionIds = new Set(ids);
            state.selectedRegionId = ids[0] ?? null;
            state.emit("selection");
        },
        isSelected(id) {
            return state.selectedRegionIds.has(id);
        },
        selectedRegion() {
            return state.regions.find((r) => r.id === state.selectedRegionId) ?? null;
        },
        setAddRegionMode(on) {
            state.addRegionMode = Boolean(on);
            state.emit("mode");
        },
        updateRegion(id, patch) {
            const r = state.regions.find((x) => x.id === id);
            if (!r) return;
            Object.assign(r, patch);
            state.emit("regions");
        },
        moveRegion(id, x, y) {
            // Members hold absolute sheet coords — carry them with the region.
            const r = state.regions.find((v) => v.id === id);
            if (!r) return;
            const dx = x - r.x, dy = y - r.y;
            r.x = x;
            r.y = y;
            for (const m of r.members ?? []) {
                m.x += dx;
                m.y += dy;
            }
            state.emit("regions");
        },
        setMemberEdit(id) {
            state.memberEditRegionId = id;
            state.emit("regions");
        },
        swapMemberContent(regionId, i, j) {
            // Reorder the ITEMS in a multi-cell region: cells keep their
            // positions, the content mapping swaps — spriteId/flipX on the
            // members plus the index-mapped taskRefs/projectPaths entries.
            const r = state.regions.find((v) => v.id === regionId);
            const m = r?.members;
            if (!m || !m[i] || !m[j]) return;
            for (const key of ["spriteId", "flipX"]) {
                const tmp = m[i][key];
                m[i][key] = m[j][key];
                m[j][key] = tmp;
            }
            const paths = r.taskRefs?.paths;
            if (paths && paths[i] !== undefined && paths[j] !== undefined) {
                [paths[i], paths[j]] = [paths[j], paths[i]];
            }
            const proj = r.projectPaths;
            if (proj && proj[i] !== undefined && proj[j] !== undefined) {
                [proj[i], proj[j]] = [proj[j], proj[i]];
            }
            state.emit("regions");
        },
        scaleRegion(id, factor) {
            // Scale the region and its cells around the region's top-left,
            // clamped inside the sheet (use case: 128px food icons at x2).
            // The cumulative factor persists on the region so repacks and
            // saves keep the user's scale.
            const r = state.regions.find((v) => v.id === id);
            if (!r) return;
            r.scale = (r.scale ?? 1) * factor;
            let w = r.w * factor;
            let h = r.h * factor;
            if (w > 1 || h > 1) {
                const cap = Math.min(1 / r.w, 1 / r.h);
                w = r.w * Math.min(factor, cap);
                h = r.h * Math.min(factor, cap);
            }
            const x = Math.max(0, Math.min(r.x, 1 - w));
            const y = Math.max(0, Math.min(r.y, 1 - h));
            state.resizeRegion(id, { x, y, w, h });
        },
        resizeRegion(id, rect) {
            // Scale member cells proportionally within the region box.
            const r = state.regions.find((v) => v.id === id);
            if (!r) return;
            const old = { x: r.x, y: r.y, w: r.w, h: r.h };
            Object.assign(r, rect);
            const sx = old.w ? rect.w / old.w : 1;
            const sy = old.h ? rect.h / old.h : 1;
            for (const m of r.members ?? []) {
                m.x = rect.x + (m.x - old.x) * sx;
                m.y = rect.y + (m.y - old.y) * sy;
                m.w *= sx;
                m.h *= sy;
            }
            state.emit("regions");
        },
        addRegion(rect) {
            const region = {
                id: `region:${Date.now().toString(36)}-${regionSeq++}`,
                name: "",
                x: rect?.x ?? 0.25, y: rect?.y ?? 0.25,
                w: rect?.w ?? 0.25, h: rect?.h ?? 0.25,
                kind: "object",
                desc: "", text: "",
                zIndex: state.regions.length,
                members: [],
            };
            state.regions.push(region);
            state.selectedRegionId = region.id;
            state.selectedRegionIds = new Set([region.id]);
            state.emit("regions");
            return region;
        },
        deleteRegion(id) {
            state.regions = state.regions.filter((r) => r.id !== id);
            state.regions.forEach((r, i) => { r.zIndex = i; });
            state.selectedRegionIds.delete(id);
            if (state.selectedRegionId === id) {
                state.selectedRegionId =
                    state.selectedRegionIds.values().next().value ?? null;
            }
            state.emit("regions");
        },
        setRegions(regions) {
            state.regions = regions;
            state.selectedRegionId = null;
            state.selectedRegionIds = new Set();
            state.emit("regions");
        },
        restackRegions(orderedIds) {
            const byId = new Map(state.regions.map((r) => [r.id, r]));
            state.regions = orderedIds.map((id, i) => {
                const r = byId.get(id);
                r.zIndex = i;
                return r;
            });
            state.emit("regions");
        },

        // settings ------------------------------------------------------------
        updateSettings(patch) {
            Object.assign(state.settings, patch);
            state.emit("settings");
        },
        setSheetSize(w, h) {
            state.sheetW = w;
            state.sheetH = h;
            state.emit("sheet");
        },
    };
    return state;
}
