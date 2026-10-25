-- Usage: prepend "PROBE_STEP='spawn'|'reload'|'ray'|'perf'|'clear'; PROBE_FROM=<first tile idx>; PROBE_COUNT=<n>"
-- Spawns 64x64-cell (8192-tri) ProceduralMesh tiles at 2 m spacing (128 m tiles) on a 16-wide grid.
local socket = require('socket')
local N, SP, TW = 65, 2.0, 128
local r = {step = PROBE_STEP}
local function matName()
  local m = 'bngEarthChecker'
  if not scenetree.findObject(m) then
    local mat = createObject('Material')
    mat:setField('mapTo', 0, m)
    mat:setField('colorMap', 0, '/temp/beamngEarth/probe_checker_v1.png')
    mat:setField('groundType', 0, 'ASPHALT')
    mat.canSave = false
    mat:registerObject(m)
  end
  return m
end
local function tilePos(idx) return vec3(200 + (idx % 16) * TW, -1000 + math.floor(idx / 16) * TW, 0.5) end
if PROBE_STEP == 'spawn' then
  local t0 = socket.gettime()
  local m = matName()
  for idx = PROBE_FROM, PROBE_FROM + PROBE_COUNT - 1 do
    local verts, uvs, normals, faces = {}, {}, {{x=0,y=0,z=1}}, {}
    for j=0,N-1 do for i=0,N-1 do
      local k = j*N+i
      verts[k+1] = {x=i*SP, y=j*SP, z=math.sin((idx*64+i)*0.05)*0.3}
      uvs[k+1] = {u=i/8, v=j/8}
    end end
    local fi = 0
    for j=0,N-2 do for i=0,N-2 do
      local a, b, c, d = j*N+i, j*N+i+1, (j+1)*N+i, (j+1)*N+i+1
      faces[fi+1]={v=a,n=0,u=a}; faces[fi+2]={v=c,n=0,u=c}; faces[fi+3]={v=b,n=0,u=b}
      faces[fi+4]={v=b,n=0,u=b}; faces[fi+5]={v=c,n=0,u=c}; faces[fi+6]={v=d,n=0,u=d}
      fi = fi + 6
    end end
    local name = 'bngEarthTile_'..idx
    local old = scenetree.findObject(name); if old then old:delete() end
    local proc = createObject('ProceduralMesh')
    proc:registerObject(name)
    proc.canSave = false
    scenetree.MissionGroup:add(proc.obj)
    proc:createMesh({{{verts=verts, uvs=uvs, normals=normals, faces=faces, material=m}}})
    proc:setPosition(tilePos(idx))
  end
  r.count = PROBE_COUNT
  r.spawn_ms = (socket.gettime()-t0)*1000
  r.per_tile_ms = r.spawn_ms / PROBE_COUNT
elseif PROBE_STEP == 'reload' then
  local t0 = socket.gettime(); be:reloadCollision(); r.reload_ms = (socket.gettime()-t0)*1000
elseif PROBE_STEP == 'ray' then
  local p = tilePos(PROBE_FROM or 0) + vec3(10.3, 10.7, 50)
  r.hitDist = castRayStatic(p, vec3(0,0,-1), 100)  -- ~49.5 = tile, 50.5 = grid floor
elseif PROBE_STEP == 'clear' then
  local n = 0
  for _, name in ipairs(scenetree.findClassObjects('ProceduralMesh')) do
    if name:find('^bngEarth') then local o = scenetree.findObject(name); if o then o:delete(); n = n + 1 end end
  end
  r.deleted = n
end
r.luaMemMB = collectgarbage('count')/1024
return jsonEncode(r)
