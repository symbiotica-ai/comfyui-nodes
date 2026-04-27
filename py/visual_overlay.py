# ABOUTME: Video infographics overlay node using Claude LLM and Remotion for rendering
# ABOUTME: Two-pass LLM pipeline with face detection for context-aware, creative visual cues

import os
import subprocess
import tempfile
import json
import shutil
import time
import re
import base64
import io

import requests
import folder_paths

from .llm_chat import claude_models

from ._bins import FFMPEG, FFPROBE, NODE_BIN, NPX_BIN, NPM_BIN

REMOTION_DIR = os.path.join(os.path.dirname(__file__), "..", "remotion")
REMOTION_BUNDLE = os.path.join(REMOTION_DIR, "bundle")

_node_dir = os.path.dirname(NODE_BIN)
_env = os.environ.copy()
_env["PATH"] = _node_dir + ":" + _env.get("PATH", "")

_deps_checked = False

NUM_SAMPLE_FRAMES = 12

# Try to load OpenCV for face detection
try:
    import cv2
    import numpy as np
    _face_cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    _face_cascade = cv2.CascadeClassifier(_face_cascade_path)
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

ALL_STYLES = [
    "Auto", "cinematic", "bold", "broadcast", "minimal",
    "glass", "neon", "editorial", "sports", "social", "tech",
]

VALID_CUE_TYPES = {
    "icon", "stat", "label", "list",
    "progress", "comparison", "callout", "counter",
    "badge", "quote", "steps", "chart",
}

DENSITY_GUIDANCE = {
    "Low": "Place 1 cue every 10-15 seconds. Only highlight key moments.",
    "Medium": "Place 1 cue every 4-8 seconds. Keep the screen visually active.",
    "High": "Place 1 cue every 2-4 seconds. Almost always have something on screen.",
}

STYLE_GUIDANCE = {
    "cinematic": "Use the cinematic style — frosted dark glass cards with accent bars and slide-reveal entrances. Feel: premium documentary, Apple keynote. Best for serious insights and key moments.",
    "bold": "Use the bold style — gradient-filled cards with bouncy entrances. Feel: energetic, celebratory. Best for achievements, hype moments, exciting numbers.",
    "broadcast": "Use the broadcast style — horizontal bars with wipe entrances. Feel: news ticker, ESPN. Best for data, metrics, business stats.",
    "minimal": "Use the minimal style — text-only with underline accents. Feel: elegant, understated. Best for definitions, terms, subtle emphasis.",
    "glass": "Use the glass style — Apple Vision Pro frosted panels with blur-reveal entrance and shimmer. Feel: futuristic, premium. Best for tech products, clean presentations.",
    "neon": "Use the neon style — dark cards with glowing colored borders that flicker on. Feel: cyberpunk, gaming. Best for gaming content, nightlife, tech/hacker topics.",
    "editorial": "Use the editorial style — clean white cards with clip-reveal entrance. Feel: NYT, magazine. Best for journalism, education, thoughtful content.",
    "sports": "Use the sports style — aggressive skewed bars that slam in. Feel: ESPN, sports broadcast. Best for sports, competitions, intense moments.",
    "social": "Use the social style — colorful pill-shaped cards that pop and wiggle. Feel: YouTube/TikTok stickers. Best for casual, fun, social media content.",
    "tech": "Use the tech style — dark terminal-like cards with typewriter text and scan-line. Feel: hacker HUD, terminal. Best for coding, tech tutorials, developer content.",
}

# --- Pass 1: Content analysis prompt (text-only, no images) ---

