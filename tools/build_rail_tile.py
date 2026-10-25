#!/usr/bin/env python3
"""NRails dev tool: build the rail meshes of the road tiles around a place with real data (Overture cells + the
DEM from the cache, fetched if missing), write them as .cdae next to a JSON summary, and read them back (cdae.read).
No game needed. Ground roads are taken as straight chunks from the same cells for the level-crossing test.

    .venv\\Scripts\\python.exe tools\\build_rail_tile.py 48.8443 2.3744 [--around 1] [--out DIR]
"""
import argparse
import json
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
import cdae       # noqa: E402
import dem        # noqa: E402
import geodesy    # noqa: E402
import mapdata    # noqa: E402
import netfetch   # noqa: E402
from nrails import paths      # noqa: E402
from nrails import rails      # noqa: E402
import roads      # noqa: E402


def road_chunks(cells, frame, elev):
    """Ground carriageways as simple chunks {n, w} (no grading): enough to find the level crossings."""
    out = []
    for feats in cells:
        if feats is None:
            continue
        specs = roads.road_specs(feats, None, None, False)
        for i, sp in enumerate(specs):
            if sp is None:
                continue
            for ring in roads.ground_parts(feats, i):
                h = np.asarray(elev(ring[:, 1], ring[:, 0]), np.float64)
                e, n, u = frame.geodetic_to_enu(ring[:, 1], ring[:, 0], h)
                out.append({"n": np.c_[e, n, u].tolist(), "w": float(sp.width)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--around", type=int, default=1, help="tiles either side of the centre tile")
    ap.add_argument("--out", default=os.path.join(ROOT, "build", "railtest"))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    cache = paths.default_cache_dir()
    net = netfetch.Fetcher(stats_dir=os.path.join(cache, "netstats"))
    md = mapdata.MapData(cache, fetcher=net)
    d = dem.Dem(os.path.join(cache, "dem"), fetcher=net)
    frame = geodesy.EnuFrame(a.lat, a.lon)
    zoom = dem.zoom_for(a.lat, 1.25, dem.FINE_ZOOM)

    def elev(la, lo):
        return np.asarray(d.sample(np.asarray(la), np.asarray(lo), zoom), np.float64)

    summary = []
    for ty in range(-a.around - 1, a.around + 1):
        for tx in range(-a.around - 1, a.around + 1):
            t0 = time.perf_counter()
            cells = [md.cell(k, layers=("roads",)).layers.get("roads") for k in roads.cells_of_tile(frame, tx, ty)]
            chunks = road_chunks(cells, frame, elev)
            rt = rails.build(frame, tx, ty, cells, elev, chunks)
            dt = time.perf_counter() - t0
            row = {"tile": [tx, ty], "seconds": round(dt, 2)}
            if rt is not None:
                for what, mesh, col in rt.shapes():
                    p = os.path.join(a.out, f"{what}_{tx}_{ty}.cdae")
                    rails.write(p, mesh, collision_only=col)
                    back = cdae.read(p)
                    row[what] = {"tris": int(len(mesh[1])), "verts": int(len(mesh[0])), "bytes": os.path.getsize(p),
                                 "z": [round(float(mesh[0][:, 2].min()), 2), round(float(mesh[0][:, 2].max()), 2)],
                                 "read_back": type(back).__name__}
                row["crossings"] = len(rt.xpts)
            summary.append(row)
            print(json.dumps(row))
    with open(os.path.join(a.out, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    md.close()


if __name__ == "__main__":
    main()
