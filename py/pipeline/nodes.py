# ABOUTME: V3 ComfyUI nodes for the order pipeline — Studio Library, Asset
# ABOUTME: Focus, Prompts, Order Tracker. Thin wrappers over py/pipeline/*.
from __future__ import annotations

import copy
import hashlib
import json
import os

import numpy as np
import torch
from comfy_api.latest import io

import folder_paths

from .order_loader import event_spec, load_order
from .order_sheet import bucket_for, canvas_size, category_recipe
from .asset_refs import DEFAULT_BACKGROUND
from .order_assets import assets_by_category, save_paths
from .prompt_store import read_file, stamp

Order = io.Custom("SYMBIOTICA_ORDER")


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
    own output and re-bill every descendant."""
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


def _register_project(project_path: str) -> None:
    """The project this execution ran against, so its folders become servable.
    Only an execution vouches for a project."""
    try:
        from .routes import register_project
        register_project(project_path)
    except Exception:
        pass


def _pil_to_tensor(img) -> torch.Tensor:
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    return torch.from_numpy(arr)[None, ...]

def _one(value, default=""):
    """is_input_list hands EVERY input in as a list, widgets included."""
    if isinstance(value, list):
        return value[0] if value else default
    return default if value is None else value


def _order_paths(project_path, month):
    """The order xlsx, client-refs folder, and sprite-catalog root, all
    derived from the project folder and the picked month."""
    project_path = (project_path or "").strip()
    op = rp = assets_root = ""
    if project_path:
        from .project_layout import require_month
        r = require_month(project_path, (month or "").strip())
        op, rp, assets_root = r["order_path"], r["refs_path"], r["assets_root"]
    return op, rp, assets_root


def _order_guide(project_path):
    path = os.path.join((project_path or "").strip(), "order-guide.md")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _order_fingerprint(project_path="", month="", feature=""):
    """The change-check for an order read off disk: the order file, the
    references folder beside it, and the guide."""
    op, rp, _ = _order_paths(project_path, month)
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
    h.update((_order_guide(project_path) or "").encode())
    return h.hexdigest()


def build_event_order(project_path="", month="", feature=""):
    """The ORDER payload for one event: project + month + feature -> the flat
    asset list every consumer reads.

    Asset Focus does the whole selection itself: project, month and feature
    on its own widgets, no node in front of it.
    """
    _register_project(project_path)
    op, rp, assets_root = _order_paths(project_path, month)
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
        "guide": _order_guide(project_path),
        # The order identity, so a consumer can reproduce this exact event
        # later (project + month + feature). Additive keys — older consumers
        # ignore them.
        "project_path": (project_path or "").strip(),
        "month": (month or "").strip(),
        # Where this pack came from — an order, not the asset library.
        "source": "order",
    }
    return payload


class SymbioticaStudioLibrary(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaStudioLibrary",
            display_name="Symbiotica Studio Library",
            category="Symbiotica",
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


def _focus_reference(order, asset_record, asset_name, wanted_file):
    """(image, mask, name) — ONE of an asset's client references, chosen by
    filename, as the tensors Asset Focus hands out.

    Which one is `wanted_file` if this asset has it and its FIRST otherwise:
    the name comes off a thumbnail he clicked on one asset, and an "all" run
    passes the same string by every other asset in the event.

    Nothing to send — no art in the order, no references folder, a file the
    order names and the disk has lost — is a one-pixel plate and an EMPTY name,
    never a raise. Two reasons: the outputs are index-aligned lists, so a
    dropped entry would pair every later asset with the wrong picture; and this
    lane is optional. Asset Focus names, files and fans out assets whether or
    not any art arrived, and refusing would take that down over a reference
    nobody wired. The empty `ref_name` is what says there was none — the panel
    shows the same thing by drawing no thumbnail.
    """
    from PIL import Image
    from .asset_refs import alpha_of, flatten, parse_hex, reference_files
    plate = torch.tensor(parse_hex(DEFAULT_BACKGROUND),
                         dtype=torch.float32).div(255.0)
    nothing = (plate.reshape(1, 1, 1, 3), torch.zeros(1, 1, 1), "")
    files = [str(n) for n in ((asset_record or {}).get("refFiles") or [])
             if str(n).strip()]
    if not files:
        return nothing

    try:
        paths, names = reference_files(order, asset_name)
        want = str(wanted_file or "").strip()
        index = names.index(want) if want in names else 0
        with Image.open(paths[index]) as im:
            alpha = alpha_of(im)
            # Composited, never converted: these files keep live pixels under
            # their transparent areas, so dropping the alpha lights up every
            # soft edge.
            flat = flatten(im, DEFAULT_BACKGROUND)
            image = _pil_to_tensor(flat)
            if alpha is None:
                mask = torch.ones(1, flat.height, flat.width)
            else:
                mask = torch.from_numpy(
                    np.asarray(alpha, dtype=np.float32) / 255.0)[None, ...]
    except (ValueError, OSError):
        return nothing
    return image, mask, names[index]


class SymbioticaAssetFocus(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaAssetFocus",
            display_name="Symbiotica Asset Focus",
            category="Symbiotica",
            description="One asset out of the order, chosen on the node, with "
                        "its whole record on separate outputs: name, category, "
                        "client prompt, save path, its canvas, and the client "
                        "reference you clicked. Set project_path and press "
                        "Read folder to fill the month and event pickers "
                        "without queueing. Choose no asset and it emits the "
                        "whole event instead, so the same node covers both "
                        "the one-asset iteration loop and a run over "
                        "everything.",
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
                # APPENDED for the same positional reason. Set by clicking a
                # reference thumbnail on the node — "i select the category, the
                # asset and then i have to select the asset again in Pick. this
                # is an extra click that is not necessary".
                io.String.Input("ref", default="", optional=True,
                                tooltip="Which of the asset's client "
                                        "references to emit, by filename. Set "
                                        "by clicking a thumbnail on the node. "
                                        "Empty means the first, which is also "
                                        "what every OTHER asset gets in an "
                                        "all-assets run."),
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
                                 tooltip="month/feature/category/asset — "
                                         "where this asset's renders are "
                                         "filed. A Save Image's "
                                         "filename_prefix takes it as is, and "
                                         "so does the Order Tracker."),
                # Replaces `index` (tail slot, wired nowhere): the order
                # itself, narrowed to each focused asset. One wire carries
                # everything the string fan-out used to.
                Order.Output(display_name="order", is_output_list=True,
                             tooltip="The incoming order narrowed to each "
                                     "focused asset — same event, same "
                                     "project, a one-asset assets list. One "
                                     "of these per focused asset, so "
                                     "downstream still runs once per asset."),
                # APPENDED: links are held by slot index, so a new output goes
                # at the end or every saved graph repoints one slot left.
                Order.Output(display_name="event_order",
                             tooltip="The WHOLE event, unnarrowed. The Order "
                                     "Tracker wants the event rather than the "
                                     "asset, and it must not change every "
                                     "time you focus a different one."),
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
                                         "empty for everything else. It "
                                         "names `<category> - <bucket>` where "
                                         "the prompt book holds one."),
                # APPENDED, all three: the reference the click chose, so
                # picking the asset and picking its art is one act — flattened
                # image plus its alpha.
                io.Image.Output(display_name="ref_image", is_output_list=True,
                                tooltip="The client reference you clicked, one "
                                        "per focused asset, composited onto "
                                        "the sheet grey. An asset the client "
                                        "sent no art for gets a one-pixel "
                                        "plate and an empty `ref_name`."),
                io.Mask.Output(display_name="ref_mask", is_output_list=True,
                               tooltip="That reference's alpha, opaque where "
                                       "the art is."),
                io.String.Output(display_name="ref_name", is_output_list=True,
                                 tooltip="Its filename — which reference was "
                                         "drawn. Empty when the asset has no "
                                         "references at all."),
                            # APPENDED: the category as a workflow is named — its canvas in
                # tiles beside it, since a 128x128 and a 128x256 Appliance are
                # two recipes — and the canvas in pixels, for saving at the
                # game's own size. `category` stays the plain sheet name, so
                # paths and datasets keep the one name the sheet gives them.
                io.String.Output(display_name="category_recipe", is_output_list=True,
                                 tooltip="The category plus its canvas in tiles: "
                                         "`Appliance 1x2`. What a recipe is "
                                         "named after."),
                io.Int.Output(display_name="width", is_output_list=True,
                              tooltip="The asset's canvas width in pixels, 0 "
                                      "when the sheet names none."),
                io.Int.Output(display_name="height", is_output_list=True,
                              tooltip="The asset's canvas height in pixels, 0 "
                                      "when the sheet names none."),
],
            hidden=[io.Hidden.unique_id],
            # An output node so it can be queued on its own. Without that there
            # is no way to run it before anything is wired downstream, and its
            # list of choices only exists once it has run at least once.
            is_output_node=True,
        )

    @classmethod
    def fingerprint_inputs(cls, order=None, category="", asset="",
                           project_path="", month="", feature="", ref=""):
        """When this node makes its own order it caches on the ORDER FILE —
        that file and the references folder move without the graph moving. With one WIRED IN, the wire already carries that, and the
        answer must be STABLE: NaN here marks the node permanently dirty, and
        because its outputs feed the string joins and the render lane, every
        queue re-ran the whole graph even with the seed untouched."""
        if not str(project_path or "").strip():
            return hashlib.sha256(
                f"{category}|{asset}|{ref}".encode()).hexdigest()
        return _order_fingerprint(project_path, month, feature)

    @classmethod
    def execute(cls, order=None, category="", asset="",
                project_path="", month="", feature="",
                ref="") -> io.NodeOutput:
        # Its own selection when nothing is wired in: month, feature, category
        # and asset are one act, and doing half of it on another node is what
        # made this two nodes.
        if not isinstance(order, dict) or "assets" not in order:
            if str(project_path or "").strip():
                order = build_event_order(project_path, month, feature)
            else:
                raise ValueError(
                    "set project_path (and month) to read an order here, or "
                    "wire another Asset Focus's `event_order` into 'order'")
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
                "pick a different feature")

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
        # Every category the EVENT holds, not just the narrowed one: the
        # `category` dropdown is built from this when the canvas has no parse
        # of its own (a wired project it cannot read), and a list narrowed to
        # the current pick would offer nothing to switch to.
        categories = []
        for a in order.get("assets", []) or []:
            if not str(a.get("assetName", "") or "").strip():
                continue
            recipe = category_recipe(a)
            if recipe and recipe not in categories:
                categories.append(recipe)
        _push("symbiotica.focus", {
            "node_id": str(getattr(getattr(cls, "hidden", None),
                                   "unique_id", "")),
            "feature": str(order.get("feature", "")),
            "refs_root": str(order.get("refsRoot", "") or ""),
            "categories": categories,
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
        # in — `refFiles` is what a downstream reference read needs.
        narrowed = [{**order,
                     "assets": [raw.get(i["assetName"], i)]} for i in picked]
        # The reference he clicked, resolved here rather than on a second
        # node: clicking the thumbnail already said which one, and being asked
        # the same question again is the click he wanted gone.
        chosen_refs = [_focus_reference(order, raw.get(i["assetName"]),
                                        i["assetName"], ref) for i in picked]
        return io.NodeOutput([i["assetName"] for i in picked],
                             [i["category"] for i in picked],
                             [i["prompt"] for i in picked],
                             save_paths(order, picked),
                             narrowed,
                             order,
                             # Re-read rather than taken off the row: an order
                             # parsed before buckets existed carries no key,
                             # and the answer is the same either way.
                             [bucket_for(i) for i in picked],
                             [r[0] for r in chosen_refs],
                             [r[1] for r in chosen_refs],
                             [r[2] for r in chosen_refs],
                             [category_recipe(raw.get(i["assetName"], i)) for i in picked],
                             [canvas_size(raw.get(i["assetName"], i))[0] for i in picked],
                             [canvas_size(raw.get(i["assetName"], i))[1] for i in picked])


# The slots an Asset Recipe can hold. ComfyUI has no dynamic outputs, so the
# node declares a fixed set of wildcard ones and the canvas grows INTO them —
# `web/js/asset_recipe.js` counts the `slot_*` outputs on the node definition
# rather than carrying a number of its own, so the two cannot drift apart.
SLOT_COUNT = 16


def _slot_rows(slots) -> list:
    """The slot table the canvas keeps, as a list of rows.

    Unreadable JSON is NO slots rather than an error: the focus half of this
    node names the asset and files the render, and a mangled table must not
    take that down with it."""
    try:
        rows = json.loads(slots or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


def _slot_value(row: dict):
    """One slot's value, in the type the widget it was taken from holds.

    The canvas records the type at the moment the wire was made, so a seed
    stays an INT even though JSON has only one kind of number — a float out
    here is a `seed` the sampler refuses. A value that cannot be read at all
    names its own slot: the alternative is a type error thrown by whichever
    node the wire reaches, which says nothing about where the value came
    from."""
    value = row.get("value")
    if value is None:
        return None
    kind = str(row.get("type") or "").upper()
    name = str(row.get("name") or "slot")
    try:
        if kind == "INT":
            return int(round(float(value)))
        if kind == "FLOAT":
            return float(value)
        if kind == "BOOLEAN":
            return bool(value)
    except (TypeError, ValueError):
        raise ValueError(f"the {name!r} slot holds {value!r}, which is not "
                         f"a {kind.lower()}")
    return value if isinstance(value, str) else str(value)


class SymbioticaAssetRecipe(SymbioticaAssetFocus):
    """Asset Focus, plus the widget values that draw the asset.

    The same selection, the same panel and the same outputs, with a growing
    block of slots under them. Drag a widget's socket — a lora, a strength, a
    seed — onto the empty slot at the foot of the output column and that value
    moves here: the slot takes the widget's name, type and current value, the
    widget on the far node goes link-driven, and a new empty slot opens below.
    Everything that decides how this asset is drawn is then set in one place.
    """

    @classmethod
    def define_schema(cls) -> io.Schema:
        # BUILT from Asset Focus's schema rather than copied out of it: an
        # output added there has to appear here too, in the same order, or the
        # two nodes stop being the same node with slots on the end.
        base = SymbioticaAssetFocus.define_schema()
        return io.Schema(
            node_id="SymbioticaAssetRecipe",
            display_name="Symbiotica Asset Recipe",
            category=base.category,
            description="Asset Focus with the widget values that draw the "
                        "asset. Everything the node chooses — month, event, "
                        "category, asset, reference — plus a slot for every "
                        "widget you drag onto it: the lora, its strength, the "
                        "seed, the denoise. One node to set up one asset.",
            inputs=[*copy.deepcopy(base.inputs),
                    # APPENDED, and the canvas hides it: this is the slot
                    # table itself, written by `web/js/asset_recipe.js` and
                    # read here. The per-slot widgets do not serialise, so the
                    # whole block rides in this one string and adding a slot
                    # never shifts another widget's saved value.
                    io.String.Input("slots", default="[]", optional=True,
                                    tooltip="The slot table, as JSON. Set by "
                                            "wiring widgets to this node.")],
            outputs=[*copy.deepcopy(base.outputs),
                     *[io.AnyType.Output(display_name=f"slot_{i}")
                       for i in range(1, SLOT_COUNT + 1)]],
            hidden=[io.Hidden.unique_id],
            is_output_node=True,
        )

    @classmethod
    def fingerprint_inputs(cls, slots="[]", **kwargs):
        # The slot table is an input like any other: change a strength and the
        # nodes it feeds have to run again.
        return hashlib.sha256(
            f"{super().fingerprint_inputs(**kwargs)}|{slots}".encode()
        ).hexdigest()

    @classmethod
    def execute(cls, slots="[]", **kwargs) -> io.NodeOutput:
        # `super()`, not the parent class by name: the focus half pushes its
        # asset list to the canvas under `cls.hidden.unique_id`, and calling
        # SymbioticaAssetFocus.execute directly would push it under the wrong
        # class — where this node's panel never sees it.
        focus = super().execute(**kwargs)
        values = [_slot_value(row) for row in _slot_rows(slots)[:SLOT_COUNT]]
        # Every declared output answers, wired or not: a slot nobody has
        # filled is None, which is what an unconnected output means anyway.
        values += [None] * (SLOT_COUNT - len(values))
        return io.NodeOutput(*focus.result, *values,
                             ui=getattr(focus, "ui", None))


class SymbioticaPromptBlock(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaPromptBlock",
            display_name="Prompts (Symbiotica)",
            category="Symbiotica",
            description="A text file on the canvas. Point it at a path, "
                        "pick a folder under it and a file in that folder, "
                        "read and edit it here, save it back. The output is "
                        "the text as shown.",
            inputs=[
                io.String.Input("path", default="",
                                tooltip="The folder holding the prompts. Type "
                                        "it, or wire a string. Its sub-folders "
                                        "fill the `folder` dropdown."),
                io.String.Input("folder", default="",
                                tooltip="Which sub-folder of the path, "
                                        "relative to it (`_rules`). `/` is "
                                        "the path itself."),
                io.String.Input("file", default="",
                                tooltip="Which file in that folder. The "
                                        "dropdown lists what the folder "
                                        "holds."),
                io.String.Input("text", default="", multiline=True,
                                tooltip="The file's text. Edit here; "
                                        "`save file` writes it back."),
            ],
            outputs=[
                io.String.Output(display_name="text",
                                 tooltip="The text as shown."),
            ],
            hidden=[io.Hidden.unique_id],
            # An output node so it can be queued on its own. A path arriving
            # on a wire the canvas cannot read — a Get node, a switch — has no
            # value until a run, and with nothing downstream there was no way
            # to make that run happen.
            is_output_node=True,
        )

    @classmethod
    def execute(cls, path="", folder="", file="", text="") -> io.NodeOutput:
        # The run knows the path the canvas only guessed at, so it hands it
        # back — the same way Asset Focus hands over its choices.
        _push("symbiotica.prompts", {
            "node_id": str(getattr(getattr(cls, "hidden", None),
                                   "unique_id", "")),
            "path": str(_one(path) or ""),
        })
        return io.NodeOutput(str(_one(text) or ""))


# A file dropdown value the canvas uses to say "nothing to load": bracketed so
# it can never collide with a real name, and never read as one here either.
def _unpicked(name):
    return not name or name.startswith("[")


class SymbioticaPromptLoad(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaPromptLoad",
            display_name="Prompt Load (Symbiotica)",
            category="Symbiotica",
            description="Load one prompt file. Point it at the same path the "
                        "Prompts node edits and pick a file from the "
                        "dropdown; the output is that file's text. It re-runs "
                        "only when the file itself changes.",
            inputs=[
                io.String.Input("path", default="",
                                tooltip="The folder holding the prompts — the "
                                        "same path the Prompts node is given. "
                                        "Type it, or wire a string."),
                io.String.Input("file", default="",
                                tooltip="Which file under that path. The "
                                        "dropdown lists every prompt file it "
                                        "holds, sub-folders included."),
            ],
            outputs=[
                io.String.Output(display_name="text",
                                 tooltip="The file's text."),
            ],
            hidden=[io.Hidden.unique_id],
            # An output node, for the same reason the Prompts node is one: a
            # path arriving through a Get node has no value the canvas can
            # read, and queueing this node on its own is how the dropdown
            # learns which folder to list.
            is_output_node=True,
        )

    @classmethod
    def fingerprint_inputs(cls, path="", file=""):
        folder = str(_one(path) or "").strip()
        name = str(_one(file) or "").strip()
        return f"{folder}|{name}|{stamp(folder, name)}"

    @classmethod
    def execute(cls, path="", file="") -> io.NodeOutput:
        folder = str(_one(path) or "").strip()
        name = str(_one(file) or "").strip()
        # Pushed BEFORE the read: the first queue of a node whose path comes
        # in on a wire has nothing picked yet, and this push is the whole
        # reason that queue was made.
        _push("symbiotica.prompt_load", {
            "node_id": str(getattr(getattr(cls, "hidden", None),
                                   "unique_id", "")),
            "path": folder,
        })
        if not folder or _unpicked(name):
            return io.NodeOutput("")
        # A picked file that has gone is loud. Silently loading nothing would
        # send an empty prompt to a billed model.
        return io.NodeOutput(read_file(folder, name))


def _pick_folders(values):
    """The distinct folders a board slot reads, resolved and de-duped.

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


class SymbioticaOrderTracker(io.ComfyNode):
    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaOrderTracker",
            display_name="Symbiotica Order Tracker",
            category="Symbiotica",
            description="The order as a board: one slot per asset it asks "
                        "for, filled with the approved render or empty. It is "
                        "a picker pointed at every asset at once — the "
                        "same folders, the same `names` tag, the same "
                        "thumbnails — so nothing is tracked that is not "
                        "already on disk. `_final` is written by approving in "
                        "a picker, or by any Save Image given that prefix.",
            inputs=[
                Order.Input("order"),
                io.String.Input("category", default="", optional=True,
                                tooltip="Narrow the board to one asset type, "
                                        "or leave empty for every type."),
                io.String.Input("names", default="_final", optional=True,
                                tooltip="Which files fill a slot, read the "
                                        "same way as a picker's `names`: "
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
            raise ValueError("wire an Asset Focus's `event_order` into "
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
    SymbioticaStudioLibrary,
    SymbioticaAssetFocus,
    SymbioticaAssetRecipe,
    SymbioticaPromptBlock,
    SymbioticaPromptLoad,
    SymbioticaOrderTracker,
]
