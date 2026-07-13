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
        selectedRegionId: null,

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
            state.emit("selection");
        },
        selectedRegion() {
            return state.regions.find((r) => r.id === state.selectedRegionId) ?? null;
        },
        updateRegion(id, patch) {
            const r = state.regions.find((x) => x.id === id);
            if (!r) return;
            Object.assign(r, patch);
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
            state.emit("regions");
            return region;
        },
        deleteRegion(id) {
            state.regions = state.regions.filter((r) => r.id !== id);
            state.regions.forEach((r, i) => { r.zIndex = i; });
            if (state.selectedRegionId === id) state.selectedRegionId = null;
            state.emit("regions");
        },
        setRegions(regions) {
            state.regions = regions;
            state.selectedRegionId = null;
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
