# What makes the official BeamNG maps look good, and what BeamNG.Earth can reuse

Research date 2026-10-10. Game: BeamNG.drive 0.39.4 (Linux). No game or MCP contact. Everything below comes
from files in the install. Paths starting `lua/`, `shaders/` and `content/` are relative to
`~/.local/share/Steam/steamapps/common/BeamNG.drive`. `levels/<x>/...` means a file inside `content/levels/<x>.zip`.
The scratch extraction is in `/tmp/claude-1000/.../scratchpad/research/maps` and the scripts are in `.../research/scripts`
(`dissect.py`, `daelod.py`).

Tags: **[V]** means verified in game files or by counting them. **[I]** means inference: not verified, needs a probe.

---

## 0. TL;DR

1. **Official ground = painted terrain + overlays, all inside 250 m.** The terrain shader turns detail textures off
   beyond `min(250, detailDistances.w)` and macro textures beyond `min(1000, macroDistances.w)`
   (`shaders/common/terrain/terrain.h.hlsl:181-185`) [V]. Beyond 1 km, an official map shows only a baked "base"
   colour/normal/AO/roughness texture at ~1 m/px over the whole map. Our satellite tiles are already that, at
   USGS ~1.9 m or EOX 10 m. **What we lack is everything in the 0–250 m band and the baked normal/AO/roughness of
   the far ground.**
2. **Density is the "alive" factor.** Forest items: 12k–70k per km². TSStatics: 0.6k–5.3k per km². DecalRoads: 0.5k–3k per km².
   Every map has 8–27 GroundCover objects and one CloudLayer. Guardrails, fences, poles and curbs are **Forest items**, not TSStatics.
3. **We can reference nearly all of it at runtime without redistributing anything.** All level zips sit in the VFS.
   Official maps already cross-reference each other's files. `art/` and `assets/` materials load globally at startup
   (`lua/ge/client/init.lua:176-178`). Level-only materials and ForestItemData can be loaded on demand with the global
   `loadJsonMaterialsFile(path)`, the same call the level loader uses (`lua/ge/server/server.lua:200-223`).
4. **Runtime creation paths all exist in stock Lua:**
   - Forest: `createObject('Forest')` / `forest:getData():createNewItem(itemData, MatrixF, scale)`.
   - GroundCover: `createObject('GroundCover')` plus indexed `setField`. It needs a **TerrainBlock layer map**.
   - DecalRoad: `createObject('DecalRoad')` + `insertNode`.
   - v1.5 Material: `setField('version',0,'1.5')`.
5. **Ranked by look gained per effort:**
   - (a) Add a CloudLayer and ForestWindEmitter, and fix our night colours.
   - (b) Move the tile material to v1.5 with a DEM normal map and a land-cover roughness map. Water gets low roughness.
   - (c) Paint the invisible physics TerrainBlock's layer map with land cover. That gives GroundCover grass and
     per-surface groundmodels for tyre grip.
   - (d) Add trees and rocks as Forest items within ~1.5 km, using level tree shapes that ship imposters.
   - (e) Add OSM DecalRoads (lines, edges, invisible navgraph roads) within ~300 m.
   - (f) Make buildings server-extruded `.cdae` meshes with *global* tileable PBR materials.

---

## 1. Dissection of four official maps

### 1.1 Object classes and counts [V]
Counts are from all `main/**/items.level.json` (plus `main.level.json` for JV). Area is the TerrainBlock extent
(`size × squareSize`; squareSize 1 m where unset, 0.75 m for JV).

| | west_coast_usa | johnson_valley | Utah | italy |
|---|---|---|---|---|
| Terrain | 2048² ≈ 4.2 km² | 4096² @0.75 = 9.4 km² | 2048² ≈ 4.2 km² | 4096² ≈ 16.8 km² |
| Objects total | 41 513 | 20 357 | 7 506 | 23 156 |
| TSStatic | 22 067 (5.3k/km²) | 15 559 (1.7k/km²) | 2 608 | 13 963 |
| DecalRoad (nodes) | 12 752 (59 557) | 4 345 (23 822) | 3 554 (18 218) | 7 884 (64 087) |
| MeshRoad | **0** | **0** | **0** | **0** |
| Forest items (types) | 133 363 (143) | 663 057 (76) | 160 169 (50) | 206 148 (99) |
| – vegetation / rock / man-made per km² | 10.3k / 10.0k / 11.5k | 6.4k / 61.7k / 2.2k | 6.6k / 31.2k / 0.5k | 8.4k / 1.7k / 2.1k |
| GroundCover objects | 14 | 12 | 8 | 27 |
| SpotLight / PointLight | 3 371 / 682 | 14 / 11 | 349 / 34 | 148 / 0 |
| Water | WaterPlane + 3 WaterBlock + 2 River | WaterPlane (hidden) | 2 WaterBlock + River | WaterPlane + 6 WaterBlock + 7 River |
| Prefab | 610 | 244 | 436 | 217 |
| Sky objects | LevelInfo, ScatterSky, TimeOfDay, CloudLayer, ForestWindEmitter, Precipitation | same minus Precipitation | same minus Precip. | same + Precipitation |

