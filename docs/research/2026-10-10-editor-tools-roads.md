# World Editor road, water and AI tools: what BeamNG.Earth can drive with real data (2026-10-10)

Scope: Road Architect, Master Spline Tool, Road Spline Tool, Decal Spline Tool, Decal Road Editor, Meshroad Editor,
River Editor, Drive Path Editor, Traffic Manager, ScriptAI Editor. For each tool: what it generates, whether its core
can be called from GE Lua without the editor UI, runtime cost, assets, rebase behaviour, determinism and limits. Then
a ranked recommendation, an integration sketch and in-game probes. This report also answers the user's question
"is there a wiki for the built-in map-making tools" (section 1).

Game 0.39.4 (Linux). No game or MCP contact. `G` = `~/.local/share/Steam/steamapps/common/BeamNG.drive`, `E` =
`G/lua/ge/extensions/editor`. Engine strings come from the exe strings dump made for
`2026-10-10-perf-and-architecture.md`, and Torque3D (T3D) sources are the upstream design, not BeamNG's exact code.
Markers: **[V]** verified in files, **[I]** inference, **[P]** needs an in-game probe (section 6).

Related: `2026-10-10-official-map-look.md` §1.5 / §3.3 (DecalRoad usage in official maps),
`2026-10-10-perf-and-architecture.md` §4 (layer plan and budgets), `2026-10-10-navgraph-traffic-signals.md` (navgraph,
`core_trafficSignals`).

---

## 0. TL;DR

1. **Every stock road tool ends up as the same handful of engine primitives:** `DecalRoad` (surface overlays,
   markings and navgraph-only `road_invisible` roads), `ProceduralMesh` (Road Architect sidewalks, curbs, bridges,
   tunnels), `TSStatic` props (lamps, guardrails), `DecalData` + DecalMgr instances (Decal Spline, Road Architect
   decals), `MeshRoad`, `River`, and terrain edits (`tb:setHeight`, `tb:setMaterialIdxWs`). All of these can be created
   from plain GE Lua with `createObject` and their C++ methods. The *tools* add authoring state, undo and UI on top
   [V].
2. **No tool can be driven as-is for streaming.** Road Architect's `finalise()` rebuilds *all* roads, then calls
   `be:reloadCollision()` and `map.reset()` (the full DecalRoad navgraph rebuild, which would wipe our custom graph)
   (`E/tech/roadArchitect/roads.lua:1269-1330`). Its road data holds imgui pointers (`im.FloatPtr`). Road Spline,
   Master Spline and Decal Spline keep module-global spline arrays and call `editor.*` (setDirty, getNodes,
   decal persistence), plus `extensions.editor_terrainEditor` for painting. They are usable only after
   `editor_main.initializeModules()` and the editor extensions are loaded [V/P].
3. **What to drive is the primitives, with the tools' conventions as the style guide.** Rank:
   (1) `DecalRoad` for markings, edge blends and wear within about 200 m of the car, configured the way Road Spline and
   Road Architect configure them. This depends on probes P1 to P3 (projection onto our hidden terrain or mesh tiles,
   re-clip cost on terrain commits).
   (2) `River` for OSM rivers and canals near the car.
   (3) `MeshRoad` for short bridge decks with built-in collision, as a stop-gap before the server `.cdae` bridge
   writer.
   (4) `ai.driveUsingPath{wpTargetList=...}` (Drive Path Editor) and `ai.startFollowing` (ScriptAI) for
   GPS-following AI and ghost replays.
   Everything else (junction meshes, sidewalks, grading, navgraph) stays **server-side** as planned. We take the
   tools' algorithms and material choices, not their code paths.
4. **Determinism:** the tools seed RNG from anchor-frame positions (`roadUtils.lua:23,120`), from a per-profile seed
   (`roadArchitect/decals.lua:175`), or not at all (`decalSpline/populate.lua:21,38`, `staticMesh.lua:142`). None of
   them is stable under our rebases. **All randomness must be resolved on the server** (hash of feature id + salt),
   and the mod receives explicit polylines and positions.
5. **Rebase:** node-based objects (`DecalRoad`, `MeshRoad`, `River`) store world-space nodes and must be
   **recreated** in the new frame. Batch-create them with the `Node` field before `registerObject`, or with
   `insertNodeNoRegen` + `regenerate()`. `ProceduralMesh` and `TSStatic` can be **moved** with one transform. DecalMgr
   instances are recreated.
6. **Docs/wiki:** the old `wiki.beamng.com` now 301-redirects to `documentation.beamng.com`. The official docs have one
   page (often a stub) per tool, a 13-section "Level Creation" guide and per-class reference pages (DecalRoad,
   MeshRoad). Most pages say they are "incomplete". None of them documents the tools' Lua APIs. **The Lua source in
   `G/lua/ge/extensions/editor` is the real reference** (section 1).

---

## 1. Documentation that exists (the "wiki" question)

