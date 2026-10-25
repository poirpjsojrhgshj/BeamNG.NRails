# Long-distance GPS navigation in BeamNG.Earth (Cannonball Run scale)

Research date 2026-10-10. Game: BeamNG.drive 0.39.4, Linux. `G` = `~/.local/share/Steam/steamapps/common/BeamNG.drive`.
Scope: how the stock navigation works (route planner, ground markers, minimap or "Navigation" app, big map, AI path following), which parts accept an externally supplied route, which routing and geocoding services the companion can use, and a concrete design and plan.
Not covered here: the world map GUI, OSM road meshes, the navgraph builder, traffic or signals. Those are other agents' topics. This report only defines its interfaces to them.

Labels: **[V]** = verified by reading game code (file:line) or by a measured request. **[I]** = inference or estimate. **[D]** = from vendor or third-party documentation (URL given).

---

## 0. TL;DR

* The stock GPS is `core_groundMarkers` plus one route-planner instance (`gameplay/route/route.lua`).
  * Its route is just a Lua array `path[i] = {pos=vec3, wp=nodeName|nil, linkCount, fixed, distToTarget}`.
  * Everything downstream reads only `pos` and `distToTarget`, and `wp/linkCount` for junction arrows: the 3 m ground decals, the 3D turn arrows, the minimap route line, the "distance to target" label, the big map route line, and the "wrong direction" message.
  * So **we can install an arbitrary list of positions** by overriding two or three methods on that one planner instance. The engine's navgraph is then never consulted. **[V]**
* The planner only knows a local frame and a local navgraph. It re-routes by itself when you leave the line by more than 18 m. So the **full 4 500 km route has to live in the companion**:
  * The companion keeps it in lat/lon.
  * It streams a ~15 km window in the current anchor frame. That is ~350 points after densifying to 50 m; measured on a real NY→LA route.
  * It re-sends the window after every rebase.
  * It does progress tracking, off-route detection, ETA and re-routing from the `pose` messages it already receives at 10 Hz.
* Routing service: use the **OSRM HTTP API**.
  * Start with the free FOSSGIS instance (`routing.openstreetmap.de/routed-car`) or the OSRM demo. Both allow ≤1 req/s and non-commercial use; a game session makes a handful of requests.
  * A NY→LA route with `steps=true&overview=full&annotations=...` came back in **0.9–1.0 s, 4 497 km, 49.8 h, 34 642 points, 71 steps, ~0.95 MB JSON**. **[V]**
  * OSRM uniquely returns the **OSM node id of every geometry point** (`annotations=nodes`). That is the key to aligning the route with an OSM-derived local navgraph and road meshes.
  * Valhalla's public instance **refuses** this trip: "max distance limit: 1500000 meters". **[V]**
* Self-hosting later: Valhalla on a US extract is the frugal option (graph on disk, mmapped). OSRM on a US extract probably needs more than this machine's 64 GB RAM to pre-process. Keep the server code engine-agnostic behind one adapter.
* Geocoding: **Photon** (`photon.komoot.io`) for search-as-you-type with a location bias. **Nominatim** only for final or reverse lookups, ≤1 req/s and cached; its policy forbids autocomplete.
* AI:
  * `ai.driveUsingPath{path = {navgraph node names}}` follows a node list. `ai.setPath(list)` appends to the current route when `list[1]` equals the current last node.
  * Every navgraph reload makes the AI drop its route, so it must be re-issued after each rebase or navgraph rebuild.
  * The `script = {...}` mode **teleports the car to the script start**, so it is unusable mid-drive. **[V]**
  * AI cars can only exist near the player, because the single physics TerrainBlock follows the player.

---

## 1. How BeamNG's navigation works (verified in game Lua)

### 1.1 Route planner: `lua/ge/extensions/gameplay/route/route.lua`

* **Construction and state.** It is a class (`C`); `require(...)()` returns an instance with `setmetatable(o, C)` (`route.lua:453-458`). Instance fields: `path`, `distance`, `dirMult`, and job handles (`route.lua:27-34`).
* **Route representation.** `self.path` is an array of `{pos = vec3, wp = <navgraph node name or nil>, linkCount = n, fixed = bool, distToTarget = m}`.
  * `runSetupPathMultiBuild` builds it (`route.lua:124-176`). It puts the raw start position in as `{pos, wp=nil}` (`:127`), each navgraph node as `{pos = map.getMap().nodes[p].pos, wp = p, linkCount}` (`:135`), and each user waypoint as `{pos, wp=nil, fixed=true}` (`:137`).
  * It merges points closer than 1 m (`:146-160`).
  * **`wp = nil` is a first-class case.** Nothing requires every point to be a navgraph node.
* **`calcDistance()`** (`route.lua:85-100`) walks backwards: last point `distToTarget = 0`, each earlier point adds the segment length. `self.distance = path[1].distToTarget`.
* **Path finding.** `setupPathMulti(positions)` (`route.lua:181-186`) calls `map.getPointToPointPath(from, to, ...)` for each consecutive pair, synchronously. `setupPathMultiJob` (`:216-247`) is the coroutine version through `core_jobsystem`.
  * `map.getPointToPointPath` (`lua/ge/map.lua:2890-2905`) is A* on the local `graphpath`. It starts from edges found by a kd-tree search around `startPos` and gives up beyond 2 km (`startPosLinks`, `map.lua:2829-2888`, `until searchRadius > 2000`).
  * **The stock planner cannot plan anything outside the local navgraph.**
* **Tracking.** `updatePathForPos(pos)` (`route.lua:412-450`) runs **every frame** from `core_groundMarkers.onPreRender` (`groundMarkers.lua:186-189`).
  * `getPositionOffset` (`:373-397`) finds the first segment within `onPathDist = 18` m (`route.lua:6`). It scans from index 1 and stops at the first segment that is farther than the best so far. When off-route it scans the whole path every frame: O(n).
  * Passed points are removed (`shortenPath`, `:399-405`).
  * The first point is projected onto the line (`fixStartEnd`, `:47-57`). It sets `a.distToTarget = |a-b| + b.distToTarget`, so **any constant offset baked into `distToTarget` is preserved**.
* **Automatic re-routing.** If the closest segment is more than 18 m away, `updatePathForPos` calls `self:recalculateRoute(pos)` (`route.lua:434-437`). That starts a jobsystem A* on the **local navgraph** from `pos` to the next `fixed` point or the last point (`:288-369`). This would destroy an externally supplied path, so it must be overridden (see §5.3).
* **Fixed nodes.** `lockFixedNodes` stops tracking at the first fixed node (`:384-386`).
  * `getNextFixedWP()` (`:256-260`) is used by `gameplay/markerInteraction.lua:521-524` to draw a distance column at the next fixed point.
  * Only the true destination should be `fixed`.

### 1.2 Ground markers: `lua/ge/extensions/core/groundMarkers.lua`

* There is **one global planner instance**, `M.routePlanner = require('/lua/ge/extensions/gameplay/route/route')()` (`groundMarkers.lua:14`).
* **`setPath(wp, options)`** (`:246-309`):
  * `wp` can be a navgraph node name, a `vec3`, a `{x,y,z}` table or a list of these (`:268-293`).
  * The vehicle position is prepended. Then `routePlanner:setupPathMulti(multiPath)` runs synchronously, followed by `trackVehicle` (`:296-301`).
  * Options: `step` (decal spacing, default 3 m), `color`, `clearPathOnReachingTarget`, `lockFixedNodes`, and routing penalties.
  * `setPath(nil)` clears the route (`:269-275`).
