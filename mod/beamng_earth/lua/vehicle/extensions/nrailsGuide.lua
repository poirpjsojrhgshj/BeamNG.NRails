-- BeamNG.NRails: rail guidance (the user's run, 2026-10-26: "un mode pour rouler avec les bogies comme collees sur les
-- voies": the WLD FS30-2 swayed left and right on the track, the TEM2 almost not). The rail mods' wheels keep to the
-- track with a flange disc against the rails' collision only; their wheels have no coned tread, so nothing centres
-- them and a long, heavy vehicle hunts from one rail to the other. Guided, each wheel is pulled to its own place across
-- the track (where it stood when the guidance found the track: the wheels' half track) by a damped spring, an
-- invisible flange that never lets it rub: no sway, no climbing the rail in curves.
--
-- 1.2 (the user, 2026-10-27: "je n'ai pas vu de difference ... il faudrait reellement creer un slider de puissance de
-- guidage, au max les bogies ne se decollent pas des rails, au minimum il se desactive ou a un effet negligeable. Le
-- guidage ON avec le TEM2 semble empirer le roulage a basse vitesse ... peut-etre en 1/carre: a basse vitesse forte
-- connexion aux rails puis plus la vitesse augmente moins ca colle, une sorte de regulation d'oscillations"):
--   * a strength s in 0..1 (the game side's slider): the spring's frequency F_MIN..F_MAX Hz and its force cap
--     ACC_MIN..ACC_MAX m/s2 grow with s; s = 0 is off;
--   * scheduled with speed: the stiffness times g(v) = 1 / (1 + (v / V0)^2), never under G_MIN (the damping follows,
--     critically damped at every speed): held hard at a walk, a light hand at line speed (the yaw modes of a long
--     vehicle at speed are not excited by a stiff spring);
--   * the damper from the hubs' own velocity across the track (the nodes' velocities), no longer the offset's finite
--     difference at 2 kHz: that one jumped at every change of track segment (2 m polyline kinks) and shook a slow TEM2;
--   * from s >= HOLD_S a vertical hold: a wheel lifting off the rail top (over its height when calibrated) pulled
--     back down, never pushed up: at full strength the bogies do not leave the rails.
--
-- Vehicle Lua (an extension of the vehicle: extensions.load('nrailsGuide')). The game side (nrailsguide.lua) sends the
-- track round the train every few tenths of a second: the centre lines (flat x, y[, z] lists, world), the routes a
-- turnout is not set to already left out, so a wheel follows the set route. Per graphics frame each wheel's nearest
-- track segment is found; per physics step (onPhysicsStep, 2 kHz) the forces are applied to the wheel's two hub nodes.
-- A wheel further than MAX_ERR_M off its place is let go (a derailed train is not pulled back).
local M = {}

M.F_MIN, M.F_MAX = 0.4, 4.0       -- Hz: the spring at strength 0+ and 1 (at a standstill)
M.ACC_MIN, M.ACC_MAX = 0.5, 14.0  -- m/s2: the force cap on a wheel's share of the mass
M.V0 = 12.0                       -- m/s (43 km/h): the speed the stiffness is halved at
M.G_MIN = 0.2
M.ZETA = 1.2
M.HOLD_S = 0.5                    -- strength from which the vertical hold works
M.HOLD_HZ = 3.0
M.HOLD_SLACK_M = 0.015            -- m a wheel may rise over its calibrated height before it is held
M.MAX_ERR_M = 0.6                 -- m off its place a wheel is no longer guided
M.SEARCH_M = 4.0                  -- m round a wheel its track segment is looked for

M.on = false
M.strength = 0.6
M.calibrated = false
M.lines = {}              -- { {x1, y1[, z1], x2, y2[, z2], ...}, ... } world
M.stride = 2
M.wheels = {}             -- { {n1, n2, m, target, h0, ax, ay, az, nx, ny, ok} }

local abs, sqrt, min, max, pi = math.abs, math.sqrt, math.min, math.max, math.pi

-- Pure: the nearest segment of lines (points of `stride` numbers: x, y[, z]) to (x, y) within reach: foot point (ax,
-- ay), unit left normal (nx, ny), the signed lateral offset of (x, y) (positive to the left of the line's direction),
-- the rail top at the foot (z lines only). nil when none within reach.
function M.nearest(lines, x, y, reach, stride)
  stride = stride or 2
  local best, bax, bay, bnx, bny, blat, baz = (reach or M.SEARCH_M) ^ 2, nil, nil, nil, nil, nil, nil
  for _, l in ipairs(lines) do
    for i = 1, #l - 2 * stride + 1, stride do
      local x1, y1, x2, y2 = l[i], l[i + 1], l[i + stride], l[i + stride + 1]
      local dx, dy = x2 - x1, y2 - y1
      local L2 = dx * dx + dy * dy
      if L2 > 1e-9 then
        local t = ((x - x1) * dx + (y - y1) * dy) / L2
        t = t < 0 and 0 or (t > 1 and 1 or t)
        local fx, fy = x1 + t * dx, y1 + t * dy
        local d2 = (x - fx) ^ 2 + (y - fy) ^ 2
        if d2 < best then
          local L = sqrt(L2)
          local nx, ny = -dy / L, dx / L
          best, bax, bay, bnx, bny = d2, fx, fy, nx, ny
          blat = (x - fx) * nx + (y - fy) * ny
          baz = stride >= 3 and (l[i + 2] + t * (l[i + stride + 2] - l[i + 2])) or nil
        end
      end
    end
  end
  if not bax then return nil end
  return bax, bay, bnx, bny, blat, baz
end

-- Pure: the speed schedule g(v) (1 at a standstill, 1/2 at V0, G_MIN at least).
function M.schedule(v)
  return max(M.G_MIN, 1 / (1 + (v / M.V0) ^ 2))
end

-- Pure: the spring's angular frequency and the force cap (m/s2) at strength s and speed v.
function M.gains(s, v)
  if s <= 0 then return 0, 0 end
  s = min(1, s)
  local f = M.F_MIN + (M.F_MAX - M.F_MIN) * s * s
  local w = 2 * pi * f * sqrt(M.schedule(v or 0))
  return w, M.ACC_MIN + (M.ACC_MAX - M.ACC_MIN) * s
end

-- Pure: the guiding force (N, along the normal) on a wheel's share of the mass m: err its offset from its place (m),
-- verr its velocity across the track (m/s); s the strength, v the train's speed.
function M.force(m, err, verr, s, v)
  local w, acc = M.gains(s == nil and M.strength or s, v or 0)
  if w <= 0 then return 0 end
  local f = -(m * w * w * err + 2 * M.ZETA * m * w * verr)
  local cap = m * acc
  return max(-cap, min(cap, f))
end

-- Pure: the vertical hold (N, up positive: only ever down) on a wheel risen `rise` m over its calibrated height,
-- going up at vz m/s; 0 under HOLD_S.
function M.hold(m, rise, vz, s)
  s = s == nil and M.strength or s
  if s < M.HOLD_S or rise <= M.HOLD_SLACK_M then return 0 end
  local k = (s - M.HOLD_S) / (1 - M.HOLD_S)
  local w = 2 * pi * M.HOLD_HZ
  local f = -(m * w * w * (rise - M.HOLD_SLACK_M) + 2 * m * w * max(0, vz)) * k
  return max(-m * 9.81 * 1.5 * k, min(0, f))
end

-- Pure: each wheel's place across the track from the offsets found when the guidance starts: the wheels' half track
-- (the median of their |offsets|), on their own side; a wheel within 0.2 m of the centre line (a whole axle as one
-- wheel) is kept on the centre line.
function M.targets(lats)
  local a = {}
  for _, l in ipairs(lats) do if abs(l) >= 0.2 then a[#a + 1] = abs(l) end end
  table.sort(a)
  local half = #a > 0 and a[math.floor((#a + 1) / 2)] or 0
  local out = {}
  for i, l in ipairs(lats) do out[i] = abs(l) < 0.2 and 0 or (l < 0 and -half or half) end
  return out
end

local function vehicleWheels()
  local out = {}
  local data = rawget(_G, 'v') and v.data
  if not data or not data.wheels then return out end
  local total, n = 0, 0
  for _, nd in pairs(data.nodes or {}) do total = total + (nd.nodeWeight or 0) end
  for _, w in pairs(data.wheels) do
    if w.node1 and w.node2 then n = n + 1; out[#out + 1] = { n1 = w.node1, n2 = w.node2 } end
  end
  for _, w in ipairs(out) do w.m = (total > 0 and total or 20000) / math.max(n, 1) end
  return out
end

local function hub(w)
  local o = obj:getPosition()
  local a, b = obj:getNodePosition(w.n1), obj:getNodePosition(w.n2)
  return o.x + (a.x + b.x) / 2, o.y + (a.y + b.y) / 2, o.z + (a.z + b.z) / 2
end

-- The hub's velocity (world): the nodes' own (obj:getNodeVelocityVector), else nil.
local function hubVel(w)
  if not obj.getNodeVelocityVector then return nil end
  local ok, a = pcall(obj.getNodeVelocityVector, obj, w.n1)
  local ok2, b = pcall(obj.getNodeVelocityVector, obj, w.n2)
  if not ok or not ok2 or not a or not b then return nil end
  return (a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2
end

-- The game side: the track round the train (see above), the strength (0..1), the lines' stride (3: x, y, z).
function M.set(lines, strength, stride)
  M.lines = lines or {}
  M.stride = stride or 2
  if strength ~= nil then M.strength = max(0, min(1, strength)) end
  if not M.on then
    M.on = true
    M.wheels = vehicleWheels()
    M.calibrated = false
  end
end

function M.off()
  M.on, M.lines, M.wheels, M.calibrated = false, {}, {}, false
end

local speed = 0
function M.updateGFX(dt)
  if not M.on or not M.lines[1] or not M.wheels[1] then return end
  local okv, vel = pcall(obj.getVelocity, obj)
  speed = okv and vel and sqrt(vel.x * vel.x + vel.y * vel.y) or 0
  local lats, found, heights = {}, 0, {}
  for i, w in ipairs(M.wheels) do
    local x, y, z = hub(w)
    local ax, ay, nx, ny, lat, az = M.nearest(M.lines, x, y, M.SEARCH_M, M.stride)
    w.ok = ax ~= nil
    if w.ok then
      w.ax, w.ay, w.az, w.nx, w.ny = ax, ay, az, nx, ny
      found = found + 1
      if az then heights[i] = z - az end
    end
    lats[i] = lat or 0
  end
  if not M.calibrated and found == #M.wheels then   -- (the wheels' places: where they stand on the track now)
    local t = M.targets(lats)
    for i, w in ipairs(M.wheels) do w.target = t[i]; w.h0 = heights[i]; w.prevErr = nil end
    M.calibrated = true
  end
end

function M.onPhysicsStep(dt)
  if not M.on or not M.calibrated or M.strength <= 0 then return end
  for _, w in ipairs(M.wheels) do
    if w.ok and w.target then
      local x, y, z = hub(w)
      local lat = (x - w.ax) * w.nx + (y - w.ay) * w.ny
      -- (its place on the side it is on: the lines of two tiles may run opposite ways, a signed place would flip)
      local err = lat - (lat < 0 and -abs(w.target) or abs(w.target))
      if abs(err) <= M.MAX_ERR_M then
        local vx, vy, vz = hubVel(w)
        local verr
        if vx then
          verr = vx * w.nx + vy * w.ny
        else                                     -- (no node velocities: the offset's rate, smoothed)
          local raw = w.prevErr and (err - w.prevErr) / max(dt, 1e-4) or 0
          w.verr = (w.verr or 0) + (raw - (w.verr or 0)) * min(1, dt / 0.02)
          verr = w.verr
        end
        w.prevErr = err
        local f = M.force(w.m, err, verr, M.strength, speed) / 2
        local fz = 0
        if w.h0 and w.az then fz = M.hold(w.m, (z - w.az) - w.h0, vz or 0, M.strength) / 2 end
        local fv = vec3(w.nx * f, w.ny * f, fz)
        obj:applyForceVector(w.n1, fv)
        obj:applyForceVector(w.n2, fv)
      else
        w.prevErr, w.verr = nil, nil
      end
    end
  end
end

function M.onReset()
  M.calibrated = false
  for _, w in ipairs(M.wheels) do w.prevErr, w.verr = nil, nil end
end

return M
