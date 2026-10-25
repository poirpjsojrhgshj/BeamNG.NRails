#!/usr/bin/env python3
"""Watch how terrain-follow commits cost more as a game session ages (2026-10-18: ~30 ms in a fresh game,
100-380 ms hours later). Every --every seconds: the mod's new commits (each with its frame and the two after
it, beamngEarth_core.status().commits), GPU memory (amdgpu sysfs), and what accumulates in the session
(far-field materials and objects, TSStatics, Materials, textures). Passive: no swaps of its own.

    python3 tools/age_watch.py --out /tmp/age.jsonl [--every 30]

One JSON line per poll: {t, vramMB, gttMB, counts, commits: [[f0, f1, f2, engine], ...]}.
"""
import argparse
import glob
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mcp  # noqa: E402

LUA = r'''
local s = load("return " .. beamngEarth_core.status())()     -- (status() is a dumps() string)
local f = require("beamngEarth/farfield").stats()
local function count(cls) local n = 0 for _ in pairs(scenetree.findClassObjects(cls) or {}) do n = n + 1 end return n end
return jsonEncode({ commits = s.commits, follow = s.followCount, far = { materials = f.materials, live = f.live,
  imports = f.imports, textured = f.textured }, tsstatic = count("TSStatic"), material = count("Material"),
  forest = count("Forest"), trees = s.trees and s.trees.items })
'''


def gpu():
    for d in glob.glob("/sys/class/drm/card*/device"):
        try:
            return (int(open(d + "/mem_info_vram_used").read()) >> 20, int(open(d + "/mem_info_gtt_used").read()) >> 20)
        except OSError:
            continue
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--every", type=float, default=30.0)
    a = ap.parse_args()
    seen = None
    t0 = time.time()
    while True:
        try:
            d = json.loads(str(mcp.call("run_lua", {"code": LUA})))
        except Exception as e:      # the game busy / restarting: try again next time
            print("poll failed:", e, file=sys.stderr)
            time.sleep(a.every)
            continue
        follow = d.pop("follow", None)
        commits = d.pop("commits", None) or []
        new = commits if seen is None else commits[-max(0, min(len(commits), (follow or 0) - seen)):] \
            if follow and follow > seen else []
        seen = follow if follow is not None else seen
        vram, gtt = gpu()
        row = {"t": round(time.time() - t0), "vramMB": vram, "gttMB": gtt, "follow": follow, "counts": d,
               "commits": [[round(x, 1) for x in (c.get("f") or [])] + [c.get("engine")] for c in new]}
        with open(a.out, "a") as f:
            f.write(json.dumps(row) + "\n")
        time.sleep(a.every)


if __name__ == "__main__":
    main()
