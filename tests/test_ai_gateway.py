# ABOUTME: Tests the Cloudflare AI Gateway transport every provider node
# ABOUTME: shares — which arm is chosen, what it carries, and how it fails.
import json

import pytest

from pipeline import ai_gateway


# The base with no provider slug; the slug is passed separately and joined on.
BASE = "https://gateway.example.invalid/v1/acct/gw"
TOKEN = "cf-token-not-a-real-one"
STUDIO = "example-studio"
# Real values from the Gemini node, so the URL a test asserts is the URL that
# node has always sent. Written out rather than imported: a literal that moves
# with the code it checks stops being independent of it.
PROVIDER = "google-ai-studio"
PATH = "/v1beta/models/gemini-3.1-flash-image:generateContent"
DIRECT = ai_gateway.DirectArm(
    "https://generativelanguage.googleapis.com", "The provider key",
    lambda key: {"x-goog-api-key": key})


def gateway_env(**overrides):
    env = {"SYMBIOTICA_AIG_BASE": BASE, "SYMBIOTICA_AIG_TOKEN": TOKEN,
           "ORDER_STUDIO": STUDIO}
    env.update(overrides)
    return {k: v for k, v in env.items() if v is not None}


def never_asked():
    raise AssertionError("the interactive key ladder was consulted")


def resolve(environ, interactive_key=never_asked, extra_headers=None):
    return ai_gateway.resolve_transport(environ, PROVIDER, PATH,
                                        interactive_key, DIRECT, extra_headers)


def test_a_configured_gateway_takes_the_call_without_asking_for_a_personal_key():
    transport = resolve(
        gateway_env(PROVIDER_API_KEY="a-personal-key-that-must-not-win"))
    assert transport.url == (
        "https://gateway.example.invalid/v1/acct/gw/google-ai-studio"
        "/v1beta/models/gemini-3.1-flash-image:generateContent")


def test_the_gateway_arm_proves_itself_to_cloudflare_and_sends_no_google_key():
    """With BYOK the gateway injects the Google key server-side. A provider key
    riding along would be a personal key spending on a studio call."""
    headers = resolve(
        gateway_env()).headers
    assert headers["cf-aig-authorization"] == f"Bearer {TOKEN}"
    assert "x-goog-api-key" not in headers
    assert headers["Content-Type"] == "application/json"


def test_a_gateway_url_without_its_token_refuses_rather_than_billing_elsewhere():
    """Falling back to a personal key here is a billing bypass wearing an
    error's clothes: the call succeeds and the spend leaves the gateway."""
    env = gateway_env(SYMBIOTICA_AIG_TOKEN=None,
                      PROVIDER_API_KEY="a-personal-key-that-must-not-rescue-this")
    with pytest.raises(ValueError, match="SYMBIOTICA_AIG_TOKEN"):
        resolve(env)


def test_the_studios_own_key_is_named_as_the_one_that_pays():
    """Each studio's Google key is stored in the gateway under its slug. The
    alias is what selects it; without the header the shared default key pays
    for somebody else's render."""
    headers = resolve(
        gateway_env()).headers
    assert headers["cf-aig-byok-alias"] == STUDIO


def test_the_call_is_tagged_with_the_studio_that_analytics_can_group_by():
    """The alias decides who is billed and is invisible to analytics — no
    AiGateway dataset carries a dimension for it. Only custom metadata is
    groupable, so the tag is what makes the spend attributable at all."""
    headers = resolve(
        gateway_env()).headers
    # Parsed, not substring-matched: a malformed body still contains the slug.
    tag = json.loads(headers["cf-aig-metadata"])
    assert tag["studio"] == STUDIO


def test_the_tag_carries_the_studio_and_the_surface_and_nothing_else():
    """Exact equality rather than a cap: the design builds two entries, so
    "at most five" passes against every implementation anyone would write."""
    tag = json.loads(resolve(
        gateway_env()).headers["cf-aig-metadata"])
    assert set(tag) == {"studio", "surface"}
    assert tag["surface"] == "order"


def test_the_transport_reports_which_studio_it_resolved_to():
    gateway = resolve(gateway_env())
    assert gateway.studio == STUDIO
    direct = resolve({}, lambda: "google-key")
    assert direct.studio is None


