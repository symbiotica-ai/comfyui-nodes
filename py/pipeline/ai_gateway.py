# ABOUTME: Cloudflare AI Gateway transport shared by every provider node —
# ABOUTME: where a call goes, what proves it may go there, and whose key pays.
from __future__ import annotations

import json
from typing import Callable, NamedTuple

# Separate from any read timeout, because a single number would spend the whole
# budget waiting on a connection that will never open — a black-holed egress
# would hold a customer's order for minutes before saying anything.
CONNECT_TIMEOUT_S = 10
# Enough of a failure body to diagnose from without pasting a whole HTML page.
MAX_ERROR_BODY_CHARS = 500
# Shorter than any real gateway token or provider key. Below this a "secret" is
# a substring of ordinary words rather than something worth hiding.
MIN_SCRUBBABLE_SECRET = 8


class Transport(NamedTuple):
    """Where one call goes, what proves it may go there, and whose key pays.

    `studio` is None on the direct arm, where the question does not arise."""
    url: str
    headers: dict
    studio: str | None


class DirectArm(NamedTuple):
    """The provider's own endpoint, for boxes with no gateway configured.

    `headers` takes the resolved key and returns the headers that present it,
    because every provider names that header differently. `key_label` is what
    a rejection calls the key, so the message names the thing the reader has
    to go and fix rather than a header nobody set by hand."""
    base: str
    key_label: str
    headers: Callable[[str], dict]


