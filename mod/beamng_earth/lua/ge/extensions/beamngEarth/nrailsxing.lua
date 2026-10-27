-- BeamNG.NRails: the level crossings' barriers, lights and protection (the user, 2026-10-27: "creer des barrieres de
-- passages a niveau la ou il y en a dans la vraie vie ... signale en rouge tous les panneaux si presence de vehicules
-- ainsi qu'une protection (ex si vehicule n'a pas bouge depuis 30 s / 1 min, despawn vehicule)").
--
-- The crossings come with the road tiles ("railx_bars", server rails.crossing_bar: one row per road crossing, its
-- centre on the road, the road's direction and half width, the span of its tracks along the road). What stands there
-- comes from OpenStreetMap's level crossing node within MATCH_M (nrailsmap.xingsLocal: crossing:barrier half /
-- double_half / full / yes, crossing:light): booms, red lights, or the St Andrew's cross alone (no OSM node, or no
-- barrier nor light mapped).
--
-- A crossing closes when a rail vehicle comes (within CLOSE_M, or CLOSE_AHEAD_S at its speed, its line through the
-- crossing within LATERAL_M) or stands on it: the lights flash, LIGHTS_BEFORE_S later the booms come down in
-- BOOM_MOVE_S (France: "SAL 2/4", 7 s then ~8 s); it opens when no rail vehicle is within OPEN_PAST_M and none comes.
-- While closed: a road vehicle inside the crossing makes it "occupied" (the signals in front of it show red: M.blocked;
-- the driver told once); a road vehicle not ours to drive, standing still inside for STUCK_S, is removed (never the
-- player's, never another player's in multiplayer).
-- Drawn with the debug drawer (no collision: the booms never hold a car, as the slabs never hold a train).
local M = {}

