# High-speed ladder, detail near-visual mode (2026-10-12)

Simulated drives and flights with `tools/drive.py` from Fells Point (39.2834, -76.5934), heading north,
server `earthd -v --status-interval 1 --deshadow full --near-visual detail` (512² block at 2 m, 64-cell
tiles). Speeds are increased until something breaks. "Edge margin" is the smallest distance from the
player to the block's collidable edge (negative: past it; the mod's edge warning).

## What broke, and the fixes

| Run | Result | Cause found |
|---|---|---|
| ground 58 m/s, before | fell after 0.5-0.8 km | blocks took 3-13 s to build; the block must move every 128 m (2.2 s at 58 m/s) |
| | | `roadwidth` ray casts: one Python call per ray (vectorised: same results, 4x) |
| | | every block recomputed all 262k heights (`heightmap.ChunkCache`: 128 m chunks, bit-exact, a moved block computes 1/8) |
| | | a map cell's first road plans and widths: 2-10 s (planned ahead along the velocity and within 2 km) |
| | | one interpreter: three far-tile workers made a block 3-10x slower (blocks in their own processes, `blockworker.py`) |
| ground 58 m/s, after | **pass**, 10 km, 0 falls, blocks 0.6-0.9 s | |
| flight 90 m/s, 40 m | edge margin -120 m | the event loop stalled 2.5-3.5 s (stack-sampling watchdog): `surface.prefetch` read whole `.npz` files per pose (now a file test), `group_deltas` ran on the loop (now a thread) |
| | | a request queued behind a prefetch in one block process (now two lanes, 4 waiting threads) |
| | | follow commits waited for a governor heavy slot past the hard commit distance (now urgent there) |
| flight 90 m/s, after | **pass**, 12 km, margin +62 m, 0 stalls | |
| flight 134 m/s, 60 m | **pass**, 16 km, margin +149 m | far-tile backlog grows (+101/min) |
| flight 200 m/s, 80 m | **pass**, 20 km, margin +69 m | far-tile backlog +131/min |
| flight 300 m/s, 400 m | **fail**: margin -730 m | the block requests outrun the answers (p50 1.3 s at altitude); fps 44 |

The ground ladder above 58 m/s is not meaningful on this line: the driver holds the car on the static
collision along a straight line through city blocks, and at 88 m/s it blew up (NaN) on the buildings /
curbs at 0.8 km. The flights hold a fixed height above the start ground: below ~100 m the hills north
of Baltimore come through the car (the user saw it clip and wreck; the streaming numbers stand, the
driver places it every frame). Fly the high rungs at 400 m with a climb (a jump to altitude in one frame
also blows the car up).

## The mod's follow wait counters

`status().followWait` (frames past the commit distance without a commit, by cause): at 200 m/s
`{server 1567, gate 775, governor 0}`; at 300 m/s `{server 2788, gate 41}`. The remaining limit is the
server's answer time against the block's 128 m grid, then the far tiles (the uncover gate).

## Next

- Far tiles: the backlog grows from 134 m/s; they share one interpreter with the server (processes like
  the blocks), and at altitude the horizon adds many.
- The base photo is still rendered in the server process (imagery corrections live there): 0.4-1.3 s of
  a block's answer.
- Commit frames of 60-80 ms in the game (37-51 per run).
- Lazy unloading (the user, 2026-10-12): keep tiles and blocks around when turning back; deletes are not
  a measured cost today.

## Frame rate (2026-10-12/13)

**Roads and sidewalks** (`earthd --sidewalks off`, `--roads off`; a 58 m/s drive north of Fells Point and 30 s
creeping there, one run each):

| | all on | sidewalks off | no roads |
|---|---|---|---|
| drive fps mean / worst second | 42.7 / 27 | 42.5 / 28 | 44.0 / 32 |
| frames over 50 ms | 111 | 89 | 55 |
| worst commit frame | 80 ms | 83 ms | 48 ms |
| creeping fps | 61.4 | 57.7 | 57.9 |

Sidewalks cost nothing measurable; roads add about half the hard dips. `be:reloadCollision()` takes 10 ms
with 27 sidewalk meshes + 30 road meshes + a deck (1.6 ms without, 2026-10-10); the roads module calls it
at most every 0.5 s while tiles arrive, the follow commit once more.

