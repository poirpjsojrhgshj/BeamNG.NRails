# Engine probes in the running game: roads, water, vegetation, ground cover, terrain layers, navgraph, CEF (2026-10-11)

Scope: the in-game probes defined in `2026-10-10-editor-tools-roads.md` §6 (P1-P10),
`2026-10-10-editor-tools-buildings-veg.md` §6 (PB1, PF1-PF5, PM1, PA1-PA2, PP1, PE1, PT1, BAT), and the ROADMAP list
"In-game probes still to run": Forest item cost, decal roads on mesh tiles, GroundCover on a hidden terrain, 8-layer
terrain import cost, navgraph `map.reset` at ~5k nodes, CEF fetch from 127.0.0.1, and borrowing stock tree and sign
assets from other levels. The world-map doc's CEF probes P1-P3 (`2026-10-10-world-map-ui.md` §8) came along with the
CEF item.

Game: BeamNG.drive 0.39.4 (Linux, Vulkan, RX 7900 XTX, 4K, vsync on), level `beamng_earth`, mod in mesh mode
(physics-only TerrainBlock `bngEarthTerrain`, 512² at 2 m, render disabled), server `earthd.py --block 512`.
All probes were run unattended through the game's MCP server (`run_lua`, `ui_eval`, `screenshot`) on 2026-10-11, 02:55-03:30 local.
Test spot: flat desert in the Owens Valley east of Lone Pine (36.6000, -118.0450). Afterwards the car was teleported
back to the Mount Whitney summit.

Method: one Lua chunk per group (`probes_2026-10-11/engine_probes.lua` + `p_*.lua`) defines a global table `BNGE_P11`
whose steps return JSON. The driver is `probes_2026-10-11/run.py`, and every result is appended to `results.jsonl`.
Times come from `hptimer` (ms, main thread, inside one GE call). Frame costs come from a pcall-wrapped
`beamngEarth_perfmon.onUpdate` that also reads `Engine.Debug.getLastPerformanceMetrics` (FramePresent, Render,
RenderShadows), averaged over 3-5 s windows. A/B pairs toggle `hidden` on the probe objects (`ab.py`).
**Caveat:** other agents' Python jobs held 4-6 cores during the session, so the idle frame time drifted
between 10.4 and 15 ms. Frame deltas below about 1 ms are noise. Per-call times are not affected.

Every object got `canSave=false` and was deleted at the end of its probe. The live terrain block was restored by
re-importing its own heightmap with the mod's own `terrain.load` arguments, captured by wrapping that function once.
The camera was never moved, inputs were zeroed, and nothing was saved. No crash, freeze or restart happened.

Markers: **[V]** measured or seen in this session, **[I]** inference.

---

## 0. Summary: decision per probe

