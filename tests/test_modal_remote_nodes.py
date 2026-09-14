# ABOUTME: Tests the remote-nodes module — nothing registered without a server
# ABOUTME: URL, a descriptor becomes a working node, a dead server is one line.
import base64
import io
import os
import sys

import pytest
from PIL import Image

from fake_http import FakeHttp, Response
from pipeline import modal_graphs, rnp_client, rnp_protocol as proto
from test_modal_render_node import load_member

BASE = "https://rnp.modal.run/t/tok"


def qwen_info():
    graph = modal_graphs.load("qwen-image")
    d = proto.descriptor("qwen-image", graph, modal_graphs.manifest(graph),
                         modal_graphs.input_specs(graph))
    return {d["name"]: d}


def png_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (8, 4), (0, 255, 0)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def module(monkeypatch):
    monkeypatch.delenv("RNP_SERVER_URL", raising=False)
    return load_member(monkeypatch, "modal_remote_nodes.py", "symbiotica_rnp_under_test")


def test_no_server_url_registers_nothing(module):
    assert module.NODE_CLASS_MAPPINGS == {}


def test_server_url_prefers_settings(module, monkeypatch):
    monkeypatch.setenv("RNP_SERVER_URL", "https://env")
    assert module.server_url(setting=lambda n: "https://ui ") == "https://ui"
    assert module.server_url(setting=lambda n: None) == "https://env"


def test_discover_builds_one_node_per_descriptor(module):
    http = FakeHttp(Response(200, {"protocol_version": "1.0"}), Response(200, qwen_info()))
    classes, names = module.discover(BASE, http)
    cls = classes["SymbioticaModalRnp_qwen_image"]
    assert names["SymbioticaModalRnp_qwen_image"] == "Qwen Image (Modal RNP)"
    schema = cls.GET_SCHEMA()
    assert schema.category == "symbiotica/modal"
    by_id = {i.id: i for i in schema.inputs}
    assert by_id["prompt"].multiline is True
    assert by_id["seed"].control_after_generate is True
    assert by_id["seed"].max == 18446744073709551615
    assert [o.display_name for o in schema.outputs] == ["image"]
    assert cls.__name__ == "SymbioticaModalRnp_qwen_image"


def test_remote_node_executes_and_decodes_the_image(module, monkeypatch):
    monkeypatch.setattr(module.time, "sleep", lambda s: None)
    http = FakeHttp(Response(200, {"protocol_version": "1.0"}), Response(200, qwen_info()),
                    Response(200, {"task_id": "fc-2"}),
                    Response(200, {"status": "done",
                                   "outputs": [proto.image_envelope(png_bytes())]}))
    classes, _ = module.discover(BASE, http)
    out = classes["SymbioticaModalRnp_qwen_image"].execute(
        prompt="green", negative="", seed=5, width=1024, height=1024)
    assert http.calls[2][2]["json"]["inputs"]["prompt"] == "green"
    image = out.result[0]
    assert tuple(image.shape) == (1, 4, 8, 3)
    assert float(image[0, 0, 0, 1]) == 1.0
    assert out.ui.image is image


def test_discover_skips_a_descriptor_it_cannot_draw(module, capsys):
    info = qwen_info()
    info["Weird"] = {"input": {"required": {"a": ["AUDIO", {}]}}, "output": ["IMAGE"],
                     "remote": {"endpoints": {"execute": {"path": "x"}}}}
    http = FakeHttp(Response(200, {"protocol_version": "1.0"}), Response(200, info))
    classes, _ = module.discover(BASE, http)
    assert set(classes) == {"SymbioticaModalRnp_qwen_image"}
    assert "AUDIO" in capsys.readouterr().out


def test_dead_server_at_import_is_one_line_and_no_nodes(monkeypatch, capsys):
    monkeypatch.setenv("RNP_SERVER_URL", "https://127.0.0.1:1/t/x")
    import requests

    def boom(*a, **kw):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(requests, "get", boom)
    module = load_member(monkeypatch, "modal_remote_nodes.py", "symbiotica_rnp_dead")
    assert module.NODE_CLASS_MAPPINGS == {}
    assert "RNP server unreachable" in capsys.readouterr().out


def test_tensor_to_envelope_uses_the_first_frame(module):
    import torch
    tensor = torch.zeros((2, 3, 5, 3))
    tensor[0, :, :, 0] = 1.0
    env = module.tensor_to_envelope(tensor)
    assert env["shape"] == [1, 3, 5, 3]
    image = Image.open(io.BytesIO(base64.b64decode(env["data"])))
    assert image.getpixel((0, 0)) == (255, 0, 0)
