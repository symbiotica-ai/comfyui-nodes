# ABOUTME: Claude text generation through Cloudflare AI Gateway — the request
# ABOUTME: it sends, how large it lets that get, and what it reads back.
from __future__ import annotations

import base64
import io
import json

from PIL import Image

from . import ai_gateway

# Cloudflare's slug for Anthropic, the last path segment of the gateway
# endpoint, and Anthropic's own path appended after it verbatim.
PROVIDER = "anthropic"
MESSAGES_PATH = "/v1/messages"
ANTHROPIC_API_BASE = "https://api.anthropic.com"
# Sent by us rather than by the gateway. ComfyUI's own Claude node omits it
# because the comfy.org proxy adds it server-side; through AI Gateway there is
# nothing in the path that would.
ANTHROPIC_VERSION = "2023-06-01"

# Live from GET /v1/models, minus claude-opus-4-1-20250805, which retires
# 2026-08-05 — offering it in a combo box means a saved workflow that stops
# working two days from now.
MODELS = ["claude-opus-5", "claude-sonnet-5", "claude-fable-5",
          "claude-opus-4-8", "claude-opus-4-7", "claude-sonnet-4-6",
          "claude-opus-4-6", "claude-opus-4-5-20251101",
          "claude-haiku-4-5-20251001", "claude-sonnet-4-5-20250929"]

# What the canvas shows against what the API is sent, in ComfyUI's own order
# and wording so the same model reads the same on either node. Opus 4.5 is
# ours alone — core does not carry it, and dropping it to match would cost a
# model rather than gain compatibility.
MODEL_LABELS = {
    "Opus 5": "claude-opus-5",
    "Opus 4.8": "claude-opus-4-8",
    "Fable 5": "claude-fable-5",
    "Sonnet 5": "claude-sonnet-5",
    "Opus 4.7": "claude-opus-4-7",
    "Opus 4.6": "claude-opus-4-6",
    "Opus 4.5": "claude-opus-4-5-20251101",
    "Sonnet 4.6": "claude-sonnet-4-6",
    "Sonnet 4.5": "claude-sonnet-4-5-20250929",
    "Haiku 4.5": "claude-haiku-4-5-20251001",
}

# Thinking is not one feature with one switch — it is four behaviours, and
# which one applies is a property of the model. That is why these are sets
# rather than a flag: a single flat model list can only omit the whole subject,
# which is exactly what this node did until the inputs became per-model.
THINKING_UNSUPPORTED = {"Haiku 4.5"}
# Anthropic sizes the budget itself from the effort hint.
ADAPTIVE_THINKING = {"Opus 4.8", "Sonnet 5", "Opus 4.7", "Opus 4.6",
                     "Sonnet 4.6"}
# Reason unconditionally: no `thinking` key at all, and "off" is not offered.
ALWAYS_THINKING = {"Opus 5", "Fable 5"}
# Wants "off" said out loud. Saying it to Fable 5 is a 400, hence a set.
EXPLICIT_THINKING_OFF = {"Sonnet 5"}
# temperature is removed on these and returns 400.
NO_TEMPERATURE = {"Opus 5", "Opus 4.8", "Fable 5", "Sonnet 5"}

REASONING_EFFORTS = ["off", "low", "medium", "high"]
# The older explicit-budget API, in tokens. Sized to sit under the default
# max_tokens of 32768 with room for an answer.
REASONING_BUDGET = {"low": 2048, "medium": 8192, "high": 16384}
# What the reply is always left, however little max_tokens allows.
MIN_ANSWER_TOKENS = 1024


def thinking_enabled(label: str, effort: str) -> bool:
    """Whether this model will reason for this effort.

    The always-thinking models ignore the effort entirely for this question:
    they reason whatever it says, which is why "off" is not among their
    choices."""
    if label in ALWAYS_THINKING:
        return True
    return effort not in ("off", None) and label not in THINKING_UNSUPPORTED


