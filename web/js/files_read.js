// ABOUTME: Files Read node UI — fullscreen files browser over a client refs
// ABOUTME: folder: tree + filters, folder=group / ticked files=cells, writes
// ABOUTME: the node's selection JSON. Tree mechanics referenced from rail.js.
import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";

const widgetOf = (node, name) => node.widgets?.find((w) => w.name === name);
const el = (tag, style = "", text = "") => {
    const d = document.createElement(tag);
    if (style) d.style.cssText = style;
    if (text) d.textContent = text;
    return d;
};
const thumbUrl = (root, rel) => api.apiURL(
    `/symbiotica/local-image?path=${encodeURIComponent(`${root}/${rel}`)}`);

async function fetchJson(url) {
    const res = await api.fetchApi(url);
    if (!res.ok) throw new Error((await res.json())?.error ?? res.statusText);
    return res.json();
}

function readSelection(node) {
    try {
        const g = JSON.parse(widgetOf(node, "selection")?.value || "{}").groups;
        return Array.isArray(g) ? g : [];
    } catch {
        return [];
    }
}

function writeSelection(node, groups) {
    const w = widgetOf(node, "selection");
    if (w) w.value = JSON.stringify({ groups });
    updateSummary(node);
}

function updateSummary(node) {
    const groups = readSelection(node);
    const n = groups.reduce((s, g) => s + (g.files?.length ?? 0), 0);
    const label = widgetOf(node, "files_summary");
    if (label) label.value = groups.length
        ? `${groups.length} groups · ${n} files`
        : "no groups — open the files browser";
    node.setDirtyCanvas(true, true);
}

// Category proposal: nested folder -> its parent folder's name; a top-level
// folder is its own category.
function proposeCategory(folderKey) {
    const parts = folderKey.split("/");
    return parts.length > 1 ? parts[parts.length - 2] : parts[0];
}

