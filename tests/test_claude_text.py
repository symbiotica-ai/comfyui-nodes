# ABOUTME: Tests the pure Claude text module — what it sends, how big it lets
# ABOUTME: that get, and what it makes of the reply — with no HTTP anywhere.
import base64
import io

import numpy as np
import pytest
from PIL import Image

from pipeline import claude_text


def test_a_prompt_of_whitespace_is_refused_before_anything_is_sent():
    """Checked before the key ladder and the encoding, so a headless operator
    learns about the prompt in one round-trip rather than two."""
    for blank in ("", "   ", "\n\t"):
        with pytest.raises(ValueError, match="prompt is required"):
            claude_text.require_prompt(blank)


def test_a_real_prompt_passes_through_unchanged():
    assert claude_text.require_prompt("  describe this  ") == "  describe this  "


def test_the_retiring_model_is_not_offered():
    """claude-opus-4-1-20250805 retires 2026-08-05. Offering it in a combo box
    means a saved workflow that stops working two days later."""
    assert "claude-opus-4-1-20250805" not in claude_text.MODELS
    assert claude_text.MODELS[0] == "claude-opus-5"


def test_the_high_resolution_models_get_the_larger_edge():
    """Anthropic accepts a 2576px long edge only on this tier; everything else
    caps at 1568 and downscales server-side, so sending 2576 there ships bytes
    that are thrown away — and, worse, spends the log budget on them."""
    for model in ("claude-opus-5", "claude-sonnet-5", "claude-fable-5",
                  "claude-opus-4-8", "claude-opus-4-7"):
        assert claude_text.max_image_edge(model) == 2576, model


def test_every_other_model_gets_the_smaller_one():
    for model in ("claude-sonnet-4-6", "claude-opus-4-6",
                  "claude-opus-4-5-20251101", "claude-haiku-4-5-20251001",
                  "claude-sonnet-4-5-20250929"):
        assert claude_text.max_image_edge(model) == 1568, model


def test_a_model_nobody_has_heard_of_gets_the_safe_edge():
    """The lookup defaults down, not up: an unrecognised id sent 2576px would
    be a request the far end rejects or silently shrinks, and either way the
    bytes were already spent."""
    assert claude_text.max_image_edge("claude-something-未来") == 1568


def test_every_offered_model_has_an_edge_that_is_one_of_the_two_tiers():
    """A model added to the combo box without a tier entry would silently take
    the default — correct here, but the assertion is what makes that a choice
    rather than an accident."""
    assert {claude_text.max_image_edge(m) for m in claude_text.MODELS} == {2576, 1568}


def flat(width, height):
    """Compresses to almost nothing — same pixel count, tiny encoded size."""
    return Image.new("RGB", (width, height), (7, 11, 13))


def noise(width, height, seed=0):
    """Compresses to almost nothing off — same pixel count, huge encoded size.
    The pair is what separates a byte check from a dimension check."""
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, (height, width, 3),
                                        dtype=np.uint8))


def decoded(block):
    return base64.b64decode(block["source"]["data"])


def test_a_reference_image_arrives_as_a_png_the_far_end_can_decode():
    block, = claude_text.image_blocks([flat(64, 64)], "claude-opus-5")
    assert block["type"] == "image"
    assert block["source"]["type"] == "base64"
    assert block["source"]["media_type"] == "image/png"
    # Round-tripped rather than trusted: a block whose data is not a PNG is a
    # 400 from Anthropic that names none of this.
    assert decoded(block)[:8] == b"\x89PNG\r\n\x1a\n"


def test_an_oversized_render_is_brought_down_to_the_models_own_ceiling():
    """A 4K render base64s to tens of megabytes and earns a 413 — and, under
    that, spends the whole log budget for fidelity nobody asked for."""
    block, = claude_text.image_blocks([flat(4000, 2000)], "claude-opus-5")
    sent = Image.open(io.BytesIO(decoded(block)))
    assert max(sent.size) == 2576
    # Aspect preserved: a squashed reference is a different picture.
    assert sent.size == (2576, 1288)


def test_a_standard_tier_model_is_sent_the_smaller_edge():
    block, = claude_text.image_blocks([flat(4000, 2000)],
                                      "claude-haiku-4-5-20251001")
    assert max(Image.open(io.BytesIO(decoded(block))).size) == 1568


