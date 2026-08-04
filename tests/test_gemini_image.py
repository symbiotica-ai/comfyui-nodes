# ABOUTME: Tests the pure Gemini image module — transport choice, request body,
# ABOUTME: response parsing — with no ComfyUI, no torch and no HTTP anywhere.
import base64
import io
import json

import pytest
from PIL import Image

from pipeline import gemini_image


MODEL = "gemini-3.1-flash-image"


def test_the_request_path_is_googles_own_generatecontent_path():
    """Written out rather than rebuilt from the module's own pieces: a join that
    loses the colon or drops the model still matches a recomputed expectation."""
    assert (gemini_image.generate_content_path("gemini-3.1-flash-image")
            == "/v1beta/models/gemini-3.1-flash-image:generateContent")



def body(prompt="a knight", inline_images=(), aspect_ratio="auto",
         resolution="2K", system_prompt=""):
    return gemini_image.request_body(prompt, list(inline_images), aspect_ratio,
                                     resolution, system_prompt)


def test_the_prompt_leads_and_the_references_follow_it_in_order():
    parts = body(inline_images=[{"inlineData": {"data": "one"}},
                                {"inlineData": {"data": "two"}}]
                 )["contents"][0]["parts"]
    assert parts[0] == {"text": "a knight"}
    assert [p["inlineData"]["data"] for p in parts[1:]] == ["one", "two"]


def test_both_modalities_are_asked_for():
    """Image-only would discard the text channel, which is the only account of
    what went wrong in a sandbox nobody is watching."""
    assert (body()["generationConfig"]["responseModalities"]
            == ["TEXT", "IMAGE"])


def test_the_output_size_is_always_stated():
    assert body(resolution="4K")["generationConfig"]["imageConfig"] == {
        "imageSize": "4K"}


def test_a_chosen_aspect_ratio_is_sent_and_auto_is_not():
    """'auto' is Google's absence of the field, not a value it understands."""
    assert body(aspect_ratio="3:4")["generationConfig"]["imageConfig"][
        "aspectRatio"] == "3:4"
    assert "aspectRatio" not in body(aspect_ratio="auto")[
        "generationConfig"]["imageConfig"]


def test_a_system_prompt_is_sent_without_a_role_and_an_empty_one_not_at_all():
    """Google's systemInstruction carries no role; the stock node passes None,
    which serializes to absent."""
    sent = body(system_prompt="always draw")["systemInstruction"]
    assert sent == {"parts": [{"text": "always draw"}]}
    assert "systemInstruction" not in body(system_prompt="")
    assert "systemInstruction" not in body(system_prompt="   ")


def test_the_seed_never_reaches_google():
    """It exists to defeat ComfyUI's output cache, not to reach the model.
    Leaked into the body it would change what comes back, which is the one
    thing a cache-buster must not do."""
    sent = body()
    assert "seed" not in sent and "seed" not in sent["generationConfig"]


def test_the_generation_controls_are_sent_with_the_defaults_core_uses():
    """These were cut from v1 because a flat model combo could not vary them
    per model — the omission was the constraint, not a preference. Pinned to
    core's own defaults so the same prompt on either node draws the same."""
    config = body()["generationConfig"]
    assert config["thinkingConfig"] == {"thinkingLevel": "MINIMAL"}
    assert config["temperature"] == 1.0
    assert config["topP"] == 0.95


def test_a_prompt_of_whitespace_is_refused_before_anything_is_sent():
    with pytest.raises(ValueError, match="prompt"):
        body(prompt="   ")


def swatch(colour=(10, 20, 30), size=(4, 4)):
    return Image.new("RGB", size, colour)


def test_a_reference_image_arrives_as_a_png_the_far_end_can_decode():
    """Decoded rather than compared against the encoder's own output: a part
    that carries the base64 of something that is not a PNG round-trips against
    itself perfectly and fails at Google."""
    part, = gemini_image.image_parts([swatch()])
    assert part["inlineData"]["mimeType"] == "image/png"
    raw = base64.b64decode(part["inlineData"]["data"])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert Image.open(io.BytesIO(raw)).size == (4, 4)


def test_fourteen_references_are_allowed_and_fifteen_are_refused():
    assert len(gemini_image.image_parts([swatch()] * 14)) == 14
    with pytest.raises(ValueError, match="14"):
        gemini_image.image_parts([swatch()] * 15)


def test_no_references_is_no_parts_rather_than_an_error():
    """A prompt on its own is a legitimate generation; only editing needs refs."""
    assert gemini_image.image_parts([]) == []


