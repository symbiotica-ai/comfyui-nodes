# ABOUTME: Camera shake maths — seeded Perlin fBm wiggle, presets, affine matrices.
# ABOUTME: Pure functions with no I/O so the curve can be unit-tested without ffmpeg.

import math

# ---------------------------------------------------------------------------
# Noise
#
# After Effects' wiggle() is fBm over classic Perlin noise: sum `octaves` of
# gradient noise, doubling the frequency and multiplying the amplitude by
# `amp_mult` each octave. We reimplement it rather than summing sines because
# a sine sum is strictly periodic — evenly spaced turning points that read as
# mechanical sway on a slow product hold. Perlin never repeats.
#
# The lattice is hashed rather than table-permuted, so there is no 256-unit
# wrap and the motion stays non-repeating for any clip length.
# ---------------------------------------------------------------------------

_U32 = 0xFFFFFFFF


def _hash(i, seed):
    """Deterministic 32-bit hash of a lattice index. Same input, same output,
    on every platform and every render pass — never seed this from time or
    random, or the shake changes between passes of the same clip."""
    h = (i * 374761393 + seed * 668265263) & _U32
    h = ((h ^ (h >> 13)) * 1274126177) & _U32
    return (h ^ (h >> 16)) & _U32


def _gradient(i, seed):
    """Lattice gradient in [-1, 1)."""
    return (_hash(i, seed) & 0xFFFF) / 32768.0 - 1.0


def _fade(t):
    """Perlin's quintic ease — zero 1st and 2nd derivatives at the lattice
    points, which is what keeps the motion free of visible kinks."""
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def perlin1d(x, seed):
    """Classic 1D Perlin noise, normalised to [-1, 1].

    Raw 1D Perlin peaks at +/-0.5 (both gradients extreme, sampled midway
    between them), so the doubling below makes the amplitude argument of
    wiggle() a true bound rather than an approximate one.
    """
    i = math.floor(x)
    t = x - i
    g0 = _gradient(i, seed)
    g1 = _gradient(i + 1, seed)
    u = _fade(t)
    return 2.0 * ((1.0 - u) * (g0 * t) + u * (g1 * (t - 1.0)))


def fbm(x, seed, octaves=1, amp_mult=0.5):
    """Fractal Brownian motion over perlin1d, normalised to [-1, 1].

    Normalising by the summed octave amplitudes is a deliberate departure from
    AE, which lets the sum overshoot `amp`. Keeping the output bounded is what
    makes required_zoom() exact instead of a guess. At the default octaves=1
    the normalisation is a no-op, so the AE presets still behave as tuned.
    """
    if octaves < 1:
        raise ValueError("octaves must be >= 1")
    total = 0.0
    norm = 0.0
    amp = 1.0
    freq = 1.0
    for o in range(octaves):
        # Offset the seed per octave so the octaves do not sit in phase.
        total += amp * perlin1d(x * freq, seed + o * 1013)
        norm += amp
        amp *= amp_mult
        freq *= 2.0
    return total / norm


def wiggle(t, freq, amp, seed, octaves=1, amp_mult=0.5):
    """AE's wiggle(freq, amp): a value within +/-amp, varying at `freq` Hz.

    `amp` is in the property's native units, exactly as in AE — pixels for
    position, percent for scale, degrees for rotation.
    """
    return amp * fbm(t * freq, seed, octaves, amp_mult)


# ---------------------------------------------------------------------------
# Handheld motion
#
# A single wiggle() is one smooth frequency, and that is exactly why it reads as
# "an After Effects effect" rather than as a person holding a camera. Two things
# give it away:
#
#   * one frequency means no texture — the motion is a slow float with no fine
#     jitter riding on it;
#   * classic Perlin returns exactly 0 on integer lattice points, so at the
#     rig's 1 Hz every axis snaps back to dead centre once a second, in unison.
#     That is a metronome buried in the shake.
#
# Real handheld is broadband. A standing operator produces slow postural drift,
# weight shifts, body sway, arm movement, and a small ever-present physiological
# tremor. Summing those bands gives micro and macro motion at once, and because
# the frequencies below share no simple ratios the sum never repeats and the
# bands never zero together.
# ---------------------------------------------------------------------------

HANDHELD_BANDS = (
    # freq Hz, relative weight
    (0.11, 1.000),   # postural drift — the operator slowly leaning
    (0.27, 0.660),   # weight shifting foot to foot
    (0.63, 0.380),   # body sway
    (1.47, 0.200),   # arm and shoulder
    (3.70, 0.085),   # grip settling
    (9.30, 0.040),   # physiological tremor — the fine "micro" texture
)