def test_a_small_reference_is_never_stretched_to_fill_the_ceiling():
    """Upscaling invents detail the model then reads as real, and costs image
    tokens by the ⌈w/28⌉×⌈h/28⌉ tile count for the privilege."""
    block, = claude_text.image_blocks([flat(512, 384)], "claude-opus-5")
    assert Image.open(io.BytesIO(decoded(block))).size == (512, 384)


def test_twenty_references_are_allowed_and_twenty_one_are_refused():
    """20 is where Anthropic's own behaviour changes — past it every image is
    downscaled to a stricter ceiling — so it is a real boundary, not a taste."""
    assert len(claude_text.image_blocks([flat(8, 8)] * 20, "claude-opus-5")) == 20
    with pytest.raises(ValueError, match="20"):
        claude_text.image_blocks([flat(8, 8)] * 21, "claude-opus-5")


def test_no_references_is_no_blocks_rather_than_an_error():
    assert claude_text.image_blocks([], "claude-opus-5") == []


def test_a_payload_over_the_log_ceiling_is_refused_by_size():
    """Cloudflare does not store a log over 10MB, and AI Gateway analytics
    reads the log. A request past the ceiling is spend that reaches no
    cockpit row — the alias says who pays and the tag says who to bill, and
    a dropped log records neither."""
    with pytest.raises(ValueError) as caught:
        claude_text.image_blocks([noise(2576, 2576, seed=i) for i in range(3)],
                                 "claude-opus-5")
    assert "8000000" in str(caught.value).replace(",", "").replace("_", "")


def test_the_refusal_names_the_size_that_did_not_fit():
    """A ceiling without the measurement leaves the operator to guess how far
    over they are, and therefore how many references to cut."""
    with pytest.raises(ValueError) as caught:
        claude_text.image_blocks([noise(2576, 2576, seed=i) for i in range(3)],
                                 "claude-opus-5")
    # The real figure, not a rounded one: it is what says "drop one" or "drop
    # five". Matched loosely because the exact byte count is PNG's business.
    assert any(len(word.strip(",.")) >= 7 and word.strip(",.").isdigit()
               for word in str(caught.value).split())


def test_an_over_budget_batch_is_refused_rather_than_quietly_shortened():
    """An answer drawn from three of eight references is a wrong answer that
    looks right — the same class of silent failure as returning a placeholder
    string instead of raising."""
    images = [noise(2576, 2576, seed=i) for i in range(3)]
    with pytest.raises(ValueError):
        claude_text.image_blocks(images, "claude-opus-5")


def test_the_budget_measures_encoded_bytes_and_not_pixel_dimensions(monkeypatch):
    """Two images of identical dimensions, one flat and one noise. A check
    written against width×height cannot tell them apart; the encoded sizes
    differ by orders of magnitude."""
    monkeypatch.setattr(claude_text, "MAX_REQUEST_BYTES", 200_000)
    assert len(claude_text.image_blocks([flat(1024, 1024)], "claude-opus-5")) == 1
    with pytest.raises(ValueError):
        claude_text.image_blocks([noise(1024, 1024)], "claude-opus-5")


def body(prompt="describe this", images=(), model="claude-opus-5",
         max_tokens=32768, system_prompt=""):
    return claude_text.request_body(prompt, list(images), model, max_tokens,
                                    system_prompt)


def content(**kwargs):
    return body(**kwargs)["messages"][0]["content"]


def test_the_prompt_is_the_users_turn_and_the_model_is_named():
    sent = body(prompt="what is this", model="claude-sonnet-5")
    assert sent["model"] == "claude-sonnet-5"
    assert [m["role"] for m in sent["messages"]] == ["user"]
    assert content(prompt="what is this") == [
        {"type": "text", "text": "what is this"}]


def test_the_token_budget_is_always_stated():
    """Anthropic requires max_tokens; a body without it is a 400 that names
    nothing else that might be wrong."""
    assert body(max_tokens=1024)["max_tokens"] == 1024


