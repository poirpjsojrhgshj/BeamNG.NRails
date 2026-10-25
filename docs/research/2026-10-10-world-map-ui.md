# World-map GUI for BeamNG.Earth: research and plan

Date: 2026-10-10. Game: BeamNG.drive 0.39.4, native Linux.
Scope: a full-screen world map where the player can pan and zoom the whole Earth, see the car, search a
place, set a GPS destination and teleport. A small HUD map version is a later option.
Method: static reading of the game install (`$BNG` = `~/.local/share/Steam/steamapps/common/BeamNG.drive`),
`strings` of `$BNG/BinLinux/BeamNG.drive.x64`, the user's own `beamng*.log`, and the web. The running game was
**not** contacted. Everything marked **[probe]** still has to be checked in-game (snippets in section 8).

Legend: **V** = verified in files, logs or binary strings. **I** = inference. **W** = from the web (URL given).

---

## 0. TL;DR

1. **The UI stack is Vue 3.5 (main), with AngularJS 1.5.8 still hosted for older apps.** Mods add Vue UI by
   dropping SFC files into `/ui/ui-vue/mods/<mod>/`. These are compiled at runtime and are not isolated, so they
   get full `window` and `document`. A mod can register a full-screen route, a pause-menu tab or button, or a HUD
   UI app (`ui/modules/apps/<Name>/app.vue` with `"vue": true`). Two mods in the user's own repo already work
   this way. **V**
2. **UI ↔ Lua.** JS → GE Lua goes through `beamng.sendEngineLua(code)`, wrapped by `bngApi.engineLua` /
   `useBridge().api.engineLua(cmd, cb)`. Lua → JS goes through `guihooks.trigger(name, ...)` (JSON), which Vue
   receives with `useEvents().on(name, fn)`. Lua can also run raw JS with `be:executeJS(js)`. **V**
3. **CEF is Chromium 148.** Pages are served from `local://local/...`, i.e. from the game VFS, so mod-zip files
   are visible. The binary carries this CSP:
   `worker-src 'none'; connect-src 'self' http(s)://localhost:* ws(s)://localhost:* http(s)://127.0.0.1:* ws(s)://127.0.0.1:*`.
   **`fetch`/XHR/WebSocket to our companion on 127.0.0.1 is explicitly allowed by the CSP. Web Workers are
   forbidden.** **V** (binary string)
   There is also a native resource allowlist in `OnBeforeResourceLoad`. It cancels non-allowlisted hosts: the user
   log shows `Resource cancel URL=https://i.imgur.com/7023Ra0.png`. **V**
   Whether 127.0.0.1 passes that allowlist for `<img>` and `fetch` is **not provable from strings** **[probe P2]**.
   Since the CSP explicitly whitelists it, it very likely does **I**.
4. **WebGL is doubtful.** CEF is started with `disable-gpu`, `disable-gpu-compositing` and
   `disable-software-rasterizer` (binary strings next to `OnBeforeChildProcessLaunch`) **V/I**. Together these
   normally mean no WebGL at all. And even with WebGL, **MapLibre GL JS cannot run in the main UI, because it
   needs Web Workers (CSP `worker-src 'none'`)**. MapLibre v6 also requires WebGL2 (W).
   ⇒ **Use Leaflet 1.9.4 (DOM/CSS + canvas 2D, no workers, no WebGL) with raster tiles proxied and cached by
   `earthd`.**
5. **Tiles.**
   - Satellite: reuse the ground chain that `earthd` already fetches and caches (USGS ImageryOnly z≤16 for the US,
     EOX Sentinel-2 cloudless z≤14 worldwide).
   - Street/terrain: EOX `terrain-light` plus the `overlay_bright` labels (free, link-back attribution, "as is";
     tested 200 OK).
   - OSM standard tiles only as an opt-in, strictly within the OSM policy (no prefetch, identifying User-Agent,
     7-day cache).
   - CARTO, Stadia and Esri need a user-supplied key, so they are BYO-key only.
   - Bundle z0–4 of EOX s2cloudless 2016 (CC BY 4.0, ~341 tiles, ~5 MB) so the map opens instantly and works
     offline.
6. **The stock big map is a 3D camera over the loaded level** (`freeroam/bigMapMode.lua`) and **the stock minimap
   is an imgui overlay drawing the navgraph** (`ui/apps/minimap/*.lua`). Neither can show anything beyond the
   streamed bubble (~80 km far field, 2 km physics block). The stock GPS (`core_groundMarkers.setPath`) only routes
   over the local navgraph. ⇒ We build our own map. Long-distance routing has to come from the server; the local
   ground-marker GPS gets fed waypoints near the car.
7. **Fallback if CEF cannot load localhost resources:** the server writes PNG tiles to `/temp/beamngEarth/map/`
   and the page loads them through `local://local/temp/...` **[probe P3]**. Or an imgui map draws
   `im.ImTextureHandler(path)` tiles (`lua/common/extensions/ui/imgui_custom_luaintf.lua:199`). Our current UI is
   already imgui (`beamngEarth/ui.lua`).

---

## 1. BeamNG 0.39 UI stack (verified in the install)