def test_a_gateway_render_with_no_studio_fails_instead_of_charging_the_default():
    """Falling back to the default alias would bill a shared key while the
    metadata tag claimed a studio — the two sources would disagree, and only
    reconciling the Google bill against gateway analytics would reveal it."""
    with pytest.raises(ValueError, match="ORDER_STUDIO"):
        resolve(
            gateway_env(ORDER_STUDIO=None))
    with pytest.raises(ValueError, match="ORDER_STUDIO"):
        resolve(
            gateway_env(ORDER_STUDIO="   "))


def test_a_studio_slug_that_cannot_be_a_header_is_refused_by_name():
    """The slug goes into a header value verbatim. A stray newline in the
    sandbox env would otherwise surface as requests' own InvalidHeader, which
    names neither ORDER_STUDIO nor the value it choked on."""
    for bad in ("evil\r\nX-Injected: yes", "two\nlines", "tab\there"):
        with pytest.raises(ValueError, match="ORDER_STUDIO"):
            resolve(
                gateway_env(ORDER_STUDIO=bad))


def test_an_ordinary_slug_is_not_caught_by_that_check():
    """Studio slugs are lowercase words with hyphens; the guard must not
    reject the shape every real studio uses."""
    for good in ("example-studio", "studio2", "a-b-c-1"):
        assert resolve(
            gateway_env(ORDER_STUDIO=good)).studio == good


def test_the_studio_is_never_quietly_replaced_by_the_default_alias():
    """No transport comes back at all, so there is no header that could carry
    `default`. Asserted by catching anything that is not the raise: a version
    that returned a transport here would have to have chosen some alias, and
    the only one available is the shared key this must never reach."""
    with pytest.raises(ValueError) as caught:
        transport = resolve(
            gateway_env(ORDER_STUDIO=None))
        pytest.fail(f"a studio-less gateway render proceeded with alias "
                    f"{transport.headers.get('cf-aig-byok-alias')!r}")
    assert "default" not in str(caught.value).lower()


def test_the_direct_arm_carries_no_studio_headers_at_all():
    """Google has no idea what a studio is; those headers mean something only
    to Cloudflare and would be noise it might reject.

    Reached with no ORDER_STUDIO, because a studio set without a gateway URL
    is now refused as a broken sandbox — so this arm can only ever be a canvas
    box, which is the only place it was ever meant to run."""
    headers = resolve(
        {}, lambda: "google-key").headers
    assert "cf-aig-byok-alias" not in headers
    assert "cf-aig-metadata" not in headers
    assert "cf-aig-authorization" not in headers


def test_with_no_gateway_the_call_goes_straight_to_google_on_a_resolved_key():
    asked = []

    def ladder():
        asked.append(1)
        return "google-key"

    transport = resolve({}, ladder)
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
    transport = resolve(
        gateway_env(SYMBIOTICA_AIG_BASE=BASE + "/"))
    assert transport.url == (
        "https://gateway.example.invalid/v1/acct/gw/google-ai-studio"
        "/v1beta/models/gemini-3.1-flash-image:generateContent")


def test_a_sandbox_whose_gateway_url_failed_to_populate_refuses_to_render():
    """ORDER_STUDIO is set by the sandbox launcher, independently of the
    secret. Its presence without a gateway URL is unambiguous evidence of a
    broken sandbox — and the direct arm there would either fail complaining
    about a Settings UI that does not exist, or succeed on a stray personal
    key and take the spend out of the gateway silently."""
    broken = [{"ORDER_STUDIO": STUDIO},                      # var misspelt
              {"ORDER_STUDIO": STUDIO, "SYMBIOTICA_AIG_BASE": ""},
              {"ORDER_STUDIO": STUDIO, "SYMBIOTICA_AIG_BASE": "   "}]
    for env in broken:
        env["PROVIDER_API_KEY"] = "a-personal-key-that-must-not-quietly-pay"
        with pytest.raises(ValueError, match="SYMBIOTICA_AIG_BASE"):
            resolve(env, lambda: "personal")


def test_a_canvas_box_without_a_studio_still_reaches_google_directly():
    """Canvas boxes never set ORDER_STUDIO, so the guard above costs
    interactive users nothing."""
    assert resolve(
        {}, lambda: "k").url.startswith(
            "https://generativelanguage.googleapis.com")


def test_a_gateway_url_that_is_not_https_is_refused():
    """The token is a bearer credential for the studio's whole gateway spend.
    Over http it crosses the wire in the clear."""
    with pytest.raises(ValueError, match="https"):
        resolve(
            gateway_env(SYMBIOTICA_AIG_BASE="http://gateway.example.invalid/x"))


