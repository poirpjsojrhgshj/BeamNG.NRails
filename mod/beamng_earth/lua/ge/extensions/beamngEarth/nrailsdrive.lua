-- BeamNG.NRails: the train's driving aids and the train configurator (the user, 2026-10-27: "des systemes dans les
-- trains plus fideles a la vraie vie (regulateurs de vitesse, etc). Un configurateur de trains (nombre de voitures ou
-- locos, distance de freinage predite, longueur totale, comparaison longueur et norme en vigueur dans la zone de
-- roulage) dans un menu").
--
-- Driving aids (the vehicle side: lua/vehicle/extensions/nrailsDrive.lua):
--   * the speed regulator: Ctrl+Shift+K on / off at the speed now (rounded to 5 km/h), Ctrl+Shift+PageUp / PageDown
--     +/- 5 km/h; it drops out on the driver's brake;
--   * the speed control (after the French KVB): the next restriction on the track ahead (the signals' aspects within
--     AHEAD_M: carre / avertissement -> stop, RR30 / R30 -> 30 km/h, RR60 -> 60 km/h; a level crossing occupied ahead
--     -> stop) sent every SEND_S, the vehicle side's braking curve, its alarm and its emergency brake;
--   * a small panel: the speed, the set speed, the restriction and the speed allowed now.
-- The configurator (Ctrl+Shift+J): the consist round the player (the rail vehicles coupled to it: gaps under
-- CHAIN_GAP_M), its vehicles, locomotives, length and mass, the stopping distances (reaction and brake build-up, then
-- the deceleration of its kind: freight or passenger), the train length allowed where it runs (the country: indicative
-- values) and a builder: N vehicles of a model added behind the consist, on the track, coupled.
local M = {}

M.SEND_S = 0.5
M.AHEAD_M = 2000
M.ON_TRACK_M = 5.0        -- m a signal's lamp may stand off the track ahead's centre line
M.CHAIN_GAP_M = 4.0
M.CONSIST_M = 1500
M.BUILD_GAP_M = 0.6       -- m between two vehicles placed by the builder (their couplers within reach)
M.BUILD_MAX = 60

