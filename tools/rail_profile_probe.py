#!/usr/bin/env python3
"""NRails: measure the rail geometry that existing track mods use (jbeam-built track: junction.zip = MRK switch,
masuostt.zip = Maseukowice station). Clusters node X (across the track) and Z (height) to recover gauge, rail head
width and rail height above the sleeper/ballast. Read-only.

    .venv\\Scripts\\python.exe tools\\rail_profile_probe.py <zip> [vehicle-subfolder-filter]
"""
import collections
import re
import sys
import zipfile

NODE_RE = re.compile(r'\[\s*"([^"\[\]]+)"\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)')

zp = sys.argv[1]
flt = sys.argv[2] if len(sys.argv) > 2 else ""
with zipfile.ZipFile(zp) as z:
    for f in sorted(n for n in z.namelist() if n.lower().endswith(".jbeam") and flt in n):
        txt = z.read(f).decode("utf-8", "replace")
        nodes = [(n, float(x), float(y), float(zz)) for n, x, y, zz in NODE_RE.findall(txt)]
        if not nodes:
            continue
        print(f"\n== {f}: {len(nodes)} nodes; first: " + ", ".join(f"{n}({x:.3f},{y:.3f},{zz:.3f})" for n, x, y, zz in nodes[:6]))
        xs = collections.Counter(round(x, 3) for _, x, _, _ in nodes)
        zs = collections.Counter(round(zz, 3) for _, _, _, zz in nodes)
        print("   X values (most common):", ", ".join(f"{k}:{v}" for k, v in xs.most_common(14)))
        print("   Z values (most common):", ", ".join(f"{k}:{v}" for k, v in zs.most_common(10)))
        prefixes = collections.Counter(re.sub(r"\d+$", "", n) for n, *_ in nodes)
        print("   node name groups:", ", ".join(f"{k}:{v}" for k, v in prefixes.most_common(12)))
        for key in ("collision", "selfCollision", "nodeMaterial", "frictionCoef", "fixed", "triangles", "beamSpring"):
            if key in txt:
                m = re.findall(r'"' + key + r'"\s*:\s*("?[\w|.\-]+"?)', txt)
                print(f"   {key}: {collections.Counter(m).most_common(3) if m else 'present'}")
