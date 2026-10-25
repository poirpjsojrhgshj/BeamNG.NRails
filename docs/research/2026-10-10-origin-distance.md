# How far from the origin can BeamNG go, and what should the rebase distance be?

Date: 2026-10-10. Game: BeamNG.drive 0.39.4 (Linux/Vulkan). Desk research only: nothing here touched
the running game or the MCP server. Paths written as `G/...` are under
`~/.local/share/Steam/steamapps/common/BeamNG.drive/`. Facts are marked **[V]** (verified in a file or
source) or **[I]** (inference).

## TL;DR

* **Recommended rebase distance: 15 km by default, with a hard cap of 16.0 km.** Every horizontal
  player coordinate in [8 192, 16 384) m sits in the same float32 binade, so its rounding step (ULP)
  is 0.977 mm everywhere in that range. Moving the trigger from 10 km to 15 km therefore costs
  **zero** precision. It cuts rebases by a third (one every 8.3 min instead of 5.6 min at 30 m/s),
  and each rebase today costs a 50 ms hitch and about 50 s of reduced fps while the tiles re-stream.
  That per-rebase cost will grow once roads (navgraph rebuild), forests and collidable buildings
  exist. Above 16 384 m the ULP doubles to 1.95 mm, so `rebase.MAX_DISTANCE = 25000` should become
  16000. Note that 15 km leaves about 1.38 km of overshoot slack before 16 384 m, which is about 14 s
  at 100 m/s.
* The engine is already built for multi-km coordinates. Vehicle physics is double precision in a
  vehicle-local space, and the GPU renders camera-relative with a split double camera position.
  BeamNG's own maps place content up to 12.6–15.8 km from the origin. The remaining float32 effect
  is the car and camera snapping to a 0.98 mm grid, about 0.9 px peak-to-peak on a road 2 m away at
  4K. That is the same as at Johnson Valley's far edge, and invisible in practice.
* **Most likely cause of the rebase flash:** the engine's temporal passes rebuild the previous frame
  with `currPos - prevPos` of the camera in world space. At a rebase that difference is about 10 km,
  so every pixel gets the maximum velocity. For that one frame, motion blur (on by default) smears
  the whole screen at maximum radius, and the GTAO and SSR histories reset. **Fix:** set
  `scenetree.PostFxMotionBlur.strength = 0` from the frame of phase 1 until 2 frames after phase 2,
  then restore it. Other candidates and a probe plan are listed below.

## 1. Precision model of the engine (verified pieces)

