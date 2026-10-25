-- luajit mod/tests/test_nrails.lua  (BeamNG.EarthNRails, nrails.lua: the railway meshes of the road tiles through
-- roads.lua's NRails hooks, the level crossings' slabs, the rail vehicles list, snap to rail)
local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local S = dofile(dir .. '/stubs.lua')

local files = {}
readFile = function(p) return files[p] end
jsonDecode = function(s) return assert(load('return ' .. s))() end   -- the test writes Lua table text

local roads = require('beamngEarth/roads')
local nrails = require('beamngEarth/nrails').init({})

local gov = { tries = 0 }
function gov:try() self.tries = self.tries + 1; return self.allow == nil or self.tries <= self.allow end
function gov:charge() end
function gov:chargeMotion() end

local function statics()
  local r = {}
  for _, o in pairs(S.objects) do if o.class == 'TSStatic' then r[#r + 1] = o end end
  return r
end
roads.RELOAD_EVERY_S = 0

-- the hooks: the kinds registered once, the materials file added once, roads.ext set
do
  local n = 0
  for _, w in ipairs(roads.EXT_KINDS) do if w == 'railcol' then n = n + 1 end end
  nrails.init({})
  local m = 0
  for _, f in ipairs(roads.MATERIAL_FILES) do if f == nrails.MATERIAL_FILE then m = m + 1 end end
  local n2 = 0
  for _, w in ipairs(roads.EXT_KINDS) do if w == 'railcol' then n2 = n2 + 1 end end
  T.check(n == 1 and n2 == 1 and m == 1, 'init twice: kinds and materials registered once')
  T.check(roads.ext and roads.ext.onTile and roads.ext.update and roads.ext.lean('railcol2')
    and not roads.ext.lean('rail'), 'roads.ext hooks set')
end

-- the track is drawn only, its rails collide through a collision detail, a rail tunnel's tube collides, and a level
-- crossing's inner slab is solid only while no rail vehicle is near (the wheelsets' flange discs fill the gauge)
do
  gov.allow, gov.tries = nil, 0
  nrails.RAILX_CHECK_S = 0
  local function at(shape) return string.format('{ shape = "/t/%s", pos = { 768, 768, 0 } }', shape) end
  files['/t/r.json'] = '{ chunks = {}, rail = ' .. at('rail_2_3_3.cdae') .. ', rail2 = ' .. at('rail_2_3_3_2.cdae')
    .. ', railcol = ' .. at('railcol_2_3_3.cdae') .. ', railx = ' .. at('railx_2_3_3.cdae')
    .. ', railtun = ' .. at('railtun_2_3_3.cdae') .. ', railx_pts = { { 900, 900, 10 } } }'
  roads.onTile({ anchorId = 2, key = '3_3', path = '/t/r.json', n = 0 }, 2)
  for _ = 1, 3 do roads.update(gov, 2) end
  local function byShape()
    local by, n = {}, 0
    for _, o in ipairs(statics()) do
      if o.fields.shapeName:find('/t/rail') then by[o.fields.shapeName] = o; n = n + 1 end
    end
    return by, n
  end
  local by, n = byShape()
  T.check(n == 5, 'rail tile: five meshes made')
  T.check(by['/t/rail_2_3_3.cdae'] and by['/t/rail_2_3_3.cdae'].fields.collisionType == 'None', 'track drawn only')
  T.check(by['/t/rail_2_3_3_2.cdae'] and by['/t/rail_2_3_3_2.cdae'].fields.collisionType == 'None', 'its second part too')
  T.check(by['/t/railcol_2_3_3.cdae'] and by['/t/railcol_2_3_3.cdae'].fields.collisionType == 'Collision Mesh',
    'rails collide through the collision detail')
  T.check(by['/t/railtun_2_3_3.cdae'] and by['/t/railtun_2_3_3.cdae'].fields.collisionType == 'Visible Mesh Final',
    'a rail tunnel drawn and colliding')
  T.check(by['/t/railx_2_3_3.cdae'] and by['/t/railx_2_3_3.cdae'].fields.collisionType == 'Visible Mesh Final',
    'crossing slab solid with no train near')
  local train = { getJBeamFilename = function() return 'tem2' end, getPosition = function() return vec3(950, 900, 10) end }
  be.getObjectCount = function() return 1 end
  be.getObject = function() return train end
  for _ = 1, 3 do roads.update(gov, 2) end
  by, n = byShape()
  T.check(n == 5 and by['/t/railx_2_3_3.cdae'] and by['/t/railx_2_3_3.cdae'].fields.collisionType == 'None',
    'a TEM2 within RAILX_CLEAR_M: the slab made again, render-only')
  train.getPosition = function() return vec3(5000, 900, 10) end
  for _ = 1, 3 do roads.update(gov, 2) end
  by, n = byShape()
  T.check(n == 5 and by['/t/railx_2_3_3.cdae'].fields.collisionType == 'Visible Mesh Final', 'train gone: solid again')
  local car = { getJBeamFilename = function() return 'etk800' end, getPosition = function() return vec3(900, 900, 10) end }
  be.getObject = function() return car end
  for _ = 1, 3 do roads.update(gov, 2) end
  by = byShape()
  T.check(by['/t/railx_2_3_3.cdae'].fields.collisionType == 'Visible Mesh Final', 'a car on the crossing: stays solid')
  roads.onDrop({ anchorId = 2, key = '3_3' })
  for _ = 1, 3 do roads.update(gov, 2) end
  local _, left = byShape()
  T.check(left == 0, 'dropped: every rail mesh deleted')
  be.getObjectCount, be.getObject = nil, nil
