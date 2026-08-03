# ABOUTME: Tests the Gemini Image node's registration and schema — it must load
# ABOUTME: without ComfyUI present, be discoverable, and offer what the spec says.
import base64
import importlib.util
import inspect
import io
import os
import sys
import types

import numpy as np
import pytest
from PIL import Image

PY_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "py")


@pytest.fixture
def node_module(monkeypatch):
    """py/gemini_image.py loaded as the package member it is at run time.

    The pack's loader imports every py/*.py inside a try/except that only
    prints the traceback, so a wrapper that will not import loses its node
    while the pack still loads clean. Loading it for real here is what makes
    that loud — and it must be loaded as a package member, because the module
    reaches its pure half through a relative import that a flat load cannot
    resolve."""
    pkg = types.ModuleType("symbiotica_gemini_under_test")
    pkg.__path__ = [PY_DIR]
    monkeypatch.setitem(sys.modules, "symbiotica_gemini_under_test", pkg)
    spec = importlib.util.spec_from_file_location(
        "symbiotica_gemini_under_test.gemini_image",
        os.path.join(PY_DIR, "gemini_image.py"))
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    return mod


def test_the_node_is_registered_under_the_house_prefix(node_module):
    assert "SymbioticaGeminiImage" in node_module.NODE_CLASS_MAPPINGS


def test_the_display_name_tells_it_apart_from_comfyuis_own_gemini_nodes(node_module):
    """Stock ComfyUI ships Gemini image nodes that sit in the same search
    results. A name that does not say whose it is picks itself by accident."""
    shown = node_module.NODE_DISPLAY_NAME_MAPPINGS["SymbioticaGeminiImage"]
    assert shown == "Gemini Image (Symbiotica)"


def test_the_node_sits_with_the_packs_other_image_work(node_module):
    assert node_module.SymbioticaGeminiImage.CATEGORY == "symbiotica/image"


def test_it_returns_the_render_and_the_models_words(node_module):
    cls = node_module.SymbioticaGeminiImage
    assert cls.RETURN_TYPES == ("IMAGE", "STRING")
    assert cls.RETURN_NAMES == ("image", "text")


def test_every_widget_the_scope_calls_for_is_present(node_module):
    schema = node_module.SymbioticaGeminiImage.INPUT_TYPES()
    required, optional = schema["required"], schema["optional"]
    assert set(required) == {"prompt", "model", "seed", "aspect_ratio",
                             "resolution"}
    assert set(optional) == {"images", "system_prompt", "api_key"}


def test_the_execute_signature_matches_the_widgets_comfyui_will_pass(node_module):
    """ComfyUI calls execute with the widget names as keywords. A schema that
    names something execute does not accept fails only at run time, in a
    sandbox, on somebody's order."""
    schema = node_module.SymbioticaGeminiImage.INPUT_TYPES()
    declared = set(schema["required"]) | set(schema["optional"])
    accepted = set(inspect.signature(
        node_module.SymbioticaGeminiImage.execute).parameters) - {"self"}
    assert declared == accepted


def test_the_reference_input_is_optional_so_a_prompt_alone_works(node_module):
    schema = node_module.SymbioticaGeminiImage.INPUT_TYPES()
    assert schema["optional"]["images"][0] == "IMAGE"
    signature = inspect.signature(node_module.SymbioticaGeminiImage.execute)
    assert signature.parameters["images"].default is None


def test_the_model_choices_are_the_ones_the_module_knows(node_module):
    from pipeline import gemini_image
    schema = node_module.SymbioticaGeminiImage.INPUT_TYPES()
    assert schema["required"]["model"][0] == gemini_image.MODELS
    assert schema["required"]["aspect_ratio"][0] == gemini_image.ASPECT_RATIOS
    assert schema["required"]["resolution"][0] == gemini_image.RESOLUTIONS


def test_the_system_prompt_defaults_to_the_one_that_forces_an_image(node_module):
    """Left blank the node sends no systemInstruction at all, and a
    conversational prompt comes back as a paragraph — a failed order."""
    from pipeline import gemini_image
    schema = node_module.SymbioticaGeminiImage.INPUT_TYPES()
    assert (schema["optional"]["system_prompt"][1]["default"]
            == gemini_image.GEMINI_IMAGE_SYS_PROMPT)


