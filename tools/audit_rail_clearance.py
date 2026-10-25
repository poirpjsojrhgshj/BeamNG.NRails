#!/usr/bin/env python3
"""NRails dev tool: does the terrain stand in a train's way? Round a point (real Overture cells and elevation,
the terrain graded as the game's: grading.Grader with the railway's bed, nrails.grade; the track's heights from the
map cells' shared profiles, nrails.canon, as the game draws them), for every track in the open:
  - the train's way: the terrain over the train's floor line (rail top + FLOOR_M) within TRAIN_HALF_M of the centre;
  - the bed: the terrain over the ballast's shoulder (rail top - SHOULDER_M) within BED_HALF_M (terrain "bleeding"
    onto the track);
on the 2 m terrain grid the game uses (its squares are flat between their corners: the bilinear surface).

    .venv\\Scripts\\python.exe tools\\audit_rail_clearance.py LAT LON [--km 1]
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
import mapdata    # noqa: E402
import netfetch   # noqa: E402
from nrails import canon, paths, rails      # noqa: E402

TRAIN_HALF_M = 1.7
FLOOR_M = 0.6           # m over the rail top: the lowest point of a train's body beside the rails
BED_HALF_M = 2.9        # m: the ballast's foot
SHOULDER_M = 0.25       # m under the rail top the ballast's shoulder lies


def grid_z(elev_xy, xy):
    """The game's terrain at xy: bilinear on the 2 m grid of corners (as the TerrainBlock draws and collides)."""
    sq = heightmap.SQUARE
    fx, fy = xy[:, 0] / sq, xy[:, 1] / sq
    ix, iy = np.floor(fx), np.floor(fy)
    ax, ay = fx - ix, fy - iy
    c = [elev_xy((ix + dx) * sq, (iy + dy) * sq) for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1))]
    return c[0] * (1 - ax) * (1 - ay) + c[1] * ax * (1 - ay) + c[2] * (1 - ax) * ay + c[3] * ax * ay


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--km", type=float, default=1.0)
    ap.add_argument("--no-corridor", action="store_true", help="the terrain without the track's corridor cut")
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
    canon.grader_made(grader)
    gen = lambda la, lo: grader.apply(la, lo, np.asarray(d.sample(np.asarray(la), np.asarray(lo), zoom),  # noqa: E731
                                                         np.float64), grading.ROAD_LIFT)
    cf = lambda k: md.cell(k, layers=("roads",)).layers.get("roads")  # noqa: E731
    r = a.km * 1000.0
    if not a.no_corridor:               # the block's heights as the game makes them (nrails.corridor)
        from nrails import corridor
        ceil = corridor.block_ceiling(frame, (-r - 10, -r - 10, r + 10, r + 10), cf, None)
        if ceil is not None:
            gen = corridor.cut(gen, frame, ceil)
    ground = rails.Ground(frame, gen)
    prof, _found, _arcs = canon.profile_box(frame, (-r, -r, r, r), cf, None)
    worst_way, worst_bed = [], []
    for fid, parts in prof.items():
        for pts, kind in parts:
            inside = (np.abs(pts[:, 0]) <= r) & (np.abs(pts[:, 1]) <= r) & (np.asarray(kind) == 0)
            if not inside.any():
                continue
            p = pts[inside]
            nrm = rails.normals(p[:, :2])
            for half, ref, lst in ((TRAIN_HALF_M, p[:, 2] + FLOOR_M, worst_way),
                                   (BED_HALF_M, p[:, 2] - SHOULDER_M, worst_bed)):
                lat = np.linspace(-half, half, 7)
                P = p[:, None, :2] + nrm[:, None, :] * lat[None, :, None]
                g = grid_z(lambda x, y: ground.z(np.ravel(x), np.ravel(y)).reshape(np.shape(x)),
                           P.reshape(-1, 2)).reshape(len(p), len(lat)).max(1)
                over = g - ref
                i = int(np.argmax(over))
                lst.append((float(over[i]), fid[:8], p[i, :2], int((over > 0.1).sum()), len(p)))
    for name, lst in (("train's way (over the floor)", worst_way), ("bed (over the shoulder)", worst_bed)):
        if not lst:
            continue
        v = np.array([w[0] for w in lst])
        n_bad = sum(w[3] for w in lst)
        n_all = sum(w[4] for w in lst)
        print(f"{name}: {len(lst)} pieces, worst {v.max():+.2f} m, samples over +0.1 m: {n_bad} / {n_all}")
        for w in sorted(lst, key=lambda w: -w[0])[:5]:
            la, lo, _ = frame.enu_to_geodetic(w[2][0], w[2][1], 0.0)
            print(f"      {w[0]:+.2f} m at {float(la):.5f},{float(lo):.5f} track {w[1]} ({w[3]} samples)")


if __name__ == "__main__":
    main()
