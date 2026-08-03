# ABOUTME: V3 ComfyUI nodes for the order pipeline — Order Read, Event Specs,
# ABOUTME: Template Builder, Template Prompt. Thin wrappers over py/pipeline/*.
from __future__ import annotations

import hashlib
import json
import os

import numpy as np
import torch
from comfy_api.latest import io, ui

import folder_paths

from .compose import (
    _draw_task_refs,
    _paint_background,
    build_catalog_sheet,
    build_paired_sheets,
    build_prefill_sheet,
    save_sheet,
)
from .markers import assign_markers, draw_placement_markers
from .model_presets import MODEL_PRESETS, preset_dims
from .prompt_enhancer import ENHANCER_SYSTEM_PROMPT, build_enhancer_task
from .prompts_split import parse_region_prompts
from .regional_edit import region_edit_prompt, region_pixel_box
from .regional_prompt import (
    build_regional_prompt,
    regions_to_pixel_bboxes,
    target_ref_size,
)
from .skeleton import build_client_prompts, build_skeleton
from .order_loader import event_spec, load_order, order_overview, spec_wire_json
from .order_sheet import slugify
from .order_assets import (assets_by_category, dataset_dir,
                           pick_reference_per_category, save_paths)
from .project_layout import project_root_of
from .prompt_book import prompts_dir, resolve_category_prompts
from .texture_pack import PackSettings

OrderEvents = io.Custom("SYMBIOTICA_ORDER_EVENTS")
EventSpec = io.Custom("SYMBIOTICA_EVENT_SPEC")
Template = io.Custom("SYMBIOTICA_TEMPLATE")
Order = io.Custom("SYMBIOTICA_ORDER")
PackSettingsWire = io.Custom("SYMBIOTICA_PACK_SETTINGS")
ModelPresetWire = io.Custom("SYMBIOTICA_MODEL_PRESET")
# A saved Auto Packer recipe from the Template Library: {order, preset,
# settings, category, overrides, name}. Distinct from SYMBIOTICA_TEMPLATE (the
# Template Builder/Editor sheet bundle) — different shape, different producer.
PackTemplateWire = io.Custom("SYMBIOTICA_PACK_TEMPLATE")

_RESOLUTIONS = ["0.5K", "1K", "2K", "4K"]
# Derived from the preset table so a new model shows up without editing here.
_MODELS = [m["id"] for m in MODEL_PRESETS] + ["custom"]
_ASPECTS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5",
            "21:9", "4:1", "1:4", "8:1", "1:8"]


def _push(event: str, payload: dict) -> None:
    """Fire-and-forget UI push; absent/failed server must never break execution."""
    try:
        from server import PromptServer
        PromptServer.instance.send_sync(event, payload)
    except Exception:
        pass


def _register_refs_root(path: str) -> None:
    try:
        from .routes import register_root
        register_root(path)
    except Exception:
        pass


def _register_project(project_path: str) -> None:
    """The project this execution ran against, so the Template Library may browse
    and delete its pools. Only an execution vouches for a project."""
    try:
        from .routes import register_project
        register_project(project_path)
    except Exception:
        pass


def _expand_studio(value: str) -> str:
    """A `studios/<slug>/...` string — what the Studio Library node's wire
    carries — becomes its absolute path under the studio-assets Volume. Any
    other path passes through, so a typed local folder still works."""
    from .studio_library import STUDIO_ASSETS_DIR, expand_studio_path
    return expand_studio_path(STUDIO_ASSETS_DIR, value)


def _pil_to_tensor(img) -> torch.Tensor:
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(arr)[None, ...]


class SymbioticaOrderRead(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaOrderRead",
            display_name="Symbiotica Order Read",
            category="symbiotica/pipeline",
            description="Point at one client project folder (with orders/ and "
                        "reference-assets/), pick a month, and read that "
                        "month's order into events. Wire the events into the "
                        "Template Editor.",
            inputs=[
                io.String.Input("project_path", default="",
                                tooltip="The client project folder — the one "
                                        "that contains orders/ and "
                                        "reference-assets/"),
                io.String.Input("month", default="",
                                tooltip="Which month's order to read (the "
                                        ".xlsx files under orders/)"),
            ],
            outputs=[OrderEvents.Output(display_name="events")],
            hidden=[io.Hidden.unique_id],
            is_output_node=True,
        )

    @classmethod
    def _paths(cls, project_path, month):
        """The order xlsx, client-refs folder, and sprite-catalog root, all
        derived from the project folder and the picked month."""
        project_path = (project_path or "").strip()
        op = rp = assets_root = ""
        if project_path:
            from .project_layout import resolve_month
            r = resolve_month(project_path, (month or "").strip())
            op = r["order_path"]
            rp = r["refs_path"]
            assets_root = r["assets_root"]
        return op, rp, assets_root

    @classmethod
    def fingerprint_inputs(cls, project_path="", month=""):
        op, rp, _ = cls._paths(project_path, month)
        h = hashlib.sha256(f"{op}|{rp}".encode())
        try:
            st = os.stat(op)
            h.update(f"{st.st_mtime_ns}:{st.st_size}".encode())
        except OSError:
            pass
        try:
            if rp:
                h.update("\n".join(sorted(os.listdir(rp))).encode())
        except OSError:
            pass
        return h.hexdigest()

    @classmethod
    def execute(cls, project_path="", month="") -> io.NodeOutput:
        _register_project(project_path)
        op, rp, assets_root = cls._paths(project_path, month)
        if not op:
            raise ValueError(
                "no order file — set the project folder (the one with an "
                "orders/ subfolder of .xlsx files) and pick a month")
        loaded = load_order(op, rp)
        payload = {
            "events": loaded["events"],
            "refFileCount": loaded["refFileCount"],
            "refsRoot": rp,
            "assetsRoot": assets_root,
        }
        if rp:
            _register_refs_root(rp)
        if assets_root:
            _register_refs_root(assets_root)
        _push("symbiotica.order_events",
              {"node_id": cls.hidden.unique_id, **payload})
        summary = json.dumps(order_overview(loaded["events"]), indent=1)
        return io.NodeOutput(payload, ui=ui.PreviewText(summary))


class SymbioticaOrderSpecs(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaOrderSpecs",
            display_name="Symbiotica Order Specs",
            category="symbiotica/pipeline",
            description="Pick a project, month, and event — outputs ONE "
                        "order wire carrying that event's assets, client "
                        "reference paths, and catalog root. Feed it to the "
                        "Auto Packer (and any task-prompt/task-image taps).",
            inputs=[
                io.String.Input("project_path", default="",
                                tooltip="The client project folder — the one "
                                        "that contains orders/ and "
                                        "reference-assets/"),
                io.String.Input("month", default="",
                                tooltip="Which month's order to read"),
                io.String.Input("feature", default="",
                                tooltip="Which event to build (empty = the "
                                        "order's first event)"),
            ],
            outputs=[Order.Output(display_name="order")],
        )

    @classmethod
    def _paths(cls, project_path, month):
        project_path = (project_path or "").strip()
        op = rp = assets_root = ""
        if project_path:
            from .project_layout import resolve_month
            r = resolve_month(project_path, (month or "").strip())
            op, rp, assets_root = r["order_path"], r["refs_path"], r["assets_root"]
        return op, rp, assets_root

    @classmethod
    def _guide(cls, project_path):
        path = os.path.join((project_path or "").strip(), "order-guide.md")
        try:
            with open(path, encoding="utf-8") as f:
                return f.read()
        except OSError:
            return None

    @classmethod
    def fingerprint_inputs(cls, project_path="", month="", feature=""):
        op, rp, _ = cls._paths(project_path, month)
        h = hashlib.sha256(f"{op}|{rp}|{feature}".encode())
        try:
            st = os.stat(op)
            h.update(f"{st.st_mtime_ns}:{st.st_size}".encode())
        except OSError:
            pass
        try:
            if rp:
                h.update("\n".join(sorted(os.listdir(rp))).encode())
        except OSError:
            pass
        h.update((cls._guide(project_path) or "").encode())
        return h.hexdigest()

    @classmethod
    def execute(cls, project_path="", month="", feature="") -> io.NodeOutput:
        _register_project(project_path)
        op, rp, assets_root = cls._paths(project_path, month)
        if not op:
            raise ValueError(
                "no order file — set the project folder (the one with an "
                "orders/ subfolder of .xlsx files) and pick a month")
        loaded = load_order(op, rp)
        events = loaded["events"]
        if not events:
            raise ValueError(f"no events found in {op}")
        feature = (feature or "").strip()
        # The JS combo labels events "Feature — Event Name"; accept that form as
        # well as the bare feature (saved workflows keep the bare value).
        if feature and feature not in {e.get("feature") for e in events}:
            feature = feature.split(" — ")[0].strip()
        feature = feature or events[0].get("feature", "")
        # event_spec returns {feature, eventName, templates}; it raises an
        # actionable ValueError listing the available features when not found.
        spec = event_spec(events, feature)
        # ORDER carries a FLAT asset list (the AutoPacker's contract); flatten
        # the template groups back out, named assets only, spec order kept.
        assets = [a for g in spec["templates"] for a in g["assets"]]
        if not assets:
            names = ", ".join(e.get("feature", "?") for e in events)
            raise ValueError(
                f"event {feature!r} has no named assets — this order's "
                f"events: {names}")
        if rp:
            _register_refs_root(rp)
        if assets_root:
            _register_refs_root(assets_root)
        payload = {
            "feature": spec.get("feature", ""),
            "eventName": spec.get("eventName", ""),
            "assets": assets,
            "refsRoot": rp,
            "assetsRoot": assets_root,
            "guide": cls._guide(project_path),
            # The order identity, so a Template Library save can reproduce this
            # exact event later (project + month + feature). Additive keys —
            # older consumers ignore them.
            "project_path": (project_path or "").strip(),
            "month": (month or "").strip(),
            # Where this pack came from — an order, not the asset library. The
            # Auto Packer files "Save as template" by this: an order template is
            # the design guide for ONE month and lives beside that month's
            # order; a reference template is universal (see the Reference
            # Browser).
            "source": "order",
        }
        return io.NodeOutput(payload)


class SymbioticaReferenceBrowser(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaReferenceBrowser",
            display_name="Symbiotica Reference Browser",
            category="symbiotica/pipeline",
            description="Build a reference template from the game's asset "
                        "library — no order, no briefs. Wire the Studio "
                        "Library's path in, browse the folders in this node, "
                        "tick what you want (a folder = one sheet row, its "
                        "images = that row's cells), and wire 'order' into the "
                        "Auto Packer.",
            inputs=[
                io.String.Input("root_path", default="",
                                tooltip="The library folder to browse — wire "
                                        "the Studio Library's path here, or "
                                        "type one"),
                io.String.Input("name", default="",
                                tooltip="Base name for the sheets (empty = "
                                        "the folder's name)"),
                io.String.Input("selection", default="{}", advanced=True,
                                tooltip="Picks JSON, set by the node's "
                                        "browser"),
            ],
            outputs=[Order.Output(display_name="order")],
        )

    @classmethod
    def fingerprint_inputs(cls, root_path="", name="", selection="{}"):
        refs_path = _expand_studio(root_path)
        h = hashlib.sha256(f"{refs_path}|{name}|{selection}".encode())
        # Re-run when any selected file changes on disk.
        try:
            sel = json.loads(selection or "{}")
        except ValueError:
            sel = {}
        groups = sel.get("groups") if isinstance(sel, dict) else None
        for g in groups or []:
            if not isinstance(g, dict):
                continue
            for rel in g.get("files") or []:
                p = os.path.join(refs_path, *str(rel).split("/"))
                try:
                    st = os.stat(p)
                    h.update(f"{rel}:{st.st_mtime_ns}:{st.st_size}".encode())
                except OSError:
                    h.update(f"{rel}:missing".encode())
        return h.hexdigest()

    @classmethod
    def execute(cls, root_path="", name="", selection="{}") -> io.NodeOutput:
        from .project_layout import project_root_of
        from .reference_browser import build_reference_order
        refs_root = _expand_studio(root_path)
        # Reference-only work never touches an order node, so this is the only
        # place that flow names its project — and it names it whether or not the
        # selection is usable, because the root alone identifies the project.
        _register_project(project_root_of(refs_root))
        order = build_reference_order(refs_root, selection, name)
        _register_refs_root(order["refsRoot"])
        return io.NodeOutput(order)


