"""Move the player east in steps (placed on ground) and log terrain-follow / rebase behaviour."""
import json, subprocess, time, sys
def mcp(*a): return subprocess.run(['python3', 'tools/mcp.py', *a], capture_output=True, text=True).stdout.strip()
step = float(sys.argv[1]) if len(sys.argv) > 1 else 400
n = int(sys.argv[2]) if len(sys.argv) > 2 else 8
print(mcp('lua', 'return tostring(beamngEarth_core.setRebaseDistance(2000))'))
for i in range(n):
    st = json.loads(mcp('lua', 'return jsonEncode(loadstring("return "..beamngEarth_core.status())())'))
    p = st['player']
    x, y = p['x'] + step, p['y']
    gz = mcp('lua', f'local r=castRayStatic(vec3({x},{y},9000), vec3(0,0,-1), 20000); return string.format("%.2f", 9000-r)')
    mcp('call', 'set_position', json.dumps({"pos": {"x": x, "y": y, "z": float(gz) + 1.0}}))
    time.sleep(2.5)
    st = json.loads(mcp('lua', 'return jsonEncode(loadstring("return "..beamngEarth_core.status())())'))
    p, f = st['player'], st['far']
    print(f"step {i}: anchor={st['anchorId']} block=({st['block']['cx']},{st['block']['cy']}) player=({p['x']:.0f},{p['y']:.0f},{p['z']:.0f}) lon={p['lon']:.5f} far live={f['live']} q={f['queued']} old={f['old']} | {st.get('status')}", flush=True)
print(mcp('lua', 'return tostring(beamngEarth_core.setRebaseDistance(10000))'))