def resolve_transport(environ, provider: str, path: str,
                      interactive_key: Callable[[], str],
                      direct: DirectArm,
                      extra_headers: dict | None = None) -> Transport:
    """The gateway when one is configured, the provider directly otherwise.

    `interactive_key` is a callable rather than a value so the direct arm's key
    ladder — which reads a settings file and the environment — is never walked
    on a call that will not use it. It is also what makes the precedence
    testable without standing up that ladder.

    A configured gateway wins over any personal key, and a gateway base without
    its token raises. The alternative, quietly spending a personal key on a box
    that was set up to route through the gateway, is the failure nobody can
    detect afterwards: the render succeeds and only the spend goes missing.

    `extra_headers` ride on both arms. They belong here rather than being added
    to the returned headers by the caller: `header_secrets` reads off these
    headers precisely so the wire and the scrubber cannot disagree, and a header
    added after this returns is a header this never saw.

    Every gateway-arm decision lives here so that the whole of it can be
    exercised without importing ComfyUI."""
    base = (environ.get("SYMBIOTICA_AIG_BASE") or "").strip().rstrip("/")
    if not base:
        # A box still carrying the per-provider variables is a box whose secret
        # was never updated. On an order sandbox ORDER_STUDIO is set and the
        # guard below catches it — but a canvas box has no studio, so it would
        # fall to the direct arm and quietly pay a personal key, which is the
        # one failure nobody detects afterwards. Named rather than inferred:
        # this says which variable to rename, where a generic missing-key error
        # sends the reader looking at the wrong system.
        retired = sorted(name for name in ("GEMINI_GATEWAY_URL",
                                           "GEMINI_GATEWAY_TOKEN")
                         if (environ.get(name) or "").strip())
        if retired:
            raise ValueError(
                f"{' and '.join(retired)} is set but SYMBIOTICA_AIG_BASE is "
                f"not. Those names are retired: the base no longer carries the "
                f"provider slug, and one token now covers every provider. "
                f"Until this box is given SYMBIOTICA_AIG_BASE and "
                f"SYMBIOTICA_AIG_TOKEN from the symbiotica-comfy-aigateway "
                f"secret, nothing here routes through the gateway.")
    # Read once: normalised in one place, so the guard below and the arm that
    # bills cannot come to disagree about what counts as a studio.
    studio = (environ.get("ORDER_STUDIO") or "").strip()
    if not base and studio:
        # The launcher sets ORDER_STUDIO whether or not the secret populated,
        # so its presence without a base is a broken sandbox rather than a
        # canvas box. Left to fall through, this either fails citing a
        # Settings UI that does not exist here, or succeeds on a stray
        # personal key and takes the spend out of the gateway in silence.
        raise ValueError(
            "ORDER_STUDIO is set but SYMBIOTICA_AIG_BASE is empty, so this "
            "looks like an order sandbox whose symbiotica-comfy-aigateway "
            "secret did not populate. Rendering here would either fail asking "
            "for a key this box cannot hold, or quietly bill one that is not "
            "the studio's."
        )
    if base:
        if not base.startswith("https://"):
            raise ValueError(
                f"SYMBIOTICA_AIG_BASE must be https, got {base!r}. The gateway "
                f"token is a bearer credential for this studio's whole spend "
                f"and would cross the wire in the clear."
            )
        token = (environ.get("SYMBIOTICA_AIG_TOKEN") or "").strip()
        if not token:
            raise ValueError(
                "SYMBIOTICA_AIG_BASE is set but SYMBIOTICA_AIG_TOKEN is empty. "
                "Both come from the symbiotica-comfy-aigateway secret; a call "
                "cannot fall back to a personal provider key here, because the "
                "spend for this box belongs in the gateway."
            )
        token = usable_as_header(token, "SYMBIOTICA_AIG_TOKEN", quote_it=False)
        if not studio:
            # No fall back to the gateway's default alias. That would bill a
            # shared key while the metadata tag named a studio, and the two
            # would disagree in a way only a reconciliation of the provider's
            # bill against gateway analytics could ever surface.
            raise ValueError(
                "ORDER_STUDIO is empty, so there is no studio whose provider "
                "key should pay for this call. The order sandbox sets it "
                "alongside the gateway secret; a call here would either be "
                "charged to another studio or attributed to none."
            )
        # Quoted, unlike the token: a studio slug is not a secret, and seeing
        # the value is most of the diagnosis.
        studio = usable_as_header(studio, "ORDER_STUDIO", quote_it=True)
        # No provider key header: with BYOK the gateway holds the key and
        # injects it upstream. There is no provider key on this box to send,
        # and Cloudflare documents that sending one alongside BYOK fails the
        # request outright rather than being ignored.
        headers = {
            "cf-aig-authorization": f"Bearer {token}",
            # Which stored key pays. Passthrough-only: on Cloudflare's Unified
            # Billing endpoints this header is ignored and `default` pays.
            "cf-aig-byok-alias": studio,
            # What analytics can group by. The alias cannot serve this — no
            # AiGateway dataset exposes a dimension for it — so spend sent
            # without this tag is spend that cannot be attributed to anyone.
            "cf-aig-metadata": studio_tag(
                studio, environ.get("SYMBIOTICA_AIG_SURFACE") or ""),
            "Content-Type": "application/json",
        }
        headers.update(extra_headers or {})
        return Transport(f"{base}/{provider}{path}", headers, studio)
    headers = dict(direct.headers(usable_as_header(
        interactive_key(), direct.key_label, quote_it=False)))
    headers["Content-Type"] = "application/json"
    headers.update(extra_headers or {})
    return Transport(direct.base + path, headers, None)


DEFAULT_SURFACE = "order"


def studio_tag(studio: str, surface: str = DEFAULT_SURFACE) -> str:
    """The cf-aig-metadata tag: whose key pays, and what kind of run it was.

    Gateway analytics groups by these, so `surface` decides which bucket the
    spend lands in. It defaults to `order` because every sandbox that exists
    today sets no surface variable, and changing what their traffic is called
    would relabel the history it is compared against.

    A canvas box routed through the gateway must set it to something else. A
    canvas render counted as an order inflates order spend under a label that
    reads correctly, which is the kind of wrong number nobody thinks to
    question."""
    return json.dumps({"studio": studio,
                       "surface": (surface or "").strip() or DEFAULT_SURFACE})


