#!/usr/bin/env python3
"""Probe: how far can BeamNG render? (user, 2026-10-10: planes see much farther than cars)

Places large marker objects (a copy of one of our L7 far-tile shapes, 32 km wide, scaled up) at
increasing distances along a fixed view direction, raises LevelInfo.visibleDistance in steps and,
from a free camera at a given altitude, records for every setting: a screenshot, the frame cost,
and which markers render (pixel check at each marker's projected screen position against a
markers-hidden reference shot). A depth-precision pair (two flat markers 5 m apart in height at
1000 km) is screenshotted twice to spot z-fighting. Everything is restored at the end (markers
deleted, visibleDistance, camera).

  python3 tools/probe_view_distance.py --out docs/research/view_distance [--alt 10000]

Run only while the user is not playing (it takes the camera for ~10 minutes).
"""
import argparse
import glob
import json
import math
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
USER = os.path.expanduser("~/.local/share/BeamNG/BeamNG.drive/current")
DISTANCES_KM = (100, 200, 400, 800, 1600, 3200)
VISIBLE_KM = (100, 1000, 5000, 20000)


def lua(code, timeout=60):
    r = subprocess.run([sys.executable, os.path.join(HERE, "mcp.py"), "lua", code],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip()


def shot(path):
    p = subprocess.run([sys.executable, os.path.join(HERE, "mcp.py"), "call", "screenshot"],
                       capture_output=True, text=True, timeout=60).stdout.strip().splitlines()[-1]
    for _ in range(80):
        if os.path.exists(p) and os.path.getsize(p) > 0:
            break
        time.sleep(0.1)
    time.sleep(0.5)
    shutil.copy(p, path)
    return path


def perf(secs=4):
    lua("beamngEarth_perfmon.snapshot() return 1")
    time.sleep(secs)
    p = json.loads(lua("return jsonEncode(beamngEarth_perfmon.snapshot())"))
    return {k: p.get(k) for k in ("fps", "p50", "p95", "maxMs")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--alt", type=float, default=10000.0, help="camera height above the origin, m")
    ap.add_argument("--scale", type=float, default=4.0, help="marker scale (L7 tile = 32.8 km wide)")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)

    # a stable copy of a big far-tile shape (the server's session files come and go)
    sess = sorted(glob.glob(os.path.join(USER, "temp", "beamngEarth", "*")), key=os.path.getmtime)[-1]
    src = sorted(glob.glob(os.path.join(sess, "far_*_7_*.cdae")))
    if not src:
        sys.exit("no L7 far tile in the current session to copy")
    dst_dir = os.path.join(USER, "temp", "beamngEarth_probe")
    os.makedirs(dst_dir, exist_ok=True)
    shutil.copy(src[0], os.path.join(dst_dir, "marker.cdae"))
    shape = "/temp/beamngEarth_probe/marker.cdae"
    print("marker shape from", os.path.basename(src[0]), flush=True)

    saved = json.loads(lua("""local c = core_camera.getPosition()
return jsonEncode({ vis = scenetree.theLevelInfo.visibleDistance })"""))
    print("saved", saved, flush=True)
    lua("if not beamngEarth_perfmon then extensions.load('beamngEarth_perfmon') end return 1")
    results = {"alt": a.alt, "scale": a.scale, "distances_km": DISTANCES_KM, "runs": []}
    try:
        # camera: above the player's position, level, looking north; markers along +y
        lua(f"""local v = getPlayerVehicle(0); local p = v and v:getPosition() or vec3(0, 0, 0)
BNGE_VD = {{ x = p.x, y = p.y, z = {a.alt}, ids = {{}} }}
commands.setFreeCamera()
core_camera.setPosition(0, vec3(BNGE_VD.x, BNGE_VD.y, BNGE_VD.z))
core_camera.setRotation(0, quatFromDir(vec3(0, 1, 0), vec3(0, 0, 1)))
return 1""")
        # markers: flat tiles centred on the view axis, raised so each sits on the camera's horizon
        # line minus a little (a flat world: no curvature drop is applied, so they are in view)
        for i, km in enumerate(DISTANCES_KM):
            lua(f"""local o = createObject('TSStatic')
o:setField('shapeName', 0, '{shape}'); o:setField('collisionType', 0, 'None'); o.canSave = false
local s = {a.scale}
o:setPosition(vec3(BNGE_VD.x - 16384 * s, BNGE_VD.y + {km * 1000} - 16384 * s, BNGE_VD.z - 2000 - {i} * 1500))
o:setScale(vec3(s, s, 1))
o:registerObject('bngeVD_{km}'); scenetree.MissionGroup:addObject(o)
table.insert(BNGE_VD.ids, o:getID())
return 1""")
        # depth pair at 1000 km: two flat markers 5 m apart, offset sideways
        for j, dz in enumerate((0.0, 5.0)):
            lua(f"""local o = createObject('TSStatic')
o:setField('shapeName', 0, '{shape}'); o:setField('collisionType', 0, 'None'); o.canSave = false
o:setPosition(vec3(BNGE_VD.x + 60000, BNGE_VD.y + 1000000, BNGE_VD.z - 6000 + {dz}))
o:setScale(vec3(3, 3, 1)); o:registerObject('bngeVDz_{j}'); scenetree.MissionGroup:addObject(o)
table.insert(BNGE_VD.ids, o:getID())
return 1""")
        time.sleep(3)
        for vis in VISIBLE_KM:
            lua(f"scenetree.theLevelInfo.visibleDistance = {vis * 1000} return 1")
            time.sleep(2)
            run = {"visible_km": vis, "perf": perf()}
            run["shot"] = shot(os.path.join(a.out, f"vis{vis}km.png"))
            run["shot2"] = shot(os.path.join(a.out, f"vis{vis}km_b.png"))   # depth flicker check
            lua("for _, id in ipairs(BNGE_VD.ids) do local o = scenetree.findObjectById(id); if o then o:setHidden(true) end end return 1")
            time.sleep(1)
            run["ref"] = shot(os.path.join(a.out, f"vis{vis}km_ref.png"))
            lua("for _, id in ipairs(BNGE_VD.ids) do local o = scenetree.findObjectById(id); if o then o:setHidden(false) end end return 1")
            print(json.dumps(run), flush=True)
            results["runs"].append(run)
    finally:
        print(lua(f"""for _, id in ipairs((BNGE_VD or {{}}).ids or {{}}) do
  local o = scenetree.findObjectById(id); if o then o:delete() end end
BNGE_VD = nil
scenetree.theLevelInfo.visibleDistance = {saved['vis']}
commands.setGameCamera()
return 'restored'"""), flush=True)
    json.dump(results, open(os.path.join(a.out, "results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
