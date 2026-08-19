# ABOUTME: Tests the Claude node's registration, schema and one-call wiring —
# ABOUTME: it must load without ComfyUI present and send what the spec says.
import importlib.util
import json
import os
import sys
import types

import pytest

import comfy_api_stub

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
    comfy_pkg, comfy_latest = comfy_api_stub.build_modules()
    monkeypatch.setitem(sys.modules, "comfy_api", comfy_pkg)
    monkeypatch.setitem(sys.modules, "comfy_api.latest", comfy_latest)
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
    schema = node_module.SymbioticaClaude.define_schema()
    assert schema.category == "symbiotica/text"
    assert schema.node_id == "SymbioticaClaude"


def test_it_returns_one_named_string(node_module):
    schema = node_module.SymbioticaClaude.define_schema()
    assert [o.display_name for o in schema.outputs] == ["text"]


def inputs_of(node_module, label="Opus 5"):
    """The schema's top-level inputs keyed by name, plus the inputs the given
    model's option carries, under `model.<name>` — the dotted names ComfyUI
    shows on the canvas."""
    schema = node_module.SymbioticaClaude.define_schema()
    found = {i.id: i for i in schema.inputs}
    option = next(o for o in found["model"].options if o.label == label)
    for inner in option.inputs:
        found[f"model.{inner.id}"] = inner
    return found


def test_the_schema_offers_what_the_node_needs_and_what_it_allows(node_module):
    """max_tokens moved inside the combo, which is where core keeps it — so
    what ComfyUI passes changed shape, not just contents."""
    assert set(inputs_of(node_module)) == {
        "prompt", "model", "seed", "system_prompt", "api_key",
        "model.max_tokens", "model.reasoning_effort", "model.images"}


def test_the_token_budget_defaults_high_enough_for_a_thinking_model(node_module):
    """On Opus 5 and Sonnet 5 thinking is on by default and shares this budget
    with the answer, so a small default truncates real answers — which the
    parser then correctly raises on, having been given a fragment."""
    budget = inputs_of(node_module)["model.max_tokens"]
    assert budget.default == 32768
    assert budget.min >= 4096
    assert budget.max == 64000


def test_the_model_list_is_the_one_the_pure_module_offers(node_module):
    """Two lists would drift, and the drift shows up as a 404 from Anthropic
    naming a model the node itself put in the box."""
    schema = node_module.SymbioticaClaude.define_schema()
    model_input = next(i for i in schema.inputs if i.id == "model")
    assert [o.label for o in model_input.options] == list(
        node_module.core.MODEL_LABELS)
    assert (set(node_module.core.MODEL_LABELS.values())
            == set(node_module.core.MODELS))


def test_the_seed_exists_only_to_defeat_comfyuis_cache(node_module):
    """Anthropic takes no seed. Without this widget a re-queue serves the
    cached output and the node looks broken."""
    seed = inputs_of(node_module)["seed"]
    assert seed.control_after_generate is True
    assert "not sent" in seed.tooltip.lower()


def test_a_model_that_rejects_a_setting_is_not_offered_it(node_module):
    """temperature is removed on Opus 5 / Fable 5 / Opus 4.8 / Sonnet 5 and
    400s there, and Haiku has no reasoning at all. Offering the widget anyway
    would be a dial that breaks the model — which is why these are absent
    rather than present and ignored."""
    for absent in ("temperature", "top_p", "top_k", "thinking", "stream"):
        assert f"model.{absent}" not in inputs_of(node_module, "Opus 5")
    assert "model.reasoning_effort" not in inputs_of(node_module, "Haiku 4.5")
    # And where the model does take it, it is there.
    assert "model.temperature" in inputs_of(node_module, "Sonnet 4.5")


def test_the_always_thinking_models_are_not_offered_an_off_switch(node_module):
    """Opus 5 reasons whatever the widget says, so an `off` in its list would
    be a setting that silently does nothing."""
    effort = inputs_of(node_module, "Opus 5")["model.reasoning_effort"]
    assert "off" not in effort.options
    assert inputs_of(node_module, "Sonnet 4.5")[
        "model.reasoning_effort"].options[0] == "off"


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
    monkeypatch.setattr(os, "environ", env or {})
    call = dict(prompt="describe this", seed=0, api_key="an-anthropic-key")
    # The per-model inputs arrive inside the combo's value rather than as
    # keywords of their own, so a caller still names them flatly and they are
    # folded in here — otherwise every test would have to know the shape.
    chosen = chosen_model()
    for key in list(kwargs):
        if key in chosen or key in ("temperature", "reasoning_effort"):
            chosen[key] = kwargs.pop(key)
    call["model"] = chosen
    call.update(kwargs)
    return sent, node_module.SymbioticaClaude.execute(**call)


