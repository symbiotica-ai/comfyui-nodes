# ABOUTME: Tests the Modal Render node — it loads without ComfyUI, offers the
# ABOUTME: recipe list, and turns a rendered PNG into an IMAGE with a preview.
import base64
import importlib.util
import io
import os
import sys
import types

import pytest
from PIL import Image

import comfy_api_stub
from fake_http import FakeHttp, Response

PY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "py")


def load_member(monkeypatch, filename, pkg_name):
    comfy_pkg, comfy_latest = comfy_api_stub.build_modules()
    monkeypatch.setitem(sys.modules, "comfy_api", comfy_pkg)
    monkeypatch.setitem(sys.modules, "comfy_api.latest", comfy_latest)
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [PY_DIR]
    monkeypatch.setitem(sys.modules, pkg_name, pkg)
    spec = importlib.util.spec_from_file_location(
        f"{pkg_name}.{filename[:-3]}", os.path.join(PY_DIR, filename))
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def node_module(monkeypatch):
    return load_member(monkeypatch, "modal_render.py", "symbiotica_modal_under_test")


def test_node_registers_with_the_recipe_combo(node_module):
    assert "SymbioticaModalRender" in node_module.NODE_CLASS_MAPPINGS
    schema = node_module.SymbioticaModalRender.GET_SCHEMA()
    assert schema.node_id == "SymbioticaModalRender"
    assert schema.category == "symbiotica/modal"
    by_id = {i.id: i for i in schema.inputs}
    assert "qwen-image" in by_id["recipe"].options
    assert by_id["seed"].control_after_generate is True
    assert [o.display_name for o in schema.outputs] == ["image"]


def test_execute_binds_the_recipe_and_returns_the_image(node_module, monkeypatch):
    buf = io.BytesIO()
    Image.new("RGB", (8, 4), (255, 0, 0)).save(buf, format="PNG")
    http = FakeHttp(Response(200, {"call_id": "fc-9"}),
                    Response(200, {"status": "succeeded", "ext": "png",
                                   "image_b64": base64.b64encode(buf.getvalue()).decode()}))
    monkeypatch.setattr(node_module, "requests", http)
    monkeypatch.setattr(node_module.time, "sleep", lambda s: None)
    for name, value in (("MODAL_ENDPOINT_URL", "https://x.modal.run"),
                        ("MODAL_TOKEN_ID", "wk-1"), ("MODAL_TOKEN_SECRET", "ws-1")):
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(node_module, "key_from_settings", lambda *a: None)

    out = node_module.SymbioticaModalRender.execute(
        recipe="qwen-image", prompt="a red square", negative="", seed=3,
        width=512, height=768)

    sent = http.calls[0][2]["json"]["workflow"]
    assert sent["6"]["inputs"]["text"] == "a red square"
    assert sent["9"]["inputs"]["seed"] == 3
    assert (sent["8"]["inputs"]["width"], sent["8"]["inputs"]["height"]) == (512, 768)
    assert "_symbiotica" not in sent
    image = out.result[0]
    assert tuple(image.shape) == (1, 4, 8, 3)
    assert float(image[0, 0, 0, 0]) == 1.0
    assert out.ui.image is image


def test_execute_without_credentials_says_where_to_put_them(node_module, monkeypatch):
    for name in ("MODAL_ENDPOINT_URL", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(node_module, "key_from_settings", lambda *a: None)
    with pytest.raises(ValueError, match="Settings → Symbiotica → Modal"):
        node_module.SymbioticaModalRender.execute(
            recipe="qwen-image", prompt="", negative="", seed=0, width=1024, height=1024)