| Source | What is there | Useful for us |
|---|---|---|
| `https://documentation.beamng.com/world_editor/tools/` | 27 tool pages. Multi-page sections exist for Master/Road/Mesh/Assembly/Decal Spline, Drive Path, Audio Ribbon and Road Architect (11 sub-pages: introduction, profile, junction, terraforming, disk options...). The ScriptAI page is a stub that points to the BeamNG.tech docs. | Concepts, field meanings, junction catalogue, spline-tool presets (road design standards: Freeway 4 %/500 m/5°, ... Off-Road 24 %/12 m/18°) |
| `.../world_editor/api_reference/` | 16 pages on *extending* the editor (tool extensions, edit modes, undo system, gizmo, inspector). The editor is Lua, the core is under `lua/ge/extensions/editor`, and the deeper API is in `editor/api`. | Nothing on driving road tools from scripts |
| `.../modding/levels/level_creation/` (sections 1 to 13, updated July 2026) | Workflow guide: terrain/water, roads (section 3: DecalRoad for most roads, MeshRoad for bridges, Road Architect, Road Spline), vegetation, performance (section 8: qualitative only, no numeric budgets) | Confirms the official approach (terrain-painted asphalt + DecalRoads) |
| `.../modding/levels/level_classes/decalorad/` (sic) and `/meshroad/` | Per-class field reference. DecalRoad lists the navgraph fields `drivability`, `autoLanes`, `lanesLeft/Right`, `oneWay`, `flipDirection`, `gatedRoad`, `autoJunction`, `useSubdivisions`, `hiddenInNavi`, and warns that "very long roads can trigger packed position range or vertex count errors, split them". MeshRoad node = `[x,y,z,width,depth,nx,ny,nz]`. | Field semantics; the split-long-roads rule matches Road Spline's 100-point chunking |
| BeamNG.tech docs (`/beamng_tech/tools/scriptaieditor/`, Road Architect OpenDRIVE import/export) | ScriptAI windows and modes; OpenDRIVE `.xodr` import/export is **tech-only** and work in progress | Not needed |
| `wiki.beamng.com` | Retired: `Starting_a_new_map_project` returns 301 to `documentation.beamng.com` | - |
| Forum and Discord (linked from the docs), community tutorials (2013 terrain tutorial, TK Arcade videos) | Workflow-level material | Visual references only |

Bottom line for the user: there is official documentation but no real API wiki. For scripting, read the source. This
report and the earlier research docs work as our own wiki for these tools.

---

## 2. The primitives the tools emit (shared facts)

| Primitive | Lua creation (no editor needed) | Engine behaviour | Rebase |
|---|---|---|---|
| `DecalRoad` | `createObject('DecalRoad')`, `setField(...)`, then either `setField('Node',0,"x y z w")` repeated **before** `registerObject` (used at runtime by `util/procTrack.lua:320-340, 878-900`), or `insertNodeNoRegen(pos,w,idx)` ... `regenerate()` (`roadSpline/layerMgr.lua:202-205, 351`) [V]. `editor.addRoadNode` is only `insertNode` + `editor.setDirty` (`E/api/roadRiver.lua:38-44`) [V]. | Projects onto the **TerrainBlock** (T3D clips terrain polys only, `decalRoad.cpp:1445`). With `overObjects`, BeamNG "enables raycast down on static meshes" (exe help string) [V]. Without terrain and without `overObjects` the engine warns "...else it will crash" [V]. Re-clips when the terrain changes (`decalRoad.cpp:388,1691`). Batched by material and renderPriority, with `distanceFade` [docs]. | Nodes are world-space with no usable object transform [I, P4]. **Recreate.** `setNodePosition` regenerates on every call. |
| `ProceduralMesh` | `createObject('ProceduralMesh')`, `registerObject`, `createMesh({{verts,faces,normals,uvs,material}})` (`roadMesh.lua:347-360, 867-871`) [V] | World-space verts with the object at the origin. Collision via `be:reloadCollision()` (`roads.lua:1318`). The project's earlier "ProceduralMesh size limit" note applies. | `setTransform`: rigid move [I]. |
| `TSStatic` props | `createObject('TSStatic')` + `shapeName` + `setPosRot` (`staticMesh.lua:146-150, 215-219`) [V] | One object per lamp or guardrail piece. Official maps use **Forest items** for these. | Move. |
| `DecalData` + instance | `createObject('DecalData')` (`material`, `texRows/Cols`), then `Engine.Render.DecalMgr.addDecalTangent(pos, nml, tan, template, scale, frame, flags, alpha)` (`E/api/decal.lua` addDecalInstanceWithTan) [V] | Clipped at add, re-clipped on `notifyDecalModified` [I]. No count limit found in the exe strings [P]. | Recreate (or edit position + notify) [P]. |
| `MeshRoad` | `createObject('MeshRoad')` + `topMaterial/bottomMaterial/sideMaterial`; `insertNode(pos,w,depth,normal,idx)`. **No `insertNodeNoRegen`** in the bindings, so insert-per-node regenerates every time; use the `Node` field (8 floats) before register (`meshRoad.cpp:961,990`) [V bindings / P BeamNG]. | Has collision (`MeshRoadConvex` in exe; T3D `buildPolyList` collision) [V]. T3D clamps width and depth to 0.25 to 50 m (`meshRoad.cpp:64-67`) [V T3D, P BeamNG]. | Recreate. |
| `River` | `createObject('River')` (`editor.createMesh` sets ripple/wave/foam defaults, `E/api/roadRiver.lua:154-185`); `insertNodeNoRegen` exists for River, plus `setMetersPerSegment`, `setMaxDivisionSize` [V bindings]. | Water object: buoyancy (`density`), drag (`viscosity`), current (`FlowMagnitudePhysics`), reflections (`fullReflect`), `LowLODDistance` [docs]. | Recreate. |
| Terrain edits | `tb:setHeight/ setHeightGrid`, `tb:setMaterialIdxWs(posWS, idx)`, then `tb:updateGridMaterials(min,max)` + `tb:updateGrid(min,max)` (`E/toolUtilities/terrainPainter.lua:80-100`, `E/terraform/terraform.lua:154-208`) [V] | Per-cell Lua calls. They fire terrain-update signals, which re-clip DecalRoads and rebuild GroundCover cells [I]. | Our server owns the heightmap and layers. These are only for small patches. |
| Navgraph | `map.reset()` scans every DecalRoad with `drivability > 0` (`G/lua/ge/map.lua:567+`, `useSubdivisions` uses edge data) [V]. `map.reset(customNodes)` skips DecalRoads entirely (navgraph doc). | All or nothing. | Rebuild with stable names (navgraph doc §2.8). |