**The block processes are not the frame cost**: a 90 m/s flight at 150 m, `--block-process on` 39.4 fps,
`off` 36.5 fps (and the block fell 3.6 km behind). At 150-400 m the settled far field draws at ~50 fps
against ~90-100 on the ground.

**Where a frame goes** (stationary, toggles): hiding the far tiles, the block, grass, particles, rain, clouds
or SSAO changed nothing; sun shadows off saved ~6 ms. The game's main thread was at 96 % CPU. The game's MCP
`get_performance_metrics` gives a per-subsystem frame breakdown (RenderShadows, Render, Lua, FramePresent,
...); `get_fps_limit_reason` the caps (vsync, 60/30 fps foreground/background limits).

**The game slows down with session age.** The same four fixed free-camera views (`fixedviews.py` in the
session scratch; the orbit camera and the time of day changed the old "stationary baseline" by several ms):
12-13 ms per frame after ~1.5 h of tests, 6.9 ms after a restart (the 144 Hz vsync cap: the fresh game is
faster still). Not the cause: particle emitters (they leak from ground-drive crashes, ~25 per drive; deleting
all of them changed nothing), decals (`decalManagerClear()` changed nothing), scene objects or live
materials (flat). Four 90 m/s flights alone did not age it measurably.

**Root cause of the dips and the "aging" (2026-10-13): the server's memory traffic.** A time series of the
game's own frame breakdown at a fixed view showed the cost alternating between two states every
~15-20 s (shadows 3.4 vs 7-10 ms, ticking 0.75 vs 1.5-2.2 ms, reflections 1.8 vs 4-5.5 ms) with the player
parked and nothing streaming. Not the vehicle (physics paused: same cycle), not the weather (clear, no
precipitation). It followed the server's CPU exactly: the colour-seam analysis (`colormatch`, ~24 s per
region, region after region while the player explores) ran at 100 % of a core in those phases, and
with the server frozen (SIGSTOP) the game stayed in the low state for 40 s. Not SMT sharing (the threads
were on different physical cores): a pure CPU loop changed nothing, one numpy thread streaming large
arrays made the shadow pass 5-6x slower (3.4 -> 16-20 ms). The game's renderer is that sensitive to memory
bandwidth. The "aging" was the analyses' backlog growing with the explored area (plus the test harness's
own numpy work); the leaked particle emitters (BNGP_*, the stock vehicle particles, ~11 per km of
scraping) were a red herring: deleting them changed nothing once measured at a fixed view.

Fix: `pacer.py`, the background analyses run at most `--background-duty` (0.25) of the time. Measured at a
fresh location while they ran: the shadow pass 4.5-6.5 ms instead of 7-10 (baseline 4.0). The remaining
bumps are single ~0.5 s numpy steps. The far-tile geometry moved to worker processes too
(`blockworker.far_geometry`), and the shadow pass is about 1.2 ms cheaper with no roads (the road and
sidewalk meshes cast sun shadows).

**The block-move frame** (`status().commits[i].engine`, the engine's breakdown of the commit frame, 58 m/s
drive): 70-94 ms = ~30 ms Lua (`importMaps` 19-21 ms + `reloadCollision` 8-17 ms), ~20 ms physics (the
collision rebuild), ~13 ms shadows (the changed terrain). The `.ter` swap of §7 of the engine-limits note
(7-11 ms, no collision rebuild) is the next step for it; it changes how the physics ground under the car
loads, so it waits for the user's OK.

**Road collision rebuilds**: every `reloadCollision` is a ~20 ms physics frame; the roads module ran one up
to every 0.5 s while sidewalk tiles arrived. At most every 3 s, and none right after a terrain commit:
p99 frame 38.2 -> 17.2 ms on a 58 m/s drive.

