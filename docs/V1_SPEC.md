# BeamNG.Earth v1 — build spec

Read `docs/ARCHITECTURE.md` first (especially "Phase 0 probe results"). This
file is the contract between the companion server (`server/`) and the mod
(`mod/`). Both sides must follow it exactly.

## Why terrain-based ground (measured 2026-10-09, see ARCHITECTURE.md)
- A TerrainBlock created at runtime (`TerrainBlock()` + `importMaps`) is real ground for vehicles.
  `be:reloadCollision()` with a 2048² terrain costs **7–10 ms**, versus 160+ ms for 0.5M mesh tris.
- `importMaps` of a 2048² 16-bit PNG: ~190–213 ms (one-time per anchor).
- `tb:setHeight(gx, gy, h)` costs ~0.1 µs per sample, and `updateGrid(min,max)` ~1.7 ms per 128² region.
  Edits reach physics only after `be:reloadCollision()`.
- A render-disabled TerrainBlock (`setRenderEnabled(false)`) **still collides**, so visuals can later be replaced
  by our own textured meshes.
- **When a TerrainBlock exists, smallgrid's GroundPlane no longer collides for vehicles.** Our level must not rely on it.
- PNG orientation for `importMaps(..., flipY=false)`: **PNG row 0 = the NORTH edge (max world y)**,
  column 0 = west edge. Grid index (gx, gy) for setHeight: gx along +x (east), gy along +y (north),
  relative to the block's position (its SW corner).
- Heights are uint16 over [0, maxHeight] above the block's z position.

## World frame
- Game world = local ENU frame of the current **anchor** (lat0, lon0, h=0 on the WGS84 ellipsoid).
  +x = east, +y = north, +z = up (ellipsoid normal at the anchor). Units are metres.
- A world point (e, n, u) maps to ECEF via the standard ENU→ECEF transform at the anchor, in float64.
- Curvature comes out naturally: the ground at horizontal distance d sits ≈ d²/(2R) lower in z.

## Terrain block (near, drivable ground)
- `size` = 2048 samples per side, `squareSize` = 2.0 m, so it spans 4096 m.
- Block position = (-size*squareSize/2, -size*squareSize/2, zBase). The block is centred on the anchor.
- Grid sample (gx, gy) sits at world (x, y) = (-4096/2 + gx*2, -4096/2 + gy*2).
- Height for a sample is computed by the server:
  1. P = ENU→ECEF(x, y, 0).
  2. (lat, lon) = geodetic(P), ignoring its h.
  3. elev = DEM(lat, lon) in metres above the ellipsoid (treat DEM orthometric heights as ellipsoidal in v1).
  4. S = geodetic→ECEF(lat, lon, elev).
  5. u = ECEF→ENU(S).z
  The heightmap value is u. Ignore the tiny horizontal shift of S.
- zBase = floor(min(u)) - 5. maxHeight = max(50, ceil(max(u) - zBase) + 5).
  The PNG stores round((u - zBase) / maxHeight * 65535) as a 16-bit grayscale, row 0 = north.

## Far field (render-only, beyond the block)
- TSStatic objects with `collisionType = "None"`, whose shapeName points to server-written `.dae` files.
- The vertices are true ENU positions, so curvature is built in. Each DAE's vertices are
  relative to the tile's own origin `pos`, which the mod sets via `setPosition`.
  The mod applies no rotation.
- Rings (v1): tiles of 1024 m with 32×32 cells (32 m spacing) out to 8 km from the anchor.
  Then tiles of 4096 m with 32×32 cells (128 m spacing) out to ~40 km. The square inside the
  terrain block (|x|,|y| < 2048) is skipped. Far tiles overlapping the block edge are lowered 3 m
  so the terrain wins where both exist.
- Each tile ≤ 8 192 tris. Write .tmp and then rename (atomic). Use a unique file name per anchor + tile key,
  because the engine caches shapes by path.
- Material: a flat land colour with simple slope/height tinting is fine for v1. Water (elev ≤ 0.5 m and
  flat) is blue-ish.

## Floating origin / rebase
- When the player vehicle is more than **1200 m** (horizontal) from the world origin, the mod asks the
  server for a new anchor at the player's current geodetic position.
  - When `anchor_ready` arrives: compute the exact new coordinates of every vehicle, with geodesy in Lua
    doubles (ENU_old → ECEF → ENU_new). Translate each vehicle with
    `veh:setClusterPosRelRot(-1, x, y, z, 0, 0, 0, 1)`; a rotation of d/R ≈ 0.01° is ignored in v1.
  - `importMaps` the new heightmap, `setPosition` the block, `be:reloadCollision()`. Move the camera by the same delta.
  - Translate the old far tiles by the same delta. Once the new anchor's far tiles have arrived, delete the old ones.