RED_PIXEL = (255, 0, 0)
GREEN_PIXEL = (0, 255, 0)


def returned_image(colour, thought=False):
    buf = io.BytesIO()
    swatch(colour).save(buf, format="PNG")
    part = {"inlineData": {"mimeType": "image/png",
                           "data": base64.b64encode(buf.getvalue()).decode()}}
    if thought:
        part["thought"] = True
    return part


def reply(*parts, finish_reason=None, **top_level):
    candidate = {"content": {"parts": list(parts)}}
    if finish_reason:
        candidate["finishReason"] = finish_reason
    return {"candidates": [candidate], **top_level}


def test_the_image_and_the_models_words_both_come_back():
    images, text, _thoughts = gemini_image.parse_response(
        reply({"text": "here you go"}, returned_image(GREEN_PIXEL)))
    assert len(images) == 1
    assert images[0].convert("RGB").getpixel((0, 0)) == GREEN_PIXEL
    assert text == "here you go"


def test_several_text_parts_are_joined_into_one_account():
    _, text, _thoughts = gemini_image.parse_response(
        reply({"text": "first"}, {"text": "second"},
              returned_image(GREEN_PIXEL)))
    assert text == "first\nsecond"


def test_the_render_comes_back_as_the_jpeg_the_api_actually_sends():
    """The API answers image/jpeg, not the PNG we send it. Accepting only PNG
    would reject every real render."""
    buf = io.BytesIO()
    swatch(GREEN_PIXEL).save(buf, format="JPEG")
    images, _, _thoughts = gemini_image.parse_response(reply(
        {"inlineData": {"mimeType": "image/jpeg",
                        "data": base64.b64encode(buf.getvalue()).decode()}}))
    assert len(images) == 1
    assert images[0].convert("RGB").getpixel((0, 0))[1] > 200


def test_a_thought_signature_on_the_real_render_does_not_get_it_filtered():
    """The genuine image part carries `thoughtSignature` and no `thought` at
    all. A filter asking "does this part have anything thought-ish on it"
    instead of "is thought true" would throw away the render itself and
    report that Gemini produced nothing."""
    part = returned_image(GREEN_PIXEL)
    part["thoughtSignature"] = "an-opaque-token-from-the-model"
    images, _, _thoughts = gemini_image.parse_response(reply(part))
    assert len(images) == 1
    assert images[0].convert("RGB").getpixel((0, 0)) == GREEN_PIXEL


def test_a_thinking_sketch_never_ships_as_the_render():
    """Thinking-capable models emit interim images flagged `thought`. Dropping
    the thought_image OUTPUT does not drop this filter: without it the sketch
    is simply the first image in the list, and the render is whatever the
    caller takes first."""
    images, _, _thoughts = gemini_image.parse_response(
        reply(returned_image(RED_PIXEL, thought=True),
              returned_image(GREEN_PIXEL)))
    assert len(images) == 1
    assert images[0].convert("RGB").getpixel((0, 0)) == GREEN_PIXEL


def test_a_thinking_sketch_alone_counts_as_no_image_at_all():
    with pytest.raises(ValueError, match="did not generate an image"):
        gemini_image.parse_response(reply(returned_image(RED_PIXEL,
                                                         thought=True)))


def test_a_blocked_prompt_says_what_blocked_it():
    with pytest.raises(ValueError, match="SAFETY.*graphic violence"):
        gemini_image.parse_response({
            "candidates": [],
            "promptFeedback": {"blockReason": "SAFETY",
                               "blockReasonMessage": "graphic violence"}})


def test_a_block_with_no_explanation_still_names_the_reason():
    with pytest.raises(ValueError, match="OTHER"):
        gemini_image.parse_response(
            {"promptFeedback": {"blockReason": "OTHER"}})


def test_an_empty_response_with_no_reason_given_says_so():
    with pytest.raises(ValueError, match="no candidates"):
        gemini_image.parse_response({"candidates": []})


def test_a_genuinely_empty_reply_is_not_blamed_on_the_endpoint():
    """A reply carrying `candidates` IS the generateContent shape, so telling
    the operator to check the URL both contradicts itself and sends them to
    inspect something that is correct."""
    with pytest.raises(ValueError) as caught:
        gemini_image.parse_response({"candidates": []})
    assert "endpoint" not in str(caught.value).lower()

    # Any of the shape's own keys is enough to prove the endpoint answered.
    for shape in ({"usageMetadata": {}}, {"modelVersion": "x"},
                  {"promptFeedback": {}}):
        with pytest.raises(ValueError) as caught:
            gemini_image.parse_response(shape)
        assert "endpoint" not in str(caught.value).lower()


