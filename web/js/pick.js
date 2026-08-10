// ABOUTME: Symbiotica Pick node UI — the asset's own render folder listed on the
// ABOUTME: node body as numbered thumbnails, ticked to choose which files travel
// ABOUTME: downstream. It holds nothing: every tile is a file already on disk.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { registerSymbioticaExtension } from "./register.js";
import { HUB, injectHubStyles, ghostButtonCss } from "./hub_theme.js";
import { attachHoverZoom, el, emptyState, errorLine, hideHoverZoom }
    from "./browser_chrome.js";

const NODE_CLASS = "SymbioticaPick";
// Widgets this node gained after graphs were already saved, with the value each
// falls back to. A saved workflow carries one value per widget it knew about,
// applied by position, so anything appended since comes back unset.
const APPENDED_WIDGETS = [["show", "approved"], ["edit_selection", ""]];
const MIN_NODE_W = 340;
const PANEL_MIN = 44;        // an empty picker still shows its own message
const DEFAULT_NODE_H = 460;  // only for a node that has never been given a height
const SIZES = { S: 64, M: 108, L: 184 };
const DEFAULT_SIZE = "S";

const widgetOf = (node, name) => node.widgets?.find((w) => w.name === name);

// Keep the /api/ prefix: ComfyUI mirrors custom routes under /api/ locally AND
// the Modal gateway proxies /api/* only, so a root-level /symbiotica/* would
// blank every thumbnail there.
const thumbUrl = (path, px) => api.apiURL(
    `/symbiotica/pick-thumb?px=${px}&path=${encodeURIComponent(path)}`);
const fullUrl = (path) => api.apiURL(
    `/symbiotica/local-image?path=${encodeURIComponent(path)}`);

async function fetchJson(url, options) {
    const res = await api.fetchApi(url, options);
    if (!res.ok) throw new Error((await res.json().catch(() => ({})))?.error ?? res.statusText);
    return res.json();
}

// `single` is for editing: you edit the image you are working on, so ticking
// replaces the previous pick instead of adding to it.
const isSingle = (node) =>
    (widgetOf(node, "mode")?.value?.trim?.() || "multiple") === "single";

// The ticks live on the `selection` widget as a JSON array of FILE NAMES, so
// they are saved with the workflow: reopening a graph shows the same picks the
// run was queued with. Names rather than positions, because a new render
// landing in the folder shifts every position after it and would silently
// re-point every tick at its neighbour.
function readSet(node, widget) {
    try {
        const raw = JSON.parse(widgetOf(node, widget)?.value || "[]");
        return new Set(Array.isArray(raw) ? raw.map(String) : []);
    } catch {
        return new Set();
    }
}

function writeSet(node, widget, values) {
    const w = widgetOf(node, widget);
    if (w) w.value = JSON.stringify([...values]);
    node.setDirtyCanvas?.(true, true);
}

const readTicks = (node) => readSet(node, "selection");
const writeTicks = (node, ticks) => writeSet(node, "selection", ticks);
// The ✎ set: files travelling out the `for_edit` output. Its own widget so
// approving and sending to edit are independent fates, both saved with the
// workflow.
const readEdits = (node) => readSet(node, "edit_selection");
const writeEdits = (node, edits) => writeSet(node, "edit_selection", edits);

function thumbSize(node) {
    const key = node.properties?.symPickThumb;
    return SIZES[key] ? key : DEFAULT_SIZE;
}