def thinking_config(label: str, effort: str, max_tokens: int):
    """`(thinking, output_config)` for one model and effort, either possibly
    None, matching ComfyUI's own node exactly.

    Four cases, and the ordering between them matters: always-thinking is
    checked before adaptive because Opus 5 is neither, and the explicit-off
    case is last because it only applies where thinking is not enabled."""
    if label in ALWAYS_THINKING:
        return None, {"effort": effort}
    if thinking_enabled(label, effort):
        if label in ADAPTIVE_THINKING:
            return {"type": "adaptive"}, {"effort": effort}
        # Budget mode. Clamped so the reply keeps room: a budget equal to
        # max_tokens spends the whole allowance reasoning and returns nothing,
        # which reads as the model having refused.
        budget = min(REASONING_BUDGET[effort],
                     max(MIN_ANSWER_TOKENS, max_tokens - MIN_ANSWER_TOKENS))
        return {"type": "enabled", "budget_tokens": budget}, None
    if label in EXPLICIT_THINKING_OFF:
        return {"type": "disabled"}, None
    return None, None


def temperature_for(label: str, effort: str, temperature):
    """The temperature to send, or None where the model will not take one.

    Anthropic rejects a temperature alongside thinking, and Opus 4.7 rejects
    one outright. Returning None rather than raising because a stale graph
    carrying a temperature into a model that stopped accepting it should still
    render — the setting is dropped, not the request."""
    if (label in NO_TEMPERATURE or label == "Opus 4.7"
            or thinking_enabled(label, effort)):
        return None
    return temperature

# Anthropic's high-resolution tier: these accept a 2576px long edge, and
# everything else caps at 1568 and downscales server-side. The default is the
# smaller one, so an id nobody has taught this about costs bytes rather than
# shipping them into a request that will shrink them anyway.
HIGH_RESOLUTION_MODELS = frozenset(
    ["claude-opus-5", "claude-sonnet-5", "claude-fable-5",
     "claude-opus-4-8", "claude-opus-4-7"])
HIGH_RESOLUTION_EDGE_PX = 2576
STANDARD_EDGE_PX = 1568


def max_image_edge(model: str) -> int:
    """The longest edge worth sending to this model.

    Not merely a fidelity question: every pixel above the model's own ceiling
    is thrown away upstream, and on the way there it is spent against
    Cloudflare's 10 MB log ceiling, past which the call is not recorded at all
    (see MAX_REQUEST_BYTES)."""
    return (HIGH_RESOLUTION_EDGE_PX if model in HIGH_RESOLUTION_MODELS
            else STANDARD_EDGE_PX)


# Anthropic's own limit, and where its behaviour changes: past twenty images a
# request is downscaled to a stricter per-image ceiling, so this is a boundary
# in the API rather than a matter of taste.
MAX_IMAGES = 20
# Cloudflare does not store a log larger than 10 MB, and AI Gateway analytics
# reads the log — so a request past that ceiling is spend that reaches no
# cockpit row, which is the whole reason this node routes through the gateway.
# The margin under 10 MB is for what JSON encoding adds on top of the bytes we
# count. In practice this binds long before MAX_IMAGES does — roughly two
# high-resolution images, or eight standard-tier ones.
MAX_REQUEST_BYTES = 8_000_000


def image_blocks(pil_images, model: str) -> list:
    """Each reference image as a base64 PNG content block, in the order given.

    PNG rather than JPEG, as elsewhere in this pack. JPEG would buy five to ten
    times the headroom below and is the obvious lever if this proves too tight,
    but that is a quality trade for reference images where artifacts may matter
    — not a default to arrive at by accident.

    Over budget this raises rather than dropping images to fit. An answer drawn
    from three of eight references is a wrong answer that looks right, and a
    wrong answer that looks right is what this pack exists to refuse."""
    images = list(pil_images)
    # Before any encoding, so a graph wired to twenty-five references fails at
    # once rather than after twenty-five PNG compressions.
    if len(images) > MAX_IMAGES:
        raise ValueError(
            f"{len(images)} reference images were given and Claude takes at "
            f"most {MAX_IMAGES}. Past that Anthropic downscales every image to "
            f"a stricter ceiling, so the extras cost fidelity rather than "
            f"adding any.")
    edge = max_image_edge(model)
    blocks = [{"type": "image",
               "source": {"type": "base64", "media_type": "image/png",
                          "data": encode_png(im, edge)}}
              for im in images]
    # Measured on what will actually cross the wire. A check written against
    # width and height cannot tell a flat colour from noise at the same
    # dimensions, and those differ by orders of magnitude once encoded.
    size = sum(len(block["source"]["data"]) for block in blocks)
    if size > MAX_REQUEST_BYTES:
        raise ValueError(
            f"The reference images encode to {size} bytes, over the "
            f"{MAX_REQUEST_BYTES} this node sends. Cloudflare stores no log "
            f"above 10 MB and AI Gateway analytics reads the log, so a request "
            f"this size would run without its spend ever being attributed to "
            f"the studio. Send fewer references, or smaller ones.")
    return blocks


