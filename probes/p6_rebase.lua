-- Floating-origin rebase: shift every tile and the player vehicle by D in one GE frame.
local s = require('socket')
local D = vec3(REBASE_DX or 0, REBASE_DY or 3000, 0)
local veh = getPlayerVehicle(0)
local r = {}
local t0 = s.gettime()
r.velBefore = veh:getVelocity():length()
local n = 0
for _, name in ipairs(scenetree.findClassObjects('ProceduralMesh')) do
  if name:find('^bngEarthTile_') then
    local o = scenetree.findObject(name)
    o:setPosition(o:getPosition() + D); n = n + 1
  end
end
local t1 = s.gettime()
be:reloadCollision()
local t2 = s.gettime()
local p = veh:getPosition() + D
veh:setClusterPosRelRot(-1, p.x, p.y, p.z, 0, 0, 0, 1)
r.tilesMoved = n
r.moveTiles_ms = (t1-t0)*1000
r.reload_ms = (t2-t1)*1000
r.total_ms = (s.gettime()-t0)*1000
return jsonEncode(r)