ANALYSIS_PROMPT = """You are a video content analyst. Given a transcript, identify the narrative structure and key moments for infographic overlay placement.

Analyze the transcript and output a JSON object with:

1. "narrative_arc": array of segments, each with:
   - "startTime": number (seconds)
   - "endTime": number (seconds)
   - "phase": one of "setup", "build", "peak", "rest", "conclusion"
   - "emotion": one of "neutral", "exciting", "serious", "funny", "dramatic", "inspirational"
   - "summary": 1 sentence describing what happens in this segment

2. "key_moments": array of the most important moments, each with:
   - "time": number (seconds)
   - "type": one of "number_mention", "list_enumeration", "key_insight", "comparison", "quote", "question", "surprise", "definition", "process_steps"
   - "content": what was said (brief)
   - "importance": 1-10 (10 = most important)
   - "suggested_cue_type": best cue type for this moment

3. "overall_tone": the dominant mood/genre of the content (e.g. "educational", "motivational", "technical", "entertainment", "news")

4. "visual_suggestions": 2-3 creative ideas for visual storytelling that go beyond literal representation. Think metaphorically — what unexpected visual could reinforce the message?

Respond with ONLY the JSON object, no markdown fences."""

# --- Pass 2: Cue generation prompt (with images + analysis context) ---

SYSTEM_PROMPT = """You are a broadcast-quality video infographics designer creating overlays for a {width}x{height} video. Given a transcript, sample frames, and a content analysis, you generate visual cue overlays.

You can SEE the video frames. Use them along with the face/person detection data below to decide WHERE to place each cue.

## VIDEO CONTEXT

Canvas: {width}x{height} pixels
{face_regions}

## CUE TYPE CATALOG

You have 12 cue types. Use variety — don't repeat the same type 3 times in a row.

**CONTENT TYPES:**
- "icon" — A concept card with icon + title. Use for ideas, topics, abstract concepts.
- "stat" — Icon + animated counter + title. Use when speaker mentions specific numbers/metrics. Requires "value" field (e.g. "+42%", "$1.2M", "3x").
- "label" — Simple emphasis card with icon + title. Use for key terms, definitions, names.
- "list" — Icon + title + bullet items. Use when speaker enumerates items/steps. Requires "items" array (2-4 strings).

**EXPANDED TYPES:**
- "progress" — Horizontal fill bar with % label. Use for percentages, completion rates, scores. Requires "value" field with percentage.
- "comparison" — Side-by-side A vs B with bars. Use when comparing two things. Requires "leftLabel", "leftValue" (number), "rightLabel", "rightValue" (number).
- "callout" — Larger card with description paragraph. Use for important explanations that need more text. Requires "description" field.
- "counter" — Big standalone number (prominent display). Use for dramatic number reveals. Requires "value" field. Optional "prefix" and "suffix" fields.
- "badge" — Small compact pill tag. Use for quick labels, tags, categories. Lightweight — good for multiple simultaneous.
- "quote" — Pull-quote with quotation mark + attribution. Use for memorable quotes. Requires "text" field, optional "attribution".
- "steps" — Numbered vertical timeline. Use for processes, sequences. Requires "items" array. Optional "activeStep" (number, how many steps are highlighted).
- "chart" — Bar chart or donut chart. Use for data visualization. Requires "data" array of {{label, value}} objects. Set "chartType" to "bar" or "donut". Optional "value" for donut center label.

## OUTPUT FORMAT

JSON array of cue objects. Each cue has:
- "type": one of the 12 types above
- "position": "left" or "right"
- "startTime": number (seconds)
- "endTime": number (seconds; duration 3-6 seconds, up to 8 for complex types like steps/chart)
- "icon": lucide icon name in kebab-case (e.g. "trending-up", "users", "zap", "target", "brain", "sparkles", "flame", "compass", "layers", "eye")
- "title": short label (1-5 words)
- "x": horizontal position 0-100 (5-15 for left, 85-95 for right). MUST avoid face regions listed above.
- "y": vertical position 0-100 (20-35 upper, 45-55 center, 65-80 lower). MUST avoid face regions listed above.
- "scale": size multiplier (0.7-1.1)
- "style": one of "cinematic", "bold", "broadcast", "minimal", "glass", "neon", "editorial", "sports", "social", "tech"
- "color": hex accent color
- Plus type-specific fields listed above.

## STYLE SELECTION

{style_guidance}

Match style to emotional weight:
- Heavy/important moments → cinematic, editorial, glass
- Exciting/hype moments → bold, sports, neon
- Data/metrics → broadcast, tech
- Light/fun moments → social, badge
- Subtle emphasis → minimal

## CREATIVE DIRECTION

Don't just label what the speaker says — enhance and elevate it:
- Use METAPHORICAL icons: "brain" for thinking differently (not just "lightbulb"), "rocket" for rapid growth, "compass" for finding direction, "layers" for complexity
- Create VISUAL STORYTELLING: if the speaker says "3 steps", show a steps timeline. If they compare things, show a comparison card. If they mention a percentage, show a progress bar.
- Make titles PUNCHY and CREATIVE — not just repeating the speaker's words. Reframe, condense, make it stick.
- Use color to create emotional arcs — warm colors building to cool colors during transitions
- SURPRISE the viewer — unexpected icons and framing make content memorable

## EMOTIONAL ARC & RHYTHM

The content analysis below maps the narrative structure. Use it:
- During "setup" phases: use lighter cues (icons, labels, badges) to ease in
- During "build" phases: increase density with stats, lists, progress bars
- During "peak" moments: deploy heavy cues (counters, callouts, charts, comparisons)
- During "rest" phases: pull back — fewer cues, lighter types, or silence
- During "conclusion": bookend with strong final cue

**Visual rhythm rules:**
- Never use 3 of the same cue type in a row
- Alternate heavy (callout, chart, comparison, steps) and light (icon, label, badge) cues
- After a complex cue, give 2-3 seconds of empty screen before the next
- Vary left/right placement — don't stack 3+ cues on the same side consecutively
- Match cue duration to importance: quick badges (2-3s) for minor points, longer callouts (5-7s) for key insights

## COLOR GUIDELINES

- Warm (#FF6B35, #F7C948) → energy, excitement, achievements
- Cool (#00D4FF, #4361EE) → tech, data, professional
- Green (#22C55E) → growth, success, positive
- Red (#FF3366) → warnings, urgency, important
- Purple (#A855F7) → creative, unique, innovative
- Keep colors consistent within related cues, but vary across the video arc

## PLACEMENT RULES

- {density}
- AVOID face regions listed in VIDEO CONTEXT — never place cues over detected faces
- LOOK at the video frames for additional context about the scene layout
- Don't overlap cues on the same side at the same time
- Prefer placing cues on the opposite side of the frame from where people/faces are

Respond with ONLY the JSON array, no markdown fences, no explanation."""

