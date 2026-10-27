-- BeamNG.NRails: the game side of the rail guidance (vehicle extension nrailsGuide.lua: the wheels held on the track,
-- the user's "bogies collees sur les voies"). Ctrl+Shift+B (or the keys window's button) turns it on / off, kept in
-- the prefs (nrailsui). While on, every SEND_S the player's train (its rail vehicles within CONSIST_M) gets the track
-- round each vehicle: the rail lines of the loaded tiles within REACH_M, the tracks that come within NEAR_M of the
-- vehicle only, and in a turnout's zone the routes it is not set to left out (a wheel follows the set route).
local M = {}

M.SEND_S = 0.4
M.REACH_M = 140           -- m of track sent round a vehicle
M.NEAR_M = 22             -- m: a track coming this close to the vehicle (half a long wagon and a turnout's spread)
M.CONSIST_M = 1200        -- m round the player the rail vehicles guided with it (a 750 m freight train whole)
M.ZONE_TOL_M = 0.35       -- m: a point this close to a route a turnout is not set to (and not to the set one): left out
M.STRENGTH = 0.6          -- the guidance's strength (0..1: the keys window's slider, the prefs' guideStrength)
M.on = false
M.sent = {}               -- [vehicle id] = true: guided

local N, switch
function M.init(nrails, sw)
  N, switch = nrails, sw
end

local function segDist(x, y, flat)
  local best = math.huge
  for i = 1, #flat - 3, 2 do
    local x1, y1, x2, y2 = flat[i], flat[i + 1], flat[i + 2], flat[i + 3]
    local dx, dy = x2 - x1, y2 - y1
    local L2 = dx * dx + dy * dy
    local t = L2 > 1e-9 and math.max(0, math.min(1, ((x - x1) * dx + (y - y1) * dy) / L2)) or 0
    local d = math.sqrt((x - x1 - t * dx) ^ 2 + (y - y1 - t * dy) ^ 2)
    if d < best then best = d end
  end
  return best
end
M._segDist = segDist

-- Pure: the guide lines round (px, py): rows (flat x, y, z, ...) of the tiles' rail lines, cut to REACH_M, kept when
-- they come within NEAR_M, the points on a turnout's unset routes (switches: {routes = {{line}}, cur}) left out.
-- Returns { {x1, y1, z1, x2, y2, z2, ...}, ... } (z: the rail top, for the vertical hold).
function M.lines(rows, switches, px, py)
  local out = {}
  local R2 = M.REACH_M * M.REACH_M
  local zones = {}
  for _, sw in ipairs(switches or {}) do
    local cur = sw.cur
    if cur and sw.routes and sw.routes[cur] and sw.at
        and (sw.at[1] - px) ^ 2 + (sw.at[2] - py) ^ 2 <= (M.REACH_M + 150) ^ 2 then
      for i, r in ipairs(sw.routes) do
        if i ~= cur and r.line then zones[#zones + 1] = { bad = r.line, good = sw.routes[cur].line } end
      end
    end
  end
  for _, row in ipairs(rows) do
    local piece = {}
    local function flush()
      if #piece >= 6 then out[#out + 1] = piece end
      piece = {}
    end
    for i = 1, #row - 2, 3 do
      local x, y = row[i], row[i + 1]
      local keep = (x - px) ^ 2 + (y - py) ^ 2 <= R2
      if keep then
        for _, z in ipairs(zones) do
          if segDist(x, y, z.bad) <= M.ZONE_TOL_M and segDist(x, y, z.good) > M.ZONE_TOL_M then keep = false; break end
        end
      end
      if keep then piece[#piece + 1] = x; piece[#piece + 1] = y; piece[#piece + 1] = row[i + 2] or 0 else flush() end
    end
    flush()
  end
  -- (the pieces of tracks that never come within NEAR_M: dropped)
  local kept = {}
  for _, p in ipairs(out) do
    local close = false
    local flat = {}
    for j = 1, #p - 2, 3 do
      flat[#flat + 1] = p[j]; flat[#flat + 1] = p[j + 1]
      if (p[j] - px) ^ 2 + (p[j + 1] - py) ^ 2 <= M.NEAR_M * M.NEAR_M then close = true end
    end
    if not close and #flat >= 4 then       -- (or a segment of it passes within NEAR_M)
      close = segDist(px, py, flat) <= M.NEAR_M
    end
    if close then kept[#kept + 1] = p end
  end
  return kept
end

-- Pure: the Lua literal of the lines (centimetres).
function M.literal(lines)
  local parts = {}
  for _, l in ipairs(lines) do
    local nums = {}
    for i = 1, #l do nums[i] = string.format('%.2f', l[i]) end
    parts[#parts + 1] = '{' .. table.concat(nums, ',') .. '}'
  end
  return '{' .. table.concat(parts, ',') .. '}'
end

M.SET_CMD = 'if not nrailsGuide then extensions.load("nrailsGuide") end if nrailsGuide then nrailsGuide.set(%s, %.2f, 3) end'
M.OFF_CMD = 'if nrailsGuide then nrailsGuide.off() end'

local function rowsOf(tiles)
  local rows = {}
  for _, t in pairs(tiles) do
    if t.railLines and not t.ghost then for _, r in ipairs(t.railLines) do rows[#rows + 1] = r end end
  end
  return rows
end

local function switchesOf(tiles)
  local out = {}
  local ok, _, list = pcall(switch.collect, tiles)
  if not ok then return out end
  for _, sw in ipairs(list or {}) do
    out[#out + 1] = { at = sw.at, routes = sw.routes, cur = switch.current(sw) }
  end
  return out
end

local last = -1
function M.update(now, tiles)
  now = now or os.clock()
  if now - last < M.SEND_S and now >= last then return end
  last = now
  local scene = N.scene(now)
  local player
  for _, r in ipairs(scene) do if r.player then player = r end end
  local want = {}
  if M.on and M.STRENGTH > 0 and player and player.rail then
    for _, r in ipairs(scene) do
      if r.rail and (r.x - player.x) ^ 2 + (r.y - player.y) ^ 2 <= M.CONSIST_M ^ 2 and r.id then want[r.id] = r end
    end
  end
  if next(want) then
    local rows, sws = rowsOf(tiles), switchesOf(tiles)
    for id, r in pairs(want) do
      local v = be and be.getObjectByID and be:getObjectByID(id)
      if v then
        local cmd = string.format(M.SET_CMD, M.literal(M.lines(rows, sws, r.x, r.y)), M.STRENGTH)
        pcall(function() v:queueLuaCommand(cmd) end)
        M.sent[id] = true
      end
    end
  end
  for id in pairs(M.sent) do
    if not want[id] then
      local v = be and be.getObjectByID and be:getObjectByID(id)
      if v then pcall(function() v:queueLuaCommand(M.OFF_CMD) end) end
      M.sent[id] = nil
    end
  end
end

-- The strength (0..1), sent with the next lines.
function M.setStrength(s)
  M.STRENGTH = math.max(0, math.min(1, tonumber(s) or M.STRENGTH))
  last = -1
  return M.STRENGTH
end

function M.toggle()
  M.on = not M.on
  last = -1
  return M.on
end

return M