def chosen_model(**overrides):
    """The value ComfyUI hands the `model` input: the label plus the inputs
    that option carries. Opus 5 always reasons and takes no temperature, so
    its option has neither `off` nor a temperature widget."""
    value = dict(model="Opus 5", max_tokens=32768, reasoning_effort="high",
                 images={})
    value.update(overrides)
    return value


def test_an_answer_reaches_the_gateway_and_comes_back_as_text(node_module,
                                                              monkeypatch):
    sent, output = run_execute(node_module, monkeypatch,
                                FakeResponse(payload=ANSWERED),
                                env=dict(GATEWAY_ENV))
    assert sent["url"] == ("https://gateway.example.invalid/v1/a/b"
                           "/anthropic/v1/messages")
    assert sent["headers"]["cf-aig-byok-alias"] == "example-studio"
    text, = output.args
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
    stalls the whole read budget before anyone learns the egress is broken.

    The read floor is not a taste. Nothing arrives until the answer is complete
    on a non-streamed call, so this bounds the whole generation, and this pack's
    other Claude client gives the same provider 500s at a smaller token budget.
    Anything under that would cut off a generation that succeeded and was
    billed, and report it to a headless operator as a transport failure."""
    sent, _ = run_execute(node_module, monkeypatch,
                          FakeResponse(payload=ANSWERED), env=dict(GATEWAY_ENV))
    connect, read = sent["timeout"]
    assert connect <= 30
    assert read >= 500


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
    monkeypatch.setattr(os, "environ", dict(GATEWAY_ENV))
    with pytest.raises(RuntimeError) as caught:
        node_module.SymbioticaClaude.execute(
            prompt="describe this", seed=0,
            model=chosen_model(max_tokens=4096))
    assert "example-studio" in str(caught.value)
    assert "ConnectTimeout" in str(caught.value)


def test_the_prompt_is_checked_before_the_key_ladder_is_walked(node_module,
                                                               monkeypatch):
    """The ladder can reach a settings file on disk and the encoding runs once
    per reference. A blank prompt should cost neither."""
    def never(*args, **kwargs):
        raise AssertionError("a request was built for a blank prompt")

    monkeypatch.setattr(node_module.requests, "post", never)
    monkeypatch.setattr(os, "environ", {})
    with pytest.raises(ValueError, match="prompt is required"):
        node_module.SymbioticaClaude.execute(
            prompt="   ", seed=0, model=chosen_model(max_tokens=4096))


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


def test_every_widget_reaches_the_request_body(node_module, monkeypatch):
    """The one seam nothing else covers. request_body and image_blocks are
    proved at the pure layer, but the CALL that maps seven widgets onto them
    lives only here — a node hard-coding the prompt, ignoring the model box and
    sending max_tokens=1 would ship on a green suite without this."""
    sent, _ = run_execute(node_module, monkeypatch,
                          FakeResponse(payload=ANSWERED), env=dict(GATEWAY_ENV),
                          prompt="what colour is the door",
                          model="claude-haiku-4-5-20251001", max_tokens=8192,
                          system_prompt="answer in one word")
    body = sent["body"]
    assert body["model"] == "claude-haiku-4-5-20251001"
    assert body["max_tokens"] == 8192
    assert body["system"] == "answer in one word"
    assert body["messages"][0]["content"][-1] == {
        "type": "text", "text": "what colour is the door"}


def test_an_empty_system_prompt_is_left_out_of_the_body_entirely(node_module,
                                                                 monkeypatch):
    """The widget defaults to empty, so this is the ordinary call. Anthropic
    has no system role and an empty `system` key is a 400."""
    sent, _ = run_execute(node_module, monkeypatch,
                          FakeResponse(payload=ANSWERED), env=dict(GATEWAY_ENV))
    assert "system" not in sent["body"]


def test_a_reference_batch_reaches_the_wire_as_labelled_png_blocks(node_module,
                                                                   monkeypatch):
    """Proves to_pil -> image_blocks -> labelled end to end. ComfyUI hands this
    node a float batch in [0,1]; every step between that and a base64 PNG lives
    only in execute()."""
    import base64
    import numpy as np
    batch = np.zeros((2, 8, 8, 3), dtype=np.float32)
    batch[1] = 1.0
    sent, _ = run_execute(node_module, monkeypatch,
                          FakeResponse(payload=ANSWERED), env=dict(GATEWAY_ENV),
                          images=batch)
    blocks = sent["body"]["messages"][0]["content"]
    assert [b.get("text") for b in blocks if b["type"] == "text"] == [
        "Image 1:", "Image 2:", "describe this"]
    images = [b for b in blocks if b["type"] == "image"]
    assert len(images) == 2
    assert base64.b64decode(images[0]["source"]["data"])[:8] == b"\x89PNG\r\n\x1a\n"


def test_a_float_batch_above_one_is_clipped_rather_than_wrapping_round(
        node_module, monkeypatch):
    """A node upstream can hand on values above 1.0. Cast without clipping,
    260.0 becomes 4 and a white reference arrives almost black."""
    import base64
    import io
    import numpy as np
    from PIL import Image as PILImage
    sent, _ = run_execute(node_module, monkeypatch,
                          FakeResponse(payload=ANSWERED), env=dict(GATEWAY_ENV),
                          images=np.full((1, 8, 8, 3), 1.02, dtype=np.float32))
    block = [b for b in sent["body"]["messages"][0]["content"]
             if b["type"] == "image"][0]
    sent_image = PILImage.open(io.BytesIO(
        base64.b64decode(block["source"]["data"])))
    assert sent_image.getpixel((0, 0)) == (255, 255, 255)


def test_reference_slots_reach_the_wire_the_way_the_canvas_filled_them(
        node_module, monkeypatch):
    """Autogrow hands `images` over as a DICT keyed by slot name, not a batch.

    Iterating that dict yields its KEYS — strings — so a node that treats it as
    a batch sends no images at all, or dies converting 'image_1' to pixels. The
    schema declares Autogrow, so this is the only shape the canvas ever
    produces; a test passing a raw batch exercises a path ComfyUI never takes.

    Slots are also numbered, and sorted as text `image_10` falls between
    `image_1` and `image_2` — so the order is asserted, not just the count."""
    import numpy as np

    def slot(value):
        return np.full((1, 2, 2, 3), value, dtype=np.float32)

    sent, _ = run_execute(
        node_module, monkeypatch, FakeResponse(payload=ANSWERED),
        images={"image_1": slot(0.0), "image_2": slot(0.5),
                "image_10": slot(1.0)})
    blocks = [b for b in sent["body"]["messages"][0]["content"]
              if b.get("type") == "image"]
    assert len(blocks) == 3
    # The pixel values, not the count: sorted as text `image_10` lands between
    # `image_1` and `image_2`, which sends three blocks in the wrong order and
    # passes any assertion that only counts them.
    import base64 as b64
    import io as _io

    from PIL import Image as _Image
    greys = [_Image.open(_io.BytesIO(b64.b64decode(b["source"]["data"])))
             .convert("RGB").getpixel((0, 0))[0] for b in blocks]
    assert greys == [0, 128, 255], f"slots arrived out of order: {greys}"


def test_which_inputs_a_stored_payload_must_carry_is_pinned(node_module):
    """Adding a REQUIRED input drops every workflow saved before it existed.

    ComfyUI validates a prompt against the CURRENT schema and answers an absent
    required input with "Required input is missing"; the declared default never
    applies. So a required input is not a default with a nudge, it is a demand
    on every payload already stored elsewhere — including the pinned order
    templates the platform dispatches, which are authored once and replayed.

    Found live on 2026.8.10 on the picker, when `get_new` shipped without
    `optional=True` and dropped all three pickers out of the pinned flow4
    template. This list is the same rule applied here: it may shrink freely,
    and it may only GROW with a deliberate edit that accepts breaking stored
    payloads. A new input belongs outside it.
    """
    schema = node_module.SymbioticaClaude.define_schema()
    inputs = {i.id: i for i in schema.inputs}
    # The per-model inputs ride inside the combo, and reach the payload under
    # the same dotted names the canvas shows, so they are pinned alongside.
    for option in inputs["model"].options:
        for inner in option.inputs:
            inputs.setdefault(f"model.{inner.id}", inner)
    required = sorted(k for k, i in inputs.items()
                      if not getattr(i, "optional", False))
    # `model.temperature` and `model.reasoning_effort` appear only on the models
    # that accept them, so this is the union across options, not one model's set.
    # That is why the node reads them with `.get(default)` while the Gemini image
    # node brackets its own: here an absent one means the chosen model has no
    # such setting, not that the payload is malformed. `nodes_anthropic.py` makes
    # the same split, with the same defaults.
    assert required == [
        "model", "model.images", "model.max_tokens", "model.reasoning_effort",
        "model.temperature", "prompt", "seed",
    ]


@pytest.fixture
def desktop_settings(monkeypatch, tmp_path):
    """A real comfy.settings.json, read the way the running server reads it.

    Written to disk rather than stubbed at `get_comfy_setting`, because the
    whole point of this route is that the file is the only channel a desktop
    box has — and a stub would pass just as well against a resolver that never
    learned to open it."""
    user_dir = tmp_path / "user"
    (user_dir / "default").mkdir(parents=True)
    fp = types.ModuleType("folder_paths")
    fp.get_user_directory = lambda: str(user_dir)
    monkeypatch.setitem(sys.modules, "folder_paths", fp)

    def write(**values):
        (user_dir / "default" / "comfy.settings.json").write_text(
            json.dumps({f"Symbiotica.{k}": v for k, v in values.items()}))
    return write


def test_a_desktop_box_reaches_the_gateway_from_its_settings(node_module,
                                                             monkeypatch,
                                                             desktop_settings):
    """Comfy Desktop launches its own Python, so there is no environment to
    put the gateway in and every call here would otherwise go straight to
    Anthropic on a personal key."""
    desktop_settings(SYMBIOTICA_AIG_BASE="https://gateway.example.invalid/v1/a/b",
                     SYMBIOTICA_AIG_TOKEN="cf-token-not-a-real-one",
                     ORDER_STUDIO="comfy-desktop")
    sent, _ = run_execute(node_module, monkeypatch,
                          FakeResponse(payload=ANSWERED), env={})
    assert sent["url"] == ("https://gateway.example.invalid/v1/a/b"
                           "/anthropic/v1/messages")
    assert sent["headers"]["cf-aig-byok-alias"] == "comfy-desktop"


def test_a_settings_gateway_still_outranks_a_personal_key(node_module,
                                                          monkeypatch,
                                                          desktop_settings):
    """The pack's standing rule, on the one arm that could quietly break it:
    a key typed on the node is right there in the call, and spending it while
    a gateway sits configured is the failure nobody detects afterwards."""
    desktop_settings(SYMBIOTICA_AIG_BASE="https://gateway.example.invalid/v1/a/b",
                     SYMBIOTICA_AIG_TOKEN="cf-token-not-a-real-one",
                     ORDER_STUDIO="comfy-desktop",
                     ANTHROPIC_API_KEY="a-personal-anthropic-key")
    sent, _ = run_execute(node_module, monkeypatch,
                          FakeResponse(payload=ANSWERED), env={})
    assert "x-api-key" not in sent["headers"]
    assert "a-personal-anthropic-key" not in json.dumps(sent["headers"])


def test_a_desktop_render_is_not_tagged_as_an_order(node_module, monkeypatch,
                                                    desktop_settings):
    """Gateway analytics groups by this tag. Counted as orders, canvas renders
    inflate order spend under a label that reads correctly."""
    desktop_settings(SYMBIOTICA_AIG_BASE="https://gateway.example.invalid/v1/a/b",
                     SYMBIOTICA_AIG_TOKEN="cf-token-not-a-real-one",
                     ORDER_STUDIO="comfy-desktop")
    sent, _ = run_execute(node_module, monkeypatch,
                          FakeResponse(payload=ANSWERED), env={})
    assert json.loads(sent["headers"]["cf-aig-metadata"])["surface"] == "canvas"
