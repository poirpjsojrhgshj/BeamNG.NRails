-- BeamNG.EarthNRails: the load guard (the user, 2026-10-24: "a chaque fois que la map charge des elements, montre
-- l'operation de chargement dans un ecran gris comme quand on se teleporte"). While driving, the car can reach road /
-- rail tiles whose colliders are not made yet (the server or the mod's queue behind: a fast train, a motorway): it
-- drove onto bare terrain or through a viaduct that was not there. The guard looks ahead along the car's path; when a
-- point within the next LEAD_S of driving (HOLD_MIN_M at least) is not ready (roads.readyAround: the tiles in, their
-- colliders made and solid), the game is held (simhold.lua: the game's pause; in BeamMP our car only) under a grey
-- screen with the loading line, until the path is ready RELEASE_S ahead (at the speed it had), at most MAX_S.
-- Never over the mod's own holds and loads (a teleport, the drop hold): those have their own screen.
-- step() is pure (mod/tests/test_nrails.lua); update() / draw() do the engine calls.
local M = {}

M.ENABLED = true
M.MIN_SPEED = 3         -- m/s: slower, nothing is held (parking, walking pace)
M.LEAD_S = 3            -- s of driving checked before holding
M.HOLD_MIN_M = 60       -- m ahead checked at least
M.RELEASE_S = 8         -- s of driving ready ahead to let go
M.RELEASE_MIN_M = 180
M.STEP_M = 40           -- m between the points checked
M.RADIUS_M = 30         -- m round each point
M.MAX_S = 45            -- a hold lasts at most this long (a tile that cannot be built)
M.MAX_SPEED = 100       -- m/s (360 km/h) the path ahead is measured at, at most
M.JUMP_SPEED = 200      -- m/s: faster is a vehicle being placed (a teleport, Snap to rail), not driving: no hold
M.COOLDOWN_S = 4        -- s after a hold before another
M.CHECK_S = 0.25
M.BACK_RGBA = { 0.42, 0.43, 0.45, 0.94 }
M.TEXT_RGBA = { 1, 1, 1, 1 }

-- Pure: the points (x, y) of the path ahead, every STEP_M up to dist (the car's own point first).
function M.ahead(x, y, dx, dy, dist)
  local out = { { x, y } }
  local n = math.max(1, math.ceil(dist / M.STEP_M))
  for i = 1, n do
    local d = math.min(dist, i * M.STEP_M)
    out[#out + 1] = { x + dx * d, y + dy * d }
  end
  return out
end

-- Pure: are all the points ready? (ready(x, y) -> bool)
function M.allReady(pts, ready)
  for _, p in ipairs(pts) do if not ready(p[1], p[2]) then return false end end
  return true
end

-- Pure: one decision. s: the guard's state { holding, since, speed, dx, dy, lastEnd }; car: { x, y, vx, vy } or nil;
-- busy: another hold or load of the mod is on; ready(x, y). Returns 'hold' | 'release' | nil.
function M.step(s, now, car, busy, ready)
  if s.holding then
    if not car then return 'release' end
    if now - s.since > M.MAX_S then return 'release' end
    local dist = math.max(M.RELEASE_MIN_M, (s.speed or 0) * M.RELEASE_S)
    if M.allReady(M.ahead(car.x, car.y, s.dx or 0, s.dy or 0, dist), ready) then return 'release' end
    return nil
  end
  if not M.ENABLED or busy or not car then return nil end
  if s.lastEnd and now - s.lastEnd < M.COOLDOWN_S then return nil end
  local v = math.sqrt(car.vx * car.vx + car.vy * car.vy)
  if v < M.MIN_SPEED then return nil end
  -- (a vehicle just placed (Snap to rail, a teleport) reports a velocity of the jump: 3 100 000 km/h held the game
  -- 21-45 s for thousands of km "ahead", the user's run 2026-10-25; no train or car goes that fast)
  if v > M.JUMP_SPEED then return nil end
  local dx, dy = car.vx / v, car.vy / v
  v = math.min(v, M.MAX_SPEED)
  local dist = math.max(M.HOLD_MIN_M, v * M.LEAD_S)
  if M.allReady(M.ahead(car.x, car.y, dx, dy, dist), ready) then return nil end
  s.speed, s.dx, s.dy = v, dx, dy
  return 'hold'
end

local state = { holding = false }
local since = math.huge
local pausedByUs = false
M.holds = 0

local function u32(im, c) return im.GetColorU32(im.ImVec4(c[1], c[2], c[3], c[4])) end

-- The grey screen with its line (imgui background draw list: over the 3D view, under imgui windows).
function M.draw(text)
  local im = rawget(_G, 'ui_imgui')
  if not im or not im.GetMainViewport then return false end
  local ok = pcall(function()
    local vp = im.GetMainViewport()
    local dl = im.GetBackgroundDrawList1()
    local a = im.ImVec2(vp.Pos.x, vp.Pos.y)
    local b = im.ImVec2(vp.Pos.x + vp.Size.x, vp.Pos.y + vp.Size.y)
    im.ImDrawList_AddRectFilled(dl, a, b, u32(im, M.BACK_RGBA), 0)
    local ts = im.CalcTextSize(text)
    local p = im.ImVec2(vp.Pos.x + (vp.Size.x - ts.x) / 2, vp.Pos.y + (vp.Size.y - ts.y) / 2)
    im.ImDrawList_AddText1(dl, p, u32(im, M.TEXT_RGBA), text, nil)
  end)
  return ok
end

-- Each frame (nrails.lua through roads.ext.update). opts: { anchor() -> anchor id, busy() -> bool, ready(aid, x, y,
-- r) -> bool, now() }.
local lastNow = nil
local function wallClock() return (os.clockhp and os.clockhp()) or os.clock() end

function M.update(dt, opts)
  local now = opts.now and opts.now() or wallClock()
  dt = dt or (lastNow and (now - lastNow)) or 0
  lastNow = now
  if state.holding then
    local secs = math.floor(now - state.since)
    M.draw(string.format('Chargement du terrain, des routes et des voies devant vous...  %d s', secs))
  end
  since = since + (dt or 0)
  if since < M.CHECK_S then return end
  since = 0
  local aid = opts.anchor and opts.anchor()
  local car
  local veh = rawget(_G, 'getPlayerVehicle') and getPlayerVehicle(0)
  if veh and aid then
    local p = veh:getPosition()
    local v = veh.getVelocity and veh:getVelocity() or { x = 0, y = 0 }
    car = { x = p.x, y = p.y, vx = v.x or 0, vy = v.y or 0 }
  end
  local simhold = require('beamngEarth/simhold')
  local busy = (opts.busy and opts.busy()) or (simhold.paused() and not pausedByUs)
  local act = M.step(state, now, car, busy, function(x, y) return opts.ready(aid, x, y, M.RADIUS_M) end)
  if act == 'hold' then
    state.holding, state.since = true, now
    M.holds = M.holds + 1
    if not simhold.paused() then simhold.pause(true); pausedByUs = true end
    if log then log('I', 'beamngEarth', string.format('nrails load guard: held at %.0f km/h, the path ahead not loaded',
      (state.speed or 0) * 3.6)) end
  elseif act == 'release' then
    state.holding, state.lastEnd = false, now
    if pausedByUs then simhold.pause(false); pausedByUs = false end
    if log then log('I', 'beamngEarth', string.format('nrails load guard: let go after %.1f s', now - (state.since or now))) end
  end
end

function M.state() return state end
function M.reset()
  if pausedByUs then pcall(function() require('beamngEarth/simhold').pause(false) end) end
  state, pausedByUs = { holding = false }, false
end

return M