# Bands at or below this are the operator's gross movement and speed up when the
# preset is faster. Above it is the body's own tremor, whose frequency is fixed
# no matter how much the operator is moving — only its amplitude rides along.
_GROSS_MOTION_HZ = 2.0

# RMS-preserving normalisation: `amp` stays the same perceived level as the
# single-octave wiggle it replaces. Peaks can reach CREST_FACTOR * amp when
# bands happen to align, which is rare and is exactly what required_zoom()
# measures per frame anyway.
_BAND_NORM = math.sqrt(sum(w * w for _, w in HANDHELD_BANDS))
CREST_FACTOR = sum(w for _, w in HANDHELD_BANDS) / _BAND_NORM

# Per-band phase offsets so no band starts on a lattice point. Without these
# every clip begins at exactly dead centre and drifts out, which never happens
# when a real operator rolls. Deliberately non-round.
_BAND_PHASE = (0.0, 0.3711, 1.7321, 2.7183, 3.1416, 4.6692)

# Vertical sway is smaller than lateral for someone standing and holding a
# camera: side-to-side is weight shift, up-down is only breathing and knees.
_VERTICAL_RATIO = 0.78

# Roll is not independent of lateral sway — swaying right tips the horizon a
# little. Fully independent rotation is a large part of the "goofy" look.
_ROLL_COUPLING = 0.38

# CIPA DC-X011-2024 section 6-27, measured by attaching sensors to cameras held
# by many people: at 24 mm and image height 60%, roll accounts for 23% of the
# combined yaw+pitch+roll handheld blur — about 57 um of roll against ~200 um of
# yaw and pitch. So roll's displacement at 60% of the image height should be
# 23/(100-23) = 0.30 of the translation that yaw and pitch produce.
#
# Every ported AE preset is far below this: Light rolls at 0.035 of its
# translation, Walk at 0.007. A real handheld camera rolls visibly and those
# presets barely roll at all, which is a large part of why the rig reads as an
# effect. Deriving roll from the translation instead of carrying a per-preset
# number also makes it correct at any resolution and aspect ratio for free.
_ROLL_BLUR_SHARE = 0.23
_ROLL_TO_SHIFT = _ROLL_BLUR_SHARE / (1.0 - _ROLL_BLUR_SHARE)
_CIPA_IMAGE_HEIGHT = 0.6
_ROLL_REFERENCE_FOCAL_MM = 24.0


# ---------------------------------------------------------------------------
# Shot type
#
# The same operator produces a different-looking shake depending on the shot,
# and CIPA measures the reason. Section 6-27: "the yaw and pitch handheld blur
# amounts increase in proportion to focal length, but the roll handheld blur
# amount does not change" — with anchors of 23% roll at 24 mm and 3% at 200 mm.
# So roll's share of the motion falls as 1/f: a wide shot visibly rolls, a
# detail shot is almost pure drift. Checking those two anchors against each
# other, the ratio of ratios is 9.66 where 1/f predicts 8.33, so the law holds
# to within the "approximately" the standard uses.
#
# `breathe` is ours, not measured: near 1:1 a small fore-and-aft sway changes
# magnification substantially, so a detail shot pulses in scale where a wide
# one does not.
#
# Deliberately NOT scaled: overall amplitude. Physically, yaw/pitch blur grows
# with focal length, which would make a detail shot shake ~5.6x a wide one and
# be unusable — and in practice tight product shots get braced or put on
# support, which is exactly the effect that cancels it. Amount stays owned by
# the preset and `strength`.
# ---------------------------------------------------------------------------

SHOT_TYPES = {
    "Wide":      dict(focal_mm=24.0,  breathe=0.60),
    "Medium":    dict(focal_mm=50.0,  breathe=0.85),
    "Close-Up":  dict(focal_mm=85.0,  breathe=1.30),
    "Detail":    dict(focal_mm=135.0, breathe=2.20),
}
SHOT_TYPE_NAMES = list(SHOT_TYPES)
DEFAULT_SHOT_TYPE = "Medium"


AUTO_SHOT_TYPE = "Auto"
SHOT_TYPE_CHOICES = [AUTO_SHOT_TYPE] + SHOT_TYPE_NAMES