TSStatic content, by parent folder of shapeName:
- **WCUSA:** objects 14 754, buildings 2 327, steel_factory 1 081, rocks 995+359, Clutter 891, roads 130.
- **Italy:** buildings 6 487, signs 3 951, quarry 1 551, rocks 1 261.
- **JV:** rocks 13 791 (TSStatic rock sheets).
- **Utah:** buildings 1 178, rocks 817.

Top man-made Forest types:
- WCUSA: guardrailpost 9 653, guardrail1/2 16k, pole_fence 7k.
- Italy: italy_guardrails_basic 10 620, italy_curb_3m 5 507, stone walls 6.7k, plus *window and door modules from
  `/art/shapes/common/building_architect_modules/`*.

**Repetitive linear props go in the Forest** [V].

TSStatic fields used (WCUSA+Italy, 36 030 statics):
- `useInstanceRenderData: true` on 24 001.
- `decalType: None` on 10 654.
- `collisionType: None` on 1 395.
- `instanceColor` on 2 478.
- `nightEmissive` on 1 426: lit windows and signs at night.
- `forceDetail: -2` on 153.
- `isRenderEnabled: false` is serialised on 35 924 statics that obviously render, so it is not a "hidden" flag.
  Don't copy it blindly [V counts / I meaning].

### 1.2 Forest data [V]
- One `Forest` object per level (`theForest`). Its instances live in `levels/<x>/forest/<type>.forest4.json`.
  Each instance is NDJSON `{"pos":[x,y,z],"rotationMatrix":[9],"scale":s,"type":"<ForestItemData>"}`.
- Item types are `TSForestItemData` / `ForestItemData` datablocks in `levels/<x>/art/forest/managedItemData.json`:
  WCUSA 226, JV 78, Utah 83, Italy 208. The fields are `shapeFile` plus wind/physics fields.
  Example, oak: `windScale 0.5, trunkBendScale 0.04, branchAmp 0.1, detailAmp 0.5, detailFreq 0.5, rigidity 5`.
  Rocks carry `radius`, `dampingCoefficient`, `shadowNullDetailSize 40`, `dynamicCubemap 0`.
- **LODs follow the Torque naming convention in the .dae.** The suffix `aN` means "use this mesh while the shape is
  ≥ N px", `bb_autobillboard25` means an imposter below 25 px, `nulldetailN` means hidden below N px, and `Colmesh*` is collision.
  Measured with `daelod.py`:
  - `levels/west_coast_usa/art/shapes/trees/trees_oak/oak_a.dae`: a900 6 433 / a600 4 501 / a300 3 147 / a150 2 258 tris,
    Colmesh 54, imposter <25 px.
  - `shrub_a.dae`: a450 1 621 / a150 972, Colmesh 10.
  - `/assets/meshes/foliage/trees_library/oak/tree_oak_large_a.dae`: a1400 5 416 / a800 1 440 / a400 992, Colmesh 120.
  - Building `city_block1.dae`: a2200 14 821 / a250 438, Colmesh 1 612.
  - `cabin1.dae`: a400 1 411 / a150 223 / a50 24, nulldetail10.
- **Imposters are pre-baked and shipped.** For example, `oak_a.dae.imposter.dds` + `.imposter_normals.dds` (1.4 MB each)
  sit next to `oak_a.dae.asset.json`, which holds `{"imposters":[{"detailLevel":3,"dimension":256,"equatorSteps":16,"size":25}]}`.
  Coverage:
  - Italy: 39/39 tree shapes have imposters.
  - Utah: 15/15.
  - ECA: 72/72.
  - WCUSA: 33/41.
  - JV: 10/11.
  - The shared `/assets/meshes/foliage/trees_library/*` has **none**. If the engine had to bake them at first use,
    that would cost a hitch [I].
- Rough math: a 10 m tree at 1080p and 60° FOV is ~935·10/d px, so it becomes an imposter beyond ≈370 m. Forest
  rendering is cell-batched: `core/metrics.lua:249-251` reports "Cells Meshed / Cells Billboarded / Meshes /
  Billboards" [V]. That batching is why 660k items on JV are affordable.
- One `ForestWindEmitter` per map (strength 0.2–0.5; Italy gustStrength 3, turbulence 5.25). Without one, trees are static [I].

### 1.3 GroundCover [V]
65 GroundCover objects across the four maps.

| Setting | Typical range |
|---|---|
| Ranges `radius / dissolveRadius / gridSize` | close 50/30/6–8; medium 100–150/60–100/8; far 350/250/2 |
| `maxElements` | 5k–650k (median ~100k) |
| `shapeCullRadius` | 45–300 |
| `shapesCastShadows` | always false |
| `reflectScale` | 0 |

- Up to 8 `Types` per object (`groundCoverEditor.lua:14`). Per type: `layer` (terrain material name),
  `billboardUVs` (atlas rect), `shapeFilename` (optional 3D mesh), `probability`, `sizeMin/Max/Exponent`,
  clump fields, `maxSlope`, `min/maxElevation`, `windScale` (`groundCoverEditor.lua:39-57, 59-64`).
- Materials used: `m_jv_dry_grass`, `dry_grass`, `m_grass_green_short_01`, `m_grass_dry_01`, `m_utah_dry_grass`,
  `m_flowers_01`, `wca_groundcover`, `italy_bushes_bb`, `BNGGrass_3`.
