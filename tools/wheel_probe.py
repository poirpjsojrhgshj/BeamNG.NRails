#!/usr/bin/env python3
"""EarthNRails: print the wheel definitions of a train mod (rows of "wheels"/"pressureWheels"/"hubWheels"/
"monoHubWheels" sections and the nodes they name) to recover the wheelset's flange / tread positions. Read-only.

    .venv\\Scripts\\python.exe tools\\wheel_probe.py <zip> [filename-filter]
"""
import re
import sys
import zipfile

NODE_RE = re.compile(r'\[\s*"([^"\[\]]+)"\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)')
zp, flt = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "")
with zipfile.ZipFile(zp) as z:
    allnodes = {}
    texts = {}
    for f in z.namelist():
        if f.lower().endswith(".jbeam"):
            t = z.read(f).decode("utf-8", "replace")
            texts[f] = t
            for n, x, y, zz in NODE_RE.findall(t):
                allnodes.setdefault(n, (float(x), float(y), float(zz)))
    for f, t in sorted(texts.items()):
        if flt not in f:
            continue
        for sec in ("pressureWheels", "hubWheels", "monoHubWheels", "wheels", "rotators"):
            for m in re.finditer(r'"' + sec + r'"\s*:\s*\[', t):
                chunk = t[m.start(): m.start() + 2500]
                print(f"\n== {f} :: {sec}\n{chunk[:1600]}")
        for m in re.finditer(r'"(flange\w*|\w*[Ff]lange\w*)"', t):
            print(f"   {f}: mention {m.group(1)}")
    for pref in ("fw", "rw", "w1", "w2", "whl", "wh", "axle", "fl", "fr"):
        hits = {k: v for k, v in allnodes.items() if k.lower().startswith(pref)}
        if hits:
            print(f"nodes {pref}*: " + ", ".join(f"{k}{v}" for k, v in list(hits.items())[:12]))
