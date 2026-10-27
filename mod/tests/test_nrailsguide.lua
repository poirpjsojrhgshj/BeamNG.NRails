-- luajit mod/tests/test_nrailsguide.lua  (BeamNG.NRails: the rail guidance, the vehicle side (nrailsGuide) and the
-- game side's track round a vehicle (nrailsguide))
local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local VG = dofile(dir .. '/../beamng_earth/lua/vehicle/extensions/nrailsGuide.lua')
local G = require('beamngEarth/nrailsguide')

-- the nearest segment and the lateral offset (left of the line's way: positive)
do
  local ax, ay, nx, ny, lat = VG.nearest({ { 0, 0, 10, 0, 20, 0 } }, 5, 0.75)
  T.check(math.abs(ax - 5) < 1e-9 and math.abs(ay) < 1e-9 and math.abs(nx) < 1e-9 and math.abs(ny - 1) < 1e-9
    and math.abs(lat - 0.75) < 1e-9, 'guide: foot point, left normal, offset')
  local _, _, _, _, lat2 = VG.nearest({ { 20, 0, 10, 0, 0, 0 } }, 5, 0.75)
  T.check(math.abs(lat2 + 0.75) < 1e-9, 'guide: the line the other way: the offset the other sign')
  T.check(VG.nearest({ { 0, 0, 10, 0 } }, 5, 9) == nil, 'guide: nothing within reach')
  local _, _, _, _, lat3 = VG.nearest({ { 0, 0, 100, 0 }, { 0, 4.5, 100, 4.5 } }, 50, 3.6)
  T.check(math.abs(lat3 + 0.9) < 1e-9, 'guide: the nearest of two tracks')
end

-- the force: a spring and its damper toward the place, capped; the strength and the speed schedule
do
  local w = VG.gains(1, 0)
  local f = VG.force(5000, 0.005, 0, 1, 0)
  T.check(math.abs(w - 2 * math.pi * VG.F_MAX) < 1e-9 and math.abs(f + 5000 * w * w * 0.005) < 1e-6,
    'guide: the spring pulls back (full strength, standing)')
  T.check(VG.force(5000, 0, 1, 1, 0) < 0 and VG.force(5000, 0, -1, 1, 0) > 0, 'guide: the damper against the motion')
  local _, acc = VG.gains(1, 0)
  T.check(math.abs(VG.force(5000, 10, 0, 1, 0)) <= 5000 * acc + 1e-6, 'guide: capped')
  T.check(VG.force(5000, 0.1, 0.1, 0, 0) == 0, 'guide: strength 0: nothing')
  T.check(math.abs(VG.force(5000, 0.005, 0, 0.1, 0)) < 0.02 * math.abs(VG.force(5000, 0.005, 0, 1, 0)),
    'guide: low strength: negligible')
  T.check(math.abs(VG.schedule(0) - 1) < 1e-9 and math.abs(VG.schedule(VG.V0) - 0.5) < 1e-9
    and VG.schedule(200) == VG.G_MIN, 'guide: the speed schedule 1 / (1 + (v/V0)^2), floored')
  T.check(math.abs(VG.force(5000, 0.005, 0, 1, 40)) < math.abs(VG.force(5000, 0.005, 0, 1, 2)),
    'guide: lighter at speed')
  T.check(VG.hold(5000, 0.05, 0, 1) < 0 and VG.hold(5000, -0.05, 0, 1) == 0 and VG.hold(5000, 0.05, 0, 0.3) == 0,
    'guide: the vertical hold pulls down only, from HOLD_S')
  local _, _, _, _, _, z = VG.nearest({ { 0, 0, 1, 10, 0, 2 } }, 5, 0.5, 4, 3)
  T.check(math.abs(z - 1.5) < 1e-9, 'guide: the rail top at the foot (x, y, z lines)')
end

-- the wheels' places: the half track on their own side, an axle as one wheel on the centre line
do
  local t = VG.targets({ 0.74, -0.76, 0.75, -0.75, 0.05 })
  T.check(t[1] == 0.75 and t[2] == -0.75 and t[3] == 0.75 and t[4] == -0.75 and t[5] == 0, 'guide: places')
end

-- the game side: the track round a vehicle, a turnout's unset route left out, far tracks not sent
do
  local function row(x0, y0, x1, y1, step)
    local r, L = {}, math.sqrt((x1 - x0) ^ 2 + (y1 - y0) ^ 2)
    local k = math.max(1, math.floor(L / (step or 2)))
    for i = 0, k do r[#r + 1] = x0 + (x1 - x0) * i / k; r[#r + 1] = y0 + (y1 - y0) * i / k; r[#r + 1] = 0 end
    return r
  end
  local main = row(-200, 0, 200, 0)
  local branch = row(0, 0, 200, 20)
  local far = row(-200, 300, 200, 300)
  local sw = { at = { 0, 0 }, cur = 1, routes = { { line = { 0, 0, 40, 0 } }, { line = { 0, 0, 40, 4 } } } }
  local lines = G.lines({ main, branch, far }, { sw }, 10, 0)
  local onBranchZone = false
  for _, l in ipairs(lines) do
    for j = 1, #l - 2, 3 do
      local x, y = l[j], l[j + 1]
      if x > 8 and x < 38 and math.abs(y - x / 10) < 0.05 and y > 1 then onBranchZone = true end
    end
  end
  T.check(not onBranchZone, 'guide lines: the branch inside the turnout zone left out (set to the main line)')
  local hasFar = false
  for _, l in ipairs(lines) do if l[2] and l[2] > 250 then hasFar = true end end
  T.check(not hasFar, 'guide lines: a track 300 m away not sent')
  sw.cur = 2
  local lines2 = G.lines({ main, branch }, { sw }, 10, 0)
  local mainInZone = false
  for _, l in ipairs(lines2) do
    for j = 1, #l - 2, 3 do
      if l[j] > 12 and l[j] < 38 and math.abs(l[j + 1]) < 0.01 then mainInZone = true end
    end
  end
  T.check(not mainInZone, 'guide lines: set to the branch: the main line inside the zone left out')
  local lit = G.literal({ { 1, 2.5, 3, 4 } })
  T.check(lit == '{{1.00,2.50,3.00,4.00}}', 'guide: the lines as a Lua literal')
  local f = load('return ' .. lit)
  T.check(f and f()[1][2] == 2.5, 'guide: the literal reads back')
end

-- the map's railways (nrailsmap): the tracks in a box, a click's nearest track point
do
  local MAP = require('beamngEarth/nrailsmap')
  local rowA = { 0, 0, 0, 10, 0, 0, 20, 0, 0, 30, 0, 0, 40, 0, 0 }
  local c = MAP.clip({ rowA }, 5, -5, 35, 5, 2)
  T.check(#c == 1 and c[1][1] == 10 and c[1][#c[1] - 1] == 30, 'map: a track cut to the box')
  local x, y, d = MAP.nearestPoint({ rowA }, 12, 3, 40)
  T.check(math.abs(x - 12) < 1e-9 and math.abs(y) < 1e-9 and math.abs(d - 3) < 1e-9, 'map: a click snapped to the track')
  T.check(MAP.nearestPoint({ rowA }, 12, 90, 40) == nil, 'map: no track near the click')
end

-- a far destination: the reachable loaded node nearest to it (never reversing)
do
  local R = require('beamngEarth/nrailsroute')
  local function row(x0, y0, x1, y1)
    local r, L = {}, math.sqrt((x1 - x0) ^ 2 + (y1 - y0) ^ 2)
    local k = math.max(1, math.floor(L / 4))
    for i = 0, k do r[#r + 1] = x0 + (x1 - x0) * i / k; r[#r + 1] = y0 + (y1 - y0) * i / k; r[#r + 1] = 0 end
    return r
  end
  local g = R.graph({ row(0, 0, 400, 0), row(200, 0, 400, 60) })
  local path, left = R.findToward(g, 10, 0, 1, 0, 2000, 900)
  T.check(path ~= nil and path[#path][1] > 390 and path[#path][2] > 50, 'route toward: the branch heading to the far point')
  T.check(left and left < math.sqrt(1600 ^ 2 + 840 ^ 2) + 1, 'route toward: the distance left from its end')
  local back = R.findToward(g, 10, 0, 1, 0, -3000, 0)
  T.check(back == nil, 'route toward: never reversing to go the other way')
end

T.done('test_nrailsguide')
