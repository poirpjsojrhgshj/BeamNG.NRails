# World Editor tools for buildings, vegetation, linear props, audio and particles: can BeamNG.Earth drive them from real data? (2026-10-10)

Scope: Building Architect, Biome Tool, Forest Editor, Mesh Spline Tool, Assembly Spline Tool, Terrain Editor
(material painting), Prefabs, Audio Ribbon Editor and Particle Editor. For each tool this report covers what it
generates, whether its core can run from GE Lua without the editor UI, what it costs at runtime, which assets it uses,
how it behaves on a rebase, whether it is deterministic, and its limits. The last sections give a ranked
recommendation, an integration sketch, and the in-game probes needed to confirm it.
Game: BeamNG.drive 0.39.4 (Linux build, buildbot 20972). I did not contact the game or its MCP server.

Paths: `GAME` = `~/.local/share/Steam/steamapps/common/BeamNG.drive`. `lua/...` paths are relative to GAME.
`E/` = `lua/ge/extensions/editor/`. Scratch files are in `scratchpad/wetools/` (exe strings dump, extracted level and
asset files, `scripts/daetris.py` for DAE triangle counts).

Markers: **[V]** verified in game files, exe strings or a measurement taken for this report. **[D]** from the online
documentation. **[I]** inference. **[P]** needs an in-game probe (section 6).

---

## 0. Summary

| Tool | What it really is underneath | Usable headless? | Verdict for BeamNG.Earth |
|---|---|---|---|
| **Forest Editor** | `ForestData` API (`createNewItem/removeItem/updateItem/getItems*`) plus the editor-only `ForestBrushTool` | **Yes, through `ForestData`.** Bound in `registerLuaApisSceneObjects`, not the editor API [V] | **Use it (rank 1).** Server places trees, rocks and repeated props. The mod calls `createNewItem` in governor batches |
| **Assembly Spline** | Lua placement math over **kits** (`assets/meshes/props/assembly_kit/*`, anchors `nail.<join>.<point/head/aux>`) that emits one **TSStatic per piece** | Partly. Pure Lua, but the module state lives in the tool, and terrain normals need `editor_terrainEditor` [V] | **Reuse the kits and the math (rank 2)**, not the tool. Guardrails, fences and telegraph poles with wires from OSM. Posts go in as Forest items |
| **Terrain Editor (painting)** | `TerrainBlock:setMaterialIdxWs/updateGridMaterials/updateGrid` and `importMaps(…, materials, textureMaps)` | **Yes.** These are TerrainBlock methods. Only grid conversion uses the editor's `TerrainEditor` [V] | **Use `importMaps` layer maps (already the v1.5 plan, rank 3).** `setMaterialIdxWs` only for small patches |
| **Audio Ribbon** | Runtime module `core_audioRibbon` (pure Lua, always loaded, `main.lua:347`) that moves FMOD `SFXEmitter`s to the closest point on a ribbon | **Yes.** `setRibbons(tbl)` and `updateRibbonData(r)` [V] | **Use it (rank 4).** River and waterfall sound from OSM waterways, a few µs per frame |
| **Prefabs** | `spawnPrefab()` / `PrefabV2:spawn()` (`ge_utils.lua:749-812`), each spawn loads a file of TSStatics | Yes [V] | **Use it selectively (rank 5).** Stock petrol stations at OSM `amenity=fuel` (the gas-station quick win), port and road furniture |
| **Particle Editor** | Edits `ParticleEmitterData`/`ParticleData` datablocks. Runtime object = `ParticleEmitterNode` | Yes. `createObject('ParticleEmitterNode')` (`flowgraph/nodes/scene/particleEmitter.lua:33-44`) [V] | **Use it (rank 6).** Waterfall spray at OSM `waterway=waterfall`, desert dust. Few objects, near the camera only |
| **Mesh Spline** | Lua: equidistant samples on a Catmull-Rom spline, **one TSStatic per piece** (`E/meshSpline/populate.lua:144,322`) | Partly (same caveats as Assembly) | **Reuse its presets as Forest items (rank 7).** Jersey barriers, lamp posts and bollards along OSM lines. The tool itself adds nothing we lack |
| **Biome Tool** | C++ `ForestBrushTool:initBiomeMatProc/LassoProc/FieldProc/EdgeProc` driven by a mask the **exact size of the TerrainBlock** | Doubtful. `ForestBrushTool` is registered in `registerLuaApisEditor` and documented "Editor use only" [V] | **Do not use.** Bound to the whole terrain block, which in our world moves every commit. Not reproducible: Replace "yields a different distribution seed" [D]. Server placement is better |
| **Building Architect** | Not present in 0.39.4: no Lua under `E/`, no strings in either the Linux or the Windows exe [V]. Only its **modules** and **materials** ship | No | **Use its assets only (rank 8).** Facade modules (`building_architect_modules/*`) as Forest items, as Italy does. `*_bat` wall and roof materials for our extruded buildings |

The common thread: every stock tool ends in one of four engine primitives:
- `ForestData` items (Forest Editor, Biome);
- per-piece `TSStatic`s (Mesh, Assembly and Decal splines, Prefabs);
- terrain layer indices (Terrain painter, spline painters);
- runtime Lua modules (audio ribbon, audio forest).

The editor tools add UI, undo and session files on top. For a streamed, deterministic, rebased world, **the server should
compute placements in the global frame**, as the perf report planned. The mod should then call the engine primitives
directly, with the stock **assets and presets** (kits, brushes, materials, emitters, FMOD events) as the content
library. None of the tools needs editor mode when used this way. The exception is `ForestBrushTool`, which we do not
want anyway.

---

## 1. Documentation (the "wiki")

The official World Editor manual is at `https://documentation.beamng.com/world_editor/` (Tools, Windows, API Reference).
The old `wiki.beamng.com` is legacy. What the manual covers:
- **Tool pages** describe UI workflows. Several are marked "work in progress" or "documentation incomplete". The Forest
  Editor page was last changed 2021-12-07, Building Architect 2025-04-02, and the site banner says Patch Notes 0.39.1.0.
- **Sub-pages for the spline tools.** The best technical content is the Assembly Spline kit rules: file names
  `*_root/_bridge/_bridge_sag/_var_*`, and anchors `nail.[join].[point|head|aux].[alias]` for ball, nail and fixed
  joints. Terraform ranges are DOI 0–500 m and margin 1–20 m. Terraforming is a "blocking operation… 2-7 seconds" [D].