M.CHECK_S = 0.25
-- The announcement (the user, 2026-10-27: "active-les comme c'est cense etre dans la vraie vie ... selon le type de
-- voie et la vitesse"): as a real crossing's announcement point is fixed, set for the fastest trains of the line, the
-- crossing closes when a train comes within ANNOUNCE_S of the LINE's speed (OSM's maxspeed of the track through it;
-- else LINE_KMH by its kind) of it, slower trains so closing it longer, as in real life; a train faster than that
-- (the player) at least ANNOUNCE_S of its own speed. Then the lights LIGHTS_BEFORE_S (France ~7-8 s, Switzerland 8 s)
-- and the booms BOOM_MOVE_S down: closed some 10 s before the fastest train arrives (Switzerland: 5 s at least).
M.ANNOUNCE_S = 25
M.ANNOUNCE_MIN_M = 150
M.LINE_KMH = { main = 120, branch = 90, light = 60, service = 40 }
M.CLOSE_M = 350           -- (no line speed known: this, or CLOSE_AHEAD_S of the train's speed)
M.CLOSE_AHEAD_S = 25
M.LATERAL_M = 30
M.OPEN_PAST_M = 30
M.LIGHTS_BEFORE_S = 7
M.BOOM_MOVE_S = 8
M.STUCK_S = 40
M.STUCK_SPEED = 0.5
M.ROAD_SCAN_S = 1.0
M.MATCH_M = 30
M.DRAW_M = 600
M.FLASH_S = 1.0
M.POST_OFF_M = 2.0        -- m from the tracks' platform to the barrier's post, along the road
M.PIVOT_H = 1.0
M.LAMP_H = 2.3
M.BLOCK_AHEAD_M = 1500    -- m before a crossing a signal shows red for it

local N, mapm
M.state = {}              -- key -> { b (0 up .. 1 down), closing, since, occupied, stuck = {id = t} }

function M.init(nrails, nrmap) N, mapm = nrails, nrmap end

-- Pure: the barrier kind of an OSM crossing tag ('half', 'double_half', 'full', 'yes', ...): 'half' | 'double' |
-- 'full' | nil (no booms); lights: whether red lights stand there.
function M.kind(barrier, light)
  local b = barrier
  local k = nil
  if b == 'half' or b == 'yes' then k = 'half'
  elseif b == 'double_half' then k = 'double'
  elseif b == 'full' or b == 'gate' then k = 'full' end
  local l = (light == 'yes') or (k ~= nil and light ~= 'no')
  return k, l
end

-- Pure: the OSM crossing nearest the row's centre within MATCH_M (xings: {x, y, barrier, light}).
function M.match(row, xings)
  local best, bd = nil, M.MATCH_M * M.MATCH_M
  for _, x in ipairs(xings or {}) do
    local d = (x[1] - row.at[1]) ^ 2 + (x[2] - row.at[2]) ^ 2
    if d < bd then best, bd = x, d end
  end
  return best
end

-- Pure: the announcement distance (m) of a crossing on a line of vmax km/h (nil: unknown).
function M.announce(vmax)
  if not vmax or vmax <= 0 then return M.CLOSE_M end
  return math.max(M.ANNOUNCE_MIN_M, vmax / 3.6 * M.ANNOUNCE_S)
end

-- Pure: does a rail vehicle {x, y, vx, vy, speed[, pts]} want the crossing (row; row.vmax: its line's speed) closed?
function M.wants(row, car)
  for _, q in ipairs(car.pts or {}) do            -- (any part of a long vehicle on it or near: held closed)
    if (row.at[1] - q[1]) ^ 2 + (row.at[2] - q[2]) ^ 2 <= M.OPEN_PAST_M * M.OPEN_PAST_M then return true end
  end
  local dx, dy = row.at[1] - car.x, row.at[2] - car.y
  local d = math.sqrt(dx * dx + dy * dy)
  if d <= M.OPEN_PAST_M then return true end
  local s = car.speed or 0
  if s < 0.5 or d > math.max(M.announce(row.vmax), s * M.CLOSE_AHEAD_S) then return false end
  local ux, uy = car.vx / s, car.vy / s
  local along = dx * ux + dy * uy
  if along <= 0 then return false end              -- (going away)
  return math.abs(dx * uy - dy * ux) <= M.LATERAL_M
end

-- Pure: is (x, y) inside the crossing (the road's width, the tracks' span and the posts)?
function M.inside(row, x, y)
  local dx, dy = x - row.at[1], y - row.at[2]
  local u = dx * row.rd[1] + dy * row.rd[2]
  local v = dx * row.rd[2] - dy * row.rd[1]
  return u >= row.d0 - 1 and u <= row.d1 + 1 and math.abs(v) <= (row.hw or 3) + 1.0
end

-- Pure: the booms of a crossing: { {post = {x, y}, dir = {x, y} (the arm's way when down), len}, ... }. Each road
-- end gets a boom on the right of the traffic coming to it (half), across the whole road (full), and a second one on
-- the other side for the traffic leaving (double).
function M.booms(row, kind)
  if not kind then return {} end
  local rx, ry = row.rd[1], row.rd[2]
  local hw = row.hw or 3
  local out = {}
  for _, s in ipairs({ -1, 1 }) do
    local u = s < 0 and (row.d0 - M.POST_OFF_M) or (row.d1 + M.POST_OFF_M)
    local cx, cy = row.at[1] + rx * u, row.at[2] + ry * u
    -- (traffic coming to this end drives -s * rd; its right side:)
    local mx, my = -s * rx, -s * ry
    local rgx, rgy = my, -mx
    local len = kind == 'full' and 2 * hw or hw
    out[#out + 1] = { post = { cx + rgx * (hw + 0.4), cy + rgy * (hw + 0.4) }, dir = { -rgx, -rgy }, len = len }
    if kind == 'double' then
      out[#out + 1] = { post = { cx - rgx * (hw + 0.4), cy - rgy * (hw + 0.4) }, dir = { rgx, rgy }, len = hw }
    end
  end
  return out
end

-- Pure: the posts of a crossing without booms (the St Andrew's cross and lights): one at each road end, right side.
function M.posts(row)
  local out = {}
  for _, b in ipairs(M.booms(row, 'half')) do out[#out + 1] = b end
  return out
end

local function key(row) return string.format('%d_%d', math.floor(row.at[1] + 0.5), math.floor(row.at[2] + 0.5)) end
M._key = key

-- The crossings in the loaded tiles, with what stands there (OSM): { {row, key, kind, lights}, ... }.
local listCache = { at = -1 }
function M.list(tiles, now)
  now = now or os.clock()
  if now - listCache.at < 2.0 and listCache.at >= 0 then return listCache.rows end
  local xings = mapm and mapm.xingsLocal and mapm.xingsLocal() or {}
  local out = {}
  for _, t in pairs(tiles or {}) do
    if t.railxBars and not t.ghost then
      for _, row in ipairs(t.railxBars) do
        if row.at and row.rd then
          local m = M.match(row, xings)
          local k, l = nil, false
          if m then k, l = M.kind(m[3], m[4]); row.vmax = tonumber(m[5]) end
          out[#out + 1] = { row = row, key = key(row), kind = k, lights = l, osm = m ~= nil }
        end
      end
    end
  end
  listCache = { at = now, rows = out }
  return out
end
function M._resetList() listCache = { at = -1 } end

-- Is a road vehicle the player's own or another player's (multiplayer)? Those are never removed.
local function protected(id, pid)
  if id == pid then return true end
  local mp = rawget(_G, 'MPVehicleGE')
  if mp and mp.isOwn then
    local ok, own = pcall(mp.isOwn, id)
    if ok and own == false then return true end
  end
  return false
end
M._protected = protected

local function removeVehicle(id)
  local v = be and be.getObjectByID and be:getObjectByID(id)
  if v then pcall(function() v:delete() end) end
end
M._remove = removeVehicle

-- The road vehicles (not rail ones) { id, x, y, speed }.
local function roadVehicles()
  local out = {}
  if not be or not be.getObjectCount then return out end
  for i = 0, be:getObjectCount() - 1 do
    local v = be:getObject(i)
    local ok, jb = pcall(function() return v:getJBeamFilename() end)
    if not (ok and N.isRailVehicle(jb)) then
      local okp, p = pcall(function() return v:getPosition() end)
      local okv, vel = pcall(function() return v:getVelocity() end)
      local okI, id = pcall(function() return v:getID() end)
      if okp and p and okI then
        local s = okv and vel and math.sqrt(vel.x * vel.x + vel.y * vel.y) or 0
        out[#out + 1] = { id = id, x = p.x, y = p.y, speed = s }
      end
    end
  end
  return out
end
M._roadVehicles = roadVehicles

-- One step (every CHECK_S): each crossing opened or closed, the booms moved, the occupied ones, the stuck removed.
local lastAt, lastRoad = nil, -100
function M.update(now, tiles, cars, roadFn)
  now = now or os.clock()
  local dt = lastAt and math.max(0, math.min(1, now - lastAt)) or 0
  lastAt = now
  cars = cars or (N.scene and N.scene()) or {}
  local list = M.list(tiles, now)
  local closingAny = false
  local seen = {}
  for _, c in ipairs(list) do
    local st = M.state[c.key]
    if not st then st = { b = 0, closing = false, since = now, stuck = {} }; M.state[c.key] = st end
    seen[c.key] = true
    local want = false
    for _, car in ipairs(cars) do
      if car.rail and M.wants(c.row, car) then want = true; break end
    end
    if want ~= st.closing then st.closing, st.since = want, now end
    if st.closing then
      closingAny = true
      if now - st.since >= M.LIGHTS_BEFORE_S then st.b = math.min(1, st.b + dt / M.BOOM_MOVE_S) end
    else
      st.b = math.max(0, st.b - dt / M.BOOM_MOVE_S)
      st.occupied, st.stuck = false, {}
    end
    c.st = st
  end
  for k in pairs(M.state) do if not seen[k] then M.state[k] = nil end end
  -- the road vehicles on the closed crossings (once a second, only while one is closing)
  if closingAny and now - lastRoad >= M.ROAD_SCAN_S then
    lastRoad = now
    local road = (roadFn or roadVehicles)()
    local pid = nil
    local pv = rawget(_G, 'getPlayerVehicle') and getPlayerVehicle(0)
    if pv then local ok, id = pcall(function() return pv:getID() end); pid = ok and id or nil end
    for _, c in ipairs(list) do
      local st = c.st
      if st.closing then
        local occ, ids = false, {}
        for _, v in ipairs(road) do
          if M.inside(c.row, v.x, v.y) then
            occ = true
            ids[v.id] = true
            if v.speed < M.STUCK_SPEED then
              st.stuck[v.id] = st.stuck[v.id] or now
              if now - st.stuck[v.id] >= M.STUCK_S and not protected(v.id, pid) then
                st.stuck[v.id] = nil
                M._remove(v.id)
                if N._setStatus then N._setStatus('NRails: vehicule immobilise sur un passage a niveau retire / '
                  .. 'stuck vehicle removed from a level crossing') end
              end
            else
              st.stuck[v.id] = nil
            end
          end
        end
        for id in pairs(st.stuck) do if not ids[id] then st.stuck[id] = nil end end
        if occ and not st.occupied and N._setStatus then
          N._setStatus('NRails: passage a niveau occupe ! signaux au rouge / level crossing occupied: signals red')
        end
        st.occupied = occ
      end
    end
  end
  M.last = list
  return list
end

-- Is an occupied crossing within BLOCK_AHEAD_M in front of (x, y) facing (fx, fy)? (the signals: red for it)
function M.blocked(x, y, fx, fy)
  for _, c in ipairs(M.last or {}) do
    if c.st and c.st.occupied then
      local dx, dy = c.row.at[1] - x, c.row.at[2] - y
      local along = dx * fx + dy * fy
      if along > 0 and along < M.BLOCK_AHEAD_M and math.abs(dx * fy - dy * fx) < M.LATERAL_M then return true end
    end
  end
  return false
end

-- ---------------------------------------------------------------------------------------------------- drawing
local function drawBoom(dd, CF, b, z, down, lights, flashOn, side)
  local px, py = b.post[1], b.post[2]
  pcall(function()
    dd:drawCylinder(vec3(px, py, z), vec3(px, py, z + M.LAMP_H + 0.3), 0.06, CF(0.75, 0.75, 0.75, 1))
  end)
  if b.len then
    local th = (1 - down) * math.pi / 2 * 0.97              -- (up: nearly vertical)
    local ax, ay, az = b.dir[1] * math.cos(th), b.dir[2] * math.cos(th), math.sin(th)
    local seg = 0.5
    local n = math.max(1, math.floor(b.len / seg + 0.5))
    for i = 0, n - 1 do
      local s0, s1 = i * b.len / n, (i + 1) * b.len / n
      local red = i % 2 == 0
      pcall(function()
        dd:drawCylinder(vec3(px + ax * s0, py + ay * s0, z + M.PIVOT_H + az * s0),
          vec3(px + ax * s1, py + ay * s1, z + M.PIVOT_H + az * s1), 0.045,
          red and CF(0.85, 0.05, 0.05, 1) or CF(0.95, 0.95, 0.95, 1))
      end)
    end
  end
  if lights then
    local on = flashOn
    local c = on and CF(1, 0.08, 0.05, 1) or CF(0.25, 0.03, 0.03, 1)
    pcall(function()
      dd:drawSphere(vec3(px, py, z + M.LAMP_H), 0.11, c)
      if on then dd:drawSphere(vec3(px, py, z + M.LAMP_H), 0.35, CF(1, 0.1, 0.05, 0.25)) end
    end)
  end
  -- the St Andrew's cross over the post (side: across the road)
  local sx, sy = side[1] * 0.45, side[2] * 0.45
  local zc = z + M.LAMP_H + 0.75
  pcall(function()
    dd:drawCylinder(vec3(px - sx, py - sy, zc - 0.3), vec3(px + sx, py + sy, zc + 0.3), 0.04, CF(0.95, 0.95, 0.95, 1))
    dd:drawCylinder(vec3(px - sx, py - sy, zc + 0.3), vec3(px + sx, py + sy, zc - 0.3), 0.04, CF(0.85, 0.05, 0.05, 1))
  end)
end

function M.draw(now, px, py)
  local dd = rawget(_G, 'debugDrawer')
  local CF = rawget(_G, 'ColorF')
  if not dd or not CF or not M.last then return end
  now = now or os.clock()
  for _, c in ipairs(M.last) do
    local row = c.row
    if not px or (row.at[1] - px) ^ 2 + (row.at[2] - py) ^ 2 < M.DRAW_M * M.DRAW_M then
      local st = c.st or { b = 0, closing = false, since = now }
      local flashOn = st.closing and ((now - st.since) % M.FLASH_S) < M.FLASH_S / 2
      local z = row.at[3] or 0
      local side = { row.rd[1], row.rd[2] }
      local list = c.kind and M.booms(row, c.kind) or M.posts(row)
      for _, b in ipairs(list) do
        if not c.kind then b = { post = b.post, dir = b.dir } end
        drawBoom(dd, CF, b, z, st.b, c.lights, flashOn, side)
      end
    end
  end
end

return M