- JV uses 3D shapes (`/levels/johnson_valley/art/shapes/groundcover/s_gc_*.dae`, pebbles) with `material` atlas billboards.
- **Placement is a GPU compute shader that reads the TerrainBlock heightmap and layer map.** A type is valid only if
  `typeMaterialId == terrainMatId` from `layerMap`, the height is inside min/max elevation, the slope is below
  maxSlope, and the UV is inside the terrain (`shaders/common/groundCoverPlacement.hlsl:107-125`).
  **No TerrainBlock means no GroundCover.** The editor tooltip says an empty layer means all layers
  (`groundCoverEditor.lua:156`). That path is not visible in the shader [I].
- Global density preference: `$pref::GroundCover::densityScale` (`core/settings/graphic.lua:1477-1480`).
- `flushGroundCoverGrids()` regenerates the cells (`editor/groundCoverEditor.lua:316-320`, `screenshot.lua:937-938`).

### 1.4 Terrain material layers (v1.5 TerrainMaterial) [V]
Every map has 11–15 `TerrainMaterial`s in `levels/<x>/art/terrains/main.materials.json` plus one
`TerrainMaterialTextureSet` (`baseTexSize` 2048–4096, `detailTexSize`/`macroTexSize` 1024).

Each material has 5 channels (baseColor, normal, roughness, ao, height) at 3 scales:
- **Base:** `*BaseTex`, one texture over the whole map. `t_terrain_base_{b,nm,r,ao,h}.png` at 2048–4096 px, so ≈1 m/px.
  Shared by all materials.
- **Macro:** `*MacroTex`, tiled every `*MacroTexSize` = 5–160 m (most often 30–100 m).
  Strength pairs `[near, far]` are typically baseColor 0.1–0.5 and normal 0.3–0.8.
- **Detail:** `*DetailTex`, tiled every 1–3 m (`*DetailTexSize`, default when unset). baseColor strength 0.2–0.6 near,
  0–0.3 far. normalDetailStrength ~1 near, 0–0.3 far.
- **Distances** are 4-tuples `[fadeInStart, fadeInEnd, fadeOutStart, fadeOutEnd]` (`terrain.h.hlsl:131-134`):
  - Detail typically `[0,0,20–100,40–3000]`. It is hard-capped at 250 m.
  - Macro `[0,0–100,100–1000,3000]`. It is hard-capped at 1 000 m (`terrain.h.hlsl:181-185`).
- **`groundmodelName` sets tyre physics per layer:** ASPHALT, GRASS, DIRT_ROCKY, SAND, GRAVEL, FOREST_FLOOR,
  DIRT_LOOSE_DUSTY, and so on.
- The detail and macro textures are shared library sets in `/assets/materials/terrain/{grass,soil,rock,sand,asphalt,forest,concrete,mud}/...`
  (`content/assets/materials/terrain.zip`). Examples: `t_ind_grass_{b,nm,r,ao,h}.png`, `t_macro_grass`,
  `macro_rocky`, `t_macro_flows`, `t_macro_sand`, `macro_clumply`, `t_gravel`, `t_dirt_crumbly`, `t_forest_ground`.
- The official template level references them via `.png.link` stubs, e.g. `levels/template/art/terrains/t_asphalt_ao.png.link`
  = `{"path":"/assets/materials/terrain/asphalt/asphalt/t_asphalt_ao.png"}`.

### 1.5 Roads [V]
**No official map uses MeshRoad.** Drivable roads are terrain painted with an asphalt or dirt TerrainMaterial,
under many DecalRoad overlays. Bridges and overpasses are TSStatic meshes (WCUSA `art/shapes/roads`, 130 instances).

DecalRoad usage:
- **Materials:**
  - WCUSA: line_white 3 141, line_yellow 1 478, road_invisible 1 299, track_rubber 828, road_crack 736, road_edge 440,
    road_asphalt_2lane 385.
  - JV: dirt tiretracks/flows/variation.
  - Italy: road markings, edge damage grassy, cracks, asphalt overlay.
- **Fields:**
  - `distanceFade` mostly `[200,50]` (WCUSA 8 775 roads), `[80,40]` or `[90,30]` (Italy), `[150,50]` (JV).
    **Overlays are invisible past 80–200 m.**
  - `textureLength` 4–300.
  - `renderPriority` used for stacking.
  - `improvedSpline: true` almost always.
  - `startEndFade` 0.1–50.
  - `decalBias` 0.0015–0.05.
  - `overObjects: true` on 5 177 WCUSA roads.
- **Geometry:**
  - Width p10/p50/p90 = 0.2/3/8 m.
  - Median node spacing 11–12 m, p90 25–37 m.
  - Median 2–4 nodes per road.
- `road_invisible` + `drivability > 0` gives navgraph-only roads, used for AI.
  The Road Architect also emits them (`editor/tech/roadArchitect/decals.lua:104-118`).

### 1.6 Lighting and environment [V]

