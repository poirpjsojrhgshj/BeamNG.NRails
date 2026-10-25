"""Fixed camera; step the car until a terrain-follow commit happens; screenshot before/after."""
import json, subprocess, time, shutil, os, sys
OUT = 'docs/research/v13_investigation'
def mcp(*a): return subprocess.run(['python3', 'tools/mcp.py', *a], capture_output=True, text=True).stdout.strip()
def status(): return json.loads(mcp('lua', 'return jsonEncode(loadstring("return "..beamngEarth_core.status())())'))
def shot(name):
    p = mcp('call', 'screenshot').splitlines()[-1]
    for _ in range(40):
        if os.path.exists(p) and os.path.getsize(p) > 0: break
        time.sleep(0.1)
    time.sleep(0.3)
    if os.path.exists(p): shutil.copy(p, f'{OUT}/{name}.png'); return f'{OUT}/{name}.png'
    return 'missing ' + p
def ground(x, y): return float(mcp('lua', f'return string.format("%.2f", 9000-castRayStatic(vec3({x},{y},9000), vec3(0,0,-1), 20000))'))
st = status(); p = st['player']; b = st['block']
print('start', round(p['x']), round(p['y']), 'block', b)
x0, y0 = p['x'], p['y']
z0 = ground(x0, y0)
# camera: 40 m above ground, 60 m behind (west of) the car, looking east and slightly down
cx, cy, cz = x0 - 60, y0, z0 + 40
mcp('lua', f'commands.setFreeCamera(); core_camera.setPosition(0, vec3({cx},{cy},{cz})); core_camera.setRotation(0, quatFromDir(vec3(1,0,-0.35):normalized(), vec3(0,0,1))); return 1')
time.sleep(2); print('A', shot('A2_before'))
x = x0
for step in range(12):
    x += 150
    g = ground(x, y0)
    mcp('call', 'set_position', json.dumps({"pos": {"x": x, "y": y0, "z": g + 1.5}}))
    mcp('lua', f'core_camera.setPosition(0, vec3({cx},{cy},{cz})); return 1')
    time.sleep(2.0)
    st = status()
    if st['block'] != b:
        print('commit after step', step, 'block', st['block'])
        mcp('lua', f'core_camera.setPosition(0, vec3({cx},{cy},{cz})); return 1')
        print('B', shot('B2_after_commit')); time.sleep(3); print('C', shot('C2_after_3s'))
        break
