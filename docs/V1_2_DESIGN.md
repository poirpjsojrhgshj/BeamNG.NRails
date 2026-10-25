# BeamNG.Earth v1.2: ground that stays put under the car, no pops nearby, no time warp

Status: design for implementation. Date 2026-10-10. Target BeamNG.drive 0.39.4 (Linux, Vulkan).
This supersedes the parts of `docs/V1_1_SPEC.md` it changes.

Evidence tags used throughout:
- **[V]** verified: code `file:line`, the game log, binary strings, stock game Lua/shaders, or a cited URL.
- **[M]** modelled: a simulation of the decoded engine dt filter.
  - `scratchpad/timewarp/sim/dtsim.py` is the research model.
  - `scratchpad/lead/v12sched.py` holds my v1.2 scenarios.
  - Scratchpad root: `/tmp/claude-1000/-home-tecnagamer-Documents-BeamNG-Earth/b02246e0-198a-4d55-8cba-7ac6107ad43e/scratchpad`.
- **[I]** inferred, not measured.
- **[P]** must be probed in-game before committing (section 10).

---

## 0. Summary

| # | User complaint | Root cause | v1.2 fix |
|---|---|---|---|
| 2 | The ground under the car changes shape | **[V]** Terrain samples sit at 2048/1022 = 2.0039 m, and every 256 m re-centre is a 127.75-sample shift, so every commit samples the DEM at new points (`server/heightmap.py:19,29-33`). **[V]** Height quantisation is chosen per block (`heightmap.py:60-62`). **[I]** The terrain's own render LOD pops (`$pref::Terrain::lodScale`). | World-locked 2.000 m lattice (256 m = 128 samples). A fixed per-anchor height quantum. Overlapping samples come out bit-identical. Tighter terrain lodScale. |
| 1 | Nearby tiles visibly update / pop | **[V]** Every commit re-keys 18–32 L0 tiles about 1 km away, because the apron mask is part of the key (`farfield.py:82-84`; the game log shows `far_5_0_-2_0_a4.dae` etc. right after each commit). **[V]** The strip uncovered behind the block is only requested after the commit (`earthd.py:528-540`). **[V]** One LOD threshold, no hysteresis, K=2 (`farfield.py:129`). **[V]** Colour seam: far palette (0.36, 0.43, 0.24) next to terrain dirt (0.39, 0.35, 0.27). No fade at all. | Far tiles stop depending on the block. L0 tiles under the block are kept, sunk or hidden, and swapped in the commit frame. Hysteresis plus K per level. A **two-phase vertical crossover** (a temporal geomorph done with transforms only) on every LOD swap. An optional alpha-tested dither dissolve after a probe. Off-screen swaps happen instantly. |
| 3 | "Would dynamic tile sizes work?" | We already have them: a quadtree with 256 m tiles near and up to 131 km far. | Tune K per level, add hysteresis, then use screen-space-error LOD with per-tile error. |
| 4 | Preloading, server or memory | Server builds only what is currently desired, nearest-first. Files are deleted per session. Anchors are arbitrary, so nothing can be reused. | Priority queue (distance × view angle, plus urgency classes). Predicted-pose prefetch. Hidden preload pool in the mod. Deterministic lattice anchors. Persistent disk cache across sessions. Offline pre-cache command. |
| 5 | "Time warp" | **[V]** The engine drives physics from a smoothed dt: clamp, then median-of-3, then a slow EMA. **[V]** Each ~60 ms commit is followed by 23–74 COLLADA imports about 25 ms apart (beamng.log). Those runs pass the median and drag the EMA, so the sim runs at 34% and then 164% speed **[M]**. | A main-thread **frame governor**. A small, smooth per-frame budget (≤2 ms, ramped). Heavy operations (commit, rebase) run isolated, with streaming ramped to zero around them. No streaming in the commit frame. Cheap units (.cdae). Fewer file-watcher events. A new wall-vs-sim metric. |
| 6 | Far-tile import cost (~7.5–25 ms each) | COLLADA XML parse on the main thread, plus the engine writing its own .cdae cache, plus file-watcher events. | Server writes binary `.cdae` directly. Material comes from a static JSON material. No apron variants. Persistent, immutable files. |

---

## 1. Complaint 2: the ground under the car changes shape

### 1.1 Root causes
1. **Non-world-locked lattice [V].**
   - `heightmap.py:19`: `SQUARE = 2*1024/1022 = 2.00391 m`.
   - `heightmap.py:29-33`: sample `i` is at `cx - 1024 + i*SQUARE`.
   - `follow.lua` moves `cx` in multiples of 256 m, i.e. 127.75 samples.
   - So after each commit no sample lands on a previous sample position. The DEM is bilinearly re-sampled at new points, and the surface under the car changes by the DEM interpolation error. That is cm on smooth ground and decimetres on rough ground **[I]**.
   - The terrain mesh triangulation also shifts by a quarter cell.
2. **Per-block height quantisation [V].** `heightmap.py:60-62` sets `zBase = floor(min)-5`, `maxHeight = ceil(max-zBase)+5`, and `q = rint((u-zBase)/maxHeight*65535)`. The quantum changes with each block, so even an identical `u` re-quantises differently. This is a few mm of extra jitter.
3. **TerrainBlock render LOD [V exists / I effect].**
   - The terrain renderer has a distance LOD driven by `$pref::Terrain::lodScale`. Normal is 1.0, High is 0.75; `screenshot.lua:936` sets 0.001 for "best" (`core/settings/terrainQuality.lua:17-27`).
   - `$TerrainBlock::cellsRendered` exists (`core/metrics.lua:241`).
   - Torque-lineage terrain cells switch LOD without geomorphing. This is a candidate for "nearby" terrain popping a few hundred metres out, though not directly under the wheels.
4. **Origin rebase [I].** At a rebase (≥10 km) the block is rebuilt in a frame rotated by about 0.05–0.09°, so the lattice cannot coincide. This is one unavoidable resample per rebase. It is rare and stays as-is (see 1.6).
5. Checked and ruled out:
   - **DEM sampling is deterministic [V]**: `dem.py:185-227`, bilinear on a fixed Mercator pixel grid. Missing tiles are cached as `.404` and produce zeros consistently. Fetch errors raise instead of falling back.
   - **Physics** picks up the new block in the same frame (`core.lua:282`).

### 1.2 Change: world-locked lattice, `squareSize = 2.0`
- `SQUARE = 2.0`, `N = 1024`. Block position stays `(cx-1024, cy-1024, zBase)`.
  - Sample `(gx, gy)` is at world `(cx-1024+2gx, cy-1024+2gy)`. Every sample is an **even-metre lattice point in the anchor frame**.
  - A 256 m move is exactly **128 samples (even)**. That preserves any parity-based diagonal rule, a Torque convention not verified for BeamNG.
- Compute coordinates as **integer lattice index × 2.0** (`k0 = (cx-1024)//2`, `x = (k0+i)*2.0`), not as `cx - half + i*s`. The same world point then gives bit-identical lat/lon in every block.
- **Compute row/column 1023 from real data** instead of repeating 1022 (`heightmap.py:53-54`). If the engine renders the last square, it now renders correct ground.
- **Valid (collidable) area is now (N-2)·2 = 2044 m**: `[cx-1024, cx+1020]` per axis **[V rule, V1_1_SPEC "Terrain edge"]**.
  - `follow.lua`: `REACH = 1020 - EDGE_MARGIN = 420` (was 424). Use the same value in `earthd.predict_centre`.
  - `follow.SQUARE_SIZE = 2.0` and `terrain.SQUARE_SIZE = 2.0` (`terrain.lua:15`, `follow.lua:12`).
