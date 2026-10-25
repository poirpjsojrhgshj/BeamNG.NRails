# BeamNG runtime terrain and mesh updates: prior art and faster techniques

I couldn't do the relayed request to "pin the camera back to the car" from here. This subagent only does web research and has no connection to the running game. The orchestrator or main session has to do it.

**Search notes:** grep.app is blocked by a Vercel checkpoint, GitHub code search needs authentication, and Sourcegraph's public index found only one BeamNG hit. To make up for that, I downloaded and read the code of the main mods I found, and grepped the local game Lua (`~/.local/share/Steam/steamapps/common/BeamNG.drive/lua`) and the Torque3D upstream source. Each item is marked:
- **[V-code]**: I read the code myself.
- **[V-doc]**: official documentation.
- **[Forum]**: a user or author claim I did not check.

## 1. Who has done live/runtime terrain or mesh updates

### 1.1 BrokenBrainCells "Terrain Deformation" (Apr 2026, free, WIP beta)
- **Links:** https://www.beamng.com/threads/free-terrain-deformation-by-brokenbraincells-uploading-to-the-repo-now.109243/ and page-2. Code is the attachment `attachments/bbcdynamicterrain-zip.1295279/`. No license is stated; the author only says it is "free and will always be free".
- **What it does:** tire ruts, bucket dig/dump for the WL40 loader, deformation when the vehicle body touches the ground, and a dozer push mode.
- **Technique [V-code]:**
  - It edits the map's existing TerrainBlock with `tb:getHeightGrid/setHeightGrid(gx,gy,h)` and then calls `tb:updateGrid(min,max)` on the dirty bounding box only.
  - Edits are throttled: `deformInterval = 0.1` s and `contactNodeDeformInterval = 0.15` s.
  - **There is no `be:reloadCollision()` call anywhere in the mod.** Its "Update Grid" button just calls `updateGrid` over the whole block.
  - Ground contact comes from the vehicle VM: `obj:castRayStatic` plus node positions are sent to GE Lua with `queueGameEngineLua` and `lpack`.
- **Performance and problems [Forum]:**
  - The author claims "0 lag" in dig/dump modes.
  - The author also says "collisions don't update immediately; wait about a second after deformation stops" and "the terrainblock in game also just will lag when updating due to how the game works but its very little now".
  - Users still report "super laggy" and "lags pretty bad". The author blames massive maps ("more terrain points").
  - Grass flickers while editing.
  - It doesn't work on asphalt or stone, and is useless on Lands of Sand because of its 64 m squareSize.
- **Why this matters:** it contradicts our ARCHITECTURE.md line "Physics sees edits only after `be:reloadCollision()`". Our p7 probe raycast right after `updateGrid`. The mod suggests physics picks up terrain changes **asynchronously or deferred (about 1 s)** without a global kd-tree rebuild. This is **unverified**, but it is the most important lead in this report.

### 1.2 zip_kiev, "BeamNG VFX & World Overhaul" WIP (Sept 2026) [Forum]
- **Link:** https://beamng.com/posts/1966823/
- He criticises another, unnamed mod that "simply scripts the standard F11 editor brush to deform geometry in real time" as "far too performance-heavy", and says "Editor brushes are built for one-time level design, not runtime operations".
- He says the grass flicker also happens in the editor.
- His own approach is visual only: POM (parallax) mud on top of "BeamNG's existing terrain physics underneath". Visual ground and physical ground don't have to be at the same height.
- **Takeaway:** a visual-only fake avoids the collision problem completely.

### 1.3 RLS Career Overhaul, `dynamicRoutes.lua`
- **Link:** https://github.com/RLS-Modding/rls_career_overhaul/blob/main/lua/ge/extensions/dynamicRoutes.lua (256 stars; the GitHub API reports no license).
- **Technique [V-code]:**
  - Road groups (DecalRoad and TSStatic) are pre-placed in the level and switched with `setHidden`.
  - It changes DecalRoad `drivability`, then calls `map.reset()` + `be:reloadCollision()`.
  - It runs at most every `timerSeconds = 1800`, and a swap is refused if a TSStatic is within `PROXIMITY_BLOCK_DISTANCE = 50` m of the player.
- **Takeaway:** a working mod treats the global collision rebuild as rare and expensive, and never does it near the player. Hidden objects drop out on the next rebuild.

### 1.4 tmaster1000/RainMod (GPL-3.0)
- **Link:** https://github.com/tmaster1000/RainMod (`lua/ge/extensions/RainTerrain.lua`)
- **[V-code]:** it changes surface physics live with `be:setGroundModel(name, data)`, including aliases, and needs no collision rebuild.
- **Takeaway:** friction and wetness per material can be streamed for free.

### 1.5 BeamNG's own shipped runtime-geometry code [V-code, local install 0.39.4]
- **trackBuilder** (`util/trackBuilder/splineTrack.lua`): one ProceduralMesh per segment.
  - Collision is only reloaded on a full rebuild. Comment at lines 978-979: "only refresh collision if the whole track would be updated… reload collision takes a lot of time on bigger maps".
  - It has an `ignoreCollision` mode.