# --- Few-shot example for creative output ---

FEW_SHOT_EXAMPLE = """Here's an example of CREATIVE cue design (don't copy this literally — use it as inspiration for quality and variety):

For a video about "Why morning routines matter":
[
  {"type":"badge","position":"left","startTime":1.5,"endTime":4,"icon":"sunrise","title":"Morning Science","x":8,"y":25,"scale":0.8,"style":"glass","color":"#F7C948"},
  {"type":"stat","position":"right","startTime":5,"endTime":9,"icon":"brain","title":"Peak Cortisol Window","value":"6-8am","x":88,"y":40,"scale":1.0,"style":"cinematic","color":"#4361EE"},
  {"type":"comparison","position":"left","startTime":11,"endTime":17,"icon":"bar-chart","title":"Productivity Impact","leftLabel":"With routine","leftValue":85,"rightLabel":"Without","rightValue":42,"x":10,"y":50,"scale":0.9,"style":"broadcast","color":"#22C55E"},
  {"type":"steps","position":"right","startTime":19,"endTime":26,"icon":"compass","title":"The Power Stack","items":["Move your body (5 min)","Cold exposure","Deep work block"],"activeStep":3,"x":87,"y":45,"scale":0.9,"style":"editorial","color":"#A855F7"},
  {"type":"counter","position":"left","startTime":28,"endTime":32,"icon":"flame","title":"Habit Streak Effect","value":"66","suffix":" days","x":10,"y":55,"scale":1.1,"style":"bold","color":"#FF6B35"},
  {"type":"quote","position":"right","startTime":34,"endTime":39,"icon":"sparkles","title":"","text":"You don't rise to the level of your goals — you fall to the level of your systems.","attribution":"James Clear","x":88,"y":45,"scale":0.9,"style":"glass","color":"#00D4FF"}
]

Notice: varied types, creative titles (not just repeating the speaker), metaphorical icons, emotional color arc, alternating sides, mix of heavy and light cues."""