| Fact | Evidence |
|---|---|
| Main UI entry is `local://local/ui/entrypoints/main/index.html`. It boots Vue first, then hosts AngularJS ("angularHost" phase) | `$BNG/ui/entrypoints/main/boot.js:38-46` (phases list), `index.html:1-140`; binary string `local://local/ui/entrypoints/main/index.html` |
| Vue 3.5.35, vue-router 5.1, pinia 3, SFCs compiled at runtime ("runtime mode" on by default) | `$BNG/ui/ui-vue/package.json` deps; `boot.js:99` `defaultRuntimeMode = true` |
| AngularJS 1.5.8 still shipped (legacy apps such as `app.js`/`app.html`) | `$BNG/ui/lib/ext/angular/angular.js` header; `ui/ui-vue/src/modules/legacyAngularHost/` |
| Vue sources ship unminified in `ui/ui-vue/src` (useful as reference) | directory listing |
| **Vue mods**: files under `/ui/ui-vue/mods/<modname>/` are discovered by GE Lua and compiled by the runtime. Optional `index.js` exports `onLoad`/`onUnload`. Components can import `"vue"`, `"@/..."` (built-in UI) and local `.vue/.js/.mjs/.json`/style/asset files | `$BNG/ui/ui-vue/mods/README.md`; `$BNG/lua/ge/extensions/ui/uiMods.lua:39-60` (`FS:findFiles('/ui/ui-vue/mods', ...)`) |
| Mod scripts are **not sandboxed**: `isolateScript = false` | `$BNG/ui/ui-vue/src/services/modManager/compilers/script.js:18` |
| Mount points for mods: `uiSlots` (`mainmenu.top`, `mainmenu.button`, `vehconfig.*`), pause menu tabs/buttons, standalone routes | `ui/ui-vue/src/services/modManager/slots.js:2-15`; README "Pause menu", "Standalone routes" |
| Pause-menu API: `extensions.ui_pause_actions.registerModTab/registerModButton(...)` | `$BNG/lua/ge/extensions/ui/pause/actions.lua:84,115`; signatures in `ui/ui-vue/src/bridge/LuaFunctionSignatures.js:1085-1091` |
| Route API: `extensions.ui_router_routeManager.registerModRoutes(sourceId, routes)`, plus `window.bngRoutes.add(...)` on the Vue side | `$BNG/lua/ge/extensions/ui/router/routeManager.lua:631-650`; README |
| Real mod examples in the user's repo: `realisticdrivercamera.zip` and `enhancedvehiclefx.zip` (`ui/ui-vue/mods/<x>/index.js` + `Settings.vue`, registering pause buttons); Angular apps in `bwm_weather.zip` and `sparkmod.zip` (`ui/modules/apps/<X>/app.{js,html,css}`) | `~/.local/share/BeamNG/BeamNG.drive/current/mods/repo/*.zip` (extracted copies in the scratchpad `research2/modexamples/`) |
| **HUD UI apps**: `/ui/modules/apps/<Folder>/app.json` (+ `app.vue` for Vue apps, `"vue": true`) | `$BNG/lua/ge/extensions/ui/apps.lua:7,63,120-196`; `$BNG/ui/modules/apps/Navigation/app.json` |
| Input actions: any `lua/ge/extensions/core/input/actions/*.json` in the VFS is merged, so a mod can add its own action | `$BNG/lua/ge/extensions/core/input/actions.lua:51-55`; stock example `actions/gameplay.json:62` (`toggleBigMap` → `freeroam_bigMapMode.toggleBigMap()`) |
| UI scale is set through root `font-size` and `--ui-scale`, not CSS `zoom`/`transform`, so Leaflet mouse maths stays correct | `$BNG/ui/ui-vue/src/App.vue:128-145` |
| On Windows the binary also ships `Ultralight.dll` (`index.html:96` has "polyfills for Ultralight"). Linux ships only `libcef.so`, so on Linux all HTML is CEF | `$BNG/Bin64/`, `$BNG/BinLinux/` listings |

### 1.1 How the stock big map and minimap work (and why they do not scale)

- **Big map** = camera mode `core/cameraModes/bigMap.lua` flying above the *loaded level*.
  - `freeroam/bigMapMode.lua:149-200` derives the level bounds by `castRayStatic` at the edges.
  - The Vue part (`ui/ui-vue/src/modules/bigmap/components/BigMap.vue`, `composables/useBigMap.js:57-367`) only
    draws POI lists and filters over the 3D view. It talks to `lua.freeroam_vueBigMap.*` and listens to
    `BigmapCameraMove`, `bigmapTransitionFinished` and similar hooks.
  - Navigation: `setNavFocus(pos)` → `core_groundMarkers.setPath(pos, {clearPathOnReachingTarget=true})`
    (`bigMapMode.lua:391-397`).
  - For Earth it would show only our streamed bubble. **Not usable as a world map.**
- **Minimap**: the Vue app `ui/modules/apps/Navigation/app.vue` only reserves a screen rectangle and sends it to
  Lua.
  - GE Lua draws an imgui window there and renders roads, route and vehicles into a
    `TextureDrawPrimitiveRegistry:getOrCreate("sdfMinimap", w, h)` texture (`ui/apps/minimap/minimap.lua:223-300,
    440-500`).
  - Roads come from `map.getMap().nodes` (`minimap/roads.lua:17-28`). The route comes from
    `core_groundMarkers.routePlanner.path` (`minimap/route.lua:37-52`).
  - Again it is limited to the injected navgraph.