end

-- more rail vehicles from the settings file (the Hub writes it)
do
  local before = nrails.isRailVehicle('hirail_dseries')
  local n = nrails.loadVehicleList(function() return '{ vehicles = { "hirail_dseries", "tem2", "" } }' end)
  T.check(not before and n == 1 and nrails.isRailVehicle('hirail_dseries'), 'vehicle list: new names added once')
  T.check(nrails.loadVehicleList(function() return nil end) == 0, 'no file: nothing')
  T.check(nrails.loadVehicleList(function() return 'nonsense(' end) == 0, 'a broken file: nothing')
end

-- snap to rail: the nearest point of the tiles' track centre lines, the pose on it
do
  gov.allow, gov.tries = nil, 0
  -- two tracks: one east-west at y = 900 rising 1 m over 100 m, one north-south at x = 1000 on a bridge (z 20)
  files['/t/s.json'] = '{ chunks = {}, rail_lines = { { 900, 900, 10, 950, 900, 10.5, 1000, 900, 11 },'
    .. ' { 1000, 850, 20, 1000, 950, 20 } } }'
  roads.onTile({ anchorId = 2, key = '3_3', path = '/t/s.json', n = 0 }, 2)
  local r = nrails.nearestRail(930, 903, 10.3)
  T.check(r and math.abs(r.x - 930) < 1e-6 and math.abs(r.y - 900) < 1e-6, 'snap: the foot on the nearest track')
  T.check(r and math.abs(r.z - 10.3) < 1e-6 and math.abs(r.dist - 3) < 1e-3, 'snap: its rail top interpolated')
  T.check(r and r.dx > 0.99 and math.abs(r.dz - 0.01) < 1e-3, 'snap: the tangent along the track')
  local b = nrails.nearestRail(998, 905, 20)
  T.check(b and b.z == 20 and b.x == 1000, 'snap: a car on the bridge goes onto the bridge track')
  local u = nrails.nearestRail(998, 905, 11)
  T.check(u and u.y == 900, 'snap: one under it onto the lower one')
  T.check(nrails.nearestRail(930, 1000, 10) == nil, 'snap: nothing beyond SNAP_MAX_M')
  local x, y, z, dx = nrails.railSnapPose(r, -1, 0.1, 1.2, true)
  T.check(x == 930 and dx < 0 and math.abs(z - (10.3 + 1.2 - nrails.SNAP_FLANGE_M)) < 1e-9,
    'snap pose: a train facing west turned west, its flanges under the rail top')
  local _, _, z2, dx2 = nrails.railSnapPose(r, 1, 0, 0.5, false)
  T.check(dx2 > 0 and math.abs(z2 - (10.3 + 0.5 + nrails.SNAP_LIFT_M)) < 1e-9, 'snap pose: a car just over the rails')
  T.check(nrails.isRailVehicle('tem2') and not nrails.isRailVehicle('etk800'), 'rail vehicles by jbeam name')
  roads.onDrop({ anchorId = 2, key = '3_3' })
  for _ = 1, 3 do roads.update(gov, 2) end
  T.check(nrails.nearestRail(930, 903, 10) == nil, 'snap: a dropped tile has no track any more')