| Probe | Decision | Key numbers [V] |
|---|---|---|
| **P1 DecalRoad on our ground** (ROADMAP "decal roads on mesh tiles") | **GO**, `overObjects=false`, tiles keep `decalType='None'` | Renders on the **hidden** TerrainBlock. Edge z = physics ground ±1 mm, no z-fighting with the mesh tiles (`decalBias` 0.005). Setting near tiles to `decalType='Visible Mesh'` changes nothing. `overObjects=true` drapes onto a collidable deck (MeshRoad top, +3.000 m), while `false` stays on the terrain under it. Use `true` only on bridges |
| **P2 re-clip on terrain change** | **GO** (no speed limit needed) | DecalRoads re-clip **by themselves, inside the same call**, for both `updateGrid` (1 m bump: edge z +1.000 at once) and `importMaps`. Commit (512² import + reload) with 50 roads × 21 nodes (11 050 edges): 16.4-17.7 ms vs 15.7-16.7 ms without, so +~0.7 ms. Full-block `updateGrid` 11.4 vs 10.0 ms. Both are far below the 3 ms limit |
| **P3 DecalRoad creation** | **GO**. Governor unit = `insertNodeNoRegen` + `regenerate` | 100-node road: Node field before register 0.40 ms, **but edges are built later** (the next frame after 50 × 21-node roads: +~13 ms). `insertNodeNoRegen`+`regenerate` 0.44 ms *with* the 1 090 edges built in the call. `insertNode` per node 6.5 ms (15× slower). Delete 0.02-0.04 ms |
| **P4 DecalRoad move** | Recreate on rebase (or `setNodePosition` per node) | `setPosition` moves **all nodes** by the delta (object position = node 0), and re-projects and re-clips at once. It is translation only, and the rebase needs the ~0.09° rotation. `setNodePosition` ≈ 9 µs per node |
| **P5 MeshRoad deck** | **GO** as a bridge stop-gap | 11 nodes, 100 m × 12 m × 1.5 m: 2-3 ms (37 ms on first use with material load). Collision appears **one frame after** `be:reloadCollision()` (0.8 ms), as for TSStatic. Removal likewise. **No 50 m width clamp** in BeamNG (60 m kept) |
| **P6 River** | **GO** for rank 2, look needs tuning | Node-field creation 0.8 ms. `containsPoint`, `getSurfaceHeightAtPoint` and `getFlowAtPoint` work (flow = unit vector down the river). With editor defaults it renders as a flat dark-blue sheet. Frame cost within noise. Buoyancy not tested (no driving in) |
| P7 editor modules headless | As planned: no tool calls | `editor` table loaded but inactive, `editor.addRoadNode == nil`. `require` of `roadSpline/layerMgr`, `decalSpline/populate` and `roadArchitect/geometry` works. `initializeModules()` deliberately not called |
| **P8 decal instances** | **GO** | `addDecalTangent` 0.025 ms. 200 instances 3.8 ms including 200 ground rays. They render on the hidden terrain. `removeDecal` of 201 takes 0.14 ms |
| P9 navgraph → OSM export | Debug only | `tech_openStreetMapExporter.export(path)` on a 900-node custom graph: 176 ms, 899 nodes and 1 740 ways (one per edge). Coordinates are pseudo lat/lon around (45°, 45°), not geodetic |
| **P10 terrain paint corridor** | **GO** | 1 km × 10 m (2 500 cells): `setMaterialIdxWs` 0.99 ms (0.39 µs per cell) + `updateGridMaterials` 0.42 ms + `updateGrid` 1.23 ms = **2.6 ms** |
| **PB1 classes outside the editor** | - | `ForestBrushTool`, `TerrainEditor` and `worldEditorCppApi` are tables. **`core_forest` is nil in our level** (no Forest at load). `core_audioRibbon` and `core_audioForest` are loaded |
| **PF1 Forest item cost** (ROADMAP) | **GO**: the cheapest way to place props | `createObject('TSForestItemData')` **returns nil**. Use `createObject('ForestItemData')`. `createNewItem` **1.1 µs** (1k) / 2.2 µs (10k). `updateItem` 3.1 µs (1k) / 13.4 µs (10k). `removeItem` 1.5-2.0 µs. Items render at once with no rebuild call. 10k posts in view: within frame noise (Render +0.3 ms CPU) |
| PF1 collision | Trees collide, the kit post does not | ECA oak items collide (trunk and canopy hull). **The first `reloadCollision` after a new collidable shape type costs 163 ms** (one-off shape collision load). After that it is 0.8-1.1 ms with 201 oaks |
| **PF2 Forest transform / several Forests** | Rebase = `updateItem` or re-add | `Forest:setPosition` changes the object position, **not the items**. A second Forest renders fine |
| PF3 non-uniform scale | **GO** | A MatrixF with column 0 × 3 renders stretched, and the world box follows (0.097 → 0.292 m) |
| **PF5 imposter bake** | Use shapes with shipped imposters, or pre-bake at load | ECA trees (ship `.imposter.dds`): 200 at 400-800 m, no hitch. `/assets/.../trees_library/oak/tree_oak_large_a.dae` (no imposter): **one 209 ms frame**. The bake is written to `<user>/temp/assets/.../*.imposter.dds`, and the second time there is no hitch |
| PM1 TSStatic per piece | Forest instead for repeats | 0.165 ms each (jersey barrier), `setPosition` 3.8 µs, `reloadCollision` with 300 pieces 2.8 ms |
| **PA1 audio ribbon** | GO with a ribbon budget | Works from Lua data. `core_audioRibbon.onUpdate`: 3 µs per frame with no ribbon, **~115 µs** with one 62-node ribbon near the car, **~830 µs with 20 ribbons** (max 13 ms in the setup frame). That is not "a few µs": keep only the 2-3 nearest ribbons registered. Not listened to |
| PA2 audio forest | GO | `buildNodeCloudFromForest` for 300 oaks: 2.4 ms → 27 nodes. Enable and restore OK |
| PP1 prefab | GO, load the source level's materials first | Italy petrol station: 625 ms first spawn (loads Italy shapes), 6 children. `Prefab:setPosition` moves the children (0.02 ms). Ground slab without Italy materials: orange "no material". `removePrefab` 0.07 ms |
| PE1 particles | GO | `ParticleEmitterNode` (waterfall spray) 0.08 ms, renders. After a 100 m move the live particles fade out at the old spot. Frame cost within noise |
| BAT materials | GO | `wall.mat.json` loads in 11 ms, and `m_bricks_01_bat` then exists |
| **GroundCover on the hidden terrain** (ROADMAP) | **GO**. Grass on the physics block's layers | Renders on the **render-disabled** block. It **honours the layer map** (grass only on its layer's stripes) but **not re-imports by itself** (corrected later the same day): it reads a layer copy refreshed only when the block is drawn in view, see §4. 200k elements, radius 80: **+0.8-1.3 ms** frame (present wait +2.8 ms), noisy |
| **8-layer terrain import** (ROADMAP) | **GO**: 8 greyscale masks | 512² live block, medians of 4-5: 1 layer 16.5-17.8 ms, **8 greyscale masks 20.8-22.6 ms (+4-5 ms)**, 8 packed as 2 RGBA PNGs 35 ms (worse). `reloadCollision` unchanged (0.6-1.3 ms). 1024² not measured (the session runs 512²) |
| **PT1 groundmodel from layers** | **GO** | Wheel contact material changes with the layer (DIRT id 15 → 10 / 19 on two layers). A `setMaterialIdxWs` strip changed the wheels' contact material (to id 21) within 0.7 s with **no `reloadCollision`** |
| **Navgraph `map.reset` at 5k nodes** (ROADMAP) | **NO-GO per terrain commit.** OK for rebases or rare rebuilds | 5 041-node grid: **96-161 ms** (median ~127, n=8) with the UI dump, **53-178 ms** (median ~101, n=8) with `NavigationMapChanged` suppressed. 900 nodes: 11-32 ms. 20k: 383 / 818 ms. Mailbox 1.86 MB (lpack 7-11 ms). Player-vehicle import (`mapmgr.setMap`) 16 ms at 5k, 119 ms at 20k |
| **CEF fetch from 127.0.0.1** (ROADMAP, world-map P2) | **NO-GO**. Plan C (files in `/temp`) is **GO** | Despite the CSP, the game's `OnBeforeResourceLoad` **cancels every http/ws request to 127.0.0.1 and localhost** (any port, including MCP 29292). Log: `Resource cancel URL=...`. Nothing reached the test server. **`local://local/temp/beamngEarth/...` works** for `<img>` and `fetch` (2 ms, case-sensitive path). WebGL and WebGL2 are unavailable. Creating a blob Worker does not throw |
| **Stock asset borrowing** (ROADMAP) | **GO**, but load the material files **before** the first use of a shape | ECA oak and US signs load by path. Without their level's `main.materials.json` they show the orange placeholder. `loadJsonMaterialsFile` (trees_oak 2.7 ms, signs_usa 0.2 ms, buildings 5.3 ms) fixes shapes loaded **afterwards**. **Shapes already loaded keep the placeholder** (the shape resource caches its bindings). `leaves_strong` is referenced by the ECA oaks but defined nowhere |

