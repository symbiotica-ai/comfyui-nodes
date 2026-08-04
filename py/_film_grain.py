# ABOUTME: Film grain maths — luminance-dependent amplitude, grain size from the gauge,
# ABOUTME: per-stock colour behaviour. No I/O and no ComfyUI, so it tests flat and fast.

import math

import numpy as np


# ---------------------------------------------------------------------------
# Luminance response
#
# The one thing that separates emulsion grain from added noise is that it is not
# uniform across the frame: it is strongest in the midtones and falls away in
# deep shadow and in blown highlights. There is a reason, and it is worth
# following because it fixes the shape of the curve rather than leaving it to
# taste.
#
# A layer holds silver halide crystals, and development turns each one either
# fully opaque or leaves it clear — there is no partly developed grain. If
# exposure develops a crystal with probability p, the count developed in a small
# patch is Binomial(N, p) with standard deviation sqrt(N p (1 - p)). Density is
# proportional to the fraction developed, so the density fluctuation — the grain
# — goes as sqrt(p (1 - p)) / sqrt(N).
#
# That is the whole shape. In deep shadow almost nothing developed, so there is
# almost nothing to vary. In a blown highlight almost everything developed, so
# there is almost nothing left to vary. Halfway between, the variance is at its
# maximum. Flat noise across the frame is the tell precisely because it throws
# this away.
#
# Rendered luminance stands in for p, monotonically, which is what lets the
# response be written against the 8-bit value we actually have in hand.
# ---------------------------------------------------------------------------

# Where the response peaks, as a code value in [0, 1]. 18% reflectance — middle
# grey, what a meter aims at — encodes to 0.18 ** (1 / 2.2) = 0.46 in the
# gamma-encoded values the decoder hands us, so the peak belongs there and not
# at the arithmetic middle of the range.
MIDTONE_PEAK = 0.46

# Rec. 709 luma weights, applied to those same gamma-encoded values. That makes
# this luma (Y') rather than luminance, which is the correct choice here: what
# the response needs to know is where the pixel sits on the transfer curve.
LUMA_COEFFS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)


def luma_response(luma, peak=MIDTONE_PEAK):
    """Grain amplitude at a normalised luminance: 1.0 at `peak`, 0 at both ends.

    `luma` may be a scalar or an array. The exponent bends the binomial curve so
    its maximum lands on `peak` rather than on 0.5, without disturbing the two
    things that matter — a single smooth hump, anchored at zero at black and at
    white.
    """
    if not 0.0 < peak < 1.0:
        raise ValueError(f"peak must be between 0 and 1, exclusive: {peak!r}")
    gamma = math.log(0.5) / math.log(peak)
    u = np.clip(np.asarray(luma, dtype=np.float64), 0.0, 1.0) ** gamma
    return 2.0 * np.sqrt(u * (1.0 - u))


def response_lut(peak=MIDTONE_PEAK):
    """The response for every 8-bit luma value.

    Precomputed because the response depends on nothing but the pixel's own
    luminance, and a 256-entry lookup beats a pow and a sqrt over eight million
    pixels a frame.
    """
    return luma_response(np.arange(256) / 255.0, peak).astype(np.float32)


# ---------------------------------------------------------------------------
# Grain size
#
# Grain is not per-pixel. A clump of developed silver is a fixed physical size
# on the emulsion, so how large it lands on screen depends only on how much the
# frame was enlarged to get there — never on the resolution it was scanned at.
# Generating one noise sample per pixel gets this exactly backwards: the grain
# would shrink as the footage got sharper, where the real thing does nothing of
# the kind.
#
# So the grain plate is generated at a resolution the gauge decides and
# resampled up to the frame. A Super 8 frame is 4.01 mm tall against 35mm's
# 18.7 mm, so the same clump is blown up 4.7x more to fill the same screen.
# That ratio is most of why Super 8 looks like Super 8, and it is measured
# rather than chosen.
# ---------------------------------------------------------------------------

# Camera aperture heights in millimetres, from the gauge standards: 35mm full
# aperture 24.9 x 18.7, Super 16 12.52 x 7.41, Super 8 5.79 x 4.01.
FRAME_HEIGHT_MM = {
    "35mm": 18.7,
    "16mm": 7.41,
    "super8": 4.01,
}


def grain_grid(stock, width, height):
    """Rows and columns of the grain plate for a frame this size.

    Cells come out square in frame space — grain has no idea what the aspect
    ratio is — and never finer than the frame itself. A scan cannot resolve
    clumps below its own pixel pitch, and generating them anyway would only cost
    time and alias.
    """
    if width <= 0 or height <= 0:
        raise ValueError("frame has no area")
    gauge = stock["gauge"]
    if gauge not in FRAME_HEIGHT_MM:
        raise ValueError(f"unknown gauge: {gauge!r}")
    rows = int(round(FRAME_HEIGHT_MM[gauge] / (stock["clump_um"] / 1000.0)))
    rows = max(2, min(rows, int(height)))
    cols = max(2, min(int(round(rows * width / float(height))), int(width)))
    return rows, cols


