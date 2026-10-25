#!/usr/bin/env python3
"""NRails dev tool: the road bridges over roads round a point (real Overture cells and elevation): where each
deck part crosses a ground road, the deck's height over that road, upstream's decks (NRails' deck hook off) against
ours (nrails.decks.deck_crossings: no junction at grade where the map does not join the two roads). A deck brought
down to the road under it (a "junction at grade" that is none) shows as a free height near or under 0.

    .venv\\Scripts\\python.exe tools\\audit_deck_over_road.py LAT LON [--km 1.5] [--cls motorway trunk]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--km", type=float, default=1.5)
    ap.add_argument("--cls", nargs="*", default=None)
    a = ap.parse_args()
    cache = paths.default_cache_dir()
    net = netfetch.Fetcher(stats_dir=os.path.join(cache, "netstats"))
    md = mapdata.MapData(cache, fetcher=net)
    d = dem.Dem(os.path.join(cache, "dem"), fetcher=net)
    frame = geodesy.EnuFrame(a.lat, a.lon)
    zoom = dem.zoom_for(a.lat, 1.25, dem.FINE_ZOOM)

    def raw(la, lo):
        return np.asarray(d.sample(np.asarray(la), np.asarray(lo), zoom), np.float64)
    import grading
    grader = grading.Grader(frame, md, lambda la, lo: np.asarray(d.sample(np.asarray(la), np.asarray(lo),
                                                                          grading.PROFILE_ZOOM), np.float64))

    def elev(la, lo):       # the graded ground the game's bridge solver reads (blockworker.roads_tile's elev)
        return grader.apply(la, lo, raw(la, lo), grading.ROAD_LIFT)

    def cell_fn(k):
        return md.cell(k, layers=("roads",)).layers.get("roads")
    dl = a.km / 111.0
    dlo = dl / max(np.cos(np.radians(a.lat)), 0.1)
    cells = [cell_fn(k) for k in mapcells.cells_for_bbox(a.lat - dl, a.lon - dlo, a.lat + dl, a.lon + dlo)]
    r = a.km * 1000.0
    box = (-r, -r, r, r)
    ground_lines = []
    for f in cells:
        if f is None or not len(f):
            continue
        specs = roads.road_specs(f)
        for i in range(len(f)):
            if specs[i] is None:
                continue
            for ring in roads.ground_parts(f, i):
                e, n, _ = frame.geodetic_to_enu(ring[:, 1], ring[:, 0], 0.0)
                ground_lines.append((specs[i].cls, np.c_[np.asarray(e), np.asarray(n)]))

    def gfn(xy):            # the road under at its graded level (grading lowers an underpass's road)
        la, lo, _ = frame.enu_to_geodetic(xy[:, 0], xy[:, 1], 0.0)
        return frame.geodetic_to_enu(la, lo, elev(la, lo))[2]

    under = roadmesh.DECK_DEPTH + roadmesh.GIRDER_D
    res = {}
    keep = hooks.deck_crossings
    for on in (False, True):
        if not on:
            hooks.deck_crossings = lambda crs, lines, comp, ground, gf: crs + hooks.deck_rail_crossings(lines, ground, gf)
        try:
            parts = roads.BridgeProfiles(frame, cell_fn, elev).parts(cells, box)
        finally:
            hooks.deck_crossings = keep
        for pid, spec, xy, z, _lon in parts:
            if a.cls and spec.cls not in a.cls:
                continue
            xy = np.asarray(xy, np.float64)[:, :2]
            s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
            for gcls, gl in ground_lines:
                for pi, arc, p in roads._crossings([xy], [gl]):
                    zr = float(gfn(np.asarray(p)[None])[0])
                    la, lo, _ = frame.enu_to_geodetic(p[0], p[1], 0.0)
                    v = res.setdefault((str(pid), round(arc)), [spec.cls, gcls, float(la), float(lo), min(arc, s[-1] - arc)])
                    v.append(float(np.interp(arc, s, z)) - under - zr)
    print(f"{len(res)} deck crossings over ground roads (free height under the girders, m)")
    print(f"{'deck':10s} {'under':12s} {'lat':>9s} {'lon':>9s} {'to end':>7s} {'upstream':>9s} {'NRails':>8s}")
    for k, v in sorted(res.items(), key=lambda kv: kv[1][5] if len(kv[1]) > 5 else 99):
        up = v[5] if len(v) > 5 else float("nan")
        nr = v[6] if len(v) > 6 else float("nan")
        flag = "  <-- changed" if abs(up - nr) > 0.3 else ""
        print(f"{v[0]:10s} {v[1]:12s} {v[2]:9.5f} {v[3]:9.5f} {v[4]:7.1f} {up:9.2f} {nr:8.2f}{flag}")


if __name__ == "__main__":
    main()