def usable_as_header(value: str, source: str, quote_it: bool) -> str:
    """`value`, once it is something an HTTP header can carry.

    Checked here rather than left to the transport library, which raises with
    the whole header value quoted in its message — the credential, in the toast
    and the log, by a path that never reaches the scrubber."""
    unusable = not value.isprintable()
    if not unusable:
        try:
            value.encode("latin-1")
        except UnicodeEncodeError:
            unusable = True
    if unusable:
        shown = f": {value!r}" if quote_it else ""
        raise ValueError(
            f"{source} contains characters an HTTP header cannot carry{shown}. "
            f"Check wherever this box keeps it — the secret, or Settings → "
            f"Symbiotica — for a stray newline or a truncated paste.")
    return value


# Cloudflare AI Gateway internal codes, observed against the real gateway
# rather than guessed. They arrive in the same error envelope and call for
# opposite responses from opposite people, so the status alone sends somebody
# at the wrong system.
GATEWAY_REMEDIES = {
    2040: ("this studio has no key stored in the gateway — add one under the "
           "studio's slug as its BYOK alias"),
    2009: ("the gateway rejected our own credential — check "
           "SYMBIOTICA_AIG_TOKEN, in the symbiotica-comfy-aigateway secret on "
           "a sandbox or under Settings → Symbiotica → AI Gateway on a box "
           "with no environment to set"),
    # Unlike the other two this is not only a failure. Cloudflare's documented
    # credential precedence is request key, then stored BYOK key by alias, then
    # Cloudflare's own credentials billed to the account balance — so with no
    # BYOK key for the provider the alias is never consulted and the call falls
    # through to that last rail. It failed here only because the balance was
    # empty; on a funded account the same call succeeds, billed to us and
    # attributed to no studio, with no error path to notice it.
    2021: ("this provider has no BYOK key at all, so the studio alias was "
           "never consulted and the call fell through to Cloudflare's own "
           "wholesale billing — add a provider key, and treat spend on this "
           "path as having left the BYOK boundary"),
}


def gateway_remedy(body: str) -> str:
    """What to do about a refusal whose internal code we recognise, or "".

    Only ever added to the body, never substituted for it. A code nobody has
    seen yet would otherwise become a generic sentence that says less than the
    response already did, and the first unrecognised code is exactly the case
    where the raw text is worth most."""
    try:
        code = json.loads(body).get("internalCode")
    except (ValueError, TypeError, AttributeError):
        return ""
    return GATEWAY_REMEDIES.get(code, "")


def header_secrets(headers) -> list:
    """The credential values these headers actually carry.

    Read back off the headers rather than re-read from the environment: the
    wire carries the token after `.strip()`, so scrubbing the raw variable
    finds nothing to replace when the secret store kept a trailing newline —
    and a trailing newline is both the commonest artifact in a secret store
    and the exact reason the strip is there. The two would disagree only in
    the case each of them exists to handle."""
    secrets = []
    # Both gateway credentials: `cf-aig-authorization` on the passthrough arm
    # and `Authorization` on the REST one. The second is a Cloudflare API
    # token, which authenticates to the whole account rather than to one model
    # vendor — leaking it into a toast is worse than leaking the provider key
    # it stands in for.
    for name in ("cf-aig-authorization", "Authorization"):
        authorization = headers.get(name)
        if not authorization:
            continue
        # Both forms: a gateway may quote back the whole header or just the
        # token it could not verify.
        secrets.append(authorization)
        secrets.append(authorization.split(" ", 1)[-1])
    for name in ("x-goog-api-key", "x-api-key"):
        key = headers.get(name)
        if key:
            secrets.append(key)
    return secrets


def http_error(status, body: str, secrets=(), studio=None, alias=None,
               service="") -> str:
    """One account of a call that did not come back as a usable answer.

    Scrubbed before it is truncated, so the guarantee holds for a credential
    straddling the cut rather than only for one that fits inside it.

    `service` names whose call this was. Two providers now share this message,
    and a log line that says only that a request failed leaves the reader to
    guess which of them it was."""
    text = body or ""
    for secret in secrets:
        # A one- or two-character value is a substring of ordinary words, so
        # replacing it shreds the message and protects nothing — and something
        # that short is not a usable credential either way.
        if secret and len(secret) >= MIN_SCRUBBABLE_SECRET:
            text = text.replace(secret, "[redacted]")
    text = text[:MAX_ERROR_BODY_CHARS]
    known = [f"studio {studio}"] if studio else []
    if alias:
        known.append(f"key alias {alias}")
    whose = f" [{', '.join(known)}]" if known else ""
    remedy = gateway_remedy(body or "")
    said = f" {remedy}." if remedy else ""
    failed = f"{service} request failed" if service else "Request failed"
    return f"{failed} ({status}){whose}:{said} {text}"