- **GPS**: `core_groundMarkers.setPath(wp, options)` (`core/groundMarkers.lua:246-305`) builds
  `routePlanner:setupPathMulti({vehiclePos, wp...})` on the **navgraph** and sends
  `NavigationGroundMarkersUpdate {markers=[x,y,...]}` to the UI (`:231-244`).
  - A route only exists where navgraph nodes exist, which for us is the injected local road graph.
  - Waypoints may be node names, vec3 or `{x,y,z}`. So we can feed ENU waypoints near the car that come from a
    server-side long route.

### 1.2 Our mod's current UI
`mod/beamng_earth/lua/ge/extensions/beamngEarth/ui.lua` is a single imgui window. It shows status,
lat/lon `InputDouble` fields and a **Teleport** button (→ `actions.teleport(lat, lon)` →
`beamngEarth_core.teleport`, `core.lua:710-722`), plus the rebase slider and attribution. There are no
CEF/Vue files yet (`mod/beamng_earth/ui/` does not exist). The global extension name is `beamngEarth_core`
(`scripts/beamng_earth/modScript.lua`).

---

## 2. UI ↔ GE Lua plumbing (verified)

| Direction | Mechanism | Evidence |
|---|---|---|
| JS → Lua (fire and forget) | `beamng.sendEngineLua(luaCode)`, wrapped as `bngApi.engineLua(cmd)` (Angular global) and `useBridge().api.engineLua(cmd)` | `ui/ui-vue/src/bridge/libs/BeamNGAPI.js:56-72` |
| JS → Lua with return value | `api.engineLua(cmd, cb)` wraps the call as `guihooks.trigger("onBNGAPICallback", id, <cmd>)` and resolves `cb` when the hook returns. `runRaw(luaCode)` gives a Promise (`bridge/libs/Lua.js:139-151`). The typed `lua.*` proxy only knows functions in `LuaFunctionSignatures.js`, so for our own extension use `runRaw("beamngEarth_core.x(...)")` | same files |
| Lua → JS events | `guihooks.trigger(name, ...)`: JSON-encodes the arguments and calls `be:queueHookJS` (`lua/common/guihooks.lua:26-38`). Vue: `const events = useEvents(); events.on(name, fn)` (`ui/ui-vue/src/services/events.js:5-20`) | |
| Lua → JS raw JSON | `guihooks.triggerRawJS(name, jsonString)` (`guihooks.lua:54-56`) avoids a re-encode for big payloads | |
| Streams | `guihooks.queueStream`/`triggerStream` + `StreamManager.add([...])` (`bridge/libs/StreamManager.js`) are meant for per-frame vehicle streams. For a map at 2–5 Hz a plain hook is simpler | |
| Lua runs JS | `be:executeJS(js)` (`lua/ge/extensions/tech/techCore.lua:828`, `mcp/tools/ui.lua:29`), `be:queueJS(cmd)` (`ui/console.lua:1054`) | |

Payload size: hooks are JSON strings through the engine queue. Keep map updates small, e.g. a pose of ~100 B at
5 Hz. Send a route polyline once, encoded (polyline6, ~3–6 B per point).

---

## 3. Can the CEF UI load things from 127.0.0.1?

**Verified (binary strings of `BinLinux/BeamNG.drive.x64`, CEF `148.0.10+g7ee53f5+chromium-148.0.7778.218`):**

- `local://` is a custom scheme served by `LocalSchemeHandlerFactoryV2` from the VFS. Strings: `local:// now
  served by V2`, `request_fail | reason=NOT_FOUND url={}`, `Cache-Control` / `public, max-age=604800`.
  ⇒ **Files are cached by URL for 7 days.** Use versioned tile URLs, the same lesson as the `.dae` path cache.
- CSP header attached to local responses (string next to `Content-Security-Policy`):
  `worker-src 'none'; connect-src 'self' http://localhost:* https://localhost:* ws://localhost:* wss://localhost:* http://127.0.0.1:* https://127.0.0.1:* ws://127.0.0.1:* wss://127.0.0.1:*`.
  - It has no `default-src`, `img-src`, `script-src` or `frame-src`, so those are unrestricted **by CSP**.
  - `connect-src` explicitly admits our server for `fetch`, XHR, `EventSource` and `WebSocket`. **I:** that
    whitelist only makes sense if localhost traffic also passes the native filter.
  - `worker-src 'none'` kills `new Worker()` and blob workers.