- **API Reference** is about writing editor extensions: undo, edit modes, inspector, windows. It documents **no**
  forest, terrain or object functions and points to `lua/ge/extensions/editor/api` [D]. The source code is therefore the
  real reference. That is what the rest of this report uses.
- **Building Architect** is documented: six base shapes, floors, Flat/Pyramid/Shed/Gable roofs, modules (window, door,
  balcony, corner, string course, pillar, stair), save to `<level>/bat/*.json`, export to Collada **without textures**,
  and ">7 floors may cause FPS problems" [D]. The tool itself is not in this build (section 2.1).

---

## 2. Tool by tool

### 2.1 Building Architect (BAT)
- **Present?** No.
  - No BAT Lua in `E/` or anywhere under `lua/`.
  - The Linux exe and `Bin64/BeamNG.drive.x64.exe` contain none of its strings ("architect", "Gable", "roofType",
    "string course"). The Linux check ran on `strings_BeamNG.drive.x64.txt`; the Windows exe was checked with ASCII and
    UTF-16 `strings` [V].
  - It was an older C++/TorqueScript-era tool. A web search found no removal note.
- **What ships** (`content/art_shapes.zip: art/shapes/common/building_architect_modules/`) [V]:
  - **Module meshes**, each with LODs: windows 31, doors 24, corner 11, string_course 6, pillar 5, basement_plinth 4,
    roof_border 4, balcony 2, stairs 2, wall_pilaster 1.
  - Examples with tris per LOD:
    - window `R_HS_A_WN_01_120x130`: L700 730 / L150 296 / L30 20;
    - door `R_HS_A_DR_01_100x210`: 505 / 224 / 34;
    - corner `C_AP_G_CO_08_80x300`: 896 / 224 / 32, plus an 8-tri Colmesh.
  - Module materials are global: `m_wood_frame_trim_paint_01`, `m_transparent_glass_window`, `m_plaster_raw_dirty_01`,
    `m_metal_frame_trim_01`. `m_worn_brushed_plaster` is defined in `art/shapes/garage_and_dealership/garage`.
  - **`bat_materials/wall.mat.json`** has 12 v1.5 materials: `m_bricks_01_bat`, `m_concrete_cinderblock_01_bat`,
    `m_plaster_float_bat`, `m_plaster_raw_dirty_01_bat`, `m_plaster_worn_01_bat`, `m_stonebrick_eroded_01_bat`,
    `m_stonebrick_mixed_01/02_bat`, `m_stonewall_damaged_01_bat`, `m_stucco_scraped_01_bat`, `m_stucco_white_bat`,
    `m_greybox_base_bat`.
  - **`bat_materials/top.mat.json`** has 4: `cladding_zinc_bat`, `m_roof_slates_{ochre,rounded,square}_bat`.
  - These materials use **`vertColor: true`** and a second "breakup" layer on UV1 (dirt and variation), which suits
    generated meshes.
  - Their file name ends in `.mat.json`. The global loader only picks up `*materials.json` (`lua/ge/main.lua:1331`), so
    load them with `loadJsonMaterialsFile` [V file name, I loader behaviour → P8].
- **How the official maps use them:** Italy registers BAT modules as **ForestItemData** and places windows, doors and
  corners as Forest items (`levels/italy/art/forest/managedItemData.json`, e.g. `C_AP_G_CO_08_80x300` →
  `/art/shapes/common/building_architect_modules/corner/...dae`) [V].
- **Rebase, determinism, limits:** not applicable to the tool. The modules behave like any Forest item.
- **Verdict:** buildings stay **server-extruded `.cdae`** (perf report section 4.3).
  - Use the `*_bat` wall and roof materials, with the vertex colour carrying AO, tint and floor banding.
  - Near the camera (< ~300 m), optionally decorate facades with BAT window and door modules as Forest items: the server
    picks a module by facade bay size and places it at window positions, as Italy does.
  - Watch the cost: a 730-tri window × 20 per facade adds up. Use the LODs, and keep modules on close buildings only.

### 2.2 Forest Editor
- **Generates** [V]:
  - `ForestItemData`/`TSForestItemData` datablocks in `<level>/art/forest/managedItemData.json`. The editor writes them
    via `editor.createDataBlock(...)` (`E/forestEditor.lua:760-762`).
  - `ForestBrush`/`ForestBrushElement` objects in `ForestBrushGroup`, saved as `main.forestbrushes4.json`
    (`:1664, 3164`).
  - Items saved per type to `forest/<type>.forest4.json` (NDJSON `{pos, rotationMatrix, scale, type}`) by
    `forest:saveForest()`.
  - Painting goes through `ForestBrushTool:on3DMouseDown/Dragged(event, elements)` (`:2538, 2577`), which needs a
    gui3D mouse event. That makes it UI-only.
- **Headless API (what we need)** [V]:
  - `ForestData` methods are bound in `GameEngineLua::registerLuaApisSceneObjects` (exe strings): `getItem`,
    `createNewItem(itemData, MatrixF, scale)`, `addItem`, `removeItem`, `getItemsPolygon`, `getItemsCircle`,
    `getItemsFrustum`, `getItemsBox`, `getItems`, `findItemByUid`, `updateItem(key, keyPos, data, MatrixF, scale, uid)`,
    `generateAndSetItemUid`.
  - `ForestItem` methods: `getKey`, `getPosition`, `getTransform`, `getScale`, `getData`, `getUid`, `getRadius`,
    `getSize`.
  - The stock non-editor wrapper is `util/forestGenerator.lua:57-65, 141-173`.
  - Forest object: `createObject('Forest')`, `registerObject`, `MissionGroup:addObject` (`E/biomeTool.lua:3533-3541`
    uses `worldEditorCppApi.createObject`).
  - Methods `saveDataFile`, `regenCells`, `enableCollision`/`disableCollision`, `getData` (exe).
  - `disableCollision` is used only to keep brush raycasts from hitting trees (`E/forestEditor.lua:2508-2510`), so it is
    a raycast toggle and says nothing about physics [V code, I semantics].
  - `worldEditorCppApi.rebuildForestManagerInstanceData()` is called only after selection highlight changes
    (`:249, 260, 295`), not after adding items [V]. We should not need it [P].