# Cloudflare's own AI API, which is where the model catalog lives. Some
# catalog models have no provider-passthrough slug at all — ByteDance's
# Seedance among them — so for those there is no `{base}/{provider}` path to
# route and this is the only way through the gateway.
CF_API_BASE = "https://api.cloudflare.com/client/v4/accounts"


def resolve_rest_transport(environ) -> Transport:
    """The account's own /ai/run, routed through our gateway and tagged.

    Unlike `resolve_transport` there is no second arm to fall back to. A
    catalog model has no provider endpoint to call directly, so a box without
    these three variables cannot make this call at all — and saying so is the
    whole of the honest answer.

    No `cf-aig-byok-alias`. Cloudflare consults only the `default` alias on
    Unified Billing endpoints, so whatever single key is stored there pays for
    every studio. Sending an alias would not change who pays; it would only
    read, to anyone auditing this later, as a per-studio key that is not in
    fact being used — which is the more expensive kind of wrong.

    The studio still rides in `cf-aig-metadata`, so spend remains attributable
    in analytics even though it is not separable by key. That distinction is
    the one thing about this arm worth keeping straight."""
    parts = {}
    for name in ("SYMBIOTICA_CF_ACCOUNT_ID", "SYMBIOTICA_CF_API_TOKEN",
                 "SYMBIOTICA_AIG_GATEWAY_ID"):
        value = (environ.get(name) or "").strip()
        if not value:
            raise ValueError(
                f"{name} is empty, so this box cannot reach the model catalog "
                f"through the gateway. All three of SYMBIOTICA_CF_ACCOUNT_ID, "
                f"SYMBIOTICA_CF_API_TOKEN and SYMBIOTICA_AIG_GATEWAY_ID come "
                f"from the symbiotica-comfy-aigateway secret. There is no "
                f"personal-key fallback here: a catalog model has no provider "
                f"endpoint of its own to call.")
        parts[name] = value
    studio = (environ.get("ORDER_STUDIO") or "").strip()
    if not studio:
        # Same reasoning as the passthrough arm, and it binds harder here:
        # that arm at least had an alias naming who paid. This one has only
        # the metadata tag, so an untagged call is spend attributable to
        # nobody by any route at all.
        raise ValueError(
            "ORDER_STUDIO is empty, so this call would be spend that reaches "
            "no studio's row. On this path the metadata tag is the only thing "
            "that attributes it — there is no key alias to fall back on.")
    studio = usable_as_header(studio, "ORDER_STUDIO", quote_it=True)
    token = usable_as_header(parts["SYMBIOTICA_CF_API_TOKEN"],
                             "SYMBIOTICA_CF_API_TOKEN", quote_it=False)
    headers = {
        "Authorization": f"Bearer {token}",
        # Without this the call runs through the account's default gateway,
        # where its log lands somewhere nobody reads and the studio tag with
        # it.
        # Quoted on failure, unlike the token: a gateway name is not a secret,
        # and seeing the value is most of the diagnosis.
        "cf-aig-gateway-id": usable_as_header(
            parts["SYMBIOTICA_AIG_GATEWAY_ID"], "SYMBIOTICA_AIG_GATEWAY_ID",
            quote_it=True),
        "cf-aig-metadata": studio_tag(
            studio, environ.get("SYMBIOTICA_AIG_SURFACE") or ""),
        "Content-Type": "application/json",
    }
    url = f"{CF_API_BASE}/{parts['SYMBIOTICA_CF_ACCOUNT_ID']}/ai/run"
    return Transport(url, headers, studio)
