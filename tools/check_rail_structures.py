#!/usr/bin/env python3
"""NRails: how many rail segments get bridge / tunnel ranges from the CURRENT pipeline (roads.level_ranges:
road_flags + level_rules). Rails carry their flags in Overture's rail_flags, which overture.py does not read yet.

    .venv\\Scripts\\python.exe tools\\check_rail_structures.py [lat lon ...]
"""
import collections
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "server"))
import mapcells  # noqa: E402
import mapdata   # noqa: E402
import roads     # noqa: E402

SITES = [("a city station (tunnel + viaduc)", 48.8443, 2.3744),
         ("Viaduc de Chaumont (A-line Paris-Mulhouse)", 48.1046, 5.1307),
         ("a city station", 48.5850, 7.7350),
         ("Paris Gare de Lyon", 48.8443, 2.3743)]
if len(sys.argv) > 2:
    a = sys.argv[1:]
    SITES = [(f"{a[k]},{a[k + 1]}", float(a[k]), float(a[k + 1])) for k in range(0, len(a) - 1, 2)]

md = mapdata.MapData()
for name, lat, lon in SITES:
    key = mapcells.cell_of(lat, lon)
    feats = md.cell(key, ("roads",)).layers["roads"]
    sub = [str(s) for s in feats.attrs["subtype"]]
    cls = [str(c) for c in feats.attrs["class"]]
    stat = collections.Counter()
    for i, s in enumerate(sub):
        kinds = {k for _, _, k in roads.level_ranges(feats, i)}
        tag = "+".join(sorted(kinds)) or "ground"
        stat[(s, tag)] += 1
    rails = {k: v for k, v in stat.items() if k[0] == "rail"}
    road_br = sum(v for (s, t), v in stat.items() if s == "road" and t != "ground")
    print(f"{name} [{key}]: rails {sum(rails.values())} -> {dict((t, v) for (_, t), v in rails.items())}; "
          f"roads with bridge/tunnel: {road_br}; rail classes {dict(collections.Counter(c for s, c in zip(sub, cls) if s == 'rail'))}")
md.close()