def _detect_faces_in_frame(frame_path, video_width, video_height):
    """Detect faces in a frame image, return bounding boxes as percentages of video dimensions."""
    if not _HAS_CV2:
        return []

    img = cv2.imread(frame_path)
    if img is None:
        return []

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    img_h, img_w = gray.shape[:2]

    faces = _face_cascade.detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
    )

    regions = []
    for (x, y, w, h) in faces:
        # Convert from image coordinates to percentage of video
        regions.append({
            "x_pct": round((x / img_w) * 100, 1),
            "y_pct": round((y / img_h) * 100, 1),
            "w_pct": round((w / img_w) * 100, 1),
            "h_pct": round((h / img_h) * 100, 1),
        })

    return regions


def _aggregate_face_regions(all_face_data):
    """Merge face detections across frames into stable no-go zones."""
    if not all_face_data:
        return []

    # Collect all face regions
    all_regions = []
    for frame_faces in all_face_data:
        all_regions.extend(frame_faces)

    if not all_regions:
        return []

    # Cluster nearby detections (faces that appear in similar positions across frames)
    merged = []
    used = [False] * len(all_regions)

    for i, r in enumerate(all_regions):
        if used[i]:
            continue
        cluster = [r]
        used[i] = True

        for j in range(i + 1, len(all_regions)):
            if used[j]:
                continue
            # Same face if centers are within 15% of each other
            cx_i = r["x_pct"] + r["w_pct"] / 2
            cy_i = r["y_pct"] + r["h_pct"] / 2
            cx_j = all_regions[j]["x_pct"] + all_regions[j]["w_pct"] / 2
            cy_j = all_regions[j]["y_pct"] + all_regions[j]["h_pct"] / 2

            if abs(cx_i - cx_j) < 15 and abs(cy_i - cy_j) < 15:
                cluster.append(all_regions[j])
                used[j] = True

        # Average the cluster with some padding
        avg_x = sum(f["x_pct"] for f in cluster) / len(cluster)
        avg_y = sum(f["y_pct"] for f in cluster) / len(cluster)
        avg_w = max(f["w_pct"] for f in cluster)
        avg_h = max(f["h_pct"] for f in cluster)

        # Add 5% padding around face region
        merged.append({
            "x_pct": round(max(0, avg_x - 5), 1),
            "y_pct": round(max(0, avg_y - 5), 1),
            "w_pct": round(min(100, avg_w + 10), 1),
            "h_pct": round(min(100, avg_h + 10), 1),
            "frequency": len(cluster),
        })

    # Only keep faces detected in at least 2 frames (persistent faces)
    stable = [r for r in merged if r["frequency"] >= 2]
    # If nothing is stable, keep the most frequent single detection
    if not stable and merged:
        stable = [max(merged, key=lambda r: r["frequency"])]

    return stable


def _format_face_regions(face_regions):
    """Format face regions into a human-readable string for the LLM prompt."""
    if not face_regions:
        return "No faces/people detected — you can place cues anywhere."

    lines = ["FACE/PERSON REGIONS (avoid placing cues here):"]
    for i, r in enumerate(face_regions):
        cx = round(r["x_pct"] + r["w_pct"] / 2, 1)
        cy = round(r["y_pct"] + r["h_pct"] / 2, 1)
        lines.append(
            f"  Face {i+1}: center at ({cx}%, {cy}%), "
            f"spans x:{r['x_pct']:.0f}-{r['x_pct']+r['w_pct']:.0f}%, "
            f"y:{r['y_pct']:.0f}-{r['y_pct']+r['h_pct']:.0f}%"
        )
    lines.append("Place cues AWAY from these regions. Use the opposite side of the frame.")
    return "\n".join(lines)


