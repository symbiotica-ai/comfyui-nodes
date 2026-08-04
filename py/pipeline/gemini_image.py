# ABOUTME: Gemini image generation through Cloudflare AI Gateway — the request
# ABOUTME: it sends, where it sends it, and what it makes of what comes back.
from __future__ import annotations

import base64
import io
from typing import Callable

from PIL import Image

from . import ai_gateway

# Cloudflare's slug for Google AI Studio, the last path segment of the gateway
# endpoint. It lives here rather than in the shared base so that adding a
# provider costs no environment variable and no secret edit.
PROVIDER = "google-ai-studio"
# Google's own path, and the suffix for both arms: AI Gateway's provider
# endpoint appends the upstream provider's path verbatim after the slug, so the
# gateway base plus this reaches the same place the direct call does.
GENERATE_CONTENT_PATH = "/v1beta/models/{model}:generateContent"
GOOGLE_API_BASE = "https://generativelanguage.googleapis.com"
# 1K renders run tens of seconds; a 4K upscale runs several minutes.
REQUEST_TIMEOUT_S = 300
# Google's own limit, and the stock node's wording for it.
MAX_REFERENCE_IMAGES = 14

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

# Any of these appearing at the top level means a generateContent endpoint
# answered, however little it had to say. Their absence is what distinguishes
# a wrong URL from an empty reply.
GENERATE_CONTENT_KEYS = {"candidates", "promptFeedback", "usageMetadata",
                         "modelVersion", "responseId"}

MODELS = ["gemini-3.1-flash-image", "gemini-3.1-flash-lite-image"]

# What the canvas shows against what the API is sent. Raw ids do not say which
# of the two is the cheap one, and the labels are the ones ComfyUI's own node
# uses, so the same model reads the same in both. The full model resolves to
# the unsuffixed AI Studio id rather than core's `-preview`: both answer 200
# through the gateway and each echoes its own name back as `modelVersion`, so
# they are separate ids on this surface and ours is the stable channel. Core
# talks Vertex, which is not a surface this pack supports.
MODEL_LABELS = {
    "Nano Banana 2 (Gemini 3.1 Flash Image)": "gemini-3.1-flash-image",
    "Nano Banana 2 Lite": "gemini-3.1-flash-lite-image",
}

ASPECT_RATIOS = ["auto", "1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4",
                 "9:16", "16:9", "21:9", "1:4", "4:1", "8:1", "1:8"]
RESOLUTIONS = ["1K", "2K", "4K"]

# Lite renders at 1K only. Offered the full list it takes 2K or 4K and refuses
# the call, so the ceiling belongs in the input rather than in a tooltip.
MODEL_RESOLUTIONS = {
    "gemini-3.1-flash-image": ["1K", "2K", "4K"],
    "gemini-3.1-flash-lite-image": ["1K"],
}

THINKING_LEVELS = ["MINIMAL", "HIGH"]

# What the model is allowed to answer with. IMAGE alone suppresses the
# commentary; the thought image needs TEXT present as well as HIGH thinking.
RESPONSE_MODALITIES = ["IMAGE", "IMAGE+TEXT"]


def generate_content_path(model: str) -> str:
    return GENERATE_CONTENT_PATH.format(model=model)


# How a Google key is presented when no gateway is configured. The header name
# and what a rejection calls the key are both Google's business, so they live
# here rather than in the transport every provider shares.
DIRECT_ARM = ai_gateway.DirectArm(
    GOOGLE_API_BASE, "The Gemini API key",
    lambda key: {"x-goog-api-key": key})


def resolve_transport(environ, model: str,
                      interactive_key: Callable[[], str]):
    """This node's call, routed by the rules every provider shares."""
    return ai_gateway.resolve_transport(
        environ, PROVIDER, generate_content_path(model), interactive_key,
        DIRECT_ARM)












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




def decode_inline_image(inline: dict):
    """One inlineData part as a PIL image.

    Every way this can fail — an absent `data` key, base64 that will not
    decode, bytes that are not an image — arrives as a library exception
    naming neither Gemini nor the render. In a sandbox log that reads as a bug
    in this pack rather than a mangled response, which is a different
    investigation entirely."""
    try:
        return Image.open(io.BytesIO(base64.b64decode(inline["data"])))
    # binascii.Error is a ValueError, so listing it separately would only
    # imply base64 failures are something ValueError does not already cover.
    except (KeyError, ValueError, TypeError, OSError) as exc:
        raise ValueError(
            f"Gemini returned an image part that could not be decoded "
            f"({type(exc).__name__}: {exc})") from exc


