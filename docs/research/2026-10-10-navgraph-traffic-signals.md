# AI navgraph, traffic, street signs and traffic lights in a runtime-streamed world

Research date 2026-10-10, BeamNG.drive 0.39.4 (Linux). Game install `G = ~/.local/share/Steam/steamapps/common/BeamNG.drive`.
All paths below are relative to `G/lua/` unless they start with `G/` or `levels/`.
Nothing was run in the game; every runtime number marked **[I]** is an inference and has a probe in section 9.
**[V]** = verified by reading the game files.

## 0. TL;DR

- The AI road graph ("navgraph", `ge/map.lua`) **can be built entirely from Lua without DecalRoads**: `map.reset(customMapNodes)`
  (`ge/map.lua:3960` exports `M.reset = loadMap`, the custom branch is `ge/map.lua:2514-2516`). It skips the whole DecalRoad
  junction/merge pipeline and only converts the graph to single-sided form, then builds the graphpath + two kd-trees, ray-casts a normal
  per node, sends the graph to every vehicle's Lua through a mailbox and fires `onNavgraphReloaded`. **[V]**
- It is **all or nothing**: no incremental add/remove of nodes, and every reset makes every AI vehicle re-import the full graph.
  The graph must therefore be a **window** around the player, rebuilt in steps. Official maps' graphs are about 4k–11k raw nodes
  (section 2.6), which is the scale a 2 × 2 km OSM window will have too. **[V]** counts / **[I]** cost.
- Five things go wrong if you call it naively (section 2.7): vehicles do not pick up the new graph by themselves; `gameplay_traffic` keeps
  a stale node table; the custom path does **not** compute speed limits; road rules (driving side, turn-on-red) come only from the
  level's `info.json`; and any stock `map.reset()` call (editor, flowgraph) wipes our graph. All five have small workarounds.
- **The physics island is the hard limit for traffic**: our drivable ground is a 2046 m TerrainBlock (`beamngEarth/follow.lua`), but
  stock traffic searches spawn points up to **1600 m** away (`gameplay/traffic.lua:402`). Outside the block, vehicles fall forever.
  Fix: clip the navgraph to the block (minus a margin) so the spawner cannot pick anything outside it, and add a guard that recycles AI
  vehicles near the block edge.
- Traffic signals (`core_trafficSignals`, "Traffic Signals V2") are fully scriptable at runtime: `newController / newSequence / newSignal
  / setupSignals(data, false, true)`. Signals bind to **navgraph edges** (`mapNodeSignals[n1][n2]`), resolved from the signal's position
  with `map.findClosestRoad`. The AI obeys three actions only: **1 = yellow, 2 = red, 3 = stop sign / flashing red**
  (`vehicle/ai.lua:4583-4605`). "yield" (4) and "slow" (5) exist in the enum but the AI ignores them. Give-way is instead modelled
  implicitly from geometry plus edge drivability (`vehicle/ai.lua:4475-4545`).
- Light heads are ordinary `TSStatic`s whose `instanceColor/1/2` fields are switched on or off; they are linked by a dynamic field
  `signalInstance = <instance name>`. Usable stock props that are always loaded live in `art/shapes/objects/`
  (`trafficlight_overhead1`, `trafficlight_city1`, `s_trafficlight_boom_sn`, `pole_light_*`, `lamp1`) and
  `art/shapes/garage_and_dealership/Clutter/italy_traf_sign_*` (stop, give way, speed 30–100, etc.). US-style signs exist only inside
  other levels' zips, whose materials are not loaded in our level (section 6).
- A floating-origin rebase means: rebuild the graph in the new frame with **stable node names**, rebuild the signals, and push the new map to
  every vehicle in the same frame as the vehicle move. Stable names keep AI routes and signal keys valid (section 2.8).

---

## 1. Where things live (verified file map)

| Piece | File | Notes |
|---|---|---|
| Navgraph builder (GE) | `ge/map.lua` (4013 lines) | global `map`; `loadMap(customMapNodes)` at 2497 |
| Graph container + pathfinding | `common/graphpath.lua` | `newGraphpath`, `bidiEdge` 218, `export` 133, `import` 147 |
| Vehicle-side map copy | `vehicle/mapmgr.lua` | `setMap` 45, `requestMap` 68, `setSignals` 84, `updateSignals` 88 |
| AI driver | `vehicle/ai.lua` (6236 lines) | `setMode` 5762, `trafficPlan` 4816, intersections 4428-4810 |
| Traffic manager | `ge/extensions/gameplay/traffic.lua` (1695) | spawn/respawn/pooling |
| Traffic helpers | `ge/extensions/gameplay/traffic/{trafficUtils,vehicle,roadTracking,baseRole}.lua` | spawn-point search, active radius |
| Traffic signals | `ge/extensions/core/trafficSignals.lua` (1724) | instances, controllers, sequences |
| Signal definitions | `G/settings/trafficSignals.json` | states + controller types |
| Level signals | `levels/<lvl>/signals.json` (+ optional `signalControllerDefinitions.json`) | auto-loaded on mission start |
| Road rules | `levels/<lvl>/info.json` → `roadRules` | read on every navgraph build, `ge/map.lua:148-155` |

---

## 2. The navgraph

### 2.1 Sources in a normal level [V]
`linkMap()` (`ge/map.lua:2141`) calls `loadJsonDecalMap()` (`ge/map.lua:567`), which reads three sources:
1. `BeamNGWaypoint` scene objects become nodes with `manual = 1` (`:571-580`).
2. Every `DecalRoad` with `drivability > 0` (`:589`). Fields read: `drivability`, `hiddenInNavi`, `gatedRoad`/`type`
   (gated → `'private'`), `oneWay`, `speedLimit` (≤0 → auto), `flipDirection`, `autoJunction` (false → `noMerge`), `autoLanes`,
   `lanesLeft`, `lanesRight`, `useSubdivisions`, `looped` (`:593-640`). Nodes come from either the control points (pos +
   `getNodeWidth/2` = radius) or the subdivided edges, simplified with a radial-distance filter plus Ramer-Douglas-Peucker. The
   tolerance is `d² > max(0.005·r², 0.04 m²)` (`:675`), so a curve keeps a node wherever the chord error exceeds ~0.2 m (or 7 % of the radius).
3. `levels/<lvl>/map.json` "segments" that link manual waypoints (`:787-915`).

