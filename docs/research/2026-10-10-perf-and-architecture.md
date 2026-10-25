# Performance budget and architecture for roads, buildings and trees (2026-10-10)

Scope: (1) where the per-frame cost of ~900 textured far tiles comes from and what reduces it,
(2) a cheaper terrain-follow commit, (3) a faster post-rebase reload, (4) an architecture and
per-layer budgets for roads, buildings, trees, ground cover and land-cover ground models that holds
>= 60 FPS at 3840x2160. No in-game measurements were taken for this report (the user was driving); every
in-game claim below is either from the project docs or marked as a probe to run later.

Markers: **[V]** verified (file:line in the game install / Torque3D source, or a project measurement),
**[M]** measured offline by me for this report, **[I]** inference, **[P]** needs an in-game probe.

Paths: `GAME` = `~/.local/share/Steam/steamapps/common/BeamNG.drive`, `USER` =
`~/.local/share/BeamNG/BeamNG.drive/current`, `T3D` = Torque3D `development` branch
(`https://github.com/TorqueGameEngines/Torque3D/blob/development/Engine/source/...`; BeamNG's engine is a
heavily modified fork, so T3D lines show the design, not necessarily BeamNG's exact behaviour).
Scratch copies: `scratchpad/research/perf/` (exe strings dump, T3D sources, extracted official-level JSON).

---

## 0. Summary

| # | Finding | Action | Expected effect |
|---|---|---|---|
| 1 | **The user's settings have `lastSplitCastersEnabled: true`** (`USER/settings/settings.json:71`); every BeamNG preset sets it `false` (`GAME/lua/ge/extensions/core/settings/settingsPresets.json:10,42,73,105,137`). The engine's own help text: "whether distant objects (buildings, trees, etc) cast shadows in the far shadow layer. off = only terrain casts far shadows (cheaper...)" (exe strings). With it on, every tile in the last cascade is drawn again into the shadow map. Shadow range is fitted live to what is visible (SDSM: "live fit of the shadow range to what is currently visible"), so an open desert (km of visible ground) puts far more tiles into the cascades than a canyon. [V] setting, [I] that this explains most of 70 vs 92 FPS | Measure A/B (section 1.5). In the mod: per-tile `Material.castShadows = 0` for levels >= 2 (satmat.lua). Satellite imagery already contains real shadows, so far tiles lose nothing. | [I] 1–4 ms/frame in open terrain |
| 2 | ~900 objects = ~900 unique Materials + ~900 textures + ~900 draw calls per pass; ~2.1 M triangles per pass (2 304 tris/tile). TSStatic has **no** shadow, fade or distance field (field list in 1.2); hardware instancing only applies to primitives below 200 vertices (`T3D ts/tsMesh.cpp:89,258`; `USER/settings/game-settings.json:7`). | **Bigger far tiles**: 64x64 cells + 512² texture for L>=1 (same vertex density, so the selection picks one level coarser). [M] 793 -> ~400 objects at one pose. | Halves draw calls, materials, texture uploads and imports |
| 3 | Terrain-follow commit = `importMaps` of a 1024² heightmap (~43 ms) + `reloadCollision` (1.6 ms). The data fit a fixed ~11 ms + ~27 ns/sample [I, from ARCHITECTURE.md P7: 1024² ~38–43 ms, 2048² 115–138 ms]. | 512² block (1 022 m collidable), 128 m step, 300 m margin: [I] ~18 ms per commit, or probe the fixed part (layer-map PNG, material setup). Do **not** move ground collision to mesh tiles (kd-tree cost, section 2). | 60–70 ms frame -> ~30 ms frame |
| 4 | After a rebase the server re-keys every tile because the quadtree lives in the anchor's ENU plane; the mod already moves the old tiles exactly (`farfield.lua:653-676`). The client imports ~10 tiles/s (governor 2 ms/frame vs ~4.5–5 ms per textured tile). [M] server builds near tiles in ~10 ms. | **Far levels on a global (cube-sphere / geodetic) quadtree with tile-local frames** (the original ARCHITECTURE.md plan): a rebase only re-positions them. Only the lattice-bound near levels are rebuilt. Same keys across sessions = disk cache. | Rebase reload ~880 tiles (~95 s) -> ~230 (~20–25 s); 0 for far tiles |
| 5 | Official maps: 2.2k–22k TSStatics but only 190–1 037 distinct shapes (shared materials), 3k–13k DecalRoads, 133k–663k Forest items, 8–27 GroundCover objects, visibleDistance 5–25 km (section 4.1). | Use the engine's batched systems: **Forest** (imposter batches per cell) for trees, **GroundCover** (keyed on terrain material layers) for grass/shrubs, terrain **layer maps** for ground models, merged per-chunk TSStatics with **shared** materials for roads/buildings. | See budgets, section 4.4 |
| 6 | No GPU/CPU split is logged today. | Log `$fps::cpuTime`, `$fps::gpuTime`, `$GFXDeviceStatistics::drawCalls/polyCount`, `$ShadowStats::drawCalls/polyCount`, `$Forest::*`, `$GroundCover::*` in perfmon (names from `GAME/lua/ge/extensions/core/metrics.lua:32,235-257`). | Every budget below becomes checkable |

---

## 1. Per-frame cost of ~900 textured TSStatic tiles

### 1.1 What is in the scene (facts)

| Quantity | Value | Source |
|---|---|---|
| Tiles selected at one pose, mesh mode | **793**: L-2 36, L-1 47, L0 146, L1 120, L2 88, L3–L5 96 each, L6 64, L7 4. By distance: <1 km 135, 1–5 km 262, 5–20 km 192, >20 km 204 | [M] `farfield.select()` run offline (`scratchpad/research/perf/count_tiles.py`); in-game ~850–900 incl. hysteresis/old tiles |
| Per tile | 33² grid + 132 skirt vertices = **1 221 verts**, 2 048 + 256 = **2 304 tris** | `server/farfield.py:335-470` (CELLS=32, `_skirt`) |
| Per tile files | `.cdae` **96.6 KB**, `.dds` (256², DXT1, full mips) **43.8 KB** | [M] mean of 3 159 tiles in `USER/temp/beamngEarth/20261010-060208-51ec/` |
| Totals for 900 tiles | ~2.07 M tris and ~1.1 M verts per pass; ~87 MB shape data, ~39 MB textures | [I] arithmetic |
| Materials / textures | one Material + one texture per tile (`satmat.lua`, `farfield.lua:175-197`) | [V] |
| Measured | v1.2 (≈770 untextured tiles, one shared material) ~94 FPS (10.6 ms); v1.3 textured: 92 FPS canyon, **69–71 FPS open desert standing still** (14.3 ms) | task brief, ARCHITECTURE.md v1.2/v1.3 tables |
| Conflicting measurement | "rendering the 850 textured tiles costs only ~0.6 ms (hidden-tiles test)" | `docs/ARCHITECTURE.md:209` – a different spot/camera; see 1.5 |

### 1.2 TSStatic fields available (BeamNG 0.39.4)

From the exe strings (`GAME/BinLinux/BeamNG.drive.x64`, dump in `scratchpad/research/perf/exe_strings.txt`
lines ~421260–421335) and stock level JSON [V]:

`shapeName, playAmbient, meshCulling, originSort, useInstanceRenderData, instanceColor, instanceColor1,
instanceColor2, collisionType ('Collision Mesh' | 'Visible Mesh' | 'Visible Mesh Final' | 'None' | 'Bounds'),
decalType (same enum), prebuildCollisionData, renderNormals, forceDetail, prepCollision`, plus SceneObject
`isRenderEnabled`, `hidden`, BeamNG `nightEmissive` (`GAME/lua/ge/extensions/editor/inspector.lua:383`).
Methods: `getTargetCount/getTargetName/getModelFile/getWorldCollisionBBox/changeMaterial`.

- **No `castShadows`, no alpha fade, no per-object visible distance on TSStatic** ("alphaFade" does not occur
  in the exe; T3D has `alphaFadeEnable` at `T3D/tsStatic.cpp:260-263`, BeamNG removed it). [V]
- Shadow casting is a **Material** field: `castShadows` (`GAME/lua/ge/extensions/editor/materialEditor.lua:2395`;
  T3D `materials/materialDefinition.cpp:443`). The shadow bin drops a mesh whose material does not cast
  (`T3D lighting/shadowMap/shadowMapPass.cpp:263`), **after** the object was culled and prepared for that split,
  so CPU culling cost per split remains; the GPU draw goes away. [V T3D, I for BeamNG]
- `meshCulling`: per-submesh culling, "only for large complex shapes like buildings" (`T3D tsStatic.cpp:234-236`).
- `changeMaterial(mapTo, oldMat, newMat)` exists (exe `fnTSStatic_changeMaterial`) – usable for `far_retex`.
- `useInstanceRenderData` + `instanceColor` + material `instanceDiffuse` = per-object tint on a **shared**
  material (`materialEditor.lua:2218`; used by 20 557 of 22 067 WCUSA TSStatics). Good for buildings
  (facade tint variation without new materials).
- `'Visible Mesh Final'`: the engine warns "Performance: Mesh is using visible collision ... please switch the
  mesh to 'Visible Mesh Final'" (exe string) – the fast mode for visible-mesh collision.
- Shape limits: "split this mesh into pieces of no more than 65k unique verts" (exe string) – merged chunks must
  stay < 65 536 verts per mesh. Shape `smallestVisibleSize`/`smallestVisibleDL` (cdae header, `server/cdae.py:14-16`)
  give **engine-side screen-size culling** with no Lua work – the only distance cull a TSStatic has.

### 1.3 Where the cost goes (ranked hypotheses)

| Rank | Cost | Why | Status |
|---|---|---|---|
| 1 | **Shadow passes** re-draw tiles | PSSM renders the scene once per split (`T3D pssmLightShadowMap.cpp:267-379`); T3D restricts the last split to terrain when `lastSplitTerrainOnly` (`:375`). BeamNG's equivalent toggle `PSSMLightShadowMap.lastSplitCastersEnabled` (`GAME/lua/ge/extensions/core/settings/graphic.lua:1494-1503`) is **on** for this user (non-default). Shadow range is fitted to the visible depth (SDSM; `cameraUpdate.lua:186-192` sets `sdsmMaxDistanceScale = 0.5` when driving). Open desert: depth to the horizon is km -> all near/mid tiles fall in the cascades; canyon walls cut that. Also `$pref::Shadows::textureScalar = 2` (4k atlas, `USER/settings/game-settings.json:57`). | [I], probe P1 |
| 2 | **Unique material per draw** | Shared shader (same features), but per-draw material constants + texture descriptor binds; RenderMeshMgr cannot merge anything across tiles. v1.2 (one material) was ~3.5 ms faster with a similar tile count. | [I], probe P1 (e)/(f) |
| 3 | Draw calls in general | ~900 main + depth/prepass + up to ~900 shadow; no instancing (unique meshes, and >200 verts). | [V] counts, [I] cost |
| 4 | Vehicle dynamic reflection | 2 cube faces per frame, objects within 300 m, detail 0.75 (`USER/settings/settings.json:30-34`): ~80–150 near tiles per face. | [I] small today; grows with buildings/trees |
| 5 | Lua UI | `buildView()` runs `farfield.stats()` every frame (`core.lua:561-563`, `farfield.lua:952-967`): a `pairs()` over all live tiles + imgui window each frame. | [V] code, [I] ~0.05–0.3 ms |
| – | Vertex/fill cost | 2 M tris is trivial for a 4K-class GPU; ground pixels are on screen whatever the tile count. | [I] not the issue |
| – | Occlusion | No occlusion culling of meshes: T3D terrain occlusion defaults off (`T3D scene/culling/sceneCullingState.cpp:39`), BeamNG exposes `SceneCullingState.disableTerrainOcclusion` (exe). Our ground is meshes, so hills never cull tiles/buildings behind them. | [V]/[I] |

### 1.4 What reduces it (ordered by value/effort)

1. **Stop far tiles casting shadows.** In `satmat.create`, add `castShadows = 0` when the tile level >= 2
   (server `far_tile.level` is already sent; one shared rule). L-2..L1 (< ~1.5 km, ~350 tiles) keep relief
   shadows near the car; beyond, the imagery's baked shadows do the job. Optionally (with the user's consent)
   set `PSSMLightShadowMap.lastSplitCastersEnabled = false` while the Earth level is loaded and restore it on
   unload – it is a user preference, so better: tell the user, or expose it in the mod UI.
