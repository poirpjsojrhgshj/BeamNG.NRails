-- luajit mod/tests/test_nrailsdrive.lua  (BeamNG.NRails: the driving aids (nrailsdrive / the vehicle's nrailsDrive)
-- and the train configurator)
local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local D = require('beamngEarth/nrailsdrive')
local VD = dofile(dir .. '/../beamng_earth/lua/vehicle/extensions/nrailsDrive.lua')

-- the aspects of the signals' lamps and the restrictions they make
do
  T.check(D.aspect({ { 'red', -1, 0, false }, { 'red', 1, 0, false } }) == 'stop', 'drive: carre: stop')
  T.check(D.aspect({ { 'yellow', 0, 1, false }, { 'yellow', 0, -1, false } }) == 'rr30', 'drive: RR30')
  T.check(D.aspect({ { 'yellow', 0, 1, true }, { 'yellow', 0, -1, true } }) == 'rr60', 'drive: RR60 (flashing)')
  T.check(D.aspect({ { 'yellow', -1, 0, false }, { 'yellow', 1, 0, false } }) == 'r30', 'drive: R30')
  T.check(D.aspect({ { 'yellow', 0, 0, false } }) == 'warn' and D.aspect({ { 'green', 0, 0 } }) == 'clear',
    'drive: avertissement, clear')
  local k, d = D.restrictionOf('warn', 100)
  T.check(k == 0 and d == 100 + D.NEXT_M, 'drive: an advance signal: the stop at the next one')
  T.check(D.restrictionOf('clear', 100) == nil, 'drive: clear: none')
  local r = D.mostRestrictive({ { 60, 200 }, { 0, 1500 }, { 30, 400 } })
  T.check(r[1] == 60, 'drive: the lowest speed allowed now (60 in 200 m before 30 in 400 m)')
end

-- the track ahead along rows (a tile seam: two rows), the distance along it of a signal
do
  local function row(x0, x1, y)
    local r = {}
    for x = x0, x1, 10 do r[#r + 1] = x; r[#r + 1] = y or 0; r[#r + 1] = 0 end
    return r
  end
  local rows = { row(0, 500), row(500, 1000), row(1000, 500, 40) }
  local line = D.ahead(rows, 100, 0, 1, 0, 800)
  T.check(#line > 10 and line[#line - 1] >= 890, 'drive: the track ahead across a seam')
  local back = D.ahead(rows, 100, 0, -1, 0, 800)
  T.check(back[#back - 1] == 0, 'drive: the other way: to the end')
  local s, off = D.along(line, 700, 3)
  T.check(s and math.abs(s - 600) < 1e-6 and math.abs(off - 3) < 1e-6, 'drive: a signal 600 m ahead, 3 m off')
  T.check(D.along(line, 700, 40) == nil, 'drive: a signal of the parallel track is not ours')
  local x, y, dx = D.pointAt(line, 250)
  T.check(math.abs(x - 350) < 1e-6 and y == 0 and dx == 1, 'drive: a point along the line')
end

-- the configurator: country, norms, stopping distances
do
  T.check(D.country(47.5, 6.9) == 'FR' and D.country(47.4, 8.0) == 'CH' and D.country(52.5, 13.4) == 'DE'
    and D.country(40.7, -74) == 'US' and D.country(55.7, 37.6) == 'RU' and D.country(48.86, 2.35) == 'FR'
    and D.country(46.2, 6.14) == 'CH' and D.country(50.85, 4.35) == 'EU' and D.country(51.5, -0.1) == 'GB'
    , 'cfg: countries')
  local list = { { jb = 'tem2', len = 17, mass = 120000 } }
  for _ = 1, 40 do list[#list + 1] = { jb = 'tank', len = 19, mass = 80000 } end
  local s = D.summary(list, 'freight', 'FR')
  T.check(s.n == 41 and s.locos == 1 and s.len > 750 and s.over and s.max == 750, 'cfg: 41 vehicles, too long for FR')
  T.check(math.abs(s.mass - 3320000) < 1, 'cfg: the mass')
  T.check(not D.summary(list, 'freight', 'US').over, 'cfg: no limit in the US')
  local a, b = D.stopping(100 / 3.6, 'freight', 750), D.stopping(100 / 3.6, 'passenger', 200)
  T.check(a > b and a > 800 and a < 1200 and b > 400 and b < 700, 'cfg: stopping distances, freight longer')
end

-- the vehicle side: the regulator and the speed control's curve
do
  local thr, brk, i = VD.regulate(10, 20, 0, 0.1)
  T.check(thr > 0 and brk == 0, 'reg: too slow: throttle')
  thr, brk = VD.regulate(25, 20, 0, 0.1)
  T.check(thr == 0 and brk > 0, 'reg: too fast: brake')
  thr, brk = VD.regulate(20.5, 20, 0, 0.1)
  T.check(thr == 0 and brk == 0, 'reg: a little over: coasting')
  T.check(math.abs(VD.curve(0, VD.MARGIN_M) - 0) < 1e-9 and VD.curve(0, 1000) > 30, 'kvb: the braking curve')
  local allowed, alarm, trip = VD.control(30, { v = 0, d = 200 })
  T.check(allowed < 20 and alarm and trip, 'kvb: 108 km/h 200 m before a stop: emergency')
  allowed, alarm, trip = VD.control(10, { v = 30 / 3.6, d = 1000 })
  T.check(not alarm and not trip, 'kvb: under the curve: nothing')
end

T.done('test_nrailsdrive')