-- Indicative train lengths allowed (m): { freight, passenger, source }.
M.NORMS = {
  FR = { 750, 400, 'SNCF Reseau: 750 m fret (850 m en essai), 400 m voyageurs (2 rames TGV)' },
  DE = { 740, 400, 'DB InfraGO / STI: 740 m fret, 400 m voyageurs' },
  CH = { 750, 400, 'CFF / SBB: 750 m fret, 400 m voyageurs' },
  GB = { 775, 300, 'Network Rail: 775 m fret au plus, ~12 voitures voyageurs' },
  US = { nil, nil, 'USA: pas de limite reglementaire (fret courant 2-3 km)' },
  CA = { nil, nil, 'Canada: pas de limite reglementaire (fret courant 2-4 km)' },
  RU = { 1050, 650, 'RZD: 71 wagons / 1050 m fret, ~25 voitures voyageurs' },
  EU = { 740, 400, 'STI (UE, RTE-T): 740 m fret, 400 m voyageurs' },
}
-- Coarse outlines (lat, lon; ~10 km) of the countries whose neighbours' boxes cover them, tested first, then rough
-- boxes (lat0, lon0, lat1, lon1), the small countries first: the country of a point, approximately.
M.OUTLINES = {
  CH = { { 47.59, 7.55 }, { 47.70, 8.40 }, { 47.80, 8.60 }, { 47.65, 9.20 }, { 47.53, 9.60 }, { 47.27, 9.55 },
    { 47.05, 9.95 }, { 46.85, 10.47 }, { 46.60, 10.45 }, { 46.30, 10.15 }, { 46.40, 9.70 }, { 46.30, 9.30 },
    { 45.82, 9.00 }, { 46.10, 8.70 }, { 46.02, 8.10 }, { 45.92, 7.85 }, { 45.87, 7.15 }, { 46.15, 6.85 },
    { 46.40, 6.80 }, { 46.30, 6.25 }, { 46.20, 6.26 }, { 46.13, 6.05 }, { 46.13, 5.96 }, { 46.40, 6.05 }, { 46.90, 6.45 }, { 47.10, 6.85 },
    { 47.30, 6.95 }, { 47.50, 7.00 } },
  FR = { { 51.09, 2.55 }, { 50.70, 3.20 }, { 50.30, 4.20 }, { 49.95, 4.85 }, { 49.55, 5.80 }, { 49.47, 6.40 },
    { 49.15, 6.75 }, { 49.00, 8.20 }, { 48.00, 7.60 }, { 47.59, 7.55 }, { 47.50, 7.00 }, { 47.30, 6.95 },
    { 47.10, 6.85 }, { 46.90, 6.45 }, { 46.40, 6.05 }, { 46.13, 5.96 }, { 46.13, 6.05 }, { 46.20, 6.26 }, { 46.30, 6.25 }, { 46.40, 6.80 },
    { 46.15, 6.85 }, { 45.90, 7.00 }, { 45.10, 6.70 }, { 44.20, 7.65 }, { 43.75, 7.50 }, { 43.10, 6.20 },
    { 43.35, 3.20 }, { 42.43, 3.17 }, { 42.70, 1.70 }, { 43.30, -1.78 }, { 46.20, -1.40 }, { 47.30, -2.60 },
    { 48.50, -4.80 }, { 48.70, -1.80 }, { 49.70, -1.90 }, { 49.50, 0.10 }, { 50.20, 1.50 } },
}
M.OUTLINE_ORDER = { 'CH', 'FR' }
M.BOXES = {
  { 49.44, 5.73, 50.19, 6.53, 'EU' },   -- LU
  { 49.49, 2.54, 51.51, 6.41, 'EU' },   -- BE
  { 50.75, 3.36, 53.56, 7.23, 'EU' },   -- NL
  { 46.37, 9.53, 49.02, 17.16, 'EU' },  -- AT
  { 49.95, -8.65, 60.86, 1.77, 'GB' },
  { 47.27, 5.87, 55.06, 15.04, 'DE' },
  { 34.0, -10.0, 71.0, 32.0, 'EU' },
  { 41.0, 27.0, 78.0, 180.0, 'RU' },
  { 24.5, -125.0, 49.0, -66.9, 'US' },
  { 49.0, -141.0, 83.0, -52.0, 'CA' },
}
-- Decelerations (m/s2) and the brake's build-up (s, plus the length over the brake pipe's propagation, ~250 m/s).
M.KIND = {
  freight = { decel = 0.45, build = 4.0, label = 'fret / freight' },
  passenger = { decel = 0.8, build = 2.0, label = 'voyageurs / passenger' },
}
M.REACT_S = 2.0

local N, switch, route, ui, mapm
local function radio(im, label, on) return im.Button((on and '[x] ' or '[ ] ') .. label) end
function M.init(nrails, sw, nrroute, nrui, nrmap) N, switch, route, ui, mapm = nrails, sw, nrroute, nrui, nrmap end