def test_the_seed_says_out_loud_that_it_never_reaches_google(node_module):
    """It exists to defeat ComfyUI's output cache. Without the tooltip saying
    so, the next reader finds a widget that is built and never sent, and
    "fixes" it by sending it."""
    schema = node_module.SymbioticaGeminiImage.INPUT_TYPES()
    tooltip = schema["required"]["seed"][1]["tooltip"].lower()
    assert "not sent" in tooltip
    assert schema["required"]["seed"][1]["control_after_generate"] is True


def test_no_reference_input_is_no_references_rather_than_a_crash(node_module):
    assert node_module.to_pil(None) == []


def test_a_float_batch_becomes_pixels_at_full_range(node_module):
    batch = np.full((1, 2, 2, 3), 0.5, dtype=np.float32)
    assert node_module.to_pil(batch)[0].getpixel((0, 0)) == (128, 128, 128)


def test_a_batch_already_in_bytes_is_not_scaled_a_second_time(node_module):
    """A uint8 200 multiplied by 255 is not a brighter pixel, it is a
    different image — every mid-tone saturates to white."""
    batch = np.full((1, 2, 2, 3), 200, dtype=np.uint8)
    assert node_module.to_pil(batch)[0].getpixel((0, 0)) == (200, 200, 200)


def test_values_outside_the_range_are_clipped_rather_than_wrapped(node_module):
    """Nodes upstream do overshoot. uint8 conversion of 1.5 wraps to a dark
    pixel, which reads as a rendering bug rather than a range one."""
    batch = np.array([[[[1.5, -0.5, 0.0]]]], dtype=np.float32)
    assert node_module.to_pil(batch)[0].getpixel((0, 0)) == (255, 0, 0)


def test_every_reference_in_the_batch_is_sent_in_order(node_module):
    batch = np.stack([np.full((2, 2, 3), 0.0, dtype=np.float32),
                      np.full((2, 2, 3), 1.0, dtype=np.float32)])
    pixels = [im.getpixel((0, 0)) for im in node_module.to_pil(batch)]
    assert pixels == [(0, 0, 0), (255, 255, 255)]


def test_renders_of_mixed_channel_counts_still_stack_into_one_batch(node_module):
    """Gemini may answer RGBA, or a palette image. A batch of images that do
    not agree on channels cannot stack, and the error names shapes rather than
    the model that returned them."""
    pytest.importorskip("torch")
    batch = node_module.to_tensor([Image.new("RGBA", (2, 2), (255, 0, 0, 128)),
                                   Image.new("RGB", (2, 2), (0, 0, 255))])
    assert tuple(batch.shape) == (2, 2, 2, 3)
    assert batch.max() <= 1.0 and batch.min() >= 0.0
    assert [round(float(v), 2) for v in batch[0, 0, 0]] == [1.0, 0.0, 0.0]


def test_renders_of_different_sizes_are_refused_by_name_not_by_numpy(node_module):
    """Gemini can answer with more than one image and nothing promises they
    agree on size. numpy's "all input arrays must have the same shape" names
    neither Gemini nor the sizes, so the operator cannot tell it from a bug in
    the tensor code."""
    pytest.importorskip("torch")
    with pytest.raises(ValueError, match="different sizes"):
        node_module.to_tensor([Image.new("RGB", (4, 4)),
                               Image.new("RGB", (8, 8))])


def test_a_single_render_of_any_size_is_still_fine(node_module):
    pytest.importorskip("torch")
    assert tuple(node_module.to_tensor(
        [Image.new("RGB", (7, 3))]).shape) == (1, 3, 7, 3)


class FakeResponse:
    """Only what execute reads off a response. Stubbing the socket, not the
    logic: everything under test here is this pack's own code, and the one
    thing being replaced is the network."""

    def __init__(self, status_code=200, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


def run_execute(node_module, monkeypatch, response, env=None, **kwargs):
    """execute with the network replaced, returning what it sent."""
    sent = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, body=json, headers=headers, timeout=timeout)
        return response

    monkeypatch.setattr(node_module.requests, "post", fake_post)
    monkeypatch.setattr(node_module.os, "environ", env or {})
    node = node_module.SymbioticaGeminiImage()
    call = dict(prompt="a knight", model="gemini-3.1-flash-image", seed=0,
                aspect_ratio="auto", resolution="2K", api_key="a-google-key")
    call.update(kwargs)
    return sent, node.execute(**call)