- Pre-fetch: start `prepare_anchor` once the player passes 900 m, so the PNG is ready by 1200 m.
  The commit happens at ≥1200 m, or immediately if the PNG is already ready by then.

## Transport
- TCP on **127.0.0.1:47613**. The server listens and the mod connects (luasocket, `settimeout(0)`,
  non-blocking, reconnect every 2 s).
- Frame = 4-byte little-endian uint32 length + UTF-8 JSON payload. (Binary frames are reserved for later.)
- The mod parses lengths with `ffi.new('uint32_t[1]')` + `ffi.copy`, or plain `string.byte` math.
  **`ffi.cast` is a stub under BeamNG's sandbox. Don't use it.**
- Bulk data travels as files written by the server into the BeamNG user folder:
  `~/.local/share/BeamNG/BeamNG.drive/current/temp/beamngEarth/<sessionId>/...`
  The game sees that folder as VFS path `/temp/beamngEarth/<sessionId>/...`.
  The server is told the user folder via CLI flag `--user-dir` (default above), and sends VFS paths in messages.

### Messages (mod → server)
- `{"type":"hello","protocol":1,"modVersion":"0.1.0"}`
- `{"type":"prepare_anchor","requestId":N,"lat":deg,"lon":deg}`
- `{"type":"pose","anchorId":N,"x":m,"y":m,"z":m,"lat":deg,"lon":deg,"speed":mps}` at ~2 Hz. The server uses it to
  prioritise far tiles. Far tiles are generated for the latest committed anchor that the mod reports in pose.anchorId.
- `{"type":"commit_anchor","anchorId":N}`: the mod has switched to this anchor, so the server should stream far tiles for it.

### Messages (server → mod)
- `{"type":"hello","protocol":1,"serverVersion":"0.1.0","sessionId":"..."}`
- `{"type":"status","text":"..."}`: progress text for the UI.
- `{"type":"anchor_ready","requestId":N,"anchorId":N,"lat":deg,"lon":deg,"heightmap":"/temp/beamngEarth/<sid>/hm_<anchorId>.png","size":2048,"squareSize":2.0,"zBase":m,"maxHeight":m,"groundZ":m}`
  `groundZ` = terrain height (ENU z) at the anchor point, used to place the vehicle on teleport.
- `{"type":"anchor_error","requestId":N,"error":"..."}`
- `{"type":"far_tile","anchorId":N,"key":"...","shape":"/temp/beamngEarth/<sid>/far_<anchorId>_<key>.dae","pos":[x,y,z]}`
- `{"type":"far_done","anchorId":N,"count":K}`: all far tiles for that anchor have been sent.

## Data sources (no API keys)
- DEM primary: **Mapterhorn** `https://tiles.mapterhorn.com/{z}/{x}/{y}.webp`. This is Terrarium encoding,
  elevation = (R*256 + G + B/256) - 32768, with 512 px tiles; it is z≤12 globally and deeper in many regions.
  Verify the tile size and max zoom at runtime, and fall back on a 404.
- DEM fallback: **AWS Terrain Tiles** `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`
  (256 px, z≤15, global).
- Both are Web Mercator (±85.05°). Beyond that, v1 returns sea level 0 (polar sources come later).
- Disk cache: `~/.cache/beamng-earth/dem/<source>/<z>/<x>/<y>.<ext>`. Concurrent fetches go through a small
  thread pool. Send a polite User-Agent "BeamNG.Earth/0.1 (+personal mod)".
- Attribution text (show in the mod UI): "Elevation: Mapterhorn (CC-BY etc., see mapterhorn.com), AWS Terrain Tiles / Mapzen".

## Mod UI (v1)
- An imgui window "BeamNG.Earth" showing:
  - Connection status, current anchor lat/lon, player lat/lon, and distance to the rebase threshold.
  - Lat/lon input fields (default 36.5785, -118.2923, near Mt Whitney/Lone Pine, CA) and a **Teleport** button.
    Teleport = prepare_anchor at that position, then on anchor_ready commit and place the player vehicle at
    (0, 0, groundZ + 1.0) with zero velocity (`spawn.safeTeleport`, or setPositionRotation + reset).
  - A status text line and the attribution text.
- On extension load in our level, delete or hide `GroundPlane` objects, set
  `scenetree.theLevelInfo.visibleDistance = 40000`, and `core_celestial`/TimeOfDay latitude & longitude
  to follow the player.
