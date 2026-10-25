local t = hptimer()
local v = getPlayerVehicle(0):getPosition()
local out = {}
local fmts = {'jpg','png','dds','jpg','png','dds'}
for k = 0, 5 do
  local name = 'bngEarthSatProbe' .. k
  local old = scenetree.findObject('bngSatProbeObj' .. k); if old then old:delete() end
  t:stopAndReset()
  local m = scenetree.findObject(name .. 'Mat')
  if not m then
    m = createObject('Material')
    m:setField('mapTo', 0, name)
    m:setField('colorMap', 0, '/temp/beamngEarth/satprobe/sat_' .. k .. '.' .. fmts[k+1])
    m.canSave = false
    m:registerObject(name .. 'Mat')
  end
  local matMs = t:stopAndReset()
  local o = createObject('TSStatic')
  o:setField('shapeName', 0, '/temp/beamngEarth/satprobe/sat_' .. k .. '.cdae')
  o:setField('collisionType', 0, 'None'); o.canSave = false
  o:setPosition(vec3(v.x - 600 + k * 260, v.y + 300, v.z + 60))
  o:registerObject('bngSatProbeObj' .. k); scenetree.MissionGroup:addObject(o)
  local objMs = t:stopAndReset()
  out[#out+1] = string.format('%s: material %.2f ms, tile %.2f ms', fmts[k+1], matMs, objMs)
end
BNGE_SAT_CAM = {v.x - 300, v.y - 250, v.z + 400}
return table.concat(out, ' | ')
