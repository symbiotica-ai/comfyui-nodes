# ABOUTME: Tests the pure Gemini image module — transport choice, request body,
# ABOUTME: response parsing — with no ComfyUI, no torch and no HTTP anywhere.
import base64
import io
import json

import pytest
from PIL import Image

from pipeline import gemini_image


GATEWAY = "https://gateway.example.invalid/v1/acct/gw/google-ai-studio"
TOKEN = "cf-token-not-a-real-one"
MODEL = "gemini-3.1-flash-image"
STUDIO = "example-studio"


def gateway_env(**overrides):
    env = {"GEMINI_GATEWAY_URL": GATEWAY, "GEMINI_GATEWAY_TOKEN": TOKEN,
           "ORDER_STUDIO": STUDIO}
    env.update(overrides)
    return {k: v for k, v in env.items() if v is not None}


def never_asked():
    raise AssertionError("the interactive key ladder was consulted")


def test_the_request_path_is_googles_own_generatecontent_path():
    """Written out rather than rebuilt from the module's own pieces: a join that
    loses the colon or drops the model still matches a recomputed expectation."""
    assert (gemini_image.generate_content_path("gemini-3.1-flash-image")
            == "/v1beta/models/gemini-3.1-flash-image:generateContent")


def test_a_configured_gateway_takes_the_call_without_asking_for_a_personal_key():
    transport = gemini_image.resolve_transport(
        gateway_env(GEMINI_API_KEY="a-personal-key-that-must-not-win"),
        MODEL, never_asked)
    assert transport.url == (
        "https://gateway.example.invalid/v1/acct/gw/google-ai-studio"
        "/v1beta/models/gemini-3.1-flash-image:generateContent")


def test_the_gateway_arm_proves_itself_to_cloudflare_and_sends_no_google_key():
    """With BYOK the gateway injects the Google key server-side. A provider key
    riding along would be a personal key spending on a studio call."""
    headers = gemini_image.resolve_transport(
        gateway_env(), MODEL, never_asked).headers
    assert headers["cf-aig-authorization"] == f"Bearer {TOKEN}"
    assert "x-goog-api-key" not in headers
    assert headers["Content-Type"] == "application/json"


def test_a_gateway_url_without_its_token_refuses_rather_than_billing_elsewhere():
    """Falling back to a personal key here is a billing bypass wearing an
    error's clothes: the call succeeds and the spend leaves the gateway."""
    env = gateway_env(GEMINI_GATEWAY_TOKEN=None,
                      GEMINI_API_KEY="a-personal-key-that-must-not-rescue-this")
    with pytest.raises(ValueError, match="GEMINI_GATEWAY_TOKEN"):
        gemini_image.resolve_transport(env, MODEL, never_asked)


def test_the_studios_own_key_is_named_as_the_one_that_pays():
    """Each studio's Google key is stored in the gateway under its slug. The
    alias is what selects it; without the header the shared default key pays
    for somebody else's render."""
    headers = gemini_image.resolve_transport(
        gateway_env(), MODEL, never_asked).headers
    assert headers["cf-aig-byok-alias"] == STUDIO


def test_the_call_is_tagged_with_the_studio_that_analytics_can_group_by():
    """The alias decides who is billed and is invisible to analytics — no
    AiGateway dataset carries a dimension for it. Only custom metadata is
    groupable, so the tag is what makes the spend attributable at all."""
    headers = gemini_image.resolve_transport(
        gateway_env(), MODEL, never_asked).headers
    # Parsed, not substring-matched: a malformed body still contains the slug.
    tag = json.loads(headers["cf-aig-metadata"])
    assert tag["studio"] == STUDIO


def test_the_tag_carries_the_studio_and_the_surface_and_nothing_else():
    """Exact equality rather than a cap: the design builds two entries, so
    "at most five" passes against every implementation anyone would write."""
    tag = json.loads(gemini_image.resolve_transport(
        gateway_env(), MODEL, never_asked).headers["cf-aig-metadata"])
    assert set(tag) == {"studio", "surface"}
    assert tag["surface"] == "order"


def test_the_transport_reports_which_studio_it_resolved_to():
    gateway = gemini_image.resolve_transport(gateway_env(), MODEL, never_asked)
    assert gateway.studio == STUDIO
    direct = gemini_image.resolve_transport({}, MODEL, lambda: "google-key")
    assert direct.studio is None


