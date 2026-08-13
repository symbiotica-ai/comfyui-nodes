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
from .order_sheet import bucket_of, slugify
from .asset_refs import DEFAULT_BACKGROUND
from .order_assets import (assets_by_category, dataset_dir,
                           pick_reference_per_category, save_paths)
from .project_layout import project_root_of
from .prompt_book import (compose_image_prompt, image_dir, prompts_dir,
                          resolve_category_prompts)
from .prompt_store import PromptPathError, read_block, resolve as resolve_block
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

# A step takes a set of images, or the one being worked on.
_PICK_MODES = ["multiple", "single"]
# What a picker fed by another picker shows: that one's approvals, or the files
# saved FROM them. Two different questions — an edit is written after the tick
# is made, so it can never be in the tick set that answers the first.
_SHOW_OPTIONS = ["approved", "edits"]

_RESOLUTIONS = ["0.5K", "1K", "2K", "4K"]
# Derived from the preset table so a new model shows up without editing here.
_MODELS = [m["id"] for m in MODEL_PRESETS] + ["custom"]
_ASPECTS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5",
            "21:9", "4:1", "1:4", "8:1", "1:8"]

# How many blocks a recipe serves. Shared by the Recipe (one output per slot)
# and the Prompt Block (which slot of the recipe it edits) so a wire from
# `text_N` and a `slot` of N cannot mean different things.
SLOT_MAX = 6


def _push(event: str, payload: dict) -> None:
    """Fire-and-forget UI push; absent/failed server must never break execution."""
    try:
        from server import PromptServer
        PromptServer.instance.send_sync(event, payload)
    except Exception:
        pass


def _register_refs_root(path: str) -> None:
    """A folder of reference artwork the graph READS — servable, and watched by
    the change-checks below."""
    try:
        from .routes import register_refs_root
        register_refs_root(path)
    except Exception:
        pass


def _register_served_root(path: str) -> None:
    """A folder the canvas must be able to fetch thumbnails from, which the
    graph also WRITES into — a template save destination, a picker's buffer.
    Servable only: a change-check that watched these would fire on the graph's
    own output and re-bill every descendant (see SymbioticaAssetRefs)."""
    try:
        from .routes import register_root
        register_root(path)
    except Exception:
        pass


def _executed_projects() -> list[str]:
    """Projects a graph execution registered. Empty when routes is unavailable
    — a change-check must degrade, never raise."""
    try:
        from .routes import executed_projects
        return executed_projects()
    except Exception:
        return []


def _reference_roots() -> list[str]:
    """Folders of reference artwork a graph execution registered — an order's
    client references and the sprite catalog. NOT every servable folder: the
    picker buffers and template save folders under ComfyUI's output directory
    are servable too, and the graph writes into them on every render."""
    try:
        from .routes import reference_roots
        return reference_roots()
    except Exception:
        return []


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


def _tensor_to_pil_mask(frame):
    """One MASK frame as an L-mode image. A mask is HxW, but ComfyUI is loose
    about a trailing channel axis, so squeeze one if it is there."""
    from PIL import Image
    arr = frame.detach().cpu().clamp(0.0, 1.0).numpy()
    if arr.ndim == 3 and arr.shape[-1] == 1:
        arr = arr[..., 0]
    return Image.fromarray((arr * 255.0).round().astype(np.uint8), mode="L")


def _tensor_to_pil(frame):
    """One HxWxC frame — NOT a batch — as a PIL image, KEEPING a fourth channel
    as alpha where the frame carries one.

    ComfyUI's IMAGE is conventionally three channels, but a background remover
    hands back four, and converting straight to RGB there discards the very
    thing it was run to produce: the sprite lands on whatever was hiding under
    its transparency, which for this art is black. Anything else — one channel,
    three, or an odd count — becomes RGB as before.

    Clamped before scaling: a frame that came through an upscaler can carry
    values a shade outside 0..1, and uint8 wraps rather than clips, so an
    overshoot of 1.004 would land as a black pixel in the middle of white art.
    """
    from PIL import Image
    arr = frame.detach().cpu().clamp(0.0, 1.0).numpy()
    out = Image.fromarray((arr * 255.0).round().astype(np.uint8))
    keep_alpha = arr.ndim == 3 and arr.shape[-1] == 4
    return out if keep_alpha and out.mode == "RGBA" else out.convert("RGB")


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
            from .project_layout import require_month
            r = require_month(project_path, (month or "").strip())
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
            from .project_layout import require_month
            r = require_month(project_path, (month or "").strip())
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
        h.update((SymbioticaOrderSpecs._guide(project_path) or "").encode())
        return h.hexdigest()

    @classmethod
    def execute(cls, project_path="", month="", feature="") -> io.NodeOutput:
        return io.NodeOutput(build_event_order(project_path, month, feature))