Not run: origin precision at 15 km (P1/P2 of the origin work; it needs a long drive), the credits overlay review, the
MeshRoad drive-over and River buoyancy (they need someone at the wheel), listening to the audio probes, and the
editor's `initializeModules()`.

**What this changes in the plans:**
- **Roads (rank 1):** go ahead with raw DecalRoads on the hidden block. Re-clip is automatic and costs about 1 µs
  per edge, so terrain commits need no road work. Create chunks with `insertNodeNoRegen` + `regenerate` so the clip
  cost lands inside the governor slot (~0.45 ms per 100-node chunk).
- **Ground (v1.5 layers):** 8 layers cost +4-5 ms per 512² import. They give correct tyre groundmodels and
  GroundCover grass for free, and grass works on the invisible block. Ship 8 single-channel masks, not RGBA.
- **Vegetation / props:** Forest items at ~1-2 µs each, about 100× cheaper than TSStatic.
  - Rebase uses `updateItem` (3-13 µs) or a re-add (~2 µs plus remove ~2 µs). Re-adding is cheaper at 10k items.
  - Budget the one-off 163 ms collision load per new collidable tree type and the 209 ms imposter bake per type
    without an imposter. Do both behind the loading screen, e.g. spawn one hidden item per type at session start.
- **Navgraph:** one 5k-node `map.reset` is a 100-160 ms hitch.
  - Rebuild only on rebases (already a heavy frame) or on big window shifts, not per terrain commit.
  - Keep the window near 1-1.5k nodes (≈ 20-35 ms), and always suppress the UI dump.