2. **Throttle the UI stats** to 4 Hz and only while the window is open (keep `nLive` incrementally).
3. **Bigger tiles for L>=1**: CELLS=64 (8 192 tris + 512 skirt, 4 225 + 260 verts, ~330 KB .cdae) and a 512²
   texture (175 KB DDS) for L>=1; keep 32x32/256² for L-2..L0 (they change often and are cheap units).
   [M] Emulating "same density, one level coarser" (K halved) gives 372 objects instead of 793; with only L>=1
   changed, ~400. Import units grow to ~6–8 ms [I], but L>=1 tiles change rarely (every 0.5–130 km); the
   governor already lets a unit above `b` run after tokens accumulate (`governor.lua:157-165`).
   The `assert len(built.tris) <= 8192` in `server/farfield.py:500` must become ~9 000 (it is a ProceduralMesh
   rule; .cdae shapes have no such cliff, ARCHITECTURE.md P5: 131k-tri .dae loads fine).
4. **Atlas instead of per-tile materials** (only if 1–3 are not enough): one Material per 4x4 siblings
   (1024² page = 16 x 256² with gutters), UVs offset by the server. Cuts materials and texture creations 16x,
   but pages must be re-versioned whenever one member changes LOD – more bookkeeping than (3) for similar gain.
5. **Horizon tiles (L>=5, >20 km, ~200 objects)**: no shadows, could be merged 4->1 (they are 8–32 km wide;
   the crossovers there are invisible anyway). Second-order once (1)+(3) are in.