Then `createSpeedLimits(true)` (`:204`), `mergeOverlappingNodes`, `optimizeNodes`, `resolveTJunctions`, `resolveXJunctions`,
`mergeNodesToLines`, `processPrivateRoads` and `convertToSingleSided` (`:2141-2290`). The T/X junction solver is how DecalRoads that merely
*touch* become connected; the custom path does not run it (2.4).

### 2.2 Data model [V]
- **Node**: `map.nodes[name] = {pos = vec3, radius = m (half road width), links = {[otherName] = edge}, normal = vec3 (computed), endNode?, noMerge?, manual?}`.
- **Edge** (one table shared by both endpoints in the double-sided form): `drivability` (0..1, also the cost divisor),
  `oneWay` (bool), `lanes` (string, e.g. `"--++"`: one char per lane, `+` = along inNode→outNode, `-` = against), `speedLimit`
  (**m/s**), `inNode`, `outNode`, `inPos`, `outPos`, `inRadius`, `outRadius` (per-edge end positions/radii, which allow lane-accurate junctions),
  `type` (`'private'` or nil), `hiddenInNavi`, `gatedRoad`, `noMerge`.
- Lanes from radius when missing: `numOfLanesFromRadius = max(1, floor(min(r1,r2)·2/3.61 + 0.5))` (`:542`). A two-way road gets half that
  per direction, ordered by `rules.rightHandDrive` (`:548-565`). **`rightHandDrive = true` means left-hand traffic** (UK/Japan): the
  lane string is then `+…-…` instead of `-…+…`.
- Auto speed limit (only in the DecalRoad path): `19.444 m/s · clamp(((r·(oneWay?2:1) + 5)/8)·drivability, 0.4, 2)`, rounded down to
  {30,50,60,80,100,120} km/h (`:204-231`).

### 2.3 Build steps common to both paths (`loadMap`, `ge/map.lua:2497-2687`) [V]
1. `M.objects = {}; M.objectNames = {}` (2502). **The vehicle tracking table is wiped**; it refills from the vehicles on the next frame.
2. `setRoadRules()`: `rules = {rightHandDrive=false, turnOnRed=false}` merged with `info.json.roadRules` of the *current level* (148-155).
3. For every node: `be:getTerrainDrivability(pos, radius)` (2569, ≤0 → 1).
4. For every node: `gp:setPointPositionRadius`, a node kd-tree preload, and for each single-sided link `gp:bidiEdge(...)` with
   `len = dist / clamp((drivN1+drivN2)/2·edge.drivability) + (gatedRoad and 10000 or 0)`, plus an edge kd-tree preload of the
   edge's 2-D box (2581-2603).
5. For every node: `n.normal = surfaceNormal(pos, radius/2)`, which costs **3 × `be:getSurfaceHeightBelow`** (506-540, 2608).
6. `gp:generateEdgeIndex()`, `edgeKdTree:build()`, `nodeKdTree:build()`, `maxRadius = min(15, max node radius)`.
7. (DecalRoad path only) snap of isolated manual waypoints → `nodeAliases`.
8. `createTrafficExclusionArea`, `buildSerial += 1`.
9. `be:sendToMailbox("mapData", lpack.encodeBinWorkBuffer({nodeAliases, maxRadius, graphData = gp:export(edgeCount), edgeKdTree = edgeKdTree:export(), rules}))` (2670-2678).
   The whole graph is serialized every time.
10. `guihooks.trigger("NavigationMapChanged", map)` sends **the whole map to the UI** (2683), then `extensions.hook("onNavgraphReloaded")` (2686).
    Listeners: `core_trafficSignals` (rebuilds all signals), `freeroam_bigMapMode`, `editor_aiViz`.

### 2.4 Runtime injection: `map.reset(customMapNodes)` [V]
With a table argument, `loadMap` sets `map.nodes = customMapNodes` and only runs `convertToSingleSided()` (2116-2134), which keeps, for
each node, only the links where `edge.inNode == otherNode`. It **skips** `createSpeedLimits`, every merge or junction step, private-road
processing and waypoint aliasing. So the caller must supply:

- string node names (graphpath compares names with `>` in `export`, `common/graphpath.lua:138`, so never mix numbers and strings);
- a **double-sided** link table: `A.links[B] == B.links[A] == edge`, with `inNode`/`outNode` set (one-way direction = in→out);
- `inPos/outPos/inRadius/outRadius` on every edge (the kd-tree preload at 2602 reads `data.inPos.x` and `min(data.inRadius, data.outRadius)` unconditionally);
- a numeric `speedLimit` in m/s on every edge: `gameplay/traffic.lua:460` does `link.speedLimit - 8.333` (nil → Lua error);
  ai.lua treats nil as "no limit" (`vehicle/ai.lua:1758-1759, 2383`);
- `lanes` (ai.lua invents lanes from the radius if missing, `vehicle/ai.lua:1146-1166`, but we know better from OSM).

Real junctions must share a node name. Nothing will snap two nearby ends together for you.
Precedent: Road Architect clears the graph with `map.reset({})` (`ge/extensions/editor/tech/roadArchitect/roads.lua:1367`).

### 2.5 How vehicles get the graph [V]
- Each vehicle VM keeps its **own full copy**: `mapmgr.setMap(serial)` decodes the `mapData` mailbox, `graphpath.newGraphpath():import(...)` and
  `kdTreeBox2D:import(...)` (`vehicle/mapmgr.lua:45-66`).
- `setMap` only runs when GE calls it: `map.request(objId, serial)` (`ge/map.lua:3720-3731`), which also sends the current signal dictionary
  via `mapmgr.setSignals(serialize(core_trafficSignals.getMapNodeSignals()))`. `map.request` only runs when the vehicle calls
  `mapmgr.requestMap()`, and **ai.lua does that only inside `setMode()`** (`vehicle/ai.lua:5782`).
  **Result: after `map.reset`, running AI vehicles keep driving on the old graph until something calls `requestMap`/`setMap` for them.**
  No stock code broadcasts it (searched every caller: only flowgraph `vehicleModule.lua:113` and `controller/tech/roadsSensor.lua:345`).
- When `mapmgr.mapData` changes, the AI drops its route (`vehicle/ai.lua:5137-5139`: `if mapData ~= mapmgr.mapData then currentRoute = nil`)
  and replans from `mapmgr.findBestRoad(ego.pos, ego.dirVec)` (`vehicle/ai.lua:4870`).
