# ABOUTME: Tests the RNP/1 wire shapes — a recipe's descriptor parses back with
# ABOUTME: the pack's own client, envelopes round-trip, task states map.
import base64
import io

import pytest
from PIL import Image

from pipeline import modal_graphs, rnp_client, rnp_protocol as proto


def png_bytes(w=6, h=3):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


def qwen_descriptor():
    graph = modal_graphs.load("qwen-image")
    return proto.descriptor("qwen-image", graph, modal_graphs.manifest(graph),
                            modal_graphs.input_specs(graph))


def test_node_id_is_python_safe():
    assert proto.node_id_for("qwen-image") == "SymbioticaModalRnp_qwen_image"
    assert proto.node_id_for("wan 2.2/i2v") == "SymbioticaModalRnp_wan_2_2_i2v"


def test_descriptor_has_the_shape_the_official_client_reads():
    d = qwen_descriptor()
    assert d["input"]["required"]["prompt"][0] == "STRING"
    assert d["input"]["required"]["prompt"][1]["multiline"] is True
    assert d["input_order"]["required"] == ["prompt", "negative", "seed", "width", "height"]
    assert d["output"] == ["IMAGE"] and d["output_name"] == ["image"]
    assert d["remote"]["endpoints"]["execute"]["path"].endswith(
        "SymbioticaModalRnp_qwen_image/execute")
    assert d["remote"]["execution"]["mode"] == "async_polling"
    assert d["remote"]["execution"]["estimated_duration_s"] == 70
    assert d["display_name"] == "Qwen Image (Modal RNP)"
    assert len(d["remote"]["schema_hash"]) == 64


def test_descriptor_parses_with_the_pack_client():
    d = qwen_descriptor()
    spec = rnp_client.parse_descriptor(d["name"], d)
    assert spec.node_id == "SymbioticaModalRnp_qwen_image"
    assert [i[0] for i in spec.inputs] == ["prompt", "negative", "seed", "width", "height"]
    assert spec.inputs[2][1] == "INT"
    assert spec.outputs == (("IMAGE", "image"),)
    assert spec.poll_interval_s == 2.0
    assert spec.hard_timeout_s == 600.0


def test_schema_hash_moves_with_the_inputs():
    d = qwen_descriptor()
    other = proto.schema_hash({"required": {"prompt": ["STRING", {}]}}, ["IMAGE"])
    assert d["remote"]["schema_hash"] != other


def test_image_envelope_round_trips_with_the_png_size():
    env = proto.image_envelope(png_bytes(6, 3))
    assert env["type"] == "image" and env["encoding"] == "png_base64"
    assert env["shape"] == [1, 3, 6, 3]
    assert proto.envelope_bytes(env) == png_bytes(6, 3)
    assert proto.is_envelope(env) and not proto.is_envelope({"type": "image"})


def test_envelope_bytes_refuses_uri_only_and_other_kinds():
    with pytest.raises(ValueError, match="uri"):
        proto.envelope_bytes({"type": "image", "encoding": "png_base64", "uri": "x"})
    with pytest.raises(ValueError, match="unsupported"):
        proto.envelope_bytes({"type": "video", "encoding": "mp4_base64", "data": ""})


def test_task_response_maps_the_engine_states():
    assert proto.task_response("running") == {"status": "running"}
    assert proto.task_response("cancelled") == {"status": "cancelled"}
    err = proto.task_response("error", error="boom")
    assert err["status"] == "error"
    assert err["exception"]["error"]["message"] == "boom"
    failed = proto.task_response("done", result={"status": "failed", "error": "graph rejected"})
    assert failed["exception"]["error"]["message"] == "graph rejected"
    done = proto.task_response("done", result={
        "status": "succeeded", "ext": "png",
        "image_b64": base64.b64encode(png_bytes()).decode()})
    assert done["status"] == "done"
    assert done["outputs"][0]["shape"] == [1, 3, 6, 3]


def test_task_response_names_a_non_png_render():
    body = proto.task_response("done", result={
        "status": "succeeded", "ext": "mp4",
        "image_b64": base64.b64encode(b"\x00\x00\x00 ftypisom").decode()})
    assert body["status"] == "error"
    assert ".mp4" in body["exception"]["error"]["message"]
