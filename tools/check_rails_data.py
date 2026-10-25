#!/usr/bin/env python3
"""NRails: prove the live data path delivers rails. Fetches the 'roads' layer of one z14 cell through the real
mapdata/overture/DuckDB pipeline (cache: server/paths.py default_cache_dir()) and counts subtype road vs rail + rail classes.

    .venv\\Scripts\\python.exe tools\\check_rails_data.py                 (a city station)
    .venv\\Scripts\\python.exe tools\\check_rails_data.py 48.8443 2.3743  (Paris Gare de Lyon)
"""
import collections
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))
import mapcells  # noqa: E402
import mapdata   # noqa: E402

lat, lon = (float(sys.argv[1]), float(sys.argv[2])) if len(sys.argv) > 2 else (48.8443, 2.3744)
key = mapcells.cell_of(lat, lon)
md = mapdata.MapData()
t0 = time.perf_counter()
cd = md.cell(key, ("roads",))
dt = time.perf_counter() - t0
feats = cd.layers["roads"]
attrs = feats.attrs
sub = [str(s) for s in attrs.get("subtype", ["road"] * len(feats))]
cls = [str(c) for c in attrs.get("class", [""] * len(feats))]
print(f"cell {key} @ {lat},{lon}: {len(feats)} features in {dt:.1f} s")
print("attribute columns:", sorted(attrs.keys()))
print("subtypes:", dict(collections.Counter(sub)))
print("rail classes:", dict(collections.Counter(c for s, c in zip(sub, cls) if s == "rail")))
for col in ("subclass", "osm_layer", "src_dataset", "is_bridge", "is_tunnel", "level", "gauge", "electrified"):
    if col in attrs:
        vals = [str(v) for s, v in zip(sub, attrs[col]) if s == "rail"]
        print(f"rail {col}:", dict(collections.Counter(vals).most_common(6)))
md.close()