- Native request filter: the strings `OnBeforeResourceLoad`, `Resource cancel URL={}` and an allowlist next to
  `http-external`: `local://`, `data:`, `devtools://`, `embed/open.spotify.com`, `youtube.com`,
  `youtube-nocookie.com`, `ytimg.com`, `googlevideo.com`, `beamng.gmbh`, `steampowered.com`, `steamstatic.com`.
  - The user's `beamng.log` contains `E|OnBeforeResourceLoad| Resource cancel URL=https://i.imgur.com/7023Ra0.png`.
    ⇒ **Internet image URLs in the UI are blocked.** The page can never fetch OSM/EOX tiles directly; our server
    must proxy them, which it does anyway.
  - localhost/127.0.0.1 is not in that visible list. It may be special-cased elsewhere (the strings `localhost/`,
    `127.0.0.1/` and `.localhost` exist but sit in the curl/luasocket area). **Unverified → probe P2.**
- Dev mode loads the UI from `http://localhost:9000` (`ui/entrypoints/main/resources.js:179`) and devtools from
  `http://localhost:8085` (`index.html:84`). But that path logs "Vue development mode detected, disabling web
  security!", so it does not prove anything for normal mode.
- The only `<iframe>` in stock UI is the YouTube embed in BBCode (`ui/ui-vue/src/services/content/bbcode_main.js:51`),
  matching the allowlist.
- `cef_add_cross_origin_whitelist_entry` is imported (`Failed to modify CEF cross-origin whitelist`). The engine
  edits CORS whitelists, target unknown.

**Consequences for the design**
- Plan A: `<img src="http://127.0.0.1:<port>/map/tile/...">` + `fetch('http://127.0.0.1:<port>/map/search?...')`.
  The server must send `Access-Control-Allow-Origin: *` (or the `local://local` origin) because the page origin is
  `local://local`. Read-only endpoints only.
- Plan B (if P2 fails for http but `fetch`/WS works): `fetch()` the tile as a Blob → `URL.createObjectURL` → `<img>`.
  `img-src` is unrestricted. This is `connect-src`, explicitly allowed.
- Plan C (if all localhost traffic is cancelled): the server writes tiles to `<user>/temp/beamngEarth/map/<ver>/z/x/y.jpg`
  and the page uses `/temp/beamngEarth/map/...` through `local://local` **[probe P3]**. Requests and readiness go
  through Lua (TCP to server → `guihooks`). That adds about 50–150 ms latency per tile batch, which is fine for a map.
- Plan D (no CEF at all): an imgui world map that draws `im.ImTextureHandler('/temp/beamngEarth/map/...')` tiles.
  That API is verified (`lua/common/extensions/ui/imgui_custom_luaintf.lua:199-206`, used by
  `editor/api/gui.lua:38`). It is less pretty but certain, and it extends today's `ui.lua`.

Security: anything on the machine (e.g. a browser tab) can reach 127.0.0.1.
- Keep the HTTP side **read-only**: tiles, search, state.
- Gate it with a per-session random token. The token goes to the mod in `hello`, then to the UI, as `?t=`.
- Keep **all actions** (teleport, destination) on the Lua path (`engineLua`), never as HTTP GETs.

---

## 4. Map library choice