- **World map UI:** HTTP from CEF to earthd is impossible.
  - earthd writes versioned tile files into `<user>/temp/beamngEarth/map/...` and the page loads them via `local://`.
  - Search and teleport requests go through GE Lua (the world-map doc's Plan C).
  - No WebGL, so use Leaflet with `<img>` tiles.

---

## 1. Setup and helpers

- `engine_probes.lua`: object tracking (`M.objs`, `M.forestItems`, kept in globals so that reloading the chunk never
  loses them), `M.clean()`, the frame sampler, and the terrain capture.
  - The terrain capture wraps `package.loaded['beamngEarth/terrain'].load` once, then a teleport to the same spot
    makes the mod import. That captured the live arguments
    `("/temp/beamngEarth/<session>/hm_12_0_0.png", 2, 4096, -512, -512, 1088)`.
  - `M.reimportLive()` replays them through the original function. This is an exact terrain commit, and it was used
    both as the "commit" being measured and as the restore. Baseline commit (512²): import 15.6-17.1 ms +
    `reloadCollision` 0.6-0.8 ms.
- Ground height for placement: `castRayStatic` from 300 m above (it hits the physics block. The mesh tiles have
  `collisionType='None'`).
- Screenshots: UI hidden (`toggle_ui`), the game's own orbit camera behind the car (facing -y), and a 1600 px copy in
  the probe folder.

## 2. Roads and water (roads doc §6)

### P1 DecalRoad on our ground
Method: three 21-node lines (10 m spacing, 1.5 m wide, 12-212 m ahead, 6 m apart):
- A: `overObjects=false`, nodes on the ground.
- B: `overObjects=true`, nodes +4.2 m (Road Architect's lift).
- C: `overObjects=false`, nodes +4.2 m, yellow double line.

Results [V]:
- All three render on the hidden block (`p1_decalroads_default.jpg`) with no visible z-fighting against the mesh tiles.
- In a later frame each has 221 edges. Middle-edge z minus physics ground: A -0.2 mm (max -1.0), B +0.006 mm,
  C -0.1 mm.
  - With `overObjects=false`, BeamNG snaps the *nodes* down to the terrain (C's node 0 z = ground, not +4.2).
  - With `overObjects=true` the nodes stay lifted and only the edges are raycast down. The ray hits the physics
    block, because our tiles do not collide.
- Creation with the Node field returns at once with 0 edges. The edges appear in a later frame (see P3). The first
  road with each new material took 14-28 ms (material load); B, reusing A's material, took 0.08 ms.
- Near tiles (24 within 300 m) set to `decalType='Visible Mesh'` + `regenerate()`: no change in edges or look
  (`p1_decalroads_tiles_visiblemesh.jpg`). Restored to `'None'`.
- Over a bridge (P5 deck +3 m): `overObjects=true` puts the line on the deck top (edge z = 1125.362 = deck),
  `false` leaves it on the ground under the deck (1122.375) (`p1b_decal_over_meshroad.jpg`).

Decision: rank 1 goes ahead with `overObjects=false`. Use `overObjects=true` with the +4.2 m lift only for
segments on bridge decks.

### P2 re-clip when the terrain changes
- 50 roads × 21 nodes × 0.4 m on a golden-angle spiral 30-165 m around the car (11 050 edges), created in 6.7 ms (in
  call).
- Live re-import + reload ×3: import 17.7 / 17.0 / 16.4 ms, reload 0.50-0.55 ms. Without roads: 15.7 / 16.0 / 16.7 ms,
  reload 0.57-0.64 ms. The commit frame's max was 25-27 ms in both cases.
- Full-block `tb:updateGrid(vec3(0,0,0), vec3(511,511,0))`: 11.4 ms with roads, 10.0 ms without.
- Bump test:
  - `setHeight(+1 m)` on 5×5 samples under road 1's middle, then `updateGrid` of the 7×7 box: 0.40 ms. The road's
    middle edge rose by exactly 1.000 m **in the same call**.
  - An explicit `regenerate()` afterwards changed nothing.
  - Re-importing the live block removed the bump, and the edge went back to its old height in the same call
    (import 19.0 ms).

Decision: the engine re-clips DecalRoads on every terrain update signal, cheaply (≈1 µs per edge in the
`updateGrid` case). The follow commit needs no road code, and no speed limit is needed for markings.

### P3 creation cost (20 roads per method, 100 nodes at 5 m, 0.5 m wide)
| Method | median ms | min-max | edges after the call | delete ms |
|---|---|---|---|---|
| `Node` field before `registerObject` | 0.40 | 0.37-0.67 | **0** (built later) | 0.015 |
| `registerObject` → `insertNodeNoRegen` ×100 → `regenerate()` | 0.44 | 0.34-0.52 | 1 090 | 0.019 |
| `registerObject` → `insertNode` ×100 | 6.51 | 6.30-7.01 | 1 090 | 0.035 |
| Node field, 21 nodes | 0.15 | 0.14-0.31 | 0 | - |

- The deferred build is real work. 50 × 21-node roads created in 4.1 ms (in call) gave a 24 ms frame against an
  11 ms baseline, i.e. ≈13 ms of deferred clipping.
- 100 roads with the line rays in the same call took 45 ms and a following 60 ms frame.

Governor: use `insertNodeNoRegen` + `regenerate`, where the cost is visible and bounded (~0.45 ms per 100-node
chunk). Then 3-4 chunks fit a 2 ms slot.

### P4 does a DecalRoad move?
- The object position is node 0 once the edges exist. `setPosition(pos + (5,0,0))` moved **every node** by +5 m in x
  and re-clipped at once (edge 0 followed).
- Node z values were re-projected (1122.00 → 1121.94 …), so the move is not rigid in z.
- `setNodePosition` on all 6 nodes: 0.05 ms.
- A rebase needs a rotation as well (0.09° at 10 km is 0.47 m over 300 m), so recreate from cached server data. At
  0.15-0.45 ms per chunk that is cheap.

### P5 MeshRoad deck
- Node field `"x y z width depth nx ny nz"` ×11, 10 m apart, deck top 3 m above ground, `m_asphalt_new_01` on all
  faces.
- Create 37 ms the first time (material), then 2-3 ms. `reloadCollision` 0.8-0.9 ms.
- `castRayStatic` at the deck centre: same frame as the reload → ground (1122.36). Next frame → **1125.36 (deck top)**.
- After `delete()` + reload, the same-frame ray still hit the deck. The next frame it hit the ground.
- Width 60: `getNodeWidth` = 60 and edge width 60.0 m. The T3D clamp of 50 m does not apply in BeamNG.
- `p5_meshroad_deck.jpg`. Driving over it was not tested.

### P6 River
- Created like `editor.createMesh` (ripple and wave defaults, `/core/art/water/*` textures), `fullReflect=false`,
  11 nodes, 20 m apart, 14 m wide, 3 m deep, 0.5 m above ground, 8 m left of the car's path.
- 0.78 ms, 24 segments.
- `containsPoint(mid)` = 4 (a segment index), far point -1. `getFlowAtPoint` = (0.006, -1.000, 0.003), down the
  river. `getSurfaceHeightAtPoint` works.
- Look: a flat dark-blue surface with no visible reflection or foam (`p6_river.jpg`). Water colour and fog fields
  need tuning (copy them from an official level's River).
- Frame A/B: 10.64 → 10.94 ms average (noise level).
- Not tested: buoyancy and current on a vehicle (needs a drive into it).

### P7 the editor's road modules without the editor
`editor` is a table and `editor_main` is loaded, but `editor.active=false` and `editor.addRoadNode=nil`: the editor API
is only installed when the editor initialises. `require('editor/roadSpline/layerMgr')`,
`'editor/decalSpline/populate'` and `'editor/tech/roadArchitect/geometry'` all load as tables (their math is
reusable). `extensions.editor_main.initializeModules()` was **not** called: it builds the whole editor state in the
user's session and cannot be undone. This does not change the recommendation to use the primitives.

### P8 decal instances
- `DecalData` (`crossing_white`, size 3) + `Engine.Render.DecalMgr.addDecalTangent(pos, up, dir, tpl, 3, -1, 0, 1)`:
  0.025 ms, uid returned.
- 200 more with a ground ray each: 3.8 ms (~19 µs each). They render on the hidden block (`p8_decal_instances.jpg`).
- `removeDecal` of all 201: 0.14 ms.
- `getDecalInstanceVecSize()` stays 201 with all slots nil. The vector does not shrink, which is harmless.

### P9 navgraph export
- `extensions.load('tech_openStreetMapExporter')` exposes `export(fileName)` only.
- On the P-nav 900-node grid it wrote `<fileName>.osm` with 899 nodes and 1 740 ways in 176 ms.
- The nodes carry `lat/lon` computed from the local x/y around (45°, 45°) (`compute2dCoords`), not real coordinates.
  It is useful as a topology dump. A diff against our source OSM needs the inverse of that scaling. Copy:
  `probes_2026-10-11/nav900.osm`. The extension was unloaded afterwards.
- Path note: `io.open('/temp/beamngEarth/...')` wrote into `<user>/temp/beamngearth/...`. Both case variants exist
  on disk (Linux). The VFS resolves case-insensitively to the existing lowercase folder, but `local://` URLs are
  case-sensitive (see CEF).

### P10 terrain paint corridor
- A 1 km × 10 m strip (500 × 5 samples at 2 m) along the block's x axis through the car, painted with index 0 (the
  only material, so the look is unchanged and the calls follow the same code path).
- `setMaterialIdxWs` ×2 500: 0.99 ms (0.39 µs per cell). `updateGridMaterials` over the box: 0.42 ms. `updateGrid`:
  1.23 ms.

## 3. Vegetation, props, ambience (buildings-veg doc §6)

### PB1
`ForestBrushTool`, `TerrainEditor`, `worldEditorCppApi`: tables. `core_forest`: **nil** (it only loads with a level
Forest), so `core_forest.getForestObject()` is not available in our level. Find our own Forest by name.
`core_audioRibbon` and `core_audioForest`: loaded.

### PF1 Forest item cost
Item data and Forest:
```lua
local db = createObject('ForestItemData')   -- 'TSForestItemData' returns nil in 0.39.4; the class is 'forestItemData'
db:setField('shapeFile', 0, shape); db.canSave = false; db:registerObject(name)
local f = createObject('Forest'); f.canSave = false; f:registerObject('bngProbeForest'); scenetree.MissionGroup:addObject(f)
local fd = f:getData()                       -- ForestData: createNewItem/updateItem/removeItem/getItems*/...
```
| Items | `createNewItem` µs each | `updateItem` µs each | `removeItem` µs each | `reloadCollision` after create |
|---|---|---|---|---|
| 1 000 (kit guardrail post) | **1.12** | 3.09 | 1.97 | 0.95 ms |
| 10 000 (same) | **2.16** | 13.4 | 1.48-1.68 | 1.94 ms |

- `ForestItem` methods: `getData getKey getMaterialNames getObjBox getPosition getRadius getScale getSize getTransform
  getUid getWorldBox isSelected setData setPosition setScale setSelected setTransform`.
- **`getTransform()` returns a const MatrixF** (`setPosition` on it throws). Build a fresh `MatrixF(true)` for
  `updateItem`.
- Items render in the same frame, and no `rebuildForestManagerInstanceData` is needed (`pf1_forest_1000_posts.jpg`,
  `pf1_forest_10000_posts.jpg`).
- Frame cost of 10 000 posts in view: avg 12.2 → 12.9 ms, Render 1.54 → 1.81 ms, shadows 1.66 → 2.07 ms CPU. The
  next idle window was 13.8 ms, so this is within the drift.
- Collision:
  - The kit post (`ak_root_guardrail_post_001`) has no collision mesh: a vertical ray through it hits the ground.
  - The ECA oak (`tree_oak_large_b`) collides. Horizontal rays at 1 m height hit the trunk 0.6 m from its axis, and a
    vertical ray hits a canopy hull ~14 m up.
  - The **first** `be:reloadCollision()` with oak items present took **163 ms**. The next two took 1.1 and 0.8 ms
    with 201 oaks.
  - So the cost is a one-off collision load per new shape, not per item.

### PF2 Forest transform and several Forests
- `f:setPosition(+10 m z)`: the Forest's position became (0, 0, 10). The items did **not** move (same positions, same
  `getItemsCircle` count, `pf2_forest_setposition_dz10.jpg`). Put back to (0, 0, 0).
- A second Forest with 100 items (0.95 ms) renders together with the first (`pf2b_second_forest.jpg`).
- So several Forests (e.g. one per streamed cell group) are possible, and the rebase must move items itself.

### PF3 non-uniform scale
- `m:setColumn(0, m:getColumn(0) * 3)` before `createNewItem`: the world box x went from 0.097 to 0.292 m (×3), y and
  z unchanged. The post renders visibly wider (`pf3_nonuniform_scale.jpg`).
- Collision of a stretched item was not checked (the post has none).

### PF5 imposter bake hitch
- 200 `tree_oak_large_b` (ECA level shape, `.imposter.dds` shipped) at 400-800 m: create 6.8 ms. Frame max 27 ms vs
  22 ms in the idle window: no bake (`pf5_oaks_400_800m.jpg`).
- 200 `/assets/meshes/foliage/trees_library/oak/tree_oak_large_a.dae` (no imposter in the zip): **one 209 ms frame**.
  The engine wrote `<user>/temp/assets/meshes/foliage/trees_library/oak/tree_oak_large_a.dae.imposter{,_normals}.dds`.
  Repeated after a cleanup: max frame 21 ms (cached). The cache file is left in place as the engine's own cache.

### Stock asset borrowing (ROADMAP)
| Step | Result |
|---|---|
| `TSStatic` `/levels/east_coast_usa/art/shapes/trees/trees_oak/tree_oak_large_a.dae`, no ECA materials | spawn 125 ms; mesh materials `Oak_bark_01, oak_leaves_01, Oak_branch_01/02, m_oak_leaves_distant, leaves_strong` all missing: orange placeholder (`borrow_before_materials.jpg`) |
| `TSStatic` `/levels/east_coast_usa/art/shapes/signs_usa/sign_stop.dae` | 37 ms; `eca_bld_metalbeams`, `signs_usa` missing: orange |
| `loadJsonMaterialsFile` of `trees/trees_oak`, `signs_usa`, `buildings` `main.materials.json` | 2.7, 0.2, 5.3 ms; all of the above now exist **except `leaves_strong`** (not defined in any materials file of the ECA zip or the assets zips) |
| The two objects already spawned | **still orange** (`borrow_after_load_same_objects.jpg`); a fresh TSStatic of the same `tree_oak_large_a` path is also still orange (the shape resource keeps its bindings) |
| New shapes after the load: `tree_oak_large_b`, `sign_yield` | **render correctly** (`borrow_after_materials.jpg`) |

- Rule: before the first use of a borrowed shape, load its level folder's `main.materials.json` (and
  `buildings/main.materials.json` for the sign posts).
- Material class names are lowercase in 0.39.4 (`getClassName()` = `'material'`).
- Stock ECA trees ship imposters, so prefer them over `/assets/.../trees_library` (PF5).

### PM1 TSStatic per piece
- 300 `art/shapes/objects/jerseybarrier_3m.dae`: **0.165 ms each**. `setPosition` 3.8 µs. `reloadCollision` with them
  2.8 ms. Deleting all 300 took 0.98 ms.
- Compared with PF1 that is ~100× the Forest item cost.

### PA1 audio ribbon
- `core_audioRibbon.updateRibbonData` + `setRibbons` + `recomputeMap` + `clearNearFarLists` with a 31 × 2-node ribbon
  (62 nodes) 20-35 m beside the car and 5 `event:>Ambient>Water>River` emitter hosts.
- Setup 0.04 ms (1 ribbon), 0.38 ms (20).
- `onUpdate` timed by a pcall wrapper:

| Ribbons | mean µs per frame | max µs |
|---|---|---|
| 0 | 3.2 | 37 |
| 1 (steady, after the first frames) | **115** | 253 |
| 1 (including setup frames) | 410 | 4 545 |
| 20 | **830** | 13 453 |

- Restored to the previous (empty) ribbon list. The SFX emitter count is back to the mod's own reverb only.
- **Cost is ~0.1 ms per frame per nearby ribbon.** Register only the nearest few, or rebuild the list as the car
  moves.

### PA2 audio forest
- `require('core/audioForest/audioForestCommon').buildNodeCloudFromForest(forest, {}, nil, {})` on 300 oaks within
  150 m: 2.4 ms → 27 nodes.
- `setNodeCloud` / `setMainEvent('event:>Ambient>Wind>Wind_Mediterranean_01')` / `setEnabled(true)` OK.
- Restored with `setEnabled(false)`, `clear()`, `setNodeCloud(nil)`.

### PP1 prefab
- `spawnPrefab('bngProbeFuel', 'levels/italy/art/prefabs/italy_small_petrolstation.prefab', pos, '0 0 1 0', '1 1 1')`:
  **625 ms** (first load of the Italy shapes), class `Prefab`, 6 children.
- `pf:setPosition(+20 m)`: 0.02 ms, and the whole station moved (`pp1_prefab_spawned.jpg` → `pp1_prefab_moved.jpg`).
- The ground slab renders orange: its material lives in Italy's level materials. Load those first, as for borrowed
  shapes.
- `removePrefab` 0.07 ms.

### PE1 particles
- `ParticleEmitterNode` with `emitter='BNGP_waterfallspray'`, `dataBlock='lightExampleEmitterNodeData1'`, 25 m ahead:
  0.08 ms, spray visible (`pe1_waterfall_spray.jpg`).
- Frame 12.36 → 12.47 ms (noise).
- `setPosition(+100 m x)`: emission moves, and existing particles stay and fade at the old spot
  (`pe1_after_move_100m.jpg`).

### BAT materials
`loadJsonMaterialsFile('/art/shapes/common/building_architect_modules/bat_materials/wall.mat.json')`: 11.1 ms.
`m_bricks_01_bat` absent before, present after.

## 4. Terrain layers and ground cover (ROADMAP)

### GroundCover on the hidden physics block
- Material `m_grass_dry_01` loaded from `/levels/west_coast_usa/art/groundcover/main.materials.json` (2.4 ms).
- Fields as WCUSA's `grass_dry_1`: radius 80, dissolve 50, gridSize 8, maxElements 200 000, UVs `0 0 1 0.5`, size
  0.5-0.9, `layer='beamngEarthDirt'` (our only layer). Registered in 32 ms (first) / 0.2-1.4 ms.
- **Grass renders around the car on the render-disabled block** (`gc1_hidden_terrain_base_layer.jpg`).
  `flushGroundCoverGrids()` costs ~0.003 ms (it only sets a flag).
- Frame A/B, 4 rounds × 3 s, toggling `hidden`: avg 16.26 vs 15.49 ms, p50 16.07 vs 14.80 ms, present wait 7.1 vs
  4.3 ms. That is **+0.8-1.3 ms** frame and ~+2.8 ms of GPU work hidden in the present wait at 4K.
  - A single 650k / radius 150 window was not slower than the 200k one, which shows the machine noise.
  - Repeat this on a quiet machine before choosing density presets.
- With the 8-layer block (next section):
  - A GroundCover on layer 4 (`bngProbeL4`) shows grass only on that 128 m stripe (`gc12_fresh_layer4_no_postapply.jpg`),
    and one on layer 3 only on its stripe (`gc6_layer3_postapply.jpg`).
  - Rendering the block on (`tbRender`) changes nothing for GroundCover.
- **Correction (2026-10-11, later in-game):** it does *not* follow re-imports by itself. GPU-placed
  GroundCover (useNewPlacementGpu, the stock setting) reads a layer copy that the block refreshes only in a frame where it is drawn and in view (the probe's
  stripes were refreshed by the `tbRender` step; the re-imports below brought back the same stripes and
  material names). A block never drawn reads as layer 0 everywhere. See ARCHITECTURE.md "Ground
  surfaces" for how the mod avoids it now (CPU placement, which reads the layers directly, plus a
  same-tick rebuild). Original observation:
