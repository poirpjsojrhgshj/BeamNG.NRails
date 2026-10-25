# LOD research: stock BeamNG vs BeamNG.Earth (2026-10-14)

Read-only research. Nothing in the project, game or server was changed. "Guess" marks anything not
confirmed by a file.

## 0. Headline findings (the soft far terrain)

1. **Stock depth of field blurs everything beyond ~250 m, and it is on.**
   - The user's `postfxsettings.postfx` uses the stock preset: DOF Enable true, BlurFar 0.25,
     FocusDistance 250, FocusAperture 100, BlurCurve 10, BlurCurveNear 20, AutoFocus false. The same
     values are in `lua/ge/client/postFx/presets/defaultpostfxpreset.postfx`, and `settings.json` has
     PostFXDOFGeneralEnabled True.
   - How the blur is computed:
     - `lua/ge/client/postFx/dof.lua` `setShaderConsts` sets focalDist 0.
     - The shader `shaders/common/postFx/dof/DOF_Final_P.hlsl` works on the depth divided by the far
       plane (`realToEyeLinearDepth` in `gbuffer.hlsl`).
     - `dofFocusLine` is never set from Lua, so steepness = 0.01.
     - With those inputs, farCoC = clamp(1 - exp(-(1000 / farDist) * (d - 225 m)), 0, 0.25).
   - What that means on screen (my derivation from the code, not measured):
     - At our farDist of 100 km or more, farCoC reaches its 0.25 cap by about 255 m.
     - At a stock farDist of 12-25 km it reaches the cap within a few metres of 225 m.
     - At CoC 0.25, `InterpolateDof` (lerp distances 0.2 / 0.3 / 0.5) blends about 73 % of the
       4-tap "small blur" over the sharp image.
     - The result is a constant ~1.5 px softening of everything past ~250 m. It is in screen pixels,
       so larger textures cannot beat it, which fits the `--tex` A/B showing no difference.
   - Stock maps get the same blur, but there it falls on haze and small views.
2. **The game renders at 2560x1440, not 4K.**
   - `current/beamng.log`: "Applying graphic settings: \\.\DISPLAY3, Fullscreen, 2560 x 1440 144 Hz".
   - "Available Video Modes" tops out at "2560 1440", and every swapchain in the logs is 2560x1440 or
     1280x720.
   - If the panel really is 4K, the compositor upscales 1.5x. Guess: Wayland fractional scaling at
     150 % reports a logical 2560x1440. That would soften everything, and fine distant detail most.
3. **Grazing-angle minification.**
   - From a 1.5 m eye, a ground pixel at distance d is stretched by d / 1.5 along the view: 670:1 at
     1 km.
   - 16x anisotropic filtering covers only 16:1. Past that the GPU falls back to coarse mips, so flat
     far ground (Lancaster farms) is mip-limited, not texture-limited, whatever `--tex` is.
   - Our mips are plain 2x2 box averages of sRGB values, which gives the softest and slightly
     darkest possible chain:
     - `server/imagery.py` `mip_chain` / `write_dds` (DXT1)
     - `server/bc7.py` `mips`
4. **Little haze.**
   - Our LevelInfo: fogDensity 4e-5, fogAtmosphereHeight 1000, visibleDistance 100 km or more.
   - Stock levels: fogDensity 2e-4 to 1.5e-3 (5-40x ours) with fogAtmosphereHeight 76-256 m, and
     visibleDistance 5-25 km. Values per level:
     - Johnson Valley: 1.5e-3 / 76 m / 24.5 km
     - Utah: 3e-4 / 256 m / 5 km
     - West Coast USA: 3.5e-4 / 193 m / 15.7 km
     - East Coast USA: 2e-4 / 182 m / 12 km
     - Italy: 2e-4 / 246 m / 25 km
   - Stock maps hide far softness behind aerial perspective; ours shows the far ground at full
     contrast, so blur and pixelation read as "low quality". The haze TODO is still open in
     `horizon.lua` (lines 14-15).
