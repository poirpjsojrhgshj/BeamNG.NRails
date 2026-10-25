-- luajit mod/tests/test_farcars.lua  (far player cars saved, taken out and put back, farcars.lua): a car far from the
-- active one for UNLOAD_AFTER_S is saved and deleted once its state file is there; a stored car near again is a
-- collision focus, comes back only with the ground under it and gets its state loaded; traffic and other BeamMP
-- players' cars are never touched; a switch to a far car saves the driven one, teleports and enters the stored car.
local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local S = dofile(dir .. '/stubs.lua')
local fc = require('beamngEarth/farcars')
local qmt = { __mul = function(a, b)       -- (the stub quat with a product)
  return quat(a.w * b.x + a.x * b.w + a.y * b.z - a.z * b.y, a.w * b.y - a.x * b.z + a.y * b.w + a.z * b.x,
    a.w * b.z + a.x * b.y - a.y * b.x + a.z * b.w, a.w * b.w - a.x * b.x - a.y * b.y - a.z * b.z)
end }
local rawQuat = quat
function quat(...) return setmetatable(rawQuat(...), qmt) end

-- a flat anchor: lat / lon are metres east / north (offset by the anchor's own place, as after a rebase)
local anchor = { ox = 0, oy = 0 }
function anchor:enuToGeodetic(e, n, u) return n + self.oy, e + self.ox, u end
function anchor:geodeticToEnu(lat, lon, h) return lon - self.ox, lat - self.oy, h end
local teleported
beamngEarth_core = {
  _state = function() return { anchor = anchor } end,
  teleport = function(lat, lon) teleported = { lat, lon } end,
}

local files, vehicles, order = {}, {}, {}
FS = { fileExists = function(_, p) return files[p] ~= nil end, removeFile = function(_, p) files[p] = nil end }
local function newCar(x, y, model)
  local o = S.newObject('BeamNGVehicle')
  o.JBeam, o.partConfig, o.color = model or 'pickup', 'vehicles/pickup/x.pc', '1 0 0 1'
  o.pos = vec3(x, y, 10)
  o.commands = {}
  function o:getId() return self.id end
  function o:getRefNodeRotation() return quat(0, 0, 0, 1) end
  function o:getMetallicPaintData() return {} end
  function o:queueLuaCommand(c) self.commands[#self.commands + 1] = c end
  local del = o.delete
  function o:delete() vehicles[self.id] = nil; del(self) end
  S.objects[o.id], vehicles[o.id] = o, o
  order[#order + 1] = o.id
  return o
end
be = { getObjectCount = function() local n = 0; for _, id in ipairs(order) do if vehicles[id] then n = n + 1 end end; return n end }
function be:getObject(i)
  local k = -1
  for _, id in ipairs(order) do
    if vehicles[id] then k = k + 1; if k == i then return vehicles[id] end end
  end
end
local entered
function be:enterVehicle(_, v) entered = v end
local player
function getPlayerVehicle() return player end
local ground = {}       -- "x,y" (rounded to 100 m) -> true: the static ground there
function castRayStatic(p) return ground[math.floor(p.x / 100 + 0.5) .. ',' .. math.floor(p.y / 100 + 0.5)] and 6 or 12 end
local spawned = {}
core_vehicles = { spawnNewVehicle = function(model, opt)
  local v = newCar(opt.pos.x, opt.pos.y, model)
  spawned[#spawned + 1] = { v = v, opt = opt }
  return v
end }
-- the vehicle Lua's beamstate.save writes its file at once
local function writeSaves()
  for _, v in pairs(vehicles) do
    for _, c in ipairs(v.commands) do
      local p = c:match('^beamstate%.save%("(.-)"%)')
      if p then files[p] = true end
    end
    v.commands = {}
  end
end
local function tick(s) fc.update(s or fc.UPDATE_S) end

-- the pure parts
T.check(fc.shouldUnload(fc.UNLOAD_M + 1, fc.UNLOAD_AFTER_S) and not fc.shouldUnload(fc.UNLOAD_M + 1, 1)
  and not fc.shouldUnload(fc.UNLOAD_M - 1, 100), 'unload: far, for long enough')
local w = fc.within({ a = { x = 0 }, b = { x = 500 }, c = { x = 3000 } }, 0, 0, 1000, function(r) return r.x, 0 end)
T.check(#w == 2 and w[1] == 'a' and w[2] == 'b', 'within: the near ones, sorted')

-- a far player car is saved, then deleted once its file is there; traffic and others' cars stay
player = newCar(0, 0)
local far = newCar(4000, 0)
local mpOther = newCar(5000, 0)
MPVehicleGE = { isOwn = function(id) return id ~= mpOther.id end }
tick()
T.check(next(fc.state().saving) == nil, 'not at once')
for _ = 1, 12 do tick() end
local sv = fc.state().saving[far.id]
T.check(sv ~= nil, 'saving after UNLOAD_AFTER_S')
T.check(fc.state().saving[mpOther.id] == nil, 'another BeamMP player\'s car: left alone')
T.check(far.commands[1] and far.commands[1]:find('beamstate.save', 1, true), 'the game\'s state save asked')
tick()
T.check(vehicles[far.id] ~= nil, 'kept until the file is written')
writeSaves()
tick()
T.check(vehicles[far.id] == nil, 'deleted once saved')
local list = fc.list()
T.check(#list == 1 and list[1].model == 'pickup' and list[1].lat == 0 and list[1].lon == 4000, 'stored with its place')
-- watching another player's car (the vehicle switch): our far cars stay
local me = player
local far2 = newCar(-4000, 0)
player = mpOther
for _ = 1, 14 do tick() end
T.check(fc.state().saving[far2.id] == nil and vehicles[far2.id] ~= nil, 'watching another player\'s car: ours stay')
player = me
far2:delete()
mpOther:delete()
MPVehicleGE = nil

-- near again: a focus first; back only with the ground under it; its state loaded
anchor.ox = 3000            -- (a rebase on the way: the stored place follows the anchor)
player.pos = vec3(-400, 0, 10)
local foci = fc.foci()
T.check(#foci == 1 and foci[1].x == 1000 and foci[1].r > 0 and foci[1].trees, 'near: a collision focus at its place')
tick()
T.check(#spawned == 0, 'no ground under it yet: not back')
ground['10,0'] = true
tick()
T.check(#spawned == 1 and spawned[1].opt.pos.x == 1000 and spawned[1].opt.config == 'vehicles/pickup/x.pc',
  'the ground there: spawned at its place with its parts')
T.check(#fc.list() == 0, 'no longer stored')
local back = spawned[1].v
tick(fc.LOAD_DELAY_S)
T.check(back.commands[1] and back.commands[1]:find('beamstate.load', 1, true), 'its state loaded')

-- a switch to a far car: the driven car saved first, then the teleport, then the stored car entered, the old one out
back.pos = vec3(1000 + fc.UNLOAD_M + 500, 0, 10)
for _ = 1, 12 do tick() end
writeSaves()
tick()
local uid = fc.list()[1].uid
T.check(uid ~= nil, 'the other car stored again')
T.check(fc.switchTo(uid) == true, 'switch under way')
T.check(fc.state().saving[player.id] and fc.state().saving[player.id].keep, 'the driven car saved first (kept)')
writeSaves()
tick()
T.check(vehicles[player.id] ~= nil and teleported ~= nil, 'saved: not deleted, the teleport asked')
T.check(#fc.list() == 2, 'the driven car is a stored car too')
-- the teleport arrives
player.pos = vec3(1000 + fc.UNLOAD_M + 500 - 50, 0, 10)
ground['40,0'] = true
tick()
T.check(#spawned == 2 and spawned[2].opt.autoEnterVehicle == true, 'the switch\'s car back, entered')
T.check(vehicles[player.id] == nil, 'the old car out first (it is stored where it was)')
entered = spawned[2].v
tick(fc.LOAD_DELAY_S)
T.check(#fc.list() == 1 and fc.list()[1].lon == 3000 - 400, 'the old car\'s record at its old place')
T.check(fc.state().switch == nil, 'the switch done')

-- a teleport: the other cars stay where they are (saved, out), the active car's trailer comes along
fc.reset()
for id in pairs(vehicles) do if id ~= entered.id then vehicles[id]:delete() end end
player = entered
anchor.ox = 0
player.pos = vec3(0, 0, 10)
local parkedHere = newCar(20, 0)
local trailer = newCar(-8, 0)
core_trailerRespawn = { getVehicleTrainHead = function(id) return id == trailer.id and player.id or id end }
local coreState = { anchor = anchor, pending = { purpose = 'teleport' } }
beamngEarth_core._state = function() return coreState end
fc.onTeleport()
T.check(fc.state().saving[parkedHere.id] ~= nil, 'teleport: the other car saved')
T.check(fc.state().saving[trailer.id] == nil, 'teleport: the trailer comes along')
writeSaves()
ground['0,0'] = true
tick()
T.check(vehicles[parkedHere.id] == nil and #fc.list() == 1 and fc.list()[1].lon == 20, 'left behind at its place')
T.check(#spawned == 2, 'not back while the teleport is under way (the player still there)')
coreState.pending = nil
core_trailerRespawn = nil

fc.reset()
T.check(#fc.list() == 0 and next(files) == nil, 'reset: forgotten, the state files deleted')
T.done('test_farcars')
