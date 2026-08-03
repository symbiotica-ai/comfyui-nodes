# ABOUTME: Tests the Claude node's registration, schema and one-call wiring —
# ABOUTME: it must load without ComfyUI present and send what the spec says.
import importlib.util
import json
import os
import sys
import types

import pytest

PY_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "py")


@pytest.fixture
def node_module(monkeypatch):
    """py/claude_text.py loaded as the package member it is at run time.

    The pack's loader imports every py/*.py inside a try/except that only
    prints the traceback, so a wrapper that will not import loses its node
    while the pack still loads clean. Loading it for real here is what makes
    that loud — and it must be loaded as a package member, because the module
    reaches its pure half through a relative import that a flat load cannot
    resolve."""
    pkg = types.ModuleType("symbiotica_claude_under_test")
    pkg.__path__ = [PY_DIR]
    monkeypatch.setitem(sys.modules, "symbiotica_claude_under_test", pkg)
    spec = importlib.util.spec_from_file_location(
        "symbiotica_claude_under_test.claude_text",
        os.path.join(PY_DIR, "claude_text.py"))
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    return mod


def test_the_node_is_registered_under_the_house_prefix(node_module):
    """`NS` marks vendored third-party code in this pack, so it would mislabel
    a node we wrote."""
    assert "SymbioticaClaude" in node_module.NODE_CLASS_MAPPINGS


def test_the_display_name_tells_it_apart_from_comfyuis_own_claude_node(node_module):
    """Stock ComfyUI ships "Anthropic Claude", which bills Comfy credits. Two
    entries a search away from each other need to say whose they are."""
    assert node_module.NODE_DISPLAY_NAME_MAPPINGS["SymbioticaClaude"] == (
        "Claude (Symbiotica)")


def test_the_node_sits_with_the_packs_other_text_work(node_module):
    assert node_module.SymbioticaClaude.CATEGORY == "symbiotica/text"


def test_it_returns_one_named_string(node_module):
    cls = node_module.SymbioticaClaude
    assert cls.RETURN_TYPES == ("STRING",)
    assert cls.RETURN_NAMES == ("text",)


def schema(node_module):
    spec = node_module.SymbioticaClaude.INPUT_TYPES()
    return spec["required"], spec["optional"]


def test_the_schema_offers_what_the_node_needs_and_what_it_allows(node_module):
    required, optional = schema(node_module)
    assert set(required) == {"prompt", "model", "max_tokens", "seed"}
    assert set(optional) == {"images", "system_prompt", "api_key"}


def test_the_token_budget_defaults_high_enough_for_a_thinking_model(node_module):
    """On Opus 5 and Sonnet 5 thinking is on by default and shares this budget
    with the answer, so a small default truncates real answers — which the
    parser then correctly raises on, having been given a fragment."""
    budget = schema(node_module)[0]["max_tokens"][1]
    assert budget["default"] == 32768
    assert budget["min"] >= 4096
    assert budget["max"] == 64000


def test_the_model_list_is_the_one_the_pure_module_offers(node_module):
    """Two lists would drift, and the drift shows up as a 404 from Anthropic
    naming a model the node itself put in the box."""
    assert schema(node_module)[0]["model"][0] is node_module.core.MODELS


def test_the_seed_exists_only_to_defeat_comfyuis_cache(node_module):
    """Anthropic takes no seed. Without this widget a re-queue serves the
    cached output and the node looks broken."""
    seed = schema(node_module)[0]["seed"][1]
    assert seed["control_after_generate"] is True
    assert "not sent" in seed["tooltip"].lower()


def test_no_sampling_widget_is_offered_at_all(node_module):
    """temperature, top_p and top_k are removed on Opus 5 / Fable 5 / Opus 4.8
    / 4.7 and 400 there. A widget for them would be a dial that breaks the
    default model."""
    required, optional = schema(node_module)
    for absent in ("temperature", "top_p", "top_k", "thinking", "stream"):
        assert absent not in required and absent not in optional


class FakeResponse:
    def __init__(self, status_code=200, text="", payload=None):
        self.status_code = status_code
        self.text = text if payload is None else json.dumps(payload)
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