The materials every road tool uses are **global** (`art/` loads at startup, map-look doc §2): decal-road materials
`road_invisible, m_line_white(_discontinue), m_line_yellow_double_discontinue, m_road_asphalt_edge(_grass),
m_road_edge_dirt, m_tread_marks_clean, road_rubber_double, m_asphalt_cracks_02, repair1/2, road_patches1,
m_asphalt_damaged_01/02, gutter1, m_dirt_variation_04, road_asphalt_2lane` are all in
`art_shapes.zip: art/shapes/common/decalroads/main.materials.json`. The mesh materials `m_asphalt_new_01, slabs_large,
m_sidewalk_curb_trim_01` are in `art/shapes/common/materials/main.materials.json`. The props `eca_lamppost.dae`,
`pole_light_double.dae` and `italy_guardrails_basic.dae` are in `art_shapes.zip` [V]. River textures are `/core/art/water/*`
[V]. **Nothing needs to be shipped.**

---

## 3. Per-tool findings

### 3.1 Road Architect (`E/roadArchitect.lua` 8.1k lines + `E/tech/roadArchitect/*` 25k lines; presets in `G/roadArchitect/{profiles,groups}`)
- **Generates on "Render mode" (`roads.finalise`, `roads.lua:1269-1330`)** [V]:
  - Per road section of `road_lane` lanes: one **navgraph DecalRoad** with `material=road_invisible`,
    `drivability=1`, `autoLanes=false`, `lanesLeft/Right`, `oneWay` from the profile, and nodes lifted 4.2 m
    (`decals.lua:104-140`).
  - **Layer DecalRoads** for centre/edge/lane lines, edge blends and wear (`decals.lua:189-337`).
  - **DecalData + decal instances** for decal layers (`decals.lua:427-440`).
  - **ProceduralMesh** sidewalks (`slabs_large`) and curbs (`m_sidewalk_curb_trim_01`), draped by `castRayStatic`
    per vertex (`roadMesh.lua:33-35, 76-90, 347-360`).
  - Bridge decks: a parabolic-arch ProceduralMesh with `m_asphalt_new_01` (`roadMesh.lua:700-880`).
  - Auto-tunnel ProceduralMeshes (`tunnelMesh.lua:377`).
  - **TSStatic** props spaced along lanes (lamps, guardrails) with random jitter (`staticMesh.lua:100-150`).
  - Then a global `be:reloadCollision()` and `map.reset()`.
  - The **asphalt itself is not a mesh**: it is the terrain, painted and graded (`terraform.lua`), exactly like the
    official maps.
- **Junctions:** 13 templates (crossroads, T, Y, roundabout, merges, separators, highway slip...), placed by hand. They
  become plain roads after `finaliseJunction` (`junctions.lua:10396-10424`). There is no automatic junction builder
  for arbitrary graphs. The closest thing is **`importRoadsFromLSystem(roadNetwork, intersections, DOI, margin,
  doTerraform)`** (`junctions.lua:10329-10391`, no caller in the shipped code). It takes road polylines plus
  intersection {pos, radius, connectedRoads}, builds 1-lane-each-way roads only (`createProfileFromDecalData(1,1)`),
  chops them at the junction sphere and adds corner-fillet overlay DecalRoads. This is the right shape for an OSM
  import, but it is too limited (lane count, no classes).
