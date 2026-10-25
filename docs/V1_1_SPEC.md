# BeamNG.Earth v1.1: decoupled terrain-follow, rare origin rebase, dynamic LOD far field

This supersedes the parts of `docs/V1_SPEC.md` it changes. Everything else in V1_SPEC still holds
(transport, framing, VFS paths, DEM sources, PNG orientation, winding, UI basics).

## Why (user feedback on v1, 2026-10-09)
- The origin rebase came every 1.2 km. Each one caused a ~250 ms stutter, the orbit camera swung in
  front of the car and back, and FPS stayed low for a few seconds while 556 far tiles re-loaded.
- BeamNG copes fine far from the origin. **Johnson Valley's boundary walls are 12.4 km from its origin, and
  Italy's backdrop meshes reach 15.8 km** (measured from the level files). So the origin can stay put for ~10 km.

## Measurements behind the design (in-game, 2026-10-09)
| | |
|---|---|
| `importMaps` into the existing block, with material + layer map | 2048²: 150–185 ms. **1024²: ~32 ms**. 512²: ~26 ms. Then `reloadCollision`: ~7 ms. |
| Without material / layer map | Saves only ~30 ms on 2048². With materials but an empty texture-map list, `importMaps` returns false. |
| Terrain edge | A block of N samples at spacing s has ground (collision) only on **[x0, x0 + (N-2)·s]**. Beyond that, `getHeight` returns the block z and rays miss. There is no wrap. |
| TSStatic `.dae` far tile load (main thread, no caching) | 512 tris ~3 ms, **2048 tris ~7.5 ms**, 8192 tris ~26 ms. |
| Terrain edits via setHeight/updateGrid | Physics updates by itself within ≤0.5 s, no reload needed. |

## 1. Two separate mechanisms
### 1a. Terrain-follow: frequent, cheap, same anchor
- The physics/near-render TerrainBlock has **N = 1024 samples**, with `squareSize s = 2048/1022 m (≈2.00391)`, so the
  valid area is exactly **2048 m × 2048 m**: [cx-1024, cx+1024] × [cy-1024, cy+1024].
  Block position = (cx - 1024, cy - 1024, zBase). Sample (gx,gy) is at (cx-1024+gx·s, cy-1024+gy·s). The last
  sample row and column (gx or gy = 1023) are beyond the valid area; fill them by repeating the edge.
- **The block centre (cx, cy) is always a multiple of 256 m** in the current anchor's ENU plane.
- The mod requests a new terrain when the player is **> 300 m** from the block centre (Chebyshev distance).
  The target centre is snap256(player + velocity·4 s), clamped so the player stays ≥ 600 m from every edge.
  It commits when the player is **> 450 m** from the current centre, or immediately if the new one is ready by then.
  Commit = `importMaps` + `setPosition` + `be:reloadCollision()`. Vehicles, camera and far tiles are **not** moved.
  Cost is about 40 ms.
- Heights are computed exactly as in V1 (ENU of the current anchor, curvature included). The block is axis-aligned in
  the anchor frame; at 10 km from the anchor the local tilt is 0.09°, which is negligible.
- zBase/maxHeight are per terrain, as in V1. The layer map must match N = 1024 (the mod ships a 1024² layer map).

### 1b. Origin rebase: rare, default every 10 km
- Triggers when the player's horizontal distance from the anchor origin is > **REBASE_DISTANCE = 10000 m**.
  It is configurable in the UI (2–25 km) and by console (`beamngEarth_core.setRebaseDistance(m)`).