- **It follows re-imports by itself:**
  - Re-importing the block with 1 layer made the layer-3 grass disappear (`gc10_after_import_1layer.jpg`).
  - Re-importing 8 layers brought it back with no flush and no `postApply` (`gc11_after_import_8layer_no_postapply.jpg`).
- Two oddities:
  - The very first layered GroundCover (L3, created right after the 8-layer import) showed nothing until
    `gc:postApply()` (`gc2` → `gc6`). A later fresh one on L4 worked at once. Not reproduced, but calling
    `postApply()` once after creation is a cheap guard (0.002 ms).
  - Grass stops ~6-8 m short of the L3/L4 boundary, which runs ~2 m right of the car. **[I]**: placement validity is
    checked per `gridSize` (8 m) cell or clump. Check this with a smaller `gridSize` before relying on sharp edges.

### 8-layer import cost
- Seven runtime `TerrainMaterial` clones of `beamngEarthDirt`: texture fields copied, `internalName` `bngProbeL1..7`,
  groundmodels GRASS, SAND, GRAVEL, ASPHALT, ROCK, MUD, ICE.
  - They join `TerrainMaterialSet` automatically.
  - They were deleted after the restore, leaving only `beamngEarthDirt` and `warning_material`.
- Masks: 512² greyscale PNGs in `<user>/temp/beamngEarth/probe11/`, 64-px vertical stripes (one per layer). Deleted
  afterwards.
