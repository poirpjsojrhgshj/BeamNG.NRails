# BeamNG.NRails — 1.2.1

**For BeamNG.Earth 1.6.3-beta** (included: this download is BeamNG.Earth 1.6.3-beta + NRails).

**Real-world railways you can drive, on the whole Earth, in BeamNG.drive.**

BeamNG.NRails is a fork of [BeamNG.Earth](https://github.com/TecnaGamer/BeamNG.Earth)
by TecnaGamer, the 1:1 streamed Earth for BeamNG.drive. It keeps everything BeamNG.Earth builds (terrain, roads,
buildings, trees, sea, airports) and adds the **real rail network** (Overture Maps / OpenStreetMap) as **physically
drivable track** for the community's rail mods: drive a locomotive from one real station to another, through the
real tunnels, over the real viaducts, across the real level crossings.

> Main lines, junctions and stations are drivable; big yards and some tunnel mouths still have flaws
> (see *Known limits*). Reports are welcome (*Issues* tab).

---

## Contents

1. [What NRails adds to BeamNG.Earth](#what-nrails-adds-to-beamngearth)
1. [What it builds](#what-it-builds)
2. [Requirements](#requirements)
3. [Rail mods (rolling stock)](#rail-mods-rolling-stock)
4. [Install](#install)
5. [Play: keys and buttons](#play-keys-and-buttons)
6. [Settings](#settings)
7. [Known limits](#known-limits)
8. [Updating, uninstalling](#updating-uninstalling)
9. [For developers](#for-developers)
10. [Licences and credits](#licences-and-credits)

---

## What NRails adds to BeamNG.Earth

| | BeamNG.Earth 1.6.3-beta alone | with BeamNG.NRails 1.2.1 |
|---|---|---|
| Railway track | a track to drive cars on (sleepers and ballast solid) | track for **rail mods**: only the rails collide, the wheels' flanges run free |
| Turnouts | both routes solid: a train picks a route by chance | **only the set route solid**, set by the train, your keys, a click on the diagram or an itinerary |
| Level crossings | the track stops at the road | **rails across**, open for trains, solid for cars; **barriers and red lights where OpenStreetMap has them**, signals red and stuck cars removed when a vehicle blocks it |
| Tunnels | left out | **tunnels** with tubes and portals, long and undersea ones |
| Viaducts, bridges | rail bridges on piers | viaducts with parapets; **road bridges at least 6 m over the rails**, no pier on a track |
| Profile | smoothed ground, 2 % ramps | shared per-cell profiles (no steps between tiles), cant in curves, grade cap, corridor cut in the terrain |
| Signals | — | **light signals** as on French lines: protection and advance signals, *carré*, *ralentissement*, yard shunting signals |
| Driving aids | — | **track diagram** with clickable turnouts and **itineraries**, **rail guidance** with a strength slider, **speed regulator**, **speed control** from the signals (after the French KVB), **train configurator** (length vs the local norm, stopping distances, add vehicles), **OpenStreetMap's railways on the map** (100 km, itineraries along them), **snap to rail**, coupling assistant, keys window |
| Catenary, platforms | — | overhead line, platforms and footbridges kept off the track |
| Loading | — | the game waits while the track ahead of a fast train is not loaded |

## What it builds

Around you, as you move, next to BeamNG.Earth's roads (same streaming, same 256 m tiles):

| | |
|---|---|
| **Track** | standard gauge 1,435 mm, UIC 60 rails (UIC 54 / UIC 50 / JIS 60 selectable), concrete sleepers every 0.60 m, ballast; cant in curves; the same heights in every tile (shared profiles) |
| **Profile** | follows the ground's smoothed envelope, grade capped (35 ‰ by default), embankments and cuttings dug into the terrain (a corridor kept clear around the track) |
| **Viaducts** | slab, parapets, piers |
| **Tunnels** | straight from portal to portal, concrete tubes, mouths cut into the hills; long and undersea tunnels (water physics off inside) |
| **Level crossings** | slabs flush with the road, flangeways; solid for cars, open for trains |
| **Road bridges over the track** | at least 6 m free over the rails (a thin slab where a deck would be too low), no pier on the track |
| **Turnouts** | each route through a turnout has its own collision, only the set route is solid: the train follows the route you chose; light signals before them |
| **Catenary** | masts and wires over electrified lines (drawn only) |
| **Stations** | platforms at track level, footbridges and halls lifted over the tracks, street furniture kept off the track |
| **Trams** | grooved rails flush with the street (drawn only) |

The mod also holds the game (a grey loading screen) while the track ahead of a fast train is not loaded yet.

## Requirements

| | |
|---|---|
| **System** | Windows 10 / 11, 64-bit (Linux works from the source, not tested for NRails) |
| **Game** | [BeamNG.drive](https://www.beamng.com/) (Steam or the BeamNG store), a recent version |
| **Python** | [Python 3.10 or newer](https://www.python.org/downloads/): during its install tick **"Add python.exe to PATH"** and keep **"tcl/tk"** |
| **Internet** | always on while playing: elevation, imagery and map data are downloaded as you travel |
| **Disk** | a cache folder of 5–50 GB (20 GB by default). **An SSD is strongly recommended**: on a USB hard disk a new area takes 15–30 s per tile to load, a few seconds on an SSD |
| **PC** | what BeamNG.drive needs, plus a few CPU cores for the companion server (16 GB of RAM or more recommended) |

## Rail mods (rolling stock)

BeamNG.NRails builds the **track**; the **trains** are community mods, **not included** (each one under its own
author's licence). Download them from the in-game *Repository* or the BeamNG forum. The ones tested:

| Mod | What | Recognised as a rail vehicle |
|---|---|---|
| **TEM2** | diesel shunting locomotive | yes (`tem2`) |
| **WLD FS30-2** | 6-axle locomotive | yes (`6axle_train`) |
| **Tank wagon** | freight wagon | yes (`tank`) |
| **DMM512** | rail vehicle | yes (`train`) |
| MRK tracks / MRK crossings | the rail profile the track's collision copies | (reference only, not needed) |

Any other rail mod: Hub → **Rails** tab → add its *jbeam* name to the list of rail vehicles (so level crossings open
for it and far trains keep their collision).

## Install

1. Install **Python** (see *Requirements*) and **BeamNG.drive**; start the game once, then close it.
2. Download this repository: green **Code** button → **Download ZIP**, unzip it anywhere (for example
   `D:\BeamNG.NRails`). Or the zip from the **Releases** page.
3. Double-click **`run_hub.bat`**. The *Hub* opens (a small window).
4. In the Hub, with **the game closed**: **Installer / mettre à jour** (Install / update). It copies the mod
   `beamng_earthnrails` into the game's mods folder (and switches the original BeamNG.Earth off: only one of the two
   can be active), and installs the server's Python packages into `.venv`. The first time takes a few minutes.
5. Tab **Cache**: choose the cache folder (on an SSD if you can).
6. **Démarrer le serveur** (Start the server), then **Lancer BeamNG.drive** (Start the game).
7. In the game: *Freeroam* → **BeamNG.Earth** → pick a place (a station!) → spawn a rail mod's vehicle →
   **Ctrl+Shift+T** puts it on the nearest track.

## Play: keys and buttons

| Key | What |
|---|---|
| **Ctrl+Shift+I** | the list of NRails' keys on / off (it also opens when you board a train, unless you tick *do not show again*) |
| **Ctrl+Shift+U** | the BeamNG.Earth window: *Teleport*, **Snap to rail**, **Reload area**, *Keys* |
| **Ctrl+Shift+T** | **Snap to rail**: your vehicle on the nearest track (within 40 m), facing the way it faced; pressed again within 6 s: the next track beside it |
| **Ctrl+Shift+G** | **Reload area**: asks the server for the whole area again (roads, rails, buildings that did not come) |
| **Ctrl+Shift+← / ↑ / →** | the **next turnout** ahead of your train: left / straight (main line) / right |
| **Ctrl+Shift+M** | the **track diagram** on / off (see below) |
| **Ctrl+Shift+O** | **couple**: coupling armed 60 s on your vehicle and the rail vehicles within 80 m; drive gently until the couplers are within 2 m |
| **Ctrl+Shift+N** | **uncouple** |
| **Ctrl+Shift+B** | **rail guidance** on / off: the wheels held on the track (no swaying, no climbing the rail), or the free physics; its strength: the slider in the keys window |
| **Ctrl+Shift+K** | **speed regulator** on / off at the speed you are at (your brake disconnects it) |
| **Ctrl+Shift+PageUp / PageDown** | regulator ±5 km/h |
| **Ctrl+Shift+J** | **train configurator**: consist, length vs the norm where you are, stopping distances, add vehicles behind |

**The track diagram** shows the tracks round your train (or, in *turnout view*, the next turnout ahead): the set
routes in green, your choices in yellow, your itinerary in blue, your train as a blue dot.
* **Click a turnout's branch**: that turnout will be set to it as soon as no train is on it. Set as many as you like.
* **Click a grey track**: an **itinerary** there along the rails (never reversing); every turnout on the way is set
  for you, and the itinerary ends when you arrive. *Clear* forgets your choices and the itinerary.
* *+ / -* zoom, *Area view / Turnout view*.

**Signals** (as on French lines): 40 m before each turnout, green: the main line is set; two yellow lights one over
the other: a diverging route (flashing: 60 km/h, steady: 30 km/h); two red lights (*carré*): a vehicle is on the
turnout, stop. On open line an advance signal 220 m before: two yellow lights side by side (slow down for the
turnout), one yellow (the turnout is taken). In yards, low shunting signals: white (go), violet (stop). **Turnouts**
you take from a branch set themselves for you.

**On BeamNG.Earth's map** (M): the *Rails* button shows the loaded tracks in orange. Right-click on a track: an
**itinerary** there (the turnouts set for you) or **teleport onto the track**; further away: the train heads that
way, or teleport there and be put on the rails once they load.

Keys can be changed in *Options → Controls → Bindings → Gameplay* (*BeamNG.NRails: …*). The rest of
BeamNG.Earth's settings: pause menu → *Mods* → *BeamNG.Earth*.

## Settings

Hub → **Rails** tab: rails on / off (off: BeamNG.Earth's own railways), rail profile, trams, level crossings,
catenary, cant, signals, maximum grade (‰), extra rail vehicles. Hub → **Cache**: folder, size cap, clean-up of temporary files (do one after an update). Hub →
**Outils** (Tools): switch back to the original BeamNG.Earth, environment check.

## Known limits

* Big stations and yards: tracks mapped very close together or meeting at odd heights can give small steps.
* Turnouts are simplified: no moving blades, no frog geometry.
* Barriers and their lights are drawn by the game's debug drawer (no shadows, no collision); a crossing with no
  OpenStreetMap node nearby shows the St Andrew's cross only.
* The train length norms and the stopping distances of the configurator are indicative values.
* Itineraries only use the tracks already loaded round you (about 1 km).
* Coupling works with rail mods that have couplers (the tested ones do); the vehicles must touch (within 2 m).
* Some tunnel mouths show untextured faces or terrain over twin tubes.
* No AI trains, no station buildings of our own; subway lines are left out; trams have no collision.
* The track only exists where Overture Maps has a `rail` segment: a missing or wrongly classed line is missing.
* Loading speed depends mostly on the cache drive (see *Requirements*).

The full technical list is in [NRAILS.md](../NRAILS.md).

## Updating, uninstalling

* **Update**: download the new version over the old folder (or a new folder), game closed → `run_hub.bat` →
  *Installer / mettre à jour* → Cache → clean temporary files.
* **Back to the original BeamNG.Earth**: Hub → *Outils* → switch the mod back.
* **Uninstall**: delete `mods\unpacked\beamng_earthnrails` in the game's user folder, the NRails folder and the cache
  folder.

## For developers

How the fork is laid out, how it follows BeamNG.Earth's releases (all NRails code in its own files, upstream files
only carry one-line `NRails hook`s), the dev and audit tools and the tests: [NRAILS.md](../NRAILS.md).
Upstream's own documentation: [README.md](../README.md).

## Licences and credits

* **BeamNG.Earth**: © TecnaGamer, [MIT licence](../LICENSE). Its own credits: [CREDITS.md](../CREDITS.md).
* **BeamNG.NRails additions** (`server/nrails/`, the `nrails*` mod files, the Hub, the tools): © the BeamNG.NRails
  authors, MIT licence ([LICENSE.NRails](../LICENSE.NRails)).
* **Map data**: © [Overture Maps Foundation](https://overturemaps.org/) and © [OpenStreetMap contributors](https://www.openstreetmap.org/copyright),
  [ODbL](https://opendatacommons.org/licenses/odbl/) (rail lines, roads, buildings). Elevation, imagery and the
  other sources as listed by BeamNG.Earth (shown in the game's corner).
* **Rail mods**: by their authors, under their own licences, not included.
* BeamNG.drive is a trademark of BeamNG GmbH; this project is not affiliated with BeamNG GmbH.

Version: see [`NRAILS_VERSION`](../NRAILS_VERSION) (NRails) and [`VERSION`](../VERSION) (the BeamNG.Earth base).
Changes: [RELEASE_NOTES_NRAILS.md](../RELEASE_NOTES_NRAILS.md).
