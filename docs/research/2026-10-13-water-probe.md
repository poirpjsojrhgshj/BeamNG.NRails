# Water: first engine probe (2026-10-13)

The roadmap's water item (docs/ROADMAP.md "Water") has nothing built yet: lakes, rivers and the harbour are the aerial photo on flat ground (the DEM's water surface; Fells Point harbour reads -0.02 m in the block, land 1-3 m). The car drives on the harbour.

## What the stock levels use (game files)

- **East Coast USA:** its ocean is one `WaterPlane` ("Ocean", z 8.93).
  - `baseColor` 40 197 254.
  - `depthGradientTex` levels/east_coast_usa/art/water/depthcolor_ramp.dds.
  - `cubemap` cubemap_ocean_reflection.
  - foam, ripple and wave arrays.
- **West Coast USA and Italy:** `WaterBlock`s (boxes) for lakes and quarries, and `River` objects (node splines with width and depth) for rivers.

## In-game probe (Fells Point, runtime objects in our level)

- **`WaterPlane`** (created at runtime, `baseColor` and the stock ripple / foam / depth-ramp textures, z 2 m) **renders**.
  - It is see-through blue-green water with a sun glint over everything below 2 m (`water_2026-10-13/waterplane_2m_fells.jpg`).
  - No noticeable frame cost at that view (`RenderReflections` under 0.3 ms).