- **Item data without the editor:**
  - `createObject('TSForestItemData')`, then `setField('shapeFile',0,path)`, `registerObject(name)`,
    `Sim.getDataBlockSet():addObject(db)` (`editor/forestTsstaticMover.lua:144-170`, `editor/api/dataBlock.lua`).
  - Or `loadJsonMaterialsFile('<level>/art/forest/managedItemData.json')` to get the tuned wind and physics fields of a
    whole level.
  - Fields: `shapeFile, collidable, radius, mass, rigidity, tightnessCoefficient, dampingCoefficient, windScale,
    trunkBendScale, branchAmp, detailAmp, detailFreq, shadowNullDetailSize, snapRotationToTerrain, annotation`
    (`NATURE`, `OBSTACLES`, `GUARD_RAIL`, `POLE`, `SIDEWALK` in Italy) [V].
- **Brush schema to copy on the server:** `ForestBrushElement` fields `forestItemData, probability, rotationRange,
  scaleMin, scaleMax, scaleExponent, sinkMin, sinkMax, sinkRadius, slopeMin, slopeMax, elevationMin, elevationMax` (exe).
  Official brushes, e.g. Italy rocks, use `scaleMin 0.8 / scaleMax 1.2` [V].
- **Runtime cost:**
  - Rendering is cell-batched with per-cell imposter batches. Counters: `$Forest::totalCells`, `$Forest::cellsRendered`,
    `$Forest::cellItemsRendered`, `$Forest::cellsBatched`, `$Forest::cellItemsBatched` [V]. JV renders 663k items.
  - Lua cost per `createNewItem`: unknown. [I] ~5–20 µs (MatrixF construction plus a C++ cell insert); [P] PF1.
  - Imposters for `/assets/.../trees_library/*` are not shipped. The engine bakes them at first use
    ("Creating imposters for: '{}'"), which is a hitch. `Engine.Render.updateImposters(true)` can pre-bake them
    (`util/compileImposters.lua`) [V]; [P] PF5.
- **Assets:** ECA, Italy, WCUSA, Utah, JV and Jungle Rock tree sets with shipped imposters, plus the global
  `trees_library`. Details are in official-map-look section 2.2. Load level materials and item data first.
- **Positions and rebase:**
  - The exe help text calls Forest "a global-bounds scene object… [items] cannot be moved at game-time" [V]. Items are in
    world coordinates and there is no per-Forest transform. `updateItem` does move items.
  - A rebase must therefore either `updateItem` every item with `T_new = R·T_old + t` (a MatrixF, so rotation works),
    or drop and re-add items per cell, nearest first.
  - [P] PF2: does `Forest:setPosition` shift items, and do two Forest objects coexist?
- **Determinism:** the API is deterministic. Randomness only comes from whoever chooses the positions, so put it on the
  server and hash it from global cell id and feature id.
- **Limits:**
  - No item cap was found. Each shape keeps the usual TSShape limits (65k verts per mesh).
  - Collision items go into the static kd-tree and need `be:reloadCollision()` (perf report: ~0.15 ms per 1k tris).
    Oak trunk Colmesh is 54 tris, so 2 000 collidable trees add ~16 ms per rebuild [I].

### 2.3 Biome Tool
- **Generates:** Forest items only [D][V]. It never creates GroundCover or terrain layers. It reads terrain material
  layers or a mask image.
- **Engine core** (`E/biomeTool.lua:1665-1743`): `ForestBrushTool()` (`:3743`) + `setActiveForest(forest)`, then:
  - `initBiomeMatProc(maskFile, matIndex, {}, centralElements, falloffElements, exclusionZones, density, borderFalloff,
    vegetationFalloff, borderDensity, {slopeInfluence, slopeMin, slopeMax}, blendMode, existingUIDs)`;
  - or `initBiomeLassoProc(lassoNodes, …)`, `initBiomeFieldProc(elements, lassoNodes, dragNodes, rowDist, itemDist,
    rowOrient, …)`, `initBiomeEdgeProc(...)`.

  It is pumped every frame with `runBiomeProcess()` and polled with `getBiomeWorkProgress()`/`isBiomeProcCompleted()`.
  `insertBiomeItems()` and `getBiomeItems()` then return `{items, itemsToDel}` (`:1757-1795, 1880-1915`) [V].
- **Constraints from exe strings** [V]:
  - "No terrain block available", "No material grids available".
  - "Terrain block size ({}x{}) and mask size ({}x{}) does not match!"
  - "Mask image… needs to be an 8-bit grayscale mask image".
  - It writes temp PNGs (`/biomeRandNoiseMask_`, `/biomeEdgePlacementEdgeMap_`).

  So it works on the **whole TerrainBlock** at its resolution. Our block is a 1–2 km physics-only block that is
  re-imported every 128–256 m.
- **Editor dependency:** `ForestBrushTool` is bound in `registerLuaApisEditor` and documented "@internal / Editor use
  only" [V]. Whether that binding exists outside editor mode: [P] PB1.
- **Determinism:** the noise mask has a seed (`RA_Seed`, default 176312589). Item placement inside the C++ proc exposes
  no seed, and the docs say Replace with the same brush "yields a different distribution seed" [D]. So it is **not
  reproducible**, which breaks the roadmap's deterministic-generation principle.
- **Cost:** unknown, C++ and multi-frame. The docs say mid-spec PCs slow down with many layers [D].
- **Verdict: do not use.** Copy its *ideas* on the server: central, falloff and edge brushes, border falloff in metres,
  slope influence, "field" rows for orchards and vineyards (OSM `landuse=orchard/vineyard`), edge placement along mask
  borders such as forest edges and hedgerows.

### 2.4 Mesh Spline Tool
- **Generates:** one **TSStatic per mesh piece**, created with `createObject('TSStatic')` + `setField('shapeName')` +
  `registerObject` into a per-spline SimGroup, and placed with `setPosRot` (`E/meshSpline/populate.lua:144, 202, 216,
  322`) [V]. There are no merged meshes and no Forest items.
- **Algorithm** [V]:
  - Catmull-Rom spline with ≥100 divisions. Each division point is conformed by `castRayStatic` down from +10 m
    (`toolUtilities/geom.lua:2088-2137`, `util.lua:53-57`).
  - `geom.sampleSpline` gives equidistant samples at `meshLength + spacing`.
  - The component is picked round-robin or weighted-random from main plus up to three aliases, with start and end caps.
  - Orientation uses the spline normal, global up, or the **terrain normal**. Terrain normal needs
    `extensions.editor_terrainEditor` (`geom.lua:464-487`), which is editor-only.
  - Optional jitter quaternion.
- **Presets** (`E/meshSpline/splineMgr.lua:15-300`), all global art [V]: `art/shapes/objects/jerseybarrier_3m.dae`,
  `garage_and_dealership/Clutter/hr_plasticbarrier.dae`, `objects/s_metal_fence.dae`,
  `garage_and_dealership/Clutter/eca_lamppost.dae`, `objects/lamp1.dae`, `objects/bollard_yellow.dae`,
  `garage_and_dealership/Clutter/metal_drum_a.dae`.