def encode_png(image, edge: int) -> str:
    """One image as base64 PNG, no larger than `edge` on its long side.

    Never enlarged — that is `thumbnail`'s own guarantee, not the guard's; the
    guard only skips a copy for an image already small enough. Enlarging a
    small reference would invent detail the model then reads as real, and be
    charged for by the ⌈w/28⌉×⌈h/28⌉ tile count for the privilege."""
    if max(image.size) > edge:
        image = image.copy()
        image.thumbnail((edge, edge), Image.LANCZOS)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def require_prompt(prompt: str) -> str:
    """`prompt`, once it is something Claude can answer.

    Its own function so the check can run before the work that would be wasted:
    walking the key ladder and encoding twenty PNGs, only to raise about the
    prompt, costs a headless operator two round-trips to learn one thing."""
    if not (prompt or "").strip():
        raise ValueError("prompt is required — Claude has nothing to answer "
                         "from an empty one")
    return prompt


def request_body(prompt: str, image_blocks: list, model: str, max_tokens: int,
                 system_prompt: str, thinking: dict | None = None,
                 output_config: dict | None = None,
                 temperature=None) -> dict:
    """One Messages-API request.

    `thinking`, `output_config` and `temperature` are what the model will
    actually accept, which is a per-model question — `thinking_config` and
    `temperature_for` answer it, and each may legitimately be None. This node
    once omitted all three unconditionally, because temperature is removed on
    Opus 5, Fable 5 and Opus 4.8/4.7, and `{"type": "disabled"}` is itself a
    400 on Fable 5, so omission was the only setting that worked across ONE
    flat model list. Per-model inputs are what retired that constraint; none of
    those facts changed."""
    blocks = list(labelled(image_blocks))
    blocks.append({"type": "text", "text": prompt})
    body = {
        "model": model,
        # Required by the API, and a budget rather than a target: on the models
        # that think by default it caps thinking and answer together, which is
        # why a small value truncates a real answer rather than shortening it.
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": blocks}],
    }
    if (system_prompt or "").strip():
        # Its own top-level key. Anthropic has no system role, and a message
        # claiming one is a 400.
        body["system"] = system_prompt
    # Each omitted rather than sent as null: the API reads an explicit null as
    # a value and rejects it on the models that removed the field.
    if thinking is not None:
        body["thinking"] = thinking
    if output_config is not None:
        body["output_config"] = output_config
    if temperature is not None:
        body["temperature"] = temperature
    # Again, on the whole request rather than the images alone. `prompt` and
    # `system_prompt` are unbounded multiline widgets riding in the same log,
    # and a pasted style guide or JSON schema — exactly what a structured-
    # extraction step invites — can carry a batch that passed image_blocks
    # over the ceiling on its own.
    size = len(json.dumps(body))
    if size > MAX_REQUEST_BYTES:
        raise ValueError(
            f"The whole request encodes to {size} bytes, over the "
            f"{MAX_REQUEST_BYTES} this node sends — the images fit, so it is "
            f"the prompt or the system prompt that does not. Cloudflare stores "
            f"no log above 10 MB and AI Gateway analytics reads the log, so a "
            f"request this size would run without its spend ever being "
            f"attributed to the studio.")
    return body


def labelled(image_blocks: list):
    """The image blocks, each preceded by its number when there are several.

    A lone image needs no label, and one image called "Image 1:" is noise the
    model reads past. The labels match `llm_api.call_claude_api`, so the two
    Claude paths in this pack send the same shape."""
    blocks = list(image_blocks)
    for index, block in enumerate(blocks, start=1):
        if len(blocks) > 1:
            yield {"type": "text", "text": f"Image {index}:"}
        yield block


# Any of these at the top level means a Messages endpoint answered, however
# little it had to say. Their absence is what distinguishes a wrong URL from
# an empty answer, which have opposite fixes.
MESSAGES_KEYS = {"content", "stop_reason", "usage", "model", "id"}


