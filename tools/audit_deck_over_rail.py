#!/usr/bin/env python3
"""NRails dev tool: the free height under the road bridges over the railways round a point (real Overture cells
and elevation), upstream's decks (the NRails hook off) against ours: the deck's underside (top - roadmesh.DECK_DEPTH -
GIRDER_D) over the rail top (nrails.decks.rail_top) where each deck part crosses a track on the ground.

    .venv\\Scripts\\python.exe tools\\audit_deck_over_rail.py LAT LON [--km 2]
"""
import argparse
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
import dem        # noqa: E402
import geodesy    # noqa: E402
import mapcells   # noqa: E402
import mapdata    # noqa: E402
import netfetch   # noqa: E402
import roadmesh   # noqa: E402
import roads      # noqa: E402
from nrails import decks, hooks, paths      # noqa: E402


def solve(frame, cell_fn, elev, cells, box, on):
    keep = hooks.deck_rail_crossings
    if not on:
        hooks.deck_rail_crossings = lambda *a, **k: []
    try:
        bp = roads.BridgeProfiles(frame, cell_fn, elev)
        return bp, bp.parts(cells, box)
    finally:
        hooks.deck_rail_crossings = keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--km", type=float, default=2.0)
    a = ap.parse_args()
    cache = paths.default_cache_dir()
    net = netfetch.Fetcher(stats_dir=os.path.join(cache, "netstats"))
    md = mapdata.MapData(cache, fetcher=net)
    d = dem.Dem(os.path.join(cache, "dem"), fetcher=net)
    frame = geodesy.EnuFrame(a.lat, a.lon)
    zoom = dem.zoom_for(a.lat, 1.25, dem.FINE_ZOOM)

    def elev(la, lo):
        return np.asarray(d.sample(np.asarray(la), np.asarray(lo), zoom), np.float64)

    def cell_fn(k):
        return md.cell(k, layers=("roads",)).layers.get("roads")

    import grading
    from nrails import canon
    canon.grader_made(grading.Grader(frame, md, lambda la, lo: np.asarray(
        d.sample(np.asarray(la), np.asarray(lo), grading.PROFILE_ZOOM), np.float64)))

    dl = a.km / 111.0
    dlo = dl / max(np.cos(np.radians(a.lat)), 0.1)
    keys = mapcells.cells_for_bbox(a.lat - dl, a.lon - dlo, a.lat + dl, a.lon + dlo)
    cells = [cell_fn(k) for k in keys]
    r = a.km * 1000.0
    box = (-r, -r, r, r)
    ground = {}
    for f in cells:
        decks.load_rails(f, frame, ground)

    def gfn(xy):
        la, lo, _ = frame.enu_to_geodetic(xy[:, 0], xy[:, 1], 0.0)
        return frame.geodetic_to_enu(la, lo, elev(la, lo))[2]

    under = roadmesh.DECK_DEPTH + roadmesh.GIRDER_D
    built = {}

    def track_z(x, y):
        """The rail top nrails.rails lays at (x, y) (its tile's centre lines, the nearest sample within 3 m)."""
        from nrails import rails
        t = (int(np.floor(x / roads.TILE)), int(np.floor(y / roads.TILE)))
        if t not in built:
            cs = [cell_fn(k) for k in roads.cells_of_tile(frame, t[0], t[1], margin=rails.NEAR_M)]
            built[t] = rails.build(frame, t[0], t[1], cs, elev, cell_fn=cell_fn)     # (nrails.canon's profiles)
        rt = built[t]
        best = (3.0, None)
        for _, pts in (rt.lines if rt is not None else []):
            dd = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
            k = int(np.argmin(dd))
            if dd[k] < best[0]:
                best = (float(dd[k]), float(pts[k, 2]))
        return best[1]

    res = {}
    for on in (False, True):
        _, parts = solve(frame, cell_fn, elev, cells, box, on)
        for pid, spec, xy, z, _lon in parts:
            xy = np.asarray(xy, np.float64)[:, :2]
            s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
            for pi, arc, zr, _cl in decks.deck_rail_crossings([xy], ground, gfn)[::3]:
                zd = float(np.interp(arc, s, z))
                x, y = float(np.interp(arc, s, xy[:, 0])), float(np.interp(arc, s, xy[:, 1]))
                la, lo, _ = frame.enu_to_geodetic(x, y, 0.0)
                v = res.setdefault((pid, round(arc)), [float(la), float(lo), track_z(x, y), zr])
                v.append(zd - under)
    print(f"{len(res)} road deck crossings over tracks (free height under the girders over the rail top, m; "
          f"'est.': the top nrails.decks estimates, 'track': the one nrails.rails lays)")
    from nrails import thin
    print(f"{'part':>28} {'lat':>10} {'lon':>10} {'track-est':>9} {'upstream':>9} {'NRails':>8} {'thin':>6}")
    short = 0
    for (pid, arc), v in sorted(res.items(), key=lambda kv: kv[1][-1] - kv[1][3]):
        la, lo, zt, ze = v[:4]
        zt = ze if zt is None else zt
        up = v[4] - zt if len(v) > 4 else float("nan")
        nr = v[5] - zt if len(v) > 5 else float("nan")
        # (nrails.thin: a slab THIN_M thick without girders where the girders leave too little)
        th = nr + under - thin.THIN_M if nr < decks.RAIL_FREE_M + thin.SPARE_M and nr + under > 2.0 else nr
        short += th < decks.RAIL_FREE_M - 0.05
        print(f"{str(pid)[-28:]:>28} {la:10.5f} {lo:10.5f} {zt - ze:9.2f} {up:9.2f} {nr:8.2f} {th:6.2f}")
    print(f"under {decks.RAIL_FREE_M} m with NRails: {short} (a deck too short to climb that high at "
          f"roads.DECK_MAX_GRADE from its abutments)")


if __name__ == "__main__":
    main()