| | WCUSA | JV | Utah | Italy | **ours** (`levels/beamng_earth/main/MissionGroup/Sky`) |
|---|---|---|---|---|---|
| visibleDistance | 15 667 | 24 500 | 5 000 | 25 000 | 100 000 |
| fogDensity | 3.5e-4 | 1.5e-3 | 3e-4 | 2e-4 | 4e-5 |
| fogAtmosphereHeight | 193 | 76 | 257 | 246 | 1 000 |
| globalEnviromentMap | cubemap_wca_reflection | cubemap_johnson_valley_reflection | cubemap_utah_reflection | cubemap_italy_reflection | BNG_Sky_01_cubemap (generic) |
| ScatterSky skyBrightness | 220 | 40 | 40 | 40 | 40 |
| mieScattering | 9.6e-5 | 4.0e-4 | 5.5e-4 | 6.8e-4 | 4.3e-4 |
| nightColor / nightFogColor | black / black | black / black | black / black | black / black | **[1,.89,.78] / [.40,.67,1]** (bright) |
| sunScale | [1,.84,.75] | [1,.65,.16] | [1,.55,.09] | [1,.73,.6] | [1,.81,.71] |
| CloudLayer | coverage 1, exposure 1.45, `art/skies/clouds/clouds_normal_displacement.png` | 1.23/1.3, `levels/jungle_rock_island/art/skies/SkyNormals_05.dds` | 1.23/1.5, `levels/Utah/art/skies/clouds_fluffy.dds` | 1.23/1.4, SkyNormals_05 | **none** |
| ForestWindEmitter | yes | yes | yes | yes | **none** |

- **PostFX/HDR/SSAO/tonemapping is not per level.** No level zip contains a `.postfx`.
  `lua/ge/client/postFx.lua:57-64` loads the global `lua/ge/client/postFx/presets/defaultpostfxpreset.postfx`:
  - HDR on, bloom on, `enableToneMapping: false`, colour ramp `default_color_ramp.png`.
  - SSAO on, `overallStrength 19.65`.
  - DOF on.
- So the "official look" in lighting comes from four things: the per-level reflection cubemap, ScatterSky
  colour/gradient tuning, haze (fog density ~2–15× ours with a 75–260 m height falloff), and clouds.
- `CloudLayer` is now **volumetric** (`volumetricEnabled`, `vrtDownsampleFactor`; `core/settings/graphic.lua:1326-1340`).
  It has a world-space weather offset: `core_environment.setCloudWeatherOffsetKm`, `environment.lua:936-950`.
  - **For rebase:** shift the offset by the rebase vector so clouds don't jump [I].
  - Cover, altitude and wind are set via `core_environment.setCloudCover/setCloudAltitudeKm/setCloudWindDirection`
    (`environment.lua:871-920`).

---

## 2. Shared assets we can reference at runtime (no redistribution)

**Mechanism [V]:**
- Level zips are in the VFS for every level. Official maps load each other's files:
  - WCUSA TSStatics use `/levels/industrial/art/shapes/...` (30).
  - The WCUSA ocean uses `/levels/small_island/art/water/ripple4.dds`.
  - JV clouds use `levels/jungle_rock_island/...`.
  - WCUSA's global decal-road materials point at `/levels/west_coast_usa/art/road/...`.
- `art/` and `assets/` `*materials.json` load globally at startup (`client/init.lua:176-178` → `main.lua:1330-1360`).
  So the materials below need no action.
- Level-only materials and item data need `loadJsonMaterialsFile('/levels/<x>/.../main.materials.json')` and
  `loadJsonMaterialsFile('/levels/<x>/art/forest/managedItemData.json')`. The level loader does exactly this for
  `*materials.json` and `/%a+Data%.json$` (`server.lua:200-223`).
- We ship only *paths*, never textures or meshes.
- One caveat: material names collide across levels (`oak_leaves`, `shrub_a`, `m_jv_dry_grass` exist in several), and
  the last load wins [I].

### 2.1 Globally loaded, ready now [V]
- **Decal-road materials:** 40 in `content/art_shapes.zip: art/shapes/common/decalroads/main.materials.json`.
  They include `road_asphalt_2lane`, `road_invisible`, `m_line_white`, `m_line_white_discontinue`, `m_line_yellow`,
  `m_line_yellow_double(_discontinue)`, `m_road_asphalt_edge(_grass)`, `m_road_edge_dirt(_grass)`, `m_dirt_road`,
  `m_dirt_road_flows/gravels`, `m_dirt_tiretracks(_02)`, `m_dirt_variation_01..04`, `m_asphalt_cracks_02`,
  `m_asphalt_damaged_01/02`, `m_tread_marks_clean`, `crossing_white`, `line_dashed_short`, `road_patches1`,
  `road_rubber_double`, `road1_concrete`, `gutter1`, `repair1/2`, `road_chevrons`, `mud_*`.
- **Road and sidewalk mesh materials:** `art/shapes/common/materials/main.materials.json` has `m_asphalt_new_01`,
  `m_concrete_plain_01`, `m_sidewalk_curb_trim_01`, `slabs_large`, `architraves`, `balustrades`, `columns`.
  Road Architect uses these (`roadMesh.lua:32-36`).
