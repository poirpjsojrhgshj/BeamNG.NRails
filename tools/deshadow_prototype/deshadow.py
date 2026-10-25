"""Relight (de-shadow) a window given the fitted sun. Two methods:
  A  physical: albedo = I / (amb_c + sun_c * lambert * lit), re-lit as flat ground in sun
  B  fallback: per-channel gain matching of shadowed pixels to nearby sunlit pixels of similar cover
"""
import sys, time, json
import numpy as np
from PIL import Image
from lib import *

def terrain_terms(hpad, res, P, W, az, el, f=4, soft=0.05):
    """lit fraction (soft) and Lambert at the work resolution res*f, for the W x W window."""
    off = P % f
    hp = down(hpad[off:, off:], f)
    pad, n = (P - off) // f, -(-W // f)
    hw = hp[pad:pad + n, pad:pad + n]
    ht = horizon_tan(hp, res * f, pad, n, az)
    t = np.tan(np.radians(el))
    lit = np.clip(0.5 + (t - ht) / (2 * soft), 0, 1)          # soft terminator (DEM noise)
    lam = lambert(normals(box(hw, 1), res * f), az, el)
    return lit.astype(np.float32), lam.astype(np.float32), off / f

def upsample(a, f, W, shift):
    """Work grid (cell centres at (i+0.5)*f - shift*f... ) -> W x W fine grid."""
    n = a.shape[0]
    yy = (np.arange(W) + 0.5 + shift * f) / f - 0.5
    Y, X = np.meshgrid(yy, yy, indexing="ij")
    return bilin(np.pad(a, 1, mode="edge"), Y + 1, X + 1).astype(np.float32)

def snap(lit, L, r=6, eps=0.02):
    """Guided filter of the DEM lit mask with log luminance as guide: moves the coarse
    terminator onto the image's own shadow edge (within ~r px), no halo."""
    g = np.log(box(L, 1) + 1e-3)
    g = (g - g.mean()) / (g.std() + 1e-6) * 0.25
    return np.clip(guided(g, lit, r, eps), 0, 1)

def fit_light(I, direct, mask=None, nb=12):
    """Per channel I_c ~ alpha_c + beta_c * direct: line through binned medians (robust to
    albedo outliers), weighted by bin counts."""
    d = direct.ravel()
    edges = np.quantile(d, np.linspace(0, 1, nb + 1))
    idx = np.clip(np.searchsorted(edges, d, side="right") - 1, 0, nb - 1)
    xs, ys, ws = [], [], []
    for b in range(nb):
        m = idx == b
        if m.sum() < 50: continue
        xs.append(np.median(d[m])); ys.append(np.median(I.reshape(-1, 3)[m], axis=0)); ws.append(m.sum())
    xs, ys, ws = np.array(xs), np.array(ys), np.array(ws, float)
    A = np.stack([np.ones_like(xs), xs], 1) * np.sqrt(ws)[:, None]
    coef, *_ = np.linalg.lstsq(A, ys * np.sqrt(ws)[:, None], rcond=None)
    return coef[0], coef[1]                  # alpha[3], beta[3]

def features(I, r=1):
    bs = np.stack([box(I[..., c], r) for c in range(3)], -1)
    Ls = luma(bs)
    return np.stack([np.log(Ls + 1e-4), bs[..., 2] / (bs.sum(-1) + 1e-5)], -1)