6. Not worth it: imposters for ground (they are for objects), fewer vertices per tile (vertex cost is not the
   bottleneck), texture compression changes (39 MB total).

### 1.5 Probe P1 – decide with numbers (lead, when the user is not driving)

At the 70-FPS desert spot, camera fixed, nothing streaming, log for 10 s each (perfmon extended with the
console variables of `core/metrics.lua:32,235-257`: `$fps::cpuTime`, `$fps::gpuTime`,
`$GFXDeviceStatistics::drawCalls`, `polyCount`, `$ShadowStats::drawCalls`, `polyCount`):
(a) as is; (b) `PSSMLightShadowMap.lastSplitCastersEnabled = false`; (c) all tile materials `castShadows = 0`;
(d) hide levels >= 3; (e) hide all tiles; (f) all tiles pointed at one shared material (`changeMaterial`);
(g) shadows off (`$pref::Shadows::disable`). Then the same at the 92-FPS canyon spot, and **in WCUSA, Johnson
Valley and Italy** at 4K with the same settings: their drawCalls/polyCount/gpuTime are the "official look"
reference budget. If gpuTime < cpuTime the frame is CPU/render-thread bound (draw calls, materials);
otherwise GPU bound (shadow fill, post FX).

---

## 2. Cheaper terrain-follow commit

