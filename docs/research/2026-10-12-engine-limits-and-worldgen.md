# Step back: BeamNG's limits, and how to generate a world fast enough (2026-10-12)

The user, 2026-10-12: roads and decoration already cause problems before buildings exist; take a step back,
(1) benchmark BeamNG and its engine (object counts, spawn rates, what lags, terrain and texture resolution,
what to bake into the terrain and what to spawn, how to modify the engine), (2) survey ways of generating
an accurate, detailed world fast enough for any speed (rules, algorithms, AI, hybrids), compare several
methods, and consider changing the data before it reaches the game (roads painted into the imagery, the
terrain edited server-side). Use the terrain mesh as much as possible instead of spawning props.

Game: BeamNG.drive 0.39.4, Linux/Vulkan, RX 7900 XTX, 4K. Level `beamng_earth`, server not running (empty
scene, so the numbers are marginal costs over a 5.1 ms / ~195 fps floor). Harness:
`docs/research/probes_2026-10-12/` (`bench.lua`, `run.py`, `seq_b*.py`, `results.jsonl`), on top of the
2026-10-11 harness. Earlier numbers come from `2026-10-11-engine-probes.md` and
`2026-10-10-perf-and-architecture.md` (marked [11] / [10]).

---

## 0. Summary

**What limits us today is not the game but our server.**
- The client can stream far more than roads need.
- The Python road builder takes 0.3-0.6 s per 256 m tile when warm and **8-21 s when it meets a new map
  cell**. Of that, 25 of 30 profiled seconds were yesterday's street-width code, which converts every
  building ring to metres one ring at a time in pure Python.
- In the last session **every road tile from 22:55 on failed**. The grading step asked the DEM for one
  bounding box around all roads of a cell (53 x 82 z15 tiles for a long highway), the DEM refused, and
  the tiles were retried endlessly. That is a large part of "roads can't keep up" and "roads missing
  outside the city".

**What the engine is good at, measured:**

| Thing | Cost | Means |
|---|---|---|
| TSStatic, shape already loaded | 0.017 ms create; 20 000 in view +0.7 ms/frame | props by the thousand are fine (shared shapes) |
| TSStatic, new shape (our road / far tiles) | 1.3 / 3.1 ms each (cold), 0.02-0.07 ms warm | ~1 cold shape per 2 ms frame budget |
| Sustained streaming | 30-40 cold meshes/s: p99 13 ms; 100-150/s: p99 14-27 ms | roads need ~4/s at 130 mph, ~20/s at 600 mph: plenty of headroom |
| Forest items | 3 µs each; 300 000 in view +6.5 ms/frame | trees, posts, signs, street furniture |
| `be:reloadCollision()` | **full rebuild every time**: 1.8 ms (few objects), 13-17 ms with 5 000 collidable statics, 27 ms with a 4096² terrain | collision is the one thing that grows with the world: keep collidable objects few and near |
| Textures | 256-2048² DXT1: 2.5-6 ms each; 4096²: 11-23 ms + one 82 ms frame | 2048² per tile is the practical maximum to stream |
| TerrainBlock import | ~40 ns/sample: 512² 20 ms, 1024² 40 ms, 2048² 150-215 ms, 4096² 580-790 ms | a full re-import of a big block is a hitch; small blocks or incremental edits only |
| TerrainBlock local edit | 200x200 samples: setHeight 7.4 ms + updateGrid 12 ms (on a 4096² block) | roads can be cut into the terrain in strips, over several frames |
| TerrainBlock rendering | 4096² at 1 m: +0.5 ms/frame | the engine's terrain renderer is very cheap |
| DecalRoads | re-clip on every terrain change, ~37 µs each [11 + 2026-10-11 lag] | fine on a static terrain, bad on a moving physics block |
| Navgraph | 5 000 nodes: 100-160 ms per `map.reset` [11] | rebuild rarely, small window |

**The official maps put most of the world into the terrain**, and so can we. West Coast USA: a 2048² heightmap at 1 m, and one
**4096² colour image stretched over the whole 2 km map** (`baseColorBaseTex`, 0.5 m/px) under every
terrain layer, with tiled detail textures (asphalt, grass, sand...) blended in within ~30-100 m. A
prototype put Fells Point on our TerrainBlock the same way (DEM heights at 1 m, a 4096² NAIP photo as
base colour, an asphalt layer from Overture roads): the photo renders correctly from the air
(`probes_2026-10-12/proto_aerial2.jpg`). Two limits showed:
1. At runtime only the base image *path* can be swapped. The texture set's slot sizes (ours: base 512) and
   the detail arrays are fixed when the level loads, so the photo was downsampled and the detail layers
   did not show. A full test needs the level shipped with a 4096 base slot (a level reload).
