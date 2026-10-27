-- BeamNG.NRails: the train's driving aids, the vehicle side (the user, 2026-10-27: "des systemes dans les trains plus
-- fideles a la vraie vie (regulateurs de vitesse, etc)"). Loaded on the player's rail vehicle by the game side
-- (nrailsdrive.lua):
--   * the speed regulator ("regulateur de vitesse", the cruise control of a locomotive): a PI on the speed error,
--     throttle up to THR_MAX, the service brake when too fast by more than BRAKE_OVER_MS;
--   * the speed control ("controle de vitesse", after the French KVB: "Controle de Vitesse par Balises"): the next
--     restriction ahead (a speed, at a distance: the signals' aspects, from the game side) gives a braking curve
--     v(d) = sqrt(vt^2 + 2 * DECEL * d); over it by WARN_MS: the alarm; by TRIP_MS: the emergency brake, held to a
--     stop or until back under the curve (as the real KVB: "freinage d'urgence").
-- Like the autopilot of an airliner, the aids only ever move the controls the driver has (throttle, brake), and
-- the regulator drops out on any brake from the driver ("disconnect").
local M = {}

M.KP, M.KI = 0.35, 0.06           -- throttle per m/s of error, per m/s.s
M.THR_MAX = 0.85
M.BRAKE_OVER_MS = 1.5             -- m/s over the set speed: the brake (the regulator's)
M.BRAKE_GAIN = 0.25               -- brake per m/s over
M.DECEL = 0.6                     -- m/s2: the braking curve's deceleration (a service brake, freight: 0.4-0.6)
M.MARGIN_M = 30                   -- m short of the restriction the curve aims at
M.WARN_MS = 5 / 3.6
M.TRIP_MS = 10 / 3.6

M.reg = nil                       -- the regulator's set speed (m/s), nil: off
M.limit = nil                     -- { v = m/s, d = m (at the time it came), at = the odometer then }
M.state = { alarm = false, trip = false, allowed = nil }

local integ, odo = 0, 0
local min, max, sqrt = math.min, math.max, math.sqrt

-- Pure: the speed allowed d m short of a restriction to vt (m/s).
function M.curve(vt, d, decel)
  return sqrt(vt * vt + 2 * (decel or M.DECEL) * max(0, d - M.MARGIN_M))
end

-- Pure: the regulator's controls (throttle, brake) for speed v (m/s), the set speed vs, the integral (returned).
function M.regulate(v, vs, i, dt)
  local e = vs - v
  i = max(-2, min(2 / M.KI, i + e * dt))
  local thr = max(0, min(M.THR_MAX, M.KP * e + M.KI * i))
  local brk = 0
  if e < -M.BRAKE_OVER_MS then brk = min(1, M.BRAKE_GAIN * (-e - M.BRAKE_OVER_MS)); thr = 0; i = min(i, 0) end
  return thr, brk, i
end

-- Pure: the speed control's verdict for speed v under the limit {v, d (left)}: allowed, alarm, trip.
function M.control(v, lim)
  if not lim then return nil, false, false end
  local allowed = M.curve(lim.v, lim.d)
  return allowed, v > allowed + M.WARN_MS, v > allowed + M.TRIP_MS
end

function M.setReg(kmh)
  if kmh == nil or kmh <= 0 then M.reg = nil else M.reg = kmh / 3.6 end
  integ = 0
end

function M.setLimit(kmh, d)
  if kmh == nil then M.limit = nil; return end
  M.limit = { v = kmh / 3.6, d = d, odo = odo }
end

local function speed()
  local ok, v = pcall(obj.getVelocity, obj)
  if not ok or not v then return 0 end
  return sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
end

local function driverBrake()
  local e = rawget(_G, 'electrics')
  local i = rawget(_G, 'input')
  local b = i and i.state and i.state.brake and i.state.brake.val
  return (b or 0) > 0.15 and not M._ourBrake
end

local function setInput(name, val)
  local i = rawget(_G, 'input')
  if i and i.event then pcall(i.event, name, val, 2) end
end

function M.updateGFX(dt)
  local v = speed()
  odo = odo + v * dt
  local thr, brk = nil, nil
  if M.reg then
    if driverBrake() then
      M.reg = nil
      setInput('throttle', 0)
    else
      thr, brk, integ = M.regulate(v, M.reg, integ, dt)
      if brk == 0 and not M._ourBrake then brk = nil end   -- (the driver's brake left alone)
    end
  end
  local lim = M.limit
  local st = M.state
  if lim then
    local left = lim.d - (odo - lim.odo)
    local allowed, alarm, trip = M.control(v, { v = lim.v, d = left })
    st.allowed, st.alarm = allowed, alarm
    if trip then st.trip = true end
    if st.trip and (v < 0.3 or not alarm) then st.trip = false end
    if left < -50 then M.limit = nil end              -- (past it: the next one comes from the game side)
  else
    st.allowed, st.alarm, st.trip = nil, false, false
  end
  if st.trip then
    thr, brk = 0, 1
    M.reg = nil
  end
  -- (the controls let go once when the aids stop: a regulator switched off leaves no throttle open, a released
  -- emergency brake no brake on)
  if thr == nil and M._wroteThr then thr = 0; M._wroteThr = false elseif thr ~= nil then M._wroteThr = true end
  if brk == nil and M._wroteBrk then brk = 0; M._wroteBrk = false elseif brk ~= nil then M._wroteBrk = true end
  if thr ~= nil then setInput('throttle', thr) end
  if brk ~= nil then
    M._ourBrake = brk > 0
    setInput('brake', brk)
  end
  st.v, st.reg = v, M.reg
end

-- What the game side shows (obj:queueGameEngineLua answer): the state as a Lua literal.
function M.report(cb)
  local st = M.state
  local s = string.format('{v=%.2f,reg=%s,allowed=%s,alarm=%s,trip=%s}', st.v or 0,
    M.reg and string.format('%.2f', M.reg) or 'nil', st.allowed and string.format('%.2f', st.allowed) or 'nil',
    tostring(st.alarm == true), tostring(st.trip == true))
  if obj.queueGameEngineLua then
    obj:queueGameEngineLua(string.format('if beamngEarth_core and beamngEarth_core.nrails and beamngEarth_core.nrails.drive then beamngEarth_core.nrails.drive.onReport(%d, %s) end', obj:getID(), s))
  end
  return s
end

function M.onReset()
  M.reg, M.limit, integ = nil, nil, 0
  M.state = { alarm = false, trip = false }
end

return M
