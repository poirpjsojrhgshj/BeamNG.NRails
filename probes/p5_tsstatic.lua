-- PROBE_SHAPE, PROBE_NAME, PROBE_POS {x,y,z}, PROBE_COLL ('None'|'Visible Mesh'|'Collision Mesh')
local s = require('socket')
local r = {}
local old = scenetree.findObject(PROBE_NAME); if old then old:delete() end
local t0 = s.gettime()
local o = createObject('TSStatic')
o:setField('shapeName', 0, PROBE_SHAPE)
o:setField('collisionType', 0, PROBE_COLL)
o:setField('decalType', 0, PROBE_COLL)
o.canSave = false
o:setPosition(vec3(PROBE_POS[1], PROBE_POS[2], PROBE_POS[3]))
o:registerObject(PROBE_NAME)
scenetree.MissionGroup:add(o)
r.spawn_ms = (s.gettime()-t0)*1000
local b = o:getWorldBox()
r.box = {b.minExtents.x, b.minExtents.y, b.minExtents.z, b.maxExtents.x, b.maxExtents.y, b.maxExtents.z}
local t1 = s.gettime(); be:reloadCollision(); r.reload_ms = (s.gettime()-t1)*1000
r.rayDown = castRayStatic(vec3(PROBE_POS[1]+10.3, PROBE_POS[2]+10.7, 50), vec3(0,0,-1), 100)
return jsonEncode(r)
