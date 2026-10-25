"""Fit the capture sun (azimuth, elevation) of a window: Lambert * (1 - cast shadow) vs luminance."""
import sys, time, json
import numpy as np
from lib import *

def load(name, f):
    d = np.load(f"data/{name}.npz")
    rgb, hpad, res, P = d["rgb"], d["h"], float(d["res"]), int(d["pad"])
    W = rgb.shape[0]
    off = P % f
    hp = down(hpad[off:, off:], f)
    pad = (P - off) // f
    n = W // f
    L = luma(down(to_lin(rgb[:n * f, :n * f]), f))
    return dict(rgb=rgb, hp=hp, pad=pad, n=n, res=res * f, L=L, lat=float(d["lat"]), lon=float(d["lon"]))

def otsu(x):
    hist, edges = np.histogram(x, 256)
    p = hist / hist.sum(); w = np.cumsum(p); mu = np.cumsum(p * edges[:-1]); mt = mu[-1]
    sb = (mt * w - mu) ** 2 / np.maximum(w * (1 - w), 1e-12)
    return edges[np.argmax(sb)]

def score_grid(D, azs, els):
    n, pad, res = D["n"], D["pad"], D["res"]
    h = D["hp"][pad:pad + n, pad:pad + n]
    nrm = normals(box(h, 1), res)
    L = D["L"].ravel(); Lc = L - L.mean(); Lv = (Lc ** 2).sum()
    dark = (D["L"] < otsu(D["L"])).ravel()
    R2 = np.zeros((len(azs), len(els))); IOU = np.zeros_like(R2); B = np.zeros_like(R2)
    for i, az in enumerate(azs):
        ht = horizon_tan(D["hp"], res, pad, n, az)
        for j, el in enumerate(els):
            lit = ht < np.tan(np.radians(el))
            dirc = (lambert(nrm, az, el) * lit).ravel()
            dc = dirc - dirc.mean()
            cov = (dc * Lc).sum(); var = (dc ** 2).sum() + 1e-12
            r = cov / np.sqrt(var * Lv)
            R2[i, j] = r * abs(r)                 # signed r^2
            B[i, j] = cov / var
            sh = (~lit.ravel()) | (dirc < 0.15)
            # Matthews correlation (phi) of predicted shadow vs dark pixels: unbiased by area
            tp = (sh & dark).sum(); fp = (sh & ~dark).sum(); fn = (~sh & dark).sum(); tn = sh.size - tp - fp - fn
            den = np.sqrt(float(tp + fp) * (tp + fn) * (tn + fp) * (tn + fn))
            IOU[i, j] = (tp * tn - fp * fn) / den if den > 0 else 0.0
    return R2, IOU, B

if __name__ == "__main__":
    name = sys.argv[1]
    f = int(sys.argv[2]) if len(sys.argv) > 2 else 8
    D = load(name, f)
    t = time.time()
    azs = np.arange(0, 360, 5.0); els = np.arange(10, 86, 2.5)
    R2, IOU, B = score_grid(D, azs, els)
    S = R2 + 0.5 * IOU
    i, j = np.unravel_index(np.argmax(S), S.shape)
    print(f"{name}: coarse {time.time()-t:.1f}s best az {azs[i]} el {els[j]} r2 {R2[i,j]:.3f} mcc {IOU[i,j]:.3f}")
    # refine
    azs2 = np.arange(azs[i] - 20, azs[i] + 20.1, 2.0); els2 = np.arange(max(5, els[j] - 12), min(88, els[j] + 12.1), 1.0)
    R2b, IOUb, Bb = score_grid(D, azs2, els2)
    Sb = R2b + 0.5 * IOUb
    i2, j2 = np.unravel_index(np.argmax(Sb), Sb.shape)
    print(f"{name}: fine best az {azs2[i2]} el {els2[j2]} r2 {R2b[i2,j2]:.3f} mcc {IOUb[i2,j2]:.3f}")
    # sharpness: half-width where score falls by 10% of (max - median)
    np.savez(f"data/{name}_fit.npz", azs=azs, els=els, R2=R2, IOU=IOU, S=S, azs2=azs2, els2=els2, R2b=R2b, IOUb=IOUb, Sb=Sb,
             az=azs2[i2], el=els2[j2])
    med = np.median(S); top = Sb.max()
    for tol in (0.02, 0.05):
        A, E = np.meshgrid(azs2, els2, indexing="ij"); k = Sb >= top - tol
        print(f"  score within {tol} of max: az {A[k].min()}..{A[k].max()}, el {E[k].min()}..{E[k].max()}")
    for lab, prof, ax in (("az", S[:, j], azs), ("el", S[i, :], els)):
        ok = ax[prof >= top - 0.1]
        if len(ok): print(f"  coarse {lab} with score >= max-0.1: {ok.min()}..{ok.max()}")
    print(f"  score max {top:.3f}, median {med:.3f}; r2-only argmax az {azs[np.unravel_index(np.argmax(R2), R2.shape)[0]]} el {els[np.unravel_index(np.argmax(R2), R2.shape)[1]]}")
