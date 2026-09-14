# ABOUTME: A small RNP/1 client — fetch the server's nodes, run one, poll it.
# ABOUTME: Pure: HTTP, clock and sleep are passed in, so every path is testable.
import dataclasses
import json
import uuid

from . import rnp_protocol as proto

CLIENT_VERSION = "symbiotica-0.1"
CONNECT_TIMEOUT_S = 10
READ_TIMEOUT_S = 60
DISCOVERY_TIMEOUT_S = 15


class RemoteFailed(RuntimeError):
    """The server answered, and the answer was a refusal or a failed task."""


@dataclasses.dataclass(frozen=True)
class NodeSpec:
    node_id: str
    display_name: str
    category: str
    description: str
    inputs: tuple          # (name, io_type, options, optional)
    outputs: tuple         # (io_type, display_name)
    execute_path: str
    poll_interval_s: float
    hard_timeout_s: float
    estimated_duration_s: float | None
    schema_hash: str | None


def headers(extra=None):
    out = {
        proto.HEADER_PROTOCOL_VERSION: proto.PROTOCOL_VERSION,
        proto.HEADER_CLIENT_VERSION: CLIENT_VERSION,
        proto.HEADER_CLIENT_CAPABILITIES: json.dumps(proto.CAPABILITIES),
    }
    if extra:
        out.update(extra)
    return out


def _url(base, path):
    return base.rstrip("/") + "/" + path.lstrip("/")


def _body(response):
    try:
        return response.json()
    except ValueError:
        return None


def _refusal(response):
    body = _body(response)
    err = (body or {}).get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return RemoteFailed(
            f"{err.get('code') or 'ERROR'}: {err.get('message') or response.status_code}")
    return RemoteFailed(
        f"RNP server answered {response.status_code}: {(response.text or '')[:300]}")


def _get(http, url, timeout=READ_TIMEOUT_S, extra=None):
    response = http.get(url, headers=headers(extra), timeout=(CONNECT_TIMEOUT_S, timeout))
    if response.status_code >= 400:
        raise _refusal(response)
    return _body(response)


def _post(http, url, payload, timeout=READ_TIMEOUT_S, extra=None):
    response = http.post(url, json=payload, headers=headers(extra),
                         timeout=(CONNECT_TIMEOUT_S, timeout))
    if response.status_code >= 400:
        raise _refusal(response)
    return _body(response)


def fetch_manifest(http, base):
    manifest = _get(http, _url(base, "rnp/v1/manifest"), DISCOVERY_TIMEOUT_S)
    version = str((manifest or {}).get("protocol_version") or "")
    if version.split(".")[0] != proto.PROTOCOL_VERSION.split(".")[0]:
        raise RemoteFailed(
            f"RNP server speaks protocol {version or '?'}, this client "
            f"speaks {proto.PROTOCOL_VERSION}")
    return manifest


def fetch_object_info(http, base):
    info = _get(http, _url(base, "rnp/v1/object_info"), DISCOVERY_TIMEOUT_S)
    if not isinstance(info, dict):
        raise RemoteFailed("RNP object_info was not a JSON object")
    return info


def parse_descriptor(node_id, d):
    """A descriptor as a NodeSpec, or ValueError naming what is unsupported."""
    remote = d.get("remote") or {}
    endpoints = remote.get("endpoints") or {}
    execute = endpoints.get("execute") or {}
    if not execute.get("path"):
        raise ValueError(f"{node_id}: no remote.endpoints.execute")
    inputs = []
    input_def = d.get("input") or {}
    order = d.get("input_order") or {}
    for kind, optional in (("required", False), ("optional", True)):
        defs = input_def.get(kind) or {}
        for name in order.get(kind) or list(defs):
            spec = defs.get(name)
            if spec is None:
                continue
            io_type = spec[0]
            options = spec[1] if len(spec) > 1 and isinstance(spec[1], dict) else {}
            if isinstance(io_type, list):
                options = dict(options, options=list(io_type))
                io_type = "COMBO"
            if io_type not in proto.SCALAR_TYPES + ("IMAGE",):
                raise ValueError(f"{node_id}: unsupported input type {io_type!r}")
            inputs.append((name, io_type, dict(options), optional))
    outputs = []
    names = d.get("output_name") or d.get("output") or []
    for i, io_type in enumerate(d.get("output") or []):
        if io_type not in ("IMAGE", "STRING", "INT", "FLOAT", "BOOLEAN"):
            raise ValueError(f"{node_id}: unsupported output type {io_type!r}")
        outputs.append((io_type, names[i] if i < len(names) else io_type))
    if not outputs:
        raise ValueError(f"{node_id}: no outputs")
    execution = remote.get("execution") or {}
    return NodeSpec(
        node_id=node_id,
        display_name=d.get("display_name") or node_id,
        category=d.get("category") or "remote",
        description=d.get("description") or "",
        inputs=tuple(inputs),
        outputs=tuple(outputs),
        execute_path=execute["path"],
        poll_interval_s=float(execution.get("poll_interval_s") or proto.POLL_INTERVAL_S),
        hard_timeout_s=float(execution.get("hard_timeout_s")
                             or execution.get("soft_timeout_s") or proto.HARD_TIMEOUT_S),
        estimated_duration_s=execution.get("estimated_duration_s"),
        schema_hash=remote.get("schema_hash"),
    )