# One dropdown, not two. A separate shot-type control alongside the preset was
# confusing — both read as "what kind of shake" — and worse, it left Auto doing
# half a job: a clip whose shots range from a macro detail to a wide would get
# the same amount of motion on both. Auto now decides amount and optics
# together, per shot, and picking a named preset means exactly that preset.
#
# The ladder: a wider shot tolerates and expects more visible framing movement,
# a macro detail almost none — 65 px of travel that reads as handheld on a wide
# would wreck a pavé close-up.
SHOT_TYPE_PRESET = {
    "Detail": "Micro",
    "Close-Up": "Subtle",
    "Medium": "Handheld",
    "Wide": "Light Soft",
}

AUTO_PRESET = "Auto"


def preset_choices():
    """Dropdown contents: Auto first, then every named preset."""
    return [AUTO_PRESET] + list(PRESETS)


def preset_for_shot(shot_type):
    """Which preset Auto uses for a detected shot type."""
    if shot_type not in SHOT_TYPE_PRESET:
        raise ValueError(f"unknown shot type: {shot_type!r}")
    return SHOT_TYPE_PRESET[shot_type]

# Classification thresholds. `face` is the widest detected face as a fraction of
# frame width; `detail` is the fraction of the frame carrying sharp local
# contrast, which reads as "how much of this is in focus".
#
# A face is the strongest available cue for how tight a shot is, because head
# size in frame is close to the definition of shot size. With no face, focus
# coverage separates a product detail (a small sharp island in bokeh) from a
# wide shot (sharp almost everywhere).
_FACE_CLOSE_UP = 0.30
_FACE_MEDIUM = 0.12
_DETAIL_MOSTLY_BOKEH = 0.10
_DETAIL_PARTIAL = 0.25


def classify_shot(detail_fraction, face_fraction=0.0):
    """Name the shot type from two cheap measurements.

    Pure so it can be tested without OpenCV or a video; the node supplies the
    measurements. Errs toward the middle: a wrong guess between neighbouring
    shot types changes the roll share slightly and nothing else.
    """
    if face_fraction >= _FACE_CLOSE_UP:
        return "Close-Up"
    if face_fraction >= _FACE_MEDIUM:
        return "Medium"
    if face_fraction > 0.0:
        # A person is present but small in frame.
        return "Wide"
    if detail_fraction < _DETAIL_MOSTLY_BOKEH:
        # A small sharp island in a sea of bokeh — a product detail shot.
        return "Detail"
    if detail_fraction < _DETAIL_PARTIAL:
        return "Close-Up"
    return "Wide"


# A cut must clear both the floor and a robust measure of the clip's own noise.
# The floor matters because MAD is near zero on a clean generated clip; the
# relative term matters because a busy handheld source has a high noise floor.
# Validated against ground truth on three real generated clips: scores of
# 15.2 / 14.9 / 9.6 for the true cuts against a 1.7 maximum elsewhere.
_CUT_SCORE_FLOOR = 4.0
_CUT_MAD_MULTIPLE = 8.0

# Two "cuts" closer together than this are one cut plus a wobble. A false
# positive is the expensive error — it re-seeds the shake mid-shot, which shows
# as a jump — so it is worth being conservative here.
MIN_SHOT_SECONDS = 0.4


def cut_threshold(scores):
    """Score above which a frame counts as a cut, from the clip's own
    distribution rather than a constant."""
    if not scores:
        return _CUT_SCORE_FLOOR
    ordered = sorted(scores)
    mid = len(ordered) // 2
    median = (ordered[mid] if len(ordered) % 2
              else 0.5 * (ordered[mid - 1] + ordered[mid]))
    deviations = sorted(abs(s - median) for s in scores)
    mid = len(deviations) // 2
    mad = (deviations[mid] if len(deviations) % 2
           else 0.5 * (deviations[mid - 1] + deviations[mid]))
    return max(_CUT_SCORE_FLOOR, median + _CUT_MAD_MULTIPLE * mad)


def cuts_from_scores(scored_frames, fps, min_shot_seconds=MIN_SHOT_SECONDS):
    """Pick cut frames from [(score, frame), ...].

    Applies the adaptive threshold and then drops anything that would create a
    shot shorter than min_shot_seconds.
    """
    if not scored_frames:
        return []
    threshold = cut_threshold([s for s, _ in scored_frames])
    candidates = sorted(frame for score, frame in scored_frames
                        if score > threshold and frame > 0)
    min_gap = max(1, int(round(min_shot_seconds * fps)))
    kept = []
    for frame in candidates:
        if not kept or frame - kept[-1] >= min_gap:
            kept.append(frame)
    return kept


