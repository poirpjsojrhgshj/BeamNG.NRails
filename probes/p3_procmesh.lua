-- Usage: prepend "PROBE_N=<grid verts per side>; PROBE_STEP='create'|'ray'|'reload'|'ray2'|'delete'"
local socket = require('socket')
local N, SP = PROBE_N or 17, 1.0
assert((N-1)*(N-1)*2 <= 8192, "refusing: >8192 tris per ProceduralMesh hangs the engine (see docs)")
local ORIGIN = vec3(300, 0, 5)
local name = 'bngEarthProbeMesh'
local r = {N = N, step = PROBE_STEP}
local from = ORIGIN + vec3(3.3, 3.7, 45)
if PROBE_STEP == 'create' then
  local old = scenetree.findObject(name); if old then old:delete() end
  local t0 = socket.gettime()
  local verts, uvs, normals, faces = {}, {}, {{x=0,y=0,z=1}}, {}
  for j=0,N-1 do for i=0,N-1 do
    local k = j*N+i
    verts[k+1] = {x=i*SP - (N-1)*SP/2, y=j*SP - (N-1)*SP/2, z=0}
    uvs[k+1] = {u=i/(N-1), v=j/(N-1)}
  end end
  local fi = 0
  for j=0,N-2 do for i=0,N-2 do
    local a, b, c, d = j*N+i, j*N+i+1, (j+1)*N+i, (j+1)*N+i+1
    faces[fi+1]={v=a,n=0,u=a}; faces[fi+2]={v=c,n=0,u=c}; faces[fi+3]={v=b,n=0,u=b}
    faces[fi+4]={v=b,n=0,u=b}; faces[fi+5]={v=c,n=0,u=c}; faces[fi+6]={v=d,n=0,u=d}
    fi = fi + 6
  end end
  local t1 = socket.gettime()
  if not scenetree.findObject('bngEarthProbeMat') then
    local mat = createObject('Material')
    mat:setField('mapTo', 0, 'bngEarthProbeMat')
    mat:setField('colorMap', 0, 'core/art/trackBuilder/track_editor_mud_d.dds')
    mat:setField('groundType', 0, 'DIRT')
    mat.canSave = false
    mat:registerObject('bngEarthProbeMat')
  end
  local proc = createObject('ProceduralMesh')
  proc:registerObject(name)
  proc.canSave = false
  scenetree.MissionGroup:add(proc.obj)
  proc:createMesh({{{verts=verts, uvs=uvs, normals=normals, faces=faces, material='bngEarthProbeMat'}}})
  proc:setPosition(ORIGIN)
  r.tris = (N-1)*(N-1)*2
  r.buildTables_ms = (t1-t0)*1000
  r.createMesh_ms = (socket.gettime()-t1)*1000
elseif PROBE_STEP == 'ray' or PROBE_STEP == 'ray2' then
  local t0 = socket.gettime()
  r.hitDist = castRayStatic(from, vec3(0,0,-1), 100)  -- 45 = mesh, 50 = grid ground
  r.ray_ms = (socket.gettime()-t0)*1000
elseif PROBE_STEP == 'reload' then
  local t0 = socket.gettime()
  be:reloadCollision()
  r.reload_ms = (socket.gettime()-t0)*1000
elseif PROBE_STEP == 'delete' then
  local o = scenetree.findObject(name); if o then o:delete() end
end
return jsonEncode(r)