2. A 0.5 m aerial photo is a far / mid-field colour only. At street level it is smeared
   (`proto_street2.jpg`); the near 100 m must come from generated materials (detail textures by layer,
   decals, meshes), exactly as WCUSA does.

**Recommendation (to discuss):** "terrain-first, server-baked".
- Do as much as possible on the server, *before* the data reaches the game: grade the heightmap for roads,
  paint road surfaces, markings and land cover into the texture, write material layer masks.
- The game then only imports terrain and textures, plus a small set of near-field meshes (curbs, sidewalks,
  bridges) and Forest items (trees, posts, signs).
- Make the server fast enough first (vectorise or move hot loops out of Python, cache baked tiles on disk,
  prefetch along the velocity vector, never block on missing detail: a coarser placeholder is always
  ready).
- Use AI offline / ahead of the player for data enrichment and terrain super-resolution, not at runtime in
  the game.

Sections 1-4 hold the numbers, the survey of methods and the option comparison.

---

## 1. Engine benchmarks (2026-10-12)

### 1.1 Object count (B1, `art/shapes/objects/jerseybarrier_3m.dae`, grid in view)
| Statics in view | create ms each (p50) | frame avg / p99 ms | render ms | reloadCollision ms |
|---|---|---|---|---|
| 0 (baseline) | - | 5.13 / 5.80 | 0.69 | - |
| 1 000 | 0.016 | 5.16 / 5.88 | 0.70 | 1.9 |
| 5 000 | 0.016 | 5.25 / 5.99 | 0.77 | 2.1 |
| 20 000 | 0.018 | 5.90 / 7.76 | 1.15 | 2.5 |
| 5 000, `Collision Mesh` | 0.018 | 5.45 / 6.46 | 0.79 | **13.4, then 17.1** |

Small shapes are instanced: 20 000 copies cost +0.7 ms. Collision is rebuilt from scratch on every
`reloadCollision` and scales with all collidable objects in the level.

### 1.2 Unique meshes, cold vs warm (B2, real tiles of the last session)
| Files | create ms p50 / mean / max (cold) | warm p50 | reloadCollision |
|---|---|---|---|
| 300 road meshes (median 356 tris) | 1.29 / 2.24 / 20.4 | 0.024 | 1.8 ms |
| 150 sidewalk meshes, `Visible Mesh` | 0.11 / 0.22 / 16.5 | 0.067 | 3.9-6.3 ms |
| 300 far tiles (2 304 tris) | 3.12 / 3.15 / 7.3 | 0.065 | 1.8 ms |

### 1.3 Sustained streaming (B6: every frame create k statics from cold files, delete beyond 64)
| Stream | objects/s | frame p50 / p95 / p99 / max ms |
|---|---|---|
| road, 0.25 per frame | 37 | 6.0 / 10.2 / 12.9 / 22 |
| road, 1 per frame | 114 | 8.2 / 12.1 / 13.9 / 54 |
| road, 2 per frame | 153 | 12.1 / 21.0 / 27.5 / 40 |
| far tiles, 0.25 per frame | 29 | 7.7 / 12.5 / 13.8 / 20 |
| sidewalks + collision every 0.5 s | 33 | 7.2 / 10.1 / 16.7 / 20 |

Demand at 130 mph (58 m/s) with 256 m road tiles in a 1.3 km band: ~1.1 new tiles/s, ~3-4 objects/s.
At 600 mph (270 m/s, flying) ~5 tiles/s, ~15-20 objects/s. The client is not the bottleneck.

### 1.4 Textures (B3, 4 materials + planes per call)
| Size (DXT1, mips) | create ms per object | worst frame in the 3 s after |
|---|---|---|
| 256² - 1024² | 2.2-3.2 (one 12 ms) | 27-29 ms (the 4 in one call) |
| 2048² | 4.1-5.9 | 28 ms |
| 4096² | 11-23 | **82 ms** |

### 1.5 Forest (B4, kit guardrail post, grid in view)
| Items | create µs each | frame avg / p99 ms | render ms |
|---|---|---|---|
| 10 000 | 3.0 | 6.5 / 7.3 | 0.93 |
| 100 000 | 3.1 | 9.5 / 10.5 | 2.75 |
| 300 000 | 2.6 | 11.9 / 13.1 | 4.75 |