- Rejected alternative: `128/63 m` (2.0317). It is not exactly representable, and it overhangs 28 m onto the neighbouring far tiles. That overlap needs runtime holes (`importMaps` has a `holesMap` argument, unverified at runtime) or it z-fights.

### 1.3 Change: fixed global height quantum
- One quantum `Q` per anchor, from the ladder {1/256, 1/128, 1/64, 1/32, 1/16} m (range 65535·Q = 256…4096 m).
  - Pick it at anchor creation from a z10 relief survey of ±15 km: the smallest Q whose range covers the regional relief plus 10%.
  - This is deterministic per anchor, so caches stay valid. The typical value is 1/64 m: ±0.8 cm per sample.
- `zBase(block) = floor((min_u - 8)/64)*64`, a multiple of Q. `maxHeight = Q*65535`, or `Q*65536` if probe **P1** shows the engine divides by 65536.
- Stored height `= zBase + q·Q = Q·round(u/Q)` for any zBase, because zBase/Q is an integer. Overlapping samples are therefore identical. The only residual is the engine's float32 `zBase + q·Q`, ≤1 mm **[I]**.
- If a block exceeds the range (rare cliffs), use the next ladder step for that block only. The one-time difference is ≤ Q/2.

### 1.4 Change: far tiles share the lattice near the block
- L0 tiles are 256 m with 32 cells, i.e. 8 m vertex spacing. Vertices now fall on lattice points.
- Build L0 tiles with **the same DEM zoom as the heightmap** (`anchor.hm_zoom`; today L0 is capped at z14 by `farfield.py:45`) and the **same Q rounding**. L0 vertices then equal the terrain samples bit for bit, so block-edge seams only differ in the sub-8 m detail.

### 1.5 Change: terrain render LOD
- Set `$pref::Terrain::lodScale` to 0.5 while our level is loaded, and restore the user's value on unload. Use `VariableRegistry.set`, as `screenshot.lua:936` does.
- Decide the value with probe **P8** (cellsRendered and frame time at 1.0 / 0.5 / 0.25). The block is only 1024², so even full resolution is about 2.1M triangles.

### 1.6 Rebase (unchanged, documented)
- One resample per rebase, every 6–10 km with lattice anchors (§4). Its magnitude is the DEM interpolation error, cm on roads **[I]**.
- Not worth more complexity in v1.2. The car is moved by the exact rigid transform, as today.

### 1.7 Server / mod / protocol
- **Server `heightmap.py`:**
  - `SQUARE=2.0`, integer-lattice coordinates, real last row/column.
  - `write_png(path, u, Q, zbase)`. `height_at` uses `x0 = cx-1024` and the valid extent `(N-2)*s`.
  - `generate()` returns `Q`, `zBase`, `maxHeight`.
- **Server `earthd.py`:**
  - `Anchor` gains `Q` (relief survey in `new_anchor`).
  - `terrain_msg` sends `squareSize: 2.0`.
  - `predict_centre` uses `REACH=420`.
- **Mod:** `terrain.lua` and `follow.lua` constants. `loadFlat` uses 2.0.
- **Protocol:** `terrain_ready.squareSize = 2.0`, plus `"q": Q` for debugging.

### 1.8 Acceptance test
- **Unit (`server/tests/test_heightmap.py`):**
  - Generate blocks at (0,0) and (256,0) with a synthetic rough `elev_fn`. Assert `q0[:, 128:1023] == q1[:, 0:895]` (uint16 equality, rows flipped consistently).
  - Repeat for (0,256) and the diagonal.
  - Assert that every sample x equals `2*k` exactly.
- **Unit (`mod/tests/test_follow.lua`):** `REACH=420`; targets keep `|p - c| ≤ 420` on both axes.

### 1.9 In-game measurement
- Probe **P1b** (after implementation): snapshot `tb:getHeight` at 2000 random points within 400 m of the car before a commit, then compare after. **Pass: max |Δ| ≤ 0.002 m** (float32). Today the expected value is cm to dm **[I]**.
- Optionally drive a 5 km straight with `castRayStatic` ground-clearance logging. There should be no step at commit frames.

---

## 2. Complaint 1: nearby tiles pop; make them fade in

### 2.1 Root causes
1. **Commit-driven churn [V].**
   - `Tile.key` includes `_a<mask>` (`farfield.py:82-84`), and `commit_terrain → update_far` (`earthd.py:528-540, 587+`) re-keys every block-adjacent tile.
   - beamng.log, my count: after each commit **23, 25, 42, 74 imports** in bursts of 0.57–2.51 s. **18–32 of them are apron re-keys** (`far_5_0_-2_0_a4.dae`, `far_5_1_-1_-5_a8.dae`, …).
   - Each re-key replaces a tile about 0.6–1.5 km from the player with a near-identical one: a visible flicker or pop.
2. **Trailing strip [V].** Tiles for the area uncovered behind the moved block are only selected after `commit_terrain`, so there is a hole until they stream in. It is usually behind the camera.
3. **Single-threshold LOD [V].**
   - `d < K·S`, K=2, no hysteresis (`farfield.py:129`).
   - At the switch, one coarse cell spans `1/(32K)` rad, about **14.6 px** at 1080p and 60° FOV for K=2. The pop amplitude is some fraction of that **[I]**.
   - A player wandering near a threshold flips tiles back and forth.
4. **Block-edge material seam [V numbers / I perception].**
   - The terrain uses a single dirt TerrainMaterial; base colour mean is (0.39, 0.35, 0.27) per `bngEarth_base_b.png`.
   - L0 far tiles use the height/slope palette, about (0.36, 0.43, 0.24) at low elevation (`farfield.py:166`).
   - Each commit moves this colour boundary 256 m. That looks like a "square of different ground" sliding along.
5. **No fade [V].** `farfield.lua:52-76` spawns and deletes outright.

### 2.2 What the engine offers for fading (verified pieces)
- Per-object `instanceColor` alpha × material opacity when the material layer has `instanceOpacity` (`shaders/.../defaultMat.hlsl:254`).
  - `alphaTest` clips in every pass, including depth and shadow (`permutations.h.hlsl:181-183`).
  - Stock Lua fades TSStatics this way: `gameplay/crawl/boundary.lua:112-135`, `freeroam/bigMapMode.lua:150-168`, `missionMarker.lua:169-172` (`updateInstanceRenderData`).
  - Stock materials use `instanceOpacity` (art_shapes.zip `sideMarker/main.materials.json`, translucent v1.5) and `alphaTest`/`alphaRef` (`common.materials.json`).
- **No** shape LOD cross-fade exists. There is **no** Lua-reachable per-object `uVisibility` (the fizzle dither) for TSStatic. `setMeshAlpha` is vehicle-only; `renderFade` is a BeamNGVehicle field.
- Transforms are cheap: 64 `setPosition` calls take 0.4 ms (ARCHITECTURE probe p6).

### 2.3 Change A: far field independent of the terrain block (largest win, no engine risk)
- **Keys are `L_i_j` only.** Delete the apron code (`farfield.py:43-44, 92-103, 207-218`).
- **The server forces L0 over `committed ∪ pending ∪ predicted` blocks.** Tiles overlapping these bboxes refine to L0. Tiles inside them are **included, not excluded**. The 8×8 L0 tiles under a block are always loaded.
- **The mod decides cover state locally** from its committed block bbox `[cx±1024]`:
  - **Edge ring** (the 28 covered tiles on the block perimeter): `setPosition(z - sink)`. `sink` is computed by the server per L0 tile as `max(0, max(tile_surface - lattice_terrain)) + 0.3 m` over its 129×129 lattice. The tile is guaranteed below the terrain everywhere.
  - These sunk tiles act as an under-floor, replacing the apron. Any crack between the terrain edge and the next tile shows ground a few dm lower, never sky.
  - They also fill the 2–4 m strip between the 2044 m valid area and the 2048 m L0 cover on the N/E edges. Probe **P1** tells whether the last square renders.
  - **Interior** (36 tiles): `setHidden(true)`. Zero GPU cost.
