# Places to test and benchmark

Spots found while driving (mostly by the project owner) that show something worth checking. They are
**benchmarks, never special cases** (docs/ROADMAP.md "Principle: improvements must generalise"):
every fix found here must come from a rule that works everywhere, and is checked here and on
the rest of the list before and after. Teleport with `beamngEarth_core.teleport(lat, lon)`, or from
the settings page's "Places" section: this table is the start of its saved places on a first run
(`places.SEED`, data only, followed by a few well-known drives; the player can edit or delete them).
Every place here (and every photo benchmark) is also in `docs/benchmarks.json` with fixed cameras,
together with a global set and a held-out set; `tools/benchmark.py` shoots and measures them all
(docs/DEVTOOLS.md "Visual benchmark"). Add a new place to both (a test checks the table).

| Place | lat, lon | What it shows | Relevant work |
|---|---|---|---|
| Fells Point, Baltimore MD | 39.2834, -76.5934 | the owner's home area: dense old city, harbour, the Fort McHenry / Harbor tunnels nearby | v1.9 cities (first test city), water, tunnels, street-level tuning |
| Mount Whitney summit | 36.5785, -118.2923 | the default start; 4416 m; 400 km line-of-sight horizon | M1h horizon, gravity (9.78671 m/s² measured in-game), sky |
| Kern River ravine (Sierra Nevada) | 36.506422, -118.402437 | strong cast shadows baked into the aerial imagery | de-shadowing |
| Monument Valley mesas | 36.7818, -110.1393 | mesas and buttes; near the stock Utah map's look; cliff faces stretched by the height field | v1.5 cliff materials, overhangs, biome reference (Utah) |
| Arizona / Utah state line, Monument Valley | 36.998218, -110.102293 | a colour seam between two imagery surveys running for miles | colour matching (seam feather) |
| Kayenta PV Solar Plant, Arizona | 36.7874, -110.2382 | a 55.3 MW solar farm (OSM way 750628044, since 2017-05): rows of panels only blurry in the imagery | energy infrastructure (ROADMAP), imagery resolution / real materials |

## Photo benchmarks (a real photo and the same view in game)

Photos stay where they are published (their licences differ from this repository's); only our own
renders are kept here, with the camera that reproduces the photo.

| View | Real photo | Game render | Camera | Differences seen (2026-10-11) |
|---|---|---|---|---|
| Mount Whitney summit, looking south | [A346, Brian W. Schaller, 2011](https://commons.wikimedia.org/wiki/File:A346,_from_summit_of_Mount_Whitney,_California,_USA,_2011.JPG) (CC BY-NC-SA 4.0 / FAL 1.3) | `docs/research/photo_benchmarks/whitney_summit_south_game_2026-10-11.jpg` (local, like every docs/research subfolder) | free camera 12 m south of 36.5785, -118.2923 at 4416.5 m, heading 170, pitch -18, FOV 65, time 0.92 (10:00 local) | layout matches (the wall, the plateau on the right, the lake basins on the left, the crest behind); the wall is satellite pixels stretched into vertical streaks (real: jointed granite blocks, v1.5 cliff materials); the plateau is smooth sand (real: granite slabs and boulders, v1.5 detail + v1.9 rocks); lakes are flat bright green imagery (real: dark blue water, Water); softer light and fewer snow patches than the photo (season, imagery date) |