def parse_response(payload):
    """What Gemini drew, said, and thought: `(images, text, thought_images)`.

    `payload` is whatever the response body decoded to, not necessarily a
    generateContent object: a misconfigured endpoint answers 200 with its own
    envelope, and a type annotation promising otherwise would only hide that.

    Raises rather than returning an empty list: a graph handed zero images
    fails somewhere downstream, with the response long out of view. In an order
    sandbox the raise is the only artifact a human ever reads, so it carries
    Gemini's own words wherever the reply put them. There are three places, and
    a refusal uses the last: text parts, `promptFeedback.blockReason`, and
    `finishMessage` on a candidate that came back with no parts at all."""
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
        # Any one of the shape's own keys proves the right endpoint answered,
        # including `candidates` itself. Keying on promptFeedback alone told
        # an operator with a legitimately empty reply to go and check a URL
        # that was correct, in a sentence that named `candidates` as evidence
        # the reply was not a generateContent shape.
        if not GENERATE_CONTENT_KEYS & set(payload):
            raise ValueError(
                f"Gemini returned no candidates, and the reply carries "
                f"{sorted(payload)[:8]} rather than a generateContent shape. "
                f"Check the endpoint this node is pointed at.")
        raise ValueError("Gemini returned no candidates.")

    images, texts, refusals, explained = [], [], [], []
    thoughts = []  # Interim sketches, kept out of `images` — see the loop.
    for candidate in candidates:
        # Same guard the payload carries, one level down: a reply whose
        # candidates are not objects is a wrong-endpoint symptom, and letting
        # it reach .get() names neither Gemini nor the URL.
        if not isinstance(candidate, dict):
            raise ValueError(
                f"Gemini returned a candidate that is a "
                f"{type(candidate).__name__} rather than an object. Check the "
                f"endpoint this node is pointed at.")
        # Coerced for the same reason finishMessage is: a response value must
        # not raise from inside the code reporting the failure.
        finish = str(candidate.get("finishReason") or "").upper()
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
            # Nothing is lost by that: a refusal carries no parts whatsoever —
            # neither text nor thought — and explains itself in
            # `finishMessage`, which this filter never sees.
            #
            # `thought` is checked by VALUE, not by presence. A genuine render
            # arrives carrying `thoughtSignature` with no `thought` key at
            # all, so a filter asking whether a part looks thought-ish would
            # discard the image and report that Gemini produced nothing.
            inline = part.get("inlineData")
            is_image = inline and str(
                inline.get("mimeType", "")).startswith("image/")
            if part.get("thought") is True:
                # Kept apart rather than dropped: an interim sketch is worth
                # seeing, but it is not the render, and letting it join `images`
                # can make it the FIRST one. Thought TEXT stays discarded — the
                # text output reaches clients and stored runs, where reasoning
                # prose would bury a one-line refusal.
                if is_image and not prohibited:
                    thoughts.append(decode_inline_image(inline))
                continue
            if is_image:
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
    return images, text, thoughts


def modalities_for(response_modalities: str) -> list:
    """Google's `responseModalities` for the choice the canvas offers.

    IMAGE alone is a real setting rather than a saving: it suppresses the
    commentary, and with it the thought image, which needs a TEXT modality to
    come back at all. Anything unrecognised asks for both, because the failure
    of a bad value here is a render that silently loses its text."""
    return ["IMAGE"] if response_modalities == "IMAGE" else ["TEXT", "IMAGE"]


def request_body(prompt: str, inline_images: list, aspect_ratio: str,
                 resolution: str, system_prompt: str,
                 thinking_level: str = "MINIMAL", temperature: float = 1.0,
                 top_p: float = 0.95,
                 response_modalities: str = "IMAGE+TEXT") -> dict:
    """One native Gemini generateContent call. `inline_images` are the parts
    `image_parts` built, and they follow the prompt in input order.

    Text is asked for alongside the image by default because the model's
    commentary is worth having and costs nothing — not because a refusal
    arrives there. A refusal carries no parts at all and explains itself in
    `finishMessage`, so asking for IMAGE only would lose the commentary and
    change nothing about diagnosing a decline. `auto` is Google's absence of
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
            "responseModalities": modalities_for(response_modalities),
            "imageConfig": image_config,
            "thinkingConfig": {"thinkingLevel": thinking_level},
            "temperature": temperature,
            "topP": top_p,
        },
    }
    # No role inside systemInstruction: Google's shape has none, and the stock
    # node passes None there for the same reason.
    if (system_prompt or "").strip():
        body["systemInstruction"] = {"parts": [{"text": system_prompt}]}
    return body