Facts [V, ARCHITECTURE.md + V1_1/V1_2 results]: block 1024² samples at 2 m (2 046 m collidable), re-centred on
a 256 m grid; commit = `importMaps` ~43 ms (uncompressed PNG) + `reloadCollision` 1.6 ms + far-tile cover
work; worst frame 59–70 ms. `setHeight` 0.1 µs/sample, `updateGrid` 37 ms per 1024² (1.7 ms per 128²);
physics picks up `setHeight` edits by itself within <= 0.5 s without `reloadCollision`. Only one TerrainBlock
collides. TSStatic visible-mesh collision costs ~0.15 ms per 1k tris on every global rebuild; terrain does not
enter the triangle kd-tree (2048² = 7 ms).

| Option | Cost per commit | Commits per km | Verdict |
|---|---|---|---|
| Today: 1024², 256 m step | ~45 ms (frame 60–70) | 4 | baseline |
| **512² (1 022 m), 128 m step, 300 m edge margin** | [I] ~18 ms (fit: ~11 ms fixed + 27 ns/sample) | 8 | **recommended first**; spikes small enough to hide under a 14 ms base frame (~30 ms frame). Margin 300 m = 7.5 s at 40 m/s; server builds a 512² heightmap in <0.1 s. Caveat: AI traffic > ~500 m from the player has no ground – keep traffic spawn radius < 400 m. |
| 256², 64 m step | [I] ~13 ms (fixed part dominates) | 16 | too little margin (256 m half-size) |
| Shrink the fixed part | ? | – | [P2] time `importMaps` with and without the layer map/material table (the all-white 1024² layer PNG is decoded every import, `terrain.lua:89-103`); try a `.dds`/raw heightmap if GBitmap accepts it. If the fixed ~11 ms is mostly layer map, 512² drops to ~8–10 ms. |
| Skip `reloadCollision` after the import | -1.6 ms today; **much more later** | – | [P3] p8 showed heights are picked up without it; check whether a moved/re-imported block is too. This matters once buildings/bridges add kd-tree tris: every commit's reload rebuilds **all** static collision (e.g. 50k building tris = +7.5 ms per commit). |
| Mesh collision (L-2 tiles `collisionType='Visible Mesh Final'`) instead of terrain | ±300 m ring = 180k tris -> ~27 ms per rebuild, every 64 m | 16 | **No**: same ms/km as today, grows with every other collidable object, and polysoup is one-sided. |
| Big fixed block + streamed patches | 128² patch = setHeight 1.6 ms + updateGrid 1.7 ms ≈ 3.3 ms, sliceable into governor units, no commit at all | 0 | Experimental. A 4096² block (8 km, ~470 ms import [I]) must still be re-imported at each rebase, and rotation between anchors makes stale far heights wrong by ~1–2 m. Only interesting together with section 3's region frames; park it. |

Recommendation: 512² + 128 m step, then P2/P3. Keep the governor's isolated heavy slot.

---

## 3. Faster rebase reload

### 3.1 Where the 95 s goes

- Client: a textured tile costs cdaeTex 3.6–4.7 ms + material 0.3 ms to bring in and delete ~0.3 ms + matDelete
  to retire (governor priors `governor.lua:49`, ARCHITECTURE.md v1.3). At `b = 2 ms/frame` and ~60 FPS that is
  ~120 ms of budget per second -> ~24 tiles/s at best, ~10 tiles/s observed with crossovers, deletes and heavy
  slots. 880 tiles -> 40–95 s. [V/I]
