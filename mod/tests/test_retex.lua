-- luajit mod/tests/test_retex.lua  (live retexture: server far_retex, --colormatch / --deshadow)
-- A shown (or loading) tile's material switches to the re-rendered texture the server names: colorMap
-- + flush + reload, time-sliced (a governor unit 'retex', at most farfield.RETEX_PER_FRAME a frame);
-- stale messages (another anchor, an unknown key, an older revision) change nothing; a failing switch
-- never throws out of the frame; nothing the tile still uses is deleted; a material shared by a tile
-- and its re-sent copy (same name) follows the newest revision.
local dir = (arg[0]:match('^(.*)[/\\]') or '.')
local T = dofile(dir .. '/testlib.lua')
local S = dofile(dir .. '/stubs.lua')
require('beamngEarth/farfield').SPARE_MAX = 0 -- deletion timing as before; the spare pool: test_farfield_spares.lua
local farfield = require('beamngEarth/farfield')
local governor = require('beamngEarth/governor')
local satmat = require('beamngEarth/satmat')

local now = 0
local function clock() return now end
local free = { clock = clock }
function free:try() return true end
function free:charge() end
function free:chargeMotion() end

local DT = 1 / 60
local SID = '/temp/beamngEarth/s1/'
local function size(l) return 256 * 2 ^ l end
local function key(l, i, j) return l .. '_' .. i .. '_' .. j end
local function matName(a, k) return 'bngEarthSat_' .. a .. '_' .. k:gsub('-', 'm') end
local function texOf(a, k, rev) return SID .. 'far_' .. a .. '_' .. k .. (rev and rev > 0 and ('_r' .. rev) or '') .. '.dds' end
local function sat(a, l, i, j, rev)
  local k = key(l, i, j)
  return { type = 'far_tile', anchorId = a, key = k, level = l, shape = SID .. 'far_' .. a .. '_' .. k .. '.cdae',
    pos = { i * size(l), j * size(l), 100 }, err = 0.5, state = 'group', material = matName(a, k),
    texture = texOf(a, k, rev), detail = true, tex = 256 }
end
local function retex(a, k, rev) return { type = 'far_retex', anchorId = a, key = k, texture = texOf(a, k, rev) } end
local function swap(a, id, add, remove)
  return { type = 'far_swap', anchorId = a, id = id, add = add, remove = remove or {}, dIn = 1, dOut = 1 }
end
local function mat(name)
  for _, o in pairs(S.objects) do if o.class == 'Material' and o.name == name then return o end end
end
local function step(gov, n) for _ = 1, n or 1 do now = now + 1; farfield.update(gov or free, DT, nil) end end
local function reloads() return S.calls.reload_Material or 0 end
local function flushes() return S.calls.flush_Material or 0 end

