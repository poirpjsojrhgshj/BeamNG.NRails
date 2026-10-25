# BeamNG.EarthNRails — BeamNG.Earth + real-world railways

A fork of [BeamNG.Earth](https://github.com/TecnaGamer/BeamNG.Earth) (MIT, © TecnaGamer; currently on
**1.6.1-beta**) that keeps its roads, buildings and terrain and adds the real rail network (Overture Maps /
OpenStreetMap) as **physically drivable track** for rail mods (TEM2, WLD FS30-2, tanker wagon, DMM512…) on the same
1:1 streamed map.

## Quick start (Windows)

1. Python 3.10+ from python.org (tick *Add python.exe to PATH* and *tcl/tk*).
2. Double-click **`run_hub.bat`** → *Installer / mettre à jour* (mod `beamng_earthnrails` into the game, server
   packages into `.venv`) → *Démarrer le serveur* → *Lancer BeamNG.drive* → Freeroam → BeamNG.Earth.
3. Tab *Rails*: track settings; tab *Cache*: cache folder, size cap, temp clean-up; tab *Outils*: mod switch back to
   the original BeamNG.Earth, environment check.

The fork installs as `mods\unpacked\beamng_earthnrails` and turns the upstream `beamng_earth` off in `mods\db.json`
(both own `/levels/beamng_earth` and `lua/ge/extensions/beamngEarth`: only one may be active). In the game:

| Key | What |
|---|---|
| **Ctrl+Shift+I** | the keys' help on / off (also the window's *Keys* button) |
| **Ctrl+Shift+U** | the BeamNG.Earth window (its *Snap to rail*, *Reload area* and *Keys* buttons) |
| **Ctrl+Shift+T** | snap to rail: the current vehicle on the nearest track |
| **Ctrl+Shift+G** | reload area: the server asked for the whole area again |
| **Ctrl+Shift+← / ↑ / →** | the next facing turnout ahead (600 m): left / straight (its default) / right |

(Options → Controls → Bindings → Gameplay → *BeamNG.EarthNRails: …* to change them.)

## How the fork is laid out (merging upstream)

Everything the fork adds lives in its own files; upstream's files only carry single lines marked `NRails hook`
(and one `NRails hook begin` … `end` block in `roads.lua`). `python tools/nrails_hooks.py` lists them;
`--check` proves that upstream's files differ from the `upstream` branch in hook lines only.

| Fork file | What |
|---|---|
| `server/nrails/hooks.py` | the functions the hook lines call; each failure-safe (an error costs the NRails part, never the upstream content) |
| `server/nrails/rails.py` | the track: profile, tunnels, meshes (rails, sleepers, ballast, viaducts, catenary, level crossings) |
| `server/nrails/decks.py` | road bridges clear the tracks under them |
| `server/nrails/bridges.py` | approach slabs past road bridge abutments |
| `server/nrails/profile.py` | road class profile limits (motorway grade, smoothing) |
| `server/nrails/paths.py` | the cache folder default |
| `mod/.../beamngEarth/nrails.lua` | the mod side: rail meshes, level crossing slabs, rail vehicles, snap to rail, far trains' collision |
| `hub.py`, `nrails_install.py`, `nrails_launcher.py`, `run_hub.*` | the Hub, the install with the fork's mod name |
| `settings/inputmaps/keyboard_nrails.json`, `core/input/actions/nrails.json` | the key binding |

Hook sites: `earthd.py` (boot, anchor tile files, road tile extras, terrain holes), `peerwork.py` (boot),
`blockworker.py` (road tile extras, terrain holes), `grading.py` (road profile), `roads.py` (shape files, write
tile, bridge solver), `roads.lua` (extension kinds, onTile, queue/remake, update, lean meshes), `core.lua` (init,
snap button), `ui.lua` (snap buttons).

**Merging a new BeamNG.Earth release:** `git checkout upstream`, copy the release over, commit it unmodified;
`git checkout main && git merge upstream` (conflicts can only be on hook lines); `python tools/nrails_hooks.py
--check`; run `tools/run_tests.py` and `tools/run_lua_tests.py`; reinstall from the Hub (new requirements).

## What the server builds

Per 256 m road tile, next to the road meshes (same pipeline, pooling, rebase and collision radius):