def _validate_cue(cue):
    """Validate and fix a single cue object. Returns corrected cue or None if unusable."""
    if not isinstance(cue, dict):
        return None

    if "startTime" not in cue or "endTime" not in cue:
        return None
    if not isinstance(cue.get("startTime"), (int, float)):
        return None
    if not isinstance(cue.get("endTime"), (int, float)):
        return None

    if cue.get("type") not in VALID_CUE_TYPES:
        cue["type"] = "icon"

    cue.setdefault("position", "right")
    cue.setdefault("icon", "info")
    cue.setdefault("title", "")

    if "x" in cue:
        cue["x"] = max(0, min(100, cue["x"]))
    if "y" in cue:
        cue["y"] = max(0, min(100, cue["y"]))
    if "scale" in cue:
        cue["scale"] = max(0.4, min(1.5, cue["scale"]))

    valid_styles = {
        "cinematic", "bold", "broadcast", "minimal",
        "glass", "neon", "editorial", "sports", "social", "tech",
    }
    if cue.get("style") not in valid_styles:
        cue.pop("style", None)

    return cue


def _validate_cues(raw_cues):
    """Validate and fix an array of cues. Drops invalid entries, fixes recoverable ones."""
    if not isinstance(raw_cues, list):
        return []

    validated = []
    for cue in raw_cues:
        fixed = _validate_cue(cue)
        if fixed is not None:
            validated.append(fixed)

    return validated