**Lazy unloading** (the user's suggestion): an out-and-back flight imported 15.5 tiles/s on the way back
against 5.6 on the way out. Removed tiles now wait hidden as spares (120 s, at most 400) and are revived:
7.8 tiles/s on the way back, 369 of ~1,770 tile loads revived.

**After tonight** (fresh game, monitors off): a 58 m/s drive through Fells Point at 101-103 fps mean,
p99 17 ms; flights at 134 m/s (400 m) 86 fps with a flat far-tile backlog, 300 m/s 80 fps (it was 44)
but the block still falls behind there (~1 s per block answer).

**2026-10-13, with the user's OK:**
- **`.ter` swap.** The server writes every block as a `.ter` (`heightmap.write_ter`, a new name per build:
  the engine skips a name it already has). Terrain-follow moves load it with `terrainFile` + `postApply`
  (`terrain.swap`) instead of `importMaps` + `reloadCollision`. Heights are identical to the import (9
  points, in-game).
  - Result, 58 m/s drive: every commit swapped, 11-14 ms of Lua, commit frames 32-42 ms (were 70-94),
    p50 9.4 ms, p99 18.5 ms, 101 fps mean, no falls.
  - Teleports, rebases and the first block still import.
- **Altitude rule** (the user: stop following at high altitude, bring it back low).
  - The far tiles do not collide, so the server answers each pose with the highest ground near the
    straight path for the next 10 s (`groundahead.py`, `ground_ahead`).
  - The block holds above 300 m over that ground and resumes below 150 m, counting 8 s of the current
    descent. The server builds no block ahead while it holds (pose `follow`).
  - 300 m/s at 400 m: passes (it failed before), 119 fps mean, worst frame 36 ms.
  - Descent from 400 m at 200 m/s to 60 m at 90 m/s: resumed at ~320 m, block under the car by 234 m;
    25 km pass, min edge margin afterwards 89 m.
- **Terrain detail and altitude.** Nothing chooses detail from the height above sea level: far-tile
  levels follow the horizontal distance only. The horizon radius uses the eye's height above sea level,
  which is right for the curvature (the terrain heights it compares with are above sea level too).
- **What is left of the block-move frame** (~37 ms): Lua ~12 ms (the `.ter` parse), and the shadow pass
  ~14 ms instead of ~1.5 (the frame after `postApply` on a shadow-casting block; physics paused, fixed
  view, 4 of 4 swaps).
  - With the block's `castShadows` off in the swap frame and back on in the next one, the spike goes and
    the swapped heights load (8 of 8). The shadows a few seconds later match a normal swap (synthetic
    120 m ridge, low sun: mean difference < 1 grey level, 17 between two ridge positions).
  - Not used: that frame draws no terrain-cast shadows (west of the ridge the ground goes visibly
    brighter), a one-frame flash in hills at low sun; a slow frame is the smaller evil.
  - Turning it off and on in the same frame keeps the spike. Re-setting `castShadows` to 1 before
    `postApply` once left the old terrain drawn: not safe.
  - The Lua part (`commits[i].ter`, `terrain.lastSwap`; 16 commits, Columbus OH at 58 m/s): the `.ter`
    load (`postApply`) is 10.8-12.6 ms of the 11.0-12.7 ms; the base photo (`setBase`, 9 materials) is
    ~0.2 ms. What is left is the engine's parse and grid rebuild on the main thread (an engine patch
    that loads it on a worker would be the next step).

**NAIP for the near ground (2026-10-13, terrain quality).** The block's base photo came from USGS
ImageryOnly at z16 (~1.9 m pixels, upscaled to the 1 m texels). The USGS NAIP ImageServer has the same
flights at 0.3-0.6 m: `imagery.SOURCES["naip"]`, first in the default chain for z17-18 only.
- **How it is fetched.** One exportImage of a z15 parent (1024 px) is split into its 16 z17 tiles on disk.
  Black texels (outside the flights) make a tile missing, so USGS fills it.
- **Never on the critical path.** A render that meets a NAIP tile not on disk takes USGS there. Only
  `Imagery.warm()` fetches NAIP: one thread, the player's straight path (0-30 s) plus the block's half
  width + 200 m, nearest first.
- **Host behaviour.** In-game the host took 6-10 s a request (512 and 1024 px alike) and answered 5xx to
  parallel requests (breaker trip): one request at a time, 2 attempts, a 6-in-120 s breaker.
- **Result.** Fells Point block photo, same 1 m texels: USGS vs NAIP vs NAIP at 0.5 m texels
  (`naip_2026-10-13/block_photo_usgs_naip_naip2048.jpg`). NAIP shows the houses, trees and parked cars;
  0.5 m texels add little over 1 m, so `BASE_PX` stays 1024.
- **Refresh.** A block built before its NAIP arrived (`Server.base_stale`) has its photo rendered again
  once `Imagery.lazy_ready` says every tile is on disk, under a new name, and sent as `block_base`. The
  mod sets it on the block in use (or on a ready one before its commit).
  - Annapolis, 25 m/s for 6 km: 30 NAIP parents fetched, 7 photos redone (6 applied); 107 fps mean,
    p99 16 ms, worst commit frame 23 ms.
