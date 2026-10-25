-- Our HUD as BeamNG UI apps (the user, 2026-10-15: "convert our current in game HUD elements to beam's ui app system and
-- create a .Earth preset based off the freeroam preset"). The apps (ui/modules/apps/BeamNGEarth*) are Angular
-- directives in the game's app layout: the player moves, resizes and removes them like any app, and the ".Earth"
-- layout (settings/ui_apps/originalLayouts/default/beamngEarth.uilayout.json) places them.
--
-- An app says when it is on screen (beamngEarth_core.hudApp(name, true / false) from its link / $destroy); while one
-- is, core leaves out the imgui drawing of the same element (statusbar.lua, credits.lua, banner.lua), so nothing shows
-- twice and the imgui HUD still works without the apps (another layout). Every SEND_S core hands update() the texts
-- and they go to the apps in one 'BeamNGEarthHud' hook, only while an app is mounted and only when something changed.
-- Pure apart from guihooks (runs under plain luajit with a stub).
local M = {}

M.NAMES = { status = true, credits = true, banner = true }
M.SEND_S = 0.25           -- s between updates to the apps (the status bar's fps changes every frame)
M.STALE_S = 5.0           -- an unchanged payload is sent again this often (an app opened since)

local mounted = {}        -- name -> true while that app is on screen
local nMounted = 0
local lastSend, lastKey, lastFull = -math.huge, nil, -math.huge
M.sends = 0

function M.setMounted(name, on)
  if not M.NAMES[name] then return false end
  on = on and true or false
  if (mounted[name] or false) ~= on then
    mounted[name] = on or nil
    nMounted = nMounted + (on and 1 or -1)
    lastKey = nil           -- a newly opened app gets the current state at the next update
  end
  return on
end

function M.mounted(name) return mounted[name] == true end
function M.any() return nMounted > 0 end

-- Pure: the payload for the apps. t: { status, loading, credits, banner = { text, level, visible }, hidden }
function M.payload(t)
  local b = t.banner or {}
  return {
    status = t.status or '',
    loading = t.loading or '',          -- the status bar's second line (statusbar.loading)
    credits = t.credits or '',
    banner = (b.visible and b.text ~= '' and b.text) or '',
    bannerLevel = b.level or 'info',
    hidden = t.hidden and true or false,
  }
end

local function key(p)
  return p.status .. '\1' .. p.loading .. '\1' .. p.credits .. '\1' .. p.banner .. '\1' .. p.bannerLevel .. '\1' .. tostring(p.hidden)
end

-- now: core's clock (s); get(): the texts (only called when a send is due, so its cost is paid at SEND_S at most).
-- Returns true if it sent.
function M.update(now, get)
  if nMounted == 0 or now - lastSend < M.SEND_S then return false end
  lastSend = now
  local p = M.payload(get())
  local k = key(p)
  if k == lastKey and now - lastFull < M.STALE_S then return false end
  lastKey, lastFull = k, now
  local gh = rawget(_G, 'guihooks')
  if gh and gh.trigger then gh.trigger('BeamNGEarthHud', p) end
  M.sends = M.sends + 1
  return true
end

-- The minimap's label (BeamNG 0.40's navigation app; the user, 2026-10-22: "change the text on top of the minimap"):
-- the stock app shows the name of the level's city zone the camera is in (gameplay_city.getHighestPrioZone), else the
-- level's title, "BeamNG.Earth" in our level, which has no zones. The town of the status bar's location takes the
-- zones' place (the street until the town is known): getHighestPrioZone is wrapped while in our level, a level's own
-- zone still first. Its callers (the minimap, photo mode's speed camera) only read the zone's name.
-- The label is the car's Earth coordinates (the user, 2026-10-23: "change the info above the minimap to be the earth
-- coordinates"); minimapName (the town) is kept for a label without them.
-- Pure: "39.28340° N, 76.59340° W" for a latitude / longitude, nil without them.
function M.coordsLabel(lat, lon)
  lat, lon = tonumber(lat), tonumber(lon)
  if not lat or not lon or lat ~= lat or lon ~= lon then return nil end
  return string.format('%.5f° %s, %.5f° %s', math.abs(lat), lat >= 0 and 'N' or 'S', math.abs(lon), lon >= 0 and 'E' or 'W')
end

-- Pure: the label for a location { street, place, region, country }, or nil (the stock fallback).
function M.minimapName(l)
  if not l then return nil end
  if l.place ~= nil and l.place ~= '' then return l.place end
  if l.street ~= nil and l.street ~= '' then return l.street end
  return nil
end

local zoneOrig, zoneWrap = nil, nil
-- getName(): the label now (or nil). Installed again if the city extension was reloaded since.
function M.hookCityZone(getName)
  local city = rawget(_G, 'gameplay_city')
  if not city or type(city.getHighestPrioZone) ~= 'function' then return false end
  if city.getHighestPrioZone == zoneWrap then return true end
  local orig = city.getHighestPrioZone
  local zone = { name = '' }
  zoneOrig = orig
  zoneWrap = function(pos, ...)
    local z = orig(pos, ...)
    if z ~= nil then return z end
    local name = getName()
    if not name then return nil end
    zone.name = name
    return zone
  end
  city.getHighestPrioZone = zoneWrap
  return true
end

function M.unhookCityZone()
  local city = rawget(_G, 'gameplay_city')
  if city and zoneWrap and city.getHighestPrioZone == zoneWrap then city.getHighestPrioZone = zoneOrig end
  zoneOrig, zoneWrap = nil, nil
end

-- The minimap's compass (the user, 2026-10-22: "fix the minimap north"): the stock compass points along the world's +y,
-- which is north only at our anchor (geodesy Anchor:northAt). Its drawCompass reads the minimap's world-to-map
-- transform (ui_apps_minimap_utils.getWorldToMapTransform: the 2nd and 4th values are where world +y points on the
-- map); while in our level that call, and only that caller's, gets true north at the camera turned through the same
-- transform. The roads, route and vehicles keep the plain transform.
-- Pure: the map direction of world direction (tx, ty) under the transform's linear part.
function M.mapNorth(xx, xy, yx, yy, tx, ty)
  return xx * tx + xy * ty, yx * tx + yy * ty
end

local northOrig, northWrap = nil, nil
-- getNorth(): true north at the camera as a world direction (x, y), or nil (leave the compass as it is).
function M.hookMinimapNorth(getNorth)
  local utils = rawget(_G, 'ui_apps_minimap_utils')
  local dbg = rawget(_G, 'debug')
  if not utils or type(utils.getWorldToMapTransform) ~= 'function' or not dbg or not dbg.getinfo then return false end
  if utils.getWorldToMapTransform == northWrap then return true end
  local orig = utils.getWorldToMapTransform
  northOrig = orig
  northWrap = function(...)
    local xx, xy, yx, yy, ox, oy = orig(...)
    local info = dbg.getinfo(2, 'n')
    if info and info.name == 'drawCompass' and xx then
      local tx, ty = getNorth()
      if tx then
        local nx, ny = M.mapNorth(xx, xy, yx, yy, tx, ty)
        return xx, nx, yx, ny, ox, oy
      end
    end
    return xx, xy, yx, yy, ox, oy
  end
  utils.getWorldToMapTransform = northWrap
  return true
end

function M.unhookMinimapNorth()
  local utils = rawget(_G, 'ui_apps_minimap_utils')
  if utils and northWrap and utils.getWorldToMapTransform == northWrap then utils.getWorldToMapTransform = northOrig end
  northOrig, northWrap = nil, nil
end

function M._reset()
  mounted, nMounted, lastSend, lastKey, lastFull, M.sends = {}, 0, -math.huge, nil, -math.huge, 0
end

return M