def test_the_body_carries_nothing_this_node_deliberately_does_not_send():
    """temperature, top_p and top_k are removed on Opus 5 / Fable 5 / Opus 4.8
    / 4.7 and 400 there. No thinking key either: on Opus 5 thinking is on by
    default when the parameter is omitted, and sending type "disabled" is
    itself a 400 on Fable 5."""
    sent = body(images=[{"type": "image"}], system_prompt="be brief")
    for absent in ("temperature", "top_p", "top_k", "thinking",
                   "output_config", "stream", "tools"):
        assert absent not in sent, absent


def test_a_system_prompt_is_sent_at_the_top_level_and_an_empty_one_not_at_all():
    """Anthropic takes `system` as its own key, not as a message with a role —
    a system-role message is a 400."""
    assert body(system_prompt="be brief")["system"] == "be brief"
    assert "system" not in body(system_prompt="")
    assert "system" not in body(system_prompt="   ")
    assert all(m["role"] != "system" for m in body(system_prompt="x")["messages"])


def test_the_references_lead_and_the_prompt_closes():
    """Anthropic's own guidance, and what call_claude_api in this repo already
    does — two Claude paths in one pack should send the same shape."""
    blocks = content(images=[{"type": "image", "source": {"data": "a"}},
                            {"type": "image", "source": {"data": "b"}}])
    assert blocks[-1] == {"type": "text", "text": "describe this"}
    images = [i for i, b in enumerate(blocks) if b["type"] == "image"]
    assert images and max(images) < len(blocks) - 1


def test_several_references_are_numbered_so_the_prompt_can_refer_to_them():
    blocks = content(images=[{"type": "image", "source": {"data": "a"}},
                            {"type": "image", "source": {"data": "b"}}])
    labels = [b["text"] for b in blocks if b["type"] == "text"]
    assert labels == ["Image 1:", "Image 2:", "describe this"]


def test_a_lone_reference_is_not_labelled():
    """A label on a single image is noise the model has to read past, and
    call_claude_api omits it for the same reason."""
    blocks = content(images=[{"type": "image", "source": {"data": "a"}}])
    assert [b["text"] for b in blocks if b["type"] == "text"] == ["describe this"]


def test_each_label_immediately_precedes_the_image_it_names():
    """"Image 2:" after both images names neither. The order is the whole
    content of the label."""
    blocks = content(images=[{"type": "image", "source": {"data": "a"}},
                            {"type": "image", "source": {"data": "b"}}])
    assert blocks[0] == {"type": "text", "text": "Image 1:"}
    assert blocks[1]["source"]["data"] == "a"
    assert blocks[2] == {"type": "text", "text": "Image 2:"}
    assert blocks[3]["source"]["data"] == "b"


def reply(*blocks, stop_reason="end_turn", **extra):
    payload = {"id": "msg_01", "model": "claude-opus-5", "type": "message",
               "role": "assistant", "content": list(blocks),
               "stop_reason": stop_reason, "stop_sequence": None,
               "stop_details": None, "usage": {"input_tokens": 9,
                                               "output_tokens": 4}}
    payload.update(extra)
    return payload


def said(text):
    return {"type": "text", "text": text}


def test_the_models_answer_comes_back():
    assert claude_text.parse_response(reply(said("a red door"))) == "a red door"


def test_several_text_blocks_are_joined_into_one_answer():
    answer = claude_text.parse_response(reply(said("a red door"), said(" ajar")))
    assert "a red door" in answer and "ajar" in answer


def test_a_thinking_block_is_never_mistaken_for_the_answer():
    """On Opus 5 and Sonnet 5 thinking is on by default when no parameter is
    sent, and its display defaults to omitted — so the block arrives with empty
    text. Collected, it would prepend nothing or leak reasoning into a caption."""
    payload = reply({"type": "thinking", "thinking": "", "signature": "sig"},
                    said("a red door"))
    assert claude_text.parse_response(payload) == "a red door"


def test_a_refusal_is_raised_before_the_content_is_even_read():
    """stop_reason "refusal" can arrive with content present. Reading content
    first would hand back whatever partial text came with the refusal as though
    it were an answer."""
    payload = reply(said("here is how to"), stop_reason="refusal",
                    stop_details={"type": "refusal", "category": "cyber",
                                  "explanation": "declined to continue"})
    with pytest.raises(ValueError) as caught:
        claude_text.parse_response(payload)
    assert "cyber" in str(caught.value)
    assert "declined to continue" in str(caught.value)


