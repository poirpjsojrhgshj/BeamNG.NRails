-- luajit mod/tests/test_nrailsroute.lua  (BeamNG.NRails: itineraries (nrailsroute), the diagram's mapping and clicks
-- (nrailsui), the turnouts' plan and the signals' aspects (nrailsswitch))
local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local R = require('beamngEarth/nrailsroute')
local SW = require('beamngEarth/nrailsswitch')
local UI = require('beamngEarth/nrailsui')

local function row(pts) local r = {} for _, p in ipairs(pts) do r[#r + 1] = p[1]; r[#r + 1] = p[2]; r[#r + 1] = 0 end return r end
local function line(x0, y0, x1, y1)
  local out, L = {}, math.sqrt((x1 - x0) ^ 2 + (y1 - y0) ^ 2)
  local k = math.max(1, math.floor(L / 2))
  for i = 0, k do out[#out + 1] = { x0 + (x1 - x0) * i / k, y0 + (y1 - y0) * i / k } end
  return out
end
local function curve()        -- (100, 0) out to (250, 20) then on to (400, 20)
  local out = {}
  for i = 0, 75 do
    local t = i / 75
    out[#out + 1] = { 100 + 2 * i, 20 * (3 * t * t - 2 * t * t * t) }
  end
  for _, p in ipairs(line(250, 20, 400, 20)) do out[#out + 1] = p end
  return out
end

-- itineraries: the way along the tracks, no reversal, the route each turnout takes
do
  local branch = curve()
  local rows = { row(line(-200, 0, 5, 0)), row(line(-5, 0, 100, 0)), row(line(100, 0, 400, 0)), row(branch) }
  local g = R.graph(rows)
  local path = R.find(g, -150, 0, 1, 0, 380, 20)
  T.check(path ~= nil and math.abs(path[#path][2] - 20) < 3, 'route: a way to the branch, across a tile seam')
  local bz
  for _, p in ipairs(branch) do if not bz and p[2] >= 3 then bz = p end end
  local sw = { id = 's', at = { 100, 0 }, routes = { { line = { 100, 0, bz[1], bz[2] } }, { line = { 100, 0, 130, 0, 160, 0 } } } }
  T.check(R.choices({ sw }, path).s == 1, 'route: the branch taken at the turnout')
  T.check(R.choices({ sw }, R.find(g, -150, 0, 1, 0, 380, 0)).s == 2, 'route: the straight route along it')
  T.check(R.find(g, -150, 0, 1, 0, -190, 0) == nil, 'route: none behind the train (no reversing)')
  T.check(R.find(g, -150, 0, -1, 0, -190, 0) ~= nil, 'route: facing the other way, there')
  T.check(R.find(g, 380, 20, -1, 0, 380, 0) == nil, 'route: no reversal at a turnout')
  T.near(R.length(R.find(g, -150, 0, 1, 0, 380, 0)), 530, 15, 'route: its length')
end

-- the diagram: its mapping and back; a click on a branch plans it; the plan sets the turnout when free; signals
do
  local msgs = {}
  UI.init({ _roads = { extTiles = function() return {} end }, switch = SW, KEYS = {},
    _setStatus = function(s) msgs[#msgs + 1] = s end })
  local at, d = { 100, 50 }, { 0.6, 0.8 }
  local q = UI.xy({ 130, 90 }, at, d, 2, 340, 200, 0.5)[1]
  local x, y = UI.inv(q[1], q[2], at, d, 2, 340, 200, 0.5)
  T.check(math.abs(x - 130) < 1e-9 and math.abs(y - 90) < 1e-9, 'diagram: a point and back')
  local sw = { id = 'a', at = { 0, 0 }, dir = { 1, 0 }, def = 1,
    routes = { { line = { 0, 0, 40, 3 }, arm = { 0, 0, 40, 3, 100, 20 } }, { line = { 0, 0, 40, 0 }, arm = { 0, 0, 40, 0, 150, 0 } } } }
  local view = { at = { 0, 0 }, dir = { 1, 0 }, scale = 2, ox = 0.5, sws = { sw }, lines = {} }
  local p1 = UI.xy({ 70, 11 }, view.at, view.dir, 2, 340, 200, 0.5)[1]
  local kind, _, idx = UI.click(p1[1], p1[2], view, nil)
  T.check(kind == 'switch' and idx == 1 and SW.plan.a == 1, 'diagram: a click on a branch plans it')
  local cars = { { x = -500, y = 0, vx = 0, vy = 0, rail = true } }
  T.check(SW.step({ sw }, cars).a == 1, 'plan: the turnout set when free')
  cars[1].x, cars[1].y = 20, 0.5
  T.check(SW.step({ sw }, cars).a == nil, 'plan: never under a train')
  T.check(SW.aspect(sw, cars) == 'red', 'signal: red, a vehicle in its zone')
  SW.state.a = 2
  T.check(SW.aspect(sw, {}) == 'green', 'signal: green, the main line set')
  SW.state.a = 1
  T.check(SW.aspect(sw, {}) == 'yellow', 'signal: yellow, a diverging route set')
  -- the French-style lights (SNCF): carre, RR30 / RR60, ralentissement, avertissement, shunting
  local function names(ls) local o = {} for _, l in ipairs(ls) do o[#o + 1] = l[1] .. l[2] .. l[3] .. (l[4] and 'f' or '') end return table.concat(o, ' ') end
  SW.state.a = 2
  T.check(names(SW.lamps(sw, {}, 'main')) == 'green00', 'lights: main line set: voie libre')
  T.check(names(SW.lamps(sw, {}, 'adv')) == 'green00', 'lights: advance, main line: green')
  SW.state.a = 1
  T.check(names(SW.lamps(sw, {}, 'main')) == 'yellow01 yellow0-1', 'lights: diverging (steep): RR30, two yellow one over the other')
  T.check(names(SW.lamps(sw, {}, 'adv')) == 'yellow-10 yellow10', 'lights: advance, diverging: R30, two yellow side by side')
  T.check(names(SW.lamps(sw, cars, 'main')) == 'red-10 red10', 'lights: a vehicle on it: carre')
  T.check(names(SW.lamps(sw, cars, 'adv')) == 'yellow00', 'lights: advance, turnout taken: avertissement')
  T.check(names(SW.lamps(sw, {}, 'main', true)) == 'white00' and names(SW.lamps(sw, cars, 'main', true)) == 'violet00',
    'lights: a yard: white, carre violet when taken')
  local gentle = { id = 'g', at = { 0, 0 }, dir = { 1, 0 }, def = 1,
    routes = { { line = { 0, 0, 40, 0.6 }, arm = { 0, 0, 60, 1.5, 200, 8 } }, { line = { 0, 0, 40, 0 }, arm = { 0, 0, 150, 0 } } } }
  SW.state.g = 1
  T.check(names(SW.lamps(gentle, {}, 'main')) == 'yellow01f yellow0-1f', 'lights: a gentle turnout: RR60, flashing')
  SW.plan, SW.state = {}, {}
  local _, _, nf = SW.step({ sw }, { { x = -100, y = 0, vx = 0, vy = 0, fx = 1, fy = 0, player = true, rail = true } })
  T.check(nf ~= nil and nf.sw == sw, 'diagram: a stopped train still sees the turnout it faces')
end

-- every bogie: a long vehicle whose centre left the zone but whose rear bogie is still on the blades locks it
do
  local sw = { id = 'x', at = { 0, 0 }, dir = { 1, 0 }, def = 0, trunk = { -60, 0, 0, 0 },
    routes = { { line = { 0, 0, 30, 0 }, arm = { 0, 0, 200, 0 } }, { line = { 0, 0, 30, 3 }, arm = { 0, 0, 200, 20 } } } }
  local car = { x = 40, y = 0, vx = 5, vy = 0, rail = true }
  T.check(not SW.conflict(sw, { car }, 2), 'switch: centre only: no lock (the old way)')
  car.pts = { { 40, 0 }, { 48, 0 }, { 32, 0 }, { 51, 0 }, { 29, 0 } }
  T.check(SW.conflict(sw, { car }, 2), 'switch: the rear bogie on the blades: locked (rear bogie)')
  T.check(SW.occupied(sw, { car }), 'switch: occupied by the rear bogie')
end

T.done('test_nrailsroute')
