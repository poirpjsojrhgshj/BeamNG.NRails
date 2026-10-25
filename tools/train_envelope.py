#!/usr/bin/env python3
"""EarthNRails: kinematic envelope of the installed rolling stock, measured from the RAIL TOP.

Rail top = axle node height - tread radius (pressureWheels node1/node2 of the first wheel rows; the tread is the
smaller of the two radii per axle, the flange disc the larger). Reports node height percentiles above the rail top
(p99 ignores stray helper nodes such as cameras / ref points), width, and the flange disc's reach below the rail top
and its half-width (what must stay clear between the rails). Read-only.

    .venv\\Scripts\\python.exe tools\\train_envelope.py
"""
import glob
import os
import re
import zipfile

import numpy as np

REPO = os.path.join(os.environ.get("LOCALAPPDATA", ""), "BeamNG", "BeamNG.drive", "current", "mods", "repo")
NODE_RE = re.compile(r'\[\s*"([^"\[\]]+)"\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)')
ROW_RE = re.compile(r'\[\s*"[^"]+"\s*,\s*"[^"]+"\s*,\s*"[^"]+"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,')
RAD_RE = re.compile(r'"radius"\s*:\s*(\d+(?:\.\d+)?)')
HUBW_RE = re.compile(r'"hubWidth"\s*:\s*(\d+(?:\.\d+)?)')

for zp in sorted(glob.glob(os.path.join(REPO, "*.zip"))):
    with zipfile.ZipFile(zp) as z:
        files = {n: z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.lower().endswith(".jbeam")}
    if not files or "masuostt" in zp or "junction" in zp:
        continue
    nodes = {}
    for t in files.values():
        for n, x, y, zz in NODE_RE.findall(t):
            nodes.setdefault(n, (float(x), float(y), float(zz)))
    radii, hubw, axle_z = [], [], []
    for t in files.values():
        if "pressureWheels" not in t and "hubWheels" not in t:
            continue
        radii += [float(r) for r in RAD_RE.findall(t)]
        hubw += [float(w) for w in HUBW_RE.findall(t)]
        for a, b in ROW_RE.findall(t):
            if a in nodes and b in nodes:
                axle_z.append((nodes[a][2] + nodes[b][2]) / 2)
    if not radii:   # hubWheels-only mods (tank, DMM512): hubRadius; ignore small hub helpers (< 0.3 m)
        radii = [float(r) for t in files.values() for r in re.findall(r'"hubRadius"\s*:\s*(\d+(?:\.\d+)?)', t)
                 if float(r) >= 0.3]
    if not radii or not axle_z:
        print(f"{os.path.basename(zp)}: wheels not parsed")
        continue
    tread, flange = min(radii), max(radii)
    rail_top = float(np.median(axle_z)) - tread
    P = np.array(list(nodes.values()))
    h = P[:, 2] - rail_top
    w = np.abs(P[:, 0])
    print(f"{os.path.basename(zp):16s} rail top z={rail_top:+.3f} | height above rail: p99 {np.percentile(h, 99):.2f} m, "
          f"max {h.max():.2f} m | half-width p99 {np.percentile(w, 99):.2f} m | tread r {tread} / flange disc r {flange} "
          f"-> disc reaches {flange - tread:.3f} m under the rail top, hubWidths {sorted(set(hubw))}")
