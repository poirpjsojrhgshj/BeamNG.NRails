-- BeamNG.NRails: the turnouts (the user's runs, 2026-10-25 / 26: "une chance sur le nombre de voies qu'un bogie aille
-- sur la mauvaise voie"; "les aiguillages ... c'est pas du tout fonctionnel").
-- The server gives each road tile its turnouts (data.railsw: id, at, dir, def (the main line's route), trunk (the
-- track behind the node, flat x, y), routes: side (+ left), line (its switch zone), arm (the route's first 250 m)) and
-- the collision shapes of their zones (data.railsw_shapes: what "nrailswN", need: {{turnout id, route}, ...}: solid
-- only while every listed turnout is set to that route; a crossover's or a ladder's overlapping zones).
-- step() is pure (mod/tests/test_nrails.lua). Every rail vehicle is placed on the LINE it runs on (the trunk or a
-- route's arm, within ON_M), never by its distance to a turnout's axis (a parallel track's turnout took the choice):
--   * running toward a turnout on one of its routes (trailing): the turnout is set to that route, as far ahead as
--     AHEAD_S of its speed (DETECT_MIN_M at least);
--   * the player's train running toward a turnout on its trunk (facing): the next one takes the choice made with
--     the keys (left / straight / right), used up;
--   * the plan (M.plan: id -> route: the turnouts clicked on the diagram, an itinerary's): each turnout set to it
--     whenever nothing above sets it (2026-10-26: "les branches cliquables, gestion des aiguillages multiples,
--     itineraire"); otherwise a turnout keeps its state (at first the main line);
--   * a turnout with a rail vehicle in its zone is locked: never set under a train.
local M = {}

M.ON_M = 2.2            -- m from a line a vehicle runs on it
M.CLEAR_M = 0.8         -- m nearer to that line than to any other of the turnout's: clearly on it
M.DETECT_MIN_M = 200    -- m ahead a turnout is looked at (at least)
M.AHEAD_S = 15          -- s of the vehicle's speed ahead a turnout is looked at
M.LOCK_M = 2.5          -- m from a zone's line a rail vehicle locks the turnout
M.MIN_SPEED = 0.3       -- m/s
M.LATERAL_M = 3         -- m (a turnout without a trunk: the vehicle within this of its axis behind it)
M.FACING_MAX_M = 1500   -- m: the player's next facing turnout looked for this far (stopped too: the diagram)

M.state = {}            -- id -> route index (1-based)
M.pending = nil         -- 'left' | 'straight' | 'right'
M.plan = {}             -- id -> route index wanted (clicked, an itinerary's)

-- The route index for a choice among the routes (sorted left to right by the server).
function M.pick(sw, choice)
  local n = #(sw.routes or {})
  if n == 0 then return nil end
  if type(choice) == 'number' then return (choice >= 1 and choice <= n) and choice or nil end
  if choice == 'left' then return 1 end
  if choice == 'right' then return n end
  return (sw.def or 0) + 1
end

function M.current(sw)
  return M.state[sw.id] or ((sw.def or 0) + 1)
end

-- Is a shape's need ({{id, route}, ...}) met by the turnouts' states? (byId: id -> row, for their defaults)
function M.needMet(need, byId)
  for _, n in ipairs(need or {}) do
    local id, idx = n[1], n[2]
    local cur = M.state[id]
    if cur == nil then
      local sw = byId and byId[id]
      cur = sw and ((sw.def or 0) + 1) or 1
    end
    if cur ~= idx then return false end
  end
  return true
end

local function distToLine(x, y, flat)
  if type(flat) ~= 'table' or #flat < 2 then return math.huge end
  if #flat == 2 then return math.sqrt((x - flat[1]) ^ 2 + (y - flat[2]) ^ 2) end
  local best = math.huge
  for i = 1, #flat - 3, 2 do
    local ax, ay, bx, by = flat[i], flat[i + 1], flat[i + 2], flat[i + 3]
    local dx, dy = bx - ax, by - ay
    local l2 = dx * dx + dy * dy
    local t = l2 > 0 and math.max(0, math.min(1, ((x - ax) * dx + (y - ay) * dy) / l2)) or 0
    local ex, ey = ax + t * dx - x, ay + t * dy - y
    local d = math.sqrt(ex * ex + ey * ey)
    if d < best then best = d end
  end
  return best
end
M._distToLine = distToLine

-- A vehicle's probe points (its bogies and ends, nrails.scene: c.pts), or its centre.
local function probes(c) return c.pts or { { c.x, c.y } } end
M._probes = probes

-- Is a rail vehicle in the turnout's zone (any of its probes on any route's zone line within LOCK_M)? (except: a car
-- not counted)
local function occupied(sw, cars, except)
  for _, c in ipairs(cars) do
    if c.rail ~= false and c ~= except then
      for _, q in ipairs(probes(c)) do
        for _, r in ipairs(sw.routes or {}) do
          if distToLine(q[1], q[2], r.line) <= M.LOCK_M then return true end
        end
      end
    end
  end
  return false
end
M.occupied = occupied

-- Where a car is about a turnout: 'trunk', the route index it runs on, or nil.
local function placeOn(sw, car)
  local best, bd, second = nil, math.huge, math.huge
  for i, r in ipairs(sw.routes or {}) do
    local d = distToLine(car.x, car.y, r.arm or r.line)
    if d < bd then best, second, bd = i, bd, d elseif d < second then second = d end
  end
  local tx, ty = sw.at[1] - car.x, sw.at[2] - car.y
  local onTrunk
  if sw.kind == 'diamond' then
    onTrunk = false
  elseif sw.trunk then
    local dt = distToLine(car.x, car.y, sw.trunk)
    onTrunk = dt <= M.ON_M and dt < bd - 0.3
  else
    local along = -(tx * sw.dir[1] + ty * sw.dir[2])
    local lateral = math.abs(-tx * sw.dir[2] + ty * sw.dir[1])
    onTrunk = along < -1 and lateral <= M.LATERAL_M
  end
  if onTrunk then return 'trunk' end
  if best and bd <= M.ON_M and second - bd >= M.CLEAR_M then return best end
  return nil
end
M._placeOn = placeOn

-- Would setting sw to route `want` move it under a rail vehicle? A rail vehicle in its zone (within LOCK_M of a
-- route's zone line) that is on another route, or on the blades where the routes cannot be told apart. One on the
-- route wanted is no reason to wait: a train running in on a track joining ours, its turnout's tile come late (the
-- train already in the zone), left the turnout on the other route, ours not solid and the joining one in our way
-- (the user's run, 2026-10-26: "les aiguillages qui viennent sur notre voie generent des collisions").
function M.conflict(sw, cars, want)
  for _, c in ipairs(cars or {}) do
    if c.rail ~= false then
      for _, q in ipairs(probes(c)) do            -- (every bogie, not the vehicle's centre alone)
        local inZone = false
        for _, r in ipairs(sw.routes or {}) do
          if distToLine(q[1], q[2], r.line) <= M.LOCK_M then inZone = true; break end
        end
        if inZone then
          local on = placeOn(sw, { x = q[1], y = q[2] })
          if on ~= want then return true end     -- (on the trunk at the zone: its body over the blades)
        end
      end
    end
  end
  return false
end

-- Pure: cars = {{x, y, vx, vy, fx, fy, player = bool, rail = bool}} (fx, fy: the way it faces, for a train
-- stopped). Returns changes { [id] = route index } (only those that change, never a locked turnout), whether the
-- pending choice was used, and the player's next facing turnout { sw, dist } (or nil; also when stopped, ahead of
-- the way the train faces).
function M.step(switches, cars)
  local changes, used, nextFacing = {}, false, nil
  if not cars or not cars[1] then return changes, used, nil end
  if cars.x then cars = { cars } end           -- (one vehicle: the older call)
  local facing, fdist = nil, math.huge
  for _, car in ipairs(cars) do
    local v = math.sqrt(car.vx * car.vx + car.vy * car.vy)
    local hx, hy = car.vx, car.vy
    if v < M.MIN_SPEED and car.fx then hx, hy = car.fx, car.fy end
    local reach = math.max(M.DETECT_MIN_M, v * M.AHEAD_S)
    for _, sw in ipairs(switches) do
      local tx, ty = sw.at[1] - car.x, sw.at[2] - car.y
      local dist = math.sqrt(tx * tx + ty * ty)
      local toward = (tx * hx + ty * hy) > 0
      local look = car.player and math.max(reach + 60, M.FACING_MAX_M) or (reach + 60)
      if dist <= look and toward then
        local on = placeOn(sw, car)
        if on == 'trunk' then
          if car.player and dist < fdist then facing, fdist = sw, dist end
        elseif on and v >= M.MIN_SPEED and dist <= reach + 60 and car.rail ~= false then
          if M.current(sw) ~= on and changes[sw.id] == nil then changes[sw.id] = on end
        end
      end
    end
  end
  if facing then
    nextFacing = { sw = facing, dist = fdist }
    if M.pending then
      local want = M.pick(facing, M.pending)
      if want and want ~= M.current(facing) then changes[facing.id] = want end
      used = true
    end
  end
  for _, sw in ipairs(switches) do              -- the plan, where nothing else sets the turnout
    local want = M.plan[sw.id]
    if want and changes[sw.id] == nil and want ~= M.current(sw) and sw.routes and sw.routes[want] then
      changes[sw.id] = want
    end
  end
  for id, want in pairs(changes) do             -- (never under a train on another route)
    for _, sw in ipairs(switches) do
      if sw.id == id and M.conflict(sw, cars, want) then changes[id] = nil end
    end
  end
  if facing and changes[facing.id] == nil and used and M.pick(facing, M.pending) ~= M.current(facing)
      and M.conflict(facing, cars, M.pick(facing, M.pending)) then
    used = false                                -- (locked: the choice waits)
  end
  return changes, used, nextFacing
end

-- A turnout's route chosen on the diagram: kept in the plan (set as soon as nothing is in its zone). Returns the
-- route index (nil: none).
function M.choose(sw, idx)
  if not sw or not sw.routes or not sw.routes[idx] then return nil end
  M.plan[sw.id] = idx
  return idx
end

-- The turnouts of the tiles (roads.extTiles), each once: { id -> row }, list.
function M.collect(tiles)
  local out, list = {}, {}
  for _, t in pairs(tiles) do
    if t.railsw and not t.ghost then
      for _, sw in ipairs(t.railsw) do
        if not out[sw.id] then out[sw.id] = sw; list[#list + 1] = sw end
      end
    end
  end
  return out, list
end

-- A diverging route taken at 60 km/h rather than 30: a gentle turnout (its route's arm less than FAST_DEG off the
-- main route's over its first FAST_AT_M).
M.FAST_DEG = 3.0
M.FAST_AT_M = 60
local function armDir(r)
  local a = r and (r.arm or r.line)
  if not a or #a < 4 then return nil end
  local x0, y0 = a[1], a[2]
  local bx, by = a[#a - 1], a[#a]
  for i = 3, #a - 1, 2 do
    if (a[i] - x0) ^ 2 + (a[i + 1] - y0) ^ 2 >= M.FAST_AT_M ^ 2 then bx, by = a[i], a[i + 1]; break end
  end
  local l = math.sqrt((bx - x0) ^ 2 + (by - y0) ^ 2)
  if l < 1e-6 then return nil end
  return (bx - x0) / l, (by - y0) / l
end
function M.fastDiverge(sw, idx)
  local main = sw.routes and sw.routes[(sw.def or 0) + 1]
  local ax, ay = armDir(sw.routes and sw.routes[idx])
  local mx, my = armDir(main)
  if not ax or not mx then return false end
  local c = math.max(-1, math.min(1, ax * mx + ay * my))
  return math.deg(math.acos(c)) < M.FAST_DEG
end

-- The lights a signal of the turnout shows (French railway's, SNCF; nrails.rails._signals places them): a list of
-- { colour, across, up, flash } (across / up: the lamp's place on the target in lamp steps, flash: blinking).
--   protection ("main"): green the main line set; RR30 / RR60 (two yellow one over the other, flashing at 60) a
--     diverging route; carre (two red side by side) a vehicle on the turnout;
--   advance ("adv"): green; ralentissement 30 / 60 (two yellow side by side, flashing at 60) a diverging route ahead;
--     avertissement (one yellow) the turnout taken by a vehicle;
--   a yard's ("yard"): white (shunting allowed), violet (carre violet) a vehicle on it.
function M.lamps(sw, cars, kind, yard)
  if not sw then return { { 'red', -1, 0 }, { 'red', 1, 0 } } end
  local occ = occupied(sw, cars or {})
  if yard then return { occ and { 'violet', 0, 0 } or { 'white', 0, 0 } } end
  local cur = M.current(sw)
  local main = cur == (sw.def or 0) + 1
  local fast = not main and M.fastDiverge(sw, cur)
  if kind == 'adv' then
    if occ then return { { 'yellow', 0, 0 } } end
    if main then return { { 'green', 0, 0 } } end
    return { { 'yellow', -1, 0, fast }, { 'yellow', 1, 0, fast } }
  end
  if occ then return { { 'red', -1, 0 }, { 'red', 1, 0 } } end
  if main then return { { 'green', 0, 0 } } end
  return { { 'yellow', 0, 1, fast }, { 'yellow', 0, -1, fast } }
end

-- A signal's aspect for a train coming toward its turnout: 'red' (a vehicle in its zone but that train), 'green'
-- (the main line set), 'yellow' (a diverging route set). Pure.
function M.aspect(sw, cars, except)
  if not sw then return 'red' end
  if occupied(sw, cars or {}, except) then return 'red' end
  return M.current(sw) == ((sw.def or 0) + 1) and 'green' or 'yellow'
end

return M
