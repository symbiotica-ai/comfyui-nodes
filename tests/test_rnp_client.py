# ABOUTME: Tests the pack's RNP client — discovery, the execute/poll loop,
# ABOUTME: refusals, and cancelling the task when the queue is interrupted.
import json

import pytest

from fake_http import FakeHttp, Response
from pipeline import rnp_client, rnp_protocol as proto

BASE = "https://rnp.modal.run/t/tok/"


def spec(**kw):
    d = {
        "input": {"required": {"prompt": ["STRING", {"multiline": True}],
                               "seed": ["INT", {"default": 0}]}},
        "output": ["IMAGE"], "output_name": ["image"],
        "remote": {"endpoints": {"execute": {"path": "rnp/v1/nodes/N/execute"}},
                   "execution": {"poll_interval_s": 1, "hard_timeout_s": 10},
                   "schema_hash": "abc"},
    }
    d.update(kw)
    return rnp_client.parse_descriptor("N", d)


def run(http, s=None, **kw):
    clock = iter(range(0, 10000, 4))
    return rnp_client.execute(http, BASE, s or spec(), {"prompt": "x", "seed": 1},
                              sleep=lambda t: None, clock=lambda: next(clock), **kw)


def test_manifest_handshake_checks_the_major_version():
    http = FakeHttp(Response(200, {"protocol_version": "1.3"}))
    rnp_client.fetch_manifest(http, BASE)
    assert http.calls[0][1] == "https://rnp.modal.run/t/tok/rnp/v1/manifest"
    sent = http.calls[0][2]["headers"]
    assert sent[proto.HEADER_PROTOCOL_VERSION] == "1.0"
    assert "image:png_base64" in json.loads(sent[proto.HEADER_CLIENT_CAPABILITIES])
    with pytest.raises(rnp_client.RemoteFailed, match="protocol 2.0"):
        rnp_client.fetch_manifest(FakeHttp(Response(200, {"protocol_version": "2.0"})), BASE)


def test_parse_descriptor_rejects_what_this_client_cannot_draw():
    with pytest.raises(ValueError, match="AUDIO"):
        spec(input={"required": {"a": ["AUDIO", {}]}})
    with pytest.raises(ValueError, match="VIDEO"):
        spec(output=["VIDEO"], output_name=["v"])
    with pytest.raises(ValueError, match="execute"):
        spec(remote={})


def test_parse_descriptor_turns_a_legacy_list_combo_into_options():
    s = spec(input={"required": {"size": [["1K", "2K"], {"default": "1K"}]}})
    assert s.inputs[0][1] == "COMBO"
    assert s.inputs[0][2]["options"] == ["1K", "2K"]


def test_encode_inputs_envelopes_images_and_requires_the_rest():
    s = spec(input={"required": {"prompt": ["STRING", {}], "image": ["IMAGE", {}]},
                    "optional": {"seed": ["INT", {}]}})
    payload = rnp_client.encode_inputs(s, {"prompt": "p", "image": "T"},
                                       encode_image=lambda t: {"type": "image", "encoding": "png_base64", "data": t})
    assert payload == {"prompt": "p", "image": {"type": "image", "encoding": "png_base64", "data": "T"}}
    with pytest.raises(ValueError, match="'prompt' missing"):
        rnp_client.encode_inputs(s, {"image": "T"}, encode_image=lambda t: t)


def test_execute_submits_polls_and_returns_outputs():
    http = FakeHttp(Response(200, {"task_id": "fc-1", "poll_interval": 0.5}),
                    Response(200, {"status": "pending"}),
                    Response(200, {"status": "running"}),
                    Response(200, {"status": "done", "outputs": ["E"]}))
    shown = []
    assert run(http, progress=shown.append) == ["E"]
    method, url, kw = http.calls[0]
    assert (method, url) == ("POST", "https://rnp.modal.run/t/tok/rnp/v1/nodes/N/execute_async")
    assert kw["json"] == {"inputs": {"prompt": "x", "seed": 1}, "context": {}}
    assert kw["headers"][proto.HEADER_SCHEMA_HASH] == "abc"
    key = kw["headers"][proto.HEADER_IDEMPOTENCY_KEY]
    assert http.calls[1][1] == "https://rnp.modal.run/t/tok/rnp/v1/tasks/fc-1"
    assert http.calls[1][2]["headers"][proto.HEADER_IDEMPOTENCY_KEY] == key
    assert shown[1].startswith("Modal RNP: pending")


def test_execute_surfaces_the_server_error_envelope():
    http = FakeHttp(Response(200, {"task_id": "fc-1"}),
                    Response(200, {"status": "error", "exception": proto.error_body(
                        "PROVIDER_UNAVAILABLE", "ComfyUI rejected the graph")}))
    with pytest.raises(rnp_client.RemoteFailed, match="PROVIDER_UNAVAILABLE: ComfyUI rejected"):
        run(http)


def test_execute_refusal_on_submit_carries_the_code():
    http = FakeHttp(Response(401, proto.error_body("AUTH_FAILED", "unknown access token")))
    with pytest.raises(rnp_client.RemoteFailed, match="AUTH_FAILED: unknown access token"):
        run(http)


def test_execute_times_out_on_the_descriptor_budget():
    http = FakeHttp(Response(200, {"task_id": "fc-1"}),
                    *[Response(200, {"status": "running"})] * 6)
    with pytest.raises(rnp_client.RemoteFailed, match="past the node's 10s budget"):
        run(http)


def test_interrupt_cancels_the_task_then_re_raises():
    http = FakeHttp(Response(200, {"task_id": "fc-1"}),
                    Response(200, {"status": "running"}),
                    Response(200, {"status": "cancelled"}))
    polls = iter([None, KeyboardInterrupt()])

    def check():
        item = next(polls)
        if item:
            raise item
    with pytest.raises(KeyboardInterrupt):
        run(http, check=check)
    assert http.calls[-1][:2] == ("POST", "https://rnp.modal.run/t/tok/rnp/v1/tasks/fc-1/cancel")


def test_decode_output_only_unwraps_images():
    env = {"type": "image", "encoding": "png_base64", "data": "AAAA"}
    assert rnp_client.decode_output(env, "IMAGE") == b"\x00\x00\x00"
    assert rnp_client.decode_output("hi", "STRING") == "hi"
    with pytest.raises(rnp_client.RemoteFailed, match="not an envelope"):
        rnp_client.decode_output("hi", "IMAGE")