def test_a_finish_reason_that_is_not_a_string_does_not_crash_the_report():
    """The last response value in the loop that could still raise from inside
    the diagnostic, taking the explanation down with the reason."""
    with pytest.raises(ValueError) as caught:
        gemini_image.parse_response({"candidates": [
            {"content": {}, "finishReason": 3, "finishMessage": "explained"}]})
    assert "explained" in str(caught.value)



def test_a_prohibited_image_is_reported_as_that_and_not_as_an_empty_render():
    with pytest.raises(ValueError, match="IMAGE_PROHIBITED_CONTENT"):
        gemini_image.parse_response(
            reply(returned_image(GREEN_PIXEL),
                  finish_reason="IMAGE_PROHIBITED_CONTENT"))


# What a refused generation actually looks like, captured against the real
# gateway. Note `content` is {} with no `parts` key at all, there is no
# promptFeedback, and the entire explanation lives in `finishMessage`.
REFUSED_REPLY = {
    "candidates": [{
        "content": {},
        "finishReason": "IMAGE_OTHER",
        "index": 0,
        "finishMessage": (
            "Unable to show the generated image. The model could not generate "
            "the image based on the prompt provided. You will not be charged "
            "for this request. Try rephrasing the prompt."),
    }],
    "modelVersion": "gemini-3.1-flash-image",
}


def test_a_real_refusal_hands_back_googles_own_explanation():
    """The diagnostic is in finishMessage, and nothing else in the reply says
    anything: no parts, no promptFeedback, no text. Substituting our own
    sentence discards the only account of the failure that exists."""
    with pytest.raises(ValueError) as caught:
        gemini_image.parse_response(REFUSED_REPLY)
    said = str(caught.value)
    assert "IMAGE_OTHER" in said
    assert "could not generate the image based on the prompt" in said


def test_a_refusal_carrying_no_parts_key_at_all_does_not_crash():
    """`content` is `{}` on this path — not an empty parts array, absent."""
    with pytest.raises(ValueError, match="IMAGE_OTHER"):
        gemini_image.parse_response(REFUSED_REPLY)


def test_our_own_advice_does_not_displace_googles():
    """Ours is generic by construction. Theirs names the model and the
    request, and today happens to agree with ours by coincidence."""
    said = ""
    try:
        gemini_image.parse_response(REFUSED_REPLY)
    except ValueError as exc:
        said = str(exc)
    assert said.count("rephras") == 1


def test_an_explanation_alone_is_enough_and_our_advice_is_not_added_to_it():
    """A candidate can explain itself without naming a finishReason. Ours is
    generic by construction; appending it to Google's specific sentence adds
    nothing and reads as two separate diagnoses."""
    with pytest.raises(ValueError) as caught:
        gemini_image.parse_response({"candidates": [
            {"content": {}, "finishMessage": "the prompt asked for a real person"}]})
    said = str(caught.value)
    assert "real person" in said
    assert "rephras" not in said.lower()


def test_one_explanation_shared_by_several_candidates_is_said_once():
    """Every candidate of a refused generation carries the same sentence.
    Repeating it per candidate turns one reason into a wall of duplicates."""
    with pytest.raises(ValueError) as caught:
        gemini_image.parse_response({"candidates": [
            {"content": {}, "finishReason": "IMAGE_OTHER",
             "finishMessage": "could not generate the image"},
            {"content": {}, "finishReason": "IMAGE_OTHER",
             "finishMessage": "could not generate the image"}]})
    assert str(caught.value).count("could not generate the image") == 1


def test_a_finish_message_that_is_not_a_sentence_does_not_crash_the_report():
    """Only the string form has been observed. A shape change upstream turning
    it into a number or an object would otherwise raise AttributeError from
    inside a diagnostic, losing the reason as well as the explanation."""
    for odd in (123, {"detail": "x"}, ["x"], True):
        with pytest.raises(ValueError, match="IMAGE_OTHER"):
            gemini_image.parse_response({"candidates": [
                {"content": {}, "finishReason": "IMAGE_OTHER",
                 "finishMessage": odd}]})


