-- BeamNG.EarthNRails: the railway in the road tiles (server/nrails). Everything the fork adds to the mod lives here;
-- upstream's files only carry short hooks marked "NRails hook" (roads.lua: M.EXT_KINDS / M.ext / M.extQueue /
-- M.extRemake; core.lua: require + init; ui.lua: the "Snap to rail" button).
--
-- A road tile's railway meshes: "rail".."rail4" drawn only, "railcol".."railcol4" a collision detail (the rails' and
-- the ballast's boxes, never drawn), "railtun" the rail tunnels' tubes and portals (drawn and colliding), "railx" the
-- level crossings' inner slabs: drawn always, solid only while no rail vehicle is within RAILX_CLEAR_M of one of the
-- tile's crossings (the rail mods' wheelsets carry a 1.37 m "flange disc" that fills the space between the rails: a
-- slab there would stop the train).
local M = {}

local roads = require('beamngEarth/roads')
local stopwatch = require('beamngEarth/stopwatch')

-- (the collision in parts of ~5k triangles at most, up to 12: the engine's static collision rebuild took 5-22 s per
-- rebuild with a 20k-triangle railcol or a 62k-triangle terrain patch in, 2026-10-24)
M.KINDS = { 'rail', 'rail2', 'rail3', 'rail4', 'railx', 'railtun' }
for k = 1, 12 do M.KINDS[#M.KINDS + 1] = k == 1 and 'railcol' or ('railcol' .. k) end
-- the turnouts' routes' rails in their switch zones (nrailsswitch.lua): collision only, solid for the set route
M.SW_MAX = 48
for k = 1, M.SW_MAX do M.KINDS[#M.KINDS + 1] = 'railsw' .. k end
local switch = require('beamngEarth/nrailsswitch')
M.switch = switch
M.MATERIAL_FILE = '/levels/beamng_earth/art/shapes/beamngEarth/rails.materials.json'
-- the rail vehicles by jbeam name (the rail mods: TEM2, FS30-2 "6axle_train", the tank wagon, DMM512 "train"); more
-- in the user's settings file (M.loadVehicleList: settings/beamngEarth/nrails_vehicles.json, the Hub writes it)
M.RAIL_VEHICLES = { tem2 = true, ['6axle_train'] = true, tank = true, train = true }
M.VEHICLES_FILE = '/settings/beamngEarth/nrails_vehicles.json'
M.RAILX_CLEAR_M = 150
M.RAILX_CHECK_S = 0.5

local function isSw(what) return what:sub(1, 6) == 'railsw' end
local function isCol(what) return what:sub(1, 7) == 'railcol' or isSw(what) end
local function isDrawnOnly(what) return what:sub(1, 4) == 'rail' and not isCol(what) and what ~= 'railx'
  and what ~= 'railtun' end
M._isCol, M._isDrawnOnly = isCol, isDrawnOnly

local setStatus = function() end

-- The rail vehicles' jbeam names from the settings file ({"vehicles": ["name", ...]}), added to the built-in ones.
function M.loadVehicleList(read)
  read = read or function(p) return readFile and readFile(p) end
  local ok, text = pcall(read, M.VEHICLES_FILE)
  if not ok or type(text) ~= 'string' or text == '' then return 0 end
  local ok2, data = pcall(jsonDecode, text)
  if not ok2 or type(data) ~= 'table' or type(data.vehicles) ~= 'table' then return 0 end
  local n = 0
  for _, name in ipairs(data.vehicles) do
    if type(name) == 'string' and name ~= '' and not M.RAIL_VEHICLES[name] then M.RAIL_VEHICLES[name] = true; n = n + 1 end
  end
  return n
end

-- Is the jbeam name a rail vehicle's (M.RAIL_VEHICLES)?
function M.isRailVehicle(jbeam) return jbeam ~= nil and M.RAIL_VEHICLES[jbeam] == true end

-- roads.ext.onTile: a road tile's railway meshes queued (render-only, colliding, the crossings' slabs)
local function onTile(key, t, data)
  if type(data.rail_lines) == 'table' and data.rail_lines[1] then t.railLines = data.rail_lines end   -- (snapToRail)
  if type(data.railx_pts) == 'table' and data.railx_pts[1] then
    t.railxPts = data.railx_pts
    t.railxSolid = not M.railVehicleNear(t.railxPts)
  end
  -- the turnouts: which route of which turnout each "railswN" shape is
  t.swOf, t.swWalk = {}, {}
  if type(data.railsw) == 'table' and data.railsw[1] then
    t.railsw = data.railsw
    for _, sw in ipairs(data.railsw) do
      for i, r in ipairs(sw.routes or {}) do
        if r.what then t.swOf[r.what] = { sw = sw, idx = i } end
      end
    end
  end
  for _, what in ipairs(M.KINDS) do
    local w = data[what]
    if type(w) == 'table' and w.shape and type(w.pos) == 'table' then
      if what == 'railx' then t.railxWalk = w end
      local off = false
      if isSw(what) then
        t.swWalk[what] = w
        local o = t.swOf[what]
        off = o ~= nil and switch.current(o.sw) ~= o.idx      -- (not the set route: not solid)
      end
      roads.extQueue(key, t, what, w, isDrawnOnly(what) or off or (what == 'railx' and t.railxSolid == false))
    end
  end
end

-- A turnout set to route idx: its routes' shapes in every tile made again, the set one solid.
function M.setSwitch(id, idx)
  switch.state[id] = idx
  for key, t in pairs(roads.extTiles()) do
    if t.swOf and not t.ghost then
      for what, o in pairs(t.swOf) do
        if o.sw.id == id and t.swWalk[what] then roads.extRemake(key, t, what, t.swWalk[what], o.idx ~= idx) end
      end
    end
  end
end

-- The player's choice for the next turnout ahead ('left' | 'straight' | 'right'; the keys).
local CHOICE_TEXT = { left = 'a gauche / left', straight = 'tout droit / straight', right = 'a droite / right' }
function M.setNext(choice)
  switch.pending = choice
  setStatus('NRails: prochain aiguillage ' .. (CHOICE_TEXT[choice] or tostring(choice)))
end

-- Every SW_CHECK_S: the player's vehicle against the turnouts near it (nrailsswitch.step).
M.SW_CHECK_S = 0.25
local sinceSw = stopwatch.new()
function M.updateSwitches()
  if sinceSw() < M.SW_CHECK_S * 1000 then return end
  sinceSw = stopwatch.new()
  local veh = rawget(_G, 'getPlayerVehicle') and getPlayerVehicle(0)
  if not veh then return end
  local p = veh:getPosition()
  local v = veh.getVelocity and veh:getVelocity() or { x = 0, y = 0 }
  local _, list = switch.collect(roads.extTiles())
  if not list[1] then return end
  local changes, used = switch.step(list, { x = p.x, y = p.y, vx = v.x or 0, vy = v.y or 0 })
  for id, idx in pairs(changes) do M.setSwitch(id, idx) end
  if used then
    switch.pending = nil
    setStatus('NRails: aiguillage regle / turnout set')
  end
end

-- The positions of the rail vehicles (M.RAIL_VEHICLES by jbeam name) in the scene.
local function railVehiclePositions()
  local out = {}
  if not be or not be.getObjectCount then return out end
  for i = 0, be:getObjectCount() - 1 do
    local v = be:getObject(i)
    local ok, jb = pcall(function() return v:getJBeamFilename() end)
    if ok and jb and M.RAIL_VEHICLES[jb] then out[#out + 1] = v:getPosition() end
  end
  return out
end
M._railVehiclePositions = railVehiclePositions

-- Is a rail vehicle within RAILX_CLEAR_M of one of the crossing centres pts ({x, y, z} rows)? (positions: optional)
function M.railVehicleNear(pts, positions)
  positions = positions or railVehiclePositions()
  local r2 = M.RAILX_CLEAR_M * M.RAILX_CLEAR_M
  for _, p in ipairs(positions) do
    for _, c in ipairs(pts or {}) do
      local dx, dy = p.x - c[1], p.y - c[2]
      if dx * dx + dy * dy <= r2 then return true end
    end
  end
  return false
end

-- roads.ext.update, every RAILX_CHECK_S: a tile whose crossings got (or lost) a rail vehicle near has its inner slabs
-- made again, solid or render-only (a TSStatic's collision type is only read when it is made).
local sinceRailx = stopwatch.new()
function M.updateRailCrossings()
  if sinceRailx() < M.RAILX_CHECK_S * 1000 then return end
  sinceRailx = stopwatch.new()
  local positions = nil
  for key, t in pairs(roads.extTiles()) do
    if t.railxPts and t.railxWalk and not t.ghost then
      positions = positions or railVehiclePositions()
      local solid = not M.railVehicleNear(t.railxPts, positions)
      if solid ~= t.railxSolid then
        t.railxSolid = solid
        roads.extRemake(key, t, 'railx', t.railxWalk, not solid)
      end
    end
  end
end

-- Snap a vehicle onto the track (M.snapToRail: the "Snap to rail" button and Ctrl+Shift+T). The road tiles carry their
-- tracks' centre lines ("rail_lines": flat x, y, z rows in the anchor frame, z the rail top, server
-- nrails.rails.RailTile.line_rows). M.nearestRail finds the nearest point of them; M.railSnapPose turns it into the
-- vehicle's pose.
M.SNAP_MAX_M = 40           -- m a track may lie from the vehicle to be snapped onto
M.SNAP_FLANGE_M = 0.10      -- m a rail vehicle's lowest point (its wheels' flange discs) is set under the rail top:
                            -- the flanges between the rails (0.21 m kept free there), the treads 5-8 cm over the rails
M.SNAP_LIFT_M = 0.05        -- m any other vehicle's lowest point is set over the rail top (a hi-rail's road tyres)
M.SNAP_Z_WEIGHT = 1.0       -- a height difference counts this much toward the distance (a track under a bridge)