* **Decals.**
  * `generateRouteDecals` (`:139-176`) runs when the car has moved more than 1 m (`:197`). It places arrow decals every `step` metres, up to `decalDrawingDistance = 120` m ahead (`:95`), fading between 10 and 100 m (`:97-98`).
  * Positions are lerped between `path[i].pos`. Only `pos` and `distToTarget` are used.
  * They are drawn with `Engine.Render.DynamicDecalMgr.addDecals(M.decalPool, n)` (`:221`). Decal scale is `(1.5, 3, 2)` (`:81`).
  * **[I]** The z of the path points must be within roughly ±1 m of the rendered ground for the projected decals to show.
* **UI feed.**
  * Every 0.25 s `sendToApp` sends **all** path x,y pairs through `guihooks.trigger("NavigationGroundMarkersUpdate", ...)` (`:223-244`).
  * A 4 500 km path at 50 m spacing would be 90 000 points every 0.25 s. **This is a hard reason to stream a window, not the whole route.**
* **Target reached.**
  * `markerInteraction.lua:518-526`: when `clearPathOnReachingTarget` is set, the route ends once `core_groundMarkers.getPathLength() < 7`. `getPathLength` returns `path[1].distToTarget` (`groundMarkers.lua:43-48`).
  * With the remaining-distance offset (§5.3) this never triggers early, even if the window's end is near. Also pass `clearPathOnReachingTarget=false` and handle arrival in the companion.

### 1.3 Turn arrows: `lua/ge/extensions/core/groundMarkerArrows.lua`

* `updateArrows(path, totalDist)` (`:121-206`) places floating 3D arrows up to 180 m ahead (`:124`).
* An arrow appears only at points with `wp` and `linkCount > 2` (a navgraph junction) when the turn angle is above 25° or another branch is straighter (`:148-166`). It reads the junction's branches from `map.getGraphpath().graph[path[i].wp]` (`:154`).
* So **turn arrows need `wp`/`linkCount` from the local navgraph.** With a pure position list you get decals but no arrows. With `wp` filled from the OSM-node alignment (§5.4) you get both.
* The "wrong direction" message comes from `velocity · (path[2].pos - vehPos) < 0` with a ±20-frame hysteresis (`:208-227`). This works with any path.

### 1.4 Minimap and "Navigation" app

* The Vue app `G/ui/modules/apps/Navigation/app.vue` is only a frame. The map itself is drawn in Lua through imgui by `ui_apps_minimap_minimap` (`app.vue:217-236` → `lua/ge/extensions/ui/apps/minimap/minimap.lua:223-376`).
* **Route line.** `ui/apps/minimap/route.lua`:
  * `drawNavigationRoute` first calls `extensions.hook("onMinimapRouteOverride", routeOverrides)`. Any extension can append route arrays of `{pos, distToTarget}`; otherwise it draws `core_groundMarkers.routePlanner.path` (`route.lua:60-75`).
  * At most **3 000 points** are drawn (`routeMaxLength`, `route.lua:11,45`).
  * The destination pointer is `path[#path].pos` (`:77-87`). With a windowed route it points at the end of the window, so suppress or replace it via `onDrawOnMinimap`.
* **Distance label.** `ui/apps/minimap/additionalInfo.lua:16-30` shows `translateDistance(rp.path[1].distToTarget, "auto")` via `guihooks.queueStream("minimap", ...)`. It is shown in `app.vue:21,34`. With the offset trick it shows the **true remaining distance** (e.g. "4123.4 km"). There is no ETA field.
* **Custom drawing.** `extensions.hook("onDrawOnMinimap", td)` (`minimap.lua:332`) lets our extension draw extra lines or markers. `ui_apps_minimap_utils.worldToMapXY/worldToMapXYZ` are public (`utils.lua:334-337`).
* **Road layer.** `ui/apps/minimap/roads.lua:15-60` builds a kd-tree of **navgraph links once** (`if not kdNodes`) and only resets on mission start or end or a settings change (`minimap.lua:526,725-738`).
  * **After every `map.reset`, i.e. a rebase or navgraph window update, call `ui_apps_minimap_roads.reset()`**, or the minimap shows stale roads in the old frame.
  * The topo layer (`topomap.lua`) is built from navgraph bounds plus terrain height. Not relevant at this scale.
* **Arrow GPS app.** `ui_arrowGPS.setTarget(key, priority, {pos=vec3, color={r,g,b}})` and `removeTarget(key)` (`lua/ge/extensions/ui/arrowGPS.lua:55-71,194-195`) give a free HUD arrow pointing at any world position. It is useful for "next manoeuvre" or for a destination beyond the window.
* **In-car navigation screens.** `lua/vehicle/controller/gauges/customModules/navigationData.lua:20-29` only streams vehicle x/y/heading to the dashboard HTML and asks `ui_uiNavi.requestVehicleDashboardMap`. The backdrop is the level's static minimap image (`ui/uiNavi.lua`, `minimapFromTerrainBlock`). It is not usable for a streaming world without our own texture pipeline; out of scope.

### 1.5 Big map: `lua/ge/extensions/freeroam/bigMapMode.lua`

* It is a **3D camera over the live scene**.
  * The frame is the terrain world box plus all navgraph nodes (`calculateCamPos`, `:249-296`; `includeClustersInBbox`, `:232-247`).
  * A click sets a destination with `castRayStatic(ray.pos, ray.dir, 50000)` against **static collision** (`clickOnMap`, `:1494-1509`).
  * In BeamNG.Earth, static collision is only the ~2 km physics TerrainBlock. Far tiles are `collisionType='None'`. **So big map clicks can only set destinations inside the bubble.** **[V]** for the code; **[I]** for the consequence.
* `setNavFocus(pos)` (`:391-399`):
  * It fires `extensions.hook("onSetBigmapNavFocus", pos)`, then `core_groundMarkers.setPath(pos, {clearPathOnReachingTarget=true})`, then `resetRoute()`.
  * `resetRoute` simplifies `routePlanner.path` for drawing and **calls `routePlanner:calcDistance()`** (`:379-389`). That would erase a distance offset unless `calcDistance` is overridden too (§5.3).
* The route is drawn as `debugDrawer:drawCylinder` segments over the simplified path (`:1176-1205`).
* Conclusion: the big map is fine as an "inside the bubble" picker. We can catch its clicks via the `onSetBigmapNavFocus` hook, turn the local position into lat/lon and ask the companion for a long route. A continent-scale picker must be the separate world map GUI.

### 1.6 Older "uiNavi" route API

`ui/uiNavi.lua:139-181` (`route_start`, `planRoute`) is legacy. It calls `map.getPath` on the local graph and triggers `RoutePlanned` or `RouteUpdate`. Not useful.

### 1.7 Navgraph injection: `lua/ge/map.lua`

* `map.reset = loadMap` (`map.lua:3960`). `loadMap(customMapNodes)` (`:2497-2687`) replaces the whole graph with the supplied `nodes` table:
  * It calls `convertToSingleSided()` (`:2116-2134`).
  * It builds `graphpath` and kd-trees and sends the graph to every vehicle's `mapmgr` through the `mapData` mailbox (`:2662-2671`).
  * It fires `onNavgraphReloaded`.