- **Profiles** (`G/roadArchitect/profiles/*.json`, 21 presets: Urban/Rural/Hwy 1W/2W x 1L/2L, Tracks 1-6,
  lamps/barriers) give us a ready **style table**: which line material goes where (US-style
  `m_line_yellow_double_discontinue` centre, `m_line_white` edges, `m_road_asphalt_edge` blends, `gutter1`), lamp
  meshes and guardrail meshes [V].
- **Headless use:** possible only by `require('editor/tech/roadArchitect/roads')` etc.
  - `setDirty` needs `extensions.editor_terrainEditor` (`roads.lua:143-152`).
  - Decals need `editor.addRoadNode`, which exists after `extensions.editor_main.initializeModules()` (precedent:
    `util/screenshotCreator.lua:1747`).
  - Road records hold imgui pointers.
  - `finalise` is all-or-nothing and calls `map.reset()`.
  - Verdict: **not drivable for streaming** [V/P7].
- **Cost [I]:**
  - Geometry: adaptive discretisation of 1 to 10 m per division by curvature (`geometry.lua:134-161`), so about
    100 to 1000 div points per km.
  - Terraforming: per-cell Lua over the road box + DOI. The docs say 2 to 7 s per run and that it blocks the UI.
  - Finalise: global collision rebuild plus a full navgraph rebuild.
- **Limits:** node z clamped to ±1000 m and banking to ±50° in the drag handlers (`roads.lua:8-9, 563-620`).
  This is UI only, but our anchor frame has h0 = sea level, so roads above 1000 m would hit the clamp if we used
  those handlers [V]. Bridges have only 2 nodes. Loading a session works only on the same map. OpenDRIVE is tech-only.
- **Determinism:** `math.randomseed(profile.conditionSeed)` for wear (`decals.lua:175`). Prop jitter uses the shared
  `math.random` stream (`staticMesh.lua:142`), so it depends on call order.

### 3.2 Master Spline Tool (`E/masterSpline*`, `E/masterSpline/{splineMgr,layerMgr,autoRoadGen,homologation}.lua`)
- **Generates nothing itself.** It is a coordinator: a centre spline (`nodes, widths, nmls`) is discretised
  (Catmull-Rom; optionally conformed to the terrain or auto-banked), offset per layer, RDP-simplified at 0.25 m and
  pushed into linked Mesh/Assembly/Decal/Road Spline objects (`layerMgr.lua:58-140`) [V].
- Extras:
  - Road-design-standard analysis and live optimisation (`homologation.lua`, presets in
    `toolUtilities/roadDesignStandards.lua`).
  - A* auto-routing between nodes (`autoRoadGen.lua`, "experimental, 1-2 min on long splines").
  - Terraform via `E/terraform/terraform.lua` (per-cell `tb:setHeight` + blur).
- **Headless:** the data is plain tables (`addNewMasterSpline`, then set `nodes/widths/nmls`, `isDirty=true`, then
  `updateDirtyMasterSplines()`). But the linked tools need editor state, and terrain conform uses
  `core_terrain.getTerrain()`.
- **Use for us:** none at runtime. The design-standard presets are a useful **server-side sanity check** for road
  grading (max grade or banking per road class).

### 3.3 Road Spline Tool (`E/roadSpline.lua`, `E/roadSpline/{groupMgr,layerMgr,import}.lua`)
- **Generates only DecalRoads** (all `drivability=-1`, so **no navgraph**), one per layer: centre, edge and lane
  lines, edge blends 1-3, tread marks, cracks, repairs, patches, damage. Each layer has fixed material, width,
  texture length, lateral position (fraction of half-width) and render priority (`layerMgr.lua:5-90`) [V].
- Also **terrain painting** under the spline (`terrainPainter.lua`: polygon scanline, then `setMaterialIdxWs` per
  cell) and a **bitmap-mask import** that skeletonises a mask into splines (`skeleton.lua`, `import.lua`) [V].
- **Long roads are chunked at 100 div points per DecalRoad** with shared boundary points and fades only at the outer
  ends (`layerMgr.lua:8, 255-290`). It uses `insertNodeNoRegen` + `regenerate()` [V]. Copy this.
- **Headless:** `groupMgr` uses `editor.getNodes/setDirty`, `util.vertRaycast` (`castRayStatic`, so it needs
  collidable ground under the nodes) and `extensions.editor_terrainEditor` for painting [V].
- **Cost [I]:** 6 to 8 layers per road; about 90 nodes/km/layer at the official 11-12 m median spacing, so about
  500 to 700 DecalRoad nodes per km of fully marked 2-lane road.

### 3.4 Decal Spline Tool (`E/decalSpline.lua`, `E/decalSpline/{splineMgr,populate}.lua`)
- **Generates** shared `DecalData` templates (saved through `decalPersistMan` into the level's
  `art/decals/managedDecalData.json`) and **DecalMgr instances** at arc-length spacing (`decalLength 4 m + spacing`),
  with up to 4 weighted components, Z-jitter and pre-rotation (`populate.lua:150-245`) [V].