- **Headless:** possible.
  - `require('editor/meshSpline/splineMgr')`, then `addNewMeshSpline()`, set `nodes/widths/nmls`, `setPreset`, and
    `updateDirtyMeshSplines()`.
  - Use `normalMode` 0 or 1 to avoid the terrain editor.
  - The objects are marked `cansave = true` and the module keeps global state.

  It is simpler to reuse the presets and the 30 lines of math.
- **Cost:** Jersey barrier 3 m with spacing −0.18 m gives ~355 TSStatics per km.
  - Placement math is O(n) Lua plus ~100–300 raycasts per spline.
  - Object creation and scene-graph cost dominate. [I] ~0.05–0.2 ms per TSStatic of an already-loaded shape; [P] PM1.
- **Rebase:** statics in world coordinates. `setPosRot` each, ~0.006 ms per object (project p6) [V].
- **Determinism:** `randomseed(spline.splineRandomSeed)` at populate (`populate.lua:235`) [V]. It is deterministic for a
  given seed, but it reseeds the **global** Lua RNG, a side effect on other mods.
- **Verdict:** put these presets in the server's prop library and place them as **Forest items** (fixed length, no
  stretching) along OSM `barrier=jersey_barrier`, `highway=street_lamp` rows and `barrier=bollard`.

### 2.5 Assembly Spline Tool
- **Generates:** TSStatics per kit piece, all via `createObject('TSStatic')` (`E/assemblySpline/populate.lua:93`) [V]:
  - **molecules** (rigid pieces such as posts) at `3.0 m + spacing` intervals (`populate.lua:10, 168-170`);
  - **bridges** (rails, boards, wires) spanning neighbouring molecules. A bridge is placed by aligning its two nail
    anchors to the molecules' anchors and **scaled non-uniformly**: `scale = (spanX, 1, sagZ)` (`populate.lua:405-421`).
- **Kits** (`content/assets/meshes.zip: assets/meshes/props/assembly_kit/`, global) [V]:

  | Kit (preset) | Pieces, tris per LOD | Materials | Spacing |
  |---|---|---|---|
  | `ak_guardrail_001` ("Metal Crash Barrier") | post 68/16/8; rail ×2 variants 68/22/10/4 + 8-tri Colmesh | `guardrail` (global `art/shapes/objects`) | 3 m |
  | `ak_wood_fence_001` ("Wooden Fence") | pole 92/92/12 + 12-tri Colmesh; boards ×2 variants 28 + 2-tri Colmesh | `m_wood_oak_raw_01` (global) | 3 m |
  | `ak_wood_pole_old_001` ("Telegraph Pole") | pole 240/88/16 + 34 Colmesh; sag wire 84 tris + **84-tri Colmesh** | `m_oldwood`, `m_electric_wires` (global `art/shapes/common/power_lines_procedural`), `ind_metal_trim` | 33 m (30 + 3), global up |

  Anchor names come straight from the DAE nodes (`nail.join1.head`, `nail.start.point.wire1`, …). The server can read
  them from the zip, so no game call is needed.
- **Headless:** same as Mesh Spline.
  - Kit parsing creates temporary TSStatics and calls `getAnchorNames`/`getNodeTransform`
    (`E/assemblySpline/molecule.lua:151-298`).
  - Terrain-up mode needs the editor's terrain editor.
- **Cost:**
  - Guardrail ≈ 334 posts + 333 rails ≈ **670 TSStatics per km per side**.
  - Fence ≈ 1 000 per km.
  - Power line ≈ 30 poles + 120 wires ≈ 150 per km. Wires need `collisionType='None'`, otherwise each km adds 10k
    collision tris.
  - Geometry is tiny (< 200 verts, so hardware instancing applies; perf report section 1.2). The per-object
    scene-graph, culling and draw-submit cost is what matters.
  - The official maps place guardrails as **Forest items** instead: WCUSA has guardrailpost 9 653 items at a 2.00 m
    nearest-neighbour spacing, scale exactly 1, and guardrail1/2 8 148 each, all unscaled [V measured from
    `forest/guardrail*.forest4.json`].
- **Rebase:** `setPosRot` per piece. Scale is unchanged.
- **Determinism:** `randomseed(spline.splineRandomSeed)` (`populate.lua:165`) [V]. Same caveat as Mesh Spline.
- **Verdict: reuse the kits and the anchor math, server-side.**
  - **Posts, poles and rails of fixed length go in as Forest items.** Choose the post spacing equal to the rail length,
    as WCUSA does, so no stretching is needed.
  - Only stretched or sagging pieces (wires between poles, the last partial rail of a run) need TSStatic with
    non-uniform scale, within ~500 m.
  - Or Forest, if a scaled MatrixF works there ([P] PF3).

### 2.6 Terrain Editor: material painting
- **Generates:** per-sample material indices on the TerrainBlock. Each `TerrainMaterial` carries a `groundmodelName`
  (tyre physics) and GroundCover keys.
- **Engine API, not editor** [V]:
  - TerrainBlock: `getMaterialIdxWs`, `setMaterialIdxWs`, `updateGridMaterials(min,max)`, `updateGrid(min,max)`,
    `addMaterial`, `removeMaterial`, `reorderMaterial`, `getMaterialCount`, `importMaps(height, squareSize,
    heightScale, holeMap, materials, textureMaps, flipY)`, `exportLayerMaps`, `exportHeightMap`.
  - Import errors seen in the exe: "Number of Materials and Layer maps must be equal", "Path/channel field is missing".
  - The spline painter `E/toolUtilities/terrainPainter.lua:30-118` shows the pattern: a scanline polygon, then
    `setMaterialIdxWs` per sample, then `updateGridMaterials` + `updateGrid` over the bbox. Only world→grid conversion
    uses the editor's `TerrainEditor`, and that is trivial to compute ourselves.
  - The editor's C++ `TerrainEditor():autoMaterialLayer(hMin, hMax, slopeMin, slopeMax, coverage)` is a rule-based
    auto-paint (`E/terrainEditor.lua:1597`). It is editor-only and we can do it better on the server.
