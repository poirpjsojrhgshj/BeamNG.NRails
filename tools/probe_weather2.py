#!/usr/bin/env python3
"""Weather probe, second pass (game focused, no other mods): baseline frame time, cloud coverage
calibration looking 20 deg up at 4 headings, cloud and rain frame cost, and ground wind on a rolling
test car. The user's vehicle is frozen meanwhile and restored; every setting is put back.

  python3 tools/probe_weather2.py --out docs/research/weather_probe2
"""
import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe_weather import lua, shot, perf, cloud_fraction, SETUP, RESTORE   # noqa: E402

HEADINGS = (0, 90, 180, 270)


def cam(az, pitch_deg, up=3.0):
    a, p = math.radians(az), math.radians(pitch_deg)
    lua(f"""local v = getPlayerVehicle(0); local q = v:getPosition()
commands.setFreeCamera(); core_camera.setPosition(0, vec3(q.x, q.y, q.z + {up}))
core_camera.setRotation(0, quatFromDir(vec3({math.sin(a) * math.cos(p)}, {math.cos(a) * math.cos(p)}, {math.sin(p)}), vec3(0, 0, 1))); return 1""")


def set_clouds(cov, cirrus_density=0.0, cirrus_cov=0.0):
    lua(f"local o = scenetree.findObject('bngEarthClouds'); o.coverage = {cov}; o.cirrusCoverage = {cirrus_cov}; "
        f"o.cirrusDensity = {cirrus_density}; o:postApply() return 1")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    res = {}
    saved = json.loads(lua("""local o = scenetree.findObject('bngEarthClouds')
return jsonEncode({ cov = o.coverage, cirrus = o.cirrusCoverage, cirrusDensity = o.cirrusDensity })"""))
    lua("if not beamngEarth_perfmon then extensions.load('beamngEarth_perfmon') end return 1")
    focused = lua("return tostring(Engine.getCurrentFpsLimitReason().windowFocused)")
    res["focused"] = focused
    print("saved", saved, "focused", focused, flush=True)
    try:
        # 1 baseline frame cost (no clouds) and cloud cost, fixed view to the south
        cam(180, 2)
        costs = {}
        for c in (0.0, 0.5, 0.9):
            set_clouds(c)
            time.sleep(3)
            costs[str(c)] = perf(5)
            print("cloud cost", c, costs[str(c)], flush=True)
        res["cloudCost"] = costs

        # 2 coverage calibration: 20 deg up, 4 headings
        cal = {}
        for c in (0.0, 0.6, 0.7, 0.8, 0.9, 0.95):
            set_clouds(c)
            time.sleep(3)
            fr = []
            for h in HEADINGS:
                cam(h, 20)
                time.sleep(1.0)
                fr.append(shot(os.path.join(a.out, f"cal_{c:.2f}_h{h}.png")))
            cal[c] = fr
        table = {}
        for c, shots in cal.items():
            refs = cal[0.0]
            fracs = [cloud_fraction(s, r) for s, r in zip(shots, refs)]
            table[str(c)] = {"perHeading": fracs, "mean": round(sum(fracs) / len(fracs), 3)}
            print(f"coverage {c:.2f}: sky fraction {table[str(c)]['mean']} {fracs}", flush=True)
        res["coverage"] = table
        # cirrus check
        set_clouds(0.0, 0.5, 0.5)
        time.sleep(3)
        cam(180, 30)
        time.sleep(1)
        shot(os.path.join(a.out, "cirrus_d0.5_c0.5.png"))

        # 3 rain cost (game camera, clouds as saved)
        set_clouds(saved["cov"], saved["cirrusDensity"], saved["cirrus"])
        lua("commands.setGameCamera() return 1")
        lua("""local p = createObject('Precipitation'); p:setField('dataBlock', 0, 'rain_medium'); p:setField('followCam', 0, '1')
p:setField('boxWidth', 0, '40'); p:setField('boxHeight', 0, '30'); p.canSave = false; p:registerObject('bngEarthRainProbe')
scenetree.MissionGroup:addObject(p); p.numDrops = 0; p:postApply(); return 1""")
        rain = {"0": perf(5)}
        for n in (3000, 9000):
            lua(f"local p = scenetree.findObject('bngEarthRainProbe'); p.numDrops = {n}; p:postApply(); if p.setPercentage then p:setPercentage(1) end return 1")
            time.sleep(2)
            rain[str(n)] = perf(5)
            shot(os.path.join(a.out, f"rain_{n}.png"))
        res["rain"] = rain
        print("rain", rain, flush=True)
        lua("local p = scenetree.findObject('bngEarthRainProbe'); if p then p:delete() end return 1")

        # 4 wind on a rolling test car: two runs of 8 s coasting at ~3 m/s, without and with 25 m/s
        # side wind (from the car's left); compare the sideways drift
        print("test car", lua(SETUP), flush=True)
        time.sleep(4)
        drift = {}
        for wind in (0, 25):
            lua("""local v = getPlayerVehicle(0)
v:queueLuaCommand('input.event(\"parkingbrake\", 0, 1); input.event(\"brake\", 0, 1); input.event(\"throttle\", 0, 1)')
local d = v:getDirectionVector(); BNGE_WX.dir = { x = d.x, y = d.y }
local p = v:getPosition(); BNGE_WX.p0 = { x = p.x, y = p.y }
v:applyClusterVelocityScaleAdd(v:getRefNodeId(), 0, d.x * 3, d.y * 3, 0)
return 1""")
            lua(f"""local d = BNGE_WX.dir; local s = {wind}
-- wind blowing toward the car's right: velocity vector = s * right
core_environment.setGroundWind(d.y * s, -d.x * s, 0) return 1""")
            time.sleep(8)
            drift[str(wind)] = json.loads(lua("""local v = getPlayerVehicle(0); local p = v:getPosition(); local d = BNGE_WX.dir
local dx, dy = p.x - BNGE_WX.p0.x, p.y - BNGE_WX.p0.y
return jsonEncode({ forward = dx * d.x + dy * d.y, right = dx * d.y - dy * d.x, speed = v:getVelocity():length() })"""))
            lua("core_environment.setGroundWind(0, 0, 0) return 1")
            print("wind", wind, drift[str(wind)], flush=True)
            time.sleep(2)
        res["wind"] = drift
    finally:
        print(lua("local p = scenetree.findObject('bngEarthRainProbe'); if p then p:delete() end "
                  "core_environment.setGroundWind(0, 0, 0) return 1"), flush=True)
        set_clouds(saved["cov"], saved["cirrusDensity"], saved["cirrus"])
        print(lua(RESTORE), flush=True)
        lua("commands.setGameCamera() return 1")
    json.dump(res, open(os.path.join(a.out, "results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
