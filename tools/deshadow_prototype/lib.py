"""De-shadowing helpers (numpy + PIL only)."""
import numpy as np

# --- colour -------------------------------------------------------------------------------
_x = np.arange(256) / 255.0
SRGB2LIN = np.where(_x <= 0.04045, _x / 12.92, ((_x + 0.055) / 1.055) ** 2.4).astype(np.float32)

def to_lin(rgb):
    return SRGB2LIN[rgb]

def to_srgb(lin):
    lin = np.clip(lin, 0, 1)
    s = np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)
    return np.clip(np.rint(s * 255), 0, 255).astype(np.uint8)

def luma(lin):
    return lin[..., 0] * 0.2126 + lin[..., 1] * 0.7152 + lin[..., 2] * 0.0722

# --- filters --------------------------------------------------------------------------------
def _run(x, r, axis):
    x = np.moveaxis(x, axis, 0)
    n = x.shape[0]
    C = np.empty((n + 1 + 2 * r,) + x.shape[1:], np.float64)
    C[:r + 1] = 0
    np.cumsum(x, axis=0, out=C[r + 1:r + 1 + n])
    C[r + 1 + n:] = C[r + n]
    cnt = (np.minimum(np.arange(n) + r + 1, n) - np.maximum(np.arange(n) - r, 0)).astype(np.float32)
    out = (C[2 * r + 1:2 * r + 1 + n] - C[:n]) / cnt.reshape((n,) + (1,) * (x.ndim - 1))
    return np.moveaxis(out.astype(np.float32), 0, axis)

_CNT = {}

def box(a, r):
    """Mean over a (2r+1)^2 box, edge-normalised: one integral image, edge-replicated so the four
    corner reads are plain slices (O(N), ~0.25 ms at 272^2)."""
    if r <= 0:
        return np.asarray(a, np.float32)
    a = np.asarray(a, np.float32)
    n, m = a.shape
    S = np.zeros((n + 1 + 2 * r, m + 1 + 2 * r), np.float64)
    core = S[r + 1:r + 1 + n, r + 1:r + 1 + m]
    np.cumsum(a, axis=0, out=core)
    np.cumsum(core, axis=1, out=core)
    S[r + 1 + n:, :] = S[r + n, :]
    S[:, r + 1 + m:] = S[:, r + m:r + m + 1]
    k = 2 * r + 1
    tot = S[k:k + n, k:k + m] - S[:n, k:k + m] - S[k:k + n, :m] + S[:n, :m]
    key = (n, m, r)
    if key not in _CNT:
        cr = np.minimum(np.arange(n) + r + 1, n) - np.maximum(np.arange(n) - r, 0)
        cc = np.minimum(np.arange(m) + r + 1, m) - np.maximum(np.arange(m) - r, 0)
        _CNT[key] = (1.0 / np.outer(cr, cc)).astype(np.float64)
    return (tot * _CNT[key]).astype(np.float32)

def guided(I, p, r, eps):
    """He et al. guided filter: p filtered with edges of guide I."""
    mI, mp = box(I, r), box(p, r)
    cov = box(I * p, r) - mI * mp
    var = box(I * I, r) - mI * mI
    a = cov / (var + eps)
    b = mp - a * mI
    return box(a, r) * I + box(b, r)

def down(a, f):
    h, w = (a.shape[0] // f) * f, (a.shape[1] // f) * f
    a = a[:h, :w]
    return a.reshape(h // f, f, w // f, f, *a.shape[2:]).mean(axis=(1, 3))

def up(a, f, shape):
    """Bilinear upsample by f (cell-centred) to shape."""
    from PIL import Image
    return np.asarray(Image.fromarray(a.astype(np.float32), "F").resize((shape[1], shape[0]), Image.BILINEAR))

# --- terrain --------------------------------------------------------------------------------
def normals(h, res):
    """Unit normals (E, N, Up) of a north-up grid (row 0 = north)."""
    gy, gx = np.gradient(h.astype(np.float64), res)
    nx, ny = -gx, gy                     # dh/dN = -d/drow
    n = np.sqrt(nx * nx + ny * ny + 1.0)
    return (nx / n).astype(np.float32), (ny / n).astype(np.float32), (1.0 / n).astype(np.float32)

def sun_vec(az, el):
    az, el = np.radians(az), np.radians(el)
    return np.sin(az) * np.cos(el), np.cos(az) * np.cos(el), np.sin(el)

def lambert(nrm, az, el):
    sx, sy, sz = sun_vec(az, el)
    return np.maximum(0.0, nrm[0] * sx + nrm[1] * sy + nrm[2] * sz)

def bilin(a, y, x):
    H, W = a.shape
    x = np.clip(x, 0, W - 1.001); y = np.clip(y, 0, H - 1.001)
    x0 = x.astype(np.int32); y0 = y.astype(np.int32)
    fx = x - x0; fy = y - y0
    return ((a[y0, x0] * (1 - fx) + a[y0, x0 + 1] * fx) * (1 - fy)
            + (a[y0 + 1, x0] * (1 - fx) + a[y0 + 1, x0 + 1] * fx) * fy)

def horizon_tan(hpad, res, pad, n, az, max_dist=1500.0, growth=1.04, lift=0.0):
    """Max tangent of the terrain elevation angle toward azimuth az for the n x n window
    starting at (pad, pad) in the padded grid hpad. Steps grow geometrically from 1 cell."""
    yy, xx = np.mgrid[pad:pad + n, pad:pad + n].astype(np.float32)
    h0 = hpad[pad:pad + n, pad:pad + n] + lift
    s, c = np.sin(np.radians(az)), np.cos(np.radians(az))
    best = np.full((n, n), -1e9, np.float32)
    d = res
    while d <= max_dist:
        hs = bilin(hpad, yy - c * d / res, xx + s * d / res)
        np.maximum(best, (hs - h0) / d, out=best)
        d = max(d + res, d * growth)
    return best
