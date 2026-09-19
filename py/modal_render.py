# ABOUTME: Modal Render node — a pinned recipe and a prompt become an image
# ABOUTME: rendered on the Symbiotica Modal engine, through the hub's submit/status door.
import os
import time

import requests
from comfy_api.latest import io, ui

from .pipeline import modal_graphs, modal_render
from ._settings import key_from_settings

SEED_MAX = 0xffffffffffffffff


def _check_interrupted():
    try:
        import comfy.model_management as mm
    except ImportError:  # outside ComfyUI
        return
    mm.throw_exception_if_processing_interrupted()


def _progress(cls):
    def show(text):
        try:
            from server import PromptServer
            node_id = getattr(getattr(cls, "hidden", None), "unique_id", None)
            if PromptServer.instance is not None and node_id:
                PromptServer.instance.send_progress_text(text, node_id)
        except Exception:
            pass
    return show


class SymbioticaModalRender(io.ComfyNode):
    """Render a pinned recipe on the Modal engine and get the image back.

    The graph is fixed server-side per recipe; the node only fills prompt,
    seed and size. Credentials live in the Settings UI, never in the
    workflow file."""

    @classmethod
    def define_schema(cls) -> io.Schema:
        return io.Schema(
            node_id="SymbioticaModalRender",
            display_name="Modal Render (Symbiotica)",
            category="Symbiotica",
            description="Runs one of the pack's pinned recipes on the "
                        "Symbiotica Modal render engine and returns the "
                        "image. Set the endpoint and proxy token pair in "
                        "Settings → Symbiotica → Modal.",
            inputs=[
                io.Combo.Input("recipe", options=modal_graphs.recipes(),
                               tooltip="Which pinned graph runs on Modal."),
                io.String.Input("prompt", multiline=True, default="",
                                tooltip="What to draw."),
                io.String.Input("negative", multiline=True, default="",
                                tooltip="What to keep out, where the recipe "
                                        "has a negative prompt."),
                io.Int.Input("seed", default=0, min=0, max=SEED_MAX,
                             control_after_generate=True),
                io.Int.Input("width", default=1024, min=256, max=2048, step=16),
                io.Int.Input("height", default=1024, min=256, max=2048, step=16),
            ],
            outputs=[io.Image.Output(display_name="image")],
            hidden=[io.Hidden.unique_id],
        )

    @classmethod
    def execute(cls, recipe, prompt, negative, seed, width, height) -> io.NodeOutput:
        graph = modal_graphs.bind(modal_graphs.load(recipe), {
            "prompt": prompt, "negative": negative, "seed": seed,
            "width": width, "height": height})
        transport = modal_render.modal_transport(os.environ, key_from_settings)
        data, ext = modal_render.render(
            requests, transport, graph, sleep=time.sleep, clock=time.monotonic,
            check=_check_interrupted, progress=_progress(cls))
        if ext not in ("png", "jpg", "jpeg", "webp"):
            raise modal_render.RenderFailed(
                f"recipe {recipe!r} returned a .{ext}, which this node cannot "
                f"turn into an IMAGE")
        image = modal_render.png_to_tensor(data)
        return io.NodeOutput(image, ui=ui.PreviewImage(image, cls=cls))


NODE_CLASS_MAPPINGS = {"SymbioticaModalRender": SymbioticaModalRender}
NODE_DISPLAY_NAME_MAPPINGS = {"SymbioticaModalRender": "Modal Render (Symbiotica)"}