5. **Real texel density at 4K, for slopes facing the camera (no grazing).**
   - Default `farfield.TEX_DEFAULT[64] = (256,256,256,512)` gives:

     | Level | Shown from | Metres per texel |
     |---|---|---|
     | L-1 | <150 m | 0.5 |
     | L0 | <400 m | 1 |
     | L1 | 0.4-1.5 km | 2 |
     | L2 | 1.5-3 km | 2 |
     | L3 | 3-5 km | 4 |
     | L4 | 5-10 km | 8 |
     | L5 | 10-20 km | 16 |

   - One 4K pixel at about a 50 deg vertical FOV is ~0.4 mrad: 0.4 m at 1 km, 2 m at 5 km, 4 m at
     10 km.
   - So facing hillsides are magnified 2-5x at 4K, and 1.3-3x at 1440p. Texture size does matter
     there, but only once items 1-2 stop masking it.

## 1. How stock BeamNG does LOD

### Graphics settings (`lua/ge/extensions/core/settings/`)

| Setting | Pref it changes, per preset | Applies to |
|---|---|---|
| Mesh Quality (`meshQuality.lua`) | `$pref::TS::detailAdjust` 0.5 / 0.75 / 1 / 1.5 / 2 (Lowest..Ultra); `skipRenderDLs` 0 | Multi-detail TS shapes only: it scales the projected pixel size used to pick a detail level |
| Terrain Quality (`terrainQuality.lua`) | `$pref::Terrain::lodScale` 2 / 1.5 / 1 / 0.75; `$pref::Terrain::detailScale` 0.5 / 0.75 / 1 / 1.5 | TerrainBlock only (then `updateAllTextures`) |
| Texture Quality (`textureQuality.lua`) | `$pref::Video::textureReductionLevel` 2 / 1 / 0 (drops top mips); `refractTexScale` | All textures |
| Anisotropic (`graphic.lua:913`) | `$pref::Video::defaultAnisotropy` 0/2/4/8/16 | Presets: Lowest 0, Low 2, Normal 4 (also the `settings/defaults.json` default 4) |
| Grass density | `$pref::GroundCover::densityScale` | GroundCover |
| Other prefs found in the exe | `$pref::TS::smallestVisiblePixelSize` (user: -1, off), `$pref::TS::maxDetail...` | TS shapes |

- The user's own values: aniso 16, Mesh Ultra (detailAdjust 2), Terrain High (lodScale 0.75,
  detailScale 1.5), Texture Normal (reduction 0), grass 1, SMAA, DOF on.
- No mip LOD bias pref exists. `mipLODBias` / `GFXSAMPMipMapLODBias` / `maxAnisotropy` are
  sampler-state strings in the exe and are not exposed to Lua.
- Shader materials sample through one global `defaultSampler2D` (`shaders/common/bng.hlsl:22`).
- Material stage field `useAnisotropic` ("Use anisotropic filtering for the textures of this stage")
  exists. Guess: the global sampler takes `defaultAnisotropy`.

### TerrainBlock

- Stock levels set only a few fields: `baseTexSize` 2048-4096, `squareSize` (Johnson Valley 0.75),
  `maxHeight`, `materialTextureSet`. `screenError` / LOD fields stay at their defaults. Distant LOD is
  controlled by `$pref::Terrain::lodScale`.
- Stock TerrainMaterials (West Coast USA `art/terrains/main.materials.json`):
  - detailDistances mostly [0, 0, 50, 3000] with the far detail strength 0 (detail fades by about
    50 m).
  - macroDistances [0, 0-10, 100, 3000] with macro strengths of about 0.1-0.5 at far range.
  - Macro textures at 30-50 m scale keep variation out to 3 km.
  - Texture set: base 4096, detail and macro 1024.

### Meshes (cdae)

- Naming convention: `base00` → `start01` → `<mesh>_a700`, `_a400`, `_a200`.
  - The suffix is the pixel size at which that detail level shows.
  - `bb_autobillboard25` is an imposter detail level shown below 25 px.
  - `Colmesh-1` is the collision mesh.
  - `.dae.asset.json` holds the imposter settings (dimension 256, 16 equator steps), plus
    `.imposter.dds` / `.imposter_normals.dds`.
- Example: East Coast USA `tree_aspen_forest_a.dae`.
- The engine picks a detail level per frame from projected size × detailAdjust.
- West Coast USA uses TSStatic `forceDetail -2` on 153 objects.

