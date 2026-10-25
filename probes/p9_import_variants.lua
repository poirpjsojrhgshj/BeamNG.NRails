local s = require('socket')
local tb = scenetree.findObject('beamngEarthTerrain') or scenetree.findClassObjects('TerrainBlock') and scenetree.findObject(scenetree.findClassObjects('TerrainBlock')[1])
local hm = '/temp/beamngEarth/20261009-224628-3147/hm_11.png'
local LAYER = '/levels/beamng_earth/art/terrains/beamngEarth_layer_2048.png'
local pos = tb:getPosition()
MAXH = tb:getHeightScaleUser()
be:setPhysicsRunning(false)
local out = {name = tb:getName()}
local function run(label, mats, tex)
  local t0 = s.gettime()
  local ok = tb:importMaps(hm, 2.0, MAXH, '', mats, tex, false)
  local t1 = s.gettime()
  tb:setPosition(pos)
  be:reloadCollision()
  out[label] = string.format('import %.0f ms, +reload %.0f ms, ok=%s', (t1-t0)*1000, (s.gettime()-t1)*1000, tostring(ok))
end
run('A_full', {'beamngEarthDirt'}, {{path=LAYER, selected=false, material='beamngEarthDirt', materialId=0, channel='R', channelId=0}})
run('B_matsNoTex', {'beamngEarthDirt'}, {})
run('C_none', {}, {})
run('D_full_again', {'beamngEarthDirt'}, {{path=LAYER, selected=false, material='beamngEarthDirt', materialId=0, channel='R', channelId=0}})
be:setPhysicsRunning(true)
out.maxH = MAXH
return jsonEncode(out)
