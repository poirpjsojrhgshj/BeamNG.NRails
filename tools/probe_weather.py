#!/usr/bin/env python3
"""In-game checks for the real-weather plan (docs/research/2026-10-10-real-weather.md section 6).

Runs only while the user is not playing. The user's vehicle is frozen (setActive(0)) and restored;
wind is tested on a spawned stock test car; every changed setting is put back.

  1 core_environment's CloudLayer cache before/after onEditorDeactivated()
  2 cloud coverage -> sky fraction, camera straight up (coverage 0 as the clear reference)
  4 ground wind push on a parked test car (neutral, no brakes)
  5 temperature: default curve, does a set value stick, temperature/pressure seen by the vehicle
  6 precipitation: create rain, frame cost at 3000 / 9000 drops
  7 cloud cost: frame ms at coverage 0 / 0.5 / 0.9

  python3 tools/probe_weather.py --out docs/research/weather_probe
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


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
    return {k: round(p.get(k) or 0, 2) for k in ("fps", "p50", "p95")}


def cloud_fraction(path, ref):
    """Share of sky pixels that are cloud: brighter and less blue than the clear reference."""
    import numpy as np
    from PIL import Image
    a = np.asarray(Image.open(path).convert("RGB"), np.float32)
    r = np.asarray(Image.open(ref).convert("RGB"), np.float32)
    h, w, _ = a.shape
    sl = (slice(int(h * 0.2), int(h * 0.8)), slice(int(w * 0.2), int(w * 0.8)))   # no UI
    a, r = a[sl], r[sl]
    sat = lambda x: (x.max(-1) - x.min(-1)) / np.maximum(x.max(-1), 1)
    cloud = (sat(a) < sat(r) - 0.12) | (a.mean(-1) > r.mean(-1) + 25)
    return round(float(cloud.mean()), 3)


SETUP = r"""
local car = getPlayerVehicle(0)
local p, d = car:getPosition(), car:getDirectionVector()
local t = core_vehicles.spawnNewVehicle('vivace', { pos = vec3(p.x + 6, p.y, p.z + 2),
  rot = quatFromDir(vec3(d.x, d.y, 0):normalized(), vec3(0, 0, 1)), autoEnterVehicle = true })
