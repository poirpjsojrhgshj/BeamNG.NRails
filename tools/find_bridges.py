#!/usr/bin/env python3
"""EarthNRails dev tool: the road bridges of given classes round a point (real Overture cells), nearest first:
their middle (lat, lon), length and class, to point tools/e2e_collect.py at.

    .venv\\Scripts\\python.exe tools\\find_bridges.py LAT LON [--km 4] [--cls motorway trunk]
"""
import argparse
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
import geodesy    # noqa: E402
import mapcells   # noqa: E402
import mapdata    # noqa: E402
import netfetch   # noqa: E402
from nrails import paths      # noqa: E402
import roads      # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--km", type=float, default=4.0)
    ap.add_argument("--cls", nargs="*", default=["motorway", "trunk"])
    a = ap.parse_args()
    cache = paths.default_cache_dir()
    md = mapdata.MapData(cache, fetcher=netfetch.Fetcher(stats_dir=os.path.join(cache, "netstats")))
    frame = geodesy.EnuFrame(a.lat, a.lon)
    dl = a.km / 111.0
    dlo = dl / max(np.cos(np.radians(a.lat)), 0.1)
    out = []
    for k in mapcells.cells_for_bbox(a.lat - dl, a.lon - dlo, a.lat + dl, a.lon + dlo):
        feats = md.cell(k, layers=("roads",)).layers.get("roads")
        if feats is None or not len(feats):
            continue
        specs = roads.road_specs(feats)
        for i in range(len(feats)):
            sp = specs[i]
            if sp is None or sp.cls not in a.cls:
                continue
            for ring in roads.bridge_parts(feats, i):
                ring = np.asarray(ring, np.float64)
                e, n, _ = frame.geodetic_to_enu(ring[:, 1], ring[:, 0], 0.0)
                xy = np.stack([np.asarray(e), np.asarray(n)], 1)
                L = float(np.hypot(*np.diff(xy, axis=0).T).sum())
                m = ring[len(ring) // 2]
                d = float(np.hypot(*xy[len(xy) // 2]))
                out.append((d, float(m[1]), float(m[0]), L, sp.cls, str(feats.ids[i])))
    seen = set()
    for d, la, lo, L, cls, fid in sorted(out):
        if fid in seen:
            continue
        seen.add(fid)
        print(f"{d / 1000:5.2f} km  {la:.5f} {lo:.5f}  {L:6.0f} m  {cls}  {fid[:8]}")


if __name__ == "__main__":
    main()
