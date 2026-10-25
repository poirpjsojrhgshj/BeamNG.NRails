"""Seasons in the imagery (the user, 2026-10-14: colour-correct Maryland's leaf-off photos, "we could use this
later for different seasons depending on the time of year; it's currently fall and trees are changing colour").

Two steps on a rendered texture (imagery.Imagery.render; the block's photo and every far tile go through it, so
they agree):
  1. leaf_on: a leaf-off source (Maryland's six-inch photos, flown in early spring: dormant grass, bare branches)
     takes the colour of the summer reference (the USGS / NAIP mosaic, the rest of the chain) where that
     reference is vegetation: its chroma at the reference's ~8 m scale and, partly, its brightness (a leafy canopy
     is darker than bare twigs over leaf litter); the photo's own detail stays. Roofs, roads, dirt and water keep
     their colours (the reference is not green there).
  2. grade: from that summer look toward the season of the date at the place (season_amounts): fall turns the
     tree canopy yellow / orange / rust in patches (world-anchored noise, so tiles and anchors agree) and yellows
     everything green a little; the share of turned trees grows with the amount. Winter and spring: later.
Pure functions of their inputs (no state); numpy only.
"""
import datetime

import numpy as np
from PIL import Image, ImageFilter

import fast

M_PER_DEG = 111320.0
# leaf_on: the reference is vegetation where its green chromaticity g / (r + g + b) is above this (summer USGS at
# Columbia: canopy and grass 0.35-0.38, pavement and roofs ~0.33)
VEG_CHROMA = (0.345, 0.37)
LEAF_ON_LUM = 0.8           # share of the reference's large-scale brightness taken in vegetation
LUM_GAIN = (0.5, 1.5)
# grade: canopy = vegetation that is darker and textured at the 2-3 m scale (lawns and verges are smooth and light)
VEG_HUE = (60.0, 75.0, 160.0, 175.0)        # deg: green between the ramps
CANOPY_V = (0.44, 0.52)                     # value above which it is not canopy
CANOPY_STD = (0.012, 0.028)                 # local std (value) below which it is not canopy
FALL_PALETTE = ((46.0, 1.12, 1.05), (30.0, 1.02, 1.10), (18.0, 0.92, 1.0))   # (hue deg, value x, sat x): yellow, orange, rust
FALL_YELLOW = 0.35          # every green pixel's hue moves this share toward yellow at full fall
PATCH_M = (18.0, 6.0, 25.0)  # noise scales: stands, single trees, colour regions
NOISE_GRID = 128            # the noise is computed on at most this many cells a side and interpolated
CANOPY_TEXTURE_MAX_M = 2.5  # coarser texels: the canopy by brightness only
FALL_PEAK_DOY_40N = 300     # ~Oct 27 at 40 degrees; 2.5 days earlier per degree further from the equator
FALL_HALF_DAYS = 28.0
WINTER_BARE_DESAT = 0.7     # saturation lost by bare canopy at full winter


def _smooth(x, a, b):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


WINTER_DOY_40N = (330, 365 + 60)   # bare from ~Nov 26 to ~Mar 1 at 40 N (ramps of WINTER_RAMP_DAYS either side)
WINTER_RAMP_DAYS = 20.0
SPRING_PEAK_DOY_40N = 112           # ~Apr 22: the fresh flush
SPRING_HALF_DAYS = 22.0


def season_amounts(date, lat):
    """{"fall", "winter", "spring": 0..1} at a date (datetime.date) and latitude: how far the leaves have turned,
    how bare the deciduous canopy is, how fresh the spring flush is (0 in the tropics; the southern hemisphere half a
    year later; 2.5 days earlier per degree north for fall, later for spring). Pure."""
    if abs(lat) < 23.0:
        return {"fall": 0.0, "winter": 0.0, "spring": 0.0}
    doy = date.timetuple().tm_yday
    if lat < 0:
        doy = (doy + 182) % 365
    shift = (abs(lat) - 40.0) * 2.5
    fall = max(0.0, 1.0 - abs(doy - (FALL_PEAK_DOY_40N - shift)) / FALL_HALF_DAYS)
    w0, w1 = WINTER_DOY_40N[0] - shift, WINTER_DOY_40N[1] + shift
    d = doy if doy >= w0 - WINTER_RAMP_DAYS else doy + 365          # Jan-Mar count from the previous year
    winter = min(max(0.0, (d - (w0 - WINTER_RAMP_DAYS)) / WINTER_RAMP_DAYS),
                 max(0.0, (w1 + WINTER_RAMP_DAYS - d) / WINTER_RAMP_DAYS), 1.0)
    spring = max(0.0, 1.0 - abs(doy - (SPRING_PEAK_DOY_40N + shift)) / SPRING_HALF_DAYS)
    return {"fall": float(fall), "winter": float(winter), "spring": float(spring)}


