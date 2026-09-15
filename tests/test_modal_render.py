# ABOUTME: Tests the Modal render transport — credentials, submit, the status
# ABOUTME: poll, decoding, and every way the door can say no.
import base64
import io

import pytest
from PIL import Image

from fake_http import FakeHttp, Response
from pipeline import modal_render

ENV = {"MODAL_ENDPOINT_URL": "https://x.modal.run/", "MODAL_TOKEN_ID": "wk-1",
       "MODAL_TOKEN_SECRET": "ws-1"}


def png_bytes(w=4, h=2):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (10, 20, 30)).save(buf, format="PNG")
    return buf.getvalue()


def succeeded(data=None):
    return {"status": "succeeded", "ext": "png",
            "image_b64": base64.b64encode(data or png_bytes()).decode()}


def test_transport_settings_win_over_environment():
    t = modal_render.modal_transport(
        dict(ENV, MODAL_TOKEN_ID="wk-env"),
        setting={"MODAL_TOKEN_ID": "wk-ui"}.get)
    assert t.key == "wk-ui"
    assert t.base == "https://x.modal.run"
    assert t.headers == {"Modal-Key": "wk-ui", "Modal-Secret": "ws-1"}


@pytest.mark.parametrize("missing", modal_render.ENV_NAMES)
def test_transport_names_the_missing_field_and_the_settings_page(missing):
    env = dict(ENV)
    env[missing] = " "
    with pytest.raises(ValueError, match=f"{missing}.*Settings → Symbiotica → Modal"):
        modal_render.modal_transport(env)


def test_transport_refuses_plain_http():
    with pytest.raises(ValueError, match="https"):
        modal_render.modal_transport(dict(ENV, MODAL_ENDPOINT_URL="http://x"))


def run(http, **kw):
    t = modal_render.modal_transport(ENV)
    clock = iter(range(0, 10000, 3))
    return modal_render.render(http, t, {"1": {}}, sleep=lambda s: None,
                               clock=lambda: next(clock), **kw)


def test_render_submits_polls_and_decodes():
    http = FakeHttp(Response(200, {"call_id": "fc-1"}), Response(202, {"status": "running"}),
                    Response(200, succeeded()))
    shown = []
    data, ext = run(http, progress=shown.append)
    assert (data, ext) == (png_bytes(), "png")
    method, url, kw = http.calls[0]
    assert (method, url) == ("POST", "https://x.modal.run/submit")
    assert kw["json"] == {"workflow": {"1": {}}}
    assert kw["headers"]["Modal-Key"] == "wk-1"
    assert http.calls[1][1] == "https://x.modal.run/status"
    assert http.calls[1][2]["params"] == {"call_id": "fc-1"}
    assert shown[0] == "Modal: queued"
    assert shown[1].startswith("Modal: waiting for the render")


def test_render_reports_a_failed_run_with_the_engine_reason():
    http = FakeHttp(Response(200, {"call_id": "fc-1"}),
                    Response(200, {"status": "failed", "error": "ComfyUI rejected the graph"}))
    with pytest.raises(modal_render.RenderFailed, match="rejected the graph"):
        run(http)


def test_render_401_points_at_the_proxy_token():
    http = FakeHttp(Response(401, text="modal-http: invalid credentials"))
    with pytest.raises(modal_render.RenderFailed, match="proxy auth token.*invalid credentials"):
        run(http)


def test_render_stops_waiting_past_the_budget():
    http = FakeHttp(Response(200, {"call_id": "fc-1"}),
                    *[Response(202, {"status": "running"})] * 5)
    with pytest.raises(modal_render.RenderFailed, match="gave up on Modal render.*waiting to be scheduled"):
        run(http, timeout_s=5)


def test_render_check_runs_every_poll_and_can_abort():
    http = FakeHttp(Response(200, {"call_id": "fc-1"}), Response(202, {"status": "running"}))
    polls = iter([None, KeyboardInterrupt()])

    def check():
        item = next(polls)
        if item:
            raise item
    with pytest.raises(KeyboardInterrupt):
        run(http, check=check)
    assert len(http.calls) == 2


def test_decode_refuses_a_success_without_an_image():
    with pytest.raises(modal_render.RenderFailed, match="no image"):
        modal_render.decode({"status": "succeeded", "ext": "png"})


def test_png_to_tensor_shape_and_range():
    tensor = modal_render.png_to_tensor(png_bytes(4, 2))
    assert tuple(tensor.shape) == (1, 2, 4, 3)
    assert abs(float(tensor[0, 0, 0, 0]) - 10 / 255) < 1e-6
