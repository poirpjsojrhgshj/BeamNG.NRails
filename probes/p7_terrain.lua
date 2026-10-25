-- PROBE_STEP: create|ray|edit|reload|move|import|delete ; PROBE_N for create/import
local s = require('socket')
local r = {step = PROBE_STEP}
local name = 'bngEarthTerrain'
local tb = scenetree.findObject(name)
local function t() return s.gettime() end
if PROBE_STEP == 'create' then
  if tb then tb:delete() end
  local t0 = t()
  tb = TerrainBlock()
  tb:setName(name)
  tb:registerObject(name)
  tb:setTerrFileLvlFolder('/temp/beamngEarth/')
  scenetree.MissionGroup:addObject(tb)
  local ok, e = pcall(function()
    return tb:importMaps('/temp/beamngEarth/probe_hm'..PROBE_N..'_v1.png', 1.0, 100.0, '', {}, {}, false)
  end)
  r.importOk = ok; r.importErr = tostring(e)
  tb:setPosition(vec3(-2000, -2000, 0))
  r.create_ms = (t()-t0)*1000
  r.blockSize = tb:getWorldBlockSize()
elseif PROBE_STEP == 'ray' then
  local p = vec3(-2000 + 100.5, -2000 + 100.5, 200)
  r.hitZ = 200 - castRayStatic(p, vec3(0,0,-1), 400)
  r.expectedZ = 20 + 5*math.sin(100.5*0.05) + 5*math.cos(100.5*0.03)
  r.heightApi = tb and tb:getHeight(vec3(p.x, p.y, 0)) or -1
elseif PROBE_STEP == 'edit' then
  local t0 = t()
  for x = 90, 110 do for y = 90, 110 do tb:setHeight(x, y, 60) end end
  local t1 = t()
  tb:updateGrid(vec3(90, 90), vec3(110, 110))
  r.setHeight441_ms = (t1-t0)*1000
  r.updateGrid_ms = (t()-t1)*1000
elseif PROBE_STEP == 'reload' then
  local t0 = t(); be:reloadCollision(); r.reload_ms = (t()-t0)*1000
elseif PROBE_STEP == 'move' then
  local t0 = t(); tb:setPosition(tb:getPosition() + vec3(0, 0, 10)); r.move_ms = (t()-t0)*1000
elseif PROBE_STEP == 'delete' then
  if tb then tb:delete() end
end
return jsonEncode(r)