# ---------------------------------------------------------------------------
# Colour
#
# A colour negative is three emulsion layers stacked, and each one grains on its
# own — the dye clouds in the blue-, green- and red-sensitive layers are
# statistically independent, which is why colour grain is speckled with colour
# instead of being grey. A black-and-white stock has a single layer, so its
# grain is pure luminance and nothing else.
#
# The catch is that the decorrelation is only visible while the clumps are large
# enough to see one at a time. On a fine-grain stock a screen pixel averages
# several clumps from every layer, the three layers' fluctuations pull toward
# each other, and what survives reads close to monochrome. So how independent
# the channels are belongs to the stock, not to the module.
#
# Mixing with sqrt weights holds the per-channel variance at 1 whatever that
# number is, so changing a stock's colour behaviour cannot quietly change how
# much grain it has.
# ---------------------------------------------------------------------------

# The blue-sensitive layer sits on top and is the fastest and coarsest of the
# three, the red-sensitive layer the finest, so colour grain leans blue rather
# than being balanced. The mean square of these is 1.00, which is deliberate:
# the balance shifts without the overall level moving with it.
CHANNEL_GAIN = np.array([0.85, 0.98, 1.15], dtype=np.float32)


def grain_plate(rows, cols, chroma, seed, index):
    """One frame's grain at plate resolution, unit variance per channel.

    Reseeded from (seed, index) on every frame. A pattern held fixed across the
    clip is sensor noise, not film: the eye latches onto anything static in a
    moving picture, and grain that does not move is the second tell after grain
    that ignores the tones underneath it.
    """
    if not 0.0 <= chroma <= 1.0:
        raise ValueError(f"chroma must be between 0 and 1: {chroma!r}")
    # Seeded with the pair rather than with seed + index: SeedSequence mixes
    # them, so consecutive frames get unrelated streams instead of adjacent
    # slices of one, and two clips a frame apart in seed do not share grain.
    rng = np.random.default_rng([int(seed), int(index)])
    shared = rng.standard_normal((rows, cols, 1), dtype=np.float32)
    if chroma <= 0.0:
        return np.repeat(shared, 3, axis=2)
    own = rng.standard_normal((rows, cols, 3), dtype=np.float32)
    return (np.float32(math.sqrt(1.0 - chroma)) * shared
            + np.float32(math.sqrt(chroma)) * CHANNEL_GAIN * own)


# ---------------------------------------------------------------------------
# Resampling the plate up to the frame
#
# Straight bilinear leaves a diamond lattice in the noise: the interpolant is
# piecewise linear, so every cell shows its own corners and the eye finds the
# grid. Easing the blend with Perlin's quintic — zero first and second
# derivative at the cell boundaries — turns the same plate into rounded blobs,
# which is what a clump of silver looks like.
#
# Interpolating noise also destroys variance: a point halfway between two
# independent unit samples has variance 1/2, not 1. Left alone that would make
# the coarse stocks quieter than the fine ones at the same nominal sigma, which
# is backwards, so the exact factor is computed from the weights and divided
# back out.
# ---------------------------------------------------------------------------

def _resample_axis(n_src, n_dst):
    """Source index pair and blend weight for each output sample along one axis.

    Half-sample-centred, the convention every image resampler uses: output
    sample i covers source coordinate (i + 0.5) * n_src / n_dst - 0.5. Getting
    this wrong shifts the whole grain plate half a cell, which is invisible on
    35mm and obvious on Super 8.
    """
    if n_src < 1 or n_dst < 1:
        raise ValueError("resampling needs at least one sample on each side")
    pos = (np.arange(n_dst, dtype=np.float64) + 0.5) * (n_src / float(n_dst)) - 0.5
    base = np.floor(pos)
    frac = pos - base
    index = base.astype(np.int64)
    lo = np.clip(index, 0, n_src - 1)
    hi = np.clip(index + 1, 0, n_src - 1)
    weight = frac * frac * frac * (frac * (frac * 6.0 - 15.0) + 10.0)
    return lo, hi, weight.astype(np.float32)


def _axis_variance(lo, hi, weight):
    """Fraction of the noise variance that survives this axis' interpolation.

    Where the two source indices coincide — the clamped samples at the edges —
    the blend is between a value and itself, so nothing is lost there.
    """
    kept = np.where(lo == hi, 1.0,
                    (1.0 - weight) ** 2 + np.asarray(weight, dtype=np.float64) ** 2)
    return float(kept.mean())