- Each import uses the live heightmap at the live position, then `setPosition`, `setRenderEnabled(false)` and
  `reloadCollision`, interleaved:

| Variant | importMs (rounds) | median |
|---|---|---|
| 1 layer (all-white mask), run 1 | 17.4, 15.2, 18.2, 19.7 | 17.8 |
| 8 greyscale masks, run 1 | 22.0, 18.9, 24.5, 23.3 | 22.7 |
| 1 layer, run 2 | 20.7, 15.3, 16.5, 18.5, 16.0 | 16.5 |
| 8 masks packed in 2 RGBA PNGs (`channel` R/G/B/A), run 2 | 35.7, 33.6, 38.3, 33.4, 35.1 | 35.1 |
| 8 greyscale masks, run 2 | 19.9, 20.2, 23.8, 20.8, 23.0 | 20.8 |

- `getMaterialIdxWs` across the block returned 0..7 in stripe order (no flip). `reloadCollision` stayed 0.6-1.3 ms.
- **+4-5 ms per 512² commit for 8 layers.** Packing into RGBA is slower: it seems to decode each file once per
  channel **[I]**.
- 1024² was not measured. By pixel count, expect ≈ +15-20 ms there **[I]**.
- Restore: `M.reimportLive()` → 1 material, render off, index 0 under the car, wheel contact back to id 15.