- The new anchor = the player's geodetic position. Do the transform exactly in Lua doubles: R, t with
  p_new = R·p_old + t (old ENU → ECEF → new ENU). At 10 km R is a 0.09° rotation and **must be applied**,
  because far tiles reach 80 km out (ignoring it would put them ~130 m out vertically).
  - Vehicles: `setClusterPosRelRot(-1, p_new, q_rel)` with q_rel = the rotation R as a quaternion, so velocity is
    rotated consistently. If the engine doesn't rotate velocity, the error is 0.09°, which is acceptable. Also update the
    original/reset transform.
  - Every far-field TSStatic: new transform = R·T_old + t (use `setPosRot`/`setTransform`, never regenerate).
  - The terrain block: request a terrain for the new frame centred at snap256(player_new) **together with** the
    anchor (`anchor_ready` carries the first terrain of the new frame, as in V1). Commit all of the above in **one frame**.
  - **Cameras:** every camera mode must be shifted, not just the free camera. Find the engine's way to translate or
    re-seat the active camera without it re-smoothing from the old position. For example: how `spawn.safeTeleport`,
    `core_camera`'s `onVehicleTeleport`-like hooks, or the camera modes' reset handlers deal with teleports
    (grep lua/ge/extensions/core/camera*.lua and core/cameraModes/*). The orbit camera must stay behind the car with no swing.
- After the rebase, the server streams far tiles for the new anchor in the background. The old-frame tiles (already
  transformed) stay visible and are swapped out progressively as new ones arrive. Nothing disappears first.

## 2. Dynamic-LOD far field (render-only)
- A quadtree in the **current anchor's ENU plane**. Leaf tiles are aligned to a 256 m grid.
  - Levels: L0 = 256 m tiles, L1 = 512 m, … up to L9 = 131 072 m. Tile (L, i, j) covers
    [i·256·2^L, (i+1)·256·2^L) × [j·…).
  - Each tile is a 32×32-cell grid (2048 tris, ~7.5 ms to load), plus **skirts** on all 4 edges (a vertical curtain
    down by max(2 m, 0.02·tileSize), so ≤ 2048 + 4·64 tris). Vertices are true ENU positions relative to the tile
    origin (curvature included), with normals, as in V1.
- Selection (server, recomputed on every pose at ~2 Hz): refine a tile while distance(player, tile) < **K · tileSize**,
  with K = 2.0 (configurable) and min level L0. The far radius is 80 km.
  **Tiles completely inside the current terrain block's valid area are excluded.** Because both are 256 m-aligned,
  the block area is exactly a set of L0 tiles. Tiles on the block boundary get an **inner apron**: one extra cell
  (8 m) extending under the block, lowered by 1.5 m, so no sky shows through where terrain and tile edges differ slightly.
- The server sends diffs: `far_tile` (add) and `far_remove`. Ordering is nearest-first.
  The mod must **never create holes**:
  1. Process adds within a per-frame time budget (default 6 ms: at least 1 tile per frame, more if small).
  2. Apply removals only when the add-queue is empty (or after the replacing tiles for that area have loaded).
- Server-side tile cache key: (anchorId, L, i, j). Files are unique per key. Tiles of a superseded anchor are deleted
  only after the mod has confirmed the rebase and the new set has loaded (`far_done`).
- visibleDistance = 100 km. Verify there is no z-fighting or flicker far away with this; reversed-Z exists.

## 3. Protocol changes (protocol version 2)
mod → server:
- `{"type":"prepare_terrain","requestId":N,"anchorId":A,"cx":m,"cy":m}` (cx, cy multiples of 256)
- `{"type":"commit_terrain","anchorId":A,"cx":m,"cy":m}`: the server now excludes far tiles inside this block.
- `pose` gains `"vx","vy"` (m/s), and the server uses `anchorId` + `x,y,z` for LOD selection.
- `prepare_anchor` and `commit_anchor` are unchanged. `prepare_anchor` may carry `"cx","cy"` hints. The
  anchor's first terrain is centred at (0,0) for a teleport and at snap256(predicted) for a rebase. `anchor_ready` includes
  `"terrain": {cx, cy, heightmap, size, squareSize, zBase, maxHeight}` and `groundZ` (the height at the player position
  for the rebase, or at (0,0) for a teleport).

server → mod:
- `{"type":"terrain_ready","requestId":N,"anchorId":A,"cx","cy","heightmap","size":1024,"squareSize":2.0039138943248533,"zBase","maxHeight"}`
- `{"type":"far_tile","anchorId":A,"key":"L_i_j","level":L,"shape":"...dae","pos":[x,y,z]}`
- `{"type":"far_remove","anchorId":A,"key":"L_i_j"}`
- `far_done` = the current desired set is fully sent (it may be re-sent after later diffs).

## 4. Prefetch and caching (server)
- DEM tiles are already disk-cached. Keep generated terrain heightmaps in an LRU keyed by (anchorId, cx, cy).
- When a pose arrives, the server may speculatively build the terrain for snap256(player + velocity·6 s) ahead of the
  request, so that `prepare_terrain` returns almost at once.
- Delete heightmap files no longer referenced (keep the current one and the last two).

## 5. Acceptance (in-game, tested by the lead)
- Driving 5 km in a straight line produces only small terrain-follow blips (≤ ~50 ms), no camera jumps, and no FPS dips
  lasting seconds.
- At 10 km the origin rebase happens with one ≤ ~80 ms hitch, the orbit camera stays behind the car, and no far tiles
  vanish.
- Far mountains render to 80 km. No cracks are visible between LOD levels or at the terrain edge.
