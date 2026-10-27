-- BeamNG.NRails: the driver's screens (the user's run, 2026-10-26): the turnout diagram (Ctrl+Shift+M: shown until
-- pressed again, stopped too; its branches clickable, every turnout round the train settable, an itinerary to a
-- point clicked on a track), the light signals before the turnouts, the keys' window shown when boarding a train
-- (with "do not show again"), the coupling assistant. nrails.lua calls it (init, update, drawHelp, drawSchema).
local M = {}

local N, roads, switch, route = nil, nil, nil, nil
local function status(s) if N and N._setStatus then N._setStatus(s) end end

M.PREFS_FILE = '/settings/beamngEarth/nrails_prefs.json'
M.prefs = { hideKeys = false, schema = true, view = 'area', zoom = 350, guide = false, guideStrength = 0.6 }
M.W, M.H = 340, 200
M.ZOOMS = { 150, 250, 350, 600, 1000 }
M.SCHEMA_ARM_M = 150
M.ARM_DRAW_M = 70       -- m of each route's arm drawn past its zone
M.CACHE_S = 1.0
M.CLICK_PX = 10
M.ARRIVE_M = 30
M.SIGNAL_DRAW_M = 900
M.COUPLE_S = 60

function M.init(nrails)
  N = nrails
  roads = nrails._roads
  switch = nrails.switch
  route = require('beamngEarth/nrailsroute')
  M.loadPrefs()
end

function M.loadPrefs()
  local rd = rawget(_G, 'jsonReadFile')
  if not rd then return end
  local ok, p = pcall(rd, M.PREFS_FILE)
  if ok and type(p) == 'table' then
    for k, v in pairs(p) do M.prefs[k] = v end
  end
end

function M.savePrefs()
  local wr = rawget(_G, 'jsonWriteFile')
  if wr then pcall(wr, M.PREFS_FILE, M.prefs, true) end
end