def test_a_refusal_with_no_details_at_all_still_raises_rather_than_crashing():
    """stop_details is populated only on a refusal and is null otherwise, so
    a reporter that reaches into it unguarded turns a refusal into a TypeError
    naming neither Claude nor the prompt."""
    with pytest.raises(ValueError, match="refus"):
        claude_text.parse_response(reply(said("x"), stop_reason="refusal",
                                         stop_details=None))
    with pytest.raises(ValueError, match="refus"):
        claude_text.parse_response(reply(said("x"), stop_reason="refusal"))


def test_a_truncated_answer_is_refused_rather_than_handed_over_half_finished():
    """max_tokens caps thinking and answer together on the models that think by
    default, so this is the ordinary way a real answer gets cut off. Returned
    silently it reaches a client as a half-sentence."""
    with pytest.raises(ValueError) as caught:
        claude_text.parse_response(reply(said("The three key points are: 1."),
                                         stop_reason="max_tokens"))
    assert "max_tokens" in str(caught.value)


def test_inputs_too_large_is_a_different_complaint_from_a_truncated_answer():
    """One is fixed by raising the widget, the other by sending less. Conflating
    them sends the operator to turn a dial that cannot help."""
    with pytest.raises(ValueError) as caught:
        claude_text.parse_response(reply(stop_reason="model_context_window_exceeded"))
    message = str(caught.value)
    assert "model_context_window_exceeded" in message
    with pytest.raises(ValueError) as truncated:
        claude_text.parse_response(reply(said("x"), stop_reason="max_tokens"))
    # Distinct advice, not merely a distinct code: one says raise the widget,
    # the other says raising it makes things worse.
    assert message != str(truncated.value)
    assert "Raise max_tokens" in str(truncated.value)


def test_an_answer_with_no_text_in_it_is_refused_and_says_why():
    """The stock node returns the literal string "Empty response from Claude
    model." here. A placeholder flowing into a downstream node is the silent
    failure this pack exists to avoid."""
    with pytest.raises(ValueError) as caught:
        claude_text.parse_response(reply(stop_reason="end_turn"))
    assert "end_turn" in str(caught.value)


def test_an_empty_answer_carries_whatever_explanation_came_with_it():
    payload = reply(stop_reason="end_turn",
                    stop_details={"explanation": "nothing to say"})
    with pytest.raises(ValueError, match="nothing to say"):
        claude_text.parse_response(payload)


def test_a_reply_from_the_wrong_endpoint_says_that_rather_than_blaming_claude():
    """A 200 carrying none of the Messages keys is a wrong URL or an
    interstitial. Reported as a refusal it sends someone to rewrite a prompt
    that was never the problem."""
    for wrong in ({"candidates": []}, {"detail": "Not Found"}, {}):
        with pytest.raises(ValueError, match="/v1/messages"):
            claude_text.parse_response(wrong)


def test_a_reply_that_is_not_even_an_object_says_so_rather_than_crashing():
    for wrong in ([], "OK", None, 7):
        with pytest.raises(ValueError):
            claude_text.parse_response(wrong)


def test_a_genuine_reply_that_happens_to_be_sparse_is_not_blamed_on_the_endpoint():
    """A Messages reply carrying only `content` and `stop_reason` is still a
    Messages reply. Treating key-absence as wrong-endpoint proof would report
    an empty answer as a bad URL."""
    with pytest.raises(ValueError) as caught:
        claude_text.parse_response({"content": [], "stop_reason": "end_turn"})
    assert "/v1/messages" not in str(caught.value)


def test_a_stop_reason_that_is_not_a_string_does_not_crash_the_report():
    with pytest.raises(ValueError):
        claude_text.parse_response(reply(stop_reason=7))


def test_a_content_block_that_is_not_an_object_is_survived():
    """Nothing promises every block is a dict, and a TypeError from inside the
    loop names neither Claude nor the reply."""
    payload = reply("not a block", said("a red door"))
    assert claude_text.parse_response(payload) == "a red door"