function openBrowser(node) {
    const root = (widgetOf(node, "refs_path")?.value || "").trim();
    if (!root) {
        alert("Set refs_path to the client reference folder first.");
        return;
    }
    const overlay = el("div",
        "position:fixed;inset:0;z-index:10000;background:#161616;color:#ddd;" +
        "display:flex;flex-direction:column;font:12px sans-serif;");
    const bar = el("div",
        "display:flex;align-items:center;gap:10px;padding:8px 12px;" +
        "background:#202020;border-bottom:1px solid #333;");
    bar.appendChild(el("b", "",
        "Files browser — folder = group, ticked files = its row cells"));
    const closeBtn = el("button", "margin-left:auto;", "Done");
    bar.appendChild(closeBtn);
    overlay.appendChild(bar);

    const body = el("div", "flex:1;display:flex;min-height:0;");
    const treePane = el("div",
        "flex:1;overflow:auto;padding:10px;border-right:1px solid #333;");
    const groupsPane = el("div", "width:340px;overflow:auto;padding:10px;");
    body.append(treePane, groupsPane);
    overlay.appendChild(body);
    document.body.appendChild(overlay);
    closeBtn.addEventListener("click", () => overlay.remove());

    let images = [];              // [{rel, w, h}]
    let groups = readSelection(node);
    let search = "";
    let sizeFilter = null;        // "WxH" | null
    const expanded = new Set();

    const groupOf = (folderKey) => groups.find((g) => g.folder === folderKey);
    const save = () => { writeSelection(node, groups); renderGroups(); };

    // --- filters -----------------------------------------------------------
    const filterBar = el("div",
        "display:flex;gap:6px;align-items:center;padding:6px 12px;" +
        "background:#1b1b1b;border-bottom:1px solid #2a2a2a;flex-wrap:wrap;");
    const searchBox = el("input", "width:220px;");
    searchBox.placeholder = "filter by name…";
    searchBox.addEventListener("input", () => {
        search = searchBox.value.trim().toLowerCase();
        renderTree();
    });
    filterBar.appendChild(searchBox);
    const sizeChips = el("div", "display:flex;gap:4px;flex-wrap:wrap;");
    filterBar.appendChild(sizeChips);
    overlay.insertBefore(filterBar, body);

    function renderSizeChips() {
        sizeChips.replaceChildren();
        const sizes = [...new Set(images.filter((i) => i.w && i.h)
            .map((i) => `${i.w}x${i.h}`))].sort((a, b) =>
                parseInt(a) - parseInt(b) || a.localeCompare(b));
        for (const label of ["all", ...sizes]) {
            const v = label === "all" ? null : label;
            const c = el("button",
                `opacity:${v === sizeFilter ? 1 : 0.55};`, label);
            c.addEventListener("click", () => {
                sizeFilter = v;
                renderSizeChips();
                renderTree();
            });
            sizeChips.appendChild(c);
        }
    }

    function visibleImages() {
        return images.filter((img) => {
            if (search && !img.rel.toLowerCase().includes(search)) return false;
            if (sizeFilter && `${img.w}x${img.h}` !== sizeFilter) return false;
            return true;
        });
    }

    // --- tree (trie per rail.js) ------------------------------------------
    function buildTree(entries) {
        const rootNode = { folders: new Map(), files: [], count: 0 };
        for (const entry of entries) {
            const parts = entry.rel.split("/");
            let n = rootNode;
            n.count++;
            for (let i = 0; i < parts.length - 1; i++) {
                if (!n.folders.has(parts[i])) {
                    n.folders.set(parts[i],
                        { folders: new Map(), files: [], count: 0 });
                }
                n = n.folders.get(parts[i]);
                n.count++;
            }
            n.files.push(entry);
        }
        return rootNode;
    }

    function renderTree() {
        treePane.replaceChildren();
        const entries = visibleImages();
        if (!entries.length) {
            treePane.appendChild(el("div", "opacity:.6;",
                images.length ? "no images match the filters"
                              : "⏳ loading folder…"));
            return;
        }

        function fileRow(entry, folderKey, depth) {
            const g = groupOf(folderKey);
            const row = el("div",
                `display:flex;align-items:center;gap:6px;padding:1px 0 1px ${12 * depth + 18}px;`);
            const check = el("input");
            check.type = "checkbox";
            check.checked = Boolean(g?.files?.includes(entry.rel));
            check.addEventListener("change", () => {
                let g2 = groupOf(folderKey);
                if (!g2) {
                    const name = folderKey.split("/").pop();
                    g2 = { folder: folderKey, name,
                           category: proposeCategory(folderKey), files: [],
                           desc: "", variants: false };
                    groups.push(g2);
                }
                g2.files = g2.files.filter((p) => p !== entry.rel);
                if (check.checked) g2.files.push(entry.rel); // tick order = cell order
                if (!g2.files.length) groups = groups.filter((x) => x !== g2);
                save();
                renderTree();
            });
            const img = el("img",
                "width:34px;height:34px;object-fit:contain;background:#111;" +
                "border-radius:3px;flex:none;");
            img.loading = "lazy";
            img.src = thumbUrl(root, entry.rel);
            const label = el("span",
                "flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;",
                `${entry.rel.split("/").pop()}  ${entry.w ?? "?"}×${entry.h ?? "?"}`);
            label.title = entry.rel;
            row.append(check, img, label);
            return row;
        }

        function renderNode(node, prefix, depth) {
            for (const [dirName, child] of node.folders) {
                const key = prefix ? `${prefix}/${dirName}` : dirName;
                const open = expanded.has(key) || Boolean(search || sizeFilter);
                const g = groupOf(key);
                const direct = child.files.map((e) => e.rel);
                const nChecked = direct.filter((p) => g?.files?.includes(p)).length;
                const fh = el("div",
                    `display:flex;align-items:center;gap:4px;padding:2px 0 2px ${12 * depth}px;`);
                const check = el("input");
                check.type = "checkbox";
                check.checked = direct.length > 0 && nChecked === direct.length;
                check.indeterminate = nChecked > 0 && nChecked < direct.length;
                check.addEventListener("click", (e) => e.stopPropagation());
                check.addEventListener("change", () => {
                    // Folder tick = group its DIRECT visible files (subfolders
                    // are their own groups — one folder, one sheet row).
                    const clearing = nChecked > 0;
                    let g2 = groupOf(key);
                    if (clearing) {
                        if (g2) {
                            g2.files = g2.files.filter((p) => !direct.includes(p));
                            if (!g2.files.length) {
                                groups = groups.filter((x) => x !== g2);
                            }
                        }
                    } else {
                        if (!g2) {
                            g2 = { folder: key, name: dirName,
                                   category: proposeCategory(key), files: [],
                                   desc: "", variants: false };
                            groups.push(g2);
                        }
                        g2.files = [...new Set([...g2.files, ...direct])];
                    }
                    save();
                    renderTree();
                });
                const label = el("span", "flex:1;cursor:pointer;",
                    `${open ? "▾" : "▸"} 📁 ${dirName}  ${nChecked}/${child.count}`);
                label.addEventListener("click", () => {
                    expanded[open ? "delete" : "add"](key);
                    renderTree();
                });
                fh.append(check, label);
                treePane.appendChild(fh);
                if (open) renderNode(child, key, depth + 1);
            }
            for (const entry of node.files) {
                treePane.appendChild(fileRow(entry, prefix || "(root)", depth));
            }
        }
        renderNode(buildTree(entries), "", 0);
    }

    // --- groups panel ------------------------------------------------------
    function renderGroups() {
        groupsPane.replaceChildren();
        groupsPane.appendChild(el("div", "font-weight:bold;margin-bottom:6px;",
            `Groups · ${groups.length}`));
        if (!groups.length) {
            groupsPane.appendChild(el("div", "opacity:.6;",
                "Tick a folder (one group = one sheet row) or single files."));
        }
        for (const g of groups) {
            const card = el("div",
                "border:1px solid #333;border-radius:6px;padding:8px;margin-bottom:8px;");
            const head = el("div", "display:flex;gap:6px;align-items:center;");
            const nameIn = el("input", "flex:1;");
            nameIn.value = g.name;
            nameIn.addEventListener("change", () => { g.name = nameIn.value; save(); });
            const del = el("button", "", "✕");
            del.addEventListener("click", () => {
                groups = groups.filter((x) => x !== g);
                save();
                renderTree();
            });
            head.append(nameIn, del);
            card.appendChild(head);

            const catRow = el("div",
                "display:flex;gap:6px;align-items:center;margin-top:4px;");
            catRow.appendChild(el("span", "opacity:.6;", "category"));
            const catIn = el("input", "flex:1;");
            catIn.value = g.category;
            catIn.addEventListener("change", () => { g.category = catIn.value; save(); });
            catRow.appendChild(catIn);
            card.appendChild(catRow);

            const descRow = el("div",
                "display:flex;gap:6px;align-items:center;margin-top:4px;");
            descRow.appendChild(el("span", "opacity:.6;", "desc"));
            const descIn = el("input", "flex:1;");
            descIn.placeholder = "optional — becomes the sheet prompt";
            descIn.value = g.desc ?? "";
            descIn.addEventListener("change", () => { g.desc = descIn.value; save(); });
            descRow.appendChild(descIn);
            card.appendChild(descRow);

            const varRow = el("label",
                "display:flex;gap:6px;align-items:center;margin-top:4px;cursor:pointer;");
            const varCheck = el("input");
            varCheck.type = "checkbox";
            varCheck.checked = Boolean(g.variants);
            varCheck.addEventListener("change", () => {
                g.variants = varCheck.checked;
                save();
            });
            varRow.append(varCheck,
                el("span", "", "variants (distinct directions, mirror/split)"));
            card.appendChild(varRow);

            const cells = el("div",
                "display:flex;gap:4px;flex-wrap:wrap;margin-top:6px;");
            g.files.forEach((rel, i) => {
                const cell = el("div",
                    "position:relative;width:44px;text-align:center;");
                const img = el("img",
                    "width:40px;height:40px;object-fit:contain;background:#111;" +
                    "border-radius:3px;");
                img.src = thumbUrl(root, rel);
                img.title = rel;
                cell.appendChild(img);
                const ctl = el("div", "display:flex;justify-content:center;gap:2px;");
                const mk = (txt, fn) => {
                    const b = el("a", "cursor:pointer;font-size:10px;", txt);
                    b.addEventListener("click", fn);
                    return b;
                };
                if (i > 0) ctl.appendChild(mk("◀", () => {
                    g.files.splice(i - 1, 0, g.files.splice(i, 1)[0]);
                    save();
                }));
                ctl.appendChild(mk("✕", () => {
                    g.files.splice(i, 1);
                    if (!g.files.length) groups = groups.filter((x) => x !== g);
                    save();
                    renderTree();
                }));
                if (i < g.files.length - 1) ctl.appendChild(mk("▶", () => {
                    g.files.splice(i + 1, 0, g.files.splice(i, 1)[0]);
                    save();
                }));
                cell.appendChild(ctl);
                cells.appendChild(cell);
            });
            card.appendChild(cells);
            groupsPane.appendChild(card);
        }
    }

    renderGroups();
    renderTree();
    fetchJson(`/symbiotica/list-assets?dir=${encodeURIComponent(root)}`)
        .then((data) => {
            images = data.images ?? [];
            renderSizeChips();
            renderTree();
        })
        .catch((e) => {
            treePane.replaceChildren(
                el("div", "color:#f66;", `could not list folder: ${e.message}`));
        });
}

app.registerExtension({
    name: "symbiotica.files_read",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "SymbioticaFilesRead") return;
        const onNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            onNodeCreated?.apply(this, arguments);
            const node = this;
            node.addWidget("button", "📂 Open files browser", null,
                () => openBrowser(node));
            const summary = node.addWidget("text", "files_summary", "", () => {});
            summary.disabled = true;
            summary.serialize = false;
            updateSummary(node);
        };
    },
});