-- The nearest track point to (x, y[, z]) within maxD (M.SNAP_MAX_M): { x, y, z (rail top), dx, dy, dz (unit tangent),
-- dist, key, colReady (the tile's rail collision is in) } or nil. Tiles moved by a rebase (ghosts) are skipped.
function M.nearestRail(x, y, z, maxD)
  maxD = maxD or M.SNAP_MAX_M
  local best
  local reach = roads.TILE_M + maxD
  for key, t in pairs(roads.extTiles()) do
    if t.railLines and not t.ghost
        and (not t.cx or (math.abs(t.cx - x) <= reach and math.abs(t.cy - y) <= reach)) then
      for _, row in ipairs(t.railLines) do
        for i = 1, #row - 5, 3 do
          local ax, ay, az, bx, by, bz = row[i], row[i + 1], row[i + 2], row[i + 3], row[i + 4], row[i + 5]
          local ex, ey, ez = bx - ax, by - ay, bz - az
          local l2 = ex * ex + ey * ey
          if l2 > 1e-8 then
            local u = math.max(0, math.min(1, ((x - ax) * ex + (y - ay) * ey) / l2))
            local px, py, pz = ax + u * ex, ay + u * ey, az + u * ez
            local dz = z and (pz - z) * M.SNAP_Z_WEIGHT or 0
            local d2 = (px - x) ^ 2 + (py - y) ^ 2 + dz * dz
            if d2 <= maxD * maxD and (not best or d2 < best.d2) then
              local l = math.sqrt(l2 + ez * ez)
              best = { d2 = d2, x = px, y = py, z = pz, dx = ex / l, dy = ey / l, dz = ez / l, key = key,
                colReady = t.railcol ~= nil }
            end
          end
        end
      end
    end
  end
  if best then best.dist = math.sqrt(best.d2) end
  return best
end

-- The pose of a vehicle snapped onto the track point r (M.nearestRail): its forward along the track the way it faced
-- (fx, fy: its forward now), its reference point at r's rail top + refOverBottom (the reference point's height over
-- the vehicle's lowest point) - M.SNAP_FLANGE_M for a rail vehicle (else + M.SNAP_LIFT_M).
-- Returns x, y, z, dx, dy, dz.
function M.railSnapPose(r, fx, fy, refOverBottom, isRail)
  local dx, dy, dz = r.dx, r.dy, r.dz
  if (fx or 0) * dx + (fy or 0) * dy < 0 then dx, dy, dz = -dx, -dy, -dz end
  local z = r.z + (refOverBottom or 0) + (isRail and -M.SNAP_FLANGE_M or M.SNAP_LIFT_M)
  return r.x, r.y, z, dx, dy, dz
end

-- The vehicle's reference node over its lowest collidable point (m) and its lateral offset from the collidable nodes'
-- centre (m, local +x: the vehicle's left), from its initial node positions (vehicle space: z up, -y forward); else
-- from its world box now. nil when neither is readable.
local function vehicleFootprint(veh)
  local ok, over, side = pcall(function()
    local bb = veh.initialCollidableNodePosBB
    local ref = veh:getInitialNodePosition(veh:getRefNodeId())
    return ref.z - bb.minExtents.z, ref.x - (bb.minExtents.x + bb.maxExtents.x) / 2
  end)
  if ok and type(over) == 'number' and over > -1 and over < 10 then return over, side end
  ok, over = pcall(function()
    local box = veh:getSpawnWorldOOBB()
    local c, he = box:getCenter(), box:getHalfExtents()
    local low = c.z
    for i = 0, 2 do low = low - math.abs(box:getAxis(i).z) * (i == 0 and he.x or i == 1 and he.y or he.z) end
    return veh:getPosition().z - low
  end)
  if ok and type(over) == 'number' and over > -1 and over < 10 then return over, 0 end
  return nil
end

-- Put the player vehicle on the nearest track within maxD m (M.SNAP_MAX_M): along the track the way it faces, its
-- wheels' flanges between the rails (a rail vehicle) or its tyres just over them (any other: a hi-rail), at rest
-- (setPositionRotation resets the vehicle there, core_checkpoints' way). Returns true when placed.
function M.snapToRail(maxD)
  local veh = getPlayerVehicle and getPlayerVehicle(0)
  if not veh then setStatus('Snap to rail: no vehicle'); return false end
  local p = veh:getPosition()
  local r = M.nearestRail(p.x, p.y, p.z, maxD)
  if not r then
    setStatus(string.format('Snap to rail: no track within %d m (are rails on in the Hub?)', maxD or M.SNAP_MAX_M))
    return false
  end
  local over, side = vehicleFootprint(veh)
  if not over then
    local ray = rawget(_G, 'castRayStatic')
    local d = ray and ray(vec3(p.x, p.y, p.z), vec3(0, 0, -1), 20)
    over, side = (d and d < 20) and d or 1.0, 0
  end
  local okJb, jb = pcall(function() return veh:getJBeamFilename() end)
  local isRail = okJb and M.isRailVehicle(jb)
  local f = veh:getDirectionVector()
  local x, y, z, dx, dy, dz = M.railSnapPose(r, f.x, f.y, over, isRail)
  side = math.max(-1, math.min(1, side or 0))
  local h = math.sqrt(dx * dx + dy * dy)
  if h > 1e-6 then x, y = x - dy / h * side, y + dx / h * side end      -- the vehicle's centre on the track's
  local dir = vec3(dx, dy, dz)
  local up = (vec3(0, 0, 1) - dir * dz):normalized()
  local rot = quatFromDir(-dir, up)                                       -- (vehicles face their -y)
  veh:resetBrokenFlexMesh()
  veh:setPositionRotation(x, y, z, rot.x, rot.y, rot.z, rot.w)
  pcall(function() veh:queueLuaCommand('recovery.clear()') end)
  setStatus(string.format('Snapped onto the track %.1f m away%s', r.dist,
    r.colReady and '' or ' (its collision is still loading: wait a moment before driving)'))
  log('I', 'beamngEarth', string.format('nrails snapToRail: %s at %.2f, %.2f, %.2f (rail top %.2f, ref over bottom %.2f%s)',
    tostring(jb), x, y, z, r.z, over, isRail and ', rail vehicle' or ''))
  return true
end

-- Collision for the trains the player is not driving (collisionfoci.lua gives every other vehicle a collision island:
-- PLAYER_R for a player's, TRAFFIC_R and no solid trees for AI traffic, none when parked). A rail vehicle gets
-- RAIL_FOCUS_R, whatever spawned it (a train set going at 160 km/h covers 320 m in 7 s: its rails must be solid before
-- it gets there), and no solid trees (a train never leaves its track). Wraps collisionfoci's vehicles / compute in
-- place (update calls them through its module table): no change to upstream's file.
M.RAIL_FOCUS_R = 480

function M.wrapFoci(cf, jbeamOf)
  if not cf or cf._nrails then return cf end
  jbeamOf = jbeamOf or function(id)
    local o = be and be.getObjectByID and be:getObjectByID(id)
    if not o then return nil end
    local ok, jb = pcall(function() return o:getJBeamFilename() end)
    return ok and jb or nil
  end
  local vehicles0, compute0 = cf.vehicles, cf.compute
  cf.vehicles = function(...)
    local out = vehicles0(...)
    for _, v in ipairs(out) do
      if M.isRailVehicle(jbeamOf(v.id)) then
        v.rail = true
        if v.kind == 'traffic' then v.kind = 'player' end
      end
    end
    return out
  end
  cf.compute = function(vehicles, ...)
    local out = compute0(vehicles, ...)
    local rail = {}
    for _, v in ipairs(vehicles or {}) do if v.rail then rail[v.id] = true end end
    for _, f in ipairs(out) do
      if rail[f.id] then f.r = math.max(f.r or 0, M.RAIL_FOCUS_R); f.trees = false; f.rail = true end
    end
    return out
  end
  cf._nrails = true
  return cf
end

-- The order the mod makes a tile's meshes in (the user, 2026-10-24: "une hierarchie de chargement: 1er terrain, 2e
-- routes et rails, 3e batiments, 4 reste"; the terrain block comes before any of them): roads.nextWalk's key k (the
-- distance along the car's path, + 1e6 for what is only drawn) with the track drawn right after the colliders (+1e5,
-- not with the buildings' facades) and the buildings' collision after the roads' and the rails' (+2e5).
function M.priority(e, k)
  local w = e.what or ''
  if w:sub(1, 4) == 'rail' and k >= 1e6 then return k - 1e6 + 1e5 end
  if w == 'bldcol' then return k + 2e5 end
  return k
end

-- Each frame (roads.ext.update): the level crossings' slabs, the load guard (nrailsload.lua).
local loadguard = require('beamngEarth/nrailsload')
M.loadguard = loadguard
-- The keys' help (Ctrl+Shift+I or the window's Keys button): a small window listing NRails' keys, shown / hidden
-- like a train mod's help.
M.KEYS = {
  { 'Ctrl+Shift+I', 'cette aide / this help' },
  { 'Ctrl+Shift+U', 'fenetre BeamNG.Earth / the window' },
  { 'Ctrl+Shift+T', 'sur le rail le plus proche / snap to rail' },
  { 'Ctrl+Shift+G', 'recharger la zone / reload area' },
  { 'Ctrl+Shift+Left', 'prochain aiguillage a gauche / next turnout left' },
  { 'Ctrl+Shift+Up', 'prochain aiguillage tout droit / next turnout straight' },
  { 'Ctrl+Shift+Right', 'prochain aiguillage a droite / next turnout right' },
}
M.helpOn = false
function M.toggleHelp() M.helpOn = not M.helpOn; return M.helpOn end

local helpPtr = nil
function M.drawHelp()
  if not M.helpOn then return end
  local im = rawget(_G, 'ui_imgui')
  if not im then return end
  helpPtr = helpPtr or im.BoolPtr(true)
  helpPtr[0] = true
  if im.Begin('NRails - touches / keys##nrailshelp', helpPtr, im.WindowFlags_AlwaysAutoResize) then
    for _, k in ipairs(M.KEYS) do
      im.TextUnformatted(k[1]); im.SameLine(150); im.TextUnformatted(k[2])
    end
  end
  im.End()
  if not helpPtr[0] then M.helpOn = false end
end

function M.update()
  M.updateRailCrossings()
  pcall(M.updateSwitches)
  pcall(M.drawHelp)
  if not M.anchor then return end
  pcall(loadguard.update, nil, {
    anchor = M.anchor,
    ready = function(aid, x, y, r) return roads.readyAround(aid, x, y, r) end,
    busy = function()
      local lp = package.loaded['beamngEarth/loadprogress']
      if lp and lp.active and lp.active() then return true end
      local core = rawget(_G, 'beamngEarth_core')
      local h = core and core.dropHoldState and core.dropHoldState()
      return h ~= nil and h.active == true
    end,
  })
end

-- core.lua (NRails hook): opts.setStatus(text) shows a status line.
local inited = false
-- Under the sea (the Channel Tunnel, 2026-10-24): the sea's WaterBlocks reach DEPTH_M / 2 under their surface, and a
-- vehicle's physics takes the newest water object it is in: the sea's physics block round the player. A train in a
-- tunnel under the sea floor was in the sea (buoyancy, drag, a drowned engine). When the player is DRY_UNDER_M or more
-- under the water's surface with something static over it (castRayStatic up: the tube's vault, the sea floor's
-- terrain) within ROOF_RAY_M, the physics block's surface is put DRY_M under the player (in DRY_STEP_M steps: the
-- sea makes the block again only when it changes): the player is out of the water.
M.DRY_UNDER_M = 3.0
M.ROOF_RAY_M = 150.0
M.DRY_M = 40.0
M.DRY_STEP_M = 20.0

-- Covered: something static over the player. Up from it (a solid roof), or down from over the water's surface to a
-- ground above it: the tube's vault is drawn only and the terrain is hit from above only, so the ray up from inside
-- the Channel Tunnel found nothing and the train drowned (the user's run, 2026-10-25).
M.COVER_M = 2.0         -- m the ground found from above stands over the player at least
function M.covered(player, surface, ray)
  local ok, d = pcall(ray, vec3(player.x, player.y, player.z + 1.5), vec3(0, 0, 1), M.ROOF_RAY_M)
  if ok and d and d < M.ROOF_RAY_M then return true end
  local top = surface + 5
  local len = top - player.z
  if len <= M.COVER_M then return false end
  ok, d = pcall(ray, vec3(player.x, player.y, top), vec3(0, 0, -1), len)
  return ok and d ~= nil and d < len - M.COVER_M
end

function M.physZ(player, z)
  if not player or not z or player.z > z - M.DRY_UNDER_M then return z end
  local ray = rawget(_G, 'castRayStatic')
  if not ray then return z end
  if not M.covered(player, z, ray) then return z end
  return math.floor((player.z - M.DRY_M) / M.DRY_STEP_M) * M.DRY_STEP_M
end

-- "Reload area" (the user's run, 2026-10-25: "un bouton pour recharger la zone ou forcer le chargement, comme un ping
-- au serveur"): the connection to the world server dropped and made again (core.reconnect): the server starts the
-- session over and sends every tile round the player again, those it never sent included. Not more often than
-- every RELOAD_MIN_S.
M.RELOAD_MIN_S = 5
local lastReload = nil
function M.reloadArea(core, now)
  core = core or rawget(_G, 'beamngEarth_core')
  now = now or os.clock()
  if lastReload and now - lastReload < M.RELOAD_MIN_S then return false, 'wait' end
  if not core or not core.reconnect then return false, 'no core' end
  lastReload = now
  local ok, err = pcall(core.reconnect)
  if setStatus then pcall(setStatus, ok and 'NRails: reloading the area (server asked again)' or ('NRails: reload failed: ' .. tostring(err))) end
  return ok, err
end

-- The loading line's roads part names the rails too (loadprogress.PARTS: the road tiles carry the track).
function M.labelLoading(lp)
  lp = lp or require('beamngEarth/loadprogress')
  for _, part in ipairs(lp.PARTS or {}) do
    if part[1] == 'roads' then part[2] = 'roads, rails & buildings' end
  end
end

function M.init(opts)
  opts = opts or {}
  if opts.setStatus then setStatus = opts.setStatus end
  if inited then return M end
  inited = true
  for _, w in ipairs(M.KINDS) do roads.EXT_KINDS[#roads.EXT_KINDS + 1] = w end
  local have = false
  for _, f in ipairs(roads.MATERIAL_FILES) do if f == M.MATERIAL_FILE then have = true end end
  if not have then roads.MATERIAL_FILES[#roads.MATERIAL_FILES + 1] = M.MATERIAL_FILE end
  if opts.anchor then M.anchor = opts.anchor end
  roads.ext = { onTile = onTile, update = M.update, lean = isCol, priority = M.priority }
  pcall(function() require('beamngEarth/sea').ext = { physZ = M.physZ } end)
  pcall(M.loadVehicleList)
  pcall(function() M.wrapFoci(require('beamngEarth/collisionfoci')) end)
  pcall(M.labelLoading)
  return M
end

return M
