import json, subprocess, time, sys
def mcp(*a): return subprocess.run(['python3', 'tools/mcp.py', *a], capture_output=True, text=True).stdout.strip()
for label, pos in [("floor", {"x": 0, "y": 0, "z": 1.0}), ("terrain", {"x": -1900, "y": -1900, "z": 21.0})]:
    mcp('call', 'set_position', json.dumps({"pos": pos, "rot": {"x": 0, "y": 0, "z": 0, "w": 1}}))
    zs = []
    for i in range(6):
        time.sleep(0.5)
        zs.append(round(json.loads(mcp('call', 'get_vehicle'))['position']['z'], 2))
    print(label, zs)