# Zero-shot prompts for shot size. Several per class and pooled by mean logit,
# which is the recipe this pack's gallery classifier landed on after measuring
# alternatives — pooling choice mattered more there than model size did.
SHOT_PROMPTS = {
    "Detail": (
        "an extreme close-up macro photograph of a small object filling the frame",
        "a macro product shot of jewellery, very shallow depth of field",
        "an extreme close-up of a texture or a small detail",
    ),
    "Close-Up": (
        "a close-up photograph of a person's face filling the frame",
        "a close-up shot of a hand or wrist wearing jewellery",
        "a tight close-up photograph",
    ),
    "Medium": (
        "a medium shot photograph of a person from the waist up",
        "a half-body portrait photograph of a person",
        "a medium shot showing a person and some of their surroundings",
    ),
    "Wide": (
        "a wide establishing shot of a whole scene",
        "a full-length photograph of a person in a room",
        "a wide angle photograph showing a large space",
    ),
}


def pool_shot_logits(logits_by_prompt):
    """Mean logit per class, then pick the winner.

    `logits_by_prompt` maps class name -> list of raw logits, one per prompt.
    Mean-of-logits rather than sum-of-probabilities: the same choice this
    pack's gallery classifier measured as best.
    """
    if not logits_by_prompt:
        raise ValueError("no logits to pool")
    means = {name: (sum(v) / len(v)) for name, v in logits_by_prompt.items() if v}
    if not means:
        raise ValueError("no logits to pool")
    return max(means, key=means.get)


def classify_shot_clip(image, model=None, processor=None):
    """Shot type from a PIL image using zero-shot CLIP.

    Returns None when transformers or the model is unavailable, so the caller
    can fall back to the measurement heuristic. Lazy-imported on purpose:
    the pack does not declare transformers and must load without it.
    """
    try:
        if model is None or processor is None:
            from transformers import CLIPModel, CLIPProcessor
            name = "openai/clip-vit-base-patch16"
            model = CLIPModel.from_pretrained(name)
            processor = CLIPProcessor.from_pretrained(name)
        prompts, owners = [], []
        for shot_type, texts in SHOT_PROMPTS.items():
            for text in texts:
                prompts.append(text)
                owners.append(shot_type)
        inputs = processor(text=prompts, images=image,
                           return_tensors="pt", padding=True)
        outputs = model(**inputs)
        logits = outputs.logits_per_image[0].tolist()
        grouped = {}
        for shot_type, value in zip(owners, logits):
            grouped.setdefault(shot_type, []).append(value)
        return pool_shot_logits(grouped)
    except Exception:
        return None


def segments_from_cuts(cut_frames, n_frames):
    """Turn cut positions into (start, end) frame ranges covering the clip.

    A cut is a new camera setup, so each segment gets its own shake: the rig is
    re-seeded and its clock restarts. Running one continuous shake across a cut
    is the thing that most obviously never happens in real footage.
    """
    if n_frames <= 0:
        return []
    bounds = sorted({0} | {c for c in cut_frames if 0 < c < n_frames})
    bounds.append(n_frames)
    return [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)
            if bounds[i + 1] > bounds[i]]


def roll_ratio_for(shot_type):
    """Roll-to-shift ratio for a shot type, from CIPA's 24 mm anchor scaled by
    the documented 1/f law."""
    if shot_type not in SHOT_TYPES:
        raise ValueError(f"unknown shot type: {shot_type!r}")
    focal = SHOT_TYPES[shot_type]["focal_mm"]
    return _ROLL_TO_SHIFT * (_ROLL_REFERENCE_FOCAL_MM / focal)

# How deeply the operator's steadiness drifts, and how fast. Gives passages that
# are calmer and passages that are busier instead of one constant energy.
_ENERGY_DEPTH = 0.55
_ENERGY_RATE = 0.11


def handheld_channel(t, seed, rate=1.0, max_freq=None):
    """One axis of broadband handheld motion, normalised to roughly [-1, 1].

    `rate` speeds up the operator's gross movement only; tremor keeps its own
    frequency. `max_freq` clamps every band below Nyquist so a fast preset
    cannot alias into buzzing jitter.
    """
    total = 0.0
    for i, (freq, weight) in enumerate(HANDHELD_BANDS):
        f = freq * rate if freq <= _GROSS_MOTION_HZ else freq
        if max_freq is not None and f > max_freq:
            f = max_freq
        total += weight * perlin1d(t * f + _BAND_PHASE[i], seed + i * 7919)
    return total / _BAND_NORM


