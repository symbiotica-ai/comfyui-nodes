# ABOUTME: Focus pull maths — the easing curve of the rack and a lens-style disc defocus.
# ABOUTME: Pure numpy, no ComfyUI and no subprocess, so both test flat and fast.

import math

import numpy as np

# ---------------------------------------------------------------------------
# The rack
#
# A focus puller does not move the barrel at a constant rate. They break it off
# the first mark, run it across, and feather it into the second — so the curve
# accelerates from rest and decelerates into the mark.
#
# The easing here is SMOOTHERSTEP, Perlin's quintic 6t^5 - 15t^4 + 10t^3.
# Three candidates were on the table:
#
#   linear                nobody pulls focus linearly; it starts and stops dead.
#   smoothstep (cubic)    zero velocity at both ends, but f''(1) = -6: the
#                         deceleration is still at full tilt on the frame the
#                         pull ends, then vanishes. That step in acceleration is
#                         exactly what "stopping dead" looks like — the image
#                         arrives and clamps.
#   smootherstep (quintic) zero velocity AND zero acceleration at both ends, so
#                         the rack eases out of rest and settles into the mark
#                         with nothing to clamp. C2 at the joins.
#
# Not used: a critically damped second-order settle, which is the honest physical
# model of a hand landing on a mark. It never actually arrives — it approaches
# the target asymptotically — so it has to be truncated at `seconds`, and the
# truncation puts back the very discontinuity the quintic was chosen to remove.
#
# Because smootherstep is symmetric about t = 0.5 (e(t) + e(1-t) == 1), pulling
# out of focus is the exact time-reverse of pulling into it. That is the right
# physics — a rack reversed is a rack — and it is what the tests assert.
# ---------------------------------------------------------------------------


def ease(t):
    """Smootherstep. Clamped outside [0, 1] so the curve holds at both ends."""
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


DIRECTION_IN = "into focus"
DIRECTION_OUT = "out of focus"
DIRECTIONS = [DIRECTION_IN, DIRECTION_OUT]

# Defocus radius at strength 1.0, as a fraction of frame height. Held as a
# fraction rather than pixels so the same setting reads the same at 480p and 4K:
# a circle of confusion 2% of the frame tall erases anything smaller than about
# a fourteenth of the frame, which puts a face past recognising while leaving the
# composition perfectly readable.
MAX_RADIUS_FRACTION = 0.02

# Below half a pixel the disc is narrower than the pixel it sits on and the
# convolution collapses to the identity anyway; short-circuiting there keeps the
# sharp end of the pull bit-identical to the source instead of merely equal to it.
MIN_RADIUS_PX = 0.5


def max_radius_px(strength, height):
    """Defocus radius at the soft end of the pull, in pixels of this frame."""
    if height <= 0:
        raise ValueError("frame has no height")
    return max(0.0, strength) * MAX_RADIUS_FRACTION * height


def pull_frames(n_frames, fps, seconds):
    """How many frames the rack occupies.

    Capped at the clip: asking for a three-second pull on a two-second clip means
    you want the shot to land, not to end halfway through the move, so the pull
    takes the whole clip instead of running off the end unfinished.
    """
    if fps <= 0:
        raise ValueError("fps must be > 0")
    span = int(round(seconds * fps))
    return max(1, min(span, max(1, n_frames - 1)))


def focus_curve(n_frames, fps, direction, strength, height, seconds):
    """Defocus radius in pixels, one per frame.

    Going in, the pull starts on the first frame and the rest of the clip is
    sharp. Coming out, it lands on the last frame and everything before it is
    sharp — which is why neither direction needs a start-time widget.

    The frame count from ffprobe is an estimate, so the caller should hold the
    last value for any frame past the end. Holding is correct in both
    directions: going in the tail is already sharp, coming out it is already
    fully soft.
    """
    if direction not in DIRECTIONS:
        raise ValueError(f"unknown direction: {direction!r}")
    if n_frames <= 0:
        return []

    peak = max_radius_px(strength, height)
    span = pull_frames(n_frames, fps, seconds)

    if direction == DIRECTION_IN:
        return [peak * (1.0 - ease(i / span)) for i in range(n_frames)]
    start = n_frames - 1 - span
    return [peak * ease((i - start) / span) for i in range(n_frames)]


# ---------------------------------------------------------------------------
# The defocus
#
# An out-of-focus point does not become a gaussian smudge, it becomes a disc —
# the circle of confusion, an image of the iris. The distinction is the whole
# look on a jewellery shot: every specular highlight on a stone turns into a
# hard-edged bokeh ball, where a gaussian would give a soft grey haze. So this
# convolves with a real flat-topped disc.
#
# THE TRADE-OFF. A disc is not separable, so the obvious implementation is
# O(r^2) per pixel and unusable. The three ways out:
#
#   gaussian              separable, O(r) — and wrong. Cheap, and the reason
#                         most "lens blur" sliders look like vaseline.
#   complex separable     the disc approximated as a sum of complex gaussians
#                         (Garcia 2017). O(1) per pixel, genuinely flat-topped,
#                         but it rings at the disc edge and the coefficients are
#                         fitted constants that cannot be checked by reading them.
#   prefix sums per row   what this does. The disc is a stack of horizontal
#                         runs, one per row offset, of half-width sqrt(r^2-dy^2).
#                         A run of any width — including a fractional one — is a
#                         difference of two entries in the row's cumulative sum,
#                         so each row costs O(1) per pixel and the whole disc
#                         costs O(r). Exact, no fitted constants, and the kernel
#                         it produces can be read straight off an impulse.
#
# The cost is that O(r) walks the frame 2r times, so the soft end of a strong
# pull at 4K is genuinely slow. That is the price of a disc, paid on the frames
# that actually need one — the sharp end of the pull short-circuits to nothing.
#
# The run widths are fractional, not rounded to whole pixels. That matters more
# than it sounds: the radius creeps up by a fraction of a pixel per frame during
# the rack, and a kernel quantised to whole pixels would hold still and then jump,
# which reads as banding in time.
# ---------------------------------------------------------------------------


