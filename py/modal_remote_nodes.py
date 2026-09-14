# ABOUTME: Remote nodes — fetched from the Symbiotica RNP server when ComfyUI
# ABOUTME: starts and registered as native nodes; each runs one Modal recipe.
import io as _io
import os
import time

import requests
from comfy_api.latest import io, ui

from .pipeline import modal_render, rnp_client, rnp_protocol
from ._settings import key_from_settings

SETTING = "RNP_SERVER_URL"
SEED_MAX = 0xffffffffffffffff


def server_url(environ=None, setting=key_from_settings):
    return (setting(SETTING) or (environ or os.environ).get(SETTING) or "").strip()


def _check_interrupted():
    try:
        import comfy.model_management as mm
    except ImportError:
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


def tensor_to_envelope(tensor):
    """The first frame of an IMAGE batch as a png_base64 envelope."""
    import numpy as np
    from PIL import Image

    frame = tensor[0] if getattr(tensor, "dim", lambda: 0)() == 4 else tensor
    array = (frame.cpu().clamp(0.0, 1.0).numpy() * 255).astype(np.uint8)
    buf = _io.BytesIO()
    Image.fromarray(array).convert("RGB").save(buf, format="PNG")
    return rnp_protocol.image_envelope(buf.getvalue())


def _input(name, io_type, options, optional):
    common = {"optional": optional, "tooltip": options.get("tooltip")}
    if io_type == "STRING":
        return io.String.Input(name, default=options.get("default", ""),
                               multiline=bool(options.get("multiline")), **common)
    if io_type == "INT":
        extra = {"control_after_generate": True} if name == "seed" else {}
        return io.Int.Input(name, default=options.get("default", 0),
                            min=options.get("min", 0),
                            max=options.get("max", SEED_MAX if name == "seed" else 2147483647),
                            step=options.get("step", 1), **extra, **common)
    if io_type == "FLOAT":
        return io.Float.Input(name, default=options.get("default", 0.0),
                              min=options.get("min", 0.0), max=options.get("max", 1.0),
                              step=options.get("step", 0.01), **common)
    if io_type == "BOOLEAN":
        return io.Boolean.Input(name, default=bool(options.get("default")), **common)
    if io_type == "COMBO":
        return io.Combo.Input(name, options=list(options.get("options") or []),
                              default=options.get("default"), **common)
    if io_type == "IMAGE":
        return io.Image.Input(name, **common)
    raise ValueError(f"unsupported input type {io_type!r}")


_OUTPUTS = {"IMAGE": lambda n: io.Image.Output(display_name=n),
            "STRING": lambda n: io.String.Output(display_name=n),
            "INT": lambda n: io.Int.Output(display_name=n),
            "FLOAT": lambda n: io.Float.Output(display_name=n),
            "BOOLEAN": lambda n: io.Boolean.Output(display_name=n)}


def build_node_class(base, spec, http=requests):
    """A V3 node class for one remote descriptor."""
    inputs = [_input(*entry) for entry in spec.inputs]
    outputs = [_OUTPUTS[t](n) for t, n in spec.outputs]

    class RemoteNode(io.ComfyNode):
        @classmethod
        def define_schema(cls) -> io.Schema:
            return io.Schema(
                node_id=spec.node_id, display_name=spec.display_name,
                category=spec.category, description=spec.description,
                inputs=inputs, outputs=outputs, hidden=[io.Hidden.unique_id])

        @classmethod
        def execute(cls, **values) -> io.NodeOutput:
            payload = rnp_client.encode_inputs(spec, values, tensor_to_envelope)
            raw = rnp_client.execute(
                http, base, spec, payload, sleep=time.sleep, clock=time.monotonic,
                check=_check_interrupted, progress=_progress(cls))
            if len(raw) != len(spec.outputs):
                raise rnp_client.RemoteFailed(
                    f"{spec.node_id} returned {len(raw)} outputs, "
                    f"schema has {len(spec.outputs)}")
            decoded = []
            preview = None
            for value, (io_type, _name) in zip(raw, spec.outputs):
                value = rnp_client.decode_output(value, io_type)
                if io_type == "IMAGE":
                    value = modal_render.png_to_tensor(value)
                    preview = preview or ui.PreviewImage(value, cls=cls)
                decoded.append(value)
            return io.NodeOutput(*decoded, ui=preview)

    RemoteNode.__name__ = spec.node_id
    RemoteNode.__qualname__ = spec.node_id
    return RemoteNode


def discover(base, http=requests):
    """(classes, display names) for every node the server publishes."""
    rnp_client.fetch_manifest(http, base)
    classes, names = {}, {}
    for node_id, descriptor in rnp_client.fetch_object_info(http, base).items():
        try:
            spec = rnp_client.parse_descriptor(node_id, descriptor)
        except ValueError as exc:
            print(f"[Symbiotica] remote node skipped: {exc}")
            continue
        classes[node_id] = build_node_class(base, spec, http)
        names[node_id] = spec.display_name
    return classes, names


NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

_base = server_url()
if _base:
    try:
        NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS = discover(_base)
        print(f"[Symbiotica] {len(NODE_CLASS_MAPPINGS)} remote node(s) from the RNP server")
    except Exception as exc:  # a dead server must not take the pack down
        print(f"[Symbiotica] RNP server unreachable, no remote nodes: {exc}")