def test_a_token_that_cannot_be_a_header_is_refused_without_being_echoed():
    """An interior newline reaches requests, which raises InvalidHeader with
    the whole header value in its message — the credential, in the toast and
    the log, by a path that never touches the scrubber."""
    bad = "tok\nen-with-a-newline"
    with pytest.raises(ValueError) as caught:
        resolve(
            gateway_env(SYMBIOTICA_AIG_TOKEN=bad))
    assert "SYMBIOTICA_AIG_TOKEN" in str(caught.value)
    assert "en-with-a-newline" not in str(caught.value)


def test_a_google_key_that_cannot_be_a_header_is_refused_the_same_way():
    with pytest.raises(ValueError) as caught:
        resolve({}, lambda: "key\nwith-newline")
    assert "with-newline" not in str(caught.value)


def test_a_token_of_only_whitespace_is_no_token():
    with pytest.raises(ValueError, match="SYMBIOTICA_AIG_TOKEN"):
        resolve(
            gateway_env(SYMBIOTICA_AIG_TOKEN="   "))


def test_a_slug_carrying_an_invisible_control_character_is_refused():
    """\\x00 is not \\r, \\n or \\t, and a guard written against only those
    three would pass it into the header."""
    with pytest.raises(ValueError, match="ORDER_STUDIO"):
        resolve(
            gateway_env(ORDER_STUDIO="studio\x00null"))


def test_a_blank_gateway_url_is_no_gateway_at_all():
    """An env var set to "" is how a secret that failed to populate arrives.
    Treating it as configured raises about a missing token and never explains
    that the URL is the empty one."""
    transport = resolve(
        {"SYMBIOTICA_AIG_BASE": "  "}, lambda: "google-key")
    assert transport.url.startswith("https://generativelanguage.googleapis.com")

def test_a_studio_slug_that_cannot_cross_the_wire_is_refused():
    """isprintable() passes plenty of characters http.client cannot encode.
    A UnicodeEncodeError from inside the transport names neither the variable
    nor the value."""
    with pytest.raises(ValueError, match="ORDER_STUDIO"):
        resolve(
            gateway_env(ORDER_STUDIO="studio-中文"))

def test_a_failed_call_reports_its_status_and_what_the_far_end_said():
    message = ai_gateway.http_error(400, '{"error":"model not found"}')
    assert "400" in message
    assert "model not found" in message


def test_a_long_failure_body_is_cut_rather_than_pasted_whole():
    message = ai_gateway.http_error(500, "x" * 5000)
    assert len(message) < 700


def test_a_credential_the_far_end_echoed_back_never_reaches_the_message():
    """Gateways do echo the presented authorization on a 401. The token would
    then travel wherever this message travels: a ComfyUI toast, the server log,
    a screenshot in a bug report."""
    message = ai_gateway.http_error(
        401, f'{{"error":"bad token Bearer {TOKEN}"}}', secrets=[TOKEN])
    assert TOKEN not in message
    assert "401" in message


def test_a_credential_straddling_the_cut_does_not_leak_its_first_half():
    """Truncating before scrubbing leaves whatever of the secret fell inside
    the window. The guarantee has to be unconditional or it is not one."""
    cut = ai_gateway.MAX_ERROR_BODY_CHARS
    for overlap in range(1, len(TOKEN)):
        body = "x" * (cut - overlap) + TOKEN + "y" * 20
        message = ai_gateway.http_error(401, body, secrets=[TOKEN])
        assert TOKEN[:overlap] not in message, (
            f"{overlap} leading characters of the credential survived")


def test_a_value_too_short_to_be_a_credential_does_not_shred_the_message():
    """A truncated or misconfigured token of a character or two appears inside
    ordinary words, so scrubbing it replaces half the message and protects
    nothing — the value is not a usable credential either way. Observed as
    "Connec[redacted]Timeou[redacted]" from a token of "t"."""
    message = ai_gateway.http_error(
        500, "ConnectTimeout: HTTPSConnectionPool timed out", secrets=["t"])
    assert "ConnectTimeout" in message
    assert "[redacted]" not in message


def test_a_credential_of_real_length_is_still_scrubbed():
    long_enough = "abcdefghij" * 4
    message = ai_gateway.http_error(500, f"rejected {long_enough}",
                                      secrets=[long_enough])
    assert long_enough not in message
    assert "[redacted]" in message


