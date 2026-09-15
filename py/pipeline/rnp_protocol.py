# ABOUTME: The Remote Node Protocol (RNP/1) wire shapes this pack speaks — node
# ABOUTME: descriptors, image envelopes, error bodies. Shared by client and server.
import base64
import hashlib
import json
import re
import struct

PROTOCOL_NAME = "comfy-rnp"
PROTOCOL_VERSION = "1.0"
PROVIDER_ID = "symbiotica-modal"
PROVIDER_NAME = "Symbiotica Modal render engine"
MAX_INLINE_PAYLOAD_BYTES = 8 * 1024 * 1024
POLL_INTERVAL_S = 2.0
# A queued render can wait many minutes for a GPU before its own 540 s cap starts.
SOFT_TIMEOUT_S = 1500.0
HARD_TIMEOUT_S = 1800.0
NODE_ID_PREFIX = "SymbioticaModalRnp_"
CATEGORY = "symbiotica/modal"

HEADER_PROTOCOL_VERSION = "X-RNP-Protocol-Version"
HEADER_CLIENT_VERSION = "X-RNP-Client-Version"
HEADER_CLIENT_CAPABILITIES = "X-RNP-Client-Capabilities"
HEADER_SCHEMA_HASH = "X-RNP-Schema-Hash"
HEADER_IDEMPOTENCY_KEY = "X-RNP-Idempotency-Key"

CAPABILITIES = ["schema:v3", "image:png_base64", "execute:async"]

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"

SCALAR_TYPES = ("STRING", "INT", "FLOAT", "BOOLEAN", "COMBO")


def node_id_for(recipe):
    """A recipe's node id: the prefix plus the name with a Python-safe spelling."""
    return NODE_ID_PREFIX + re.sub(r"[^A-Za-z0-9]+", "_", recipe).strip("_")


def schema_hash(inputs, outputs):
    payload = json.dumps({"input": inputs, "output": outputs}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def descriptor(recipe, graph, manifest, input_specs):
    """One recipe as an RNP node descriptor, in the V3 `get_v1_info` shape the
    official client parses. Every recipe input is a widget; the only output
    is the rendered IMAGE."""
    node_id = node_id_for(recipe)
    required = {}
    order = []
    for name, io_type, options in input_specs:
        required[name] = [io_type, dict(options)]
        order.append(name)
    inputs = {"required": required, "optional": {}, "hidden": {}}
    outputs = ["IMAGE"]
    title = manifest.get("title") or recipe
    return {
        "name": node_id,
        "display_name": f"{title} (Modal RNP)",
        "category": CATEGORY,
        "description": manifest.get("description") or "",
        "input": inputs,
        "input_order": {"required": order, "optional": []},
        "output": outputs,
        "output_name": ["image"],
        "output_is_list": [False],
        "output_tooltips": [None],
        "output_node": False,
        "api_node": False,
        "remote": {
            "endpoints": {
                "execute": {"path": f"rnp/v1/nodes/{node_id}/execute"},
                "execute_async": {"path": f"rnp/v1/nodes/{node_id}/execute_async"},
            },
            "schema_hash": schema_hash(inputs, outputs),
            "execution": {
                "mode": "async_polling",
                "poll_interval_s": POLL_INTERVAL_S,
                "soft_timeout_s": SOFT_TIMEOUT_S,
                "hard_timeout_s": HARD_TIMEOUT_S,
                "estimated_duration_s": manifest.get("estimated_duration_s"),
                "idempotency": "client_key",
            },
            "input_serialization": {},
            "url_fetch": {},
        },
        "recipe": recipe,
    }


def png_size(data):
    """(width, height) off a PNG's IHDR, so the envelope can carry a shape
    without decoding the pixels."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def image_envelope(png_bytes):
    width, height = png_size(png_bytes)
    return {
        "type": "image",
        "encoding": "png_base64",
        "data": base64.b64encode(png_bytes).decode("ascii"),
        "shape": [1, height, width, 3],
        "dtype": "uint8",
        "color_space": "srgb",
    }


def is_envelope(value):
    return (isinstance(value, dict) and isinstance(value.get("type"), str)
            and isinstance(value.get("encoding"), str))


def envelope_bytes(envelope):
    """The bytes of an inline envelope. Only PNG images are spoken here."""
    if envelope.get("type") != "image" or envelope.get("encoding") != "png_base64":
        raise ValueError(
            f"unsupported envelope {envelope.get('type')}:{envelope.get('encoding')}")
    if "data" not in envelope:
        raise ValueError("envelope carries a uri, not inline data")
    return base64.b64decode(envelope["data"])


def error_body(code, message, *, user_facing=True, retryable=False, details=None):
    body = {"code": code, "message": message, "user_facing": user_facing,
            "retryable": retryable}
    if details:
        body["details"] = details
    return {"error": body}


def task_response(state, *, result=None, error=None):
    """The poll body for one task state.

    `result` is the render engine's status body; `error` a string. Kept here
    so the client tests and the server agree on the mapping."""
    if state == "running":
        return {"status": STATUS_RUNNING}
    if state == "cancelled":
        return {"status": STATUS_CANCELLED}
    if state == "error" or (result or {}).get("status") != "succeeded":
        message = error or (result or {}).get("error") or "render failed"
        return {"status": STATUS_ERROR,
                "exception": error_body("PROVIDER_UNAVAILABLE", str(message))}
    data = result.get("image_b64")
    if not data:
        return {"status": STATUS_ERROR,
                "exception": error_body("INTERNAL", "render carried no image")}
    png = base64.b64decode(data)
    try:
        envelope = image_envelope(png)
    except ValueError as exc:
        return {"status": STATUS_ERROR,
                "exception": error_body(
                    "INTERNAL", f"render is a .{result.get('ext')}, not a PNG: {exc}")}
    return {"status": STATUS_DONE, "outputs": [envelope]}