-- ------------------------------------------------------------------------------------------------- pure helpers
local function inside(poly, lat, lon)
  local c, n = false, #poly
  local j = n
  for i = 1, n do
    local yi, xi, yj, xj = poly[i][1], poly[i][2], poly[j][1], poly[j][2]
    if (yi > lat) ~= (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi then c = not c end
    j = i
  end
  return c
end
M._inside = inside

function M.country(lat, lon)
  for _, k in ipairs(M.OUTLINE_ORDER) do
    if inside(M.OUTLINES[k], lat, lon) then return k end
  end
  for _, b in ipairs(M.BOXES) do
    if lat >= b[1] and lat <= b[3] and lon >= b[2] and lon <= b[4] then return b[5] end
  end
  return 'EU'
end

-- Pure: the stopping distance (m) of a train of `len` m and `kind` from v m/s: the reaction, the brake's build-up,
-- then the deceleration.
function M.stopping(v, kind, len)
  local k = M.KIND[kind] or M.KIND.freight
  local t = M.REACT_S + k.build + (len or 0) / 250
  return v * t + v * v / (2 * k.decel)
end

-- Pure: the aspect of a signal's lamps ({colour, across, up, flash}): 'stop' | 'rr30' | 'rr60' | 'r30' | 'warn' |
-- 'clear'.
function M.aspect(lamps)
  local red, yel, flash, across, up = 0, 0, false, false, false
  for _, l in ipairs(lamps or {}) do
    if l[1] == 'red' then red = red + 1
    elseif l[1] == 'yellow' then
      yel = yel + 1
      if l[4] then flash = true end
      if (l[2] or 0) ~= 0 then across = true end
      if (l[3] or 0) ~= 0 then up = true end
    end
  end
  if red > 0 then return 'stop' end
  if yel >= 2 and up then return flash and 'rr60' or 'rr30' end
  if yel >= 2 and across then return 'r30' end
  if yel == 1 then return 'warn' end
  return 'clear'
end

-- Pure: the restriction an aspect at d m makes: kmh, d (m to where it applies); nil for clear.
M.NEXT_M = 180            -- m from an advance signal to the main signal it announces (server SIGNAL_ADV_M - BACK_M)
function M.restrictionOf(aspect, d)
  if aspect == 'stop' then return 0, d end
  if aspect == 'rr30' then return 30, d end
  if aspect == 'rr60' then return 60, d end
  if aspect == 'r30' then return 30, d + M.NEXT_M end
  if aspect == 'warn' then return 0, d + M.NEXT_M end
  return nil
end

-- Pure: the most restrictive of restrictions {kmh, d} for a train at v m/s (the lowest speed allowed now).
function M.mostRestrictive(list, decel)
  local best, ba = nil, math.huge
  for _, r in ipairs(list) do
    local vt = r[1] / 3.6
    local a = math.sqrt(vt * vt + 2 * (decel or 0.6) * math.max(0, r[2] - 30))
    if a < ba then best, ba = r, a end
  end
  return best
end

-- Pure: the track ahead of (x, y) heading (hx, hy) along the rows (flat x, y, z), up to `len` m: a flat x, y list. At a
-- row's end the row starting (or ending) within JOIN_M that turns the least is followed (a turnout: the straightest
-- way, or `prefer(x, y)` scoring the candidates when given).
M.JOIN_M = 1.5
function M.ahead(rows, x, y, hx, hy, len)
  local best, bi, bd = nil, nil, 400
  for ri, row in ipairs(rows) do
    for i = 1, #row - 5, 3 do
      local x1, y1, x2, y2 = row[i], row[i + 1], row[i + 3], row[i + 4]
      local dx, dy = x2 - x1, y2 - y1
      local L2 = dx * dx + dy * dy
      if L2 > 1e-9 then
        local t = math.max(0, math.min(1, ((x - x1) * dx + (y - y1) * dy) / L2))
        local d = (x - x1 - t * dx) ^ 2 + (y - y1 - t * dy) ^ 2
        if d < bd then best, bi, bd = ri, i, d end
      end
    end
  end
  if not best then return {} end
  local out = { x, y }
  local row, i = rows[best], bi
  local dir = ((row[i + 3] - row[i]) * hx + (row[i + 4] - row[i + 1]) * hy) >= 0 and 1 or -1
  local used, s = { [best] = true }, 0
  local px, py = x, y
  local j = dir > 0 and i + 3 or i
  local guard = 0
  while s < len and guard < 20000 do
    guard = guard + 1
    if j >= 1 and j <= #row - 2 then
      local qx, qy = row[j], row[j + 1]
      s = s + math.sqrt((qx - px) ^ 2 + (qy - py) ^ 2)
      out[#out + 1] = qx; out[#out + 1] = qy
      px, py = qx, qy
      j = j + 3 * dir
    else
      -- the next row from this end
      local ex, ey = px, py
      local n = #out
      local tx, ty = out[n - 1] - (out[n - 3] or out[n - 1]), out[n] - (out[n - 2] or out[n])
      local tl = math.sqrt(tx * tx + ty * ty)
      if tl < 1e-6 then break end
      tx, ty = tx / tl, ty / tl
      local nb, nj, nd, ns = nil, nil, nil, -2
      for ri, r in ipairs(rows) do
        if not used[ri] and #r >= 6 then
          for _, e in ipairs({ { 1, 1 }, { #r - 2, -1 } }) do
            local k = e[1]
            if (r[k] - ex) ^ 2 + (r[k + 1] - ey) ^ 2 <= M.JOIN_M * M.JOIN_M then
              local k2 = k + 3 * e[2]
              local ux, uy = r[k2] - r[k], r[k2 + 1] - r[k + 1]
              local ul = math.sqrt(ux * ux + uy * uy)
              local sc = ul > 1e-6 and (ux * tx + uy * ty) / ul or -2
              if sc > ns then nb, nj, nd, ns = ri, k2, e[2], sc end
            end
          end
        end
      end
      if not nb or ns < 0.5 then break end
      used[nb] = true
      row, j, dir = rows[nb], nj, nd
    end
  end
  return out
end

-- Pure: the distance along a flat x, y line from its start to the foot of (x, y), and the offset; nil when off it.
function M.along(line, x, y, maxOff)
  local s, bs, bo = 0, nil, maxOff or M.ON_TRACK_M
  for i = 1, #line - 3, 2 do
    local x1, y1, x2, y2 = line[i], line[i + 1], line[i + 2], line[i + 3]
    local dx, dy = x2 - x1, y2 - y1
    local L = math.sqrt(dx * dx + dy * dy)
    if L > 1e-9 then
      local t = math.max(0, math.min(1, ((x - x1) * dx + (y - y1) * dy) / (L * L)))
      local o = math.sqrt((x - x1 - t * dx) ^ 2 + (y - y1 - t * dy) ^ 2)
      if o < bo then bs, bo = s + t * L, o end
    end
    s = s + L
  end
  return bs, bo
end

-- ---------------------------------------------------------------------------------------------- driving aids
M.reports = {}            -- [vehicle id] = { v, reg, allowed, alarm, trip }
M.limit = nil             -- { kmh, d, aspect } sent last
M.showPanel = true

local function playerRail()
  local p = ui and ui._playerPose and ui._playerPose()
  if not p or not p.rail then return nil end
  return p
end

local function tell(veh, cmd)
  if veh then pcall(function() veh:queueLuaCommand('if not nrailsDrive then extensions.load("nrailsDrive") end '
    .. 'if nrailsDrive then ' .. cmd .. ' end') end) end
end

function M.onReport(id, st)
  if type(st) == 'table' then M.reports[id] = st end
end

function M.regToggle()
  local p = playerRail()
  if not p then N._setStatus('NRails: monte dans un train / board a train'); return end
  local r = M.reports[p.id]
  if r and r.reg then
    tell(p.veh, 'nrailsDrive.setReg(nil)')
    M.regKmh = nil
    N._setStatus('NRails: regulateur off / cruise control off')
  else
    local kmh = math.max(10, math.floor((r and r.v or 0) * 3.6 / 5 + 0.5) * 5)
    M.regKmh = kmh
    tell(p.veh, string.format('nrailsDrive.setReg(%d)', kmh))
    N._setStatus(string.format('NRails: regulateur %d km/h / cruise control', kmh))
  end
end

function M.regStep(d)
  local p = playerRail()
  if not p then return end
  M.regKmh = math.max(5, math.min(300, (M.regKmh or 0) + d))
  tell(p.veh, string.format('nrailsDrive.setReg(%d)', M.regKmh))
  N._setStatus(string.format('NRails: regulateur %d km/h', M.regKmh))
end

-- The restrictions on the track ahead of p: { {kmh, d, aspect}, ... }.
function M.restrictions(p, tiles)
  local rows = route.rows(tiles)
  local line = M.ahead(rows, p.x, p.y, p.hx, p.hy, M.AHEAD_M)
  if #line < 4 then return {}, line end
  local cars = N.scene and N.scene() or {}
  local out = {}
  for _, t in pairs(tiles) do
    if t.railsig and not t.ghost then
      for _, s in ipairs(t.railsig) do
        local fx, fy = s.face and s.face[1] or 0, s.face and s.face[2] or 0
        local lx, ly = s.lamp[1], s.lamp[2]
        if (lx - p.x) ^ 2 + (ly - p.y) ^ 2 < M.AHEAD_M * M.AHEAD_M then
          local d, off = M.along(line, lx, ly, M.ON_TRACK_M)
          if d and d > 2 then
            -- (its face along the track there, the train's way)
            local i = 1
            local acc = 0
            for k = 1, #line - 3, 2 do
              local L = math.sqrt((line[k + 2] - line[k]) ^ 2 + (line[k + 3] - line[k + 1]) ^ 2)
              if acc + L >= d then i = k; break end
              acc = acc + L
            end
            local tx, ty = line[i + 2] - line[i], line[i + 3] - line[i + 1]
            if tx * fx + ty * fy > 0 then
              local lamps = switch.lamps(N._swById and N._swById[s.id], cars, s.kind or 'main', s.yard)
              if N.xing and N.xing.blocked(lx, ly, fx, fy) then lamps = { { 'red', -1, 0, false } } end
              local asp = M.aspect(lamps)
              local kmh, dd = M.restrictionOf(asp, d)
              if kmh then out[#out + 1] = { kmh, dd, asp } end
            end
          end
        end
      end
    end
  end
  return out, line
end

local lastSend = -1
function M.update(now, tiles)
  now = now or os.clock()
  if now - lastSend < M.SEND_S and now >= lastSend then return end
  lastSend = now
  local p = playerRail()
  if not p then M.limit = nil; return end
  local list = M.restrictions(p, tiles or {})
  local r = M.mostRestrictive(list)
  if r then
    M.limit = { kmh = r[1], d = r[2], aspect = r[3] }
    tell(p.veh, string.format('nrailsDrive.setLimit(%d, %.1f) nrailsDrive.report()', r[1], r[2]))
  else
    M.limit = nil
    tell(p.veh, 'nrailsDrive.setLimit(nil) nrailsDrive.report()')
  end
end

local ASPECT_TEXT = { stop = 'arret / stop', rr30 = 'RR30', rr60 = 'RR60', r30 = 'R30', warn = 'avertissement' }
function M.drawPanel()
  if not M.showPanel then return end
  local p = playerRail()
  local im = rawget(_G, 'ui_imgui')
  if not p or not im then return end
  local r = M.reports[p.id] or {}
  im.SetNextWindowBgAlpha(0.55)
  if im.Begin('NRails - conduite##nrdrive', nil, im.WindowFlags_AlwaysAutoResize + im.WindowFlags_NoCollapse) then
    im.TextUnformatted(string.format('Vitesse / speed : %d km/h', math.floor((r.v or 0) * 3.6 + 0.5)))
    im.TextUnformatted(r.reg and string.format('Regulateur : %d km/h (Ctrl+Shift+K)', math.floor(r.reg * 3.6 + 0.5))
      or 'Regulateur : off (Ctrl+Shift+K)')
    if M.limit then
      im.TextUnformatted(string.format('Controle : %s, %d km/h dans %d m', ASPECT_TEXT[M.limit.aspect] or '?',
        M.limit.kmh, math.floor(M.limit.d)))
      if r.allowed then im.TextUnformatted(string.format('  vitesse permise / allowed : %d km/h', math.floor(r.allowed * 3.6))) end
    else
      im.TextUnformatted('Controle : voie libre / clear')
    end
    if r.trip then im.TextColored(im.ImVec4(1, 0.2, 0.15, 1), 'FREINAGE D\'URGENCE / EMERGENCY BRAKE')
    elseif r.alarm then im.TextColored(im.ImVec4(1, 0.75, 0.1, 1), 'SURVITESSE / OVERSPEED') end
  end
  im.End()
end

-- ---------------------------------------------------------------------------------------------- configurator
M.cfgOn = false
M.kind = 'freight'
function M.toggleConfig() M.cfgOn = not M.cfgOn; return M.cfgOn end

local function vehInfo(v)
  local info = { id = v:getID(), jb = v:getJBeamFilename() }
  local ok, he = pcall(function() return v:getSpawnWorldOOBB():getHalfExtents() end)
  info.len = ok and he and 2 * math.max(he.x, he.y) or 15
  local okm, m = pcall(function()
    local vd = core_vehicle_manager.getVehicleData(info.id)
    local s = 0
    for _, n in pairs(vd.vdata.nodes or {}) do s = s + (n.nodeWeight or 0) end
    return s
  end)
  info.mass = okm and m and m > 0 and m or nil
  local p = v:getPosition()
  info.x, info.y = p.x, p.y
  return info
end

-- The consist: the rail vehicles chained to the player's (each within its neighbours' lengths + CHAIN_GAP_M).
function M.consist()
  local p = playerRail()
  if not p or not be then return {} end
  local all = {}
  for i = 0, be:getObjectCount() - 1 do
    local v = be:getObject(i)
    local ok, jb = pcall(function() return v:getJBeamFilename() end)
    if ok and N.isRailVehicle(jb) then
      local q = v:getPosition()
      if (q.x - p.x) ^ 2 + (q.y - p.y) ^ 2 < M.CONSIST_M ^ 2 then all[#all + 1] = vehInfo(v) end
    end
  end
  local inC, out = {}, {}
  for _, a in ipairs(all) do if a.id == p.id then inC[a.id] = true; out[1] = a end end
  if not out[1] then return {} end
  local grew = true
  while grew do
    grew = false
    for _, a in ipairs(all) do
      if not inC[a.id] then
        for _, b in ipairs(out) do
          local d = math.sqrt((a.x - b.x) ^ 2 + (a.y - b.y) ^ 2)
          if d <= (a.len + b.len) / 2 + M.CHAIN_GAP_M then inC[a.id] = true; out[#out + 1] = a; grew = true; break end
        end
      end
    end
  end
  -- (along the train: by the distance along the player's heading)
  table.sort(out, function(a, b) return (a.x - p.x) * p.hx + (a.y - p.y) * p.hy > (b.x - p.x) * p.hx + (b.y - p.y) * p.hy end)
  return out
end

M.LOCOS = { tem2 = true, ['6axle_train'] = true, train = true }
function M.summary(list, kind, country)
  local s = { n = #list, locos = 0, len = 0, mass = 0, massKnown = true }
  for _, v in ipairs(list) do
    if M.LOCOS[v.jb] then s.locos = s.locos + 1 end
    s.len = s.len + v.len
    if v.mass then s.mass = s.mass + v.mass else s.massKnown = false end
  end
  s.len = s.len + math.max(0, #list - 1) * 0.3
  local norm = M.NORMS[country] or M.NORMS.EU
  s.max = kind == 'passenger' and norm[2] or norm[1]
  s.normText = norm[3]
  s.over = s.max ~= nil and s.len > s.max
  return s
end

-- The builder: n vehicles of `model` behind the consist's tail, on the track, then coupled.
M.build = nil
function M.addBehind(model, n)
  local p = playerRail()
  if not p then N._setStatus('NRails: monte dans un train / board a train'); return false end
  local list = M.consist()
  local tail = list[#list] or { x = p.x, y = p.y, len = 15 }
  local rows = route.rows(N._roads.extTiles())
  local line = M.ahead(rows, tail.x, tail.y, -p.hx, -p.hy, (n + 2) * 30 + tail.len)
  if #line < 4 then N._setStatus('NRails: pas de voie derriere / no track behind'); return false end
  M.build = { model = model, n = math.min(n, M.BUILD_MAX), line = line, s = tail.len / 2 + M.BUILD_GAP_M, done = 0,
    ids = {}, hx = p.hx, hy = p.hy, wait = 0 }
  return true
end

-- Pure: the point and direction at s m along a flat x, y line.
function M.pointAt(line, s)
  local acc = 0
  for i = 1, #line - 3, 2 do
    local dx, dy = line[i + 2] - line[i], line[i + 3] - line[i + 1]
    local L = math.sqrt(dx * dx + dy * dy)
    if L > 1e-9 and acc + L >= s then
      local t = (s - acc) / L
      return line[i] + t * dx, line[i + 1] + t * dy, dx / L, dy / L
    end
    acc = acc + L
  end
  return nil
end

local function stepBuild()
  local b = M.build
  if not b then return end
  if b.pending then                          -- (the last one spawned: its length known, it is placed)
    local v = be:getObjectByID(b.pending)
    if not v then b.pending = nil; return end
    local info = vehInfo(v)
    local x, y, dx, dy = M.pointAt(b.line, b.s + info.len / 2)
    if not x then M.build = nil; return end
    local r = N.nearestRail(x, y, nil, 6)
    if r then
      local over = N._footprint and N._footprint(v) or 1.0
      local px, py, pz, ddx, ddy, ddz = N.railSnapPose(r, b.hx, b.hy, over, true)
      local dir = vec3(ddx, ddy, ddz)
      local rot = quatFromDir(-dir, (vec3(0, 0, 1) - dir * ddz):normalized())
      v:setPositionRotation(px, py, pz, rot.x, rot.y, rot.z, rot.w)
    end
    b.s = b.s + info.len + M.BUILD_GAP_M
    b.ids[#b.ids + 1] = b.pending
    b.pending = nil
    b.done = b.done + 1
    return
  end
  if b.done >= b.n then
    for _, id in ipairs(b.ids) do
      local v = be:getObjectByID(id)
      if v then pcall(function() v:queueLuaCommand(N.COUPLE_CMD) end) end
    end
    pcall(N.couple, true)
    N._setStatus(string.format('NRails: %d vehicule(s) ajoute(s) et attele(s) / added and coupled', b.done))
    M.build = nil
    return
  end
  local x, y = M.pointAt(b.line, b.s + 10)
  if not x then M.build = nil; N._setStatus('NRails: plus de voie / no more track'); return end
  local r = N.nearestRail(x, y, nil, 6)
  local z = r and r.z + 2 or 0
  local ok, v = pcall(function()
    return core_vehicles.spawnNewVehicle(b.model, { pos = vec3(x, y, z), rot = quat(0, 0, 0, 1), autoEnterVehicle = false })
  end)
  if ok and v then b.pending = v:getID() else M.build = nil; N._setStatus('NRails: echec du spawn / spawn failed') end
end

local lastBuild = -1
function M.drawConfig(now)
  now = now or os.clock()
  if M.build and now - lastBuild > 0.6 then lastBuild = now; pcall(stepBuild) end
  if not M.cfgOn then return end
  local im = rawget(_G, 'ui_imgui')
  if not im then return end
  M.cfgPtr = M.cfgPtr or im.BoolPtr(true)
  M.cfgPtr[0] = true
  if im.Begin('NRails - configurateur de train / train configurator##nrcfg', M.cfgPtr, im.WindowFlags_AlwaysAutoResize) then
    local p = playerRail()
    if not p then
      im.TextUnformatted('Monte dans un vehicule ferroviaire / board a rail vehicle')
    else
      local list = M.consist()
      local lat, lon = mapm._toLatLon(p.x, p.y)
      local country = lat and M.country(lat, lon) or 'EU'
      if radio(im, 'fret / freight##nrk1', M.kind == 'freight') then M.kind = 'freight' end
      im.SameLine()
      if radio(im, 'voyageurs / passenger##nrk2', M.kind == 'passenger') then M.kind = 'passenger' end
      local s = M.summary(list, M.kind, country)
      im.TextUnformatted(string.format('%d vehicule(s) : %d loco(s), %d voiture(s)/wagon(s)', s.n, s.locos, s.n - s.locos))
      im.TextUnformatted(string.format('Longueur totale / length : %.0f m', s.len))
      im.TextUnformatted(s.massKnown and string.format('Masse / mass : %.0f t', s.mass / 1000) or 'Masse : inconnue / unknown')
      if s.max then
        local txt = string.format('Norme (%s) : %d m max -> %s', country, s.max, s.over and 'TROP LONG / too long' or 'OK')
        if s.over then im.TextColored(im.ImVec4(1, 0.3, 0.2, 1), txt) else im.TextUnformatted(txt) end
      else
        im.TextUnformatted('Norme (' .. country .. ') : pas de limite')
      end
      im.TextUnformatted('  ' .. s.normText .. ' (valeurs indicatives)')
      im.Separator()
      im.TextUnformatted('Distance d\'arret predite / stopping distance:')
      local r = M.reports[p.id]
      for _, kmh in ipairs({ 40, 80, 100, 120, 160 }) do
        im.TextUnformatted(string.format('  %3d km/h : %5.0f m', kmh, M.stopping(kmh / 3.6, M.kind, s.len)))
      end
      if r and r.v and r.v > 1 then
        im.TextUnformatted(string.format('  maintenant / now (%d km/h) : %.0f m', math.floor(r.v * 3.6),
          M.stopping(r.v, M.kind, s.len)))
      end
      im.Separator()
      for i, v in ipairs(list) do
        im.TextUnformatted(string.format('%2d. %-14s %5.1f m%s', i, tostring(v.jb), v.len,
          v.mass and string.format('  %5.1f t', v.mass / 1000) or ''))
      end
      im.Separator()
      M.models = M.models or {}
      local names = {}
      for name in pairs(N.RAIL_VEHICLES) do names[#names + 1] = name end
      table.sort(names)
      M.modelIdx = M.modelIdx or 1
      im.TextUnformatted('Ajouter derriere / add behind:')
      for i, name in ipairs(names) do
        if radio(im, name .. '##nrm' .. i, M.modelIdx == i) then M.modelIdx = i end
        if i % 4 ~= 0 and i < #names then im.SameLine() end
      end
      M.countPtr = M.countPtr or im.IntPtr(3)
      im.PushItemWidth(160)
      im.SliderInt('nombre / count##nrc', M.countPtr, 1, 30)
      im.PopItemWidth()
      im.SameLine()
      if M.build then
        im.TextUnformatted(string.format('ajout %d/%d...', M.build.done, M.build.n))
      elseif im.Button('Ajouter / add##nradd') and names[M.modelIdx] then
        M.addBehind(names[M.modelIdx], M.countPtr[0])
      end
    end
  end
  im.End()
  if not M.cfgPtr[0] then M.cfgOn = false end
end

return M