- **Cost:** the project measured `setHeight` at 0.1 µs per sample and `updateGrid` at 37 ms per 1024² (1.7 ms per 128²).
  `setMaterialIdxWs` is likely similar [I]. A full 512² repaint by Lua is therefore ~26 ms plus the grid update, so use
  `importMaps` layer maps for whole commits (v1.5 plan, perf report P6). Use `setMaterialIdxWs` for small strips such as
  a road built under the car between commits.
- **Rebase:** the block is re-imported anyway, so layers come with it.
- **Determinism:** data-driven.
- **Limits:** official maps use 11–15 materials. Materials are per block, and the layer map is the block's resolution
  (2 m).
- **Verdict:** **already the plan.** Painting tools add nothing beyond `importMaps`.

### 2.7 Prefabs
- **Generates:** a `Prefab` (v1, `.prefab` TorqueScript or `.prefab.json`) or a `PrefabV2` template plus a
  `PrefabInstance`. Each one is a group of TSStatics, lights and other objects.
  - Example: `levels/italy/art/prefabs/italy_small_petrolstation.prefab` = SimGroup + 6 TSStatics with level shapes.
  - Fuel-station assets ship in WCUSA (127 matching files), Italy (69) and Utah (9) [V].
- **Runtime API** [V]: `spawnPrefab(name, file, pos, rot, scale)` and `removePrefab(name)` (`lua/ge/ge_utils.lua:749-821`).
  - v1: `createObject('Prefab')` with `loadMode=1`, then `p:load()`.
  - v2: `PrefabV2():load(file)` once per template, then `prefab:spawn(name, pos, QuatF, scale)`.
  - **Bug:** for v2 with *string* arguments, the parser uses `([0-9]*)`, which drops minus signs and decimals
    (`:765-777`). Always pass `vec3`/`QuatF`.
  - Each template load logs at level 'E' (`:711`).
  - `editor.active` triggers `Engine.setNeedCollisionRebuild(true)`. Outside the editor we call `be:reloadCollision()`
    ourselves.
- **Cost:** a file parse plus N object creations per spawn. [I] ~1–5 ms for a 6-object station; [P] PP1.
- **Rebase:** `Prefab`/`PrefabInstance` is a SceneObject. In T3D, moving the prefab moves its children; BeamNG adds
  `updateChildOffsetTransform` [I]; [P] PP1.
- **Determinism:** deterministic, given that the server picks the prefab variant by hash.
- **Verdict:** good for **rare, composite** things: fuel stations (roadmap candidate "Gas stations"), port bollards and
  cranes near OSM harbours, and later bus stops. Choose the variant from data (brand, footprint size, region style
  attribute), never from hard-coded places. Spawn within ~1 km. Remove on cell unload.

### 2.8 Audio Ribbon Editor → `core_audioRibbon`
- **Runtime module:** `lua/ge/extensions/core/audioRibbon.lua` is loaded by default (`main.lua:347`) [V].
  - **Data:** `ribbons[i] = {persistantId, name, isEnabled, isAmbient, isUpRibbon, isTopActive, isQuadAndVolume, isMuteA..D,
    speed, nodes = {vec3 left0, vec3 right0, left1, right1, ...}, depths = {...}, emitters = 5× createEmitterHost(event)}`.
  - `updateRibbonData(r)` computes `numSegs = (#nodes-4)/2+1` and the pair widths (`:437-452`).
  - `setRibbons(list)` (`:726`), `recomputeMap()`, `clearNearFarLists()`.
- **Per frame** (`:292-404`):
  - Listener pose from `SFXSystem`.
  - Near ribbons (< 500 m): up to 3 triangle closest-point tests for each of 5 emitters.
  - Far ribbons: one per frame, round-robin.
  - One `SFXEmitter` per (axis, event), created lazily, with `setVolumePitchCT(vol, pitch, colour=width,
    texture=attenuation)`.
  - [I] tens of µs per frame for ~20 ribbons.
- **Events used by the official levels** [V, 44 ribbons in 6 levels]: `event:>Ambient>Water>River`,
  `event:>Ambient>Rivers>front`, `event:>Ambient>Water>Waterfall`. All are water. No road or traffic ribbons ship.
- **Level loading:** `onClientCustomObjectSpawning` reads `levels/<lvl>/dynamicAudioEmitters/ribbonData.audioSFX.json`
  and resets the list (`:672-690`). Our level has no such file, so the list starts empty. We set ribbons after the level
  loads.
- **Rebase:** node `vec3`s are world positions. Transform them in place (`R·p + t`), then call `updateRibbonData` and
  `clearNearFarLists()`. The emitters follow on the next frame. Cheap.
  - Avoid `removeRibbon(idx)`: it calls `clearAllSFXEmitters()` and would cut every river sound. Replace the whole list
    with `setRibbons` instead.
- **Determinism:** pure geometry from data.
- **Related: `core_audioForest`** (also default-loaded).
  - `setNodeCloud(cloud)` + `setMainEvent('event:>Ambient>Wind>Wind_<biome>_01')` gives wind-in-trees sound from a
    KD-node cloud built from Forest items (`core/audioForest/audioForestCommon.lua:231`, a full prepass over all items).
  - Once we stream trees, rebuild the cloud per rebase or per few cells, or build it on the server [I]; [P] PA2.
- **Verdict: use it.** It costs little and fits roadmap "Sound design".
  - Server: OSM/Overture `waterway=river|stream|canal` centrelines with width (`width` tag, Overture water polygons, or
    a width-from-class default) become left/right bank pairs every ~10–20 m. z = the water surface (DEM at the
    shoreline). Depth comes from the water plan.
  - Waterfall points get a short ribbon with the Waterfall event.

### 2.9 Particle Editor → `ParticleEmitterNode`
- **Editor:** edits `ParticleEmitterData`/`ParticleData` datablocks and saves them to json [D][V]. Runtime use is
  `createObject('ParticleEmitterNode')` with `setField('emitter',0,<ParticleEmitterData>)`,
  `setField('dataBlock',0,'lightExampleEmitterNodeData1')`, `registerObject`, `MissionGroup:addObject`
  (`flowgraph/nodes/scene/particleEmitter.lua:33-44`) [V].
- **Global emitters** (`gameengine.zip art/datablocks/*.json`, 89 total) [V]: `BNGP_waterfallspray`,
  `BNGP_waterfallsprayshort`, `BNGP_waterfallsteam`, `BNGP_utah_dust`, `BNGP_utah_dust_huge`, `BNG_Leaves`,
  `BNG_dust_gravel`, `SmokeEmitter`, `FireEmitter`, `BNGP_sprinkler`, `BNGP_1..83`.
