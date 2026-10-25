# Quick wins from the game's existing features (2026-10-10)

The question: what do the official levels and the 0.39.4 engine already have that our streamed level
does not use yet? Each candidate below costs a day or less. Real weather is first because the user
asked for it ("could we pull from weather data to match the in game sky in weather to real life").

Sources: the game install `$G = ~/.local/share/Steam/steamapps/common/BeamNG.drive`. Level files were
extracted from `$G/content/levels/{west_coast_usa,johnson_valley,italy}.zip` into
`/tmp/claude-1000/.../scratchpad/research3/` (paths below are `levels/<lvl>/...` inside the zips).
Open-Meteo was called live on 2026-10-10. The game and its MCP server were **not** contacted.
Claims are marked **[V]** (verified in code, data or a live API call) or **[I]** (inferred: needs
the in-game check given for it).

## 0. Summary

- **"Set it to realtime" is already done in `sky.lua`** **[V]**. `M.sync()` writes the real UTC
  instant into TimeOfDay every 30 s with `dayLength = 86400` and `play = true`
  (`sky.lua:74-87`, `RESYNC_S = 30`). What is still wrong is the **local clock** in many countries,
  because the UTC offset is guessed from the nearest 15° meridian (`sky.lua:47-53`).
  - Open-Meteo returns the real zone with `timezone=auto` **[V]**: Madrid +2 (guess +1), Urumqi +8
    (guess +6), Delhi +5.5 (guess +5), Singapore +8 (guess +7, `mod/tests/test_sky.lua` pins 7).
  - The weather call already returns this offset, so the fix comes free with #1.
- **Top 5** (ranked by value to the player against cost):
  1. **Real weather from Open-Meteo**, through the engine's own controls: clouds (amount, cirrus,
     height), ground wind that acts on the car and on planes, fog from visibility, rain and snow,
     a darker sky under overcast, and the real time zone. About 1 day.
  2. **Level-file parity**: add the objects every official level has (CloudLayer, Precipitation,
     ForestWindEmitter, a reverb snapshot emitter, `temperatureCurveC`). This fixes 3 latent bugs
     and is what makes #1 and the stock weather UI work. 1-2 h.
  3. **Ambient sound by biome**: the stock room-tone and reverb events (desert, forest,
     Mediterranean, tropical), chosen by a Köppen climate lookup on the server. Today our world is
     silent apart from the car. About half a day.
  4. **Physical atmosphere**: real air temperature (engine and tyre thermals, gauges) and gravity by
     latitude and height. Air density already falls with altitude for free; this needs checking
     in-game. 2-3 h.
  5. **Famous places in the stock level selector** (info.json `spawnPoints` with previews). The
     player picks "Fells Point" or "Whitney summit" when loading the level. This connects to the
     scheduled "Saved places" item. About half a day.
- **Bugs found** that the parity work fixes:
  - **(a)** `core_environment` caches "no CloudLayer" per class. Our CloudLayer is created at
    runtime, so the stock Environment UI cloud slider (and BWM_Weather) may silently do nothing
    (`environment.lua:53-66`).
  - **(b)** We have no `temperatureCurveC`, so the engine's air temperature is never set: the
    Environment UI shows −273.15 °C and drag time slips show 0 K (`environment.lua:1234-1236,
    1267, 1666`).
  - **(c)** The stock weather presets (`core_weather.activate('rainy')`) log "object class not
    found" for Precipitation and ForestWindEmitter (`weather.lua:225-227`).

## 1. Object classes: official levels vs ours

Counted with `scratchpad/classes.py` over every `*.level.json` under each level's `main/`.