def test_redaction_of_nothing_does_not_redact_everything():
    """An unset credential is the empty string, and replacing that would put a
    marker between every character of the body."""
    message = ai_gateway.http_error(429, "slow down", secrets=["", None])
    assert "slow down" in message


def test_any_gateway_failure_names_the_studio_and_the_key_it_asked_for():
    """Unconditional rather than recognised from a response signature. The
    gateway's answer to an alias with no stored key is undocumented, so a node
    that pattern-matched it would stay green here and fail to name the studio
    in the one place it matters — a headless log nobody is watching."""
    message = ai_gateway.http_error(403, '{"error":"forbidden"}',
                                      studio=STUDIO, alias=STUDIO)
    assert STUDIO in message
    assert "403" in message


def test_the_alias_is_reported_even_when_it_is_not_the_studios_own_name():
    """Reporting the studio alone would leave a mismatch between the two
    invisible, and a mismatch is exactly the bug this header can have."""
    message = ai_gateway.http_error(401, "nope", studio="studio-a",
                                      alias="studio-b")
    assert "studio-a" in message and "studio-b" in message


def test_a_direct_arm_failure_does_not_invent_a_studio():
    message = ai_gateway.http_error(400, "bad request")
    assert "studio" not in message.lower()


# The shape Cloudflare AI Gateway actually returns for an alias it holds no
# key for, captured against the real gateway rather than imagined. The slugs
# are substituted: the real body enumerates the live studio roster, and that
# does not belong in a committed fixture. Everything structural is verbatim.
UNKNOWN_ALIAS_BODY = (
    '{"success":false,"result":[],"messages":[],"error":[{"code":2040,'
    '"message":"Provider \'google-ai-studio\' has no BYOK credential named '
    '\'example-studio\'. Configured aliases: \'other-studio\'"}],'
    '"name":"AiGatewayError","httpCode":400,"internalCode":2040,'
    '"message":"Provider \'google-ai-studio\' has no BYOK credential named '
    '\'example-studio\'. Configured aliases: \'other-studio\'"}')

UNAUTHORIZED_BODY = (
    '{"success":false,"error":[{"code":2009,"message":"Unauthorized"}],'
    '"name":"AiGatewayError","httpCode":400,"internalCode":2009,'
    '"message":"Unauthorized"}')


def test_an_unprovisioned_studio_is_told_to_provision_that_studio():
    """Observed, not invented: the gateway refuses an unknown alias with a 400
    rather than falling back to the shared key. The remedy is to add a key for
    this studio, and nothing in the raw body says that in those words."""
    message = ai_gateway.http_error(400, UNKNOWN_ALIAS_BODY,
                                      studio=STUDIO, alias=STUDIO)
    assert "no key" in message.lower() or "not provisioned" in message.lower()
    assert STUDIO in message
    # The body survives alongside it: the remedy is a reading of the response,
    # not a replacement for it.
    assert "2040" in message


def test_a_rejected_gateway_token_is_not_confused_with_a_missing_studio_key():
    """Same status, same error envelope, opposite remedy — one is "provision
    this studio", the other is "our own secret is wrong". Telling an operator
    to add a studio key when the token is what broke sends them at the wrong
    system entirely."""
    message = ai_gateway.http_error(400, UNAUTHORIZED_BODY,
                                      studio=STUDIO, alias=STUDIO)
    assert "SYMBIOTICA_AIG_TOKEN" in message
    assert "no key" not in message.lower()


def test_a_code_nobody_has_seen_yet_earns_no_remedy_at_all():
    """The failure mode of code-matching is not losing the body — it is
    inventing a diagnosis for a code nobody has read yet. A generic sentence
    reads as recognition and sends the operator looking for the wrong thing,
    while the response's own words were the only real information present."""
    body = ('{"error":[{"code":9999,"message":"something new"}],'
            '"internalCode":9999}')
    assert ai_gateway.gateway_remedy(body) == ""
    message = ai_gateway.http_error(400, body, studio=STUDIO, alias=STUDIO)
    assert "something new" in message
    # Nothing between the colon and the body: no sentence was manufactured.
    assert message.split(f"{STUDIO}]:")[1].lstrip().startswith("{")