- `map.updateDrivabilities({nA,nB,driv,...})` (`ge/map.lua:3733-3758`) is the only incremental update. It changes edge drivability (and so
  path cost) without a rebuild and tells tracked vehicles. It can "close" edges cheaply, but cannot add or move them.

### 2.6 Size and cost
Verified counts of drivable DecalRoads in official levels (script `scratchpad/research2/scripts/count_roads.py`, run on the level zips):

| Level | Drivable DecalRoads | Control nodes (before RDP and merges) | Centreline km | Signal instances (`signals.json`) |
|---|---|---|---|---|
| east_coast_usa | 407 | 3 820 | 57.9 | 69 (5 controllers, 3 sequences) |
| west_coast_usa | 1 354 | 8 685 | 148.3 | 335 (9 controllers, 7 sequences) |
| italy | 480 | 10 803 | 146.2 | 57 (1 controller, 0 sequences: stop signs only) |

- Stock levels therefore run **~4k–11k nodes for 60–150 km of road**, which is the size the AI, traffic and kd-trees are tuned for. **[V]**
- A 2 × 2 km OSM window in a dense US grid holds roughly 60–100 km of drivable ways. After simplification (densified only on curves)
  that is ≈2–6k nodes, i.e. official-map scale. Rural windows are 10× smaller. **[I]**
- Per-node GE cost in `map.reset`: 1 terrain-drivability query + 3 surface ray-casts + table/kd work. At an estimated 5–20 µs
  per node, 5k nodes ≈ 25–100 ms on the main thread, plus lpack encoding and the UI trigger **[I]** (probe P1). Each vehicle's import
  runs inside that vehicle's Lua VM **[I: assumed to be the vehicle thread]**. There is no explicit size limit in the code; the practical
  limits are the main-thread hitch and the per-vehicle memory (one copy per AI vehicle).
- `guihooks.trigger("NavigationMapChanged", map)` serialises the whole map to the CEF UI on every reset **[V]**. For large graphs
  this may be the dominant cost **[I]** (measure in P1; a hook-side workaround is in 8.6).

### 2.7 Pitfalls with a custom graph (all [V] unless marked)
1. **Vehicles do not reload by themselves** (2.5). After every reset do `be:queueAllObjectLua('mapmgr.requestMap()')`. That is two
   hops (vehicle → GE `map.request` → vehicle `setMap` + `setSignals`), about 1–2 frames **[I]**.
2. **Stale node table in `gameplay_traffic`**: `onTrafficStarted` caches `mapNodes = map.getMap().nodes` (`gameplay/traffic.lua:1467`). `loadMap`
   first **clears** the old table (2506-2509) and then *replaces* it with ours (2515). Traffic then indexes an empty table
   (`traffic.lua:1252`: `mapNodes[n1].radius` → error every 5 s; `:458` on respawn). Only `forceTeleport` refreshes it (`:499`).
   Workaround: keep one persistent table `P`. Before the reset, hold the reference; after it, copy the new nodes into `P` and set
   `map.getMap().nodes = P` (same node objects, so gp, kd-trees and signals stay consistent).
3. **No auto speed limits** in the custom path. The server must always send `speedLimit` (m/s).
4. **Road rules** are re-read from `levels/<current level>/info.json` on every reset (`ge/map.lua:148-155`) and sent to the vehicles with the
   graph. For a planet with left- and right-hand traffic, wrap the reset:
   `local o = path.getPathLevelInfo; path.getPathLevelInfo = function() return '/temp/beamngEarth/rules.json' end; pcall(map.reset, nodes); path.getPathLevelInfo = o`
   (`path.getPathLevelInfo` is a plain global function, `common/utils.lua:1077`). `rules.json` = `{"roadRules":{"rightHandDrive":true,"turnOnRed":false}}`.
   `trafficUtils.getLevelInfo` (country for vehicle selection, `gameplay/traffic/trafficUtils.lua:26-43`) uses the same function and could
   be steered the same way.
5. **Foreign resets wipe our graph**: `map.reset()` without arguments rebuilds from DecalRoads. Our level has none, so the graph comes back
   empty. Callers include `main.lua:782/1027` (`assureLoad` on mission start), `editor/trafficSignalsEditor.lua:322`,
   `flowgraph/modules/prefabModule.lua:29,196,217,332`, `tech/sensors.lua:1291`, `gameplay/drag/core.lua:178` and the rally
   traffic-exclusion code. Handle `onNavgraphReloaded` in our extension: if the graph is not ours (keep a flag set only during our own
   call), re-inject on the next frame.
6. `M.objects` is reset (pitfall-free, one frame without `map.objects[id]`; `gameplay_traffic` guards it at `traffic/vehicle.lua:683`).
7. `nodeAliases` is `{}` for custom graphs, and `maxRadius` is capped at 15 m. A road wider than 30 m has to be split into one-way edges anyway.

### 2.8 Behaviour across our floating-origin rebase
Everything the graph stores is in absolute frame coordinates: node positions, edge in/out positions, kd-tree boxes, normals, signal
positions, the vehicles' copies, and the AI's current plan (`plan[i].pos` vectors). A rebase moves all vehicles by ~10 km (+ ~0.09°)
with `setClusterPosRelRot` (`beamngEarth/rebase.lua:62-76`). Positions would be wrong without a rebuild, so:

- **Rebuild the graph in the new frame** from server data (the server already re-emits everything in new-anchor ENU). Do the
  `map.reset` in the same GE frame as phase 1 (vehicle move) or phase 2 of the rebase, then `requestMap` for all vehicles.
- **Keep node names stable across frames and windows**, e.g. `n<osmNodeId>` for OSM nodes that survive simplification, and
  `w<wayId>_<k>` for densified points. Then the AI's path (a list of node names), the signal dictionary keys (`[n1][n2]`) and the
  groundMarkers route nodes stay meaningful. The AI only has to re-snap positions, which it does on its own once `mapmgr.mapData` changes (2.5).
- Between the vehicle move and the vehicles' `setMap` (1–2 frames **[I]**), an AI steers toward old-frame plan points 10 km away.
  At 60 fps that is a ~30 ms steering blip **[I]**. To remove it, call `mapmgr.setMap(<serial>)` + `setSignals` directly in the same
  `queueAllObjectLua` batch as the move instead of the two-hop `requestMap` (serial = `map.getMap().buildSerial`). Probe P5.