* Node format, as the stock builder produces it (`map.lua:675-704`): `nodes[name] = {pos=vec3, radius=m, links = {[other] = data}}`.
  * `data = {drivability, oneWay, lanes='++' / '-+', speedLimit, inNode, outNode, inPos, outPos, inRadius, outRadius, type, hiddenInNavi}`.
  * The **same `data` table is stored on both endpoints**, and `convertToSingleSided` keeps the copy where `data.inNode == lid`.
  * Lane strings: `+` is the in→out direction, `-` the opposite (`map.lua:161-172,548-566`).

### 1.8 AI path following: `lua/vehicle/ai.lua`

* **`ai.driveUsingPath{...}`** (`ai.lua:5906-6098`). Arguments are documented in-line at `:5907-5941`:
  * `path` = node names, followed in order.
  * `wpTargetList` = node names, with shortest paths between them.
  * `script` = positions.
  * Options: `driveInLane='on'`, `avoidCars='on'`, `routeSpeed`, `routeSpeedMode='legal'|'limit'|'set'`, `aggression`.
* **`script` mode teleports the vehicle.** It computes a start pose from `script[1..k]` and queues `vehicleSetPositionRotation(...)` (`ai.lua:6003-6009`), which calls `setPositionRotation` (`lua/ge/ge_utils.lua:459-463`). It also replaces the AI map with a private chain graph (`:6010-6037`).
  * **Unusable for a car that is already driving**, and it would also bypass traffic and signals. **[V]**
* **Node-list path.**
  * `driveUsingPath{path=...}` or `ai.setPath(list)` (`:5901-5904`) sets `manualPath`. In manual mode, `newManualPath()` (`:3836-3899`, called at `:5307-5308`) either creates the route, or **extends the current one with `pathExtend`**.
  * `pathExtend` appends `newPath[2..]` only when `newPath[1]` equals the current last node (`:977-985`). That is an incremental "next chunk" API.
* **Navgraph reload drops the AI route.** `updateGFX` runs `if mapData ~= mapmgr.mapData then currentRoute = nil end` (`ai.lua:5137-5139`).
  * Every `map.reset` (each rebase, each navgraph window refresh) makes every AI forget its path. The mod must re-issue the remaining node list afterwards. **[V]**
* Speed: with `routeSpeedMode='legal'` the AI uses the edges' `speedLimit`, which the navgraph builder should fill from OSM `maxspeed`. Signals come from `mapmgr.signalsData` (`ai.lua:136, 4250-4290, 4442`); that is the traffic agent's topic.

---

## 2. Routing services: policies, limits, measurements

### 2.1 Measured requests (one each, 2026-10-10, with an identifying User-Agent)

| Service | Request | Result |
|---|---|---|
| OSRM demo `router.project-osrm.org` | `/route/v1/driving/-74.0060,40.7128;-118.2437,34.0522?overview=full&geometries=polyline6&steps=true&annotations=nodes` | HTTP 200 in **1.05 s**, 954 KB. 4 496.9 km, 49.81 h, **34 642 geometry points = 34 642 OSM node ids**, 71 steps, 1 747 intersections |
| FOSSGIS OSRM `routing.openstreetmap.de/routed-car` | same without annotations | HTTP 200 in **0.87 s**, 587 KB, identical route |
| FOSSGIS Valhalla `valhalla1.openstreetmap.de/route` | `{"locations":[NYC,LA],"costing":"auto"}` | **HTTP 400, error 154 "Path distance exceeds the max distance limit: 1500000 meters"** |

Route geometry statistics (NY→LA, OSRM full overview), computed by a decode script in the scratchpad:

* Segment length: median 66.8 m, p90 282 m, **max 6 256 m** (long straight interstate stretches with no intermediate OSM nodes).
* polyline6 decode of all 34 642 points in Python: 29 ms.
* A 15 km window holds a median of 98 raw points (p95 262, max 723).
* **Densified to ≤50 m spacing**: median 349, p95 424, **max 824 points**. This fits the minimap's 3 000-point limit and the 0.25 s UI feed.

Sample steps (they show the data available for turn-by-turn), as type/modifier | name | ref | destinations | exits:

* `off ramp slight right | | I 80 | I 80 West, I 94, US 6: Des Moines | 21`
* `fork slight left | Z. H. Confair Memorial Highway | I 80 | … 512.1 km`
* `merge slight right | Barstow Freeway / Mojave Freeway | I 15 | … 262.3 km`

**[V]** All of the above are measured.

### 2.2 Policies and quotas

| Service | Key | Limits / policy | Long routes | Notes |
|---|---|---|---|---|
| **OSRM demo** `router.project-osrm.org` | none | "Do not exceed 1 request per second"; "reasonable, non-commercial use-cases"; no uptime guarantee **[D]** https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server | NY→LA OK **[V]** | Car only |
| **FOSSGIS OSRM** `routing.openstreetmap.de/routed-{car,bike,foot}/route/v1/driving/...` | none | "One request per second max", "No scraping, no heavy usage", "Use a valid user agent and, if applicable, a correct referrer", show attribution plus a "fix the map" link **[D]** https://routing.openstreetmap.de/about.html | NY→LA OK **[V]** | Car/bike/foot worldwide |
| **FOSSGIS Valhalla** `valhalla1.openstreetmap.de` | none | Fair use. Third-party sources quote "1 call/user/sec and 100 calls/sec total" (**unconfirmed**) | **Max 1 500 km per route [V]**, so a Cannonball needs ≥4 chained requests | Ready-made instruction text, multi-language |
| **GraphHopper** Directions API | **API key** (sign-up, no card) | Free plan: **500 credits/day, max 5 locations, non-commercial only** **[D]** https://www.graphhopper.com/pricing/ | Credits per long route not published on the page | Workable but a key to manage |
| **openrouteservice** | **API key** | Standard (free): Directions **2 000/day, 40/min**; **max route 6 000 km**; 50 waypoints; alternatives only ≤100 km **[D]** https://openrouteservice.org/plans/, https://openrouteservice.org/restrictions/ | NY→LA OK on paper | Good fallback |
| Self-hosted OSRM | none | none | none | See §2.3 |
| Self-hosted Valhalla | none | `service_limits.auto.max_distance` default **5 000 000 m** (crow-fly between all locations), `max_locations: 20` (`scripts/valhalla_build_config:320-326`) **[V]** | Configurable | See §2.3 |

Usage estimate for BeamNG.Earth **[I]**:

* One route request per destination, plus re-routes. A short re-route to a rejoin point (§4.4) happens about every few minutes when the player strays.
* Even an aggressive player stays below ~1 request/minute on average. That is well inside every policy above.
* Always: serialize requests to ≤1/s per host, send `User-Agent: BeamNG.Earth/<ver> (+contact)`, cache responses on disk, and show "Routing © OSRM / FOSSGIS, data © OpenStreetMap contributors" in the mod UI while routing is active.

### 2.3 Self-hosting (this machine: 16 cores, 64 GB RAM + 64 GB swap, 1.1 TB free; docker and podman installed) **[V]**