def test_a_body_carrying_no_code_at_all_earns_no_remedy_either():
    assert ai_gateway.gateway_remedy('{"message":"plain"}') == ""
    assert ai_gateway.gateway_remedy("not json at all") == ""


def test_a_body_that_is_not_json_still_reaches_the_operator():
    """Gateways answer with HTML when they are unhappy enough."""
    message = ai_gateway.http_error(502, "<html>Bad Gateway</html>",
                                      studio=STUDIO, alias=STUDIO)
    assert "Bad Gateway" in message


def test_a_missing_alias_is_left_out_rather_than_printed_as_none():
    """"key alias None" reads as an alias literally named None, which is a
    different and much more alarming bug than the one that happened."""
    message = ai_gateway.http_error(500, "boom", studio="a-studio")
    assert "None" not in message
    assert "a-studio" in message


# The state dev's anthropic provider is in today: no BYOK credential exists for
# the provider at all, so the alias is never consulted and the call falls
# through to Cloudflare's own billing. Captured against the real gateway.
NO_PROVIDER_KEY_BODY = (
    '{"success":false,"error":[{"code":2021,"message":"Insufficient wholesale '
    'credits"}],"name":"AiGatewayError","httpCode":402,"internalCode":2021,'
    '"message":"Insufficient wholesale credits"}')


def test_a_provider_with_no_byok_key_at_all_is_told_that_and_not_to_add_an_alias():
    """Distinct from 2040 in who fixes it and how: 2040 means this studio is
    unprovisioned, 2021 means the provider is, and the alias was never read."""
    message = ai_gateway.http_error(402, NO_PROVIDER_KEY_BODY,
                                    studio=STUDIO, alias=STUDIO)
    assert "no BYOK key" in message
    assert "studio's slug as its BYOK alias" not in message


def test_the_provider_with_no_key_case_warns_that_the_spend_left_the_boundary():
    """The only code here whose bad outcome has no error path. It failed as a
    402 because the balance was empty; Cloudflare's documented precedence is
    request key, then stored BYOK by alias, then their own credentials billed
    to that balance — so a funded account turns this same call into a success
    attributed to nobody."""
    remedy = ai_gateway.gateway_remedy(NO_PROVIDER_KEY_BODY)
    assert "wholesale" in remedy
    assert "BYOK boundary" in remedy


def test_each_of_the_three_codes_keeps_its_own_advice():
    """One dict, three opposite readers — an operator sent at the wrong system
    is the failure this table exists to prevent."""
    remedies = {code: ai_gateway.GATEWAY_REMEDIES[code]
                for code in (2009, 2040, 2021)}
    assert len(set(remedies.values())) == 3
    assert "SYMBIOTICA_AIG_TOKEN" in remedies[2009]
    assert "this studio" in remedies[2040]
    assert "this provider" in remedies[2021]


def test_an_anthropic_key_is_scrubbed_from_a_failure_like_a_google_one():
    """Anthropic presents its key as x-api-key. A scrubber that knew only
    Google's header name would pass a Claude key straight into the log."""
    key = "sk-ant-not-a-real-key-at-all"
    secrets = ai_gateway.header_secrets({"x-api-key": key})
    message = ai_gateway.http_error(401, f'{{"error":"bad key {key}"}}',
                                    secrets=secrets)
    assert key not in message
    assert "[redacted]" in message


def test_a_header_the_call_needs_beyond_the_gateways_own_rides_both_arms():
    """anthropic-version is required by Anthropic and injected by nobody. It
    is merged here rather than added to the returned headers, because
    header_secrets reads off these headers to guarantee the wire and the
    scrubber agree — and a header added afterwards is one this never saw."""
    version = {"anthropic-version": "2023-06-01"}
    assert resolve(gateway_env(), extra_headers=version)[1][
        "anthropic-version"] == "2023-06-01"
    assert resolve({}, lambda: "k", extra_headers=version)[1][
        "anthropic-version"] == "2023-06-01"


def test_a_failure_names_whose_call_it_was():
    """Two providers share this formatter now. "Request failed (500)" in a
    headless log leaves the reader to guess which of them it was, and the
    guess is between the node that draws and the node that writes."""
    assert ai_gateway.http_error(500, "boom", service="Gemini").startswith(
        "Gemini request failed (500)")
    assert ai_gateway.http_error(500, "boom", service="Claude").startswith(
        "Claude request failed (500)")