GATEWAY_ENV = {
    "GEMINI_GATEWAY_URL": "https://gateway.example.invalid/v1/a/b/google-ai-studio",
    "GEMINI_GATEWAY_TOKEN": "cf-token-not-a-real-one",
    "ORDER_STUDIO": "example-studio",
}


def one_png(colour=(0, 255, 0)):
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), colour).save(buf, format="PNG")
    return {"candidates": [{"content": {"parts": [
        {"text": "here you go"},
        {"inlineData": {"mimeType": "image/png",
                        "data": base64.b64encode(buf.getvalue()).decode()}}]}}]}


def test_a_render_reaches_the_gateway_and_comes_back_as_a_batch(node_module,
                                                                monkeypatch):
    pytest.importorskip("torch")
    sent, (batch, text) = run_execute(
        node_module, monkeypatch, FakeResponse(payload=one_png()),
        env=dict(GATEWAY_ENV))
    assert sent["url"].startswith("https://gateway.example.invalid")
    assert sent["headers"]["cf-aig-byok-alias"] == "example-studio"
    assert tuple(batch.shape) == (1, 4, 4, 3)
    assert text == "here you go"


def test_the_request_is_given_a_connect_deadline_of_its_own(node_module,
                                                            monkeypatch):
    """A single number applies to the read only in effect — a black-holed host
    stalls the whole 300s before anyone learns the egress is broken, and a
    customer order waits all of it."""
    sent, _ = run_execute(node_module, monkeypatch,
                          FakeResponse(payload=one_png()), env=dict(GATEWAY_ENV))
    connect, read = sent["timeout"]
    assert connect <= 30
    assert read == 300


def test_a_failed_gateway_call_names_the_studio_and_hides_the_token(
        node_module, monkeypatch):
    """The wiring that hands the scrubber its secrets lives here and nowhere
    else. Proved at the pure layer, it is still only a property of a function
    this node is never shown to call correctly."""
    token = GATEWAY_ENV["GEMINI_GATEWAY_TOKEN"]
    with pytest.raises(RuntimeError) as caught:
        run_execute(node_module, monkeypatch,
                    FakeResponse(403, f'{{"error":"bad token {token}"}}'),
                    env=dict(GATEWAY_ENV))
    message = str(caught.value)
    assert "example-studio" in message
    assert token not in message
    assert "403" in message


def test_a_token_stored_with_a_trailing_newline_is_still_scrubbed(
        node_module, monkeypatch):
    """The wire carries the stripped token; scrubbing the raw env value finds
    nothing to replace. A trailing newline is the commonest artifact there is
    in a secret store, and the code strips precisely because it expects one."""
    env = dict(GATEWAY_ENV, GEMINI_GATEWAY_TOKEN="cf-token-not-a-real-one\n")
    with pytest.raises(RuntimeError) as caught:
        run_execute(node_module, monkeypatch,
                    FakeResponse(401, '{"error":"bad cf-token-not-a-real-one"}'),
                    env=env)
    assert "cf-token-not-a-real-one" not in str(caught.value)


def test_a_direct_call_does_not_leak_the_google_key_either(node_module,
                                                           monkeypatch):
    with pytest.raises(RuntimeError) as caught:
        run_execute(node_module, monkeypatch,
                    FakeResponse(400, '{"error":"bad key a-google-key"}'),
                    env={})
    assert "a-google-key" not in str(caught.value)


def test_a_failure_that_happens_to_be_valid_json_is_still_a_failure(
        node_module, monkeypatch):
    """A gateway rejecting a request answers with a JSON error body, and a
    rate limit answers 429 with one too. Without the status check those parse
    cleanly and are read as a render that produced no image, so the operator
    is told Gemini declined when the call never reached it."""
    with pytest.raises(RuntimeError, match="429"):
        run_execute(node_module, monkeypatch,
                    FakeResponse(429, '{"error":{"message":"rate limited"}}',
                                 payload={"error": {"message": "rate limited"}}),
                    env=dict(GATEWAY_ENV))