- **Colour.** The NAIP block was a darker, greener square against the far tiles (USGS, colour-matched
  and de-shadowed), its water much darker. `match_colours`: NAIP x blur(USGS) / blur(NAIP), Gaussian
  40 m (20 m left haloes round white roofs), gain clipped to [1/3, 3]: NAIP's detail, USGS's colours;
  the square is gone in-game (`naip_2026-10-13/annapolis_seam_before_after.jpg`, a faint edge left on
  water).
- **USDA's own NAIP service first** (`naipusda`, apps.geo.fpac.usda.gov): 2024-25 flights, 1.6-4 s per
  1024² instead of ~10 s, but black over Maryland (and Denver). Chain naipusda, naip, usgs.
  - warm() asks USGS's NAIP only where USDA's image was black; `lazy_ready` takes the first source
    with data per tile.
  - Columbus OH, 58 m/s for 10 km: all 43 blocks built with >= 99 % NAIP (none redone).
  - p50 10.4 ms, p99 21.6 ms, worst commit frame 26 ms, 93 fps mean (the 142 ms frame is the
    harness stopping in the last second).
  - In Maryland, the slow USGS service still decides: town speeds only.

**Shorter paced slices in the colour match (2026-10-13).** `pace()` wrapped to log the gaps between its
calls, one Fells Point region run offline. Before: `detect_seams` ran 0.7 s per angle pass between two
`pace()` calls (315 times a region) and 1.45 s after its last one; `base_weights` 0.44 s.
- Fix: `pace()` per rotated channel and between the median steps, in the NMS / hysteresis / component
  loops, and `base_weights` in 256-row chunks. Every gap is now <= 0.36 s (most <= 0.26 s); de-shadow
  was already <= 0.3 s. The colour match tests are unchanged.
- In-game A/B (fixed view, vsync off, one region running offline at duty 0.25, 180 s each): shadow pass
  median 1.24 vs 1.27 ms, p99 1.83 vs 1.75 ms (idle 1.19). No measurable difference at this light view:
  last night's pacing had already taken most of the effect.

