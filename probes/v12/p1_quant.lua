local tb = scenetree.findObject('bngEarthTerrain')
be:setPhysicsRunning(false)
local H = 65535/64
local L = '/levels/beamng_earth/art/terrains/beamngEarth_layer_1024.png'
local ok = tb:importMaps('/temp/beamngEarth/probe/q_x.png', 2.0, H, '', {'beamngEarthDirt'},
  {{path=L, selected=false, material='beamngEarthDirt', materialId=0, channel='R', channelId=0}}, false)
local x0, y0, z0 = 4096, 4096, 100
tb:setPosition(vec3(x0, y0, z0)); be:reloadCollision()
local r = {ok=ok, sq=tb:getSquareSize(), hsu=tb:getHeightScaleUser(), s={}}
for _, gx in ipairs({0,1,2,511,512,1000,1020,1021,1022,1023}) do
  local h = tb:getHeight(vec3(x0 + 2*gx, y0 + 1000, 0))
  r.s[#r.s+1] = {gx=gx, q=math.min(gx*64,65535), dz=h and (h - z0) or 'nil', ratio = h and gx > 0 and (h - z0)/(gx*64) or 0}
end
r.mid = tb:getHeight(vec3(x0 + 1023, y0 + 1000, 0)) - z0
for _, dx in ipairs({2039.9, 2041, 2043, 2045, 2047}) do
  local d = castRayStatic(vec3(x0+dx, y0+1000, z0+3000), vec3(0,0,-1), 4000)
  r['phys_'..dx] = d < 4000 and (z0 + 3000 - d - z0) or 'miss'
end
return jsonEncode(r)
