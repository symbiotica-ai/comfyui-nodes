# ABOUTME: The Symbiotica RNP/1 server on Modal — publishes the pack's pinned
# ABOUTME: recipes as remote nodes and runs them on the hub's render engine.
#
# Deploy:   modal deploy -e dev modal/rnp_server.py
# Secret:   modal secret create -e dev symbiotica-rnp RNP_ACCESS_TOKEN=<token>
# Client:   Settings → Symbiotica → Modal → Remote nodes server URL =
#           https://symbiotica-dev--symbiotica-rnp-api.modal.run/t/<token>
#
# Access is the token in the path: the official RNP client sends no headers
# of its own, so the URL is the one credential it can carry.
import os
import secrets
from pathlib import Path

import modal

APP_NAME = "symbiotica-rnp"
RENDER_APP = "symbiotica-comfy"
RENDER_CLASS = "Comfy"
SECRET_NAME = "symbiotica-rnp"
RECIPES_REMOTE = "/root/modal_workflows"
REPO = Path(__file__).resolve().parent.parent

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("fastapi[standard]")
    .add_local_file(REPO / "py" / "pipeline" / "modal_graphs.py", "/root/modal_graphs.py")
    .add_local_file(REPO / "py" / "pipeline" / "rnp_protocol.py", "/root/rnp_protocol.py")
    .add_local_dir(REPO / "py" / "modal_workflows", RECIPES_REMOTE)
)

app = modal.App(APP_NAME)
# Idempotency key → call id, so a retried submit returns the task it already
# started instead of paying for a second render.
idempotency = modal.Dict.from_name("symbiotica-rnp-idempotency", create_if_missing=True)


@app.function(image=image, secrets=[modal.Secret.from_name(SECRET_NAME)], timeout=900)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def api():
    import hashlib
    import json

    os.environ["SYMBIOTICA_MODAL_RECIPES"] = RECIPES_REMOTE
    import modal_graphs
    import rnp_protocol as proto
    from fastapi import APIRouter, FastAPI, HTTPException, Request, Response
    from fastapi.responses import JSONResponse

    expected = os.environ["RNP_ACCESS_TOKEN"]
    render_cls = modal.Cls.from_name(RENDER_APP, RENDER_CLASS)

    def refuse(status, code, message, retryable=False):
        return HTTPException(status, detail=proto.error_body(
            code, message, retryable=retryable))

    def graphs():
        out = {}
        for name in modal_graphs.recipes():
            graph = modal_graphs.load(name)
            out[proto.node_id_for(name)] = (name, graph)
        return out

    def object_info():
        info = {}
        for node_id, (name, graph) in graphs().items():
            info[node_id] = proto.descriptor(
                name, graph, modal_graphs.manifest(graph), modal_graphs.input_specs(graph))
        return info

    web = FastAPI()

    @web.exception_handler(HTTPException)
    async def _envelope(request, exc):
        detail = exc.detail if isinstance(exc.detail, dict) else proto.error_body(
            "INTERNAL", str(exc.detail))
        return JSONResponse(detail, status_code=exc.status_code)

    router = APIRouter(prefix="/t/{token}/rnp/v1")

    def guard(token):
        if not secrets.compare_digest(token, expected):
            raise refuse(401, "AUTH_FAILED", "unknown access token")

    @router.get("/manifest")
    def manifest(token: str):
        guard(token)
        return {
            "protocol_name": proto.PROTOCOL_NAME,
            "protocol_version": proto.PROTOCOL_VERSION,
            "provider": {"id": proto.PROVIDER_ID, "name": proto.PROVIDER_NAME},
            "capabilities": proto.CAPABILITIES,
            "max_inline_payload_bytes": proto.MAX_INLINE_PAYLOAD_BYTES,
        }

    @router.get("/object_info")
    def object_info_route(token: str, request: Request):
        guard(token)
        body = json.dumps(object_info(), sort_keys=True)
        etag = '"' + hashlib.sha256(body.encode()).hexdigest()[:32] + '"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return Response(body, media_type="application/json",
                        headers={"ETag": etag, "Cache-Control": "max-age=300"})

    def bound_graph(node_id, payload):
        entry = graphs().get(node_id)
        if entry is None:
            raise refuse(404, "NOT_FOUND", f"no remote node {node_id}")
        name, graph = entry
        inputs = payload.get("inputs") if isinstance(payload, dict) else None
        if not isinstance(inputs, dict):
            raise refuse(400, "INPUT_INVALID", "body needs an inputs object")
        for key, value in inputs.items():
            if proto.is_envelope(value):
                raise refuse(400, "INPUT_INVALID",
                             f"{name} takes no media input ({key}); the render "
                             f"engine has no inputs volume yet")
        values = dict(modal_graphs.defaults(graph))
        try:
            values.update(inputs)
            return modal_graphs.bind(graph, values, strict=True)
        except ValueError as exc:
            raise refuse(400, "INPUT_INVALID", str(exc))

    def spawn(node_id, payload, key):
        if key:
            existing = idempotency.get(key)
            if existing:
                return existing
        graph = bound_graph(node_id, payload)
        call = render_cls().render.spawn(graph)
        if key:
            idempotency[key] = call.object_id
        return call.object_id

    @router.post("/nodes/{node_id}/execute_async")
    async def execute_async(token: str, node_id: str, request: Request):
        guard(token)
        payload = await request.json()
        key = request.headers.get(proto.HEADER_IDEMPOTENCY_KEY)
        return {"task_id": spawn(node_id, payload, key),
                "poll_interval": proto.POLL_INTERVAL_S}

    def poll(task_id):
        try:
            call = modal.FunctionCall.from_id(task_id)
        except Exception:
            raise refuse(404, "NOT_FOUND", f"no task {task_id}")
        try:
            result = call.get(timeout=0)
        except TimeoutError:
            return proto.task_response("running")
        except modal.exception.FunctionTimeoutError as exc:
            return proto.task_response("error", error=f"render timed out: {exc}")
        except Exception as exc:
            text = str(exc)
            if "cancel" in text.lower():
                return proto.task_response("cancelled")
            return proto.task_response("error", error=text)
        return proto.task_response("done", result=result)

    @router.get("/tasks/{task_id}")
    def task(token: str, task_id: str):
        guard(token)
        return poll(task_id)

    @router.post("/tasks/{task_id}/cancel")
    def cancel(token: str, task_id: str):
        guard(token)
        try:
            modal.FunctionCall.from_id(task_id).cancel()
        except Exception as exc:
            raise refuse(404, "NOT_FOUND", f"no task {task_id}: {exc}")
        return {"status": proto.STATUS_CANCELLED}

    @router.post("/nodes/{node_id}/execute")
    async def execute(token: str, node_id: str, request: Request):
        guard(token)
        payload = await request.json()
        task_id = spawn(node_id, payload, request.headers.get(proto.HEADER_IDEMPOTENCY_KEY))
        try:
            result = modal.FunctionCall.from_id(task_id).get(timeout=proto.HARD_TIMEOUT_S)
        except TimeoutError:
            raise refuse(504, "TIMEOUT", f"task {task_id} passed {proto.HARD_TIMEOUT_S}s")
        except Exception as exc:
            raise refuse(502, "PROVIDER_UNAVAILABLE", str(exc))
        body = proto.task_response("done", result=result)
        if body["status"] != proto.STATUS_DONE:
            raise refuse(502, "PROVIDER_UNAVAILABLE",
                         body["exception"]["error"]["message"])
        return {"outputs": body["outputs"]}

    web.include_router(router)
    return web