- **`core/dynamicProps.lua`:** swaps forest items for physics props near the player and calls **`be:reloadCollision(false, true)`** and **`be:reloadCollision(false, false)`**. The two boolean arguments are undocumented; nothing else in the Lua passes arguments.
- **Collision dirty flag:**
  - `Engine.getNeedCollisionRebuild()` and `Engine.clearNeedCollisionRebuild()` are used by `editor/mainMenu.lua` (Ctrl+F7, "Rebuild Static Collision Data").
  - `setNeedCollisionRebuild` and `reloadStaticCollision` exist as strings in the binary.
- **Editor terrain tools** (terrainPainter, terraform, riverbed, roadArchitect terraform, tunnelMesh): they all call `setHeight`/`setMaterialIdxWs` followed by `updateGrid`/`updateGridMaterials` on a bounding box. **None of them call `reloadCollision` after terrain edits.** Collision reloads appear only after mesh, road or prefab changes. This supports the idea that terrain collision follows `updateGrid` by itself.
- **`util/procTrack.lua`** (gymkhana generator): spawns TSStatics at runtime with `prebuildCollisionData = "0"` and `collisionType = "Collision Mesh"`.
- **BeamNGpy** (https://github.com/BeamNG/BeamNGpy, MIT):
  - `scenario/procedural.py` sends `CreateCylinder`, `CreateBump`, `CreateCone`, `CreateCube` and `CreateRing`. These go to techCore, which uses `ProceduralMesh` + `createMesh`.
  - `tools/terrain_import.py` has `ImportHeightmap`, `TerrainAndRoadImport`, `PeaksAndRoadImport` and `ResetTerrain`. These replace the whole terrain; there is no incremental API.

### 1.6 Forum history on ProceduralMesh
- **Link:** https://beamng.com/posts/962342/ (2018).
- BeamNG staff member TStabbert described the format: verts `{x,y,z}`, uvs `{u,v}`, normals, and faces as v/n/uv triplets; materials and LODs are optional. He said trackBuilder "uses procedural meshes heavily".
- Nothing about size limits.

## 2. Specific questions

**(a) Incremental or per-object collision update.** No public API found. The static mesh path is only `be:reloadCollision([bool,bool])` / `reloadStaticCollision`, which rebuilds everything.
- Candidates to benchmark:
  1. `reloadCollision(false,true)` versus `(false,false)` versus no arguments.
  2. `Engine.setNeedCollisionRebuild()`, to see whether the engine then rebuilds lazily or on a worker thread.
  3. **TerrainBlock + `updateGrid` with no reload.** The deformation mod relies on this, and the editor's terrain tools behave the same way.
- TSStatic docs [V-doc] (https://documentation.beamng.com/modding/levels/level_classes/tsstatic/): "If the referenced shape file changes, the object can recreate its shape and refresh collision/material data". It is not clear whether that is per object or global. `prebuildCollisionData` "prebuilds collision data at load time".

**(b) ProceduralMesh vertex/index limits.** No BeamNG report found. BeamNG staff say render meshes have no known hard triangle cap; cars are about 30-40k tris (https://www.beamng.com/threads/how-do-i-make-a-high-poly-car-mod.67584/).
- Upstream Torque3D was built around 16-bit indices [V-code, TorqueGameEngines/Torque3D development branch]:
  - `gfxPrimitiveBuffer.h`: `MaxIndexCount = 65535`.
  - `colladaAppMesh.cpp` splits primitives: "too many verts for 16-bit indices".
  - `tsMesh.cpp` stores primitive start/numElements as S16 and warns at ≥0x10000 indices: "split this mesh into pieces of no more than 65k unique verts".
- **Hypothesis, not verified:** our hang at about 32k tris lines up with 2^15 = 32768 (a signed 16-bit count) or with corner count > 65535. To pin it down, test 32767 versus 32768 tris and 21845 versus 21846 tris (65535 versus 65538 corners).
- Until then, keep each ProceduralMesh well under 21k tris / 65k corners, or split it into several submeshes or objects.

**(c) How deformable-terrain mods update collision live.** `setHeightGrid` + `updateGrid(dirty box)` only, about every 0.1 s, with physics reportedly catching up about 1 s later. The author's claim is [Forum]; the code is [V-code]. No mod uses `reloadCollision` for terrain. The alternative is visual-only POM (zip_kiev).

**(d) BeamNG developer statements on large or streamed worlds.**
- tdev (BeamNG Team), Oct 2024: float precision is "a long-standing issue we want to address", "a lot of work to fix all up without making the game engine twice as slow", "we just stabilized the camera as a starting point" (https://www.beamng.com/posts/1767831).
- TerrainBlock docs: "Most normal outdoor levels have one main terrain object" [V-doc] (https://documentation.beamng.com/modding/levels/level_classes/terrainblock/).
- No developer statement on runtime terrain or mesh streaming was found.

**(e) Multiple TerrainBlocks with physics.** No authoritative source either way.
- `core/terrain.lua`, `map.lua` and `heatmap.lua` only use `findClassObjects('TerrainBlock')[1]`, so Lua helpers assume a single block [V-code].
- The editor's `terrainEditor.lua` does track several blocks through `terrainBlockProxies`.
- The binary has a collision `addTerrainBlock` symbol, which hints that physics accepts more than one block.
- Grille's LevelTemplateCreator added an "experimental terrain merger tool… resize or combine multiple terrain blocks" (https://www.beamng.com/threads/beamng_leveltemplatecreator-pbr-v0-4.98334). That suggests people merge blocks rather than ship several.
- **Needs an in-game probe:** two blocks, a car driven across the seam, and `castRayStatic` on both.

## 3. Infinite, procedural, streamed or large-world attempts (nothing truly runtime found)
- **No BeamNG mod streams or generates terrain or roads while you drive.** "Endless Highways" (ModPackIndex/CurseForge) is a **Minecraft** mod.
- **Fixed or illusion maps:**
  - Ocean Road loops with World Editor tricks (https://www.modland.net/beamng.drive-mods/maps/ocean-road-3.html).
  - "Endless Highway" is just long (https://www.modland.net/beamng.drive-mods/maps/endless-highway.html).
  - Random Desert Highway is a fixed 4096² map (https://beamng.com/posts/1962388/).
- **"The World" by Willfa** (https://beamng.com/goto/post?id=1969254): shrank from 1000×1000 km to 125×125 km because terrain was "not very manageable", loading needed 66 GB+ RAM, and float precision was a problem. A commenter notes 16-bit heights give about 3 cm steps over 2000 m.
- **Offline bakers only:**
  - MapNG (https://mapng.com).
  - BeamNG Mapping Tools, a standalone .NET app (https://www.beamng.com/threads/beamng-mapping-tools-updated-2026-08-01.89058/). A user reports terrain-material editing "will crash the game" on big maps [Forum].
  - nikkiluzader/BeamNGTerrainGenerator (MIT).
  - bobberdolle1/ivanovo2beam: 4096² at 1.25 m; "sector streaming" is listed as Not started; in-game loading is untested.
  - bobberdolle1/BeamNG.WorldForge (max 400 km²).
- **ProceduralMesh mods with collision on GitHub/Sourcegraph:** none found outside BeamNG's own code.

## Implications for BeamNG.Earth
1. **Re-run p7 with delays.** After `setHeight` + `updateGrid` with no reload, sample at 0, 0.1, 0.5, 1 and 2 s using both GE `castRayStatic` and vehicle-side `obj:castRayStatic`, and drop a car on the edit. If physics follows `updateGrid` on its own, TerrainBlock becomes the incremental-collision path for near ground:
   - about 1.7 ms per 128² `updateGrid` versus a 7-10 ms+ global `reloadCollision`;
   - ring-buffer heights inside a fixed block and recenter it when the floating origin rebases.
2. **Benchmark the reload variants.** Time `be:reloadCollision(false,true)` and `(false,false)` against no arguments, with and without a 2048² terrain present. Also test whether `Engine.setNeedCollisionRebuild()` defers the work. If a variant skips terrain, the per-1k-tri cost (0.31 ms) may hold even on large maps.
3. **Treat a global rebuild as rare and away from the player.** Batch ProceduralMesh/TSStatic collision tiles, rebuild only when a ring boundary is crossed, and don't swap collision within about 50 m of the car, as RLS does. Use render-only LODs (no collision) for everything far away.
4. **Cap each ProceduralMesh** below about 21k tris or 65k corners until the 32k threshold is bisected. Split big tiles into several objects or submeshes (Torque3D's 16-bit index heritage).
5. **Use `be:setGroundModel`** for live per-material friction (rain or surface type) at zero collision cost.
6. **Multiple TerrainBlocks are unproven.** Probe before designing around them. The Lua helpers (`core_terrain`, `map.lua`) only see the first block, so the mod would have to answer height queries itself.
7. **There is no prior art for real runtime streaming in BeamNG.** BeamNG.Earth would be first. The closest working references are BrokenBrainCells (terrain edits) and BeamNG's trackBuilder and `planet.lua` (ProceduralMesh plus a reload).

Local copies of the downloaded code are in `/tmp/claude-1000/-home-tecnagamer-Documents-BeamNG-Earth/b02246e0-198a-4d55-8cba-7ac6107ad43e/scratchpad/`:
- `bbc/x/lua/ge/extensions/bbcTerrainEditorv4.lua` and `bbcDigDump.lua`
- `rls/dynamicRoutes.lua`
- `rain/RainTerrain.lua`
- `t3d/`
- `bngpy/`

The local stale claim is at line 73 of `./docs/ARCHITECTURE.md`.
