#!/usr/bin/env python3
"""EarthNRails dev tool: every road crossing a track round a point (real Overture cells and elevation), as the track
profile sorts it (nrails.rails.structure_masks): a level crossing (and why), or grade-separated (the road over / under
the track: its ground masked for the track), with the DEM bump at the crossing; and the track's level there with
and without the masks (BNGE_RAIL_SEP).

    .venv\\Scripts\\python.exe tools\\audit_rail_separation.py LAT LON [--km 1.5]
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
from nrails import paths, rails      # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--km", type=float, default=1.5)
    a = ap.parse_args()
    cache = paths.default_cache_dir()
    net = netfetch.Fetcher(stats_dir=os.path.join(cache, "netstats"))
    md = mapdata.MapData(cache, fetcher=net)
    d = dem.Dem(os.path.join(cache, "dem"), fetcher=net)
    frame = geodesy.EnuFrame(a.lat, a.lon)
    zoom = dem.zoom_for(a.lat, 1.25, dem.FINE_ZOOM)

    def elev(la, lo):
        return np.asarray(d.sample(np.asarray(la), np.asarray(lo), zoom), np.float64)
    ground = rails.Ground(frame, elev)
    dl = (a.km + 0.3) / 111.0
    dlo = dl / max(np.cos(np.radians(a.lat)), 0.1)
    cells = [md.cell(k, layers=("roads",)).layers.get("roads")
             for k in mapcells.cells_for_bbox(a.lat - dl, a.lon - dlo, a.lat + dl, a.lon + dlo)]
    r = a.km * 1000.0
    near = (-r, -r, r, r)
    roads_near = rails.road_lines(cells, frame, near)
    structs = rails.road_structs(cells, frame, near)
    conns = rails.rail_connectors(cells)
    n_level = n_sep = 0
    for fid, cls, xy, ranges in rails.rail_features(cells, frame, near):
        if cls not in rails.HEAVY_CLASSES:
            continue
        w = rails._window(xy, ranges, near)
        if w is None:
            continue
        pxy, s, kind, sel = w
        for x in rails.crossings_on(pxy, s, roads_near):
            k = int(np.clip(np.searchsorted(s, x["s"]), 0, len(s) - 1))
            if kind[k] != 0 or not sel[k]:
                continue
            st = structs.get(x["road"])
            if st is None:
                continue
            lvl = rails.is_level_crossing(x, conns.get(fid, set()), st, ground, pxy, s)
            shared = bool(conns.get(fid) and st["conns"] and conns[fid] & st["conns"])
            sp = np.clip(np.array([x["s"] - rails.SEP_PROBE_M, x["s"], x["s"] + rails.SEP_PROBE_M]), s[0], s[-1])
            g = ground.z(np.interp(sp, s, pxy[:, 0]), np.interp(sp, s, pxy[:, 1]))
            bump = float(g[1] - (g[0] + g[2]) / 2)
            la, lo, _ = frame.enu_to_geodetic(x["at"][0], x["at"][1], 0.0)
            n_level += lvl
            n_sep += not lvl
            print(f"{float(la):.5f},{float(lo):.5f}  {cls:14s} x {st['cls']:13s} {'LEVEL' if lvl else 'SEPARATED':9s} "
                  f"shared={int(shared)} layer={st['layer']:g} bump={bump:+.2f} m")
        for xx in rails.crossings_on(pxy, s, [(rf, q, hw) for rf, st in structs.items() for kd, q, hw in st["parts"]
                                              if kd != "ground"]):
            la, lo, _ = frame.enu_to_geodetic(xx["at"][0], xx["at"][1], 0.0)
            print(f"{float(la):.5f},{float(lo):.5f}  {cls:14s} x {structs[xx['road']]['cls']:13s} STRUCTURE "
                  f"({[kd for kd, *_ in structs[xx['road']]['parts'] if kd != 'ground']})")
    print(f"level {n_level}, separated {n_sep}")


if __name__ == "__main__":
    main()