**The block's edge (2026-10-13, terrain quality).** From the air and at low angles a dark line ran along
the drawn block's edge (Columbus OH, `block_edge_2026-10-13/block_edge_cmp.jpg`). Two causes:
- **The neighbours were L1 tiles** (512 m, 8 m cells, 2 m texels: USGS), next to the block's 2 m
  lattice and 1 m NAIP photo.
  - `forced()` now grows each block box by `DETAIL_RING_M` = 128 m in detail mode: a ring of L-1
    tiles (the block's own lattice, NAIP z17) around it.
  - NAIP is capped at z17, so the L-1 tiles (0.5 m texels) use the tiles warm() fetched for the block.
- **The dark line itself** stayed with the ring, went away in the raw view (block hidden) and stayed
  with the block's `castShadows` off.
  - Top-down it is the block's outermost 2 m cell column, dark on the edges lower than the opposite
    edge (W 218.7 vs E 227.6 m: dark; E: not; N / S 1-2 m apart: faint).
  - So the engine lights a lone block's edge cells as if it repeated: their normals take the
    opposite edge's heights.
  - Fix: `.ter` layer index 255 (a hole) on the outermost samples (`heightmap.TER_HOLE`); the sunk
    edge ring shows there instead.
  - The edge guard keeps the car 15 m inside, so no collision is lost where it matters.
  - Every block load now takes the `.ter`: teleports and rebases swap (and rebuild collision as
    before), and the first import of a session swaps right after.
- **Drives (Columbus, 58 m/s, 10 km):**
  - the earlier route passes (p99 21.5 ms, worst commit 26 ms);
  - a second route went NaN once at 1.8 km mid-block (a physics blow-up, not at an edge), then passed
    10 km on the rerun.

**Maryland's own imagery (2026-10-13; the user asked about it).** The state research
(`2026-10-10-us-state-imagery.md`) lists MD iMAP's six-inch (0.15 m, 2023-25, statewide) and three-inch
layers.
- **Speed.** Six-inch export: ~1.3 s per 1024² (vs ~10 s for the USGS NAIP service; USDA's has
  nothing in Maryland). White outside the state.
- **Source `md6in`.** First in the chain, with `bounds` (never asked outside Maryland's box) and
  `nodata="white"` (> 25 % pure white = missing; roofs stay).
- **Alignment.** Within ~5.6 m of NAIP (phase correlation over a z15 parent). Our road edges sit on
  the streets in both.
- **Licence.** Free with acknowledgement ("State of Maryland, MD iMAP / DoIT", in the credits),
  to re-verify before release.
- **Result.** Baltimore, north from Fells Point, 58 m/s for 10 km: all 43 blocks built with the sharp
  imagery.
- **Apparent regression.** That drive and the morning's Fells Point route east ran at 69-74 fps (101
  this morning), and the east route failed at 4 km: a block answer took 6.4 s (its base photo stage
  5.4 s) and the edge guard held the car.
  - The A/B with a fresh game and a fresh server each (the morning's route, 58 m/s, 10 km):
    - ring 0: pass, 106.7 fps, p99 17.1 ms;
    - ring 128: pass, 100.2 fps, p99 18.2 ms; worst commit 24.6 ms both.
  - So the slow run was the hours-old game session (many teleports), and the ring costs ~6 % fps:
    kept.
- **The base photo stage's tail** (median ~0.6 s, p90 ~2 s, max ~4.7 s; this morning p90 1.1 s, max
  2.6 s).
  - De-shadow waits are now never on the path (`Deshadow.no_wait`; the photo is redone once its
    regions are ready, `Server.base_ready`), but the tail stayed.
  - Its parts over 51 photos: render median 0.23 s (p90 1.32, max 2.49); PNG save median 0.05 s
    (max 1.86); BC7 cache 0.29 s (max 0.45).
  - A 0.05 s PNG save taking 1.86 s, and the loop watchdog's two stalls in `os.path.exists` /
    `os.remove` (0.3 s on an NVMe disk), point at contention for the main process's GIL.
  - Next: profile what holds it, or move the base photo render into a process.

**What held the server's GIL (2026-10-13).** A stack sampler (every thread's innermost frame every 5 ms,
waits excluded) during a 58 m/s drive: road tile builds (roads / junctions / sidewalks / grading Python,
in the default executor) were ~80 % of the main process's busy threads, map data loads ~30 %, far
textures 10-20 %.
- `RuleTable.rows` (feature -> rows, built once) removed a whole-table scan per feature: 8 % on road
  tiles.
- The cost is spread over many functions, so road tiles now build in their own processes
  (`blockworker.roads_tile`, `--road-processes`, default 2; byte-identical tiles, `test_blockworker`).
- Fresh game and server each, Fells Point east, 58 m/s, 10 km:

| road tiles in | fps | p99 | block photo p90 / max | road tiles live |
|---|---|---|---|---|
| threads (0) | 100.7-101.2 | 18.1-18.4 ms | 2.40-2.49 / 4.29-4.64 s | 38 |
| 1 process | 93.9 | 20.5 ms | 0.59 / 0.76 s | |
| 2 processes | 93.0-96.4 | 20.3-21.5 ms | 0.57-0.58 / 0.75 s | 42 |
| 2, paced to 50 % | 94.3 | 20.8 ms | 0.57 / 0.75 s | |

- Pacing the road processes changes nothing, and 10 % more live road tiles cannot explain ~0.7 ms. So
  the cost is the rest of the server keeping up better: its far textures and analyses no longer
  queue behind the GIL and use memory bandwidth next to the game.
- Kept: block delivery is what decides the edge guard at speed (the failed drive today was a 6.4 s
  answer). `--road-processes 0` gives the old balance.
- **Two more checks of that cost** (same drive, fresh game each):
  - The NAIP colour match against a 1/8-size reference (block photo median 0.42 s, max 0.66 s): 92.6 fps.
  - The road processes at nice 15: 94.9 fps.
  - Neither moves it (runs spread 92.6-96.4), so it is neither the imagery work nor CPU competition
    with the road processes. Accepted for now.

**How sharp the block photo is drawn (2026-10-13).** From 120 m straight down the Fells Point photo looked
like 3-4 m texels while its file (MD six-inch at 1 m texels) is crisp.
- The block's `baseTexSize` 4096 instead of 1024 changed nothing.
- A test photo of 1, 2, 4 and 8 texel stripes showed even the 1-texel stripes. So the engine draws the
  photo at its full 1 m; the softness is 1 m texels magnified (+ BC7, the colour match, the detail
  textures, haze).
