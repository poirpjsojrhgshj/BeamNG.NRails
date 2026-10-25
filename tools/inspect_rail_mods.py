#!/usr/bin/env python3
"""NRails: read-only survey of the installed rail mods (zips in <user>/mods and mods/repo).

For each zip: top-level content (vehicles / levels / art), and for each vehicle the bounding box of all its jbeam
nodes (all part variants together, so an upper bound) -> length / width / height above the lowest node.
Also lists wheel-related jbeam keys (hubWidth, radius, wheelOffset) and any 'gauge'/'rail' mentions.

    .venv\\Scripts\\python.exe tools\\inspect_rail_mods.py [zip ...]
"""
import collections
import glob
import os
import re
import sys
import zipfile

USER = os.path.join(os.environ.get("LOCALAPPDATA", ""), "BeamNG", "BeamNG.drive", "current", "mods")
NODE_RE = re.compile(r'\[\s*"([^"\[\]]+)"\s*,\s*(-?\d+(?:\.\d+)?(?:e-?\d+)?)\s*,\s*(-?\d+(?:\.\d+)?(?:e-?\d+)?)\s*,'
                     r'\s*(-?\d+(?:\.\d+)?(?:e-?\d+)?)\s*[,\]]', re.I)
KEY_RE = re.compile(r'"(hubWidth|hubRadius|radius|tireWidth|wheelOffset|wheelDir|trackWidth|gauge|flange\w*)"\s*:\s*'
                    r'(-?\d+(?:\.\d+)?)', re.I)


def survey(path):
    print(f"\n######## {os.path.basename(path)}  ({os.path.getsize(path) / 2**20:.0f} MB)")
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        tops = collections.Counter("/".join(n.split("/")[:2]) for n in names if "/" in n)
        for t, n in sorted(tops.items()):
            print(f"  {t}/  ({n} files)")
        veh = collections.defaultdict(list)
        for n in names:
            m = re.match(r"vehicles/([^/]+)/.*\.jbeam$", n, re.I)
            if m:
                veh[m.group(1)].append(n)
        for v, files in sorted(veh.items()):
            xs, ys, zs, keys = [], [], [], collections.Counter()
            for f in files:
                txt = z.read(f).decode("utf-8", "replace")
                for _, x, y, zz in NODE_RE.findall(txt):
                    xs.append(float(x)), ys.append(float(y)), zs.append(float(zz))
                for k, val in KEY_RE.findall(txt):
                    keys[(k, round(float(val), 3))] += 1
            if not xs:
                print(f"  vehicle {v}: no nodes parsed ({len(files)} jbeam)")
                continue
            print(f"  vehicle {v}: {len(xs)} nodes in {len(files)} jbeam | X {min(xs):.2f}..{max(xs):.2f} "
                  f"(w {max(xs) - min(xs):.2f}) | Y {min(ys):.2f}..{max(ys):.2f} (l {max(ys) - min(ys):.2f}) | "
                  f"Z {min(zs):.2f}..{max(zs):.2f} (h {max(zs) - min(zs):.2f} m)")
            top = sorted(keys.items(), key=lambda kv: -kv[1])[:12]
            if top:
                print("     wheel keys:", ", ".join(f"{k}={v} x{c}" for (k, v), c in top))
        other = [n for n in names if re.search(r"\.(dae|cdae)$", n, re.I) and not n.lower().startswith("vehicles/")]
        if other:
            print(f"  meshes outside vehicles: {len(other)} e.g. " + ", ".join(other[:8]))
        lv = sorted({n.split("/")[1] for n in names if n.lower().startswith("levels/") and n.count("/") > 1})
        if lv:
            print("  levels:", lv)


zips = sys.argv[1:] or sorted(glob.glob(os.path.join(USER, "*.zip")) + glob.glob(os.path.join(USER, "repo", "*.zip")))
for p in zips:
    try:
        survey(p)
    except (OSError, zipfile.BadZipFile) as e:
        print(f"{p}: {e}")