- **Building and facade PBR (v1.5) materials, one folder each under `art/shapes/objects/`:**
  `m_bricks_01`, `m_plaster_worn_01`, `m_plaster_raw_dirty_01`, `m_stucco_scraped_01`, `m_stonebrick_mixed_01/02`,
  `m_stonebrick_eroded_01`, `m_stonewall_damaged_01`, `m_roof_slates_square/rounded/ochre`, `m_metal_new_01`,
  `m_wood_oak_raw_01`, `m_wood_frame_trim_01`, `m_metal_frame_trim_01`, `m_edge_damage_trim_01`, `slabs_marble`,
  `windows_doors_reflective`, `m_transparent_glass_window`.
  - `m_windows_glass_01` has `emissiveMap t_windows_glass_01_lit_e`: lit windows at night.
  - Plus 55 in `art/shapes/objects/main.materials.json`: `concrete_plain`, `ind_metal_plates`, `si_metal_roof`,
    `metal_galvanized`, `guardrail`, `chainlink`, `roadsigns`, `instanced_trafficlight`, and others.
- **Italy building set, global (gameengine.zip `art/main.materials.json`, 27 materials):** `italy_bld_old_bricks`,
  `italy_bld_roof_tiles`, `italy_bld_windows`, `italy_bld_old_concrete`, `italy_bld_trim_concrete`, `italy_sidewalk_tiles`, …
  Textures are in `/assets/materials/{atlas,tileable}/...`.
- **Shared meshes (`content/assets/meshes.zip`):**
  - `/assets/meshes/foliage/trees_library/{beech,birch(aspen),oak,cork_oak}/*.cdae` (49 shapes: large/small/forest/bush/dead/blocker).
  - `/assets/meshes/foliage/bushes/generibush(_small).cdae`.
  - `/assets/meshes/architecture/buildings/industrial/ind_bld_02..08, ind_bld_tin_01_*, warehouse_huge_*` (2–9 MB each).
  - `/assets/meshes/architecture/modular/.../fences`.
  - **These trees' materials (`Oak_bark_01`, `beech_leaves`, `leaves_strong`…) are not global.** They are defined
    in level files such as `levels/east_coast_usa/art/shapes/trees/*/main.materials.json`.
- **Modular facade pieces:** `/art/shapes/common/building_architect_modules/{windows(64),doors(50),corner(23),string_course(13),pillar,roof_border,basement_plinth,balcony,stairs,gutter}`.
  Italy places them as Forest items.
- `/art/shapes/garage_and_dealership/Clutter/*` (595 files) and `/art/shapes/objects/*` (barriers, crates, bus stops).

### 2.2 Level assets to load on demand (load the listed materials.json first) [V]
**Trees with LODs and shipped imposters, by biome:**
- **Temperate/eastern:** `levels/east_coast_usa/art/shapes/trees/{trees_aspen(17),trees_beech(18),trees_douglasfir(16),trees_oak(14),ECA_coast_bush(5)}/`.
  Materials are in each folder plus `.../trees/common/` and `.../trees/main.materials.json`.
  hirochi_raceway has the same set.
- **Mediterranean:** `levels/italy/art/shapes/trees/trees_italy/` (39: cork_oak_*, holm_oak_*, olive, maritime_pine_*,
  cypress_tree/hedge, fanpalm_*, generibush, fluffy_bush, scraggly_*, grape_vine).
- **Californian:** `levels/west_coast_usa/art/shapes/trees/{trees_conifer(pine_radiata_*, redwood_*),trees_oak(oak_a..d, oak_a_distant),trees_eucalyptus,trees_palm,trees_cypress,trees_shrub}/`.
- **Arid:** `levels/Utah/art/shapes/trees/Juniper/` (15) and `levels/johnson_valley/art/shapes/trees/{deserttrees,trees_shrub}/`.
- **Tropical:** `levels/jungle_rock_island/art/shapes/trees/{trees_palm,trees_tropical_1,trees_tropical_2,bush_tropical_1/2}/`.

**ForestItemData sets** (wind and physics already tuned): `levels/{west_coast_usa,johnson_valley,Utah,italy}/art/forest/managedItemData.json`.

**Rocks:**
- `levels/johnson_valley/art/shapes/rocks/s_rocks_desert_{tiny,small,medium,large,huge,collection}_*.dae` (170 files; low-poly in `rocks_low/`).
- `levels/Utah/art/shapes/rocks/utah_boulder_1..9, utah_rock_*`.
- `levels/italy/art/shapes/rocks/italy_rockface_*`.
- `levels/template/art/shapes/rocks/pac_rock_*`.

**Grass and GroundCover materials (atlases in `/assets/materials/foliage/{grass,groundcover,bush}/`):**
- `levels/west_coast_usa/art/groundcover/main.materials.json`: BNGGrass_3, grass_field, m_grass_dry_01, m_grass_green_01/02, m_weed_01, wca_groundcover.
- `levels/italy/art/shapes/groundcover/main.materials.json`: m_grass_green_short_01, m_flowers_01, italy_bushes_bb,
  m_grass_dry_short, plus copies of m_jv_dry_grass and m_utah_dry_grass.
- `levels/johnson_valley/art/shapes/groundcover/` (materials + `s_gc_*.dae` 3D shapes, pebbles).
- `levels/template/art/shapes/groundcover/main.materials.json`: GrassMiddle, a v1.5 template.