def energy(t, seed, rate=1.0):
    """Slow drift in how steady the operator is, in [1 - depth, 1].

    Two octaves so the swell itself is not a clean sine.
    """
    n = fbm(t * _ENERGY_RATE * rate, seed, octaves=2, amp_mult=0.55)
    return 1.0 - _ENERGY_DEPTH * (1.0 - n) * 0.5


# How many time constants of decay count as "settled". At 4, the shake is down
# to 1.8% of the hit, so `decay` reads as the wall-clock length of the impact
# rather than as an abstract tau.
_DECAY_TAU_DIVISOR = 4.0


def impulse_envelope(t, impact_time, decay):
    """Amplitude multiplier for an impact: nothing, then a hit, then a settle.

    Returns 1.0 everywhere when `decay` <= 0, which is what makes the
    continuous presets fall through this unchanged.

    The AE rig does this by keyframing the *amount* on a separate layer instead
    of holding it constant — the frequencies are the only thing its Impact
    presets expose. An exponential settle is the physical response of a struck
    object, and it means one number (`decay`) describes the whole tail.
    """
    if decay <= 0:
        return 1.0
    if t < impact_time:
        # Dead still before the hit. That stillness is the point: the contrast
        # is what sells the impact.
        return 0.0
    return math.exp(-(t - impact_time) / (decay / _DECAY_TAU_DIVISOR))


# ---------------------------------------------------------------------------
# Presets
#
# Position amounts are pixels against a 1920-tall frame and are rescaled to
# the real frame height by shake_curve(), so a preset looks the same on any
# resolution. Rotation follows AE's convention of amount/10 degrees. Scale
# amounts are percent.
#
# Light/Heavy/Walk/Run carry the tuning of a standard handheld AE rig, read
# out of its per-preset client controls and cross-checked against the three
# expressions that drive it:
#
#   position -> wiggle(Position Frequency, Position Amount)
#   scale    -> wiggle(Scale Frequency, Scale Amount)
#   rotation -> wiggle(Rotate Frequency, Rotate Amount)/10
#
# which is where the amount/10 rotation convention below comes from. `zoom`
# is that rig's "Footage Scale Correction", its manual edge guard.
#
# Micro and Subtle are ours, for macro product work where 65 px of travel on
# a 1920-tall frame would fight the shot.
#
# Not ported: that rig's two Impact presets. They are a different animation
# model — the amount is keyframed as an impulse-and-decay on a separate layer
# rather than held constant, and they drive frequency through a /10 variant of
# the expression. Adding them means picking a hit time and a decay, so they
# want their own node rather than a preset here.
# ---------------------------------------------------------------------------

PRESET_CUSTOM = "Custom"

# `decay` is the impact tail in seconds; 0 means a continuous shake with no
# envelope, which is what every non-Impact preset wants.
PRESETS = {
    #                pos_freq pos_amt  scale_freq scale_amt  rot_freq rot_amt  zoom  decay
    "Micro":        dict(pos_freq=1.0, pos_amt=8.0,   scale_freq=1.0, scale_amt=0.3, rot_freq=1.0, rot_amt=0.6,  zoom=1.02,  decay=0.0),
    "Subtle":       dict(pos_freq=1.0, pos_amt=20.0,  scale_freq=1.0, scale_amt=0.5, rot_freq=1.0, rot_amt=1.2,  zoom=1.03,  decay=0.0),
    # The everyday one: an operator holding the camera, breathing. Ours, sat
    # between Subtle and the rig's Light, and the sane default.
    "Handheld":     dict(pos_freq=1.0, pos_amt=35.0,  scale_freq=1.0, scale_amt=0.8, rot_freq=1.0, rot_amt=1.6,  zoom=1.04,  decay=0.0),
    "Light Soft":   dict(pos_freq=1.0, pos_amt=52.0,  scale_freq=1.0, scale_amt=1.0, rot_freq=1.0, rot_amt=2.0,  zoom=1.05,  decay=0.0),
    "Light":        dict(pos_freq=1.0, pos_amt=65.0,  scale_freq=1.0, scale_amt=1.0, rot_freq=1.0, rot_amt=2.0,  zoom=1.05,  decay=0.0),
    "Heavy":        dict(pos_freq=2.0, pos_amt=38.0,  scale_freq=1.0, scale_amt=3.0, rot_freq=10.0, rot_amt=2.0, zoom=1.00,  decay=0.0),
    "Heavy Wide":   dict(pos_freq=2.0, pos_amt=115.0, scale_freq=1.0, scale_amt=2.0, rot_freq=2.0, rot_amt=55.0, zoom=1.132, decay=0.0),
    "Walk":         dict(pos_freq=1.0, pos_amt=170.0, scale_freq=1.0, scale_amt=1.0, rot_freq=1.0, rot_amt=1.0,  zoom=1.10,  decay=0.0),
    "Run":          dict(pos_freq=3.0, pos_amt=90.0,  scale_freq=1.0, scale_amt=1.0, rot_freq=1.0, rot_amt=1.0,  zoom=1.10,  decay=0.0),
    # Impact frequencies are the AE rig's values divided by 10, because its
    # Impact comps use the wiggle(Frequency/10, Amount) form of the expression
    # — which is why its sliders read 120 and 20 where the others read 1 and 2.
    # The amounts are ours: the rig keyframes them on a separate layer and
    # exposes no slider, so there was no number to port.
    "Impact":       dict(pos_freq=12.0, pos_amt=55.0, scale_freq=1.0, scale_amt=4.0, rot_freq=2.0,  rot_amt=25.0, zoom=1.05, decay=0.55),
    "Impact Rumble": dict(pos_freq=5.47, pos_amt=90.0, scale_freq=2.2, scale_amt=5.0, rot_freq=3.28, rot_amt=40.0, zoom=1.05, decay=1.10),
}