- Signals: clear them before the reset (`core_trafficSignals.resetSignals()`), otherwise `onNavgraphReloaded → runSignals` re-resolves the
  *old-frame* instance positions against the new graph and logs "Map node could not be set" (`core/trafficSignals.lua:597-612`). Rebuild
  them from server data afterwards. Our own signal and sign props move with our other scene objects (or are recreated).
- `gameplay_traffic` focus and vehicle state come from `map.objects`, which refills from the moved vehicles. Inactive pooled vehicles are
  moved too (`getAllVehicles`), and they are respawned on activation anyway.

---

## 3. Traffic system (`gameplay_traffic`) [V]

- **Start**: `gameplay_traffic.setupTraffic(amount, options)` (`traffic.lua:967`) or the pause-menu path `setupTrafficWaitForUi`. Default
  amount = setting `trafficAmount`, which defaults to `max(1, min(physical cores, free GB, 8) - 1)` (`ge/ge_utils.lua:872-887`). Extra
  pooled (inactive) vehicles come from `trafficExtraVehicles/trafficExtraAmount`. Vehicles are spawned by `core_multiSpawn.spawnGroup`
  in mode `traffic`, at `findSafeSpawnPoint(nil, nil, 0, 500, 0)` (`core/multiSpawn.lua:546`), i.e. **0–500 m from the camera on the graph**.
  The spawn waits for each vehicle's `onVehicleMapmgrUpdate` hook, with an 8 s watchdog (`traffic.lua:871, 1290-1299`). **Start traffic
  only after our first graph exists**, otherwise `setMap` never succeeds and the loading screen waits for the watchdog.
- **Vehicle selection**: `createTrafficGroup` (`trafficUtils.lua:58-83`) filters by type car/truck, by the level's `country` (from `info.json`,
  known: usa, germany, italy, france, japan) and optionally by region. `trafficSimpleVehicles` uses the cheap `proptraffic` models.
- **Pooling**: `core_vehicleActivePooling` keeps at most `activeAmount` vehicles simulated. Inactive vehicles cost memory but no physics
  (`traffic.lua:568-621`).
- **Per-frame work**: `doTraffic` updates all vehicles but runs respawn logic for **one vehicle per frame** (`traffic.lua:1219-1235`) and
  samples road density every 5 s (`:1243-1275`). Each traffic vehicle ray-casts to the focus every tick for visibility
  (`traffic/vehicle.lua:608`, `castRayStatic` at `trafficUtils.lua:223`), so occlusion uses **static collision** only (our invisible TerrainBlock
  counts; render-only buildings and tiles do not, so cars may pop in behind them).
- **Despawn / recycle**: `activeRadius = lerp(160, 80, spawnValue)`, plus `extraRadius = focusSpeed + max(0, (1 - v/5)·80) + 150·[ahead]`
  (`traffic/vehicle.lua:404-420`). Once `focusDist > finalRadius` the vehicle fades out and is respawned (`:422-454`). Typical recycle
  distance at speed: **~250–450 m**.
- **Respawn point**: `getNextSpawnPoint` (`traffic.lua:369-467`): `minDist = clamp(50+50/spawnValue, 50, 400) + addedDist`
  (`addedDist ≤ 120 + dynamicSpawnDist ≤ 1000`), `maxDist = clamp(minDist·distCoef, 200, 1600)` (`:400-402`). The search runs along a
  random route ahead (`findSpawnPointOnRoute`), then radially, then on a line. Spawn roads are filtered by drivability (randomised
  min 0.5–1.0, narrow roads are penalised: `trafficUtils.lua:177-211`), by `type ~= 'private'` and by `radius ≥ 1.2`. Points within a
  junction node's radius are excluded. `finalizeSpawnPoint` snaps the car to a lane: `laneWidth = 3.05` (2.2 if the road is narrower
  than 6.1 m), lane count = `floor(width/laneWidth)` (`trafficUtils.lua:296-381`).
- **Headlights and tunnels** use `core_terrain.getTerrainHeight` (`traffic/vehicle.lua:619-633`). This works with our physics-only terrain;
  under bridges or overpasses the ray fallback is used.

**Consequence for BeamNG.Earth (critical)**: our only collidable ground is the TerrainBlock, 1024 samples × 2 m = **2046 m square**,
re-centred so the player stays ≥ ~320–600 m from any edge (`beamngEarth/follow.lua:5-31`). Stock traffic can choose spawn points up
to 1600 m away and keeps vehicles active up to ~450 m away, so both can lie outside the block, where vehicles fall forever. Two guards are needed:
1. **Clip the navgraph to the current block minus ~60 m.** The spawner only ever picks graph points, so it cannot spawn outside.
2. **An edge guard** in our extension (one vehicle per frame is enough): any traffic vehicle within ~80 m of the block edge is sent to
   `gameplay_traffic.forceTeleport(id)` (`traffic.lua:489`). At graph dead-ends the AI replans or turns around (`trafficPlan`, 4.3).

---

## 4. AI driving (`vehicle/ai.lua`) [V]

### 4.1 Traffic mode
`ai.setMode('traffic')` (`:5762-5815`) → `resetMapAndRoute()`, `mapmgr.requestMap()`, `setSpeedMode('legal')`, `driveInLane('on')`,
traction model 1, `setSpeedProfileMode('Back')`, and "fast physics" (self-collision and aero mode 2, `opt.enableFastPhysicsforTraffic` defaults to true, `:113`).
`avoidCars` is on.

### 4.2 Speed and lanes
- `legal` speed mode uses the edge `speedLimit` (m/s) of the path edges (`:1758, 2383, 2531, 2960`), combined with the curvature
  speed profile. A `math.huge` limit means curvature only.
- Lane keeping uses the `lanes` string and the node radii: lane width = 2·radius / #lanes, direction from `+`/`-` relative to inNode
  (`getEdgeLaneConfig`, `:1146-1166`). The driving side comes from `mapmgr.rules.rightHandDrive` (`:1157, 1340, 3562, 4407`).
  **So `radius` must be half the full carriageway width, and divided roads must be two one-way edges** (OSM already models them that way).
- Plan resolution: the AI follows graph nodes, so curves need nodes. Use map.lua's RDP rule (chord error ≤ ~0.2 m), and also cap edges
  at ~100 m or ≤ 1 m vertical deviation, because the closest-road search weights height (`wZ = 1.85`, `vehicle/mapmgr.lua:207-214`).

