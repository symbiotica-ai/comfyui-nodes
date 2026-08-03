# ABOUTME: Gemini image generation through Cloudflare AI Gateway — the request
# ABOUTME: it sends, where it sends it, and what it makes of what comes back.
from __future__ import annotations

import base64
import binascii
import io
import json
from typing import Callable, NamedTuple

from PIL import Image

# Google's own path, and the suffix for both arms: AI Gateway's provider
# endpoint appends the upstream provider's path verbatim after the slug, so the
# gateway base plus this reaches the same place the direct call does.
GENERATE_CONTENT_PATH = "/v1beta/models/{model}:generateContent"
GOOGLE_API_BASE = "https://generativelanguage.googleapis.com"
# 1K renders run tens of seconds; a 4K upscale runs several minutes.
REQUEST_TIMEOUT_S = 300
# Separate, because a single number would spend the whole read budget waiting
# on a connection that will never open — a black-holed egress would hold a
# customer's order for five minutes before saying anything.
CONNECT_TIMEOUT_S = 10
# Google's own limit, and the stock node's wording for it.
MAX_REFERENCE_IMAGES = 14
# Enough of a failure body to diagnose from without pasting a whole HTML page.
MAX_ERROR_BODY_CHARS = 500

# Verbatim from ComfyUI's own Gemini image nodes. It forces image-first
# behaviour, which is what keeps a conversational prompt from coming back as a
# paragraph — in a headless render that is a failed order, not a chat.
GEMINI_IMAGE_SYS_PROMPT = (
    "You are an expert image-generation engine. You must ALWAYS produce an image.\n"
    "Interpret all user input—regardless of "
    "format, intent, or abstraction—as literal visual directives for image composition.\n"
    "If a prompt is conversational or lacks specific visual details, "
    "you must creatively invent a concrete visual scenario that depicts the concept.\n"
    "Prioritize generating the visual representation above any text, formatting, or conversational requests."
)

MODELS = ["gemini-3.1-flash-image", "gemini-3.1-flash-lite-image"]
ASPECT_RATIOS = ["auto", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4",
                 "9:16", "16:9", "21:9"]
RESOLUTIONS = ["1K", "2K", "4K"]


def generate_content_path(model: str) -> str:
    return GENERATE_CONTENT_PATH.format(model=model)


class Transport(NamedTuple):
    """Where one call goes, what proves it may go there, and whose key pays.

    `studio` is None on the direct arm, where the question does not arise."""
    url: str
    headers: dict
    studio: str | None