The official maps carry 133k-663k Forest items [10].

### 1.6 Terrain (B5: the live block re-imported at other sizes; physics paused; restored)
| Samples @ square | Area | importMaps | reloadCollision |
|---|---|---|---|
| 512² @ 2 m | 1 km | 19.6 ms | 0.4 ms |
| 1024² @ 2 m | 2 km | 40.1 ms | 1.7 ms |
| 2048² @ 2 m | 4 km | 149 ms | 7.3 ms |
| 4096² @ 2 m | 8 km | 584 ms | 26.4 ms |
| 2048² @ 0.5 m | 1 km | 206 ms | 6.8 ms |
| 4096² @ 0.5 m | 2 km | 578 ms | 27.0 ms |
| 4096² @ 0.25 m | 1 km | 793 ms | 26.9 ms |
| 2048² @ 1 m, rendered | 2 km | 215 ms | 6.9 ms; frame 5.6 ms (+0.4) |
| 4096² @ 1 m, rendered | 4 km | 584 ms | 27.8 ms; frame 5.8 ms (+0.6) |

- Square sizes down to 0.25 m work.
- Local edit on the 4096² block:
  - 50 x 50 samples: setHeight 0.5 ms + updateGrid 5.1 ms.
  - 200 x 200 samples: 7.4 ms + 12.0 ms.
- `importMaps` with no layer mask does nothing and reports success (0.0 ms): always pass a mask.