- Server [M] (`scratchpad/research/perf/time_tile.py`, warm caches, single thread): L-2 geometry 2 ms + imagery
  3 ms + DDS 2 ms + cdae 2 ms ≈ 9 ms; L0 ≈ 12 ms; L2 ≈ 300 ms and L4 ≈ 85 ms (imagery mosaic dominates;
  first tile 400 ms). With 3 workers the server keeps up for near tiles; far tiles are server-bound only on
  cold imagery. **The client import rate is the bottleneck.**

### 3.2 Reuse tiles across rebases: global far quadtree with tile-local frames

The mod already maps every live tile exactly into the new frame (`farfield.lua:653-676`, `setPosRot`,
~0.006 ms per object, p6). They are thrown away only because the server's keys `L_i_j` are defined on the
anchor's ENU plane (`server/farfield.py:4-6`). Proposal (it is ARCHITECTURE.md's original "cube-sphere
quadtree, S2-style" tile index):

- Levels >= L1 (or >= L2) are keyed on a **global** quadtree (cube-sphere face/level/i/j, or geodetic
  lat/lon quads below |lat| 80°). Each tile's geometry is written in **its own ENU frame** at its centre
  (float32 positions relative to that origin – <= 2 mm precision at 32 km). The message carries the tile
  centre (lat, lon, h); the mod computes `tile -> anchor` (rotation + translation, doubles, as
  `geodesy.lua` already does for anchors) and places it with `setPosRot`. On a rebase the same rule
  re-places it – nothing is re-streamed.