def test_a_two_hundred_that_is_not_json_is_reported_with_its_body(node_module,
                                                                  monkeypatch):
    """A gateway interstitial or a challenge page answers 200 with HTML. Bare,
    this is "Expecting value: line 1 column 1" and nothing about who answered."""
    with pytest.raises(RuntimeError) as caught:
        run_execute(node_module, monkeypatch,
                    FakeResponse(200, "<html>Attention Required</html>"),
                    env=dict(GATEWAY_ENV))
    message = str(caught.value)
    assert "Attention Required" in message
    assert "example-studio" in message


def test_a_call_that_never_reached_the_gateway_still_names_the_studio(
        node_module, monkeypatch):
    """A black-holed egress, a DNS failure or a TLS error raises before any
    response exists, so the failure formatter never ran and the exception
    named neither the studio nor the arm. In a sandbox log a bare
    ConnectTimeout is indistinguishable between "the gateway is down" and
    "this box has no egress"."""
    def refuse_to_connect(*a, **k):
        raise node_module.requests.exceptions.ConnectTimeout(
            "HTTPSConnectionPool(host='gateway.example.invalid'): timed out")

    monkeypatch.setattr(node_module.requests, "post", refuse_to_connect)
    monkeypatch.setattr(node_module.os, "environ", dict(GATEWAY_ENV))
    with pytest.raises(RuntimeError) as caught:
        node_module.SymbioticaGeminiImage().execute(
            prompt="a knight", model="gemini-3.1-flash-image", seed=0,
            aspect_ratio="auto", resolution="2K")
    message = str(caught.value)
    assert "example-studio" in message
    assert "ConnectTimeout" in message


def test_a_transport_failure_does_not_leak_the_token_either(node_module,
                                                            monkeypatch):
    """Some transport errors quote the request, and the scrubber has to cover
    this path for the same reason it covers the others."""
    token = GATEWAY_ENV["GEMINI_GATEWAY_TOKEN"]

    def leaky(*a, **k):
        raise node_module.requests.exceptions.ConnectionError(
            f"failed sending header Bearer {token}")

    monkeypatch.setattr(node_module.requests, "post", leaky)
    monkeypatch.setattr(node_module.os, "environ", dict(GATEWAY_ENV))
    with pytest.raises(RuntimeError) as caught:
        node_module.SymbioticaGeminiImage().execute(
            prompt="a knight", model="gemini-3.1-flash-image", seed=0,
            aspect_ratio="auto", resolution="2K")
    assert token not in str(caught.value)


def test_an_empty_prompt_is_refused_before_the_key_ladder_is_walked(
        node_module, monkeypatch):
    """Otherwise a headless run costs two round-trips: the operator is told to
    configure a key, configures one, re-runs, and only then learns the prompt
    was empty."""
    def exploding_post(*a, **k):
        raise AssertionError("a request was built for an empty prompt")

    monkeypatch.setattr(node_module.requests, "post", exploding_post)
    monkeypatch.setattr(node_module.os, "environ", {})
    with pytest.raises(ValueError, match="prompt"):
        node_module.SymbioticaGeminiImage().execute(
            prompt="   ", model="gemini-3.1-flash-image", seed=0,
            aspect_ratio="auto", resolution="2K", api_key="")


def test_the_prompt_is_sent_as_the_users_turn(node_module, monkeypatch):
    """Google reads `role` to tell the user's turn from the model's. Absent,
    the prompt can be taken for the assistant's own prior output."""
    sent, _ = run_execute(node_module, monkeypatch,
                          FakeResponse(payload=one_png()), env=dict(GATEWAY_ENV))
    assert sent["body"]["contents"][0]["role"] == "user"


def test_torch_is_reached_for_only_when_a_render_actually_runs(node_module):
    """The fixture importing this module at all is the live half of the claim —
    CI installs neither torch nor ComfyUI. This pins the reason it works, so
    that hoisting the import to the top of the file fails here rather than on
    the box where the pack silently loses the node."""
    source = open(os.path.join(PY_DIR, "gemini_image.py")).read()
    assert "import torch" not in source.split("def execute")[0]