-- Pure: flat x, y list -> diagram points: u along dir from at, v to its left, scale px/m, ox the node's place (0..1).
function M.xy(flat, at, dir, scale, w, h, ox, every)
  local out = {}
  every = every or 1
  ox = ox or 0.5
  for i = 1, #flat - 1, 2 * every do
    local rx, ry = flat[i] - at[1], flat[i + 1] - at[2]
    local u = rx * dir[1] + ry * dir[2]
    local v = -rx * dir[2] + ry * dir[1]
    out[#out + 1] = { w * ox + u * scale, h * 0.5 - v * scale }
  end
  return out
end

-- Pure: a diagram point back to the world.
function M.inv(sx, sy, at, dir, scale, w, h, ox)
  local u = (sx - w * (ox or 0.5)) / scale
  local v = (h * 0.5 - sy) / scale
  return at[1] + u * dir[1] - v * dir[2], at[2] + u * dir[2] + v * dir[1]
end

-- Pure: the distance (px) from (x, y) to the diagram polyline pts.
function M.pxDist(x, y, pts)
  local best = math.huge
  for i = 1, #pts - 1 do
    local a, b = pts[i], pts[i + 1]
    local dx, dy = b[1] - a[1], b[2] - a[2]
    local l2 = dx * dx + dy * dy
    local t = l2 > 0 and math.max(0, math.min(1, ((x - a[1]) * dx + (y - a[2]) * dy) / l2)) or 0
    local ex, ey = a[1] + t * dx - x, a[2] + t * dy - y
    local d = math.sqrt(ex * ex + ey * ey)
    if d < best then best = d end
  end
  return best
end

-- Pure: a route's drawn line: its zone and ARM_DRAW_M of its arm past it (flat x, y).
function M.routeLine(r)
  local out = {}
  for _, v in ipairs(r.line or {}) do out[#out + 1] = v end
  local arm = r.arm or {}
  if #out >= 2 and #arm >= 4 then
    local ex, ey = out[#out - 1], out[#out]
    local s, started = 0, false
    local px, py = arm[1], arm[2]
    for i = 3, #arm - 1, 2 do
      local x, y = arm[i], arm[i + 1]
      s = s + math.sqrt((x - px) ^ 2 + (y - py) ^ 2)
      px, py = x, y
      if not started and (x - ex) ^ 2 + (y - ey) ^ 2 < 9 then started = true end
      if started then out[#out + 1] = x; out[#out + 1] = y end
      if s > M.ARM_DRAW_M + 120 then break end
    end
  end
  return out
end

-- The player's train: position, heading (its motion, or the way it faces when stopped), whether it is a rail one.
local function playerPose()
  local veh = rawget(_G, 'getPlayerVehicle') and getPlayerVehicle(0)
  if not veh then return nil end
  local okp, p = pcall(function() return veh:getPosition() end)
  if not okp or not p then return nil end
  local hx, hy = 0, 0
  local okv, v = pcall(function() return veh:getVelocity() end)
  if okv and v and (v.x * v.x + v.y * v.y) > 1 then hx, hy = v.x, v.y
  else
    local okd, d = pcall(function() return veh:getDirectionVector() end)
    if okd and d then hx, hy = d.x, d.y end
  end
  local l = math.sqrt(hx * hx + hy * hy)
  if l < 1e-6 then hx, hy, l = 1, 0, 1 end
  local okj, jb = pcall(function() return veh:getJBeamFilename() end)
  return { veh = veh, x = p.x, y = p.y, z = p.z, hx = hx / l, hy = hy / l,
    rail = okj and N.isRailVehicle and N.isRailVehicle(jb) or false, id = veh.getID and veh:getID() }
end
M._playerPose = playerPose

-- ---------------------------------------------------------------------------------------------------------- keys
M.helpHide = nil
function M.drawHelp()
  if not N.helpOn then return end
  local im = rawget(_G, 'ui_imgui')
  if not im then return end
  M.helpPtr = M.helpPtr or im.BoolPtr(true)
  M.helpPtr[0] = true
  M.helpHide = M.helpHide or im.BoolPtr(M.prefs.hideKeys == true)
  if im.Begin('NRails - touches / keys##nrailshelp', M.helpPtr, im.WindowFlags_AlwaysAutoResize) then
    for _, k in ipairs(N.KEYS) do
      im.TextUnformatted(k[1]); im.SameLine(170); im.TextUnformatted(k[2])
    end
    if im.Button('Atteler / couple') then N.couple(true) end
    im.SameLine()
    if im.Button('Deteler / uncouple') then N.couple(false) end
    im.SameLine()
    if im.Button('Schema') then M.toggleSchema() end
    im.SameLine()
    if im.Button('Configurateur##nrcfgb') and N.toggleConfig then N.toggleConfig() end
    im.SameLine()
    local gOn = N.guide and N.guide.on
    if im.Button(gOn and 'Guidage : on##nrguide' or 'Guidage : off##nrguide') then N.toggleGuide() end
    if N.guide then
      M.strPtr = M.strPtr or im.FloatPtr(N.guide.STRENGTH or 0.6)
      im.PushItemWidth(260)
      if im.SliderFloat('puissance du guidage / guidance strength##nrgs', M.strPtr, 0, 1, '%.2f') then
        N.guide.setStrength(M.strPtr[0])
      end
      im.PopItemWidth()
      if im.IsItemDeactivatedAfterEdit and im.IsItemDeactivatedAfterEdit() then
        M.prefs.guideStrength = N.guide.STRENGTH
        M.savePrefs()
      end
      im.TextUnformatted('  0 : sans effet / none  -  1 : bogies tenus sur les rails / held on the rails')
    end
    if im.Checkbox('Ne plus afficher en montant dans un train / do not show when boarding', M.helpHide) then
      M.prefs.hideKeys = M.helpHide[0] == true
      M.savePrefs()
    end
  end
  im.End()
  if not M.helpPtr[0] then N.helpOn = false end
end

-- ------------------------------------------------------------------------------------------------------- diagram
M.visible = false
function M.toggleSchema()
  M.visible = not M.visible
  M.prefs.schema = M.visible
  M.savePrefs()
  status('NRails: schema ' .. (M.visible and 'affiche / on' or 'masque / off'))
  return M.visible
end

local cache = { at = -1 }
local function worldCache(p, now)
  local R = (M.prefs.zoom or 350) * 1.6
  if cache.at >= 0 and now - cache.at < M.CACHE_S and cache.R == R
      and (cache.x - p.x) ^ 2 + (cache.y - p.y) ^ 2 < 2500 then
    return cache
  end
  local lines = {}
  for _, t in pairs(roads.extTiles()) do
    if t.railLines and not t.ghost then
      for _, row in ipairs(t.railLines) do
        local flat, lx, ly = {}, nil, nil
        local near = false
        for i = 1, #row - 2, 3 do
          local x, y = row[i], row[i + 1]
          if (x - p.x) ^ 2 + (y - p.y) ^ 2 < R * R then near = true end
          if not lx or (x - lx) ^ 2 + (y - ly) ^ 2 > 64 or i >= #row - 2 then
            flat[#flat + 1] = x; flat[#flat + 1] = y; lx, ly = x, y
          end
        end
        if near and #flat >= 4 then lines[#lines + 1] = flat end
      end
    end
  end
  local sws = {}
  for _, sw in ipairs(N._swList or {}) do
    if (sw.at[1] - p.x) ^ 2 + (sw.at[2] - p.y) ^ 2 < R * R then sws[#sws + 1] = sw end
  end
  cache = { at = now, R = R, x = p.x, y = p.y, lines = lines, sws = sws }
  return cache
end

local cols = {}
local function col(im, r, g, b, a)
  local k = r * 1e6 + g * 1e4 + b * 1e2 + (a or 1)
  local c = cols[k]
  if not c then c = im.GetColorU322(im.ImVec4(r, g, b, a or 1)); cols[k] = c end
  return c
end

M.itin = nil            -- { path, tx, ty, ids = {id = true} }

function M.clearPlan()
  switch.plan = {}
  M.itin = nil
  status('NRails: choix et itineraire effaces / plan cleared')
end

function M.setItinerary(p, wx, wy)
  local g = route.graph(route.rows(roads.extTiles()))
  local path = route.find(g, p.x, p.y, p.hx, p.hy, wx, wy)
  if not path then
    status('NRails: pas d\'itineraire (demi-tour impossible ou voie non chargee) / no way there')
    return nil
  end
  local n = M.planPath(path, wx, wy)
  status(string.format('NRails: itineraire %d m, %d aiguillage(s) regle(s) / itinerary set', math.floor(route.length(path)), n))
  return M.itin
end

-- The turnouts on a way (a list of points) set for it (switch.plan; the last itinerary's choices dropped first): the
-- itinerary M.itin. Returns how many turnouts.
function M.planPath(path, wx, wy)
  if M.itin then for id in pairs(M.itin.ids) do switch.plan[id] = nil end end
  local ch = route.choices(N._swList or {}, path)
  local n = 0
  local ids = {}
  for id, idx in pairs(ch) do switch.plan[id] = idx; ids[id] = true; n = n + 1 end
  M.itin = { path = path, tx = wx, ty = wy, ids = ids }
  return n
end

-- A click at diagram point (sx, sy): a turnout's branch chosen, else an itinerary to the track there. Pure but for
-- what it sets (switch.plan, M.itin). view: { at, dir, scale, ox, sws, lines }.
function M.click(sx, sy, view, p)
  local best, bd, bsw = nil, M.CLICK_PX, nil
  for _, sw in ipairs(view.sws or {}) do
    for i, r in ipairs(sw.routes or {}) do
      local d = M.pxDist(sx, sy, M.xy(M.routeLine(r), view.at, view.dir, view.scale, M.W, M.H, view.ox))
      if d < bd then best, bd, bsw = i, d, sw end
    end
  end
  if bsw then
    switch.choose(bsw, best)
    local n = #(bsw.routes or {})
    local word = (best == (bsw.def or 0) + 1) and 'principale' or (best == 1 and 'gauche') or (best == n and 'droite') or 'milieu'
    status('NRails: aiguillage -> ' .. word .. ' (des que libre) / turnout set')
    return 'switch', bsw, best
  end
  local near = false
  for _, flat in ipairs(view.lines or {}) do
    if M.pxDist(sx, sy, M.xy(flat, view.at, view.dir, view.scale, M.W, M.H, view.ox)) <= M.CLICK_PX then near = true; break end
  end
  if near and p then
    local wx, wy = M.inv(sx, sy, view.at, view.dir, view.scale, M.W, M.H, view.ox)
    return 'itinerary', M.setItinerary(p, wx, wy)
  end
  return nil
end

function M.drawSchema(now)
  if not M.visible then return end
  local im = rawget(_G, 'ui_imgui')
  if not im or not im.GetWindowDrawList then return end
  local p = playerPose()
  if not p then return end
  now = now or os.clock()
  local wc = worldCache(p, now)
  local nf = N._nextFacing
  local W, H = M.W, M.H
  local view
  if M.prefs.view == 'turnout' and nf and nf.sw then
    local sw = nf.sw
    view = { at = sw.at, dir = sw.dir, scale = W / (M.SCHEMA_ARM_M + 80), ox = 0.35, sws = { sw }, lines = {} }
  else
    local R = M.prefs.zoom or 350
    view = { at = { p.x, p.y }, dir = { p.hx, p.hy }, scale = W / (2 * R), ox = 0.5, sws = wc.sws, lines = wc.lines }
  end
  M._view = view
  M.ptr = M.ptr or im.BoolPtr(true)
  M.ptr[0] = true
  im.SetNextWindowBgAlpha(0.8)
  local title = nf and string.format('NRails - aiguillage dans %d m##nrailsschema', math.floor(nf.dist))
    or 'NRails - voies / tracks##nrailsschema'
  if im.Begin(title, M.ptr, im.WindowFlags_AlwaysAutoResize + (im.WindowFlags_NoFocusOnAppearing or 0)) then
    if im.Button(M.prefs.view == 'turnout' and 'Vue zone' or 'Vue aiguillage') then
      M.prefs.view = M.prefs.view == 'turnout' and 'area' or 'turnout'; M.savePrefs()
    end
    im.SameLine()
    if im.Button(' - ') then
      for i, z in ipairs(M.ZOOMS) do if z == M.prefs.zoom and i < #M.ZOOMS then M.prefs.zoom = M.ZOOMS[i + 1]; break end end
      M.savePrefs()
    end
    im.SameLine()
    if im.Button(' + ') then
      for i, z in ipairs(M.ZOOMS) do if z == M.prefs.zoom and i > 1 then M.prefs.zoom = M.ZOOMS[i - 1]; break end end
      M.savePrefs()
    end
    im.SameLine()
    if im.Button('Effacer / clear') then M.clearPlan() end
    local o = im.GetCursorScreenPos()
    local clicked = im.InvisibleButton('##nrailsschemacanvas', im.ImVec2(W, H))
    local dl = im.GetWindowDrawList()
    im.ImDrawList_AddRectFilled(dl, im.ImVec2(o.x, o.y), im.ImVec2(o.x + W, o.y + H), col(im, 0.08, 0.09, 0.1, 0.9))
    local function poly(pts, c, th)
      for i = 1, #pts - 1 do
        local a, b = pts[i], pts[i + 1]
        if a[1] > -W and a[1] < 2 * W and b[1] > -W and b[1] < 2 * W and a[2] > -H and a[2] < 2 * H then
          im.ImDrawList_AddLine(dl, im.ImVec2(o.x + a[1], o.y + a[2]), im.ImVec2(o.x + b[1], o.y + b[2]), c, th)
        end
      end
    end
    im.ImDrawList_PushClipRect(dl, im.ImVec2(o.x, o.y), im.ImVec2(o.x + W, o.y + H), true)
    local grey = col(im, 0.5, 0.5, 0.5, 0.9)
    for _, flat in ipairs(view.lines) do poly(M.xy(flat, view.at, view.dir, view.scale, W, H, view.ox), grey, 1.5) end
    if M.itin and M.itin.path then
      local flat = {}
      for _, q in ipairs(M.itin.path) do flat[#flat + 1] = q[1]; flat[#flat + 1] = q[2] end
      poly(M.xy(flat, view.at, view.dir, view.scale, W, H, view.ox), col(im, 0.2, 0.8, 1.0, 0.8), 5)
    end
    local green, yellow, white = col(im, 0.2, 0.9, 0.3), col(im, 1.0, 0.85, 0.1), col(im, 0.85, 0.85, 0.85, 0.9)
    local pend = nf and nf.sw and switch.pending and switch.pick(nf.sw, switch.pending) or nil
    for _, sw in ipairs(view.sws) do
      local cur = switch.current(sw)
      local plan = switch.plan[sw.id]
      for i, r in ipairs(sw.routes or {}) do
        local pts = M.xy(M.routeLine(r), view.at, view.dir, view.scale, W, H, view.ox)
        if i ~= cur then
          local want = (plan == i) or (nf and nf.sw == sw and pend == i)
          poly(pts, want and yellow or white, want and 3.5 or 2)
        end
      end
      local r = sw.routes and sw.routes[cur]
      if r then poly(M.xy(M.routeLine(r), view.at, view.dir, view.scale, W, H, view.ox), green, 4.5) end
      if sw.trunk and view.ox == 0.35 then poly(M.xy(sw.trunk, view.at, view.dir, view.scale, W, H, view.ox), white, 3) end
    end
    local q = M.xy({ p.x, p.y }, view.at, view.dir, view.scale, W, H, view.ox)[1]
    if q then
      local blue = col(im, 0.3, 0.6, 1.0)
      im.ImDrawList_AddCircleFilled(dl, im.ImVec2(o.x + q[1], o.y + q[2]), 5, blue, 12)
      local q2 = M.xy({ p.x + p.hx * 12 / view.scale, p.y + p.hy * 12 / view.scale }, view.at, view.dir, view.scale, W, H, view.ox)[1]
      im.ImDrawList_AddLine(dl, im.ImVec2(o.x + q[1], o.y + q[2]), im.ImVec2(o.x + q2[1], o.y + q2[2]), blue, 2)
    end
    im.ImDrawList_PopClipRect(dl)
    if clicked then
      local m = im.GetMousePos()
      pcall(M.click, m.x - o.x, m.y - o.y, view, p)
    end
    local line = 'Clic : branche = aiguillage, voie grise = itineraire'
    if nf and nf.sw then
      local sw = nf.sw
      local n, cur = #(sw.routes or {}), switch.current(sw)
      local w = (cur == (sw.def or 0) + 1) and 'principale' or (cur == 1 and 'gauche') or (cur == n and 'droite') or 'milieu'
      line = string.format('Prochain aiguillage %d m : %s', math.floor(nf.dist), w)
    end
    if M.itin and M.itin.path then line = line .. string.format('   itineraire %d m', math.floor(route.length(M.itin.path))) end
    im.TextUnformatted(line)
  end
  im.End()
  if not M.ptr[0] then M.visible = false; M.prefs.schema = false; M.savePrefs() end
end

-- ------------------------------------------------------------------------------------------------------- signals
local sigCache = { at = -1, rows = {} }
local ASPECT = { green = { 0.1, 1.0, 0.25 }, yellow = { 1.0, 0.8, 0.05 }, red = { 1.0, 0.08, 0.05 },
  white = { 1.0, 1.0, 0.95 }, violet = { 0.62, 0.2, 1.0 } }
M.LAMP_STEP_M = 0.16      -- m between two lamps on a target (side by side, one over the other)
M.FLASH_S = 1.0           -- a flashing light's period (on half of it)
function M.drawSignals(now)
  local dd = rawget(_G, 'debugDrawer')
  local CF = rawget(_G, 'ColorF')
  if not dd or not CF or not N._swById then return end
  local p = playerPose()
  if not p then return end
  now = now or os.clock()
  if now - sigCache.at > 1.0 then
    local rows = {}
    for _, t in pairs(roads.extTiles()) do
      if t.railsig and not t.ghost then
        for _, s in ipairs(t.railsig) do
          if (s.lamp[1] - p.x) ^ 2 + (s.lamp[2] - p.y) ^ 2 < M.SIGNAL_DRAW_M ^ 2 then rows[#rows + 1] = s end
        end
      end
    end
    sigCache = { at = now, rows = rows }
  end
  local cars = N.scene and N.scene() or {}
  local flashOn = (now % M.FLASH_S) < M.FLASH_S / 2
  for _, s in ipairs(sigCache.rows) do
    local fx, fy = s.face and s.face[1] or 1, s.face and s.face[2] or 0
    local ax, ay = -fy, fx                      -- (across the target)
    local small = s.yard and 0.6 or 1.0
    local lamps = switch.lamps(N._swById[s.id], cars, s.kind or 'main', s.yard)
    if N.xing and N.xing.blocked(s.lamp[1], s.lamp[2], fx, fy) then   -- (a level crossing occupied ahead: carre)
      lamps = { { 'red', -1, 0, false }, { 'red', 1, 0, false } }
    end
    for _, l in ipairs(lamps) do
      if not l[4] or flashOn then
        local c = ASPECT[l[1]] or ASPECT.red
        local d = M.LAMP_STEP_M * small
        local pos = vec3(s.lamp[1] + ax * l[2] * d, s.lamp[2] + ay * l[2] * d, s.lamp[3] + l[3] * d * 1.4)
        pcall(function()
          dd:drawSphere(pos, 0.075 * small, CF(c[1], c[2], c[3], 1))
          dd:drawSphere(pos, 0.2 * small, CF(c[1], c[2], c[3], 0.2))
        end)
      end
    end
  end
end

-- ------------------------------------------------------------------------------------------------------- coupling
M.coupling = nil
local function halfLen(v)
  local ok, hl = pcall(function()
    local b = v:getSpawnWorldOOBB()
    local e = b:getHalfExtents()
    return math.max(e.x, e.y)
  end)
  return ok and hl or nil
end

-- The gap (m) from the player's vehicle to the nearest other rail vehicle (ends to ends when their boxes are known).
function M.couplingGap()
  local p = playerPose()
  if not p or not be or not be.getObjectCount then return nil end
  local best, bv = math.huge, nil
  for i = 0, be:getObjectCount() - 1 do
    local v = be:getObject(i)
    local okI, id = pcall(function() return v:getID() end)
    local okJ, jb = pcall(function() return v:getJBeamFilename() end)
    if okI and id ~= p.id and okJ and N.isRailVehicle(jb) then
      local q = v:getPosition()
      local d = math.sqrt((q.x - p.x) ^ 2 + (q.y - p.y) ^ 2)
      if d < best then best, bv = d, v end
    end
  end
  if not bv then return nil end
  local a, b = halfLen(p.veh), halfLen(bv)
  if a and b then return math.max(0, best - a - b), true, bv end
  return best, false, bv
end

-- In reach (COUPLE_REACH_M ends to ends): both vehicles asked to attach again (their coupler radius is 2-2.4 m: the
-- first ask, made when the coupling was armed far away, found nothing).
M.COUPLE_REACH_M = 2.5
local function askAttach(p, bv)
  for _, v in ipairs({ p and p.veh, bv }) do
    if v then pcall(function() v:queueLuaCommand(N.COUPLE_CMD) end) end
  end
end

function M.onCouple(on, n)
  if on then
    M.coupling = { untilT = os.clock() + M.COUPLE_S, next = 0 }
  else
    M.coupling = nil
  end
end

local function couplingStatus(now)
  local c = M.coupling
  if not c then return end
  if now > c.untilT then M.coupling = nil; return end
  if now < c.next then return end
  c.next = now + 0.5
  local gap, ends, bv = M.couplingGap()
  if not gap then status('NRails: attelage arme, aucun vehicule ferroviaire proche / no rail vehicle near'); return end
  if ends and gap <= M.COUPLE_REACH_M then askAttach(playerPose(), bv) end
  if ends then
    if gap <= 0.4 then
      c.touching = (c.touching or 0) + 1
      if c.touching == 1 then status('NRails: attelage en contact, accrochage / couplers touching, attaching') end
      if c.touching >= 4 then M.coupling = nil end       -- (asked 4 times in contact: done, no more lines in the log)
    elseif gap <= 2 then status(string.format('NRails: attelage dans %.1f m, avance doucement / coupling in reach', gap))
    else status(string.format('NRails: attelage arme %d s : approche a moins de 2 m (ecart %.0f m) / come within 2 m', math.floor(c.untilT - now), gap)) end
  else
    status(string.format('NRails: attelage arme %d s : approche-toi doucement du vehicule (%.0f m entre centres)', math.floor(c.untilT - now), gap))
  end
end

-- ------------------------------------------------------------------------------------------------------- update
M._lastVeh = nil
function M.update(now)
  now = now or os.clock()
  local p = playerPose()
  local id = p and p.id
  if id ~= M._lastVeh then                     -- boarding a train: the keys and the diagram
    M._lastVeh = id
    if p and p.rail then
      if not M.prefs.hideKeys then N.helpOn = true end
      if M.prefs.schema ~= false then M.visible = true end
    end
  end
  if M.itin and p and (p.x - M.itin.tx) ^ 2 + (p.y - M.itin.ty) ^ 2 < M.ARRIVE_M ^ 2 then
    for sid in pairs(M.itin.ids) do switch.plan[sid] = nil end
    M.itin = nil
    status('NRails: arrive / itinerary done')
  end
  couplingStatus(now)
  pcall(M.drawSignals, now)
end

return M