### Forest, groundcover, decals

- Forest: only `lodReflectScalar` (0-0.15) is set. Items get the shape's own detail levels and
  batched imposters (`RenderImposterMgr`). There is no density fade.
- GroundCover:
  - Typical stock values: radius 50-120 m, dissolveRadius 30-80, shapeCullRadius 45-100,
    maxBillboardTiltAngle 40.
  - West Coast USA also has `shrubs_far` with radius 350 m / dissolve 250 m.
  - Density is multiplied by `densityScale`.
- DecalRoad distanceFade: mostly [200, 50] in West Coast USA, [80, 40] in Italy, [150, 50] in
  Johnson Valley, [400, 200] in Utah.

## 2. Our LOD mechanisms

| Mechanism | File | What and where |
|---|---|---|
| Far terrain quadtree | `server/farfield.py` | 64 cells; K table {1: .75, 2: 1.5, 3: 1.5, 4: 1.25}; near radii L-1 to 150 m, L0 to 400 m; 25 % hysteresis; 2 s hold; tex per level (256,256,256,512); horizon mode roots at L10 out to 80 km-1500 km with a horizon cull; HORIZON_TEX 8: 256, 9: 256, 10: 128 |
| Swap transitions | `crossover.lua` | Two-phase vertical crossover, 0.25 s + 0.25 s, 24 at once; beyond 5 km at the cap it pops |
| Far-tile shapes | `server/cdae.py:450-470` | One detail "detail2" (size 2 px), smallestVisibleSize 2. The engine never switches or culls them until 2 px; the server quadtree is the only LOD |
| Imagery textures | `server/imagery.py` | DXT1 with a full box-filtered mip chain; 8-texel gutter (seam-free down to mip 3); source zoom matched to the texel size (`zoom_for`) |
| Far material | `satmat.lua` | v1.0 Material: colorMap, useAnisotropic 1, roughness 1, detailMap `detail_ground.dds` on UV1 at 4 m, whose mips fade to grey (a distance fade done through mips) |
| Static palette material | `bngEarthFar_v3` | Untextured tiles only |
| TerrainBlock | `terrain.lua` | Physics only in mesh mode (render disabled), baseTexSize 1024; the detail look uses detailDistances 0 0 50 80 and macroDistances 0 0 150 1500 |
| Trees and props | `trees.lua` | Stock Forest items. RINGS shows rank < 1.0 to 300 m, 0.5 to 550 m, 0.25 to 900 m, then 0.12. GROUP_MAX_M caps props (doors 120 m … wall signs 800 m). Server vegetation sent to 1280 m |
| Groundcover | `groundcover.lua` | Stock defs with share 0.05-0.25; long grass radius 70 / dissolve 45; own DENSITY 0.5 / 1 / 2 on top |
| Roads | `roads.lua` | DecalRoad distanceFade '450 150'; road tiles sent to 640 m, dropped at 960 m |
| Buildings | `server/buildings.py` | Near meshes in road tiles (≤ ~640 m); "lite" far tiles to 1600 m (dropped at 1900 m) |
| Sea | `sea.lua` | WaterBlock gridSize 220, element 0.8; River LowLODDistance 120 |
| View distance | `horizon.lua` | visibleDistance = max(100 km, 1.1 × radius) |

## 3. Comparison

### Overlaps with what the engine does

- **Terrain:** our quadtree does what TerrainBlock LOD does, but a single TerrainBlock cannot stream
  hundreds of km, so this is not redundant.
- **The game's own sliders do nothing for most of our world:**
  - Terrain Quality has no effect on our ground in mesh mode, because the block is not drawn.
  - Mesh Quality has no effect on our single-detail shapes; it only affects the stock trees and
    props.
- **Grass density is doubled up:** groundcover `M.DENSITY` and the engine's `densityScale` both scale
  the same thing.
- **Trees:** the engine already turns each tree into a cheap batched imposter. Our RINGS thinning
  (to 12 % past 900 m) is not duplicated by the engine; it is extra and makes far forest look sparse.
  Worth re-measuring the Forest cost with gentler rings.
- **Buildings:** the server swaps tiles (near mesh ↔ lite mesh) where the engine could switch per
  frame if the cdae carried two detail levels.