def snap_bayes(lit_dem, I, band_px=40, maxs=20000):
    """Per-pixel shadow posterior: prior from the DEM mask blurred by the expected misregistration
    (band_px), likelihood from two shadow cues of the image itself (log luminance, blue ratio:
    shadows are lit by the blue sky only), class Gaussians fitted on the confident DEM interiors.
    Returns (soft lit fraction, diagnostics) or (DEM mask, None) if the classes do not separate."""
    blur = box((lit_dem > 0.5).astype(np.float32), band_px)
    S, Lm = blur < 0.01, blur > 0.99
    if S.sum() < 2000 or Lm.sum() < 2000:
        return lit_dem, None
    X = features(I)
    rng = np.random.default_rng(0)
    def gauss(m):
        x = X[m]; x = x[rng.choice(len(x), min(maxs, len(x)), replace=False)]
        mu = x.mean(0); C = np.cov(x.T) + np.eye(2) * 1e-5
        return mu, np.linalg.inv(C), np.log(np.linalg.det(C)), np.sqrt(C[0, 0])
    gs, gl = gauss(S), gauss(Lm)
    def ll(g):
        d = X - g[0]
        return -0.5 * (np.einsum("...i,ij,...j->...", d, g[1], d) + g[2])
    llr = np.clip(ll(gs) - ll(gl), -12, 12)
    # separability: how well the likelihood alone classifies the interiors
    acc = 0.5 * ((llr[S] > 0).mean() + (llr[Lm] < 0).mean())
    if acc < 0.9:                       # the image cannot confirm the DEM shadows: no cast term
        return np.ones_like(lit_dem), dict(sep=float(acc), cast="off")
    prior = np.clip(1 - blur, 0.03, 0.97)          # the image has the last word
    post = 1 / (1 + np.exp(-(np.log(prior / (1 - prior)) + llr)))
    lit = 1 - post
    g = np.log(box(luma(I), 1) + 1e-3); g = (g - g.mean()) / (g.std() + 1e-6) * 0.25
    lit = np.clip((guided(g, lit, 2, 0.01) - 0.5) * 3 + 0.5, 0, 1)   # penumbra <= ~2 px at 1.9 m: sharpen (no rim, no halo)
    # halo guard: a pixel brighter than any plausible shadow pixel is sunlit, whatever the mask says
    lp = np.log(luma(I) + 1e-4)
    lit = np.maximum(lit, np.clip((lp - (gs[0][0] + 2.5 * gs[3])) / 0.3, 0, 1))
    return lit, dict(sep=float(acc), mu_shadow=gs[0].tolist(), mu_lit=gl[0].tolist())

def fit_edge(I, rgb, lit, lam, band_px=16, gap=4, nclass=1):
    """Shadow/sun ratio per channel from pixels on both sides of the cast-shadow terminator
    (same surfaces, so albedo cancels), per vegetation class: k_c = amb_c / (amb_c + sun_c*lam).
    Returns rho_c = amb_c / sun_c, and diagnostics."""
    near = box((lit > 0.5).astype(np.float32), band_px)
    gapm = box((lit > 0.5).astype(np.float32), gap)
    band = (near > 0.02) & (near < 0.98) & ((gapm < 0.01) | (gapm > 0.99))   # both sides, off the edge
    v = exg(rgb)
    qs = np.quantile(v[band], np.linspace(0, 1, nclass + 1)[1:-1]) if band.sum() > 500 else [0.0]
    cls = np.searchsorted(qs, v)
    ks, ws = [], []
    for k in range(len(qs) + 1):
        s_ = band & (cls == k) & (lit < 0.1); l_ = band & (cls == k) & (lit > 0.9)
        if s_.sum() < 200 or l_.sum() < 200: continue
        ks.append(np.median(I[s_], axis=0) / np.maximum(np.median(I[l_], axis=0), 1e-4))
        ws.append(min(s_.sum(), l_.sum()))
        lam_e = float(np.median(lam[l_]))
    if not ks:
        return None
    kc = np.clip(np.average(np.array(ks), axis=0, weights=ws), 0.03, 0.95)
    rho = kc * lam_e / (1 - kc)
    return rho, dict(k_edge=kc.tolist(), lam_edge=lam_e, n_edge=int(sum(ws)))

LAM_CAP = 1.6

