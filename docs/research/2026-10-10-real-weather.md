# Real weather at the player's location: research and plan

Date: 2026-10-10. Game: BeamNG.drive 0.39.4 (Linux/Vulkan). Topic: match the in-game sky and weather
(clouds, rain/snow, fog/haze, wind, temperature) to real life where the player is, using Open-Meteo
through earthd, because the game's Lua has no internet access.

`G` = the game install (`~/.local/share/Steam/steamapps/common/BeamNG.drive`). Line numbers are for 0.39.4.
**[V]** = verified in code, data or a live request. **[I]** = inferred, needs the in-game check named in §6.
No running game or MCP server was contacted. Scratch files: `scratchpad/research3/` (extracted level
objects, `om/*.json` = today's Open-Meteo responses, `strings.txt` = engine binary strings).

Side note: the user also asked to "set it to realtime". `sky.lua` already does that: mode `'real'` is the
default, it re-syncs TimeOfDay to real UTC every 30 s with `dayLength = 86400`. There is nothing to add.

---

## 1. Data: Open-Meteo forecast API

### 1.1 Request (measured 2026-10-10 ~20:15 UTC, generic UA, no key, no personal data)
```
GET https://api.open-meteo.com/v1/forecast?latitude=39.29,36.58&longitude=-76.53,-118.29
    &current=temperature_2m,dew_point_2m,relative_humidity_2m,is_day,precipitation,rain,showers,
             snowfall,weather_code,cloud_cover,cloud_cover_low,cloud_cover_mid,cloud_cover_high,
             surface_pressure,wind_speed_10m,wind_direction_10m,wind_gusts_10m,visibility
    &hourly=freezing_level_height,wind_speed_700hPa,wind_direction_700hPa&forecast_hours=1
    &wind_speed_unit=ms&timeformat=unixtime
```
- **[V]** HTTP 200 in 0.52-0.54 s. About 2.2 KB for one point and 6.3 KB for 5 points. Comma-separated
  coordinates return a JSON array, so one call can serve several points (useful for a look-ahead point).
- **[V]** `current` is 15-minutely: `"interval": 900`. `precipitation`, `rain`, `showers` and `snowfall` are
  sums over the previous 15 min (mm or cm), so **rate mm/h = value × 3600 / interval**. Docs: "Current
  conditions are based on 15-minutely weather model data" (https://open-meteo.com/en/docs).
- **[V]** Every variable in the list was present in `current`, including `visibility`, which was non-null
  in Baltimore, Whitney, Sydney, London and Manaus (35.4 / 60.8 / 24.7 / 21.7 / 39.0 km).
  Pressure-level variables (wind at 1000-30 hPa, temperature, RH, cloud cover, geopotential) and
  `freezing_level_height` are available hourly.
- Docs [V]: cloud_cover_low is "Low level clouds and fog up to 3 km", mid is 3-8 km and high is from
  8 km. Pressure-level heights are "above sea level". `elevation=` sets the downscaling height (default
  90 m DEM, `nan` = grid-cell mean). `cell_selection=land|sea|nearest`. WMO weather codes: 0-3 clear to
  overcast, **45 fog / 48 depositing rime fog**, 51-57 drizzle (56/57 freezing), 61-67 rain (66/67
  freezing), 71-77 snow, 80-82 rain showers, 85/86 snow showers, 95/96/99 thunderstorm (96/99 hail only
  from ICON/UKMO).
- Update cadence [V docs]: the models update every 1 h (GFS/HRRR, Météo-France, UKMO) to every 3-6 h
  (most others). New runs are stitched without gaps. **Polling every 10 min is enough**. A 15-min `current`
  slot is the finest step.
- Limits [V https://open-meteo.com/en/terms]: free and **non-commercial only**, with no key: < 600
  calls/min, 5,000/h, 10,000/day, 300,000/month. Our worst case is about 20 calls/h (one per 25 km at
  134 m/s plus the 10-min timer).
- Attribution [V https://open-meteo.com/en/licence]: CC BY 4.0. Show **"Weather data by Open-Meteo.com"**
  linked to https://open-meteo.com/ wherever the data is displayed. Add it to `Server.attribution()`
  (earthd.py:473), which the mod already shows.

### 1.2 Measured values (today, fixtures in `scratchpad/research3/om/`)
| | Baltimore 39.29,-76.53 (grid elev 33 m) | Whitney 36.58,-118.29 (grid elev 4042 m) |
|---|---|---|
| T / Td | 20.8 / 11.4 °C, so LCL ≈ 125 × 9.4 ≈ 1.2 km AGL | 3.5 / -13.8 °C, so LCL ≈ 2.2 km AGL |
| code, cover total/low/mid/high | 3 (overcast), 100 / 2 / 100 / 100 | 0, 2 / 0 / 2 / 0 |
| visibility | 35.4 km | 60.8 km |
| wind 10 m (gust) from | 2.4 (6.1) m/s from 96° | 9.5 (13.7) m/s from 233° |
| 700 hPa wind | 4.5 m/s from 216° | 6.0 m/s from 228° |
| freezing level | 4150 m | 4040 m (summit level) |
| surface pressure | 1023.9 hPa | 620.5 hPa |
Caveat [V]: pressure levels below the ground are extrapolated (Whitney's 850 hPa temperature reads 20 °C).
Use 700 hPa or higher for winds aloft over high ground.

### 1.3 Derived quantities
- **Cloud base** (Espy, standard rule) [I]: base_AGL ≈ 125 m × (T − Td). Use it when the low deck
  dominates. When the mid deck dominates (Baltimore today), use base_ASL = max(ground + LCL, 3000 m). When
  only high cloud is present, the volumetric layer stays thin and the high cover becomes cirrus.
- **Fog / haze** (Koschmieder) [I, standard]: extinction σ = 3.912 / V (V in metres, 2 % contrast). Codes
  45/48 with a model V above 1 km mean fog anyway, so clamp V ≤ 800 m. Today's 35 km gives σ = 1.1e-4.
  The official maps use fogDensity 1.7e-4 to 3.5e-4 (east_coast_usa 2e-4, west_coast_usa 3.5e-4, from the
  extracted `items.level.json`), which is the same order of magnitude. So the shader fog is metric
  extinction per metre (§2.3).

---

## 2. Game side (0.39.4): every weather system

### 2.1 core_environment (`G/lua/ge/extensions/core/environment.lua`, 1943 lines)
- **Object cache pitfall [V]**: `getObject(class)` (53-67) caches the *first* object of each class. A
  miss is cached as `0` and returns nil until the cache is cleared. That happens at
  `onClientPostStartMission` (1609), `onClientStartMission` (1688) and `onEditorDeactivated` (1699-1702).
  Our CloudLayer is created later by `sky.lua` (first `onUpdate`), and the level has no Precipitation
  object, so **every `core_environment` cloud and precipitation call misses our objects**: the stock
  Environment UI cloud slider, BWM_Weather's cloud changes and missions' `setCloudCover`. The fix is to
  call `core_environment.onEditorDeactivated()` once after creating our objects (it only clears the cache
  and refreshes night lights).
- Clouds (871-1140) [V]: `setCloudCover`, `setWindSpeed`, `setCloudWindDirection` (Point2F),
  `setCloudAltitudeKm`, `setCloudCirrusAltitudeKm`, `setCloudCirrusCoverage`, `setCloudCirrusDensity`,
  `get/setCloudWeatherOffsetKm`, `regenerateWeatherMap(seed)`, plus `...ByID` variants. Each one writes the
  field, calls `postApply()` and fires `extensions.hook('onEnvironmentChanged', …)`. `onClientStartMission`
  calls `regenerateWeatherMap()`, so the cloud pattern is random on every load (1694).
- Fog (1147-1190) [V]: `setFogDensity` (LevelInfo.fogDensity + postApply) and `setFogAtmosphereHeight`.
  The state/UI value is `fogDensity × 1000` (1262, 1296). `fogColor` exists on LevelInfo, with no setter.
- **Precipitation (1218-1231) [V, broken]**: `setPrecipitation` writes `numOfDrops`, but the engine field
  is `numDrops`. The binary's Precipitation field list has `numDrops` and no `numOfDrops`
  (`strings.txt` ~419150). The official levels even carry a junk dynamic `"numOfDrops":"0"`
  (east_coast_usa / small_island `rain_single_drops`). `core_weather` presets use the correct `numDrops`
  (`gameengine.zip art/weather/defaults.json`). **Do not use the env precipitation API.**
- **Ground wind [V]**: `setGroundWind(x,y,z)` (840-846) → `applyGroundWind` (46-51) =
  `be:queueAllObjectLua("obj:setWind(x,y,z)")` + `be:setGroundWind`, and it is re-applied on vehicle
  spawn/reset (1940-1941). The units are **m/s air velocity in world axes**. The flowgraph node "Set Wind"
  says "Wind speed, in metres per second" and calls the same `obj:setWind`
  (`flowgraph/nodes/environment/setWind.lua:16,44`). Missions set it from `windSpeed` / `windDirAngle`
  (`missionManager.lua:849-854`). The UI builds it as `x = s·sin(dir), y = s·cos(dir)`
  (`EnvWeather.vue:357-368`, `ui/modules/apps/Winds/app.js`). So the vector points to where the air goes:
  **meteorological "from θ" → (−s·sinθ, −s·cosθ, 0)**. Audio uses its length (`core/sounds.lua:61`
  `g_WindSpeedMS`). [I] The aero force is engine-side (`obj:setWind` is a C++ binding; no vehicle Lua
  reads it), so the push on cars and planes needs the check in §6. `interAero.lua:515 setWindAero` is the
  separate per-vehicle drafting wind.
- **Temperature [V]**: `onUpdate` (1651-1683) interpolates LevelInfo's `temperatureCurveC` (pairs of
  tod.time and °C) and calls `be:setSeaLevelTemperatureK` every frame, but **returns early when the curve
  has fewer than 2 points** (1667). Our level's LevelInfo has no `temperatureCurveC`
  (`mod/.../Sky/items.level.json`), so [I] nothing overrides a value we set with
  `be:setSeaLevelTemperatureK(K)`. Only the UI's "temperatureC" shows −273 (`getTemperatureK` returns the
  module local, 0). The engine also exposes `LevelInfo:setTemperatureCurveC` and `isEditorDirty` /
  `setEditorDirty` (`strings.txt` 408103-408463) as a cleaner route (§4).
- Vehicle consumers of ambient temperature [V]: engine thermals (oil, block, cylinder, exhaust against
  `tEnv`: `vehicle/powertrain/combustionEngineThermals.lua:525-577`), **cold-exhaust steam particles**
  (`:507`, `exhaustCondensationThresholdEnvTemp`), tyre thermals (`vehicle/wheels.lua:179,723,850`),
  brakes and clutch (`powertrain/centrifugalClutch.lua:22`), fire (`fire.lua:75,304`), pneumatic and
  pressure tanks (`energyStorage/pressureTank.lua:109`), and dash gauges (`etkGauges`, `vivaceGauges`,
  `sbrGauges`). Air pressure: `obj:getEnvPressure()` (`powertrain.lua:183`). [I] It follows altitude
  (standard atmosphere), so "SeaLevel" temperature means T_sl = T2m + 0.0065 × elevation. Check in §6.
- `setState(state, lerp)` (1340-1387) lerps only cloudCover, fogDensity, fogAtmosphereHeight and time,
  with the duration scaled by √(Δ/range) and cut to 0.3 s when a lerp is already running. It is too coarse
  for us, so we do our own lerp.
- Missions [V]: `missionManager.lua:822-855` saves and sets clouds, fog, time and wind on start and restores
  them on stop (944-968). The hooks are `onAnyMissionChanged("started"|"stopped", mission)` (874, 942,
  1002). Real weather must pause while a mission runs.

### 2.2 CloudLayer (0.39 volumetric) [V shaders `G/shaders/common/clouds/`, field docs in the binary]
- Lua-visible fields: `coverage` ("Fraction of sky covered by clouds 0-1"), `altitudeKm` ("Base altitude
  of the volumetric cloud layer in kilometers"), `windDirection` ("Direction the volumetric clouds drift
  (normalized 2D vector)"), `windSpeed` ("Overall scalar to texture scroll speed"; legacy 2D),
  `cirrusAltitudeKm`, `cirrusCoverage`, `cirrusDensity`, `exposure`, `baseColor` and `texture`. Class
  statics: `CloudLayer.volumetricEnabled / vrtDownsampleFactor / shadowLutUpdateGroupSize / stepCount /
  sunShadowStepCount`, `get/setWeatherOffsetKm`, `regenerateWeatherMap` (graphics quality presets set
  these: `core/settings/graphic.lua:1319-1340`). Layer height, density scale, weather scale and wind speed
  in km/s are debug-only (strings "Layer height (km)", "Density scale"…) with no Lua field. So we cannot
  build tall cumulonimbus. One volumetric deck plus cirrus is the vocabulary.
- **Coverage curve** (`include/cloudCommon.h.hlsl:217`): local = saturate(map.r − 0.5 + (−0.5 + 2.1 ·
  coverage^0.8)). The weather map r = saturate((n − 0.4) · 2.5), with n normalised to mean 0.484 and
  std 0.109 (`cloudWeather2D.cs.hlsl`, `cloudWeatherNorm.h.hlsl`). Clouds form where the base noise exceeds
  1 − local (`:236`). A Monte Carlo of that pipeline (base noise assumed uniform, so [I] for the exact
  look) gives the **sky fraction F for each `coverage` value**:

  | coverage | 0.17 | 0.29 | 0.40 | 0.53 | 0.67 | 0.79 | 0.92 | ≥1 |
  |---|---|---|---|---|---|---|---|---|
  | sky fraction | 2 % | 10 % | 25 % | 50 % | 75 % | 90 % | 99 % | 100 % (values >1, as maps' 1.23 or BWM's 2.9, only saturate) |

  So **coverage = interp(F)** over this table, not coverage = cloud_cover/100. Today's sky.lua default of
  0.5 gives about 45 %.
- Cirrus (`cloudCommon.h.hlsl:267-330`): it appears when both cirrusCoverage > 0 and cirrusDensity > 0.
  Coverage is saturated to 0..1, density is ×20, and the altitude is clamped above the deck top. It is
  driven by the weather map's b channel: cirrusCoverage = high/100, cirrusDensity ≈ 0.05-0.15
  (cirrusAltitudeKm ≈ 9).
- The clouds lie on a sphere (`planetRadiusKm`), and **cloud shadows and sun attenuation are automatic**
  (`cloudSunTransmittanceCookie.cs.hlsl`, used in `lighting/advanced/vectorLightP.hlsl`). Ambient light
  comes from the sky SH. Overcast darkens the scene with no ScatterSky edits. (The `core_weather` presets
  also dim `sunScale` and `colorize`, an optional extra.)
- Changing coverage or altitude does not regenerate the map. Never call `regenerateWeatherMap` for
  weather changes, because the pattern pops (BWM reached the same conclusion).
- Cost [I]: a ray-march per pixel at the user's quality (VRT downsample 4/6/8). More cover means more
  marching steps. Measure frame ms at coverage 0 / 0.5 / 0.9 (§6).

### 2.3 Fog: LevelInfo, height-based [V `G/shaders/common/sceneFog.h.hlsl`]
Transmittance = exp(−fogDensity · ∫exp(−z·k) ds): the density **decays with absolute world z**. [I from
Torque3D] k = fogData.z = 1/fogAtmosphereHeight. In our frame z = 0 is about sea level, so today's
level fog (density 4e-5, height 1000) is **e^-4.4 ≈ 1/80 as thick at Whitney (4.4 km) as at sea level**:
mountains get no haze at all. To get the target σ at the player's ground height z_g:
**fogDensity = σ · exp(z_g / H)**, re-tuned when z_g changes by more than ~50 m. Keep H ≥ 500 m (fog
codes 300-500 m, otherwise 1000-1500 m) or valleys far below the player turn opaque (density e^{Δz/H}
times higher). This altitude compensation is a quick win even without real weather.

### 2.4 Precipitation [V binary field list and docs, levels, BWM]
- Class `Precipitation` (Torque3D) has fields `numDrops` (pool), `boxWidth/boxHeight`, `dropSize`,
  `splashSize`, `splashMS`, `fadeDist/fadeDistEnd`, `followCam`, `useWind`, `minSpeed/maxSpeed`,
  `minMass/maxMass`, `useTurbulence/maxTurbulence/turbulenceSpeed`, `doCollision`, `hitVehicles` and
  `dataBlock`. Methods: `setPercentage(0..1)` ("maximum number of drops … as a percentage of numDrops")
  and `setTurbulence(max, speed, ms)`.
- Datablocks (`gameengine.zip art/datablocks/managedDatablocks.datablocks.json:793-868`): `rain_drop`,
  `rain_medium` (rain textures + splash) and **`Snow_menu`** (`Particle_snow.dds`). Also the sound
  profile `amb_rain_medium` (AudioLoop2D). Official maps place a `rain_medium` object with `numDrops 0`
  (italy, east_coast_usa, small_island) and west_coast_usa places `rain_drop` 50×50 with `hitVehicles`.
  The editor creates one with `dataBlock rain_drop` (`editor/createObjectTool.lua:844-849`).
- Runtime recipe (BWM verified it on 0.39.2: `environmentController.lua:10-38`): `createObject
  ('Precipitation')`, set fields, `registerObject`, `numDrops = max`, `setPercentage(p)`, and
  `setHidden(p ≈ 0)`. Cost [I]: Torque3D simulates each drop on the CPU every frame, so keep the pool
  ≤ ~4000 with a box of about 40 m around the camera.
- **No wet roads, puddles, wetness or lightning system [V]**: no `wetness` or `puddle` in Lua or the
  material shaders (`$wetnessParams` is the water shoreline only), and Lightning is commented out as
  "TODO: not exists?" (`createObjectTool.lua:981`). Physics wetness exists as ground models (`ASPHALT_WET`
  µ 0.92/0.55 against ASPHALT 0.98/0.70, `GRAVEL_WET`; `gameengine.zip art/groundmodels.json:10-35,233`).
  Using it means swapping the terrain material's ground model (`setGroundmodelName`) once v1.5 has real
  surface layers. Today our terrain is all `DIRT`.
- `ForestWindEmitter` (`strength`, gusts) sways trees. It is irrelevant until we have Forest items (v1.9).

### 2.5 core_weather (`G/lua/ge/extensions/core/weather.lua`) [V]
This is the legacy preset lerper (`art/weather/*.json` + `levels/<lvl>/weather/*.json`) over arbitrary
class fields. It is used by the old Angular environment UI and by `tech/techCore.lua:2543`. It is not
needed; its "rainy" preset (numDrops 200, coverage 1, fog 0.005, dimmed ScatterSky) is a useful reference.

---

## 3. The user's BWM_Weather mod (Beamworks Weather 1.0.0, `mods/repo/bwm_weather.zip`) [V]
- Entry `extensions.load("BWM_Weather_main")` (`scripts/BWM_Weather/modScript.cs`). Public API
  (`BWM_Weather/main.lua:34-56`): `setWeatherPreset(name)`, `setWeatherIntensity`,
  `setAutomaticWeather(bool)`, `setWindStrength`, `setFogDensity`, `setTimeOfDay`, `setRainQuality`,
  `stopWeather`, `resetWeather` and `getWeatherState`. Settings (`settingsManager.lua`,
  `/settings/BWM_Weather.json`): lastSelectedPreset "clear", rainQuality "medium", transitionDuration 15,
  automaticWeather false, automaticTime false.
- Presets (`presetManager.lua`): clear / cloudy / lightRain / mediumRain / heavyRain / thunderstorm / fog,
  each a fixed bundle of cloud coverage (up to 2.9), cirrus, **fixed cloudAltitudeKm (0.8-2.8)**, fog,
  wind and rain. Its writes go through `core_environment` (`environmentController.lua:56-64`), with
  **`setGroundWind(vec3(windStrength*12, 0, 0))`**, an always-eastward wind. Rain uses its own
  camera-following `Precipitation` "BWM_Weather_Precipitation" (1800/4500/9000 drops). Thunderstorm
  lightning is a PointLight flash plus debugDrawer bolts plus thunder wavs delayed by distance/343
  (`lightningController.lua`, `main.lua:66-73`).
- Behaviour: on every level start it transitions to the saved preset (default "clear") over about 12-15 s,
  then stops writing until the user acts or automatic weather fires (`weatherController.lua:44-58`).
  On our level its cloud writes miss our CloudLayer (cache, §2.1), but its **fog writes (fogDensity → 0,
  height → 180) and ground wind do land**.
- Recommendation: **coexist, do not drive it, and own the objects when "Real weather" is on.** It has no
  per-variable API (only presets), fixed altitudes fight our ground-following base, the east-only wind is
  wrong, and the lightning is debug-draw lines. Concretely: (a) ignore `onEnvironmentChanged` events for
  15 s after level start (BWM's start transition plus env's own `setState(init_env)`); (b) if
  `BWM_Weather_main` is loaded and its state has `automaticWeather` or a non-"clear" target while real
  weather is on, show a one-line notice ("BWM_Weather is also changing the weather: set it to Clear /
  automatic off, or turn Real weather off"); (c) treat later `onEnvironmentChanged` events as a **manual
  override** (§4). Reimplement thunder ourselves later (PointLight flash + `Engine.Audio.playOnce`,
  as BWM does), without copying its files, because its licence is not stated.

---

## 4. Plan (small; about 300 lines server + mod)

### 4.1 Server: `server/weather.py` (new) + earthd hook
- `fetch(lat, lon) -> dict`: the GET from §1.1 (+ `&cell_selection=land`) via urllib with
  `dem.USER_AGENT`, a 10 s timeout, run in an executor (as `earthd.py:434`). On error, keep the last
  state and retry in 2 min.
- `derive(om) -> state` (pure, unit-tested). The compact state is v1:
  `{type:'weather', v:1, t, lat, lon, code, cover:{tot,low,mid,high}, baseM (ASL), cirrus, precip
  {kind:'none'|'rain'|'snow', mmh}, visM, fog, wind:{ms, fromDeg, gustMs}, aloft:{ms, fromDeg}, tempC,
  elevM, slTempC, thunder, credit:'Weather data by Open-Meteo.com'}`. Rules: deck = max(low, mid) (the
  volumetric layer), cirrus = high; baseM is the §1.3 rule; mmh = precipitation·3600/interval; kind =
  snow if snowfall > 0 and rain + showers == 0, or code ∈ {71-77, 85, 86}; visM = min(vis, 800) if code
  ∈ {45, 48}; thunder = code ≥ 95; slTempC = T2m + 0.0065·elev.
- `Client`: a timer in `on_pose` (earthd.py:926). Convert the player to lat/lon with the active anchor
  frame's `enu_to_geodetic`, and fetch when ≥ 600 s have passed or the player moved > 25 km since the last
  fetch. Send `weather` to the mod, re-send on `hello`, and send it immediately after connecting. Cache
  by (round(lat, 1), round(lon, 1), 15-min slot), shared across clients.
- `--weather on|off` (default on). Add the credit to `Server.attribution()`.
- Protocol: additive. Both sides ignore unknown types (`earthd.py:776-777`, `core.lua:406-496` has no
  else branch), so **no PROTOCOL bump**. Optional mod→server `weather_cfg {enabled}` turns fetching off.

### 4.2 Mod: `beamngEarth/weather.lua` (new, pure mapping + lerp), applied by `sky.lua` (the single owner
of CloudLayer, LevelInfo fog and the Precipitation objects)
- `core.lua` `onMessage`: `elseif t == 'weather' then beamngEarth_sky.onWeather(msg)`.
- Pure functions (luajit-testable): `coverageFor(F)` (§2.2 table, linear interpolation),
  `fogDensityFor(sigma, groundZ, H)`, `windVec(ms, fromDeg)` → (−ms·sinθ, −ms·cosθ),
  `cloudDir(fromDeg)`, `rainPct(mmh)` = clamp(√(mmh/8), 0.08, 1) when mmh > 0.05, otherwise 0, and
  `targets(state, groundZ)` → {coverage, altitudeKm = max(baseM/1000, groundZ/1000 + 0.3), cirrusCov,
  cirrusDen, fogDensity, fogH, groundWind, cloudWindDir, rainPct, snowPct, slTempK}.
- `step(cur, tgt, dt, T = 60)`: exponential approach (rate 3/T) per field. Write to the objects at
  **2 Hz** and only when a field changed by more than its epsilon. Use direct field writes +
  `postApply()` (not `core_environment.set*`, so no `onEnvironmentChanged` storm and no hook loop).
  groundWind uses `core_environment.setGroundWind` (it must reach every vehicle), at most 1 Hz, plus a
  gust term: an Ornstein-Uhlenbeck process between ms and gustMs with τ ≈ 4 s.
- Objects: create two `Precipitation` objects (`rain_medium` and `Snow_menu`, `followCam 1`,
  `numDrops 3000`, box 40×30, `canSave = false`), drive them with `setPercentage` and hide them at 0.
  Snow gets `minSpeed/maxSpeed` 0.15/0.3. After creating the CloudLayer or Precipitation, call
  `core_environment.onEditorDeactivated()` (cache reset, §2.1). No rain when the camera is above
  `altitudeKm`.
- Temperature: `be:setSeaLevelTemperatureK(slTempC + 273.15)` once per weather message. If §6 check 5
  shows env overriding it, use `theLevelInfo:setTemperatureCurveC` with a flat curve plus one frame of
  `setEditorDirty(true)` instead.
- Modes: `M.setWeatherMode('real'|'manual')` (default 'real') and `M.weatherStatus()`. Manual override:
  `onEnvironmentChanged(changes)` (after a 15 s grace period from mission start) puts the touched fields
  into `override[field] = true`. Real weather keeps driving the rest, and `setWeatherMode('real')` clears
  the overrides. `onAnyMissionChanged('started')` pauses and `'stopped'` resumes after 5 s (the mission
  restore runs first). The settings page later sets the mode and the per-field override.

### 4.3 Tests
- `server/tests/test_weather.py`: derive() on the two recorded fixtures (Baltimore → deck 1.0, base ≥
  3000 m, cirrus 1, no precip, vis 35400; Whitney → deck ≈ 0.02, wind from 233°), synthetic codes 45, 63,
  73 and 95, the precip rate from interval, cache hits, the 25 km / 600 s refetch rule, and the hello
  re-send. Fake the HTTP layer in the same way as `fake_imagery_earthd.py`.
- `test_protocol_agreement.py`: add 'weather' to both sides' known types. luajit: `coverageFor`
  monotone with table points ±0.01, `windVec(10, 270)` = (10, 0) (a west wind blows east), `fogDensityFor`
  round trip, and `step` convergence (95 % in 60 s).

### 4.4 Quick wins that use existing game features (smallest first)
1. Cache reset after creating our CloudLayer: makes the stock Environment UI cloud slider and missions
   work on our level (1 line).
2. Altitude-compensated haze, `fogDensity = σ·e^{z_g/H}`: mountains get haze back (sky.lua's 5 s
   ground check already exists).
3. Real ground wind (`setGroundWind`): wind noise in audio, a push on cars and planes [I], and rain slant
   if `useWind`.
4. Real temperature: cold-start engine and tyre behaviour, exhaust steam on cold mornings (thermals line
   507) and dash temperature, all from one call.
5. Cloud cover from data with the calibrated table. Cloud shadows and dimming come for free.
6. Rain/snow particles. 7. Later: wet ground models with v1.5 surfaces, our own lightning/thunder,
   rain audio (`amb_rain_medium`), and tree sway when forests exist.

---

## 5. Verified vs inferred summary
Verified: the API, variables, limits, licence and measured responses; env cache behaviour; the broken
`setPrecipitation`; ground wind units and convention; the temperature curve early return; vehicle
temperature consumers; CloudLayer fields and coverage maths; cloud shadows; fog height decay; the
precipitation API and datablocks; no wetness or lightning system; BWM's behaviour and API.
Inferred: the sky-fraction calibration (base-noise distribution), fog k = 1/H, ground-wind force on
vehicles, the getEnvTemperature lapse rate, precipitation and cloud cost, `useWind` behaviour, and
LevelInfo's empty default temperature curve.

## 6. In-game checks (user not driving; GE Lua console)
```lua
-- 1 cache: should print nil before and a number after the reset
print(core_environment.getCloudCover()); core_environment.onEditorDeactivated(); print(core_environment.getCloudCover())
-- 2 coverage calibration: screenshot straight up at each value, count cloud pixels
local o = scenetree.findObject('bngEarthClouds'); for _, c in ipairs({0.29,0.40,0.53,0.67,0.79}) do o.coverage = c; o:postApply() end
-- 3 fog k = 1/H: at z_g ~ 4000, set density so sigma = 1e-3 (V ~ 3.9 km) and look at a ridge ~4 km away
local li = scenetree.theLevelInfo; li.fogAtmosphereHeight = 1000; li.fogDensity = 1e-3 * math.exp(4000/1000); li:postApply()
-- 4 ground wind push: car parked in neutral, brakes off, on flat ground
core_environment.setGroundWind(-20, 0, 0) -- 20 m/s toward -x; watch getVelocity() after 5 s
-- 5 temperature: is there a default curve? does the value stick, and does it drop with altitude?
dump(scenetree.theLevelInfo:getTemperatureCurveC()); be:setSeaLevelTemperatureK(273.15 - 5)
getPlayerVehicle(0):queueLuaCommand('print(obj:getEnvTemperature() - 273.15, obj:getEnvPressure())')
-- 6 precipitation: create, 50 %, frame-time cost with perfmon at 3000 vs 9000 drops
local p = createObject('Precipitation'); p:setField('dataBlock',0,'rain_medium'); p:setField('followCam',0,'1')
p:setField('boxWidth',0,'40'); p:setField('boxHeight',0,'30'); p.canSave = false; p:registerObject('bngEarthRain')
scenetree.MissionGroup:addObject(p); p.numDrops = 3000; p:postApply(); p:setPercentage(0.5)
-- 7 cloud cost: perfmon frame ms at coverage 0 / 0.5 / 0.9 (camera fixed, car parked)
```
Gate: the coverage table within ±10 % sky fraction, rain at 3000 drops ≤ 0.5 ms, cloud cover 0.9
costing ≤ 1.5 ms more than 0, and no fight with BWM set to "clear".