-- a shown field of 6 textured L0 tiles under anchor 1
farfield.switchAnchor(1, false, { cx = 100000, cy = 0 })
local keys = {}
for i = 0, 5 do
  local m = sat(1, 0, i, 0)
  keys[#keys + 1] = m.key
  farfield.onTile(m)
end
step(free, 3)
farfield.onSwap(swap(1, 1, keys))
step(free, 2)
for _, k in ipairs(keys) do
  T.check(farfield._tile(k) and farfield._tile(k).shown, 'tile ' .. k .. ' shown')
end
local k0, name0 = keys[1], matName(1, keys[1])
local id0 = farfield._tile(k0).id
T.check(mat(name0).fields.colorMap == texOf(1, k0), 'first render on screen')
T.check(not satmat.hasRetex() and not farfield.hasWork(), 'idle before any far_retex')

------------------------------------------------------------------------------------------
-- far_retex applies: the material takes the new file, flushed and reloaded, in the next update
do
  local r0, f0 = reloads(), flushes()
  farfield.onRetex(retex(1, k0, 1))
  T.check(mat(name0).fields.colorMap == texOf(1, k0), 'nothing happens in the message handler (time-sliced)')
  T.check(satmat.hasRetex() and farfield.hasWork(), 'a queued switch is streaming work (the governor ramps)')
  step()
  T.check(mat(name0).fields.colorMap == texOf(1, k0, 1), 'colorMap = the re-rendered texture')
  T.check(reloads() == r0 + 1 and flushes() == f0 + 1, 'flushed and reloaded once')
  T.check(satmat.texture(name0) == texOf(1, k0, 1) and farfield._tile(k0).texture == texOf(1, k0, 1), 'records follow')
  T.check(farfield.stats().retex == 1 and satmat.retexCount() == 1, 'counted')
  T.check(farfield._tile(k0).id == id0 and S.objects[id0] ~= nil and not S.objects[id0].hidden, 'the tile object stays, shown')
  T.check(satmat.refs(name0) == 1 and satmat.count() == 6, 'no material deleted or added')
  T.check(not satmat.hasRetex(), 'queue drained')
end

------------------------------------------------------------------------------------------
-- stale messages change nothing
do
  local r0, st0 = reloads(), farfield.stats().retexStale
  farfield.onRetex(retex(2, k0, 2))                 -- another anchor
  farfield.onRetex(retex(1, key(0, 40, 40), 1))     -- a key not shown or loading
  farfield.onRetex({ type = 'far_retex', anchorId = 1, key = k0 })       -- no texture
  farfield.onRetex({ type = 'far_retex', anchorId = 1, texture = 'x' })  -- no key
  farfield.onRetex(retex(1, k0, 1))                 -- the revision it already shows: a no-op
  step(free, 3)
  T.check(farfield.stats().retexStale == st0 + 4, 'stale far_retex counted')
  T.check(reloads() == r0 and mat(name0).fields.colorMap == texOf(1, k0, 1), 'no switch, no reload')
  -- an older revision after a newer one: the newer stays
  farfield.onRetex(retex(1, k0, 3))
  farfield.onRetex(retex(1, k0, 2))
  step()
  T.check(mat(name0).fields.colorMap == texOf(1, k0, 3) and reloads() == r0 + 1, 'newest revision wins, one reload')
  farfield.onRetex(retex(1, k0, 2))
  step()
  T.check(mat(name0).fields.colorMap == texOf(1, k0, 3) and reloads() == r0 + 1, 'older revision ignored')
  T.check(farfield._tile(k0).texture == texOf(1, k0, 3), 'the record keeps the newest too')
end

------------------------------------------------------------------------------------------
-- time slicing: at most RETEX_PER_FRAME switches per frame, and only within the governor's budget
do
  T.check(farfield.RETEX_PER_FRAME >= 1 and farfield.RETEX_PER_FRAME <= 4, 'a small per-frame cap')
  local base = satmat.retexCount()
  for n = 2, 6 do farfield.onRetex(retex(1, keys[n], 1)) end
  local perFrame = {}
  for f = 1, 10 do
    local c0 = satmat.retexCount()
    step()
    perFrame[f] = satmat.retexCount() - c0
  end
  local maxN = 0
  for _, n in ipairs(perFrame) do maxN = math.max(maxN, n) end
  T.check(maxN == farfield.RETEX_PER_FRAME, 'at most RETEX_PER_FRAME a frame (got ' .. maxN .. ')')
  T.check(satmat.retexCount() == base + 5, 'all five done within a few frames')
  for n = 2, 6 do T.check(mat(matName(1, keys[n])).fields.colorMap == texOf(1, keys[n], 1), 'tile ' .. keys[n] .. ' switched') end

  -- through the real governor: each switch is a 'retex' unit, charged, and none runs in a heavy frame
  local gov = governor.new({ clock = clock })
  T.check(governor.PRIOR.retex ~= nil, "'retex' has a prior cost")
  for n = 2, 6 do farfield.onRetex(retex(1, keys[n], 2)) end
  local frames, units0 = 0, gov.stats.units
  while satmat.hasRetex() and frames < 200 do
    gov:beginFrame(farfield.hasWork(), 16)
    local c0 = satmat.retexCount()
    farfield.update(gov, DT, nil)
    T.check(satmat.retexCount() - c0 <= farfield.RETEX_PER_FRAME, 'governor frame within the cap')
    frames = frames + 1
  end
  T.check(not satmat.hasRetex() and gov.stats.units - units0 == 5, 'governor ran five retex units')
  T.check(frames > 1, 'spread over frames (the budget ramps up from 0)')
  -- a heavy frame runs no switch
  farfield.onRetex(retex(1, keys[2], 3))
  gov:beginFrame(true, 16)
  T.check(gov:heavyNow(), 'heavy slot granted')
  local c0 = satmat.retexCount()
  farfield.update(gov, DT, nil)
  T.check(satmat.retexCount() == c0 and satmat.hasRetex(), 'no switch in the heavy frame')
  for _ = 1, 60 do
    gov:beginFrame(farfield.hasWork(), 16)
    farfield.update(gov, DT, nil)
  end
  T.check(not satmat.hasRetex() and mat(matName(1, keys[2])).fields.colorMap == texOf(1, keys[2], 3), 'done after the quiet frames')
end

------------------------------------------------------------------------------------------
-- no per-frame errors: a switch that throws is counted and dropped, the frame goes on
do
  local m = mat(matName(1, keys[3]))
  local realSet = m.setField
  m.setField = function() error('engine refused') end
  farfield.onRetex(retex(1, keys[3], 5))
  farfield.onRetex(retex(1, keys[4], 5))
  local ok = pcall(step, free, 1)
  T.check(ok, 'update does not throw')
  T.check(farfield.stats().retexFailed == 1 and mat(matName(1, keys[4])).fields.colorMap == texOf(1, keys[4], 5),
    'the failing switch counted, the next one still runs')
  local f0 = farfield.stats().retexFailed
  ok = pcall(step, free, 5)
  T.check(ok and farfield.stats().retexFailed == f0 and not satmat.hasRetex(), 'not retried every frame')
  m.setField = realSet
  -- a reload that throws inside the engine call is swallowed (pcall) and the switch counts
  local realReload = m.reload
  m.reload = function() error('reload failed') end
  farfield.onRetex(retex(1, keys[3], 6))
  ok = pcall(step, free, 1)
  T.check(ok and m.fields.colorMap == texOf(1, keys[3], 6), 'reload error swallowed, colorMap set')
  m.reload = realReload
end

------------------------------------------------------------------------------------------
-- a missing file: the material keeps its texture (no orange "no texture"), warned, no reload
do
  local realExists = FS.fileExists
  FS.fileExists = function(_, p) return not p:match('_r9%.dds$') end
  local r0 = reloads()
  farfield.onRetex(retex(1, keys[5], 9))
  step()
  T.check(mat(matName(1, keys[5])).fields.colorMap == texOf(1, keys[5], 2) and reloads() == r0, 'missing file: texture kept')
  FS.fileExists = realExists
end

------------------------------------------------------------------------------------------
-- a tile still loading (sent, not swapped in): its material does not exist yet - it is created with
-- the new texture, no switch needed; one whose material exists already (re-sent key) switches
do
  local m = sat(1, 0, 10, 0)
  farfield.onTile(m)
  farfield.onRetex(retex(1, m.key, 1))
  T.check(not satmat.hasRetex(), 'no material yet: nothing queued')
  step()
  T.check(mat(m.material) and mat(m.material).fields.colorMap == texOf(1, m.key, 1), 'material created with the new texture')
  T.check(farfield._pending(m.key) and farfield._pending(m.key).loaded, 'tile loaded hidden')
  farfield.onRetex(retex(1, m.key, 2))
  step()
  T.check(mat(m.material).fields.colorMap == texOf(1, m.key, 2), 'a loading tile with its material switches too')
  farfield.onSwap(swap(1, 2, { m.key }))
  step()
  T.check(farfield._tile(m.key).shown and mat(m.material).fields.colorMap == texOf(1, m.key, 2), 'shown with the new texture')
end

------------------------------------------------------------------------------------------
-- shared material (satmat.ref rules): a shown tile re-sent with a newer revision of its own texture
-- (same name) switches the material time-sliced for both instances; an unrelated texture under the
-- same name (a restarted server) still keeps the in-use one
do
  local k, name = keys[6], matName(1, keys[6])
  T.check(mat(name).fields.colorMap == texOf(1, k, 2), 'shown tile on r2')
  local m = sat(1, 0, 5, 0, 4)                      -- the same key re-sent with r4
  farfield.onTile(m)
  local r0 = reloads()
  step()                                             -- the new instance refs the shared material
  T.check(satmat.refs(name) == 2, 'two instances share the material')
  step(free, 2)
  T.check(mat(name).fields.colorMap == texOf(1, k, 4) and reloads() > r0, 'in-use material switched to the newer revision')
  -- an older revision re-sent afterwards (cannot come from one server, but must not go back)
  satmat.unref(name)
  T.check(satmat.ref(name, texOf(1, k, 3)) and mat(name).fields.colorMap == texOf(1, k, 4), 'older revision: kept')
  -- another session's file under the same name: the existing rule (in use: keep)
  T.check(satmat.ref(name, '/temp/beamngEarth/s2/far_1_' .. k .. '.dds') and mat(name).fields.colorMap == texOf(1, k, 4),
    'another session: in-use material keeps its texture')
  satmat.unref(name) -- back to the two references the instances hold
  farfield.onSwap(swap(1, 3, { k }, { k }))
  step(free, 60)
  T.check(farfield._tile(k) and farfield._tile(k).shown and mat(name) ~= nil and satmat.refs(name) == 1,
    'replacement in place keeps the material, one reference')
end

------------------------------------------------------------------------------------------
-- a material created without its file (fallback colour) loses the tint when its texture arrives
do
  local realExists = FS.fileExists
  local m = sat(1, 0, 11, 0)
  FS.fileExists = function(_, p) return p ~= m.texture end
  farfield.onTile(m)
  step()
  local o = mat(m.material)
  T.check(o and o.fields.diffuseColor == satmat.FALLBACK_COLOR and o.fields.colorMap == nil, 'fallback colour')
  FS.fileExists = realExists
  farfield.onRetex(retex(1, m.key, 1))
  step()
  T.check(o.fields.colorMap == texOf(1, m.key, 1) and o.fields.diffuseColor == '1 1 1 1', 'texture on, tint off')
end

------------------------------------------------------------------------------------------
-- a switch queued for a tile that goes before it runs: dropped (its material is deleted after the
-- object); the same name created again later is not switched by the stale entry
do
  local k, name = keys[2], matName(1, keys[2])
  farfield.onRetex(retex(1, k, 7))
  farfield.onRemove({ type = 'far_remove', anchorId = 1, key = k })    -- swapped out meanwhile
  farfield.switchAnchor(2, false, { cx = 0, cy = 0 })                  -- teleport: everything goes
  step(free, 400)
  T.check(mat(name) == nil and satmat.count() == 0, 'teleport: tiles and materials gone')
  T.check(not satmat.hasRetex(), 'queue drained without a switch')
  farfield.onRetex(retex(1, k, 8))                  -- the previous anchor's: stale
  step()
  T.check(farfield.stats().retexStale > 0 and not satmat.hasRetex(), 'previous anchor ignored')
end

------------------------------------------------------------------------------------------
-- review: a switch queued while the material was in use must not undo a newer texture the material
-- took meanwhile. Its tile went before the switch ran (a frame budget that fits a delete, 0.3 ms, but
-- not a switch, 1.0 ms), and the key was re-sent with a later revision: ref() points the unused
-- material at the re-sent file at once; the stale queued switch then went back to the older file.
do
  local name = 'bngEarthSat_9_0_0_0'
  local t0, t1, t2 = SID .. 'far_9_0_0_0.dds', SID .. 'far_9_0_0_0_r1.dds', SID .. 'far_9_0_0_0_r2.dds'
  T.check(satmat.create(name, t0, false) and satmat.ref(name, t0), 'material in use on r0')
  T.check(satmat.requestRetex(name, t1) and satmat.hasRetex(), 'switch to r1 queued')
  satmat.unref(name) -- its tile is gone before the switch ran: refs 0, waiting for deletion
  T.check(satmat.ref(name, t2), 'the key re-sent with r2')
  T.check(mat(name).fields.colorMap == t2, 'the unused material takes r2 at once')
  local guard = 0
  while satmat.hasRetex() and guard < 10 do
    satmat.retexNext()
    guard = guard + 1
  end
  T.check(mat(name).fields.colorMap == t2 and satmat.texture(name) == t2, 'the queued r1 switch does not go back to r1')
end

------------------------------------------------------------------------------------------
-- merge (robustness x cm-retex): farfield.heldSessions (satmat.eachTexture) names the texture the
-- material shows until the switch runs, the queued one meanwhile too (its folder must stay, e.g. an
-- earlier server's session this game holds), and only the new one once the switch ran
do
  local name = 'bngEarthSat_9_1_0_0'
  local cur, other = '/temp/beamngEarth/s1/far_9_1_0_0.dds', '/temp/beamngEarth/s2/far_9_1_0_0_r1.dds'
  local function held(tex)
    local n = 0
    satmat.eachTexture(function(t) if t == tex then n = n + 1 end end)
    return n
  end
  local function folders()
    local set = {}
    for _, f in ipairs(farfield.heldSessions()) do set[f] = true end
    return set
  end
  T.check(satmat.create(name, cur, false) and satmat.ref(name, cur), 'material in use on s1')
  T.check(held(cur) == 1 and held(other) == 0 and not folders().s2, 'nothing queued: only its texture named')
  T.check(satmat.requestRetex(name, other) and satmat.hasRetex(), 'switch to another folder queued')
  T.check(held(cur) == 1 and held(other) == 1, 'queued: both the shown texture and the queued one named')
  T.check(folders().s1 and folders().s2, 'queued: heldSessions names both folders')
  local guard = 0
  while satmat.hasRetex() and guard < 10 do
    satmat.retexNext()
    guard = guard + 1
  end
  T.check(satmat.texture(name) == other and mat(name).fields.colorMap == other, 'switched')
  T.check(held(cur) == 0 and held(other) == 1 and folders().s2, 'switched: only the texture in use named')
end

T.done('test_retex')