def amounts_for(mode, lat, today=None):
    """season_amounts for --season: "auto" (today's date), "off" (none), "fall" / "winter" / "spring" (full)."""
    if mode in ("fall", "winter", "spring"):
        return {"fall": 0.0, "winter": 0.0, "spring": 0.0, mode: 1.0}
    if mode == "auto":
        return season_amounts(today or datetime.date.today(), lat)
    return {"fall": 0.0, "winter": 0.0, "spring": 0.0}


def leaf_on(rgb, ref):
    """rgb (uint8 [h, w, 3], a leaf-off photo already matched to ref at the large scale) with the summer reference
    ref's (coarser uint8) colour in its vegetation: chroma, and LEAF_ON_LUM of the brightness, at ref's scale."""
    h, w = rgb.shape[:2]
    rim = Image.fromarray(ref, "RGB").filter(ImageFilter.GaussianBlur(1.0))
    c = np.asarray(rim, np.float32)
    veg = _smooth(c[..., 1] / (c.sum(-1) + 1.0), *VEG_CHROMA)
    if not (veg > 0.01).any():
        return rgb
    vw = np.asarray(Image.fromarray(veg.astype(np.float32), "F").resize((w, h), Image.BILINEAR))
    ycc = np.asarray(Image.fromarray(rgb, "RGB").convert("YCbCr"), np.float32).copy()
    rc = np.asarray(rim.resize((w, h), Image.BILINEAR).convert("YCbCr"), np.float32)
    ycc[..., 1:] += vw[..., None] * (rc[..., 1:] - ycc[..., 1:])
    # brightness: ratio of the reference's to ours, both at ref's texels
    small = (ref.shape[1], ref.shape[0])
    ys = np.asarray(Image.fromarray(rgb, "RGB").resize(small, Image.BOX).convert("L")
                    .filter(ImageFilter.GaussianBlur(1.0)), np.float32)
    yr = np.asarray(rim.convert("L"), np.float32)
    g = np.clip((yr + 4.0) / (ys + 4.0), *LUM_GAIN)
    g = np.asarray(Image.fromarray(g.astype(np.float32), "F").resize((w, h), Image.BILINEAR))
    ycc[..., 0] *= 1.0 + vw * LEAF_ON_LUM * (g - 1.0)
    out = Image.fromarray(np.clip(np.rint(ycc), 0, 255).astype(np.uint8), "YCbCr").convert("RGB")
    return np.asarray(out)


def _box(a, r):
    """Mean of a (float) over (2r+1)² windows, edges clamped."""
    p = np.pad(a.astype(np.float64), r + 1, mode="edge")
    c = p.cumsum(0).cumsum(1)
    k = 2 * r + 1
    out = c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]
    return (out[:a.shape[0], :a.shape[1]] / (k * k)).astype(np.float32)


def _noise(x, y, seed):
    """Smooth value noise in [0, 1] on a unit lattice (x, y float arrays of one shape) (earthfast.season_noise)."""
    fast.require(1, "season noise")
    x, y = np.asarray(x, np.float32), np.asarray(y, np.float32)
    shape = x.shape
    flat = lambda a: np.ascontiguousarray(a.reshape(1, -1) if a.ndim != 2 else a)     # noqa: E731 (the kernel: 2-D)
    return fast._ef.season_noise(flat(x), flat(y), int(seed)).reshape(shape)



GRADE_HALF_PX = 512         # textures this big are graded at half size and applied as a colour ratio