def resolve_transport(environ, model: str,
                      interactive_key: Callable[[], str]) -> Transport:
    """The gateway when one is configured, Google directly otherwise.

    `interactive_key` is a callable rather than a value so the direct arm's
    key ladder — which reads a settings file and the environment — is never
    walked on a call that will not use it. It is also what makes the precedence
    testable without standing up that ladder.

    A configured gateway wins over any personal key, and a gateway URL without
    its token raises. The alternative, quietly spending a personal key on a box
    that was set up to route through the gateway, is the failure nobody can
    detect afterwards: the render succeeds and only the spend goes missing.

    Every gateway-arm decision lives here so that the whole of it can be
    exercised without importing ComfyUI."""
    gateway = (environ.get("GEMINI_GATEWAY_URL") or "").strip().rstrip("/")
    if not gateway and (environ.get("ORDER_STUDIO") or "").strip():
        # The launcher sets ORDER_STUDIO whether or not the secret populated,
        # so its presence without a URL is a broken sandbox rather than a
        # canvas box. Left to fall through, this either fails citing a
        # Settings UI that does not exist here, or succeeds on a stray
        # personal key and takes the spend out of the gateway in silence.
        raise ValueError(
            "ORDER_STUDIO is set but GEMINI_GATEWAY_URL is empty, so this "
            "looks like an order sandbox whose symbiotica-comfy-gemini secret "
            "did not populate. Rendering here would either fail asking for a "
            "key this box cannot hold, or quietly bill one that is not the "
            "studio's."
        )
    if gateway:
        if not gateway.startswith("https://"):
            raise ValueError(
                f"GEMINI_GATEWAY_URL must be https, got {gateway!r}. The "
                f"gateway token is a bearer credential for this studio's "
                f"whole spend and would cross the wire in the clear."
            )
        token = (environ.get("GEMINI_GATEWAY_TOKEN") or "").strip()
        if not token:
            raise ValueError(
                "GEMINI_GATEWAY_URL is set but GEMINI_GATEWAY_TOKEN is empty. "
                "Both come from the symbiotica-comfy-gemini secret; a call "
                "cannot fall back to a personal Google key here, because the "
                "spend for this box belongs in the gateway."
            )
        token = usable_as_header(token, "GEMINI_GATEWAY_TOKEN", quote_it=False)
        studio = (environ.get("ORDER_STUDIO") or "").strip()
        if not studio:
            # No fall back to the gateway's default alias. That would bill a
            # shared key while the metadata tag named a studio, and the two
            # would disagree in a way only a reconciliation of the Google bill
            # against gateway analytics could ever surface.
            raise ValueError(
                "ORDER_STUDIO is empty, so there is no studio whose Google key "
                "should pay for this render. The order sandbox sets it "
                "alongside the gateway secret; a render here would either be "
                "charged to another studio or attributed to none."
            )
        # Quoted, unlike the token: a studio slug is not a secret, and seeing
        # the value is most of the diagnosis.
        studio = usable_as_header(studio, "ORDER_STUDIO", quote_it=True)
        # No x-goog-api-key: with BYOK the gateway holds the Google key and
        # injects it upstream. There is no Google key on this box to send.
        return Transport(gateway + generate_content_path(model), {
            "cf-aig-authorization": f"Bearer {token}",
            # Which stored key pays. Passthrough-only: on Cloudflare's Unified
            # Billing endpoints this header is ignored and `default` pays.
            "cf-aig-byok-alias": studio,
            # What analytics can group by. The alias cannot serve this — no
            # AiGateway dataset exposes a dimension for it — so spend sent
            # without this tag is spend that cannot be attributed to anyone.
            "cf-aig-metadata": studio_tag(studio),
            "Content-Type": "application/json",
        }, studio)
    return Transport(GOOGLE_API_BASE + generate_content_path(model), {
        "x-goog-api-key": usable_as_header(
            interactive_key(), "The Gemini API key", quote_it=False),
        "Content-Type": "application/json",
    }, None)