### PT1 groundmodel under the wheels
Read in the vehicle VM (`wheels.wheels[*].contactMaterialID1/2`, sent back to GE):
- Before (DIRT everywhere): all four wheels 15.
- After the 8-layer import: left wheels 10, right wheels 19. The car straddles the ASPHALT/GRAVEL stripes.
- Painting a 66 m × 18 m patch with index 7 (ICE) through `setMaterialIdxWs` (297 cells, 0.63 ms) +
  `updateGridMaterials` (0.18 ms) + `updateGrid` (0.76 ms), **with no `reloadCollision`**: all wheels read 21 after
  0.7 s.
- So land-cover layers on the hidden block give real tyre physics, and small patches need no collision rebuild.

## 5. Navgraph `map.reset(customNodes)` at scale
- Grid of n × n nodes at 25 m around the car, node z from ground rays. Each edge is double-sided, `speedLimit` 13.9,
  `lanes '-+'`, radius 4.
- The level's graph was empty before (0 nodes). It was restored with `map.reset()` (0 nodes, 0.9-1.6 ms) and
  `mapmgr.requestMap()` for the car.

| Nodes | `map.reset` ms with UI dump | ms with `NavigationMapChanged` suppressed | mailbox | lpack encode | vehicle `mapmgr.setMap` |
|---|---|---|---|---|---|
| 900 | 32.3 | 10.7-19.4 | 325 KB | 1.0-2.5 ms | 4.7 ms |
| 5 041 | 96, 116, 117, 120, 133, 155, 161, 161 | 53, 89, 92, 99, 102, 125, 131, 178 | 1.86 MB | 7-11 ms | **16.3 ms** |
| 19 881 | 818 | 383 | 7.5 MB | 51-101 ms | 119 ms |

- Building the Lua node table took 4-35 ms at 900-5k nodes (it includes the ground rays), on top of these numbers.
- The UI dump is worth ~20-30 ms at 5k. Lua GC pressure adds variance: the heap was 123 MB after the 20k runs.
- Decision against the navgraph doc's 30 ms threshold: **a full 5k reset can't run on every terrain commit.**
  - Rebuild on rebases and on window shifts of ≥ ~1 km only, in a heavy slot, with the UI dump suppressed.
  - Use `map.updateDrivabilities` for small changes.
  - Or shrink the window to ~1-1.5k nodes (≈ 20-35 ms).
- Each AI vehicle pays the `setMap` import (16 ms at 5k) in its own VM.

## 6. CEF: fetch from 127.0.0.1 and files from `/temp`
- Scratch servers (outside the game, `cef_test_server.py`): 127.0.0.1:47699 with `Access-Control-Allow-Origin: *`,
  47698 without. The earthd port was not touched.
- From the main UI (`ui_eval`, origin `local://local`), every one of these failed in 1-45 ms with
  `TypeError: Failed to fetch`, image `error`, or a WebSocket timeout:
  - `fetch` with and without CORS, `mode:'no-cors'`, `localhost` instead of 127.0.0.1, POST to the game's own MCP
    server (29292), ports 80/8080/47613/47698/47699;
  - XHR, WebSocket and `<img>`.
- **No request reached the test server.**
- `beamng.log`: `E|OnBeforeResourceLoad| Resource cancel URL=http://127.0.0.1:47699/a.json` (and the same for the
  others). External URLs are refused by the CSP itself (`Connecting to 'https://example.com/' violates ... connect-src`).
- **Files in the user folder work.** `<img src="local://local/temp/beamngEarth/probe11/tile.png">` and the relative
  `/temp/beamngEarth/...` load (256×256, 2.5 ms). `fetch()` of the same file → 200 `image/png`, and of an `.osm` →
  369 844 bytes.
  - The URL path is **case-sensitive**: `/temp/beamngearth/...` failed for a file in `beamngEarth/`.
- World-map P1: `webgl2=false`, `webgl=false`. `new Worker(blobURL)` did not throw (`worker:'ok'`). Whether it runs
  under `worker-src 'none'` was not checked.
- Window globals used by the probe were deleted afterwards.

Decision: the world map uses the world-map doc's **Plan C**:
- earthd writes versioned tile images under `<user>/temp/beamngEarth/map/...`;
- the UI loads them through `local://` (cached 7 days by URL, so versioned names are required);
- search, teleport and readiness go through `bngApi.engineLua` → GE Lua → earthd TCP → `guihooks`;
- use Leaflet (no WebGL).