end

-- trains away from the player keep their rails solid: a rail vehicle's collision island is RAIL_FOCUS_R, even when AI
-- traffic spawned it, without solid trees; other cars keep upstream's foci
do
  local cf = require('beamngEarth/collisionfoci')
  T.check(cf._nrails == true, 'collisionfoci wrapped at init')
  local fake = {
    vehicles = function()
      return { { id = 1, x = 0, y = 0, kind = 'player' }, { id = 2, x = 1000, y = 0, kind = 'traffic' },
               { id = 3, x = 2000, y = 0, kind = 'traffic' }, { id = 4, x = 3000, y = 0, kind = 'parked' } }
    end,
  }
  local names = { [1] = 'etk800', [2] = 'tem2', [3] = 'pickup', [4] = 'tank' }
  -- upstream's compute on a fresh copy of the module (the wrapped one is already the real one's)
  package.loaded['beamngEarth/collisionfoci'] = nil
  local up = require('beamngEarth/collisionfoci')
  fake.compute = up.compute
  nrails.wrapFoci(fake, function(id) return names[id] end)
  local vs = fake.vehicles()
  T.check(vs[2].kind == 'player' and vs[2].rail and vs[3].kind == 'traffic' and vs[4].kind == 'parked',
    'a train from traffic counts as a player\'s; a parked one stays parked')
  local foci = fake.compute(vs, 1, 0, 0)
  local byId = {}
  for _, f in ipairs(foci) do byId[f.id] = f end
  T.check(byId[2] and byId[2].r == nrails.RAIL_FOCUS_R and byId[2].trees == false, 'a train: RAIL_FOCUS_R, no trees')
  T.check(byId[3] and byId[3].r == up.TRAFFIC_R and not byId[4], 'a traffic car and a parked train as upstream')
  T.check(nrails.wrapFoci(fake) == fake, 'wrapped once')
  package.loaded['beamngEarth/collisionfoci'] = cf
end

-- the order the meshes are made in: the colliders, the track drawn, the buildings' collision, the rest
do
  local k = 50
  T.check(nrails.priority({ what = 'railcol' }, k) == k, 'a rail collider as a road collider')
  T.check(nrails.priority({ what = 'rail2', renderOnly = true }, k + 1e6) == k + 1e5, 'the track drawn before the rest')
  T.check(nrails.priority({ what = 'bldcol' }, k) == k + 2e5, "the buildings' collision after the roads' and rails'")
  T.check(nrails.priority({ what = 'bld', renderOnly = true }, k + 1e6) == k + 1e6, 'the facades as upstream')
end