def test_a_candidate_that_is_not_an_object_is_reported_not_crashed_on():
    """Same guard the payload itself already has, one level down: a reply
    whose candidates are strings is a wrong-endpoint symptom, and
    "'str' object has no attribute 'get'" names neither Gemini nor the URL."""
    with pytest.raises(ValueError, match="candidate"):
        gemini_image.parse_response({"candidates": ["not an object"]})


def test_a_refusal_for_any_reason_says_which_reason():
    """Gemini stops for SAFETY, RECITATION and others, not only for prohibited
    imagery. Reporting only the one reason we special-cased means the model
    said exactly why and the operator reads generic advice instead — in a
    sandbox that sentence is the whole incident report."""
    for reason in ("SAFETY", "RECITATION", "MAX_TOKENS"):
        with pytest.raises(ValueError, match=reason):
            gemini_image.parse_response(
                reply(finish_reason=reason))


def test_every_distinct_reason_is_reported_not_just_the_first():
    """A response can carry several candidates stopped for different reasons.
    Naming only one hands the operator a partial account of a failure they
    cannot reproduce."""
    payload = {"candidates": [
        {"finishReason": "SAFETY", "content": {"parts": []}},
        {"finishReason": "RECITATION", "content": {"parts": []}},
    ]}
    with pytest.raises(ValueError) as caught:
        gemini_image.parse_response(payload)
    assert "SAFETY" in str(caught.value)
    assert "RECITATION" in str(caught.value)


def test_one_reason_shared_by_several_candidates_is_said_once():
    payload = {"candidates": [
        {"finishReason": "SAFETY", "content": {"parts": []}},
        {"finishReason": "SAFETY", "content": {"parts": []}},
    ]}
    with pytest.raises(ValueError) as caught:
        gemini_image.parse_response(payload)
    assert str(caught.value).count("SAFETY") == 1


def test_generic_advice_is_not_offered_when_the_real_reason_is_known():
    """Appending it regardless would undo the point of naming the reason: the
    operator reads "rephrase your prompt" under a SAFETY stop and tries the
    one thing that cannot help."""
    with pytest.raises(ValueError) as caught:
        gemini_image.parse_response(reply(finish_reason="SAFETY"))
    assert "rephras" not in str(caught.value).lower()

    with pytest.raises(ValueError) as caught:
        gemini_image.parse_response(reply({"text": "I will not draw that."}))
    assert "rephras" not in str(caught.value).lower()


def test_a_finished_candidate_is_not_reported_as_a_refusal():
    """STOP is how a normal completion ends. Naming it in an error would put a
    refusal reason on every empty response that was never refused."""
    with pytest.raises(ValueError) as caught:
        gemini_image.parse_response(reply({"text": "no picture"},
                                          finish_reason="STOP"))
    assert "STOP" not in str(caught.value)


def test_a_blocked_candidate_still_yields_its_own_explanation():
    """The block reason names the rule; the model's sentence names what broke
    it. Skipping the candidate to avoid its images threw away its words too,
    which is the half an operator can actually act on."""
    with pytest.raises(ValueError) as caught:
        gemini_image.parse_response(reply(
            {"text": "I cannot depict this trademarked character."},
            returned_image(GREEN_PIXEL),
            finish_reason="IMAGE_PROHIBITED_CONTENT"))
    assert "IMAGE_PROHIBITED_CONTENT" in str(caught.value)
    assert "trademarked character" in str(caught.value)


def test_a_blocked_candidates_images_are_still_never_returned():
    """Its words are wanted; its pixels are the thing that was prohibited."""
    with pytest.raises(ValueError):
        gemini_image.parse_response(reply(
            returned_image(GREEN_PIXEL),
            finish_reason="IMAGE_PROHIBITED_CONTENT"))


def test_a_reason_and_the_models_words_are_both_reported():
    """Each is half the account. A version that dropped the text whenever a
    reason existed would read as complete and would not be."""
    with pytest.raises(ValueError) as caught:
        gemini_image.parse_response(reply(
            {"text": "that character is trademarked"},
            finish_reason="SAFETY"))
    assert "SAFETY" in str(caught.value)
    assert "trademarked" in str(caught.value)


def test_a_candidate_that_carries_no_content_at_all_is_survivable():
    """This is the shape the wire actually uses for a safety stop: a
    finishReason and no content key whatsoever."""
    with pytest.raises(ValueError, match="IMAGE_SAFETY"):
        gemini_image.parse_response({"candidates": [
            {"finishReason": "IMAGE_SAFETY"}]})


