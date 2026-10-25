"""EarthNRails: the track's corridor cut into the terrain block (the user's run, 2026-10-25: "terrain qui bave sur les
voies ... envisage sur chaque rail que tu places peut-etre un rectangle d'extrusion du terrain").

The railway's bed is graded through upstream's grader (nrails.grade), but other plans win where they overlap it: a road
bridge's approach embankment, a road at a junction, a cell's plan cut at its box. At a village the terrain stood 1.7 m
into the train's way and 4.9 m over the ballast under a road bridge. Here, as the terrain block's heights are made,
every sample within CUT_HALF_M of a track in the open is kept at least BED_M under its rail top, and further out no
higher than a CUT_SLOPE cutting wall rising from there: a ceiling stamped from the track's samples (the shared
profiles, nrails.canon, so every block and tile agrees), applied as min with the graded heights (it only ever cuts;
a track on an embankment is left alone). Level crossings (the road's own level) and the tracks on bridges and in
tunnels are left alone. BNGE_RAIL_CORRIDOR=off: none.
"""
import numpy as np

BED_M = 0.65                # m under the rail top at most within CUT_HALF_M (the ballast's foot: 0.55-0.6)
CUT_HALF_M = 3.4            # m either side of the centre line at that level
CUT_SLOPE = 1.0             # rise per metre beyond (a 45 degree cutting wall)
CUT_REACH_M = 24.0          # m beyond CUT_HALF_M the ceiling reaches (deeper cuttings: the grader's own plans)
RES_M = 0.5                 # the ceiling raster's resolution
X_KEEP_M = 4.0              # m round a level crossing's slab (its half along the track + this) left at the road's level


class Ceiling:
    """A raster over box (x0, y0, x1, y1) of the highest terrain allowed (inf: no limit), frame up."""

    def __init__(self, box, res=RES_M):
        self.x0, self.y0 = float(box[0]), float(box[1])
        self.res = res
        self.nx = int(np.ceil((box[2] - box[0]) / res)) + 1
        self.ny = int(np.ceil((box[3] - box[1]) / res)) + 1
        self.z = np.full((self.ny, self.nx), np.inf, np.float32)
        self.n = 0

    def stamp(self, pts, half=CUT_HALF_M, slope=CUT_SLOPE, reach=CUT_REACH_M, bed=BED_M):
        """The ceiling of a track's samples pts (k, 3) (rail tops, 2 m apart), each a cone: rail - bed within half,
        rising at slope beyond, out to half + reach. The cones' envelope is the corridor."""
        k = int(np.ceil((half + reach) / self.res)) + 1
        off = np.arange(-k, k + 1) * self.res
        ox, oy = np.meshgrid(off, off)
        for p in np.asarray(pts, np.float64):
            ix, iy = int(round((p[0] - self.x0) / self.res)), int(round((p[1] - self.y0) / self.res))
            a0, a1, b0, b1 = max(iy - k, 0), min(iy + k + 1, self.ny), max(ix - k, 0), min(ix + k + 1, self.nx)
            if a0 >= a1 or b0 >= b1:
                continue
            # (the offsets of the raster's cells from the sample itself, not from its snapped cell)
            dx = ox[a0 - iy + k:a1 - iy + k, b0 - ix + k:b1 - ix + k] + (ix * self.res + self.x0 - p[0])
            dy = oy[a0 - iy + k:a1 - iy + k, b0 - ix + k:b1 - ix + k] + (iy * self.res + self.y0 - p[1])
            d = np.hypot(dx, dy)
            v = np.where(d <= half + reach, p[2] - bed + np.maximum(0.0, d - half) * slope, np.inf)
            view = self.z[a0:a1, b0:b1]
            np.minimum(view, v.astype(np.float32), out=view)
            self.n += 1

    def at(self, x, y):
        """The ceiling at (x, y) (bilinear; inf where any corner has none)."""
        fx = (np.asarray(x, np.float64) - self.x0) / self.res
        fy = (np.asarray(y, np.float64) - self.y0) / self.res
        out = np.full(np.shape(fx), np.inf)
        ok = (fx >= 0) & (fx < self.nx - 1) & (fy >= 0) & (fy < self.ny - 1)
        if not ok.any():
            return out
        i, j = np.floor(fx[ok]).astype(np.int64), np.floor(fy[ok]).astype(np.int64)
        tx, ty = fx[ok] - i, fy[ok] - j
        z = self.z
        a, b = z[j, i].astype(np.float64), z[j, i + 1].astype(np.float64)
        c_, d = z[j + 1, i].astype(np.float64), z[j + 1, i + 1].astype(np.float64)
        with np.errstate(invalid="ignore"):     # (inf * 0 at the corridor's rim: no limit there)
            c = (a * (1 - tx) + b * tx) * (1 - ty) + (c_ * (1 - tx) + d * tx) * ty
        out[ok] = np.where(np.isfinite(c), c, np.inf)
        return out


def open_samples(prof, found, box=None):
    """The rail tops (k, 3) of the tracks in the open (not on bridges, in tunnels, at level crossings) of a
    profile_box result, within box if given."""
    xs = [(np.asarray(x["at"], np.float64)[:2], float(x.get("half", 4.0)) + X_KEEP_M) for x in found]
    out = []
    for parts in prof.values():
        for pts, kind in parts:
            pts = np.asarray(pts, np.float64)
            sel = np.asarray(kind) == 0
            if box is not None:
                sel &= (pts[:, 0] > box[0]) & (pts[:, 0] < box[2]) & (pts[:, 1] > box[1]) & (pts[:, 1] < box[3])
            for c, h in xs:
                sel &= np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1]) > h
            if sel.any():
                out.append(pts[sel])
    return np.concatenate(out) if out else np.zeros((0, 3))


def block_ceiling(frame, box, cell_fn, elev):
    """The Ceiling over box (and CUT_HALF_M + CUT_REACH_M round it) of the tracks in the open, None without any."""
    from nrails import canon
    m = CUT_HALF_M + CUT_REACH_M + 2.0
    big = (box[0] - m, box[1] - m, box[2] + m, box[3] + m)
    prof, found, _arcs = canon.profile_box(frame, big, cell_fn, elev)
    pts = open_samples(prof, found, big) if prof else np.zeros((0, 3))
    if not len(pts):
        return None
    ceil = Ceiling((box[0] - 4.0, box[1] - 4.0, box[2] + 4.0, box[3] + 4.0))
    ceil.stamp(pts)
    return ceil


def cut(gen, frame, ceil):
    """gen(la, lo) -> heights over the ellipsoid, under the ceiling (frame up)."""
    def f(la, lo):
        z = np.asarray(gen(la, lo), np.float64)
        la_, lo_ = np.asarray(la, np.float64), np.asarray(lo, np.float64)
        e, n, u = frame.geodetic_to_enu(la_.ravel(), lo_.ravel(), z.ravel())
        c = ceil.at(np.asarray(e), np.asarray(n))
        over = np.maximum(0.0, np.asarray(u, np.float64) - c)       # (du/dz = 1 within a block's few km)
        return z - over.reshape(z.shape)
    return f