## 7. Session notes
- The probe chunk was reloaded mid-session once before the object lists were kept in globals. That left 5 TSStatics,
  a Forest and a datablock untracked for a few minutes. They were found by a scene scan and deleted by id. The final
  scan found only the mod's objects, the stock `arrow*` markers and the `tireTrackDecal` datablock.
- Final state:
  - No probe objects, no ribbons, empty navgraph, live block with 1 material and render off.
  - `beamngEarth_perfmon` unloaded (it was loaded for the probes), inputs zeroed, UI shown, car back on Mount Whitney.
  - Materials loaded by the probes stay until the next level load: ECA trees_oak / signs_usa / buildings, WCUSA
    groundcover, BAT wall, and Italy prefab shapes. They are never saved.
- The far field was rebuilt three times (teleports: to the test spot, again to the same spot for the terrain
  capture, back to Whitney), with no errors.

---

## Appendix A: files (`docs/research/probes_2026-10-11/`, git-ignored)
- `engine_probes.lua`: core (tracking, clean, frame sampler, terrain capture and re-import).
- `p_roads.lua`: P1-P10. `p_veg.lua`: PB1, PF1-PF5, borrowing, PM1, PP1, PE1, PA1, PA2, BAT.
  `p_terrain.lua`: GroundCover, 8 layers, PT1. `p_nav.lua`: navgraph.
- `run.py`: loader and step runner (`python3 run.py load | step NAME '{json}' | shot NAME`). `ab.py`: hidden-toggle
  frame A/B.
- `cef_fetch.js`, `cef_test_server.py`: the CEF probes.
- `results.jsonl`: every step's JSON output. `*.jpg`: the screenshots named above. `nav900.osm`: the exporter output.

## Appendix B: the essential Lua (also in the files above)

DecalRoad, both creation paths (P1-P3):
```lua
local r = createObject('DecalRoad'); r.canSave = false
r:setField('material', 0, 'm_line_white'); r:setField('improvedSpline', 0, 'true'); r:setField('drivability', 0, '-1')
r:setField('overObjects', 0, 'false'); r:setField('textureLength', 0, '5'); r:setField('renderPriority', 0, '10')
r:setField('distanceFade', 0, '400 50'); r:setField('decalBias', 0, '0.005')
-- (a) deferred edges:   for each node: r:setField('Node', 0, string.format('%.3f %.3f %.3f %.3f', x, y, z, w)) end; r:registerObject('')
-- (b) edges in the call: r:registerObject(''); for i, n in ipairs(nodes) do r:insertNodeNoRegen(vec3(n[1], n[2], n[3]), n[4], i - 1) end; r:regenerate()
scenetree.MissionGroup:addObject(r)
```

Bump test (P2), grid coordinates relative to the block's SW corner:
```lua
for i = -2, 2 do for j = -2, 2 do tb:setHeight(gx + i, gy + j, tb:getHeightGrid(gx + i, gy + j) + 1) end end
tb:updateGrid(vec3(gx - 3, gy - 3, 0), vec3(gx + 3, gy + 3, 0))
local e = road:getMiddleEdgePosition(mid)   -- already +1 m here
```

Forest (PF1/PF2), rebase by update:
```lua
local m = MatrixF(true); m:setFromEuler(vec3(0, 0, yaw)); m:setPosition(vec3(x, y, z))
local it = fd:createNewItem(db, m, 1)
local m2 = MatrixF(true); m2:setFromEuler(vec3(0, 0, yaw)); m2:setPosition(newPos)          -- getTransform() is const
it = fd:updateItem(it:getKey(), it:getPosition(), it:getData(), m2, it:getScale(), it:getUid())
fd:removeItem(it)
```

8-layer import (live heightmap, live position):
```lua
local mats, tex = {}, {}
for i = 1, 8 do
  mats[i] = names[i]   -- 'beamngEarthDirt', 'bngProbeL1'..'bngProbeL7'
  tex[i] = { path = '/temp/beamngEarth/probe11/layer8_' .. (i - 1) .. '.png', selected = false, material = names[i],
             materialId = i - 1, channel = 'R', channelId = 0 }
end
tb:importMaps(hmPath, 2.0, maxHeight, '', mats, tex, false)
tb:setPosition(vec3(x0, y0, zBase)); tb:setRenderEnabled(false); be:reloadCollision()
```

GroundCover on a layer of the hidden block:
```lua
loadJsonMaterialsFile('/levels/west_coast_usa/art/groundcover/main.materials.json')
local gc = createObject('GroundCover'); gc.canSave = false
gc:setField('material', 0, 'm_grass_dry_01'); gc:setField('radius', 0, '80'); gc:setField('dissolveRadius', 0, '50')
gc:setField('gridSize', 0, '8'); gc:setField('maxElements', 0, '200000'); gc:setField('shapesCastShadows', 0, 'false')
gc:setField('layer', 0, 'bngProbeL4'); gc:setField('probability', 0, '1'); gc:setField('billboardUVs', 0, '0 0 1 0.5')
gc:setField('sizeMin', 0, '0.5'); gc:setField('sizeMax', 0, '0.9')
gc:registerObject(''); scenetree.MissionGroup:addObject(gc); gc:postApply()
```

Wheel contact material (PT1), vehicle VM → GE:
```lua
veh:queueLuaCommand([[local t = {} for _, wd in pairs(wheels.wheels) do t[#t+1] = wd.name .. '=' .. tostring(wd.contactMaterialID1) end
  obj:queueGameEngineLua('BNGE_P11_CONTACT = ' .. string.format('%q', table.concat(t, ' ')))]])
```

Navgraph timing with the UI dump suppressed:
```lua
local orig = guihooks.trigger
guihooks.trigger = function(name, ...) if name == 'NavigationMapChanged' then return end return orig(name, ...) end
local t = hptimer(); local ok, err = pcall(map.reset, nodes); local ms = t:stop()
guihooks.trigger = orig
```
