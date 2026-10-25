#!/usr/bin/env python3
"""EarthNRails dev tool: every place a road meets a railway in the cells around a point, and what the generator makes
of it (level crossing, road bridge over, road tunnel under, or a road the tile does not draw as a chunk).

    .venv\\Scripts\\python.exe tools\\audit_crossings.py LAT LON [--r 600]
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
import mapgeom    # noqa: E402
from nrails import rails      # noqa: E402
import roads      # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lat", type=float)
    ap.add_argument("lon", type=float)
    ap.add_argument("--r", type=float, default=600.0)
    a = ap.parse_args()
    frame = geodesy.EnuFrame(a.lat, a.lon)
    md = mapdata.MapData()
    keys = set()
    for dx in (-a.r, 0, a.r):
        for dy in (-a.r, 0, a.r):
            la, lo, _ = frame.enu_to_geodetic(dx, dy, 0.0)
            keys.add(mapcells.cell_of(float(la), float(lo)))
    cells = [md.cell(k, layers=("roads",)).layers.get("roads") for k in sorted(keys, key=str)]
    box = (-a.r, -a.r, a.r, a.r)
    rl = rails.rail_features(cells, frame, box)
    road_rows, seen = [], set()
    for feats in cells:
        specs = roads.road_specs(feats, None, None, False)
        for i in range(len(feats)):
            if str(feats.attrs["subtype"][i]) != "road" or str(feats.ids[i]) in seen:
                continue
            seen.add(str(feats.ids[i]))
            cls = str(feats.attrs["class"][i])
            for kind, parts in (("ground", roads.ground_parts(feats, i)), ("bridge", roads.bridge_parts(feats, i)),
                                ("tunnel", roads.tunnel_parts(feats, i))):
                for ring in parts:
                    e, n = mapgeom.enu_xy(feats, frame, ring)
                    sp = specs[i]
                    painted = sp is not None and roads.terrain_surface(sp)
                    road_rows.append((str(feats.ids[i])[:10], cls, kind, sp, painted, np.c_[e, n]))
    print(f"{len(rl)} rail segments, {len(road_rows)} road parts within {a.r:.0f} m")
    for fid, rcls, xy, rng in rl:
        for rid, cls, kind, sp, painted, q in road_rows:
            for i, ti, j, uj in rails._seg_intersections(xy, q):
                p = xy[i] + ti * (xy[i + 1] - xy[i])
                if abs(p[0]) > a.r or abs(p[1]) > a.r:
                    continue
                f = (np.hypot(*np.diff(xy[:i + 1], axis=0).T).sum() + ti * np.hypot(*(xy[i + 1] - xy[i]))) / max(
                    np.hypot(*np.diff(xy, axis=0).T).sum(), 1e-9)
                rk = next((k for s0, s1, k in rng if s0 <= f <= s1), "ground")
                verdict = ("level crossing" if kind == "ground" and rk == "ground" and sp is not None and not painted
                           else "road over rail" if kind == "bridge" or rk == "tunnel"
                           else "rail over road" if kind == "tunnel" or rk == "bridge"
                           else "NOT DRAWN AS CHUNK (no spec)" if sp is None
                           else "NOT DRAWN AS CHUNK (painted into the ground)")
                print(f"  ({p[0]:7.1f},{p[1]:7.1f}) rail {fid[:10]} {rcls:14s} [{rk:6s}] x road {rid} {cls:12s} "
                      f"[{kind:6s}] w={getattr(sp, 'width', None)} -> {verdict}")
    md.close()


if __name__ == "__main__":
    main()
