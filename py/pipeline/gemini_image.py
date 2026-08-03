# ABOUTME: Gemini image generation through Cloudflare AI Gateway — the request
# ABOUTME: it sends, where it sends it, and what it makes of what comes back.
from __future__ import annotations

import base64
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
    if gateway:
        token = (environ.get("GEMINI_GATEWAY_TOKEN") or "").strip()
        if not token:
            raise ValueError(
                "GEMINI_GATEWAY_URL is set but GEMINI_GATEWAY_TOKEN is empty. "
                "Both come from the symbiotica-comfy-gemini secret; a call "
                "cannot fall back to a personal Google key here, because the "
                "spend for this box belongs in the gateway."
            )
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
        "x-goog-api-key": interactive_key(),
        "Content-Type": "application/json",
    }, None)


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
    text = (body or "")[:MAX_ERROR_BODY_CHARS]
    for secret in secrets:
        # An unset credential is "", and replacing that seeds the marker
        # between every character of the body.
        if secret:
            text = text.replace(secret, "[redacted]")
    whose = f" [studio {studio}, key alias {alias}]" if studio or alias else ""
    return f"Gemini request failed ({status}){whose}: {text}"


def parse_response(payload: dict):
    """The images Gemini drew and what it said about them, `(images, text)`.

    Raises rather than returning an empty list: a graph handed zero images
    fails somewhere downstream, with the response long out of view. In an order
    sandbox the raise is the only artifact a human ever reads, so it carries
    Gemini's own words whenever there are any — a refusal is explained in the
    text channel and nowhere else."""
    candidates = payload.get("candidates") or []
    if not candidates:
        feedback = payload.get("promptFeedback") or {}
        reason = feedback.get("blockReason")
        if reason:
            detail = feedback.get("blockReasonMessage")
            raise ValueError(f"Gemini blocked the request. Reason: {reason}"
                             + (f" ({detail})" if detail else ""))
        raise ValueError("Gemini returned no candidates.")

    images, texts, blocked = [], [], []
    for candidate in candidates:
        finish = (candidate.get("finishReason") or "").upper()
        if finish == "IMAGE_PROHIBITED_CONTENT":
            blocked.append(finish)
            continue
        for part in (candidate.get("content") or {}).get("parts") or []:
            # Thinking-capable models emit interim sketches flagged this way.
            # v1 has no thought_image output, but an unfiltered sketch does not
            # vanish — it becomes an ordinary image, and possibly the first one.
            if part.get("thought") is True:
                continue
            inline = part.get("inlineData")
            if inline and str(inline.get("mimeType", "")).startswith("image/"):
                images.append(Image.open(
                    io.BytesIO(base64.b64decode(inline["data"]))))
            elif part.get("text"):
                texts.append(part["text"])
    text = "\n".join(texts).strip()
    if not images:
        if blocked:
            raise ValueError(f"Gemini blocked the image. Reason: "
                             f"{', '.join(blocked)}")
        if text:
            raise ValueError(f"Gemini did not generate an image. "
                             f"Model response: {text}")
        raise ValueError("Gemini did not generate an image. Try rephrasing the "
                         "prompt.")
    return images, text


def request_body(prompt: str, inline_images: list, aspect_ratio: str,
                 resolution: str, system_prompt: str) -> dict:
    """One native Gemini generateContent call. `inline_images` are the parts
    `image_parts` built, and they follow the prompt in input order.

    Text is asked for alongside the image because it is the diagnostic channel:
    when Gemini declines, it says why there, and in a headless sandbox that
    sentence is the only account anyone gets. `auto` is Google's absence of
    aspectRatio rather than a value it accepts, so it is omitted."""
    if not (prompt or "").strip():
        raise ValueError("prompt is required — Gemini has nothing to draw from "
                         "an empty one")
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