### 4.3 Route choice
`trafficPlan` (`:4816`) extends a pseudo-random forward path with `mapData:getPathTWithState(...)`, 80–100 m ahead. When the AI is
blocked it tries the reverse direction (two-way roads only) and honks. There is no destination. At a dead end it replans; a graph
clipped at the window edge behaves like a dead end, which is acceptable because vehicles are recycled long before.

### 4.4 Intersections (how it "reads" them)
Path scan (`:4433-4560`) for each upcoming path edge `(nid1, nid2)`:
- **Controlled**: if `signalsData[nid1][nid2]` exists, `tSi.pos` = the signal's position = the **stop point**, `tSi.action` = its action.
  For stop signs (action 3) `getControlledBranches` (`:4247-4300`) walks ≤ 20 m to the junction node (degree > 2) and finds the other
  stop-controlled legs, which enables the 4-way-stop logic (`is4stops4legs`, `:4610-4730`).
- **Uncontrolled**: at any node of degree > 2, the AI **gives way** if its turn is between 45° and 135° (`abs(dot) < 0.707`), **or if its
  incoming edge has lower drivability than another edge at that node** (`:4479-4489`). T-junction right-of-way follows the "natural
  continuation" heuristic (`roadNaturalContinuation`, `:1169`). The stop point is `radius + 2` m before the node (`:4507`).
  → **Road hierarchy at unsignalled junctions = edge drivability.** Encode OSM priority (motorway > trunk > primary > … > service)
  as small drivability steps (e.g. 1.0 / 0.98 / 0.96 …). Spawn and path cost then barely change, but minor roads yield.
- **Stopping** (`:4565-4800`): actions 2 and 3 stop at the plan node nearest `tSi.pos`. Action 1 (yellow) stops only if the car can brake
  in time. Action 3 waits `parameters.trafficWaitTime` and checks cross traffic. Action 2 waits for the light, except turn-on-red
  (right turn in right-hand traffic) when `rules.turnOnRed` (`:4765-4771`).
- **Actions ignored by the AI**: 4 (yield) and 5 (slow). `ai.lua` never compares them (searched every `.action` use).

---

## 5. Traffic signals (`core_trafficSignals`) [V]

### 5.1 Model
- **SignalInstance** (`core/trafficSignals.lua:114-676`): `{id, name, pos, dir, group?, controllerId, sequenceId, startDisabled}`. `pos` is
  the logical **stop point**. It is resolved to a navgraph edge with `getBestRoad` → `map.findClosestRoad(pos)`, oriented with `dir`
  (one-way edges keep their direction, `:286-322`).
- **SignalController** (`:679-800`): `{id, name, type, isSimple, defaultIndex, states = {{state, duration}}}`, built from
  `settings/trafficSignals.json` types: `lightsBasic` (green 15 / yellow 4 / red 1), `lightsBasicEU` (red+yellow first),
  `lightsBasicProtectedGreen`, `lightsRedFlashing`, `lightsYellowFlashing`, `signStop`, `signSlow`. State → action:
  `greenTrafficLight go(0)`, `yellowTrafficLight alert(1)`, `redTrafficLight / redYellowTrafficLight stop(2)`,
  `basicStop / redFlashingTrafficLight briefStop(3)`, `basicSlow slow(5)`. `autoSetTimings(speed, intersectionLength)` sets
  green `clamp(0.7v + 0.6L, 10, 40)` and yellow `clamp(1 + (v-4.167)/3.27, 3, 7)` (`:740-753`).
- **SignalSequence** (`:803-1175`): `phases = {{controllerIds = {...}, startTime?}}`, run on one global timer with a min-heap queue.
  An intersection = one sequence with two phases (NS/EW). Each phase's controller is shared by all instances of that approach group.
- **Level file** `levels/<lvl>/signals.json` = `{instances, controllers, sequences}`, auto-loaded on mission start (`:1476-1513, 1627`).
  Example (east_coast_usa): `{"controllerId":4,"dir":[-0.0025,-0.9999,0.0166],"group":"group_9_10_11","id":9,"name":"trafficLight1","pos":[728.6,-76.8,52.1],"sequenceId":7}`,
  controller `{"id":4,"name":"green15_EW","type":"lightsBasic","defaultIndex":3,"states":[{"duration":15,"state":"greenTrafficLight"},{"duration":4,"state":"yellowTrafficLight"},{"duration":1.25,"state":"redTrafficLight"}]}`,
  sequence `{"id":7,"name":"trafficLights_10_15","phases":[{"controllerIds":[1]},{"controllerIds":[4]}],"startTime":0}`.
  Stop signs are just instances with a `signStop` controller and no sequence (italy: 57 instances, 0 sequences).
- **Props**: any `TSStatic` with the dynamic field `signalInstance = "<instance name>"` (`:51-64`). Lights are switched by
  `obj:setField('instanceColor'|'instanceColor1'|'instanceColor2', '0', '1 1 1 1' or '0 0 0 1')` (`:146-159`). The material does the rest:
  `art/shapes/objects/main.materials.json` → `instanced_trafficlight` with `instanceDiffuse/instanceEmissive = true` and a colour palette map.
  Real level example (east_coast_usa `main/.../items.level.json`): `{"class":"TSStatic","annotation":"TRAFFIC_SIGNALS","dynamic":true,"shapeName":"/levels/east_coast_usa/art/shapes/buildings/eca_traffic_high_ew_right.dae","signalInstance":"trafficLight1",...}`.
  The prop position is independent of the instance position (prop at the roadside or overhead, instance at the stop line).
  `SignalInstance:createSignalObject(shape, pos, rot)` (`:207-264`) creates such a prop (collision None, dynamic) in group `AutoTrafficSignals`.
- **To the AI**: `buildMapNodeSignals` (`:1314-1331`) makes `mapNodeSignals[n1][n2] = {{instance, pos, state, action}}`. Vehicles receive it
  via `map.request` → `mapmgr.setSignals`. State changes go out as `trafficSignalUpdates` mailbox deltas `{n1, n2, idx, action}`
  (`:1601`), which `mapmgr.sendTracking` applies each frame (`vehicle/mapmgr.lua:101-110`).

