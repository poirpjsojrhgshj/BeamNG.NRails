"""Per-tile cost of the relight with region-level parameters precomputed: what the server would
run per 256 px source tile. Region params (once per region / source tile block): sun, haze, rho,
the two class Gaussians of the shadow classifier. Per tile: horizon (from the padded DEM at 7.7 m),
Lambert, Bayes snap, gain, chroma smoothing."""
import sys, time, json
import numpy as np
from lib import *
from deshadow import features, chroma_smooth, upsample

M = 8   # filter margin (px) around the 256 tile

def region_params(rgb, hpad, res, P, az, el):
    """Reuse deshadow.method_a's machinery on the region once, keep the scalars."""
    import deshadow as ds
    W = rgb.shape[0]
    lit_w, lam_w, sh = ds.terrain_terms(hpad, res, P, W, az, el)
    I = to_lin(rgb)
    lit_dem = upsample(lit_w, 4, W, sh)
    blur = box((lit_dem > 0.5).astype(np.float32), 40)
    X = features(I)
    rng = np.random.default_rng(0)
    def gauss(m):
        x = X[m]; x = x[rng.choice(len(x), min(20000, len(x)), replace=False)]
        C = np.cov(x.T) + np.eye(2) * 1e-5
        return x.mean(0).astype(np.float32), np.linalg.inv(C).astype(np.float32), float(np.log(np.linalg.det(C))), float(np.sqrt(C[0, 0]))
    info = json.load(open(f"data/{name}_info.json"))
    return dict(gs=gauss(blur < 0.01), gl=gauss(blur > 0.99), haze=np.float32(info["haze"]),
                rho=np.float32(info["amb_over_sun"]), az=az, el=el)

def tile_horizon(hpad, res, P, ty, tx, az, el, f=4, cells=64 + 4):
    """lit/lambert on the 7.7 m work grid for one tile (+2 cells margin), marching the padded DEM."""
    off = P % f
    if (id(hpad), f) not in HP_CACHE:   # region-level: the padded DEM on the 7.7 m work grid
        HP_CACHE[(id(hpad), f)] = down(hpad[off:, off:], f)
        HP_CACHE[("max", id(hpad))] = float(HP_CACHE[(id(hpad), f)].max())
    hp = HP_CACHE[(id(hpad), f)]
    pad = (P - off) // f
    cy, cx = pad + ty // f - 2, pad + tx // f - 2
    yy, xx = np.mgrid[cy:cy + cells, cx:cx + cells].astype(np.float32)
    h0 = hp[cy:cy + cells, cx:cx + cells]
    s, c = np.sin(np.radians(az)), np.cos(np.radians(az))
    best = np.full(h0.shape, -1e9, np.float32); d = res * f
    hmax = HP_CACHE[("max", id(hpad))]  # region max (a max-pyramid in production)
    dmax = min(1500.0, (hmax - float(h0.min())) / np.tan(np.radians(el)) + res * f)
    while d <= dmax:
        np.maximum(best, (bilin(hp, yy - c * d / (res * f), xx + s * d / (res * f)) - h0) / d, out=best)
        d = max(d + res * f, d * 1.04)
    t = np.tan(np.radians(el))
    lit = np.clip(0.5 + (t - best) / 0.1, 0, 1)
    lam = lambert(normals(box(h0, 1), res * f), az, el)
    return lit.astype(np.float32), lam.astype(np.float32), box((lit > 0.5).astype(np.float32), 10)

HP_CACHE = {}

STATS = {"fast": 0, "snap": 0}