- **Cost:** GPU fill (soft particles) plus a small CPU update per active emitter. Keep ≤ ~20 within ~500 m [I].
- **Rebase:** `setPosition` per node. Existing particles live in world space and will be left behind as a one-frame
  pop [I].
- **Verdict:** a small "alive" win:
  - waterfalls (OSM `waterway=waterfall`);
  - desert dust devils in arid biomes, positioned by global-cell hash;
  - industrial chimney smoke (OSM `man_made=chimney`).

---

## 3. What runs headless and what needs the editor

| Need | Headless call | Needs editor mode / undo / selection? |
|---|---|---|
| Forest object | `createObject('Forest')`; `core_forest.getForestObject()` | No [V code, P runtime] |
| Item types | `createObject('TSForestItemData')` + `Sim.getDataBlockSet():addObject`, or `loadJsonMaterialsFile(managedItemData.json)` | No |
| Items | `forest:getData():createNewItem/removeItem/updateItem/getItemsCircle` | No. `editor.createForestItem` only adds dirty flags (`E/api/forest.lua:68-72`) |
| Brush and biome procs | `ForestBrushTool()` | Editor API binding [V], unknown outside the editor [P] |
| Spline populate (mesh/assembly) | `require('editor/<tool>/splineMgr')` + `updateDirty*()` | No undo needed. Terrain-normal mode needs `editor_terrainEditor` [V] |
| Terrain layers | `TerrainBlock:importMaps/setMaterialIdxWs/updateGridMaterials` | No |
| Prefab | `spawnPrefab`/`removePrefab` | No |
| Audio ribbon / audio forest | `core_audioRibbon.setRibbons`, `core_audioForest.setNodeCloud` | No |
| Particles | `createObject('ParticleEmitterNode')` | No |

---

## 4. Ranked recommendation

1. **Forest items for all vegetation, rocks and repeated linear props** (Forest Editor's engine layer).
   - Trees come from the Meta/WRI canopy height model (positions and heights). Land cover and Köppen class give the
     species set, taken from official level sets whose imposters ship.
   - Shrubs and rocks come from land cover and slope.
   - Guardrails and posts, fence posts and boards, telegraph poles, bollards, jersey barriers and lamp posts come from
     OSM ways.
   - Facade modules on close buildings.
   - This is how the official maps do it (Forest = every repeated prop) and it keeps draw calls batched.
2. **Assembly-kit geometry on the server** for linear infrastructure:
   - OSM `barrier=guard_rail` → `ak_guardrail_001`;
   - `barrier=fence` (+ `fence_type=wood`) → `ak_wood_fence_001`;
   - `power=minor_line`/`telecom=line` → `ak_wood_pole_old_001` + sag wires.

   Posts and rails become Forest items. Wires become TSStatics with non-uniform scale and `collisionType=None`, within
   ~500 m.
3. **Terrain layer maps through `importMaps`** for surfaces and groundmodels (v1.5, unchanged). Use
   `setMaterialIdxWs` strips only between commits.
4. **Audio ribbons** along rivers and streams, plus waterfalls. Feed **audio forest** from our tree cells.
5. **Prefabs** for fuel stations and harbour furniture at OSM POIs.
6. **Particle emitters** for waterfalls, dust and chimneys.
7. **Mesh-spline presets** as Forest items. Not the tool.
8. **BAT assets** (modules + `*_bat` materials) inside our own building generator. **Biome Tool: no.**

### 4.1 Integration sketch

**Server** (decides everything; deterministic):
- **Content cells.** 256 m cells on the global quadtree (v1.4 global keys), each in its own tile-local ENU frame.
  Placement is a pure function of (global position, data snapshot ids, per-layer salt, generator version), e.g.
  Poisson-disk seeded by `hash(cell_id, layer)`. Every object gets a fixed rank for LOD thinning (roadmap
  determinism principle).
- **Type table**, sent once per session as `forest_types`:
  `{id, name, shapeFile, itemDataSource: {file=<level managedItemData.json>, name} | {fields...}, materialsFiles:[...],
  collidable, lodClass}`. The server reads kit anchors and LOD sizes from the game's DAE files locally (zip read, no
  redistribution).
- **`forest_cell {key, frame:{lat,lon,h}, file}`**: binary rows `u16 type, f32 x,y,z (cell frame), i16 yaw/pitch/roll
  (0.01°), u8 scale (0.5–2.0 log), u8 rank, u32 featureHash` (≈20 B per item). Also `forest_drop {key}`.
- **`statics_cell {key, frame, rows: shape, pos, quat, scale3, collision}`** for stretched pieces (wires, partial rails)
  and **`prefab {id, file, pos, quat}`** for POIs. Both drop with the cell.
- **`ribbons {list}`** per ~2 km window (bank pairs + depth + event), and **`emitters {list}`** for particles. Positions
  are in cell frames.

**Mod** (new `forest.lua`, `props.lua`, `ambience.lua`; governor kinds `forestBatch`, `forestDrop`, `staticBatch`,
`prefab`, `collisionReload`):
- **Init.** Create one `Forest` (`bngEarthForest`, `canSave=false`). For each type: `loadJsonMaterialsFile` of its
  materials and item-data files once, or `createObject('TSForestItemData')`. Optionally pre-bake imposters
  (`Engine.Render.updateImposters`) during the loading screen.
- **Add a cell.** Compute `cell→anchor` (R, t) with `geodesy.lua`, as for far tiles. Create items in batches sized to
  ≤ 2 ms (PF1 decides N). Keep `keys[cell] = {item keys}`. Order cells by time-to-reach (v1.4 priority).
- **Drop a cell.** `removeItem` for its keys, in batches.
- **Collision.** Only near-cell trunk and guardrail types are `collidable`. `be:reloadCollision()` runs in the heavy
  slot together with the terrain commit (never per batch).
- **Rebase.** One of:
  - **(a)** `updateItem` per item with the new matrix (`T_new = R·T + t`), nearest cells first, if PF1/PF2 show
    ≤ ~5 µs per item (30k items ≈ 150 ms spread over ~75 frames). Far items being briefly wrong is acceptable because
    they are ≥ 1.5 km away and a rebase is a 15 km jump, so wrong far items land far outside view.
  - **(b)** Delete the Forest object and re-add cells nearest first. A single delete is O(1) Lua.

  Pick by PF2. Statics, prefabs and particles use `setPosRot`/`setPosition`. Ribbons are transformed in Lua.
- **Radii** (perf report budgets): trees mesh ≤ ~250 m, imposters to 1.5–3 km. Props ≤ 500 m. Prefabs ≤ 1 km.
  Particles ≤ 500 m. Ribbons < 2 km window (the module itself culls at 500 m).