### 5.2 Runtime API (no files needed)
```lua
local ts = core_trafficSignals             -- extension name; load with extensions.load('core_trafficSignals') if absent
ts.resetSignals()                           -- clears everything (setupSignals(nil))
local cNS = ts.newController({name='J1_NS'}); cNS:applyDefinition('lightsBasic')   -- or 'lightsBasicEU', 'signStop'
local cEW = ts.newController({name='J1_EW'}); cEW:applyDefinition('lightsBasic')
local seq = ts.newSequence({name='J1', phases={{controllerIds={cNS.id}}, {controllerIds={cEW.id}}}})
local s1  = ts.newSignal({name='J1_a', pos=vec3(x,y,z), dir=vec3(dx,dy,0), controllerId=cNS.id, sequenceId=seq.id})
s1:createSignalObject('art/shapes/objects/trafficlight_city1.dae', propPos, propQuat)  -- props must exist BEFORE setupSignals
ts.setupSignals({instances={s1,...}, controllers={cNS,cEW}, sequences={seq}}, false, true)  -- autoRun: needs the navgraph already loaded
-- vehicles whose map serial is unchanged get no signals from map.request, so push them explicitly:
be:queueAllObjectLua('mapmgr.setSignals(' .. serialize(ts.getMapNodeSignals()) .. ')')
```
Caveats [V]: `SignalSequence:include()` calls `resetSignals()` and wipes everything (`:1135-1137`), so never call it. `setupSignals` scans **all**
TSStatics for `signalInstance` (`getObjectsByClass('TSStatic')`, `:54`); with ~900 far tiles that is fine but not free. `map.request`
only pushes signals when the vehicle's map serial differs (`ge/map.lua:3721`). After a signals-only rebuild (same graph),
push `mapmgr.setSignals(serialize(ts.getMapNodeSignals()))` to all vehicles explicitly.

### 5.3 Placement rules derived from the AI code
- The instance `pos` must resolve (closest-edge search) to the **approach edge**. Put it on the centreline 6–10 m before the junction node.
  Have the server insert a node there if the approach edge is long, so a crossing edge cannot win the closest-edge search.
- For stop signs, the junction node (degree > 2) must be within 20 m along the graph of the signal's edge
  (`getControlledBranches` `searchDist = 20`).
- `dir` = travel direction of the controlled approach.
- `turnOnRed` comes from road rules (section 2.7 item 4). `lightsBasicEU` for Europe, `lightsBasic` for North America.

---

## 6. Stock prop shapes we can place [V paths; materials note]

Materials under `/art/` are loaded globally at client start (`ge/client/init.lua:177` `loadDirRec("art/")`); level materials only for the
loaded level (`ge/server/server.lua:200` scans `levelDir`). So **`art/...` shapes render correctly in our level**. Shapes inside other
levels' zips need (a) the zip to be mounted while our level is loaded and (b) that level's `*.materials.json` loaded with
`loadJsonMaterialsFile`. Both are unverified (probe P7).

Always safe (in `G/content/art_shapes.zip`):
| Use | Shape (`.dae`, a `.cdae` sits next to each) |
|---|---|
| Traffic light, overhead mast | `art/shapes/objects/trafficlight_overhead1.dae` (default of `createSignalObject`) |
| Traffic light, pole/city | `art/shapes/objects/trafficlight_city1.dae` |
| Traffic light, boom | `art/shapes/objects/s_trafficlight_boom_sn.dae` |
| Street lights | `art/shapes/objects/pole_light_single.dae`, `pole_light_double.dae`, `pole_light_bridge.dae`, `lamp1.dae`, `s_standinglight_01.dae`, `s_bollard_big_lightpole.dae`; `art/shapes/garage_and_dealership/Clutter/eca_lamppost.dae` |
| Utility poles | `art/shapes/common/power_lines_procedural/electric_pole_wood_old_01/02`, `metal_pole_indus_old_01` |
| EU signs (Vienna-convention style) | `art/shapes/garage_and_dealership/Clutter/italy_traf_sign_stop`, `_give_way`, `_speed_30/50/60/80/90/100`, `_speed_adv_60/100(_end)`, `_noentry`, `_one_way`, `_priorityroad(_end)`, `_roundabout`, `_crossroad`, `_dead_end`, `_no_overtaking(_end)`, `_zebra`, `_parking`, `_no_parking`, `_keep_left/right`, `_turn_*`, `_warn_*` (bends, humps, slippery, steep, ...) |
| Bus stops | `art/shapes/objects/s_busstop_{ecu,it,jri,utah,wcu,wcu_01..04}.dae`, `s_sign_busstop.dae` |
| Construction | `art/shapes/objects/construction_sign_big_a/b/c.DAE` |

Level-only (need P7 first):
- **US signs (east_coast_usa)**: `levels/east_coast_usa/art/shapes/signs_usa/sign_stop`, `sign_yield`, `sign_speedlimit_40/50`, `sign_4way`, `sign_2way`,
  `sign_stop_ahead`, `sign_yield_ahead`, curve and junction warnings. Traffic heads: `levels/east_coast_usa/art/shapes/buildings/eca_traffic_{ns,ew}_{left,right}`,
  `eca_traffic_high_{ns,ew}_right`, `eca_traffic_pedestrian_{ns,ew}`.
- **US (Utah)**: `levels/Utah/art/shapes/ut_roadsigns/ut_30..80_speed_limit`, `ut_STOP`, `ut_stop_ahead`, `ut_do_not_enter`, `ut_dead_end`, ...
- **west_coast_usa**: `levels/west_coast_usa/art/shapes/objects/sign_stop`, `sign_yield`, `sign_speed25`, `sign_speed5`, `sign_twoway`, `trafficlight1a..2c`,
  `trafficlight_city2`, `trafficlight_overhead2`, `pole_traffic1`, `pole_light_signal1`, `boom_trafficlight_small`, `lamp4`.
- **Italy**: `levels/italy/art/shapes/buildings/italy_traffic_light_{ns,ew}_pd_{left,right}` plus the same `italy_traf_sign_*` set.

Street lighting: a `TSStatic` emits no light. Real lamps in official maps are prefabs (east_coast_usa has 888 Prefab objects and only 1 PointLight at top level) **[I: lights live inside the prefabs]**.
Use emissive heads everywhere and real `PointLight`/`SpotLight` objects only for the nearest ~20–40 lamps at night **[I]**.

---

## 7. OSM → navgraph / signals mapping (server side)

