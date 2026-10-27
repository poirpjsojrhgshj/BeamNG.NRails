-- BeamNG.NRails: the railway in the road tiles (server/nrails). Everything the fork adds to the mod lives here;
-- upstream's files only carry short hooks marked "NRails hook" (roads.lua: M.EXT_KINDS / M.ext / M.extQueue /
-- M.extRemake; core.lua: require + init; ui.lua: the "Snap to rail" button).
--
-- A road tile's railway meshes: "nrail".."nrail4" drawn only, "nrailcol".."nrailcol4" a collision detail (the rails' and
-- the ballast's boxes, never drawn), "nrailtun" the rail tunnels' tubes and portals (drawn and colliding), "nrailx" the
-- level crossings' inner slabs: drawn always, solid only while no rail vehicle is within RAILX_CLEAR_M of one of the
-- tile's crossings (the rail mods' wheelsets carry a 1.37 m "flange disc" that fills the space between the rails: a
-- slab there would stop the train).
local M = {}

local roads = require('beamngEarth/roads')
local stopwatch = require('beamngEarth/stopwatch')

-- (the collision in parts of ~5k triangles at most, up to 12: the engine's static collision rebuild took 5-22 s per
-- rebuild with a 20k-triangle railcol or a 62k-triangle terrain patch in, 2026-10-24)
-- ('nrail': BeamNG.Earth 1.6.3 has a 'rail' kind of its own, colliding, made by roads.lua itself)
M.KINDS = { 'nrail', 'nrail2', 'nrail3', 'nrail4', 'nrailx', 'nrailtun' }
for k = 1, 12 do M.KINDS[#M.KINDS + 1] = k == 1 and 'nrailcol' or ('nrailcol' .. k) end
-- the turnouts' routes' rails in their switch zones (nrailsswitch.lua): collision only, solid for the set route
M.SW_MAX = 160          -- (48 in 1.1: a big station's zones past it were always solid, the user's run 2026-10-27)
for k = 1, M.SW_MAX do M.KINDS[#M.KINDS + 1] = 'nrailsw' .. k end
-- the contacts (server rails.CONTACT_M): a track's rails where another track comes within reach of a bogie, outside
-- the turnouts' zones; collision only, non-solid while a rail vehicle runs on another track there and none on this one
M.CT_MAX = 64
for k = 1, M.CT_MAX do M.KINDS[#M.KINDS + 1] = 'nrailct' .. k end
local switch = require('beamngEarth/nrailsswitch')
M.switch = switch
M.MATERIAL_FILE = '/levels/beamng_earth/art/shapes/beamngEarth/rails.materials.json'
-- the rail vehicles by jbeam name (the rail mods: TEM2, FS30-2 "6axle_train", the tank wagon, DMM512 "train"); more
-- in the user's settings file (M.loadVehicleList: settings/beamngEarth/nrails_vehicles.json, the Hub writes it)
M.RAIL_VEHICLES = { tem2 = true, ['6axle_train'] = true, tank = true, train = true }
M.VEHICLES_FILE = '/settings/beamngEarth/nrails_vehicles.json'
M.RAILX_CLEAR_M = 150
M.RAILX_CHECK_S = 0.5

local function isSw(what) return what:sub(1, 7) == 'nrailsw' end
local function isCt(what) return what:sub(1, 7) == 'nrailct' end
local function isCol(what) return what:sub(1, 8) == 'nrailcol' or isSw(what) or isCt(what) end
local function isDrawnOnly(what) return what:sub(1, 5) == 'nrail' and not isCol(what) and what ~= 'nrailx'
  and what ~= 'nrailtun' end
M._isCol, M._isDrawnOnly = isCol, isDrawnOnly

local setStatus = function() end

-- The rail vehicles' jbeam names from the settings file ({"vehicles": ["name", ...]}), added to the built-in ones.
function M.loadVehicleList(read)
  read = read or function(p) return readFile and readFile(p) end
  local ok, text = pcall(read, M.VEHICLES_FILE)
  if not ok or type(text) ~= 'string' or text == '' then return 0 end
  local ok2, data = pcall(jsonDecode, text)
  if not ok2 or type(data) ~= 'table' or type(data.vehicles) ~= 'table' then return 0 end
  local n = 0
  for _, name in ipairs(data.vehicles) do
    if type(name) == 'string' and name ~= '' and not M.RAIL_VEHICLES[name] then M.RAIL_VEHICLES[name] = true; n = n + 1 end
  end
  return n
end

-- Is the jbeam name a rail vehicle's (M.RAIL_VEHICLES)?
function M.isRailVehicle(jbeam) return jbeam ~= nil and M.RAIL_VEHICLES[jbeam] == true end

-- roads.ext.onTile: a road tile's railway meshes queued (render-only, colliding, the crossings' slabs)
local function onTile(key, t, data)
  if type(data.rail_lines) == 'table' and data.rail_lines[1] then t.railLines = data.rail_lines end   -- (snapToRail)
  t.railsig = (type(data.railsig) == 'table' and data.railsig[1]) and data.railsig or nil         -- (the signals)
  t.railxBars = (type(data.railx_bars) == 'table' and data.railx_bars[1]) and data.railx_bars or nil  -- (barriers)
  if t.railxBars and M.xing then M.xing._resetList() end
  if type(data.railx_pts) == 'table' and data.railx_pts[1] then
    t.railxPts = data.railx_pts
    t.railxSolid = not M.railVehicleNear(t.railxPts)
  end
  -- the turnouts: which route of which turnout each "nrailswN" shape is
  -- (t.swNeed: each "nrailswN" shape's need {{turnout id, route}, ...}; an older server's data: one route each)
  t.swNeed, t.swWalk, t.swSolid = {}, {}, {}
  t.ctLines, t.ctCore, t.ctWalk, t.ctSolid = {}, {}, {}, {}
  if type(data.railc) == 'table' then
    for _, c in ipairs(data.railc) do
      if c.what and type(c.lines) == 'table' then
        t.ctLines[c.what] = c.lines
        t.ctCore[c.what] = type(c.core) == 'table' and c.core or c.lines
      end
    end
  end
  if type(data.railsw) == 'table' and data.railsw[1] then
    t.railsw = data.railsw
    if type(data.railsw_shapes) == 'table' and data.railsw_shapes[1] then
      for _, s in ipairs(data.railsw_shapes) do
        if s.what then t.swNeed[s.what] = s.need or {} end
      end
    else
      for _, sw in ipairs(data.railsw) do
        for i, r in ipairs(sw.routes or {}) do
          if r.what then t.swNeed[r.what] = { { sw.id, i } } end
        end
      end
    end
  end
  local byId = t.railsw and switch.collect({ t }) or {}
  for _, what in ipairs(M.KINDS) do
    local w = data[what]
    if type(w) == 'table' and w.shape and type(w.pos) == 'table' then
      if what == 'nrailx' then t.railxWalk = w end
      local off = false
      if isCt(what) then
        t.ctWalk[what] = w
        local ok, o = pcall(M.contactOff, t.ctCore[what], M.activeWays and M.activeWays.ways, M.activeWays and M.activeWays.cars)
        off = ok and o == true
        t.ctSolid[what] = not off
      end
      if isSw(what) then
        t.swWalk[what] = w
        local need = t.swNeed[what]
        off = need ~= nil and not switch.needMet(need, byId)   -- (not the set routes: not solid)
        t.swSolid[what] = not off
      end
      roads.extQueue(key, t, what, w, isDrawnOnly(what) or off or (what == 'nrailx' and t.railxSolid == false))
    end
  end
end

-- A turnout set to route idx: its routes' shapes in every tile made again, the set one solid.
function M.setSwitch(id, idx)
  switch.state[id] = idx
  local byId = switch.collect(roads.extTiles())
  for key, t in pairs(roads.extTiles()) do
    if t.swNeed and not t.ghost then
      for what, need in pairs(t.swNeed) do
        local mine = false
        for _, n in ipairs(need) do if n[1] == id then mine = true end end
        if mine and t.swWalk[what] then
          local solid = switch.needMet(need, byId)
          if solid ~= t.swSolid[what] then
            t.swSolid[what] = solid
            roads.extRemake(key, t, what, t.swWalk[what], not solid)
          end
        end
      end
    end
  end
end

-- The player's choice for the next turnout ahead ('left' | 'straight' | 'right'; the keys).
local CHOICE_TEXT = { left = 'a gauche / left', straight = 'tout droit / straight', right = 'a droite / right' }
function M.setNext(choice)
  switch.pending = choice
  setStatus('NRails: prochain aiguillage ' .. (CHOICE_TEXT[choice] or tostring(choice)))
end

-- Every SW_CHECK_S: the player's vehicle against the turnouts near it (nrailsswitch.step).
M.SW_CHECK_S = 0.25
local sinceSw = stopwatch.new()
function M.updateSwitches()
  if sinceSw() < M.SW_CHECK_S * 1000 then return end
  sinceSw = stopwatch.new()
  local byId, list = switch.collect(roads.extTiles())
  M._swById, M._swList = byId, list                -- (the diagram and the signals)
  if not list[1] then M._nextFacing = nil; return end
  local cars = M.scene()                           -- every rail vehicle (a train sets the turnouts it runs through)
  if not cars[1] then return end
  local changes, used, nextFacing = switch.step(list, cars)
  M._nextFacing = nextFacing
  for id, idx in pairs(changes) do M.setSwitch(id, idx) end
  if used then
    switch.pending = nil
    setStatus('NRails: aiguillage regle / turnout set')
  end
  -- the next turnout ahead of the player, once per turnout: its distance and the route it is set to
  local nf = nextFacing and nextFacing.sw
  if nf and nf.id ~= M._lastFacing then
    M._lastFacing = nf.id
    local cur, n = switch.current(nf), #(nf.routes or {})
    local word = (cur == (nf.def or 0) + 1) and 'ligne principale / main line'
      or (cur == 1 and 'a gauche / left') or (cur == n and 'a droite / right') or 'tout droit / straight'
    setStatus(string.format('NRails: aiguillage dans %d m : %s (Ctrl+Shift+fleches)', math.floor(nextFacing.dist), word))
  elseif not nf then
    M._lastFacing = nil
  end
end

-- A rail vehicle's probe points along it (the user's run, 2026-10-27: a long locomotive's rear bogie still on the
-- blades when its centre had left the turnout's zone: the turnout set under it, the rear bogie on the other route):
-- its centre, both bogies (BOGIE_IN_M in from its ends) and both ends, {{x, y}, ...}. Pure.
M.BOGIE_IN_M = 3.0
function M.probes(x, y, fx, fy, hl)
  local l = math.sqrt(fx * fx + fy * fy)
  if l < 1e-6 or not hl then return { { x, y } } end
  fx, fy = fx / l, fy / l
  local b = math.max(0, hl - M.BOGIE_IN_M)
  return { { x, y }, { x + fx * b, y + fy * b }, { x - fx * b, y - fy * b }, { x + fx * hl, y + fy * hl },
    { x - fx * hl, y - fy * hl } }
end

-- A vehicle's half length (m, its spawn box), kept per vehicle id.
M._hl = {}
function M.halfLength(v, id)
  if id and M._hl[id] then return M._hl[id] end
  local ok, hl = pcall(function()
    local e = v:getSpawnWorldOOBB():getHalfExtents()
    return math.max(e.x, e.y, e.z)
  end)
  hl = (ok and type(hl) == 'number' and hl > 0.5 and hl < 60) and hl or 8
  if id then M._hl[id] = hl end
  return hl
end

-- The rail vehicles and the player in the scene, scanned once every SCENE_S for the turnouts and the level crossings
-- alike (one pass over the objects, not one per user: the CPU cost of the mod each frame kept low):
-- { x, y, z, vx, vy, speed, player, rail } rows.
M.SCENE_S = 0.2
local sceneRows, sceneAt = {}, -1
local function jbeamOf(v) return v:getJBeamFilename() end
local function posOf(v) return v:getPosition() end
local function velOf(v) return v:getVelocity() end
local function idOf(v) return v:getID() end
local function dirOf(v) return v:getDirectionVector() end
function M.scene(now)
  now = now or os.clock()
  if now - sceneAt < M.SCENE_S and now >= sceneAt then return sceneRows end
  sceneAt = now
  local out = {}
  local player = rawget(_G, 'getPlayerVehicle') and getPlayerVehicle(0)
  local pid = nil
  if player and player.getID then local ok, id = pcall(idOf, player); pid = ok and id or nil end
  local function add(v, isPlayer, isRail, id)
    local okp, p = pcall(posOf, v)
    if not okp or not p then return end
    local okv, vel = pcall(velOf, v)
    local vx, vy = 0, 0
    if okv and vel then vx, vy = vel.x or 0, vel.y or 0 end
    local fx, fy = nil, nil                         -- (the way it faces: a train stopped still sees its next turnout)
    if isPlayer or isRail then
      local okd, d = pcall(dirOf, v)
      if okd and d then fx, fy = d.x, d.y end
    end
    local row = { x = p.x, y = p.y, z = p.z, vx = vx, vy = vy, speed = math.sqrt(vx * vx + vy * vy),
      fx = fx, fy = fy, player = isPlayer, rail = isRail, id = id }
    if isRail and fx then row.pts, row.hl = M.probes(p.x, p.y, fx, fy, M.halfLength(v, id)) end
    out[#out + 1] = row
  end
  if be and be.getObjectCount then
    for i = 0, be:getObjectCount() - 1 do
      local v = be:getObject(i)
      local ok, jb = pcall(jbeamOf, v)
      local isRail = ok and jb ~= nil and M.RAIL_VEHICLES[jb] == true
      local isPlayer, vid = false, nil
      if v.getID then local okI, id = pcall(idOf, v); vid = okI and id or nil end
      isPlayer = pid ~= nil and vid == pid
      if isRail or isPlayer then add(v, isPlayer, isRail, vid) end
    end
  elseif player then
    add(player, true, true, pid)
  end
  sceneRows = out
  return out
end
function M._resetScene() sceneAt = -1 end

-- The positions of the rail vehicles (M.RAIL_VEHICLES by jbeam name) in the scene.
local function railVehiclePositions()
  local out = {}
  for _, r in ipairs(M.scene()) do if r.rail then out[#out + 1] = r end end
  return out
end
M._railVehiclePositions = railVehiclePositions

-- Is a rail vehicle within RAILX_CLEAR_M of one of the crossing centres pts ({x, y, z} rows), or within
-- RAILX_AHEAD_S of driving at its speed (a fast train: the slab made render-only and the collision rebuilt in time)?
-- (positions: optional, {x, y[, speed]})
M.RAILX_AHEAD_S = 15
-- While the player drives a rail vehicle every crossing's inner slab is render-only, near or not (the user's idea,
-- 2026-10-26: "If player drive WLD, PN collisions OFF"): made so from the start, no slab to be made again in time
-- ahead of a fast train (a static collision rebuild late, or a tile come late, and the WLD's snowplow hit it).
-- Only in this game: another player's crossings follow their own train.
M.RAILX_PLAYER_OFF = true
function M.railVehicleNear(pts, positions)
  positions = positions or railVehiclePositions()
  for _, p in ipairs(positions) do
    if M.RAILX_PLAYER_OFF and p.player and pts and pts[1] then return true end
    local r = math.max(M.RAILX_CLEAR_M, (p.speed or 0) * M.RAILX_AHEAD_S)
    local r2 = r * r
    for _, c in ipairs(pts or {}) do
      local dx, dy = p.x - c[1], p.y - c[2]
      if dx * dx + dy * dy <= r2 then return true end
    end
  end
  return false
end

-- The contacts (the user, 2026-10-27: "lorsque le joueur se trouve sur une voie celle-ci est active, ... toutes les
-- autres voies ... qui rentrent en contact avec notre voie, leurs collisions sont desactivees"): a contact shape is
-- the rails of one track (its centre line round them: lines) where another track comes close. It is made
-- non-solid while a rail vehicle near it (CT_NEAR_M) runs on another track and none runs on this one; a vehicle is
-- on this track when, at its centre and CT_PROBE_M ahead and behind (along its motion), this track's line is as near
-- as any loaded track's (within CT_SAME_M): so in multiplayer a train on this track keeps it solid for itself.
M.CT_NEAR_M = 60
M.CT_PROBE_M = 6
M.CT_SAME_M = 0.15
M.CT_CHECK_S = 0.25

local function lineDist(lines, x, y)
  local best = math.huge
  for _, l in ipairs(lines or {}) do
    for i = 1, #l - 3, 2 do
      local x1, y1, x2, y2 = l[i], l[i + 1], l[i + 2], l[i + 3]
      local dx, dy = x2 - x1, y2 - y1
      local L2 = dx * dx + dy * dy
      local t = L2 > 1e-9 and math.max(0, math.min(1, ((x - x1) * dx + (y - y1) * dy) / L2)) or 0
      local d = math.sqrt((x - x1 - t * dx) ^ 2 + (y - y1 - t * dy) ^ 2)
      if d < best then best = d end
    end
  end
  return best
end
M._lineDist = lineDist

-- v2 (the user's run, 2026-10-27 on a high-speed line: a 280 m crossover lying between the two main tracks still
-- solid, the train derailed on it at speed): the contacts follow every rail vehicle's WAY, not its neighbourhood.
-- M.updateWays (every CT_CHECK_S) follows each train along the tracks as its turnouts are set (nrailsroute.follow),
-- AHEAD_S of its speed ahead (AHEAD_MIN_M at least) and its length behind: a contact whose own samples (core) lie on
-- such a way (CT_ON_M, over CT_ON_SHARE of them) is solid, as is one a vehicle stands on; every other one near a rail
-- vehicle (CT_FAR_M) is not: made non-solid kilometres ahead of a fast train, the collision rebuilt in time. With no
-- rail vehicle near, all solid (a train put on any of them).
M.CT_ON_M = 0.6
M.CT_ON_SHARE = 0.4
M.CT_FAR_M = 3000
M.AHEAD_S = 40
M.AHEAD_MIN_M = 500
M.BEHIND_M = 60
M.WAY_GROUP_M = 400

-- Pure: is a contact (core: flat x, y lists) on a way (ways: {{ {x, y}, ... }, ...})?
local function box(pts, flat)
  local x0, y0, x1, y1 = math.huge, math.huge, -math.huge, -math.huge
  if flat then
    for _, l in ipairs(pts) do
      for i = 1, #l - 1, 2 do
        local x, y = l[i], l[i + 1]
        if x < x0 then x0 = x end
        if x > x1 then x1 = x end
        if y < y0 then y0 = y end
        if y > y1 then y1 = y end
      end
    end
  else
    for _, q in ipairs(pts) do
      if q[1] < x0 then x0 = q[1] end
      if q[1] > x1 then x1 = q[1] end
      if q[2] < y0 then y0 = q[2] end
      if q[2] > y1 then y1 = q[2] end
    end
  end
  return x0, y0, x1, y1
end

function M.onWays(core, ways)
  local cx0, cy0, cx1, cy1 = box(core or {}, true)
  local near = {}
  for _, w in ipairs(ways or {}) do
    local x0, y0, x1, y1 = box(w, false)
    if x0 <= cx1 + 1 and x1 >= cx0 - 1 and y0 <= cy1 + 1 and y1 >= cy0 - 1 then near[#near + 1] = w end
  end
  if not near[1] then return false end
  ways = near
  local n, on = 0, 0
  for _, l in ipairs(core or {}) do
    for i = 1, #l - 1, 2 do
      n = n + 1
      local x, y = l[i], l[i + 1]
      for _, w in ipairs(ways or {}) do
        local hit = false
        for j = 1, #w - 1 do
          local ax, ay, bx, by = w[j][1], w[j][2], w[j + 1][1], w[j + 1][2]
          if math.abs(x - ax) < 60 and math.abs(y - ay) < 60 then
            local dx, dy = bx - ax, by - ay
            local L2 = dx * dx + dy * dy
            local t = L2 > 1e-9 and math.max(0, math.min(1, ((x - ax) * dx + (y - ay) * dy) / L2)) or 0
            if (x - ax - t * dx) ^ 2 + (y - ay - t * dy) ^ 2 <= M.CT_ON_M * M.CT_ON_M then hit = true; break end
          end
        end
        if hit then on = on + 1; break end
      end
    end
  end
  return n > 0 and on >= M.CT_ON_SHARE * n
end

-- Pure: is the contact (core) to be non-solid, given the trains' ways and the rail vehicles ({x, y, pts})?
function M.contactOff(core, ways, cars)
  if not core or not core[1] then return false end
  local near = false
  for _, c in ipairs(cars or {}) do
    if c.rail ~= false then
      local d = lineDist(core, c.x, c.y)
      if d <= M.CT_FAR_M then near = true end
      for _, q in ipairs(c.pts or { { c.x, c.y } }) do
        if lineDist(core, q[1], q[2]) <= M.CT_ON_M then return false end   -- (a vehicle stands on it)
      end
    end
  end
  if not near then return false end
  return not M.onWays(core, ways)
end

-- The ways of the rail vehicles (see above): M.activeWays = { ways = {...}, cars = {...}, player = way }.
local graphCache = { at = -100, sig = nil, g = nil }
local function graphNow(now)
  if now - graphCache.at < 2.0 and graphCache.g then return graphCache.g end
  local route = require('beamngEarth/nrailsroute')
  local n, sig = 0, 0
  for key, t in pairs(roads.extTiles()) do
    if t.railLines and not t.ghost then n = n + 1; sig = sig + #key * 7 + #t.railLines end
  end
  local s = n .. ':' .. sig
  if graphCache.sig ~= s or not graphCache.g then
    graphCache.g = route.graph(route.rows(roads.extTiles()))
    graphCache.sig = s
  end
  graphCache.at = now
  return graphCache.g
end

-- At a node with several ways on: the one a turnout there is set to (its set route's line nearest the way 15 m on).
local function pickBySwitches(g, route)
  return function(b, a, cands)
    local bx, by = g.x[b], g.y[b]
    local sw = nil
    for _, s in ipairs(M._swList or {}) do
      if s.at and (s.at[1] - bx) ^ 2 + (s.at[2] - by) ^ 2 <= 64 then sw = s; break end
    end
    if not sw then return nil end
    local r = sw.routes and sw.routes[switch.current(sw)]
    local line = r and (r.line or r.arm)
    if not line then return nil end
    local best, bd = nil, math.huge
    for _, n in ipairs(cands) do
      local x, y = route.ahead(g, b, n, 15)
      local d = switch._distToLine(x, y, line)
      if d < bd then best, bd = n, d end
    end
    return best
  end
end

function M.ways(now, cars)
  local route = require('beamngEarth/nrailsroute')
  local g = graphNow(now)
  local out = { ways = {}, cars = cars, player = nil }
  if not g or not next(g.x) then return out end
  local pick = pickBySwitches(g, route)
  -- (one way per train, not per wagon: the player's first, then any rail vehicle further than WAY_GROUP_M from those
  -- already followed or heading another way; the wagons between keep their contacts by their probes)
  table.sort(cars, function(a, b) return (a.player and 1 or 0) > (b.player and 1 or 0) end)
  local done = {}
  local function grouped(c)
    for _, d in ipairs(done) do
      if (c.x - d.x) ^ 2 + (c.y - d.y) ^ 2 < M.WAY_GROUP_M * M.WAY_GROUP_M then
        local s1, s2 = c.speed or 0, d.speed or 0
        if s1 < 0.5 or s2 < 0.5 or (c.vx * d.vx + c.vy * d.vy) > 0.9 * s1 * s2 then return true end
      end
    end
    return false
  end
  for _, c in ipairs(cars) do
    if c.rail ~= false and (c.player or not grouped(c)) then
      done[#done + 1] = c
      local hx, hy = c.vx, c.vy
      if (c.speed or 0) < 0.5 then hx, hy = c.fx or 0, c.fy or 0 end
      local len = math.max(M.AHEAD_MIN_M, (c.speed or 0) * M.AHEAD_S)
      local fwd = route.follow(g, c.x, c.y, hx, hy, len, pick)
      local back = route.follow(g, c.x, c.y, -hx, -hy, (c.hl or 10) + M.BEHIND_M, pick)
      out.ways[#out.ways + 1] = fwd
      out.ways[#out.ways + 1] = back
      if c.player then out.player = fwd end
    end
  end
  return out
end

local sinceCt = stopwatch.new()
function M.updateContacts(now)
  if sinceCt() < M.CT_CHECK_S * 1000 then return end
  sinceCt = stopwatch.new()
  now = now or os.clock()
  local cars = railVehiclePositions()
  local ok, w = pcall(M.ways, now, cars)
  M.activeWays = ok and w or { ways = {}, cars = cars }
  for key, t in pairs(roads.extTiles()) do
    if t.ctWalk and next(t.ctWalk) and not t.ghost then
      for what, wk in pairs(t.ctWalk) do
        local solid = not M.contactOff(t.ctCore[what], M.activeWays.ways, cars)
        if solid ~= t.ctSolid[what] then
          t.ctSolid[what] = solid
          roads.extRemake(key, t, what, wk, not solid)
        end
      end
    end
  end
end

-- roads.ext.update, every RAILX_CHECK_S: a tile whose crossings got (or lost) a rail vehicle near has its inner slabs
-- made again, solid or render-only (a TSStatic's collision type is only read when it is made).
local sinceRailx = stopwatch.new()
function M.updateRailCrossings()
  if sinceRailx() < M.RAILX_CHECK_S * 1000 then return end
  sinceRailx = stopwatch.new()
  local positions = nil
  for key, t in pairs(roads.extTiles()) do
    if t.railxPts and t.railxWalk and not t.ghost then
      positions = positions or railVehiclePositions()
      local solid = not M.railVehicleNear(t.railxPts, positions)
      if solid ~= t.railxSolid then
        t.railxSolid = solid
        roads.extRemake(key, t, 'nrailx', t.railxWalk, not solid)
      end
    end
  end
end

-- Snap a vehicle onto the track (M.snapToRail: the "Snap to rail" button and Ctrl+Shift+T). The road tiles carry their
-- tracks' centre lines ("rail_lines": flat x, y, z rows in the anchor frame, z the rail top, server
-- nrails.rails.RailTile.line_rows). M.nearestRail finds the nearest point of them; M.railSnapPose turns it into the
-- vehicle's pose.
M.SNAP_MAX_M = 40           -- m a track may lie from the vehicle to be snapped onto
M.SNAP_FLANGE_M = 0.10      -- m a rail vehicle's lowest point (its wheels' flange discs) is set under the rail top:
                            -- the flanges between the rails (0.21 m kept free there), the treads 5-8 cm over the rails
M.SNAP_LIFT_M = 0.05        -- m any other vehicle's lowest point is set over the rail top (a hi-rail's road tyres)
M.SNAP_Z_WEIGHT = 1.0       -- a height difference counts this much toward the distance (a track under a bridge)

-- The nearest track point to (x, y[, z]) within maxD (M.SNAP_MAX_M): { x, y, z (rail top), dx, dy, dz (unit tangent),
-- dist, key, colReady (the tile's rail collision is in) } or nil. Tiles moved by a rebase (ghosts) are skipped.
function M.nearestRail(x, y, z, maxD)
  maxD = maxD or M.SNAP_MAX_M
  local best
  local reach = roads.TILE_M + maxD
  for key, t in pairs(roads.extTiles()) do
    if t.railLines and not t.ghost
        and (not t.cx or (math.abs(t.cx - x) <= reach and math.abs(t.cy - y) <= reach)) then
      for _, row in ipairs(t.railLines) do
        for i = 1, #row - 5, 3 do
          local ax, ay, az, bx, by, bz = row[i], row[i + 1], row[i + 2], row[i + 3], row[i + 4], row[i + 5]
          local ex, ey, ez = bx - ax, by - ay, bz - az
          local l2 = ex * ex + ey * ey
          if l2 > 1e-8 then
            local u = math.max(0, math.min(1, ((x - ax) * ex + (y - ay) * ey) / l2))
            local px, py, pz = ax + u * ex, ay + u * ey, az + u * ez
            local dz = z and (pz - z) * M.SNAP_Z_WEIGHT or 0
            local d2 = (px - x) ^ 2 + (py - y) ^ 2 + dz * dz
            if d2 <= maxD * maxD and (not best or d2 < best.d2) then
              local l = math.sqrt(l2 + ez * ez)
              best = { d2 = d2, x = px, y = py, z = pz, dx = ex / l, dy = ey / l, dz = ez / l, key = key,
                colReady = t.nrailcol ~= nil }
            end
          end
        end
      end
    end
  end
  if best then best.dist = math.sqrt(best.d2) end
  return best
end

-- The tracks within maxD of (x, y[, z]): their nearest points, one per track (a track cut over several tiles' rows
-- counted once: points within SNAP_SAME_M of a nearer one dropped), nearest first (M.snapToRail's cycle).
M.SNAP_SAME_M = 2.0
function M.nearestRails(x, y, z, maxD)
  maxD = maxD or M.SNAP_MAX_M
  local cands = {}
  local reach = roads.TILE_M + maxD
  for key, t in pairs(roads.extTiles()) do
    if t.railLines and not t.ghost
        and (not t.cx or (math.abs(t.cx - x) <= reach and math.abs(t.cy - y) <= reach)) then
      for _, row in ipairs(t.railLines) do
        local best
        for i = 1, #row - 5, 3 do
          local ax, ay, az, bx, by, bz = row[i], row[i + 1], row[i + 2], row[i + 3], row[i + 4], row[i + 5]
          local ex, ey, ez = bx - ax, by - ay, bz - az
          local l2 = ex * ex + ey * ey
          if l2 > 1e-8 then
            local u = math.max(0, math.min(1, ((x - ax) * ex + (y - ay) * ey) / l2))
            local px, py, pz = ax + u * ex, ay + u * ey, az + u * ez
            local dz = z and (pz - z) * M.SNAP_Z_WEIGHT or 0
            local d2 = (px - x) ^ 2 + (py - y) ^ 2 + dz * dz
            if d2 <= maxD * maxD and (not best or d2 < best.d2) then
              local l = math.sqrt(l2 + ez * ez)
              best = { d2 = d2, x = px, y = py, z = pz, dx = ex / l, dy = ey / l, dz = ez / l, key = key,
                colReady = t.nrailcol ~= nil }
            end
          end
        end
        if best then cands[#cands + 1] = best end
      end
    end
  end
  table.sort(cands, function(a, b) return a.d2 < b.d2 end)
  local out = {}
  for _, c in ipairs(cands) do
    local dup = false
    for _, o in ipairs(out) do
      if (c.x - o.x) ^ 2 + (c.y - o.y) ^ 2 < M.SNAP_SAME_M ^ 2 then dup = true; break end
    end
    if not dup then c.dist = math.sqrt(c.d2); out[#out + 1] = c end
  end
  return out
end

-- Snap to rail pressed again within SNAP_CYCLE_S with the vehicle where it was put: the next track round the spot it
-- was first pressed at (the user, 2026-10-26: "quand on spam ctrl+shift+t, ca cycle parmi les rails adjacents").
M.SNAP_CYCLE_S = 6
M._snapCycle = nil
function M.snapPick(p, now)
  local c = M._snapCycle
  if c and now - c.at <= M.SNAP_CYCLE_S and (p.x - c.lx) ^ 2 + (p.y - c.ly) ^ 2 < 9 and #c.list > 1 then
    c.idx = c.idx % #c.list + 1
    return c.list[c.idx], c.idx, #c.list, c
  end
  local list = M.nearestRails(p.x, p.y, p.z)
  if not list[1] then return nil end
  c = { list = list, idx = 1 }
  return list[1], 1, #list, c
end

-- The pose of a vehicle snapped onto the track point r (M.nearestRail): its forward along the track the way it faced
-- (fx, fy: its forward now), its reference point at r's rail top + refOverBottom (the reference point's height over
-- the vehicle's lowest point) - M.SNAP_FLANGE_M for a rail vehicle (else + M.SNAP_LIFT_M).
-- Returns x, y, z, dx, dy, dz.
function M.railSnapPose(r, fx, fy, refOverBottom, isRail)
  local dx, dy, dz = r.dx, r.dy, r.dz
  if (fx or 0) * dx + (fy or 0) * dy < 0 then dx, dy, dz = -dx, -dy, -dz end
  local z = r.z + (refOverBottom or 0) + (isRail and -M.SNAP_FLANGE_M or M.SNAP_LIFT_M)
  return r.x, r.y, z, dx, dy, dz
end

-- The vehicle's reference node over its lowest collidable point (m) and its lateral offset from the collidable nodes'
-- centre (m, local +x: the vehicle's left), from its initial node positions (vehicle space: z up, -y forward); else
-- from its world box now. nil when neither is readable.
local function vehicleFootprint(veh)
  local ok, over, side = pcall(function()
    local bb = veh.initialCollidableNodePosBB
    local ref = veh:getInitialNodePosition(veh:getRefNodeId())
    return ref.z - bb.minExtents.z, ref.x - (bb.minExtents.x + bb.maxExtents.x) / 2
  end)
  if ok and type(over) == 'number' and over > -1 and over < 10 then return over, side end
  ok, over = pcall(function()
    local box = veh:getSpawnWorldOOBB()
    local c, he = box:getCenter(), box:getHalfExtents()
    local low = c.z
    for i = 0, 2 do low = low - math.abs(box:getAxis(i).z) * (i == 0 and he.x or i == 1 and he.y or he.z) end
    return veh:getPosition().z - low
  end)
  if ok and type(over) == 'number' and over > -1 and over < 10 then return over, 0 end
  return nil
end

M._footprint = vehicleFootprint

-- Put the player vehicle on the nearest track within maxD m (M.SNAP_MAX_M): along the track the way it faces, its
-- wheels' flanges between the rails (a rail vehicle) or its tyres just over them (any other: a hi-rail), at rest
-- (setPositionRotation resets the vehicle there, core_checkpoints' way). Returns true when placed.
function M.snapToRail(maxD)
  local veh = getPlayerVehicle and getPlayerVehicle(0)
  if not veh then setStatus('Snap to rail: no vehicle'); return false end
  local p = veh:getPosition()
  local r, idx, n, cyc
  if maxD then r = M.nearestRail(p.x, p.y, p.z, maxD); idx, n = 1, 1
  else r, idx, n, cyc = M.snapPick(p, os.clock()) end
  if not r then
    setStatus(string.format('Snap to rail: no track within %d m (are rails on in the Hub?)', maxD or M.SNAP_MAX_M))
    return false
  end
  local over, side = vehicleFootprint(veh)
  if not over then
    local ray = rawget(_G, 'castRayStatic')
    local d = ray and ray(vec3(p.x, p.y, p.z), vec3(0, 0, -1), 20)
    over, side = (d and d < 20) and d or 1.0, 0
  end
  local okJb, jb = pcall(function() return veh:getJBeamFilename() end)
  local isRail = okJb and M.isRailVehicle(jb)
  local f = veh:getDirectionVector()
  local x, y, z, dx, dy, dz = M.railSnapPose(r, f.x, f.y, over, isRail)
  side = math.max(-1, math.min(1, side or 0))
  local h = math.sqrt(dx * dx + dy * dy)
  if h > 1e-6 then x, y = x - dy / h * side, y + dx / h * side end      -- the vehicle's centre on the track's
  local dir = vec3(dx, dy, dz)
  local up = (vec3(0, 0, 1) - dir * dz):normalized()
  local rot = quatFromDir(-dir, up)                                       -- (vehicles face their -y)
  veh:resetBrokenFlexMesh()
  veh:setPositionRotation(x, y, z, rot.x, rot.y, rot.z, rot.w)
  pcall(function() veh:queueLuaCommand('recovery.clear()') end)
  if cyc then cyc.at, cyc.lx, cyc.ly = os.clock(), x, y; M._snapCycle = cyc end
  setStatus(string.format('Snapped onto the track %.1f m away%s%s', r.dist,
    (n or 1) > 1 and string.format(' - voie %d/%d (Ctrl+Shift+T encore : la suivante)', idx, n) or '',
    r.colReady and '' or ' (its collision is still loading: wait a moment before driving)'))
  log('I', 'beamngEarth', string.format('nrails snapToRail: %s at %.2f, %.2f, %.2f (rail top %.2f, ref over bottom %.2f%s)',
    tostring(jb), x, y, z, r.z, over, isRail and ', rail vehicle' or ''))
  return true
end

-- Couple / uncouple (the user, 2026-10-26: "un bouton pour attacher un ou des rails"): the couplers of the player's
-- vehicle and of every rail vehicle within COUPLE_M of it (BeamNG's beamstate couplers: auto-coupling on and the
-- couplers in reach attached; or detached and auto-coupling off). Returns how many vehicles were told.
M.COUPLE_M = 80
-- (the rail mods put "tag" on one end and "couplerTag" on the other, the coupler part's variant (A / B) choosing which:
-- two vehicles meeting tag end to tag end never coupled with beamstate's auto-coupling (the user's run, 2026-10-26:
-- "couplers touching" and nothing). So every coupler node of the vehicle, couplerTag or a coupler "tag", asks the
-- engine itself (obj:attachCoupler) for a node of the other vehicle with its tag within its coupler radius; the
-- auto-coupling on for those tags too.)
M.COUPLE_CMD = 'local s = {} for _, n in pairs(v.data.nodes or {}) do local t = n.couplerTag or (type(n.tag) == "string" and n.tag:find("coupler", 1, true) and n.tag) if t and n.cid then s[t] = true obj:attachCoupler(n.cid, t, n.couplerStrength or 3000000, math.max(n.couplerRadius or 0, 1.5), n.couplerLockRadius or 0.025, n.couplerLatchSpeed or 0.3, 0) end end local l = {} for t in pairs(s) do l[#l + 1] = t end if #l > 0 and beamstate.activateAutoCoupling then beamstate.activateAutoCoupling(l) end'
M.UNCOUPLE_CMD = 'if beamstate.disableAutoCoupling then beamstate.disableAutoCoupling() end for _, n in pairs(v.data.nodes or {}) do local t = n.couplerTag or (type(n.tag) == "string" and n.tag:find("coupler", 1, true) and n.tag) if t and n.cid then obj:detachCoupler(n.cid, 0) end end if beamstate.detachCouplers then beamstate.detachCouplers(nil, true) end'
function M.couple(on)
  local player = rawget(_G, 'getPlayerVehicle') and getPlayerVehicle(0)
  if not player then setStatus('NRails: no vehicle'); return 0 end
  local pp = player:getPosition()
  local pid = player.getID and player:getID()
  local n = 0
  local function tell(v)
    if pcall(function() v:queueLuaCommand(on and M.COUPLE_CMD or M.UNCOUPLE_CMD) end) then n = n + 1 end
  end
  tell(player)
  if be and be.getObjectCount then
    for i = 0, be:getObjectCount() - 1 do
      local v = be:getObject(i)
      local ok, jb = pcall(function() return v:getJBeamFilename() end)
      if ok and M.RAIL_VEHICLES[jb] and not (pid and v.getID and v:getID() == pid) then
        local q = v:getPosition()
        if (q.x - pp.x) ^ 2 + (q.y - pp.y) ^ 2 <= M.COUPLE_M ^ 2 then tell(v) end
      end
    end
  end
  if M.ui then M.ui.onCouple(on, n) end
  setStatus(on and string.format('NRails: attelage / coupling (%d vehicule(s))', n)
    or string.format('NRails: detelage / uncoupling (%d vehicule(s))', n))
  return n
end

-- Collision for the trains the player is not driving (collisionfoci.lua gives every other vehicle a collision island:
-- PLAYER_R for a player's, TRAFFIC_R and no solid trees for AI traffic, none when parked). A rail vehicle gets
-- RAIL_FOCUS_R, whatever spawned it (a train set going at 160 km/h covers 320 m in 7 s: its rails must be solid before
-- it gets there), and no solid trees (a train never leaves its track). Wraps collisionfoci's vehicles / compute in
-- place (update calls them through its module table): no change to upstream's file.
M.RAIL_FOCUS_R = 480

function M.wrapFoci(cf, jbeamOf)
  if not cf or cf._nrails then return cf end
  jbeamOf = jbeamOf or function(id)
    local o = be and be.getObjectByID and be:getObjectByID(id)
    if not o then return nil end
    local ok, jb = pcall(function() return o:getJBeamFilename() end)
    return ok and jb or nil
  end
  local vehicles0, compute0 = cf.vehicles, cf.compute
  cf.vehicles = function(...)
    local out = vehicles0(...)
    for _, v in ipairs(out) do
      if M.isRailVehicle(jbeamOf(v.id)) then
        v.rail = true
        if v.kind == 'traffic' then v.kind = 'player' end
      end
    end
    return out
  end
  cf.compute = function(vehicles, ...)
    local out = compute0(vehicles, ...)
    local rail = {}
    for _, v in ipairs(vehicles or {}) do if v.rail then rail[v.id] = true end end
    for _, f in ipairs(out) do
      if rail[f.id] then f.r = math.max(f.r or 0, M.RAIL_FOCUS_R); f.trees = false; f.rail = true end
    end
    return out
  end
  cf._nrails = true
  return cf
end

-- The order the mod makes a tile's meshes in (the user, 2026-10-24: "une hierarchie de chargement: 1er terrain, 2e
-- routes et rails, 3e batiments, 4 reste"; the terrain block comes before any of them): roads.nextWalk's key k (the
-- distance along the car's path, + 1e6 for what is only drawn) with the track drawn right after the colliders (+1e5,
-- not with the buildings' facades) and the buildings' collision after the roads' and the rails' (+2e5).
function M.priority(e, k)
  local w = e.what or ''
  if w:sub(1, 5) == 'nrail' and k >= 1e6 then return k - 1e6 + 1e5 end
  if w == 'bldcol' then return k + 2e5 end
  return k
end

-- Each frame (roads.ext.update): the level crossings' slabs, the load guard (nrailsload.lua).
local loadguard = require('beamngEarth/nrailsload')
M.loadguard = loadguard
-- The keys' help (Ctrl+Shift+I, the window's Keys button, and by itself when boarding a train unless "do not show
-- again" is ticked), the turnout diagram (Ctrl+Shift+M: shown until pressed again), the signals and the coupling
-- assistant: nrailsui.lua.
M.KEYS = {
  { 'Ctrl+Shift+I', 'cette aide / this help' },
  { 'Ctrl+Shift+U', 'fenetre BeamNG.Earth / the window' },
  { 'Ctrl+Shift+T', 'sur le rail le plus proche / snap to rail' },
  { 'Ctrl+Shift+T (x2)', 'encore : la voie voisine suivante / next track' },
  { 'Ctrl+Shift+G', 'recharger la zone / reload area' },
  { 'Ctrl+Shift+Left', 'prochain aiguillage a gauche / next turnout left' },
  { 'Ctrl+Shift+Up', 'prochain aiguillage tout droit / next turnout straight' },
  { 'Ctrl+Shift+Right', 'prochain aiguillage a droite / next turnout right' },
  { 'Ctrl+Shift+M', 'schema des voies on / off (clic : aiguillage, itineraire)' },
  { 'Ctrl+Shift+O', 'atteler (approcher a moins de 2 m) / couple' },
  { 'Ctrl+Shift+N', 'deteler / uncouple' },
  { 'Ctrl+Shift+B', 'guidage : bogies tenus sur les rails on / off / rail guidance' },
  { 'Ctrl+Shift+K', 'regulateur de vitesse on / off / cruise control' },
  { 'Ctrl+Shift+PgUp / PgDn', 'regulateur +/- 5 km/h' },
  { 'Ctrl+Shift+J', 'configurateur de train / train configurator' },
}
M.helpOn = false
function M.toggleHelp() M.helpOn = not M.helpOn; return M.helpOn end

M._roads = roads
function M._setStatus(s) setStatus(s) end
local ui = require('beamngEarth/nrailsui')
M.ui = ui
ui.init(M)
function M.drawHelp() return ui.drawHelp() end
function M.toggleSchema() return ui.toggleSchema() end
function M.drawSchema(now) return ui.drawSchema(now) end

-- The rail guidance (nrailsguide.lua and the vehicle extension nrailsGuide.lua): the wheels held on the track, on / off
-- by Ctrl+Shift+B or the keys window's button, kept in the prefs.
local guide = require('beamngEarth/nrailsguide')
M.guide = guide
guide.init(M, switch)
guide.on = ui.prefs and ui.prefs.guide == true
guide.STRENGTH = ui.prefs and tonumber(ui.prefs.guideStrength) or guide.STRENGTH
function M.toggleGuide()
  local on = guide.toggle()
  if ui.prefs then ui.prefs.guide = on; pcall(ui.savePrefs) end
  setStatus(on and 'NRails: guidage on : bogies tenus sur les rails / rail guidance on'
    or 'NRails: guidage off : physique libre / rail guidance off')
  return on
end

-- The railways on BeamNG.Earth's map: nrailsmap.lua (the map's NRails parts call M.map.*).
local map = require('beamngEarth/nrailsmap')
M.map = map
map.init(M, ui, require('beamngEarth/nrailsroute'), roads, function() return M.geo and M.geo() end)

-- The level crossings' barriers, lights and protection: nrailsxing.lua (OSM's crossing tags through nrailsmap).
local xing = require('beamngEarth/nrailsxing')
M.xing = xing
xing.init(M, map)

-- The driving aids (the speed regulator, the speed control after the KVB) and the train configurator: nrailsdrive.lua.
local drive = require('beamngEarth/nrailsdrive')
M.drive = drive
drive.init(M, switch, require('beamngEarth/nrailsroute'), ui, map)
function M.regToggle() return drive.regToggle() end
function M.regStep(d) return drive.regStep(d) end
function M.toggleConfig() return drive.toggleConfig() end

-- The server's "nrails_*" answers (core.lua's NRails hook): OSM's railways, routes (nrailsmap).
function M.onMessage(msg)
  if type(msg) ~= 'table' then return end
  pcall(map.onMessage, msg)
end

-- Pure: the flat x, y list mapped into a diagram (the node at 0.35 of its width; nrailsui.xy).
function M.schemaXY(flat, at, dir, scale, w, h, every)
  return ui.xy(flat, at, dir, scale, w, h, 0.35, every)
end

-- A teleport's first block comes provisional (server make_provisional: the DEM's ground, no road grading, no rail
-- corridor: the terrain over the rails) and is swapped for the graded one (terrain_refresh) 15-60 s later on a fresh
-- place. core.lua (NRails hooks) tells us; a rail vehicle setting off meanwhile is held by the load guard (the user's
-- runs 2026-10-25 / 26: "reapparition de ce terrain apres teleportation"), PROVISIONAL_MAX_S at most.
M.PROVISIONAL_MAX_S = 90
M.provisional, M.provisionalAt = false, nil
function M.setProvisional(on)
  M.provisional = on == true
  M.provisionalAt = M.provisional and os.clock() or nil
end
function M.provisionalHolds(now)
  if not M.provisional then return false end
  now = now or os.clock()
  if M.provisionalAt and now - M.provisionalAt > M.PROVISIONAL_MAX_S then return false end
  local veh = rawget(_G, 'getPlayerVehicle') and getPlayerVehicle(0)
  if not veh then return false end
  local ok, jb = pcall(function() return veh:getJBeamFilename() end)
  return ok and M.isRailVehicle(jb) or false
end

local sinceXing = stopwatch.new()
function M.update()
  M.updateRailCrossings()
  pcall(M.updateContacts)
  pcall(M.updateSwitches)
  pcall(ui.update)
  pcall(guide.update, nil, roads.extTiles())
  pcall(map.update)
  if sinceXing() >= xing.CHECK_S * 1000 then
    sinceXing = stopwatch.new()
    pcall(xing.update, nil, roads.extTiles())
  end
  local pp = ui._playerPose and ui._playerPose()
  pcall(xing.draw, nil, pp and pp.x, pp and pp.y)
  pcall(drive.update, nil, roads.extTiles())
  pcall(drive.drawPanel)
  pcall(drive.drawConfig)
  pcall(M.drawHelp)
  pcall(M.drawSchema)
  if not M.anchor then return end
  local holdRail = M.provisionalHolds()
  pcall(loadguard.update, nil, {
    anchor = M.anchor,
    ready = function(aid, x, y, r)
      if holdRail then return false end         -- (a train on a teleport's provisional block: wait for the graded)
      return roads.readyAround(aid, x, y, r)
    end,
    busy = function()
      local lp = package.loaded['beamngEarth/loadprogress']
      if lp and lp.active and lp.active() then return true end
      local core = rawget(_G, 'beamngEarth_core')
      local h = core and core.dropHoldState and core.dropHoldState()
      return h ~= nil and h.active == true
    end,
  })
end

-- core.lua (NRails hook): opts.setStatus(text) shows a status line.
local inited = false
-- Under the sea (the Channel Tunnel, 2026-10-24): the sea's WaterBlocks reach DEPTH_M / 2 under their surface, and a
-- vehicle's physics takes the newest water object it is in: the sea's physics block round the player. A train in a
-- tunnel under the sea floor was in the sea (buoyancy, drag, a drowned engine). When the player is DRY_UNDER_M or more
-- under the water's surface with something static over it (castRayStatic up: the tube's vault, the sea floor's
-- terrain) within ROOF_RAY_M, the physics block's surface is put DRY_M under the player (in DRY_STEP_M steps: the
-- sea makes the block again only when it changes): the player is out of the water.
M.DRY_UNDER_M = 3.0
M.ROOF_RAY_M = 150.0
M.DRY_M = 40.0
M.DRY_STEP_M = 20.0

-- Covered: something static over the player. Up from it (a solid roof), or down from over the water's surface to a
-- ground above it: the tube's vault is drawn only and the terrain is hit from above only, so the ray up from inside
-- the Channel Tunnel found nothing and the train drowned (the user's run, 2026-10-25).
M.COVER_M = 2.0         -- m the ground found from above stands over the player at least
function M.covered(player, surface, ray)
  local ok, d = pcall(ray, vec3(player.x, player.y, player.z + 1.5), vec3(0, 0, 1), M.ROOF_RAY_M)
  if ok and d and d < M.ROOF_RAY_M then return true end
  local top = surface + 5
  local len = top - player.z
  if len <= M.COVER_M then return false end
  ok, d = pcall(ray, vec3(player.x, player.y, top), vec3(0, 0, -1), len)
  return ok and d ~= nil and d < len - M.COVER_M
end

function M.physZ(player, z)
  if not player or not z or player.z > z - M.DRY_UNDER_M then return z end
  local ray = rawget(_G, 'castRayStatic')
  if not ray then return z end
  if not M.covered(player, z, ray) then return z end
  return math.floor((player.z - M.DRY_M) / M.DRY_STEP_M) * M.DRY_STEP_M
end

-- "Reload area" (the user's run, 2026-10-25: "un bouton pour recharger la zone ou forcer le chargement, comme un ping
-- au serveur"): the connection to the world server dropped and made again (core.reconnect): the server starts the
-- session over and sends every tile round the player again, those it never sent included. Not more often than
-- every RELOAD_MIN_S.
M.RELOAD_MIN_S = 5
local lastReload = nil
function M.reloadArea(core, now)
  core = core or rawget(_G, 'beamngEarth_core')
  now = now or os.clock()
  if lastReload and now - lastReload < M.RELOAD_MIN_S then return false, 'wait' end
  if not core or not core.reconnect then return false, 'no core' end
  lastReload = now
  local ok, err = pcall(core.reconnect)
  if setStatus then pcall(setStatus, ok and 'NRails: reloading the area (server asked again)' or ('NRails: reload failed: ' .. tostring(err))) end
  return ok, err
end

-- The loading line's roads part names the rails too (loadprogress.PARTS: the road tiles carry the track).
function M.labelLoading(lp)
  lp = lp or require('beamngEarth/loadprogress')
  for _, part in ipairs(lp.PARTS or {}) do
    if part[1] == 'roads' then part[2] = 'roads, rails & buildings' end
  end
end

function M.init(opts)
  opts = opts or {}
  if opts.setStatus then setStatus = opts.setStatus end
  if inited then return M end
  inited = true
  for _, w in ipairs(M.KINDS) do roads.EXT_KINDS[#roads.EXT_KINDS + 1] = w end
  local have = false
  for _, f in ipairs(roads.MATERIAL_FILES) do if f == M.MATERIAL_FILE then have = true end end
  if not have then roads.MATERIAL_FILES[#roads.MATERIAL_FILES + 1] = M.MATERIAL_FILE end
  if opts.anchor then M.anchor = opts.anchor end
  if opts.geo then M.geo = opts.geo end                  -- (the anchor's geodesy: the map's lat / lon, nrailsmap)
  roads.ext = { onTile = onTile, update = M.update, lean = isCol, priority = M.priority }
  -- a remade NRails mesh (a level crossing's slab, a turnout's route: roads.extRemake) makes the next collision rebuild
  -- urgent (URGENT_GAP_S), not the RELOAD_EVERY_S of the other meshes: the train is on its way to it
  if not M._urgentWrapped and roads.urgentColliders then
    local orig = roads.urgentColliders
    roads.urgentColliders = function(...)
      if roads.extUrgentUntil and os.clock() * 1000 < roads.extUrgentUntil then return true end
      return orig(...)
    end
    M._urgentWrapped = true
  end
  pcall(function() require('beamngEarth/sea').ext = { physZ = M.physZ } end)
  pcall(M.loadVehicleList)
  pcall(function() M.wrapFoci(require('beamngEarth/collisionfoci')) end)
  pcall(M.labelLoading)
  return M
end

return M