def test_an_unnamed_service_is_left_unnamed_rather_than_guessed():
    assert ai_gateway.http_error(500, "boom").startswith("Request failed (500)")


def test_a_box_still_carrying_the_retired_names_refuses_rather_than_paying():
    """The migration window. An order sandbox on the old names has
    ORDER_STUDIO set and is caught by the guard below, but a CANVAS box has no
    studio — so without this it falls to the direct arm and quietly bills a
    personal key, which the code's own comment calls the failure nobody can
    detect afterwards."""
    for stale in ({"GEMINI_GATEWAY_URL": "https://gateway.example.invalid/x"},
                  {"GEMINI_GATEWAY_TOKEN": TOKEN},
                  {"GEMINI_GATEWAY_URL": "https://gateway.example.invalid/x",
                   "GEMINI_GATEWAY_TOKEN": TOKEN}):
        with pytest.raises(ValueError) as caught:
            resolve(dict(stale), lambda: "a-personal-key-that-must-not-pay")
        # Names the variable to rename. A generic "no key" would send the
        # reader at the Settings UI rather than at the Modal secret.
        assert "SYMBIOTICA_AIG_BASE" in str(caught.value)
        assert any(name in str(caught.value) for name in stale)


def test_the_guard_does_not_fire_on_a_box_that_simply_has_no_gateway():
    """Canvas boxes carry none of these. The migration guard must cost the
    ordinary interactive user nothing."""
    assert resolve({}, lambda: "k").url.startswith(
        "https://generativelanguage.googleapis.com")


def test_a_retired_name_left_empty_is_not_treated_as_set():
    """An unset variable arrives as "" from a secret that failed to populate,
    and blocking on that would strand a box that had already migrated."""
    assert resolve({"GEMINI_GATEWAY_URL": "  ", "GEMINI_GATEWAY_TOKEN": ""},
                   lambda: "k").url.startswith(
        "https://generativelanguage.googleapis.com")


def test_the_surface_says_where_the_call_came_from(monkeypatch):
    """Gateway analytics groups by this tag, so a canvas render arriving as an
    order inflates order spend with a label that looks right, which is the kind
    of wrong number nobody thinks to question."""
    assert json.loads(ai_gateway.studio_tag("a-studio", "canvas")) == {
        "studio": "a-studio", "surface": "canvas"}


def test_an_unset_surface_still_says_order(monkeypatch):
    """Every order sandbox in existence sets no surface variable, so the
    default is what keeps their traffic labelled as it always has been. A
    change of default would silently relabel history's worth of runs."""
    transport = resolve(gateway_env())
    assert json.loads(transport.headers["cf-aig-metadata"])["surface"] == "order"


def test_the_environment_chooses_the_surface(monkeypatch):
    """Set alongside the base and the studio, by whoever creates the sandbox."""
    transport = resolve(gateway_env(SYMBIOTICA_AIG_SURFACE="canvas"))
    assert json.loads(transport.headers["cf-aig-metadata"]) == {
        "studio": STUDIO, "surface": "canvas"}


def test_a_hostile_surface_cannot_break_the_metadata_header():
    """`studio` is put through usable_as_header; `surface` is not, because it
    arrives from the environment and lands inside a JSON string rather than
    beside one. What keeps that safe is json.dumps escaping: a newline becomes
    a literal backslash-n and anything non-ASCII becomes \\uXXXX, so the header
    stays one printable latin-1 line whatever the variable holds.

    Pinned because the safety is a DEFAULT, not a decision anyone made here.
    `ensure_ascii=False` on that dump would put raw bytes into a header, and
    requests raises on those with the whole header value in the message."""
    for hostile in ("a\nb", "x\ry", "café", "中文", "a b\tc"):
        tag = ai_gateway.studio_tag(STUDIO, hostile)
        assert tag.isprintable(), f"{hostile!r} left a control character"
        tag.encode("latin-1")
        assert json.loads(tag)["surface"] == hostile


# The REST arm — Cloudflare's own AI API rather than provider passthrough.
# It exists because some catalog models (ByteDance's Seedance among them) have
# no passthrough provider slug at all, so there is no /bytedance path to route.
REST_ENV = {"SYMBIOTICA_CF_ACCOUNT_ID": "acct-tag",
            "SYMBIOTICA_CF_API_TOKEN": "cf-api-token-not-a-real-one",
            "SYMBIOTICA_AIG_GATEWAY_ID": "symbiotica-hub-dev",
            "ORDER_STUDIO": STUDIO}


