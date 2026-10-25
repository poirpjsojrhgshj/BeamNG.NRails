"""Drive the player car across the probe tiles and sample its pose."""
import json, subprocess, time
def mcp(*a): return subprocess.run(['python3', 'tools/mcp.py', *a], capture_output=True, text=True).stdout.strip()
mcp('call', 'set_position', json.dumps({"pos": {"x": 150, "y": -936, "z": 1.0}, "rot": {"x": 0, "y": 0, "z": 0.7071, "w": 0.7071}}))
time.sleep(1.5)
mcp('call', 'set_camera', json.dumps({"mode": "chase"}))
mcp('call', 'inject_input', json.dumps({"event": "parkingbrake", "value": 0}))
mcp('call', 'inject_input', json.dumps({"event": "throttle", "value": 1}))
for i in range(16):
    time.sleep(0.5)
    v = json.loads(mcp('call', 'get_vehicle'))
    gnd = mcp('lua', 'local v=getPlayerVehicle(0); local p=v:getPosition(); return string.format("%.2f", castRayStatic(p+vec3(0,0,2), vec3(0,0,-1), 10)-2)')
    p = v.get('pos') or v.get('position')
    print(f"t={i*0.5+0.5:4.1f}s pos=({p['x']:7.1f},{p['y']:7.1f},{p['z']:5.2f}) speed={v.get('speed',0):5.1f} groundBelowRef={gnd}")
mcp('call', 'inject_input', json.dumps({"event": "throttle", "value": 0}))
mcp('call', 'inject_input', json.dumps({"event": "brake", "value": 1}))
print(mcp('call', 'get_instability'))