| Option | Needs | Verdict |
|---|---|---|
| **Leaflet 1.9.4** (BSD-2, ~42 KB gz; 2.0 is only alpha, W: https://leafletjs.com/) | DOM, CSS transforms, canvas 2D for vectors; no WebGL, no workers | **Chosen.** Raster XYZ tiles, `L.polyline` route, `L.divIcon` rotated car marker, `L.rectangle`/`L.polygon` loaded area, `worldCopyJump` for the antimeridian, `map.on('click', e => e.latlng.wrap())` |
| MapLibre GL JS 5/6 | WebGL (v6: **WebGL2 required**, ESM only; W: https://newreleases.io/project/github/maplibre/maplibre-gl-js/release/v6.0.0) + **Web Worker** (`worker-src 'self'`/blob needed; W: https://maplibre.org/maplibre-gl-js/docs/) | **Blocked** in the main UI by `worker-src 'none'`. Possible only inside an iframe served by our own http server (own CSP) **and** if WebGL works **[probe P1/P4]**. Not worth it for v1 |
| OpenLayers | canvas 2D; vector tiles work without workers | Viable but ~5x heavier; only if we later want client-side vector tiles |
| Own mini slippy map (~300 LOC) | DOM | A fallback if loading a 3rd-party UMD into the mod runtime turns out awkward |

How Leaflet gets loaded in a Vue mod: ship `leaflet.js` (UMD) + `leaflet.css` in
`ui/ui-vue/mods/beamngEarth/vendor/`. In `onMounted` inject `<script src="/ui/ui-vue/mods/beamngEarth/vendor/leaflet.js">`
(origin `local://local`, `script-src` unrestricted) and use `window.L`. This avoids pushing a 14k-line file through
the runtime SFC compiler (sucrase/meriyah). Importing `leaflet-src.esm.js` directly may also work **[probe P5]**.

Projection: Leaflet uses EPSG:3857, so the poles beyond ±85.05° cannot be shown.
- Teleports to polar lat/lon still work through the search box or typed coordinates.
- The ENU game frame is unaffected.

Since the ENU frame is true-north-aligned at the anchor, the marker heading needs no Mercator correction
(Mercator is conformal). The offset between anchor-north and local north (meridian convergence
`Δlon·sin(lat)`) stays below 0.1° within the 10 km rebase radius.

---

## 5. Tile sources and policies

| Layer | URL (tested 2026-10-10, HTTP 200) | Zoom | Licence / policy | Use |
|---|---|---|---|---|
| USGS ImageryOnly | `basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}` | ≤16 (US; global low-res ≤9) | Public domain | **Satellite**: the same source and cache as the ground (`server/imagery.py:84-92`) |
| EOX Sentinel-2 cloudless 2016 / 2023 | `tiles.maps.eox.at/wmts/1.0.0/s2cloudless[-2023]_3857/default/g/{z}/{y}/{x}.jpg` | ≤14 | 2016: CC BY 4.0; 2023: CC BY-NC-SA 4.0 | **Satellite** worldwide. Bundle 2016 z0–4 offline |
| EOX terrain-light | `tiles.maps.eox.at/wmts/1.0.0/terrain-light_3857/default/g/{z}/{y}/{x}.jpg` | data to ~z13+, served higher | "Just feel free to use them. We just ask for a link back" + data credits (OSM, NaturalEarth, …); "as is" (W: https://maps.eox.at/) | **Default street/terrain map** |
| EOX overlay_bright | `…/overlay_bright_3857/default/g/{z}/{y}/{x}.png` | ≤14 (404 at z15 in test) | as above (OSM data) | Labels/roads over satellite |
| USGS Topo | `basemap.nationalmap.gov/arcgis/rest/services/USGSTopo/MapServer/tile/{z}/{y}/{x}` | US | Public domain | US topo layer |
| OSM standard | `tile.openstreetmap.org/{z}/{x}/{y}.png` | ≤19 | **Policy** (W: https://operations.osmfoundation.org/policies/tiles/): unique stable User-Agent naming the app; honour cache headers or keep ≥7 days; **no prefetch/bulk**; **"Offline use is not permitted"**; visible attribution; heavy use can be blocked without notice | **Opt-in only**, interactive viewing only, never prefetched, proxy keeps the UA and Referer |
| OpenFreeMap | style `https://tiles.openfreemap.org/styles/liberty`, TileJSON `/planet` → `…/planet/<build>/{z}/{x}/{y}.pbf`, z0–14 | vector only | Free, no key, no request limits, commercial OK, attribution OpenFreeMap + OpenMapTiles + OSM (W: https://openfreemap.org/) | Needs a vector renderer: MapLibre (blocked, §4) or server-side rasterisation (heavy). **Later**, or skip |
| Esri World Imagery | `server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` | ≤19+ | Esri Master License; the item page says not for offline export (W: https://goto.arcgis.com/maps/World_Imagery) | BYO key/account only, private cache (matches `docs/ARCHITECTURE.md`) |
| CARTO basemaps | `{s}.basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}.png` | ≤20 | **API key now required** (free, 5 M tiles/month, non-commercial intent; W: https://carto.com/basemaps/apikey/) | BYO key |
| Stadia (Stamen styles) | key | | Free plan 200 k credits/month, non-commercial (W: https://stadiamaps.com/faqs/) | BYO key |
| OpenTopoMap | `tile.opentopomap.org/{z}/{x}/{y}.png` | ≤17 | CC BY-SA; small volunteer server | Avoid by default |

Proxy and cache rules in `earthd`:
- One fetcher (reuse `imagery.py`'s per-host keep-alive HTTPS pool and backoff) with User-Agent
  `BeamNG.Earth/<version> (+<project URL>)`.
- Disk LRU cache per layer.
- For OSM: honour `Cache-Control`/`Expires`, else 7 days, conditional revalidation, and **only tiles the map view
  asks for**. No neighbour prefetch for OSM. Light prefetch is OK for our own satellite chain.
- Rate cap per host (e.g. ≤8 concurrent, ≤50/s for EOX/USGS; ≤2 concurrent for OSM).
- An attribution string per layer in `layers.json`. The map shows it bottom-right, never hidden.

Search (geocoding):
- **Nominatim public**: ≤1 req/s for the whole application, **no autocomplete**, results must be cached,
  identifying UA (W: https://operations.osmfoundation.org/policies/nominatim/). So: search on Enter only, debounce,
  cache, and proxy through the server with the UA.
- **Photon (komoot)** supports type-ahead, "be fair, extensive usage will be throttled"; third-party docs suggest
  1 req/s (W: https://docs.mobilizon.org/3.%20System%20administration/configure/geocoders/).
- Optional later: an offline gazetteer (GeoNames cities15000, CC BY 4.0, ~25 k places, ~3 MB) inside the server
  for instant type-ahead of towns.
- Coordinate parsing (`47.37, 8.54`, DMS, plus-codes later) is client-side.

Routing (shared with the GPS/long-distance topic): OSRM demo server is "≤1 request per second", "reasonable,
non-commercial" (W: https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server). For a cannonball run, one route
request per destination is fine. A self-hosted OSRM/Valhalla over a Geofabrik extract is the robust option.

---

## 6. Map semantics: what to draw and how it maps to the game

- **Player**: GE Lua already has `st.player.lat/lon` (`core.lua:442-453`, via `st.anchor:enuToGeodetic`).
  - Heading: `veh:getDirectionVector()` is in ENU (+X east, +Y north), so `heading = atan2(d.x, d.y)` in degrees,
    0 = north, clockwise.
  - Send `{lat, lon, heading, speedMs, alt}` at 5 Hz while the map is open and 1 Hz for a HUD map. Nothing is sent
    when closed.
  - Marker: `L.marker([lat,lon], {icon: L.divIcon({html:'<div class=car style="transform:rotate(${h}deg)">'})})`.
    Optional "follow" mode keeps the map centred.
- **Loaded area**:
  - Physics TerrainBlock: 1024² × 2 m (`server/heightmap.py:25-29`; collidable 2046 m), centre `(blockCx, blockCy)`
    in ENU. Send 4 corners → `anchor:enuToGeodetic` → `L.polygon`.
  - Near mesh rings 150/400 m (`farfield.py:69`) and far field radius 80 km (`farfield.py:65`) → `L.circle`.
  - Anchor point and rebase radius (`rebase.distance`) as a dashed circle.
  - The server could later send the true union of live far tiles as a simplified polygon.
- **Route**: the server returns a polyline6 in lat/lon → `L.polyline`. Distance and ETA in a side panel. The GPS
  module separately converts the next ~2 km of it to ENU for `core_groundMarkers.setPath({...})`. Re-feed after
  every rebase, because positions change frame.
- **Click → action**: `map.on('click')` → context popup with "Teleport here", "Set destination", "Copy
  coordinates".
  - Lat/lon come from `e.latlng.wrap()`. Clamp lat to ±85.0511.
  - Teleport: `runRaw('beamngEarth_core.teleport(' + lat.toFixed(7) + ',' + lon.toFixed(7) + ')')`. This reuses the
    existing anchor/terrain flow (`core.lua:710-722`): 66 ms in-game commit, ~0.3 s server build per
    `docs/ARCHITECTURE.md` v1.1.
  - Close the map on success, or keep it open with the status line (`st.status`) streamed in.
- **Antimeridian**: `worldCopyJump: true`. Before drawing, unwrap the marker/route longitudes relative to the map
  centre.

---

## 7. Implementation plan

### 7.1 Components and files (all new unless noted)
1. **Server** (`server/maphttp.py` + small hooks in `server/earthd.py`):
   - An asyncio HTTP/1.1 server (stdlib `asyncio.start_server` is enough; no new dependency) on
     `127.0.0.1:47614`, started alongside the TCP port.
   - Routes:
     - `GET /map/layers.json?t=` → `[{id, name, kind:'sat'|'map'|'overlay', minZoom, maxZoom, attribution, url:'/map/tile/<id>/{z}/{x}/{y}?t=...&v=<cacheVer>'}]`
     - `GET /map/tile/<layer>/<z>/<x>/<y>` → JPEG/PNG from cache or fetched upstream. 404 → transparent 1×1.
       Headers: `Access-Control-Allow-Origin: *`, `Cache-Control: max-age=86400`.
     - `GET /map/search?q=&lat=&lon=&t=` → JSON from Photon/Nominatim through a 1 req/s token bucket and an LRU
       cache. Coordinates are parsed locally.
     - `GET /map/state?t=` (optional) → anchor, block polygon, far radius. Lets the page work without Lua hooks.
     - `GET /map/` → optionally a standalone HTML map for debugging in a normal browser.
   - Shared tile fetch/cache code lives in `server/tilecache.py`, refactored out of `imagery.py`'s fetcher, with
     per-layer policy (`allow_prefetch`, `max_conc`, `ua`).
   - `hello` gains `mapHttp: {port, token}`.
2. **TCP protocol additions** (`server/protocol.py` unchanged framing):
   - mod → server `geocode {requestId, q, lat?, lon?, limit}` → `geocode_result {requestId, results:[{name, detail, lat, lon, bbox?, kind}]}` or `geocode_error`.
   - mod → server `route {requestId, from:{lat,lon}, to:{lat,lon}}` → `route_result {requestId, polyline6, distanceM, durationS, bbox}`. Coordinate with the GPS topic owner.
   - These duplicate the HTTP search so that Plan C/D (no localhost from CEF) still works.
3. **GE Lua** (`mod/beamng_earth/lua/ge/extensions/beamngEarth/mapui.lua`, wired from `core.lua`):
   - Public API on `beamngEarth_core`: `mapOpen()`, `mapClose()`, `mapToggle()`, `mapReady()`, `teleport(lat,lon)`
     (exists), `setDestination(lat, lon, label)`, `clearDestination()`, `search(q)`, `getMapInit()`.
   - Hooks to the UI:
     - `BeamNGEarthMapInit {httpBase:'http://127.0.0.1:47614', token, layers?, attribution}`
     - `BeamNGEarthMapPose {lat, lon, heading, speed}`, 5 Hz while open
     - `BeamNGEarthMapArea {anchor:{lat,lon}, rebaseRadius, block:[[lat,lon]x4], nearRadii:[150,400], farRadius}`, sent on change
     - `BeamNGEarthMapRoute {polyline6, distanceM, durationS}`
     - `BeamNGEarthMapSearch {requestId, results}`
     - `BeamNGEarthMapStatus {text, teleporting}`
   - Navigation: `ui_router.navigate('beamngEarth.map')` to open, back target `play`.
   - Bigmap override: in our level, wrap `freeroam_bigMapMode.toggleBigMap` (monkey-patch, restored on unload).
     Alternatively ship input action `beamngEarthToggleMap` in `lua/ge/extensions/core/input/actions/beamngEarth.json`
     and let the user bind it, e.g. `M`.
4. **Vue UI** (`mod/beamng_earth/ui/ui-vue/mods/beamngEarth/`):
   - `index.js`:
     - `onLoad` registers the route `{path:'/beamng-earth-map', name:'beamngEarth.map', component: WorldMap, meta:{uiApps:{shown:false}, luaRoute:{title:'Earth Map', backTarget:'play'}}}` through `window.bngRoutes.add` + `ui_router_routeManager.registerModRoutes`.
     - Also registers a pause-menu button "Earth Map" (`ui_pause_actions.registerModButton`) that navigates to it.
   - `WorldMap.vue`:
     - Leaflet map, layer switcher, search box (Enter → `/map/search` or `beamngEarth_core.search`), results list.
     - Player marker, loaded-area overlays, route, context popup, follow toggle, status and attribution bar.
     - Coordinate entry (lat, lon / DMS).
     - Calls `runRaw` for actions. Uses `useEvents()` for hooks.
     - Calls `mapReady()` on mount to pull `MapInit`, and `mapClose()` on unmount.
   - `vendor/leaflet.js`, `vendor/leaflet.css` (BSD-2 licence file included).
   - `tiles/s2c2016/{z}/{x}/{y}.jpg` for z0–4 (offline base, `local://`).
5. **Later: HUD map app** (`mod/beamng_earth/ui/modules/apps/BeamNGEarthMap/app.json` + `app.vue`, `"vue": true`,
   `"interactive": "optional"`):
   - The same component in compact mode.
   - Throttle pans to ≤10 Hz with CSS transitions, because CEF repaint cost is unknown. The stock minimap avoids CEF
     for exactly this reason (it draws in imgui).
6. **imgui fallback** (extend `ui.lua`): a "Map" tab with a 256 px-tile mosaic through `im.ImTextureHandler`
   (server writes `/temp/beamngEarth/map/...`), click → lat/lon, teleport. Built only if P2 and P3 both fail.

### 7.2 Order of work
1. Run probes P1–P5 (section 8) in one session when the user allows it.
2. Server: `tilecache.py` + `maphttp.py` (tiles, layers, search), with unit tests for tile maths, cache policy,
   rate limiter and CORS headers.
3. Lua `mapui.lua`: hooks, API, heading, loaded-area polygon. Tests under `mod/tests/` with stubs (geodesy of the
   block corners, heading maths).
4. Vue route + `WorldMap.vue` (Leaflet). Teleport end-to-end.
5. Search, then route display (after the GPS/routing work lands), then the HUD app.

### 7.3 Risks
- **R1 (high): localhost blocked by `OnBeforeResourceLoad`** → Plan B/C/D (§3). Mitigated by the probes before any
  UI work.
- **R2: WebGL absent** → irrelevant with Leaflet. Only matters if vector maps are wanted later.
- **R3: Runtime SFC compiler quirks** (imports, `<script setup>` features, UMD libs) → load Leaflet with a script
  tag, keep the SFC simple. Reference examples: the user's `realisticdrivercamera` / `enhancedvehiclefx`.
- **R4: Policy**:
  - OSM tiles and Nominatim must never be prefetched or autocompleted. The server enforces this.
  - EOX "demo service as is" may rate-limit, so cache aggressively and keep the bundled z0–4.
  - 2023 s2cloudless is NC-SA, so show it in the attribution.
- **R5: Port clash / multiple servers** → port in `hello`, not hard-coded in the UI.
- **R6: Hook spam / GC** → only while the map is open. Pose payload of ~6 numbers. Encoded route sent once.
- **R7: Game-version churn**: 0.39 rewrote the router/pause APIs (README describes "registerModRoutes", new in
  this generation). Pin to the documented APIs and re-check on game updates.
- **R8: Local-scheme cache (`max-age=604800`)** → version all `/temp` tile paths if Plan C is used.
- **R9: Map open during a rebase** → positions come as lat/lon from Lua, so they are frame-independent. Only the
  ENU waypoints for ground markers need re-feeding after a rebase.
- **R10: Input**: on our route the cursor and keyboard belong to the UI. The ESC/back handling has to follow the
  router (`backTarget:'play'`). The text field must stop the game's key bindings: BeamNG uses `bng-no-nav` /
  `v-bng-on-ui-nav` (see `BigMap.vue:1-40`).

---

## 8. In-game probes to run later (GE Lua, via the console or MCP `run_lua`, only when the user allows)

Results come back through `beamng.sendEngineLua` → `log()`; read them with MCP `get_logs` or in `beamng.log`.

**P1: WebGL, workers, UA.**
```lua
be:executeJS([[(function(){var r={ua:navigator.userAgent};
 try{r.webgl2=!!document.createElement('canvas').getContext('webgl2')}catch(e){r.webgl2=String(e)}
 try{r.webgl=!!document.createElement('canvas').getContext('webgl')}catch(e){r.webgl=String(e)}
 try{new Worker(URL.createObjectURL(new Blob(['1'],{type:'text/javascript'})));r.worker='ok'}catch(e){r.worker=String(e)}
 r.origin=location.origin;r.href=location.href;
 beamng.sendEngineLua('log("I","bngEarthProbe","P1 "..'+JSON.stringify(JSON.stringify(r))+')')})()]])
```
Expect `webgl2=false` and `worker=SecurityError`. If WebGL works, note the renderer:
`gl.getParameter(gl.RENDERER)`.

**P2: localhost from the main UI** (img, fetch, WS, iframe). Before running it, start a probe server *outside* the
game. Use a new scratch script that serves `/p.png` and `/j` with `Access-Control-Allow-Origin: *`, logs the
request `Origin`/`User-Agent` headers, and accepts a WebSocket. Port 47699. Then:
```lua
be:executeJS([[(function(){var B='http://127.0.0.1:47699',out={};function rep(k,v){out[k]=v;
 beamng.sendEngineLua('log("I","bngEarthProbe","P2 '+k+' "..'+JSON.stringify(JSON.stringify(v))+')')}
 var i=new Image();i.onload=function(){rep('img','ok '+i.width)};i.onerror=function(e){rep('img','error')};i.src=B+'/p.png?'+Date.now();
 fetch(B+'/j').then(function(r){return r.text()}).then(function(t){rep('fetch','ok '+t.length)},function(e){rep('fetch',String(e))});
 fetch(B+'/p.png').then(function(r){return r.blob()}).then(function(b){rep('fetchBlob','ok '+b.size)},function(e){rep('fetchBlob',String(e))});
 try{var w=new WebSocket('ws://127.0.0.1:47699/ws');w.onopen=function(){rep('ws','open');w.close()};w.onerror=function(){rep('ws','error')}}catch(e){rep('ws',String(e))}
 var f=document.createElement('iframe');f.style.display='none';f.onload=function(){rep('iframe','load')};f.src=B+'/frame.html';document.body.appendChild(f);
 setTimeout(function(){f.remove()},5000)})()]])
```
Then check `beamng.log` for `Resource cancel URL=http://127.0.0.1:47699/...` and the probe server's request log.
The request log shows which requests actually arrived, and the `Origin` value tells us how to set CORS.

**P3: `/temp` via `local://`.** First write a PNG to `<user>/temp/beamngEarth/probe_map.png` (outside the game,
or `writeFile` from Lua). Then:
```lua
be:executeJS([[(function(){var i=new Image();i.onload=function(){beamng.sendEngineLua('log("I","bngEarthProbe","P3 ok '+i.width+'")')};
 i.onerror=function(){beamng.sendEngineLua('log("I","bngEarthProbe","P3 error")')};i.src='/temp/beamngEarth/probe_map.png?'+Date.now()})()]])
```

**P4: an iframe page with its own CSP.** Only if P1 shows WebGL and P2 shows `iframe load`. Serve a page from the
probe server that creates a Worker and a WebGL2 context and posts the result back with
`parent.postMessage`. This decides whether MapLibre in an iframe is ever an option.

**P5: Leaflet in the mod runtime.** Drop a test mod `ui/ui-vue/mods/bngEarthProbe/` with a `Probe.vue` that
(a) injects `vendor/leaflet.js` with a script tag and (b) separately `import`s `./vendor/leaflet-src.esm.js`. Mount it
as a pause button. Check that both create an `L.map` with one tile layer. Measure the frame time while panning
(`perfmon`).

**P6: bigmap override safety.** In our level, run `freeroam_bigMapMode.toggleBigMap()` once and watch the log. If
the stock big map breaks or misbehaves on our level (no level bounds or POIs), that justifies redirecting `M` to our
map.

---

## 9. Sources
- Game install: paths and line numbers as cited above (`$BNG/ui/...`, `$BNG/lua/...`), binary
  `$BNG/BinLinux/BeamNG.drive.x64` (strings), user log `~/.local/share/BeamNG/BeamNG.drive/current/beamng*.log`.
- OSM tile usage policy: https://operations.osmfoundation.org/policies/tiles/
- Nominatim usage policy: https://operations.osmfoundation.org/policies/nominatim/
- OpenFreeMap: https://openfreemap.org/ , https://openfreemap.org/quick_start/ , TileJSON https://tiles.openfreemap.org/planet
- EOX Maps terms: https://maps.eox.at/
- MapLibre docs (WebGL, worker CSP): https://maplibre.org/maplibre-gl-js/docs/ ; v6 WebGL2-only: https://newreleases.io/project/github/maplibre/maplibre-gl-js/release/v6.0.0
- Leaflet: https://leafletjs.com/
- CARTO basemap key: https://carto.com/basemaps/apikey/ ; Stadia: https://stadiamaps.com/faqs/
- Esri World Imagery item: https://goto.arcgis.com/maps/World_Imagery
- OSRM demo server policy: https://github.com/Project-OSRM/osrm-backend/wiki/Demo-server
- Photon fair-use (quoted by): https://docs.mobilizon.org/3.%20System%20administration/configure/geocoders/