- **Determinism: none.** It uses unseeded `math.random` (`populate.lua:21,38`; `geom.lua:1593`) [V].
- **Headless:** needs `editor.addDecalInstanceWithTan` and `editor.getDecalDataFilePath` (the persistence manager
  marks templates dirty for the *level folder*, which we must never save) [V].
- **Use for us:** not the tool. If we want arrows, crosswalk stripes or manholes, call
  `Engine.Render.DecalMgr.addDecalTangent` directly with server-chosen positions [P8].

### 3.5 Decal Road Editor (`E/roadEditor.lua` + `E/roadUtils.lua`, `E/roadDecorations.lua`, `E/roadTemplateEditor.lua`)
- UI over `DecalRoad` (create, split, fuse, flip, width, undo). The "road templates" feature (`levels/<lvl>/roadtemplates/*.road.json`) adds:
  - **child DecalRoads** offset across the parent at 2 m resolution (`roadUtils.lua:172-232`);
  - **decoration TSStatics** every `period` metres on both sides (`roadDecorations.decorateProps`, `:118-182`), with
    `collisionType='Collision Mesh'` and z from `core_terrain.getTerrainHeight`;
  - random **patch decals** (`reloadDecals`).
  It then calls `be:reloadCollision()` [V].
- **Determinism:** seeds from anchor-frame coordinates (`roadUtils.lua:23,120`), so positions would change after a
  rebase [V].
- **Use for us:** the DecalRoad field set and the "props every N m along the edge" algorithm (trivial to do on the
  server; place as Forest items, as the official maps do).

### 3.6 Meshroad Editor (`E/meshRoadEditor.lua` → shared `E/meshEditor.lua`)
- UI only. It creates `MeshRoad` through `editor.createMesh('MeshRoad', nodes, fields)` (`roadRiver.lua:146-195`).
  Node normals set the banking (`meshEditor.lua:497-522`) [V].
- MeshRoad gives a solid deck with top, side and bottom materials and its **own collision** (MeshRoadConvex). Width
  and depth are clamped to 50 m in T3D [V T3D].
- Official maps never use it (map-look doc). It is documented as the tool for "bridges, overpasses", and collision
  must be continuous across spans [docs].
- **Use for us:** a candidate for **bridge decks (v1.6)** until the server `.cdae` bridge writer exists. Rebase
  means recreate (1 object per bridge, cheap). Collision needs `be:reloadCollision()`, which is a heavy slot to
  batch with terrain commits [I, P5].

### 3.7 River Editor (`E/riverEditor.lua` → `E/meshEditor.lua`)
- UI only. `River` objects are created via `editor.createMesh('River', ...)` with stock ripple/wave/foam/cubemap
  defaults (`roadRiver.lua:154-185`) [V].
- The River has a sloped water surface following the node z, width and depth per node, a current that pushes
  vehicles (`FlowMagnitudePhysics`), buoyancy and drag, and LOD (`LowLODDistance`) [docs].
- Official maps use 2 to 7 Rivers each (map-look doc §1).
- `toolUtilities/riverbed.lua` has a riverbed carving terraform (spatial hash + blur). We do this on the server
  instead.
- **Cost [I]:** each River with `fullReflect=true` renders an extra reflection pass. Always use `fullReflect=false` +
  `cubemap`, and keep `SegmentLength/SubdivideLength` coarse (about 10 m).
- **Use for us:** OSM `waterway=river/canal/stream` with a width within about 1 to 2 km of the car, as one River per
  tile-clipped segment. Lakes and sea use WaterBlocks (not in this report).

### 3.8 Drive Path Editor (`E/drivePathEditor*`)
- Produces AI driving routes, not scene objects: `ai.driveUsingPath{script=...}` (free-drawn) or
  `ai.driveUsingPath{wpTargetList={navgraph node names}, ...}` with per-node speeds, aggression, lane behaviour and
  `routeSpeed(Mode)` (`drivePathEditor/playback.lua:138-184`). Saved as JSON [V].
- **Use for us:** for v1.7/1.8 "AI follows the GPS route" or traffic with a set destination, send the AI the route
  as `wpTargetList` of **our stable navgraph node names**. A rebase does not invalidate names, but the AI must be
  re-issued after every `map.reset(custom)` (navgraph doc pitfall 1).

### 3.9 Traffic Manager (`E/trafficManager.lua`)
- Scenario setup: spawns vehicles, sets AI modes through `queueLuaCommand('ai.setMode/setTarget/setSpeed/...')`
  (`:340-400`) and runs `gameplay_traffic.insertTraffic/removeTraffic` (`:328-336`).
- Traffic lights: `core_trafficSignals.newController/newSequence/newSignal/setupSignals`, **followed by `map.reset()`**
  (`:484-487`). This is one more stock `map.reset()` caller that would wipe a custom graph (navgraph doc pitfall 5).