- **`WaterBlock`** (created at runtime) **does not render**.
  - `getWorldBox` is right: the position is the box's centre and the scale its size, so the surface is at position.z + scale.z / 2.
  - Nothing is drawn, even with the surface 2 m above the ground (`water_2026-10-13/waterblock_not_drawn.jpg`).
  - Tried: the `scale` field or `setScale`; `postApply`; stock grid settings (gridSize / gridElementSize 1); 200 m and 2.4 km boxes.
  - No log errors.
  - The stock definition (West Coast USA's `WaterBlock_1`, all its fields) spawned the editor's way (`Sim.deserializeObjectFromText(json, true, true)`), surface at 1 m: not drawn either.
  - The editor's own recipe (`editor/createObjectTool.lua` `buildWaterBlock`: its ripple / wave arrays, `/core/art/water/ripple_nm.normal.dds`, `depthcolor_ramp_b.color.png`, `foam_b.color.png`, `DefaultSkyCubemap`, then `reloadTextures()`): not drawn either.
  - So it is not our field values.
  - Loaded with the level (West Coast USA's `WaterBlock_1` in a temporary MissionGroup group of our level, game restarted): not drawn either. So it is not runtime creation: in our level (smallgrid-based, `levels/beamng_earth`) WaterBlocks are not drawn while a WaterPlane is. Next: compare the level's setup with a stock level that has water (LevelInfo / post effects / water-related globals).

### In gridmap_v2 (a stock level with one WaterBlock, a sunken pool)

- **The stock block** draws.
  - Moved with `setPosition` / `setPosRot` onto a neighbouring test panel, it was not seen.
  - Moved back, it drew again.
  - The panels are raised meshes above the terrain height `getTerrainHeight` reported, so the moved
    water sat under them: inconclusive.
- **Field diff with a runtime block:** the runtime default is `fullReflect` 1 (stock 0). But a runtime
  block with `fullReflect` 0 and its surface 1 m above Fells Point harbour (our level) was not drawn
  either.
- **So far:** WaterPlane yes, runtime WaterBlock never, in our level. The design should start from
  WaterPlanes (bounded by placement, see below) unless the WaterBlock is solved in an engine-level look.

## Why a plane is not enough

A `WaterPlane` is infinite and flat in the anchor frame, but the earth curves away below it: d^2 / 2R = 0.3 m at 2 km, 7.8 m at 10 km. Coastal land lower than that in the distance would be drawn under water. Lakes need their own levels.

So the plan stays the roadmap's: bounded water per area near the player (blocks or a plane only while the player is near sea-level water), the physics block carved below the surface, and the far tiles' water left to the photo.

## Plan (to agree with the user before building)

1. **Data:** Overture `base/water` polygons and river lines near the player (the map-data pipeline has the base theme). The surface level is the DEM at the shoreline (median inside the polygon near the player).
2. **Physics:**
   - Carve the physics block under water in the server's block build, like the road grading: a shore slope to a capped depth (e.g. 1:5 to 3 m; GEBCO / NOAA CUDEM later).
   - Bridges are already decks over the ground.
3. **Rendering:**
   - Near the player, water objects at the surface level, covering the water polygons in rectangles of a coarse grid, so land lower than the water outside the shore is not flooded.
   - Needs the WaterBlock fix, or a `WaterPlane` per sea-level area while the player is within ~2 km.
4. **Buoyancy:** the engine's water objects give it (to verify with a car).

## Second probe (2026-10-13 evening, with the user watching)

- **View distance is not the cause:** our LevelInfo `visibleDistance` (~147 km) set to gridmap_v2's 12.8 km made no difference.
- **The runtime WaterBlock is dead for physics too:** with a 30 m block around the parked car (surface 0.5 m above the ground), `obj:inWater` was false for all 950 nodes. That held whether the block was moved after registering or placed before.
- **A WaterPlane works for both:** 0.5 m above the ground, it drew (it flooded everything lower, `plane_test.jpg`) and 379 of 950 nodes were in water.
- **Not tested:** whether a runtime WaterBlock works in a stock level. The open question is whether WaterBlocks need something our level lacks or are broken at runtime everywhere.

## Third probe: River objects (2026-10-13 evening, Arizona desert, user's car)

- **Lead:** BeamNG's docs ([level classes: water](https://documentation.beamng.com/modding/levels/level_classes/water/)) list three water classes. Italy uses a `River` with two nodes and a 160 m width as a rectangle of water.
- **A runtime River draws.** Made with `Sim.deserializeObjectFromText(jsonEncode(def), true, true)` from a stock-style definition (`nodes`: {x, y, z, width, depth, nx, ny, nz}, core ripple / foam / depth-ramp textures), 40 m x 15 m. It shows as a dark sheet (no reflection cubemap set yet).
- **Physics: only after the vehicle is reset.** The River was around the car, 1.5 m deep:
  - before a reset, 0 of 950 nodes were in water (`be:reloadCollision()` did not help);
  - after `obj:requestReset(RESET_PHYSICS)`, 894 of 950 were.
  So a vehicle seems to take the water objects that exist when it spawns or resets. The runtime WaterPlane was seen without a reset.
- **A runtime WaterBlock stays dead** even after a reset: 0 of 950 nodes, not drawn.
- **So:** lakes and rivers can use River objects. Open question: a way to refresh a vehicle's water objects without a reset (a reset stops the car).

## Fourth probe: the WaterBlock cause found, and vehicles and new water (2026-10-13 night)

- **The cause:** a WaterBlock's surface is at its `position`. The engine caps the volume's top at the box centre (Torque3D `Engine/source/environment/waterBlock.cpp`, `isUnderwater`), even though `getWorldBox` shows the box extending scale.z/2 above. Every earlier test placed the position scale.z/2 *below* the wanted surface, so the water was underground. Found by a research pass over the BeamNG docs and the Torque3D source.
- **A block placed right works:** 60 x 60 x 10 m at Sandy Point, position.z = ground + 1.5 m around the parked car. It drew (`wb_fixed2.jpg`, with the editor's test ripples) and, after a same-place nudge, 906 of 950 nodes were in water.
- **Driving into new water:** a River created after the car had parked, then driven into at up to 10.8 m/s (throttle 0.35). Inside the river, 898-907 of 950 nodes were in water; the car slowed from 10.6 to 2.5 m/s; it dropped back on the way out. No reset was needed.
- **Water appearing around a parked car** is only seen after the car moves. `setPositionRotation` to its own place works (68 -> 907 of 950).
- **WaterPlane hidden** with `setHidden(true)`: 0 of 950 (no physics). With "transparent" fields (baseColor alpha 0, no foam / ripples / waves) it still draws a grey sheet with sun glint, and keeps its physics.
- **Curvature with the plane, from altitude:** 200 m above Sandy Point the plane covered Kent Island (8 km east, lifted to only 0.3 m above the plane) and the Eastern Shore (30-40 km, beyond the 30 km lift radius). The engine's own help text says the WaterPlane "is primarily designed to be viewed from ground level".
- Sources: the BeamNG water doc (above), the Torque3D environment sources, the Flood mod (github.com/daniel-w0/beamng-flood: moves an existing WaterPlane; hides Rivers / WaterBlocks with `isRenderEnabled = false`).

## Rivers: how the engine builds them, and the stock maps' values (2026-10-13 research + in-game)

From Torque3D's `Engine/source/environment/river.cpp` / `waterObject.cpp` / `waterV.hlsl` (BeamNG's
water derives from them) and the stock levels' files:
- **Mesh:** the nodes make a Catmull-Rom spline. Each span is cut into slices every `SegmentLength`
  (default 10). The near mesh is a grid of ceil(widest node / `SubdivideLength`) columns per segment.
  The far mesh is two triangles per segment. A segment within `LowLODDistance` (default 50) of the camera
  uses the near mesh, and the waves fade out at that distance.
  - In game, a 48 m creek's near mesh was not drawn at all with SubdivideLength 3 (the creek vanished up
    to the camera along a line that moved with it); it drew at 6 and 10. So `sea.lua` sets
    SubdivideLength = max(6, widest / 8).
- **Building after styling:** a River made from a definition and styled afterwards needs `reloadTextures()`
  (else "NO MATERIAL" and white bands) and `regenerate()` (else no near mesh).
- **Texture:** no UV channel. x is the offset across the river in metres; y is the distance along the
  centreline. So the outer bank of a bend is stretched and an inner edge with a radius under half the
  width folds over. Smooth centres and widths, and short slices.
- **Flow:** `flowMagnitudePhysics` only pushes physics objects. The visible flow is the ripple layers:
  coord = pos / rippleTexScale - rippleDir * t * rippleSpeed (tiles per second).
  - Stock rivers: rippleDir (0, 1) along the flow; Italy uses speeds 1 / 0.25 / 0.02 on tiles 2 / 5 / 20 m.
  - Stock flowMagnitudePhysics: 2-4 (waterfalls 5-8).
- **Stock values:**
  - Node spacing: 20-57 m (East Coast streams 2-12 m).
  - Depth: 5 m.
  - LowLODDistance: 80-150 where it is set.
  - SegmentLength: 2-5 on Jungle Rock Island.
  - Waves: small (0.002-0.5).
  - Lakes (WaterBlocks): ripple speeds 0.001-0.065 in three directions.
  - fullReflect is off everywhere.
- **Overlapping Rivers** drew by turns as the camera moved: the pieces now share a node, never a segment.