def build_event_order(project_path="", month="", feature=""):
    """The ORDER payload for one event: project + month + feature -> the flat
    asset list every consumer reads.

    Lifted out of Order Specs so Asset Focus can do the same selection without
    a second node in front of it. One implementation, or the two would drift on
    exactly the thing that makes an order identifiable.
    """
    _register_project(project_path)
    op, rp, assets_root = SymbioticaOrderSpecs._paths(project_path, month)
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
        "guide": SymbioticaOrderSpecs._guide(project_path),
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
    return payload


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
                io.String.Output(display_name="names",
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
        # Where the save LANDED, so the canvas can fetch its sheet thumbnails.
        # Served, not watched: the packer writes here.
        _register_served_root(base)
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
        h = hashlib.sha256(b"category-prompts")
        # The project usually arrives on the ORDER wire, and a linked input
        # reads as unset here — the widget alone left this hashing a path that
        # never resolves, so a prompt edit did not bust the cache in exactly
        # the graphs this node was written for. Same fallback as Dataset
        # Reference: the projects executions have registered.
        candidates = [str(cls._one(project_path)).strip()]
        if not candidates[0]:
            candidates = _executed_projects()
        for project in candidates:
            if not project:
                continue
            root = prompts_dir(project)
            h.update(root.encode())
            # RECURSIVE: the shared rules live in prompts/_rules/. Listing one
            # level deep would miss an edited lighting rule entirely — ComfyUI
            # would reuse the cached prompt and the run would render from the
            # old text while the new text sat on disk, which reads as "my edit
            # did nothing". Only `.md` files count: renders.jsonl and the
            # editor's `.bak` files live in the same folder and churn on every
            # run, and hashing them re-billed the LLM each queue press with
            # the prompts untouched.
            try:
                for where, dirs, files in os.walk(root):
                    dirs.sort()
                    for name in sorted(files):
                        if not name.endswith(".md"):
                            continue
                        p = os.path.join(where, name)
                        st = os.stat(p)
                        rel = os.path.relpath(p, root)
                        h.update(
                            f"{rel}:{st.st_mtime_ns}:{st.st_size}".encode())
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


class SymbioticaClientExamples(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaClientExamples",
            display_name="Symbiotica Client Examples",
            category="symbiotica/pipeline",
            description="Several of the client's own briefs as ONE text "
                        "block, for showing an LLM what a client prompt for "
                        "this asset type looks like. Order Assets emits the "
                        "same records as lists, which fans the graph out and "
                        "runs the lane once per asset; this collapses them "
                        "into a single string, so an LLM node downstream runs "
                        "ONCE and sees every example at the same time.",
            inputs=[
                Order.Input("order"),
                io.String.Input("category", default="",
                                tooltip="One asset type, or empty for every "
                                        "type. Narrow it to the type you are "
                                        "writing a prompt block for."),
                io.Int.Input("limit", default=0, min=0, max=50,
                             tooltip="How many briefs to include. 0 keeps "
                                     "every asset of the type; a smaller "
                                     "number keeps the first N and says so in "
                                     "the header."),
            ],
            outputs=[
                io.String.Output(display_name="examples",
                                 tooltip="A header naming the type and how "
                                         "many briefs follow, then the briefs "
                                         "themselves, numbered, verbatim from "
                                         "the order sheet."),
                io.Int.Output(display_name="count",
                              tooltip="How many briefs the text holds."),
            ],
        )

    @classmethod
    def execute(cls, order=None, category="", limit=0) -> io.NodeOutput:
        if not isinstance(order, dict) or "assets" not in order:
            raise ValueError("wire an Order Specs (or a Reference Browser) "
                             "into 'order'")
        want = (category or "All").strip() or "All"
        items = assets_by_category(order, category)
        # An asset with no brief teaches an LLM nothing about the shape of a
        # client prompt, and a blank numbered entry reads as a missing example
        # rather than an empty one. Drop them, and count what is left.
        briefed = [a for a in items if str(a.get("prompt", "") or "").strip()]
        if not briefed:
            present = sorted({str(a.get("category", "") or "").strip()
                              for a in order.get("assets", []) or []
                              if str(a.get("prompt", "") or "").strip()})
            if want != "All" and present:
                raise ValueError(
                    f"no {want!r} asset in {order.get('feature', '')!r} "
                    f"carries a client brief — briefs exist for: "
                    f"{', '.join(present)}")
            raise ValueError(
                f"no asset in {order.get('feature', '')!r} carries a client "
                "brief, so there is no example to show — check the order "
                "sheet's prompt column")
        total = len(briefed)
        kept = briefed[:limit] if limit else briefed
        # Never a silent cap: a text that shows three of eight briefs must say
        # so, or the LLM reading it treats three as the whole population.
        span = (f"the first {len(kept)} of {total}" if len(kept) < total
                else f"all {total}")
        noun = "asset" if want == "All" else f"{want!r} asset"
        if len(kept) != 1:
            noun += "s"
        head = (f"CLIENT EXAMPLES — {span} {noun} the client ordered for "
                f"{order.get('feature', '')!r}, each brief as the client "
                f"wrote it")
        parts = [head]
        for i, a in enumerate(kept, 1):
            name = str(a.get("assetName", "") or "").strip() or "unnamed"
            cat = str(a.get("category", "") or "").strip()
            label = f"{i}. {name}" + (f" — {cat}" if cat and want == "All"
                                      else "")
            parts.append(f"{label}\n{str(a['prompt']).strip()}")
        return io.NodeOutput("\n\n".join(parts), len(kept))


class SymbioticaAssetFocus(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaAssetFocus",
            display_name="Symbiotica Asset Focus",
            category="symbiotica/pipeline",
            description="One asset out of the order, chosen on the node, with "
                        "its whole record on separate outputs. Order Assets "
                        "emits four index-aligned lists and Dataset Reference "
                        "three more, so working on a single asset meant an "
                        "index node per list, all held at the same position by "
                        "hand. The index is applied once, here, and nothing "
                        "downstream has a list to index. Choose nothing and it "
                        "emits the whole event instead, so the same node "
                        "covers both the one-asset iteration loop and a run "
                        "over everything.",
            inputs=[
                # Optional since this node can make its own: month, feature,
                # category and asset are one selection, and splitting it across
                # two nodes meant picking half of it in each.
                Order.Input("order", optional=True),
                io.String.Input("category", default="",
                                tooltip="Narrow the choice to one asset type, "
                                        "or leave empty for every type."),
                io.String.Input("asset", default="",
                                tooltip="Which asset, by name. Set by clicking "
                                        "it on the node; typed names work too. "
                                        "Empty means the first."),
                # APPENDED, and optional. A saved workflow restores widget
                # values BY POSITION, so anything added ahead of `asset` would
                # hand every existing graph the wrong value in every slot.
                io.String.Input("project_path", default="", optional=True,
                                tooltip="The project folder, the one with an "
                                        "orders/ subfolder. Only read when no "
                                        "order is wired in — this node then "
                                        "does the whole selection itself."),
                io.String.Input("month", default="", optional=True),
                io.String.Input("feature", default="", optional=True,
                                tooltip="Which event of that month. Empty "
                                        "means the order's first."),
            ],
            # Lists, but normally of one. A single-element list behaves exactly
            # like a scalar downstream — it runs once — so choosing an asset
            # leaves nothing to index. Choosing none emits every asset instead,
            # and downstream fans out over the whole event.
            outputs=[
                io.String.Output(display_name="asset_name", is_output_list=True),
                io.String.Output(display_name="category", is_output_list=True),
                io.String.Output(display_name="client_prompt",
                                 is_output_list=True),
                io.String.Output(display_name="save_path", is_output_list=True,
                                 tooltip="month/feature/category/asset — the "
                                         "same value Order Assets emits, so a "
                                         "save node and a Pick node's "
                                         "save_path both take it."),
                # Replaces `index` (tail slot, wired nowhere): the order
                # itself, narrowed to each focused asset. One wire feeds
                # Dataset Reference, Asset Refs and Prompt Recipe everything
                # the string fan-out used to carry.
                Order.Output(display_name="order", is_output_list=True,
                             tooltip="The incoming order narrowed to each "
                                     "focused asset — same event, same "
                                     "project, a one-asset assets list. One "
                                     "of these per focused asset, so "
                                     "downstream still runs once per asset."),
                # APPENDED: links are held by slot index, so a new output goes
                # at the end or every saved graph repoints one slot left.
                Order.Output(display_name="event_order",
                             tooltip="The WHOLE event, unnarrowed — what an "
                                     "Order Specs emits. The Auto Packer, "
                                     "Order Assets and the Order Tracker all "
                                     "want the event rather than the asset, "
                                     "and they must not change every time you "
                                     "focus a different one."),
                # APPENDED for the same reason. A NARROWING of the category,
                # not a second one: one category can be drawn two ways —
                # `Food - 3 stages` is a chopping board for a cake and an empty
                # cup on a saucer for a tea — and the client's own Prep) line
                # already says which. Emitted beside the category so the
                # sheets, the dataset folders and the save paths keep seeing
                # the one name the order sheet gives them.
                io.String.Output(display_name="bucket", is_output_list=True,
                                 tooltip="Which sub-kind of its category this "
                                         "asset is — `Drinks` for a Food row "
                                         "whose Prep line is an empty cup, "
                                         "empty for everything else. Wire it "
                                         "into the Prompt Recipe beside "
                                         "`category` and it serves "
                                         "`<category> - <bucket>` when the "
                                         "book has one."),
            ],
            hidden=[io.Hidden.unique_id],
            # An output node so it can be queued on its own. Without that there
            # is no way to run it before anything is wired downstream, and its
            # list of choices only exists once it has run at least once.
            is_output_node=True,
        )

    @classmethod
    def fingerprint_inputs(cls, order=None, category="", asset="",
                           project_path="", month="", feature=""):
        """When this node makes its own order it inherits Order Specs' change
        check — the order file and the references folder move without the graph
        moving. With one WIRED IN, the wire already carries that, and the
        answer must be STABLE: NaN here marks the node permanently dirty, and
        because its outputs feed the string joins and the render lane, every
        queue re-ran the whole graph even with the seed untouched."""
        if not str(project_path or "").strip():
            return hashlib.sha256(
                f"{category}|{asset}".encode()).hexdigest()
        return SymbioticaOrderSpecs.fingerprint_inputs(
            project_path=project_path, month=month, feature=feature)

    @classmethod
    def execute(cls, order=None, category="", asset="",
                project_path="", month="", feature="") -> io.NodeOutput:
        # Its own selection when nothing is wired in: month, feature, category
        # and asset are one act, and doing half of it on another node is what
        # made this two nodes.
        if not isinstance(order, dict) or "assets" not in order:
            if str(project_path or "").strip():
                order = build_event_order(project_path, month, feature)
            else:
                raise ValueError(
                    "set project_path (and month) to read an order here, or "
                    "wire an Order Specs / Reference Browser into 'order'")
        items = assets_by_category(order, category)
        if not items:
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

        # The RAW asset record, by name: `assets_by_category` keeps the four
        # fields a run needs and drops `refFiles`, which both the panel below
        # and the narrowed order at the end read references off.
        raw = {str(a.get("assetName", "") or "").strip(): a
               for a in order.get("assets", []) or []}

        # The panel needs the choices before anything is chosen, and the order
        # arrives on a wire the canvas cannot read. It draws the client's own
        # reference art beside each name, so every ref file goes over with the
        # root they are relative to — the root whoever parsed the order
        # registered, which is what lets the thumbnail route serve out of it.
        _push("symbiotica.focus", {
            "node_id": str(getattr(getattr(cls, "hidden", None),
                                   "unique_id", "")),
            "feature": str(order.get("feature", "")),
            "refs_root": str(order.get("refsRoot", "") or ""),
            "assets": [{"name": a["assetName"], "category": a["category"],
                        "canvas": a.get("canvas", ""),
                        "refs": list(raw.get(a["assetName"], {})
                                     .get("refFiles", []) or [])}
                       for a in items],
        })

        wanted = str(asset or "").strip()
        chosen = list(enumerate(items))
        if wanted:
            names = [a["assetName"] for a in items]
            if wanted not in names:
                # Falling back silently would render the wrong asset under the
                # wrong name and file it in the wrong folder. An event whose
                # assets were renamed must say so.
                raise ValueError(
                    f"no asset called {wanted!r} in "
                    f"{order.get('feature', '')!r} — it holds: "
                    f"{', '.join(names)}")
            index = names.index(wanted)
            chosen = [(index, items[index])]
        # No choice means the whole event, which is what the panel's "all"
        # says: a button that reads "all" and emits one asset is lying about
        # what the node is going to do.
        picked = [item for _, item in chosen]
        # A narrowed order per asset: the whole record on ONE wire, in the
        # shape every order consumer already reads. The RAW asset record goes
        # in — Asset Refs downstream reads references off exactly that key.
        narrowed = [{**order,
                     "assets": [raw.get(i["assetName"], i)]} for i in picked]
        return io.NodeOutput([i["assetName"] for i in picked],
                             [i["category"] for i in picked],
                             [i["prompt"] for i in picked],
                             save_paths(order, picked),
                             narrowed,
                             order,
                             # Re-read rather than taken off the row: an order
                             # parsed before buckets existed carries no key,
                             # and the answer is the same either way.
                             [i.get("bucket") or bucket_of(i.get("prompt", ""))
                              for i in picked])


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

        out_dir = str(one(subfolder, "renders")).strip() or "renders"
        out_root = os.path.join(folder_paths.get_output_directory(), out_dir)
        os.makedirs(out_root, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        files, shas, records, saved = [], [], [], []
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
            saved.append(ui.SavedResult(fname, out_dir, io.FolderType.output))
            shas.append(rec["prompt_sha"])
            records.append(rec)
        if project:
            append_records(project, records, timestamp=stamp)
        # Declared as SAVED, not previewed: the files are already on disk under
        # the output folder, and a preview would write them a second time into
        # temp. Only what a node declares reaches /history, which is the one
        # path a caller outside this machine has to the images — an API client
        # sees a run with no renders at all otherwise, and an edit of one has no
        # parent it can name.
        return io.NodeOutput(files, shas, ui=ui.SavedImages(saved))


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
                io.String.Output(display_name="project_path",
                                 tooltip="The project whose book this panel is "
                                         "editing — wire into any node's "
                                         "project_path so both read the same "
                                         "one."),
                io.String.Output(display_name="image_prompt",
                                 tooltip="The blocks in <project>/prompts/"
                                         "_image/, joined in filename order — "
                                         "the style, light and camera rules the "
                                         "IMAGE model needs. Prefer Prompt "
                                         "Recipe's image_prompt, which is the "
                                         "same text with version picks; this "
                                         "output stays for older graphs."),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, project_path="", order=None):
        # An edited image block must re-fire the image node, and ComfyUI would
        # otherwise serve the string it cached on the first queue. Same shape
        # and same caveats as Category Prompts: only WIDGET values are real
        # here, so the wired order cannot be read, and this must never raise —
        # a raise sets is_changed to NaN, which folds into every descendant's
        # cache key and re-bills the image model on every queue.
        h = hashlib.sha256(b"prompt-book")
        # Same wire blindness and the same fallback as Category Prompts: with
        # the project delivered by the order, the widget is empty and the
        # listing below was dead. And `.md` only — a `.bak` written by the
        # panel's save must not re-bill the image model.
        candidates = [str(project_path or "").strip()]
        if not candidates[0]:
            candidates = _executed_projects()
        for project in candidates:
            if not project:
                continue
            root = image_dir(project)
            h.update(root.encode())
            try:
                for name in sorted(os.listdir(root)):
                    if not name.endswith(".md"):
                        continue
                    st = os.stat(os.path.join(root, name))
                    h.update(f"{name}:{st.st_mtime_ns}:{st.st_size}".encode())
            except OSError:
                pass
        return h.hexdigest()

    @classmethod
    def execute(cls, project_path="", order=None) -> io.NodeOutput:
        project = SymbioticaCategoryPrompts._project([project_path], [order])
        if not project:
            raise ValueError(
                "no project folder to read the prompt book from — wire an "
                "order, or set project_path")
        # Empty when the project has no _image/ blocks yet, rather than a
        # raise: this node is the editor those blocks are written in, so it has
        # to run before they exist.
        return io.NodeOutput(project, compose_image_prompt(project))


def _prompt_node_project(project_path):
    """The project a prompt-book canvas node reads: its own value — typed or
    delivered on the wire — nothing else. These nodes sit downstream of the
    Prompt Book's `project_path` output, which is already resolved, so there is no
    order to walk the way Category Prompts must."""
    cand = str(project_path or "").strip()
    return cand if cand and os.path.isdir(cand) else ""


class SymbioticaPromptBlock(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaPromptBlock",
            display_name="Symbiotica Prompt Block",
            category="symbiotica/pipeline",
            description="One block of the prompt book, edited on the canvas — "
                        "a shared rule, an image-model block, or an asset "
                        "type. Several of these side by side ARE the book, "
                        "laid out like the string-literal graphs they replace, "
                        "except a save here lands in "
                        "<project>/prompts/ where every queue reads it. Wire "
                        "the Prompt Book's `project_path` output in, and chain "
                        "block to block through `project` so one wire feeds "
                        "the row. Wire a Prompt Recipe's `text_N` into "
                        "`text_in` and Asset Focus's `category` in, and this "
                        "becomes a window onto that recipe's slot: the asset "
                        "picks the block, you read it, edit it and pass it on.",
            inputs=[
                io.String.Input("project_path", default="",
                                tooltip="Client project folder holding the "
                                        "prompt book. Wire the Prompt Book's "
                                        "`project` output, or a neighbouring "
                                        "block's `project` passthrough."),
                io.String.Input("block", default="",
                                tooltip="Which block this node edits: a type "
                                        "block (Chair.md), a shared rule "
                                        "(_rules/02-inputs.md) or an image "
                                        "block (_image/01-image-model.md). "
                                        "The panel's picker fills this in. "
                                        "Ignored while `category` is wired — "
                                        "then the recipe names the block."),
                io.Combo.Input("slot",
                               options=[str(i) for i in
                                        range(1, SLOT_MAX + 1)],
                               default="1",
                               tooltip="Which slot of the category's recipe "
                                       "this node edits. Set for you when "
                                       "`text_in` comes from a Prompt "
                                       "Recipe — wiring `text_3` in makes "
                                       "this 3."),
                io.String.Input("category", optional=True, force_input=True,
                                tooltip="Wire Asset Focus's `category` here "
                                        "and this node edits whatever "
                                        "`_recipes/<category>.json` names in "
                                        "`slot` — switch asset type and the "
                                        "block on screen follows, with "
                                        "nothing to pick."),
                io.String.Input("text_in", force_input=True, optional=True,
                                tooltip="Wire the Prompt Recipe's `text_N` "
                                        "here to preview and edit that "
                                        "prompt. With no `category` wired it "
                                        "is the old chain input instead: the "
                                        "previous block's `text`, which this "
                                        "node appends its own block to."),
            ],
            outputs=[
                io.String.Output(display_name="project_path",
                                 tooltip="Passthrough of the project, so "
                                         "blocks chain on one wire instead of "
                                         "fanning every node back to the "
                                         "book."),
                io.String.Output(display_name="text",
                                 tooltip="This node's block, ready for the "
                                         "LLM. Chained (no `category` wired) "
                                         "it is everything so far: text_in "
                                         "plus this block, blank-line "
                                         "separated, so the LAST block in a "
                                         "row carries the whole prompt."),
            ],
            # A push needs the node id to reach the right panel: which block a
            # wired category names is decided at run time, and without the id
            # the panel keeps showing whatever was last picked by hand.
            hidden=[io.Hidden.unique_id],
        )

    @staticmethod
    def _slot_index(slot):
        """`slot` as a 0-based index, clamped. Never raises: the widget is
        written by the panel from a wire, and a stray value must not kill the
        queue."""
        try:
            n = int(str(slot or "1").strip() or 1)
        except ValueError:
            n = 1
        return max(1, min(n, SLOT_MAX)) - 1

    @classmethod
    def _pick(cls, project, block="", slot="1", category=""):
        """Which block this node edits, as `(name, version, from_recipe)`.

        A wired category beats the picker: the whole point is that switching
        asset type re-points this editor with nothing to choose. It only wins
        when the recipe actually names something in this slot — an absent
        recipe or a short one falls back to the picked block rather than
        blanking the panel the user is typing into.
        """
        cat = str(category or "").strip()
        if not cat:
            return str(block or "").strip(), "", False
        from .prompt_book import read_recipe
        picked = read_recipe(project, cat)
        i = cls._slot_index(slot)
        if i < len(picked) and picked[i].get("block"):
            return picked[i]["block"], picked[i].get("version", ""), True
        return str(block or "").strip(), "", False

    @classmethod
    def fingerprint_inputs(cls, project_path="", block="", slot="1",
                           category="", text_in=None):
        # Widgets only — a linked project reads as None here (see Category
        # Prompts), so fall back to the projects executions registered. Hash
        # the one file this node edits; never raise — a raise becomes NaN and
        # re-bills every descendant on each queue press.
        one = SymbioticaCategoryPrompts._one
        cat = str(one(category) or "").strip()
        # The category and the slot are what NAME the file when a recipe
        # drives this node, so they belong in the hash even though the name
        # below is derived from them — a recipe edited to point slot 2 at a
        # different block changes nothing else here.
        h = hashlib.sha256(
            f"block:{str(block or '').strip()}:{cat}:{one(slot, '1')}".encode())
        candidates = [str(project_path or "").strip()]
        if not candidates[0]:
            candidates = _executed_projects()
        for project in candidates:
            if not project:
                continue
            h.update(project.encode())
            try:
                name, version, _ = cls._pick(project, block, one(slot, "1"),
                                             cat)
                h.update(f"{name}:{version}".encode())
                st = os.stat(resolve_block(project, name))
                h.update(f"{st.st_mtime_ns}:{st.st_size}".encode())
            except (PromptPathError, OSError, ValueError):
                pass
        return h.hexdigest()

    @classmethod
    def execute(cls, project_path="", block="", slot="1", category="",
                text_in=None) -> io.NodeOutput:
        from .prompt_book import pick_version

        one = SymbioticaCategoryPrompts._one
        project = _prompt_node_project(project_path)
        if not project:
            raise ValueError(
                "no project folder to read the prompt book from — wire the "
                "Prompt Book's `project_path` output, or set project_path")
        name, version, from_recipe = cls._pick(
            project, block, one(slot, "1"), one(category))
        if not name:
            raise ValueError(
                "no block picked — choose one in the panel, or wire a "
                "`category` whose recipe names one")
        # Empty rather than a raise when the file is not there yet: this node
        # is the editor the block is written in, so it has to run before its
        # first save. The composed architect prompts still raise on absence —
        # they are read by nodes that can do nothing without them.
        try:
            body = read_block(project, name)
        except PromptPathError:
            body = ""
        text = pick_version(body, version) if from_recipe else body.strip()
        if from_recipe:
            # Recipe-driven, so `text_in` is the SAME prompt arriving off the
            # wire — appending it would emit the block twice. This node is a
            # window onto the recipe's slot here, not a link in a chain.
            out = text
        else:
            # Chained: this node's output is everything so far. The join is the
            # same blank line compose_prompt uses, so a hand-chained row reads
            # the same as the book-composed prompt.
            out = "\n\n".join(
                p for p in (str(text_in or "").strip(), text) if p)
        # The panel cannot know which block a wired category named — that is
        # decided here, at run time — so it is told, the same way the Recipe
        # tells its own panel which recipe it served.
        if from_recipe:
            _push("symbiotica.block", {
                "node_id": str(getattr(getattr(cls, "hidden", None),
                                       "unique_id", "")),
                "name": name,
                "version": version,
            })
        return io.NodeOutput(project, out)


class SymbioticaPromptCompose(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaPromptCompose",
            display_name="Symbiotica Prompt Compose (deprecated — use "
                         "Prompt Recipe)",
            category="symbiotica/pipeline",
            description="One asset type's ARCHITECT prompt, composed exactly "
                        "as the queue composes it: shared _rules/ blocks "
                        "first, the type's own block last. The panel shows "
                        "the byte-exact text, so this node replaces the "
                        "join-strings-and-preview scaffolding — wire "
                        "`system_prompt` into an LLM node to test the book "
                        "against a real call.",
            inputs=[
                io.String.Input("project_path", default="",
                                tooltip="Client project folder holding the "
                                        "prompt book. Wire the Prompt Book's "
                                        "`project` output, or a block's "
                                        "`project` passthrough."),
                io.String.Input("category", default="",
                                tooltip="The asset type to compose — the "
                                        "panel's picker lists the book's "
                                        "types."),
            ],
            outputs=[
                io.String.Output(display_name="system_prompt",
                                 tooltip="The composed architect prompt for "
                                         "this type — the same text Category "
                                         "Prompts hands the LLM for its "
                                         "sheets."),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, project_path="", category=""):
        # Widgets only, fall back to executed projects, never raise — same
        # contract as Category Prompts. Only `.md` files count: renders.jsonl
        # and the editor's `.bak` files live in the same folder and churn on
        # every run, and hashing them would re-bill the LLM each queue press
        # with the prompts untouched.
        h = hashlib.sha256(f"compose:{str(category or '').strip()}".encode())
        candidates = [str(project_path or "").strip()]
        if not candidates[0]:
            candidates = _executed_projects()
        for project in candidates:
            if not project:
                continue
            h.update(project.encode())
            try:
                for where, dirs, files in os.walk(prompts_dir(project)):
                    dirs.sort()
                    for name in sorted(files):
                        if not name.endswith(".md"):
                            continue
                        p = os.path.join(where, name)
                        st = os.stat(p)
                        rel = os.path.relpath(p, prompts_dir(project))
                        h.update(
                            f"{rel}:{st.st_mtime_ns}:{st.st_size}".encode())
            except OSError:
                pass
        return h.hexdigest()

    @classmethod
    def execute(cls, project_path="", category="") -> io.NodeOutput:
        project = _prompt_node_project(project_path)
        if not project:
            raise ValueError(
                "no project folder to read the prompt book from — wire the "
                "Prompt Book's `project_path` output, or set project_path")
        cat = str(category or "").strip()
        if not cat:
            raise ValueError("no asset type to compose — pick one in the "
                             "panel")
        return io.NodeOutput(resolve_category_prompts(project, [cat])[0])


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
                io.String.Input("categories", force_input=True, optional=True,
                                tooltip="Asset type per asset — Order Assets' "
                                        "`categories` or Asset Focus's "
                                        "`category`. Leave unwired when the "
                                        "order comes from Asset Focus: the "
                                        "focused order carries each asset's "
                                        "type already."),
                io.Int.Input("seed", default=0, min=0, max=0xFFFFFFFFFFFFFFF,
                             control_after_generate=True,
                             tooltip="Which reference each type draws. Same "
                                     "seed = same references; bump it to draw "
                                     "again. A type keeps its own pick when "
                                     "another type joins the order."),
                io.String.Input("subfolder", default="dataset",
                                tooltip="Subfolder under the project holding "
                                        "the per-type reference folders — the "
                                        "same sense as Save Render's "
                                        "subfolder."),
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
                io.String.Output(display_name="names",
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
                io.String.Output(display_name="save_path",
                                 is_output_list=True,
                                 tooltip="The type folder asset i's reference "
                                         "was drawn from. Wire it into a Pick "
                                         "node's `save_path` to see every "
                                         "reference of that type in a grid and "
                                         "tick the ones you want, instead of "
                                         "taking the seeded draw — leave the "
                                         "picker's `stage` empty, since these "
                                         "are source art with no steps under "
                                         "them. A picker reads the first "
                                         "folder handed to it, so focus one "
                                         "asset (Asset Focus's `category`) "
                                         "when the order carries several "
                                         "types."),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, categories=None, seed=0, subfolder="dataset",
                           project_path="", order=None):
        # Widgets only — linked inputs arrive as None here (see Category
        # Prompts). Hash the folder listing so adding or removing a reference
        # redraws, and never raise: a raise becomes NaN and re-bills every
        # descendant on each queue press.
        one = SymbioticaCategoryPrompts._one
        sub_folder = str(one(subfolder, "dataset")).strip() or "dataset"
        h = hashlib.sha256(f"{sub_folder}:{one(seed, 0)}".encode())
        # The project usually arrives on the ORDER wire, and a linked input
        # reads as unset here — so the widget alone left this hashing a
        # relative "dataset" that never resolves, and the folder walk below
        # was dead in exactly the graphs it was written for. Fall back to the
        # projects executions have registered.
        candidates = [str(one(project_path)).strip()]
        if not candidates[0]:
            candidates = _executed_projects()
        for project in candidates:
            if not project:
                continue
            h.update(project.encode())
            # The layout decides where the cells are, and it lives in files no
            # node lists as an input — without it a re-ruled type keeps
            # serving the boxes of the old grid.
            from .sheet_cells import layout_fingerprint
            h.update(layout_fingerprint(project, sub_folder).encode())
            root = dataset_dir(project, sub_folder)
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
    def execute(cls, categories=None, seed=0, subfolder="dataset",
                project_path="", order=None) -> io.NodeOutput:
        one = SymbioticaCategoryPrompts._one
        cats = [c for c in (categories or []) if str(c or "").strip()]
        if not cats:
            # No categories wire: read each wired order's own assets. Index
            # alignment holds — Asset Focus emits one narrowed order per
            # asset, in the same order as its string outputs.
            orders = order if isinstance(order, list) else [order]
            for o in orders:
                if isinstance(o, dict):
                    cats.extend(str(a.get("category", "") or "").strip()
                                for a in o.get("assets", []) or [])
            cats = [c for c in cats if c]
        if not cats:
            raise ValueError("no assets to reference — wire Asset Focus's "
                             "`order` output, or Order Assets' `categories`")
        project = SymbioticaCategoryPrompts._project(project_path, order)
        if not project:
            raise ValueError(
                "this order names no project folder, so there is nowhere to "
                "read the dataset from — set project_path on this node")
        paths, names = pick_reference_per_category(
            project, cats, int(one(seed, 0) or 0),
            str(one(subfolder, "dataset")).strip() or "dataset")
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
        # The folder each reference came OUT of, so a Pick node can list it and
        # the reference can be chosen by eye rather than by seed. Taken from
        # the chosen file rather than re-joined from project/folder/category:
        # one derivation, and it cannot drift from the draw.
        folders = [os.path.dirname(p) for p in paths]
        # Servable so the picker's grid can fetch thumbnails from a project
        # that lives outside the studio volume — servable ONLY. A dataset
        # folder in the refs set would enter Asset Refs' change-check, and a
        # new reference file would then re-run the LLM and the image model
        # under it.
        for folder_path in dict.fromkeys(folders):
            _register_served_root(folder_path)
        return io.NodeOutput(images, names, boxes, folders)


class SymbioticaReconstructCells(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaReconstructCells",
            display_name="Symbiotica Reconstruct Cells",
            category="symbiotica/pipeline",
            description="Puts cells back into the sheet they were cut from — "
                        "Slice Cells read the other way, on the same boxes. "
                        "Edit each asset on its own, then rebuild the packed "
                        "layout a style LoRA was trained on, at the same size "
                        "and the same padding as the sheet that was split.",
            # Every cell at once: a sheet cannot be laid out one cell per
            # execution, and mapped per image this would emit one sheet each.
            is_input_list=True,
            inputs=[
                io.Image.Input("cells",
                               tooltip="The finished sprites, in the order "
                                       "Slice Cells returned them."),
                io.String.Input("cell_boxes", force_input=True,
                                tooltip="The same `cell_boxes` that cut them — "
                                        "from Dataset Reference. The sheet is "
                                        "rebuilt on exactly those boxes."),
                io.String.Input("background", default=DEFAULT_BACKGROUND,
                                tooltip="What the gutters and any cell with no "
                                        "sprite are filled with. Match the "
                                        "packed sheets and the result is "
                                        "indistinguishable from one."),
                io.Int.Input("canvas_size", default=0, min=0, max=8192,
                             tooltip="Sheet size, or 0 to recover it from the "
                                     "boxes — the grid is centred, so the "
                                     "margin after the last cell equals the "
                                     "one before the first."),
                io.Mask.Input("masks", optional=True,
                              tooltip="Transparency for the cells. A loader "
                                      "flattens alpha before this node sees "
                                      "it, so without the mask a transparent "
                                      "sprite lands on a black rectangle "
                                      "instead of the background."),
                io.Boolean.Input("mask_is_transparency", default=True,
                                 tooltip="ON for ComfyUI's Load Image, whose "
                                         "mask is 1 where the picture is "
                                         "see-through. OFF for a straight "
                                         "alpha channel, where 1 is the art."),
                # Appended: links address an input by slot index.
                io.String.Input("padding_color", default="#000000",
                                tooltip="What sits OUTSIDE the cells — the "
                                        "gutters and the border. The packer "
                                        "floods the sheet with this and then "
                                        "punches each cell back to the "
                                        "background above, which is what draws "
                                        "the black outline around every cell. "
                                        "Set it to the same colour as the "
                                        "background for no outline at all."),
            ],
            outputs=[
                io.Image.Output(display_name="sheet",
                                tooltip="One sheet, laid out like the packed "
                                        "one the cells came from."),
            ],
        )

    @classmethod
    def execute(cls, cells=None, cell_boxes="", background=DEFAULT_BACKGROUND,
                canvas_size=0, masks=None, mask_is_transparency=True,
                padding_color="#000000") -> io.NodeOutput:
        from PIL import Image

        from .asset_refs import parse_hex
        from .compare_sheet import fit_box, with_alpha
        from .sheet_cells import canvas_of
        one = SymbioticaCategoryPrompts._one

        raw = one(cell_boxes, "")
        try:
            boxes = json.loads(str(raw or "").strip() or "[]")
        except ValueError:
            boxes = None
        if not isinstance(boxes, list) or not boxes:
            raise ValueError(
                "no cell boxes — wire the Dataset Reference node's "
                "`cell_boxes` output into this node, the same one that cut "
                "these cells")

        frames = [f for t in (cells or []) if t is not None for f in t]
        if not frames:
            raise ValueError("wire the finished sprites into 'cells'")
        mask_frames = [f for t in (masks or []) if t is not None for f in t]

        size = int(one(canvas_size, 0) or 0)
        width, height = (size, size) if size > 0 else canvas_of(boxes)
        if width <= 0 or height <= 0:
            raise ValueError("these boxes describe no sheet — set canvas_size")

        # Flooded with the matte, then each cell punched back to the
        # background — the packer's own order, and the reason every cell comes
        # out ringed in the gutter colour. Painting the cells first and the
        # gutters after would leave no outline at all.
        cell_colour = parse_hex(one(background, DEFAULT_BACKGROUND))
        sheet = Image.new("RGB", (width, height),
                          parse_hex(one(padding_color, "#000000")))
        for box in boxes:
            sheet.paste(cell_colour,
                        (int(box.get("x", 0)), int(box.get("y", 0)),
                         int(box.get("x", 0)) + int(box.get("w", 0)),
                         int(box.get("y", 0)) + int(box.get("h", 0))))
        # Zipped, so a run with fewer sprites than cells leaves the rest as
        # background rather than shifting every later sprite into the wrong
        # cell — the same alignment rule the cut side keeps.
        for index, box in enumerate(boxes):
            if index >= len(frames):
                break
            image = _tensor_to_pil(frames[index])
            if index < len(mask_frames):
                image = with_alpha(image,
                                   _tensor_to_pil_mask(mask_frames[index]),
                                   bool(one(mask_is_transparency, True)))
            box_w, box_h = int(box.get("w", 0)), int(box.get("h", 0))
            new_w, new_h, dx, dy = fit_box(image.width, image.height,
                                           min(box_w, box_h))
            if not new_w or not new_h:
                continue
            # Centred in its own box, so a sprite whose aspect drifted during
            # editing still sits where the cell is rather than overhanging it.
            dx += (box_w - min(box_w, box_h)) // 2
            dy += (box_h - min(box_w, box_h)) // 2
            at = (int(box.get("x", 0)) + dx, int(box.get("y", 0)) + dy)
            if image.mode == "RGBA":
                scaled = image.resize((new_w, new_h), Image.LANCZOS)
                sheet.paste(scaled, at, scaled)
            else:
                sheet.paste(image.convert("RGB").resize((new_w, new_h),
                                                        Image.LANCZOS), at)
        return io.NodeOutput(_pil_to_tensor(sheet))


class SymbioticaCompareSheet(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaCompareSheet",
            display_name="Symbiotica Compare Sheet",
            category="symbiotica/pipeline",
            description="Lays a row of references over a row of results as one "
                        "image, so an asset and the art it was drawn from are "
                        "read side by side instead of clicked between. Takes "
                        "whole batches, unlike a two-image stitch: wire Asset "
                        "Refs into the top row and Slice Cells into the "
                        "bottom, and each result lands under the reference it "
                        "belongs to.",
            # Both rows at once: laying them out needs every image together, and
            # mapped per image this would emit one sheet per cell.
            is_input_list=True,
            inputs=[
                io.Image.Input("references",
                               tooltip="The top row — the client's reference "
                                       "art, e.g. Asset Refs' `images`."),
                io.Image.Input("results",
                               tooltip="The bottom row — what was made from "
                                       "it, e.g. Slice Cells' `cells`."),
                io.Int.Input("cell_size", default=0, min=0, max=4096,
                             tooltip="Square each image is fitted into, or 0 "
                                     "to take the largest edge among them so "
                                     "nothing is enlarged into softness."),
                io.Int.Input("spacing", default=16, min=0, max=512,
                             tooltip="Gutter between cells, and the sheet's "
                                     "own border."),
                io.String.Input("background", default=DEFAULT_BACKGROUND,
                                tooltip="What sits behind each sprite, and what "
                                        "fills a cell with no sprite in it."),
                # Appended: links address an input by slot index.
                io.Mask.Input("reference_masks", optional=True,
                              tooltip="Transparency for the top row. A loader "
                                      "hands the pixels on with alpha already "
                                      "flattened — over black, for these "
                                      "sprites — so without the mask a "
                                      "transparent PNG lands as a black "
                                      "rectangle instead of the background."),
                io.Mask.Input("result_masks", optional=True,
                              tooltip="Transparency for the bottom row."),
                io.Boolean.Input("mask_is_transparency", default=True,
                                 tooltip="ON for ComfyUI's own Load Image, "
                                         "whose mask is 1 where the picture is "
                                         "SEE-THROUGH. OFF for a straight "
                                         "alpha channel, where 1 is where the "
                                         "art is — which is what this pack's "
                                         "Asset Refs `masks` hands out. Wrong "
                                         "way round and every sprite is cut "
                                         "out instead of its background."),
                io.String.Input("padding_color", default="#000000",
                                tooltip="What sits OUTSIDE the cells — the "
                                        "gutters and the border — so the sheet "
                                        "reads like the packed ones, every "
                                        "cell ringed in the matte. Set it to "
                                        "the same colour as the background for "
                                        "a plain sheet with no outlines."),
                io.Float.Input("reference_scale", default=1.0, min=0.05,
                               max=1.0, step=0.05,
                               tooltip="Draws the top row smaller inside its "
                                       "own cells. The cells and the columns "
                                       "do not move, and each reference stays "
                                       "centred over the result below it — so "
                                       "a reference that dwarfs the finished "
                                       "asset stops reading as the bigger of "
                                       "the two. 1.0 leaves it alone."),
            ],
            outputs=[
                io.Image.Output(display_name="sheet",
                                tooltip="One image: references on top, results "
                                        "beneath, aligned by column."),
            ],
        )

    @classmethod
    def execute(cls, references=None, results=None, cell_size=0, spacing=16,
                background=DEFAULT_BACKGROUND, reference_masks=None,
                result_masks=None, mask_is_transparency=True,
                padding_color="#000000",
                reference_scale=1.0) -> io.NodeOutput:
        from .asset_refs import parse_hex
        from .compare_sheet import auto_cell, compose_rows, with_alpha
        one = SymbioticaCategoryPrompts._one
        transparency = bool(one(mask_is_transparency, True))

        def frames(batch):
            """Every frame on the wire, whatever shape it arrived in. A list
            input carries one tensor per upstream execution, and each of those
            may itself hold a batch — flattening both is what lets this take a
            fanned-out lane and a plain batch on the same socket."""
            out = []
            for tensor in (batch or []):
                if tensor is None:
                    continue
                for frame in tensor:
                    out.append(frame)
            return out

        def as_images(batch, masks):
            """The row's images, each given back its transparency where a mask
            came with it. Paired by position, and a row with fewer masks than
            images keeps the extra images opaque rather than dropping them."""
            mask_frames = frames(masks)
            out = []
            for index, frame in enumerate(frames(batch)):
                image = _tensor_to_pil(frame)
                if index < len(mask_frames):
                    image = with_alpha(image,
                                       _tensor_to_pil_mask(mask_frames[index]),
                                       transparency)
                out.append(image)
            return out

        top = as_images(references, reference_masks)
        bottom = as_images(results, result_masks)
        if not top and not bottom:
            raise ValueError("wire images into 'references' and 'results' — "
                             "both rows are empty")

        cell = int(one(cell_size, 0) or 0)
        if cell <= 0:
            cell = auto_cell([(im.width, im.height) for im in top + bottom])
        # A short row keeps its holes: the result belongs UNDER the reference it
        # came from, and closing the row up would pair each with the wrong one.
        columns = max(len(top), len(bottom))
        rows = [row + [None] * (columns - len(row)) for row in (top, bottom)]
        # Only the references shrink; the results keep their cell, so the two
        # rows stay column-aligned and the size difference reads as intended.
        scales = [float(one(reference_scale, 1.0) or 1.0), 1.0]
        sheet = compose_rows(rows, cell, max(0, int(one(spacing, 16) or 0)),
                             parse_hex(one(background, DEFAULT_BACKGROUND)),
                             parse_hex(one(padding_color, "#000000")),
                             row_scales=scales)
        return io.NodeOutput(_pil_to_tensor(sheet))


_REF_SIZES = ["native", "512", "1024"]


class SymbioticaAssetRefs(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaAssetRefs",
            display_name="Symbiotica Asset Refs",
            category="symbiotica/pipeline",
            description="The client's own reference art for ONE asset — what "
                        "they sent for this thing, not the dataset's house "
                        "style. Wire Order Assets' `asset_names` in and each "
                        "asset yields its references in order; for a type "
                        "packed in stages that is prep, ready, serving, so the "
                        "same index that picks a cell out of Slice Cells picks "
                        "the reference that belongs to it.",
            inputs=[
                Order.Input("order"),
                io.String.Input("asset_name", force_input=True, optional=True,
                                tooltip="Which asset, by name — Order Assets' "
                                        "asset_names or Asset Focus's "
                                        "asset_name. Leave unwired when the "
                                        "order comes from Asset Focus: a "
                                        "focused order names one asset "
                                        "already."),
                io.String.Input("background", default=DEFAULT_BACKGROUND,
                                tooltip="What a reference with transparency "
                                        "sits on. Grey by default, matching "
                                        "the packed sheets, so the reference "
                                        "and the cell beside it share a "
                                        "backdrop. Set it to your "
                                        "generations' background to compare "
                                        "them like for like."),
                io.Boolean.Input("keep_transparency", default=False,
                                 tooltip="Leave the background alone and hand "
                                         "the alpha out as `masks` instead. "
                                         "Off composites onto the colour "
                                         "above — which is what you want "
                                         "feeding an image model, since these "
                                         "files hide real pixels under their "
                                         "transparent areas."),
                io.Combo.Input("output_size", options=_REF_SIZES,
                               default="native",
                               tooltip="Send a smaller reference when the "
                                       "detail is not worth the tokens. "
                                       "Lanczos, the same resample Slice "
                                       "Cells uses, so a reference and the "
                                       "cell it pairs with are treated "
                                       "identically."),
            ],
            outputs=[
                io.Image.Output(display_name="images", is_output_list=True,
                                tooltip="One image per reference the client "
                                        "sent for this asset, in the order the "
                                        "order sheet pairs them."),
                io.String.Output(display_name="asset_names",
                                 is_output_list=True,
                                 tooltip="Filename of each reference, so a "
                                         "wrong pick is traceable to its file. "
                                         "Wire into a Pick node's `names` to "
                                         "list only this asset's files."),
                # Appended: links address an output by slot index.
                io.Mask.Output(display_name="masks", is_output_list=True,
                               tooltip="Each reference's alpha, opaque where "
                                       "the art is. Emitted whether or not "
                                       "transparency is kept, so a reference "
                                       "can always be composited onto "
                                       "something else downstream."),
                # Shown as `refs_path`: this node READS that folder, it
                # saves nothing. Only the printed label changes — a link
                # addresses an output by slot index, so saved graphs are
                # untouched.
                io.String.Output(display_name="refs_path",
                                 tooltip="The folder these references were "
                                         "read from — the order's own "
                                         "references root. Wire it into a "
                                         "Pick node's `input_path` to tick the "
                                         "client's references by eye instead "
                                         "of taking every one of them."),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, order=None, asset_name="",
                           background=DEFAULT_BACKGROUND,
                           keep_transparency=False, output_size="native"):
        # Every input that names a FILE here is linked — the order and the
        # asset name both arrive on wires, and a linked input reads as unset in
        # a change-check. So a client dropping a corrected reference into the
        # month folder changes nothing this node can see, and the cached tensor
        # of the old picture is served forever. Hash the reference folders
        # executions have registered instead, by name and size and mtime: a
        # replaced file moves the hash even though its path did not change.
        #
        # REFERENCE folders only. This once walked every servable folder, which
        # includes the ones the graph writes into — so saving a render or
        # ticking a thumbnail in a Pick node moved this hash, re-ran the
        # reference load, and with it the LLM reading the reference and the
        # image model reading the LLM. A new paid image per queue press, on a
        # seed that never changed.
        one = SymbioticaCategoryPrompts._one
        h = hashlib.sha256(f"{one(background, '')}:"
                           f"{one(keep_transparency, False)}:"
                           f"{one(output_size, 'native')}".encode())
        for root in _reference_roots():
            h.update(root.encode())
            try:
                for name in sorted(os.listdir(root)):
                    path = os.path.join(root, name)
                    if not os.path.isfile(path):
                        continue
                    st = os.stat(path)
                    h.update(f"{name}:{st.st_size}:{st.st_mtime_ns}".encode())
            except OSError:
                # Never raise: a raise becomes NaN and re-bills every
                # descendant on each queue press.
                pass
        return h.hexdigest()

    @classmethod
    def execute(cls, order=None, asset_name="",
                background=DEFAULT_BACKGROUND, keep_transparency=False,
                output_size="native") -> io.NodeOutput:
        from .asset_refs import (alpha_of, flatten, pairing_note,
                                 reference_files)
        from .sheet_cells import boxes_for_category
        if not isinstance(order, dict) or "assets" not in order:
            raise ValueError("wire an Order Specs into 'order'")
        wanted = str(asset_name or "").strip()
        if not wanted:
            # A focused order names its asset; a whole event does not, and
            # guessing one would pair the wrong art in silence.
            named = [str(a.get("assetName", "") or "").strip()
                     for a in order.get("assets", []) or []]
            named = [n for n in named if n]
            if len(named) == 1:
                wanted = named[0]
            else:
                raise ValueError(
                    "asset_name is unwired and this order holds "
                    f"{len(named)} assets — wire Asset Focus's `order` "
                    "output (one asset), or wire asset_name")
        paths, names = reference_files(order, wanted)

        from PIL import Image
        size = 0 if str(output_size) == "native" else int(output_size)
        images, masks = [], []
        for path in paths:
            with Image.open(path) as im:
                alpha = alpha_of(im)
                if keep_transparency:
                    # The pixels as authored. Only meaningful WITH the mask —
                    # on its own this is the glowing version, because these
                    # files keep live pixels under their transparent areas.
                    flat = im.convert("RGB")
                else:
                    # Composited, never just converted: dropping alpha lights up
                    # every soft edge and uncovers the hidden backdrop.
                    flat = flatten(im, background)
                if size:
                    # Resampled here rather than on the tensor so the mask can
                    # travel with its image: ComfyUI's lanczos collapses a
                    # one-channel tensor to three dimensions, and it is PIL
                    # LANCZOS underneath anyway — the same resample Slice Cells
                    # applies to the cell this reference pairs with.
                    flat = flat.resize((size, size), Image.LANCZOS)
                    if alpha is not None:
                        alpha = alpha.resize((size, size), Image.LANCZOS)
                images.append(_pil_to_tensor(flat))
                if alpha is None:
                    masks.append(torch.ones(1, flat.height, flat.width))
                else:
                    masks.append(torch.from_numpy(
                        np.asarray(alpha, dtype=np.float32) / 255.0)[None, ...])

        # Say whether these line up with the sheet's cells rather than assume
        # it: same count means index i is role i, a different count means an
        # index picks unrelated things on each side, and both look identical
        # once the images are on the wire.
        asset = next((a for a in order["assets"]
                      if str(a.get("assetName", "")).strip()
                      == wanted), {})
        cells = boxes_for_category(
            str(order.get("project_path", "") or "").strip(),
            str(asset.get("category", "") or "").strip())
        note = pairing_note(order, wanted, names, cells)
        # The folder, not the files: a Pick node lists a directory and lets him
        # tick what he wants out of it, so handing it the paths would be the
        # wrong shape and handing it one file's dirname would break the moment
        # the order's refs root gains a subfolder.
        folder = os.path.dirname(paths[0]) if paths else str(
            (order or {}).get("refsRoot", "") or "").strip()
        return io.NodeOutput(images, names, masks, folder,
                             ui=ui.PreviewText(note))


def _resize_square(cell, size):
    """One cell resized to `size`x`size`, by the same resampler the rest of the
    graph uses.

    Lanczos via ComfyUI's own `common_upscale`, so a cell coming out of here
    matches an Upscale Image node set to lanczos exactly — and matches the
    packer, which resamples its sprites with PIL LANCZOS too. Going through
    Comfy also means no clamping is needed: that path is 8-bit via PIL, so the
    ringing bicubic produces at hard edges cannot leave the 0..1 range.

    Falls back to bicubic when `comfy` is absent, which is only ever the test
    harness — antialiased and clamped there, since nothing else would catch the
    overshoot.
    """
    try:
        from comfy.utils import common_upscale
    except ImportError:
        return torch.nn.functional.interpolate(
            cell.movedim(-1, 1), size=(size, size), mode="bicubic",
            antialias=True, align_corners=False).movedim(1, -1).clamp(0.0, 1.0)
    return common_upscale(cell.movedim(-1, 1), size, size,
                          "lanczos", "disabled").movedim(1, -1)


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
                                     "keep it at its cut size. Lanczos, the "
                                     "same resampler an Upscale Image node "
                                     "uses."),
            ],
            outputs=[
                io.Image.Output(display_name="cells", is_output_list=True,
                                tooltip="One image per cell, in reading order."),
                io.String.Output(display_name="roles", is_output_list=True,
                                 tooltip="What each cell holds — 'prep', "
                                         "'serving', a rotation — index-aligned "
                                         "with `cells`."),
                # APPENDED: saved graphs hold output links by slot number.
                io.Image.Output(display_name="stitched",
                                tooltip="Every cell in one image, side by "
                                        "side left to right in the same "
                                        "order `cells` counts them. A "
                                        "shorter cell is padded at the "
                                        "bottom to the tallest one."),
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
                cell = _resize_square(cell, size)
            cells.append(cell)
            roles.append(role)
        # The same cells as ONE image, side by side in index order — for the
        # lanes that want the set travelling as a single picture (compare,
        # preview, a contact-sheet save) without a stitcher node in between.
        tallest = max(c.shape[1] for c in cells)
        strips = []
        for cell in cells:
            if cell.shape[1] < tallest:
                pad = torch.zeros(
                    (cell.shape[0], tallest - cell.shape[1],
                     cell.shape[2], cell.shape[3]),
                    dtype=cell.dtype, device=cell.device)
                cell = torch.cat([cell, pad], dim=1)
            strips.append(cell)
        stitched = torch.cat(strips, dim=2)
        return io.NodeOutput(cells, roles, stitched)


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
            # Template pools — browsed and saved into, so served only.
            _register_served_root(d)
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
        """One event's spec plus the client-refs root.

        A blank feature means "whichever this order leads with". A NAMED one the
        order does not hold is a stale request — a saved workflow keeps the
        feature it was built with, and the order it names can be re-issued
        without it. `event_spec` refuses it and lists what the order does hold;
        building the first event instead spends a render on artwork nobody asked
        for and reports it as the one that was requested."""
        feat = (feature or "").strip() or (
            events_list[0].get("feature", "") if events_list else "")
        return {**event_spec(events_list, feat), "refsRoot": refs_root}

    @classmethod
    def _resolve_spec(cls, spec, events, project_path, month, feature):
        """One event's spec + the sprite-catalog root. The node reads the order
        itself from project+month; a wired spec/events still works; with none of
        them it's an empty spec for a from-scratch template."""
        if project_path and project_path.strip():
            from .project_layout import require_month
            r = require_month(project_path.strip(), (month or "").strip())
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


def _image_frames(images):
    """Every HxWxC frame in whatever arrived on an IMAGE input.

    Three shapes reach here and all three are ordinary: a batch tensor from one
    generator, a single frame, and a Python list when an upstream node fans out
    per asset. Flattening them all to frames means the picker never has to care
    which stage of the pipeline it was dropped into.
    """
    if images is None:
        return []
    if isinstance(images, (list, tuple)):
        out = []
        for item in images:
            out.extend(_image_frames(item))
        return out
    if hasattr(images, "ndim") and images.ndim == 4:
        return [images[i] for i in range(images.shape[0])]
    return [images]


def _unevaluated(value):
    """Whether a lazy input has not been resolved yet.

    Under is_input_list ComfyUI hands an unevaluated lazy input in as `(None,)`
    rather than `None` (comfy_api/latest/_io.py, check_lazy_status docstring).
    Testing only for `None` reads that tuple as a real value, so the input is
    never requested, the wire is never evaluated, and the node quietly records
    nothing while the run reports success.
    """
    if value is None:
        return True
    if isinstance(value, (list, tuple)):
        return len(value) > 0 and all(item is None for item in value)
    return False


def _as_list(value):
    """A per-item input as a list, whatever arrived.

    Under is_input_list a widget reaches the node as a list of one, but a node
    executed directly (a test, or ComfyUI collapsing a single item) hands the
    bare value — treating that string as a sequence would tag candidates with
    one character each.
    """
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _pil_to_tensor_keep_alpha(img):
    """A stored candidate back on the wire, with its transparency intact.

    The RGB-only converter next door would flatten a background-removed pick on
    its way out of the node — the picker would then be the thing that undid the
    removal it was used to approve.
    """
    if img.mode == "P" and "transparency" in img.info:
        img = img.convert("RGBA")
    elif img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")
    arr = np.asarray(img, dtype=np.float32) / 255.0
    return torch.from_numpy(arr)[None, ...]


def _segment_or_blank(value):
    """A `stage` name reduced to one path segment, or "".

    Typed by hand beside a folder it becomes part of, so a slash in it would
    silently deepen the tree — and the same cleaning the save paths get is what
    keeps the folder this node lists identical to the one a save node wrote.
    """
    from .order_assets import _segment
    return _segment(str(value or ""))


def _pick_folders(values):
    """The distinct folders a Pick node was pointed at, resolved and de-duped.

    A relative value resolves under ComfyUI's output directory, because that is
    what `save_paths` emits — `month/feature/category/asset`, the tail of the
    tree the renders are already filed in. A fanned-out lane hands one folder
    per asset, and the same folder repeated is one read, not several.
    """
    out = []
    for value in values or ():
        text = str(value or "").strip()
        if not text:
            continue
        path = text if os.path.isabs(text) else os.path.join(
            folder_paths.get_output_directory(), text)
        path = os.path.normpath(path)
        if path not in out:
            out.append(path)
    return out


def _pick_ids(selection):
    """The ticked candidate ids from the node's stored selection.

    The value is written by the canvas, so it is JSON in practice; a
    comma-separated string is accepted too so the widget stays usable by hand.
    Anything unparseable means nothing is ticked, which the node treats as "no
    picks yet" rather than an error.
    """
    text = str(selection or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return [p.strip() for p in text.split(",") if p.strip()]
    if isinstance(data, str):
        return [data] if data.strip() else []
    if isinstance(data, list):
        return [str(i).strip() for i in data if str(i).strip()]
    return []


class SymbioticaPick(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaPick",
            display_name="Symbiotica Pick",
            category="symbiotica/pipeline",
            description="Lists the images one stage of an asset has produced, "
                        "numbered, and sends on the ones ticked. It writes "
                        "nothing and stores nothing: the files stay where the "
                        "save node put them, so a new render appears by "
                        "queueing this node again and looking at the work can "
                        "never cost a generation. "
                        "The folder is one wire: Asset Focus's `save_path` "
                        "into `save_path`. `stage` names a step under it "
                        "(`edits` reads `…/<asset>/edits_00001_.png`). Wire "
                        "the `save_path` output into the Save Image that fills "
                        "that stage and this node lists exactly what that node "
                        "wrote, by construction. "
                        "Chain them: a picker wired to another picker's "
                        "`picked` lists exactly what that one approved, so "
                        "choosing from a shortlist needs no folder of copies. "
                        "`mode` is whether this step takes a set or one image "
                        "— editing is done to one.",
            # The whole run at once. Without this the node executes once per
            # item whenever the lane above it fans out — three variants means
            # three executions, each re-emitting the same picks, and the
            # preview downstream shows one approved image three times.
            is_input_list=True,
            inputs=[
                io.Image.Input("images", optional=True, lazy=True,
                               tooltip="Wire the save or preview node this "
                                       "stage's images come out of. Its VALUE "
                                       "is never used — the images are read "
                                       "off disk — but the link makes this "
                                       "node run after it, so a fresh render "
                                       "is listed the same queue it was made. "
                                       "Wired to another Pick, this node lists "
                                       "exactly what that one ticked."),
                io.String.Input("save_path", default="", optional=True,
                                tooltip="Wire Asset Focus's `save_path` here "
                                        "— the same string the save nodes "
                                        "take, so this node lists exactly "
                                        "where they write, and `stage` names "
                                        "a step under it. A relative path "
                                        "resolves under ComfyUI's output "
                                        "directory; a save node's own prefix "
                                        "works too (`…/Food - 3 stages/"
                                        "Spookies` lists that asset's "
                                        "`Spookies_*` files)."),
                # Canvas state, hidden by the web extension: the ticks live on
                # the node so they are saved with the workflow.
                io.String.Input("selection", default="", optional=True),
                io.String.Input("view", default="", optional=True),
                io.Combo.Input("mode", options=_PICK_MODES, default="multiple",
                               optional=True,
                               tooltip="Whether this step takes a set or one "
                                       "image. `single` is for editing — you "
                                       "edit the image you are working on, so "
                                       "ticking replaces the previous pick "
                                       "instead of adding to it."),
                io.String.Input("stage", default="", optional=True,
                                tooltip="Deprecated — review a step by "
                                        "chaining pickers with `show` and "
                                        "`edit_save_path` instead; the panel "
                                        "hides this widget when it is empty. "
                                        "Kept because widget values restore "
                                        "by position in saved graphs. "
                                        "Which step of this asset to list, as "
                                        "a name under the asset's own folder: "
                                        "`edits` lists "
                                        "`…/<asset>/edits_00001_.png`. Empty "
                                        "lists the asset's own renders, which "
                                        "is where a save node writes them "
                                        "first. Wire the `save_path` output "
                                        "into the Save Image that fills this "
                                        "stage and the two cannot disagree."),
                io.String.Input("names", default="", optional=True,
                                tooltip="Which files out of the folder. An "
                                        "entry with an extension is one exact "
                                        "file — wire Asset Refs' names to see "
                                        "only THIS asset's client references. "
                                        "An entry without one is a save "
                                        "prefix: the same tag the Save Image "
                                        "in this lane was given (`_base`, "
                                        "`edits`) lists exactly what it "
                                        "wrote. Empty lists the whole "
                                        "folder."),
                # APPENDED, and optional. ComfyUI restores a saved workflow's
                # widget values positionally, and a REQUIRED input is a demand
                # on every payload already stored elsewhere — both of which
                # this node has been bitten by before.
                io.Combo.Input("show", options=_SHOW_OPTIONS,
                               default="approved", optional=True,
                               advanced=True,
                               tooltip="Only matters when another picker feeds "
                                       "this one, and does nothing otherwise. "
                                       "`approved` lists exactly what that "
                                       "picker ticked. `edits` lists the files "
                                       "saved FROM those ticks instead, which "
                                       "is how you review the edits of one "
                                       "approval — wire that picker's "
                                       "`edit_save_path` into the Save Image "
                                       "in between, so each edit records the "
                                       "render it came from."),
                # Canvas state like `selection`, appended so saved graphs
                # restore positionally: the files marked ✎ on the panel, a
                # second set beside the approve ticks with its own output.
                io.String.Input("edit_selection", default="", optional=True),
                # Canvas state, appended for the same reason: which step of the
                # folder the panel's breadcrumb is standing on, as a path
                # relative to the wired one. Empty is the whole tree.
                io.String.Input("subfolder", default="", optional=True),
            ],
            outputs=[
                io.Image.Output(display_name="picked", is_output_list=True),
                io.String.Output(display_name="save_path",
                                 tooltip="The path this node lists, ready "
                                         "for a Save Image node's "
                                         "`filename_prefix` — so the node that "
                                         "WRITES this stage and the node that "
                                         "READS it are named in one place."),
                # APPENDED for the same reason the widget was: a saved
                # workflow's links are held by slot number, so an output added
                # anywhere but the end repoints them at their neighbours.
                io.String.Output(display_name="edit_save_path",
                                 tooltip="`save_path`, marked with the render "
                                         "that was picked — for the Save Image "
                                         "that writes EDITS of it. The mark is "
                                         "what lets a later picker list the "
                                         "edits of one approval, which no set "
                                         "of ticks can do: an edit is a file "
                                         "named after the tick was made. With "
                                         "no single pick to name, this is "
                                         "`save_path` and the edit carries no "
                                         "mark."),
                # APPENDED. The files marked ✎ on the panel — a second lane
                # out of one picker, so approving to export and sending to
                # edit no longer need two chained nodes.
                io.Image.Output(display_name="for_edit", is_output_list=True,
                                tooltip="The images marked for edit on the "
                                        "panel (✎), as their own lane — wire "
                                        "into the edit chat/model. Approve "
                                        "ticks flow out `picked` unchanged."),
            ],
            # `prompt`/`dynprompt` are how check_lazy_status finds out whether
            # `images` actually has a link before asking for it, and how a
            # picker fed by another picker reads what that one ticked.
            hidden=[io.Hidden.unique_id, io.Hidden.prompt, io.Hidden.dynprompt],
            # An output node so it can be queued on its own: "Queue Selected
            # Output Node" on this picker lists the folder and sends the ticks
            # on, with nothing downstream needing to exist yet.
            is_output_node=True,
        )

    @classmethod
    def fingerprint_inputs(cls, images=None, save_path="", selection="",
                           view="", mode="multiple", stage="", names="",
                           show="approved", edit_selection="", subfolder=""):
        """Change only when what LEAVES the node could have.

        The first version returned NaN — always changed — so the panel would
        re-list. But an always-changed node marks its output fresh on every
        queue, and everything downstream of `picked` re-ran with it: the edit
        model re-rendered the same tick, at full price, once per queue. The
        panel's freshness now comes from the canvas — pick.js re-lists when a
        queue finishes — so this only has to answer for the emission.

        Wired inputs read as unset here (this runs before upstream outputs
        exist), so the folder comes from what the last execution registered. A
        node that has not run yet, or whose files cannot be statted, says NaN
        and runs once: that run registers the folder, and from there the stamp
        holds until a tick, the mode, the stage, or a ticked file's bytes
        change. A file replaced under the same name changes mtime and size,
        which is why the stat is part of the stamp rather than just the name.
        """
        from .pick_folder import listing_for, picked_paths, resolved, under

        one = SymbioticaCategoryPrompts._one
        node_id = getattr(getattr(cls, "hidden", None), "unique_id", None)
        node_id = one(node_id, None) if isinstance(node_id, list) else node_id
        target, only, derived = resolved(node_id) if node_id else ("", None, None)
        if not target:
            return float("nan")
        # The breadcrumb names a different folder, so what leaves the node can
        # change with nothing else touched.
        target = under(target, str(one(subfolder, "") or ""))
        picked_one = str(one(mode, "multiple") or "multiple") == "single"
        ticks = _pick_ids(str(one(selection, "")))
        edit_ticks = _pick_ids(str(one(edit_selection, "")))
        stamp = [target, sorted(only) if only is not None else None,
                 sorted(derived) if derived is not None else None,
                 picked_one, str(one(stage, "")), ticks, edit_ticks]
        def stamp_of(path):
            """A file that cannot be statted is stamped as ABSENT rather than
            answering NaN for the whole node. A tick naming a file that is no
            longer in the folder is ordinary — the panel says "1 missing" and
            carries on — and NaN would mark this node permanently dirty, which
            re-runs everything downstream of `picked` on every queue."""
            try:
                st = os.stat(path)
                return [path, st.st_mtime_ns, st.st_size]
            except OSError:
                return [path, None, None]

        try:
            listing = listing_for(target, only=only, derived_from=derived)
            paths = picked_paths(listing, ticks)
            for path in paths[:1] if picked_one else paths:
                stamp.append(stamp_of(path))
            # The edit set is an emission too: a file re-rendered under a
            # marked name must reach the edit lane the next queue.
            for path in picked_paths(listing, edit_ticks):
                stamp.append(stamp_of(path))
        except OSError:
            # The FOLDER is unreadable, which is a different thing: nothing can
            # be said about what would leave the node.
            return float("nan")
        return json.dumps(stamp)

    @classmethod
    def check_lazy_status(cls, images=None, save_path="", selection="",
                          view="", mode="multiple", stage="", names="",
                          show="approved", edit_selection="", subfolder=""):
        """Ask for the wire when there is one — for its ORDER, not its value.

        The images are read off disk, and `execute` ignores whatever arrives
        here. What the wire buys is sequence: without it this node depends on
        nothing that the lane above produces, and ComfyUI is free to run it
        BEFORE the save node writes the new file — so a fresh render would show
        up one queue late, every time.

        Asking costs nothing that was not already spent. What a picker is wired
        to is a save or preview node, and those are output nodes: ComfyUI runs
        them on every queue whether or not this node asks for them.

        Not merely "not False": an unknowable wire is refused too, because
        asking for an input that has no link fails the whole graph with
        NodeInputError, and a picker sitting on the canvas before anything is
        wired to it is an ordinary state.
        """
        if cls._images_wired() is not True:
            return []
        return ["images"] if _unevaluated(images) else []

    @classmethod
    def _prompt_node(cls, node_id=None):
        """One node out of the prompt, by id, from whichever hidden carries it."""
        hidden = getattr(cls, "hidden", None)
        wanted = node_id if node_id is not None else str(
            getattr(hidden, "unique_id", "") or "")
        if not wanted:
            return None
        for source in (getattr(hidden, "prompt", None),
                       getattr(hidden, "dynprompt", None)):
            try:
                if isinstance(source, dict):
                    found = source.get(wanted)
                elif source is not None and hasattr(source, "get_node"):
                    found = source.get_node(wanted)
                else:
                    continue
            except Exception:
                continue
            if isinstance(found, dict):
                return found
        return None

    @classmethod
    def _images_wired(cls):
        """True/False when the `images` input's link can be determined, else None.

        Asking for an input that has no link is not a no-op: ComfyUI answers
        with `NodeInputError` and fails the whole graph.
        """
        node = cls._prompt_node()
        if not isinstance(node, dict):
            return None
        # A wired input is stored as [origin_node_id, slot]; a widget value is
        # a scalar, and an unconnected optional is absent.
        return isinstance((node.get("inputs") or {}).get("images"), list)

    @classmethod
    def _upstream_pick(cls):
        """The id of the Pick node feeding `images`, or "" when it is not one.

        A picker wired to another picker chooses from what that one approved —
        "521 reads the indexed 3 images from 518" — which is what makes an
        "approved" folder of copies unnecessary. The shortlist is the upstream
        node's ticks, and those are on the wire's own node in the prompt.
        """
        node = cls._prompt_node()
        link = (node or {}).get("inputs", {}).get("images")
        if not isinstance(link, list) or not link:
            return ""
        source_id = str(link[0])
        source = cls._prompt_node(source_id)
        return source_id if (source or {}).get("class_type") == "SymbioticaPick" \
            else ""

    @classmethod
    def execute(cls, images=None, save_path="", selection="", view="",
                mode="multiple", stage="", names="",
                show="approved", edit_selection="",
                subfolder="") -> io.NodeOutput:
        from PIL import Image

        from .pick_folder import (edit_prefix, listing_for, picked_paths,
                                  remember, resolved, under)

        one = SymbioticaCategoryPrompts._one
        node_id = getattr(getattr(cls, "hidden", None), "unique_id", None)
        node_id = one(node_id, None) if isinstance(node_id, list) else node_id
        step = _segment_or_blank(one(stage, ""))

        # One wire names the asset's folder: Asset Focus's `save_path` into
        # `folder` is the same string the save nodes take, so the picker and
        # the savers cannot disagree. `stage` is a step under the asset:
        # `…/<asset>/edits` names the files the edit lane writes, the same
        # way `…/<asset>` names its first renders.
        typed = _pick_folders(_as_list(save_path))
        home = typed[0] if typed else ""
        # The folder this asset's `stage` step lives in, whether or not this
        # node is the one listing it.
        stage_home = os.path.join(home, step) if (home and step) else home
        target = stage_home

        # Fed by another picker: list exactly what it approved. Its ticks are
        # on its own node in the prompt, and the folder they name is the one it
        # resolved when it ran — which it did, because asking for its wire is
        # what put it before this node.
        only = None
        derived_from = None
        upstream = cls._upstream_pick()
        if upstream:
            source = cls._prompt_node(upstream) or {}
            ticks = _pick_ids(str((source.get("inputs") or {}).get("selection", "")))
            source_target, source_only, _ = resolved(upstream)
            if source_only is not None:
                # The upstream is itself narrowed; a tick it no longer shows is
                # not something this node may offer.
                ticks = [name for name in ticks if name in set(source_only)]
            if str(one(show, "approved") or "approved") == "edits":
                # The edits OF those picks, which sit in THIS node's stage
                # folder under names the picker above never saw — so its ticks
                # cannot narrow them, and the mark each file carries does. The
                # target stays this node's own for the same reason.
                derived_from = ticks
            else:
                only = ticks
                if source_target:
                    target = source_target

        # A name filter narrows the folder to one asset's files. Order
        # references live FLAT in the order's folder, so a path cannot say
        # which asset a file belongs to — only its name can.
        wanted = [str(n).strip() for n in _as_list(names) if str(n).strip()]
        if wanted:
            only = wanted if only is None else [n for n in only
                                                if n in set(wanted)]
        # The panel lists the same thing this run resolved; it cannot work it
        # out for itself, because asset and category arrive on wires and a
        # wired input has no value on the canvas. What is remembered is the
        # ROOT — the breadcrumb walks down from it, and the panel applies its
        # own step the same way this does, so navigating needs no re-queue.
        remember(node_id, target, only, derived_from)
        here = under(target, str(one(subfolder, "") or ""))
        entries = listing_for(here, only=only, derived_from=derived_from)

        # Nothing ticked is a legitimate state, not a failure: it is what the
        # node looks like before the images have been looked at. An empty list
        # simply runs nothing downstream, where raising would paint a run red
        # for having worked correctly.
        paths = picked_paths(entries, _pick_ids(one(selection, "")))
        # "in edit mode i want to only be able to select one image. i am
        # EDITING so it has to be the one i am working on". The panel already
        # replaces rather than adds under `single`; this is for the graph saved
        # with several ticks, or switched to `single` after the picks were
        # made. First in listing order, which is the one numbered lowest on
        # screen.
        if str(one(mode, "multiple") or "multiple") == "single":
            paths = paths[:1]

        out_dir = folder_paths.get_output_directory()

        def _shown(path):
            """A path as the node should say it: relative to the output tree.

            That is also the form a Save Image node's `filename_prefix` takes,
            which is the point of handing it out — the node that WRITES this
            stage and the node that READS it are then named in one place.
            """
            try:
                return os.path.relpath(path, out_dir).replace(os.sep, "/")
            except ValueError:
                return path

        # What this node LISTS is not always what it hands out. A picker fed by
        # another lists that one's approvals — the base renders — while its
        # `stage` says which step the images it sends are on their way to. So
        # the folder output follows the stage, and the save node in between
        # takes it from the picker BEFORE it. Wiring the reader's folder into
        # that save node instead is a dependency cycle: it feeds this node's
        # images, so it cannot also wait for this node.
        out_folder = stage_home if step else target
        listed = _shown(out_folder) if out_folder else ""
        # Where an EDIT of this pick gets saved: the same stage prefix, marked
        # with the render it came from. An edit is a file the approving picker
        # never saw, so its own name is the only place that link can live.
        # Nothing single to point at means no mark rather than a wrong one, and
        # the lane still works — the edit simply has no parent.
        # Where an EDIT of this pick is saved: the prefix this node already
        # hands out, with its last segment marked by the render the edit came
        # from. An edit is a file the approving picker never saw, so its own
        # name is the only place that link can live.
        #
        # Marking that prefix rather than requiring a step keeps this valid
        # wherever `save_path` is. A blank is NOT the safe answer here: a blank
        # reaches Save Image as a real filename_prefix, and ComfyUI resolves it
        # to a hidden `._00001_.png` at the output root — which no listing
        # shows, since dot-names are skipped, and which every later save
        # overwrites because the counter never matches. That loses paid,
        # unrepeatable renders and reports success.
        #
        # Nothing single to point at means no mark rather than a wrong one, and
        # the prefix is then exactly `save_path`.
        marked = ""
        if listed:
            head, _, tail = listed.rpartition("/")
            parent = os.path.basename(paths[0]) if len(paths) == 1 else ""
            stem = edit_prefix(tail, parent)
            marked = f"{head}/{stem}" if head else stem
        # The ✎ set, a second lane out of the same listing. Not narrowed by
        # `single`: mode is about how many the APPROVE step takes, and a batch
        # of edits is the point of marking several.
        edit_paths = picked_paths(entries, _pick_ids(one(edit_selection, "")))
        _push("symbiotica.pick", {
            "node_id": str(node_id), "count": len(entries),
            "folder": listed, "picked": len(paths),
            "for_edit": len(edit_paths),
            "shortlist": bool(upstream),
        })
        picked = [_pil_to_tensor_keep_alpha(Image.open(p)) for p in paths]
        for_edit = [_pil_to_tensor_keep_alpha(Image.open(p))
                    for p in edit_paths]
        return io.NodeOutput(picked, listed, marked, for_edit)


class SymbioticaPromptRecipe(io.ComfyNode):
    """A saved set of blocks, served on one wire each.

    A category needs several prompts at once — the architect's, the image
    model's, the mirror rewriter's — and swapping category meant editing every
    one of them by hand. A recipe names those blocks together under one name,
    so changing category is changing one widget.
    """

    # Outputs are fixed because a schema is; `slots` decides how many of them
    # carry text. Six because the chain that motivated this is three, and a
    # type that grows a fourth and fifth prompt must not need a release.
    MAX_SLOTS = SLOT_MAX

    # Pick this instead of a name and the recipe is the one named after the
    # asset's own category: choosing a Food asset upstream serves
    # `_recipes/Food - 3 stages.json` with no second thing to remember. The
    # whole point of the node is that changing category is one move.
    FOLLOW = "(follow category)"

    @staticmethod
    def _order_category(order):
        """The single category the wired order is on, or "" when it isn't one.

        Asset Focus narrows to one asset per run, so the normal case has
        exactly one category. A wider order (a whole event) has several, and
        guessing one of them would serve the wrong prompts under the right
        name — the caller turns that into an error naming what it found.
        """
        if isinstance(order, dict):
            orders = [order]
        elif isinstance(order, (list, tuple)):
            orders = [o for o in order if isinstance(o, dict)]
        else:
            return []
        # What Asset Focus is focused on beats what the event happens to hold:
        # `event_order` carries all 61 assets of the month, so counting their
        # categories says "several" and the node would fall back to whatever
        # was pinned — the whole complaint. The narrowed `order` output has no
        # focus key and needs none: it holds the one asset already.
        focused = {str((one.get("focus") or {}).get("category", "") or "").strip()
                   for one in orders}
        focused.discard("")
        if len(focused) == 1:
            return sorted(focused)
        cats = set()
        for one in orders:
            for asset in one.get("assets", []) or []:
                cat = str(asset.get("category", "") or "").strip()
                if cat:
                    cats.add(cat)
        return sorted(cats)

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaPromptRecipe",
            display_name="Symbiotica Prompt Recipe",
            category="symbiotica/pipeline",
            description="Serves a saved recipe: one prompt block per output, "
                        "picked in the panel and stored under "
                        "`prompts/_recipes/<name>.json`. Switching recipe "
                        "switches every prompt the category needs at once.",
            inputs=[
                io.String.Input("recipe", default="",
                                tooltip="The saved preset to serve. Pick it "
                                        "in the panel — the panel writes this "
                                        "widget, and it is what survives a "
                                        "workflow reload. “(follow category)” "
                                        "serves the recipe named after the "
                                        "asset's category instead, so picking "
                                        "a Food asset upstream serves the "
                                        "Food recipe."),
                io.Combo.Input("slots",
                               options=[str(i) for i in
                                        range(1, cls.MAX_SLOTS + 1)],
                               default="3",
                               tooltip="How many blocks this recipe serves. "
                                       "Outputs past it come back empty."),
                io.String.Input("project_path", default="",
                                tooltip="Client project folder holding the "
                                        "prompt book. Unneeded when `order` "
                                        "is wired."),
                Order.Input("order", optional=True,
                            tooltip="Any order from the pipeline — it carries "
                                    "the project, so project_path can stay "
                                    "empty."),
                io.String.Input("category", optional=True, force_input=True,
                                tooltip="Wire Asset Focus's `category` here "
                                        "and the recipe named after it is the "
                                        "one served — picking the asset then "
                                        "picks its prompts, with nothing to "
                                        "set here."),
                io.String.Input("bucket", optional=True, force_input=True,
                                tooltip="Asset Focus's `bucket` — how this row "
                                        "of the category is drawn. With one "
                                        "wired, `<category> - <bucket>` is "
                                        "served when the book has such a "
                                        "recipe (`Food - 3 stages - Drinks`), "
                                        "and the plain category otherwise."),
            ],
            outputs=[
                io.String.Output(display_name=f"text_{i}",
                                 tooltip=f"Slot {i} of the recipe, or empty "
                                         "when the recipe has no such slot.")
                for i in range(1, cls.MAX_SLOTS + 1)
            ],
            # The run says which recipe it served, and a push needs the node
            # id to reach the right panel. Without this the id went over empty
            # and the node kept its old title while serving the new prompts.
            hidden=[io.Hidden.unique_id],
            # Queueable on its own — "Queue Selected Output Node" on this node
            # resolves the wired category and bucket and tells the panel what
            # it served. Which recipe a wire picks is decided in Python, so
            # without a run of its own the panel sits on the last name it was
            # told and there is no way to find out what the graph would send
            # short of rendering the whole thing.
            is_output_node=True,
        )

    @classmethod
    def fingerprint_inputs(cls, recipe="", slots=3, project_path="",
                           order=None, category="", bucket=""):
        # Widgets plus the book's file mtimes, and never raise: a raise becomes
        # NaN, which re-bills every model under this node on each queue press.
        one = SymbioticaCategoryPrompts._one
        h = hashlib.sha256(
            f"recipe:{str(one(recipe)).strip()}:{int(one(slots, 3) or 3)}"
            .encode())
        # On “follow category” the recipe name comes off the wire, so the
        # category has to be part of the fingerprint — without it, switching
        # from an Appliance asset to a Food one served the cached Appliance
        # prompts and nothing on the canvas said why.
        h.update("|".join(cls._order_category(order)).encode())
        h.update(str(one(category) or "").strip().encode())
        # The bucket names a DIFFERENT recipe, so switching from a cake to a
        # tea under one category has to miss the cache the same way switching
        # category does.
        h.update(str(one(bucket) or "").strip().encode())
        candidates = [str(one(project_path)).strip()]
        if not candidates[0]:
            candidates = _executed_projects()
        for project in candidates:
            if not project:
                continue
            h.update(project.encode())
            try:
                for where, dirs, files in os.walk(prompts_dir(project)):
                    dirs.sort()
                    for name in sorted(files):
                        if not (name.endswith(".md")
                                or name.endswith(".json")):
                            continue
                        p = os.path.join(where, name)
                        st = os.stat(p)
                        rel = os.path.relpath(p, prompts_dir(project))
                        h.update(
                            f"{rel}:{st.st_mtime_ns}:{st.st_size}".encode())
            except OSError:
                pass
        return h.hexdigest()

    @classmethod
    def execute(cls, recipe="", slots=3, project_path="",
                order=None, category="", bucket="") -> io.NodeOutput:
        from .prompt_book import pick_version, read_recipe
        from .prompt_store import PromptPathError, read_block

        project = _prompt_node_project(project_path)
        if not project and isinstance(order, dict):
            project = str(order.get("project_path", "") or "").strip()
        if not project:
            raise ValueError(
                "no project folder to read the prompt book from — wire an "
                "`order`, or set project_path")
        name = str(recipe or "").strip()
        # The order decides. Picking a Food asset upstream has to serve the
        # Food prompts by itself — a recipe pinned in the widget that keeps
        # serving Appliance under a Food asset is the bug, not the feature.
        # A pinned name still answers for a category the book has no recipe
        # for, and for a Recipe with no order wired at all.
        # A wired category is the plainest statement of all: Asset Focus says
        # what the picked asset is, and that names the recipe.
        wired = str(SymbioticaCategoryPrompts._one(category) or "").strip()
        cats = [wired] if wired else cls._order_category(order)
        # A bucket narrows the category: one category can be drawn two ways —
        # `Food - 3 stages` is a chopping board for a cake and an empty cup for
        # a tea — so `<category> - <bucket>` is preferred when the book holds
        # one, and the plain category answers for everything else. Never an
        # error on its own: a bucket with no recipe means that row is drawn the
        # ordinary way.
        sub = str(SymbioticaCategoryPrompts._one(bucket) or "").strip()
        if len(cats) == 1 and sub and read_recipe(project, f"{cats[0]} - {sub}"):
            name = f"{cats[0]} - {sub}"
        elif len(cats) == 1 and read_recipe(project, cats[0]):
            name = cats[0]
        elif name == cls.FOLLOW:
            if not cats:
                raise ValueError(
                    "“follow category” needs an order that names one — wire "
                    "Asset Focus's order in, or pick a recipe by name")
            if len(cats) > 1:
                raise ValueError(
                    "“follow category” needs ONE category and this order "
                    f"holds {len(cats)}: {', '.join(cats)}. Narrow it with "
                    "Asset Focus, or pick a recipe by name")
            raise ValueError(
                f"no recipe named {cats[0]!r} in prompts/_recipes/ — save one "
                "under that name, or pick a recipe by name")
        if not name:
            raise ValueError("no recipe picked — choose one in the panel, or "
                             "save a new one")
        picked = read_recipe(project, name)
        if not picked:
            raise ValueError(
                f"recipe {name!r} names no blocks — it is missing from "
                "prompts/_recipes/, or it was saved empty")
        want = max(1, min(int(SymbioticaCategoryPrompts._one(slots, 3)
                              or 3), cls.MAX_SLOTS))
        texts = []
        for i in range(cls.MAX_SLOTS):
            slot = picked[i] if i < len(picked) else None
            if i >= want or not slot or not slot.get("block"):
                texts.append("")
                continue
            try:
                body = read_block(project, slot["block"])
            except PromptPathError as exc:
                raise ValueError(
                    f"recipe {name!r} slot {i + 1}: {exc}") from exc
            texts.append(pick_version(body, slot.get("version", "")))
        # Say which recipe actually ran. The name is decided here, from the
        # wire, so the canvas has no way to know it otherwise — and "which
        # prompts did that render use" is the first question after a switch.
        _push("symbiotica.recipe", {
            "node_id": str(getattr(getattr(cls, "hidden", None),
                                   "unique_id", "")),
            "name": name,
            "blocks": [str(s.get("block", "")) for s in picked[:want]],
            # How big each served block actually is. "i have no idea what the
            # actual prompt this sends out" — the names say which blocks, the
            # sizes say they were read and not empty.
            "chars": [len(t) for t in texts[:want]],
        })
        return io.NodeOutput(*texts)


class SymbioticaGridLayout(io.ComfyNode):
    """The grid an asset type is drawn on, picked the way its recipe is.

    The layout stopped being scenery the day the prompts started describing it —
    three grey slots, a diamond grid in each, black everywhere else — so a
    category that gets its own prompts needs its own grid, and switching asset
    had to switch both.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaGridLayout",
            display_name="Symbiotica Grid Layout",
            category="symbiotica/pipeline",
            description="The layout image an asset type is drawn on, out of "
                        "<project>/datasets/layouts/. Wire Asset Focus's "
                        "`category` and `bucket` in and it picks "
                        "`<category> - <bucket>` then `<category>`, newest "
                        "version first — the same ladder the Prompt Recipe "
                        "climbs, so one naming rule covers the prompts and the "
                        "grid. A new version is a new file (`Food - 3 "
                        "stages-7.png`), never a rename.",
            inputs=[
                io.String.Input("project_path", default="",
                                tooltip="Client project folder. Unneeded when "
                                        "`order` is wired."),
                io.String.Input("layout", default="",
                                tooltip="Pin one file by name and it wins over "
                                        "the category. Empty follows the "
                                        "category — the panel's picker fills "
                                        "this in."),
                Order.Input("order", optional=True,
                            tooltip="Any order from the pipeline — it carries "
                                    "the project, so project_path can stay "
                                    "empty."),
                io.String.Input("category", optional=True, force_input=True,
                                tooltip="Asset Focus's `category`. Names the "
                                        "layout the same way it names the "
                                        "recipe."),
                io.String.Input("bucket", optional=True, force_input=True,
                                tooltip="Asset Focus's `bucket`. Narrows to "
                                        "`<category> - <bucket>` when the "
                                        "folder holds one, and falls back to "
                                        "the plain category when it does not."),
            ],
            outputs=[
                io.Image.Output(display_name="image",
                                tooltip="The layout, ready for the image "
                                        "model's first input."),
                io.Mask.Output(display_name="mask",
                               tooltip="Its alpha, opaque where the layout has "
                                       "pixels. Fully opaque for a layout "
                                       "saved without transparency."),
                io.String.Output(display_name="name",
                                 tooltip="Which file was used — the answer to "
                                         "\"which grid did that render "
                                         "stand on\"."),
            ],
            hidden=[io.Hidden.unique_id],
            # Queueable on its own, for the same reason the Recipe is: which
            # file a wired category picks is decided here, so without a run of
            # its own the canvas cannot say which grid it would send.
            is_output_node=True,
        )

    @classmethod
    def _project(cls, project_path, order):
        one = SymbioticaCategoryPrompts._one
        project = str(one(project_path) or "").strip()
        if project:
            return project
        wired = one(order, None)
        if isinstance(wired, dict):
            return str(wired.get("project_path", "") or "").strip()
        return ""

    @classmethod
    def fingerprint_inputs(cls, project_path="", layout="", order=None,
                           category="", bucket=""):
        # Never raise: a raise is NaN, which re-bills every model under this
        # node on each queue press.
        from .layouts import pick_layout

        one = SymbioticaCategoryPrompts._one
        h = hashlib.sha256(
            f"layout:{str(one(layout) or '').strip()}:"
            f"{str(one(category) or '').strip()}:"
            f"{str(one(bucket) or '').strip()}".encode())
        try:
            project = cls._project(project_path, order)
            found = pick_layout(project, str(one(category) or ""),
                                str(one(bucket) or ""),
                                str(one(layout) or ""))
            h.update(found.encode())
            st = os.stat(found)
            # A layout redrawn under the same name is a different grid, and the
            # render standing on it has to be made again.
            h.update(f"{st.st_mtime_ns}:{st.st_size}".encode())
        except (OSError, ValueError):
            pass
        return h.hexdigest()

    @classmethod
    def execute(cls, project_path="", layout="", order=None, category="",
                bucket="") -> io.NodeOutput:
        from PIL import Image, UnidentifiedImageError

        from .layouts import (built_dir, layouts_dir, list_layouts,
                              pick_layout)

        one = SymbioticaCategoryPrompts._one
        project = cls._project(project_path, order)
        if not project:
            raise ValueError(
                "no project folder to read layouts from — wire an `order`, or "
                "set project_path")
        wanted_category = str(one(category) or "").strip()
        pinned = str(one(layout) or "").strip()
        found = pick_layout(project, wanted_category,
                            str(one(bucket) or ""), pinned)
        if not found:
            # Name the folder AND what is in it: "no layout" is otherwise
            # indistinguishable from "wrong project", and the fix is different.
            held = list_layouts(project)
            asked = pinned or wanted_category or "(nothing wired)"
            built = built_dir(project, wanted_category)
            raise ValueError(
                f"no layout for {asked!r}. {layouts_dir(project)} "
                + (f"holds: {', '.join(held)}" if held
                   else "is empty or missing")
                + (f"; assetkit's {built} holds nothing readable" if built
                   else f"; assetkit has no {wanted_category!r} Layout folder "
                        "under datasets/dataset-single"))
        try:
            with Image.open(found) as opened:
                opened.load()
                image = opened.convert("RGBA")
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            raise ValueError(f"{found} could not be read as an image") from exc
        arr = np.asarray(image, dtype=np.float32) / 255.0
        pixels = torch.from_numpy(arr[..., :3])[None, ...]
        mask = torch.from_numpy(arr[..., 3])[None, ...]
        name = os.path.basename(found)
        # The canvas cannot know which file a wired category picked — that is
        # decided here — so it is told, the same way the Recipe reports the
        # recipe it served.
        _push("symbiotica.layout", {
            "node_id": str(getattr(getattr(cls, "hidden", None),
                                   "unique_id", "")),
            "name": name,
            "layouts": list_layouts(project),
        })
        return io.NodeOutput(pixels, mask, name)


class SymbioticaOrderTracker(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaOrderTracker",
            display_name="Symbiotica Order Tracker",
            category="symbiotica/pipeline",
            description="The order as a board: one slot per asset it asks "
                        "for, filled with the approved render or empty. It is "
                        "a Pick node pointed at every asset at once — the "
                        "same folders, the same `names` tag, the same "
                        "thumbnails — so nothing is tracked that is not "
                        "already on disk. `_final` is written by approving in "
                        "a Pick node, or by any Save Image given that prefix.",
            inputs=[
                Order.Input("order"),
                io.String.Input("category", default="", optional=True,
                                tooltip="Narrow the board to one asset type, "
                                        "or leave empty for every type."),
                io.String.Input("names", default="_final", optional=True,
                                tooltip="Which files fill a slot, read the "
                                        "same way as a Pick node's `names`: "
                                        "an entry without an extension is a "
                                        "save prefix. `_final` is what "
                                        "approving writes."),
            ],
            outputs=[],
            hidden=[io.Hidden.unique_id],
            # Queued on its own — "Queue Selected Output Node" on the tracker
            # re-reads the folders, which is the same gesture that refreshes a
            # picker, with nothing downstream needing to exist.
            is_output_node=True,
        )

    @classmethod
    def fingerprint_inputs(cls, order=None, category="", names="_final"):
        """The board is a question about DISK, and disk changes without the
        graph changing — a render saved, an approval written. Caching this on
        its inputs would show yesterday's board until a widget moved."""
        return float("nan")

    @classmethod
    def execute(cls, order=None, category="", names="_final") -> io.NodeOutput:
        from .pick_folder import listing_for

        if not isinstance(order, dict) or "assets" not in order:
            raise ValueError("wire an Order Specs (or an Asset Focus) into "
                             "'order'")
        items = assets_by_category(order, category)
        wanted = [n for n in (str(names or "").split(",")) if n.strip()]
        wanted = [n.strip() for n in wanted] or None

        slots = []
        for item, path in zip(items, save_paths(order, items)):
            folders = _pick_folders([path])
            target = folders[0] if folders else ""
            # Same read the picker makes, one folder per asset. `only` is the
            # tag: `_final` lists approvals, and any other save prefix asks the
            # board a different question without a code change.
            entries = listing_for(target, only=wanted) if target else []
            # The tiles are fetched by the canvas from a folder the graph also
            # WRITES into, which is exactly what `_register_served_root` is
            # for — servable, not watched.
            if target:
                _register_served_root(target)
            slots.append({
                "asset": item["assetName"],
                "category": item["category"],
                "image": entries[0]["path"] if entries else None,
                "count": len(entries),
            })

        done = sum(1 for slot in slots if slot["image"])
        # The order arrives on a wire the canvas cannot read, so the run hands
        # the board over — the same way Asset Focus hands over its choices.
        _push("symbiotica.tracker", {
            "node_id": str(getattr(getattr(cls, "hidden", None),
                                   "unique_id", "")),
            "feature": str(order.get("feature", "")),
            "done": done, "total": len(slots), "slots": slots,
        })
        return io.NodeOutput()


PIPELINE_NODE_CLASSES = [
    SymbioticaPick,
    SymbioticaAssetFocus,
    SymbioticaOrderTracker,
    SymbioticaOrderRead,
    SymbioticaOrderSpecs,
    SymbioticaReferenceBrowser,
    SymbioticaRefsFolder,
    SymbioticaModelPreset,
    SymbioticaAutoPackerSettings,
    SymbioticaAutoPacker,
    SymbioticaCategoryPrompts,
    SymbioticaOrderAssets,
    SymbioticaClientExamples,
    SymbioticaPromptBook,
    SymbioticaPromptBlock,
    SymbioticaPromptCompose,
    SymbioticaPromptRecipe,
    SymbioticaGridLayout,
    SymbioticaSaveRender,
    SymbioticaDatasetReference,
    SymbioticaSliceCells,
    SymbioticaAssetRefs,
    SymbioticaCompareSheet,
    SymbioticaReconstructCells,
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