- **Adaptive.** Ranks let the client thin a cell without new data: show only items with `rank < threshold`.

---

## 5. Cost estimates per unit [I unless marked]

| Content | Objects | Main-thread creation | Rebase | Notes |
|---|---|---|---|---|
| 1 km of guardrail (Forest, WCUSA style) | ~500 posts + ~250 rails | ~750 × 5–20 µs ≈ 4–15 ms | 750 `updateItem` | ~6k collision tris if rails collide |
| 1 km of guardrail (Assembly TSStatics) | ~670 TSStatics | ~670 × 0.05–0.2 ms ≈ 35–130 ms | 670 × 6 µs ≈ 4 ms [V rate] | ~670 scene objects, so avoid |
| 1 km of power line | 30 poles (Forest) + ~120 wires (TSStatic) | ~10–25 ms | trivial | wires `collisionType=None` |
| 1 km² of temperate forest (canopy-thinned) | 5–20k trees + shrubs | 25–400 ms → 12–200 governor frames | 5–20k `updateItem` | imposter bake hitch per new species |
| 1 building facade-decorated (20 windows + 2 doors) | ~22 Forest items | < 0.5 ms | 22 `updateItem` | modules only within ~300 m |
| 1 fuel-station prefab | ~6 TSStatics | 1–5 ms | 1 `setPosition` (if it moves children) | |
| 1 river ribbon (2 km) | 200 vec3 + up to 5 SFX emitters | < 0.1 ms | < 0.1 ms | per-frame ~µs |

At 134 m/s with a 1.5 km tree radius, new ground enters at ~0.4 km² per second. Forested areas then cost ~4–8k
`createNewItem` per second ≈ 20–160 ms per second (1–10 % of frame time). This is affordable only if PF1 lands at the
low end. Otherwise shrink the tree radius with speed, as v1.4 does for tiles.

---

## 6. Probes (run only when the user is not driving; camera stays on the car; nothing saved)

All are GE Lua for the MCP `execute_lua` path. Each one cleans up after itself.

**PB1: are the editor-bound classes available outside the editor?**
```lua
return jsonEncode({fbt = type(ForestBrushTool), te = type(TerrainEditor), wecpp = type(worldEditorCppApi),
  forest = core_forest.getForestObject() ~= nil, ribbon = type(core_audioRibbon), aforest = type(core_audioForest)})
```

**PF1: Forest item create, update and remove cost (1 000 items, a global shape with a global material)**
```lua
local s = require('socket'); local r = {}
local f = core_forest.getForestObject()
if not f then f = createObject('Forest'); f.canSave = false; f:registerObject('bngEarthForestProbe'); scenetree.MissionGroup:addObject(f) end
local db = scenetree.findObject('bngProbePost')
if not db then
  db = createObject('TSForestItemData')
  db:setField('shapeFile', 0, '/assets/meshes/props/assembly_kit/ak_guardrail_001/ak_root_guardrail_post_001.dae')
  db:registerObject('bngProbePost'); Sim.getDataBlockSet():addObject(db)
end
local fd = f:getData(); local veh = getPlayerVehicle(0); local p = veh:getPosition()
local items = {}; local t0 = s.gettime()
for i = 1, 1000 do
  local m = MatrixF(true); m:setFromEuler(vec3(0, 0, i * 0.1))
  local x, y = p.x + 30 + (i % 40) * 2, p.y + math.floor(i / 40) * 2
  m:setPosition(vec3(x, y, core_terrain.getTerrainHeight(vec3(x, y, 0)) or p.z))
  items[i] = fd:createNewItem(db, m, 1)
end
local t1 = s.gettime()
for i = 1, 1000 do local it = items[i]; local m = it:getTransform(); m:setPosition(vec3(it:getPosition()) + vec3(0, 0, 0.5))
  items[i] = fd:updateItem(it:getKey(), it:getPosition(), it:getData(), m, it:getScale(), it:getUid()) end
local t2 = s.gettime()
for i = 1, 1000 do fd:removeItem(items[i]) end
local t3 = s.gettime()
r.create_us = (t1 - t0) * 1e3; r.update_us = (t2 - t1) * 1e3; r.remove_us = (t3 - t2) * 1e3  -- per item, in µs
r.count_after = #fd:getItems()
return jsonEncode(r)
```
Also screenshot before the remove step, to confirm the items render without `rebuildForestManagerInstanceData`. Repeat
with 10 000 items for scaling, and with `be:reloadCollision()` timed after the create step.

**PF2: Forest transform and multiple Forests.** After PF1's create step: `f:setPosition(f:getPosition() + vec3(100,0,0))`
and check whether the items moved (screenshot, `getItemsCircle` at the old position). Then create a second Forest and
add 100 items to it: do both render, and does `core_forest.getForestObject()` still return the first?

**PF3: non-uniform scale in `createNewItem`.** Build a MatrixF with column 0 scaled ×3
(`m:setColumn(0, m:getColumn(0) * 3)`) for a rail piece. Does it render stretched, and do the bounds and collision
follow?

**PF5: imposter bake hitch.**
- Register `/assets/meshes/foliage/trees_library/oak/tree_oak_bush_a.dae`, after loading
  `levels/east_coast_usa/art/shapes/trees/main.materials.json`.
- Add 200 items at 400–800 m and log the frame-time spike plus the "Creating imposters" log line.
- Then try `Engine.Render.updateImposters(true)` at load time.

**PM1: TSStatic per-piece cost** (stock shape, already loaded)
```lua
local s = require('socket'); local p = getPlayerVehicle(0):getPosition(); local o = {}
local t0 = s.gettime()
for i = 1, 300 do local m = createObject('TSStatic'); m:setField('shapeName', 0, 'art/shapes/objects/jerseybarrier_3m.dae')
  m.canSave = false; m:registerObject(''); m:setPosRot(p.x + 30, p.y + i * 3, p.z, 0, 0, 0, 1); scenetree.MissionGroup:addObject(m); o[i] = m end
local t1 = s.gettime(); for i = 1, 300 do o[i]:delete() end
return jsonEncode({create_ms_each = (t1 - t0) * 1000 / 300, delete_ms_total = (s.gettime() - t1) * 1000})
```

