# BeamNG.NRails — 1.0.1-beta

**Real-world railways you can drive, on the whole Earth, in BeamNG.drive.**

BeamNG.NRails is a fork of [BeamNG.Earth](https://github.com/TecnaGamer/BeamNG.Earth)
by TecnaGamer, the 1:1 streamed Earth for BeamNG.drive. It keeps everything BeamNG.Earth builds (terrain, roads,
buildings, trees, sea, airports) and adds the **real rail network** (Overture Maps / OpenStreetMap) as **physically
drivable track** for the community's rail mods: drive a locomotive from one real station to another, through the
real tunnels, over the real viaducts, across the real level crossings.

> **Beta.** This is the first public version. Main lines in the open are drivable from end to end; big stations,
> yards, roads near the tracks and some tunnel mouths still have flaws (see *Known limits*). Reports are welcome
> (*Issues* tab).

---

## Contents

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
| **Turnouts** | each route through a turnout has its own collision, only the set route is solid: the train follows the route you chose |
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
| **Ctrl+Shift+I** | the list of NRails' keys on / off (also the *Keys* button) |
| **Ctrl+Shift+U** | the BeamNG.Earth window: *Teleport*, **Snap to rail**, **Reload area**, *Keys* |
| **Ctrl+Shift+T** | **Snap to rail**: your vehicle on the nearest track (within 40 m), facing the way it faced |
| **Ctrl+Shift+G** | **Reload area**: asks the server for the whole area again (roads, rails, buildings that did not come) |
| **Ctrl+Shift+← / ↑ / →** | the **next turnout** ahead of your train (up to 600 m): left / straight / right |

Turnouts: one you take from a branch sets itself for you; one where the line divides ahead takes your choice,
otherwise its straightest route. Keys can be changed in *Options → Controls → Bindings → Gameplay*
(*BeamNG.NRails: …*). The rest of BeamNG.Earth's settings: pause menu → *Mods* → *BeamNG.Earth*.

## Settings

Hub → **Rails** tab: rails on / off, rail profile, trams, level crossings, catenary, cant, maximum grade (‰), extra
rail vehicles. Hub → **Cache**: folder, size cap, clean-up of temporary files (do one after an update). Hub →
**Outils** (Tools): switch back to the original BeamNG.Earth, environment check.

## Known limits

* Big stations and yards: tracks mapped very close together or meeting at odd heights can give small steps.
* Turnouts are simplified: no moving blades, no frog geometry.
* Roads near the railway: a road passing under a rail bridge can get lumps of terrain; some motorway junctions
  are rough (BeamNG.Earth's road grading plus the railway's own).
* Terrain under the track can come back after a teleport in some places (*Reload area* helps).
* Some tunnel mouths show untextured faces or terrain over twin tubes.
* No AI trains, no signals, no station buildings of our own; subway lines are left out; trams have no collision.
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