def method_a(rgb, hpad, res, P, az, el, f=4, strength=1.0, gmax=10.0, lam_strength=0.7, timing=None, rho_default=None):
    W = rgb.shape[0]
    t0 = time.perf_counter()
    lit_w, lam_w, shift = terrain_terms(hpad, res, P, W, az, el, f)
    t1 = time.perf_counter()
    I = to_lin(rgb)
    L = luma(I)
    lit_dem = upsample(lit_w, f, W, shift)
    lit, sdiag = snap_bayes(lit_dem, I)
    tsnap = time.perf_counter()
    lam = upsample(lam_w, f, W, shift)
    # Lambert only partly trusted (DEM/ortho misregistration, canopy not in the bare-earth DEM)
    sz = np.sin(np.radians(el))
    lam = sz + lam_strength * (lam - sz)
    direct = lam * lit
    # additive path radiance / black level (dark-object subtraction): without it the boosted
    # shadows come out hazy and flat
    shm = lit < 0.5
    haze = 0.9 * np.percentile(I[shm] if shm.sum() > 10000 else I.reshape(-1, 3), 0.5, axis=0)
    I = np.maximum(I - haze, 0)
    fe = fit_edge(I, rgb, lit, lam)
    if fe is None:                      # no cast-shadow edge: fall back to the regression
        alpha, beta = fit_light(I, direct); diag = dict(edge=None)
        alpha = np.maximum(alpha, 0.05 * beta); beta = np.maximum(beta, 1e-4)
    else:
        rho, diag = fe
        alpha, beta = rho, np.ones(3)
    if rho_default is not None and (fe is None or diag.get("n_edge", 0) < 5000):
        alpha, beta = np.asarray(rho_default), np.ones(3); diag["rho"] = "default"
    diag["snap"] = sdiag; diag["haze"] = haze.tolist()
    target = alpha + beta * sz
    # Lambert part capped (a 7.7 m bare-earth DEM misjudges small walls and canopy): the cast-shadow
    # part is whatever the image-confirmed mask adds on top
    rho = alpha / beta
    g_lam = np.clip((rho + sz) / (rho + lam[..., None]), 1 / LAM_CAP, LAM_CAP)
    gain = g_lam * (rho + lam[..., None]) / (rho + direct[..., None])
    gain = 1 + strength * (gain - 1)
    gm = gain.max(-1, keepdims=True)                 # clamp all channels together (keeps hue)
    gain = gain * np.minimum(1, gmax / gm)
    gain = np.maximum(gain, 1 / gmax)
    out = I * gain + haze
    out = chroma_smooth(out, np.clip((luma(gain) - 1) / 3, 0, 1))
    # soft shoulder instead of hard clip for boosted highlights
    out = np.where(out > 0.8, 0.8 + 0.2 * np.tanh((out - 0.8) / 0.2), out)
    o = to_srgb(out)
    t2 = time.perf_counter()
    if timing is not None:
        timing.update(terrain_s=t1 - t0, snap_s=tsnap - t1, relight_s=t2 - tsnap, px=W * W)
    return o, dict(amb_over_sun=(alpha / beta).tolist(), flat_sun_over_amb=(beta * sz / alpha).tolist(), **diag), lit, direct

def exg(rgb):
    r, g, b = [rgb[..., i].astype(np.float32) for i in range(3)]
    return (2 * g - r - b) / (r + g + b + 1)

def method_b(rgb, lit, r=96, nclass=3, gmax=40.0, band_px=24):
    """Fallback (no sun / Lambert model needed, only a shadow mask): per-channel gain matching of
    shadowed pixels to nearby sunlit pixels of the same land-cover rank, after dark-object
    (haze) subtraction. Classes are terciles of the vegetation index computed separately inside
    and outside the shadow (shadow light is blue, so a single ExG threshold would put every
    shadowed pixel in the 'least green' class)."""
    I0 = to_lin(rgb)
    sh = (lit < 0.3); li = (lit > 0.7)
    if sh.sum() < 1000 or li.sum() < 1000:
        return rgb.copy()
    haze = 0.9 * np.percentile(I0[sh], 0.5, axis=0)
    I = np.maximum(I0 - haze, 0)
    v = exg(rgb)
    cls = np.zeros(v.shape, np.int32)
    for m, refm in ((sh, sh), (li, li), (~(sh | li), li)):
        qs = np.quantile(v[refm], np.linspace(0, 1, nclass + 1)[1:-1])
        cls[m] = np.searchsorted(qs, v[m])
    # statistics only from a band along the terminator (same slope, same cover on both sides;
    # far from it the sunlit side is often a different surface, e.g. bare granite vs forest)
    near = box((lit > 0.5).astype(np.float32), band_px)
    band = (near > 0.02) & (near < 0.98)
    shf, lif = (sh & band).astype(np.float32), (li & band).astype(np.float32)
    gain = np.ones_like(I)
    for k in range(nclass):
        ck = (cls == k).astype(np.float32)
        ws_, wl_ = ck * shf, ck * lif
        ns, nl = box(ws_, r), box(wl_, r)
        a_s, a_l = np.clip(ns / 0.05, 0, 1), np.clip(nl / 0.05, 0, 1)
        for c in range(3):
            x = np.log(I[..., c] + 2e-3)           # geometric means: bright outliers do not dominate
            ms = a_s * box(ws_ * x, r) / np.maximum(ns, 1e-6) + (1 - a_s) * (ws_ * x).sum() / max(ws_.sum(), 1)
            ml = a_l * box(wl_ * x, r) / np.maximum(nl, 1e-6) + (1 - a_l) * (wl_ * x).sum() / max(wl_.sum(), 1)
            gain[..., c] = np.where(ck > 0, np.clip(np.exp(ml - ms), 1, gmax), gain[..., c])
    gain = np.stack([box(gain[..., c], 8) for c in range(3)], -1)   # no per-class blotches
    gain = gain * np.minimum(1, gmax / gain.max(-1, keepdims=True))   # keep the hue when clamping
    w = (1 - lit)[..., None]
    out = I * (1 + w * (gain - 1)) + haze
    out = chroma_smooth(out, w[..., 0] * np.clip((gain.mean(-1) - 1) / 3, 0, 1))
    out = np.where(out > 0.8, 0.8 + 0.2 * np.tanh((out - 0.8) / 0.2), out)
    return to_srgb(out)

