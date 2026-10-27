-- luajit mod/tests/test_nrailsxing.lua  (BeamNG.NRails: the level crossings' barriers and protection (nrailsxing), the
-- map's OpenStreetMap railways (nrailsmap))
local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local X = require('beamngEarth/nrailsxing')
local MAP = require('beamngEarth/nrailsmap')

-- a road along y crossing two tracks along x at y = 0 and y = 4.5
local row = { at = { 0, 2.25, 100 }, rd = { 0, 1 }, hw = 3.5, d0 = -4.5, d1 = 4.5, tr = { 1, 0 }, z = 100.25 }

do
  T.check(X.kind('half', 'yes') == 'half' and X.kind('double_half') == 'double' and X.kind('full') == 'full',
    'xing: barrier kinds')
  local k, l = X.kind(nil, 'yes')
  T.check(k == nil and l == true, 'xing: lights without booms')
  k, l = X.kind('no', 'no')
  T.check(k == nil and l == false, 'xing: nothing but the cross')
  local m = X.match(row, { { 500, 0, 'full' }, { 3, 2, 'half', 'yes' } })
  T.check(m and m[3] == 'half', 'xing: the OSM node nearest')
  T.check(X.match(row, { { 100, 0, 'half' } }) == nil, 'xing: none within reach')
end

do
  local coming = { x = -300, y = 0, vx = 20, vy = 0, speed = 20, rail = true }
  T.check(X.wants(row, coming), 'xing: a train coming closes it')
  T.check(not X.wants(row, { x = -300, y = 0, vx = -20, vy = 0, speed = 20 }), 'xing: a train going away does not')
  T.check(not X.wants(row, { x = -300, y = 200, vx = 20, vy = 0, speed = 20 }), 'xing: a train on another line does not')
  T.check(X.wants(row, { x = -10, y = 0, vx = 0, vy = 0, speed = 0 }), 'xing: a train standing on it holds it')
  T.check(not X.wants(row, { x = -1000, y = 0, vx = 5, vy = 0, speed = 5 }), 'xing: a slow train far: not yet')
  local fast = { at = row.at, rd = row.rd, hw = row.hw, d0 = row.d0, d1 = row.d1, vmax = 160 }
  T.check(math.abs(X.announce(160) - 160 / 3.6 * X.ANNOUNCE_S) < 1e-9 and X.announce(20) == X.ANNOUNCE_MIN_M,
    'xing: the announcement from the line speed')
  T.check(X.wants(fast, { x = -1000, y = 0, vx = 5, vy = 0, speed = 5 }), 'xing: a 160 km/h line: closed 1.1 km ahead even for a slow train')
  T.check(X.wants(row, { x = -900, y = 0, vx = 40, vy = 0, speed = 40 }), 'xing: a fast train far: already')
end

do
  T.check(X.inside(row, 1, 2) and X.inside(row, -3.9, -1.5), 'xing: on the crossing')
  T.check(not X.inside(row, 8, 2) and not X.inside(row, 0, 30), 'xing: off the crossing')
  local b = X.booms(row, 'half')
  T.check(#b == 2, 'xing: a half boom at each end')
  -- the end at y < 0: traffic comes driving +y, its right is +x: the post at x > 0, the arm toward -x
  local s = b[1]
  T.check(s.post[1] > 3.5 and s.post[2] < row.at[2] + row.d0 and s.dir[1] < 0 and s.len == 3.5, 'xing: right-hand boom')
  T.check(#X.booms(row, 'double') == 4 and X.booms(row, 'full')[1].len == 7, 'xing: double and full')
  T.check(#X.booms(row, nil) == 0, 'xing: no booms')
end

-- the cycle: lights, the booms after LIGHTS_BEFORE_S, a stuck car removed, the signals red, then open again
do
  X.init({ isRailVehicle = function() return false end, _setStatus = function() end, scene = function() return {} end },
    { xingsLocal = function() return { { 0, 2, 'half', 'yes' } } end })
  local tiles = { a = { railxBars = { row } } }
  local train = { { x = -300, y = 0, vx = 20, vy = 0, speed = 20, rail = true } }
  local car = { { id = 7, x = 0.5, y = 2.5, speed = 0 } }
  local removed = {}
  X._remove = function(id) removed[#removed + 1] = id end
  X._resetList()
  local list = X.update(0, tiles, train, function() return car end)
  T.check(list[1].kind == 'half' and list[1].lights and list[1].st.closing, 'xing: closing, half booms from OSM')
  local t = 0
  while t < X.LIGHTS_BEFORE_S + X.BOOM_MOVE_S + 1 do t = t + 0.25; X.update(t, tiles, train, function() return car end) end
  T.check(list[1].st.b > 0.99, 'xing: booms down')
  T.check(X.blocked(-300, 0, 1, 0) and not X.blocked(-300, 0, -1, 0), 'xing: occupied: the signals before it red')
  while t < X.STUCK_S + 2 do t = t + 0.25; X.update(t, tiles, train, function() return car end) end
  T.check(removed[1] == 7, 'xing: the stuck car removed')
  local gone = { { x = 300, y = 0, vx = 20, vy = 0, speed = 20, rail = true } }
  for _ = 1, 4 * (X.BOOM_MOVE_S + 1) do t = t + 0.25; X.update(t, tiles, gone, function() return {} end) end
  T.check(not list[1].st.closing and list[1].st.b < 0.01 and not X.blocked(-300, 0, 1, 0), 'xing: open again')
end

-- the map: OSM's file made ready, the lines in a view, the nearest point
do
  local o = MAP.prepareOsm({ lines = { { id = 1, k = 'main', pts = { { 47.0, 7.0 }, { 47.0, 7.01 } } },
    { id = 2, k = 'service', pts = { { 47.1, 7.0 }, { 47.1, 7.001 } } } }, xings = { { 47.0, 7.005, 'half', 'yes' } },
    reach = true })
  T.check(o and #o.lines == 2 and o.reach and o.xings[1].barrier == 'half', 'map: OSM prepared')
  MAP.osm = o
  T.check(#MAP.osmLines(46.9, 6.9, 47.2, 7.1, 13) == 2, 'map: every line zoomed in')
  T.check(#MAP.osmLines(46.9, 6.9, 47.2, 7.1, 9) == 1, 'map: the sidings left out zoomed out')
  T.check(#MAP.osmLines(48, 6.9, 48.2, 7.1, 13) == 0, 'map: none out of view')
  local la, lo, d = MAP.nearestOsm(o.lines, 47.0005, 7.004, 200)
  T.check(la and math.abs(la - 47.0) < 1e-6 and math.abs(lo - 7.004) < 1e-6 and math.abs(d - 55.6) < 1, 'map: nearest')
  T.check(MAP.nearestOsm(o.lines, 47.05, 7.004, 200) == nil, 'map: nothing near')
  local many = { lines = { { k = 'main', p = {}, box = { 47, 7, 47.1, 7.1 } } } }
  for i = 1, 50000 do many.lines[1].p[#many.lines[1].p + 1] = 47 + i * 1e-6; many.lines[1].p[#many.lines[1].p + 1] = 7 end
  MAP.osm = many
  local l = MAP.osmLines(46, 6, 48, 8, 12)
  T.check(#l[1].p / 2 <= MAP.OSM_MAX_PTS + 1, 'map: thinned to OSM_MAX_PTS')
  MAP.osm = nil
end

T.done('test_nrailsxing')