def test_a_gateway_render_with_no_studio_fails_instead_of_charging_the_default():
    """Falling back to the default alias would bill a shared key while the
    metadata tag claimed a studio — the two sources would disagree, and only
    reconciling the Google bill against gateway analytics would reveal it."""
    with pytest.raises(ValueError, match="ORDER_STUDIO"):
        gemini_image.resolve_transport(
            gateway_env(ORDER_STUDIO=None), MODEL, never_asked)
    with pytest.raises(ValueError, match="ORDER_STUDIO"):
        gemini_image.resolve_transport(
            gateway_env(ORDER_STUDIO="   "), MODEL, never_asked)


def test_a_studio_slug_that_cannot_be_a_header_is_refused_by_name():
    """The slug goes into a header value verbatim. A stray newline in the
    sandbox env would otherwise surface as requests' own InvalidHeader, which
    names neither ORDER_STUDIO nor the value it choked on."""
    for bad in ("evil\r\nX-Injected: yes", "two\nlines", "tab\there"):
        with pytest.raises(ValueError, match="ORDER_STUDIO"):
            gemini_image.resolve_transport(
                gateway_env(ORDER_STUDIO=bad), MODEL, never_asked)


def test_an_ordinary_slug_is_not_caught_by_that_check():
    """Studio slugs are lowercase words with hyphens; the guard must not
    reject the shape every real studio uses."""
    for good in ("example-studio", "studio2", "a-b-c-1"):
        assert gemini_image.resolve_transport(
            gateway_env(ORDER_STUDIO=good), MODEL, never_asked).studio == good


def test_the_studio_is_never_quietly_replaced_by_the_default_alias():
    """The one substitution that must never happen silently, asserted against
    the value rather than only against the raise."""
    try:
        gemini_image.resolve_transport(
            gateway_env(ORDER_STUDIO=None), MODEL, never_asked)
    except ValueError as exc:
        assert "default" not in str(exc).split("ORDER_STUDIO")[0].lower()
    else:
        pytest.fail("a gateway render without a studio was allowed to proceed")


def test_the_direct_arm_carries_no_studio_headers_at_all():
    """Google has no idea what a studio is; the headers mean something only to
    Cloudflare, and ORDER_STUDIO being set does not make this a studio call."""
    headers = gemini_image.resolve_transport(
        {"ORDER_STUDIO": STUDIO}, MODEL, lambda: "google-key").headers
    assert "cf-aig-byok-alias" not in headers
    assert "cf-aig-metadata" not in headers


def test_with_no_gateway_the_call_goes_straight_to_google_on_a_resolved_key():
    asked = []

    def ladder():
        asked.append(1)
        return "google-key"

    transport = gemini_image.resolve_transport({}, MODEL, ladder)
    assert transport.url == ("https://generativelanguage.googleapis.com"
                            "/v1beta/models/gemini-3.1-flash-image:generateContent")
    assert transport.headers["x-goog-api-key"] == "google-key"
    assert "cf-aig-authorization" not in transport.headers
    # Once, not per header: the ladder can reach a Settings file on disk.
    assert asked == [1]


def test_a_gateway_url_written_with_a_trailing_slash_still_joins_cleanly():
    """The base is hand-entered into a Modal secret, where a trailing slash is
    the most ordinary typo there is — and `//v1beta` is a 404 whose message
    says nothing about a slash."""
    transport = gemini_image.resolve_transport(
        gateway_env(GEMINI_GATEWAY_URL=GATEWAY + "/"), MODEL, never_asked)
    assert transport.url == (
        "https://gateway.example.invalid/v1/acct/gw/google-ai-studio"
        "/v1beta/models/gemini-3.1-flash-image:generateContent")


def test_a_blank_gateway_url_is_no_gateway_at_all():
    """An env var set to "" is how a secret that failed to populate arrives.
    Treating it as configured raises about a missing token and never explains
    that the URL is the empty one."""
    transport = gemini_image.resolve_transport(
        {"GEMINI_GATEWAY_URL": "  "}, MODEL, lambda: "google-key")
    assert transport.url.startswith("https://generativelanguage.googleapis.com")


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


def test_the_body_carries_nothing_this_node_deliberately_does_not_send():
    """The seed exists to defeat ComfyUI's output cache, not to reach Google;
    thinking, temperature and topP are v1 scope cuts. Each would change what
    comes back if it leaked in."""
    sent = body()
    assert "thinkingConfig" not in sent["generationConfig"]
    assert "temperature" not in sent["generationConfig"]
    assert "topP" not in sent["generationConfig"]
    assert "seed" not in sent and "seed" not in sent["generationConfig"]


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
    images, text = gemini_image.parse_response(
        reply({"text": "here you go"}, returned_image(GREEN_PIXEL)))
    assert len(images) == 1
    assert images[0].convert("RGB").getpixel((0, 0)) == GREEN_PIXEL
    assert text == "here you go"