### 1.7 Terrain base texture (prototype, §0)
- Material fields as WCUSA (`baseColorBaseTex` + `...BaseTexSize` = block size in metres; detail / macro
  per layer; `TerrainMaterialTextureSet` sizes fixed per level; "pixel dimensions MUST match" the set's
  sizes: the game's own terrain material editor).
- `TerrainBlock:updateMaterial(index, internalName)` applies a changed material at runtime. That is how
  the base image path was swapped.
- Not yet measured (needs the level with a 4096 base slot, i.e. a level reload):
  - the cost of swapping a 4096² base image;
  - detail layers on runtime materials;
  - an 8192² base.

### 1.8 Server (Python) road build, Fells Point, cached data
| Tile | build s | note |
|---|---|---|
| warm tiles | 0.29-0.60 | 140-230 chunks + 27-78 sidewalk runs |
| first tile / new cells | 7.9-20.9 | `roadwidth._walls`: building rings converted one by one (302k `geodetic_to_enu` calls) and a Python bucket index |

Plus the grading crash (§0). Both are ordinary fixes (vectorise; split the DEM request into bounded
boxes).

---

## 2. Engine modification

| Layer | What we can change | How | Risk |
|---|---|---|---|
| GE / vehicle Lua (`lua/ge`, `lua/vehicle`) | everything scripted: spawning, camera, UI, navgraph, extensions, the editor's tools | our mod overrides or extends files; already used | low; breaks on game updates only where we override |
| Shaders / materials | terrain and object materials, post FX | material JSON, shader overrides in the mod | medium |
| Native engine (C++ exe, closed) | behaviour inside functions: e.g. `tools/gcpatch` keeps grass across block moves | `LD_PRELOAD` library that patches bytes or hooks functions at startup; checks the exact build and stays off otherwise | high: per-version offsets, Linux only (Windows needs DLL injection), unsupported; a bad patch crashes the game, removing the launch option fixes it |

Native targets worth the risk, by value:
1. An incremental `reloadCollision` (add/remove one object instead of rebuilding all).
2. An asynchronous or double-buffered `TerrainBlock::importMaps`, so a 2-4 km block can recentre
   without a 150-600 ms hitch.
3. Larger texture-set slots at runtime.

Each needs reverse engineering first (as gcpatch did), so prototype them only if the Lua-level design
can't avoid them.

**Not being blocked.**
- Claude Code's auto mode refused to build and load native patches earlier. This is a permission
  setting, not a technical limit.
- The user can allow the specific commands in `.claude/settings.local.json`, e.g.
  `"permissions": {"allow": ["Bash(tools/gcpatch/build.sh:*)", "Bash(tools/restart_game.sh:*)"]}`.
- The user can also run them with `! <command>`.
- The game itself must be restarted with the `LD_PRELOAD` launch option (Steam > Properties), which only
  the user can set.

---

## 3. How others build the world (survey)

| Method | Who | How | Fits us? |
|---|---|---|---|
| Aerial photogrammetry meshes | Google Photorealistic 3D Tiles, Apple Flyover (C3 aircraft imagery), Cesium tilers | overlapping oblique aerial photos -> textured mesh, OGC 3D Tiles with LOD by geometric error; weeks-months of processing per city, big cities only | no: licensing (project rule: no Google/Cesium tiles), lighting baked in, not drivable / no semantics |
| ML reconstruction from 2D imagery + procedural geometry | MSFS (Blackshark.ai): 1.5 B buildings classified from satellite imagery (roof type, neighbourhood, shadows), then generated procedurally; whole world recomputed in ~72 h on Azure | AI offline, procedural at runtime; semantics allow relighting, windows, night lights | **yes, as the model**: AI enriches the data ahead of time, procedural rules generate in real time |
| Vector data baked into the terrain | Outerra (real Earth, 90 m DEM refined fractally to cm): roads are Catmull-Rom splines drawn into each terrain tile's **material map and height map**, blended at the edges, terrain cut/filled first, quad-tree indexed; "once the map is created it adds no extra performance cost" | GPU, per tile, at runtime | **yes**: the same idea as baking roads into our terrain tiles on the server |
| Virtual texturing with baked decals | Far Cry 4/5 (Adaptive Virtual Texture, 10 km world at 10 texels/cm; decals and splines rendered into the terrain texture once) | engine feature | partly: BeamNG has no virtual texture, but our server can bake the same into per-tile textures |
| Autogen from OSM + photo mesh | X-Plane / Ortho4XP: photo-textured mesh per tile, OSM roads / buildings / forests as overlays | offline per tile | yes for the overlay split, but offline |
| Runtime OSM -> 3D in the browser | Streets GL, OSM2World | vector tiles -> geometry at runtime (roads, buildings by Simple 3D Buildings) | yes as references for road / building geometry rules |
| Real-time Earth in a voxel game | Build The Earth's Terra++ (Minecraft): DEM + OSM roads streamed and generated per chunk on the fly | fast, simple per-chunk rules | shows that per-chunk rule-based generation keeps up when every rule is local |
| BeamNG offline generators | MapNG (1 m US lidar heightmaps, OSM buildings / trees, road masks), TerraDrive (OSM roads with lanes, curbs, bridges, intersections; 0.3-5 km areas) | export a level | no (offline, small areas), but they confirm the terrain + road-mask approach in BeamNG |
| Procedural city grammars | Esri CityEngine (CGA rules), "Complete Street" rules | parametric streets and buildings from rules | yes: rule sets for street cross-sections and buildings |
| Terrain super-resolution | DEM SR papers (feedback / attention networks, aerial-image-guided FCN "up to 10x", ELEVATE 2026 diffusion guided by RGB, SRTM 30 m -> WorldDEM 12 m datasets) | ML upsampling of DEMs, often guided by imagery | **yes, offline / on the server**: "DLSS for the Earth" for terrain outside lidar areas |
| Imagery super-resolution | Real-ESRGAN-type (one pass, ~200x faster than diffusion SR), latent diffusion SR (~0.2 s per 512² x4) | ML | maybe for far / mid textures, server-side and cached; never trust it for road geometry |
| Generative 3D cities | Sat2City (ICCV 2025), Skyfall-GS (Gaussian splats from satellite + diffusion), ABot-Earth (minutes per km²) | neural scenes | no for now: not drivable geometry, minutes per km², not in a Torque engine |

What carries over:
1. Everyone big separates **offline enrichment** (photogrammetry, ML classification) from **runtime
   generation** (procedural rules, LOD streaming).
2. Roads in terrain engines are **baked into the terrain** (height + material), not spawned as objects.
3. Streaming systems always have a cheap placeholder ready (Cesium's placeholder tiles) and never wait for
   detail.

---

## 4. Options for BeamNG.Earth

### 4.1 Ground and roads

| Option | Ground | Roads | Speed | Look | Risk |
|---|---|---|---|---|---|
| A. Today | mesh tiles with photo textures; hidden 512² physics block moved under the car | per-tile road / sidewalk / deck meshes from Python, collision on sidewalks / decks | server-bound (0.3-21 s per tile), collision reloads grow | good near, but many systems | known bugs, Python speed |
| **B. Terrain-first, server-baked** | near: a rendered TerrainBlock (e.g. 2048² @ 1 m = 2 km, or 0.5 m), photo base + generated land-cover layers + ground cover; far: mesh tiles as today | heightmap graded and shaped by the server (road crowns, ditches, kerb lines at 0.5 m); surfaces as material layers (asphalt / concrete / cobble groundmodels); markings painted into the near texture or as decal instances; meshes only for curbs, sidewalks, bridges within ~300 m | client cheap; server does raster work (vectorisable, cacheable) | official-map look (WCUSA's own method) | block recentre costs 150-600 ms (needs strips / incremental edits, or a native async import) |
| C. Hybrid of A and B | as B | roads as B, plus a few spline meshes where the terrain can't (bridges, tunnels, multi-level) | as B | best | most work |

The prototype showed B renders. Still open: the 4096 base slot with detail layers (level reload), and
how to recentre a large block without a hitch:
- update strips with `setHeight` + `updateGrid` over several frames;
- or two blocks prepared at load and swapped (an earlier crash came from *creating* a second block while
  a vehicle existed; preparing both at load time was never tested);
- or a native async import.

### 4.2 Generator

| Option | What runs where | Keeps up? | Quality |
|---|---|---|---|
| Rules in Python (today) | server, per tile | no (Python loops) | good where tuned |
| Rules, vectorised / native (Rust or C++ module, numpy throughout) | server, per tile, cached on disk, prefetched along the velocity | yes: rasters and meshes in ms | same rules, faster |
| Rules + offline AI enrichment | AI ahead of the player (or offline per region): land-cover / material segmentation from imagery, road widths and lanes, tree positions, roof types, DEM super-resolution where no lidar | yes (AI cost is outside the frame and cached) | closest to "handcrafted everywhere" |
| AI at runtime in the game | GPU next to the game | no on weaker PCs | unproven |
| Generative neural scenes | - | no | not drivable |

**Recommended: vectorised rules + offline AI enrichment + LOD placeholders.** Train custom models only
where rules can't read the data: for example materials from imagery (asphalt vs concrete vs grass at
1 m), and a terrain super-resolution model trained on US 3DEP lidar (1 m) vs 30 m DEM pairs, then used
outside the US. Our GPU can train such small models. In the US, use the 1 m lidar directly; no AI is
needed there.

### 4.3 What to bake vs spawn (decision table)

| Feature | Bake into terrain (height / layers / texture) | Spawn |
|---|---|---|
| Road surface, crown, ditches, shoulders | yes | - |
| Lane markings, crosswalks | near texture or decal instances | DecalRoads only on a static terrain |
| Curbs, raised sidewalks | kerb line in the heightmap at 0.5 m (approximate) | merged meshes within ~300 m (collision) |
| Bridges, overpasses, tunnels | - | meshes (decks) |
| Land cover (grass, dirt, sand, rock) | layers + photo base | GroundCover on the layers (grass) |
| Trees, posts, signs, hydrants | - | Forest items |
| Buildings | footprint ground and colour in the texture far away | meshes near (shared materials, instancing) |

---

## 5. Problems the user reported (2026-10-12), with what this study found
| Report | Found | Status |
|---|---|---|
| Edge warnings at high speed in Baltimore | road tiles fail (grading DEM box) and take 8-21 s on new cells (street widths), filling the server's workers | fix both; then re-test |
| Low-quality terrain outside the city | DEM top zoom 15 (~4 m at 39°N) | US: 3DEP 1 m lidar exists (found via the Planetary Computer, see the parked `wip/bridge-lidar` branch); elsewhere: super-resolution (§3) |
| "Timewarp" in natural environments | not reproduced in this study | to measure with perfmon while driving |
| LODs / rebase stopped while flying, ground not solid | not reproduced in this study | to measure; the physics block follows in 128 m steps and may fall behind at aircraft speeds |

## 6. Round 2: near-field detail on the terrain (2026-10-12, later)

The user, after round 1:
- only the terrain *near the player* needs high-resolution heights and textures (the far field stays as
  it is);
- test editing the terrain: smooth paved roads, add sidewalks, even buildings (and use them as the
  buildings' far LOD);
- rocky peaks, dunes and forest floors look smooth and blurry up close, so add model and texture detail
  everywhere;
- copy the resolution of the official maps;
- add a toggle that captures before / after images of the raw data vs ours.

Setup: a test level `bngearth_lab` in the user folder (`probes_2026-10-12/lab/make_lab.py`):
- one TerrainBlock, 2048² at 0.5 m (1 km);
- a texture set with a **4096 base slot** (the photo) and 1024 detail / macro slots;
- 8 layers from stock textures (grass, forest floor, rock, sand, asphalt, concrete, dirt, gravel).

Four 1 km scenes, each with heights from our DEM, 8 masks and a 4096² NAIP photo (`scenes.py`):
- Fells Point (urban);
- the Mount Whitney summit ridge;
- the Mesquite Flat dunes;
- Patapsco forest.

The rocks are a scatter of Johnson Valley's rock meshes (`rocks.py`). Captures: `compare.py`, the
before / after toggle (RAW = DEM + photo only, every detail and macro strength 0, no meshes; GENERATED =
edited heights + layers + meshes) -> `lab/cmp_<scene>_<view>.jpg`.

### 6.1 What the official maps do (`lab/survey_levels.py`, `levels_survey.json`)
| Level | Terrain | Base colour | Detail / macro tiles | Rock meshes | Forest items |
|---|---|---|---|---|---|
| West Coast USA | 2048² @ 1 m (2 km) | 4096² | 3-9 m / 20-50 m, detail to 50 m | 1 520 statics + 42k forest rocks | 133k |
| Johnson Valley | 4096² @ 0.75 m (3 km) | 4096² | 3 m / 20-100 m, detail to 50-80 m | **13 792 statics + 582k forest rocks** | 663k |
| Italy | 4096² @ 1 m (4 km) | 4096² | - / 15-160 m, detail to 25-50 m | 1 854 statics (rock faces) + 58k | 206k |
| Utah | 2048² @ 1 m | 2048² | 1 m / 5-80 m | 827 statics + 131k boulders | 160k |
| East Coast USA | 2048² @ 1 m | 2048² | - / 10-80 m | 481 + 34k | 187k |
| Jungle Rock Island | 2048² @ 1 m | 2048² | 2 m / 50-60 m | 1 773 + 17k | 75k |

Rock mesh resolution (full-detail level of detail, each with LOD chains and imposters):
- large rocks: 3.5-7.5k triangles;
- Italy's rock faces: 13-20k triangles;
- small scatter rocks: ~100 triangles.

**The official maps' sharp rock, cliffs and boulders are meshes on a fairly smooth 0.75-1 m heightmap**,
not heightmap detail.

### 6.2 Results
| Test | Result |
|---|---|
| Photo as terrain base colour at 4096² over 1 km | sharp from the air (~0.25 m/px), works with `updateMaterial` swaps |
| Detail textures by layer (asphalt, concrete, rock, sand, forest floor) | crisp at the wheels, as the official maps; masks come from our data |
| Roads graded + crowned, sidewalks +15 cm | road surfaces fine; at 0.5 m spacing a curb is a 0.5 m ramp, not a step: curbs stay meshes (or need 0.25 m: 4x the import cost) |
| Buildings extruded into the heightmap | good far LOD from the air (`lab_urban_aerial.jpg`); at street level streaky walls: near buildings must be meshes |
| Synthetic rock noise / ridge sharpening on the heightmap | worse: contour-line ripples and false walls (`shade_mountain.png`). Heightmap noise does not make rock |
| **Rock meshes scattered by slope** (115k Johnson Valley rocks in 1 km², small / tiny only within 150-300 m) | **the official-map look** (`cmp_mountain_slope.jpg`). Generation 1.6 s; create 209 ms (3 µs each); collision 56 ms; frame 5.2 vs 5.1 ms |
| Dunes: crest sharpening + wind waves + ripples | ripples and waves help near the ground, but the dunes themselves are missing from our DEM (z15, seams): their shape has to come from the imagery |
| Forest floor: mounds, roots, boulders | plausible micro-relief; the photo shows canopy, so the floor needs its own colour plus trees and undergrowth as meshes |
| Mapterhorn above z15 | **real data we were discarding**: z16 at Whitney, Alabama Hills, Fells Point, Patapsco; z17 in the Alps. Fine-scale curvature +25-80 % at z16, ~3x at z17. Our server caps at z15 |
| 3DEP lidar DTM (Planetary Computer) | none at Whitney or the dunes; patchy coverage |
| 2048² @ 0.5 m import (1 km) | 285-316 ms + collision 6.7 ms |
| 4 blocks of 1024² @ 0.5 m in the level | load fine with a vehicle present; import ~80 ms each; one-cell cracks at block edges (needs a 1-sample overlap) |
| **Collision of several TerrainBlocks** | **only the first block collides**; rays and vehicles pass through the others. Physics stays one block near the car |

### 6.3 Direction
The official recipe, generated from real data, with the high-resolution part only near the player:
1. **Real data first.**
   - Read Mapterhorn up to z16 / z17 where it exists.
   - Use lidar DTMs where available.
   - Imagery-guided shape synthesis only where the data is coarse (dunes, outside lidar areas): the
     place for a trained model.
2. **Near-field terrain at 0.5-1 m** with the photo as base colour and generated layer masks (roads,
   sidewalks, land cover, slope / rock), using the stock detail and macro textures. Roads graded and
   crowned into the heights; road markings painted into the near texture or as decals.
3. **Meshes for everything sharp**, as the official maps:
   - rocks, outcrops and cliff faces as Forest items scattered by slope, land cover and imagery;
   - curbs, sidewalks and near buildings as meshes;
   - trees and bushes as Forest items, grass as GroundCover.
   - All deterministic from world position, streamed in rings (tiny objects close, big ones farther).
4. **Far field unchanged in kind:**
   - mesh tiles with the photo;
   - buildings as heightmap extrusions or merged low-poly blocks;
   - far rocks as imposters (the stock shapes ship them).

Open problem, the one engineering question left: **moving the high-resolution near terrain without a
hitch.**
- Physics needs a single block.
- Re-importing 512 m at 0.5 m costs ~80 ms (about today's 512² @ 2 m commit is ~17-20 ms for the same
  sample count at 256 m).
- Candidates, to test next:
  - a 512² @ 0.5 m physics block (256 m, ~20 ms) following the car as today, with the near render as
    render-only blocks or mesh tiles;
  - incremental `setHeight` + `updateGrid` strips;
  - an engine patch for an asynchronous / double-buffered import.

Before / after toggle: in the lab today (`compare.py`). In the real pipeline it becomes a setting
("Generated detail: on / off") so any place can be captured both ways.

## 7. Moving the high-resolution near terrain without stutter (2026-10-12, test)

The user: "Sure, start the test." Levels `bngearth_lab` (one block) and `bngearth_lab4` (four blocks of
1024² @ 0.5 m defined in the level file); tools `probes_2026-10-12/lab/swap.lua`; physics paused
around every swap.

| Test | Result |
|---|---|
| Several blocks in the level, vehicle present | load fine, but **only the first block collides**. `enableCollision()` does not make another block collide. `disableCollision()` on a block **also stops it rendering**. Missed rays read the level's built-in ground plane at z = 0 |
| Fill a second block over several frames, then swap physics to it | **not possible** (only the first block collides). Deleting / creating blocks with a vehicle present was not tried (the user's rule) |
| `importMaps` 512² @ 0.5 m | 1 mask 14 ms, 8 masks 18 ms, + `reloadCollision` 5-6 ms |
| **`terrainFile` + `postApply` (binary .ter v9 written by the server)** | **256² @ 1 m: 6.6-7.4 ms; 512² @ 0.5 or 1 m: 10.4-14.7 ms** (21 ms the first time a file is read); 1024²: 26-38 ms; 2048²: 92 ms (importMaps: 300 ms). Needs a new file name each time (the same name is skipped) |
| Collision after a .ter swap or an `updateGrid` edit | follows **by the next frame with no `reloadCollision`** (saves 5-6 ms) |
| Worst frames while swapping every second | 256² @ 1 m: 11.6 ms; 512²: 19.7-20.3 ms (5 ms idle) |
| Local edits (`setHeight` + `updateGrid`) | 0.095 µs per sample + 2.5 ms per 16-row slice of a 1024-wide block (5 ms per slice in total). Fine for roads appearing or local changes between swaps; they cannot recentre a block (moving the block shifts every sample) |
| Lua reading server data | `ffi` in GE Lua is a stub (`ffi.cast` returns the string). `string.byte` decodes 1 M u16 in 1.6 ms |
| Base photo swap (`baseColorBaseTex` + `updateMaterial`, no reload) | works on the single-block level: 4096² **PNG ~23 ms** once (decode); **DDS DXT1 ~725 ms** (the terrain re-encodes it): give the terrain PNGs. On the 4-block level the photo never showed (unresolved, not needed: one block) |

**Design that follows:**
- One TerrainBlock, physics and near render, 512² at 0.5 m (256 m) or 1 m (512 m).
- The server writes a binary .ter (heights + layer indices) per step.
- The mod swaps it with `postApply` every ~64-128 m of travel: ~11 ms, no collision rebuild.
- The base photo is swapped as a PNG in a separate frame (~23 ms at 4096²; less at 2048²).
- Local edits go between swaps.
- That is the same hitch class as today's 512² @ 2 m commit (17-20 ms + 2-6 ms collision) at 2-4x the
  resolution.
- Beyond the block, the mesh tiles as today. The tiles under the block must give way (seam work).
- Rocks and props stream as Forest items (3 µs each, in chunks).
- What remains of the hitch (the .ter parse, the PNG decode) is main-thread engine work: the only further
  gain is a native patch that loads them on a worker thread.

Open tweaks noted by the user (later, during implementation):
- repeating texture patterns: anti-tiling (macro variation, two detail scales, random rotation by
  layer);
- region-matched rock colours;
- the dev-tools before / after toggle in the mod.

## Sources
- BeamNG: [TerrainBlock](https://documentation.beamng.com/modding/levels/level_classes/terrainblock/), [terrain files](https://documentation.beamng.com/modding/levels/level_formats/terrain/), [Creating urban environments](https://beamng.com/game/news/blog/creating-urban-environments), WCUSA `art/terrains/main.materials.json` (game files), `lua/ge/extensions/editor/terrainMaterialsEditor.lua` (game files)
- Outerra: [Roads (2009)](https://outerra.blogspot.com/2009/06/roads.html), [Integrating vector data - roads (2010)](https://outerra.blogspot.com/2010/05/integrating-vector-data-roads.html), [Road interpolator (2012)](https://outerra.blogspot.com/2012/04/road-interpolator.html)
- MSFS / Blackshark.ai: [TechCrunch](https://techcrunch.com/?p=2032098), [Blackshark](https://blackshark.ai/?p=1857), [Neumann interview](https://stevivor.com/features/interviews/jorg-neumann-microsoft-flight-simulator-2024-new-architecture)
- Google / Cesium: [Photorealistic 3D Tiles blog](https://cloud.google.com/blog/ja/products/maps-platform/create-immersive-3d-map-experiences-photorealistic-3d-tiles), [Cesium photogrammetry tiling](https://cesium.com/platform/cesium-ion/3d-tiling-pipeline/photogrammetry/), [Better low LODs](https://cesium.com/blog/2019/02/06/better-low-lods/)
- Apple: [Flyover](https://en.wikipedia.org/wiki/Flyover_(Apple_Maps))
- Far Cry: [Terrain rendering in Far Cry 5](https://gdcvault.com/play/1025480/Terrain-Rendering-in-Far-Cry), [Procedural world generation of Far Cry 5](https://gdcvault.com/play/1025557/Procedural-World-Generation-of-Far), [Adaptive virtual texture rendering in Far Cry 4](https://gdcvault.com/play/1021760/Adaptive-Virtual-Texture-Rendering-in)
- OSM renderers: [Streets GL](https://github.com/strandedkitty/streets-gl), [OSM2World](https://fosdem.org/schedule/event/BMMGNT-osm2world_3d_rendering_openstreetmap_data); [Terra++](https://github.com/BuildTheEarth/terraplusplus); X-Plane / [Ortho4XP guide](https://flyawaysimulation.com/ask/answers/create-install-ortho4xp-scenery-x-plane-12/)
- BeamNG generators: [MapNG](https://mapng.com), [TerraDrive article](https://boxthislap.org/beamng-drive-real-world-map-generator-terradrive/)
- Terrain / imagery SR: [ELEVATE (arXiv 2609.11886)](https://arxiv.org/pdf/2609.11886), [DSRFB (arXiv 2007.01940)](https://arxiv.org/pdf/2007.01940), [Argudo et al., aerial-guided FCN](https://diglib.eg.org/handle/10.1111/cgf13345), [AFN (ACCV 2020)](https://openaccess.thecvf.com/content/ACCV2020/papers/Kubade_AFN_Attentional_Feedback_Network_based_3D_Terrain_Super-Resolution_ACCV_2020_paper.pdf), [Remote-sensing SR survey](https://arxiv.org/pdf/2311.18082), [Latent diffusion SR](https://arxiv.org/pdf/2410.22830)
- Generative cities: [Sat2City / Skyfall-GS (arXiv 2510.15869)](https://arxiv.org/abs/2510.15869v1), [arXiv 2507.04403](https://arxiv.org/abs/2507.04403v1)
