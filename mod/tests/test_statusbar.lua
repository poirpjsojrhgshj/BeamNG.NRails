-- luajit mod/tests/test_statusbar.lua  (statusbar.lua: the slim bar at the top: street, place, loading, fps)
local T = dofile((arg[0]:match('^(.*)[/\\]') or '.') .. '/testlib.lua')
local sb = require('beamngEarth/statusbar')

T.check(sb.compose({ street = 'Thames Street', place = 'Baltimore', region = 'Maryland', country = 'United States' },
  'Loading 120/433', 71.4) == 'Thames Street  |  Baltimore, Maryland, United States  |  Loading 120/433  |  71 fps',
  'every part, in order')
T.check(sb.compose({ street = '', place = 'Bishop', region = 'California', country = 'United States' }, nil, nil)
  == 'Bishop, California, United States', 'no street, loaded, no fps yet')
T.check(sb.compose({ street = '', place = '', region = '', country = '' }, nil, 60) == '60 fps', 'nothing known yet')
T.check(sb.compose({ place = 'Monaco', region = 'Monaco', country = 'Monaco' }) == 'Monaco', 'repeats once')
T.check(sb.loadingLine('Far field loading: 150/433 tiles') == 'Loading 150/433', 'far field loading')
T.check(sb.loadingLine('Preparing terrain at 39.1, -76.2 ...') == 'Building terrain', 'a teleport')
T.check(sb.loadingLine('Far field ready (433 tiles)') == nil, 'ready: no loading part')
-- the loading line is its own row (the user, 2026-10-23): the location row never carries it
T.check(sb.loading('Anchor #3', 'Loading 40%  |  trees 2/9') == 'Loading 40%  |  trees 2/9', 'the loading row: the line given')
T.check(sb.loading('Anchor #3', false) == '', 'no load: no loading row')
T.check(not sb.text('Far field loading: 150/433 tiles', 'Loading 40%'):find('Loading', 1, true), 'the location row without it')

-- requests: at once, then not before WHERE_MIN_S and WHERE_STREET_M; the place when online and far / late enough
local p = { x = 0, y = 0, lat = 39.28, lon = -76.59 }
local q = sb.request(0, p, true)
T.check(q and q.type == 'where' and q.online == true, 'the first request asks the place too')
T.check(sb.request(1, { x = 100, y = 0, lat = 39.28, lon = -76.5888 }, true) == nil, 'not within WHERE_MIN_S')
T.check(sb.request(5, { x = 10, y = 0, lat = 39.28, lon = -76.58988 }, true) == nil, 'not without moving')
q = sb.request(5, { x = 100, y = 0, lat = 39.28, lon = -76.5888 }, true)
T.check(q and q.online == false, 'moved 100 m: the street only')
q = sb.request(10, { x = 2000, y = 0, lat = 39.28, lon = -76.5668 }, true)
T.check(q and q.online == true, 'moved 2 km: the place again')
q = sb.request(20, { x = 4000, y = 0, lat = 39.28, lon = -76.5437 }, false)
T.check(q and q.online == false, 'place names off: never online')
sb.onResult({ street = 'Boston Street' })
sb.onResult({ street = 'Boston Street', place = 'Baltimore', region = 'Maryland', country = 'United States' })
local l = sb.location()
T.check(l.street == 'Boston Street' and l.place == 'Baltimore' and l.country == 'United States', 'results kept')
sb.reset()
T.check(sb.location().street == '' and sb.request(30, p, true).online == true, 'a teleport: asked afresh')
-- a teleport lands at x, y ~ 0 again: still a new place (lat / lon), the old one cleared at once
sb.onResult({ street = 'John Muir Trail' })
q = sb.request(40, { x = 0, y = 0, lat = 43.911, lon = 5.2005 }, true)
T.check(q and q.online == true and sb.location().street == '', 'a teleport to another place: asked, old street gone')
T.done('test_statusbar')