### Engine features we bypass or leave weak

- Box sRGB mips (see 0.3).
- No macro-scale variation on the far ground. Stock maps use macro textures out to 3 km; our only
  far detail texture fades out through its mips.
- Almost no haze (see 0.4).
- No control over DOF in our world (see 0.1).
- **Fine as is:**
  - We do write full mip chains.
  - Anisotropy is set, and the user runs 16x.

## 4. Recommended changes (ranked by expected payoff, all low-risk)

1. **A/B DOF off** (Options > Graphics > Post FX > Depth of field) at the same far views; zero code.
   - If that is it, have the mod set DOFPostEffect `farBlurMax = 0` while in our level and restore it
     on unload:
     - Use `dof.lua` `setFocusParams` or `$DOFPostFx::BlurMax` + `updateDOFSettings`.
     - The place for it is `sky.lua` / `horizon.lua`, next to the visibleDistance handling.
2. **Check the render resolution:**
   - In the in-game display options, does the resolution list offer 3840x2160?
   - What is the compositor scale on DISPLAY3?
   - If the game is capped at 1440p, fix the OS scaling or the mode. Then repeat the `--tex` A/B at a
     real 4K.
3. **Sharper mips** in `server/imagery.py` `mip_chain` (and `bc7.py` `mips`):
   - Downsample in linear light.
   - Use a Kaiser / Lanczos-3 filter instead of 2x2 box.
   - Add a mild unsharp mask on levels ≥ 1.
   - Server-only, deterministic, no protocol change.
4. **Haze:** implement the `horizon.lua` TODO.
   - Use `core_environment.setFogDensity` / `setFogAtmosphereHeight` toward stock-like values.
   - The weather module's "Real" mode may already override fog.
5. **Raise far texture size only after 1-3**, and only where it can be seen:
   - Set L3+ to 1024 with `--tex 256,256,256,512,1024`, i.e. `farfield.TEX_DEFAULT[64]`.
   - Judge it on facing slopes at a true 4K.
6. **Far-ground macro variation:**
   - Add a second, coarse world-locked grain (~64 m repeat) whose mips stay alive to ~3 km.
   - Satmat / v1.0 only has one detailMap, so this means a v1.5 material or baking it into the imagery.
   - Guess at the payoff.
7. **Trees:** try RINGS { {300,1}, {700,0.6}, {1500,0.35}, {1e9,0.2} } and measure Forest ms
   (`trees.lua:11`).
8. **Buildings:** put the lite mesh as a second cdae detail level (e.g. size ~40 px) in the near
   tiles (`cdae.py` details vector). The engine then LODs by screen size and `detailAdjust`, and the
   server's bldfar swaps get simpler. Low priority.

## Files read

Project:
- `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`
- `mod/.../levels/beamng_earth/main/MissionGroup/Sky/items.level.json`
- `art/terrains/main.materials.json`, `art/shapes/beamngEarth/{main,buildings}.materials.json`
- `satmat.lua`, `terrain.lua`, `trees.lua`, `groundcover.lua`, `roads.lua`, `sea.lua`, `crossover.lua`,
  `horizon.lua`
- `server/farfield.py`, `server/imagery.py`, `server/bc7.py`, `server/cdae.py`, `server/buildings.py`,
  `server/roads.py`, `server/vegetation.py`, `server/earthd.py`

Game:
- `lua/ge/extensions/core/settings/{graphic,meshQuality,terrainQuality,textureQuality}.lua`,
  `settingsPresets.json`, `settings/defaults.json`
- `lua/ge/client/postFx.lua`, `lua/ge/client/postFx/dof.lua`, `presets/defaultpostfxpreset.postfx`
- `shaders/common/postFx/dof/DOF_Final*.hlsl`, `shaders/common/gbuffer.hlsl`,
  `shaders/common/bng.hlsl`
- Stock levels' `items.level.json` (West Coast USA, East Coast USA, Utah, Italy, Johnson Valley),
  West Coast USA terrain materials, East Coast USA `managedItemData` and aspen dae / asset.json
- Exe strings

User folder:
- `current/settings/{settings.json, game-settings-old.cs, postfxsettings.postfx, taa_standalone.json}`
- `current/beamng*.log`