ANSWERED = {"id": "msg_01", "model": "claude-opus-5", "content":
            [{"type": "text", "text": "a red door"}],
            "stop_reason": "end_turn", "stop_details": None,
            "usage": {"input_tokens": 9, "output_tokens": 4}}

GATEWAY_ENV = {
    "SYMBIOTICA_AIG_BASE": "https://gateway.example.invalid/v1/a/b",
    "SYMBIOTICA_AIG_TOKEN": "cf-token-not-a-real-one",
    "ORDER_STUDIO": "example-studio",
}


def run_execute(node_module, monkeypatch, response, env=None, **kwargs):
    """One execute() with the single requests.post seam stubbed.

    The house rule is no HTTP mocks, and this is the disclosed exception: the
    wiring between the pure halves lives only here, so without it a status
    check that never fires leaves the whole suite green."""
    sent = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, body=json, headers=headers, timeout=timeout)
        return response

    monkeypatch.setattr(node_module.requests, "post", fake_post)
    monkeypatch.setattr(node_module.os, "environ", env or {})
    node = node_module.SymbioticaClaude()
    call = dict(prompt="describe this", model="claude-opus-5", seed=0,
                max_tokens=32768, api_key="an-anthropic-key")
    call.update(kwargs)
    return sent, node.execute(**call)


def test_an_answer_reaches_the_gateway_and_comes_back_as_text(node_module,
                                                              monkeypatch):
    sent, (text,) = run_execute(node_module, monkeypatch,
                                FakeResponse(payload=ANSWERED),
                                env=dict(GATEWAY_ENV))
    assert sent["url"] == ("https://gateway.example.invalid/v1/a/b"
                           "/anthropic/v1/messages")
    assert sent["headers"]["cf-aig-byok-alias"] == "example-studio"
    assert text == "a red door"


def test_the_gateway_arm_sends_no_anthropic_key_of_its_own(node_module,
                                                           monkeypatch):
    """Stronger than hygiene: Cloudflare documents that an x-api-key sent
    alongside BYOK causes the request to fail, so a key riding along here
    breaks every studio render rather than merely leaking."""
    sent, _ = run_execute(node_module, monkeypatch,
                          FakeResponse(payload=ANSWERED), env=dict(GATEWAY_ENV))
    assert "x-api-key" not in sent["headers"]
    assert sent["headers"]["cf-aig-authorization"].startswith("Bearer ")


def test_both_arms_carry_the_api_version_the_caller_must_supply(node_module,
                                                                monkeypatch):
    """ComfyUI's own node omits this because the comfy.org proxy adds it; the
    gateway does not, so a missing header is a 400 on every call."""
    through_gateway, _ = run_execute(node_module, monkeypatch,
                                     FakeResponse(payload=ANSWERED),
                                     env=dict(GATEWAY_ENV))
    direct, _ = run_execute(node_module, monkeypatch,
                            FakeResponse(payload=ANSWERED), env={})
    assert through_gateway["headers"]["anthropic-version"] == "2023-06-01"
    assert direct["headers"]["anthropic-version"] == "2023-06-01"


def test_without_a_gateway_the_call_goes_to_anthropic_on_the_nodes_key(
        node_module, monkeypatch):
    sent, _ = run_execute(node_module, monkeypatch,
                          FakeResponse(payload=ANSWERED), env={})
    assert sent["url"] == "https://api.anthropic.com/v1/messages"
    assert sent["headers"]["x-api-key"] == "an-anthropic-key"
    assert "cf-aig-authorization" not in sent["headers"]


def test_the_request_is_given_a_connect_deadline_of_its_own(node_module,
                                                            monkeypatch):
    """A single number applies to the read only in effect — a black-holed host
    stalls the whole read budget before anyone learns the egress is broken."""
    sent, _ = run_execute(node_module, monkeypatch,
                          FakeResponse(payload=ANSWERED), env=dict(GATEWAY_ENV))
    connect, read = sent["timeout"]
    assert connect <= 30
    assert read >= 120