def make_resampler(rows, cols, height, width):
    """Return fn(plate) -> (height, width, 3) float32, variance corrected.

    The index and weight tables depend on nothing but the geometry, so they are
    built once for the clip instead of once per frame.

    Only ever asked to enlarge: grain_grid() caps the plate at the frame's own
    resolution, so a two-tap filter is enough and there is no shrinking pass to
    alias.
    """
    ly, hy, wy = _resample_axis(rows, height)
    lx, hx, wx = _resample_axis(cols, width)
    gain = np.float32(1.0 / math.sqrt(_axis_variance(ly, hy, wy)
                                      * _axis_variance(lx, hx, wx)))
    wy = wy[:, None, None]
    wx = wx[None, :, None]

    def resample(plate):
        rows_ = plate[ly] * (1.0 - wy) + plate[hy] * wy
        return (rows_[:, lx] * (1.0 - wx) + rows_[:, hx] * wx) * gain

    return resample


# ---------------------------------------------------------------------------
# Stocks
#
# Four, spanning the range that matters: a modern fine-grain 35mm colour
# negative, the 35mm black-and-white everyone reaches for, the 16mm tungsten
# stock that defines the grainy-documentary look, and Super 8.
#
# `clump_um` is the clump diameter on the emulsion in microns. The anchor is ISO
# 10505, which measures RMS granularity through a 48 um aperture — a clump has
# to sit well inside that — together with the arithmetic that a 4K scan of a
# 35mm frame is 8.7 um per pixel, where colour negative grain reads as roughly
# two pixels. The ordering (a 500T is coarser than a 250D, a small-gauge
# reversal stock coarser again) is the solid part; the absolute figures are set
# to land those ratios on screen rather than read off a datasheet.
#
# `sigma` is the peak grain amplitude in 8-bit code values, at strength 1.0 and
# at the midtone where the response peaks. Picked so the stock's own normal
# amount is what strength 1.0 gives you, and strength is a multiplier on
# something sane rather than the only thing between the operator and a blizzard.
# ---------------------------------------------------------------------------

STOCKS = {
    #                   gauge              clump_um  chroma  sigma
    "35mm":      dict(gauge="35mm",   clump_um=18.0, chroma=0.25, sigma=4.0),
    "35mm B&W":  dict(gauge="35mm",   clump_um=26.0, chroma=0.00, sigma=8.0),
    "16mm":      dict(gauge="16mm",   clump_um=24.0, chroma=0.45, sigma=8.5),
    "Super 8":   dict(gauge="super8", clump_um=30.0, chroma=0.55, sigma=13.0),
}

DEFAULT_PRESET = "35mm"


def preset_choices():
    """Dropdown contents, finest grain first."""
    return list(STOCKS)


def resolve_preset(preset):
    """The stock constants for a preset name, as a copy the caller may edit."""
    if preset not in STOCKS:
        raise ValueError(f"unknown preset: {preset!r}")
    return dict(STOCKS[preset])


def grain_size_px(preset, width, height):
    """How large one grain clump lands on screen, in pixels.

    The number that has to move with the resolution rather than stay put: the
    same stock on the same framing is the same fraction of the frame at 2K and
    at 4K, which means twice as many pixels across at 4K. It stops tracking only
    once the clump falls under one pixel, where the scan, not the emulsion, is
    what is limiting.
    """
    rows, _ = grain_grid(resolve_preset(preset), width, height)
    return height / float(rows)


# ---------------------------------------------------------------------------
# The effect
# ---------------------------------------------------------------------------

def make_grain(preset, width, height, strength=1.0, seed=0, peak=MIDTONE_PEAK):
    """Return fn(frame, index, info) -> grained frame, ready for process().

    Everything that depends only on the geometry — the plate size, the
    resampling tables, the response lookup — is built here, once for the clip.
    Only the plate itself is rolled per frame.
    """
    if strength < 0.0:
        raise ValueError(f"strength must be >= 0: {strength!r}")
    stock = resolve_preset(preset)
    rows, cols = grain_grid(stock, width, height)
    resample = make_resampler(rows, cols, height, width)
    # Folded into the lookup rather than multiplied over the frame: it is 256
    # numbers here against eight million there.
    lut = response_lut(peak) * np.float32(stock["sigma"] * strength)
    chroma = float(stock["chroma"])
    seed = int(seed)

    def apply(frame, index, info=None):
        noise = resample(grain_plate(rows, cols, chroma, seed, index))
        luma = frame @ LUMA_COEFFS
        # The coefficients sum to 1, so this cannot exceed 255 by more than a
        # float32 rounding — but that rounding would wrap the cast to 0 and put
        # full grain on a blown highlight.
        amount = lut[np.clip(luma, 0.0, 255.0).astype(np.uint8)]
        # In place from here: at 4K every one of these is a hundred megabytes.
        noise *= amount[:, :, None]
        noise += frame
        np.clip(noise, 0.0, 255.0, out=noise)
        return noise.astype(np.uint8)

    return apply