| Shape | Drawn | Collides | Content |
|---|---|---|---|
| `rail_*[_k].cdae` | yes | no | UIC rail profile, B70 sleepers every 0.60 m, ballast, viaduct slabs / parapets / piers, catenary |
| `railcol_*[_k].cdae` | no | yes | one box per rail (head width × 0.36 m), the ballast bed (crest 0.23 m under the rail top), viaduct slabs and parapets, crossing outer slabs |
| `railx_*.cdae` | yes | only while no rail vehicle is within 150 m | level crossings' inner slabs, 45 mm flangeways |
| `railtun_*.cdae` | yes | yes | rail tunnel tubes and portals (the terrain is cut at the portals) |

* Gauge 1,435 mm; profile UIC 60 (default), UIC 54, UIC 50, JIS 60.
* Plan: mapped corners rounded (Chaikin), resampled every 2 m.
* Profile: upper envelope of the ground (±8 m), Gaussian σ 24 m, +0.50 m formation; at least 0.32 m over the
  physics ground; grade capped (default 35 ‰, an embankment where the ground is steeper); nodes pinned so tracks
  meeting there agree; bridges straight between their ends; **tunnels** as a network (runs between nodes, the
  portals fixed, crossovers and branches cut in: one level), straight from portal to portal along a chain, 15 m
  under the ground when no portal is known; chains up to 60 km profiled whole in every window.
* **The same heights in every tile**: each road tile profiles its tracks 500 m round it (`NEAR_M`), every reach of
  one sample's height (grade cap 360 m, side-by-side easing 80 m, node lifts 100 m) inside that, the roads crossing
  them read 400 m further, the tracks round a structure's ends included: steps at tile seams of a few cm
  (`tools/audit_rail_route.py --tile-seams`).
* **Cant**: equilibrium cant min(150 mm, 11.8 V²/R) at V = min(4.6 √R, 160 km/h), curvature smoothed over 30 m,
  none near level crossings.
* **Viaducts**: slab, parapets (1 m, colliding), piers every 30 m where the slab is 1.5 m+ over the ground.
* **Catenary** over standard gauge and light rail: masts every 55 m (7.6 m, on the side with room), contact wire
  5.5 m, messenger 6.7 m; drawn only; none in tunnels.
* **Road bridges over tracks**: 6 m free over the rail top under the girders where the deck can climb that high
  (`tools/audit_deck_over_rail.py`).
* **Tracks side by side** (double track, station tracks) at one level: raised to the higher of the two, eased in
  and out at 1.2 % (`BNGE_RAIL_PARALLEL`).
* **Grade-separated crossings**: a road crossing a track is a level crossing only where the map joins them (a shared
  Overture connector), or for a minor road whose ground shows no structure; otherwise (and under every road bridge or
  over every road tunnel) the track goes straight through at its own level, the structure's embankments masked out
  of its ground (`BNGE_RAIL_SEP`).
* **The railway's bed in the terrain** (`server/nrails/grade.py`, `BNGE_RAIL_GRADE`): the track's own grading plan in
  upstream's grader: 0.6 m under the rail top over 3.5 m each side, cut and filled back to the ground beside it, 6 m
  into tunnel mouths, at road level across level crossings. Embankments and cuttings, no hillside in the train's way.