# What the node offers. PRESET_CUSTOM is deliberately absent: the node exposes
# no amount or frequency widgets, so there would be nothing for it to
# customise. resolve_preset() still accepts it for programmatic callers.
PRESET_NAMES = list(PRESETS.keys())

# Reference frame height the preset pixel amounts were tuned against.
REFERENCE_HEIGHT = 1920.0

# Seed offsets keep the three axes from moving in lockstep. Any distinct
# constants work; these are arbitrary and only need to stay stable, since
# changing them changes every existing shake_variation.
_SEED_X = 0
_SEED_Y = 7919
_SEED_ROT = 15773
_SEED_SCALE = 23773


def resolve_preset(preset, pos_amt, rot_amt, safety_zoom,
                   pos_freq=1.0, rot_freq=1.0,
                   scale_amt=0.0, scale_freq=1.0, decay=0.0):
    """Return the base wiggle parameters for a preset, or the widget values
    when preset is Custom.

    The masters (shake_strength, shake_speed) are applied later, on top of
    whatever this returns — that is what lets you pick a preset and then dial
    it down, which is the whole point of the masters.
    """
    if preset == PRESET_CUSTOM:
        return dict(pos_freq=pos_freq, pos_amt=pos_amt,
                    scale_freq=scale_freq, scale_amt=scale_amt,
                    rot_freq=rot_freq, rot_amt=rot_amt,
                    zoom=safety_zoom, decay=decay)
    if preset not in PRESETS:
        raise ValueError(f"unknown preset: {preset!r}")
    return dict(PRESETS[preset])


# The amplitude arguments are peak-ish while CIPA's ratio is between two RMS
# blur figures, and blending roll with lateral sway lowers its variance further.
# Rather than guess, this factor was measured: it is the number that makes the
# finished curve's roll-to-shift RMS ratio land on CIPA's 0.299, averaged over
# 200 seeds. Two hundred is not overkill — the lowest band has a ~9 s period, so
# a single clip is only a couple of cycles and a 40-seed estimate came out 22%
# wrong. Re-measure if the bands, the coupling or _VERTICAL_RATIO change.
_ROLL_RMS_CALIBRATION = 1.692


def roll_amplitude_deg(pos_amp_px, width, height, roll_ratio=_ROLL_TO_SHIFT):
    """Roll amplitude in degrees for a given translation amplitude.

    Derived from CIPA's measurements rather than carried per preset, so it is
    automatically right for any frame size and aspect. `roll_ratio` comes from
    the shot type — see roll_ratio_for().
    """
    radius = _CIPA_IMAGE_HEIGHT * 0.5 * math.hypot(width, height)
    if radius <= 0:
        raise ValueError("frame has no area")
    return math.degrees(
        roll_ratio * _ROLL_RMS_CALIBRATION * pos_amp_px / radius)


