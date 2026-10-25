-- BeamNG.EarthNRails: the turnouts (the user's run, 2026-10-25: "je ne sais pas comment on se dirige sur les
-- aiguillages ... une chance sur le nombre de voies qu'un bogie aille sur la mauvaise voie"). The server gives each
-- road tile its turnouts (data.railsw: id, at, dir (the way the routes leave), def (the straight route), routes: what
-- (its collision shape "railswN" in this tile, or nil), side (+ left), line (its zone's centre line, flat x, y)): each
-- route's rails in the switch zone are a shape of their own; only the set route's is solid.
--   * The player sets the NEXT turnout ahead with the keys (left / straight / right): the choice waits until a
--     turnout is ahead within FACING_M on the line the vehicle runs on, is applied to it and used up.
--   * A turnout run through from one of its routes (trailing) is set to that route.
--   * Otherwise a turnout keeps its state (at first its straight route).
-- step() is pure (mod/tests/test_nrails.lua).
local M = {}

M.FACING_M = 600        -- m ahead a turnout takes the player's choice
M.LATERAL_M = 6         -- m from the turnout's axis (behind it) the vehicle may be
M.TRAIL_M = 120         -- m past the node a vehicle on a route sets the turnout to it (coming back)
M.ON_ROUTE_M = 2.0      -- m from a route's line the vehicle is on it
M.MIN_SPEED = 0.5       -- m/s

M.state = {}            -- id -> route index (1-based)
M.pending = nil         -- 'left' | 'straight' | 'right'

-- The route index for a choice among the routes (sorted left to right by the server).
function M.pick(sw, choice)
  local n = #sw.routes
  if n == 0 then return nil end
  if choice == 'left' then return 1 end
  if choice == 'right' then return n end
  return (sw.def or 0) + 1
end

function M.current(sw)
  return M.state[sw.id] or ((sw.def or 0) + 1)
end

local function distToLine(x, y, flat)
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
  if #flat == 2 then best = math.sqrt((x - flat[1]) ^ 2 + (y - flat[2]) ^ 2) end
  return best
end
M._distToLine = distToLine

-- Pure: the changes to make for vehicle car {x, y, vx, vy} among the turnouts (a list of rows, each id once):
-- returns { [id] = route index } (only those that change) and whether the pending choice was used.
function M.step(switches, car)
  local changes, used = {}, false
  if not car then return changes, used end
  local v = math.sqrt(car.vx * car.vx + car.vy * car.vy)
  local facing, fdist = nil, math.huge
  for _, sw in ipairs(switches) do
    local rx, ry = car.x - sw.at[1], car.y - sw.at[2]
    local along = rx * sw.dir[1] + ry * sw.dir[2]
    local lateral = math.abs(rx * sw.dir[2] - ry * sw.dir[1])
    local vel = (car.vx * sw.dir[1] + car.vy * sw.dir[2])
    if along < 0 and -along <= M.FACING_M and lateral <= M.LATERAL_M and v >= M.MIN_SPEED and vel > 0 then
      if -along < fdist then facing, fdist = sw, -along end
    elseif along > 0 and along <= M.TRAIL_M and v >= M.MIN_SPEED and vel < 0 then
      -- coming back through it from one of its routes: that route (the one it is on, clearly)
      local best, bd, second = nil, math.huge, math.huge
      for i, r in ipairs(sw.routes) do
        local d = distToLine(car.x, car.y, r.line or {})
        if d < bd then best, second, bd = i, bd, d elseif d < second then second = d end
      end
      if best and bd <= M.ON_ROUTE_M and second - bd >= 1.0 and M.current(sw) ~= best then changes[sw.id] = best end
    end
  end
  if facing and M.pending then
    local want = M.pick(facing, M.pending)
    if want and want ~= M.current(facing) then changes[facing.id] = want end
    used = true
  end
  return changes, used
end

-- The turnouts of the tiles (roads.extTiles), each once: { id -> row }.
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

return M