| OSM | Navgraph / signals |
|---|---|
| `highway=motorway/trunk/primary/secondary/tertiary/unclassified/residential/living_street/service/track`, `*_link` | edge; drivability 1.0/0.98/0.96/0.94/0.92/0.9/0.9/0.85/0.6/0.3 (`service` 0.6 stays above traffic's 0.5 spawn floor only sometimes; `track` never spawns). The order sets give-way priority (4.4) |
| `oneway=yes/-1/reversible`, implied for motorway and `junction=roundabout` | `oneWay = true`, inNode→outNode in the legal direction (`-1` flips) |
| `lanes`, `lanes:forward`, `lanes:backward` | `lanes` string (`'-'·backward .. '+'·forward`, mirrored for left-hand traffic) |
| `width` or lanes × 3.5 m (+ shoulders for motorway) | node radius = width/2 (cap 15 m: `maxRadius`) |
| `maxspeed` (`50`, `30 mph`, `XX:urban`, `none`), defaults by country × class | `speedLimit` in m/s (`none` → 130 km/h cap for AI) |
| `access=private/no`, `service=driveway/parking_aisle` | `type = 'private'` (traffic will not spawn there; GPS penalty via `gatedRoad`) |
| `area=yes`, `highway=pedestrian/footway/cycleway/steps`, `construction` | excluded |
| `highway=traffic_signals` (node), `traffic_signals:direction=forward/backward` | cluster all signal nodes within ~40 m of a junction into one sequence; approaches split into 2 phases by bearing (k-means on angle mod 180°); controller `lightsBasic` (NA) or `lightsBasicEU` (EU), `autoSetTimings(speedLimit, junctionSize)`; one instance per approach at the stop point; one head prop per approach |
| `highway=stop` (+ `stop=all`) | instance with a `signStop` controller on that approach (all approaches for `stop=all` → 4-way-stop logic) |
| `highway=give_way` | **no AI action exists**. Lower the approach edge's drivability (implicit give-way, 4.4) + place the sign prop only |
| `highway=street_lamp`, `lit=yes` | lamp props (OSM coverage is sparse: fall back to one per ~35 m along `lit=yes` roads near the player) |
| `traffic_sign=*` with `maxspeed` changes | speed sign prop where `maxspeed` changes along a way |

---

## 8. Implementation plan for BeamNG.Earth

### 8.1 Components
**Server (`server/`, Python):**
1. `roads/osm_graph.py`: from the OSM extract (other agents choose the source), build a routable graph: split ways at shared nodes, drop
   non-drivable classes, apply the mapping table above, densify curves (chord ≤ 0.2 m, edge ≤ 100 m), and give node ids stable names (2.8).
2. `roads/navwindow.py`: cut the window = current terrain block square minus 60 m (and later, if P1 allows, the block plus a ring).
   Edges crossing the border are cut at the border with a terminal node `c<edgeId>`. Output in current-anchor ENU with z from the
   **same DEM as the physics terrain** (or the bridge deck).
3. `roads/signals.py`: junction clustering, phases, stop points, prop transforms (side of road from the driving side, offset = radius + 1.5 m).
4. Road rules per window from the country polygon: `{rightHandDrive, turnOnRed}` (US/CA turnOnRed = true, most others false).

**Mod (`mod/beamng_earth/lua/ge/extensions/beamngEarth/`):**
1. `navgraph.lua`: decode → node table → `apply(nodes, rules)`. This does the rules wrap (2.7.4), `map.reset`, the persistent-table copy-back
   (2.7.2), `be:queueAllObjectLua('mapmgr.requestMap()')`, re-injection on foreign `onNavgraphReloaded` (2.7.5), and timing to `perfmon`.
2. `signals.lua`: `core_trafficSignals.resetSignals()` before each navgraph apply, then create props + `setupSignals(..., false, true)` after it.
   Props live in our own SimGroup so rebase and teardown handle them.
3. `props.lua`: pooled `TSStatic` creation for signs and lamps, time-sliced with the existing governor (~2 ms per frame), a distance cap of ~400 m,
   and recycling by key.
4. `trafficguard.lua`: block-edge guard (forceTeleport), start traffic only after the first graph, and optionally cap traffic's spawn distance by
   patching `gameplay_traffic.setTrafficVars({spawnValue=...})` (a higher spawnValue means a smaller minDist).
5. `core.lua` hooks: a new window on terrain-follow commit (if the player moved > 400 m since the last window); a full rebuild in the
   rebase frame (2.8).

### 8.2 Protocol (JSON control + one binary frame; framing already supports binary payloads up to 64 MiB, `framing.lua:9`)
- mod → server: `{"type":"nav_request","requestId":N,"anchorId":A,"cx":m,"cy":m,"half":1023,"margin":60}` (sent with `prepare_terrain`, same centre).
- server → mod: `{"type":"nav_ready","requestId":N,"anchorId":A,"cx","cy","nodes":K,"edges":E,"rules":{"rightHandDrive":false,"turnOnRed":true},"country":"usa","blob":<frame id>}`,
  followed by a binary frame: header + `names` (NUL-separated) + `float32[3K] pos` + `float32[K] radius` + edges
  `{uint32 in, uint32 out, uint8 flags(oneWay,private,hidden), float32 drivability, float32 speedLimit, uint8 laneLen, lane chars}`.
  Parse with `ffi.copy` into typed arrays (`ffi.cast` is a stub, see ARCHITECTURE.md). JSON is acceptable at first for ≤ 3k nodes **[I: ~10–30 ms decode]**.
- server → mod: `{"type":"signals","anchorId":A,"window":N,"junctions":[{"id":"j<osm>","seq":[[phase controller names]],"controllers":[{"name","type","states"?}],"instances":[{"name","pos","dir","controller","phase"}],"props":[{"shape","pos","quat","instance"?}]}]}`
- server → mod: `{"type":"props","anchorId":A,"window":N,"add":[{"key","shape","pos","quat"}],"remove":["key",...]}` for signs and lamps (keys stable across windows).
- The server reuses `commit_terrain`/`commit_anchor` to know which frame the mod is in. The rebase prepare (`prepare_anchor` for purpose `rebase`)
  also prepares `nav_ready` for the new anchor, so the rebase commit frame has everything ready.

### 8.3 Sequencing
- **Window shift** (same anchor): when `terrain_ready` is committed → next frame `navgraph.apply` (do not put it in the same frame as
  `importMaps`, which already takes ~45 ms) → next frame `signals.apply`. Props stream continuously.
- **Rebase**: phase 1 (vehicles moved) → in the same frame `signals.reset` + `navgraph.apply(newFrame)` + push `setMap`/`setSignals` → phase 2 as today → `signals.apply`.
- **Teleport**: stop traffic (`gameplay_traffic.deactivate`/`deleteVehicles`), wait for the first graph, then restart.

### 8.4 Risks
| Risk | Mitigation |
|---|---|
| `map.reset` cost (all-or-nothing, plus the UI `NavigationMapChanged` dump) at ~5k nodes | P1. If >30 ms: shrink the window, rebuild every 2nd terrain commit, or wrap `guihooks.trigger` during our reset to drop `NavigationMapChanged` (bigmap is ours anyway) |
| Traffic outside the physics island | graph clip + edge guard (section 3) |
| AI steering blip on rebase | push `setMap` in the move frame (P5) |
| Foreign `map.reset()` wipes the graph | `onNavgraphReloaded` re-inject |
| Junction topology errors in OSM (dual carriageways, offset joins) | server-side merge of junction nodes within the radius; validator (degree, dangling edges) before sending |
| Give-way not supported by the AI | drivability hierarchy; stop sign only where OSM says `stop` |
| Other-level props missing materials | use `art/` shapes; P7 decides whether US signs can be borrowed |
| Many TSStatics (lamps) | distance cap, pooling, emissive-only far away |
| `rightHandDrive` misuse | remember: `true` = drive on the **left** |

### 8.5 Files to add (nothing existing changes except hooks in `core.lua`)
`server/roads/{osm_graph,navwindow,signals,props}.py`, `mod/.../beamngEarth/{navgraph,signals,props,trafficguard}.lua`,
a protocol section in a new `docs/V1_4_SPEC.md` (or the next spec), and probes in `probes/nav/`.

### 8.6 Handy snippets
Rules wrap and persistent table:
```lua
local P -- persistent node table, handed to gameplay_traffic once
local function apply(nodes, rules)
  writeFile('/temp/beamngEarth/rules.json', jsonEncode({roadRules = rules}))
  local orig = path.getPathLevelInfo
  path.getPathLevelInfo = function() return '/temp/beamngEarth/rules.json' end
  M._ours = true
  local ok, err = pcall(map.reset, nodes)
  M._ours = false
  path.getPathLevelInfo = orig
  if not ok then log('E', 'beamngEarth', 'navgraph: ' .. tostring(err)) return end
  local m = map.getMap()
  if P and P ~= m.nodes then table.clear(P); for k, v in pairs(m.nodes) do P[k] = v end; m.nodes = P else P = m.nodes end
  be:queueAllObjectLua('mapmgr.requestMap()')
end
```

---

## 9. In-game probes to run later (do NOT run while the user is playing; smallgrid or our level, via MCP `run_lua`)

**P1: inject a synthetic grid and time it** (n = 30/71/141 → ~0.9k / 5k / 20k nodes):
```lua
local n, sp = 71, 25
local p = be:getPlayerVehicle(0):getPosition()
local nodes = {}
local function id(i, j) return 'g' .. i .. '_' .. j end
for i = 0, n-1 do for j = 0, n-1 do
  local pos = vec3(p.x + (i - n/2) * sp, p.y + (j - n/2) * sp, p.z + 200)
  pos.z = be:getSurfaceHeightBelow(pos)
  nodes[id(i, j)] = {pos = pos, radius = 4, links = {}}
end end
local function link(a, b)
  local A, B = nodes[a], nodes[b]
  local e = {drivability = 1, oneWay = false, lanes = '-+', speedLimit = 13.9, inNode = a, outNode = b,
             inPos = A.pos, outPos = B.pos, inRadius = A.radius, outRadius = B.radius}
  A.links[b] = e; B.links[a] = e
end
for i = 0, n-1 do for j = 0, n-1 do
  if i < n-1 then link(id(i, j), id(i+1, j)) end
  if j < n-1 then link(id(i, j), id(i, j+1)) end
end end
local t0 = os.clockhp(); map.reset(nodes); local t1 = os.clockhp()
local gp = map.getGraphpath()
local blob = lpack.encodeBin({graphData = gp:export()})
return {resetMs = (t1 - t0) * 1000, nodes = tableSize(map.getMap().nodes), mailboxBytes = #blob}
```
Repeat with `guihooks.trigger` wrapped to no-op for `NavigationMapChanged` to isolate the UI cost.

**P2: vehicle import cost**: spawn 1 car; `veh:queueLuaCommand("local t=os.clockhp(); mapmgr.setMap(-12345); obj:queueGameEngineLua('print(\"setMap ms \"..'..'(os.clockhp()-t)*1000)')")`. (Compare 1k/5k/20k.)

**P3: AI on the grid**: `veh:queueLuaCommand("ai.setMode('traffic')")`, watch for 60 s; then `gameplay_traffic.setupTraffic(4)` and check
there are no errors at `traffic.lua:1252` (expected without the copy-back) and that the copy-back fixes them.

**P4: signals on the grid centre**: build one 4-leg sequence (section 5.2) with `trafficlight_city1` props. Check `core_trafficSignals.getMapNodeSignals()`
is keyed by the approach edges, and that an AI car stops on red at `pos` (`core_trafficSignals.debugLevel = 2` draws them).

**P5: rebase simulation**: shift every node by (+3000, 0, 0) into a new table, move all vehicles by the same offset (as `probes/p6_rebase.lua`), `map.reset`, and
compare `requestMap` against a direct `be:queueAllObjectLua('mapmgr.setMap('..map.getMap().buildSerial..')')`. Log each AI's steering for 10 frames.

**P6: rules wrap**: run the snippet in 8.6 with `rightHandDrive = true`; check `map.getRoadRules().rightHandDrive == true`
and that traffic keeps to the left.

**P7: foreign assets**:
`return {FS:fileExists('/levels/east_coast_usa/art/shapes/signs_usa/sign_stop.dae'), FS:fileExists('/art/shapes/objects/trafficlight_city1.dae'), scenetree.findObject('instanced_trafficlight') ~= nil}`.
Then spawn `sign_stop.dae` as a TSStatic and screenshot it for a missing material (orange/"No material") before and after
`loadJsonMaterialsFile('/levels/east_coast_usa/art/shapes/signs_usa/main.materials.json')` (path to be confirmed from the zip listing).

**P8: terrain drivability**: `return be:getTerrainDrivability(be:getPlayerVehicle(0):getPosition(), 4)` on our physics-only terrain (expect > 0).

**P9: foreign reset**: call `map.reset()` while our graph is live and check that the `onNavgraphReloaded` re-injection restores it in one frame.

**P10: block edge**: put an AI car on a graph edge 50 m inside the block edge, driving outward, and verify the guard teleports it before it leaves the block.