def make_sampler(params, fps, strength=1.0, speed=1.0, variation=0,
                 height=REFERENCE_HEIGHT, width=None, impact_time=0.0,
                 shot_type=DEFAULT_SHOT_TYPE):
    """Return a function t -> (dx_px, dy_px, rot_deg, scale_mult).

    Continuous in t rather than per-frame, because motion blur has to evaluate
    the rig *between* frames — at several instants across the shutter opening.
    """
    # Preset pixel amounts are tuned for a 1920-tall frame; keep the motion a
    # constant fraction of frame height at any resolution.
    px_scale = height / REFERENCE_HEIGHT
    if width is None:
        # Fall back to the reference portrait aspect; callers with a real frame
        # pass width so the roll derivation is exact.
        width = height * 9.0 / 16.0

    shot = SHOT_TYPES[shot_type] if shot_type in SHOT_TYPES else None
    if shot is None:
        raise ValueError(f"unknown shot type: {shot_type!r}")

    pos_amp = params["pos_amt"] * strength * px_scale
    # A detail shot pulses in scale where a wide one does not: near 1:1 a small
    # fore-and-aft sway changes magnification a lot.
    scale_amp = params["scale_amt"] * strength * shot["breathe"]
    rot_amp = roll_amplitude_deg(pos_amp, width, height,
                                 roll_ratio_for(shot_type))

    rate = params["pos_freq"] * speed
    scale_rate = params["scale_freq"] * speed
    decay = params.get("decay", 0.0)

    # Nothing may exceed Nyquist, or a fast preset aliases into buzzing.
    nyquist = 0.5 * fps * 0.8
    seed = int(variation)

    def sample(t):
        env = impulse_envelope(t, impact_time, decay) * energy(t, seed + 31337, rate)
        if env == 0.0:
            # Before the hit on an impact preset: perfectly still.
            return (0.0, 0.0, 0.0, 1.0)

        nx = handheld_channel(t, seed + _SEED_X, rate, nyquist)
        ny = handheld_channel(t, seed + _SEED_Y, rate, nyquist)
        nr = handheld_channel(t, seed + _SEED_ROT, rate, nyquist)
        ns = handheld_channel(t, seed + _SEED_SCALE, scale_rate, nyquist)

        dx = env * pos_amp * nx
        dy = env * pos_amp * _VERTICAL_RATIO * ny
        # Swaying sideways tips the horizon with you; the rest is independent.
        rot = env * rot_amp * ((1.0 - _ROLL_COUPLING) * nr + _ROLL_COUPLING * nx)
        sc = env * scale_amp * ns
        return (dx, dy, rot, 1.0 + sc / 100.0)

    return sample


def shake_curve(n_frames, fps, params, strength=1.0, speed=1.0,
                variation=0, height=REFERENCE_HEIGHT, width=None,
                octaves=1, amp_mult=0.5, impact_time=0.0,
                shot_type=DEFAULT_SHOT_TYPE):
    """Per-frame handheld motion.

    Returns a list of (dx_px, dy_px, rot_deg, scale_mult), one per frame:

      dx, dy      translation in pixels of the *real* frame
      rot_deg     roll in degrees
      scale_mult  multiplier around 1.0, before the safety zoom is applied

    `strength` scales the amounts, `speed` the rate, and `variation` is the
    seed: the same settings with a different variation give a completely
    different but equally valid shake.

    The motion is broadband (see HANDHELD_BANDS), its energy drifts over time,
    the axes are asymmetric, and roll is partly coupled to lateral sway —
    the four things that separate a person holding a camera from a wiggle().
    """
    sample = make_sampler(params, fps, strength, speed, variation,
                          height, width, impact_time, shot_type)
    return [sample(n / fps) for n in range(n_frames)]


# ---------------------------------------------------------------------------
# Motion blur
#
# A camera that moves during the exposure smears the image along the path it
# travelled. That is precisely what CIPA calls "handheld blur amount" — the
# shift of the subject in the image caused by the camera moving while the
# shutter is open — so the same standard that gave us the motion also tells us
# how finely to sample it.
# ---------------------------------------------------------------------------

# CIPA DC-X011-2024 3-1-11: 20 um on a 35 mm frame is the determination level,
# the blur below which a viewer cannot tell. On a 1080x1920 frame that is
# almost exactly one pixel, which makes it a principled step size: keep every
# sub-step of the shutter under this and the accumulation cannot band.
_CIPA_BLUR_LEVEL_UM = 20.0
_FULL_FRAME_DIAGONAL_MM = 43.3

# A 180-degree shutter — half the frame interval — is the cinema default and
# what strength 1.0 means here.
SHUTTER_180 = 0.5


def blur_step_px(width, height):
    """The largest sub-step, in pixels, that stays under CIPA's visible-blur
    level for this frame size."""
    return (_CIPA_BLUR_LEVEL_UM / 1000.0 / _FULL_FRAME_DIAGONAL_MM) * math.hypot(width, height)