function pickPanel(node) {
    injectHubStyles();

    // height:100% — the layout gives the widget a box, this fills it, and the
    // grid scrolls inside. Sizing to content instead is what used to drive the
    // node's height.
    const container = el("div", "box-sizing:border-box;width:100%;height:100%;"
        + "overflow-y:auto;overflow-x:hidden;");
    // ComfyUI sizes the container from computeSize, so its scrollHeight only
    // echoes its own box. Measure this inner list — its natural height IS the
    // content height.
    const list = el("div", `padding:2px;font:11px ${HUB.font};color:${HUB.ink};`);
    container.appendChild(list);
    container.addEventListener("wheel", (e) => e.stopPropagation(), { passive: true });

    // THE NODE'S HEIGHT IS HIS, AND IT MUST BE DRAGGABLE BOTH WAYS.
    //
    // LiteGraph derives a node's MINIMUM height by summing its widgets, and
    // for each widget it prefers `computeSize` over `computeLayoutSize`:
    //
    //     if (w.computeSize) t += w.computeSize(width)[1]
    //     else if (w.computeLayoutSize) t += w.computeLayoutSize(node).minHeight
    //
    // So a `computeSize` that answers with the space currently below the panel
    // makes the minimum equal the current height, and the node can be dragged
    // taller but never shorter. That is what "i am pulling on the corner and
    // it cannot be made smaller" was, here and in the prompt editor.
    //
    // The panel therefore declares a small CONSTANT floor and no computeSize
    // at all: the layout hands it whatever is left of the node's body, the
    // element fills that box, and the grid scrolls inside it.
    const panelWidget = node.addDOMWidget("pick_panel", "sym_pick", container, {
        serialize: false,
        hideOnZoom: true,
        getMinHeight: () => PANEL_MIN,
    });
    // The `serialize` in those options is a DIFFERENT flag: it governs the API
    // prompt. Persistence in the workflow is `serialize` ON THE WIDGET, which
    // `LGraphNode.configure` and `.serialize` are the ones to read, and
    // addDOMWidget never copies the option onto the widget. Left alone the
    // panel takes a slot in `widgets_values` and contributes an empty string —
    // a DOM widget with no `getValue` reads as "" — so the next widget added to
    // this node inherits that empty string on load and its combo refuses the
    // queue. Setting it here is what keeps the saved values to the real widgets.
    if (panelWidget) panelWidget.serialize = false;
    // Redraw, never resize. The only thing this may change is a node so narrow
    // that a tile cannot fit, and a node that has never been given a height.
    const refit = () => requestAnimationFrame(() => {
        if (node.size[0] < MIN_NODE_W) {
            node.setSize?.([MIN_NODE_W, node.size[1]]);
        }
        node.setDirtyCanvas?.(true, true);
    });
    node.size[0] = Math.max(node.size[0], MIN_NODE_W);
    // A starting height for a node that has never had one. Never a floor: a
    // graph reopening keeps whatever height it was saved at, and dragging goes
    // all the way down to the widgets plus PANEL_MIN.
    if (!node.size[1] || node.size[1] < PANEL_MIN) {
        node.size[1] = DEFAULT_NODE_H;
    }

    let images = [];
    let folder = "";
    // Listing another picker's approvals rather than a folder of its own.
    let shortlist = false;
    let error = "";
    let notice = "";
    let loading = false;
    // A first load can land before the graph has finished configuring, while
    // the node still carries a placeholder id — and the server answers by node
    // id, so that reads as "no folder". Retry a few times rather than sit on
    // that answer forever, with the images right there on disk.
    let loads = 0;
    let loadedOk = false;

    async function load(explicitFolder = "") {
        loading = true;
        loads += 1;
        render();
        try {
            const q = new URLSearchParams({ node_id: String(node.id) });
            if (explicitFolder) q.set("folder", explicitFolder);
            const data = await fetchJson(`/symbiotica/pick-list?${q.toString()}`);
            images = Array.isArray(data.images) ? data.images : [];
            folder = data.folder || "";
            shortlist = Boolean(data.shortlist);
            loadedOk = images.length > 0;
            error = "";
        } catch (e) {
            error = e.message || "could not list that folder";
        } finally {
            loading = false;
            render();
        }
        if (!loadedOk && !error && loads < 4) {
            setTimeout(() => { if (!loadedOk) load(explicitFolder); }, 400 * loads);
        }
    }
    node._symReloadPick = load;
    node._symPickNote = (text) => { notice = String(text || ""); render(); };

    const stageOf = () => widgetOf(node, "stage")?.value?.trim?.() || "";

    // A stage names a different folder, so the list has to be fetched again.
    const stageWidget = widgetOf(node, "stage");
    if (stageWidget) {
        const previous = stageWidget.callback;
        stageWidget.callback = function () {
            previous?.apply(this, arguments);
            load();
        };
    }
    const oneAtATime = () => isSingle(node);

    // Batch selection: which tiles the bar's buttons act on. Canvas-only —
    // a half-made selection is not workflow state worth saving.
    let checked = new Set();

    function toggle(name) {
        const ticks = readTicks(node);
        if (ticks.has(name)) {
            // Clicking the chosen one clears it, which is how you change your
            // mind without having to pick something else first.
            ticks.delete(name);
        } else if (oneAtATime()) {
            // Replace rather than add — including ticks left over from another
            // asset, which are not travelling anywhere either.
            ticks.clear();
            ticks.add(name);
        } else {
            ticks.add(name);
        }
        writeTicks(node, ticks);
        render();
    }

    // One fate per action. Approve and edit are independent sets — a file can
    // be both (approved for export AND sent for a variant edit) — so each
    // button toggles its own set and never touches the other.
    function assign(names, fate) {
        if (fate === "approve") {
            const ticks = readTicks(node);
            const allIn = names.every((n) => ticks.has(n));
            for (const n of names) allIn ? ticks.delete(n) : ticks.add(n);
            if (oneAtATime() && !allIn) {
                const keep = names[names.length - 1];
                ticks.clear();
                ticks.add(keep);
            }
            writeTicks(node, ticks);
        } else if (fate === "edit") {
            const edits = readEdits(node);
            const allIn = names.every((n) => edits.has(n));
            for (const n of names) allIn ? edits.delete(n) : edits.add(n);
            writeEdits(node, edits);
        }
        render();
    }

    // The only control that touches the disk: files move one folder deeper,
    // never away. Both sets forget a discarded file so no tick reads as
    // "missing" forever.
    async function discard(names) {
        if (!names.length) return;
        try {
            const res = await fetchJson("/symbiotica/pick-discard", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ node_id: String(node.id),
                                       names }),
            });
            const dropped = new Set(names);
            writeTicks(node, new Set([...readTicks(node)]
                .filter((t) => !dropped.has(t))));
            writeEdits(node, new Set([...readEdits(node)]
                .filter((t) => !dropped.has(t))));
            checked = new Set([...checked].filter((t) => !dropped.has(t)));
            notice = `${(res.discarded || []).length} moved to discarded/`;
        } catch (e) {
            error = e.message || "could not discard those";
        }
        await load();
    }

    // --- header ------------------------------------------------------------
    function renderHead(ticks, edits) {
        const bar = el("div",
            `display:flex;align-items:center;gap:6px;padding:2px 2px 4px;color:${HUB.inkSubtle};`);
        const here = images.filter((i) => ticks.has(i.id)).length;
        const editing = images.filter((i) => edits.has(i.id)).length;
        bar.append(el("span", "flex:1;min-width:0;overflow:hidden;"
            + "text-overflow:ellipsis;white-space:nowrap;",
            images.length
                ? `${images.length} in folder · ${here} ✓`
                  + (editing ? ` · ${editing} ✎` : "")
                : `nothing listed yet (node ${node.id})`));

        // A tick whose file is no longer in the folder is not sent on, and is
        // invisible here — saying so beats a count that does not add up.
        const missing = ticks.size - here;
        if (missing > 0) {
            const drop = el("button", ghostButtonCss + "padding:1px 7px;flex:none;",
                            `${missing} missing ✕`);
            drop.className = "sym-btn";
            drop.title = `${missing} tick(s) name files that are not in this `
                + "folder, so they are not sent on. Click to forget them.";
            drop.addEventListener("pointerdown", (e) => e.stopPropagation());
            drop.addEventListener("click", () => {
                const present = new Set(images.map((i) => i.id));
                writeTicks(node, new Set([...ticks].filter((t) => present.has(t))));
                render();
            });
            bar.appendChild(drop);
        }

        // What this picker is looking at, and how many it takes. Both are
        // widgets, but a widget is a thing to read; a chip is a thing you see.
        const label = shortlist ? "shortlist" : (stageOf() || "renders");
        const chip = el("div",
            `flex:none;padding:1px 6px;border-radius:3px;font:10px ${HUB.font};`
            + `background:${HUB.surface1};color:${HUB.inkSubtle};`
            + `border:1px solid ${HUB.hairline};`,
            oneAtATime() ? `${label} · one` : label);
        chip.title = (shortlist
            ? "listing exactly what the picker upstream approved"
            : `listing ${stageOf() ? `this asset's \`${stageOf()}\` step`
                                   : "this asset's own renders"}`)
            + (oneAtATime()
                ? "\nsingle: ticking replaces the previous pick"
                : "");
        bar.appendChild(chip);

        for (const key of Object.keys(SIZES)) {
            const b = el("button", ghostButtonCss + "padding:1px 6px;flex:none;"
                + (thumbSize(node) === key ? `border-color:${HUB.accent};color:${HUB.ink};` : ""),
                         key);
            b.className = "sym-btn";
            b.title = `${SIZES[key]}px thumbnails`;
            b.addEventListener("pointerdown", (e) => e.stopPropagation());
            b.addEventListener("click", () => {
                node.properties = node.properties ?? {};
                node.properties.symPickThumb = key;
                render();
            });
            bar.appendChild(b);
        }

        const reload = el("button", ghostButtonCss + "padding:1px 6px;flex:none;", "⟳");
        reload.className = "sym-btn";
        reload.title = "Re-read the folder";
        reload.addEventListener("pointerdown", (e) => e.stopPropagation());
        reload.addEventListener("click", () => load());
        bar.appendChild(reload);

        if (ticks.size || edits.size) {
            const clear = el("button", ghostButtonCss + "padding:1px 8px;flex:none;",
                             "untick all");
            clear.className = "sym-btn";
            clear.title = "Clear every ✓ and ✎. The images on disk are untouched.";
            clear.addEventListener("pointerdown", (e) => e.stopPropagation());
            clear.addEventListener("click", () => {
                writeTicks(node, new Set());
                writeEdits(node, new Set());
                render();
            });
            bar.appendChild(clear);
        }
        return bar;
    }

    // --- batch bar ----------------------------------------------------------
    // Appears once anything is checkbox-selected: one row, three fates, each
    // acting on every checked tile at once. Discard keeps its two-click arm —
    // it is still the only control that touches the disk.
    function renderBatchBar() {
        const names = images.filter((i) => checked.has(i.id)).map((i) => i.id);
        const bar = el("div",
            `display:flex;align-items:center;gap:6px;padding:3px 2px 4px;`
            + `border-top:1px solid ${HUB.hairline};color:${HUB.ink};`);
        bar.append(el("span", "flex:none;", `${names.length} selected`));

        const make = (label, title, fn, accent) => {
            const b = el("button", ghostButtonCss + "padding:1px 9px;flex:none;"
                + (accent ? `border-color:${HUB.accent};color:${HUB.ink};` : ""),
                         label);
            b.className = "sym-btn";
            b.title = title;
            b.addEventListener("pointerdown", (e) => e.stopPropagation());
            b.addEventListener("click", fn);
            return b;
        };

        bar.appendChild(make(`✓ approve ${names.length}`,
            "Toggle the checked tiles in the approved set — they flow out "
            + "`picked` to the final export step.",
            () => assign(names, "approve")));
        bar.appendChild(make(`✎ edit ${names.length}`,
            "Toggle the checked tiles in the edit set — they flow out "
            + "`for_edit` to the edit lane.",
            () => assign(names, "edit")));
        const armed = node._symDiscardArmed;
        bar.appendChild(make(
            armed ? `✕ discard ${names.length}?` : `✕ discard ${names.length}`,
            "Move the checked files into `discarded/` under this folder. They "
            + "leave the grid, not the disk — drag them back to undo.",
            async () => {
                if (!node._symDiscardArmed) {
                    node._symDiscardArmed = true;
                    render();
                    setTimeout(() => {
                        if (node._symDiscardArmed) {
                            node._symDiscardArmed = false;
                            render();
                        }
                    }, 4000);
                    return;
                }
                node._symDiscardArmed = false;
                await discard(names);
            }, armed));
        bar.appendChild(make("clear",
            "Drop the checkbox selection. Nothing else changes.",
            () => { checked = new Set(); render(); }));
        return bar;
    }

    // --- grid --------------------------------------------------------------
    // Files saved as `<asset>_<role>_00001_.png` carry their role in the
    // name, so the grid can row itself by it — one row per role makes "one of
    // each, none twice" readable at a glance. The group key is the stem minus
    // ComfyUI's counter; the label is what the keys do not share.
    const groupOf = (name) =>
        name.replace(/\.[^.]+$/, "").replace(/_\d+_?$/, "");

    // The edit set's own colour, one step warmer than the approve accent so a
    // tile carrying both reads as both.
    const EDIT_HUE = "#e0a84a";

    function renderRow(ticks, edits, rowImages) {
        const px = SIZES[thumbSize(node)];
        const grid = el("div", "display:flex;flex-wrap:wrap;gap:4px;"
            + "width:100%;box-sizing:border-box;");
        for (const image of rowImages) {
            const on = ticks.has(image.id);
            const editing = edits.has(image.id);
            const isChecked = checked.has(image.id);
            const border = on ? HUB.accent
                : editing ? EDIT_HUE
                : isChecked ? HUB.inkSubtle : HUB.hairline;
            const cell = el("div",
                `position:relative;width:${px}px;height:${px}px;flex:none;`
                + `border:2px solid ${border};`
                + `border-radius:4px;overflow:hidden;cursor:pointer;`
                + `background:${HUB.surface1};box-sizing:border-box;`);
            cell.className = "sym-pick-cell";
            const caption = `${image.index} · ${image.name}`
                + (image.w ? ` · ${image.w}×${image.h}` : "");
            // No `title`: the browser's own tooltip lands a second later, on
            // top of the render being judged, saying what the preview's own
            // caption already says. The frame is the tooltip.

            const img = el("img", "width:100%;height:100%;object-fit:cover;"
                + "display:block;pointer-events:none;");
            img.src = thumbUrl(image.path, px * 2);
            img.loading = "lazy";
            cell.appendChild(img);

            // The number is how a pick is named out loud — "take 3, 7 and 12".
            const badge = el("div",
                `position:absolute;left:0;top:0;min-width:14px;padding:0 3px;`
                + `font:10px ${HUB.font};text-align:center;`
                + `background:${on ? HUB.accent : "rgba(0,0,0,.55)"};`
                + `color:${on ? "#000" : HUB.ink};border-radius:0 0 4px 0;`,
                String(image.index));
            cell.appendChild(badge);
            if (editing) {
                cell.appendChild(el("div",
                    `position:absolute;left:0;bottom:0;padding:0 3px;`
                    + `font:10px ${HUB.font};background:${EDIT_HUE};`
                    + "color:#000;border-radius:0 4px 0 0;", "✎"));
            }

            // Batch checkbox, its own click target: selecting for a batch
            // action must not toggle the approve tick underneath.
            const box = el("div",
                `position:absolute;right:0;top:0;width:15px;height:15px;`
                + `font:11px/13px ${HUB.font};text-align:center;`
                + `background:${isChecked ? HUB.ink : "rgba(0,0,0,.55)"};`
                + `color:${isChecked ? "#000" : HUB.inkSubtle};`
                + "border-radius:0 0 0 4px;",
                isChecked ? "✔" : "☐");
            box.title = "select for a batch action (approve / edit / discard "
                + "several at once)";
            box.addEventListener("pointerdown", (e) => e.stopPropagation());
            box.addEventListener("click", (e) => {
                e.stopPropagation?.();
                isChecked ? checked.delete(image.id) : checked.add(image.id);
                render();
            });
            cell.appendChild(box);

            // Per-tile fates, on hover so the render stays the thing looked
            // at. The strip is the same three verbs as the batch bar.
            const acts = el("div", "position:absolute;left:0;right:0;bottom:0;"
                + "display:none;justify-content:space-around;"
                + "background:rgba(0,0,0,.62);padding:1px 0;");
            acts.className = "sym-pick-acts";
            const act = (glyph, title, fn, active, hue) => {
                const b = el("div",
                    `flex:1;text-align:center;font:12px ${HUB.font};`
                    + "cursor:pointer;"
                    + `color:${active ? (hue || HUB.accent) : HUB.ink};`,
                    glyph);
                b.title = title;
                b.addEventListener("pointerdown", (e) => e.stopPropagation());
                b.addEventListener("click", (e) => { e.stopPropagation?.(); fn(); });
                return b;
            };
            acts.appendChild(act("✓",
                on ? "approved — click to unapprove"
                   : "approve: send out `picked` to the final export step",
                () => assign([image.id], "approve"), on));
            acts.appendChild(act("✎",
                editing ? "marked for edit — click to unmark"
                        : "send out `for_edit` to the edit lane",
                () => assign([image.id], "edit"), editing, EDIT_HUE));
            acts.appendChild(act("✕",
                "discard: move this file into `discarded/` (leaves the grid, "
                + "not the disk)",
                () => discard([image.id]), false));
            cell.appendChild(acts);

            // S tiles are 64px: too small to tell two renders apart, which is
            // the whole job of this node. Resting on one floats it big beside
            // the grid, off the same resize route the tile came from.
            attachHoverZoom(cell, () => ({
                w: image.w,
                h: image.h,
                label: caption,
                hint: "click to tick · double-click to open full size",
                placeholder: img.src,   // already fetched: the frame fills now
                src: (zoomPx) => thumbUrl(image.path, zoomPx),
            }));
            cell.addEventListener("mouseenter",
                () => { acts.style.display = "flex"; });
            cell.addEventListener("mouseleave",
                () => { acts.style.display = "none"; });

            cell.addEventListener("pointerdown", (e) => e.stopPropagation());
            cell.addEventListener("click", () => toggle(image.id));
            cell.addEventListener("dblclick", (e) => {
                e.stopPropagation();
                window.open(fullUrl(image.path), "_blank");
            });
            grid.appendChild(cell);
        }
        return grid;
    }

    function renderGrid(ticks, edits) {
        const groups = new Map();
        for (const image of images) {
            const key = groupOf(image.name);
            if (!groups.has(key)) groups.set(key, []);
            groups.get(key).push(image);
        }
        if (groups.size <= 1) return renderRow(ticks, edits, images);

        // The shared start of every key is the asset's own name — the label
        // is the part that differs, which is the role.
        const keys = [...groups.keys()];
        let shared = keys[0];
        for (const key of keys) {
            while (shared && !key.startsWith(shared)) {
                shared = shared.slice(0, -1);
            }
        }
        // Rows are for the ROLES OF ONE ASSET — `<asset>_<role>_00001_.png`.
        // A folder of unrelated names has no asset in common, so every file
        // became its own row: a dataset folder of 57 references drew as 57
        // one-tile rows labelled with their own filenames, which is a list
        // pretending to be a grid. Row only when every key is the shared stem
        // or a `_`-suffixed extension of it; otherwise the names merely start
        // alike ("Baking Class", "Baking With Mom Statue") and the grid is the
        // honest layout.
        const stem = shared.replace(/_+$/, "");
        const rowed = stem && keys.every(
            (key) => key === stem || key.startsWith(`${stem}_`));
        if (!rowed) return renderRow(ticks, edits, images);

        const wrap = el("div", "width:100%;box-sizing:border-box;");
        for (const [key, rowImages] of groups) {
            const label = key.slice(stem.length).replace(/^_/, "") || "base";
            const here = rowImages.filter((i) => ticks.has(i.id)).length;
            wrap.appendChild(el("div",
                `padding:5px 3px 2px;font:10px ${HUB.font};`
                + `color:${here ? HUB.ink : HUB.inkSubtle};`,
                `${label} · ${rowImages.length}${here ? ` · ${here} ✓` : ""}`));
            wrap.appendChild(renderRow(ticks, edits, rowImages));
        }
        return wrap;
    }

    function render() {
        const ticks = readTicks(node);
        const edits = readEdits(node);
        // The tile a preview belongs to is about to be thrown away — a frame
        // left up would be floating beside nothing.
        hideHoverZoom();
        list.replaceChildren();
        // The counts, the sizes and the folder stay put while the grid moves
        // under them: with 85 thumbnails the controls are otherwise a scroll
        // away from the images they act on, and the folder a picker landed on
        // is the thing worth being able to read at any time.
        const top = el("div", "position:sticky;top:0;z-index:2;"
            + `background:${HUB.surface1};padding-bottom:2px;`);
        top.appendChild(renderHead(ticks, edits));
        if (checked.size) top.appendChild(renderBatchBar());
        if (folder) {
            top.appendChild(el("div",
                `color:${HUB.inkTertiary};font:10px ${HUB.font};padding:0 3px 3px;`
                + "overflow:hidden;text-overflow:ellipsis;white-space:nowrap;",
                folder));
        }
        if (error) top.appendChild(errorLine(error));
        if (notice) {
            top.appendChild(el("div",
                `color:${HUB.inkTertiary};font:10px ${HUB.font};padding:0 3px 3px;`,
                notice));
        }
        list.appendChild(top);
        if (loading && !images.length) {
            list.appendChild(emptyState("reading…"));
        } else if (!images.length) {
            list.appendChild(emptyState(shortlist
                ? "the picker above has nothing ticked yet — approve some "
                  + "there and they appear here"
                : "queue this node once — it works out which folder this "
                  + "asset's images are in from the wires, then lists them "
                  + "here"));
        } else {
            list.appendChild(renderGrid(ticks, edits));
        }
        refit();
    }

    render();
    load();
}

registerSymbioticaExtension(app, {
    name: "symbiotica.pick",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== NODE_CLASS) return;

        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            // Canvas state: collapse it (a bare .hidden is ignored by the
            // classic canvas widgets).
            for (const name of ["selection", "view", "edit_selection"]) {
                const w = widgetOf(this, name);
                if (w) { w.hidden = true; w.computeSize = () => [0, -4]; }
            }
            // Shown as `input_path`: this node READS that path — "it doesn't
            // make any sense that an input path is called save when the node
            // doesn't save". The id stays `save_path` so saved graphs, API
            // payloads and the schema keep loading untouched; only what the
            // canvas prints changes.
            const sp = widgetOf(this, "save_path");
            if (sp) sp.label = "input_path";
            const spInput = this.inputs?.find((i) => i.name === "save_path");
            if (spInput) spInput.localized_name = "input_path";
            // Deprecated, superseded by chaining pickers with `show` +
            // `edit_save_path`. The slot stays (values restore positionally);
            // an empty one just stops taking up a row. A graph that still
            // uses a stage keeps its visible widget.
            const stage = widgetOf(this, "stage");
            if (stage && !String(stage.value ?? "").trim()) {
                stage.hidden = true;
                stage.computeSize = () => [0, -4];
            }
            pickPanel(this);
        };

        // A saved workflow restores the ticks AFTER creation, and the node id
        // the listing is keyed by is only final once the graph is configured.
        const onConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            onConfigure?.apply(this, arguments);
            // Graphs saved before the node was stripped to one wire carry ten
            // widget values, applied positionally onto the five widgets that
            // remain — which lands the ticks on `mode` and the stage nowhere.
            // Put each surviving value back on its own widget, by the position
            // it held in the old layout: [get_new, asset, category, selection,
            // view, role, folder, phase, mode, stage].
            const v = info?.widgets_values;
            if (Array.isArray(v) && v.length >= 10) {
                for (const [name, i] of [["save_path", 6], ["selection", 3],
                                         ["view", 4], ["mode", 8],
                                         ["stage", 9]]) {
                    const w = widgetOf(this, name);
                    if (w) w.value = v[i];
                }
                // Every widget added since that layout is holding one of its
                // values by now, so each goes back to its own default.
                for (const [name, value] of APPENDED_WIDGETS) {
                    const w = widgetOf(this, name);
                    if (w) w.value = value;
                }
            }
            // Repair for graphs already on disk. `LGraphNode.configure` walks
            // the widgets and takes `widgets_values` in order, so a value saved
            // against one widget lands on whichever widget now holds that
            // position. Any save written while the panel still occupied a slot
            // carries its empty string there, and it comes back on the widget
            // that took the position since. An empty string is not one of a
            // combo's options, so ComfyUI refuses the whole queue over it:
            // `Value not in list: show: '' not in [...]`. Anything the widget
            // does not actually offer goes back to its default.
            for (const [name, value] of APPENDED_WIDGETS) {
                const w = widgetOf(this, name);
                if (!w) continue;
                const offered = w.options?.values;
                const known = Array.isArray(offered)
                    ? offered.includes(w.value)
                    : w.value !== undefined && w.value !== null && w.value !== "";
                if (!known) w.value = value;
            }
            queueMicrotask(() => this._symReloadPick?.());
        };
    },
});

// A run just resolved the folder — list it, rather than making the user press
// reload to find out which one the node landed on.
api.addEventListener("symbiotica.pick", (event) => {
    const detail = event?.detail ?? {};
    if (detail.node_id == null) return;
    const node = app.graph?.getNodeById?.(Number(detail.node_id))
        ?? app.graph?.getNodeById?.(detail.node_id);
    if (!node) return;
    node._symReloadPick?.();
});

// A cached picker does not execute, and its change-check only answers for
// what it EMITS — so a queue that wrote new renders can finish without the
// node running at all. The re-list comes from here instead: every picker on
// the canvas refreshes when a queue ends.
api.addEventListener("execution_success", () => {
    for (const node of app.graph?._nodes ?? []) node._symReloadPick?.();
});