def encode_inputs(spec, values, encode_image=None):
    """The request `inputs`: scalars as they are, IMAGE tensors as envelopes."""
    payload = {}
    for name, io_type, _options, optional in spec.inputs:
        if name not in values:
            if optional:
                continue
            raise ValueError(f"{spec.node_id}: input {name!r} missing")
        value = values[name]
        if io_type == "IMAGE":
            if encode_image is None:
                raise ValueError(f"{spec.node_id}: no image encoder for {name!r}")
            value = encode_image(value)
        payload[name] = value
    return payload


def execute(http, base, spec, payload, *, sleep, clock, check=lambda: None,
            progress=lambda text: None):
    """Submit through execute_async and poll to a terminal state; returns the
    raw outputs list (envelopes and scalars). An interrupt while polling
    cancels the task best-effort and re-raises."""
    key = uuid.uuid4().hex
    extra = {proto.HEADER_IDEMPOTENCY_KEY: key}
    if spec.schema_hash:
        extra[proto.HEADER_SCHEMA_HASH] = spec.schema_hash
    submit = _post(http, _url(base, f"rnp/v1/nodes/{spec.node_id}/execute_async"),
                   {"inputs": payload, "context": {}}, extra=extra)
    task_id = (submit or {}).get("task_id")
    if not task_id:
        raise RemoteFailed(f"execute_async answered without a task_id: {submit!r}")
    interval = float((submit or {}).get("poll_interval") or spec.poll_interval_s)
    started = clock()
    progress("Modal RNP: queued")
    poll_url = _url(base, f"rnp/v1/tasks/{task_id}")
    while True:
        try:
            check()
        except BaseException:
            try:
                http.post(_url(base, f"rnp/v1/tasks/{task_id}/cancel"),
                          headers=headers(extra), timeout=(CONNECT_TIMEOUT_S, 10))
            except Exception:
                pass
            raise
        body = _get(http, poll_url, extra=extra) or {}
        status = body.get("status")
        if status == proto.STATUS_DONE:
            outputs = body.get("outputs")
            if not isinstance(outputs, list):
                raise RemoteFailed(f"task {task_id} done without outputs")
            return outputs
        if status == proto.STATUS_ERROR:
            err = (body.get("exception") or {}).get("error") or {}
            raise RemoteFailed(
                f"{err.get('code') or 'ERROR'}: {err.get('message') or 'remote task failed'}")
        if status == proto.STATUS_CANCELLED:
            raise RemoteFailed(f"task {task_id} was cancelled on the server")
        if status not in (proto.STATUS_PENDING, proto.STATUS_RUNNING):
            raise RemoteFailed(f"task {task_id} in unknown state {status!r}")
        elapsed = int(clock() - started)
        if elapsed > spec.hard_timeout_s:
            raise RemoteFailed(
                f"task {task_id} still {status} after {elapsed}s, past the "
                f"node's {int(spec.hard_timeout_s)}s budget")
        progress(f"Modal RNP: {status} {elapsed}s")
        sleep(interval)


def decode_output(value, io_type):
    """An output as the node hands it on: PNG bytes for IMAGE, the scalar itself
    otherwise."""
    if io_type == "IMAGE":
        if not proto.is_envelope(value):
            raise RemoteFailed("IMAGE output was not an envelope")
        return proto.envelope_bytes(value)
    return value