**Other level assets:**
- **Road materials:** `levels/{west_coast_usa,Utah}/art/road/main.materials.json` (line_white, AsphaltRoad_variation_01, …),
  `levels/italy/art/road/...`, `levels/johnson_valley/art/decalroad/...`. The 1.4 GB library is `/assets/materials/decalroad/{asphalt,lines,dirt,treadmark,...}`.
- **Reflection cubemaps:** `levels/<x>/art/cubemaps/cubemap_*_reflection/` (CubemapData in the level's materials.json).
  Pick one per biome instead of the generic BNG_Sky_01 [I: needs the CubemapData loaded first].
- **Terrain detail and macro texture library:** `/assets/materials/terrain/**` (see 1.4).

---

## 3. Creating these at runtime from GE Lua

### 3.1 Forest [V API, I costs]
- **Forest object:**
  ```lua
  local f = createObject('Forest'); f:registerObject('bngEarthForest')
  scenetree.MissionGroup:addObject(f)
  ```
  The editor uses `worldEditorCppApi.createObject("Forest")` (`editor/forestEditor.lua:1441-1450`, `biomeTool.lua:3533-3541`).
  `core_forest.getForestObject()` returns the first Forest (`core/forest.lua:9-19`).
- **Item data:** either `loadJsonMaterialsFile` on a level's `managedItemData.json`, or follow
  `editor/api/dataBlock.lua:13-41`: `createObject('TSForestItemData')`, `registerObject(name)`,
  `Sim.getDataBlockSet():addObject(db)`, `setField('shapeFile','',path)`. `forestTsstaticMover.lua:144-170` does the same.
- **Instances:**
  - `local fd = f:getData(); local it = fd:createNewItem(itemData, MatrixF(pos,rot), scale)`.
  - Remove with `fd:removeItem(it)`. Move with `fd:updateItem(key, keyPos, data, mtx, scale, uid)`.
  - Query with `fd:getItemsCircle(pos, r)` and `getItemsPolygon`.
  - Sources: `util/forestGenerator.lua:57-65, 141-173`, `editor/api/forest.lua:47-87`.
  - After bulk edits the editor calls `worldEditorCppApi.rebuildForestManagerInstanceData()`
    (`forestTsstaticMover.lua:276, 303, 359`). That is editor API, so check it exists outside the editor [I].
- **Native biome placer:** `ForestBrushTool():initBiomeMatProc(mask, matIdx, …, density, borderFalloff, slope, …)`
  is async (`isBiomeProcCompleted`/`insertBiomeItems`, `biomeTool.lua:1665-1800`). It is editor-oriented. Prefer
  server-side placement (below).
- **Collision:** forest items are part of the static kd-tree, so they need `be:reloadCollision()`.
  - At our measured TSStatic rate (~0.15 ms per 1k tris), 2 000 trees × 54 tri Colmesh ≈ 108k tris ≈ 16 ms extra per
    rebuild [I: rate measured for TSStatic, not Forest].
  - `forest:disableCollision()` exists (`forestEditor.lua:2508-2510`). Whether it removes the items from physics is
    untested; for ProceduralMesh it did not.
- **Rebase:** forest items are stored in world coordinates, so a rebase means either a per-item `updateItem` or
  removing and re-adding the tile's items. Whether `Forest:setPosition` shifts the items is unknown [I].

### 3.2 GroundCover [V API, I with an invisible terrain]
- Create it:
  ```lua
  local gc = createObject('GroundCover')
  gc:setField('material', 0, 'm_grass_green_short_01')
  gc:setField('radius', 0, '100'); gc:setField('dissolveRadius', 0, '60'); gc:setField('gridSize', 0, '8')
  gc:setField('maxElements', 0, '200000'); gc:setField('shapeCullRadius', 0, '90'); gc:setField('shapesCastShadows', 0, 'false')
  gc:setField('layer', 0, 'bngGrass'); gc:setField('probability', 0, '1'); gc:setField('billboardUVs', 0, '0 0 1 0.46')
  gc:setField('sizeMin', 0, '0.1'); gc:setField('sizeMax', 0, '0.3') -- type slot 0..7 = setField(name, slot, v)
  gc:registerObject(''); scenetree.MissionGroup:addObject(gc)
  ```
  This is the pattern from `groundCoverEditor.lua:368-383` and the defaults at `:76-79`.
- **It needs our physics TerrainBlock to carry a land-cover layer map.** `importMaps` takes material names and
  per-material mask PNGs (`util/terrainGenerator.lua:451-463`). Our `terrain.lua:89-101` currently imports a single
  all-white layer. Each TerrainMaterial's `groundmodelName` then also gives correct tyre grip for grass, sand, asphalt and so on.
- Call `flushGroundCoverGrids()` after each terrain-follow commit [I: cost unknown].
- **Unknown:** whether the GPU heightmap and layer textures that GroundCover samples still exist while
  `setRenderEnabled(false)` [I]. This is the key probe.
- **Visual fit:** GroundCover sits on the *bilinear* terrain height. Our mesh differs by median 0.4 cm, p99 3.9 cm
  (ARCHITECTURE v1.3). WCUSA uses `zOffset -0.15` for such cases.
- **Cost:** CPU is small because placement and wind run on the GPU. GPU cost scales with `maxElements` and radius.
  The official per-cell budget presets are Sparse 1 200, Normal 4 500 and Dense 8 500 elements
  (`groundCoverEditor.lua:108-112`).

### 3.3 DecalRoad / MeshRoad [V API]
- **Creation:**
  ```lua
  local r = createObject('DecalRoad')
  r:setField('improvedSpline',0,'true'); r:setField('material',0,'m_line_white')
  r:setField('overObjects',0,'true'); r:setField('drivability',0,'-1')
  r:setField('textureLength',0,'16'); r:setField('renderPriority',0,'8')
  r:setField('distanceFade',0,'200 50'); r:setField('startEndFade',0,'5 5')
  r:registerObject('')
  r:insertNode(pos, width, idx)
  ```
  Sources: `editor/api/roadRiver.lua:38-41, 67-87`; `roadArchitect/decals.lua:104-118, 189-202`.
- **MeshRoad:** `insertNode(pos, width, depth, normal, idx)` (`roadRiver.lua:144`). No official map uses it, and we don't need it.
- **Navgraph:** `material='road_invisible', drivability=1, lanesLeft/Right, oneWay` (`decals.lua:104-118`),
  or `map.reset(customNodes)` (ARCHITECTURE).
- **Projection onto our world [I]:** DecalRoads project onto the terrain, plus objects when `overObjects`.
  - Our visible tiles have `decalType='None'` (`farfield.lua:187`). Roads would then project onto the *invisible*
    TerrainBlock, which matches the mesh to cm (with `decalBias` 0.0015–0.05 as in official maps).
  - The alternative is `decalType='Visible Mesh'` on near tiles. Probe both.
- **Rebase:** `setNodePosition` per node, or recreate. Keep only roads within ~300 m: official overlays fade by 80–200 m,
  and the satellite already shows roads beyond that.

### 3.4 TSStatic, instanced
- Our tile import costs 1.9 ms (cdae) to 3.6–4.7 ms (textured) (ARCHITECTURE v1.2/v1.3).
- **Instancing:** official repeated props set `useInstanceRenderData=true` (24k statics; also
  `core/groundMarkerArrows.lua:62`, `editor/assetBrowser.lua:1222`). Unique per-tile meshes gain nothing from it.
- **For thousands of identical props, use the Forest instead.** BeamNG built `editor/forestTsstaticMover.lua`
  precisely to convert TSStatics into forest items.
- **Distant-city proxies:** `util/tileBake.lua:1-16` (dev only) bakes all statics and big forest items into 200 m
  tiles: one mesh plus an atlas per tile, with LODs. Vegetation is skipped because the forest imposter system covers it.
  **That is the same plan we should follow for far buildings:** server-merged per-tile building meshes.

---

## 4. PBR material v1.5 vs our v1.0 tile material

**Today** (`satmat.lua:72-95`): `createObject('Material')`, no `version` field, so it is v1.0.
Fields: `colorMap`, `useAnisotropic`, `roughnessFactor 1`, `detailMap` on UV1 with `detailScale 0.5`.

**v1.5 at runtime [V]:**
- `mat:setField('version',0,'1.5')`. Then per layer `i`: `setField('baseColorMap', i, path)` (`editor/api/material.lua:40-48`,
  `shapeEditor.lua:196`, `materialEditor.lua:2147`).
- `activeLayers` = 1..4 (`materialEditor.lua:2177-2190`).
- Stage fields seen in official v1.5 materials: `baseColorMap`, `baseColorFactor`, `normalMap`, `normalMapStrength`,
  `roughnessMap`, `roughnessFactor`, `metallicMap/Factor`, `ambientOcclusionMap`, `opacityMap`, `detailMap`,
  `detailNormalMap`, `detailScale`, `detailBaseColorMapStrength`, `detailNormalMapStrength`, `overlayMap`, and
  `diffuseMapUseUV`/`detailMapUseUV`/`normalDetailMapUseUV` (`art/shapes/common/materials/main.materials.json: m_asphalt_new_01`).
- Per-texture UV1 flags exist for every map (`shadergen.h.hlsl:26-57`), and so does BC5 normal support (`:41`).

**Shader facts (`shaders/common/material/shadergen/defaultMat.hlsl`) [V]:**
- Detail blend is `base + (detail*2-1)*factor` (`:204-210`). Detail is centred on 0.5, so a mean-0.5 detail map keeps
  the satellite colour.
- **There is no distance fade on detail in v1.5 either** (`:268, 301-307`). Keep the mip-to-grey trick of
  `art/beamngEarth/detail_ground.dds`.
- Layers ≥1 lerp over lower layers by their own `opacity` (`:291-308`). Example 2-layer material:
  `levels/johnson_valley/art/shapes/building/main.materials.json: m_metal_trim_trailers`, where layer 1 is a dust
  `baseColorMap` on UV1 plus an `opacityMap`.
- Normal: `normalMap × normalMapStrength`, plus `detailNormalMap × detailNormalMapStrength` (`:374-388`).
- Per-instance distance fade exists (`MaterialFlagInstanceDistFade`, `:481-483`).

**What would make the satellite ground look less flat** (ordered by value):
1. **Per-tile normal map baked from the DEM**, at the DEM's native resolution capped by the texture size. It matters
   most for far tiles, whose vertex spacing (tens of m) is far coarser than the DEM. That is what official
   `normalBaseTex` does for the whole map (all 4 maps ship `t_terrain_base_nm.png`). Use DXT5nm or BC5, about 1 B/px.
   - Caveat: imagery already contains baked sun shading. Keep `normalMapStrength` ~0.5–0.8, or partially de-light
     the imagery on the server using the DEM and the capture sun angle [I].
2. **Roughness map from land cover** (64–128 px per tile is enough):
   - water 0.1–0.2, which gives sun glint on lakes and sea;
   - asphalt and roofs 0.6–0.75;
   - rock 0.7;
   - vegetation and soil 0.9–1.0.
   The source can be ESA WorldCover or OSM, which are already in the plan.
3. **AO map from the DEM** (horizon or cavity, low-res), as official `aoBaseTex`. In PBR it only darkens ambient light,
   so it is more correct than multiplying it into the colour.
4. **Land-cover-specific micro detail without colour shift:**
   - Layer 0 = satellite + generic fine detail.
   - Layer 1..3 = *the same satellite `baseColorMap` on UV0*, a land-cover `detailMap` and `detailNormalMap` on UV1
     (world-locked), and `opacityMap` = that land cover's mask on UV0.
   - Detail colour maps must be mean-0.5 and fade to grey in the mips, so build them with `tools/make_detail_texture.py`.
   - Stock `/assets/materials/terrain/*/*_nm.png` can serve as `detailNormalMap` directly, because normals have a flat
     mean and mip-average toward flat.
   - Limit detail strength the way official materials do (0.2–0.6 near). Apply it only on L-2/L-1 tiles: official
     detail stops at ≤250 m.
5. **Macro variation is mostly unnecessary.** Satellite imagery already gives real large-scale variation. The one
   place it helps is EOX 10 m areas at 10–100 m from the camera, to break up pixel blocks.
   Official strength 0.1–0.5, tile size 30–100 m.

**Rejected:** rendering the physics TerrainBlock with v1.5 TerrainMaterials (satellite as `baseColorBaseTex`).
It would bring back the visible change on every terrain-follow commit that v1.3 removed. TerrainMaterialTextureSet
uploads are heavy.

---

## 5. Recommendations (ordered) and the probes they need

| # | Change | Expected look gain | Cost / risk | Probe (when not driving) |
|---|---|---|---|---|
| 1 | Add `CloudLayer` (volumetric) + `ForestWindEmitter` to the level. Set nightColor/nightFogColor to black. Raise fogDensity to ~1–2e-4 with fogAtmosphereHeight ~300–1000 m. Pick a biome reflection cubemap. | High (sky, depth, nights) | Clouds are GPU only. Shift `setCloudWeatherOffsetKm` on rebase | Clouds continuous across a rebase |
| 2 | v1.5 tile material: baseColorMap + DEM normalMap + land-cover roughnessMap (+AO) | High at mid/far range | +2 textures per tile (~+50% VRAM per tile) and import time | Import ms for v1.5 vs v1.0 (now 3.6–4.7 ms); BC5 vs DXT5nm |
| 3 | Land-cover layer maps on the physics TerrainBlock (materials named per class, with groundmodels). Add GroundCover objects per class within 50–150 m | High near the car | Extra mask PNGs per `importMaps` (time unknown). `flushGroundCoverGrids` per commit | **Does GroundCover render on a render-disabled TerrainBlock?** Import ms with 4–6 layers |
| 4 | Server places trees and rocks per tile (WorldCover class + Meta canopy height → species and size, blue-noise), streamed as `(type,x,y,z,yaw,scale)` binary. Mod calls `createNewItem` under the governor; keep ≤1.5–3 km (imposters beyond ~370 m) | Very high ("alive") | Collision tris in rebuilds (~16 ms per 2 000 trees) and rebase handling | ms per `createNewItem` (1k/10k), `disableCollision` effect, `setPosition` for rebase, imposter generation for trees_library |
| 5 | DecalRoads from OSM within ~300 m: lane lines, edges, `road_invisible` for AI; settings copied from official ones (distanceFade 200/50, decalBias 0.0015–0.05) | Medium-high | Rebuild on rebase; node count | z-fight on invisible terrain vs `decalType='Visible Mesh'`; ms per 100 nodes |
| 6 | Buildings: server-extruded `.cdae` with 2–3 LOD details (`aN` + `nulldetailN`) using global materials (`m_bricks_01`, `m_plaster_worn_01`, `m_roof_slates_*`, `italy_bld_*`, `m_windows_glass_01` emissive) + `nightEmissive`; far range = merged per-tile meshes like `tileBake.lua` | High in cities | cdae writer needs multi-detail + UV scale | None for materials (they are global) |
| 7 | Guardrails, fences, poles from OSM as Forest items along polylines (as WCUSA and Italy do) | Medium | Same as #4 | – |

What we deliberately don't copy:
- MeshRoad: unused by BeamNG maps.
- Per-level PostFX: it doesn't exist.
- Hand-placed TSStatic rock sheets: use Forest items instead.
- `WaterPlane` for oceans [I]: it is one infinite flat plane. In our flat ENU frame the sea surface falls d²/2R below it
  (7.8 m at 10 km, 196 m at 50 km), so it would flood distant low coastline. Draw water in the tile mesh with low
  roughness, or use local WaterBlocks.
