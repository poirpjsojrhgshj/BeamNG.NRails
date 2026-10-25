# Racetrack data sources (2026-10-22)

Question: are there track-specific databases or maps for motor racing circuits (Nordschleife, Daytona,
Spa, Monza, Laguna Seca ...) that beat what we get from OSM raceways plus our DEM? We would want
centerlines, per-point left/right width, banking / 3D elevation, pit lanes, kerbs, run-off, surface
types and a worldwide list of tracks.

Short answer: **no open "track database" is better than OSM + lidar DEM**. The dedicated
datasets are small (25-40 F1-style tracks), not georeferenced or coarse, and have unclear licensing.
What we already have does the most important job. **The DEM captures oval banking where Mapterhorn has
lidar at z16-z17** (measured below: Daytona about 29-31 deg, Talladega 32-33 deg, Bristol 23-24 deg, IMS
8.6-9.2 deg, all matching the published figures). At z14 (Zandvoort, Monza) it reads 25-65 % low. At z12
(Interlagos, Bathurst, Hungaroring) it's gone.

## Ranked recommendation

| # | Source | Use it for | Licence | Verdict |
|---|--------|-----------|---------|---------|
| 1 | **OSM `highway=raceway`** (via Layercake highways) | centerlines, pit lanes, surface, oneway, some `width` | ODbL | **Use** (already planned). Note: Layercake drops `sport`, `raceway`, `area:highway`, `banking` (see below) |
| 2 | **Mapterhorn DEM (lidar where available)** | banking + 3D elevation | per-source open licences (already in use) | **Use as the banking source**: measured, accurate at z16-z17 tiles |
| 3 | **OSM `leisure=*` + `sport=motor/karting/motocross` areas** (Layercake *pois* layer keeps `leisure`, `sport`, `wikidata`) | tell car circuits from kart / motocross / rc tracks, venue names, Wikidata join | ODbL | **Use** to classify raceway ways (point-in-polygon) |
| 4 | **Wikidata** (motorsport racing track class and subclasses) | worldwide list (~1,780 items, ~1,320 with coordinates), names, length, opening date | CC0 | **Optional** catalogue / UI list (teleport menu "famous tracks"). Few OSM links |
| 5 | **Wikipedia "Infobox motorsport venue"** `banking` field | per-turn banking numbers for ovals where the DEM is coarse | CC BY-SA 4.0 (single facts; attribute) | **Optional fallback** for banking outside lidar areas (about 200 pages fill the field) |
| 6 | TUMFTM racetrack-database | per-point left/right width for 25 tracks | LGPL-3.0 as published, but centerlines are OSM-derived (so ODbL applies too) | **Don't ship**. Not georeferenced and only 25 tracks. Possibly a width sanity check |
| 7 | bacinger/f1-circuits | list of 40 F1 circuits with length/opened/altitude | MIT (geometry provenance: a third-party Google My Maps layer) | **Don't use the geometry** (about 45 m vertex spacing, unclear origin). Metadata maybe |
| x | RACECAR dataset (IAC), sim tracks (iRacing, AC, rFactor), lap-timer DBs (AiM, RaceChrono, Harry's), F1 live-timing / FastF1 positions, LapMeta | - | CC BY-NC / proprietary | **Not usable** in a free mod |

## 1. OpenStreetMap track tagging (what exists, how complete)

Worldwide counts (taginfo, data until 2026-10-20):

| Tag | Count | Notes |
|-----|-------|-------|
| `highway=raceway` | 45,826 ways, 335 rel, 135 nodes | combos: `sport=motor` 19,405, `sport=motocross` 9,099, `sport=karting` 8,227; `surface` on 16,154; `width` on only 1,224 |
| `leisure=track` | 120k ways, 43.6k rel | mostly athletics / horse. `sport=motor` overall 22k ways |
| `area:highway=raceway` | 137 ways + 80 rel (216 objects at about 100 venues) | road-surface polygons. Clustered: Korea (36.9,127.6) 29, Pembrey UK 16, Mexico City 6, Assen/Zandvoort area, Lausitzring, Sepang, Abu Dhabi, Bahrain, Qatar ... |
| `type=circuit` relation | 221 | one relation per **layout** (e.g. Daytona: Oval / Road Course / Moto / Kart; IMS 2026 oval + RC + Pitlane; Watkins Glen long/short). 54 have `wikidata`, 11 `length` |
| `raceway=*` | 1,012 | `start-finish` 346, `start` 148, `finish` 92, **`kerb` 72 ways (only 4 venues: Sachsenring, Lausitzring, Pembrey, one in Finland)**, `gravel trap` 50, `pitlane` 47 + `pit_lane` 28, `runoff_area` 20, `grid` 10 |
| `banking=*` | 19 objects | **only IMS** turns 1-4 (`9° 12'`). The rest are misuse (bank buildings) |
| `incline:across` | 11,900 | sidewalk/wheelchair use. **0 on raceways** (global query) |
| `barrier=kerb` | 3.1M | street kerbs. Inside circuits almost none (Daytona 3, Spa 2, Monza 1) |

Spot checks around big tracks (Overpass, `highway=raceway` keys):

- **Daytona**: 26 raceway ways (oval, road course, pit lane, kart, flat track), 5 `type=circuit` layouts. Keys: sport, oneway, lit, surface, some TIGER leftovers, `embankment`. No width, no banking.
- **Talladega / Bristol**: 6 ways each, centerline only (oneway, sport, surface). Bristol: no surface.
- **IMS**: 42 ways, turn ways tagged `banking=9° 12'`, plus 3 layout relations (2026 oval, RC, pitlane).
- **Spa**: 35 ways + circuit relation (wikidata Q172851), surface on 30. Lots of walls/fences/hedges mapped.
- **Monza**: 50 ways, historic banking ring present (`historic`, `bridge`, `layer`), circuit relation Q171417.
- **Laguna Seca**: 9 ways (name, oneway, surface), 70 `barrier=wall`.

Conclusion: OSM gives **good centerlines and pit lanes for every notable track worldwide**, decent
`surface`, layout relations for about 200 circuits. It does **not** reliably give width (2.7 % of ways),
banking (one venue), kerbs (4 venues) or run-off. The wiki itself calls `area:highway=raceway`
"controversial/proposed". Treat width/kerb/run-off as procedural (rules by `sport` + ...).

### Layercake caveat (important for the planned import)

`osmus/layercake` `sql/highways.sql` keeps a fixed column set: highway, service, name, ref, bridge,
tunnel, layer, lanes, lit, surface, smoothness, tracktype, **width**, access, oneway, maxspeed, ...
It does **not** keep `sport`, `raceway`, `banking`, `incline:across`, `area:highway`, `wikidata`.
Objects without a `highway` key (`area:highway=raceway` polygons, `raceway=start-finish` nodes,
`type=circuit` relations) are not in the layer at all. `highway=raceway` + `area=yes` polygons are kept.
So from Layercake alone we can't tell a kart track or motocross loop from a car circuit, except by
`surface` (dirt/ground/unpaved, about 6.4k of 16k surfaced ways). The **pois** layer (`sql/pois.sql`) keeps
`leisure`, `sport` and `wikidata` for nodes/areas. A point-in-polygon join of raceway ways against
`leisure=sports_centre|stadium|track` + `sport=*` areas recovers the class for most venues.
(Repo: https://github.com/osmus/layercake, docs: https://layercake.openstreetmap.us/)

Overture: `base/land_use` has a `track` class (from OSM `leisure=track`, so athletics too) and
`stadium`. There is no raceway line class and no place category for race tracks in the current schema
(checked OvertureMaps/schema).

## 2. Banking from the DEM: measured

Method: for every vertex of each OSM `highway=raceway` way, take a cross-section perpendicular to the
way (+/-6 m, 0.5 m steps). Sample the Mapterhorn terrarium tile at the deepest zoom it serves there,
bilinear. Fit a line and report the slope angle. "Turn" means curvature > 1.5 rad/km. Script:
`scratchpad/scripts/bank.py` (not in repo).

| Track (published banking) | DEM zoom (px) | Measured, turn median / p90 |
|---|---|---|
| Daytona, turns 31 deg, tri-oval 18 deg | z17 (~0.5 m) | 28.7 / 29.6 (one way), 28.2 / 31.0 ("Speedway" way). Its straights read 6.7 = tri-oval/back-straight mix |
| Talladega, 33 deg | z16 (~1 m) | 33.1 / 33.7 and 31.9 / 32.5 |
| Bristol, 24-28 deg (variable) | z16 | 23.1 / 24.3 (+/-6 m around the centerline = lower/middle groove) |
| IMS, 9 deg 12' (9.2) | z16 | turns 1-4: 8.6, 8.6, 9.2, 8.9 |
| Daytona / IMS infield road course (flat) | z16-17 | 0.2-1.4 |

So **where Mapterhorn serves z16+ (national lidar), the terrain already holds real banking to
within about 1-3 deg**. The mod has to *preserve* it, not add it. Road grading / flattening must not
level the road cross-section on raceways: grade along the centerline only, and keep the DEM's
cross-slope.

Mapterhorn deepest zoom per track (HTTP probe, 512 px tiles: z17 ~0.6 m, z16 ~1.2 m, z14 ~4.8 m,
z12 ~19 m at the equator, times cos(lat)):

- z17: Daytona, COTA, Spa, Le Mans
- z16: Talladega, Bristol, Texas MS, Laguna Seca, Nordschleife, Lausitzring, Motegi, Suzuka,
  Silverstone, Red Bull Ring, Catalunya, Rockingham
- z14: Monza (incl. the old banking), Zandvoort
- z12 only (Copernicus-class, banking lost): Interlagos, Bathurst, Hungaroring

At **z14 (~3 m px) the banking is there but flattened**:

| Track (published) | z14 measured turn median / p90 |
|---|---|
| Zandvoort Hugenholtzbocht (about 19 deg) | 9.5 / 10.0 |
| Zandvoort Arie Luyendykbocht (about 18 deg) | 14.2 / 15.2 |
| Monza Sopraelevata (old oval, up to about 80 % = 38 deg at the top) | 11.9 / 14.3 (Nord, one way) |

That is 25-65 % low. A 12-15 m wide banked lane is only 4-5 DEM pixels, and bilinear sampling smooths the
edges. Monza's banking is also an elevated concrete structure.

Where the DEM is coarse (z14 underestimates, z12 loses it), banking has to come from a number, e.g. the Wikipedia infobox
(`banking = Turns: 31°<br />Tri-oval: 18°...`) or an OSM `banking` tag. Then it gets applied as a
cross-slope. Few ovals sit outside lidar areas: the US, Japan, Germany and the UK are covered.

## 3. TUMFTM racetrack-database

- URL: https://github.com/TUMFTM/racetrack-database. Licence file **LGPL-3.0**. Last commit
  2021-09-18 (unmaintained).
- 25 tracks: Austin, BrandsHatch, Budapest, Catalunya, Hockenheim, IMS, Melbourne, MexicoCity,
  Montreal, Monza, MoscowRaceway, Norisring, Nuerburgring (GP circuit, 5.1 km, not Nordschleife),
  Oschersleben, Sakhir, SaoPaulo, Sepang, Shanghai, Silverstone, Sochi, Spa, Spielberg, Suzuka,
  YasMarina, Zandvoort.
- Format: `tracks/<Name>.csv`: `# x_m,y_m,w_tr_right_m,w_tr_left_m`, 5 m steps. `racelines/<Name>.csv`:
  `x_m,y_m` (min-curvature line).
- **Not georeferenced**: local metres starting at (0,0), no lat/lon origin or rotation given. Using it
  means fitting each track onto the OSM way (ICP).
- Provenance: centerlines are smoothed **OSM** GPS points, so they are ODbL derivative data whatever the
  LGPL file says. Widths come from "satellite images" with an image-processing step. The imagery source
  isn't named. README warns accuracy "varies greatly" and centerlines are no longer centred.
- Width sanity: Spa total width 7.9-16.4 m (median 9.2 m, low for Spa). IMS constant 15.3 m (hand-set,
  no turn widening). Nürburgring GP 7.6-21.4 m.
- No elevation, no banking, no kerbs/pits.
- Verdict: too few tracks, needs registration, mixed licence. At most a reference to calibrate a
  procedural "racetrack width" rule (typical 10-15 m).

## 4. bacinger/f1-circuits

- URL: https://github.com/bacinger/f1-circuits. Licence **MIT** (c) 2019-2025 Tomislav Bacinger.
  Active (last commit 2026-10-16, includes Madrid 2026).
- 40 circuits in `f1-circuits.geojson` (LineString per circuit) and `circuits/<cc-year>.geojson`, plus
  `f1-locations.geojson/json` points.
- Properties: `id` (e.g. `be-1925`), `Location`, `Name`, `opened`, `firstgp`, `length` (m),
  `altitude` (one number, start/finish, from a formula1.com article, official sites or the *city's*
  altitude).
- Geometry: 2D, coarse (Spa 153 vertices for 7.0 km = about 45 m spacing). Initial data came from a
  third-party Google My Maps layer, so it was likely traced over Google imagery. The provenance doesn't
  match the MIT label.
- Verdict: worse than OSM geometry. The metadata (length/opened) can be had from Wikidata (CC0)
  instead.

## 5. Wikidata

- Licence **CC0**. Live SPARQL (https://query.wikidata.org/sparql) or a dump.
- Items that are an instance of a subclass of *motorsport racing track* (Q2338524): **1,782**. By class:
  motorsport racing track 1,277, kart circuit 189, street circuit 177, motocross 45+22, dragstrip 36,
  rallycross 31. (The parent *race track* Q1777138 also holds 867 horse venues, dog tracks and so on.
  Filter on Q2338524.)
- Property coverage on those 1,782: coordinates (P625) 1,324; length (P2043) 186; inception
  (P571) 194; OSM way ID (P10689) 136; OSM relation ID (P402) 34; elevation (P2044) 8; closure
  (P3999) 38. No banking or turns property in use.
- Join: the better direction is OSM to Wikidata (`wikidata=*` on circuit relations: 54 of 221, on some
  raceway ways and on venue areas in the Layercake pois layer).
- Verdict: good, free **catalogue** (name, coordinates, type, length) for a "go to a track" list.
  It adds no geometry.

## 6. Wikipedia infobox banking

- `Template:Infobox motorsport venue` is used on 1,165 enwiki articles. About 197 have a non-empty
  `banking` field (CirrusSearch regex, rough), about 51 with a degree sign. Values are free text per
  layout (`banking`, `banking2` ...), e.g. Daytona `Turns: 31°<br />Tri-oval: 18°<br />Back
  straightaway: 3°`.
- Text licence CC BY-SA 4.0. Single numeric facts are low-risk with attribution. Parsing is messy.
  Only worth it as a fallback for ovals outside lidar coverage (few exist).

## 7. Other candidates checked (not usable or not useful)

- **RACECAR dataset** (Indy Autonomous Challenge, IMS/LVMS/Monza lidar + GNSS): **CC BY-NC 4.0**,
  so not usable (https://registry.opendata.aws/racecar-dataset/). IAC teams' HD track maps are not
  published.
- **Sim tracks** (iRacing, Assetto Corsa, rFactor 2, ACC: laser-scanned with exact banking/kerbs):
  proprietary, all rights reserved. Community AC/rF2 mods are mostly unlicensed conversions of those.
  Not open data, and must not be used.
- **F1 live timing / FastF1** car X/Y/Z positions: data belongs to Formula One; no open licence.
- **Lap-timer track databases** (AiM about 3,000 tracks, RaceChrono, Harry's LapTimer): closed.
- **LapMeta**, MAPOG/igismap racetrack downloads: commercial or registration-walled.
- **Málaga open data** "circuitos motor" GeoJSON: CC BY 4.0, but one city's local venues.
- Wikimedia Commons circuit SVGs: CC BY-SA, schematic, not georeferenced.
- No open dataset with banking or elevation for NASCAR/IndyCar ovals was found. The DEM (section 2)
  is the answer.

## What to build (suggested)

1. Import `highway=raceway` from Layercake highways (planned). Join Layercake **pois** areas
   (`leisure` + `sport` + `wikidata`) to classify each raceway: car circuit / kart / motocross / other.
2. Raceway cross-section: **don't flatten across the track**. Fit the road surface to the DEM's own
   cross-slope (lidar areas show the real banking). Apply an explicit cross-slope only where the
   DEM is coarse and a banking number exists (OSM `banking`, or a small table from Wikipedia).
3. Width: use OSM `width` when present (2.7 %), else a rule by class (car circuit about 12 m, oval
   about 15-18 m, kart about 8 m, pit lane about 10 m). `area:highway=raceway` polygons (about 100 venues)
   would need the raw OSM / another extract, since Layercake drops them.
4. Optional: a Wikidata (CC0) list of the about 1,300 geocoded motorsport tracks for a "tracks"
   teleport menu.
5. Attribution: OSM (ODbL) already credited. Add Wikidata (CC0, attribution optional) and Wikipedia
   (CC BY-SA) only if those get used.

Downloads used for this study: `/tmp/claude-1000/-home-tecnagamer-Documents-BeamNG-Earth/b02246e0-198a-4d55-8cba-7ac6107ad43e/scratchpad/tracks/` (temporary).