* **US extract:** Geofabrik `us-latest.osm.pbf` = **11.4 GB** (2026-10-09) **[D]** https://download.geofabrik.de/north-america/us.html. Individual states run from 90 MB (Wyoming) to 1.2 GB (California).
* **OSRM.**
  * The wiki lists, for the planet (61 GiB pbf, v5.26, car): extract **415 GiB**, partition 220 GiB, customize 174 GiB, contract 230 GiB. Runtime "around **123 GiB of RAM**". Sizes "scale roughly linear with input data size" **[D]** https://github.com/Project-OSRM/osrm-backend/wiki/Disk-and-Memory-Requirements.
  * The scraped table does not label the pre-processing column as RAM or disk.
  * Scaled linearly to 11.4 GB, a US car extract needs **~78 GiB peak** for extract, ~41 GiB for partition and **~23 GiB RAM at runtime** **[I]**.
  * That is too much next to a running BeamNG on a 64 GB box. A single state or a Geofabrik sub-region is fine.
  * Commands (docker `ghcr.io/project-osrm/osrm-backend`): `osrm-extract -p /opt/car.lua x.osm.pbf && osrm-partition x.osrm && osrm-customize x.osrm && osrm-routed --algorithm mld x.osrm`.
* **Valhalla.**
  * The graph is tiled on disk and memory-mapped at runtime. Planet builds take "about a day" on 24 cores / 32 GB with NVMe, or close to 24 h on 16 cores / 64 GB. Graph ≈ 1–1.5× the pbf size, peak disk ~350 GB for the planet **[D]**: https://github.com/valhalla/valhalla/discussions/3197, https://github.com/valhalla/valhalla/issues/5099, https://github.com/valhalla/valhalla/discussions/3661.
  * Scaled to the US (~13 % of the planet), expect **~3 h build, ~12–17 GB graph, a few GB resident** **[I]**.
  * Docker: `docker run -dt -p 8002:8002 -v $PWD/custom_files:/custom_files -e tile_urls=https://download.geofabrik.de/north-america/us-latest.osm.pbf ghcr.io/valhalla/valhalla-scripted:latest` **[D]** (valhalla `docker/README.md`). Set `server_threads` lower if the OOM killer strikes.
  * Raise `service_limits.auto.max_distance` for trips over 5 000 km crow-fly.

### 2.4 Recommendation

**Use the OSRM HTTP API format as the routing contract, with a configurable base URL.**

* Default: `https://routing.openstreetmap.de/routed-car`. Fallback: `https://router.project-osrm.org`.
* Optional user setting: a self-hosted OSRM, or Valhalla through `"format":"osrm"`. Valhalla can answer in OSRM format, but without OSM node ids.
* Reasons:
  1. No key, and it measurably handles the full Cannonball distance in one ~1 s request.
  2. `annotations=nodes` gives the **OSM node id per geometry point**. That is the cleanest way to snap the route onto our own OSM-derived roads and navgraph (§5.4). No other free API offers this.
  3. `annotations=duration,distance` gives per-segment expected times for an honest ETA.
  4. Steps carry `ref`, `destinations` and `exits`, which is everything a highway-style instruction needs.
* Valhalla's ready-made `instruction` strings are the one thing OSRM lacks. We generate text from OSRM steps ourselves (§4.5); it is a small table.

**Exact request (full route):**

```
GET {base}/route/v1/driving/{lon0},{lat0};{lon1},{lat1}
    ?overview=full&geometries=polyline6&steps=true
    &annotations=nodes,distance,duration
    &continue_straight=true
    &bearings={heading_deg},45;
    &radiuses=50;
```

* `bearings` and `radiuses` need exactly one element per coordinate, so the empty element for the destination is required. These are documented in `docs/http.md`, general options **[D]** https://raw.githubusercontent.com/Project-OSRM/osrm-backend/master/docs/http.md.
* Optional: `exclude=toll|motorway|ferry`, comma-joined; the names depend on the server profile.
* Response:
  * `routes[0].geometry`: polyline6 of [lat, lon].
  * `routes[0].legs[k].annotation.nodes|distance|duration[]`: parallel arrays. `nodes` has one more entry than the per-segment arrays.
  * `legs[k].steps[] = {distance, duration, name, ref, destinations, exits, maneuver:{type, modifier, location:[lon,lat], bearing_before, bearing_after, exit}, intersections[]}`.

**Exact request (Valhalla alternative, self-hosted):**

```
POST {base}/route
{"locations":[{"lat":..,"lon":..,"heading":H,"heading_tolerance":45},{"lat":..,"lon":..}],
 "costing":"auto","units":"kilometers","language":"en-US"}
```

* Response: `trip.legs[].shape` (polyline6) and `trip.legs[].maneuvers[] = {type, instruction, verbal_pre_transition_instruction, street_names, begin_shape_index, end_shape_index, length, time, sign:{exit_number_elements, exit_toward_elements, ...}}`.
* `trip.summary.{length,time}`.
* **[D]** https://valhalla.github.io/valhalla/api/route/api-reference/

### 2.5 Geocoding

* **Photon** (komoot), `https://photon.komoot.io/api/?q=<text>&limit=5&lat=<bias>&lon=<bias>`.
  * Free "if your request volume stays reasonable"; heavy use may be throttled or banned. **Supports search-as-you-type** **[D]** https://github.com/komoot/photon.
  * Measured: `q=santa monica pier` returned Santa Monica Pier (CA) first, in 0.59 s. Answers are GeoJSON features with `properties.{name, city, state, country, osm_key, osm_value, type}` and `geometry.coordinates=[lon,lat]` **[V]**.
  * Self-hosting needs a ~95 GB planet DB and ≥64 GB RAM recommended **[D]**, so stay on the public instance.
* **Nominatim** (`nominatim.openstreetmap.org/search?q=..&format=jsonv2&limit=5`). Policy **[D]** https://operations.osmfoundation.org/policies/nominatim/:
  * "an absolute maximum of 1 request per second".
  * A real UA ("stock User-Agents as set by http libraries will not do").
  * "Results must be cached on your side".
  * **"Auto-complete search" is unacceptable use.**
  * Measured: 0.30 s, the same top hit **[V]**.
* Plan:
  * Photon for typing, debounced to ≥400 ms of idle and ≤1 req/s, and biased to the player's lat/lon.
  * Nominatim only for an explicit "search" button fallback and for reverse geocoding ("you are near …", throttled to ≤1/min).
  * All results go to a disk cache.

---

## 3. Constraints that shape the design

1. **GE Lua has no internet** (`docs/ARCHITECTURE.md`, "Hard engine facts"). All routing and geocoding runs in `earthd`.
2. **One planner instance and a per-frame O(n) tracker.** Stock UI paths push every path point to the UI 4×/s (§1.2), and the minimap draws ≤3 000 points (§1.4). So the game should hold **≤ ~1 000 points**.
3. **Floating origin.** Every rebase changes the frame (rotation ~d/R plus translation). Positions held by the planner, the AI routes and the arrow GPS target must be remapped or re-sent.
4. **Navgraph reloads reset AI routes and the minimap road cache** (§1.4, §1.8).
5. **Physics exists only near the player** (one TerrainBlock follows the player car). An AI car more than ~1 km from the player has no ground. **AI on a long route therefore means "AI drives the player's car" or "AI rivals near the player"**, never cars hundreds of km away. **[I]** from the ARCHITECTURE TerrainBlock probes.
6. **Session length.** NY→LA is ~50 h of driving at real speed. The route state (route, progress `s`, stats) must survive game and server restarts.