BNGE_WX = { carId = car:getID(), testId = t:getID() }
car:setActive(0)
return jsonEncode(BNGE_WX)"""

RESTORE = r"""
local st = BNGE_WX
if not st then return 'nothing' end
local t = getObjectByID(st.testId); if t then t:delete() end
local car = getObjectByID(st.carId); if car then car:setActive(1); be:enterVehicle(0, car) end
commands.setGameCamera()
BNGE_WX = nil
return 'restored'"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    res = {}
    saved = json.loads(lua("""local o = scenetree.findObject('bngEarthClouds')
local li = scenetree.theLevelInfo
return jsonEncode({ cov = o and o.coverage, cirrus = o and o.cirrusCoverage,
  fog = li.fogDensity, fogH = li.fogAtmosphereHeight })"""))
    print("saved", saved, flush=True)
    lua("if not beamngEarth_perfmon then extensions.load('beamngEarth_perfmon') end return 1")
    try:
        # 1 cache
        res["cache"] = lua("""local a = tostring(core_environment.getCloudCover())
core_environment.onEditorDeactivated()
return a .. ' -> ' .. tostring(core_environment.getCloudCover())""")
        print("1 cache:", res["cache"], flush=True)

        # 2 + 7 coverage calibration and cost: camera straight up from the player
        lua("""local v = getPlayerVehicle(0); local p = v:getPosition()
commands.setFreeCamera(); core_camera.setPosition(0, vec3(p.x, p.y, p.z + 3))
core_camera.setRotation(0, quatFromDir(vec3(0.001, 0.2, 1):normalized(), vec3(0, 1, 0))); return 1""")
        cov = {}
        for c in (0.0, 0.29, 0.40, 0.53, 0.67, 0.79, 0.9):
            lua(f"local o = scenetree.findObject('bngEarthClouds'); o.coverage = {c}; o.cirrusCoverage = 0; o:postApply() return 1")
            time.sleep(4)
            path = shot(os.path.join(a.out, f"cov_{c:.2f}.png"))
            cov[c] = {"shot": path}
            if c in (0.0, 0.53, 0.9):
                cov[c]["perf"] = perf()
        ref = cov[0.0]["shot"]
        for c, d in cov.items():
            d["skyFraction"] = cloud_fraction(d["shot"], ref)
            print(f"2 coverage {c:.2f}: sky fraction {d['skyFraction']}  {d.get('perf', '')}", flush=True)
        res["coverage"] = {str(k): v for k, v in cov.items()}
        lua(f"local o = scenetree.findObject('bngEarthClouds'); o.coverage = {saved['cov']}; o.cirrusCoverage = {saved['cirrus']}; o:postApply() return 1")

        # 5 temperature
        res["temperature"] = lua("""local li = scenetree.theLevelInfo
local curve = li.getTemperatureCurveC and li:getTemperatureCurveC() or 'n/a'
local before = be.getSeaLevelTemperatureK and be:getSeaLevelTemperatureK() or 'n/a'
if be.setSeaLevelTemperatureK then be:setSeaLevelTemperatureK(273.15 + 21) end
local after = be.getSeaLevelTemperatureK and be:getSeaLevelTemperatureK() or 'n/a'
return jsonEncode({ curve = tostring(curve), before = before, after = after })""")
        print("5 temperature:", res["temperature"], flush=True)

        # 4 wind on a test car, and the vehicle's view of temperature/pressure
        print("test car", lua(SETUP), flush=True)
        time.sleep(4)
        lua("""local v = getPlayerVehicle(0)
v:queueLuaCommand('controller.mainController.setGearboxMode(\"neutral\"); input.event(\"parkingbrake\", 0, 1); input.event(\"brake\", 0, 1); input.event(\"throttle\", 0, 1)')
return 1""")
        time.sleep(2)
        lua("""getPlayerVehicle(0):queueLuaCommand('obj:queueGameEngineLua(\"BNGE_WX.env = \" .. serialize({ t = obj:getEnvTemperature() - 273.15, p = obj:getEnvPressure() }))') return 1""")
        time.sleep(1)
        res["vehicleEnv"] = lua("return BNGE_WX and BNGE_WX.env and jsonEncode(BNGE_WX.env) or 'n/a'")
        print("5 vehicle env:", res["vehicleEnv"], flush=True)
        v0 = lua("local v = getPlayerVehicle(0):getVelocity() return string.format('%.3f %.3f %.3f', v.x, v.y, v.z)")
        lua("core_environment.setGroundWind(-20, 0, 0) return 1")
        time.sleep(6)
        v1 = lua("local v = getPlayerVehicle(0):getVelocity() return string.format('%.3f %.3f %.3f', v.x, v.y, v.z)")
        lua("core_environment.setGroundWind(0, 0, 0) return 1")
        res["wind"] = {"before": v0, "after6s_20ms_toward_-x": v1}
        print("4 wind:", res["wind"], flush=True)

        # 6 precipitation cost
        lua("""local p = createObject('Precipitation'); p:setField('dataBlock', 0, 'rain_medium'); p:setField('followCam', 0, '1')
p:setField('boxWidth', 0, '40'); p:setField('boxHeight', 0, '30'); p.canSave = false; p:registerObject('bngEarthRainProbe')
scenetree.MissionGroup:addObject(p); p.numDrops = 0; p:postApply(); return 1""")
        lua("commands.setGameCamera() return 1")
        base = perf()
        rain = {"0": base}
        for n in (3000, 9000):
            lua(f"local p = scenetree.findObject('bngEarthRainProbe'); p.numDrops = {n}; p:postApply(); if p.setPercentage then p:setPercentage(1) end return 1")
            time.sleep(2)
            rain[str(n)] = perf()
            shot(os.path.join(a.out, f"rain_{n}.png"))
        res["rain"] = rain
        print("6 rain:", rain, flush=True)
    finally:
        print(lua("local p = scenetree.findObject('bngEarthRainProbe'); if p then p:delete() end "
                  "core_environment.setGroundWind(0, 0, 0) return 1"), flush=True)
        print(lua(f"""local o = scenetree.findObject('bngEarthClouds'); if o then o.coverage = {saved['cov']}; o.cirrusCoverage = {saved['cirrus']}; o:postApply() end
local li = scenetree.theLevelInfo; li.fogDensity = {saved['fog']}; li.fogAtmosphereHeight = {saved['fogH']}; li:postApply()
return 1"""), flush=True)
        print(lua(RESTORE), flush=True)
    json.dump(res, open(os.path.join(a.out, "results.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