**PA1: audio ribbon from data**
```lua
local p = getPlayerVehicle(0):getPosition(); local nodes, depths = {}, {}
for i = 0, 30 do local y = p.y + i * 10
  nodes[#nodes + 1] = vec3(p.x + 20, y, p.z - 1); depths[#depths + 1] = 2
  nodes[#nodes + 1] = vec3(p.x + 35, y, p.z - 1); depths[#depths + 1] = 2 end
local ev = 'event:>Ambient>Water>River'; local H = core_audioRibbon.createEmitterHost
local r = {persistantId = 'bngEarthProbe', name = 'probe', isEnabled = true, isAmbient = false, isUpRibbon = true,
  isTopActive = true, isQuadAndVolume = false, isMuteA = false, isMuteB = false, isMuteC = false, isMuteD = false,
  speed = 1, nodes = nodes, depths = depths, emitters = {H(ev), H(ev), H(ev), H(ev), H(ev)}}
core_audioRibbon.updateRibbonData(r); core_audioRibbon.setRibbons({r})
core_audioRibbon.recomputeMap(); core_audioRibbon.clearNearFarLists()
return 'ok'   -- listen near the car; afterwards: core_audioRibbon.clearAllSFXEmitters(); core_audioRibbon.setRibbons({})
```
Also time `core_audioRibbon.onUpdate` with 20 copies of the ribbon (wrap it with `socket.gettime`).

**PA2: audio forest from streamed trees.** After PF1's create step, with `audioForestCommon` required:
`local c = require('core/audioForest/audioForestCommon').buildNodeCloudFromForest(core_forest.getForestObject(), {}, nil, {})`.
Time it, then `core_audioForest.setNodeCloud(c); core_audioForest.setMainEvent('event:>Ambient>Wind>Wind_Mediterranean_01'); core_audioForest.setEnabled(true)`.

**PP1: prefab spawn and move**
```lua
local s = require('socket'); local p = getPlayerVehicle(0):getPosition(); local t0 = s.gettime()
local pf = spawnPrefab('bngProbeFuel', 'levels/italy/art/prefabs/italy_small_petrolstation.prefab', tostring(p.x + 40)..' '..tostring(p.y)..' '..tostring(p.z), '0 0 1 0', '1 1 1')
local t1 = s.gettime(); pf:setPosition(pf:getPosition() + vec3(0, 20, 0))
return jsonEncode({spawn_ms = (t1 - t0) * 1000})   -- screenshot: did the children move? then removePrefab('bngProbeFuel')
```
(v1 `.prefab`, which takes strings; position strings are fine on the v1 path.)

**PE1: waterfall particles.**
- `createObject('ParticleEmitterNode')` with `emitter = 'BNGP_waterfallspray'` and
  `dataBlock = 'lightExampleEmitterNodeData1'`, placed 30 m ahead.
- Measure `$fps::gpuTime` with and without it, then `setPosition` it by 100 m to check for left-behind particles.
- Delete it.

**PT1: terrain layer strip.** On the physics block, paint a 64 × 2 m wide strip with `setMaterialIdxWs` +
`updateGridMaterials` + `updateGrid`.
- Time it.
- Drive over it (with the user's consent) or check `groundModel` under a wheel via the vehicle's ground model debug.
  Does the groundmodel change without `reloadCollision`?

**P8: BAT materials.** `loadJsonMaterialsFile('/art/shapes/common/building_architect_modules/bat_materials/wall.mat.json')`,
then `scenetree.findObject('m_bricks_01_bat') ~= nil`.

---

## 7. Sources

Game Lua: `E/forestEditor.lua:240-300, 675-760, 1348, 1431-1450, 2495-2600, 3164-3169`; `E/biomeTool.lua:60-125,
354-380, 998-1028, 1665-1800, 1880-1950, 2560-2600, 3124-3160, 3533-3541, 3727-3750, 3884-3900`; `E/api/forest.lua:44-101`;
`util/forestGenerator.lua:23-196`; `core/forest.lua`; `E/meshSpline/{populate.lua, splineMgr.lua:1-60, 384-476,
480-525, 1006-1176}`; `E/assemblySpline/{splineMgr.lua:1-175, populate.lua:10, 52-130, 156-260, 405-421,
molecule.lua:127-300}`; `E/toolUtilities/{geom.lua:464-487, 1441-1467, 1599-1620, 2088-2137, util.lua:1-98,
terrainPainter.lua}`; `E/terrainEditor.lua:1266, 1438-1449, 1566-1597, 2809, 3387-3388`; `lua/ge/ge_utils.lua:709-821`;
`core/audioRibbon.lua`; `core/audioForest.lua`, `core/audioForest/audioForestCommon.lua:231`;
`E/particleEditor.lua:70`, `E/particleEditor2.lua:220`, `flowgraph/nodes/scene/particleEmitter.lua:33-44`;
`util/compileImposters.lua`; `util/tileBake.lua`; `lua/ge/main.lua:347, 1331`.

Exe strings (`BinLinux/BeamNG.drive.x64`, dump `scratchpad/wetools/strings_BeamNG.drive.x64.txt`): ForestData and
TerrainBlock method lists (~152190-152360); ForestBrushTool biome API and errors (~167640-167800, 168260-168330);
ForestBrushElement fields; Forest class help and `$Forest::*` (~144405-144450); imposter messages (~144775-144950).

Content: `content/levels/{italy,west_coast_usa,template,east_coast_usa,Utah,jungle_rock_island,Industrial,automation_test_track}.zip`
(forest brushes, managedItemData, biomeTool.json, `forest/guardrail*.forest4.json`, `dynamicAudioEmitters/*`, prefabs);
`content/assets/meshes.zip` (`assembly_kit/*`, `trees_library/*`); `content/art_shapes.zip`
(`building_architect_modules/*`, `power_lines_procedural/*`, material files); `gameengine.zip art/datablocks/*.json`.

Docs [D]: https://documentation.beamng.com/world_editor/tools/ and the pages `building_architect/`, `biome_tool/`,
`forest_editor/`, `mesh_spline_tool/overview/`, `mesh_spline_tool/advanced_usage/`, `assembly_spline_tool/overview/`,
`assembly_spline_tool/advanced_usage/`, `audio_ribbon_editor/overview/`, `terrain_editor/`, `prefabs/`,
`particle_editor/`; https://documentation.beamng.com/world_editor/api_reference/.

Project: `docs/ROADMAP.md` (determinism and generalisation principles, v1.5-v1.9),
`docs/research/2026-10-10-official-map-look.md`, `docs/research/2026-10-10-perf-and-architecture.md`,
`docs/research/2026-10-10-game-feature-quick-wins.md`, `probes/p6_rebase.lua`.