---

## 4. Companion-side design (`earthd`)

### 4.1 Route model (float64, lat/lon)

```
Route { id, rev, dest{lat,lon,label}, created, source(url, attribution)
        lat[], lon[]           # N points (OSRM full overview, 34 642 for NY-LA)
        osm[]                  # OSM node id per point (annotations=nodes), may be None
        cum[]                  # cumulative geodesic metres, cum[0]=0
        segDur[]               # OSRM expected seconds per segment (annotations=duration)
        steps[]                # {s (along-route m), type, modifier, name, ref, destinations, exits, exitNo, lat, lon, bearing_after}
        legs/waypoints }
```

* Memory is ~2 MB for NY→LA. It is persisted to `<cache>/routes/<id>.json.gz` together with the progress state `{s, lastPoseAt, driven_m, driven_s}`.
* Step `s` is the cumulative distance at the step's first geometry index. Find it by walking `steps[].geometry` lengths, or by nearest-point search on `maneuver.location`.

### 4.2 Tracking (on each `pose`, 10 Hz, already received: `server/earthd.py:620,773`)

1. Convert the car pose `(anchorId, x, y, z)` to lat/lon with the active anchor's `EnuFrame.enu_to_geodetic` (`server/geodesy.py:83`).
2. **Map matching to the route:**
   * Search segments `i ∈ [k-50, k+400]` around the last match `k`, i.e. ~±few km.
   * Use a local tangent-plane projection: cross-track `e`, along-track `s = cum[i] + t·len_i`.
   * Penalise heading mismatch: `|bearing_seg − heading| > 100°` means "wrong way".
3. **Off-route** when `e > 35 m` for more than 3 s, or wrong-way for more than 5 s, and speed > 2 m/s. Hysteresis: back on route at `e < 20 m`.
   * The stock threshold is 18 m (`route.lua:6`), but OSM centrelines of wide roads and our lane offset need slack.