def test_a_failed_call_names_the_studio_and_hides_the_token(node_module,
                                                            monkeypatch):
    """The wiring that hands the scrubber its secrets lives here and nowhere
    else. Proved at the pure layer it is still only a property of a function
    this node is never shown to call correctly."""
    token = GATEWAY_ENV["SYMBIOTICA_AIG_TOKEN"]
    with pytest.raises(RuntimeError) as caught:
        run_execute(node_module, monkeypatch,
                    FakeResponse(403, f'{{"error":"bad token {token}"}}'),
                    env=dict(GATEWAY_ENV))
    message = str(caught.value)
    assert "example-studio" in message
    assert token not in message
    assert "403" in message
    assert "Claude" in message


def test_an_anthropic_key_echoed_back_on_the_direct_arm_is_scrubbed_too(
        node_module, monkeypatch):
    """The direct arm has no studio and no alias, so nothing else in the
    message would have told the scrubber this string was a credential."""
    with pytest.raises(RuntimeError) as caught:
        run_execute(node_module, monkeypatch,
                    FakeResponse(401, '{"error":"invalid x-api-key '
                                      'an-anthropic-key-long-enough"}'),
                    env={}, api_key="an-anthropic-key-long-enough")
    assert "an-anthropic-key-long-enough" not in str(caught.value)


def test_a_two_hundred_that_is_not_json_is_reported_with_its_body(node_module,
                                                                  monkeypatch):
    """A gateway interstitial or a challenge page answers 200 with HTML. Bare,
    this is "Expecting value: line 1 column 1" and nothing about which service
    produced it."""
    with pytest.raises(RuntimeError) as caught:
        run_execute(node_module, monkeypatch,
                    FakeResponse(200, "<html>Just a moment</html>"),
                    env=dict(GATEWAY_ENV))
    assert "Just a moment" in str(caught.value)


def test_a_call_that_never_reached_the_gateway_still_names_the_studio(
        node_module, monkeypatch):
    """A bare ConnectTimeout in a sandbox log cannot be told apart from "the
    gateway is down" and "this box has no egress", and names no studio."""
    def explode(*args, **kwargs):
        raise node_module.requests.ConnectTimeout("timed out")

    monkeypatch.setattr(node_module.requests, "post", explode)
    monkeypatch.setattr(node_module.os, "environ", dict(GATEWAY_ENV))
    with pytest.raises(RuntimeError) as caught:
        node_module.SymbioticaClaude().execute(
            prompt="describe this", model="claude-opus-5", seed=0,
            max_tokens=1024)
    assert "example-studio" in str(caught.value)
    assert "ConnectTimeout" in str(caught.value)


def test_the_prompt_is_checked_before_the_key_ladder_is_walked(node_module,
                                                               monkeypatch):
    """The ladder can reach a settings file on disk and the encoding runs once
    per reference. A blank prompt should cost neither."""
    def never(*args, **kwargs):
        raise AssertionError("a request was built for a blank prompt")

    monkeypatch.setattr(node_module.requests, "post", never)
    monkeypatch.setattr(node_module.os, "environ", {})
    with pytest.raises(ValueError, match="prompt is required"):
        node_module.SymbioticaClaude().execute(
            prompt="   ", model="claude-opus-5", seed=0, max_tokens=1024)


def test_a_non_200_carrying_valid_json_is_still_a_failure(node_module,
                                                          monkeypatch):
    """The one that catches a status check that never fires. Every other
    failure test here sends a body that is not JSON, so the parse path raises
    with the same status and the same studio and the suite stays green with
    the check deleted. Anthropic's own errors ARE valid JSON, and a 400 read
    as a reply is reported as "not a Messages shape" — sending the operator to
    check the gateway base when the model said what was wrong."""
    error = {"type": "error",
             "error": {"type": "invalid_request_error",
                       "message": "max_tokens: must be greater than 0"}}
    with pytest.raises(RuntimeError) as caught:
        run_execute(node_module, monkeypatch, FakeResponse(400, payload=error),
                    env=dict(GATEWAY_ENV))
    message = str(caught.value)
    assert "400" in message
    assert "must be greater than 0" in message
    assert "not a Messages shape" not in message
    assert "/v1/messages" not in message