-- the load guard: held when the path ahead is not loaded, let go once it is
do
  local lg = nrails.loadguard
  local s = { holding = false }
  local loaded = function(x, y) return x < 50 end           -- nothing loaded east of x = 50 (3 s at 30 m/s: 90 m)
  T.check(lg.step(s, 0, { x = 0, y = 0, vx = 1, vy = 0 }, false, loaded) == nil, 'slow: never held')
  T.check(lg.step(s, 0, { x = 0, y = 0, vx = 30, vy = 0 }, false, loaded) == 'hold', 'fast toward the unloaded: held')
  s.holding, s.since = true, 0
  T.check(lg.step(s, 1, { x = 0, y = 0, vx = 0, vy = 0 }, false, loaded) == nil, 'held while the path is not in')
  T.check(lg.step(s, 2, { x = 0, y = 0, vx = 0, vy = 0 }, false, function() return true end) == 'release',
    'let go once it is')
  local s2 = { holding = false }
  T.check(lg.step(s2, 0, { x = 0, y = 0, vx = 30, vy = 0 }, true, loaded) == nil, 'never over another hold or load')
  local s3 = { holding = true, since = 0, speed = 30, dx = 1, dy = 0 }
  T.check(lg.step(s3, lg.MAX_S + 1, { x = 0, y = 0, vx = 0, vy = 0 }, false, loaded) == 'release', 'at most MAX_S')
  local s4 = { holding = false }       -- a vehicle being placed (Snap to rail): the jump's velocity, no hold
  T.check(lg.step(s4, 0, { x = 0, y = 0, vx = 862000, vy = 0 }, false, loaded) == nil, 'a placement jump: not held')
  local s5 = { holding = false }       -- very fast: the path measured at MAX_SPEED at most
  T.check(lg.step(s5, 0, { x = 0, y = 0, vx = 150, vy = 0 }, false, loaded) == 'hold' and s5.speed == lg.MAX_SPEED
    and math.abs(s5.dx - 1) < 1e-9, 'fast: measured at MAX_SPEED, its direction kept')
end

-- under the sea in a tunnel: the sea's physics block goes under the player (out of the water); in the open sea not
do
  T.check(require('beamngEarth/sea').ext and require('beamngEarth/sea').ext.physZ == nrails.physZ, 'sea hook set')
  local saved = rawget(_G, 'castRayStatic')
  local vec = rawget(_G, 'vec3')
  if not vec then _G.vec3 = function(x, y, z) return { x = x, y = y, z = z } end end
  _G.castRayStatic = function() return 8 end              -- the vault 8 m over the player
  local z = nrails.physZ({ x = 0, y = 0, z = -60 }, 0)
  T.check(z < -60 - 20, 'in a tunnel under the sea: the water under the player (' .. tostring(z) .. ')')
  T.check(nrails.physZ({ x = 0, y = 0, z = -1 }, 0) == 0, 'at the surface: the sea')
  _G.castRayStatic = function(_, _, len) return len end   -- nothing over it: in the sea
  T.check(nrails.physZ({ x = 0, y = 0, z = -60 }, 0) == 0, 'under open water: the sea')
  -- the tube drawn only, the terrain hit from above only: up nothing, down from over the sea the sea floor at -40
  _G.castRayStatic = function(o, dir, len)
    if dir.z > 0 then return len end
    local d = o.z - (-40)
    return d < len and d or len
  end
  T.check(nrails.physZ({ x = 0, y = 0, z = -60 }, 0) < -60, 'under the sea floor (found from above): dry')
  T.check(nrails.physZ({ x = 0, y = 0, z = -30 }, 0) == 0, 'over the sea floor (in the water): the sea')
  _G.castRayStatic = saved
  if not vec then _G.vec3 = nil end
end