def grade(rgb, xm, ym, amounts):
    """season grade (grade_full) of rgb; at GRADE_HALF_PX or more, computed on a half-size copy and applied as a
    per-channel ratio (the colour change is a few metres coarse at most, the detail stays the texture's own)."""
    if not any(float(amounts.get(k, 0.0)) > 0.0 for k in ("fall", "winter", "spring")):
        return rgb
    hh, ww = rgb.shape[:2]
    if min(hh, ww) < GRADE_HALF_PX:
        return grade_full(rgb, xm, ym, amounts)
    sm = (ww // 2, hh // 2)
    small = np.asarray(Image.fromarray(rgb, "RGB").resize(sm, Image.BOX))
    g = grade_full(small, xm[::2, ::2][:sm[1], :sm[0]], ym[::2, ::2][:sm[1], :sm[0]], amounts)
    if g is small:
        return rgb
    ratio = (g.astype(np.float32) + 2.0) / (small.astype(np.float32) + 2.0)
    up = np.stack([np.asarray(Image.fromarray(ratio[..., c], "F").resize((ww, hh), Image.BILINEAR)) for c in range(3)], -1)
    return np.clip(np.rint(rgb.astype(np.float32) * up), 0, 255).astype(np.uint8)


def grade_full(rgb, xm, ym, amounts):
    """rgb (uint8, a summer look) toward the season: amounts {"fall": 0..1}; xm, ym (float [h, w]) the texels'
    world position in metres (east, north: noise anchored to the world). Unchanged when every amount is 0. Only
    the vegetation's texels are converted; the noise is computed on a grid of ~2 m and interpolated."""
    fall = float(amounts.get("fall", 0.0))
    winter = float(amounts.get("winter", 0.0))
    spring = float(amounts.get("spring", 0.0))
    if fall <= 0.0 and winter <= 0.0 and spring <= 0.0:
        return rgb
    fast.require(1, "season grade")
    return _grade_rust(np.ascontiguousarray(np.asarray(rgb, np.uint8)[..., :3]), xm, ym, fall, winter, spring)


def _noise_and_canopy(v, xm, ym, hh, ww):
    """grade_full's canopy (h, w) and noise n, pick (h, w), float32."""
    texel = max(1e-3, float(abs(xm[0, -1] - xm[0, 0])) / max(1, ww - 1))
    if texel <= CANOPY_TEXTURE_MAX_M:
        m1 = _box(v, 2)
        std = np.sqrt(np.clip(_box(v * v, 2) - m1 * m1, 0.0, None))
        canopy = _smooth(std, *CANOPY_STD) * (1.0 - _smooth(m1, *CANOPY_V))
    else:
        canopy = 1.0 - _smooth(v, *CANOPY_V)
    f = max(1, int(2.0 / texel), -(-max(hh, ww) // NOISE_GRID))
    xs, ys = xm[::f, ::f], ym[::f, ::f]

    def up(a):
        return a if f == 1 else np.asarray(Image.fromarray(a.astype(np.float32), "F").resize((ww, hh), Image.BILINEAR))
    n = up(0.75 * _noise(xs / PATCH_M[0], ys / PATCH_M[0], 1) + 0.25 * _noise(xs / PATCH_M[1], ys / PATCH_M[1], 2))
    pick = up(_noise(xs / PATCH_M[2], ys / PATCH_M[2], 3))
    return canopy, n, pick


_PAL32 = np.array(FALL_PALETTE, np.float32)


def _grade_rust(rgb, xm, ym, fall, winter, spring):
    """grade_full by the Rust kernel (earthfast.season_grade; the noise and canopy as above). ~2/3 of a far tile's season grade was numpy's masked indexing (~14 s of a teleport's far threads)."""
    hh, ww = rgb.shape[:2]
    # rgb.max(-1) without the strided reduction (the same bytes)
    v = np.maximum(np.maximum(rgb[..., 0], rgb[..., 1]), rgb[..., 2]).astype(np.float32) / 255.0
    canopy, n, pick = _noise_and_canopy(v, xm, ym, hh, ww)
    f32 = lambda a: np.ascontiguousarray(np.broadcast_to(np.asarray(a, np.float32), (hh, ww)))  # noqa: E731
    out = fast._ef.season_grade(np.ascontiguousarray(rgb), f32(n), f32(pick), f32(canopy), fall, winter, spring,
                                _PAL32, FALL_YELLOW, WINTER_BARE_DESAT)
    return rgb if out is None else out


def world_metres(lat, lon):
    """(east, north) metres of geodetic arrays, on a fixed world grid (noise anchors). Pure."""
    lat = np.asarray(lat, np.float64)
    return (np.asarray(lon, np.float64) * M_PER_DEG * np.cos(np.radians(lat))).astype(np.float32), \
        (lat * M_PER_DEG).astype(np.float32)