class SymbioticaStudioLibrary(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaStudioLibrary",
            display_name="Symbiotica Studio Library",
            category="symbiotica/pipeline",
            description="Pick a file or folder from the studio asset library; "
                        "outputs its absolute sandbox path (and whether it is a "
                        "folder). Open the browser, click one entry.",
            inputs=[
                io.String.Input("selection", default="", advanced=True,
                                tooltip="Volume-relative pick, set by the "
                                        "studio-library browser"),
            ],
            outputs=[
                io.String.Output(display_name="path"),
                io.Boolean.Output(display_name="is_dir"),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, selection=""):
        from .studio_library import STUDIO_ASSETS_DIR, selection_fingerprint
        return selection_fingerprint(STUDIO_ASSETS_DIR, selection)

    @classmethod
    def execute(cls, selection="") -> io.NodeOutput:
        from .studio_library import STUDIO_ASSETS_DIR, resolve_selection
        path, is_dir = resolve_selection(STUDIO_ASSETS_DIR, selection)
        return io.NodeOutput(path, is_dir)


class SymbioticaRefsFolder(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaRefsFolder",
            display_name="Symbiotica Refs Folder",
            category="symbiotica/pipeline",
            description="Load every image in one folder, in filename order. "
                        "Takes an absolute folder path and nothing else — no "
                        "browsing, no picking — so a dispatcher can bind the "
                        "path and run the graph headless.",
            inputs=[
                io.String.Input("refs_dir", default="",
                                tooltip="Absolute path to the folder of "
                                        "reference images"),
                io.Int.Input("max_count", default=0, min=0, max=512,
                             tooltip="Keep at most this many images "
                                     "(0 = all of them)"),
            ],
            outputs=[
                io.Image.Output(display_name="images", is_output_list=True,
                                tooltip="One image per file, in filename "
                                        "order"),
                io.String.Output(display_name="filenames",
                                 is_output_list=True,
                                 tooltip="Filename of image i — index-aligned "
                                         "with images"),
                io.Int.Output(display_name="count"),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, refs_dir="", max_count=0):
        from .refs_dir import refs_fingerprint
        return refs_fingerprint(_expand_studio(refs_dir), max_count)

    @classmethod
    def execute(cls, refs_dir="", max_count=0) -> io.NodeOutput:
        from .refs_dir import open_reference_images
        # Deliberately vouches for nothing: this node hands back pixels rather
        # than serving files over a route, so it has no reason to widen what the
        # browsers may read.
        opened = open_reference_images(_expand_studio(refs_dir), max_count)
        return io.NodeOutput(
            [_pil_to_tensor(im) for _, im in opened],
            [os.path.basename(p) for p, _ in opened],
            len(opened),
        )


class SymbioticaModelPreset(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaModelPreset",
            display_name="Symbiotica Model Preset",
            category="symbiotica/pipeline",
            description="Shared sheet preset for the Auto Packer — model, "
                        "resolution, aspect, layout (columns / rows) and "
                        "background. Wire 'preset' into one or many Auto "
                        "Packers to drive them all from a single node.",
            inputs=[
                io.Combo.Input("preset_model", options=_MODELS,
                               default="qwen-image"),
                io.Combo.Input("resolution", options=_RESOLUTIONS,
                               default="1K"),
                io.Combo.Input("aspect_ratio", options=_ASPECTS, default="1:1"),
                io.Int.Input("columns", default=1, min=1, max=4,
                             tooltip="Assets side by side per row"),
                io.Int.Input("max_rows_per_sheet", default=4, min=1, max=12,
                             tooltip="Rows per sheet before a new sheet"),
                io.String.Input("background", default="#808080",
                                tooltip="Sheet background color; empty = "
                                        "transparent"),
            ],
            outputs=[ModelPresetWire.Output(display_name="preset")],
        )

    @classmethod
    def execute(cls, preset_model="qwen-image", resolution="1K",
                aspect_ratio="1:1", columns=1, max_rows_per_sheet=4,
                background="#808080") -> io.NodeOutput:
        return io.NodeOutput({
            "model": preset_model, "tier": resolution, "ar": aspect_ratio,
            "columns": int(columns), "max_rows": int(max_rows_per_sheet),
            "background": background,
        })


class SymbioticaAutoPackerSettings(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaAutoPackerSettings",
            display_name="Symbiotica Auto Packer Settings",
            category="symbiotica/pipeline",
            description="Optional pack-settings knobs for the Auto Packer — the "
                        "same layout controls as the Template Editor's Pack "
                        "Settings, so a hands-off run can reproduce an editor "
                        "sheet (e.g. recipes stacked per row at 2x scale). Wire "
                        "'settings' into the Auto Packer.",
            inputs=[
                io.Combo.Input("scale_target",
                               options=["off", "256", "384", "512", "768",
                                        "1024", "fit width"],
                               default="off",
                               tooltip="Grow each sprite so its longest edge "
                                       "reaches ~this many px (capped by "
                                       "scale_max, never shrinks) — small "
                                       "sprites scale more than large ones. "
                                       "'off' = native size. 'fit width' = "
                                       "scale the whole packed block to fill "
                                       "the sheet width (5px margin)."),
                io.Combo.Input("scale_max",
                               options=["2x", "3x", "4x", "6x", "8x"],
                               default="3x",
                               tooltip="Max zoom for the target above — a small "
                                       "sprite never grows more than this, so a "
                                       "scaled sheet can't overflow. e.g. target "
                                       "512 + 3x → 128px:3x, 256px:2x, "
                                       "512px:native."),
                io.Combo.Input("algorithm",
                               options=["shelf", "maxrects", "grid"],
                               default="shelf",
                               tooltip="Packing algorithm (Shelf/Strip = one "
                                       "strip per row)"),
                io.Boolean.Input("distribute_by_folder", default=True,
                                 tooltip="Lay each asset type's strip on its own "
                                         "row (the editor default)"),
                io.Int.Input("padding", default=0, min=0, max=512,
                             tooltip="Gap between packed strips AND between an "
                                     "asset and its mirror cell (px)"),
                io.Int.Input("border", default=0, min=0, max=512,
                             tooltip="Draw an outline box this many px thick "
                                     "around each icon cell (the asset and its "
                                     "mirror each get a box). 0 = no box."),
                io.Boolean.Input("combined_sheet", default=True,
                                 tooltip="Emit the grouped, paginated sheets "
                                         "(the normal output). Off = only the "
                                         "split-variant sheets below."),
                io.Boolean.Input("split_variants", default=False,
                                 tooltip="For directional assets (xlsx rotation "
                                         "2/4), emit one sheet per variant ref "
                                         "(max 3) — mirrored for rotation 2. "
                                         "Food (rotation -) is never split."),
                io.Combo.Input("max_refs", options=["all", "1", "2", "3"],
                               default="all",
                               tooltip="Hard cap on reference images per asset "
                                       "— keep the first N (in the panel's "
                                       "order), drop the rest, so a sheet is "
                                       "never overloaded with refs. 'all' = no "
                                       "cap."),
            ],
            outputs=[PackSettingsWire.Output(display_name="settings")],
        )

    _CAP = {"2x": 2.0, "3x": 3.0, "4x": 4.0, "6x": 6.0, "8x": 8.0}

    @classmethod
    def execute(cls, scale_target="off", scale_max="3x", algorithm="shelf",
                distribute_by_folder=True, padding=0, border=0,
                combined_sheet=True, split_variants=False,
                max_refs="all") -> io.NodeOutput:
        fit_width = scale_target == "fit width"
        try:
            # 0 = off or fit-width (a block-fit mode, not a per-asset target).
            # int() guards a stale pre-target value from an old saved workflow.
            target = 0 if scale_target in ("off", "fit width") \
                else int(scale_target)
        except (ValueError, TypeError):
            target = 0
        return io.NodeOutput({
            "scale_target": target,
            "scale_max": cls._CAP.get(scale_max, 3.0),
            "fit_width": fit_width,
            "algorithm": algorithm,
            "distribute_by_folder": bool(distribute_by_folder),
            "padding": int(padding),
            "border": int(border),
            "combined_sheet": bool(combined_sheet),
            "split_variants": bool(split_variants),
            "max_refs": None if max_refs == "all" else int(max_refs),
        })


class SymbioticaAutoPacker(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaAutoPacker",
            display_name="Symbiotica Auto Packer",
            category="symbiotica/pipeline",
            description="The whole order as ready-to-run template sheets: "
                        "similar assets grouped 1-2 columns x 3-4 rows per "
                        "sheet, each sheet paired with its client prompts. "
                        "Wire sheets -> img2img and sheet_prompts -> your "
                        "LLM/prompt input; downstream runs once per sheet.",
            inputs=[
                # Optional: the order comes from Order Specs, OR from a wired
                # Template Library `template` (which carries a frozen order).
                Order.Input("order", optional=True),
                # Sheet size / layout / background come from a Model Preset
                # node (or defaults); pack behaviour from a Settings node. Only
                # the category picker + per-asset panel live on this node.
                # Empty = unset (defers to a wired template's saved category);
                # a concrete pick, including "All", is the user's choice.
                io.String.Input("category", default="",
                                tooltip="One asset type, or All"),
                io.String.Input("overrides", default="{}",
                                tooltip="Per-asset hide/reorder, set from the "
                                        "node's Assets panel (JSON)"),
                io.String.Input("save_as", default="",
                                tooltip="Set by the '💾 Save as template' button "
                                        "— names the template this run writes to "
                                        "the project's templates/ folder. Empty "
                                        "= don't save."),
                ModelPresetWire.Input("preset", optional=True),
                PackSettingsWire.Input("settings", optional=True),
                # A saved recipe from the Template Library: supplies order /
                # preset / settings / category / overrides as DEFAULTS — this
                # node's own wired inputs and edited widgets override them.
                PackTemplateWire.Input("template", optional=True),
            ],
            outputs=[
                io.Image.Output(display_name="sheets", is_output_list=True,
                                tooltip="One template sheet per chunk of "
                                        "similar assets"),
                io.String.Output(display_name="sheet_prompts",
                                 is_output_list=True,
                                 tooltip="Client prompts for sheet i — "
                                         "index-aligned with sheets"),
                io.String.Output(display_name="sheet_names",
                                 is_output_list=True,
                                 tooltip="Slug per sheet — wire into Save "
                                         "Image filename_prefix"),
                # Appended, never inserted: ComfyUI links address an output by
                # SLOT INDEX, so a new slot in the middle would re-point every
                # saved workflow's wires.
                io.String.Output(display_name="categories",
                                 is_output_list=True,
                                 tooltip="The asset types this pack covers, "
                                         "each named ONCE (e.g. 'Food - 3 "
                                         "stages'), in first-appearance order. "
                                         "Not one per sheet — a type that "
                                         "paginates is still one type."),
                io.String.Output(display_name="sheet_categories",
                                 is_output_list=True,
                                 tooltip="Asset type of sheet i — ONE PER "
                                         "SHEET, index-aligned with sheets. "
                                         "Wire THIS into Category Prompts, not "
                                         "the deduped `categories` above: a "
                                         "short list does not error, it "
                                         "silently reuses its last entry."),
            ],
        )

    @classmethod
    def execute(cls, order=None, category="", overrides="{}", save_as="",
                preset=None, settings=None, template=None) -> io.NodeOutput:
        from .pack_library import resolve_pack_inputs
        # A wired Template Library `template` supplies order/preset/settings/
        # category/overrides as DEFAULTS; this node's own inputs + widgets win.
        cfg = resolve_pack_inputs(order=order, preset=preset, settings=settings,
                                  category=category, overrides=overrides,
                                  template=template)
        eff_order = cfg["order"]
        if not isinstance(eff_order, dict) or "assets" not in eff_order:
            raise ValueError("wire an Order Specs into 'order', or a Template "
                             "Library template into 'template'")
        # Sheet size / layout / background come from a wired Model Preset node
        # (or these defaults when it is unwired).
        p = cfg["preset"]
        model = p.get("model", "qwen-image")
        tier = p.get("tier", "1K")
        ar = p.get("ar", "1:1")
        columns = int(p.get("columns", 1))
        max_rows_per_sheet = int(p.get("max_rows", 4))
        background = p.get("background", "#808080")
        dims = preset_dims({"model": model, "tier": tier, "ar": ar})
        if not dims:
            raise ValueError(f"invalid preset: {model} / {tier} / {ar}")
        # Optional pack-settings node (unwired = today's defaults: shelf, no
        # distribute, scale 1 — nothing regresses).
        s = cfg["settings"]
        from .autopack import apply_overrides, autopack_order, packed_categories
        try:
            ov = json.loads(cfg["overrides"]) if cfg["overrides"] else {}
        except (ValueError, TypeError):
            ov = {}
        if not isinstance(ov, dict):
            ov = {}
        base = slugify(eff_order.get("feature", "")) or "order"
        assets = apply_overrides(eff_order["assets"], ov)
        packed = autopack_order(
            assets, eff_order.get("refsRoot", ""),
            sheet_w=dims["w"], sheet_h=dims["h"], columns=columns,
            max_rows=max_rows_per_sheet, background=background,
            category=cfg["category"], base_name=base,
            scale_target=s.get("scale_target", 0),
            scale_max=s.get("scale_max", 1.0),
            algorithm=s.get("algorithm", "shelf"),
            distribute_by_folder=s.get("distribute_by_folder", False),
            padding=s.get("padding", 0), border=s.get("border", 0),
            combined_sheet=s.get("combined_sheet", True),
            split_variants=s.get("split_variants", False),
            max_refs=s.get("max_refs"), fit_width=s.get("fit_width", False))
        if (save_as or "").strip():
            # Capture the EFFECTIVE preset/settings (what actually packed these
            # sheets), not the raw wire, so a re-load reproduces them exactly.
            eff_preset = {"model": model, "tier": tier, "ar": ar,
                          "columns": columns, "max_rows": max_rows_per_sheet,
                          "background": background}
            eff_settings = {
                "scale_target": s.get("scale_target", 0),
                "scale_max": s.get("scale_max", 1.0),
                "fit_width": s.get("fit_width", False),
                "algorithm": s.get("algorithm", "shelf"),
                "distribute_by_folder": s.get("distribute_by_folder", False),
                "padding": s.get("padding", 0), "border": s.get("border", 0),
                "combined_sheet": s.get("combined_sheet", True),
                "split_variants": s.get("split_variants", False),
                "max_refs": s.get("max_refs"),
            }
            cls._save_template(save_as, eff_order, eff_preset, eff_settings,
                               cfg["category"], ov, packed)
        return io.NodeOutput(
            [_pil_to_tensor(p["image"]) for p in packed],
            [p["prompts"] for p in packed],
            [p["name"] for p in packed],
            # NOT index-aligned with sheets, unlike the three lists above: one
            # entry per distinct asset type, not one per sheet.
            packed_categories(packed),
            # Index-aligned again — this is the one that pairs with sheets.
            [p.get("category", "") for p in packed],
        )

    @classmethod
    def _save_template(cls, name, order, preset, settings, category,
                       overrides, packed) -> None:
        """Write this run's sheets + recipe as a Template Library folder, filed
        by KIND: a pack from an Order Specs goes beside that month's order
        (<project>/orders/<Client-Month>/templates), a pack from the Reference
        Browser goes to the universal pool (<project>/templates/reference).
        Never raises — a save failure must not lose the packed output; it falls
        back to output/templates/<kind> and tells the UI via a push."""
        from .pack_library import kind_of_order, qualified_name, save_dirs, write_pack_template
        project_path = str(order.get("project_path", "")).strip()
        month = str(order.get("month", ""))
        kind = kind_of_order(order)
        out_root = os.path.join(folder_paths.get_output_directory(), "templates")
        dirs = save_dirs(project_path, kind, month, out_root)
        sidecar = {
            "eventName": order.get("eventName", ""),
            # The kind is written down, not re-derived: a template that is later
            # copied elsewhere (or read by an older browse) still knows which
            # pool it belongs to.
            "kind": kind,
            "month": month,
            "order": {
                "project_path": project_path,
                "month": month,
                "feature": order.get("feature", ""),
                "eventName": order.get("eventName", ""),
                "assets": order.get("assets", []),
                "refsRoot": order.get("refsRoot", ""),
                "assetsRoot": order.get("assetsRoot", ""),
                # So re-packing THIS template from the Library and saving again
                # lands in the same pool.
                "source": kind,
            },
            "preset": preset,
            "settings": settings,
            "category": category,
            "overrides": overrides if isinstance(overrides, dict) else {},
            "sheetNames": [p.get("name", "") for p in packed],
            # Saved so the Template Library can re-emit each sheet's client
            # prompts without re-packing (index-aligned with sheets/sheetNames).
            "sheetPrompts": [p.get("prompts", "") for p in packed],
            # Per-sheet asset type, so a Library replay can drive the Category
            # Prompts node without re-packing. Written now because it cannot be
            # recovered later: nothing in a saved template says which type a
            # sheet held.
            "sheetCategories": [p.get("category", "") for p in packed],
        }
        images = [p["image"] for p in packed]
        result = base = err = None
        for i, candidate in enumerate(dirs):
            try:
                result = write_pack_template(candidate, name, images, sidecar)
                base = candidate
                # With no project the project candidate is not in the list at
                # all, so index 0 IS the output fallback — the save still went
                # somewhere the user did not pick, and the UI must say so.
                fell_back = i > 0 or not project_path
                break
            except Exception as e:  # unwritable project folder → try the fallback
                err = e
        if result is None:
            _push("symbiotica.pack_template_saved",
                  {"error": f"could not save template: {err}"})
            return
        _register_refs_root(base)
        _push("symbiotica.pack_template_saved",
              {"name": result["name"], "key": qualified_name(kind, result["name"]),
               "kind": kind, "month": month, "dir": result["dir"],
               "project_path": project_path, "fellBack": fell_back})


class SymbioticaCategoryPrompts(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaCategoryPrompts",
            display_name="Symbiotica Category Prompts",
            category="symbiotica/pipeline",
            description="One architect system prompt per sheet, chosen by that "
                        "sheet's asset type and read from "
                        "<project>/prompts/<type>.md. Wire the Auto Packer's "
                        "sheet_categories in and system_prompts into your LLM "
                        "node's system prompt: one queue press then covers "
                        "every asset type in the order, instead of one pass "
                        "per type.",
            # The WHOLE list at once. Mapped per category instead, the engine
            # would re-read each file once per sheet and raise on the first
            # missing prompt alone — fail, write one file, fail again.
            is_input_list=True,
            inputs=[
                io.String.Input("sheet_categories", force_input=True,
                                tooltip="Per-sheet asset type: the Auto "
                                        "Packer's sheet_categories output. NOT "
                                        "its deduped `categories` — a short "
                                        "list does not error, it silently "
                                        "repeats its last entry."),
                io.String.Input("project_path", default="",
                                tooltip="Client project folder, holding the "
                                        "prompt book at <project>/prompts/. "
                                        "Filled in from the order when one is "
                                        "wired."),
                Order.Input("order", optional=True),
            ],
            outputs=[
                # Same split as the packer's categories / sheet_categories, and
                # for the same reason: one list is for reading, the other for
                # driving the render.
                io.String.Output(display_name="system_prompts",
                                 is_output_list=True,
                                 tooltip="The architect prompts this order "
                                         "uses, each ONCE, in first-appearance "
                                         "order — one per asset type, for "
                                         "reading. Two types, two entries, "
                                         "however many sheets they pack into."),
                io.String.Output(display_name="sheet_system_prompts",
                                 is_output_list=True,
                                 tooltip="Architect prompt for sheet i — one "
                                         "per SHEET, index-aligned with the "
                                         "packer's sheets. Wire THIS into the "
                                         "LLM's system prompt."),
            ],
        )

    @staticmethod
    def _one(value, default=""):
        """is_input_list hands EVERY input in as a list, widgets included."""
        if isinstance(value, list):
            return value[0] if value else default
        return default if value is None else value

    @classmethod
    def _project(cls, project_path, order):
        """The order's own project, then a Reference Browser order's refs root,
        then the widget. A reference order carries no project_path at all, so
        without the refsRoot walk its error would name a path like
        '/prompts/signage.md' that the user cannot act on."""
        o = cls._one(order, {}) or {}
        candidates = (
            str(o.get("project_path", "") or "").strip(),
            project_root_of(str(o.get("refsRoot", "") or "").strip()),
            str(cls._one(project_path)).strip(),
        )
        for cand in candidates:
            if cand and os.path.isdir(cand):
                return cand
        return ""

    @classmethod
    def fingerprint_inputs(cls, sheet_categories=None, project_path="",
                           order=None):
        # Only WIDGET values are real here: ComfyUI calls this with
        # execution_list=None, so every linked input arrives as None and the
        # order wire cannot be read. Hash the whole prompt book from the widget
        # — that catches an edited file and a missing one being created. It must
        # never raise: a raise sets is_changed to NaN, which folds into every
        # descendant's cache key and re-bills the LLM and Gemini every queue.
        root = prompts_dir(str(cls._one(project_path)).strip())
        h = hashlib.sha256(root.encode())
        # RECURSIVE: the shared rules live in prompts/_rules/. Listing one level
        # deep would miss an edited lighting rule entirely — ComfyUI would reuse
        # the cached prompt and the run would render from the old text while the
        # new text sat on disk, which reads as "my edit did nothing".
        try:
            for where, dirs, files in os.walk(root):
                dirs.sort()
                for name in sorted(files):
                    p = os.path.join(where, name)
                    st = os.stat(p)
                    rel = os.path.relpath(p, root)
                    h.update(f"{rel}:{st.st_mtime_ns}:{st.st_size}".encode())
        except OSError:
            pass
        return h.hexdigest()

    @classmethod
    def execute(cls, sheet_categories=None, project_path="",
                order=None) -> io.NodeOutput:
        cats = list(sheet_categories or [])
        if not cats:
            raise ValueError("no sheets to prompt for — wire the Auto Packer's "
                             "sheet_categories output into this node")
        project = cls._project(project_path, order)
        if not project:
            raise ValueError(
                "this order names no project folder, so there is nowhere to "
                "read the prompt book from — set project_path on this node")
        per_sheet = resolve_category_prompts(project, cats)
        # Deduped by TEXT, not by category: two types that share a prompt file
        # are one document to read. Order follows first appearance.
        seen, unique = set(), []
        for text in per_sheet:
            if text not in seen:
                seen.add(text)
                unique.append(text)
        return io.NodeOutput(unique, per_sheet)


class SymbioticaOrderAssets(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaOrderAssets",
            display_name="Symbiotica Order Assets",
            category="symbiotica/pipeline",
            description="The event's assets as ONE ITEM PER ASSET, grouped by "
                        "asset type: every decoration, then every food. Wire "
                        "the three lists into one render lane and ComfyUI runs "
                        "it once per asset, in that order — no loop node, and "
                        "no second copy of the lane per type. Use this, not the "
                        "Auto Packer, when the render works from a dataset "
                        "reference rather than a packed sheet.",
            inputs=[
                Order.Input("order"),
                io.String.Input("category", default="",
                                tooltip="One asset type, or All. Narrow to "
                                        "Food while you tune food, without "
                                        "spending a render on decorations."),
            ],
            outputs=[
                io.String.Output(display_name="asset_names",
                                 is_output_list=True,
                                 tooltip="One per asset — wire into Save "
                                         "Image's filename_prefix so each "
                                         "render lands under its own name."),
                io.String.Output(display_name="categories",
                                 is_output_list=True,
                                 tooltip="Asset type per asset. Feed Category "
                                         "Prompts and Dataset Reference from "
                                         "this — all three stay aligned."),
                io.String.Output(display_name="client_prompts",
                                 is_output_list=True,
                                 tooltip="The client's brief per asset, "
                                         "verbatim from the order sheet."),
                # Appended: links address an output by slot index, so a new
                # slot in the middle would re-point every saved workflow.
                io.String.Output(display_name="save_paths",
                                 is_output_list=True,
                                 tooltip="month/feature/category/asset per "
                                         "asset — wire into a save node's "
                                         "filename prefix and the run files "
                                         "itself, e.g. 'October/Mini 1 — "
                                         "Ghostly Goodies/Food - 3 stages/"
                                         "Spookies'."),
            ],
        )

    @classmethod
    def execute(cls, order=None, category="") -> io.NodeOutput:
        if not isinstance(order, dict) or "assets" not in order:
            raise ValueError("wire an Order Specs (or a Reference Browser) "
                             "into 'order'")
        items = assets_by_category(order, category)
        if not items:
            # A pick that matches nothing is a different mistake from an empty
            # event, and the fix is different too — so say which one it is, and
            # what this event actually holds.
            present = sorted({str(a.get("category", "") or "").strip()
                              for a in order.get("assets", []) or []
                              if str(a.get("assetName", "") or "").strip()})
            want = (category or "All").strip() or "All"
            if want != "All" and present:
                raise ValueError(
                    f"no {want!r} assets in {order.get('feature', '')!r} — "
                    f"this event holds: {', '.join(present)}")
            raise ValueError(
                f"the event {order.get('feature', '')!r} has no named assets — "
                "pick a feature on the Order Specs node")
        return io.NodeOutput([a["assetName"] for a in items],
                             [a["category"] for a in items],
                             [a["prompt"] for a in items],
                             save_paths(order, items))


class SymbioticaSaveRender(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaSaveRender",
            display_name="Symbiotica Save Render",
            category="symbiotica/pipeline",
            description="Save each render under its asset name AND record what "
                        "produced it: the architect prompt's hash, the version "
                        "of every rule block that composed it, the reference "
                        "drawn and the seed. Without that record, 'this one "
                        "came out flat' has nothing to attach to — the prompt "
                        "may have changed twice since. The record goes in the "
                        "PNG and in <project>/prompts/renders.jsonl.",
            # The whole run at once: the log is appended per RUN, so writing it
            # per image would interleave with other nodes' saves.
            is_input_list=True,
            inputs=[
                io.Image.Input("images"),
                io.String.Input("asset_names", force_input=True,
                                tooltip="Order Assets' asset_names — names the "
                                        "file and the record."),
                io.String.Input("categories", force_input=True),
                io.String.Input("system_prompts", force_input=True,
                                tooltip="Category Prompts' PER-ASSET output, "
                                        "the text actually sent."),
                io.String.Input("client_prompts", optional=True),
                io.String.Input("reference_names", optional=True),
                io.Int.Input("seed", default=0, min=0,
                             max=0xFFFFFFFFFFFFFFF, optional=True),
                io.String.Input("subfolder", default="renders"),
                io.String.Input("project_path", default=""),
                Order.Input("order", optional=True),
            ],
            outputs=[
                io.String.Output(display_name="files", is_output_list=True),
                io.String.Output(display_name="prompt_shas",
                                 is_output_list=True,
                                 tooltip="The architect prompt's hash per "
                                         "image — the handle feedback uses to "
                                         "name which prompt it is about."),
            ],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, images=None, asset_names=None, categories=None,
                system_prompts=None, client_prompts=None, reference_names=None,
                seed=0, subfolder="renders", project_path="",
                order=None) -> io.NodeOutput:
        import datetime

        from PIL import Image
        from PIL.PngImagePlugin import PngInfo

        from .provenance import append_records, build_record

        one = SymbioticaCategoryPrompts._one
        imgs = list(images or [])
        if not imgs:
            raise ValueError("nothing to save — wire the render's images in")
        names = list(asset_names or [])
        cats = list(categories or [])
        sys_prompts = list(system_prompts or [])
        briefs = list(client_prompts or [])
        refs = list(reference_names or [])
        project = SymbioticaCategoryPrompts._project(project_path, order)
        ord_dict = one(order, {}) or {}

        def at(seq, i, default=""):
            # Index-aligned lists, but a shorter one is a wiring mistake worth
            # surviving: a missing label must not lose the image.
            return seq[i] if i < len(seq) else default

        out_root = os.path.join(folder_paths.get_output_directory(),
                                str(one(subfolder, "renders")).strip()
                                or "renders")
        os.makedirs(out_root, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        files, shas, records = [], [], []
        for i, tensor in enumerate(imgs):
            name = str(at(names, i, f"render-{i + 1}")).strip() or f"render-{i + 1}"
            cat = str(at(cats, i))
            prompt = str(at(sys_prompts, i))
            rec = build_record(
                project_path=project, asset_name=name, category=cat,
                system_prompt=prompt, client_prompt=str(at(briefs, i)),
                reference=str(at(refs, i)), seed=int(one(seed, 0) or 0),
                feature=str(ord_dict.get("feature", "")),
                month=str(ord_dict.get("month", "")))
            fname = f"{slugify(name) or 'render'}-{stamp}-{i + 1:02d}.png"
            rec["image"] = fname
            meta = PngInfo()
            # In the PNG as well as the log: an image that travels out of the
            # project keeps its own provenance, and a log lost to a sync
            # conflict does not orphan every render before it.
            meta.add_text("symbiotica_provenance", json.dumps(rec))
            arr = tensor[0] if hasattr(tensor, "ndim") and tensor.ndim == 4 \
                else tensor
            img = Image.fromarray(
                (arr.cpu().numpy() * 255).clip(0, 255).astype(np.uint8))
            img.save(os.path.join(out_root, fname), pnginfo=meta)
            files.append(fname)
            shas.append(rec["prompt_sha"])
            records.append(rec)
        if project:
            append_records(project, records, timestamp=stamp)
        return io.NodeOutput(files, shas)


class SymbioticaPromptBook(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaPromptBook",
            display_name="Symbiotica Prompt Book",
            category="symbiotica/pipeline",
            description="Read and edit the architect prompts without leaving "
                        "the graph. The shared game rules in "
                        "<project>/prompts/_rules/ apply to every asset type — "
                        "edit lighting once and all types pick it up on the "
                        "next queue. The per-type blocks below hold only what "
                        "differs. Editing here needs no restart: the Category "
                        "Prompts node re-reads the book when a file changes.",
            inputs=[
                io.String.Input("project_path", default="",
                                tooltip="Client project folder holding the "
                                        "prompt book. Filled in from the order "
                                        "when one is wired."),
                Order.Input("order", optional=True),
            ],
            outputs=[
                io.String.Output(display_name="project",
                                 tooltip="The project whose book this panel is "
                                         "editing — wire into Category Prompts "
                                         "so both read the same one."),
            ],
        )

    @classmethod
    def execute(cls, project_path="", order=None) -> io.NodeOutput:
        project = SymbioticaCategoryPrompts._project([project_path], [order])
        if not project:
            raise ValueError(
                "no project folder to read the prompt book from — wire an "
                "order, or set project_path")
        return io.NodeOutput(project)


class SymbioticaDatasetReference(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaDatasetReference",
            display_name="Symbiotica Dataset Reference",
            category="symbiotica/pipeline",
            description="One style reference per asset, drawn at random from "
                        "<project>/dataset/<Asset Type>/ — the existing game "
                        "art for that type. The draw is PER TYPE, so every food "
                        "item in a run shares one food reference and the batch "
                        "comes out consistent. Seeded, so the same seed redraws "
                        "the same references and bumping it picks new ones.",
            # The whole list at once: the draw is per TYPE, which cannot be
            # decided from one asset's category in isolation.
            is_input_list=True,
            inputs=[
                io.String.Input("categories", force_input=True,
                                tooltip="Asset type per asset — the Order "
                                        "Assets node's `categories` output."),
                io.Int.Input("seed", default=0, min=0, max=0xFFFFFFFFFFFFFFF,
                             control_after_generate=True,
                             tooltip="Which reference each type draws. Same "
                                     "seed = same references; bump it to draw "
                                     "again. A type keeps its own pick when "
                                     "another type joins the order."),
                io.String.Input("folder", default="dataset",
                                tooltip="Folder under the project holding the "
                                        "per-type reference folders."),
                io.String.Input("project_path", default="",
                                tooltip="Client project folder. Filled in from "
                                        "the order when one is wired."),
                Order.Input("order", optional=True),
            ],
            outputs=[
                io.Image.Output(display_name="images", is_output_list=True,
                                tooltip="The reference for asset i — index-"
                                        "aligned with Order Assets. Wire into "
                                        "the LLM/Gemini image input."),
                io.String.Output(display_name="reference_names",
                                 is_output_list=True,
                                 tooltip="Filename of the reference drawn for "
                                         "asset i, so a good draw can be "
                                         "traced back to its file."),
                # Appended: links address an output by slot index, so a new
                # slot in the middle would re-point every saved workflow.
                io.String.Output(display_name="cell_boxes",
                                 is_output_list=True,
                                 tooltip="Where each asset sits inside this "
                                         "type's packed sheet, as JSON — wire "
                                         "into Slice Cells to cut a generated "
                                         "sheet back into one image per role. "
                                         "Comes from the same dataset folder "
                                         "the reference was drawn from, so it "
                                         "describes the grid the render was "
                                         "asked to reproduce."),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, categories=None, seed=0, folder="dataset",
                           project_path="", order=None):
        # Widgets only — linked inputs arrive as None here (see Category
        # Prompts). Hash the folder listing so adding or removing a reference
        # redraws, and never raise: a raise becomes NaN and re-bills every
        # descendant on each queue press.
        one = SymbioticaCategoryPrompts._one
        root = dataset_dir(str(one(project_path)).strip(),
                           str(one(folder, "dataset")).strip() or "dataset")
        h = hashlib.sha256(f"{root}:{one(seed, 0)}".encode())
        try:
            for cat in sorted(os.listdir(root)):
                sub = os.path.join(root, cat)
                if not os.path.isdir(sub):
                    continue
                h.update(cat.encode())
                for name in sorted(os.listdir(sub)):
                    h.update(name.encode())
        except OSError:
            pass
        return h.hexdigest()

    @classmethod
    def execute(cls, categories=None, seed=0, folder="dataset",
                project_path="", order=None) -> io.NodeOutput:
        one = SymbioticaCategoryPrompts._one
        cats = list(categories or [])
        if not cats:
            raise ValueError("no assets to reference — wire the Order Assets "
                             "node's `categories` output into this node")
        project = SymbioticaCategoryPrompts._project(project_path, order)
        if not project:
            raise ValueError(
                "this order names no project folder, so there is nowhere to "
                "read the dataset from — set project_path on this node")
        paths, names = pick_reference_per_category(
            project, cats, int(one(seed, 0) or 0),
            str(one(folder, "dataset")).strip() or "dataset")
        from PIL import Image
        images = []
        for p in paths:
            with Image.open(p) as im:
                images.append(_pil_to_tensor(im.convert("RGB")))
        # Per ASSET, not per type: the boxes ride the same index as the images
        # so a lane that fans out over assets can cut each render without
        # re-deriving which type it came from. Cheap to repeat — the lookup is
        # memoised per type below, and the payload is a few hundred bytes.
        from .sheet_cells import boxes_for_category
        per_type = {}
        boxes = []
        for cat in cats:
            key = str(cat).strip()
            if key not in per_type:
                per_type[key] = json.dumps(boxes_for_category(project, key))
            boxes.append(per_type[key])
        return io.NodeOutput(images, names, boxes)


class SymbioticaSliceCells(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaSliceCells",
            display_name="Symbiotica Slice Cells",
            category="symbiotica/pipeline",
            description="Cuts a generated sheet back into one image per asset, "
                        "on the grid the dataset was packed to. Wire the Dataset "
                        "Reference node's `cell_boxes` in and every asset type "
                        "cuts itself — a food sheet gives prep/ready/serving, a "
                        "chair sheet gives its four rotations — with no crop "
                        "coordinates to type and nothing to rewire when the run "
                        "changes type. `roles` names each cell, so an edit can "
                        "address 'serving' rather than 'the third one'.",
            inputs=[
                io.Image.Input("image",
                               tooltip="The generated sheet to cut."),
                io.String.Input("cell_boxes", force_input=True,
                                tooltip="The Dataset Reference node's "
                                        "`cell_boxes` output."),
                io.Int.Input("inset", default=1, min=0, max=256,
                             tooltip="Pixels to shrink every cell by. The boxes "
                                     "are the grid the render was ASKED to hit, "
                                     "so a pixel or two of slack keeps the "
                                     "background out of a cell when the render "
                                     "lands slightly off."),
                io.Int.Input("output_size", default=0, min=0, max=8192,
                             tooltip="Resize each cell to this square, or 0 to "
                                     "keep it at its cut size."),
            ],
            outputs=[
                io.Image.Output(display_name="cells", is_output_list=True,
                                tooltip="One image per cell, in reading order."),
                io.String.Output(display_name="roles", is_output_list=True,
                                 tooltip="What each cell holds — 'prep', "
                                         "'serving', a rotation — index-aligned "
                                         "with `cells`."),
            ],
        )

    @classmethod
    def execute(cls, image=None, cell_boxes="", inset=1,
                output_size=0) -> io.NodeOutput:
        from .sheet_cells import crop_regions
        if image is None or not len(image):
            raise ValueError("wire the generated sheet into 'image'")
        try:
            boxes = json.loads(str(cell_boxes or "").strip() or "[]")
        except ValueError:
            boxes = None
        if not isinstance(boxes, list) or not boxes:
            raise ValueError(
                "no cell boxes — wire the Dataset Reference node's "
                "`cell_boxes` output into this node. An empty list also means "
                "the asset type has no packing rule recorded for it yet.")

        height, width = int(image.shape[1]), int(image.shape[2])
        regions = crop_regions(boxes, width, height, inset)
        if not regions:
            raise ValueError(
                f"none of the {len(boxes)} cells fall inside this "
                f"{width}x{height} image — it is not the sheet these boxes "
                f"describe")

        size = max(0, int(output_size or 0))
        cells, roles = [], []
        for role, left, top, right, bottom in regions:
            cell = image[:, top:bottom, left:right, :]
            if size:
                # Channels-first for interpolate, and back again. Antialiased so
                # a cell shrunk to a working size does not alias the crisp
                # game-art edges this pack exists to produce.
                cell = torch.nn.functional.interpolate(
                    cell.movedim(-1, 1), size=(size, size),
                    mode="bicubic", antialias=True,
                    align_corners=False).movedim(1, -1).clamp(0.0, 1.0)
            cells.append(cell)
            roles.append(role)
        return io.NodeOutput(cells, roles)


class SymbioticaTemplateLibrary(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaTemplateLibrary",
            display_name="Symbiotica Template Library",
            category="symbiotica/pipeline",
            description="Browse the Auto Packer templates saved for a project "
                        "(as folders, with sheet thumbnails). `kind` picks the "
                        "pool: Reference = universal style guides built from the "
                        "game's asset library, Order = the wired month's design "
                        "guides. 'use' one → its full recipe on 'template' (wire "
                        "into the Auto Packer to re-pack or edit). CHECK any → "
                        "their saved sheets + prompts stream out of "
                        "'sheets'/'sheet_prompts' with no re-render.",
            # `kind` and `month` are APPENDED, never inserted: ComfyUI restores
            # a saved workflow's widget values positionally, so putting a new
            # input ahead of `selected`/`checked` would drop the saved template
            # pick onto the wrong widget and silently lose it. Added last, an
            # older workflow's three values still land on the three original
            # inputs and the new ones keep their defaults.
            inputs=[
                io.String.Input("project_path", default="",
                                tooltip="The client project folder — its "
                                        "templates are browsed"),
                io.String.Input("selected", default="",
                                tooltip="Which saved template to output as a "
                                        "recipe — set by the browser's 'use'"),
                io.String.Input("checked", default="[]",
                                tooltip="Templates whose saved sheets/prompts to "
                                        "emit — JSON list, set by the browser's "
                                        "checkboxes"),
                io.String.Input("kind", default="All",
                                tooltip="Which pool to browse: Reference "
                                        "(universal, from the asset library), "
                                        "Order (this month's order), or All"),
                io.String.Input("month", default="",
                                tooltip="Which month's order templates to browse "
                                        "— only used when kind is Order/All "
                                        "(empty = the project's first month)"),
            ],
            outputs=[
                PackTemplateWire.Output(display_name="template"),
                io.Image.Output(display_name="sheets", is_output_list=True,
                                tooltip="Saved sheets of the CHECKED templates "
                                        "(no re-render)"),
                io.String.Output(display_name="sheet_prompts",
                                 is_output_list=True,
                                 tooltip="Client prompts index-aligned with "
                                         "sheets"),
            ],
        )

    _NEUTRAL = {"order": {}, "preset": {}, "settings": {}, "category": "",
                "overrides": {}, "name": "", "kind": "", "month": ""}

    @classmethod
    def _dirs(cls, project_path, kind="", month=""):
        from .pack_library import pack_dirs
        out = os.path.join(folder_paths.get_output_directory(), "templates")
        # Project dirs first so a filed template shadows a fallback of the same
        # name; output/templates covers read-only-project + no-project saves.
        # str(month or "") because a workflow saved before these inputs existed
        # can restore them as None, which slugify would choke on.
        return pack_dirs(project_path, cls._kind(kind), str(month or ""), out)

    @staticmethod
    def _kind(kind):
        """The widget's label ("All"/"Order"/"Reference") as a pool id; "" =
        every pool."""
        from .pack_library import KINDS
        k = str(kind or "").strip().lower()
        return k if k in KINDS else ""

    @classmethod
    def execute(cls, project_path="", kind="All", month="", selected="",
                checked="[]") -> io.NodeOutput:
        _register_project(project_path)
        from .pack_library import (collect_checked, load_pack_template_dirs)
        dirs = cls._dirs(project_path, kind, month)
        for d in dirs:
            _register_refs_root(d)
        # (1) The recipe bundle for the single 'use'-selected template. Missing
        # or unselected → a NEUTRAL bundle, never a raise: this node may sit
        # beside a live Order Specs (the order wins), and it also drives the
        # sheets output below — a raise would kill both.
        bundle = dict(cls._NEUTRAL)
        if (selected or "").strip():
            tpl = load_pack_template_dirs(dirs, selected)
            if tpl:
                order = tpl.get("order") or {}
                if order.get("refsRoot"):
                    _register_refs_root(order["refsRoot"])
                bundle = {
                    "order": order,
                    "preset": tpl.get("preset") or {},
                    "settings": tpl.get("settings") or {},
                    "category": tpl.get("category", "All"),
                    "overrides": tpl.get("overrides") or {},
                    "name": tpl.get("name", ""),
                    # Which pool it came from, so a re-pack saved from the Auto
                    # Packer goes back to the same one.
                    "kind": tpl.get("kind", ""),
                    "month": str(tpl.get("month", "")),
                }
        # (2) Saved sheets + prompts for the CHECKED templates — loaded from
        # disk, no re-pack. Falls back to the 'use'-selected template when
        # nothing is checked, so a wired Preview shows something.
        try:
            names = json.loads(checked) if checked else []
        except (ValueError, TypeError):
            names = []
        if not (isinstance(names, list) and names):
            names = [selected.strip()] if (selected or "").strip() else []
        sheets, prompts = [], []
        from PIL import Image
        for path, prompt in collect_checked(dirs, names):
            try:
                with Image.open(path) as im:
                    tensor = _pil_to_tensor(im.copy())
            except (OSError, ValueError):
                continue
            sheets.append(tensor)
            prompts.append(prompt)
        if not sheets:
            # ComfyUI maps a downstream node over an is_output_list output and
            # does v[-1] on an EMPTY list → IndexError (crashes a wired Preview
            # / Show Text). Emit one small placeholder so the graph degrades
            # gracefully when nothing is checked or selected.
            sheets = [torch.full((1, 8, 8, 3), 0.5)]
            prompts = ["(no template checked — tick a box or press 'use')"]
        return io.NodeOutput(bundle, sheets, prompts)


class SymbioticaEventSpecs(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaEventSpecs",
            display_name="Symbiotica Event Specs",
            category="symbiotica/pipeline",
            description="Pick one event from the parsed order and emit its "
                        "spec — template groups with per-asset canvas, plot, "
                        "client prompt, and reference files.",
            inputs=[
                OrderEvents.Input("events"),
                io.String.Input("feature", default="",
                                tooltip="Event to work on (the order's Feature "
                                        "column, e.g. \"QE 2\")"),
            ],
            outputs=[EventSpec.Output(display_name="event spec")],
            hidden=[io.Hidden.unique_id],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, events, feature) -> io.NodeOutput:
        spec = event_spec(events["events"], feature.strip())
        spec = {**spec, "refsRoot": events.get("refsRoot", "")}
        _push("symbiotica.event_spec",
              {"node_id": cls.hidden.unique_id, "feature": spec["feature"],
               "templates": [{"template": g["template"], "category": g["category"],
                              "canvas": g["canvas"], "assets": len(g["assets"])}
                             for g in spec["templates"]]})
        return io.NodeOutput(spec, ui=ui.PreviewText(spec_wire_json(spec)))


class SymbioticaTemplateBuilder(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaTemplateBuilder",
            display_name="Symbiotica Template Builder",
            category="symbiotica/pipeline",
            description="Compose a template sheet from an event spec: either "
                        "prefill strips from the client's reference images, or "
                        "a grid of existing catalog art for one template group.",
            inputs=[
                EventSpec.Input("spec"),
                io.Combo.Input("mode", options=["prefill_from_specs", "catalog_grid"],
                               default="prefill_from_specs"),
                io.String.Input("group", default="", optional=True,
                                tooltip="Template group slug (required for "
                                        "catalog_grid; filters prefill when set)"),
                io.String.Input("assets_root", default="", optional=True,
                                tooltip="Game asset catalog folder "
                                        "(catalog_grid mode)"),
                io.String.Input("sheet_name", default="", optional=True,
                                tooltip="Saved sheet name (defaults to the "
                                        "group / feature slug)"),
                io.Combo.Input("preset_model", options=_MODELS,
                               default="qwen-image"),
                io.Combo.Input("resolution", options=_RESOLUTIONS, default="1K"),
                io.Combo.Input("aspect_ratio", options=_ASPECTS, default="1:1"),
                io.Int.Input("max_width", default=2048, min=64, max=8192,
                             optional=True, advanced=True,
                             tooltip="Sheet width when preset_model=custom"),
                io.Int.Input("max_height", default=2048, min=64, max=8192,
                             optional=True, advanced=True),
                io.Combo.Input("algorithm", options=["shelf", "maxrects", "grid"],
                               default="shelf"),
                io.Boolean.Input("distribute_by_folder", default=True),
                io.Int.Input("padding", default=0, min=0, max=512, optional=True,
                             advanced=True),
                io.Int.Input("border", default=0, min=0, max=512, optional=True,
                             advanced=True),
                io.Int.Input("grid_cell", default=0, min=0, max=4096, optional=True,
                             advanced=True),
                io.Int.Input("columns", default=1, min=0, max=64, optional=True,
                             advanced=True),
                io.String.Input("background", default="#808080", optional=True,
                                tooltip="Hex fill; empty = transparent"),
            ],
            outputs=[
                Template.Output(display_name="template"),
                io.Image.Output(display_name="sheet"),
                io.String.Output(display_name="bundle_json"),
            ],
            hidden=[io.Hidden.unique_id],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, spec, mode, group="", assets_root="", sheet_name="",
                preset_model="qwen-image", resolution="2K", aspect_ratio="1:1",
                max_width=2048, max_height=2048, algorithm="shelf",
                distribute_by_folder=True, padding=0, border=0, grid_cell=0,
                columns=1, background="#808080") -> io.NodeOutput:
        groups = spec["templates"]
        group = group.strip()
        preset = (None if preset_model == "custom"
                  else {"model": preset_model, "tier": resolution, "ar": aspect_ratio})
        if preset is not None and preset_dims(preset) is None:
            model = next((m for m in MODEL_PRESETS if m["id"] == preset_model), None)
            raise ValueError(
                f'{preset_model} does not support {resolution} @ {aspect_ratio} — '
                f'valid tiers: {", ".join(model["tiers"])}; '
                f'aspect ratios: {", ".join(model["aspectRatios"])}'
                if model else f'unknown preset model "{preset_model}"'
            )
        settings = PackSettings(
            algorithm=algorithm, preset=preset, max_width=max_width,
            max_height=max_height, padding=padding, border=border,
            grid_cell=grid_cell, distribute_by_folder=distribute_by_folder,
            columns=columns, background=background.strip(),
        )

        if mode == "catalog_grid":
            picked = next((g for g in groups if g["template"] == group), None)
            if picked is None:
                have = ", ".join(g["template"] for g in groups)
                raise ValueError(
                    f'group "{group}" is not in the event spec (have: {have})')
            if not assets_root.strip():
                raise ValueError("catalog_grid mode needs assets_root "
                                 "(the game's existing asset folder)")
            sheet, regions, sheet_w, sheet_h = build_catalog_sheet(
                picked, assets_root.strip())
            template_name = picked["template"]
            assets = picked["assets"]
        else:
            if group:
                groups = [g for g in groups if g["template"] == group]
                if not groups:
                    raise ValueError(f'group "{group}" is not in the event spec')
            assets = [a for g in groups for a in g["assets"] if a["refFiles"]]
            if not assets:
                raise ValueError(
                    "no assets with reference files to prefill — check the "
                    "Order Read project folder's month refs")
            from .texture_pack import effective_max
            dims = effective_max(settings)
            sheet_w, sheet_h = dims["w"], dims["h"]
            sheet, regions, overflow = build_prefill_sheet(
                assets, spec.get("refsRoot", ""), sheet_w, sheet_h, settings)
            if overflow:
                print(f"[Symbiotica] template overflow (stacked below): {overflow}")
            template_name = group or f"{slugify(spec['feature'])}-specs"

        name = sheet_name.strip() or template_name
        rel = save_sheet(sheet, regions, name, folder_paths.get_output_directory(),
                         meta={"template": template_name})

        refs_root = (spec.get("refsRoot", "") or "").rstrip("/")
        ref_paths = (
            {a["assetName"]: [f"{refs_root}/{f}" for f in a["refFiles"]]
             for a in assets}
            if refs_root else {}
        )
        bundle = {
            "kind": "template",
            "template": template_name,
            "sheetFile": rel,
            "templateSize": {"w": sheet.width, "h": sheet.height},
            "regions": regions,
            "refPaths": ref_paths,
        }
        tensor = _pil_to_tensor(sheet)
        return io.NodeOutput(bundle, tensor, json.dumps(bundle, indent=1),
                             ui=ui.PreviewImage(tensor, cls=cls))


MAX_REGION_REFS = 10


def _region_crop(region, task_sheet):
    """One region's rect cut out of the task sheet, snapped to the formula
    resolution — the crop's own pixels drift with rounding and fit-scaling."""
    th = int(task_sheet.shape[1])
    tw = int(task_sheet.shape[2])
    x0 = max(0, min(tw - 1, round(region["x"] * tw)))
    y0 = max(0, min(th - 1, round(region["y"] * th)))
    x1 = max(x0 + 1, min(tw, round((region["x"] + region["w"]) * tw)))
    y1 = max(y0 + 1, min(th, round((region["y"] + region["h"]) * th)))
    crop = task_sheet[:1, y0:y1, x0:x1, :]
    want_w, want_h = target_ref_size(region, x1 - x0, y1 - y0)
    if (want_w, want_h) != (x1 - x0, y1 - y0):
        crop = torch.nn.functional.interpolate(
            crop[..., :3].permute(0, 3, 1, 2),
            size=(want_h, want_w), mode="nearest-exact",
        ).permute(0, 2, 3, 1)
    return crop[..., :3]


def _sheet_client_prompts(png_path):
    """The client prompts for one saved sheet, built from its .json sidecar's
    regions (the same "row N / Prep) … Ready) … Serving)" text the whole-order
    `prompts` output uses, but scoped to this sheet). Empty when the sidecar is
    missing or unreadable."""
    sidecar = os.path.splitext(png_path)[0] + ".json"
    try:
        with open(sidecar) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return ""
    regions = data.get("regions") if isinstance(data, dict) else None
    return build_client_prompts(regions) if isinstance(regions, list) else ""


def _load_selected_sheets(selected_json):
    """The ticked sheets as two index-aligned lists: the sheet IMAGE (one tensor
    each, for a Save Image / img2img batch) and that sheet's client PROMPTS (for
    Show Text). A sheet joins both lists only if its PNG loads, so `sheets` and
    `sheet_prompts` stay paired — sheets[i] is the picture for sheet_prompts[i]."""
    from PIL import Image as PILImage
    try:
        files = json.loads(selected_json or "[]")
    except (ValueError, TypeError):
        files = []
    images, prompts = [], []
    base = folder_paths.get_output_directory()
    for rel in files if isinstance(files, list) else []:
        if not isinstance(rel, str) or not rel:
            continue
        path = os.path.join(base, *rel.split("/"))
        try:
            img = PILImage.open(path)
            img.load()
        except OSError:
            continue
        images.append(_pil_to_tensor(img))
        prompts.append(_sheet_client_prompts(path))
    return images, prompts


def _layout_outputs(bundle, task_tensor, sheet_batch, sheet_prompts):
    """The editor's LLM-facing tail: skeleton, sheet size, the selected-sheet
    batch + its per-sheet prompts, and per-region crops.

    Image 1 is the sheet being edited, so the references number from 2 — the
    same order the Regional Prompt Builder feeds them to the edit node in.
    """
    regions = sorted(bundle.get("regions", []), key=lambda r: r.get("zIndex", 0))
    size = bundle.get("templateSize", {})
    width = int(size.get("w") or task_tensor.shape[2])
    height = int(size.get("h") or task_tensor.shape[1])
    crops = [_region_crop(r, task_tensor) for r in regions]
    ref_numbers = {r.get("id"): i + 2 for i, r in enumerate(regions)}
    skeleton = build_skeleton(regions, width, height, ref_numbers) if regions else ""
    prompts = build_client_prompts(regions) if regions else ""
    gray = torch.full((1, 8, 8, 3), 0.5)
    refs = [crops[i] if i < len(crops) else gray
            for i in range(MAX_REGION_REFS)]
    return (skeleton, prompts, width, height, sheet_batch, sheet_prompts, *refs)


class SymbioticaTemplateEditor(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaTemplateEditor",
            display_name="Symbiotica Template Editor",
            category="symbiotica/pipeline",
            description="Point at one client project folder (with orders/ and "
                        "reference-assets/), pick a month and event, and build "
                        "the region sheet — order, layout, and editor in one "
                        "node. Emits a base sheet + task sheet + the layout "
                        "skeleton and client prompts.",
            inputs=[
                # The node reads the order itself: one project folder + a month.
                # Both are advanced: the node face is the Template Editor button
                # only, and the editor's own rail sets the project + month (they
                # persist back here, hidden, so a queued run still resolves the
                # order).
                io.String.Input("project_path", default="", advanced=True,
                                tooltip="The client project folder — the one "
                                        "that contains orders/ and "
                                        "reference-assets/"),
                io.String.Input("month", default="", advanced=True,
                                tooltip="Which month's order to build (the "
                                        ".xlsx files under orders/)"),
                # Optional legacy inputs: a wired order still works, but the
                # project folder above needs no upstream node.
                OrderEvents.Input("events", optional=True, advanced=True,
                                  tooltip="Legacy: the whole order from an Order "
                                          "Read node (else read from project + "
                                          "month here)"),
                EventSpec.Input("spec", optional=True, advanced=True,
                                tooltip="Legacy: one event's spec from Event "
                                        "Specs (ignored when project/events set)"),
                io.String.Input("feature", default="", advanced=True,
                                tooltip="Which event the editor is building "
                                        "(set by the editor's Event selector)"),
                io.String.Input("selected_sheets", default="[]", advanced=True,
                                tooltip="JSON list of saved sheets ticked in the "
                                        "editor's grid — emitted on the 'sheets' "
                                        "output (managed by the editor)"),
                io.String.Input("assignments", default="{}", multiline=True,
                                advanced=True,
                                tooltip="JSON: task asset name -> catalog rel "
                                        "path (managed by the node UI)"),
                io.String.Input("group", default="", optional=True,
                                advanced=True,
                                tooltip="Template group slug filter (empty = "
                                        "all groups with refs)"),
                io.String.Input("sheet_name", default="", optional=True,
                                advanced=True),
                io.Combo.Input("preset_model", options=_MODELS,
                               default="qwen-image", advanced=True),
                io.Combo.Input("resolution", options=_RESOLUTIONS, default="1K",
                               advanced=True),
                io.Combo.Input("aspect_ratio", options=_ASPECTS, default="1:1",
                               advanced=True),
                io.Int.Input("max_width", default=2048, min=64, max=8192,
                             optional=True, advanced=True,
                             tooltip="Sheet width when preset_model=custom"),
                io.Int.Input("max_height", default=2048, min=64, max=8192,
                             optional=True, advanced=True),
                io.Combo.Input("algorithm", options=["shelf", "maxrects", "grid"],
                               default="shelf", advanced=True),
                io.Boolean.Input("distribute_by_folder", default=True,
                                 advanced=True),
                io.String.Input("background", default="#808080", optional=True,
                                advanced=True,
                                tooltip="Hex fill; empty = transparent"),
                io.String.Input("sheet_file", default="", optional=True,
                                advanced=True,
                                tooltip="Saved editor sheet (managed by the "
                                        "editor)"),
                io.String.Input("regions_json", default="[]", multiline=True,
                                optional=True, advanced=True),
                io.String.Input("scene_prompt", default="", multiline=True,
                                optional=True, advanced=True),
            ],
            outputs=[
                Template.Output(display_name="template"),
                io.Image.Output(display_name="base sheet"),
                io.Image.Output(display_name="task sheet"),
                io.String.Output(display_name="bundle_json"),
                io.String.Output(
                    display_name="skeleton",
                    tooltip="The layout facts for an LLM to turn into the edit "
                            "prompt: one numbered element per region with its "
                            "box_2d placement, reference image number, and the "
                            "client's brief. Carries no framing of its own — "
                            "the LLM's system prompt owns that."),
                io.String.Output(
                    display_name="prompts",
                    tooltip="The order's client prompts, one recipe per row "
                            "(\"row 1\\nPrep) … Ready) … Serving) …\") — the "
                            "text the recipe/grid workflow feeds its LLM "
                            "alongside the sheet."),
                io.Int.Output(display_name="width"),
                io.Int.Output(display_name="height"),
                io.Image.Output(
                    display_name="sheets", is_output_list=True,
                    tooltip="The saved sheets ticked in the editor's grid, as a "
                            "batch — wire to Save Image, or use each as an "
                            "img2img base. Downstream runs once per sheet."),
                io.String.Output(
                    display_name="sheet_prompts", is_output_list=True,
                    tooltip="Client prompts for each ticked sheet, 1:1 with "
                            "`sheets` (same order). Wire to Show Text next to "
                            "`sheets`→Save Image: one save + one prompt block per "
                            "sheet, however many you ticked (food, decorations, "
                            "appliances…)."),
                # Per-region task-sheet crops, for the Regional Prompt
                # Builder's ref_N sockets. The browser trims the tail to the
                # template's region count. `sheets` sits BEFORE these so the
                # bridge's ref_N tail-trim never removes it.
                *(io.Image.Output(
                    display_name=f"ref_{n}",
                    tooltip=f"Region {n}'s reference crop from the task sheet")
                  for n in range(1, 11)),
            ],
            hidden=[io.Hidden.unique_id],
            is_output_node=True,
        )

    @staticmethod
    def _event_spec_of(events_list, refs_root, feature):
        feat = (feature or "").strip() or (
            events_list[0].get("feature", "") if events_list else "")
        try:
            resolved = event_spec(events_list, feat)
        except ValueError:
            resolved = event_spec(events_list, events_list[0].get("feature", ""))
        return {**resolved, "refsRoot": refs_root}

    @classmethod
    def _resolve_spec(cls, spec, events, project_path, month, feature):
        """One event's spec + the sprite-catalog root. The node reads the order
        itself from project+month; a wired spec/events still works; with none of
        them it's an empty spec for a from-scratch template."""
        if project_path and project_path.strip():
            from .project_layout import resolve_month
            r = resolve_month(project_path.strip(), (month or "").strip())
            if r["order_path"]:
                loaded = load_order(r["order_path"], r["refs_path"])
                return (cls._event_spec_of(loaded["events"], r["refs_path"], feature),
                        r["assets_root"])
        if spec:
            return spec, ""
        if events and events.get("events"):
            return (cls._event_spec_of(events["events"],
                                       events.get("refsRoot", ""), feature),
                    events.get("assetsRoot", ""))
        return {"feature": "", "templates": [], "refsRoot": ""}, ""

    @classmethod
    def execute(cls, assignments, project_path="", month="",
                events=None, spec=None,
                feature="", selected_sheets="[]", group="", sheet_name="",
                preset_model="qwen-image", resolution="1K", aspect_ratio="1:1",
                max_width=2048, max_height=2048, algorithm="shelf",
                distribute_by_folder=True, background="#808080",
                sheet_file="", regions_json="[]",
                scene_prompt="") -> io.NodeOutput:
        # One path in: the sprite catalog is the project's reference-assets/.
        spec, assets_root = cls._resolve_spec(spec, events, project_path, month,
                                              feature)
        sheet_batch, sheet_prompts = _load_selected_sheets(selected_sheets)
        if sheet_file.strip():
            return cls._execute_editor_sheet(
                spec, sheet_file.strip(), regions_json, scene_prompt,
                sheet_name, background, sheet_batch, sheet_prompts)
        assets_root = assets_root.strip()
        if not assets_root or not os.path.isdir(assets_root):
            raise ValueError(
                "no sprite catalog — set project_path to a folder that has a "
                "reference-assets/ subfolder (this path is for building fresh "
                "from the catalog; the usual editor flow saves a sheet_file "
                "instead)")
        try:
            assigned = json.loads(assignments or "{}")
        except json.JSONDecodeError as e:
            raise ValueError(f"assignments is not valid JSON: {e}")
        if not isinstance(assigned, dict):
            raise ValueError("assignments must be a JSON object "
                             "(task asset name -> catalog rel path)")

        preset = (None if preset_model == "custom"
                  else {"model": preset_model, "tier": resolution, "ar": aspect_ratio})
        if preset is not None and preset_dims(preset) is None:
            model = next((m for m in MODEL_PRESETS if m["id"] == preset_model), None)
            raise ValueError(
                f'{preset_model} does not support {resolution} @ {aspect_ratio} — '
                f'valid tiers: {", ".join(model["tiers"])}; '
                f'aspect ratios: {", ".join(model["aspectRatios"])}'
                if model else f'unknown preset model "{preset_model}"'
            )
        settings = PackSettings(
            algorithm=algorithm, preset=preset, max_width=max_width,
            max_height=max_height, distribute_by_folder=distribute_by_folder,
            background=background.strip(),
        )

        groups = spec["templates"]
        group = group.strip()
        if group:
            groups = [g for g in groups if g["template"] == group]
            if not groups:
                have = ", ".join(g["template"] for g in spec["templates"])
                raise ValueError(
                    f'group "{group}" is not in the event spec (have: {have})')
        assets = [a for g in groups for a in g["assets"] if a["refFiles"]]
        if not assets:
            raise ValueError("no assets with reference files — check the "
                             "Order Read project folder's month refs")

        from .texture_pack import effective_max
        dims = effective_max(settings)
        sheet_w, sheet_h = dims["w"], dims["h"]
        base_sheet, task_sheet, regions, overflow = build_paired_sheets(
            assets, spec.get("refsRoot", ""), assets_root, assigned,
            sheet_w, sheet_h, settings)
        if overflow:
            print(f"[Symbiotica] template overflow (stacked below): {overflow}")

        _register_refs_root(assets_root)
        template_name = group or f"{slugify(spec['feature'])}-specs"
        name = sheet_name.strip() or template_name
        rel = save_sheet(task_sheet, regions, name,
                         folder_paths.get_output_directory(),
                         meta={"template": template_name})
        base_rel = save_sheet(base_sheet, regions, f"{name}-base",
                              folder_paths.get_output_directory(),
                              meta={"template": template_name, "role": "base"})

        refs_root = (spec.get("refsRoot", "") or "").rstrip("/")
        ref_paths = (
            {a["assetName"]: [f"{refs_root}/{f}" for f in a["refFiles"]]
             for a in assets}
            if refs_root else {}
        )
        bundle = {
            "kind": "template",
            "template": template_name,
            "sheetFile": rel,
            "baseSheetFile": base_rel,
            "templateSize": {"w": task_sheet.width, "h": task_sheet.height},
            "regions": regions,
            "refPaths": ref_paths,
        }
        if scene_prompt.strip():
            bundle["scenePrompt"] = scene_prompt.strip()
        base_tensor = _pil_to_tensor(base_sheet)
        task_tensor = _pil_to_tensor(task_sheet)
        return io.NodeOutput(bundle, base_tensor, task_tensor,
                             json.dumps(bundle, indent=1),
                             *_layout_outputs(bundle, task_tensor, sheet_batch,
                                              sheet_prompts),
                             ui=ui.PreviewImage(base_tensor, cls=cls))

    @classmethod
    def _execute_editor_sheet(cls, spec, sheet_file, regions_json, scene_prompt,
                              sheet_name, background, sheet_batch,
                              sheet_prompts) -> io.NodeOutput:
        """Editor-saved sheet branch: the saved PNG IS the base sheet and the
        editor's regions ARE the layout — no assets_root or packing needed.
        The task sheet is repainted from the client refs on the same layout."""
        from PIL import Image
        path = os.path.join(folder_paths.get_output_directory(),
                            *sheet_file.split("/"))
        try:
            base_sheet = Image.open(path)
            base_sheet.load()
        except OSError:
            raise ValueError(f"could not read sheet {path} — re-save from the "
                             "template editor")
        base_sheet = base_sheet.convert("RGBA")
        try:
            regions = json.loads(regions_json or "[]")
        except json.JSONDecodeError as e:
            raise ValueError(f"regions_json is not valid JSON: {e}")
        if not isinstance(regions, list):
            raise ValueError("regions_json must be a JSON list")

        sheet_w, sheet_h = base_sheet.width, base_sheet.height
        task_sheet = _paint_background(sheet_w, sheet_h, background.strip())
        _draw_task_refs(task_sheet, regions, spec.get("refsRoot", ""),
                        sheet_w, sheet_h)

        template_name = slugify(
            os.path.splitext(os.path.basename(sheet_file))[0]) or "template"
        name = sheet_name.strip() or template_name
        rel = save_sheet(task_sheet, regions, f"{name}-task",
                         folder_paths.get_output_directory(),
                         meta={"template": template_name, "role": "task"})

        bundle = {
            "kind": "template",
            "template": template_name,
            "sheetFile": rel,
            "baseSheetFile": sheet_file,
            "templateSize": {"w": sheet_w, "h": sheet_h},
            "regions": regions,
            "refPaths": {},
        }
        if scene_prompt.strip():
            bundle["scenePrompt"] = scene_prompt.strip()
        base_tensor = _pil_to_tensor(base_sheet)
        task_tensor = _pil_to_tensor(task_sheet)
        return io.NodeOutput(bundle, base_tensor, task_tensor,
                             json.dumps(bundle, indent=1),
                             *_layout_outputs(bundle, task_tensor, sheet_batch,
                                              sheet_prompts),
                             ui=ui.PreviewImage(base_tensor, cls=cls))


class SymbioticaRegionalPrompt(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaRegionalPrompt",
            display_name="Symbiotica Regional Prompt",
            category="symbiotica/pipeline",
            description="Turn a template bundle into a layout-aware edit prompt "
                        "(ERPK Regional Prompt Builder format): numbered box_2d "
                        "placements per region, base sheet as image 1, per-region "
                        "reference images numbered from 2. Wires into ERPK's "
                        "Gemini Image Edit (image_refs) or any edit node via the "
                        "refs batch.",
            inputs=[
                Template.Input("template"),
                io.Image.Input("base_sheet",
                               tooltip="The editor's base sheet — becomes image 1"),
                io.Image.Input("task_sheet", optional=True,
                               tooltip="The editor's task sheet; region_crop refs "
                                       "are cut from it"),
                io.String.Input("scene_prompt", default="", multiline=True,
                                optional=True,
                                tooltip="Overrides the bundle's scene prompt"),
                io.Combo.Input("ref_mode",
                               options=["region_crop", "ref_files", "none"],
                               default="region_crop",
                               tooltip="Per-region reference: crop of the task "
                                       "sheet at the region's box, the first "
                                       "checked ref file, or none"),
                io.Boolean.Input("placement_markers", default=True,
                                 optional=True,
                                 tooltip="Draw a labeled colored dot at each "
                                         "region's center on image 1 and cite "
                                         "it in that region's prompt line "
                                         "(set-of-mark). The edit model places "
                                         "each element on its dot and paints "
                                         "the dot out — the strongest lever "
                                         "against position drift."),
                io.Boolean.Input("enhance_prompts", default=True,
                                 optional=True,
                                 tooltip="Rewrite each region's client text "
                                         "into a dense production prompt "
                                         "(Claude, grounded in the task "
                                         "sheet). Feeds the desc_N outputs "
                                         "and this node's own prompt. Key: "
                                         "Settings > Symbiotica > "
                                         "ANTHROPIC_API_KEY."),
                io.String.Input("llm_model", default="claude-sonnet-5",
                                optional=True),
                io.String.Input("extra_rules", default="", multiline=True,
                                optional=True,
                                tooltip="Appended to the enhancer's system "
                                        "prompt — game/style conventions"),
                io.Int.Input("llm_seed", default=0, min=0, max=2**31 - 1,
                             optional=True,
                             tooltip="Change to re-roll the enhanced prompts "
                                     "(otherwise they cache with the "
                                     "template)"),
                io.String.Input("api_key", default="", optional=True,
                                tooltip="Overrides Settings > Symbiotica > "
                                        "ANTHROPIC_API_KEY"),
                io.Combo.Input("ref_framing",
                               options=["restyle_to_base", "reproduce_exact"],
                               default="restyle_to_base", optional=True,
                               tooltip="How the prompt cites each reference: "
                                       "restyle_to_base = take the DESIGN "
                                       "from the reference but redraw it in "
                                       "image 1's art style (design "
                                       "transfer); reproduce_exact = copy "
                                       "the reference item as-is (ERPK "
                                       "parity)"),
            ],
            hidden=[io.Hidden.unique_id],
            outputs=[
                io.String.Output(display_name="prompt"),
                io.Image.Output(display_name="image"),
                io.Custom("ERPK_IMAGE_REFS").Output(
                    display_name="image_refs",
                    tooltip="Per-region refs in region order — connect to an "
                            "ERPK image edit node's image_refs"),
                io.Image.Output(display_name="refs_batch",
                                tooltip="Same refs as one IMAGE batch (padded to "
                                        "a common size) for generic edit nodes"),
                io.Custom("BOUNDING_BOX").Output(display_name="bboxes"),
                io.Mask.Output(display_name="masks"),
                io.Int.Output(display_name="width"),
                io.Int.Output(display_name="height"),
                # desc_N/ref_N come in pairs so the browser can trim the tail
                # down to the template's region count: an output's slot index
                # is what the API prompt cites, so only whole trailing pairs
                # can go without remapping what the remaining wires mean.
                *[out for n in range(1, 11) for out in (
                    io.String.Output(
                        display_name=f"desc_{n}",
                        tooltip=f"Region {n}'s prompt (enhanced when "
                                "enhance_prompts is on) — for ERPK desc_N "
                                "sockets"),
                    io.Image.Output(
                        display_name=f"ref_{n}",
                        tooltip=f"Region {n}'s reference crop — for ERPK "
                                "ref_N sockets"),
                )],
            ],
        )

    @classmethod
    def execute(cls, template, base_sheet, task_sheet=None, scene_prompt="",
                ref_mode="region_crop", placement_markers=True,
                enhance_prompts=True, llm_model="claude-sonnet-5",
                extra_rules="", llm_seed=0, api_key="",
                ref_framing="restyle_to_base") -> io.NodeOutput:
        regions = sorted(template.get("regions", []),
                         key=lambda r: r.get("zIndex", 0))
        if not regions:
            raise ValueError("the template bundle has no regions — build/save "
                             "one in the Template Editor first")
        height = int(base_sheet.shape[1])
        width = int(base_sheet.shape[2])

        # Per-region reference images, numbered from 2 (base sheet is image 1).
        refs: list[torch.Tensor] = []
        ref_numbers: dict[str, int] = {}

        def add_ref(region, tensor):
            refs.append(tensor)
            ref_numbers[region.get("id")] = len(refs) + 1

        if ref_mode == "region_crop":
            if task_sheet is None:
                raise ValueError("ref_mode=region_crop needs the task_sheet "
                                 "input (wire the editor's task sheet output)")
            th = int(task_sheet.shape[1])
            tw = int(task_sheet.shape[2])
            for region in regions:
                x0 = max(0, min(tw - 1, round(region["x"] * tw)))
                y0 = max(0, min(th - 1, round(region["y"] * th)))
                x1 = max(x0 + 1, min(tw, round((region["x"] + region["w"]) * tw)))
                y1 = max(y0 + 1, min(th, round((region["y"] + region["h"]) * th)))
                crop = task_sheet[:1, y0:y1, x0:x1, :]
                # Snap the ref to the formula resolution — n_cells x (canvas x
                # scale) — instead of trusting the crop's sheet pixels (rounding,
                # fit-scaled layouts, and old baked gaps all drift).
                want_w, want_h = target_ref_size(region, x1 - x0, y1 - y0)
                if (want_w, want_h) != (x1 - x0, y1 - y0):
                    crop = torch.nn.functional.interpolate(
                        crop[..., :3].permute(0, 3, 1, 2),
                        size=(want_h, want_w), mode="nearest-exact",
                    ).permute(0, 2, 3, 1)
                add_ref(region, crop)
        elif ref_mode == "ref_files":
            from PIL import Image as PILImage
            ref_paths = template.get("refPaths", {})
            for region in regions:
                paths = ref_paths.get(region.get("name") or "", [])
                if not paths:
                    continue
                try:
                    img = PILImage.open(paths[0])
                    img.load()
                except OSError:
                    continue
                add_ref(region, _pil_to_tensor(img))

        # Generic batch: one tensor must share one size, so smaller crops are
        # CENTERED on a canvas filled with the sheet's background color (its
        # top-left pixel) — no black bars, previews read like mini-sheets.
        # image_refs keeps every crop at its true size.
        if refs:
            max_h = max(int(r.shape[1]) for r in refs)
            max_w = max(int(r.shape[2]) for r in refs)
            fill = base_sheet[0, 0, 0, :3]
            padded = []
            for r in refs:
                canvas = fill.expand(1, max_h, max_w, 3).clone().to(r.dtype)
                rh, rw = int(r.shape[1]), int(r.shape[2])
                oy = (max_h - rh) // 2
                ox = (max_w - rw) // 2
                canvas[:, oy:oy + rh, ox:ox + rw, :] = r[..., :3]
                padded.append(canvas)
            refs_batch = torch.cat(padded, dim=0)
        else:
            refs_batch = torch.zeros((0, height, width, 3))

        masks = torch.zeros((len(regions), height, width))
        for i, region in enumerate(regions):
            x0 = max(0, min(width, round(region["x"] * width)))
            y0 = max(0, min(height, round(region["y"] * height)))
            x1 = max(x0, min(width, round((region["x"] + region["w"]) * width)))
            y1 = max(y0, min(height, round((region["y"] + region["h"]) * height)))
            masks[i, y0:y1, x0:x1] = 1.0

        # Set-of-mark dots: drawn on the image 1 output and cited per prompt
        # line, so the edit model gets a pixel target for every box_2d.
        marks = assign_markers(regions) if placement_markers else {}
        image_out = base_sheet
        if marks:
            from PIL import Image as PILImage
            frames = []
            for i in range(int(base_sheet.shape[0])):
                arr = (base_sheet[i, ..., :3].cpu().numpy() * 255.0)
                pil = PILImage.fromarray(arr.clip(0, 255).astype(np.uint8))
                pil = draw_placement_markers(pil, regions, marks)
                frames.append(_pil_to_tensor(pil))
            image_out = torch.cat(frames, dim=0).to(base_sheet.dtype)

        # Per-region prompts: the client text, or its LLM rewrite (dense
        # production language grounded in the task sheet). Both feed the
        # desc_N outputs AND this node's own assembled prompt.
        def raw_desc(region):
            name = (region.get("name") or "").strip()
            desc = (region.get("desc") or "").strip()
            return f"{name}: {desc}" if name and desc else (desc or name)

        descs = [raw_desc(r) for r in regions]
        if enhance_prompts:
            key = (api_key or "").strip()
            if not key:
                from .._settings import resolve_key
                key = resolve_key(["ANTHROPIC_API_KEY"]) or ""
            if not key:
                raise ValueError("enhance_prompts needs an Anthropic API key "
                                 "— set Settings > Symbiotica > "
                                 "ANTHROPIC_API_KEY, or turn the toggle off.")
            from ..llm_api import call_claude_api
            ref_sheet = task_sheet if task_sheet is not None else base_sheet
            system = ENHANCER_SYSTEM_PROMPT
            if extra_rules.strip():
                system = f"{system}\nAdditional rules:\n{extra_rules.strip()}"
            if llm_seed:
                system = f"{system}\n(variation {llm_seed})"
            task = build_enhancer_task(
                regions, int(ref_sheet.shape[2]), int(ref_sheet.shape[1]))
            response = call_claude_api(
                api_key=key, model=llm_model, prompt=task,
                system_prompt=system, image=ref_sheet[:1],
                max_tokens=4096, temperature=1.0)
            enhanced = parse_region_prompts(response, max(len(regions), 10))
            if not any(enhanced[:len(regions)]):
                raise ValueError("the prompt enhancer returned no parseable "
                                 f"prompts — response starts: {response[:300]!r}")
            descs = [enhanced[i] or descs[i] for i in range(len(regions))]

        scene = scene_prompt.strip() or (template.get("scenePrompt") or "").strip()
        prompt_regions = [
            {**r, "name": "", "desc": descs[i]} for i, r in enumerate(regions)
        ] if enhance_prompts else regions
        framing = "restyle" if ref_framing == "restyle_to_base" else "reproduce"
        prompt = build_regional_prompt(scene, width, height, prompt_regions,
                                       ref_numbers, marks, framing)
        bboxes = regions_to_pixel_bboxes(regions, width, height)

        # Let the browser bridge mirror the final per-region prompts into a
        # linked ERPK builder's canvas, so hovering a region shows what will
        # actually run instead of the raw spreadsheet text.
        _push("symbiotica.region_descs",
              {"node_id": cls.hidden.unique_id, "descs": descs})

        desc_outs = (descs + [""] * 10)[:10]
        gray = torch.full((1, 8, 8, 3), 0.5)
        ref_outs = [refs[i][..., :3] if i < len(refs) else gray
                    for i in range(10)]
        pair_outs = [out for n in range(10)
                     for out in (desc_outs[n], ref_outs[n])]
        return io.NodeOutput(prompt, image_out, refs, refs_batch, bboxes,
                             masks, width, height, *pair_outs,
                             ui=ui.PreviewText(prompt))


class SymbioticaTemplatePrompt(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaTemplatePrompt",
            display_name="Symbiotica Template Prompt",
            category="symbiotica/pipeline",
            description="Turn a template bundle into an edit prompt for the "
                        "image nodes: one numbered instruction per region, "
                        "using each asset's client prompt.",
            inputs=[
                Template.Input("template"),
                io.String.Input("scene", default="", multiline=True, optional=True,
                                tooltip="Overall scene/style instruction "
                                        "prepended to the region list"),
            ],
            outputs=[io.String.Output(display_name="prompt")],
        )

    @classmethod
    def execute(cls, template, scene="") -> io.NodeOutput:
        lines = []
        if scene.strip():
            lines.append(scene.strip())
        lines.append(
            "The image is a sprite template sheet. Replace the content of each "
            "listed region with a new game asset, keeping position and size; "
            "keep everything outside the regions unchanged.")
        for region in sorted(template["regions"], key=lambda r: r.get("zIndex", 0)):
            name = region.get("name") or region["id"]
            desc = (region.get("desc") or "").strip()
            asset_type = region.get("assetType") or ""
            suffix = f" ({asset_type})" if asset_type else ""
            lines.append(f"{region.get('zIndex', 0) + 1}. \"{name}\"{suffix}: "
                         f"{desc or 'match the sheet style'}")
        return io.NodeOutput("\n".join(lines))


class SymbioticaRegionalEdit(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaRegionalEdit",
            display_name="Symbiotica Regional Edit",
            category="symbiotica/pipeline",
            description="Design-transfer the template one region at a time: "
                        "for each region, the base-sheet crop (style + layout) "
                        "and the task-sheet crop (client design) go to Gemini "
                        "as a single small edit, and the result is pasted back "
                        "at the region's exact pixel box. Sidesteps the "
                        "fidelity ceiling of one giant whole-sheet edit — no "
                        "markers, no position drift by construction.",
            inputs=[
                Template.Input("template"),
                io.Image.Input("base_sheet",
                               tooltip="The editor's base sheet — style source "
                                       "and the canvas regions are pasted into"),
                io.Image.Input("task_sheet",
                               tooltip="The editor's task sheet — each "
                                       "region's design reference is cropped "
                                       "from it"),
                io.Combo.Input("model",
                               options=["gemini-3.1-flash-image",
                                        "gemini-2.5-flash-image"],
                               default="gemini-3.1-flash-image"),
                io.String.Input("style", default="", multiline=True,
                                optional=True,
                                tooltip="Style directive for every region. "
                                        "Empty = 'the exact graphic style of "
                                        "image 1' (the base sheet's art)"),
                io.Float.Input("temperature", default=1.0, min=0.0, max=2.0,
                               step=0.1, optional=True),
                io.Int.Input("seed", default=0, min=-1, max=2**31 - 1,
                             control_after_generate="randomize",
                             tooltip="-1 sends no seed; any change re-runs "
                                     "the node"),
                io.String.Input("api_key", default="", optional=True,
                                tooltip="Overrides Settings > Symbiotica > "
                                        "GEMINI_API_KEY"),
            ],
            outputs=[
                io.Image.Output(display_name="sheet",
                                tooltip="Base sheet with every region "
                                        "replaced by its edited crop"),
                io.String.Output(display_name="report",
                                 tooltip="Per-region status — failed regions "
                                         "keep their placeholder art"),
            ],
        )

    @classmethod
    def execute(cls, template, base_sheet, task_sheet, model,
                style="", temperature=1.0, seed=0, api_key="") -> io.NodeOutput:
        regions = sorted(template.get("regions", []),
                         key=lambda r: r.get("zIndex", 0))
        if not regions:
            raise ValueError("the template bundle has no regions — build/save "
                             "one in the Template Editor first")
        key = (api_key or "").strip()
        if not key:
            from .._settings import resolve_key
            key = resolve_key(["GEMINI_API_KEY", "GOOGLE_API_KEY"]) or ""
        if not key:
            raise ValueError("No Gemini API key. Set it in Settings > "
                             "Symbiotica > GEMINI_API_KEY (or pass api_key).")
        try:
            from google import genai
            from google.genai import types as genai_types
        except ImportError as exc:
            raise ValueError("google-genai is not installed in this ComfyUI "
                             "environment (pip install google-genai)") from exc
        from PIL import Image as PILImage

        client = genai.Client(api_key=key)
        height = int(base_sheet.shape[1])
        width = int(base_sheet.shape[2])
        th = int(task_sheet.shape[1])
        tw = int(task_sheet.shape[2])

        def to_pil(tensor):
            arr = (tensor[..., :3].cpu().numpy() * 255.0).clip(0, 255)
            return PILImage.fromarray(arr.astype(np.uint8))

        sheet = base_sheet[:1].clone()
        report = []
        for region in regions:
            name = region.get("name") or region.get("id") or "?"
            bx0, by0, bx1, by1 = region_pixel_box(region, width, height)
            tx0, ty0, tx1, ty1 = region_pixel_box(region, tw, th)
            base_crop = to_pil(base_sheet[0, by0:by1, bx0:bx1, :])
            ref_crop = to_pil(task_sheet[0, ty0:ty1, tx0:tx1, :])
            prompt = region_edit_prompt(region, style)
            config = genai_types.GenerateContentConfig(
                temperature=temperature,
                response_modalities=["IMAGE"],
                seed=seed if seed >= 0 else None,
            )
            edited = None
            error = ""
            for _attempt in range(2):
                try:
                    resp = client.models.generate_content(
                        model=model,
                        contents=[base_crop, ref_crop, prompt],
                        config=config)
                    edited = _first_inline_image(resp)
                    if edited is not None:
                        break
                    error = "no image in response"
                except Exception as exc:  # noqa: BLE001 — per-region isolation
                    error = str(exc)
            if edited is None:
                report.append(f"FAIL {name}: {error[:200]}")
                continue
            if edited.size != (bx1 - bx0, by1 - by0):
                edited = edited.resize((bx1 - bx0, by1 - by0),
                                       PILImage.LANCZOS)
            patch = _pil_to_tensor(edited).to(sheet.dtype)
            sheet[:, by0:by1, bx0:bx1, :] = patch
            report.append(f"OK   {name}: {bx1 - bx0}x{by1 - by0}")
        return io.NodeOutput(sheet, "\n".join(report),
                             ui=ui.PreviewImage(sheet, cls=cls))


def _first_inline_image(resp):
    """The first inline image in a Gemini response as PIL RGB, or None."""
    import base64
    import io as _io
    from PIL import Image as PILImage
    for candidate in getattr(resp, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            inline = getattr(part, "inline_data", None)
            data = getattr(inline, "data", None)
            if not data:
                continue
            if isinstance(data, str):
                data = base64.b64decode(data)
            return PILImage.open(_io.BytesIO(data)).convert("RGB")
    return None


class SymbioticaRefsSplit(io.ComfyNode):
    """Fan the Regional Prompt's image_refs list out to individual IMAGE
    outputs, so each ref can feed one ref_N socket on ERPK's Regional Prompt
    Builder (which binds references per canvas region, one socket each)."""

    MAX_REFS = 10  # mirrors ERPK's ref_N socket family cap

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaRefsSplit",
            display_name="Symbiotica Refs Split",
            category="symbiotica/pipeline",
            description="Splits ERPK_IMAGE_REFS into ref_1..ref_10 IMAGE "
                        "outputs (region order). Missing slots emit a small "
                        "gray placeholder.",
            inputs=[
                io.Custom("ERPK_IMAGE_REFS").Input(
                    "image_refs",
                    tooltip="The Symbiotica Regional Prompt's image_refs "
                            "output"),
            ],
            outputs=[
                io.Image.Output(display_name=f"ref_{n}")
                for n in range(1, cls.MAX_REFS + 1)
            ],
        )

    @classmethod
    def execute(cls, image_refs) -> io.NodeOutput:
        refs = list(image_refs or [])
        outs = []
        for i in range(cls.MAX_REFS):
            if i < len(refs):
                outs.append(refs[i][..., :3])
            else:
                outs.append(torch.full((1, 8, 8, 3), 0.5))
        return io.NodeOutput(*outs)


class SymbioticaPromptsSplit(io.ComfyNode):
    """Fan an LLM's enhanced per-region prompt list out to individual STRING
    outputs, one per region, so each can feed a desc_N socket on ERPK's
    Regional Prompt Builder (which overrides that region's description)."""

    MAX_DESCS = 10  # mirrors ERPK's desc_N socket family cap

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaPromptsSplit",
            display_name="Symbiotica Prompts Split",
            category="symbiotica/pipeline",
            description="Splits an enhanced-prompts list (strict JSON array "
                        "or numbered lines, region order) into desc_1..desc_10 "
                        "STRING outputs. Empty slots leave the region's "
                        "original description untouched downstream.",
            inputs=[
                io.String.Input("prompts", default="", multiline=True,
                                tooltip="LLM output: JSON array of one "
                                        "prompt per region (region order), "
                                        "or numbered lines"),
            ],
            outputs=[
                io.String.Output(display_name=f"desc_{n}")
                for n in range(1, cls.MAX_DESCS + 1)
            ],
        )

    @classmethod
    def execute(cls, prompts="") -> io.NodeOutput:
        return io.NodeOutput(*parse_region_prompts(prompts, cls.MAX_DESCS))


class SymbioticaPromptEnhancer(io.ComfyNode):
    """One-node LLM enhancer: template + task reference sheet in, one dense
    production prompt per region out on desc_1..desc_10 — wired straight into
    ERPK Regional Prompt Builder's desc_N override sockets. The Anthropic call,
    request framing, and response parsing all live server-side, so there is no
    system-prompt/user-message wiring to get wrong."""

    MAX_DESCS = 10  # mirrors ERPK's desc_N socket family cap

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaPromptEnhancer",
            display_name="Symbiotica Prompt Enhancer",
            category="symbiotica/pipeline",
            description="Rewrites each template region's client text into a "
                        "dense production prompt (Claude, grounded in the "
                        "task reference sheet). desc_N outputs plug into "
                        "ERPK's desc_N sockets; prompts_json shows the raw "
                        "list. Key: Settings > Symbiotica > "
                        "ANTHROPIC_API_KEY.",
            inputs=[
                Template.Input("template"),
                io.Image.Input("task_sheet",
                               tooltip="The editor's task sheet — the "
                                       "designs the LLM looks at per region"),
                io.String.Input("model", default="claude-sonnet-5",
                                optional=True),
                io.String.Input("extra_rules", default="", multiline=True,
                                optional=True,
                                tooltip="Appended to the enhancer's system "
                                        "prompt — game/style conventions, "
                                        "bans, vocabulary"),
                io.Int.Input("max_tokens", default=4096, min=256, max=16384,
                             optional=True),
                io.Int.Input("seed", default=0, min=-1, max=2**31 - 1,
                             control_after_generate="randomize",
                             tooltip="Any change re-runs the node"),
                io.String.Input("api_key", default="", optional=True,
                                tooltip="Overrides Settings > Symbiotica > "
                                        "ANTHROPIC_API_KEY"),
            ],
            outputs=[
                *(io.String.Output(display_name=f"desc_{n}")
                  for n in range(1, cls.MAX_DESCS + 1)),
                io.String.Output(display_name="prompts_json",
                                 tooltip="The parsed prompt list, for "
                                         "preview/debugging"),
            ],
        )

    @classmethod
    def execute(cls, template, task_sheet, model="claude-sonnet-5",
                extra_rules="", max_tokens=4096, seed=0,
                api_key="") -> io.NodeOutput:
        import json as _json

        regions = sorted(template.get("regions", []),
                         key=lambda r: r.get("zIndex", 0))
        if not regions:
            raise ValueError("the template bundle has no regions — build/save "
                             "one in the Template Editor first")
        key = (api_key or "").strip()
        if not key:
            from .._settings import resolve_key
            key = resolve_key(["ANTHROPIC_API_KEY"]) or ""
        if not key:
            raise ValueError("No Anthropic API key. Set it in Settings > "
                             "Symbiotica > ANTHROPIC_API_KEY (or pass "
                             "api_key).")
        from ..llm_api import call_claude_api

        height = int(task_sheet.shape[1])
        width = int(task_sheet.shape[2])
        task = build_enhancer_task(regions, width, height)
        system = ENHANCER_SYSTEM_PROMPT
        if extra_rules.strip():
            system = f"{system}\nAdditional rules:\n{extra_rules.strip()}"

        response = call_claude_api(
            api_key=key, model=model, prompt=task, system_prompt=system,
            image=task_sheet[:1], max_tokens=max_tokens, temperature=1.0,
            seed=seed)
        descs = parse_region_prompts(response, cls.MAX_DESCS)
        filled = sum(1 for d in descs[:len(regions)] if d)
        if not filled:
            raise ValueError("the LLM returned no parseable prompts — raw "
                             f"response starts: {response[:300]!r}")
        preview = _json.dumps(
            [d for d in descs[:max(len(regions), filled)]], indent=1)
        return io.NodeOutput(*descs, preview, ui=ui.PreviewText(preview))


PIPELINE_NODE_CLASSES = [
    SymbioticaOrderRead,
    SymbioticaOrderSpecs,
    SymbioticaReferenceBrowser,
    SymbioticaRefsFolder,
    SymbioticaModelPreset,
    SymbioticaAutoPackerSettings,
    SymbioticaAutoPacker,
    SymbioticaCategoryPrompts,
    SymbioticaOrderAssets,
    SymbioticaPromptBook,
    SymbioticaSaveRender,
    SymbioticaDatasetReference,
    SymbioticaSliceCells,
    SymbioticaTemplateLibrary,
    SymbioticaEventSpecs,
    SymbioticaTemplateBuilder,
    SymbioticaTemplateEditor,
    SymbioticaRegionalPrompt,
    SymbioticaRegionalEdit,
    SymbioticaRefsSplit,
    SymbioticaPromptsSplit,
    SymbioticaPromptEnhancer,
    SymbioticaTemplatePrompt,
    SymbioticaStudioLibrary,
]