| class | WCUSA | JV | Italy | ours | what it gives | quick win? |
|---|---|---|---|---|---|---|
| LevelInfo / TimeOfDay / ScatterSky | 1/1/1 | 1/1/1 | 1/1/1 | 1/1/1 | – | fields differ, see below |
| CloudLayer | 1 | 1 | 1 | **0 in file**; created at runtime by `sky.lua:144-160` | volumetric clouds | move into the level file (bug a) |
| Precipitation | 1 (`numDrops` 0) | 0 | 1 (`numDrops` 0) | 0 | rain or snow particles around the camera | **yes** (#1/#2) |
| ForestWindEmitter | 1 | 1 | 1 | 0 | sways Forest trees | only once we have trees; add now so presets work |
| SFXEmitter, non-3D, `snapshot:>Reverb_*` | 1 | 1 | 1 | 0 | level-wide outdoor reverb on every sound | **yes** (#3) |
| SFXSpace / SFXEmitter (local ambience, tunnels) | 372 / 73 | 1 / 1 | 382 / 10 | 0 | city, tunnel and building reverb zones | later (needs buildings and tunnels) |
| `dynamicAudioEmitters/forestData.audioSFX.json` | yes | yes | yes | no | forest wind event + room tone | room tone **yes** via API (#3) |
| Zone (tunnel lighting) | 33 | 0 | 3 | 0 | darkens tunnels | later (v1.6 tunnels) |
| SpawnSphere + info.json `spawnPoints` | 15 | 6 | 11 | 1, no list | spawn choices in the level selector; bigmap fast-travel POIs | **yes** (#5) |
| GroundCover / Forest / TSStatic / DecalRoad | many | many | many | 0 | grass, trees, props, roads | roadmap v1.5-v1.9 |
| BeamNGWaypoint (navgraph), signals.json | 838 | 0 | 196 | 0 | AI, minimap, GPS | v1.7/1.8 |
| WaterBlock / River / WaterPlane | 3/2/1 | 0/0/1 | 6/7/1 | 0 | water | Water section of the roadmap |
| facilities (gas stations, garages) | yes | yes | yes | no | refuel, POIs | later (§3, 1-2 days) |

LevelInfo fields, from `west_coast_usa/main/MissionGroup/LevelObjects/items.level.json:1`,
`johnson_valley/.../sky/items.level.json:3` and `italy/.../Level_objects/items.level.json:1`:

- All three have **`temperatureCurveC`**, e.g. JV `[0,21, 0.167,22.5, 0.701,10.5, 1,21]` as
  (time of day, °C) pairs; we have none.
- They have their own reflection cubemaps (`cubemap_<level>_reflection`); we use `BNG_Sky_01_cubemap`.
- WCUSA has `bigMapLevelBorderVisible`.

ScatterSky: our `nightColor` / `nightFogColor` are bright where the official levels use black. This
does **not** matter: `core_celestial` forces both to black and sets the moon scale while it is
active (`core/celestial.lua:322-334`) **[V]**. So "black night colours" from the roadmap is already
handled by the engine.

info.json keys that we lack:

| key | official levels | what it does |
|---|---|---|
| `spawnPoints` | all three | level-select spawns |
| `localUnits` (WCUSA) | `{"gasoline":"gallonUS"}` | fuel price units: `career/modules/fuel.lua:110-126`, `freeroam/facilities/fuelPrice.lua:35` |
| `roadRules` (WCUSA) | `{"turnOnRed":true}` | read once by `map.lua:148-155`; `rightHandDrive` = drive on the left, used by AI, spawn and taxi (`spawn.lua:680`, `gameplay/taxi.lua:326`) |
| `country`, `region` | all three | level-selector grouping |
| `minimap` image list | all three | not read by the 0.39 Lua minimap (§3) |

## 2. Engine facts these quick wins rely on

| fact | evidence |
|---|---|
| `core_environment` finds env objects through a per-class id cache; a cached 0 means "none" until the cache resets at `onClientPostStartMission`, `onClientStartMission` or `onEditorDeactivated` | `environment.lua:53-66, 1609, 1688, 1700` **[V]** |
| All cloud setters write the **first** CloudLayer and call `postApply()` | `environment.lua:856-997` **[V]** |
| Ground wind is a world vector in m/s, pushed to every vehicle with `obj:setWind` and `be:setGroundWind`, and re-applied on every vehicle spawn or reset | `environment.lua:46-51, 840-846, 1935-1936` **[V]** |
| UI wind convention: `x = s·sin(dir)`, `y = s·cos(dir)`, where `dir` is the direction the wind blows **towards**, clockwise from +Y (north); max 210 m/s | `ui/ui-vue/src/modules/environmentControls/components/envPanels/EnvWeather.vue:366-377, 272-311` **[V]** |
| Air temperature comes only from `LevelInfo:getTemperatureCurveC()`, read at mission start or when `levelInfo:isEditorDirty()`; with fewer than 2 points the engine is never set and `getTemperatureK()` stays 0 | `environment.lua:1599-1603, 1651-1683` (early return 1666), `1234-1236` **[V]** |
| `setTemperatureK` is local (not exported); it calls `be:setSeaLevelTemperatureK(tempK)` | `environment.lua:1635-1638`, exports `1834-1940` **[V]** |
| Vehicles read `obj:getEnvTemperature()` (tyre thermals `wheels.lua:179,723,850`; powertrain `powertrain.lua:14,179`; fire `fire.lua:75`; dashboard gauges) and `obj:getRelativeAirDensity()` (engine torque × intake air density, `combustionEngine.lua:306,616,748`) | **[V]** |
| The engine computes air density and pressure from **sea-level** temperature and the vehicle's height. Our z ≈ height above sea level, so engines should already lose power on Whitney | name `setSeaLevelTemperatureK` + `getEnvPressure` **[I]** (check §6) |
| Gravity: `core_environment.setGravity(g)` writes `theLevelInfo.gravity` (used for new spawns) and calls `obj:setGravity` on every vehicle | `environment.lua:1194-1205` **[V]** |
| Precipitation: the level field is `numDrops` (all level files, `art/weather/defaults.json:148`). `core_environment.setPrecipitation` writes `numOfDrops`, which may be only a legacy alias | `environment.lua:1218-1223` **[V]**; alias **[I]** |
| Precipitation datablocks `rain_drop`, `rain_medium`, `Snow_menu`, and a 2D rain loop `amb_rain_medium` (SFXProfile, `AudioLoop2D`) ship with the game | `$G/gameengine.zip art/datablocks/managedDatablocks.datablocks.json:793,820,854,862` **[V]** |
| A runtime Precipitation with `followCam=1`, `numDrops` = pool size, `setPercentage(f)` and `setHidden(b)` works | third-party BWM_Weather (`mods/repo/bwm_weather.zip: lua/ge/extensions/BWM_Weather/environmentController.lua`, `TECHNICAL_FINDINGS.md`) **[I]** for us |
| Stock weather presets (`art/weather/defaults.json`): `sunny` vs `rainy`/`cloudy` give the overcast sky look; the overcast values are `colorize` 0.427 grey, `sunScale` 0.686, `shadowSoftness` 1, CloudLayer `coverage` 1, ForestWindEmitter `strength` 1.5 | `$G/gameengine.zip art/weather/defaults.json` **[V]** |
| `core_weather` merges presets from `art/weather/*.json` and `<level>/weather/*.json`; `switchWeather(name, t)` lerps over 15 s | `weather.lua:185-207, 296-313` **[V]** |
| Celestial profile at runtime: `core_celestial.loadProfile(table)` re-pushes atmosphere (Rayleigh, Mie, ozone, ground albedo) to ScatterSky on the next frame | `celestial.lua:375-430, 782-787, 1046-1051`; Earth defaults in `gameengine.zip art/skies/profiles/earth.json` **[V]** |
| Room tone API: `core_audioForest.setRoomtoneEvent(name)` then `setRoomtoneEnabled(true)` creates an unsaved SFXEmitter at (0,0,roomtoneZ) | `core/audioForest.lua:193-232, 412-441` **[V]** |
| The level-file path for room tone needs a TerrainBlock at `onClientCustomObjectSpawning`, which ours does not have (it is created later by `terrain.loadFlat`) | `audioForest.lua:472-493` **[V]**; `core.lua:732-757` **[V]** |
| Stock room tone and wind events by biome: `Roomtone_Desert_01/02` (Utah, JV), `Roomtone_ConiferousDeciduous_01/02` (ECA, WCUSA), `Roomtone_Mediterranean_01/02` (Italy, Cliff), `Roomtone_Tropical` (Jungle Rock); `Wind_*` counterparts | each level's `dynamicAudioEmitters/forestData.audioSFX.json` line 1 **[V]** |
| Every official level has one non-3D `SFXEmitter` with `track = "snapshot:>Reverb_<lvl>"` and `useTrackDescriptionOnly` (e.g. `Reverb_JV`, `Reverb_UT`, `Reverb_EC`, `Reverb_WC_Open`, `Reverb_ATT_Forest`) | e.g. `johnson_valley/main/MissionGroup/Audio/items.level.json:4` **[V]** |
| Level-select spawn: `setSpawnpoint.loadDefaultSpawnpoint()` returns the chosen `spawnPoints[].objectname` if that object exists, else `defaultSpawnPointName` | `setSpawnpoint.lua:30-56`, `spawn.lua:853-862` **[V]** |
| `core_levels` turns every info.json spawn point into a bigmap fast-travel POI at the SpawnSphere's position | `core/levels.lua:524-552` **[V]** |
| Without a navgraph, "recover to last road" only uprights the car in place | `spawn.lua:678-686` **[V]** |
| Cross-level asset references work in official content: JV's CloudLayer uses `levels/jungle_rock_island/art/skies/SkyNormals_05.dds` | `johnson_valley/.../sky/items.level.json:4` **[V]** |
| Wet ground models exist: `ASPHALT_WET`, `GRAVEL_WET` (our terrain uses `DIRT`) | `gameengine.zip art/groundmodels.json:23,233`; ours `levels/beamng_earth/art/terrains/main.materials.json:7` **[V]** |

Open-Meteo, called live 2026-10-10 **[V]**:

- `https://api.open-meteo.com/v1/forecast?latitude=36.58&longitude=-118.29&current=temperature_2m,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,precipitation,rain,showers,snowfall,weather_code,visibility,wind_speed_10m,wind_direction_10m,wind_gusts_10m,surface_pressure,is_day&wind_speed_unit=ms&timezone=auto`
  - It returns all of those fields, `elevation` (4042 m, the model cell height),
    `utc_offset_seconds` and `timezone`, at 15-minute resolution (`"interval":900`).
  - `visibility` works in `current`, although the docs list it under hourly only.
- `https://air-quality-api.open-meteo.com/v1/air-quality?...&current=aerosol_optical_depth,dust`
  is hourly.
- Terms (https://open-meteo.com/en/terms): free for non-commercial use, 600/min, 5,000/h,
  10,000/day; data under CC BY 4.0, so we credit it next to our existing attribution.

## 3. All candidates

Cost is for one developer who knows the codebase. "Rebase" means: does it survive the floating
origin moving the world by kilometres?

| # | candidate | where in the game | what we add | cost | rebase / perf risk | value to the player |
|---|---|---|---|---|---|---|
| A | **Real weather** (clouds, cirrus, cloud height, wind, fog, rain/snow, overcast sky look, time zone) | `core_environment` setters (§2), `art/weather/defaults.json`, Precipitation | server `weather.py` + `weather` message; `sky.lua` applies it | 1 day | Clouds: already shift the weather map on rebase (`sky.lua:170-176`). Wind is a vector. Precipitation follows the camera. Fog `fogAtmosphereHeight` is relative to z = 0 (like cloud altitude) and needs the same follow-the-ground treatment **[I]**. Perf: one HTTP call every ~10 min; rain particles cost GPU at high `numDrops` | **high**: the sky matches the window; crosswind is felt at 300 mph and by plane mods |
| B | **Level-file parity** (CloudLayer, Precipitation, ForestWindEmitter, reverb emitter, `temperatureCurveC`) | official level files (§1) | `tools/make_level_assets.py` → `Sky/items.level.json` | 1-2 h | none (non-positional, or follows the camera) | fixes bugs a-c; makes the stock Environment UI and presets work |
| C | **Biome room tone + reverb** | `core_audioForest` API, reverb snapshots | server Köppen lookup → `biome` field; mod switches events | 0.5 day | room tone emitter at (0,0,z): if the event is 3D it fades away from the origin; then re-place it at the listener every second **[I]**. Perf: one emitter | **medium-high**: wind and insects instead of silence |
| D | **Real air temperature** | `temperatureCurveC` / `be:setSeaLevelTemperatureK` | the day's hourly temperature curve from #A | 2-3 h (with A) | scalar | medium: engine and tyre temperatures and the dashboard outside-temperature gauge are right (hot desert, cold Alps) |
| E | **Gravity by latitude and height** | `core_environment.setGravity` | Somigliana formula in the mod | 1 h | scalar; only call it when the value changes by more than 1e-4 (it queues Lua into every vehicle) | low: 9.780-9.832 m/s², about 0.5 %; "free realism" |
| F | **Level-select famous places** | info.json `spawnPoints`, `setSpawnpoint.loadDefaultSpawnpoint` | N spawn spheres at (0,0,0.5) with `bngEarthLatLon` dynamic fields, preview JPGs, a teleport at level start | 0.5 day | spheres sit at the origin, so core_levels' bigmap fast travel would jump to the anchor origin: wrap it (§5.5) | **medium-high**: pick Fells Point / Whitney / Nürburgring from the stock UI |
| G | Haze from aerosol optical depth | celestial profile Mie terms (`celestial.lua:383-385`) | scale `mieScattering`/`mieExtinction` from `earth.json` by AOD/0.1 | 2 h | none | medium (hazy LA vs crisp Alps); needs visual tuning |
| H | Reflection cubemap per biome | `LevelInfo.globalEnviromentMap`; level cubemaps such as `levels/johnson_valley/art/cubemaps/cubemap_johnson_valley_reflection/` | CubemapData materials pointing at other levels' DDS; switch at runtime with `postApply` | 0.5 day | runtime switch unproven **[I]** | low-medium: car paint reflects a desert or forest horizon |
| I | Wet ground when raining | `ASPHALT_WET`/`GRAVEL_WET` | terrain material `groundmodelName` swap | wait for v1.5 per-cell surfaces (all our ground is DIRT today) | collision reload | medium later |
| J | Drive on the left (UK, Japan, AU) for AI and spawn | `map.getRoadRules()` returns the live `rules` table (`map.lua:157-159`) | mutate `rightHandDrive` after each `setRoadRules` | 1 h, but only useful with v1.8 AI traffic | none | later |
| K | Real gas stations + refuelling (Cannonball) | `freeroam/gasStations.lua` (pumps = scene objects, `enableGasStationsInFreeroam`), facilities cached per level (`freeroam/facilities.lua:78-98`) | OSM `amenity=fuel` → our own `onGetRawPoiListForLevel` POIs + pump trigger objects that move with each rebase | 1-2 days | world-positioned objects must be moved on rebase; rawPois cache must be cleared (`gameplay_rawPois.clear()`) | medium (long trips) |
| L | Stock big map | `freeroam/bigMapMode.lua:249-259` frames `core_terrain.getTerrain():getWorldBox()` (our 2 km physics block) plus POIs | – | – | – | not a world map; replace `M` with our map (`2026-10-10-world-map-ui.md` §1.1, P6) |
| M | Stock minimap | `ui/apps/minimap/*` draws `map.getMap()` roads and a topomap scanned once from the TerrainBlock (`topomap.lua:127-240, 425`) | – | – | – | empty until the v1.7 navgraph |
| N | Radial menu entries ("Earth: home", "real weather on/off") | `core_quickAccess.addEntry{level, generator}` (`core/quickAccess.lua:611-657, 2657`) | one generator in the mod | 1-2 h | none | low-medium convenience |
| O | Reset / recovery in the open world | `vehicle/recovery.lua` points, `spawn.teleportToLastRoad` | already remapped on rebase (`rebase.lua:114-161`) | done | – | – |
| P | Career mode | – | needs facilities, garages, navgraph | days+ | – | not a quick win |
| Q | Thunder / lightning | no public flash API (BWM notes) | – | – | – | skip |

## 4. Ranking

Value per hour: **B** (enables everything) > **A** > **F** > **C** > **D** > E ≈ G > N > H. A and D
share the same server call, so they ship together. E rides along because it is one hour. The top 5
below are B + A + C + D/E + F. G is optional inside A.

## 5. Top 5: concrete steps

### 5.1 (do first) Level-file parity: B

Edit `tools/make_level_assets.py` (the level files are generated by it; lines 23-70), then
regenerate.

- In the `Sky` group add:
  - `{"name":"bngEarthClouds","class":"CloudLayer","texture":"art/skies/clouds/clouds_normal_displacement.png","coverage":0.5,"cirrusCoverage":0.3,"exposure":1.45,"windSpeed":0.1,"baseColor":[0.99,0.99,0.99,0.9],"altitudeKm":1.5}`.
    This is the same as `sky.lua:148-158`; sky.lua then finds it and never needs `createObject`,
    which fixes bug a.
  - `{"name":"bngEarthRain","class":"Precipitation","dataBlock":"rain_medium","numDrops":0,"boxWidth":50,"boxHeight":50,"dropSize":0.6,"splashSize":0.25,"useTurbulence":true,"useWind":true,"followCam":true}`
    (Italy's object plus `followCam`, which BWM uses).
  - `{"class":"ForestWindEmitter","strength":0.5}`.
  - `{"name":"bngEarthReverb","class":"SFXEmitter","is3D":false,"isLooping":false,"maxDistance":0.01,"referenceDistance":0,"track":"snapshot:>Reverb_WC_Open","useTrackDescriptionOnly":true}`
    (copied from JV `Audio/items.level.json:4`).
- In LevelInfo add `"temperatureCurveC":[0,15,1,15]` (ISA 15 °C until real weather arrives),
  which fixes bug b.
- Positions: none matter. Precipitation follows the camera, the emitter is 2D, and clouds use their
  own weather offset, so the floating origin is irrelevant.
- `sky.lua`: keep `cloudObj()`'s `createObject` path only as a fallback.
- Tests: extend whatever already checks `make_level_assets.py` output; at minimum, a Python test
  that loads the generated `Sky/items.level.json` and asserts each class is present once.
- In-game check (after a level reload; camera stays on the user's car, no inputs):
  ```lua
  print(core_environment.getCloudCover(), core_environment.getPrecipitation(), core_environment.getTemperatureK())
  -- expect 0.5, 0 (or nil: numOfDrops alias), 288.15
  core_weather.activate('sunny')   -- no "object class not found" errors in the log
  ```

### 5.2 Real weather: A (with D, E, G)

**Server** (`server/weather.py`, new; hooked into `earthd.py`):

- `fetch(lat, lon)` makes one GET to `api.open-meteo.com/v1/forecast` with the `current=` list in
  §2, `&hourly=temperature_2m&forecast_days=2&wind_speed_unit=ms&timezone=auto`, optionally a
  second GET to `air-quality-api.../v1/air-quality?current=aerosol_optical_depth`.
  - Use the existing `urllib` and `USER_AGENT` pattern (`dem.py:94`), run in the thread pool.
  - Cache by (0.1° cell, 15-min slot) in memory.
- The trigger runs in `Session.on_pose`:
  - convert the focus to lat/lon (`self.s.anchors[self.active].frame.enu_to_geodetic(x, y)`,
    `geodesy.py:83`);
  - refetch when there is no weather yet, the player moved more than 20 km from the last fetch, or
    the data is older than 10 min;
  - at most 1 in-flight request.
  - At ≤ 6 calls/h per player this is far inside 5,000/h.
- On failure, log and keep the last weather; send nothing new (the mod keeps its current state).
- Add `"Weather: Open-Meteo.com (CC BY 4.0)"` to `attribution()` (`earthd.py:473`).
- New message, server → mod. `PROTOCOL` stays 4: the mod's `onMessage` ignores unknown types
  (`core.lua:406-497` has no else-error) and the server ignores unknown types (`earthd.py:775`).
  ```json
  {"type":"weather","lat":36.58,"lon":-118.29,"time":"2026-10-10T20:15Z","tz":"America/Los_Angeles","utcOffsetH":-7,
   "cloud":{"total":2,"low":0,"mid":2,"high":0},"precipMmH":0.0,"snowCmH":0.0,"code":0,"visibilityM":60800,
   "wind":{"speedMs":9.53,"fromDeg":233,"gustMs":13.7},"tempC":3.5,"elevM":4042,"pressureHpa":620.5,"isDay":1,
   "tempCurveC":[t0,c0, t1,c1, ...],"aod":0.07}
  ```
  `tempCurveC` holds 25 points of today's hourly `temperature_2m`, already converted to sea level
  (`+0.0065·elevM`) and keyed by TimeOfDay time `(localHour/24 − 0.5) mod 1`, sorted.
- Optional mod → server message `{"type":"weather_refresh"}` forces a fetch (console/UI button).
- Tests (`server/tests/test_weather.py`):
  - parse a recorded Open-Meteo JSON fixture (the one above) into the message;
  - cache-key and refetch rules (move 19 vs 21 km, 9 vs 11 min);
  - the temperature curve is sorted, 0 ≤ t < 1, and wraps at local noon;
  - no network in tests (inject `fetch`).

**Mod** (`sky.lua`; pure mapping functions first, so `mod/tests/test_sky.lua` covers them):

- `M.onWeather(msg)` is called from `core.lua onMessage` (`elseif t == 'weather'`).
  - It stores `msg` and sets the targets.
  - A per-frame lerp (60 s, like the stock 15 s `switchWeather`) moves the current values towards
    them, so there are no pops after a teleport.
- `M.utcOffset`: `M.sync()` uses `msg.utcOffsetH` when a weather message exists for a point within
  200 km, else the `utcOffsetFor` guess. This fixes Madrid, China and India.
- Pure mappings (all **[I]**, tune in-game; the constants live at the top of sky.lua):
  - `coverage = 2.0 * (max(low, mid)/100)^0.8`. The UI range is 0..3 (`EnvWeather.vue:450`);
    official "fair" levels sit at 1-1.23; stock "cloudy" = 1.
  - `cirrusCoverage = CIRRUS_MAX * high/100`.
  - Cloud base above the ground: `low ≥ mid` → 1.0 km, else 3.0 km.
    This becomes `CLOUD_ABOVE_KM` in the existing follow-the-ground code (`sky.lua:126-133`).
  - Wind: `w = speed · (−sin θ, −cos θ, 0)`, θ = `fromDeg`.
    Meteorological "from" is the opposite of the UI "towards" vector (`EnvWeather.vue:366-377`).
    Our ENU +Y is true north at every anchor, so no rotation is needed.
    - Apply with `core_environment.setGroundWind(vec3(w))`; set the cloud
      `windDirection = Point2F(−sin θ, −cos θ)` and `windSpeed = 0.01·speed` (official 0.1-0.2).
    - Optional gusts: every 2-6 s a random magnitude between speed and gust (seeded),
      smoothed over 1 s. Call `setGroundWind` at most 2×/s: each call queues Lua into every vehicle
      (`environment.lua:49`).
  - Fog: if `visibilityM < 20000`, `fogDensity = clamp(3/visibilityM, 4e-5, 0.02)`
    (Koschmieder; Torque's exponential fog **[I]**); else keep the level's 4e-5.
    Set `fogAtmosphereHeight = groundZ + 1000` so height fog follows the terrain like the clouds
    (z = 0 is sea level; at Whitney a 1000 m fog layer is under the ground **[I]**).
  - Rain/snow:
    - `frac = clamp(precipMmH / 8, 0, 1)`.
    - Datablock `Snow_menu` if `snowCmH > 0` and `tempC < 1`, else `rain_medium`.
    - Pool `numDrops = 4000`; set `setPercentage(frac)` if present, else `numDrops = floor(frac·4000)`;
      `setHidden(frac < 0.01)`.
    - Rain loop: a 2D SFXEmitter `track = "amb_rain_medium"`, volume = `frac`, deleted when dry
      **[I]**: the field name and profile-as-track need checking.
  - Overcast look: `o = clamp((total−50)/50, 0, 1)` lerps ScatterSky `colorize`, `sunScale`,
    `ambientScale`, `fogScale`, `shadowSoftness` from the level values (`make_level_assets.py:54-62`)
    to the stock `rainy`/`cloudy` preset values (`art/weather/defaults.json`).
    Write them through `obj:setField` + `postApply` (as `weather.lua:258-263` does for LevelInfo).
  - Temperature (D): `lvl:setField('temperatureCurveC', 0, table.concat(curve, ' '))`, then
    `lvl:setEditorDirty(true)` (pattern `editor/api/object.lua:297-304`) so
    `environment.lua:1657-1658` re-reads it next frame; clear the flag the frame after.
    - Fallback, if the field will not take a string: leave the curve empty and call
      `be:setSeaLevelTemperatureK(T+273.15)` directly (the early return at `environment.lua:1666`
      keeps it). The UI then shows −273 °C, so the curve route is preferred.
  - Gravity (E): `g = 9.7803253359·(1+0.00193185265241·s²)/sqrt(1−0.00669437999013·s²) − 3.086e-6·h`
    with `s = sin(lat)`, `h` = player height.
    Call `core_environment.setGravity(−g)` when it differs by more than 1e-4 from the last value
    (`core.lua updateSky` already runs on `SKY_INTERVAL` with the player's lat/lon).
  - Haze (G, optional): `p = deepcopy(earth.json)`; scale `atmosphere.mieScattering` and
    `mieExtinction` by `clamp(aod/0.1, 0.5, 5)`; `core_celestial.loadProfile(p)` only when the
    factor changes by more than 10 %.
- Coexistence:
  - If BWM_Weather is loaded (`extensions.isExtensionLoaded('BWM_Weather_main')` **[I]** name from
    its `lua/ge/extensions/BWM/Weather/main.lua`), real weather defaults to off and the status line
    says so; the two would fight over `setCloudCover`/`setGroundWind`.
  - `sky.setMode('manual')` already hands time to the stock UI; add `setWeatherMode('real'|'manual')`
    the same way.
- Tests (`mod/tests/test_sky.lua`, pure):
  - coverage monotone and within 0..3;
  - wind from 270° (west wind) gives +x (blows east);
  - fog density clamp;
  - rain fraction and datablock choice;
  - Somigliana values 9.7803 at 0°, 9.8322 at 90°;
  - the utcOffset preference order;
  - the temperature curve string format.
- In-game checks (car parked, inputs zero, camera on the user's car):
  ```lua
  -- wind reaches the vehicle physics: airflow ~10 m/s while parked
  core_environment.setGroundWind(vec3(0,10,0)); be:getPlayerVehicle(0):queueLuaCommand("print('air', obj:getAirflowSpeed(), obj:getGroundSpeed())")
  core_environment.setGroundWind(vec3(0,0,0))
  -- temperature and altitude physics (run at Baltimore, then at Whitney summit)
  be:getPlayerVehicle(0):queueLuaCommand("print('env', obj:getEnvTemperature()-273.15, obj:getEnvPressure(), obj:getRelativeAirDensity())")
  -- expect pressure ~101 kPa / density ~1.0 at sea level, ~62 kPa / ~0.65 at 4.4 km if the engine uses z
  -- precipitation
  local r = scenetree.findObject('bngEarthRain'); r:setPercentage(0.5); r:setHidden(false)   -- then 0 / true
  -- temperature curve route
  local l = scenetree.theLevelInfo; l:setField('temperatureCurveC', 0, '0 30 1 30'); l:setEditorDirty(true)
  -- next frame: print(core_environment.getTemperatureK() - 273.15) -> 30
  ```

### 5.3 Ambient sound by biome: C

- **Server**:
  - ship a coarse Köppen-Geiger grid (Beck et al., https://www.gloh2o.org/koppen/; 0.1° resampled
    = 3600×1800 bytes ≈ 6.5 MB; the page says CC BY 4.0 but links the NC licence, so check before
    redistributing, or download on first use);
  - put `"climate":"BWh"` and `"biome":"desert"` in the `weather` message (or in `anchor_ready` if
    weather is off).
  - Mapping:
    - A* → `tropical`;
    - B* → `desert`;
    - Cs* → `mediterranean`;
    - other C*, D* → `forest`;
    - E* → `desert` (bare, windy) or `forest` below the treeline;
    - ESA WorldCover "built-up" can later switch to a city ambience (WCUSA's `Amb_WC_City` space).
- **Mod** (`sky.lua` or a new `ambience.lua`):

  | biome | room tone (`event:>Ambient>Roomtones>`) | reverb snapshot |
  |---|---|---|
  | desert | `Roomtone_Desert_01` | `Reverb_UT` |
  | forest | `Roomtone_ConiferousDeciduous_01` | `Reverb_EC` |
  | mediterranean | `Roomtone_Mediterranean_01` | `Reverb_WC_Open` |
  | tropical | `Roomtone_Tropical` | `Reverb_JR` |

  - Switching: `core_audioForest.setRoomtoneEvent(ev)` then `core_audioForest.setRoomtoneEnabled(true)`.
  - The reverb: `scenetree.findObject('bngEarthReverb'):setField('track',0,'snapshot:>Reverb_UT'); obj:play()`.
  - Switch only when the biome changes, with a 30 s hold so borders do not flap.
  - Optional wind layer: our own SFXEmitter on `event:>Ambient>Wind>Wind_Desert_01`, re-placed at
    the listener each second, volume ∝ wind speed from #A.
- Risks:
  - `createSfxEmitter` starts at `setVolumePitchCT(0.0, …)` (`audioForest.lua:201`) and the room
    tone sits at world (0,0,z). If it is silent, or fades with distance from the origin (a 3D
    event), use our own emitter re-placed at the listener (`SFXSystem.getPositionXYZ()`, as
    `audioForest.lua:329` reads it). This is rebase-safe because it is re-placed every second.
  - Unload: `core_audioForest.clear()` on mission end is already done by the engine (`:584-586`).
- Tests: pure `biomeFor(koppen)` and the event table; the server's grid lookup (known points:
  Phoenix BWh, Rome Csa, Singapore Af, Baltimore Cfa).
- In-game check:
  ```lua
  core_audioForest.setRoomtoneEvent('event:>Ambient>Roomtones>Roomtone_Desert_01'); core_audioForest.setRoomtoneEnabled(true)
  -- listen; then teleport > 5 km away and listen again (3D falloff test); disable with setRoomtoneEnabled(false)
  ```

### 5.4 Physical atmosphere: D + E

These are covered inside 5.2. They are listed separately because they work **without** the weather
service:

- the ISA 15 °C curve from 5.1;
- latitude gravity from the mod alone.

Ship them first if 5.2 slips.

### 5.5 Famous places in the level selector: F

- `tools/make_level_assets.py`:
  - info.json gets `"spawnPoints":[{"translationId":"Fells Point, Baltimore","objectname":"spawn_fells_point","preview":"spawn_fells_point.jpg"}, …]`
    (6-10 places: Fells Point, Whitney summit, Nürburgring, Monaco, Death Valley, Tokyo Shibuya,
    Hana Highway, Stelvio Pass, Salt Lake Bonneville, Cannonball start NYC).
  - Each place gets a `SpawnSphere` under `PlayerDropPoints` at `[0,0,0.5]` (like `spawn_default`)
    with dynamic field `"bngEarthLatLon":"39.2823 -76.5929"`.
  - `translationId` falls back to the literal string when there is no translation key **[I]**.
- `core.lua onLevelStart` (`core.lua:732-757`): before `M.teleport(ui.getLatLon(...))`, read
  `local sp = setSpawnpoint.loadDefaultSpawnpoint()`. If it is not `spawn_default` and the object
  has `bngEarthLatLon`, teleport there instead.
- Previews:
  - a 16:9 JPG per place, made with the existing screenshot tooling once each place renders well;
  - placeholder: the level preview.
- Big map side-effect: core_levels now lists these as fast-travel POIs at (0,0)
  (`core/levels.lua:524-552`).
  - In our extension's `onGetRawPoiListForLevel(level, elements)`, replace
    `bigmapMarker.quickTravelPosRotFunction` of `data.type == 'spawnPoint'` elements with one that
    calls `M.teleport(lat, lon)` and returns nil (so `bigMapMode.lua:1441-1444` does not move the
    car).
  - Hook order is not guaranteed. If ours runs first, wrap `core_levels.onGetRawPoiListForLevel` at
    extension load and restore it on unload.
  - This also gives the stock bigmap a non-empty POI list.
- Tests: `test_core_stubbed.lua` case where a stubbed `setSpawnpoint.loadDefaultSpawnpoint` returns
  `spawn_fells_point` and a stub object carries the field. Assert that the teleport goes to its
  lat/lon and that `spawn_default` keeps the old behaviour.
- In-game check:
  ```lua
  print(setSpawnpoint.loadDefaultSpawnpoint(), scenetree.findObject('spawn_fells_point'):getDynDataFieldbyName('bngEarthLatLon', 0))
  ```

## 6. Implementation plan

| order | files | change | protocol | tests | in-game |
|---|---|---|---|---|---|
| 1 | `tools/make_level_assets.py` → regenerated `levels/beamng_earth/main/MissionGroup/Sky/items.level.json` | CloudLayer, Precipitation, ForestWindEmitter, reverb SFXEmitter, `temperatureCurveC` | – | generated-file test | 5.1 snippet |
| 2 | `mod/.../sky.lua`, `core.lua` | gravity by latitude; ISA curve | – | `test_sky.lua` Somigliana | `print(core_environment.getGravity())` |
| 3 | `server/weather.py` (new), `server/earthd.py` (`on_pose` trigger, `attribution`), `server/README.md` | Open-Meteo fetch + cache | **`weather`** S→M; optional `weather_refresh` M→S | `server/tests/test_weather.py` (fixture, no network); `test_protocol_agreement.py` lists the new type | – |
| 4 | `sky.lua` (`onWeather`, mappings, lerp), `core.lua` (dispatch), `ui.lua` (status line "Weather: 3 °C, wind 9 m/s from SW, clear") | apply weather; real tz in `M.sync` | – | `test_sky.lua` mappings | 5.2 snippets; visual compare against a webcam |
| 5 | `server/weather.py` (+ Köppen grid), `sky.lua`/`ambience.lua` | biome sound | `weather.biome` | lookup + mapping tests | 5.3 snippet |
| 6 | `make_level_assets.py`, `core.lua`, preview JPGs | spawn places | – | `test_core_stubbed.lua` | 5.5 snippet; load the level from the selector |

Order rationale: 1 and 2 are independent and tiny. 3 and 4 make real weather. 5 reuses 3's
message. 6 is independent and can go in parallel.

## 7. Verified vs inferred

- **Verified** (code, data or live API): everything in the §2 table not marked [I];
  - the class counts in §1;
  - the time-zone errors of the current guess (live Open-Meteo `timezone=auto`);
  - the Open-Meteo field names and units, including `visibility` in `current`;
  - celestial forcing black night colours;
  - the room tone and reverb event names per level;
  - the `teleportToLastRoad` behaviour without a navgraph;
  - recovery points already remapped on rebase.
- **Inferred**, to check in-game with the snippets above:
  - the engine's altitude-dependent air density;
  - the runtime `temperatureCurveC` string format;
  - Precipitation `setPercentage`/`followCam` on our build (taken from BWM_Weather);
  - `numOfDrops` vs `numDrops`;
  - the room tone's 3D/2D nature and initial volume;
  - `track = 'amb_rain_medium'` on an SFXEmitter;
  - the fog density ↔ visibility relation and `fogAtmosphereHeight` being relative to z = 0;
  - the coverage/cirrus mapping constants;
  - bug a actually triggering (it depends on extension order; shipping the CloudLayer in the level
    file removes it either way);
  - whether a runtime `globalEnviromentMap` switch (H) takes effect.