def test_several_text_parts_are_joined_into_one_account():
    _, text = gemini_image.parse_response(
        reply({"text": "first"}, {"text": "second"},
              returned_image(GREEN_PIXEL)))
    assert text == "first\nsecond"


def test_a_thinking_sketch_never_ships_as_the_render():
    """Thinking-capable models emit interim images flagged `thought`. Dropping
    the thought_image OUTPUT does not drop this filter: without it the sketch
    is simply the first image in the list, and the render is whatever the
    caller takes first."""
    images, _ = gemini_image.parse_response(
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


def test_a_prohibited_image_is_reported_as_that_and_not_as_an_empty_render():
    with pytest.raises(ValueError, match="IMAGE_PROHIBITED_CONTENT"):
        gemini_image.parse_response(
            reply(returned_image(GREEN_PIXEL),
                  finish_reason="IMAGE_PROHIBITED_CONTENT"))


def test_a_refusal_for_any_reason_says_which_reason():
    """Gemini stops for SAFETY, RECITATION and others, not only for prohibited
    imagery. Reporting only the one reason we special-cased means the model
    said exactly why and the operator reads generic advice instead — in a
    sandbox that sentence is the whole incident report."""
    for reason in ("SAFETY", "RECITATION", "MAX_TOKENS"):
        with pytest.raises(ValueError, match=reason):
            gemini_image.parse_response(
                reply(finish_reason=reason))


def test_a_finished_candidate_is_not_reported_as_a_refusal():
    """STOP is how a normal completion ends. Naming it in an error would put a
    refusal reason on every empty response that was never refused."""
    with pytest.raises(ValueError) as caught:
        gemini_image.parse_response(reply({"text": "no picture"},
                                          finish_reason="STOP"))
    assert "STOP" not in str(caught.value)


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


def test_a_failed_call_reports_its_status_and_what_the_far_end_said():
    message = gemini_image.http_error(400, '{"error":"model not found"}')
    assert "400" in message
    assert "model not found" in message


def test_a_long_failure_body_is_cut_rather_than_pasted_whole():
    message = gemini_image.http_error(500, "x" * 5000)
    assert len(message) < 700


def test_a_credential_the_far_end_echoed_back_never_reaches_the_message():
    """Gateways do echo the presented authorization on a 401. The token would
    then travel wherever this message travels: a ComfyUI toast, the server log,
    a screenshot in a bug report."""
    message = gemini_image.http_error(
        401, f'{{"error":"bad token Bearer {TOKEN}"}}', secrets=[TOKEN])
    assert TOKEN not in message
    assert "401" in message


def test_a_credential_straddling_the_cut_does_not_leak_its_first_half():
    """Truncating before scrubbing leaves whatever of the secret fell inside
    the window. The guarantee has to be unconditional or it is not one."""
    cut = gemini_image.MAX_ERROR_BODY_CHARS
    for overlap in range(1, len(TOKEN)):
        body = "x" * (cut - overlap) + TOKEN + "y" * 20
        message = gemini_image.http_error(401, body, secrets=[TOKEN])
        assert TOKEN[:overlap] not in message, (
            f"{overlap} leading characters of the credential survived")


def test_redaction_of_nothing_does_not_redact_everything():
    """An unset credential is the empty string, and replacing that would put a
    marker between every character of the body."""
    message = gemini_image.http_error(429, "slow down", secrets=["", None])
    assert "slow down" in message


def test_any_gateway_failure_names_the_studio_and_the_key_it_asked_for():
    """Unconditional rather than recognised from a response signature. The
    gateway's answer to an alias with no stored key is undocumented, so a node
    that pattern-matched it would stay green here and fail to name the studio
    in the one place it matters — a headless log nobody is watching."""
    message = gemini_image.http_error(403, '{"error":"forbidden"}',
                                      studio=STUDIO, alias=STUDIO)
    assert STUDIO in message
    assert "403" in message


def test_the_alias_is_reported_even_when_it_is_not_the_studios_own_name():
    """Reporting the studio alone would leave a mismatch between the two
    invisible, and a mismatch is exactly the bug this header can have."""
    message = gemini_image.http_error(401, "nope", studio="studio-a",
                                      alias="studio-b")
    assert "studio-a" in message and "studio-b" in message


def test_a_direct_arm_failure_does_not_invent_a_studio():
    message = gemini_image.http_error(400, "bad request")
    assert "studio" not in message.lower()


def test_a_missing_alias_is_left_out_rather_than_printed_as_none():
    """"key alias None" reads as an alias literally named None, which is a
    different and much more alarming bug than the one that happened."""
    message = gemini_image.http_error(500, "boom", studio="a-studio")
    assert "None" not in message
    assert "a-studio" in message
