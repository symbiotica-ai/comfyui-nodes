# ABOUTME: Chromatic aberration maths — per-channel radial sampling maps and the
# ABOUTME: bilinear gather that applies them. Pure numpy so it tests without ffmpeg.

import math

import numpy as np

# ---------------------------------------------------------------------------
# Which way each channel goes
#
# Lateral chromatic aberration is a magnification that differs with wavelength:
# the three channels form images of slightly different sizes, so a point away
# from the optical axis lands in a slightly different place in each. That is why
# the fringe is radial, why it is zero on the axis, and why it is a colour split
# rather than a blur.
#
# Cauchy's n(lambda) = A + B/lambda**2 makes the index error, and so the
# magnification error, go as 1/lambda**2. Referencing every channel to green
# gives green exactly zero and puts red and blue on opposite sides of it, which
# is the shape of the real thing: a lens that images green correctly images red
# a touch small and blue a touch large, or the reverse.
#
# Taking the primaries' own wavelengths rather than assuming a symmetric pair is
# what gets the asymmetry right — blue lands about twice as far out as red, so
# the outer fringe reads blue-violet and the inner one a weak cyan-red. A
# mirrored +/-1 pair is the giveaway of an effect that was guessed at.
# ---------------------------------------------------------------------------

# Dominant wavelengths of the Rec.709 / sRGB primaries, in nanometres.
_PRIMARY_NM = (611.0, 549.0, 464.0)


def _channel_shifts(primaries=_PRIMARY_NM):
    """Outward displacement of each channel per unit of red-to-blue separation.

    Normalised so the two outer channels are 1.0 apart. That is what lets
    `strength` be read straight off as pixels of fringe at the corner.

    Which of the two goes outward is a property of the lens design and real
    ones do both; what is not a choice is that they go opposite ways.
    """
    red, green, blue = (1.0 / (nm * nm) for nm in primaries)
    d_red, d_blue = red - green, blue - green
    span = abs(d_red) + abs(d_blue)
    return (d_red / span, 0.0, d_blue / span)


CHANNEL_SHIFTS = _channel_shifts()

# Index of the reference channel, the one that is never resampled. Leaving the
# channel that carries ~71% of the luminance completely untouched is why the
# picture does not soften: all the resampling lands where the eye resolves
# least, which is also where the real aberration lives.
GREEN = 1


# ---------------------------------------------------------------------------
# How it grows across the frame
#
# The Seidel expansion puts primary lateral colour linear in field height and
# the next order cubic. Measured lenses bulge toward the corner rather than
# rising in a straight line, so most of the weight belongs on the cubic term.
# At the split below, mid-field carries about a quarter of the corner fringe
# where a pure magnification error would put half of it there. The exact number
# is taste within what the expansion allows; a linear-only profile is not — it
# spreads visible fringing across the middle of the frame, where a real lens has
# effectively none.
# ---------------------------------------------------------------------------

_CUBIC_SHARE = 0.65


def _profile_over_rho(rho_squared):
    """field_profile(rho) / rho, taken from rho**2.

    The sampling map needs the fringe per unit radius rather than the fringe
    itself, and dividing the profile out algebraically removes the 0/0 at the
    optical centre instead of special-casing the middle pixel.
    """
    return (1.0 - _CUBIC_SHARE) + _CUBIC_SHARE * rho_squared


def field_profile(rho):
    """Fringe size at normalised field height `rho`: 0 at the centre, 1 at the corner."""
    rho = np.asarray(rho, dtype=np.float64)
    return rho * _profile_over_rho(rho * rho)


# Red-to-blue separation at the corner, in pixels, at strength 1.0 on a
# 1080x1920 frame. Several times what a corrected modern lens leaves and about
# what a fast vintage wide gives wide open: obvious once you look at a corner,
# invisible in the middle. Held against the half-diagonal so the same strength
# is the same effect at any resolution.
REFERENCE_CORNER_SPLIT_PX = 3.0
_REFERENCE_HALF_DIAGONAL = math.hypot(1080.0, 1920.0) / 2.0