# Cloudflare AI Gateway internal codes, observed against the real gateway
# rather than guessed. Both arrive as HTTP 400 in the same error envelope and
# call for opposite responses from opposite people, so the status alone sends
# somebody at the wrong system.
GATEWAY_REMEDIES = {
    2040: ("this studio has no key stored in the gateway — add one under the "
           "studio's slug as its BYOK alias"),
    2009: ("the gateway rejected our own credential — check "
           "GEMINI_GATEWAY_TOKEN in the symbiotica-comfy-gemini secret"),
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
    authorization = headers.get("cf-aig-authorization")
    if authorization:
        # Both forms: a gateway may quote back the whole header or just the
        # token it could not verify.
        secrets.append(authorization)
        secrets.append(authorization.split(" ", 1)[-1])
    key = headers.get("x-goog-api-key")
    if key:
        secrets.append(key)
    return secrets


def require_prompt(prompt: str) -> str:
    """`prompt`, once it is something Gemini can draw from.

    Its own function so the check can run before the work that would be
    wasted: walking the key ladder and encoding fourteen PNGs, only to raise
    about the prompt, costs a headless operator two round-trips to learn one
    thing."""
    if not (prompt or "").strip():
        raise ValueError("prompt is required — Gemini has nothing to draw from "
                         "an empty one")
    return prompt


def usable_as_header(value: str, source: str, quote_it: bool) -> str:
    """`value`, once it is something an HTTP header can actually carry.

    requests rejects control characters itself, but its exception quotes the
    whole header value — so a credential with an interior newline, which is
    what a mangled multi-line paste into a secret store produces, ends up in
    the toast and the log by a path that never reaches the scrubber. Refusing
    here keeps the diagnosis and loses the value: `quote_it` is False for
    anything secret, so the message names the variable and not its contents."""
    if any(c in value for c in "\r\n\t") or not value.isprintable():
        shown = f": {value!r}" if quote_it else ""
        raise ValueError(
            f"{source} contains characters an HTTP header cannot carry{shown}. "
            f"Check the secret for a stray newline or a truncated paste.")
    return value


def studio_tag(studio: str) -> str:
    """The `cf-aig-metadata` value for one studio's render.

    `surface` separates order renders from any later caller sharing the studio
    key. Kept to two entries deliberately: Cloudflare stores only the first
    five and silently drops the rest, so this is not an open bag."""
    return json.dumps({"studio": studio, "surface": "order"})


def image_parts(pil_images) -> list:
    """Each reference image as an inline PNG part, in the order given.

    Inline rather than uploaded: the stock node's upload path runs through
    ComfyUI's own credit infrastructure, which is the thing this node exists to
    avoid. The cap is checked before any encoding so a graph wired to sixteen
    references fails immediately rather than after sixteen PNG compressions."""
    images = list(pil_images)
    if len(images) > MAX_REFERENCE_IMAGES:
        raise ValueError(f"The current maximum number of supported images is "
                         f"{MAX_REFERENCE_IMAGES}.")
    parts = []
    for im in images:
        buf = io.BytesIO()
        im.save(buf, format="PNG")
        parts.append({"inlineData": {
            "mimeType": "image/png",
            "data": base64.b64encode(buf.getvalue()).decode("ascii"),
        }})
    return parts


def http_error(status: int, body: str, secrets=(), studio=None,
               alias=None) -> str:
    """What to say when the call came back a failure.

    A gateway failure names the studio and the alias unconditionally, rather
    than only when the response looks like an unprovisioned key. The gateway's
    answer to an alias it holds no key for is undocumented, so recognising that
    case would mean matching a signature nobody has observed — and a wrong
    guess stays green in tests while failing to name the studio in the headless
    log where the name is the whole diagnosis.

    `secrets` are scrubbed from the body because a gateway rejecting a token
    may quote it back, and this message goes on to a toast, a server log and
    whatever screenshot ends up in a bug report."""
    # Scrubbed before the cut, not after: truncating first leaves whatever of
    # a credential fell inside the window, and half a token in a bug report is
    # still half a token.
    text = body or ""
    for secret in secrets:
        # An unset credential is "", and replacing that seeds the marker
        # between every character of the body.
        if secret:
            text = text.replace(secret, "[redacted]")
    text = text[:MAX_ERROR_BODY_CHARS]
    # Each named only when known. "key alias None" reads as an alias literally
    # called None, which is a more alarming bug than the one that happened.
    known = [f"studio {studio}"] if studio else []
    if alias:
        known.append(f"key alias {alias}")
    whose = f" [{', '.join(known)}]" if known else ""
    # The remedy leads, because it is the sentence an operator acts on; the
    # body follows, because it is the one that survives a code we do not know.
    remedy = gateway_remedy(body or "")
    said = f" {remedy}." if remedy else ""
    return f"Gemini request failed ({status}){whose}:{said} {text}"


def decode_inline_image(inline: dict):
    """One inlineData part as a PIL image.

    Every way this can fail — an absent `data` key, base64 that will not
    decode, bytes that are not an image — arrives as a library exception
    naming neither Gemini nor the render. In a sandbox log that reads as a bug
    in this pack rather than a mangled response, which is a different
    investigation entirely."""
    try:
        return Image.open(io.BytesIO(base64.b64decode(inline["data"])))
    except (KeyError, ValueError, TypeError, OSError, binascii.Error) as exc:
        raise ValueError(
            f"Gemini returned an image part that could not be decoded "
            f"({type(exc).__name__}: {exc})") from exc


def parse_response(payload):
    """The images Gemini drew and what it said about them, `(images, text)`.

    `payload` is whatever the response body decoded to, not necessarily a
    generateContent object: a misconfigured endpoint answers 200 with its own
    envelope, and a type annotation promising otherwise would only hide that.

    Raises rather than returning an empty list: a graph handed zero images
    fails somewhere downstream, with the response long out of view. In an order
    sandbox the raise is the only artifact a human ever reads, so it carries
    Gemini's own words whenever there are any — a refusal is explained in the
    text channel and nowhere else."""
    # A wrong endpoint answers 200 with a different envelope entirely, and
    # "no candidates" reads as the model having refused — so the operator
    # retries the prompt while the URL is what is wrong.
    if not isinstance(payload, dict):
        raise ValueError(f"Gemini returned a {type(payload).__name__} rather "
                         f"than a generateContent object. Check the endpoint "
                         f"this node is pointed at.")
    candidates = payload.get("candidates") or []
    if not candidates:
        feedback = payload.get("promptFeedback") or {}
        reason = feedback.get("blockReason")
        if reason:
            detail = feedback.get("blockReasonMessage")
            raise ValueError(f"Gemini blocked the request. Reason: {reason}"
                             + (f" ({detail})" if detail else ""))
        if "promptFeedback" not in payload:
            raise ValueError(
                f"Gemini returned no candidates, and the reply carries "
                f"{sorted(payload)[:8]} rather than a generateContent shape. "
                f"Check the endpoint this node is pointed at.")
        raise ValueError("Gemini returned no candidates.")

    images, texts, refusals, explained = [], [], [], []
    for candidate in candidates:
        # Same guard the payload carries, one level down: a reply whose
        # candidates are not objects is a wrong-endpoint symptom, and letting
        # it reach .get() names neither Gemini nor the URL.
        if not isinstance(candidate, dict):
            raise ValueError(
                f"Gemini returned a candidate that is a "
                f"{type(candidate).__name__} rather than an object. Check the "
                f"endpoint this node is pointed at.")
        finish = (candidate.get("finishReason") or "").upper()
        # Where a refusal actually explains itself. A declined generation
        # comes back 200 with no parts at all — no text, no thought, an empty
        # `content` — so this field is the only account of it in the reply,
        # and substituting our own sentence for it discards the whole thing.
        #
        # str() rather than .strip() on the raw value: only the string form
        # has been observed, and a shape change upstream must not raise from
        # inside the diagnostic and lose the reason along with it.
        explanation = str(candidate.get("finishMessage") or "").strip()
        if explanation and explanation not in explained:
            explained.append(explanation)
        # Every reason but STOP is kept, not only the one worth skipping the
        # candidate for. Gemini also stops for SAFETY, RECITATION and others,
        # and reporting only the special case means the model said exactly why
        # while the operator read generic advice.
        if finish and finish != "STOP" and finish not in refusals:
            refusals.append(finish)
        # A prohibited candidate's IMAGES are the thing being refused; its
        # WORDS are the half an operator can act on. Skipping the whole
        # candidate threw both away together.
        prohibited = finish == "IMAGE_PROHIBITED_CONTENT"
        for part in (candidate.get("content") or {}).get("parts") or []:
            # Thinking-capable models emit interim sketches flagged this way.
            # v1 has no thought_image output, but an unfiltered sketch does not
            # vanish — it becomes an ordinary image, and possibly the first one.
            #
            # This drops thought TEXT too, which ComfyUI's own nodes keep. The
            # text output is a diagnostic that can reach a client or a stored
            # run, and reasoning prose would bury a one-line refusal in it.
            # That rests on refusals arriving as ordinary text parts, which is
            # how they arrive today but is not a documented guarantee: if one
            # ever came back flagged `thought`, this line would eat the only
            # account of why the render failed.
            if part.get("thought") is True:
                continue
            inline = part.get("inlineData")
            if inline and str(inline.get("mimeType", "")).startswith("image/"):
                if not prohibited:
                    images.append(decode_inline_image(inline))
            elif part.get("text"):
                texts.append(part["text"])
    text = "\n".join(texts).strip()
    if not images:
        # Everything the response offered about why, in one sentence: the
        # reasons it stopped for and its own words. Only when it offered
        # neither is there nothing better to say than advice.
        said = "Gemini did not generate an image."
        if refusals:
            said += f" Reason: {', '.join(refusals)}."
        for explanation in explained:
            said += f" {explanation}"
        if text:
            said += f" Model response: {text}"
        # Only when the reply offered nothing at all. Ours is generic by
        # construction; Google's names the model and the request, so adding
        # ours alongside theirs would say the same thing twice and worse.
        if not refusals and not text and not explained:
            said += " Try rephrasing the prompt."
        raise ValueError(said)
    return images, text


def request_body(prompt: str, inline_images: list, aspect_ratio: str,
                 resolution: str, system_prompt: str) -> dict:
    """One native Gemini generateContent call. `inline_images` are the parts
    `image_parts` built, and they follow the prompt in input order.

    Text is asked for alongside the image because it is the diagnostic channel:
    when Gemini declines, it says why there, and in a headless sandbox that
    sentence is the only account anyone gets. `auto` is Google's absence of
    aspectRatio rather than a value it accepts, so it is omitted."""
    require_prompt(prompt)
    image_config = {"imageSize": resolution}
    if aspect_ratio != "auto":
        image_config["aspectRatio"] = aspect_ratio
    body = {
        "contents": [{
            "role": "user",
            "parts": [{"text": prompt}] + list(inline_images),
        }],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
            "imageConfig": image_config,
        },
    }
    # No role inside systemInstruction: Google's shape has none, and the stock
    # node passes None there for the same reason.
    if (system_prompt or "").strip():
        body["systemInstruction"] = {"parts": [{"text": system_prompt}]}
    return body