- Traffic signs are spawned as the **`roadsigns` jbeam prop vehicle** (configs stop, yield, 25-65 mph, turns;
  `:2020-2040`, `G/content/vehicles/roadsigns.zip`), and "the AI does not follow them" [docs].
- **Use for us:** the API pattern for v1.8 (already in the navgraph doc). Do not use `roadsigns` props for mass
  signage: every sign is a physics vehicle [I]. Use TSStatic signs.

### 3.10 ScriptAI Editor / Manager (`E/scriptAIEditor.lua`, `E/scriptAIManager.lua`)
- Records and plays **trajectories**: `ai.startRecording()` / `ai.stopRecording()` returns a time- or speed-based
  script, saved as `/replays/scriptai/tracks/*.track.json`; playback with `ai.startFollowing(script)`
  (`scriptAIManager.lua:73-112`). Trajectories can be drawn and edited in the editor (`scriptAIEditor.lua:936-1125`) [V].
- **Use for us:** ghosts or "replay a run" for generated time trials and Cannonball (roadmap Gameplay). The script is
  in world coordinates. Store it in lat/lon/h (or ECEF) on our side, and after a rebase re-issue `startFollowing` with
  the transformed script.

### 3.11 Also found (outside the requested list, road-relevant)
- **`editor_terrainAndRoadImporter`** (`E/terrainAndRoadImporter.lua`; UI is tech-licence gated, functions exported):
  `importRoads(jsonPath, DOI, margin)` reads `[[{x,y,width},...],...]`, triangulates road ribbons with a bloated
  margin, kd-tree point-in-triangle per terrain cell, takes the lowest road z per cell, Gaussian-blurs the mask,
  writes `tb:setHeight`, then creates `road_asphalt_2lane` DecalRoads (`drivability=1`) and calls `map.reset()`
  (`:233-448, 581-628`) [V]. This is the stock **"roads from data" grading algorithm**: the same idea as our planned
  server-side grading, but in Lua on the main thread.
- **`tech_openStreetMapExporter` / `tech_sumoExporter` / `tech_openDriveExporter`**: export the *navgraph*
  (`map.getGraphpath()`, `openStreetMapExporter.lua:222-239`) to `.osm` / SUMO / `.xodr`. The UI is tech-gated
  (`roadNetworkExporter.lua`). Exporting our generated navgraph to `.osm` and diffing it against the source OSM
  would be a cheap **validation test** [P9].
- `sidewalkSpline` places kit TSStatics (`square.dae`/`triangle.dae` pieces) with a seeded RNG (`splineRandomSeed`).
- `util/procTrack.lua` creates DecalRoads at **runtime outside the editor**, using the `Node` field (`:320-340`).
  This is a stock precedent for our use.

---

## 4. Ranked recommendation

| Rank | Drive this | For | Instead of | Condition |
|---|---|---|---|---|
| 1 | `DecalRoad` (raw), configured like Road Spline / Road Architect profiles | Lane, edge and centre lines, edge blends (asphalt to grass/dirt), wear (cracks, patches, tread marks) within the fade radius (about 200 m); dirt-road variation overlays | Baking markings into our road ribbon meshes (perf doc §4.3 "markings as a 2nd UV set") | P1 (renders on our hidden TerrainBlock or with `overObjects` on mesh tiles), P2 (re-clip cost per terrain commit is within budget), P3 (creation ≤ 2 ms per 100 nodes). If P1 or P2 fails, fall back to the perf-doc plan (markings in the ribbon mesh). |
| 2 | `River` | OSM rivers and canals with width near the car (buoyancy, current, real water look) | A water colour in the tile texture only | P6 (frame cost with `fullReflect=false`; sloped rivers on our terrain) |
| 3 | `MeshRoad` | Bridge and overpass decks (v1.6) with collision, 1 object per bridge | A server `.cdae` deck + `Visible Mesh Final` collision | P5 (collision works for vehicles after `be:reloadCollision`; width limit; `Node`-field creation) |
| 4 | `ai.driveUsingPath{wpTargetList}` / `ai.startFollowing` | AI along the GPS route (v1.7/1.8), ghosts and time trials | Writing our own path follower | Navgraph v1.7 in place |
| 5 | DecalMgr instances (`addDecalTangent`) | Painted arrows, crosswalks, stop lines, manholes at server-chosen spots | Decal Spline Tool | P8 |
| - | Road Architect, Master/Road/Decal Spline, Decal Road templates, Terrain-and-Road Importer | **Not at runtime.** Use them as a source of style tables (profiles, layer materials, widths, texture lengths, fades, render priorities) and algorithms (chunk at 100 points, RDP 0.25 m, fillet overlays at junctions, design standards, grading) re-implemented on the server | - | - |
| - | `map.reset()` from DecalRoads | **No.** Keep `map.reset(customNodes)` (navgraph doc). Our DecalRoads always use `drivability=-1`, so a stray stock `map.reset()` cannot pick them up half-built. | - | - |