- Sharper needs finer texels: MD six-inch draws nothing finer than ~1 m (`imagery.py`), NAIP at 0.5 m
  looked hardly sharper; the three-inch ImageServer is the candidate.

**Airports (2026-10-13, `--airports on`).** Runway grading and markings wired (ARCHITECTURE.md "Airports and
runways").
- KBWI 10/28: the centreline 3x smoother than the DEM.
- Markings drawn by the road mesh in the mod's runway paint: threshold stripes, displaced-threshold arrows,
  centreline, side stripes.
- Courchevel (LFLJ, 12-19 %): the game matches the planned profile within +-3 cm at 20 m steps; the
  runway's top end 0.7 m lower (a graded road there).

**Height quantum from block-sized windows.** At Courchevel the "roughness" along the runway was the
block's quantum: 1/16 m (6 cm steps).
- `survey_q` took the relief of the whole +-15 km survey, so every mountain anchor was 1/16.
- A block only holds its own relief (zBase per block, a coarser step for one that does not fit), so
  the survey now takes the largest relief inside any 1.5-block window (61 x 61 samples, 500 m apart).
- Courchevel and Whitney 1/16 -> 1/32 m; Fells Point and KBWI 1/128 -> 1/256 m.
- In-game at LFLJ: the centreline's 2nd-difference RMS (4 m steps) 10.2 -> 2.1 cm.

**Intermittent physics blow-ups in test drives (2026-10-13, open).** Two of ~17 drives today ended with the
vehicle's velocity NaN mid-block (guard clear, the block under the car):
- Columbus OH at 1.8 km (near the Scioto river);
- Fells Point east at 7.5 km (the harbour area), the first drive after a server restart.

The same routes passed on reruns. Both were first passes over freshly built data.

Hypothesis: a colliding mesh that arrived late becomes solid around the car.
- The sidewalks and bridge decks (`roads.lua` `createWalk`, `collisionType` 'Visible Mesh') turn solid
  at the next `reloadCollision` (every 3 s or at a terrain commit).
- On a first pass their road tile can arrive after the car is already on them.
- Or the harness (`tools/drive.py` follows the static-collision ground) lifts the car onto a deck that
  just appeared above it.

Next:
- Log, at every road `reloadCollision`, the new colliders and the player's distance to their meshes,
  and reproduce on fresh data.
- If confirmed, create a collider that the car is touching without collision until it is clear: a
  per-mesh check, since a sidewalk mesh spans its whole 256 m tile.
- First diagnostic (`roads.status().solidAround`, logged): Philadelphia east over the Delaware, 8 km on
  fresh data, no NaN, but 8 sidewalk meshes turned solid with the player inside their bounds (4 while
  parked at the start). The bounds are a whole tile, so it happens every drive. Next: a per-triangle
  test against the vehicle's box.
- Mitigation instead of a finer diagnostic: the server's road tile now lists boxes around its sidewalk
  runs / corners and bridge decks, in 20 m pieces (`roads.collider_boxes`, the tile's `colliders`), and
  the mod holds a colliding mesh while the player's car is within 3 m (2.5 m vertically) of one of its
  boxes: not made, or made since the last `reloadCollision` and removed again before it, then made
  once the car is clear (`roads.lua` `playerIn` / `releaseHeld` / `noteNewColliders`).
  Fresh-data drives, 30 m/s for 6 km each: Philadelphia (north), Washington (east), Manhattan
  (south-west). All passed with no falls; the hold fired 3 times in total. The NaN rate before was
  2 in about 17, so three clean drives do not prove the cause yet. Keep counting across later drives.
- Washington had no NAIP at all (every block USGS 1.9 m): MD iMAP's "white" outside the state comes back
  as 253 in its JPEGs, under the 254 of the nodata-white test, so its blank tiles inside the Maryland
  box (DC, northern Virginia, Delaware) were cached as imagery and warm() counted those places as
  covered. Threshold now 250 (the 25 % share still keeps white roofs); 512 of 3296 cached md6in tiles
  were such blanks (converted to .404 by hand). Same drive after: 49 of 50 blocks >= 99 % NAIP (was 0).