def chroma_smooth(out, w, r=3):
    """Boosted shadows carry JPEG chroma noise x gain: keep their luminance detail, take the
    chroma from a (2r+1)^2 average (weight w = how much the pixel was boosted); the luminance
    is lightly denoised too (half-way to a 3x3 mean)."""
    Y = luma(out)
    Y = (Y + w * 0.5 * (box(Y, 1) - Y))[..., None]
    bs = np.stack([box(out[..., c], r) for c in range(3)], -1)
    cs = bs / np.maximum(luma(bs)[..., None], 1e-5)
    w = w[..., None]
    return out + w * (cs * Y - out)

def label(img, text):
    from PIL import ImageDraw
    im = Image.fromarray(img); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 8 + 7 * len(text), 18], fill=(0, 0, 0)); d.text((4, 3), text, fill=(255, 255, 255))
    return np.asarray(im)

if __name__ == "__main__":
    name = sys.argv[1]; outdir = sys.argv[2]
    d = np.load(f"data/{name}.npz"); fitd = np.load(f"data/{name}_fit.npz")
    az, el = float(sys.argv[3]) if len(sys.argv) > 3 else float(fitd["az"]), float(sys.argv[4]) if len(sys.argv) > 4 else float(fitd["el"])
    rgb, hpad, res, P = d["rgb"], d["h"], float(d["res"]), int(d["pad"])
    tm = {}
    rho_def = json.load(open("data/ravine_info.json"))["amb_over_sun"] if name != "ravine" else None
    a, info, lit, direct = method_a(rgb, hpad, res, P, az, el, timing=tm, rho_default=rho_def)
    t = time.perf_counter(); b = method_b(rgb, lit); tb = time.perf_counter() - t
    info.update(az=az, el=el, timing=tm, method_b_s=tb)
    print(name, json.dumps(info))
    S = 780
    rs = lambda x: np.asarray(Image.fromarray(x).resize((S, S), Image.LANCZOS))
    row = np.concatenate([label(rs(rgb), "before"), np.full((S, 6, 3), 255, np.uint8),
                          label(rs(a), f"A: relit (sun az {az:.0f} el {el:.0f})"), np.full((S, 6, 3), 255, np.uint8),
                          label(rs(b), "B: gain matching")], 1)
    Image.fromarray(row).save(f"{outdir}/{name}_before_after.png", optimize=True)
    Image.fromarray(a).save(f"data/{name}_A.png"); Image.fromarray(b).save(f"data/{name}_B.png")
    Image.fromarray((np.clip(direct, 0, 1) * 255).astype(np.uint8)).save(f"data/{name}_direct.png")
    json.dump(info, open(f"data/{name}_info.json", "w"))