def apply_tile(rgb_t, lit_w, lam_w, R, lam_strength=0.7, gmax=10.0, lit_w_blur=None):
    n = rgb_t.shape[0]
    I = to_lin(rgb_t)
    # work grid -> tile pixels (the work grid starts 2 cells = 8 px before the tile's margin)
    from PIL import Image
    big = lambda a: np.asarray(Image.fromarray(a, "F").resize((a.shape[1] * 4, a.shape[0] * 4), Image.BILINEAR))
    lit_dem = big(lit_w)[8 - M:8 - M + n, 8 - M:8 - M + n]
    lam = big(lam_w)[8 - M:8 - M + n, 8 - M:8 - M + n]
    blur = big(lit_w_blur)[8 - M:8 - M + n, 8 - M:8 - M + n] if lit_w_blur is not None else lit_dem
    if blur.min() > 0.99 or blur.max() < 0.01:
        lit = lit_dem                   # fast path: no terminator within ~77 m of this tile
        STATS["fast"] += 1
    else:
        STATS["snap"] += 1
        Ih2 = down(I, 2)                # likelihood at half resolution (3.8 m), edges re-snapped below
        X = features(Ih2)
        def ll(g):
            d0, d1 = X[..., 0] - g[0][0], X[..., 1] - g[0][1]
            A = g[1]
            return -0.5 * (A[0, 0] * d0 * d0 + 2 * A[0, 1] * d0 * d1 + A[1, 1] * d1 * d1 + g[2])
        llr = np.clip(ll(R["gs"]) - ll(R["gl"]), -12, 12)
        llr = np.repeat(np.repeat(llr, 2, 0), 2, 1)
        prior = np.clip(1 - blur, 0.03, 0.97)
        lit = 1 - 1 / (1 + np.exp(-(np.log(prior / (1 - prior)) + llr)))
        g = np.log(box(luma(I), 1) + 1e-3); g = (g - g.mean()) / (g.std() + 1e-6) * 0.25
        lit = np.clip((guided(g, lit, 2, 0.01) - 0.5) * 3 + 0.5, 0, 1)
        lp = np.log(luma(I) + 1e-4)
        lit = np.maximum(lit, np.clip((lp - (R["gs"][0][0] + 2.5 * R["gs"][3])) / 0.3, 0, 1))
    sz = np.sin(np.radians(R["el"]))
    lam = sz + lam_strength * (lam - sz)
    direct = (lam * lit)[..., None]
    if np.abs(direct - sz).max() < 0.01:  # flat and sunlit: nothing to undo
        STATS["noop"] = STATS.get("noop", 0) + 1
        return rgb_t[M:-M, M:-M].copy()
    Ih = np.maximum(I - R["haze"], 0)
    lam3 = lam[..., None]
    gain = np.clip((R["rho"] + sz) / (R["rho"] + lam3), 1 / 1.6, 1.6) * (R["rho"] + lam3) / (R["rho"] + direct)
    gain = gain * np.minimum(1, gmax / gain.max(-1, keepdims=True))
    out = Ih * gain + R["haze"]
    gl_ = luma(gain)
    if gl_.max() > 1.5:                 # only boosted shadows carry amplified chroma noise
        out = chroma_smooth(out, np.clip((gl_ - 1) / 3, 0, 1))
    out = out[M:-M, M:-M]
    q = np.clip(out * 4095 + 0.5, 0, 4095).astype(np.int16)
    return LIN2SRGB_SHOULDER[q]

_l = np.arange(4096) / 4095.0
_l = np.where(_l > 0.8, 0.8 + 0.2 * np.tanh((_l - 0.8) / 0.2), _l)
LIN2SRGB_SHOULDER = to_srgb(_l)

if __name__ == "__main__":
    name = sys.argv[1]; az, el = float(sys.argv[2]), float(sys.argv[3])
    d = np.load(f"data/{name}.npz"); rgb, hpad, res, P = d["rgb"], d["h"], float(d["res"]), int(d["pad"])
    t = time.perf_counter(); R = region_params(rgb, hpad, res, P, az, el); tr = time.perf_counter() - t
    W = rgb.shape[0]
    out = np.zeros_like(rgb); th, ta = [], []
    for ty in range(64, W - 256 - 64, 256):
        for tx in range(64, W - 256 - 64, 256):
            t0 = time.perf_counter()
            lw, mw, bw = tile_horizon(hpad, res, P, ty - M, tx - M, az, el)
            t1 = time.perf_counter()
            o = apply_tile(rgb[ty - M:ty + 256 + M, tx - M:tx + 256 + M], lw, mw, R, lit_w_blur=bw)
            t2 = time.perf_counter()
            out[ty:ty + 256, tx:tx + 256] = o
            th.append(t1 - t0); ta.append(t2 - t1)
    ta = np.array(ta)
    print(f"  relight ms: all median {np.median(ta)*1000:.1f} p90 {np.percentile(ta,90)*1000:.1f} max {ta.max()*1000:.1f}; {STATS}")
    print(f"{name}: region params {tr*1000:.0f} ms; per 256 px tile: horizon {np.median(th)*1000:.1f} ms, "
          f"relight {np.median(ta)*1000:.1f} ms (median of {len(ta)})")
    from PIL import Image
    Image.fromarray(out).save(f"data/{name}_tiled.png")
