import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe_view_distance as P
import numpy as np
from PIL import Image
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'docs', 'research', 'view_distance', os.environ.get('TAG', 'each')) + '/'
os.makedirs(OUT, exist_ok=True)
shape = "/temp/beamngEarth_probe/marker.cdae"
FOG = float(os.environ.get("FOG", "-1"))
VIS_LIST = tuple(int(v) for v in os.environ.get("VIS", "100,20000").split(","))
saved = json.loads(P.lua("return jsonEncode({ vis = scenetree.theLevelInfo.visibleDistance, fog = scenetree.theLevelInfo.fogDensity, fov = core_camera.getFovDeg and core_camera.getFovDeg() or -1 })"))
if FOG >= 0:
    P.lua(f"scenetree.theLevelInfo.fogDensity = {FOG} return 1")
print('saved', saved, flush=True)
res = []
try:
    P.lua("""local v = getPlayerVehicle(0); local p = v and v:getPosition() or vec3(0, 0, 0)
BNGE_VD = { x = p.x, y = p.y, z = 10000, ids = {} }
commands.setFreeCamera()
core_camera.setPosition(0, vec3(BNGE_VD.x, BNGE_VD.y, BNGE_VD.z))
core_camera.setRotation(0, quatFromDir(vec3(0, 1, -0.02):normalized(), vec3(0, 0, 1)))
return 1""")
    # one marker: a 4x tile (131 km) centred at distance D, top 300 m below the eye line at D
    P.lua(f"""local o = createObject('TSStatic')
o:setField('shapeName', 0, '{shape}'); o:setField('collisionType', 0, 'None'); o.canSave = false
o:setScale(vec3(4, 4, 1)); o:registerObject('bngeVD_one'); scenetree.MissionGroup:addObject(o)
o:setHidden(true); table.insert(BNGE_VD.ids, o:getID()); return 1""")
    for vis in VIS_LIST:
        P.lua(f"local li = scenetree.theLevelInfo; li.visibleDistance = {vis * 1000}; "
              f"if li.postApply then li:postApply() end; if li.inspectPostApply then li:inspectPostApply() end; return 1")
        time.sleep(1.5)
        ref = P.shot(os.path.join(OUT, f'ref_vis{vis}.png'))
        R = np.asarray(Image.open(ref).convert('L'), np.float32)
        for km in (50, 100, 200, 400, 800, 1600, 3200, 6400):
            d = km * 1000
            # z so the tile centre sits ~0.5 deg below the camera's pitch line -> on screen
            z = 10000 - d * 0.02 - d * 0.009
            P.lua(f"""local o = scenetree.findObject('bngeVD_one')
o:setPosition(vec3(BNGE_VD.x - 65536, BNGE_VD.y + {d} - 65536, {z})); o:setHidden(false); return 1""")
            time.sleep(1.2)
            p = P.shot(os.path.join(OUT, f'vis{vis}_m{km}.png'))
            A = np.asarray(Image.open(p).convert('L'), np.float32)
            diff = float(np.abs(A - R)[200:2000, 700:3100].mean())
            px = int((np.abs(A - R)[200:2000, 700:3100] > 20).sum())
            print(f"vis {vis} km  marker {km} km: diff {diff:.2f}, changed px {px}", flush=True)
            res.append({'vis': vis, 'km': km, 'diff': diff, 'px': px})
            P.lua("scenetree.findObject('bngeVD_one'):setHidden(true) return 1")
finally:
    print(P.lua(f"""for _, id in ipairs((BNGE_VD or {{}}).ids or {{}}) do local o = scenetree.findObjectById(id); if o then o:delete() end end
BNGE_VD = nil; scenetree.theLevelInfo.visibleDistance = {saved['vis']}; if scenetree.theLevelInfo.postApply then scenetree.theLevelInfo:postApply() end; scenetree.theLevelInfo.fogDensity = {saved['fog']}; commands.setGameCamera(); return 'restored'"""), flush=True)
json.dump({'saved': saved, 'res': res}, open(os.path.join(OUT, 'results.json'), 'w'), indent=1)