Why not "let Road Architect build the city": it needs a full editor session, it rebuilds the whole network and
collision on every change, it overwrites the navgraph, its RNG is not rebase-stable, junctions are manual templates,
and the 1-lane-only graph import is unused code. For our cases, grading and junction geometry are better done in
numpy on the server, which already owns the heightmap.

---

## 5. Integration sketch

### 5.1 Server (per L0 tile, 256 m, in the tile-local or global frame; versioned and deterministic)
- Build the road graph (OSM/Overture) and grade the DEM under the roads first (perf doc §4.3).
- Per way, pick a **profile** by class, lanes and country driving side (style table derived from
  `G/roadArchitect/profiles/*.json` and Road Spline's `layerMgr.lua:5-90`). Compute centreline offsets for each
  layer, clip to the tile with 2 m overlap, RDP-simplify at 0.25 m, split at ≤ 100 nodes, and drape z on the *graded*
  DEM + 2 cm. With `overObjects`, add the lift Road Architect uses (+4.2 m raycast start), except under bridges, where
  the raycast would hit the deck.
- Wear layers (cracks, patches, repairs): choose segments with `hash(osm_id, layer, salt)`, so the server sends
  explicit start/end chainages, never a seed.
- Junction fillets: corner arcs between adjacent approaches (Road Architect's `createAutoJctOverlay` idea), sent as
  ordinary edge-line or blend polylines; stop lines and arrows as decal-instance records.
- Message (protocol v5 addition): `roads_tile {key, frame, layers:[{mat, w | widths[], texLen, prio, fade:[d,r],
  startEndFade:[a,b], bias, nodes:[[x,y,z],...]}], decals:[{tpl, pos, nml, tan, scale, frame}], rivers:[{nodes:[[x,y,z,w,d]], flow}],
  bridges:[{nodes:[[x,y,z,w,d,nx,ny,nz]], top, side, bottom}]}`, plus `roads_drop {key}`. Use binary floats for node
  arrays, as `forest_cell` does.

### 5.2 Mod (`roads.lua`, governor kind `roadTile`, budget ≤ 2 ms per unit)
```lua
-- create one layer chunk in a single generation pass
local r = createObject('DecalRoad')
r:setField('material', 0, L.mat);      r:setField('improvedSpline', 0, 'true')
r:setField('drivability', 0, '-1');    r:setField('textureLength', 0, tostring(L.texLen))
r:setField('renderPriority', 0, tostring(L.prio))
r:setField('distanceFade', 0, string.format('%g %g', L.fade[1], L.fade[2]))
r:setField('startEndFade', 0, string.format('%g %g', L.se[1], L.se[2]))
r:setField('decalBias', 0, tostring(L.bias or 0.005))
r:setField('overObjects', 0, OVER_OBJECTS and 'true' or 'false')   -- P1 decides
for i, n in ipairs(L.nodes) do                                      -- anchor-frame xyz from tile frame
  local x, y, z = xf(n)
  r:setField('Node', 0, string.format('%.3f %.3f %.3f %.3f', x, y, z, L.w or L.widths[i]))
end
r:registerObject('')               -- name-less; keep ids in a per-tile list
group:addObject(r)
```
- Streaming: tiles within about 300 m (fade 200 m + margin) get roads. Drop by deleting the tile's object list.
  Never remove before the replacement exists (`far_swap` rule).
- Terrain commits (follow): after each commit, `regenerate()` only the DecalRoads of tiles that *entered* the block
  (they had no terrain to clip against before). Budget this with P2's numbers. If the engine already re-clips them
  through the terrain update signal, skip it.
- **Rebase:** delete and recreate all road chunks from the cached server data (tile frame to new anchor, exact),
  spread over frames nearest-first. Rivers and MeshRoad bridges are recreated the same way. ProceduralMesh and TSStatic
  extras get `setTransform`. The navgraph is rebuilt via `map.reset(custom)` with stable names, and AI path commands
  are re-issued.
- Guard against stock `map.reset()` callers (Traffic Manager, Road Architect, Terrain-and-Road Importer, flowgraph):
  hook `onNavgraphReloaded` and re-apply the custom graph (navgraph doc §2.7).
- Never call the editor tools themselves. Never touch `decalPersistMan` or level saves.

---

## 6. In-game probes (run only when the user is not playing; our level; via MCP `run_lua`; camera on the car, zero inputs)

```lua
-- P1 DecalRoad on our ground: does it render / clip on the hidden TerrainBlock? with overObjects on mesh tiles?
local p = core_camera.getPosition(); local d = core_camera.getForward(); d.z = 0; d:normalize()
local function mk(over)
  local r = createObject('DecalRoad'); r:setField('material',0,'m_line_white'); r:setField('improvedSpline',0,'true')
  r:setField('drivability',0,'-1'); r:setField('overObjects',0, over and 'true' or 'false')
  for i = 0, 20 do local q = p + d*(20 + i*10); q.z = q.z + (over and 4.2 or 0)
    r:setField('Node',0,string.format('%.3f %.3f %.3f 0.3', q.x, q.y, q.z)) end
  local t = hptimer(); r:registerObject(''); scenetree.MissionGroup:addObject(r)
  return r, t:stop(), r:getEdgeCount()
end
local a, ta, ea = mk(false); local b, tb_, eb = mk(true)
log('I','probe', string.format('P1 terrain: %.2f ms edges=%d | overObjects: %.2f ms edges=%d', ta, ea, tb_, eb))
-- then: screenshot; repeat with near tiles' decalType set to 'Visible Mesh' (farfield.lua:187 sets 'None')
-- P2: with 50 such roads around the car, time one terrain-follow commit (perfmon frame ms before/after) and
--     tb:updateGrid over the full block; log whether edges change (re-clip) and the spike in ms.
-- P3: create 100-node roads three ways (Node field / insertNodeNoRegen+regenerate / insertNode) x 20, mean ms each.
-- P4: a:setPosition(a:getPosition() + vec3(5,0,0)) -> does the decal move? (expect no: recreate on rebase)
-- P5 MeshRoad deck with collision
local m = createObject('MeshRoad'); m:setField('topMaterial',0,'m_asphalt_new_01')
m:setField('sideMaterial',0,'m_asphalt_new_01'); m:setField('bottomMaterial',0,'m_asphalt_new_01')
for i = 0, 10 do local q = p + d*(30 + i*10); q.z = q.z + 3
  m:setField('Node',0,string.format('%.3f %.3f %.3f 12 1.5 0 0 1', q.x, q.y, q.z)) end
m:registerObject(''); scenetree.MissionGroup:addObject(m)
local t = hptimer(); be:reloadCollision(); local tc = t:stop()
local hit = castRayStatic(p + d*80 + vec3(0,0,20), vec3(0,0,-1), 100)
log('I','probe', string.format('P5 nodes=%d reload=%.1f ms ray=%.2f', m:getNodeCount(), tc, hit))
-- also try width 60 (clamped to 50?), and drive a car over it later (user present).
-- P6 River: same Node format via editor defaults; fullReflect=false; perfmon A/B frame ms; containsPoint(q).
-- P7 headless editor: extensions.editor_main.initializeModules(); log(type(editor.addRoadNode));
--     log(pcall(extensions.load,'editor_terrainEditor')); log(pcall(require,'editor/roadSpline/layerMgr'))
-- P8 decal instance: local tpl=createObject('DecalData'); tpl:setField('material',0,'crossing_white'); tpl:registerObject('')
--     local inst=Engine.Render.DecalMgr.addDecalTangent(p+d*15, vec3(0,0,1), d, tpl, 3, -1, 0, 1); log(inst and inst.uid)
-- P9 navgraph export after map.reset(custom): extensions.load('tech_openStreetMapExporter');
--     pcall(tech_openStreetMapExporter.export, '/temp/earth_nav') -> diff against source OSM offline.
-- P10 terrain paint corridor: 1 km x 10 m of setMaterialIdxWs + updateGridMaterials on the hidden block: ms.
-- Cleanup: delete every probe object; map.reset(<our custom nodes>) if anything touched the graph.
```

Expected outcomes and decisions:
- **P1:** "terrain" works means rank 1 goes ahead with `overObjects=false`. If only "overObjects + Visible Mesh"
  works, set near-tile `decalType` accordingly.
- **P2:** if the spike exceeds 3 ms per commit at 134 m/s, limit DecalRoads to below 60 mph or bake markings into
  the mesh.
- **P3:** the creation method decides the governor unit size.
- **P5 and P6:** go/no-go for ranks 3 and 2.

---

## 7. Numbers to carry forward

| Item | Value | Source |
|---|---|---|
| DecalRoad chunk size | ≤ 100 div points per object | `roadSpline/layerMgr.lua:8` [V] |
| Node simplification | RDP 0.25 m | `roadSpline/layerMgr.lua:10`, `masterSpline/layerMgr.lua:113` [V] |
| Official overlay fade | 200/50 m (WCUSA), 80-90/30-40 m (Italy) | map-look doc §1.5 [V] |
| Official node spacing | median 11-12 m, 2-4 nodes per road | map-look doc §1.5 [V] |
| Layers per fully marked road | 6-8 DecalRoads (centre, 2 edges, 2-3 blends, 1-2 wear) | `layerMgr.lua:5-90` [V] |
| DecalRoad nodes per km (2-lane, marked) | about 500-700 | [I] from the two rows above |
| Road Architect div spacing | 1-10 m by curvature radius | `geometry.lua:157-161` [V] |
| MeshRoad width/depth clamp | 0.25-50 m | T3D `meshRoad.cpp:64-67` [V T3D, P5] |
| Terraform cost (stock Lua) | 2-7 s per run, blocks the UI | Master Spline docs [docs] |
| Lift for overObjects raycast | +4.2 m (decals), +4.5 m (meshes) | `decals.lua:23`, `roadMesh.lua:28` [V] |