def test_the_rest_arm_posts_to_the_accounts_own_ai_run():
    sent = ai_gateway.resolve_rest_transport(dict(REST_ENV))
    assert sent.url == ("https://api.cloudflare.com/client/v4/accounts/"
                        "acct-tag/ai/run")


def test_the_rest_arm_names_the_gateway_its_spend_belongs_to():
    """Without this header the call runs through the account's default
    gateway, so its log lands somewhere nobody reads and the studio tag with
    it."""
    sent = ai_gateway.resolve_rest_transport(dict(REST_ENV))
    assert sent.headers["cf-aig-gateway-id"] == "symbiotica-hub-dev"


def test_the_rest_arm_presents_the_cloudflare_token_as_a_bearer():
    sent = ai_gateway.resolve_rest_transport(dict(REST_ENV))
    assert sent.headers["Authorization"] == "Bearer cf-api-token-not-a-real-one"


def test_the_rest_arm_tags_its_spend_with_the_studio_like_the_other_one():
    sent = ai_gateway.resolve_rest_transport(dict(REST_ENV))
    assert json.loads(sent.headers["cf-aig-metadata"])["studio"] == STUDIO
    assert sent.studio == STUDIO


def test_the_rest_arm_sends_no_byok_alias_because_this_path_ignores_it():
    """Cloudflare consults only the `default` alias on Unified Billing
    endpoints. A header saying otherwise would read, to anyone auditing this,
    as a per-studio key that is not in fact being used."""
    sent = ai_gateway.resolve_rest_transport(dict(REST_ENV))
    assert "cf-aig-byok-alias" not in sent.headers


@pytest.mark.parametrize("missing", ["SYMBIOTICA_CF_ACCOUNT_ID",
                                     "SYMBIOTICA_CF_API_TOKEN",
                                     "SYMBIOTICA_AIG_GATEWAY_ID"])
def test_a_rest_arm_missing_any_of_its_three_parts_says_which(missing):
    environ = dict(REST_ENV)
    del environ[missing]
    with pytest.raises(ValueError) as raised:
        ai_gateway.resolve_rest_transport(environ)
    assert missing in str(raised.value)


def test_the_rest_arm_refuses_to_run_for_no_studio_at_all():
    """Same reasoning as the passthrough arm: spend that reaches no studio row
    is spend nobody can account for, and this path has no alias to fall back
    on either."""
    environ = dict(REST_ENV)
    del environ["ORDER_STUDIO"]
    with pytest.raises(ValueError) as raised:
        ai_gateway.resolve_rest_transport(environ)
    assert "studio" in str(raised.value).lower()


def test_a_cloudflare_token_with_a_stray_newline_is_refused_before_it_is_sent():
    """A trailing newline is the commonest artifact in a secret store, and the
    transport library would raise with the whole credential quoted in its
    message — by a path that never reaches the scrubber."""
    environ = dict(REST_ENV, SYMBIOTICA_CF_API_TOKEN="tok\nen-value-here")
    with pytest.raises(ValueError) as raised:
        ai_gateway.resolve_rest_transport(environ)
    assert "en-value-here" not in str(raised.value)


def test_the_cloudflare_token_is_scrubbed_out_of_a_failure():
    """It is a broader credential than any provider key — it authenticates to
    the Cloudflare account, not to one model vendor. Leaking it into a toast
    is worse than leaking the provider key it stands in for."""
    sent = ai_gateway.resolve_rest_transport(dict(REST_ENV))
    said = ai_gateway.http_error(
        403, "rejected token cf-api-token-not-a-real-one",
        secrets=ai_gateway.header_secrets(sent.headers))
    assert "cf-api-token-not-a-real-one" not in said
    assert "[redacted]" in said


def test_a_gateway_id_with_a_stray_newline_is_refused_before_it_is_sent():
    """It rides in a header like the others, so it gets the same check. Left to
    the transport library this raises with the value quoted, from a message
    written for a credential rather than for a gateway name."""
    environ = dict(REST_ENV, SYMBIOTICA_AIG_GATEWAY_ID="hub\ndev")
    with pytest.raises(ValueError) as raised:
        ai_gateway.resolve_rest_transport(environ)
    assert "SYMBIOTICA_AIG_GATEWAY_ID" in str(raised.value)
