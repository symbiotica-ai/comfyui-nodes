# ABOUTME: The hub's Modal render door — submit an API graph, poll until it
# ABOUTME: settles, hand back the bytes. Pure: HTTP, clock and sleep are passed in.
import base64
import dataclasses
import io

ENV_NAMES = ("MODAL_ENDPOINT_URL", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET")
SETTINGS_HINT = "Settings → Symbiotica → Modal"
CONNECT_TIMEOUT_S = 10
READ_TIMEOUT_S = 60
POLL_S = 2.0
# The render itself is capped at 540 s on Modal, but that clock starts when a
# GPU is found; a call can sit queued for many minutes first when the card is
# scarce. The wait here covers the queue, not just the render.
TIMEOUT_S = 1800.0


@dataclasses.dataclass(frozen=True)
class Transport:
    base: str
    key: str
    secret: str

    @property
    def headers(self):
        return {"Modal-Key": self.key, "Modal-Secret": self.secret}


class RenderFailed(RuntimeError):
    """The render engine answered, and the answer was not an image."""


def modal_transport(environ, setting=lambda name: None):
    """Where to send a render and what to sign it with.

    The Settings UI wins over the environment, because on Comfy Desktop the
    environment is whatever Electron started Python with, which is nothing."""
    values = {}
    for name in ENV_NAMES:
        value = (setting(name) or environ.get(name) or "").strip()
        if not value:
            raise ValueError(
                f"{name} is not set. All three Modal fields go together in "
                f"{SETTINGS_HINT}: the endpoint URL and the proxy token pair "
                f"from the hub's symbiotica-comfy-proxy-token secret.")
        values[name] = value
    base = values["MODAL_ENDPOINT_URL"].rstrip("/")
    if not base.startswith("https://"):
        raise ValueError(
            f"MODAL_ENDPOINT_URL must be https, got {base!r}; the proxy token "
            f"travels in the headers of every request.")
    return Transport(base, values["MODAL_TOKEN_ID"], values["MODAL_TOKEN_SECRET"])


def _failure(status, text):
    text = (text or "")[:500]
    if status == 401:
        return RenderFailed(
            f"Modal refused the proxy token (401). The pair in {SETTINGS_HINT} "
            f"must be a proxy auth token (wk-…/ws-…), not a CLI token: {text}")
    return RenderFailed(f"Modal render endpoint answered {status}: {text}")


def submit(http, transport, workflow):
    """Queue one API graph; returns the call id the status poll is keyed by."""
    response = http.post(transport.base + "/submit", json={"workflow": workflow},
                         headers=transport.headers,
                         timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S))
    if response.status_code != 200:
        raise _failure(response.status_code, response.text)
    call_id = response.json().get("call_id")
    if not call_id:
        raise RenderFailed(f"submit answered without a call_id: {response.text[:200]}")
    return call_id


def status(http, transport, call_id):
    """One poll: ('running', None) or ('succeeded'|'failed', body)."""
    response = http.get(transport.base + "/status", params={"call_id": call_id},
                        headers=transport.headers,
                        timeout=(CONNECT_TIMEOUT_S, READ_TIMEOUT_S))
    if response.status_code == 202:
        return "running", None
    if response.status_code != 200:
        raise _failure(response.status_code, response.text)
    body = response.json()
    return body.get("status") or "failed", body


def decode(body):
    """(bytes, ext) out of a succeeded status body."""
    if body.get("status") != "succeeded":
        raise RenderFailed(f"render failed on Modal: {body.get('error') or body}")
    data = body.get("image_b64")
    if not data:
        raise RenderFailed("render succeeded but carried no image")
    return base64.b64decode(data), (body.get("ext") or "png").lower()


def render(http, transport, workflow, *, sleep, clock, check=lambda: None,
           progress=lambda text: None, poll_s=POLL_S, timeout_s=TIMEOUT_S):
    """Submit, poll, decode. `check` runs every poll so an interrupted queue
    stops waiting; the render itself finishes on Modal either way."""
    call_id = submit(http, transport, workflow)
    started = clock()
    progress("Modal: queued")
    while True:
        check()
        state, body = status(http, transport, call_id)
        if state != "running":
            return decode(body)
        elapsed = int(clock() - started)
        if elapsed > timeout_s:
            raise RenderFailed(
                f"gave up on Modal render {call_id} after {elapsed}s. It is "
                f"usually still queued for a GPU: run `modal app logs -e dev "
                f"symbiotica-comfy -f` and look for 'waiting to be scheduled'.")
        progress(f"Modal: waiting for the render {elapsed}s")
        sleep(poll_s)


def png_to_tensor(data):
    """PNG bytes as a [1,H,W,3] float tensor. Torch is imported here so the
    pure half stays importable on a box without it."""
    import numpy as np
    import torch
    from PIL import Image

    image = Image.open(io.BytesIO(data)).convert("RGB")
    array = np.asarray(image, dtype=np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)