def blur_sample_count(path_px, width, height, max_samples=16):
    """How many sub-exposures a frame needs, given how far it travels during
    the shutter.

    Adaptive on purpose: a subtle shake moves well under a pixel per frame, so
    almost every frame resolves to a single sample and costs nothing extra.
    Only the frames that genuinely smear pay for more.
    """
    if path_px <= 0:
        return 1
    step = blur_step_px(width, height)
    if step <= 0:
        return 1
    return max(1, min(int(max_samples), int(math.ceil(path_px / step)) ))


def shutter_path_px(sample, t0, dt, width, height):
    """Distance the frame's worst-case corner travels over the shutter, in
    pixels — translation plus what the roll contributes out at the corner."""
    x0, y0, r0, s0 = sample(t0)
    x1, y1, r1, s1 = sample(t0 + dt)
    radius = 0.5 * math.hypot(width, height)
    shift = math.hypot(x1 - x0, y1 - y0)
    roll = abs(math.radians(r1 - r0)) * radius
    breathe = abs(s1 - s0) * radius
    return shift + roll + breathe


# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def affine_matrix(width, height, dx, dy, rot_deg, scale):
    """Inverse affine coefficients for PIL's Image.transform(AFFINE).

    PIL maps *output* (x, y) to *input* (a x + b y + c, d x + e y + f), so this
    returns the inverse of the transform we actually want, which is: scale
    about the frame centre, rotate about the frame centre, then translate.

    Doing it as one matrix means one resample per frame. Chaining ffmpeg's
    scale -> rotate -> crop would resample three times, and crop can only
    translate in whole pixels (two, in yuv420p, because x snaps to the chroma
    grid) which makes a subtle shake visibly step.
    """
    if scale <= 0:
        raise ValueError("scale must be > 0")
    cx = width / 2.0
    cy = height / 2.0
    th = math.radians(rot_deg)
    cos_t = math.cos(th) / scale
    sin_t = math.sin(th) / scale

    a = cos_t
    b = sin_t
    d = -sin_t
    e = cos_t
    # Translate first in output space, then map back around the centre.
    ox = cx + dx
    oy = cy + dy
    c = cx - (a * ox + b * oy)
    f = cy - (d * ox + e * oy)
    return (a, b, c, d, e, f)


# Bicubic resampling reads two pixels either side of its sample point, so a
# backend that fills out-of-bounds reads with a flat colour needs the sampled
# region held this far inside the source. Pillow does not: it clamps at the
# edge, verified by warping a white frame half a pixel and finding the border
# still at 255. So the default is 0 — a non-zero pad would crop every render
# slightly for no reason, and would stop a still frame from passing through
# untouched. Kept as a parameter for any backend that does not clamp.
RESAMPLE_PAD_PX = 0.0


def _required_scale(width, height, dx, dy, rot_deg, pad_px=RESAMPLE_PAD_PX):
    """Smallest uniform scale that keeps the whole output frame inside the
    source for one frame's rotation and translation.

    Each output corner maps back to R(-theta) * (corner - centre - offset) / s.
    Requiring that to land inside the source half-extents, less the resampling
    pad, gives a lower bound on s per corner and axis; the largest of those
    bounds is the answer.
    """
    cx = width / 2.0
    cy = height / 2.0
    # Half-extents the sample point must stay within.
    lim_x = cx - pad_px
    lim_y = cy - pad_px
    if lim_x <= 0 or lim_y <= 0:
        raise ValueError("frame is too small for the resampling pad")

    th = math.radians(rot_deg)
    cos_t = math.cos(th)
    sin_t = math.sin(th)

    need = 1.0
    for px, py in ((0.0, 0.0), (width, 0.0), (0.0, height), (width, height)):
        vx = px - cx - dx
        vy = py - cy - dy
        rx = cos_t * vx + sin_t * vy
        ry = -sin_t * vx + cos_t * vy
        need = max(need, abs(rx) / lim_x, abs(ry) / lim_y)
    return need


def required_zoom(width, height, curve, pad_px=RESAMPLE_PAD_PX):
    """Smallest safety zoom that never reveals the frame edge, over the whole
    clip.

    This is the one place the node beats the AE rig it is modelled on: there,
    Safety Zoom is a manual slider you nudge until the edges stop showing.
    """
    base = 1.0
    for dx, dy, rot, scale_mult in curve:
        need = _required_scale(width, height, dx, dy, rot, pad_px)
        # The scale wiggle multiplies the base zoom, so a frame that wiggles
        # smaller needs a proportionally larger base to still cover.
        if scale_mult <= 0:
            raise ValueError("scale multiplier must be > 0")
        base = max(base, need / scale_mult)
    return base