* **Collision kept light**: the collision line simplified (within 1 cm), in parts of ~5k triangles (up to 12
  `railcol` parts per tile) (the terrain patches under far vehicles: upstream's 128 m cells since 1.6.2).
* **Viaducts side by side**: no parapet toward the next track, the two slabs joined into one deck.
* **Stations**: buildings standing on a track (platform canopies traced by ML footprints) left out; a footprint the
  tracks run through and that reaches out on both sides of them (a footbridge, a station hall over the tracks) is
  lifted to start 7 m off the ground (6 m free over the rail top) instead of standing on the tracks; mapped
  platforms at track level (infrastructure transit/platform, level 0) built as 0.55 m slabs, edge 1.65 m from the
  track centre (EN 15273), never reaching closer than 1.65 m to the next track; a bridge structure's piers keep off
  the tracks as off the roads.
* **Tunnel mouths**: from each portal into the hill until the ground stands 2 m over the vault, every terrain sample
  over the tube is cut whatever its height (no slope left hanging into the opening); the portal face covers the
  highest ground over that stretch (`BNGE_RAIL_MOUTH_CUT`, `tools/audit_rail_portals.py`).
* **Tunnels under the sea / a valley**: where the straight line between the portals would leave the vault out of
  the ground (the Channel Tunnel over the sea floor), the track dives to 8 m of ground over the vault at 1.25 %
  (at the line's grade limit when the shore is too close to the portal), the portals unchanged. In the mod, a train
  in a tunnel under the sea is out of the sea's water physics (`nrails.physZ`: the cover found by a ray down onto
  the terrain over the tube, as the tube itself is drawn only).
* **Road bridges**: a road crossing a deck near its end is a junction at grade only where the map joins them; the
  street under a short motorway span is lowered for it (grading's `UNDER_*`, tuned through `nrails.hooks.tune`,
  `BNGE_ROAD_TUNE=off` for upstream's values).
* **Loading**: the mod makes the colliders first, then the track drawn, then the buildings' collision, then the rest;
  a grey loading screen holds the game while the path ahead (3 s of driving, 60 m at least) is not loaded
  (`nrailsload.lua`).
* **Corridor in the terrain** (`nrails.corridor`, `BNGE_RAIL_CORRIDOR`): as a terrain block's heights are made, the
  ground within 3.4 m of every track in the open stays 0.65 m under its rail top, with a 1:1 cutting wall beyond
  (24 m at most); it only cuts. The track's own level ignores bumps shorter than 32 m in the elevation data (trees,
  houses, a road bridge's ramps): the corridor cuts them away instead of the track climbing over them.
* **Road bridges over the track** (`nrails.thin`): a deck whose 2.2 m of slab and girders would leave under 6.5 m
  over the rails is drawn as a 0.6 m slab bridge (no girders), its piers up to it.
* **Nothing on the track** (`nrails.clearway`): street furniture (poles, lamps, street trees) within 3.2 m of a
  track at its level, pole-to-pole wires through the track's room (under 7.5 m over the rails) and road retaining
  walls across the track are left out. Catenary masts keep 3.2 m from any other track.
* Overture's rail class `unknown` (OSM's abandoned / disused lines) is not drawn (`BNGE_RAIL_UNKNOWN=on` to draw
  it); narrow gauge is.
* Mod: **Reload area** button (beside *Snap to rail*): the server is asked for the whole area again (reconnect);
  the loading line reads *roads, rails & buildings*.
* **Turnouts** (`nrails.switches`, `BNGE_RAIL_SWITCHES`): where tracks fan out from a node (within 20°), each route
  through the turnout's zone (up to 100 m) is its own collision shape (`railswN`), only the set route colliding:
  a bogie can no longer pick the wrong track. The mod sets it: a trailing turnout follows the train, a facing one
  takes the choice made ahead (Ctrl+Shift+← / ↑ / →), else its straightest route. Diamonds and the rest: a rail's
  collision dropped where it runs inside another track's gauge (simplified frog).
* **Bridge piers off the tracks** (`nrails.clearway`): a road bridge's pier within 2.2 m of a track is left out.
* **Tunnel portals on a cliff**: the ground next to a tunnel or a structure is median-filtered on its own side
  before the fill through it (a cliff read at a portal no longer lifts the whole bore).
* **Loading guard**: the hold on the path ahead ignores a teleport (snap to rail, reload): no more stuck loading
  screen after a snap.
* Trams: grooved heads flush with the street, render-only.
* Trains away from the player: a 480 m collision island around every rail vehicle (collisionfoci.lua, wrapped).

Environment (set by the Hub): `BNGE_RAILS`, `BNGE_RAIL_PROFILE`, `BNGE_RAIL_TRAMS`, `BNGE_RAIL_CROSSINGS`,
`BNGE_RAIL_CATENARY`, `BNGE_RAIL_CANT`, `BNGE_RAIL_MAX_GRADE` (‰), `BNGE_CACHE_DIR`; `BNE_CLASS_PROFILE` (road
class profiles). Switches for diagnosis (on by default): `BNGE_RAIL_PARALLEL`, `BNGE_RAIL_SEP`, `BNGE_RAIL_GRADE`,
`BNGE_RAIL_MOUTH_CUT`, `BNGE_RAIL_CORRIDOR`, `BNGE_ROAD_TUNE`; off by default: `BNGE_RAIL_UNKNOWN`. Rail vehicles beyond the built-in ones: Hub → *Rails* → list of jbeam names
(`<user>/settings/beamngEarth/nrails_vehicles.json`).

### Why sleepers, ballast and the crossing inner slab never collide

The rail mods' wheelsets are a tread cylinder (1.50–1.53 m wide) on the rail heads plus a **flange disc** cylinder
(r 0.60–0.68 m, 1.37 m wide) filling the whole gauge 155–180 mm under the rail top (`tools/train_envelope.py`).
Anything solid between the rails above rail top − 0.21 m stops the train, so the level crossing's inner slab is
solid for cars only while no rail vehicle is near.

| Mod | Height over rail top (p99 / max) | Half-width | Flange disc under rail top |
|---|---|---|---|
| WLD FS30-2 | 4.86 / 5.98 m | 1.56 m | 0.180 m |
| TEM2 | 4.43 / 4.71 m | 1.56 m | 0.155 m |
| Tanker wagon | 4.23 m | 1.49 m | 0.180 m |

## Known limits

* Short road bridges over tracks: a deck climbs at most 6 % from abutments that keep the ground's height, so a
  short one can stay under 6 m even as a thin slab (5.3-5.5 m at the worst seen): enough for the trains
  (4.3-4.9 m), a catenary would touch it.
* The game's loading speed depends a lot on the cache drive: on a USB hard disk a cold road tile takes 15-30 s
  (thousands of small files read, written and touched), a few seconds on an SSD.
* Road tunnels under a motorway mapped both as a road tunnel and a motorway bridge (seen on a French motorway): the coarse
  elevation data sees no cover, the tunnel is graded as an open cutting.
* Road tunnels' low arches (3.6 m) ignore trains.
* Tile seams of a track can differ by a few cm (up to ~0.3 m in a few spots of a big terminal: Folkestone).
* A DEM spike or a hillside more than ~11 m over the track within 360 m is crossed steeper than the grade limit
  (the grade cap's reach, for the tiles to agree); a portal on a steep hillside can be approached at 5-10 %.
* The Channel Tunnel: profile, cover and seams checked on the DEM; with the sea floor carved from bathymetry, not
  yet in game; inside the tube under the sea the water physics are off (the mod), the underwater fog not tested.
* Profiling is ~2x what it was (the 500 m window); tiles near a 50 km tunnel take a few seconds each (server
  side, in the background).
* Switches are simplified (no moving blades, no frog geometry); trams have no collision; subway and narrow gauge
  are drawn as standard gauge (or left out); no AI trains or station buildings of our own; no LOD for far track.
* The server builds a road tile's buildings with its roads (one job): the hierarchy terrain > roads & rails >
  buildings holds on the mod side (what is made first), not in the server's queue.
* Rail lines only come from Overture's `rail` segments: a missing or misclassed segment is missing in the game.

## Dev tools

    .venv\Scripts\python.exe tools\nrails_hooks.py --check          the hook lines; upstream files touched elsewhere
    .venv\Scripts\python.exe tools\build_rail_tile.py LAT LON       real rail tiles to build\railtest (no game)
    .venv\Scripts\python.exe tools\audit_rail_continuity.py LAT LON seams, joints, grades of the built track
    .venv\Scripts\python.exe tools\audit_deck_over_rail.py LAT LON  free height under road bridges over the tracks
    .venv\Scripts\python.exe tools\audit_deck_over_road.py LAT LON  free height under road bridges over roads
    .venv\Scripts\python.exe tools\audit_rail_separation.py LAT LON level / grade-separated rail-road crossings
    .venv\Scripts\python.exe tools\audit_rail_clearance.py LAT LON  terrain in the train's way, bed graded on / off
    .venv\Scripts\python.exe tools\audit_rail_portals.py LAT LON    terrain in the train's way at tunnel mouths
    .venv\Scripts\python.exe tools\audit_rail_route.py A_LAT A_LON B_LAT B_LON [--tile-seams KM] [--portals]
                                                                    the rail path A -> B: gaps, tunnels, portals;
                                                                    --tile-seams: as the game (canon), the seams,
                                                                    steepest grade, tunnel vaults out of the ground
    .venv\Scripts\python.exe tools\find_rail_tunnels.py LAT LON     rail tunnels round a point
    .venv\Scripts\python.exe tools\plot_road_tiles.py ...           a top view of road / rail tiles
    .venv\Scripts\python.exe tools\train_envelope.py                installed rolling stock envelopes
    .venv\Scripts\python.exe tools\run_lua_tests.py                 the mod's Lua tests (LuaJIT via lupa)
    .venv\Scripts\python.exe tools\run_tests.py test_nrails_rails   server tests

## Credits and licence

MIT, like upstream: BeamNG.Earth © TecnaGamer (see `LICENSE`, `CREDITS.md`); the EarthNRails additions © their
authors. Map data © Overture Maps Foundation / OpenStreetMap contributors (ODbL). Rail vehicles are third-party
mods, not included.
