-- BeamNG.NRails: the railways on BeamNG.Earth's map (the user, 2026-10-26: "dans la map de Earth un onglet creation
-- d'itineraires mettant en une couleur les voies ferrees et pouvant cliquer a un endroit (precis a la voie pres) pour
-- soit creer un itineraire (ferroviaire) soit se tp"; 2026-10-27: "tu sais que tu peux extraire des donnees de rails
-- [d'OpenStreetMap], extrait les, met les sur la map, s'il y a trop a charger, charge les 100 km autour uniquement
-- accessibles depuis notre voie").
--
-- Two kinds of lines: OpenStreetMap's railways within OSM_KM of the player, those reachable along the tracks from its
-- own (the server's nrails.osmmsg, asked once a place: a file the game reads), and the loaded tracks (the road tiles':
-- precise to the rail). The map's NRails parts (ui-vue/.../NRailsMap*.vue) ask here through engineLua
-- (beamngEarth_core.nrails.map.*):
--   osmLines(lat0, lon0, lat1, lon1, z): OSM's lines in the view { {k = kind, p = {lat, lon, ...}}, ... };
--   rails(lat0, lon0, lat1, lon1, step): the loaded tracks in the view as lat / lon lines;
--   pick(lat, lon, reachM): the loaded track (or OSM line) point nearest a click as lat / lon, or nil;
--   itinerary(lat, lon): an itinerary from the player's train there. Along OSM's railways (the server's route, no
--     reversing at a junction: drawn on the map at once), the loaded part of it set in the turnouts
--     (nrailsui.setItinerary to the farthest point of it already loaded, again every FAR_EVERY_S as tiles come);
--   teleportRail(lat, lon): BeamNG.Earth's teleport there, then the vehicle put on the nearest track as soon as it is
--     loaded (snap to rail, within SNAP_AFTER_M, for SNAP_WAIT_S at most);
--   refreshOsm(): OSM's railways asked again round the player;
--   state(): the itinerary, the OSM route, the far destination, the waiting snap, OSM's loading.
local M = {}

M.PICK_M = 40             -- m round a click a loaded track point is taken
M.FAR_EVERY_S = 5
M.NEAR_M = 40             -- m: a destination this close to a loaded track: the itinerary itself
M.ON_PATH_M = 15          -- m: an OSM route's point this close to a loaded track: that track is the route's
M.SNAP_AFTER_M = 120      -- m round the teleport's point a track is looked for after it
M.SNAP_WAIT_S = 120
M.OSM_KM = 100
M.OSM_MAIN_KM = 200       -- the main lines and branches only, out to this
M.OSM_AGAIN_KM = 40       -- the player this far from the last ask's centre: OSM's railways asked again
M.OSM_MAX_PTS = 20000     -- points sent to the map a view at most (the far zoom levels: the main lines first)

local N, ui, route, roads, geo
M.far = nil               -- { lat, lon, at }
M.snap = nil              -- { lat, lon, untilT }
M.osm = nil               -- { lines = {{k, p = {lat, lon, ...}, box = {la0, lo0, la1, lo1}}}, xings, reach }
M.osmStatus = { asked = false, done = 0, total = 0, error = nil, n = 0, reach = nil }
M.osmRoute = nil          -- { pts = {{lat, lon}, ...}, dist, dest = {lat, lon} }

function M.init(nrails, nrui, nrroute, nrroads, anchorFn)
  N, ui, route, roads, geo = nrails, nrui, nrroute, nrroads, anchorFn
end

local function anchor() return geo and geo() or nil end
local function send(msg)
  local ok, net = pcall(require, 'beamngEarth/net')
  if ok and net and net.send then pcall(net.send, msg) end
end
M._send = send

-- Pure: the rows' points (flat x, y, z, ...) inside (x0, y0, x1, y1), every `step` m at least, as lines of world
-- points { {x, y, x, y, ...}, ... } (a row leaving the box: cut there).
function M.clip(rows, x0, y0, x1, y1, step)
  local out = {}
  for _, row in ipairs(rows) do
    local cur, lx, ly = {}, nil, nil
    for i = 1, #row - 2, 3 do
      local x, y = row[i], row[i + 1]
      if x >= x0 and x <= x1 and y >= y0 and y <= y1 then
        if not lx or (x - lx) ^ 2 + (y - ly) ^ 2 >= step * step or i >= #row - 2 then
          cur[#cur + 1] = x; cur[#cur + 1] = y; lx, ly = x, y
        end
      else
        if #cur >= 4 then out[#out + 1] = cur end
        cur, lx, ly = {}, nil, nil
      end
    end
    if #cur >= 4 then out[#out + 1] = cur end
  end
  return out
end

-- Pure: the nearest point of the rows to (x, y) within reach: x, y, distance (nil if none).
function M.nearestPoint(rows, x, y, reach)
  local best, bx, by = (reach or M.PICK_M) ^ 2, nil, nil
  for _, row in ipairs(rows) do
    for i = 1, #row - 5, 3 do
      local x1, y1, x2, y2 = row[i], row[i + 1], row[i + 3], row[i + 4]
      local dx, dy = x2 - x1, y2 - y1
      local L2 = dx * dx + dy * dy
      local t = L2 > 1e-9 and math.max(0, math.min(1, ((x - x1) * dx + (y - y1) * dy) / L2)) or 0
      local fx, fy = x1 + t * dx, y1 + t * dy
      local d2 = (x - fx) ^ 2 + (y - fy) ^ 2
      if d2 < best then best, bx, by = d2, fx, fy end
    end
  end
  if not bx then return nil end
  return bx, by, math.sqrt(best)
end

local function rows() return route.rows(roads.extTiles()) end

local function toWorld(lat, lon)
  local a = anchor()
  if not a then return nil end
  local x, y = a:geodeticToEnu(lat, lon, 0)
  return x, y
end

local function toLatLon(x, y)
  local a = anchor()
  if not a then return nil end
  local lat, lon = a:enuToGeodetic(x, y, 0)
  return lat, lon
end
M._toWorld, M._toLatLon = toWorld, toLatLon

-- ----------------------------------------------------------------------------------------------- OpenStreetMap
-- Pure: the file's content made ready for the map (each line's lat / lon box).
function M.prepareOsm(data)
  if type(data) ~= 'table' or type(data.lines) ~= 'table' then return nil end
  local lines = {}
  for _, l in ipairs(data.lines) do
    local pts = l.pts
    if type(pts) == 'table' and #pts >= 2 then
      local flat = {}
      local la0, lo0, la1, lo1 = 90, 180, -90, -180
      for _, q in ipairs(pts) do
        local la, lo = q[1], q[2]
        flat[#flat + 1] = la; flat[#flat + 1] = lo
        if la < la0 then la0 = la end
        if la > la1 then la1 = la end
        if lo < lo0 then lo0 = lo end
        if lo > lo1 then lo1 = lo end
      end
      lines[#lines + 1] = { k = l.k or 'branch', p = flat, box = { la0, lo0, la1, lo1 } }
    end
  end
  local xings = {}
  for _, x in ipairs(type(data.xings) == 'table' and data.xings or {}) do
    if type(x) == 'table' and x[1] then
      xings[#xings + 1] = { lat = x[1], lon = x[2], barrier = x[3], light = x[4], vmax = tonumber(x[5]) }
    end
  end
  return { lines = lines, xings = xings, reach = data.reach == true }
end

-- The OSM lines in the view: { {k, p = {lat, lon, ...}}, ... }. Zoomed out, the sidings and yards first left out,
-- then every other point (OSM_MAX_PTS at most).
local KIND_MIN_Z = { main = 0, branch = 8, light = 9, service = 12 }
function M.osmLines(lat0, lon0, lat1, lon1, z)
  local o = M.osm
  if not o then return {} end
  z = z or 12
  local sel, n = {}, 0
  for _, l in ipairs(o.lines) do
    local b = l.box
    if z >= (KIND_MIN_Z[l.k] or 8) and b[3] >= lat0 and b[1] <= lat1 and b[4] >= lon0 and b[2] <= lon1 then
      sel[#sel + 1] = l
      n = n + #l.p / 2
    end
  end
  local every = math.max(1, math.ceil(n / M.OSM_MAX_PTS))
  local out = {}
  for _, l in ipairs(sel) do
    if every == 1 then
      out[#out + 1] = { k = l.k, p = l.p }
    else
      local p, m = {}, #l.p / 2
      for i = 1, m, every do p[#p + 1] = l.p[2 * i - 1]; p[#p + 1] = l.p[2 * i] end
      if (m - 1) % every ~= 0 then p[#p + 1] = l.p[2 * m - 1]; p[#p + 1] = l.p[2 * m] end
      out[#out + 1] = { k = l.k, p = p }
    end
  end
  return out
end

-- Pure: the nearest point of OSM's lines (lat / lon) to (lat, lon) within reach m: lat, lon, distance.
function M.nearestOsm(lines, lat, lon, reach)
  local k = math.cos(math.rad(lat)) * 111200
  local best, bla, blo = reach * reach, nil, nil
  local dl = reach / 111200
  for _, l in ipairs(lines or {}) do
    local b = l.box
    if not b or (b[1] - dl <= lat and b[3] + dl >= lat and b[2] - dl * 2 <= lon and b[4] + dl * 2 >= lon) then
      local p = l.p
      for i = 1, #p - 3, 2 do
        local x1, y1 = (p[i + 1] - lon) * k, (p[i] - lat) * 111200
        local x2, y2 = (p[i + 3] - lon) * k, (p[i + 2] - lat) * 111200
        local dx, dy = x2 - x1, y2 - y1
        local L2 = dx * dx + dy * dy
        local t = L2 > 1e-9 and math.max(0, math.min(1, -(x1 * dx + y1 * dy) / L2)) or 0
        local fx, fy = x1 + t * dx, y1 + t * dy
        local d2 = fx * fx + fy * fy
        if d2 < best then best, bla, blo = d2, lat + fy / 111200, lon + fx / k end
      end
    end
  end
  if not bla then return nil end
  return bla, blo, math.sqrt(best)
end

local osmCentre, osmId = nil, 0
-- Ask the server for OSM's railways round the player (reachable from its track when it stands on one).
function M.requestOsm(force)
  local p = ui._playerPose()
  if not p then return false end
  local lat, lon = toLatLon(p.x, p.y)
  if not lat then return false end
  if not force and osmCentre then
    local k = math.cos(math.rad(lat)) * 111.2
    local d = math.sqrt(((lat - osmCentre[1]) * 111.2) ^ 2 + ((lon - osmCentre[2]) * k) ^ 2)
    if d < M.OSM_AGAIN_KM then return false end
  end
  osmCentre = { lat, lon }
  osmId = osmId + 1
  -- the start: the nearest loaded track's point (else the player: the server looks 300 m round it)
  local slat, slon = lat, lon
  local t = N.nearestRail and N.nearestRail(p.x, p.y, p.z, 200)
  if t then slat, slon = toLatLon(t.x, t.y) end
  M.osmStatus = { asked = true, done = 0, total = 0, n = M.osmStatus.n, reach = M.osmStatus.reach }
  send({ type = 'nrails_osm', id = osmId, lat = lat, lon = lon, slat = slat, slon = slon, r_km = M.OSM_KM,
    main_km = M.OSM_MAIN_KM })
  return true
end
function M.refreshOsm() return M.requestOsm(true) end
function M._resetOsm() osmCentre = nil end

local function readJson(path)
  local text = readFile and readFile(path)
  if type(text) ~= 'string' or text == '' then return nil end
  local ok, data = pcall(jsonDecode, text)
  return ok and data or nil
end
M._readJson = readJson

-- The server's answers (core.lua's NRails hook -> nrails.onMessage).
function M.onMessage(msg)
  if msg.type == 'nrails_osm_ready' then
    local s = M.osmStatus
    if msg.error then s.error = tostring(msg.error) end
    if tonumber(msg.done) and msg.done >= 0 then s.done, s.total = msg.done, msg.total end
    if msg.file then
      local o = M.prepareOsm(M._readJson(msg.file))
      if o then
        M.osm = o
        M._xingCache = nil
        s.n, s.reach = #o.lines, o.reach
      end
    end
  elseif msg.type == 'nrails_osm_route_result' then
    local pend = M._routeAsk
    if not pend or msg.id ~= pend.id then return end
    M._routeAsk = nil
    if msg.error or type(msg.points) ~= 'table' or not msg.points[2] then
      N._setStatus('NRails: pas d\'itineraire OSM / no OSM route: ' .. tostring(msg.error or 'none'))
      return
    end
    M.osmRoute = { pts = msg.points, dist = tonumber(msg.dist) or 0, dest = pend.dest }
    M.far = { lat = pend.dest[1], lon = pend.dest[2], at = os.clock() }
    N._setStatus(string.format('NRails: itineraire %.1f km le long des voies (OSM) / route set', M.osmRoute.dist / 1000))
    pcall(M.steer)
  end
end

-- OpenStreetMap's level crossings in the anchor's frame: { {x, y, barrier, light}, ... } (the barriers, nrailsxing).
function M.xingsLocal()
  local a = anchor()
  if not M.osm or not a then return {} end
  if M._xingCache and M._xingCache.a == a then return M._xingCache.rows end
  local rows_ = {}
  for _, x in ipairs(M.osm.xings) do
    local okx, wx, wy = pcall(function() return a:geodeticToEnu(x.lat, x.lon, 0) end)
    if okx and wx then rows_[#rows_ + 1] = { wx, wy, x.barrier, x.light, x.vmax } end
  end
  M._xingCache = { a = a, rows = rows_ }
  return rows_
end

-- ------------------------------------------------------------------------------------------------- the map's asks
-- The loaded tracks in the view (lat / lon box), every `step` m: { {lat, lon, lat, lon, ...}, ... }.
function M.rails(lat0, lon0, lat1, lon1, step)
  local a = anchor()
  if not a then return {} end
  local xs, ys = {}, {}
  for _, c in ipairs({ { lat0, lon0 }, { lat0, lon1 }, { lat1, lon0 }, { lat1, lon1 } }) do
    local x, y = a:geodeticToEnu(c[1], c[2], 0)
    xs[#xs + 1], ys[#ys + 1] = x, y
  end
  local lines = M.clip(rows(), math.min(unpack(xs)), math.min(unpack(ys)), math.max(unpack(xs)), math.max(unpack(ys)),
    math.max(2, step or 10))
  local out = {}
  for _, l in ipairs(lines) do
    local ll = {}
    for i = 1, #l - 1, 2 do
      local la, lo = a:enuToGeodetic(l[i], l[i + 1], 0)
      ll[#ll + 1] = la; ll[#ll + 1] = lo
    end
    out[#out + 1] = ll
  end
  return out
end

-- The point a click (lat, lon) means: the loaded track within PICK_M ({lat, lon, d, loaded = true}), else OSM's
-- railway within reachM (the map's scale: ~12 px) ({lat, lon, d, osm = true}), else nil.
function M.pick(lat, lon, reachM)
  local x, y = toWorld(lat, lon)
  if x then
    local px, py, d = M.nearestPoint(rows(), x, y, M.PICK_M)
    if px then
      local la, lo = toLatLon(px, py)
      return { lat = la, lon = lo, d = d, loaded = true }
    end
  end
  if M.osm then
    local la, lo, d = M.nearestOsm(M.osm.lines, lat, lon, math.max(M.PICK_M, reachM or 200))
    if la then return { lat = la, lon = lo, d = d, osm = true } end
  end
  return nil
end

-- The OSM route's farthest point (from its start) lying on a loaded track: x, y (world), the index.
function M.loadedEnd(pts, rs)
  rs = rs or rows()
  for i = #pts, 1, -1 do
    local x, y = toWorld(pts[i][1], pts[i][2])
    if x then
      local px, py = M.nearestPoint(rs, x, y, M.ON_PATH_M)
      if px then return px, py, i end
    end
  end
  return nil
end

-- The loaded part of the itinerary set in the turnouts.
local lastFar = -1
function M.steer()
  local p = ui._playerPose()
  if not p or not p.rail or not M.far then return false end
  local x, y = toWorld(M.far.lat, M.far.lon)
  if not x then return false end
  local rs = rows()
  local px, py = M.nearestPoint(rs, x, y, M.NEAR_M)
  if px then                                   -- (the destination's track is loaded: the itinerary itself)
    M.far = nil
    return ui.setItinerary(p, px, py) ~= nil
  end
  if M.osmRoute then
    local ex, ey = M.loadedEnd(M.osmRoute.pts, rs)
    if ex then return ui.setItinerary(p, ex, ey) ~= nil end
  end
  local g = route.graph(rs)                    -- (no OSM route: the way toward it)
  local path = route.findToward(g, p.x, p.y, p.hx, p.hy, x, y)
  if path then ui.planPath(path, x, y); return true end
  return false
end

M._routeAsk = nil
local routeId = 0
function M.itinerary(lat, lon)
  local p = ui._playerPose()
  if not p then return { ok = false, msg = 'NRails: pas de vehicule / no vehicle' } end
  local x, y = toWorld(lat, lon)
  if not x then return { ok = false, msg = 'no anchor' } end
  M.osmRoute = nil
  local px, py = M.nearestPoint(rows(), x, y, M.NEAR_M)
  if px and p.rail then
    M.far = nil
    local it = ui.setItinerary(p, px, py)
    if it then return { ok = true, msg = 'itineraire regle / itinerary set' } end
  end
  -- along OpenStreetMap's railways (the server): drawn on the map, the loaded part set in the turnouts
  local slat, slon = toLatLon(p.x, p.y)
  local t = N.nearestRail and N.nearestRail(p.x, p.y, p.z, 200)
  if t then slat, slon = toLatLon(t.x, t.y) end
  routeId = routeId + 1
  M._routeAsk = { id = routeId, dest = { lat, lon } }
  M.far = { lat = lat, lon = lon, at = os.clock() }
  send({ type = 'nrails_osm_route', id = routeId, lat0 = slat, lon0 = slon, lat1 = lat, lon1 = lon })
  return { ok = true, far = true, msg = p.rail and 'itineraire demande (OSM) / route asked'
    or 'itineraire affiche ; monte dans un train pour regler les aiguillages / board a train to set the turnouts' }
end

function M.teleportRail(lat, lon)
  local s = rawget(_G, 'beamngEarth_settings')
  if not s or not s.uiMapTeleport then return { ok = false } end
  local r = s.uiMapTeleport(lat, lon, '')
  if r and r.ok then M.snap = { lat = lat, lon = lon, untilT = os.clock() + M.SNAP_WAIT_S } end
  return r
end

function M.clear()
  M.far = nil
  M.osmRoute = nil
  M._routeAsk = nil
  if ui.clearPlan then ui.clearPlan() end
end

function M.state()
  local s = M.osmStatus
  local out = { far = M.far and { lat = M.far.lat, lon = M.far.lon } or nil, snapping = M.snap ~= nil,
    osm = { asked = s.asked, done = s.done, total = s.total, n = s.n, reach = s.reach, error = s.error },
    asking = M._routeAsk ~= nil }
  local it = ui.itin
  if it and it.path then
    local pts = {}
    for i = 1, #it.path, math.max(1, math.floor(#it.path / 300)) do
      local la, lo = toLatLon(it.path[i][1], it.path[i][2])
      if la then pts[#pts + 1] = { la, lo } end
    end
    local n = 0
    for _ in pairs(it.ids or {}) do n = n + 1 end
    out.itin = { pts = pts, length = math.floor(route.length(it.path)), turnouts = n }
  end
  if M.osmRoute then
    local r, pts = M.osmRoute.pts, {}
    for i = 1, #r, math.max(1, math.floor(#r / 1500)) do pts[#pts + 1] = r[i] end
    if pts[#pts] ~= r[#r] then pts[#pts + 1] = r[#r] end
    out.route = { pts = pts, dist = M.osmRoute.dist }
  end
  return out
end

local lastAsk = -100
function M.update(now)
  now = now or os.clock()
  if now - lastAsk > 10 then                   -- (OSM's railways round the player: once a place)
    lastAsk = now
    if anchor() and next(roads.extTiles()) ~= nil then pcall(M.requestOsm, false) end
  end
  if M.snap then
    if now > M.snap.untilT then
      M.snap = nil
    else
      local p = ui._playerPose()
      if p then
        local px = M.nearestPoint(rows(), p.x, p.y, M.SNAP_AFTER_M)
        if px then
          M.snap = nil
          pcall(N.snapToRail, M.SNAP_AFTER_M)
        end
      end
    end
  end
  if M.far and now - lastFar >= M.FAR_EVERY_S then
    lastFar = now
    pcall(M.steer)
  end
end

return M