| Subsystem | Precision | Evidence |
|---|---|---|
| Vehicle physics (nodes) | double, computed in a vehicle-local space | [V] `G/lua/ge/extensions/core/cameraUpdate.lua:146` `veh:getRefNodeAbsPositionXYZ() -- vehicle's actual position on a double precision grid`. [V] BeamNG dev *estama*, 2020-09-09: "vehicle physics are always calculated in a local to each vehicle space … no difference if the vehicle is at origin or 10km from origin" ([forum](https://www.beamng.com/posts/1327487/)). |
| Scene object transform (TSStatic, vehicle scene object) | float32 (`Point3F`/`MatrixF`) | [V] `cameraUpdate.lua:145` `veh:getPositionXYZ() -- scene object position - this jumps on the floating point grid`. [V] The engine API docstrings use `Point3F` for positions (e.g. `virtual void setNodePosition(u32 idx, Point3F pos)` in the strings of `G/BinLinux/BeamNG.drive.x64`). [V] An old console test expects float32 rounding: `G/lua/console/unittests.lua:27` (`133007.133 -> 133007.141`). |
| GE Lua math (`vec3`, `quat`) | double | [V] `G/lua/common/cdefMath.lua:8-9` `struct __luaVec3_t {double x, y, z;}` |
| Camera position | split double (`eyePosWorld` + `cameraRemainder`, two float3) | [V] `G/shaders/common/bng.hlsl:290,296` (cbuffer), `:314,316` (previous frame). [V] *tdev* (BeamNG), 2024-10-09: "We just stabilized the camera as a starting point" ([thread](https://www.beamng.com/posts/1767831)). |
| Mesh vertex transform | camera-relative: `subMatrixPosition(subMatrixPosition(instanceTransform, eyePosWorld), cameraRemainder)` and then `worldToScreenPos0` | [V] `G/shaders/common/material/shadergen/v0/defaultMatV0.hlsl:410,438` (the v1.0 material our tiles use); `defaultMat.hlsl:495`; vehicle props `vehicle/propSelection.hlsl:41-52`. The instance translation is a float32 world position, so each object is placed to within ½ ULP, but no large-number cancellation happens in the vertex math. |
| Terrain vertex transform | camera-relative **without** the remainder | [V] `terrainMatV0.hlsl:197`, `terrainMat.hlsl:137`. Slightly worse than meshes, and irrelevant to us because our TerrainBlock is not rendered (our mesh-tile ground takes the more precise path). |
| Sun shadows (PSSM/SDSM, screen-space mask, vehicle shadow map) | camera-relative (`screenToWorldPos0`, `worldPos0ToLightProj`, `vehicleWorldToLightProj`) | [V] `postFx/sunShadowMask/sunShadowMask.cs.hlsl:30-32`, `sunShadowMaskCommon.h.hlsl:20-27`, `lighting/shadowMap/shadowMapPSSM.hlsl:95`. |
| Motion vectors, GTAO and SSR history | camera-relative, with `currMinusPrevCamPos` | [V] `postFx/motionBlur/clear.cs.hlsl:25-37` (comment: "keeps matrix math in small-magnitude space so fp32 stays precise on large maps where absolute world coords reach kilometers"); `postFx/gtao/gtao_upsample.cs.hlsl:90-114`. |
| Particles | **world-space float32** through `modelViewProj` | [V] `particles/particlesV.hlsl:28` `mul(modelViewProj, float4(In.pos,1))`. [I] This is the one render path that is not camera-relative: expect error of about ULP×(a few), i.e. 1–3 mm at 10 km and 2–6 mm at 20 km, on smoke and dust. |
| Debug draw, ProceduralMesh/GPU mesh upload | float32 world | [V] `G/lua/common/cdefDebugDraw.lua:7-17`, `cdefGpuMesh.lua:23-24`. Debug only, and our tiles are `.cdae` TSStatics. |
| DecalRoad | vertices packed relative to a per-batch "leaf origin" with a limited local range | [V] engine string: `DecalRoad [{}] packed position exceeded supported local range of {} meters … leaf origin=…`. [I] Independent of the distance from the origin, but **long DecalRoads must be split** (relevant to paved roads). |
| Depth buffer | engine supports reversed-Z (`BNG_USE_REVERSED_DEPTH_BUFFER`) | [V] `sunShadowMask.cs.hlsl:18`. Depth precision depends on near/far, not on the origin. |
| Sound | FMOD, float32 positions; the engine passes listener velocity | [V] engine strings `getListenerTranformAndVelocity`, `dopplerFactor`. [I] mm-level error at 10–16 km is inaudible. |
| Navgraph / AI | LuaJIT doubles (`G/lua/ge/map.lua`), no world-size constants found | [V] Rebuilt by `map.reset = loadMap` (`map.lua:3960`, `loadMap` at `:2497`), which sends `mapData` to every vehicle (`:2670`, `vehicle/mapmgr.lua:45`). [I] Not a precision limit, but a per-rebase cost once roads exist. |
| Hard world limits | none found | [V] No world bounds, "world size" or maximum-coordinate constant in the Lua, the shaders or the engine strings (searched: `world.?size`, `out of bounds`, `too far`, `largeWorld`, `floating origin`). This is absence of evidence. |

The forum history agrees. The "wicked floating point issues after about 2–4 km" (Occam's Razer, March
2016, [post](https://beamng.com/goto/post?id=333729)) and the "jitter on Italy-size maps" reports
(Jan–Oct 2024, [thread](https://www.beamng.com/posts/1767831)) predate or coincide with the camera
stabilization. BeamNG still says a full fix "requires some core parts of the engine to be rewritten"
(tdev, 2024-10-01). The design described above, with double physics, a double camera and float32
scene objects, matches that status.

## 2. What distances BeamNG's own maps use [V]
Extracted from `G/content/levels/*.zip` (TerrainBlock entries, `items.level.json` object
positions, mesh bounds). The scripts and data are in the scratchpad `research/levels/`.

| Map | Terrain (samples × square) | Terrain extent | Farthest content | visibleDistance |
|---|---|---|---|---|
| Italy | 4096 × 1 m (default) | ±2.05 km | backdrop TSStatics at 9.6–**15.8 km** (`italy_backdrop_long.dae`) | 25 000 |
| Johnson Valley | 4096 × 0.75 m | ±1.53 km | backdrop mesh vertices from −12.6 to **+15.7 km** (`s_backdrop.dae`), backdrop roads to 11.2 km, 78 invisible map-limit walls up to **12.4 km** (`johnson_valley_map_limits/salt_plain_limits`) | 24 500 |
| East Coast USA | 2048 × 1 m | ±1.0 km | rock prefabs at 6.9 km | 12 000 |
| West Coast USA | 2048 × 1 m | ±1.0 km | 3.3 km | 15 667 |
| Automation Test Track | 4096 × 0.5 m | ±1.0 km | river at 4.7 km | 5 500 |

So official content normally keeps driving within about ±2 km and draws scenery out to 12–16 km. Johnson
Valley places walls meant to stop vehicles 12.4 km out, so BeamNG expects cars that far from the
origin [I]. Our 10 km bubble (rebase log `Anchor #37 … 0.089 deg`, terrain block at y = −9216 just
before it) already works in that range.

## 3. Error budget against distance

ULP = float32 spacing at the coordinate. The world jitters relative to the camera by up to 1 ULP
peak-to-peak, because the car and camera follow the snapped scene position (`orbit.lua:293`,
`chase.lua:169`, `driver.lua:123` all use `data.pos` = `getPositionXYZ`). Pixel size assumes 4K
(2160 rows) and a 60° vertical FOV.

| Player distance | ULP | jitter on road 2 m away | at 5 m | chase-cam velocity noise (240 fps) | ENU tilt d/R | ENU drop d²/2R |
|---|---|---|---|---|---|---|
| 2 km | 0.12 mm | 0.11 px | 0.05 px | 0.03 m/s | 0.018° | 0.3 m |
| 8.2–16.38 km | **0.98 mm** | 0.91 px | 0.37 px | 0.23 m/s | 0.074–0.147° | 5.3–21 m |
| 16.4–32.8 km | 1.95 mm | 1.83 px | 0.73 px | 0.47 m/s | 0.15–0.30° | 21–84 m |
| 32.8–65.5 km | 3.9 mm | 3.65 px | 1.46 px | 0.94 m/s | 0.3–0.6° | 84–337 m |

Notes:
* Jitter shows only when the snapped position changes while the camera image is otherwise still:
  crawling, or idle engine shake. At speed it is hidden by real motion. [I]
* The tilt does not hurt precision; it is the cost of the flat ENU bubble. At 15 km a "level" lake is
  0.135° (0.24 %) off level. That is far below tyre rolling resistance (about 1–1.5 %), so parked cars
  do not creep. The rebase turns velocity by the same angle (0.135° at 15 km), which the V1_1 spec
  already accepts at 0.09°. Flat water planes would sit 17.7 m wrong at 15 km, so water must stay a
  curved mesh, as on the roadmap. [I]
* Physics: no distance effect is expected at all (double, vehicle-local). Static collision geometry
  is presumably float32 world data [I, unverified], i.e. 0.5 mm quantization of contact surfaces at
  15 km, well below the 0.4 cm median mesh/terrain mismatch already measured in v1.3.

## 4. Recommended rebase distance

1. **Default 15 000 m** (`rebase.DEFAULT_DISTANCE`), **MAX 16 000 m**, MIN 2000 m for tests. The
   reasons:
   * Precision is identical to 10 km: same binade, 0.98 mm ULP.
   * There is margin: the commit fires at `dist >= distance` (`rebase.lua:39-41`), and a slow
     prepare can overshoot. 16 384 − 15 000 = 1.38 km is ≥ 13.8 s at 100 m/s and ≥ 46 s at 30 m/s.
     If the anchor is still not ready by 16.2 km, log a warning; it is not an emergency, because
     the next binade is only 1.95 mm.
   * Rebases cost a 50 ms frame, about 50 s at 56–70 fps of re-streaming roughly 880 tiles, a
     possible flash, and in future a navgraph rebuild, forest and road moves and a collision
     rebuild. 15 km means one third fewer of them.
2. Do not raise the trigger above 16 km "because it is still fine". Up to about 30 km it would still
   look acceptable (0.73 px at 5 m), but nothing is gained in exchange: the tiles are re-streamed per
   rebase anyway, and particles (the one path that is not camera-relative) degrade linearly.
3. The rebase uses `veh:getPosition()` (float) as input (`rebase.lua:68`). Each rebase therefore
   carries ≤ 0.5 mm of error, which does not accumulate because the tiles are re-placed from Lua
   doubles. `getRefNodeAbsPositionXYZ()` would be exact, but it is not worth the change. [I]
4. Before switching, run probes P1/P2 below to confirm there is no visible difference between 10 km
   and 15 km (theory says they are identical).

## 5. The rebase flash: hypotheses and fixes

Context [V]: in the last session, rebase #37 committed both phases in one frame
(`phase 2 after 0 frame(s)`, `rebase: vehicle move visible after 0 frame(s), as scheduled`,
`~/.local/share/BeamNG/BeamNG.drive/current/beamng.log:12236-12237`), so the Lua-visible world,
vehicle and camera were in sync. The commit frame took 50 ms (about 43 ms of it the TerrainBlock
`importMaps`, ARCHITECTURE v1.1/v1.2). The user's settings (`current/settings/settings.json`):
SMAA (no TAA in this build; `taa_standalone.json` is `"active": false` and has no Lua consumer),
SSAO/GTAO on, dynamic reflections on (2 faces per update), vsync, 239 Hz. Motion blur is not overridden,
so it is on: `G/settings/defaults.json:216-218` gives `PostFXMotionBlurEnabled true, strength 0.3`.
Our level has no `CloudLayer`, so volumetric-cloud history is out of scope.

### H1 (most likely): temporal reprojection sees a camera jump of about 10 km
* [V] The camera-motion velocity of every pixel is built in `postFx/motionBlur/clear.cs.hlsl:25-37`:
  `world_pos_rel_prev = world_pos_rel_curr + uCurrMinusPrevCamPos.xyz`, projected with the
  previous frame's matrix, and capped at 0.5 UV ("sanity cap only"). The shader has **no teleport
  check** (it ignores `.w`). At a rebase the camera's world position changes by |t| ≈ 10 km, so
  every static pixel gets the 0.5-UV cap. Motion blur then "reclamps to its own radius"
  (`velocity_reduce.hlsl:20-55`), and the whole screen is blurred at maximum radius in one direction
  for one frame.
* [V] Vehicle pixels take their velocity from the vehicle's last transform
  (`defaultMat.hlsl:505-516`, `vvd.lastTransform`), which after `setClusterPosRelRot` is the
  old-frame pose. That also gives the maximum velocity, so the car smears too.
* [V] GTAO has a history and accumulates up to 12 frames (`gtao_upsample.cs.hlsl:34`). Its
  reprojection fails (off screen or `tooFast` > 96 px, `:104-114`), so the age resets and AO
  re-converges over about 12 frames (50 ms at 240 fps): a brief noisy or lighter AO "pulse". The
  engine has a teleport flag (`currMinusPrevCamPos.w`, "ctrl+c, respawn", `:107-108`), but nothing
  in Lua sets it ([V]: no Lua API found on RenderView or core_camera). Whether the C++ side sets it
  for a 10 km jump is unknown. The stochastic SSR (`PostFxSSSR`, engine strings `SSSR_*History`)
  has the same issue [I].
* **Fix F1 (cheap, recommended now):** around the rebase, zero motion blur without touching the
  user's settings, and restore it afterwards:
  ```lua
  -- phase 1 (commitRebase), before moveVehicles:
  local mb = scenetree.findObject('PostFxMotionBlur')
  if mb and st.mbSaved == nil then st.mbSaved = mb.strength; mb.strength = 0 end
  st.mbRestoreFrames = 3      -- counted down in onPreRender after finishRebase ran
  -- onPreRender: if st.mbRestoreFrames then ... when it reaches 0:
  --   local mb = scenetree.findObject('PostFxMotionBlur'); if mb and st.mbSaved then mb.strength = st.mbSaved end
  --   st.mbSaved, st.mbRestoreFrames = nil, nil
  ```
  Use `strength`, which `core/settings/graphic.lua:1386-1396` sets live, not `:disable()/:enable()`,
  so no post-effect is torn down or rebuilt. Do not toggle `SSAOPostFx`: its `onDisabled` flips
  `$AL::UseSSAOMask`, which reloads the lighting shaders (`G/lua/ge/client/postFx/ssao.lua:7-15`),
  a hitch. Accept the 12-frame AO re-convergence.

### H2: the 50 ms commit frame itself
[I] At 239 Hz a 50 ms frame is about 12 missed refreshes. The next frame then contains a large real
camera move (30 m/s × 50 ms = 1.5 m), which also earns a strong motion-blur frame. Together these
read as a "blink". **Fix F2:** shrink the commit frame. About 43 ms of it is `importMaps` of the new
anchor's terrain. Pre-import the new terrain into a *second*, hidden, non-collidable TerrainBlock
during prefetch, so the commit becomes swap + `reloadCollision` (1.6–2 ms). That requires probe P7
(can two TerrainBlocks coexist, and does `importMaps` on an inactive block stay off the collision
path?).

### H3: dynamic reflection cubemap or ambient lags behind the jump
[I] With `GraphicDynReflectionFacesPerupdate = 2`, the car's cubemap is rebuilt over 3 frames.
Faces rendered just before or after the rebase come from the same rigid scene, so they should match.
But if the capture position is taken from the previous frame (old-frame coordinates, which in the new
frame lie about 10 km away inside the far tiles), 1–3 frames of wrong reflections and ambient light
on the car would follow. **Test:** P4 (reflections off). **Fix F3 if confirmed:** set
`$pref::BeamNGVehicle::dynamicReflection::facesPerUpdate` to 6 for the 2 frames after the rebase
(`graphic.lua:1235-1241`).

### H4: one mismatched frame between the rendered vehicle and the world
[I] The Lua probe says the move was visible in the same frame. The flexmesh, however, is fed from
physics node buffers (`shaders/common/vehicle/vehicle.h:20-21`, uploaded as floats), which could lag
the scene object by a frame. If they do, the car would be drawn about 10 km away (i.e. vanish) for
one frame. **Test:** a high-fps screen recording (P3) tells H1 (smear), H2 (freeze + blur) and H4
(car missing) apart.

### H5 (confounder): the PerformanceTweaker user mod
[V] `current/mods/repo/performancetweaker.zip` is active. On "GPU pressure" it switches graphics tiers
and toggles `SSAOPostFx`, `PostFxMotionBlur`, `SMAA_PostEffect`, shadow targets and more
(`lua/ge/extensions/PerformanceTweaker/core.lua:595-620`; tiers at `:650-660`, e.g. fpsEMA < 55
selects tier 2). The 56–70 fps re-stream after a rebase is exactly that kind of trigger. In the log
its tier changes were not at the time of rebase #37 (43 912–44 028 s vs 44 079.9 s), but any flash
seen seconds after a rebase may be this mod. **Test:** repeat P3 with the mod disabled.

### Excluded or minor
Shadows are camera-relative and stable [V]. Clouds are not present in our level. TAA is not in this
build. Auto-exposure is driven by luminance (`lastFrameExposure`, `bng.hlsl:318`, `adaptRate 0.1` in
`postfxsettings.postfx`) and only reacts if H1–H4 change the image. The Doppler effect at the rebase
frame (listener velocity) could give a one-frame audio chirp [I]; check by ear in P3.

## 6. Probes to run later (GE Lua via `run_lua`; not run now)

Shared helper: a per-frame hook without a mod file, using the engine's extension proxy
(`G/lua/common/extensions.lua:1086-1163`, the same mechanism flowgraph uses in
`flowgraph/manager.lua:222`):
```lua
-- install: returns immediately; results accumulate in _G.__bngProbe
local P = { frames = 0, rows = {} }
local sink = {}
function sink:onPreRender(dtReal, dtSim) P.frames = P.frames + 1; if P.tick then P.tick(dtReal, dtSim) end end
P.proxy = newExtensionProxy(nil, 'bngEarthProbe')
P.proxy:submitEventSinks({ sink }, {})
_G.__bngProbe = P
-- uninstall: __bngProbe.proxy:destroy(); __bngProbe = nil
```

**P1: Is the scene position on the float32 grid, and how far is it from the double ref node?** (one
shot, at 2 km and about 9.5 km):
```lua
local ffi = require('ffi'); local f = ffi.new('float[1]')
local function f32(x) f[0] = x; return f[0] end
local v = getPlayerVehicle(0)
local sx, sy, sz = v:getPositionXYZ()
local rx, ry, rz = v:getRefNodeAbsPositionXYZ()
return string.format('scene(%.6f,%.6f) f32grid=%s  ref(%.6f,%.6f) f32grid=%s  d=(%.3f,%.3f)mm',
  sx, sy, tostring(sx == f32(sx) and sy == f32(sy)), rx, ry, tostring(rx == f32(rx) and ry == f32(ry)),
  (sx-rx)*1e3, (sy-ry)*1e3)
```
Expect: the scene position is on the grid and the ref node is not.

**P2: Snapping and physics noise against distance** (parked, engine idling, 600 frames). Run at
2 km, then after `beamngEarth_core.setRebaseDistance(25000)` drive (tools/sim_drive.py) to 9.5, 15
and 20 km. Restore 10000 (or 15000) afterwards.
```lua
local P = __bngProbe; local v = getPlayerVehicle(0)
local xs, n, distinct, last = {}, 0, 0, nil
P.tick = function()
  local sx = v:getPositionXYZ(); local _, _, rz = v:getRefNodeAbsPositionXYZ()
  n = n + 1; if sx ~= last then distinct = distinct + 1; last = sx end
  xs[#xs+1] = rz
  if n == 600 then
    local m = 0; for _, z in ipairs(xs) do m = m + z end; m = m / #xs
    local s = 0; for _, z in ipairs(xs) do s = s + (z-m)^2 end
    P.result = string.format('dist=%.0f distinctSceneX=%d/600 refZ std=%.4f mm', math.sqrt(sx^2 + (select(2, v:getPositionXYZ()))^2), distinct, math.sqrt(s/#xs)*1e3)
    P.tick = nil
  end
end
return 'sampling'
-- later: return __bngProbe.result
```
Expect: the ref-node z std is the same at every distance (physics is distance-free), and the
number of distinct scene X values falls as the ULP grows. Pair this with two screenshots one second
apart in cockpit view at each distance and diff them (the v13_investigation method): the pixel diff
on the near road should stay below 1 px up to 16 km.

**P3: Flash isolation** (`setRebaseDistance(2000)`, drive in a straight line, record the screen at
≥ 240 fps with `gpu-screen-recorder -w screen -f 240`, then `ffmpeg -ss … -vf select` the ±5 frames
around the 50 ms hitch). Runs:
(a) baseline;
(b) motion blur zeroed: `__bngProbe.mb = scenetree.PostFxMotionBlur.strength; scenetree.PostFxMotionBlur.strength = 0`, restored afterwards;
(c) like (b), plus the PerformanceTweaker mod disabled.
What to look for: a full-screen directional smear means H1; a frozen frame followed by a blurred one
means H2; the car missing means H4; a reflection change only on the car means H3.

**P4: Reflections** (H3): `__bngProbe.r = VariableRegistry.get('$pref::BeamNGVehicle::dynamicReflection::enabled'); VariableRegistry.set('$pref::BeamNGVehicle::dynamicReflection::enabled', false)`, repeat P3(b), then restore.

**P5: Engine teleport flag for GTAO** (H1, AO part): in P3(b) footage, compare the AO noise in the 3
frames after the rebase with the 3 frames after a vehicle reset (R). The same noise means the engine
treats both as teleports; a visible AO "drop" only at the rebase means our jump is not flagged.

**P6: Particles** (the one path that is not camera-relative): burnout smoke at 2 km and at 15/20 km,
cockpit view, 240 fps recording. Look for smoke sprites shimmering relative to the car.

**P7: Commit-frame breakdown and double-buffered terrain** (H2):
```lua
local sw = function() return require('socket').gettime() end
local T = package.loaded['beamngEarth/terrain']; local F = package.loaded['beamngEarth/farfield']
local P = __bngProbe; P.t = {}
for name, mod in pairs({ terrain_load = T and { T, 'load' }, far_transform = F and { F, 'transform' },
                         far_switch = F and { F, 'switchAnchor' } }) do
  local m, k = mod[1], mod[2]; local orig = m[k]
  m[k] = function(...) local t0 = sw(); local a, b, c = orig(...); P.t[name] = (sw()-t0)*1e3; return a, b, c end
end
return 'wrapped'  -- after the next rebase: return dumps(__bngProbe.t); re-require or reload the mod to unwrap
```
Then test the double-buffer idea in an empty session. Create a second TerrainBlock (`createObject('TerrainBlock')`,
`importMaps` into it while `setHidden(true)`), time `importMaps` on it, and check with
`castRayStatic` that the hidden block does not collide until `be:reloadCollision()` runs after the
swap.

**P8: Per-rebase costs of future systems** (on an official map, to size things before they exist):
`local t=os.clock(); map.reset(); return (os.clock()-t)*1e3` on west_coast_usa gives the navgraph
rebuild cost. Later, the time to move N forest items and N DecalRoads.

## 7. Sources
* Game files (paths with line numbers above): `G/lua/ge/extensions/core/cameraUpdate.lua`,
  `G/lua/common/{cdefMath,cdefDebugDraw,cdefGpuMesh,utils,extensions}.lua`,
  `G/lua/ge/{map.lua,client/postFx/*.lua,extensions/core/settings/graphic.lua}`,
  `G/settings/defaults.json`, `G/shaders/common/{bng.hlsl,material/shadergen/**,postFx/motionBlur/*,postFx/gtao/gtao_upsample.cs.hlsl,postFx/sunShadowMask/*,particles/particlesV.hlsl,vehicle/*}`,
  engine strings from `G/BinLinux/BeamNG.drive.x64`, and level data from `G/content/levels/*.zip`.
* Forum: estama (BeamNG), 2020, "vehicle physics … local to each vehicle space": https://www.beamng.com/posts/1327487/
* Forum: "Double Precision Float" thread, tdev (BeamNG), 2024-10-01/09 ("requires some core parts of the engine to be rewritten", "We just stabilized the camera"): https://www.beamng.com/posts/1767831
* Forum: 2016 report of issues after 2–4 km (obsolete, before camera-relative rendering): https://beamng.com/goto/post?id=333729
* v0.39 release notes (shadow overhaul: SDSM, PCSS, dedicated vehicle shadow, motion blur fixes): https://beamng.com/game/news/patch/beamng-drive-v0-39/
* Terrain file format: https://documentation.beamng.com/modding/levels/level_formats/terrain/
