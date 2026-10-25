#!/usr/bin/env python3
"""Far-tile build benchmark (docs/V1_4_SPEC.md §3.0, M0): build time per level, single worker,
cold (empty DEM and imagery caches, real downloads) and warm (the same tile again, caches full).
Its numbers feed the worker-wait row of table 2.5 (a burst of 4 exact children at ~40 ms each [I]).
Not a unit test (the name keeps it out of `unittest discover`): it needs the network unless
--synthetic.

    python3 server/tests/bench_build.py                         # 64 cells, 256 and 512 px, L-1..L7
    python3 server/tests/bench_build.py --cells 32 --levels -2..7 --tex 256
    python3 server/tests/bench_build.py --synthetic --repeat 5  # offline: geometry, DDS and write only
    python3 server/tests/bench_build.py --json out.json

Every build goes through earthd.Server.make_tile, the worker-thread function the server runs
(DEM sampling, the error reference, imagery mosaic + DXT1 encode, .cdae write), called here in one
thread. A cold build gets a new Server with fresh cache directories, so no level warms the next
one's DEM or imagery; the anchor's height quantum is surveyed once beforehand in a cache of its own
(or given with --q). Output goes to a temporary user folder, never the game's.

The layout comes from earthd.Server(cells=..., tex=(px,)) (docs/V1_4_SPEC.md §3.1, M1: the server's
Layout; nothing is patched in the process), so 32- and 64-cell builds can run side by side.
"""
import argparse
import json
import math
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))
import earthd  # noqa: E402
import farfield as ff  # noqa: E402
import imagery as imagerymod  # noqa: E402

LAT, LON = 36.5785, -118.2923        # Mt Whitney / Lone Pine (the default spot; USGS imagery)
POINT = (300.0, 200.0)               # each level's tile is the one containing this ENU point


def parse_levels(text):
    if ".." in text:
        a, b = (int(v) for v in text.split(".."))
        return list(range(a, b + 1))
    return [int(v) for v in text.split(",")]


def new_server(root, px, synthetic, cells):
    user = tempfile.mkdtemp(prefix="user_", dir=root)
    cache = tempfile.mkdtemp(prefix="cache_", dir=root)
    s = earthd.Server(user, cache, tile_workers=1, imagery=None if synthetic else imagerymod.DEFAULT_CHAIN,
                      near_visual="mesh", cells=cells, tex=(px,))
    if synthetic:
        import test_server
        s.dem = test_server.FakeDem()
        s.imagery = test_server.FakeImagery(os.path.join(cache, "imagery"))
    return s


def close(s):
    s.tile_pool.shutdown(wait=True)
    s.hm_pool.shutdown(wait=True)
    if s.imagery is not None:
        s.imagery.close()


def build(s, anchor, tile):
    """One make_tile call: total ms, geometry + write ms, texture ms, shape KB, texture KB."""
    t0 = time.perf_counter()
    info = s.make_tile(anchor, tile)
    total = (time.perf_counter() - t0) * 1000
    tex = info.tex_seconds * 1000
    return {"ms": total, "geomMs": total - tex, "texMs": tex, "shapeKB": info.bytes / 1024,
            "texKB": info.tex_bytes / 1024}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cells", type=int, choices=(32, 64), default=64)
    ap.add_argument("--tex", default="256,512", help="texture sizes (px), comma separated")
    ap.add_argument("--levels", default=None, help="e.g. -1..7 (default: the exact level of --cells .. 7)")
    ap.add_argument("--lat", type=float, default=LAT)
    ap.add_argument("--lon", type=float, default=LON)
    ap.add_argument("--repeat", type=int, default=3, help="warm builds per tile (median reported)")
    ap.add_argument("--modes", default="cold,warm", help="cold, warm or both")
    ap.add_argument("--q", type=float, default=None, help="height quantum (skips the relief survey)")
    ap.add_argument("--synthetic", action="store_true", help="synthetic DEM and imagery (no network)")
    ap.add_argument("--json", default=None, help="also write the rows here")
    a = ap.parse_args(argv)
    lay = ff.Layout(a.cells)
    exact = lay.exact_level
    levels = parse_levels(a.levels) if a.levels else list(range(exact, 8))
    texs = [int(v) for v in a.tex.split(",")]
    modes = set(a.modes.split(","))
    rows = []
    with tempfile.TemporaryDirectory(prefix="bench_build_") as root:
        q = a.q
        if q is None:
            if a.synthetic:
                q = 1 / 64
            else:
                s = new_server(root, texs[0], False, a.cells)
                t0 = time.perf_counter()
                q = s.anchor_q(s.new_anchor(a.lat, a.lon))
                close(s)
                print(f"relief survey: q = 1/{round(1 / q)} m ({time.perf_counter() - t0:.1f} s, not timed below)")
        print(f"{a.cells} cells, single worker, {'synthetic' if a.synthetic else 'network'} data at "
              f"{a.lat:.4f}, {a.lon:.4f}; ms = total (geometry+write / texture)")
        print(f"{'level':>5} {'px':>4} {'tris':>5} {'cold ms':>22} {'warm ms':>22} {'shape KB':>8} {'tex KB':>7}")
        for px in texs:
            for lvl in levels:
                size = ff.level_size(lvl)
                tile = ff.Tile(lvl, math.floor(POINT[0] / size), math.floor(POINT[1] / size))
                s = new_server(root, px, a.synthetic, a.cells)
                anchor = s.new_anchor(a.lat, a.lon)
                anchor.q = q
                row = {"cells": a.cells, "level": lvl, "px": px, "key": tile.key,
                       "tris": lay.tris if lvl >= exact else None}
                try:
                    first = build(s, anchor, tile)
                    if "cold" in modes:
                        row["cold"] = first
                    if "warm" in modes:
                        warm = [build(s, anchor, tile) for _ in range(max(1, a.repeat))]
                        row["warm"] = {k: statistics.median(w[k] for w in warm) for k in warm[0]}
                finally:
                    close(s)
                rows.append(row)

                def fmt(r):
                    return f"{r['ms']:7.1f} ({r['geomMs']:6.1f} / {r['texMs']:6.1f})" if r else " " * 22
                ref = row.get("warm") or row.get("cold")
                print(f"{lvl:>5} {px:>4} {row['tris'] or 0:>5} {fmt(row.get('cold')):>22} {fmt(row.get('warm')):>22} "
                      f"{ref['shapeKB']:8.0f} {ref['texKB']:7.0f}", flush=True)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(rows, f, indent=1)
    return rows


if __name__ == "__main__":
    main()
