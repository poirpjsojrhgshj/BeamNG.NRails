"""Does terrain collision follow setHeight+updateGrid WITHOUT be:reloadCollision()?"""
import json, subprocess, time
def mcp(*a): return subprocess.run(['python3', 'tools/mcp.py', *a], capture_output=True, text=True).stdout.strip()
# block is at (-2000,-2000), 2 m squares. Edit gx,gy 140..160 => world x,y in [-1720,-1680]; raise to 60 m.
print(mcp('lua', 'local tb=scenetree.findObject("bngEarthTerrain"); local s=require("socket"); local t0=s.gettime(); for x=140,160 do for y=140,160 do tb:setHeight(x,y,60) end end; tb:updateGrid(vec3(140,140),vec3(160,160)); return string.format("edited in %.2f ms; getHeight=%.2f", (s.gettime()-t0)*1000, tb:getHeight(vec3(-1700,-1700,0)))'))
t0 = time.time()
for i in range(8):
    r = mcp('lua', 'return string.format("%.2f", 200-castRayStatic(vec3(-1700.5,-1700.5,200), vec3(0,0,-1), 400))')
    print(f"t={time.time()-t0:4.1f}s GE castRayStatic z={r}", flush=True)
    time.sleep(0.5)
# drop the car onto the raised plateau (top at z=60); if physics hasn't updated, it sinks to old ~20 m
mcp('call', 'set_position', json.dumps({"pos": {"x": -1700, "y": -1700, "z": 63}, "rot": {"x": 0, "y": 0, "z": 0, "w": 1}}))
zs = []
for i in range(6):
    time.sleep(0.5); zs.append(round(json.loads(mcp('call', 'get_vehicle'))['position']['z'], 2))
print("car z on plateau (expect ~60.3 if physics updated):", zs)
