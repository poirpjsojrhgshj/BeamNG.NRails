#!/usr/bin/env python3
"""NRails dev tool: the railway tunnels (and bridges: --kind bridge) round a point (real Overture cells),
nearest first: their middle (lat, lon), length, class, segment id. To point tools/e2e_collect.py at.

    .venv\\Scripts\\python.exe tools\\find_rail_tunnels.py LAT LON [--km 10] [--kind tunnel]
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
import roads      # noqa: E402
from nrails import paths      # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--km", type=float, default=10.0)
    ap.add_argument("--kind", default="tunnel", choices=["tunnel", "bridge"])
    a = ap.parse_args()
    cache = paths.default_cache_dir()
    md = mapdata.MapData(cache, fetcher=netfetch.Fetcher(stats_dir=os.path.join(cache, "netstats")))
    frame = geodesy.EnuFrame(a.lat, a.lon)
    dl = a.km / 111.0
    dlo = dl / max(np.cos(np.radians(a.lat)), 0.1)
    out, seen = [], set()
    for k in mapcells.cells_for_bbox(a.lat - dl, a.lon - dlo, a.lat + dl, a.lon + dlo):
        feats = md.cell(k, layers=("roads",)).layers.get("roads")
        if feats is None or not len(feats) or "subtype" not in feats.attrs:
            continue
        sub, cls = feats.attrs["subtype"], feats.attrs.get("class")
        for i in range(len(feats)):
            if str(sub[i]) != "rail" or str(feats.ids[i]) in seen:
                continue
            for s0, s1, kind in roads.level_ranges(feats, i):
                if kind != a.kind:
                    continue
                for part in feats.parts(i):
                    for ring in part:
                        ring = np.asarray(ring, np.float64)
                        if len(ring) < 2:
                            continue
                        sub_ring = roads.sub_polyline(ring, s0, s1)
                        if sub_ring is None or len(sub_ring) < 2:
                            continue
                        e, n, _ = frame.geodetic_to_enu(sub_ring[:, 1], sub_ring[:, 0], 0.0)
                        xy = np.stack([np.asarray(e), np.asarray(n)], 1)
                        L = float(np.hypot(*np.diff(xy, axis=0).T).sum())
                        m = sub_ring[len(sub_ring) // 2]
                        d = float(np.hypot(*xy[len(xy) // 2]))
                        out.append((d, float(m[1]), float(m[0]), L, str(cls[i]) if cls is not None else "?",
                                    str(feats.ids[i])))
                        seen.add(str(feats.ids[i]))
    for d, la, lo, L, c, fid in sorted(out)[:40]:
        print(f"{d / 1000:6.2f} km  {la:.5f} {lo:.5f}  {L:7.0f} m  {c:15s} {fid[:8]}")


if __name__ == "__main__":
    main()