- **Commit frame (atomic, inside the governor's heavy slot):** `importMaps` + `setPosition(block)` + `reloadCollision` + `farfield.onBlockCommit(old, new)`.
  - Newly uncovered tiles: unhide or raise to true z.
  - Newly covered tiles: sink (edge ring) or hide.
  - That is at most about 48 `setPosition`/`setHidden` calls, about 0.3 ms **[I, from p6]**.
  - **Zero imports in that frame.**
- **Commit gating (mod `follow.decide`):** commit only when the terrain is ready, `d > 450`, **and every L0 tile in `oldBlock − newBlock` is live**.
  - Hard override at `d > 700 m` (still ≥320 m from the edge).
  - The server streams those tiles at urgency class 0 as soon as `prepare_terrain` arrives.
- Colour continuity:
  - Change the far palette's land ramp below 1500 m to the terrain's macro colour (0.39, 0.35, 0.27), blending to the height palette by about 2500 m.
  - Ship the palette as a static file in the mod (it is deterministic, `farfield.py:165`).
  - A real fix (imagery on both) is a v1.3 item.

### 2.4 Change B: hysteresis and K per level (see §3 for numbers)
- Refine node L when `d < K(L)·S`. Keep it refined while `d < (K(L)+0.5)·S`. The server stores last call's `refined` set per connection.
- Per-area rate limit: a node may not change state more than once per 2 s.

### 2.5 Change C: transitions. Every swap is a crossover, never a pop
A "new nearby tile" always replaces something already visible: its parent, its children, an old-anchor tile, or the terrain. So "fade in" is implemented as a **crossover between old and new**.

The server turns each LOD change into an explicit **swap group** `{add:[keys], remove:[keys]}`, emitted once all adds are sent. The mod runs the group when every add is loaded:

**C1. Off-screen swap (instant).** If the whole group is outside the camera frustum (plus a 10° margin) or more than 30 km away, swap in one frame. This is Cesium's "foveated" / UE's "behind the source" idea **[V, §5 research]**.

**C2. Two-phase vertical crossover (default, transforms only, zero shader risk).**
- Let `Δin ≥ max(new − old)` and `Δout ≥ max(old − new)`. Bound both by `1.2·(err_new + err_old) + 0.2 m`, where `err` is the per-tile geometric error the server now sends.
- **Spawn:** add the new tiles at `z − Δin`. They are completely under the old surface, so there is no visual change.
- **Phase 1 (0.25 s, smootherstep):** raise the new tiles from `−Δin` to 0. The visible surface is `max(new(t), old)`, so every point *rises* continuously to `max(new, old)`.
- **Phase 2 (0.25 s):** sink the old tiles from 0 to `−Δout`. The visible surface `max(new, old(t))` *falls* continuously to `new`.
- **End:** delete the old tiles.
- Result: every surface point moves **monotonically and continuously from the old height to the new height**. This is a per-pixel geomorph done in time, with no shader. It is Google Earth's "child in over opaque parent, then parent out" order (US9105129 **[V]**) realised with rigid transforms.
- **Skirt depth** = `max(2 m, 0.02·S, 2.5·err + 1 m)`, so neighbours never show cracks while tiles move.
- **Cost:** one `setPosition` per moving tile per frame. Cap at 24 concurrent groups; beyond the cap, use C1.
- **Terrain↔tile transitions at a commit** use phase 2 only: newly covered tiles sink over 0.3 s instead of instantly. With the shared lattice (§1.4) the residual difference is sub-8 m detail at ≥574 m, under 1 px **[I]**.

**C3. Optional dither dissolve (only if probe P3 passes).**
- One static far-tile material (§6.2): `alphaTest`, `alphaRef=128`, `instanceOpacity`, `opacityMap = 64×64 blue noise with values in [0.51, 1]` on **UV1**.
- UV1 is world xy scaled per tile, `·64/S`, so the noise has a constant screen frequency at the switch distance (about 5 px per texel at K=3).
- Visible fraction `f` ⇔ `instanceColor.a = 1/(2 − f)`, ramped over 0.3 s, then left at 1 forever.
- Pair it with C2's ordering: new dissolves in over old, then old dissolves out. Depth testing gives the union, so no complementary noise is needed.
- Use C3 for groups that have no geometric parent (initial load after teleport, rebase swaps between differently gridded anchors). Use C2 elsewhere.
- Pre-warm the shader permutation at level load: spawn one tile under the terrain with `a = 0.4`.
- **Fallback if alphaTest fails but translucent works (P2):** use translucent for adds only during the 0.3 s fade, with stock `boundary.lua` timing. This needs a runtime material swap (`skin`, unverified). C2 stays the default either way.

### 2.6 Change D: load replacements early, hidden (§4.4)
Children of nodes about to refine, i.e. inside `(K(L) + v·T/S)·S` along the heading, are prefetched hidden. The swap then costs no import.

### 2.7 Server / mod / protocol (v3)
- **Server `farfield.py`:**
  - `select(px, py, forced_bboxes, prev_refined, kfun, h)` returns `(tiles, refined)`.
  - `build_tile` returns `err` (vs a 65×65 DEM reference) and, for L0, `sink` (vs the 129×129 lattice).
  - It also returns UV1 and the skirt depth computed from `err`.
- **Server `earthd.py`:**
  - `update_far` runs on pose **and** on `prepare_terrain` (pending block) and predicted-block changes.
  - Swap-group computation replaces `flush_removals` for the active anchor. The old-anchor logic is kept for rebases.
- **Mod `farfield.lua`:** rewrite as a tile state machine:
  - States: `queued → loading → loaded-hidden → (crossover) → shown → sunk/hidden-covered → doomed`.
  - Swap-group bookkeeping, cover logic, transition list.
  - Imports are scheduled by the governor (§5).
- **Messages:**
  - `far_tile{anchorId,key,level,shape,pos,err,sink?,state:"group"|"prefetch"}`
  - `far_swap{anchorId,id,add:[...],remove:[...]}`
  - `far_remove{...}` for prefetch evictions and old-anchor removals.
  - `far_done` unchanged.

### 2.8 Acceptance tests
- **Unit (server):**
  - Keys are unchanged when only the block moves.
  - Hysteresis: an oscillating pose ±40 m around a threshold produces 0 swaps after the first.
  - Every swap group's `add` footprint equals its `remove` footprint (no hole, no overlap).
  - L0 `sink` ≥ max(tile − lattice) on a synthetic V-valley.
- **Unit (mod, `test_farfield.lua`):**
  - The invariant "every point of the plane is covered by a shown tile or the committed block" holds at every simulated frame through commits, swaps and rebases.
  - No import runs in a commit frame.

### 2.9 In-game measurement
- beamng.log: **COLLADA/cdae imports within 2 s after a commit = 0** (today 23–74).
- Mod counter of **in-frustum swaps with d < 5 km that were not C2/C3 = 0**.
- Count of `far_*` imports per km driven.
- A recorded drive (same route as `docs/research/perf-session-2026-10-10.jsonl`) reviewed for visible pops.

---

## 3. Complaint 3: dynamic tile sizes

**For the user:** yes, and the game already does it. The far field is a quadtree: tiles are 256 m right next to the drivable area and double in size every ring outward (512 m, 1 km, 2 km … 131 km). Every tile has the same 32×32 grid, so distant tiles are coarser. Making the near tiles smaller would not stop popping by itself. What you notice is when and how a tile is swapped for a finer one. v1.2 fixes that part:
- tiles switch farther away (higher K for the nearest rings);
- they don't flip back and forth (hysteresis);
- they glide into place instead of snapping (crossover);
- they are loaded before they are needed.

Tuning (tile counts computed with `farfield.select` for the player near the block centre **[V computed]**; "+64 covered" = the L0 tiles now kept under the block):

| Setting | Tiles (excl. covered) | L0/L1/L2 | Coarse-cell size at switch |
|---|---|---|---|
| v1.1: K=2 everywhere | 390 | 24/58/60 | 14.6 px |
| **v1.2: K=3 for L1,L2; 2.5 beyond; h=+0.5** | **666 (+64)** | 104/118/88 | 9.7 px near, 11.7 px far |
| K=4 for L1,L2; 3 for L3,L4; 2.5 beyond | 870 (+64) | 204/201/93 | 7.3 px near |
| K=3 everywhere | 762 | 104/118/120 | 9.7 px |

- Recommended: **K(L) = {L1: 3, L2: 3, ≥L3: 2.5}, hysteresis 0.5, min level L0, RADIUS 80 km.**
- Move to the K=4 row only after `.cdae` loads are measured below 2 ms (P5). That row is about 1.25× the import work and draw calls.
- The tighter near values are justified because terrain roughness relative to cell size grows at small scales **[I]**.
- **Phase 6, screen-space error:** refine when `err·f/d > τ` (τ = 2 px near, 4 px beyond 20 km), with the K rule as a floor (`d < 1.5·S` always refines). Flat land then stays coarse and mountains refine, which is Cesium's geometricError model **[V cesium-native]**.
- No in-shape LODs (`base00/_L<px>`): they also switch instantly, and all of them are parsed at import **[V binary strings]**.

**Acceptance:** live tile count ≤ 800 in steady driving. GPU and frame time within +1 ms of v1.1 (perfmon p50).

---

## 4. Complaint 4: preloading (server, disk, memory)

How shipping engines do it **[V unless noted]**:
- **Cesium:** priority = (1−dot)·distance. Parent kept until all children are ready. `preloadFlightDestinations`. `cullRequestsWhileMoving`. 0.25–1 s fades.
- **Frostbite** (supercars, jets): one global priority over every quadtree node, modified by speed and culling, with a fixed pool. Newly streamed data fades in.
- **UE World Partition:** streaming sources with velocity- and angle-weighted cell priority, plus a source placed at a teleport target.
- **MSFS:** draws the best available data with parent fallback, a rolling disk cache, and a manual region pre-cache (cache details are community-sourced).
- **Clipmaps:** only the newly exposed strip is filled; fine samples never move.
- Spider-Man / Forza / The Crew: only the qualitative lesson that streaming must stay ahead of top speed **[unverified numbers]**.

### 4.1 One priority queue (server build order and mod import order)
`key = (class, d · (1 + 1.5·(1 − cos θ)))`, where θ is the angle between the tile direction and the **camera forward**. The pose now carries the camera via `core_camera.getPositionXYZ` / `getForwardXYZ` (`core/camera.lua:1927,1931`) **[V]**.

Classes:
- 0: tiles that gate a terrain commit (the uncover set).
- 1: tiles of a pending swap group that has started loading (keeps groups short).
- 2: current desired tiles.
- 3: prefetch.

Prefetch whose predicted need time is more than 10 s away is dropped (Cesium's cullRequestsWhileMoving).

The server uses a heap in `_stream` instead of `nearest_first` (`farfield.py:138`). The mod re-sorts its local queue every frame with the live camera, because server order is up to 0.5 s stale.

### 4.2 Predicted-pose prefetch (server)
- On each pose, also run `select()` at `p + v·T` for T ∈ {3 s, 6 s} and add the difference as class 3.
- Terrain prefetch already exists (`earthd.maybe_prefetch`). Add: the predicted block's L0 tiles (class 0 once it is the pending block).
- **Before a rebase:** the next lattice anchor is known when the player is about 8 km out (§4.3). Pre-build that anchor's first terrain plus L0–L3 around the predicted entry point at class 3. Pre-fetch DEM tiles for the next 2 blocks along the heading.

### 4.3 Deterministic anchors and a persistent cache
- **Lattice anchors:** latitude every 0.05°; longitude every `0.05°·2^round(log2(1/cos φ))`; the poles are single anchors.
  - Key `a<k>_<m>`.
  - Rebase and teleport choose the nearest lattice anchor, so the player is ≤ about 3.9 km from the origin. Teleport spawns at the target's ENU, not (0,0).
  - The protocol keeps the int `anchorId` epoch (monotonic, as now: `earthd.py on_pose`) and adds `anchorKey`.
- With lattice anchors every artefact is a pure function of `(FORMAT, anchorKey, content key)`:
  - `cache/f<FORMAT>/<anchorKey>/far_L_i_j.cdae`
  - `.../hm_<cx>_<cy>.png`
  - These are immutable and never rewritten, which matters because the engine watches loaded files (`earthd.py:56-58`).
- Path: `<user>/temp/beamngEarth/cache/…`. It is **not** deleted by `_clean_old_sessions` (`earthd.py:149-155`).
- Size-capped LRU (default 3 GB), with an index of last-use times, pruned at start and hourly. Deletes go through the existing rate-limited `queue_delete` (`earthd.py:172-193`).
- **Revisits and second sessions** then cost zero server time and zero file writes.
- **Pre-cache command:** `earthd.py --precache LAT,LON,RADIUS_KM [--route file.gpx]` builds terrain blocks plus L0–L4 tiles offline (MSFS manual cache analogue).
- **DEM in memory:** raise `Dem(mem_tiles)` from 192 to 512 (about 512 MB of float32 512² tiles).

### 4.4 Hidden preload pool (mod)
- Prefetched tiles are created with `hidden = true` and registered within the governor budget, only when classes 0–2 are empty. Stock `ui/arrowGPS.lua:74-87` does register-then-hide **[V]**.
- Revealing one costs no import. Pool cap 150 tiles; the server evicts with `far_remove`.
- Probe **P6** checks the open question of whether a hidden TSStatic really loads its shape at `registerObject` (the research says yes: synchronous `onAdd`).
- Probe **P5** checks whether a re-spawned shape path is served from the engine's resource cache. If it is, hysteresis churn is nearly free.

### 4.5 Server CPU
- Start earthd with `nice -n 10`, and set `OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1` in `main()` before importing numpy.
- Keep `tile_workers=3`, so tile building cannot starve the game's physics threads **[I]**.

### 4.6 Acceptance and measurement
- **Unit:** priority order puts the forward cone first; the predicted set ⊇ next-commit uncover set; cache keys are identical across two server runs.
- **In-game:**
  - `prepare_terrain → terrain_ready` latency p95 < 50 ms (prefetched).
  - Share of swap groups whose adds were already loaded (prefetch hits) > 80% at 30 m/s.
  - Second drive of the same route: server tile builds = 0, file writes = 0.

---

## 5. Complaint 5: the "time warp"

### 5.1 Mechanism [V, decoded by research]
- Each frame the engine clamps raw dt to 1 s, takes the median of the last 3, then applies an EMA with gain 0.025 or 0.075. That smoothed dt is Lua's `dtReal`, and physics simulates `dtReal × timescale` in 0.5 ms steps (max 100 per frame).
- It is located at exe `0x119bdb0`, called from the main loop at `0x11a1928`; physics uses the smoothed value at `0x11a171a`.
- Consequences:
  - **One isolated slow frame:** rejected by the median, so its time is never simulated. You see a hitch.
  - **Two or more adjacent slow frames, or an H,L,H,L pattern:** pass the median, and the slow EMA lags. The sim runs slow, then fast. That is the "smooth lag spike".

### 5.2 Our trigger [V log + M]
- `core.lua:467` commits the terrain (60 ms), then **the same frame** calls `farfield.update()` (`core.lua:529`). That always imports at least one tile (`farfield.lua:185` breaks only after an add).
- The server then streams 23–74 re-keyed and new tiles at about 25 ms intervals (my beamng.log count above).
- Model of that pattern: **sim speed 34% → 164%** over about 1 s, max lag 163 ms **[M]**.
- **Second, rebase-related source [V, `earthd.py:60-62`]:** deleting about 400 files in one burst stalled the game 200–340 ms. The engine's file watcher calls `onFileChanged` and fans out `extensions.hook` per file (`lua/ge/main.lua:1052-1062`).
  - Tile **writes** (`.tmp` plus rename) also reach this watcher **[V path / I cost]**. Probe P9 measures it.
- **Perfmon cannot see the warp [V].** `perfmon.lua:45-52` compares `dtSim` against the smoothed `dtReal` from the same clock.

### 5.3 What the model says about candidate fixes (`scratchpad/lead/v12sched.py`, baseline 11.5 ms) [M]

| Pattern | Lost sim time / max lag | Worst 100 ms sim speed |
|---|---|---|
| v1.1: 60 ms commit + 15×25 ms imports | 163 ms | 34% … 164% |
| Isolated 45 ms commit (2 quiet frames each side) | 33.5 ms lost (one hitch) | 67% in that one bucket (hitch, not warp) |
| **8 ms import every 3rd frame (H,L,L), sustained** | **800 ms lost over 300 frames** | **77% sustained: slow motion** |
| 22 ms import every 3rd frame, sustained | 2.2 s lost | 57% |
| 8 ms import every frame, 200 frames | 106 ms | 66% … 153% |
| +2 ms per frame, step | 26 ms | 88% … 114% |
| **+3 ms per frame, ramped over 40 frames** | 40 ms (repaid) | **93% … 112%** |
| +1.5 ms per frame, step | 20 ms | 91% … 112% |

Two conclusions:
- **Correction to the research recommendation:** "isolate heavy frames" is right for *rare* events (commit, rebase). It is **wrong for sustained streaming**: every isolated spike's time is dropped, which is continuous slow motion.
- Streaming must be **small, smooth, ramped** work per frame. That requires cheap import units (`.cdae`, §6).

### 5.4 Change: frame governor (`mod/.../beamngEarth/governor.lua`, new)
- **Clock:** the wall frame time `W` from `hptimer` at `onUpdate` entry (not `dtReal`). `base` = median of the last 64 non-heavy frames.
- **Streaming budget `b` (ms):**
  - Ramps toward `bT` (default **2.0 ms**, configurable 1–4) at +0.05 ms/frame while there is work.
  - Ramps down at −0.05 ms/frame when idle.
  - Ramps down at −0.1 ms/frame when a heavy op is pending.
- **Token bucket:** `tokens = min(tokens + b, 2·maxUnit)`. Run units (import, delete, reveal) while `tokens ≥ est(unit)`, where `est` is an EMA per unit kind, scaled by triangle count. Subtract the measured cost.
  - **No "at least one per frame" rule.** Remove it from `farfield.lua:175-187`.
- **Heavy slot** (terrain commit, rebase phase 2, teleport): allowed only when `b == 0` and the last 2 frames were ≤ `base + 1.5 ms`.
  - Afterwards force 2 quiet frames (no streaming), then ramp up again.
  - Worst-case delay is about 25 frames (b 2→0 at 0.1/frame), about 2 m of extra travel at 30 m/s per 0.1 s.
  - `follow.decide`'s 'commit' becomes a *request* to the governor.
- **Loading mode:** after a teleport (car being placed) or below 1 m/s for over 3 s, `bT = 8 ms`. A warp is invisible there; this speeds up the initial fill.
- **Interim, until `.cdae` lands:** DAE units cost 7.5–25 ms. Use density-ramped streaming (budget as a fraction of frames, ramped over 40 frames). Modelled at 79% … 137%: still a warp, but rarer once §2.3 removes the 18–32 re-keys per commit. Ship §2.3 and §6 together if possible.
- **File-watcher hygiene:**
  - Write files once (persistent cache).
  - Keep `DELETE_INTERVAL` rate limiting (`earthd.py:62`) for all deletes, including the engine's `.cdae` duplicates.
  - With direct `.cdae` there are no duplicate engine-written cache files to delete.

### 5.5 Change: trim the commit itself
Probe **P7** splits `importMaps` cost into heightmap decode, material/layer map, `baseTexSize`, and `setPosition`. If `baseTexSize` 1024→256 or dropping a redundant layer-map decode saves ≥10 ms, adopt it. The model gives an isolated 30 ms commit as 18.5 ms lost (one hitch).

The commit stays a single isolated frame. Incremental `setHeight` slicing cannot move the block, because TerrainBlock has no toroidal wrap **[V V1_1_SPEC]**. Rendering the near ground with TSStatics over a render-disabled block is a v1.3 option, outside v1.2 scope.

### 5.6 Change: measurement (`perfmon.lua`)
- In `onPreRender(dtReal, dtSim, dtRaw)` (3rd argument per `lua/ge/main.lua:820` **[V signature / I meaning]**), accumulate wall time (hptimer) and ΣdtSim. Report:
  - `lag = Σwall − Σsim` (min/max per window);
  - per-100 ms sim speed min/max;
  - count of buckets outside [0.9, 1.1];
  - `dtReal − dtRaw` (filter error).
- Tag events in the ring: commit, rebase, import (with ms), delete, file write.
- Update `tools/perfmon.py` to plot speed per 100 ms with event markers.

### 5.7 Acceptance
- **Unit (`mod/tests`):**
  - Governor: given a scripted queue, no heavy op is ever adjacent (±2 frames) to a frame with streaming work.
  - Per-frame streaming spend ≤ `b + maxUnit`.
  - `b` changes by at most 0.1 ms per frame.
- **In-game (10 km at 30 m/s, same route as the 2026-10-10 session):**
  - ≥ 99.5% of 100 ms buckets within [0.9, 1.1] sim speed. Today: windows with minSimRatio 0.78–0.82 at every commit, per `perf-session-2026-10-10.jsonl` **[V]**.
  - Per-commit lost time ≤ 35 ms.
  - No frames over 33 ms except commit and rebase frames.
  - Streaming frames p99 ≤ base + 4 ms.

---

## 6. Cutting far-tile import cost

### 6.1 Server-written `.cdae` (primary)
- The engine already compiles every DAE to a v31 `.cdae` in `<user>/temp/temp/beamngearth/…` **[V]**: about 500–900 orphaned files. A 2048-triangle tile is 77 KB (`delprobe2_0.cdae`).
- `TSStatic` accepts `.cdae` directly (exe `".dae;.dts;.cdae"`, `editor/api/valueInspector.lua:867`) **[V]**.
- The format **[V decoded]**: 8-byte header (`0x007C001F` + header size), a msgpack header map, then an uncompressed msgpack body.
  - The body holds shape info, details, names, meshes (verts 12 B, tverts 8 B, **tverts2 8 B for UV1**, norms 12 B, encodedNorms, primitives, u32 indices, tangents 16 B) and materials.
  - Reference reader: `scratchpad/engine/dl/cdae_dump_info.py`; decoder `scratchpad/engine/scripts/mp.py`.
- New `server/cdae.py`: a numpy writer. **Golden test** against engine-written `lodtest_16_0.cdae` and `lodtest_32_0.cdae`, compared as decoded-structure equality for the same mesh. Copy meshFlags and primitive flag bits from the engine files.
- Keep normals (lighting) and write tangents.
- **Fallback if direct load is refused (P5):** write `x.cdae` beside a stub `x.dae` with an older mtime, at the engine's cache path.
- **Expected** cost is memcpy-like loading, below 2 ms per 2k-triangle tile **[I]**. P5 measures it.

### 6.2 Static material (enables C3 and removes per-session material names)
- Ship `levels/beamng_earth/art/shapes/beamngEarth/main.materials.json`. The level loader auto-loads it (`server/server.lua:200-212`, as noted in `terrain.lua:9-10`).
  - It contains `bngEarthFar_v3` (v1.5, `baseColorMap` = shipped palette).
  - If P3 passes, add to the same material: `opacityMap` = shipped noise, `opacityMapUseUV: 1`, `instanceOpacity`, `alphaTest`, `alphaRef: 128`.
- Tiles reference this material by name. Drop the per-session `self.material` (`earthd.py:125`) and the session palette.

### 6.3 Smaller and fewer
- No apron variants (§2.3). Skirt rows stay at 4×33 vertices.
- Do not go below 32×32 cells: per-triangle throughput is worst for small DAE tiles.
- Interim only: emit DAE floats with `%.3f` positions and `%.3f` normals instead of `%.4f` (`dae.py:13`). This is a modest parse saving **[I]**.

### 6.4 Acceptance and measurement
- **Unit:** golden decode equality; file size ≤ 90 KB per 2k-triangle tile.
- **In-game:** per-import stopwatch around `registerObject` (already in `farfield.lua` budget accounting): **median ≤ 2 ms, p99 ≤ 4 ms**.
- `temp/temp/beamngearth` stops growing.

---

## 7. Protocol v3 (summary)

**mod → server**
- `hello{protocol:3, format:3}`
- `pose{anchorId,x,y,z,vx,vy,lat,lon,speed, cam:{x,y,z,fx,fy,fz,fovDeg}}`
- `prepare_terrain` and `commit_terrain`: unchanged fields. `commit_terrain` no longer changes any far-tile key.
- `prepare_anchor{lat,lon,cx?,cy?}`: the server snaps to a lattice anchor and returns its `anchorKey`.

**server → mod**
- `anchor_ready{…, anchorKey, terrain:{cx,cy,heightmap,size:1024,squareSize:2.0,zBase,maxHeight,q}}`
- `terrain_ready{…squareSize:2.0,q}`
- `far_tile{anchorId,key:"L_i_j",level,shape:".cdae",pos:[x,y,z],err,sink?,state:"group"|"prefetch"}`
- `far_swap{anchorId,id,add:[keys],remove:[keys]}`. The mod runs C1/C2/C3 once all adds are loaded.
- `far_remove{anchorId,key}`: prefetch eviction, or a previous anchor's tile (v1.1 rule kept for rebases).
- `far_done{anchorId,count}`

---

## 8. Prioritised implementation plan

| Phase | Work | Fixes | Est. | Depends on |
|---|---|---|---|---|
| **0** | Perfmon wall-vs-sim metric plus event tags. Run probes P1, P5, P6, P7, P8, P9 (and P2/P3). | measures 5 | 0.5 d | none |
| **1a** | 2.0 m lattice, integer-index coords, real last row, Q ladder. Tests. Mod constants (`REACH=420`). | 2 | 0.5 d | P1 |
| **1b** | Block-independent far field: drop aprons, force L0 over committed/pending/predicted blocks, covered L0 sink/hide with server-computed `sink`, atomic `onBlockCommit`, commit gating, colour ramp. | 1, 5 | 1.5 d | 1a |
| **1c** | Governor: heavy slot isolation, no streaming in commit frame, token bucket with ramp, remove "≥1 per frame". `nice` + thread caps for earthd. lodScale pref. | 5, 2 | 1 d | 0 |
| **2** | `server/cdae.py` with golden tests, static material JSON plus shipped palette, `.cdae` shapes, governor `bT = 2 ms`. | 6, 5 | 2 d | P5 |
| **3** | Hysteresis + K(L); per-tile `err`; skirt depth from err; swap groups; C1 off-screen swap; **C2 vertical crossover**; transition cap. | 1, 3 | 2 d | 1b, 2 |
| **4** | Priority heap (classes, camera angle) on server and mod; predicted-pose prefetch; hidden preload pool; DEM LRU 512. | 4, 1 | 1.5 d | 3, P6 |
| **5** | Lattice anchors (`anchorKey`), persistent cache plus LRU, next-anchor pre-build, `--precache`. | 4, 5 | 2 d | 2 |
| **6** (opt.) | C3 dither dissolve (if P3); SSE-based selection; quadrant cutting; imagery and colour unification. | 1, 3 | 2–3 d | P3 |

Ship 1a, 1b and 1c together as v1.2-alpha. They address complaints 2 and 1 (the main pops) and 5 (removes the import burst after commits). Then ship 2 quickly: without `.cdae` the smooth budget cannot be met.

---

## 9. Acceptance drive (lead, in-game, after phase 3)
Same route as the 2026-10-10 perf session, 10 km at about 30 m/s, orbit camera, perfmon loaded:
1. P1b: max |Δheight| within 400 m of the car across every commit ≤ 2 mm.
2. 0 imports within 2 s of each commit. 0 non-transitioned in-frustum swaps within 5 km.
3. ≥ 99.5% of 100 ms buckets with sim speed in [0.9, 1.1]. Per-commit lost time ≤ 35 ms.
4. Import median ≤ 2 ms, p99 ≤ 4 ms. Live tiles ≤ 800. p50 frame time within +1 ms of v1.1.
5. Rebase: one hitch ≤ 80 ms. No far tiles vanish. With pre-built next anchor, new-frame tiles complete in < 3 s.

---

## 10. Probes to run before committing to a choice
Run them through the user's console or the lead's MCP session. Each returns `jsonEncode`. Pause physics where noted, and restore the world afterwards with `beamngEarth_core.teleport(lat, lon)`. Helper files are written by small Python snippets into `<user>/temp/beamngEarth/probe/`.

### P1: quantisation formula, valid area, last-square rendering (decides `maxHeight = Q·65535` vs `Q·65536`, and the N/E gap width)
Python helper:
```python
import os, numpy as np; from PIL import Image
d = os.path.expanduser('~/.local/share/BeamNG/BeamNG.drive/current/temp/beamngEarth/probe'); os.makedirs(d, exist_ok=True)
q = np.minimum(np.arange(1024) * 64, 65535).astype(np.uint16); q[1023] = 65535
Image.fromarray(np.ascontiguousarray(np.tile(q, (1024, 1)))).save(d + '/q_x.png')
```
Lua:
```lua
local tb = scenetree.findObject('bngEarthTerrain')
be:setPhysicsRunning(false)
local H = 65535/64
local L = '/levels/beamng_earth/art/terrains/beamngEarth_layer_1024.png'
local ok = tb:importMaps('/temp/beamngEarth/probe/q_x.png', 2.0, H, '', {'beamngEarthDirt'},
  {{path=L, selected=false, material='beamngEarthDirt', materialId=0, channel='R', channelId=0}}, false)
local x0, y0, z0 = 4096, 4096, 100
tb:setPosition(vec3(x0, y0, z0)); be:reloadCollision()
local r = {ok=ok, sq=tb:getSquareSize(), hsu=tb:getHeightScaleUser(), s={}}
for _, gx in ipairs({0,1,2,511,512,1000,1020,1021,1022,1023}) do
  local h = tb:getHeight(vec3(x0 + 2*gx, y0 + 1000, 0))
  r.s[#r.s+1] = {gx=gx, q=math.min(gx*64,65535), dz=h and (h - z0) or 'nil'}
end
r.mid = tb:getHeight(vec3(x0 + 1023, y0 + 1000, 0)) - z0          -- between gx 511 and 512
for _, dx in ipairs({2039.9, 2041, 2043, 2045, 2047}) do
  local hit = Engine.castRay(vec3(x0+dx, y0+1000, z0+3000), vec3(x0+dx, y0+1000, z0-10), true, true)
  r['render_'..dx] = hit and (hit.pt.z - z0) or 'miss'
end
be:setPhysicsRunning(true)
return jsonEncode(r)
```
- **Pass/decide:**
  - `dz/q == 1/64` (±1e-5) means the engine divides by 65535. `0.015624762` means 65536.
  - `dz` at gx 1021/1022 vs the block z gives the valid edge.
  - `render_2045 ≈ 1024` means the last square renders (2 m gap). `miss` or ≈0 means a 4 m gap.
  - Also take a screenshot of the edge.

### P1b: overlap identity across a commit (after phase 1a)
```lua
-- A) just before a commit (watch the UI 'to commit' distance):
local tb = scenetree.findObject('bngEarthTerrain'); local c = getPlayerVehicle(0):getPosition()
BNGE_SNAP = {}; math.randomseed(7)
for i = 1, 2000 do local a, d = math.random()*6.2832, math.sqrt(math.random())*400
  local x, y = c.x + d*math.cos(a), c.y + d*math.sin(a); BNGE_SNAP[i] = {x, y, tb:getHeight(vec3(x, y, 0))} end
return #BNGE_SNAP
-- B) right after 'terrain block now at' appears in the log:
local tb = scenetree.findObject('bngEarthTerrain'); local m, n = 0, 0
for _, s in ipairs(BNGE_SNAP) do local h = tb:getHeight(vec3(s[1], s[2], 0))
  if h and s[3] then n = n + 1; m = math.max(m, math.abs(h - s[3])) end end
return jsonEncode({n = n, maxAbsDelta = m})
```
**Pass:** `maxAbsDelta ≤ 0.002`. Run once before 1a for the baseline.

### P2: Lua/JSON Material overrides a DAE effect, and translucent instance alpha works on a TSStatic
Python helper: write a 32×32 tile DAE with material `bngEarthProbeFade1`:
```python
import sys; sys.path.insert(0, './server'); import dae, os, math
d = os.path.expanduser('~/.local/share/BeamNG/BeamNG.drive/current/temp/beamngEarth/probe')
p, uv, t = dae.grid(32, 8.0, lambda x, y: 3*math.sin(x*0.05)); dae.write_grid_dae(d + '/fade1.dae', p, uv, t, material='bngEarthProbeFade1')
```
Lua:
```lua
local m = createObject('Material')
m:setField('mapTo', 0, 'bngEarthProbeFade1')
m:setField('diffuseColor', 0, '1 0 0 1')        -- red = our Material won over the DAE's grey effect
m:setField('instanceOpacity', 0, '1')
m.translucent = true
m.canSave = false
m:registerObject('bngEarthProbeFade1Mat')
local o = createObject('TSStatic')
o:setField('shapeName', 0, '/temp/beamngEarth/probe/fade1.dae')
o:setField('collisionType', 0, 'None'); o.useInstanceRenderData = true; o.dynamic = true; o.canSave = false
local cx, cy, cz = core_camera.getPositionXYZ(); local fx, fy = core_camera.getForwardXYZ()
o:setPosition(vec3(cx + fx*80 - 128, cy + fy*80 - 128, cz - 6))
o:registerObject('bngEarthProbeFade1Obj'); scenetree.MissionGroup:addObject(o)
function BNGE_A(a) local t = scenetree.findObject('bngEarthProbeFade1Obj')
  t:setField('instanceColor', 0, string.format('1 1 1 %.3f', a)); t:updateInstanceRenderData() end
BNGE_A(0.3)
return 'screenshot now; then BNGE_A(1)'
```
- **Pass:** red and see-through at 0.3, opaque at 1.
- If the tile is grey, a mapTo Material does not override an already-parsed DAE effect. Then use the `.cdae` path (no effect) or a JSON material loaded before the first tile.

### P3: alpha-tested dither dissolve via instanceOpacity × opacityMap(UV1) (decides C3)
Prerequisites:
- Extend `dae.write_grid_dae` with a TEXCOORD `set="1"` stream: UV1 = `(x, y)·64/256`.
- Write a 64×64 RGBA noise PNG with values in [130, 255] in every channel to `probe/noise64.png`.
- Write `probe/main.materials.json`:
```json
{"bngEarthProbeDissolve": {"name": "bngEarthProbeDissolve", "mapTo": "bngEarthProbeDissolve", "class": "Material",
  "version": 1.5, "alphaTest": true, "alphaRef": 128, "castShadows": true,
  "Stages": [{"baseColorMap": "/temp/beamngEarth/probe/pal.png", "opacityMap": "/temp/beamngEarth/probe/noise64.png",
              "opacityMapUseUV": 1, "instanceOpacity": true, "metallicFactor": 0, "roughnessFactor": 1}, {}, {}, {}]}}
```
Lua:
```lua
loadJsonMaterialsFile('/temp/beamngEarth/probe/main.materials.json')
local o = createObject('TSStatic')
o:setField('shapeName', 0, '/temp/beamngEarth/probe/dissolve.dae')   -- material 'bngEarthProbeDissolve', 2 UV sets
o:setField('collisionType', 0, 'None'); o.useInstanceRenderData = true; o.dynamic = true; o.canSave = false
local cx, cy, cz = core_camera.getPositionXYZ(); local fx, fy = core_camera.getForwardXYZ()
o:setPosition(vec3(cx + fx*150 - 128, cy + fy*150 - 128, cz - 8))
o:registerObject('bngEarthProbeDissolveObj'); scenetree.MissionGroup:addObject(o)
function BNGE_D(f) local t = scenetree.findObject('bngEarthProbeDissolveObj')
  t:setField('instanceColor', 0, string.format('1 1 1 %.4f', 1/(2 - f))); t:updateInstanceRenderData() end
BNGE_D(0.5)
return 'screenshot at f = 0, 0.25, 0.5, 0.75, 1 (call BNGE_D(f)); watch the shadow and the GPU frame time'
```
- **Pass:** the visible pixel fraction is close to f; the shadow is dithered consistently; no shimmer at a standstill; frame-time delta < 0.3 ms for one full-screen tile vs the opaque material.
- **Fail:** the tile is fully visible or fully hidden at all f → keep C2 only.

### P5: `.cdae` direct load, cost vs DAE, resource-cache reuse
```lua
local function spawn(shape, name)
  local t = hptimer(); t:stopAndReset()
  local o = createObject('TSStatic'); o:setField('shapeName', 0, shape); o:setField('collisionType', 0, 'None')
  o.canSave = false; o:setPosition(vec3(0, 0, -2000)); o:registerObject(name); scenetree.MissionGroup:addObject(o)
  return t:stopAndReset(), o
end
local r = {}
local cd = '/temp/temp/beamngearth/lodtest_32_0.cdae'
r.cdaeExists = FS:fileExists(cd)
r.cdae1, a = spawn(cd, 'bngeP5a')
r.cdae2, b = spawn(cd, 'bngeP5b')                                   -- same path again: resource cache?
r.dae1, c = spawn('/temp/beamngEarth/probe/fade1.dae', 'bngeP5c')    -- fresh DAE (written by P2 helper)
r.dae2, d = spawn('/temp/beamngEarth/probe/fade1.dae', 'bngeP5d')
for _, o in ipairs({a, b, c, d}) do o:delete() end
return jsonEncode(r)
```
- **Pass:** `cdae1` loads (non-nil object, visible when moved into view) and `cdae1 ≤ 2.5 ms`.
- `cdae2`/`dae2` ≪ the first load means shapes are shared, which makes re-spawn cheap.

### P6: hidden preload really front-loads the cost
```lua
local t = hptimer(); t:stopAndReset()
local o = createObject('TSStatic'); o:setField('shapeName', 0, '/temp/beamngEarth/probe/fade1.dae')
o:setField('collisionType', 0, 'None'); o.canSave = false; o.hidden = true
local cx, cy, cz = core_camera.getPositionXYZ(); local fx, fy = core_camera.getForwardXYZ()
o:setPosition(vec3(cx + fx*80, cy + fy*80, cz - 6)); o:registerObject('bngeP6'); scenetree.MissionGroup:addObject(o)
local reg = t:stopAndReset()
BNGE_P6 = o:getID()
return jsonEncode({registerMs = reg})   -- then, a few frames later, unhide and read perfmon's worst frame:
-- scenetree.findObjectById(BNGE_P6).hidden = false
```
- Use a fresh DAE name so it is not cached.
- **Pass:** `registerMs` is about the full import cost, and the unhide frame is within +1 ms of base (perfmon `worst`).
- **Fail:** the load is deferred to first render, so prefetch must be "visible but under the terrain" instead of hidden.

### P7: importMaps cost breakdown (decides commit trimming)
Extend `probes/p9_import_variants.lua` to 1024², 2.0 m, the current heightmap (`st.block` path), with `hptimer`:
- variants A_full, B_matsNoTex, C_none;
- `tb:setField('baseTexSize', 0, '256')` vs `'1024'`;
- a separate timing of `tb:setPosition` and `be:reloadCollision()`.

**Decide:** adopt any variant that saves ≥ 10 ms and still renders the dirt material.

### P8: terrain render LOD
```lua
local r = {}
for _, s in ipairs({1.0, 0.5, 0.25}) do
  VariableRegistry.set('$pref::Terrain::lodScale', s)
  r[tostring(s)] = getConsoleNumber('$TerrainBlock::cellsRendered')
end
return jsonEncode(r)  -- read each value one frame after setting (run three times, one scale per call), plus perfmon p50
```
**Pick:** the lowest scale whose p50 frame-time cost is ≤ 0.5 ms. Check visually for distant terrain popping while driving.

### P9: file-watcher cost of tile writes and deletes
- With the game idle on our level, run a Python loop that writes N 80 KB files per second into `temp/beamngEarth/probe/w/` via tmp + rename, for N = 5, 20, 50 per second.
- Then delete them at the same rates.
- Record perfmon p50/p99 and maxMs per window.
- **Decide:** the write and delete rate limits. If writes cost > 0.2 ms each, the persistent cache (§4.3) becomes phase 2 priority.

### P10: confirm the dt arguments (validates the perfmon redesign)
```lua
-- 600 frames: compare Σ dtRaw (3rd onPreRender arg) with Σ hptimer wall
-- (implement in perfmon: M.onPreRender = function(dtReal, dtSim, dtRaw) ... end)
```
**Pass:** Σ dtRaw is within 1% of Σ wall. dtReal lags dtRaw after an injected 60 ms `os.clock` busy-wait.

---

## 11. Open risks and questions
- **C2 crossover visuals [I]:**
  - Motion amplitude equals the true LOD error, spread over 0.5 s.
  - If err bounds are wrong, a child may poke through early (a pop of that size). The server's err is measured against a 2× DEM reference, so there is margin.
  - Skirts must exceed Δ.
- **P1 fails** (the engine stores heights differently): fall back to identical *quantised* q via a fixed zBase per anchor region. The bit-identity claim then becomes ≤ 1 quantum.
- **P2/P3 fail:** C2 alone covers complaint 1. C3 is optional.
- **`.cdae` refused or version mismatch:** the stub-DAE fallback, then compileCollada. Keep the DAE path behind a flag and check the version word (0x007C001F).
- **Lattice anchors** change teleport spawn coordinates (player ≤ 3.9 km from the origin). Precision there is still about 0.25 mm in float32 **[I]**.
- **The commit hitch remains** (one isolated frame of about 30–45 ms, ≈ 18–34 ms of sim time skipped) until P7 trimming or a v1.3 near-ground redesign.
- **The orbit camera can look backwards:** priorities and C1 use the camera, not the vehicle velocity.
---

## 12. Probe results (in-game, 2026-10-10, lead): binding for implementation
| Probe | Result | Decision |
|---|---|---|
| **P1** quantisation/edge | Measured dz/q = **0.0156247616 = H/65536**, so the engine computes **h = q · maxHeight / 65536**. Samples gx 0..1022 return heights via getHeight; gx 1023 returns the block z via getHeight, **but physics (castRayStatic) hits up to x = 2045.x** (interpolating toward sample 1023) and misses at 2047. | Use **maxHeight = Q · 65536** (Q = fixed quantum, e.g. 2^-k m) and zBase a multiple of Q, so the same world height maps to the same q in every block. Physics valid width = (N-1)·s = 2046 m with s = 2.0; the N/E strip from 2046 to 2048 is a **2 m gap** that far tiles must cover. Write real DEM data into row/col 1023 (no duplicate edge). |
| **P7** importMaps cost | 1024² real heightmap, 2.0 m: **~42 ms warm, ~59 ms on first read**. setPosition 0.02 ms, reloadCollision 1.6 ms. baseTexSize 1024/256/128: no difference. Without material/layer map: 35.5 ms, but it renders the placeholder. | The commit floor is ~42 ms (+cold read). Isolate it (governor). Keep the material. Optional: pre-read the PNG (touch/read a few frames before the commit) to warm the OS cache. |
| **P5** .cdae direct | TSStatic with an engine-written **.cdae shapeName loads fine**. 2k-tri .cdae first load **3.4 ms** (likely includes one-time material init); **8k-tri .cdae 1.5 ms**; 2k-tri DAE 8.3 ms. Re-spawning the same path: **0.12–0.24 ms** (resource cache shared). | **Server writes .cdae** (phase 2 is a go). Persistent, reused paths make re-spawns ~free. |
| **P6** hidden preload | A TSStatic created with hidden = true pays the **full import at registerObject (9.4 ms)**. Unhiding produced no measurable frame cost. | Hidden preload pool works: load ahead hidden, show at swap time for free. |
| **P2** material override + translucent instance alpha | A Lua-created Material with mapTo = the DAE material name **overrides the DAE effect** (tile rendered red). **instanceColor alpha 0.3 vs 1.0 made no visible difference** (translucent = true, instanceOpacity = 1, useInstanceRenderData, dynamic, updateInstanceRenderData). | Material override: usable (static JSON material OK). **Translucent instance fade: FAILED in this setup**, so implement **C2 vertical crossover** (transform-only) as the transition. C3 dissolve stays optional, after a proper P3 probe. |
| **P9** file watcher | Writing/deleting **never-loaded** 80 KB files at 5/20/50 per second: no frame-time change (window unfocused, 30 fps cap, so small costs may be hidden). Observed live: deleting ~400 **loaded** tile files in one burst ~30 s after each rebase caused **200–340 ms frames (4/4 rebases)**. | Server deletes old files **rate-limited at 5/s** (already implemented: `DELETE_INTERVAL`, test enforces non-burst). With a persistent cache, deletes become rare. |
| P3, P8, P10 | Not run. | P8: leave lodScale default for now. P10: perfmon already records hptimer wall plus dtSim. |

Live perf session (2026-10-10, ~45 min, docs/research/perf-session-2026-10-10.jsonl):
- Terrain-follow commits 57–63 ms, i.e. one 71–84 ms frame.
- Rebase 61–65 ms, followed by an 8–11 s far-tile reload at ~44 fps.
- **Time-warp correlation:**
  - samples with far-tile churn: 6.6 slow-sim frames per 2 s, minimum ratio 0.87;
  - samples with a terrain-follow: 9.5 per 2 s, minimum ratio 0.83;
  - no churn: 1.0 per 2 s.
- Server: 3–6% CPU, RSS levels at ~400–415 MB.