def corner_split_px(width, height, strength=1.0):
    """Red-to-blue separation at the frame corner, in pixels."""
    return (strength * REFERENCE_CORNER_SPLIT_PX
            * math.hypot(width, height) / 2.0 / _REFERENCE_HALF_DIAGONAL)


def sampling_maps(width, height, strength=1.0):
    """Source coordinates each channel reads from, as (sx, sy) float32 planes.

    One entry per channel in RGB order; green's is None because it is the
    reference and is never resampled.

    The maps depend only on the geometry, so a clip builds them once. Sampling
    inward is what displaces the content outward, hence the sign.
    """
    if width < 2 or height < 2:
        raise ValueError(f"frame is too small to aberrate: {width}x{height}")

    # Pixel centres sit on integers, so the frame centre is (n - 1) / 2 and the
    # map comes out exactly symmetric about it.
    cx = (width - 1) / 2.0
    cy = (height - 1) / 2.0
    r_corner = math.hypot(cx, cy)

    vx = (np.arange(width, dtype=np.float32) - cx)[None, :]
    vy = (np.arange(height, dtype=np.float32) - cy)[:, None]
    rho_squared = (vx * vx + vy * vy) / (r_corner * r_corner)

    # Fringe per unit radius: the same field for every channel, so it is built
    # once and only the per-channel amplitude changes.
    per_radius = (corner_split_px(width, height, strength)
                  * _profile_over_rho(rho_squared) / r_corner)

    maps = []
    for amplitude in CHANNEL_SHIFTS:
        if amplitude == 0.0:
            maps.append(None)
            continue
        factor = 1.0 - amplitude * per_radius
        maps.append((np.asarray(cx + vx * factor, dtype=np.float32),
                     np.asarray(cy + vy * factor, dtype=np.float32)))
    return tuple(maps)


def sample_bilinear(plane, sx, sy):
    """Read `plane` at fractional (sx, sy). Returns float32.

    Bilinear rather than a whole-pixel roll because the displacement is under a
    pixel across most of the frame: rounding it to an integer would hold the
    channel still through the middle and then jump it, which shows as concentric
    rings of colour instead of a smooth fringe.

    Coordinates are clamped, not wrapped or filled. The inward-displaced channel
    reads past the edge along every side, and anything but the edge pixel there
    arrives as a coloured or black rim around the frame.
    """
    height, width = plane.shape
    x = np.clip(sx, 0.0, width - 1.0)
    y = np.clip(sy, 0.0, height - 1.0)

    x0 = np.floor(x).astype(np.int32)
    y0 = np.floor(y).astype(np.int32)
    x1 = np.minimum(x0 + 1, width - 1)
    y1 = np.minimum(y0 + 1, height - 1)
    fx = (x - x0).astype(np.float32)
    fy = (y - y0).astype(np.float32)

    top = plane[y0, x0] * (1.0 - fx) + plane[y0, x1] * fx
    bottom = plane[y1, x0] * (1.0 - fx) + plane[y1, x1] * fx
    return top * (1.0 - fy) + bottom * fy


def apply_maps(frame, maps):
    """Resample each channel through its own map, leaving green alone."""
    out = frame.copy()
    for channel, entry in enumerate(maps):
        if entry is None:
            continue
        sx, sy = entry
        resampled = sample_bilinear(frame[:, :, channel], sx, sy)
        out[:, :, channel] = np.clip(np.rint(resampled), 0, 255).astype(np.uint8)
    return out


def make_effect(strength):
    """A fn(frame, index, info) for _video_fx.process().

    The maps are geometry, not content, so they are built on the first frame and
    reused for the rest of the clip.
    """
    maps = None

    def effect(frame, index, info):
        nonlocal maps
        if maps is None:
            maps = sampling_maps(frame.shape[1], frame.shape[0], strength)
        return apply_maps(frame, maps)

    return effect
