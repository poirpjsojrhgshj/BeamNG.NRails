#!/usr/bin/env python3
"""NRails dev tool: is a rail tunnel's mouth clear? Round a point (real Overture cells and elevation, the terrain
graded as the game's: grading.Grader with the railway's bed), for every portal of the rail tunnels' tubes
(nrails.rails.block_tubes): a terrain block's 2 m grid round it with the portal holes cut (tunnel_hole_mask, the game's
kernel), then the train's way (TRAIN_HALF_M either side of the tube's centre line, from rail top + FLOOR_M up to the
vault inside, up to TRAIN_H_M outside) from OUT_M outside the portal to IN_M inside: every point there where terrain
that is not cut stands in it. With the mouth's cut (BNGE_RAIL_MOUTH_CUT) on and off.

    .venv\\Scripts\\python.exe tools\\audit_rail_portals.py LAT LON [--km 3]
"""
import argparse
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
import dem        # noqa: E402
import geodesy    # noqa: E402
import heightmap  # noqa: E402
import mapcells   # noqa: E402
import mapdata    # noqa: E402
import netfetch   # noqa: E402
from nrails import paths, rails      # noqa: E402

TRAIN_HALF_M = 1.7
TRAIN_H_M = 4.6         # m over the rail top a train (and its pantograph down) reaches
FLOOR_M = 0.6
OUT_M = 20.0
IN_M = 20.0
GRID_N = 64             # samples a side of the block round a portal (128 m)


def portal_check(tube, e, ground):
    sq = heightmap.SQUARE
    xy, z = np.asarray(tube["xy"]), np.asarray(tube["z"])
    if e == 1:
        xy, z = xy[::-1], z[::-1]
    p0 = xy[0]
    cx, cy = (np.round(p0 / sq) * sq)
    half = GRID_N * sq / 2
    ix = np.arange(GRID_N)
    X, Y = np.meshgrid(cx - half + ix * sq, cy - half + ix * sq)
    u = ground.z(X.ravel(), Y.ravel()).reshape(X.shape)
    out = {}
    for mode in ("off", "on"):
        os.environ["BNGE_RAIL_MOUTH_CUT"] = mode
        mask = rails.tunnel_hole_mask([tube], u, cx, cy, sq)
        s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
        t0 = (xy[min(1, len(xy) - 1)] - xy[0])
        t0 = t0 / max(np.hypot(*t0), 1e-9)
        n0 = np.array([-t0[1], t0[0]])
        bad, worst = 0, 0.0
        for si in np.arange(-OUT_M, IN_M + 0.01, 0.5):
            if si < 0:
                c, zf, nn = p0 + t0 * si, z[0], n0
            else:
                if si > s[-1]:
                    break
                c = np.array([np.interp(si, s, xy[:, 0]), np.interp(si, s, xy[:, 1])])
                zf = float(np.interp(si, s, z))
                j = min(int(np.searchsorted(s, si)), len(xy) - 1)
                d = xy[j] - xy[max(j - 1, 0)] if j else xy[1] - xy[0]
                d = d / max(np.hypot(*d), 1e-9)
                nn = np.array([-d[1], d[0]])
            rail = zf + rails.TUNNEL_FLOOR_M
            top = (zf + rails.TUNNEL_H - 0.2) if si >= 0 else rail + TRAIN_H_M
            for lat in np.linspace(-TRAIN_HALF_M, TRAIN_HALF_M, 7):
                q = c + nn * lat
                fx, fy = (q[0] - (cx - half)) / sq, (q[1] - (cy - half)) / sq
                i0, j0 = int(np.floor(fx)), int(np.floor(fy))
                if not (0 <= i0 < GRID_N - 1 and 0 <= j0 < GRID_N - 1):
                    continue
                if mask[j0, i0]:
                    continue                    # (the square is a hole)
                g = float(rails._bilinear(u, cx - half, cy - half, sq, q[None])[0])
                if rail + FLOOR_M < g < top:
                    bad += 1
                    worst = max(worst, g - (rail + FLOOR_M))
        out[mode] = (bad, worst, int(mask.sum()))
    os.environ.pop("BNGE_RAIL_MOUTH_CUT", None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--km", type=float, default=3.0)
    a = ap.parse_args()
    cache = paths.default_cache_dir()
    net = netfetch.Fetcher(stats_dir=os.path.join(cache, "netstats"))
    md = mapdata.MapData(cache, fetcher=net)
    d = dem.Dem(os.path.join(cache, "dem"), fetcher=net)
    frame = geodesy.EnuFrame(a.lat, a.lon)
    zoom = dem.zoom_for(a.lat, 1.25, dem.FINE_ZOOM)
    import grading
    grader = grading.Grader(frame, md, lambda la, lo: np.asarray(d.sample(np.asarray(la), np.asarray(lo),
                                                                          grading.PROFILE_ZOOM), np.float64))

    def elev(la, lo):
        return grader.apply(la, lo, np.asarray(d.sample(np.asarray(la), np.asarray(lo), zoom), np.float64),
                            grading.ROAD_LIFT)
    ground = rails.Ground(frame, elev)
    dl = (a.km + 0.6) / 111.0
    dlo = dl / max(np.cos(np.radians(a.lat)), 0.1)
    keys = mapcells.cells_for_bbox(a.lat - dl, a.lon - dlo, a.lat + dl, a.lon + dlo)
    cells = list(rails.more_cells(keys, lambda k: md.cell(k, layers=("roads",)).layers.get("roads")).values())
    r = a.km * 1000.0
    tubes = rails.block_tubes(frame, cells, elev, (-r, -r, r, r))
    print(f"{len(tubes)} tubes, {sum(sum(t['portal']) for t in tubes)} portals")
    tot = {"off": 0, "on": 0}
    for t in tubes:
        for e in (0, 1):
            if not t["portal"][e]:
                continue
            p = t["xy"][0 if e == 0 else -1]
            if np.abs(p).max() > r:
                continue
            res = portal_check(t, e, ground)
            la, lo, _ = frame.enu_to_geodetic(p[0], p[1], 0.0)
            up = t["up"][e]
            print(f"portal at {float(la):.5f},{float(lo):.5f} w={t['w']:.1f} up={up}: "
                  + "  ".join(f"cut {m}: {res[m][0]:3d} pts in the way (worst +{res[m][1]:.2f} m, {res[m][2]} holes)"
                              for m in ("off", "on")))
            for m in tot:
                tot[m] += res[m][0] > 0
    print("portals with terrain in the way:", tot)


if __name__ == "__main__":
    main()