def _row_half_width(dy, radius):
    """Half-width of the disc's run in the pixel row centred on `dy`.

    The area-average across the row rather than the width at its centre. It
    costs an arcsin and buys the temporal smoothness the whole node depends on:
    sqrt(r^2 - dy^2) leaves a row with infinite slope, so a row would snap into
    existence at full brightness the instant the radius passed it — measurably,
    a 0.02 px change in radius moved an impulse's edge pixels by 18 code values.
    Integrating over the row instead makes a row fade in as the 3/2 power, and
    the sum of these across every row is exactly pi r^2.
    """
    lo = max(dy - 0.5, -radius)
    hi = min(dy + 0.5, radius)
    if hi <= lo:
        return 0.0
    return _circle_area_to(hi, radius) - _circle_area_to(lo, radius)


def _circle_area_to(y, radius):
    """Antiderivative of sqrt(r^2 - y^2)."""
    y = min(max(y, -radius), radius)
    return 0.5 * (y * math.sqrt(max(0.0, radius * radius - y * y))
                  + radius * radius * math.asin(y / radius))


# Blurring happens in linear light. Averaging gamma-encoded values is averaging
# the wrong numbers: a highlight defocused in sRGB space loses most of its
# energy and the bokeh comes out grey and dead, where in linear light it stays
# bright and reads as an actual out-of-focus highlight. Gamma 2.0 rather than
# the sRGB piecewise curve, because then the encode back is a plain sqrt — the
# error against true sRGB is under a code value and invisible, while pow(1/2.2)
# over a 4K frame is not free.
# Squaring here and sqrt on the way out are a matched pair; changing one without
# the other silently shifts every midtone.
_DECODE = ((np.arange(256, dtype=np.float32) / 255.0) ** 2).astype(np.float32)


def disc_blur(frame, radius):
    """Convolve an (H, W, 3) uint8 RGB frame with a disc of `radius` pixels.

    Returns the frame itself when the radius is under half a pixel, so the sharp
    end of a pull is passed through rather than round-tripped.
    """
    if radius < MIN_RADIUS_PX:
        return frame

    height, width = frame.shape[:2]
    # Rows whose strip overlaps the disc at all, so the outermost pair can carry
    # its sliver of area rather than being dropped.
    rows = int(math.floor(radius + 0.5))
    pad_y = rows
    # A run reaches at most floor(radius + 0.5) = rows columns past the pixel it
    # is centred on; two more than that is comfortably inside.
    pad_x = rows + 2

    lin = _DECODE[frame]
    padded = np.pad(lin, ((pad_y, pad_y), (pad_x, pad_x), (0, 0)), mode="edge")

    # cum[y, j] is the sum of padded[y, :j], which is the integral of the row —
    # read as a piecewise-constant signal — from the left edge to j - 0.5.
    #
    # float32 despite the cancellation a running sum across a 4K row invites:
    # measured against a float64 run of the same algorithm on a deliberately
    # worst-case frame — near-black with scattered blown highlights — the whole
    # 4K frame lands within one code value, and float64 would double both the
    # memory and the time for that.
    cum = np.empty((padded.shape[0], padded.shape[1] + 1, 3), dtype=np.float32)
    cum[:, 0] = 0.0
    np.cumsum(padded, axis=1, out=cum[:, 1:])

    acc = np.zeros((height, width, 3), dtype=np.float32)
    weight = 0.0
    for dy in range(-rows, rows + 1):
        half = _row_half_width(dy, radius)
        if half <= 0.0:
            continue
        # Integrating the row from x - half to x + half. Both bounds land inside
        # a pixel, so each is a whole cumulative-sum entry plus a fraction of the
        # pixel it lands in.
        right = math.floor(half + 0.5)
        left = math.floor(0.5 - half)
        t_right = half + 0.5 - right
        t_left = 0.5 - half - left

        ys = slice(pad_y + dy, pad_y + dy + height)
        xr = pad_x + int(right)
        xl = pad_x + int(left)
        acc += cum[ys, xr:xr + width] - cum[ys, xl:xl + width]
        acc += t_right * padded[ys, xr:xr + width]
        acc -= t_left * padded[ys, xl:xl + width]
        weight += 2.0 * half

    acc /= weight
    # A run over a black region is a difference of two nearly equal cumulative
    # sums, so float32 cancellation can leave it a hair below zero — and sqrt of
    # that is a NaN, which casts to a random byte and shows as a lit speckle in
    # the shadows. Seen on real footage, not theorised.
    np.maximum(acc, 0.0, out=acc)
    np.sqrt(acc, out=acc)
    acc *= 255.0
    acc += 0.5
    return np.clip(acc, 0.0, 255.0).astype(np.uint8)
