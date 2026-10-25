#!/usr/bin/env python3
"""NRails dev tool: are the rails continuous? Builds the rail tiles of a square around a point (real Overture cells
and DEM, like build_rail_tile.py) and checks every place a track piece ends:
  - seam: the piece ends at a tile edge; the neighbouring tile's piece of the same track must start there, at the same
    height (dz) and in line (gap = horizontal distance);
  - joint: the piece ends inside the tile where another track's piece starts or ends (a node between two mapped
    segments): gap, dz and the kink angle between the two;
  - open end: nothing there (a buffer stop, a tunnel portal, a gap in the data ... or a bug).
Also the steepest grade and the sharpest vertical change per track.

    .venv\\Scripts\\python.exe tools\\audit_rail_continuity.py LAT LON [--around 2]
"""
import argparse
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import dem        # noqa: E402
import geodesy    # noqa: E402
import mapdata    # noqa: E402
import netfetch   # noqa: E402
from nrails import paths      # noqa: E402
from nrails import rails      # noqa: E402
import roads      # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--around", type=int, default=2)
    a = ap.parse_args()
    cache = paths.default_cache_dir()
    net = netfetch.Fetcher(stats_dir=os.path.join(cache, "netstats"))
    md = mapdata.MapData(cache, fetcher=net)
    d = dem.Dem(os.path.join(cache, "dem"), fetcher=net)
    frame = geodesy.EnuFrame(a.lat, a.lon)
    zoom = dem.zoom_for(a.lat, 1.25, dem.FINE_ZOOM)

    def elev(la, lo):
        return np.asarray(d.sample(np.asarray(la), np.asarray(lo), zoom), np.float64)

    pieces = []             # (tile, track fid, pts)
    rng = range(-a.around, a.around)
    for ty in rng:
        for tx in rng:
            cells = [md.cell(k, layers=("roads",)).layers.get("roads")
                     for k in roads.cells_of_tile(frame, tx, ty, margin=rails.NEAR_M)]     # (as blockworker.rail_tile)
            rt = rails.build(frame, tx, ty, cells, elev)
            if rt is None:
                continue
            fids = [f[0] for f in rails.rail_features(cells, frame, (-1e9, -1e9, 1e9, 1e9))]
            near = roads.tile_bbox(tx, ty)
            near = rails._feature_box((near[0] - rails.NEAR_M, near[1] - rails.NEAR_M, near[2] + rails.NEAR_M,
                                       near[3] + rails.NEAR_M))     # (as rails.build lists them)
            fids = [f[0] for f in rails.rail_features(cells, frame, near)]
            for k, pts in rt.lines:
                pieces.append(((tx, ty), fids[k], pts))
    lo, hi = -a.around * roads.TILE, a.around * roads.TILE
    print(f"{len(pieces)} track pieces in {len(rng) ** 2} tiles")
    ends = []
    for i, (t, fid, pts) in enumerate(pieces):
        for e, (p, q) in enumerate(((pts[0], pts[1]), (pts[-1], pts[-2]))):
            ends.append((i, e, p, (p - q)[:2] / max(np.hypot(*(p - q)[:2]), 1e-9)))
    worst = {"seam": [], "joint": []}
    opened = 0
    for i, e, p, dvec in ends:
        t, fid, pts = pieces[i]
        x0, y0, x1, y1 = roads.tile_bbox(*t)
        at_edge = min(abs(p[0] - x0), abs(p[0] - x1), abs(p[1] - y0), abs(p[1] - y1)) < rails.OVERLAP_M + rails.STEP_M + 1
        outer = p[0] < lo + 5 or p[0] > hi - 5 or p[1] < lo + 5 or p[1] > hi - 5
        best = None
        for j, (t2, fid2, pts2) in enumerate(pieces):
            if j == i:
                continue
            dd = np.hypot(pts2[:, 0] - p[0], pts2[:, 1] - p[1])
            k = int(np.argmin(dd))
            if best is None or dd[k] < best[0]:
                best = (dd[k], float(pts2[k, 2] - p[2]), j, k, fid2 == fid)
        if best is None or best[0] > 6.0:
            if not outer:
                opened += 1
            continue
        if best[0] > rails.NODE_TOL_M:     # a parallel track ends near it (a siding's buffer stop): not a joint
            continue
        kind = "seam" if at_edge and best[4] else "joint"
        j, k = best[2], best[3]
        pts2 = pieces[j][2]
        k2 = min(max(k, 1), len(pts2) - 1)
        d2 = (pts2[k2] - pts2[k2 - 1])[:2]
        d2 = d2 / max(np.hypot(*d2), 1e-9)
        kink = float(np.degrees(np.arccos(np.clip(abs(np.dot(d2, dvec)), -1, 1))))
        worst[kind].append((best[0], abs(best[1]), kink, t, fid[:10]))
    for kind in ("seam", "joint"):
        w = worst[kind]
        if not w:
            print(f"{kind}s: none")
            continue
        arr = np.array([r[:3] for r in w])
        print(f"{kind}s: {len(w)}  gap max {arr[:, 0].max():.3f} m  |dz| max {arr[:, 1].max():.3f} m  "
              f"kink max {arr[:, 2].max():.1f} deg  (>5 cm dz: {(arr[:, 1] > 0.05).sum()}, >0.5 m gap: "
              f"{(arr[:, 0] > 0.5).sum()}, >10 deg kink: {(arr[:, 2] > 10).sum()})")
        for r in sorted(w, key=lambda r: -max(r[1] * 10, r[0], r[2] / 10))[:6]:
            print(f"   gap {r[0]:.2f} m dz {r[1]:.3f} m kink {r[2]:.1f} deg  tile {r[3]} track {r[4]}")
    print(f"open ends inside the square: {opened}")
    g = []
    for t, fid, pts in pieces:
        s = np.hypot(*np.diff(pts[:, :2], axis=0).T)
        ok = s > 0.5
        if ok.any():
            gr = np.where(ok, np.abs(np.diff(pts[:, 2])) / np.maximum(s, 1e-9), 0.0)
            i = int(np.argmax(gr))
            g.append((gr[i], t, fid[:10], pts[i, :3].round(1).tolist()))
    if g:
        print(f"steepest grade of a piece: {max(r[0] for r in g) * 100:.1f} %  "
              f"(pieces over 3.5 %: {sum(r[0] > 0.0355 for r in g)})")
        for r in sorted(g, key=lambda r: -r[0])[:5]:
            print(f"   {r[0] * 100:.1f} % at {r[3]} tile {r[1]} track {r[2]}")
    # tracks side by side (3-6.5 m apart, parallel): their level difference (rails.level_parallel)
    par = []
    for i, (t, fid, pts) in enumerate(pieces):
        if len(pts) < 3:
            continue
        for j, (t2, fid2, pts2) in enumerate(pieces):
            if j == i or t2 != t or fid2 == fid or len(pts2) < 3:
                continue
            d, c, seg, tt = rails._nearest_on(pts[:, :2], pts2[:, :2])
            ok = (d > 3.0) & (d < 6.5)
            if not ok.any():
                continue
            z2 = pts2[seg, 2] + tt * (pts2[np.minimum(seg + 1, len(pts2) - 1), 2] - pts2[seg, 2])
            dz = np.abs(pts[:, 2] - z2)[ok]
            par.append((float(dz.max()), float(np.median(dz)), t, fid[:10]))
    if par:
        arr = np.array([p[:2] for p in par])
        print(f"tracks side by side: {len(par)} pairs, |dz| max {arr[:, 0].max():.3f} m, median of medians "
              f"{np.median(arr[:, 1]):.3f} m (pairs over 5 cm: {(arr[:, 0] > 0.05).sum()})")
        for p in sorted(par, key=lambda p: -p[0])[:4]:
            print(f"   |dz| {p[0]:.3f} m tile {p[2]} track {p[3]}")
    md.close()


if __name__ == "__main__":
    main()