4. **Progress:**
   * `remain = cum[N-1] − s`.
   * `eta_osrm = Σ segDur[i..]`, with a partial segment.
   * `eta = eta_osrm × clamp(f, 0.6, 1.6)`, where `f` = (player's actual time on the last 30 driven km) / (OSRM time for the same km), updated only while on route and moving.
   * Also report `eta_osrm` raw. Arrival is local wall-clock plus `eta`, shown in the destination's time zone (later).
5. **Next manoeuvre:** first step with `step.s > s + 5`. Distance = `step.s − s`. Announce thresholds at 2 km, 500 m and 150 m for highways (`ref` starts with I/US or `maneuver.type` is off ramp/fork/merge) and at 300/100 m otherwise.
6. **Arrival:** `remain < 30 m` and speed < 3 m/s, or `remain < 10 m`. Then send `gps_arrived` and clear.

### 4.3 Windowing into the anchor frame

* **Window** = `[s − 300 m, s + W]` with `W = 15 km`. That is above the 10 km rebase distance, so a window always covers the next rebase, and it is enough for the minimap at any zoom you would use while driving.
* **Resample:**
  * Keep every OSM vertex.
  * Insert points so no segment exceeds **50 m** (measured 349 median / 824 max points per window, §2.1).
  * A 6 km straight segment as a great-circle arc in ENU sags d²/8R = 0.7 m mid-chord, and terrain varies too, so long chords need intermediate points for z anyway.
* **Transform:** `EnuFrame(anchor).geodetic_to_enu(lat, lon, h)` (`server/geodesy.py:86`), where `h` = DEM height at the point **+ 0.3 m**. The DEM is the same one the terrain and mesh tiles are built from, so the z agrees with the ground to centimetres away from bridges. For bridges and tunnels, take z from the road mesh builder (OSM `bridge=*` / `layer`) once roads exist.
* **Lane offset (optional, later):** shift points right by `(lanes/2 − 0.5)·3.5 m` on two-way roads. The stock groundMarkers draw on navgraph centrelines, so plain centrelines are acceptable for v1.
* **Re-send triggers:**
  * (a) new route or re-route;
  * (b) progress: `s − window.s0 > 5 km`, so the window always has ≥10 km ahead;
  * (c) `commit_anchor`: send the window for the new anchor immediately after `anchor_ready` and before the mod commits, so it is ready at the commit, the same way terrain is prepared;
  * (d) player teleport.
* **Payload:** ~400 points × (x,y,z, s) as JSON numbers with 2 decimals is about 20 KB. Even 1 000 points is under 50 KB; one frame's parse is ~1 ms **[I]**.

### 4.4 Re-routing

* **Strategy:** do not re-plan 4 000 km on every miss. Route from the current pose to a **rejoin point** on the original route and splice the result in.
  * Rejoin = first route point with `s_r ≥ s + max(20 km, 3·e)` on a road class at least as high as the current one. Prefer the next motorway on-ramp from steps.
  * If the player has strayed more than 50 km from the route, or the rejoin attempt fails twice, re-plan to the destination.
  * The bearing parameter (`bearings=H,45;`) keeps OSRM from planning an immediate U-turn on a divided highway.
* Splice: `newRoute = detour (cum shifted) + original[s_r:]`, recompute `cum`, `rev += 1`, then send `gps_route` and `gps_window`.
* Rate: ≤1 routing request/s globally (token bucket); one re-route in flight; a 10 s cool-down after a re-route. The cache key is the rounded request URL.
* Cost: detour requests are short, so latency is ~0.2–0.4 s **[I]**. The full NY→LA request took 0.87–1.05 s **[V]**.

### 4.5 Instruction text (OSRM steps → English)

A small table, modelled on Project-OSRM's `osrm-text-instructions` (https://github.com/Project-OSRM/osrm-text-instructions):

* `depart`: "Head {dir} on {name|ref}"
* `turn` + modifier: "Turn {modifier} onto {name}"
* `new name`: hidden unless the `ref` changes
* `merge`: "Merge {modifier} onto {ref name}"
* `on ramp`: "Take the ramp {modifier} toward {destinations}"
* `off ramp`: "Take exit {exits} toward {destinations}"
* `fork`: "Keep {left|right} toward {destinations|ref}"
* `end of road`: "Turn {modifier} at the end of the road"
* `roundabout` / `rotary`: "At the roundabout take the {exit}th exit"
* `continue`: "Continue on {name}"
* `arrive`: "You have arrived"

Units follow the game setting (`translateDistance`, imperial or metric). Long legs read "Continue on I 80 W for 512 km".

### 4.6 Geocoding endpoint

* Photon client with a 400 ms debounce, `lat/lon` bias = player position, and `limit=8`.
* Nominatim client: 1 req/s, explicit search plus reverse.
* Both cache to disk. Results are returned to the mod as `{label, lat, lon, kind}`.

---

## 5. Mod-side design (`beamngEarth_gps`)

### 5.1 Responsibilities

* Request and clear routes and send search queries, from the imgui window and later from the world-map GUI.
* Install each `gps_window` into `core_groundMarkers.routePlanner`.
* On rebase, remap the installed path with the rebase transform at once, so nothing jumps for a frame, and wait for the server's new-frame window.
* Reset the minimap road cache after navgraph reloads.
* Drive AI (autopilot) with node lists.
* Draw the HUD: next manoeuvre, distance, remaining km, ETA. Use our imgui window first and a small Vue app later. Optionally `ui_arrowGPS.setTarget('beamngEarth', 10, {pos = nextManeuverPos})`.

### 5.2 Installing a window into the stock GPS

On `gps_window` (fields in §6):

```lua
local gm = core_groundMarkers
local rp = gm.routePlanner
local C  = getmetatable(rp)              -- the route class (route.lua:453-458)
local active, pending, tail = false, nil, 0   -- tail = metres from window end to destination

-- install overrides once (instance fields shadow class methods)
rp.setupPathMulti = function(self, positions)
  if not pending then return C.setupPathMulti(self, positions) end   -- other game systems still work
  local path = {}
  for i = 1, #pending.pts / 3 do
    local j = 3*i - 2
    path[i] = { pos = vec3(pending.pts[j], pending.pts[j+1], pending.pts[j+2]),
                wp = pending.wp and pending.wp[i] or nil,                 -- see 5.4
                linkCount = pending.wp and pending.wp[i] and map.getNodeLinkCount(pending.wp[i]) or nil,
                fixed = (i == #pending.pts/3 and pending.destInWindow) or nil }
  end
  self.path = path
  self:calcDistance()
end
rp.calcDistance = function(self)
  local d = C.calcDistance(self)
  if active and self.path[1] then
    for _, e in ipairs(self.path) do e.distToTarget = e.distToTarget + tail end
    self.distance = self.path[1].distToTarget
    return self.distance
  end
  return d
end
rp.recalculateRoute = function(self, pos)
  if not active then return C.recalculateRoute(self, pos) end
  -- no-op: the companion decides off-route and re-routes (it already gets the pose at 10 Hz)
end

-- per window:
pending, tail, active = msg, msg.tailM, true
gm.setPath(vec3(lastX, lastY, lastZ), { clearPathOnReachingTarget = false, step = 3 })
pending = nil
```

* `setPath` then runs the normal bookkeeping: decal pool, colour, `endWP`, arrow pool, `trackVehicle`, `sendToApp`. Only path finding is replaced. **[V]** by reading `groundMarkers.lua:246-309`; untested (probe G1).
* `calcDistance` with the `tail` offset makes these show the **true remaining route distance**: the stock distance label (`additionalInfo.lua:24`), the big map (`bigMapMode.lua:384`) and `getPathLength` (`groundMarkers.lua:43-48`). It also stops `markerInteraction` from declaring arrival at the end of the window. `fixStartEnd` keeps the offset (§1.1).
* Clearing: `active = false; gm.setPath(nil)`. Overrides stay installed but delegate to the class, so missions and career routes keep working.

### 5.3 Rebase handling

`rebase.lua` already applies `xf:apply(x,y,z)` to vehicles (`mod/.../rebase.lua:62-76`). The GPS module registers a callback in the same commit:

* For each `e` in `rp.path`: `e.pos = vec3(xf:apply(e.pos.x, e.pos.y, e.pos.z))`. Do the same for the arrow GPS target and the cached window.
* Do not call `setPath` here, so there is no visual pop. The server's new-anchor window replaces this path within a second.
* Because `map.reset` runs in the same rebase ("rebuilds collision and the navgraph once", ARCHITECTURE), call `ui_apps_minimap_roads.reset()` and re-issue the AI paths (§5.5) after it.

### 5.4 Aligning with the local road meshes and navgraph

* The navgraph agent builds nodes from OSM. If it **names nodes after OSM node ids**, the window can carry `wp[i] = "osm<id>"` for each route point that is a navgraph node, taken from OSRM `annotations=nodes`.
  * Suggested convention for split nodes: `osm<id>`, or `osm<id>_<k>`.
  * The game then gets junction arrows (§1.3) and exact AI node lists for free.
  * Points inserted by densifying get `wp=nil`.
  * A navgraph that merges nodes (RDP simplification, `map.lua:660-704`) still keeps the junctions, and junctions are the only places arrows need.
* If the local navgraph and the route disagree (data vintage differs: the OSRM server's OSM date versus our extract), the server computes the window from the route geometry anyway. The mod checks `map.getMap().nodes[wp]` and drops unknown `wp`s.
* Positions come from the same lat/lon→ENU transform and the same DEM as the road meshes, so the route lies on the road mesh centreline to within the OSM-version difference.

### 5.5 AI following the long route

* **Autopilot for the player car (supported):**
  * When AI-drive is toggled, the mod asks the server for `gps_ai_nodes` (the `wp` list for the current window, from the car's edge onward).
  * It sends `veh:queueLuaCommand("ai.driveUsingPath{path=" .. serialize(nodes) .. ", driveInLane='on', avoidCars='on', routeSpeedMode='legal', aggression=0.3}")`.
  * Every ~5 km it sends `ai.setPath({lastNode, ...next nodes})`. `pathExtend` appends only if the first node equals the AI's current last node (`ai.lua:977-985`), so the server must start each chunk at the previous chunk's last node.
  * After every `map.reset` (rebase or navgraph refresh) the AI has dropped its route (`ai.lua:5137-5139`). Re-issue `driveUsingPath{path = remaining nodes from the car's current edge}`.
* **Without an OSM navgraph yet (bootstrap):**
  * Build a **corridor navgraph** from the route window: a one-way chain `gps1 → gps2 → …` with `radius = 4`, `lanes='+'`, `oneWay=true`, `speedLimit` from OSRM `annotation.speed` capped at 35 m/s, and the same `data` stored on both nodes (§1.7). Load it with `map.reset(nodes)`.
  * Stock groundMarkers, the minimap road layer and AI `path` driving then all work on the route alone.
  * It conflicts with the navgraph agent's `map.reset`. Once a real navgraph exists, merge the corridor into it or drop it.
* **Do not use** `driveUsingPath{script=...}`: it teleports (§1.8).
* **AI rivals (Cannonball race):** feasible only while they stay within the physics bubble (§3.5). Despawn and re-spawn rivals ahead or behind as virtual racers simulated on the server: position along the route `s_ai(t)` from OSRM durations × a skill factor. Spawn a real AI car only when `|s_ai − s_player| < ~500 m`. **[I]**

### 5.6 HUD

* imgui section in `ui.lua`:
  * Destination search box, which sends `gps_search` and shows the list.
  * "Go" button, which sends `gps_route_request`.
  * Next manoeuvre text and distance, remaining distance, ETA, and the OSRM/OSM attribution.
* Later: a Vue app `mod/beamng_earth/ui/modules/apps/BeamngEarthNav/app.vue` streamed via `guihooks.queueStream('beamngEarthNav', {...})`.
* Big map: implement `M.onSetBigmapNavFocus(pos)`. If `pos` is set, convert it to lat/lon (mod geodesy or the server) and send a `gps_route_request` with `dest = {anchorId, x, y, z}`; the server converts it. Then set our window as normal.

---

## 6. Protocol messages (JSON over the existing framed TCP, `server/protocol.py`)

Mod → server:

| type | fields |
|---|---|
| `gps_search` | `requestId, q, near:{lat,lon}?, final:bool` (`final` = Nominatim allowed) |
| `gps_reverse` | `requestId, lat, lon` |
| `gps_route_request` | `requestId, dest:{lat,lon,label}` or `dest:{anchorId,x,y,z}`, `via:[{lat,lon}]?`, `avoid:["toll","ferry","motorway"]?`, `resume:bool` |
| `gps_clear` | `{}` |
| `gps_ai_nodes` | `requestId, fromNode?, maxKm` (node list for the autopilot) |
| (existing) `pose` | already carries `anchorId,x,y,z,vx,vy` at ~10 Hz; add `heading` if absent |

Server → mod:

| type | fields |
|---|---|
| `gps_search_result` | `requestId, results:[{label, lat, lon, kind}]`, `attribution` |
| `gps_route` | `routeId, rev, dest:{lat,lon,label}, totalM, durationS, summary, steps:[{s, text, type, modifier, ref, exit}]` (all steps, small), `attribution` |
| `gps_window` | `routeId, rev, anchorId, s0, pts:[x,y,z,...]` (flat, anchor frame), `ss:[s...]` (along-route m per point), `wp:["osm123",false,...]?`, `tailM` (window end → destination), `destInWindow` |
| `gps_progress` (2 Hz) | `routeId, s, remainM, etaS, etaOsrmS, xtrackM, onRoute, next:{text, distM, type, modifier, x,y,z}` |
| `gps_reroute` | `routeId, reason` ("offroute", "wrongway", "user"), followed by `gps_route` and `gps_window` |
| `gps_arrived` / `gps_error` | `routeId` / `requestId, error` |
| `gps_ai_nodes_result` | `requestId, anchorId, nodes:[...]` |

Ordering rule: a `gps_window` with an `anchorId` other than the mod's active anchor is cached and installed at that anchor's commit. This is the same pattern as terrain and far tiles.

---

## 7. Files to add or change (when implementation is approved)

| File | What |
|---|---|
| `server/routing.py` (new) | OSRM client (urllib, UA, 1 req/s token bucket, gz disk cache), polyline6 decode, `Route` model, tracking/projection, window resample and transform, re-route splice, persistence |
| `server/geocode.py` (new) | Photon and Nominatim clients, debounce, cache, attribution |
| `server/instructions.py` (new) | OSRM step → text (§4.5) |
| `server/earthd.py` | Handlers for `gps_*`; call `routing.on_pose` from `on_pose` (`:773`); after `anchor_ready` / `commit_anchor` (`:673`, `:728`), emit the window for the new anchor |
| `server/tests/test_routing.py` | Uses the stored NY→LA fixture (`scratchpad/research2/gps/dl/osrm.json`, copied into `server/tests/fixtures/`): decode, cumulative length (4 489.9 km geodesic vs 4 496.9 OSRM), window sizes, projection, splice |
| `mod/.../beamngEarth/gps.lua` (new) | Window install (§5.2), rebase remap (§5.3), minimap road reset, AI feed (§5.5), arrow GPS |
| `mod/.../beamngEarth/core.lua` | Route `gps_*` messages to gps.lua; call `gps.onRebase(xf)` inside the rebase commit; draw the GPS section through `ui.lua` |
| `mod/.../beamngEarth/ui.lua` | Search box, results, route summary, next manoeuvre, ETA, attribution |
| `docs/V1_x_SPEC.md` | Spec for this feature |

---

## 8. Risks

1. **Public server availability and policy.** No SLA, ≤1 req/s, non-commercial only. Mitigation: configurable base URL with a fallback list, a disk cache, and a self-host recipe. If the mod is ever distributed widely, the public instances could see real load; document self-hosting and keep usage minimal.
2. **OSM data mismatch.** The OSRM server's OSM date differs from our road extract. Node ids may vanish (deleted or split ways) and geometry may differ by metres. Mitigation: geometry-first window, `wp` best-effort, tracking tolerance 35 m.
3. **Overriding instance methods of `core_groundMarkers.routePlanner`.** Fragile across game updates. If BeamNG adds new route-planner callers, or recreates the instance (it is created once at module load, `groundMarkers.lua:14`; a Lua reload of `core_groundMarkers` creates a new one), the overrides are lost. Mitigation: re-install when `rawget(rp, 'recalculateRoute')` is missing, checked every second.
4. **Z of decals on bridges, tunnels and stacked interchanges.** DEM z puts markers under bridges. This needs the road mesh's z once roads exist; until then, ray-cast down from DEM+20 m inside the physics bubble.
5. **Re-route thrash** at complex interchanges. Mitigation: hysteresis, 10 s cool-down, the bearing parameter, and rejoin-point splicing.
6. **AI route resets on every navgraph reload.** That happens every rebase (~every 10 km, ~5 min at highway speed) and every navgraph window refresh. Re-issuing is cheap, but the AI may brake briefly while it re-plans. Measure it (probe A2).
7. **AI far from the player has no ground** (single TerrainBlock). Long-distance AI rivals must be virtual.
8. **Performance.** `updatePathForPos` scans O(n) per frame when off-route, and `sendToApp` pushes all points 4×/s. Keep windows ≤1 000 points (measured max 824 at 50 m spacing, 15 km).
9. **Licensing/attribution.** OSM ODbL attribution plus "Routing: OSRM (FOSSGIS / Project-OSRM)" plus "Search: Photon / Nominatim" must be visible while the features are active (FOSSGIS about page; Nominatim policy).

---

## 9. In-game probes to run later

These go through MCP `run_lua`, **only when the user allows it**. Keep the camera on the car and zero all inputs afterwards. Every probe only reads, or touches the GPS route and AI of the player's own car.

**G1: install an arbitrary position list as the stock route.** Expect: decals and the minimap line along a straight 2 km line ahead, and the minimap label showing ~4002 km.

```lua
local gm, veh = core_groundMarkers, getPlayerVehicle(0)
local rp = gm.routePlanner; local C = getmetatable(rp)
local p0 = veh:getPosition(); local f = veh:getDirectionVector(); f.z = 0; f:normalize()
local pts = {}
for i = 0, 100 do
  local p = p0 + f * (i * 20)
  local d = castRayStatic(p + vec3(0,0,60), vec3(0,0,-1), 300)
  p.z = p.z + 60 - d + 0.3; pts[#pts+1] = p
end
local TAIL = 4000000
rp.setupPathMulti = function(self) local path = {} for i, p in ipairs(pts) do path[i] = {pos = vec3(p)} end self.path = path; self:calcDistance() end
rp.calcDistance = function(self) C.calcDistance(self) for _, e in ipairs(self.path) do e.distToTarget = e.distToTarget + TAIL end self.distance = self.path[1] and self.path[1].distToTarget or 0 return self.distance end
local lastLog = 0
rp.recalculateRoute = function(self, pos) if os.clock() - lastLog > 1 then lastLog = os.clock(); log('I', 'gpsprobe', 'offroute ' .. tostring(pos)) end end
gm.setPath(pts[#pts], {clearPathOnReachingTarget = false})
return {n = #rp.path, d0 = rp.path[1].distToTarget, endWP = gm.currentlyHasTarget()}
-- cleanup: rp.setupPathMulti = nil; rp.calcDistance = nil; rp.recalculateRoute = nil; gm.setPath(nil)
```

**G2: no navgraph re-routing.** Drive or teleport 40 m sideways. Expect `gpsprobe offroute` lines in the log, the path unchanged, and no `route calculated` log line (`route.lua:9-11`).

**G3: cost.** With an 800-point path (step 19 m over 15 km):
```lua
local t = hptimer(); for i = 1, 100 do core_groundMarkers.routePlanner:updatePathForPos(getPlayerVehicle(0):getPosition() + vec3(100, 0, 0)) end; return t:stop() / 100
```
This measures the off-route full scan. Also check frame time with the Navigation app open (`sendToApp`).

**G4: rebase remap.** After a real rebase, verify `rp.path[1].pos` is within 1 m of the car and the decals are continuous: `return rp.path[1].pos:distance(getPlayerVehicle(0):getPosition())`.

**N1: corridor navgraph through `map.reset`.** Expect `map.getMap().nodes` count = 101 and `map.getPointToPointPath(p0, pts[#pts])` with ≥2 nodes.
```lua
local nodes = {}
for i, p in ipairs(pts) do nodes['gps'..i] = {pos = vec3(p), radius = 4, links = {}} end
for i = 1, #pts - 1 do
  local a, b = 'gps'..i, 'gps'..(i+1)
  local d = {drivability = 1, oneWay = true, lanes = '+', speedLimit = 30, inNode = a, outNode = b,
             inPos = nodes[a].pos, outPos = nodes[b].pos, inRadius = 4, outRadius = 4}
  nodes[a].links[b] = d; nodes[b].links[a] = d
end
map.reset(nodes); ui_apps_minimap_roads.reset()
local cnt = 0 for _ in pairs(map.getMap().nodes) do cnt = cnt + 1 end
return {nodes = cnt, path = #map.getPointToPointPath(pts[1], pts[#pts])}
```
This is destructive for the level's navgraph until a reload, which is fine on the Earth level because it has none.

**A1: AI follows a node list and extends it.** The player car drives itself, at low speed.
```lua
local v = getPlayerVehicle(0)
local first = {} for i = 1, 50 do first[i] = 'gps'..i end
v:queueLuaCommand("ai.driveUsingPath{path=" .. serialize(first) .. ", routeSpeed=15, routeSpeedMode='limit', driveInLane='off', avoidCars='off'}")
-- ~20 s later:
local nxt = {} for i = 50, 101 do nxt[#nxt+1] = 'gps'..i end
v:queueLuaCommand("ai.setPath(" .. serialize(nxt) .. ")")
-- verify with v:queueLuaCommand("ai.dumpCurrentRoute()") in the log; end with:
-- v:queueLuaCommand("ai.setMode('disabled')"); then zero inputs: v:queueLuaCommand("input.event('throttle',0,1); input.event('brake',0,1)")
```

**A2: navgraph reload drops the AI route.** While A1 drives, run `map.reset(nodes)` again. Expect the AI to stop following (`currentRoute=nil`, `ai.lua:5137`). Re-issue `driveUsingPath` with the remaining nodes, and measure the speed dip.

**B1: big map hook.** Add a temporary extension function `onSetBigmapNavFocus(pos)` (log only), click inside the bubble, and confirm `pos` arrives before `setPath`.

**M1: minimap override.** Return a test route from the `onMinimapRouteOverride` hook and confirm it draws while groundMarkers has no path. This is the option for showing the GPS line on the minimap without touching the planner.

---

## 10. Implementation plan (ordered)

1. **Server routing core (no game needed).** `routing.py` + `instructions.py` + tests on the NY→LA fixture: decode, cumulative length, resample (≤50 m), projection, ETA, splice, persistence. Add an offline `tools/` script that prints a simulated drive's progress and instructions.
2. **Protocol and handlers.** `gps_route_request`, `gps_route`, `gps_window` (anchor frame, re-emitted at `anchor_ready`/`commit`), `gps_progress`, `gps_clear`, `gps_arrived`. The 1 req/s client and the cache go behind a config base URL: FOSSGIS by default, OSRM demo as fallback.
3. **Mod `gps.lua` v1.** Install windows via the planner overrides (§5.2), remap on rebase, show next manoeuvre, remaining distance and ETA in the imgui window, plus attribution. Run probes G1–G4 first.
4. **Search.** `gps_search` (Photon, debounced) and the result list in imgui; big map `onSetBigmapNavFocus` handoff; reverse geocode for the location label.
5. **Re-routing.** Off-route detection, rejoin-point detours, the bearing parameter, cool-down.
6. **Navgraph alignment.** With the navgraph agent's OSM node naming, fill `wp[]` from `annotations=nodes` → junction arrows. Reset the minimap road cache on `onNavgraphReloaded`.
7. **Autopilot AI.** Corridor navgraph (bootstrap) or the real navgraph, `driveUsingPath{path}`, chunked `ai.setPath`, re-issue after each reload (probes N1, A1, A2).
8. **World map GUI integration.** The world map (other agent) sends `gps_route_request` with lat/lon and draws `gps_route` geometry, which the server down-samples per zoom.
9. **Optional.** Self-hosted Valhalla or OSRM profile for heavy users; virtual AI rivals for Cannonball races; voice prompts via the game's audio or `ui_message`.

---

## Sources

* Game code: `G/lua/ge/extensions/gameplay/route/route.lua`, `G/lua/ge/extensions/core/groundMarkers.lua`, `G/lua/ge/extensions/core/groundMarkerArrows.lua`, `G/lua/ge/extensions/ui/apps/minimap/{route,roads,additionalInfo,minimap,utils}.lua`, `G/ui/modules/apps/Navigation/app.vue`, `G/lua/ge/extensions/freeroam/bigMapMode.lua`, `G/lua/ge/map.lua`, `G/lua/vehicle/ai.lua`, `G/lua/ge/ge_utils.lua`, `G/lua/ge/extensions/ui/arrowGPS.lua`, `G/lua/ge/extensions/ui/uiNavi.lua`, `G/lua/ge/extensions/gameplay/markerInteraction.lua`, `G/lua/vehicle/controller/gauges/customModules/navigationData.lua`.
* OSRM demo policy: https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server
* OSRM HTTP API: https://raw.githubusercontent.com/Project-OSRM/osrm-backend/master/docs/http.md
* OSRM resources: https://github.com/Project-OSRM/osrm-backend/wiki/Disk-and-Memory-Requirements
* FOSSGIS routing: https://routing.openstreetmap.de/about.html
* Valhalla API: https://valhalla.github.io/valhalla/api/route/api-reference/
* Valhalla docker: https://raw.githubusercontent.com/valhalla/valhalla/master/docker/README.md
* Valhalla limits: https://raw.githubusercontent.com/valhalla/valhalla/master/scripts/valhalla_build_config (lines 320-326)
* Valhalla build effort: https://github.com/valhalla/valhalla/discussions/3197, https://github.com/valhalla/valhalla/issues/5099, https://github.com/valhalla/valhalla/discussions/3661
* GraphHopper pricing: https://www.graphhopper.com/pricing/
* openrouteservice: https://openrouteservice.org/plans/, https://openrouteservice.org/restrictions/
* Nominatim policy: https://operations.osmfoundation.org/policies/nominatim/
* Photon: https://github.com/komoot/photon
* Geofabrik US: https://download.geofabrik.de/north-america/us.html
* Measured responses and the decode script: `/tmp/claude-1000/-home-tecnagamer-Documents-BeamNG-Earth/b02246e0-198a-4d55-8cba-7ac6107ad43e/scratchpad/research2/gps/` (`dl/osrm.json`, `dl/fossgis.json`, `dl/valhalla.json`, `an.py`, `win.py`).
