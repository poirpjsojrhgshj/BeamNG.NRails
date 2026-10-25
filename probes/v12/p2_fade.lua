if not scenetree.findObject('bngEarthProbeFade1Mat') then
  local m = createObject('Material')
  m:setField('mapTo', 0, 'bngEarthProbeFade1')
  m:setField('diffuseColor', 0, '1 0 0 1')
  m:setField('instanceOpacity', 0, '1')
  m.translucent = true
  m.canSave = false
  m:registerObject('bngEarthProbeFade1Mat')
end
local old = scenetree.findObject('bngEarthProbeFade1Obj'); if old then old:delete() end
local o = createObject('TSStatic')
o:setField('shapeName', 0, '/temp/beamngEarth/probe/fade1.dae')
o:setField('collisionType', 0, 'None'); o.useInstanceRenderData = true; o.dynamic = true; o.canSave = false
local p = getPlayerVehicle(0):getPosition()
o:setPosition(vec3(p.x - 128, p.y + 20, p.z + 4))
o:registerObject('bngEarthProbeFade1Obj'); scenetree.MissionGroup:addObject(o)
function BNGE_A(a) local t = scenetree.findObject('bngEarthProbeFade1Obj')
  t:setField('instanceColor', 0, string.format('1 1 1 %.3f', a)); t:updateInstanceRenderData() end
BNGE_A(0.3)
local q = quatFromDir(vec3(0, 1, -0.25):normalized(), vec3(0,0,1))
return jsonEncode({pos = tostring(o:getPosition())})
