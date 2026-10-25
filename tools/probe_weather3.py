#!/usr/bin/env python3
"""Weather probe, third pass, on flat open ground (Central Valley): ground wind on a coasting test car,
cloud overcast search (layer height/thickness, baseColor alpha, weather seeds) and rain visibility.
The user's vehicle is teleported here, frozen during the test car runs, and teleported back.

  python3 tools/probe_weather3.py --out docs/research/weather_probe3
"""
import argparse
import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from probe_weather import lua, shot, perf, cloud_fraction, SETUP, RESTORE   # noqa: E402
from probe_weather2 import cam, set_clouds                                  # noqa: E402

SITE = (35.40, -119.20)


def wait_loaded(timeout=180):
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = lua('local s = loadstring("return " .. beamngEarth_core.status())() '
                'return string.format("%s %d", tostring(s.far.done), s.far.queued)')
        if r.startswith("true") and int(r.split()[1]) < 5:
            return True
        time.sleep(3)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    res = {}
    home = json.loads(lua('local s = loadstring("return " .. beamngEarth_core.status())() '
                          'return jsonEncode({ lat = s.player.lat, lon = s.player.lon })'))
    saved = json.loads(lua("""local o = scenetree.findObject('bngEarthClouds')
return jsonEncode({ cov = o.coverage, cirrus = o.cirrusCoverage, cirrusDensity = o.cirrusDensity, height = o.height,
  baseColor = o:getField('baseColor', 0) })"""))
    print("home", home, "saved", saved, flush=True)
    lua("if not beamngEarth_perfmon then extensions.load('beamngEarth_perfmon') end return 1")
    try:
        lua(f"commands.setGameCamera(); return beamngEarth_core.teleport({SITE[0]}, {SITE[1]})")
        print("loaded", wait_loaded(), flush=True)
        time.sleep(5)

        # 1 wind on flat ground: coast at 5 m/s for 8 s, wind 0 / 25 m/s from the left
        print("test car", lua(SETUP), flush=True)
        time.sleep(5)
        drift = {}
        for wind in (0, 25, 0, 25):
            lua("""local v = getPlayerVehicle(0)
v:queueLuaCommand('input.event(\"parkingbrake\", 0, 1); input.event(\"brake\", 0, 1); input.event(\"throttle\", 0, 1)')
local d = v:getDirectionVector(); BNGE_WX.dir = { x = d.x, y = d.y }
local p = v:getPosition(); BNGE_WX.p0 = { x = p.x, y = p.y, z = p.z }
v:applyClusterVelocityScaleAdd(v:getRefNodeId(), 0, d.x * 5, d.y * 5, 0)
return 1""")
            lua(f"local d = BNGE_WX.dir; core_environment.setGroundWind(d.y * {wind}, -d.x * {wind}, 0) return 1")
            time.sleep(8)
            r = json.loads(lua("""local v = getPlayerVehicle(0); local p = v:getPosition(); local d = BNGE_WX.dir
local dx, dy = p.x - BNGE_WX.p0.x, p.y - BNGE_WX.p0.y
return jsonEncode({ forward = dx * d.x + dy * d.y, right = dx * d.y - dy * d.x, dz = p.z - BNGE_WX.p0.z,
  speed = v:getVelocity():length() })"""))
            lua("core_environment.setGroundWind(0, 0, 0) return 1")
            drift.setdefault(str(wind), []).append(r)
            print("wind", wind, r, flush=True)
            time.sleep(2)
        res["wind"] = drift
        print(lua(RESTORE), flush=True)
        time.sleep(3)

        # 2 overcast search, camera 25 deg up to the north
        cam(0, 25)
        trials = [("cov0", 0.0, None, None, None)]
        for h in (4, 8, 12):
            for alpha in (0.9, 1.0):
                trials.append((f"cov0.95_h{h}_a{alpha}", 0.95, h, alpha, None))
        for seed in (1, 77, 4242):
            trials.append((f"cov0.95_h8_seed{seed}", 0.95, 8, 1.0, seed))
        refshot = None
        out = {}
        for name, cov, h, alpha, seed in trials:
            code = f"local o = scenetree.findObject('bngEarthClouds'); o.coverage = {cov}; "
            if h is not None:
                code += f"o.height = {h}; "
            if alpha is not None:
                code += f"o:setField('baseColor', 0, '0.99 0.99 0.99 {alpha}'); "
            code += "o:postApply(); "
            if seed is not None:
                code += f"if CloudLayer and CloudLayer.regenerateWeatherMap then pcall(CloudLayer.regenerateWeatherMap, {seed}) end "
            lua(code + "return 1")
            time.sleep(4)
            p = shot(os.path.join(a.out, f"{name}.png"))
            if refshot is None:
                refshot = p
            out[name] = cloud_fraction(p, refshot)
            print("clouds", name, out[name], flush=True)
        res["overcast"] = out

        # 3 rain visibility: Precipitation at full percentage, camera at the car looking level
        lua(f"local o = scenetree.findObject('bngEarthClouds'); o.coverage = {saved['cov']}; o.height = {saved['height']}; "
            f"o:setField('baseColor', 0, '{saved['baseColor']}'); o:postApply() return 1")
        cam(0, 0, 1.6)
        lua("""local p = createObject('Precipitation'); p:setField('dataBlock', 0, 'rain_medium'); p:setField('followCam', 0, '1')
p:setField('boxWidth', 0, '40'); p:setField('boxHeight', 0, '30'); p.canSave = false; p:registerObject('bngEarthRainProbe')
scenetree.MissionGroup:addObject(p); p.numDrops = 9000; p:postApply()
local r = {}
for _, m in ipairs({ 'setPercentage', 'modifyStorm' }) do r[#r + 1] = m .. '=' .. tostring(p[m] ~= nil) end
pcall(function() p:setPercentage(1) end)
pcall(function() p:modifyStorm(1, 0) end)
BNGE_WX_RAIN = table.concat(r, ' ')
return 1""")
        time.sleep(3)
        shot(os.path.join(a.out, "rain_full.png"))
        res["rainMethods"] = lua("return BNGE_WX_RAIN or ''")
        res["rainFields"] = lua("""local p = scenetree.findObject('bngEarthRainProbe'); local out = {}
for k, _ in pairs(p:getFields() or {}) do local ok, v = pcall(function() return p:getField(k, 0) end); out[#out + 1] = k .. '=' .. tostring(v) end
table.sort(out); return table.concat(out, ' | ')""")
        print("rain", res["rainMethods"], flush=True)
    finally:
        lua("local p = scenetree.findObject('bngEarthRainProbe'); if p then p:delete() end core_environment.setGroundWind(0, 0, 0) return 1")
        lua(f"local o = scenetree.findObject('bngEarthClouds'); if o then o.coverage = {saved['cov']}; o.height = {saved['height']}; "
            f"o:setField('baseColor', 0, '{saved['baseColor']}'); o:postApply() end return 1")
        print(lua(RESTORE), flush=True)
        print(lua(f"commands.setGameCamera(); return beamngEarth_core.teleport({home['lat']}, {home['lon']})"), flush=True)
        wait_loaded(120)
    json.dump(res, open(os.path.join(a.out, "results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