- Keys and texture footprints no longer depend on the anchor: **identical across rebases and sessions**, so
  the server can keep a disk cache (`~/.cache/beamng-earth/tiles/<source-version>/<key>.{cdae,dds}`, ~140 KB
  per tile at today's sizes; 10k tiles = 1.4 GB) and hard-link/copy into the session folder. Teleporting back
  to a visited place then costs only client imports.
- Levels L-2..L0 stay in the anchor frame: L-2 must equal the 2 m physics lattice and its Torque diagonal
  pattern (`server/farfield.py:108-128`). That is ~230 tiles, rebuilt nearest-first after a rebase.
- **Seam between the two sets.** The anchor-aligned inner square and the global tiles are rotated against each
  other by the meridian convergence (Δlon·sin lat) plus d/R: e.g. 10 km east of a tile-frame origin at 36° N
  ≈ 0.05° -> ~1.3 m mismatch along a 1.5 km boundary. Make the outer set **overlap** the inner square
  (select global tiles that are not fully inside it) and give the inner set's outermost ring a downward
  apron/skirt (the v1.1 apron idea) so overlaps never z-fight and gaps never open. At ~1.5–4 km a 1 m vertical
  offset is about one pixel at 4K.
- Effect [I]: post-rebase work drops from ~880 to ~230 tiles (~20–25 s at the observed rate, nearest first so
  the ground under the car is replaced within a few seconds), and to 0 for everything beyond ~1.5 km.

### 3.3 Cheaper per-tile imports (helps every path)

- Bigger L>=1 tiles (1.4 item 3): half the imports.
- Governor: raise `b` to 3–4 ms while `base` has headroom below 16.7 ms (the 2 ms default is sized for a 10 ms
  base; at a 14 ms base and a 60 FPS goal, 2.5 ms is free).
- Atlas (1.4 item 4) removes the texture load from most imports (cdae 1.9 ms vs cdaeTex ~4 ms).
- `.cdae` size: tangents are 16 of ~56 bytes/vertex (`server/cdae.py` doc); try dropping them [P] – the
  material has no normal map. Import time scales with bytes (P5: 2k tris 3.4 ms, 131k-tri DAE 415 ms).

---

## 4. Architecture for content layers

### 4.1 What official maps contain (reference)

[M] counted from the level zips (`scratchpad/research/perf/count_level.py`, `main/**/items.level.json`,
`forest/*.forest4.json`):

| Map | TSStatic | distinct shapes | DecalRoad | GroundCover | Forest items | visibleDistance |
|---|---|---|---|---|---|---|
| West Coast USA | 22 067 | 1 037 | 12 752 | 14 | 133 363 | 15.7 km |
| Italy | 13 971 | 627 | 7 900 | 27 | 206 148 | 25 km |
| Johnson Valley | 15 559 | 190 | 4 345 | 12 | 663 057 | 24.5 km |
| East Coast USA | 2 187 | 225 | 3 115 | 23 | 186 706 | 12 km |
| Utah | 2 608 | 254 | 3 554 | 8 | 160 169 | 5 km |

WCUSA Forest types (top): guardrail posts/rails 26k, desert rocks 34k, shrubs 26k, fences 7k – i.e. Forest is
used for **every repeated prop**, not only trees (`levels/west_coast_usa/art/forest/managedItemData.json`,
226 `TSForestItemData`). Trees ship `.dae.imposter.dds` (104 in WCUSA). GroundCover example (`shrubs_med`):
`gridSize 2, maxElements 43 688, dissolveRadius 150, shapeCullRadius 200, shapesCastShadows false,
reflectScale 0`, layers keyed on terrain materials ("Forest", "grass4", "dirt_grass"). Shared tree library
always mounted: `/assets/meshes/foliage/trees_library/{beech,oak,birch,cork_oak}` + `bushes/generibush*`
(`GAME/content/assets/meshes.zip`, no imposter DDS shipped -> generated at first use, exe: "Creating
imposters for: '{}'"). Road materials: `/assets/materials/decalroad/asphalt/*` (`assets/materials/decalroad.zip`).

### 4.2 Engine mechanisms to build on

| Mechanism | Use | Evidence | Open question |
|---|---|---|---|
| **Forest** + `ForestItemData` | trees, shrubs, rocks, poles, guardrails | Runtime API: `core_forest.getForestObject():getData():createNewItem(itemData, MatrixF, scale)`, `removeItem`, `getItemsCircle` (`GAME/lua/ge/extensions/util/forestGenerator.lua:34,64,167,172`); Forest object creatable (`editor/forestEditor.lua:1444`); item data via `createObject('ForestItemData')` + `shapeFile` (`editor/forestTsstaticMover.lua:144-160`). Far items rendered as **imposter batches per cell** (`T3D forest/forestCell.cpp:70-125`), counters `$Forest::cellsRendered/cellItemsBatched` | [P4] cost per `createNewItem`/`removeItem` (batch of 1 000), whether `worldEditorCppApi` is needed outside the editor, imposter generation time per species |
| **GroundCover** | grass, flowers, small shrubs near the car | Placement keyed on the TerrainBlock's material layers, regenerated on terrain updates (`T3D T3D/fx/groundCover.cpp:1137-1161, 1394-1412`); billboards batched; `shapesCastShadows` gate (`:1600`); `$pref::GroundCover::densityScale` | [P5] works on a **render-disabled** TerrainBlock? cost of cell rebuild after each import |
| **Terrain layer maps** | per-surface physics (groundmodel: asphalt, grass, sand, mud, rock, snow) and GroundCover layers | `importMaps(..., materials, textureMaps)` takes one layer map per material with a channel (`terrain.lua:89-103`, stock `util/terrainGenerator.lua:183-185`); `setMaterialIdxWs` + `updateGridMaterials` for patches (`editor/toolUtilities/terrainPainter.lua:96,107`) | [P6] import cost with 4–8 layer maps (pack 4 per RGBA PNG); changing only layer maps must not trigger the 121 ms texture repack (that came from changing a material's texture, V1_3_SPEC) |
| **TSStatic chunks** (server .cdae, shared materials) | roads, buildings, bridges | as far tiles today; `instanceColor` tint; `smallestVisibleSize` cull; detail levels inside one .cdae (TSShape LODs: engine picks per pass, shadow pass with its own detail scale, exe help "lod detail adjust in shadow") | cdae writer needs multi-detail support |
| DecalRoad | – | clips against **terrain polys only** in T3D (`environment/decalRoad.cpp:1445`) and re-clips on every terrain update (`:388,1691`) | Not recommended: our terrain moves every 128–256 m and covers only 1–2 km; roads beyond would vanish. |

### 4.3 Layers: generation, protocol, client units, radii

General rule: the **server** decides what exists (selection by distance/screen error, per-layer caps); the
**client** only imports, places, deletes, within the governor; everything shares one quadtree vocabulary
(layer content hangs on quadtree nodes) so swap groups and the `far_swap` "never remove before the
replacement is loaded" rule carry over.

| Layer | Server generation | Representation in game | Radius / LOD | Collision |
|---|---|---|---|---|
| Roads near | OSM/Overture road graph -> ribbons (width from lanes/class), draped onto the **exact** L-2 triangulation (clip ribbon polygons against the 2 m lattice triangles, same `torque_split45` diagonals), lifted 3–5 cm; markings as a 2nd UV set into a shared marking atlas. **Grade the DEM under roads** before writing heightmap and L-2 tiles, so physics, visuals and road agree. | one TSStatic per 256 m node (L0 key), 2–3 shared materials (asphalt, markings, gravel), `castShadows=0`, `collisionType=None` (physics = graded terrain + ASPHALT layer) | 0–1.5 km, L0 chunks; 1 detail level | terrain |
| Roads far | rasterise OSM roads into the tile imagery texture (asphalt colour, line at sub-texel width ramps) | none (in far tile textures) | 1.5–80 km | – |
| Bridges/tunnels | OSM `bridge=yes` decks + piers | TSStatic `'Visible Mesh Final'` collision, per bridge | 0–1 km collidable, visual to 5 km | kd-tree (budget below) |
| Buildings LOD0 | footprints + height/levels (OSM, Overture), flat/gabled roofs, facade UVs on a shared atlas (floor 3 m, window bays), `instanceColor` tint | merged per 256 m node, <= 65k verts/mesh, 2–4 shared materials, LOD0/1 detail levels inside the .cdae, `meshCulling` on | 0–1 km | box hulls (12 tris/building) in a `Collision Mesh` detail, only nodes within ~300 m |
| Buildings LOD1/2 | extruded boxes + roof colour, merged per 1 km node (L2) | 1–2 shared materials, `smallestVisibleSize` cull | 1–8 km | none |
| Buildings far | darken/raise in far tile texture only | – | > 8 km | – |
| Trees | ESA WorldCover (tree class) + Meta canopy height (size), OSM `natural=wood/tree`; Poisson-disk placement per 256 m cell, species by biome from the stock library; avoid roads/buildings masks | **Forest** items (one Forest object; items added/removed per cell) | mesh to ~250 m, imposters to 3–5 km; beyond: only imagery | trunks optional (ForestItemData radius) |
| Ground cover | none (engine) – server sends land cover as terrain layer maps | **GroundCover** objects per biome keyed on layers | 150–200 m (engine) | – |
| Ground models | WorldCover/OSM landuse -> 4–8 terrain materials with `groundmodelName` | TerrainBlock layer maps (render disabled) | terrain block | terrain |
| Water | OSM water polygons | WaterPlane/WaterBlock later | – | – |
| Navgraph | OSM roads | `map.reset(customMapNodes)` (`lua/ge/map.lua`, ARCHITECTURE.md) | ~2 km | – |

Protocol v5 (additive to v4):
- `materials {defs:[{name, colorMap, normalMap?, detailMap?, castShadows, instanceDiffuse, groundType?}]}` –
  shared materials once per session (roads, facades, roofs); chunks only name them.
- `chunk {layer, key, level, frame:'anchor'|'tile', anchorId? | origin:{lat,lon,h}, shape, pos, rot?,
  materials:[names], collision:'none'|'hull'|'mesh', tris, bytes, castShadows}` and
  `chunk_swap {layer, id, add, remove}` / `chunk_remove {layer, key}` with `far_swap` semantics.
- `forest_cell {key, file}` – a binary file per 256 m cell: `u16 type, f32 x, y, z, u8 yaw, u8 scale` (14 B/item,
  1 000 items = 14 KB) parsed with `ffi.copy` as net.lua does; `forest_drop {key}`.
- `terrain` gains `layers:[{material, path, channel}]` (fixed material list per session).
- `nav {file}`.

Client: a generic `chunks.lua` (farfield's instance/queue/swap machinery, parameterised per layer) and
`forest.lua`. Governor kinds and priors to start with [I]: `roadChunk 2 ms`, `bldChunk 4 ms`, `forestBatch`
(N items per unit, sized from P4 so a unit <= 2 ms), `forestDrop`, `collisionReload` (heavy slot, batched with
terrain commits). Priority order: near ground > near roads > near buildings > trees > far anything.
Per-layer **caps** live on the server (objects/tris per layer around the player) and an **adaptive radius**
controller on the client: if p95 `$fps::gpuTime` > 14 ms for 5 s, shrink tree and building radii by 10 %
(and grow back slowly), reported to the server in `pose`.

Rebase: road/building/tree content uses tile-local frames like the far tiles (3.2), so it survives rebases;
road ribbons draped in the old anchor frame are off the new lattice by < 2 cm over a 256 m chunk – hidden by the
3–5 cm lift and rebuilt lazily.

### 4.4 Budgets for >= 60 FPS at 3840x2160

Assumption: 16.7 ms frame; the engine's fixed cost at 4K (post FX: SSAO, DOF, light rays, bloom, SMAA 4,
clustered lighting Ultra, vehicle + reflections) is unknown – P1 in an official map gives it. These are
planning targets [I], to be replaced by P1/P4 numbers.

| Layer | Objects in view | Draw calls (main) | Shadow casters | Tris in view | GPU ms | Main-thread streaming |
|---|---|---|---|---|---|---|
| Ground L-2..L0 (anchor) | ~230 | ~230 | yes | ~0.5 M | 1.0 | cdaeTex ~4 ms/unit |
| Ground L1+ (global, 64²) | ~170 | ~170 | L1 only | ~1.4 M | 0.8 | 6–8 ms/unit, rare |
| Roads near | <= 100 chunks | <= 250 | no | <= 0.3 M | 0.5 | ~2 ms/unit |
| Buildings LOD0 | <= 50 chunks | <= 150 | yes | <= 0.8 M | 1.5 | ~4 ms/unit |
| Buildings LOD1/2 | <= 60 chunks | <= 120 | no (or L1 only) | <= 0.6 M | 0.7 | ~4 ms/unit |
| Trees (Forest) | <= 30k items, <= 1 000 as meshes | <= 2 500 (meshes are not instanced above 200 verts) + imposter batches | near meshes only | <= 3 M | 2.5 | batches <= 2 ms |
| Ground cover | engine | ~100 batches | no | – | 0.8 | none |
| Collision kd-tree | – | – | – | <= 50k tris (~7.5 ms rebuild) | – | heavy slot only |
| **Sum** | | **<= ~3 500** | | **<= ~7.5 M** | **~8** | **<= 2–3 ms/frame** |

Reality check: today ~900 draws/pass and ~2 M tris give 14.3 ms in the desert, so this table is only
reachable after section 1 (shadow casters + bigger tiles) brings the ground back to ~10.5 ms (v1.2 level).
If P1 shows the frame is render-thread bound, cut the tree mesh radius first (imposters are batched).

### 4.5 Environments

Per biome (Köppen class or ecoregion from the server): a terrain material set (groundmodels), GroundCover
types, a tree species list from the stock library (beech/oak/birch for temperate, conifers from WCUSA assets
for mountains [I: other levels' zips are mounted under `/levels/...`; P7], desert shrubs/rocks from Johnson
Valley/Utah), and a detail texture for the mesh tiles (satmat `DETAIL_MAP` per biome). Snow from WorldCover
class 70 / latitude-altitude. Night: street lights later via `nightEmissive` TSStatics.

---

## 5. Probes to run (in order)

| Id | What | Why |
|---|---|---|
| P1 | Frame A/B with metrics (1.5) in the desert, canyon, WCUSA, JV, Italy | decides 1.4 order; sets the budget baseline |
| P2 | `importMaps` 512²/1024² with vs without layer map; raw/DDS heightmap | commit cost model |
| P3 | Terrain commit without `reloadCollision` (car stays on new block?) | keeps commits cheap once buildings collide |
| P4 | Forest at runtime: create Forest + ForestItemData from Lua outside the editor; time `createNewItem` x1000, `removeItem` x1000; imposter generation per species | tree streaming units |
| P5 | GroundCover on a render-disabled TerrainBlock; rebuild cost after `importMaps` | grass/shrubs |
| P6 | `importMaps` with 4–8 materials and layer maps: cost, no texture repack | ground models |
| P7 | Reference `/levels/west_coast_usa/art/shapes/trees/...` from our level | conifer/desert species |
| P8 | 64x64-cell, 512² tile import cost (cdaeTex) | section 1.4 item 3 |

## 6. Sources

Game: `GAME/lua/ge/extensions/core/settings/graphic.lua:1170-1215,1494-1515`, `settingsPresets.json:10,42,73,105,137`,
`core/cameraUpdate.lua:40,186-192`, `core/metrics.lua:32,235-257`, `editor/materialEditor.lua:2218,2395`,
`editor/inspector.lua:383`, `util/forestGenerator.lua:23-184`, `editor/api/forest.lua:44-72`,
`editor/forestEditor.lua:1442-1450`, `editor/forestTsstaticMover.lua:131-165,262-270`,
`editor/toolUtilities/terrainPainter.lua:96-107`, `util/procTrack.lua:1278`; exe strings of
`BinLinux/BeamNG.drive.x64` (TSStatic fields, PSSM help texts, `lastSplitCastersEnabled`, 65k-vertex warning,
imposter messages); `content/levels/{west_coast_usa,italy,johnson_valley,east_coast_usa,Utah}.zip`,
`content/assets/meshes.zip`, `content/assets/materials/decalroad.zip`.
User: `USER/settings/settings.json:30-34,43,46,71,101-102`, `USER/settings/game-settings.json:4,7,57,61,64`.
Torque3D (`development`): `lighting/shadowMap/shadowMapPass.cpp:252-271`, `pssmLightShadowMap.cpp:267-379`,
`materials/materialDefinition.cpp:443`, `ts/tsMesh.cpp:89,258`, `ts/tsShapeInstance.cpp:46-88,676-678`,
`T3D/tsStatic.cpp:225-279`, `forest/forestCell.cpp:70-125`, `forest/forest.cpp:57-58,123-133`,
`T3D/fx/groundCover.cpp:572-577,677,1137-1161,1394-1412,1600`, `environment/decalRoad.cpp:388,1445,1691`,
`scene/culling/sceneCullingState.cpp:39,823-895`.
Project: `docs/ARCHITECTURE.md` (probe tables, v1.1–v1.3 results), `docs/V1_3_SPEC.md`, `server/farfield.py`,
`server/earthd.py:400-445`, `server/imagery.py`, `mod/.../{farfield,governor,satmat,core,terrain,follow}.lua`.
Scratch: `scratchpad/research/perf/{count_tiles.py,time_tile.py,count_level.py,exe_strings.txt,t3dsrc/}`.
