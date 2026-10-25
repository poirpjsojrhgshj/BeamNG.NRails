-- luajit mod/tests/test_m4_probes.lua [--json]  (probes/v14/m4_probes.lua, docs/V1_4_SPEC.md 3.5 / 7)
-- The M4 in-game probe chunk against a fake engine: a TerrainBlock model whose static collision is a
-- snapshot taken at be:reloadCollision of the FIRST registered TerrainBlock (ARCHITECTURE.md: a second
-- block does not collide), heights = ground(x, y) + (z - zBase0), the collidable extent
-- [x0, x0 + (N-1)*2]. It runs every step the tool runs (info, P2, P11, P7 a and b, restore) and checks
-- that each one leaves the live block as it was. With --json it prints the probe answers instead, for
-- server/tests/test_m4_probes_tool.py (the tool's pass criteria on these answers).
local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local JSON = arg[1] == '--json'
local T = dofile(dir .. '/testlib.lua')
local S = dofile(dir .. '/stubs.lua')
local PROBE = dir .. '/../../probes/v14/m4_probes.lua'

------------------------------------------------------------------------------------------
-- fake engine
local Z0 = 1100
local HM1024 = '/temp/beamngEarth/s1/hm_1_0_0.png'
local HM512 = '/temp/beamngEarth/m4probe/hm512_0_0.png'
local SIZES = { [HM1024] = 1024, [HM512] = 512 }
local function ground(x, y) return 1200 + 0.01 * x - 0.02 * y end

local hp = 0
function hptimer() return { stopAndReset = function() hp = hp + 1; return 1.0 end } end
function jsonEncode(v) return v end

local physics, collider, reloads = true, nil, 0
local function firstBlock()
  local best
  for id, o in pairs(S.objects) do
    if o.class == 'TerrainBlock' and o.n and (not best or id < best.id) then best = o end
  end
  return best
end
be = {
  reloadCollision = function()
    reloads = reloads + 1
    local b = firstBlock()
    collider = b and { x0 = b.pos.x, y0 = b.pos.y, z = b.pos.z, n = b.n } or nil
  end,
  setPhysicsRunning = function(_, v) physics = v end,
  getPhysicsRunning = function() return physics end,
}
function castRayStatic(pos, _, len)
  local c = collider
  if not c then return len end
  local w = (c.n - 1) * 2
  if pos.x < c.x0 or pos.x > c.x0 + w or pos.y < c.y0 or pos.y > c.y0 + w then return len end
  local d = pos.z - (ground(pos.x, pos.y) + c.z - Z0)
  if d < 0 or d >= len then return len end
  return d
end
local baseTB = TerrainBlock
function TerrainBlock()
  local tb = baseTB()
  tb.renderEnabled = true
  local imp = tb.importMaps
  function tb:importMaps(path, sq, maxH, ...)
    if not SIZES[path] then return false end
    self.n, self.maxH = SIZES[path], maxH
    return imp(self, path, sq, maxH, ...)
  end
  function tb:getHeight(p)
    if not self.n then return nil end
    return ground(p.x, p.y) + self.pos.z - Z0
  end
  function tb:isRenderEnabled() return self.renderEnabled end
  function tb:getHeightScaleUser() return self.maxH end
  function tb:getSquareSize() return 2 end
  return tb
end

local veh = { pos = vec3(10, 20, ground(10, 20) + 0.5), cmds = {} }
function veh:getPosition() return vec3(self.pos.x, self.pos.y, self.pos.z) end
function veh:getVelocity() return vec3(0, 0, 0) end
function veh:queueLuaCommand(c) self.cmds[#self.cmds + 1] = c end
function veh:getId() return 77 end
veh.active = 1
function veh:setActive(a) self.active = a end
function getPlayerVehicle() return veh end
be = be or {}
function be:getObjectByID(id) return id == 77 and veh or nil end

local proxies = {}
function newExtensionProxy(_, prefix)
  local p = { prefix = prefix, destroyed = false }
  function p:submitEventSinks(sinks) self.sinks = sinks end
  function p:destroy() self.destroyed = true end
  proxies[#proxies + 1] = p
  return p
end
local function preRender() for _, p in ipairs(proxies) do if not p.destroyed then p.sinks[1]:onPreRender() end end end

beamngEarth_core = { status = function()
  return "{ anchorId = 1, block = { cx = 0, cy = 0 }, blockSize = 1024, nearVisual = 'mesh', session = 's1' }"
end }

-- the live block, as terrain.lua makes it (mesh mode: render off)
local live = TerrainBlock()
live:setName('bngEarthTerrain')
live:registerObject('bngEarthTerrain')
scenetree.MissionGroup:addObject(live)
live:importMaps(HM1024, 2, 1024, '', {}, {}, false)
live:setPosition(vec3(-1024, -1024, Z0))
live.renderEnabled = false
be:reloadCollision()

-- the mod modules P7 (a) wraps
local calls = {}
local function fakeMod(name, keys)
  local m = {}
  for _, k in ipairs(keys) do m[k] = function(...) calls[#calls + 1] = name .. '.' .. k; return k end end
  package.loaded['beamngEarth/' .. name] = m
  return m
end
local fTerrain = fakeMod('terrain', { 'load' })
fakeMod('farfield', { 'transform', 'switchAnchor', 'onBlockCommit' })
fakeMod('camshift', { 'shift' })
fakeMod('rebase', { 'moveVehicles' })
fakeMod('net', { 'send' })
local origLoad = fTerrain.load

------------------------------------------------------------------------------------------
local function h(x, y, dz) return math.floor((ground(x, y) + (dz or 0)) * 1000 + 0.5) / 1000 end
local function rayAt(rs, dx, dy)
  for _, r in ipairs(rs) do
    if r.dx == dx and r.dy == dy then
      -- ray heights are zTop - distance: round to the mm before comparing with ground()
      return r.h and math.floor(r.h * 1000 + 0.5) / 1000
    end
  end
end
local function liveState()
  local tb = scenetree.findObject('bngEarthTerrain')
  return tb and tb.n, tb and tb.pos.x, tb and tb.pos.y, tb and tb.pos.z, tb and tb.renderEnabled
end
local function checkRestored(label)
  local n, x, y, z, r = liveState()
  T.check(n == 1024 and x == -1024 and y == -1024 and z == Z0 and r == false and collider.n == 1024 and collider.z == Z0,
    label .. ': the live block restored (1024², its position, render off, collision rebuilt)')
  T.check(physics, label .. ': physics running again')
end

T.check(dofile(PROBE) == 'ok', 'chunk loads')
local M = BNGE_M4
local out = {}

out.info = M.info()
T.check(out.info.mod and out.info.terrain and out.info.blockSize == 1024 and out.info.block.cx == 0, 'info: mod, block')
T.check(out.info.tb.x == -1024 and out.info.tb.z == Z0 and out.info.tb.render == false and out.info.car.speed == 0, 'info: block, car')
local s = out.info.samples[2]
T.check(#out.info.samples == 6 and s.gx == 512 and s.h == h(-1024 + 1024, -1024 + 1024), 'info: lattice samples')

local cfg = { cx = 0, cy = 0, hm512 = HM512, layer512 = '/temp/beamngEarth/m4probe/layer_512.png', steady = 5,
  orig = { path = HM1024, maxH = 1024, x = -1024, y = -1024, z = Z0, render = false,
    layer = '/levels/beamng_earth/art/terrains/beamngEarth_layer_1024.png' } }

-- P2
local reloads0 = reloads
out.p2a = M.p2a(cfg)
T.check(not physics, 'P2: physics paused')
T.check(out.p2a.first512.ok and live.n == 512 and live.pos.x == -512, 'P2a: the 512² crop imported at (c-512, c-512)')
T.check(live.lastImport.maps[1].path == cfg.layer512 and out.p2a.renderAfterImport == false, 'P2a: with the 512 layer map; render flag read')
T.check(rayAt(out.p2a.sameFrame, 0, 0) == h(0, 0) and rayAt(out.p2a.sameFrame, 509, 0) == h(509, 0)
  and rayAt(out.p2a.sameFrame, 511, 0) == false and rayAt(out.p2a.sameFrame, -513, 0) == false, 'P2a: the 512 extent')
T.check(rayAt(out.p2a.before, 1021, 0) == h(1021, 0) and rayAt(out.p2a.before, 1023, 0) == false, 'P2a: the 1024 extent before')
preRender()
out.p2b = M.p2b(cfg)
T.check(#out.p2b.steady512Layer == 5 and #out.p2b.steady512NoLayer == 5 and #out.p2b.steady1024Layer == 2, 'P2b: the series')
T.check(rayAt(out.p2b.back1024Rays, 1021, 0) == h(1021, 0), 'P2b: back to 1024²')
T.check(out.p2b.error == nil and rayAt(out.p2b.after, -1023, 0) == h(-1023, 0), 'P2b: no error, heights after')
T.check(reloads - reloads0 == 1 + 5 + 5 + 1 + 2 + 1, 'P2: one reloadCollision per import')
checkRestored('P2')

-- P11
out.p11a = M.p11a(cfg)
T.check(out.p11a.ok and live.pos.z == Z0 + 0.3 and collider.z == Z0, 'P11a: re-imported 0.3 m higher, collision not rebuilt')
T.check(out.p11a.raySameFrame == out.p11a.rayBefore, 'P11a: the fake physics keeps the old surface (no reload)')
out.p11samples = {}
for i = 1, 4 do out.p11samples[i] = M.p11sample() end
T.check(out.p11samples[4].carZ == veh.pos.z and out.p11samples[1].ray == out.p11a.rayBefore, 'P11 samples')
out.p11b = M.p11b(cfg)
T.check(out.p11b.ok and live.n == 512 and rayAt(out.p11b.sameFrame, 700, 0) == h(700, 0), 'P11b: 512², old collision still there')
T.check(veh.active == 0, 'P11b: the car is frozen while the collision is stale')
out.p11bSamples = {}
for i = 1, 4 do out.p11bSamples[i] = M.p11bSample() end
T.check(veh.active == 0, 'P11b samples: the car stays frozen')
out.p11restore = M.restore(cfg)
checkRestored('P11')
T.check(veh.active == 1 and out.p11restore.carUnfrozen == true and M.frozenCar == nil, 'P11 restore: the car is back')

-- P7 (a)
out.p7aInstall = M.p7aInstall()
T.check(out.p7aInstall.ok and out.p7aInstall.wrapped == 7 and #out.p7aInstall.reloadCollisionMs == 3, 'P7a: 7 functions wrapped')
local Tm = package.loaded['beamngEarth/terrain']
T.check(Tm.load ~= origLoad, 'P7a: terrain.load wrapped')
local F = package.loaded['beamngEarth/farfield']
local N = package.loaded['beamngEarth/net']
preRender(); preRender()
-- a rebase with phase 2 one frame later, then a terrain-follow commit
package.loaded['beamngEarth/rebase'].moveVehicles('xf')
preRender()
Tm.load('/x.png'); F.transform('xf'); F.switchAnchor(2); package.loaded['beamngEarth/camshift'].shift('xf')
N.send({ type = 'commit_anchor', anchorId = 2 }); N.send({ type = 'commit_terrain' }); N.send({ type = 'pose' })
preRender(); preRender()
Tm.load('/y.png'); F.onBlockCommit(128, 0); N.send({ type = 'commit_terrain' })
preRender()
out.p7aRead = M.p7aRead()
local names = {}
for _, c in ipairs(out.p7aRead.calls) do names[#names + 1] = c.name .. '@' .. c.frame end
T.check(table.concat(names, ' ') == 'rebase.moveVehicles@2 terrain.load@3 farfield.transform@3 farfield.switchAnchor@3 '
  .. 'camshift.shift@3 send.commit_anchor@3 send.commit_terrain@3 terrain.load@5 farfield.onBlockCommit@5 send.commit_terrain@5',
  'P7a: the calls with their frames (pose not recorded): ' .. table.concat(names, ' '))
T.check(#out.p7aRead.frames == 6 and out.p7aRead.frameBase == 0, 'P7a: one wall time per frame')
T.check(calls[#calls] == 'net.send' and #calls == 11, 'P7a: the originals still run')
T.check(M.p7aUninstall() == 'uninstalled' and Tm.load == origLoad and proxies[#proxies].destroyed, 'P7a: unwrapped, proxy gone')

-- P7 (b)
out.p7b = M.p7b(cfg)
T.check(out.p7b.error == nil, 'P7b: no error ' .. tostring(out.p7b.error))
T.check(rayAt(out.p7b.withBNoReload, 0, 0) == h(0, 0) and rayAt(out.p7b.withBReload, 0, 0) == h(0, 0),
  'P7b: the hidden second block does not collide (fake engine: first block only)')
T.check(rayAt(out.p7b.afterSwap, 0, 0) == h(0, 0, 5) and rayAt(out.p7b.afterSwap, 700, 0) == false, 'P7b: after the swap B collides (+5 m)')
T.check(scenetree.findObject('bngEarthTerrainM4B') == nil and #S.liveOf('TerrainBlock') == 1, 'P7b: one block left')
live = scenetree.findObject('bngEarthTerrain')
checkRestored('P7b')

if JSON then
  -- a minimal JSON encoder for the tool's test
  local function enc(v)
    local t = type(v)
    if t == 'table' then
      if #v > 0 or next(v) == nil then
        local a = {}
        for i = 1, #v do a[i] = enc(v[i]) end
        return '[' .. table.concat(a, ',') .. ']'
      end
      local a = {}
      for k, x in pairs(v) do a[#a + 1] = string.format('%q', tostring(k)) .. ':' .. enc(x) end
      return '{' .. table.concat(a, ',') .. '}'
    elseif t == 'string' then return string.format('%q', v)
    elseif t == 'number' then return string.format('%.17g', v)
    elseif t == 'boolean' then return tostring(v)
    end
    return 'null'
  end
  print(enc(out))
  os.exit(T.failed == 0 and 0 or 1)
end
T.done('test_m4_probes')