-- our key (settings/inputmaps/keyboard_nrails.json) is free: not the game's (BEAMNG_DIR) nor upstream's
do
  local function read(p) local f = io.open(p, 'rb'); if not f then return nil end; local s = f:read('*a'); f:close(); return s end
  local function controls(s)
    local out = {}
    for c in (s or ''):gmatch('"control"%s*:%s*"([^"]+)"') do out[c] = true end
    return out
  end
  local ours = controls(read(dir .. '/../beamng_earth/settings/inputmaps/keyboard_nrails.json'))
  T.check(next(ours) ~= nil, 'our key map read')
  local others = { dir .. '/../beamng_earth/settings/inputmaps/keyboard_beamngEarth.json' }
  local game = os.getenv('BEAMNG_DIR')
  if game then
    others[#others + 1] = game .. '/settings/inputmaps/keyboard.json'
    others[#others + 1] = game .. '/settings/inputmaps/keyboard_editor.json'
  end
  for _, p in ipairs(others) do
    local theirs = controls(read(p))
    for c in pairs(ours) do T.check(not theirs[c], 'key ' .. c .. ' free in ' .. p) end
  end
end

-- Turnouts (nrailsswitch.lua): the choice used on the next one ahead, a trailing run sets the route it comes from
do
  local sw = require('beamngEarth/nrailsswitch')
  sw.state, sw.pending = {}, nil
  -- a turnout at the origin, its routes leaving along +x: route 1 to the left (+y), route 2 straight (default)
  local t = { id = 'a', at = { 0, 0 }, dir = { 1, 0 }, def = 1, routes = {
    { what = 'railsw1', side = 0.08, line = { 0, 0, 20, 1, 40, 3.2 } },
    { what = 'railsw2', side = 0.0, line = { 0, 0, 20, 0, 40, 0 } } } }
  T.check(sw.current(t) == 2, 'turnout: the straight route at first')
  local ch, used = sw.step({ t }, { x = -100, y = 0, vx = 20, vy = 0 })
  T.check(next(ch) == nil and not used, 'turnout: nothing without a choice')
  sw.pending = 'left'
  ch, used = sw.step({ t }, { x = -100, y = 0, vx = 20, vy = 0 })
  T.check(ch.a == 1 and used, 'turnout: the choice goes to the next one ahead')
  sw.pending = 'left'
  ch, used = sw.step({ t }, { x = -100, y = 0, vx = -20, vy = 0 })
  T.check(next(ch) == nil and not used, 'turnout: not one behind the train')
  sw.pending = nil
  sw.state.a = 2
  ch = sw.step({ t }, { x = 38, y = 3.0, vx = -15, vy = -1 })
  T.check(ch.a == 1, 'turnout: coming back on the left route sets it')
  ch = sw.step({ t }, { x = 38, y = 0.1, vx = -15, vy = 0 })
  T.check(next(ch) == nil, 'turnout: coming back on the set route: no change')
  T.check(sw.pick(t, 'right') == 2 and sw.pick(t, 'straight') == 2 and sw.pick(t, 'left') == 1, 'turnout: picks')
  local _, list = sw.collect({ k1 = { railsw = { t } }, k2 = { railsw = { t } }, k3 = { railsw = { t }, ghost = true } })
  T.check(#list == 1, 'turnout: each once over the tiles')
  sw.state, sw.pending = {}, nil
end

-- Reload area: core.reconnect called, not more often than RELOAD_MIN_S; the loading line names the rails
do
  local n = 0
  local core = { reconnect = function() n = n + 1 end }
  T.check(nrails.reloadArea(core, 100) == true and n == 1, 'reload: reconnect asked')
  T.check(nrails.reloadArea(core, 101) == false and n == 1, 'reload: not again within RELOAD_MIN_S')
  T.check(nrails.reloadArea(core, 100 + nrails.RELOAD_MIN_S + 1) == true and n == 2, 'reload: again later')
  T.check(nrails.reloadArea({}, 1000) == false, 'reload: no core, no error')
  local lp = { PARTS = { { 'ground', 'ground' }, { 'roads', 'roads & buildings' } } }
  nrails.labelLoading(lp)
  T.check(lp.PARTS[2][2] == 'roads, rails & buildings', 'loading line: rails named')
  T.check(lp.PARTS[1][2] == 'ground', 'loading line: the rest as it was')
end

T.done('test_nrails')
