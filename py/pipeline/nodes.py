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
from .texture_pack import PackSettings

OrderEvents = io.Custom("SYMBIOTICA_ORDER_EVENTS")
EventSpec = io.Custom("SYMBIOTICA_EVENT_SPEC")
Template = io.Custom("SYMBIOTICA_TEMPLATE")
Order = io.Custom("SYMBIOTICA_ORDER")
PackSettingsWire = io.Custom("SYMBIOTICA_PACK_SETTINGS")

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
        op, rp, assets_root = cls._paths(project_path, month)
        if not op:
            raise ValueError(
                "no order file — set the project folder (the one with an "
                "orders/ subfolder of .xlsx files) and pick a month")
        loaded = load_order(op, rp)
        events = loaded["events"]
        if not events:
            raise ValueError(f"no events found in {op}")
        feature = (feature or "").strip() or events[0].get("feature", "")
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
        }
        return io.NodeOutput(payload)


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
                io.Combo.Input("scale", options=["0.5x", "1x", "2x", "3x"],
                               default="1x",
                               tooltip="Enlarge small sprites (the editor's "
                                       "half / x2). Only assets at/under the "
                                       "cutoff grow."),
                io.Combo.Input("scale_max_canvas",
                               options=["128", "256", "512", "1024", "all"],
                               default="256",
                               tooltip="Only scale assets whose canvas max edge "
                                       "is <= this (px) — the asset "
                                       "resolutions. 256 = grow food/128/256, "
                                       "leave 512+ native. 'all' = every size."),
                io.Combo.Input("algorithm",
                               options=["shelf", "maxrects", "grid"],
                               default="shelf",
                               tooltip="Packing algorithm (Shelf/Strip = one "
                                       "strip per row)"),
                io.Boolean.Input("distribute_by_folder", default=True,
                                 tooltip="Lay each asset type's strip on its own "
                                         "row (the editor default)"),
                io.Int.Input("padding", default=0, min=0, max=512,
                             tooltip="Gap between packed strips (px)"),
                io.Int.Input("border", default=0, min=0, max=512,
                             tooltip="Margin around the packed block (px)"),
                io.Boolean.Input("combined_sheet", default=True,
                                 tooltip="Emit the grouped, paginated sheets "
                                         "(the normal output). Off = only the "
                                         "split-variant sheets below."),
                io.Boolean.Input("split_variants", default=False,
                                 tooltip="For directional assets (xlsx rotation "
                                         "2/4), emit one sheet per variant ref "
                                         "(max 3) — mirrored for rotation 2. "
                                         "Food (rotation -) is never split."),
            ],
            outputs=[PackSettingsWire.Output(display_name="settings")],
        )

    _SCALE = {"0.5x": 0.5, "1x": 1.0, "2x": 2.0, "3x": 3.0}

    @classmethod
    def execute(cls, scale="1x", scale_max_canvas="256", algorithm="shelf",
                distribute_by_folder=True, padding=0, border=0,
                combined_sheet=True, split_variants=False) -> io.NodeOutput:
        cutoff = 10 ** 9 if scale_max_canvas == "all" else int(scale_max_canvas)
        return io.NodeOutput({
            "scale": cls._SCALE.get(scale, 1.0),
            "scale_max_canvas": cutoff,
            "algorithm": algorithm,
            "distribute_by_folder": bool(distribute_by_folder),
            "padding": int(padding),
            "border": int(border),
            "combined_sheet": bool(combined_sheet),
            "split_variants": bool(split_variants),
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
                Order.Input("order"),
                io.Int.Input("columns", default=1, min=1, max=4,
                             tooltip="Assets side by side per row"),
                io.Int.Input("max_rows_per_sheet", default=4, min=1, max=12,
                             tooltip="Rows per sheet before starting a new "
                                     "sheet"),
                # Copied verbatim from SymbioticaTemplateEditor's schema so the
                # option lists + defaults match the editor exactly.
                io.Combo.Input("preset_model", options=_MODELS,
                               default="qwen-image"),
                io.Combo.Input("resolution", options=_RESOLUTIONS,
                               default="1K"),
                io.Combo.Input("aspect_ratio", options=_ASPECTS,
                               default="1:1"),
                io.String.Input("background", default="#808080",
                                tooltip="Sheet background color; empty = "
                                        "transparent"),
                io.String.Input("category", default="All",
                                tooltip="One asset type, or All"),
                io.String.Input("overrides", default="{}",
                                tooltip="Per-asset hide/reorder, set from the "
                                        "node's Assets panel (JSON)"),
                PackSettingsWire.Input("settings", optional=True),
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
            ],
        )

    @classmethod
    def execute(cls, order, columns=1, max_rows_per_sheet=4,
                preset_model="qwen-image", resolution="1K", aspect_ratio="1:1",
                background="#808080", category="All", overrides="{}",
                settings=None) -> io.NodeOutput:
        if not isinstance(order, dict) or "assets" not in order:
            raise ValueError("order input must come from Symbiotica Order "
                             "Specs")
        dims = preset_dims({"model": preset_model, "tier": resolution,
                            "ar": aspect_ratio})
        if not dims:
            raise ValueError(
                f"invalid preset: {preset_model} / {resolution} / "
                f"{aspect_ratio}")
        # Optional pack-settings node (unwired = today's defaults: shelf, no
        # distribute, scale 1 — nothing regresses).
        s = settings if isinstance(settings, dict) else {}
        from .autopack import apply_overrides, autopack_order
        try:
            ov = json.loads(overrides) if overrides else {}
        except (ValueError, TypeError):
            ov = {}
        base = slugify(order.get("feature", "")) or "order"
        assets = apply_overrides(order["assets"],
                                 ov if isinstance(ov, dict) else {})
        packed = autopack_order(
            assets, order.get("refsRoot", ""),
            sheet_w=dims["w"], sheet_h=dims["h"], columns=columns,
            max_rows=max_rows_per_sheet, background=background,
            category=(category or "All").strip() or "All", base_name=base,
            scale=s.get("scale", 1.0),
            scale_max_canvas=s.get("scale_max_canvas", 256),
            algorithm=s.get("algorithm", "shelf"),
            distribute_by_folder=s.get("distribute_by_folder", False),
            padding=s.get("padding", 0), border=s.get("border", 0),
            combined_sheet=s.get("combined_sheet", True),
            split_variants=s.get("split_variants", False))
        return io.NodeOutput(
            [_pil_to_tensor(p["image"]) for p in packed],
            [p["prompts"] for p in packed],
            [p["name"] for p in packed],
        )


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
    SymbioticaAutoPackerSettings,
    SymbioticaAutoPacker,
    SymbioticaEventSpecs,
    SymbioticaTemplateBuilder,
    SymbioticaTemplateEditor,
    SymbioticaRegionalPrompt,
    SymbioticaRegionalEdit,
    SymbioticaRefsSplit,
    SymbioticaPromptsSplit,
    SymbioticaPromptEnhancer,
    SymbioticaTemplatePrompt,
]