def test_a_reply_that_is_not_a_generatecontent_shape_says_so():
    """A wrong endpoint answers 200 with a different envelope. "no candidates"
    reads as the model refusing, so an operator retries the prompt instead of
    looking at the URL."""
    with pytest.raises(ValueError, match="success.*result|result.*success"):
        gemini_image.parse_response({"success": True, "result": {}})


def test_a_reply_that_is_not_even_an_object_says_that_rather_than_crashing():
    with pytest.raises(ValueError, match="list"):
        gemini_image.parse_response([{"candidates": []}])


def test_a_refusal_carries_the_models_own_explanation_of_it():
    """Gemini declines in prose. That sentence is the whole diagnosis, and in a
    headless sandbox it is the only one anybody ever sees."""
    with pytest.raises(ValueError, match="cannot depict a real person"):
        gemini_image.parse_response(
            reply({"text": "I cannot depict a real person."}))


def test_a_silent_refusal_still_suggests_what_to_do():
    with pytest.raises(ValueError, match="rephras"):
        gemini_image.parse_response(reply({"text": "   "}))


def test_an_image_offered_only_as_a_link_is_not_mistaken_for_a_render():
    """AI Studio returns images inline. A fileData URI is a Vertex/file-API
    shape this node does not fetch, and treating it as a hit would hand the
    graph a part with no pixels in it."""
    with pytest.raises(ValueError, match="did not generate an image"):
        gemini_image.parse_response(
            reply({"fileData": {"mimeType": "image/png",
                                "fileUri": "https://example.invalid/x.png"}}))


def test_an_undecodable_image_is_reported_as_one_rather_than_as_binascii():
    """A sandbox log holding only "Invalid base64-encoded string" names
    neither Gemini nor the render. The operator cannot tell a mangled response
    from a bug in this pack."""
    for broken in ("!!!not base64!!!", base64.b64encode(b"hello").decode()):
        with pytest.raises(ValueError, match="could not be decoded"):
            gemini_image.parse_response(
                reply({"inlineData": {"mimeType": "image/png",
                                      "data": broken}}))


def test_an_image_part_with_no_data_at_all_is_reported_the_same_way():
    """`KeyError: 'data'` is what a shape change upstream looks like, and it
    reads as this pack having a bug rather than the response having one."""
    with pytest.raises(ValueError, match="could not be decoded"):
        gemini_image.parse_response(
            reply({"inlineData": {"mimeType": "image/png"}}))


def test_a_non_image_attachment_is_not_decoded_as_one():
    with pytest.raises(ValueError, match="did not generate an image"):
        gemini_image.parse_response(
            reply({"inlineData": {"mimeType": "application/json",
                                  "data": "e30="}}))




def test_this_nodes_call_carries_googles_slug_and_googles_path():
    """The slug moved out of the operator-supplied URL and into this module,
    where the transport tests cannot see it — they run against their own
    provider literal. Written out in full rather than rebuilt from the module's
    own pieces: a join that drops the slug still matches a recomputed value."""
    transport = gemini_image.resolve_transport(
        {"SYMBIOTICA_AIG_BASE": "https://gateway.example.invalid/v1/acct/gw",
         "SYMBIOTICA_AIG_TOKEN": "cf-token-not-a-real-one",
         "ORDER_STUDIO": "example-studio"},
        "gemini-3.1-flash-image", never_consulted)
    assert transport.url == (
        "https://gateway.example.invalid/v1/acct/gw/google-ai-studio"
        "/v1beta/models/gemini-3.1-flash-image:generateContent")


def test_without_a_gateway_this_node_still_calls_google_on_googles_header():
    """The direct base and the header name that presents the key both live in
    this module now. Sending Google's key under Anthropic's header name would
    be invisible to the shared scrubber, which knows both."""
    transport = gemini_image.resolve_transport(
        {}, "gemini-3.1-flash-image", lambda: "a-google-key")
    assert transport.url == ("https://generativelanguage.googleapis.com"
                             "/v1beta/models/gemini-3.1-flash-image"
                             ":generateContent")
    assert transport.headers["x-goog-api-key"] == "a-google-key"
    assert "x-api-key" not in transport.headers


def test_a_google_key_that_cannot_be_a_header_is_refused_as_googles():
    """The label a rejection uses is this module's, and it is what tells the
    reader which of two providers' keys to go and look at."""
    with pytest.raises(ValueError, match="Gemini"):
        gemini_image.resolve_transport(
            {}, "gemini-3.1-flash-image", lambda: "key\nwith-newline")


def never_consulted():
    raise AssertionError("the interactive key ladder was consulted")