def parse_response(payload) -> str:
    """Claude's answer, or a raise that says why there is not one.

    Order matters. A refusal is recognised before the content is read, because
    a refusal can arrive with partial text attached and reading content first
    hands that back as though it were an answer. Every other outcome that is
    not a complete answer raises too: a graph handed an empty string fails
    downstream where the cause is out of view, and in an order sandbox the
    raise is the only artifact a human reads."""
    if not isinstance(payload, dict):
        raise ValueError(
            f"Claude replied with a {type(payload).__name__} rather than an "
            f"object. Nothing at {MESSAGES_PATH} answers that way, so the "
            f"reply came from somewhere else.")
    if not MESSAGES_KEYS & set(payload):
        raise ValueError(
            f"The reply carries {sorted(payload)} rather than anything a "
            f"{MESSAGES_PATH} reply carries, so this is not Claude answering. "
            f"Check the gateway base and the provider slug before the prompt.")

    stop = str(payload.get("stop_reason") or "")
    # Populated only on a refusal, and null the rest of the time — so it is
    # read through a guard rather than reached into.
    details = payload.get("stop_details")
    details = details if isinstance(details, dict) else {}
    explanation = str(details.get("explanation") or "").strip()
    said = f" Claude said: {explanation}" if explanation else ""

    if stop == "refusal":
        category = str(details.get("category") or "").strip()
        about = f" ({category})" if category else ""
        raise ValueError(
            f"Claude refused this request{about}.{said} A refusal is the "
            f"model declining the prompt itself, so retrying it unchanged "
            f"will refuse again.")
    if stop == "max_tokens":
        raise ValueError(
            f"Claude's answer was cut off at the max_tokens budget, so what "
            f"came back is a fragment rather than an answer. Raise max_tokens "
            f"— on the models that think by default it caps the reasoning and "
            f"the answer together, so the reasoning can consume all of it.")
    if stop == "model_context_window_exceeded":
        raise ValueError(
            "Claude stopped with model_context_window_exceeded: the request "
            "did not fit in the model's context window, which is the inputs "
            "being too large rather than the answer being too long "
            "— send a shorter prompt or fewer reference images. Raising "
            "max_tokens makes this worse, not better.")

    answer = "".join(
        block["text"] for block in payload.get("content") or []
        if isinstance(block, dict) and block.get("type") == "text"
        and block.get("text"))
    if not answer:
        raise ValueError(
            f"Claude returned no text at all (stop_reason {stop or 'absent'})."
            f"{said} An empty answer is handed on as a placeholder by some "
            f"nodes; this one raises, because a placeholder reaching a client "
            f"looks like an answer.")
    return answer


# Bounds the whole generation, not an idle socket. Nothing arrives until the
# answer is complete on a non-streamed call, so requests' read timeout is
# inter-byte only in name — and the gateway's own timeout is time-to-first-byte,
# which means it will not cut a slow answer short on our behalf either. This
# number is the only thing that will. It has to cover the widget's own ceiling
# of 64000 tokens with thinking sharing the budget, so it is longer than the
# 500s `llm_api.call_claude_api` gives the same provider at a smaller one, and
# much longer than the image node's 300s, where the output is a single picture.
# Too short is the worse error: a generation that finished and was billed comes
# back to a headless operator as a transport failure.
REQUEST_TIMEOUT_S = 600

# How an Anthropic key is presented when no gateway is configured. The header
# name and what a rejection calls the key are both Anthropic's business, so
# they live here rather than in the transport every provider shares.
DIRECT_ARM = ai_gateway.DirectArm(
    ANTHROPIC_API_BASE, "The Anthropic API key",
    lambda key: {"x-api-key": key})


def resolve_transport(environ, interactive_key):
    """This node's call, routed by the rules every provider shares.

    anthropic-version rides both arms. ComfyUI's own Claude node omits it
    because the comfy.org proxy adds it server-side; through the gateway
    nothing does, and Anthropic rejects a request without it."""
    return ai_gateway.resolve_transport(
        environ, PROVIDER, MESSAGES_PATH, interactive_key, DIRECT_ARM,
        {"anthropic-version": ANTHROPIC_VERSION})