class NSVisualOverlay:
    """
    Analyzes video transcript and frames with Claude to generate contextual
    infographic overlays with vision-aware placement and face detection.
    Two-pass LLM pipeline: content analysis → creative cue generation.
    Requires a TRANSCRIPT from NS Whisper Transcribe.
    """

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "video": ("VIDEO",),
                "transcript": ("TRANSCRIPT",),
            },
            "optional": {
                "api_key": ("STRING", {"multiline": False, "default": ""}),
                "model": (claude_models, {"default": "claude-sonnet-4-5"}),
                "density": (["Low", "Medium", "High"], {"default": "Medium"}),
                "style": (ALL_STYLES, {"default": "Auto"}),
            }
        }

    RETURN_TYPES = ("VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "execute"
    CATEGORY = "neuralsins/Video"

    def _ensure_deps(self):
        """Check Node.js is available and Remotion dependencies are installed."""
        global _deps_checked
        if _deps_checked:
            return

        if not os.path.isfile(NODE_BIN):
            raise RuntimeError(
                "Node.js not found. Install it from https://nodejs.org/ "
                "and restart ComfyUI."
            )

        node_modules = os.path.join(REMOTION_DIR, "node_modules")
        if not os.path.isdir(node_modules):
            print("[NSVisualOverlay] Installing Remotion dependencies (first run)...")
            result = subprocess.run(
                [NPM_BIN, "install"],
                cwd=REMOTION_DIR,
                capture_output=True, text=True,
                env=_env,
            )
            if result.returncode != 0:
                raise RuntimeError(
                    f"npm install failed in remotion/:\n{result.stderr[-1000:]}"
                )
            print("[NSVisualOverlay] Dependencies installed.")

        _deps_checked = True

    def _get_video_info(self, path):
        """Get fps, width, height, and duration from a video file."""
        result = subprocess.run(
            [FFPROBE, "-v", "error",
             "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate",
             "-show_entries", "format=duration",
             "-of", "json", path],
            capture_output=True, text=True
        )
        data = json.loads(result.stdout)
        duration = float(data["format"]["duration"])
        stream = data["streams"][0]
        width = int(stream["width"])
        height = int(stream["height"])
        num, den = stream["r_frame_rate"].split("/")
        fps = float(num) / float(den)
        return fps, width, height, duration

    def _resolve_api_key(self, api_key):
        """Resolve API key from input, then env vars."""
        if api_key and api_key.strip():
            return api_key.strip()
        key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
        if not key:
            raise RuntimeError(
                "Anthropic API key required. Provide it in the node input "
                "or set ANTHROPIC_API_KEY environment variable."
            )
        return key

    def _extract_frames(self, video_path, duration, width, height, num_frames=NUM_SAMPLE_FRAMES):
        """Extract evenly spaced frames with face detection."""
        frames = []
        all_face_data = []
        temp_dir = tempfile.mkdtemp()
        try:
            interval = duration / (num_frames + 1)
            timestamps = [interval * (i + 1) for i in range(num_frames)]

            for i, ts in enumerate(timestamps):
                frame_path = os.path.join(temp_dir, f"frame_{i:03d}.jpg")
                cmd = [
                    FFMPEG, "-y",
                    "-ss", str(ts),
                    "-i", video_path,
                    "-vframes", "1",
                    "-q:v", "8",
                    "-vf", "scale=640:-2",
                    frame_path
                ]
                subprocess.run(cmd, capture_output=True, text=True)
                if os.path.isfile(frame_path):
                    with open(frame_path, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode("utf-8")
                    frames.append({"timestamp": round(ts, 2), "base64": b64})

                    # Run face detection on this frame
                    face_regions = _detect_faces_in_frame(frame_path, width, height)
                    all_face_data.append(face_regions)

            # Aggregate face detections across all frames
            face_regions = _aggregate_face_regions(all_face_data)

            face_count = sum(len(f) for f in all_face_data)
            print(f"[NSVisualOverlay] Extracted {len(frames)} frames, {face_count} face detections -> {len(face_regions)} stable regions")
            return frames, face_regions
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _call_claude(self, api_key, model, system, prompt, frames=None, thinking_budget=0):
        """Call Claude API with optional images and extended thinking."""
        content = []

        if frames:
            for frame in frames:
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": frame["base64"],
                    },
                })
                content.append({
                    "type": "text",
                    "text": f"[Frame at {frame['timestamp']}s]",
                })

        content.append({"type": "text", "text": prompt})

        data = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": 16384 if thinking_budget > 0 else 8192,
            "temperature": 1 if thinking_budget > 0 else 0.5,
        }

        if thinking_budget > 0:
            data["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking_budget,
            }

        if system and system.strip():
            data["system"] = system

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        response = requests.post(
            "https://api.anthropic.com/v1/messages",
            json=data, headers=headers, timeout=500,
        )

        if response.status_code != 200:
            error_msg = f"API request failed with status {response.status_code}"
            try:
                error_data = response.json()
                if error_data.get("error"):
                    error_msg = error_data["error"].get("message", error_msg)
            except Exception:
                error_msg = f"{error_msg}: {response.text}"
            raise RuntimeError(error_msg)

        response_data = response.json()
        if response_data.get("error"):
            raise RuntimeError(response_data["error"].get("message", "Unknown error"))

        # Extract text from response (skip thinking blocks)
        for block in response_data["content"]:
            if block["type"] == "text":
                return block["text"]

        return ""

    def _build_style_guidance(self, style):
        """Build the style guidance section for the system prompt."""
        if style == "Auto":
            return (
                "Choose the best style for each cue based on content and emotional weight. "
                "Mix styles for visual variety — don't use the same style for every cue."
            )
        return STYLE_GUIDANCE.get(style, "")

    def _pass1_analyze_content(self, api_key, model, words):
        """Pass 1: Analyze transcript for narrative structure, key moments, and creative opportunities."""
        transcript_text = " ".join(w["word"] for w in words)
        transcript_json = json.dumps(
            [{"word": w["word"], "start": w["start"], "end": w["end"]} for w in words],
            indent=None
        )

        prompt = (
            f"Transcript text: {transcript_text}\n\n"
            f"Word-level timestamps:\n{transcript_json}"
        )

        print(f"[NSVisualOverlay] Pass 1: Analyzing content structure...")
        response = self._call_claude(
            api_key, model, ANALYSIS_PROMPT, prompt,
            thinking_budget=4096,
        )

        # Parse the analysis JSON
        text = response.strip()
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()

        try:
            analysis = json.loads(text)
            print(f"[NSVisualOverlay] Pass 1 complete: {len(analysis.get('key_moments', []))} key moments, tone: {analysis.get('overall_tone', 'unknown')}")
            return analysis
        except json.JSONDecodeError as e:
            print(f"[NSVisualOverlay] Pass 1 JSON error: {e}, proceeding without analysis")
            return None

    def _pass2_generate_cues(self, api_key, model, words, density, style,
                              video_path, duration, width, height,
                              analysis, frames, face_regions):
        """Pass 2: Generate visual cues using analysis context, frames, and face detection."""
        transcript_json = json.dumps(
            [{"word": w["word"], "start": w["start"], "end": w["end"]} for w in words],
            indent=None
        )

        style_guidance = self._build_style_guidance(style)
        face_text = _format_face_regions(face_regions)

        system = SYSTEM_PROMPT.format(
            width=width,
            height=height,
            face_regions=face_text,
            style_guidance=style_guidance,
            density=DENSITY_GUIDANCE[density],
        )

        # Build the user prompt with analysis context and few-shot example
        prompt_parts = [FEW_SHOT_EXAMPLE, ""]

        if analysis:
            prompt_parts.append("## CONTENT ANALYSIS (from Pass 1)\n")
            prompt_parts.append(json.dumps(analysis, indent=2))
            prompt_parts.append("")

        prompt_parts.append(f"## TRANSCRIPT\n\n{transcript_json}")
        prompt_parts.append(
            "\nNow generate the visual cues JSON array. Be creative, use variety, "
            "and follow the emotional arc from the analysis. Think about visual "
            "storytelling — don't just label, ENHANCE."
        )

        prompt = "\n".join(prompt_parts)

        print(f"[NSVisualOverlay] Pass 2: Generating cues with {len(frames)} frames (density: {density}, style: {style})...")
        response = self._call_claude(
            api_key, model, system, prompt,
            frames=frames,
            thinking_budget=8192,
        )

        # Parse JSON from response
        text = response.strip()
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()

        try:
            raw_cues = json.loads(text)
        except json.JSONDecodeError as e:
            print(f"[NSVisualOverlay] Pass 2 JSON error: {e}")
            print(f"[NSVisualOverlay] Raw response: {text[:500]}")
            return []

        cues = _validate_cues(raw_cues)
        print(f"[NSVisualOverlay] Generated {len(cues)} visual cues ({len(raw_cues) - len(cues)} dropped)")
        return cues

    def _get_concurrency(self):
        """Detect available CPU cores, respecting cgroup limits on Linux pods."""
        try:
            n_cores = len(os.sched_getaffinity(0))
        except AttributeError:
            n_cores = os.cpu_count() or 1
        return max(1, min(n_cores // 2, 6))

    @staticmethod
    def _kill_stale_chrome():
        """Kill leftover Chrome processes from previous renders."""
        import platform
        if platform.system() != "Linux":
            return
        subprocess.run(["pkill", "-9", "-f", "headless.*remotion"],
                       capture_output=True, text=True)
        time.sleep(1)

    def _render_overlay(self, props, overlay_path):
        """Call Remotion CLI to render the transparent visual overlay."""
        props_path = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        )
        json.dump(props, props_path)
        props_path.close()

        try:
            concurrency = self._get_concurrency()
            entry = REMOTION_BUNDLE if os.path.isdir(REMOTION_BUNDLE) else "src/index.ts"
            cmd = [
                NPX_BIN, "remotion", "render",
                entry, "VisualOverlay",
                f"--props={props_path.name}",
                "--codec=vp9",
                "--image-format=png",
                "--pixel-format=yuva420p",
                f"--concurrency={concurrency}",
                f"--output={overlay_path}",
                "--log=error",
            ]
            n_frames = props['durationInFrames']
            render_timeout = max(600, n_frames * 3)
            print(f"[NSVisualOverlay] Rendering overlay ({n_frames} frames, "
                  f"concurrency={concurrency}, timeout={render_timeout}s)...")

            for attempt in range(3):
                result = subprocess.run(
                    cmd, cwd=REMOTION_DIR,
                    capture_output=True, text=True,
                    timeout=render_timeout,
                    env=_env,
                )
                if result.returncode == 0:
                    break
                if attempt < 2 and "Timed out" in result.stderr:
                    print(f"[NSVisualOverlay] Chrome launch failed (attempt {attempt + 1}), cleaning up...")
                    self._kill_stale_chrome()
                    continue
                raise RuntimeError(
                    f"Remotion render failed:\n{result.stderr[-1500:]}"
                )
            print("[NSVisualOverlay] Overlay rendered.")
        finally:
            try:
                os.unlink(props_path.name)
            except OSError:
                pass

    def _composite(self, original_path, overlay_path, output_path):
        """Composite the transparent overlay onto the original video with FFmpeg."""
        cmd = [
            FFMPEG, "-y",
            "-i", original_path,
            "-c:v", "libvpx-vp9", "-i", overlay_path,
            "-filter_complex", "[0:v][1:v]overlay=format=auto[outv]",
            "-map", "[outv]",
            "-map", "0:a?",
            "-c:v", "libx264", "-preset", "fast",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            output_path
        ]

        print("[NSVisualOverlay] Compositing overlay onto video...")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"FFmpeg composite error:\n{result.stderr[-1000:]}"
            )

    def _process_file(self, input_path, output_path, settings):
        """Apply visual overlay to a video file on disk. Used by execute() and NSVideoConcatMulti."""
        self._ensure_deps()

        cues = settings.get("cues", [])
        if not cues:
            print("[NSVisualOverlay] No cues in settings, copying input")
            shutil.copy2(input_path, output_path)
            return

        temp_files = []
        try:
            fps, width, height, duration = self._get_video_info(input_path)
            duration_in_frames = int(round(duration * fps))

            props = {
                "cues": cues,
                "width": width,
                "height": height,
                "fps": round(fps),
                "durationInFrames": duration_in_frames,
            }

            if settings.get("defaultStyle"):
                props["defaultStyle"] = settings["defaultStyle"]

            overlay_path = tempfile.NamedTemporaryFile(
                suffix=".webm", delete=False
            ).name
            temp_files.append(overlay_path)

            self._render_overlay(props, overlay_path)
            self._composite(input_path, overlay_path, output_path)

        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass

    def execute(self, video, transcript, api_key="", model="claude-sonnet-4-5", density="Medium", style="Auto"):
        from comfy_api.latest import InputImpl

        if isinstance(transcript, str):
            transcript = json.loads(transcript)
        words = transcript.get("words", [])

        if not words:
            print("[NSVisualOverlay] Empty transcript, returning original video")
            return (video,)

        resolved_key = self._resolve_api_key(api_key)

        temp_files = []
        try:
            original_path = tempfile.NamedTemporaryFile(
                suffix=".mp4", delete=False
            ).name
            temp_files.append(original_path)
            video.save_to(original_path, format="mp4", codec="h264")

            fps, width, height, duration = self._get_video_info(original_path)

            # Pass 1: Content analysis (text-only)
            analysis = self._pass1_analyze_content(
                resolved_key, model, words
            )

            # Extract frames with face detection
            frames, face_regions = self._extract_frames(
                original_path, duration, width, height
            )

            # Pass 2: Generate cues (with images, analysis, face data)
            cues = self._pass2_generate_cues(
                resolved_key, model, words, density, style,
                original_path, duration, width, height,
                analysis, frames, face_regions
            )

            settings = {"cues": cues}
            if style != "Auto":
                settings["defaultStyle"] = style

            output_dir = folder_paths.get_output_directory()
            output_path = os.path.join(
                output_dir, f"infographic_{int(time.time())}.mp4"
            )

            self._process_file(original_path, output_path, settings)

            print(f"[NSVisualOverlay] Done -> {output_path}")
            return (InputImpl.VideoFromFile(output_path),)

        finally:
            for f in temp_files:
                try:
                    os.unlink(f)
                except OSError:
                    pass


NODE_CLASS_MAPPINGS = {
    "NSVisualOverlay": NSVisualOverlay,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSVisualOverlay": "NS Video Infographics",
}
