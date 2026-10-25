# OpenStreetMap vs Overture: what each has, measured (2026-10-22)

The question (the user, 2026-10-22): does OSM have better building data than Overture? And, for all map
data (roads, buildings, the rest), what does each source have and what does each do better?

**Short answer.**
- **Buildings: OSM is not better.** Overture's buildings *are* OSM's buildings wherever OSM has them, and they
  keep OSM's height, levels, roof shape, colours and materials (measured: 0–1 values lost per place). On top of
  that, Overture adds machine-learned footprints where OSM has gaps (Florianópolis +66 %) and Microsoft's
  machine-learned heights (Hays, Kansas: 82 % of buildings have a height in Overture, 6 % in OSM). OSM has
  only two small extras: `roof:levels` (7 % of buildings in Fells Point and Stuttgart) and colour values
  that Overture drops (named or `#`-less colours).
- **Roads: OSM is much richer.** It has lane counts, sidewalks, on-street parking, street lighting,
  turn lanes, cycleways and smoothness. Overture has none of these. Both have the same speed limits, widths,
  surfaces, one-way information and bridge/tunnel/layer data, because Overture takes them from OSM. Overture
  has a few road extras of its own: turn restrictions, destinations, route refs, and a link from each segment
  to its connectors (the road-graph topology).
- **Street furniture, trees, signals: already in Overture.** Overture's `base` theme (infrastructure, land)
  carries OSM's traffic signals, stop signs, crossings, street lamps, trees, tree rows, benches, hydrants,
  bollards, kerbs, fences, walls and hedges. Its counts match OSM's to within a few %. BeamNG.Earth reads
  `infrastructure` but uses only bridges and parking lots from it, and it doesn't read `base/land` (the tree
  points) at all.
- **Places and addresses: Overture is better.** It has 2–5x OSM's POIs (from Meta, Foursquare and
  Microsoft) and official address registers (13x OSM's addresses in Melbourne and Hays). The only thing OSM
  has here that Overture lacks is building entrances.

## Method

- Six boxes of 1 km x 1 km around: Fells Point, Baltimore (39.2834, -76.5934); Stuttgart centre (48.7758,
  9.1829); Melbourne CBD (-37.8136, 144.9631); Florianópolis centre (-27.5954, -48.5480); Hays, Kansas
  (38.8792, -99.3268); Shibuya, Tokyo (35.6595, 139.7005). A feature counts when the centre of its bbox
  lies in the box. Exception: Postpass counts use `ST_PointOnSurface`.
- **Overture** release 2026-09-23.1 (the pinned one). All columns of buildings/building, building_part,
  transportation/segment, connector, base/infrastructure, land, land_use, water, places/place and
  addresses/address were read through the project's own `overture.Reader`: STAC index, range reads, DuckDB.
- **OSM, tag columns:** OSM US Layercake, versions of 2026-10-18 (`buildings`, `highways`, `pois`,
  `addresses`). Only the row groups for each box were range-read, with the same method as
  `server/osmtags.py`.
- **OSM, full tags:** Overpass (overpass-api.de and two mirrors) answered 502/504 all morning, so it was used
  only for Fells Point. For all six boxes the full-tag counts come from Geofabrik's **Postpass** (an SQL API
  over a fresh osm2pgsql import), with the counting done on the server (5 small queries per place). For Fells
  Point, Overpass and Postpass agree (178 vs 184 roads, 156 vs 160 with lanes, 115 vs 118 with sidewalks).
- **Building join check:** each OSM-sourced Overture building was joined to its OSM way or relation by the id
  in `sources[1].record_id` ("w123@4"), and the attributes on both sides were compared.
- The scripts are in the session scratchpad (`osmcmp/`): `ovt_fetch.py`, `lc_fetch.py`, `pp_fetch.py`,
  `cmp.py` and `osm_stats.py`. Nothing in the repo was changed.

## 1. Buildings

| | Fells Point | Stuttgart | Melbourne | Florianópolis | Hays KS | Shibuya |
|---|---|---|---|---|---|---|
| Overture footprints | 2,165 | 1,318 | 879 | **1,505** | 1,157 | 1,617 |
| … of which from OSM | 2,165 | 1,311 | 879 | 908 | 1,154 | 1,593 |
| … ML / other sources | 0 | 7 MS | 0 | **572 Google + 25 MS** | 3 MS | 19 Shi et al. (East Asia) + 5 MS |
| OSM footprints (Layercake) | 2,166 | 1,313 | 881 | 907 | 1,155 | 1,598 |
| Overture height | 3 % | 15 % | 10 % | 1 % | **82 %** | 55 % |
| … of which Microsoft ML height | 3 % | 14 % | 2 % | 0 | 82 % | 0 |
| OSM `height` | 0 % | 1 % | 8 % | 2 % | 0 % | 56 % |
| Overture num_floors / OSM `building:levels` | 11 / 11 % | 14 / 14 % | 29 / 29 % | 31 / 52 %¹ | 6 / 6 % | 57 / 58 % |
| **height or floors**: Overture / OSM | 14 / 11 % | **25 / 14 %** | 34 / 33 % | 31 / 52 %¹ | **84 / 6 %** | 60 / 61 % |
| roof shape: Overture / OSM | 1 / 1 % | 8 / 8 % | 1 / 1 % | 10 / 16 %¹ | 0 / 0 | 0 / 0 |
| `roof:levels` (OSM only; not carried into Overture) | 7 % | 7 % | 0 | 1 % | 2 % | 0 |
| roof / facade colour, material: Overture / OSM | 0 / 0 | roof material 3 / 3 % | ~1 / ~1 % | roof material 6 / 11 %¹ | 0 | colour 2 / 3 %, material 3 / 3 % |
| min_height: Overture / OSM | 0 / 0 | 0 / 0.3 % | 0 / 0.2 % | 0 / 0.2 % | 0 | 0 / 0.5 % |
| class (OSM `building` ≠ yes) | 14 / 14 % | 27 / 28 % | 18 / 18 % | 31 / 51 %¹ | 15 / 15 % | 11 / 12 % |
| name | 4 / 4 % | 9 / 9 % | 24 / 24 % | 20 / 33 %¹ | 1 / 1 % | 28 / 29 % |
| building parts: Overture `building_part` (OSM `building:part` ways, measured in Stuttgart only) | 8 | 123 (OSM 124; with height/levels 110 vs 99, min height 12 vs 17, roof shape 36 vs 30) | 39 | 15 | 0 | 19 |

¹ Florianópolis' Overture percentages are over all 1,505 footprints, 597 of which are ML footprints
with no attributes. Over the OSM-sourced 908 they equal OSM's.

**Join check** (OSM-sourced Overture buildings to Layercake by way/relation id):

| | Fells Point | Stuttgart | Melbourne | Florianópolis | Hays | Shibuya |
|---|---|---|---|---|---|---|
| found in OSM by id | 2,165 / 2,165 | 1,311 / 1,311 | 878 / 879 | 907 / 908 | 1,154 / 1,154 | 1,593 / 1,593 |
| OSM has height/levels but Overture has none | 0 of 230 | 1 of 185 | 0 of 295 | 0 of 470 | 0 of 70 | 1 of 967 |
| OSM roof:shape lost in Overture | 0 | 0 | 0 | 0 | 0 | 0 |
| OSM colour lost in Overture | 2 ("burlywood") | 0 | 5 ("Red Brick", "tan"…) | 0 | 0 | 12 (hex without "#") |
| OSM `roof:levels` lost in Overture | 146 | 85 | 3 | 6 | — | 1 |

Notes:
- Overture's OSM-derived building data is about one month behind OSM, which is not a meaningful difference
  (footprint counts within 0–5 per km²).
- The Microsoft ML heights are noisy. Where the same building also has a floor count, the height per floor
  runs from 1 m to 6 m (Fells Point, 12 buildings), and Stuttgart's median is 2.6 m. In Hays they say what
  matters, though: one-storey houses (median 4.4 m). Treat them as a hint and clamp them to the footprint
  predictor's range, not as truth.
- Layercake's buildings layer has no `building:part`-only features and no `min_height` /
  `building:min_level` column. Overture's `building_part` type does have them.

**Verdict:** keep Overture as the only footprint and attribute source. There is nothing in OSM's buildings
that Overture lacks except `roof:levels` and non-standard colour strings.

## 2. Roads (drivable classes, without service roads)

Overture counts are per segment (OSM ways are split at intersections) and OSM counts are per way, so read
the percentages as coverage, not as one-to-one counts. 98.6 % of Overture segments keep the OSM way id
(`osmtags.py`). TomTom contributed 1–19 segments of class "unknown" per box, nothing else.

| % with … | Fells Point | Stuttgart | Melbourne | Florianópolis | Hays KS | Shibuya |
|---|---|---|---|---|---|---|
| **Both have it (Overture / OSM)** | | | | | | |
| speed limit | 95 / 96 | 98 / 99 | 86 / 85 | 25 / 25 | 0 / 0 | 27 / 22 |
| width | 3 / 2 | 19 / 22 | 9 / 8 | 0 / 0 | 0 / 0 | 1 / 0 |
| surface | 99 / 100 | 99 / 99 | 99 / 100 | 99 / 98 | 48 / 50 | 79 / 78 |
| one-way² (Overture: access denied backward) | 36 / 55 | 76 / 76 | 85 / 87 | 85 / 92 | 17 / 8 | 56 / 63 |
| layer / level | 1 / 1 | 3 / 3 | 1 / 1 | 0 / 0 | 0 / 0 | 3 / 4 |
| name | 99 / 99 | 82 / 86 | 94 / 95 | 93 / 91 | 99 / 98 | 53 / 59 |
| **OSM only** | | | | | | |
| `lanes` | **88** | **71** | **74** | **57** | 0 | **44** |
| `lanes:forward/backward` | 27 | 3 | 1 | 3 | 0 | 1 |
| `turn:lanes*` | 14 | 23 | 2 | 5 | 0 | 4 |
| `width:lanes*` | 2 | 8 | 0 | 0 | 0 | 0 |
| `sidewalk*` (any key) | **65** | **95** | **88** | **96** | 5 | 12 |
| … plain `sidewalk` only (all Layercake has) | 1 | 82 | 10 | 88 | 2 | 7 |
| `cycleway*` | 31 | 61 | 90 | 19 | 0 | 5 |
| `parking:*` (on-street parking lanes) | **86** | **32** | 7 | 0 | 0 | 0 |
| `lit` | 20 | **96** | **77** | 55 | 8 | 37 |
| `smoothness` | 30 | 49 | 4 | 0 | 0 | 4 |
| `placement*` | 7 | 14 | 0 | 0 | 0 | 0 |
| `hgv` | 16 | 1 | 0 | 0 | 0 | 0 |
| **Overture only (as structured data)** | | | | | | |
| turn restrictions (prohibited_transitions) | 6 | 26 | 4 | 6 | 0 | 7 |
| destinations (sign texts) | 0 | 35 | 0 | 3 | 0 | 14 |
| routes (ref / network) | 0 | 18 | 10 | 0 | 0 | 24 |
| access restrictions (incl. one-way) | 46 | 79 | 89 | 87 | 17 | 63 |
| subclass: sidewalk / crosswalk / driveway / parking_aisle / alley segments | yes | yes | yes | yes | yes | yes |
| connector topology, GERS ids, linear ranges ("between") | yes | yes | yes | yes | yes | yes |

² OSM counts any `oneway` tag, including `oneway=no`, so the two numbers measure different things. Overture's
access rules carry the actual one-way direction.

Service roads (driveways, parking aisles, alleys) are thin in both sources: in OSM, surface on 7–75 %,
lanes on 0–17 %, sidewalks on 0–19 %.

`junction=*` came out as 0 % on drivable ways in all six boxes. Roundabouts are rare in 1 km city centres,
so this says nothing about other places.

### Road-related points (OSM nodes) vs Overture infrastructure

Overture *does* have these as points (`base/infrastructure`, class `traffic_signals`, `stop`, `give_way`,
`crossing`, `street_lamp`, `bus_stop`, …), but they are not linked to the segments or connectors. A join
means snapping each point to the nearest connector or segment.

| count in box: Overture / OSM | Fells Point | Stuttgart | Melbourne | Florianópolis | Hays | Shibuya |
|---|---|---|---|---|---|---|
| traffic signals | 32 / 32 | 38 / 37 | 140 / 140 | 50 / 50 | 0 / 0 | 79 / 79 |
| stop + give way | 19 / 22 | 49 / 49 | 0 / 0 | 25 / 25 | 0 / 0 | 42 / 43 |
| crossings (nodes) | 334 / 321 | 118 / 118 | 399 / 402 | 313 / 313 | 260 / 260 | 246 / 254 |
| street lamps | 47 / 47 | 105 / 121 | 5 / 5 | 13 / 13 | 0 / 0 | 8 / 8 |
| bus stops | 25 / 25 | 20 / 20 | 27 / 27 | 26 / 25 | 0 / 0 | 57 / 57 |
| kerbs (nodes) | 445 / 427 | 22 / 13 | 101 / 99 | 228 / 228 | 0 / 0 | 10 / 16 |

## 3. Everything else

| count in box: Overture / OSM | Fells Point | Stuttgart | Melbourne | Florianópolis | Hays | Shibuya |
|---|---|---|---|---|---|---|
| trees (points) | 54 / 54 | **728 / 729** | **501 / 501** | **368 / 368** | 22 / 22 | 29 / 28 |
| tree rows | 0 / 0 | 4 / 4 | 0 / 0 | 9 / 7 | 1 / 1 | 6 / 7 |
| benches | 45 / 43 | 223 / 215 | 116 / 123 | 13 / 9 | 2 / 2 | 18 / 19 |
| waste baskets | 12 / 12 | 136 / 137 | 88 / 87 | 7 / 7 | 2 / 2 | 2 / 2 |
| fire hydrants | 10 / 10 | 24 / 24 | 202 / 225 | 1 / 1 | 0 / 0 | 20 / 20 |
| bollards | 29 / 25 | 156 / 193 | 24 / 23 | 2 / 2 | 0 / 0 | 5 / 4 |
| fences / walls / hedges / retaining walls (ways) | 17 / 18 | 146 / 147 | 36 / 35 | 0 / 0 | 88 / 87 | 7 / 7 |
| bicycle parking | 48 / 48 | 131 / 100 | 123 / 163 | 9 / 8 | 0 / 0 | 17 / 14 |
| power lines / poles | 0 / 0 | 0 / 0 | 0 / 2 | 0 / 0 | 0 / 0 | 0 / 0 |
| building entrances (OSM `entrance`) | — / 27 | — / 259 | — / 153 | — / 47 | — / 11 | — / 34 |
| `area:highway` (carriageway outlines) | — / 0 | — / 66 | — / 5 | — / 0 | — / 0 | — / 1 |
| places / POIs (Overture all; ≥ 0.7 confidence) / OSM POIs | 919; 740 / 497 | 3,143; 1,677 / 1,788 | 10,253; 6,667 / 2,502 | 4,684; 2,067 / 732 | 43; 36 / 32 | 8,414; 6,079 / 1,977 |
| addresses | **3,511** (NAD) / 2,384 | 886 (BW state) / 1,357 | **26,552** (AU national) / 2,013 | **2,316** (SC state) / 639 | **853** (NAD) / 66 | 213 (Tokyo) / 506 |

- Land use, water and land: Overture's `base` theme is OSM's (plus Daylight coastlines, ESA WorldCover land
  cover, and bathymetry), so the polygons are the same.
- The places sources are Meta (most of them), Foursquare, Microsoft, BrightQuery (USA/Germany), AllThePlaces
  and others. Points from these sources are often less precisely placed than OSM's, but there are many more
  of them.

## 4. Who does what better

**Overture is better at:**
- Building footprint completeness where OSM is thin: Google/Microsoft/Esri ML footprints in the Global South,
  the Shi et al. dataset in East Asia, Spain's BTN.
- Heights where OSM has none: Microsoft ML heights, US-wide.
- One schema, typed values: units are converted, colours normalised, `num_floors` is an integer.
- Road topology (connectors), turn restrictions, destinations and routes as structured data, and
  linear-referenced ("between") attributes on a segment.
- Places (2–5x the POIs) and authoritative addresses.
- Stable GERS ids (with bridge files between releases) and immutable monthly releases.

**OSM is better at:**
- Lane-level road detail: lanes, turn lanes, lanes per direction, widths per lane, placement.
- The street cross-section: sidewalks, cycleways, on-street parking, kerbs as tags, `area:highway`.
- Lighting (`lit`) and `smoothness`.
- Building entrances, `roof:levels`, and free-form colour values.
- Freshness: Layercake is rebuilt weekly, Postpass is minutes old, Overture is monthly.

**Both have:** traffic signals, stop signs, crossings, lamps, trees, benches, hydrants, bollards, fences and
walls, land use, water, speed limits, surfaces, one-way, bridges, tunnels and layers. Overture's values for
all of these come from OSM, so Overture is enough.

## 5. Practical aspects

| Source | Coverage | Updates | Access | Size | Licence |
|---|---|---|---|---|---|
| Overture (in use) | global | monthly; **only the last ~2 releases (60 days) stay online.** Current is 2026-10-21.0, and the pinned 2026-09-23.1 will likely go when 2026-11-18.0 is out | STAC per-file index plus GeoParquet range reads (as `overture.py` does). A 1 km box costs 1–6 s and a few MB per theme | ~1,000 files per release | buildings / transportation / base: ODbL; buildings partly CC BY (Google, Esri, Shi et al., BTN); places: CDLA-Permissive-2.0 / Apache-2.0 / CC0; addresses: permissive, per source |
| OSM US Layercake (in use for highways) | **global** (planet), despite "US" in the name | about weekly (all files Last-Modified 2026-10-18) | one GeoParquet file per layer, spatially clustered: **a 1 km box = 1 row group, 1.6–4 MB of non-geometry columns, 2–7 s cold.** Footers: buildings 15.6 MB, highways 9.3 MB, POIs 4.9 MB, addresses 4.5 MB (read once per version) | buildings 46 GB, highways 29 GB, POIs 4.7 GB, addresses 5.3 GB; also parks, waterways, wetlands, boundaries, settlements | ODbL |
| Layercake gaps | — | — | **only the tag columns it chose:** highways have `sidewalk` but not `sidewalk:both/left/right`, and lack `parking:*`, `turn:lanes`, `lanes:forward/backward`, `cycleway:both`, `placement`, `width:lanes`, `junction`. Buildings have no `building:part` and no `min_height`. No layer for trees, street furniture, barriers or power | — | — |
| Open Planet Data planet GeoParquet | global | daily | one 204 GB file with **all tags as a MAP column** (from ohsome-planet). **Poorly clustered:** a 1 km box matches 96–538 of its 12,333 row groups by statistics, and the bbox columns alone are ~2.5 MB per row group. Not usable for runtime range reads; usable offline to build an own extract | 204 GB | ODbL |
| Geofabrik PBF extracts (+ osmium / duckdb-osmium) | per region | daily | whole-region downloads (tens to hundreds of MB per US state or sub-region, GBs per large country) | — | ODbL |
| Postpass (Geofabrik) | global | minutes | SQL API with aggregates on the server. Great for research and offline checks. **A public service: not for app runtime**, the same reasoning as netfetch's Overpass deny row | — | ODbL |
| Overpass | global | minutes | down (502/504) on all three endpoints during this run; already denied at runtime in `netfetch.POLICIES` | — | ODbL |

On licences, adding OSM data directly changes nothing: the Overture themes already used are ODbL with
"© OpenStreetMap contributors", and the local cell cache is the same kind of derived database. CREDITS.md
already has a Layercake row (osmtags). A new Layercake layer or a self-built extract would need only its
"Used for" text widened.

## 6. Recommendations (ranked by payoff)

1. **Roads: get the full street cross-section from OSM, joined by way id (as osmtags does).**
   - **Quick fix now:** `osmtags.py` reads Layercake's `sidewalk` column only. Most sidewalk mapping is
     `sidewalk:both/left/right`, which Layercake drops: Fells Point is 1 % through Layercake against 65 %
     in OSM, Melbourne 10 % against 88 %. Until that is fixed, treat "no sidewalk tag" as unknown, never as
     "no sidewalk".
   - **The real gap:** on-street parking (`parking:*`, 86 % in Fells Point, 32 % in Stuttgart; it would
     drive the parked-cars feature street by street), `turn:lanes` (lane arrows and markings),
     `lanes:forward/backward` and `placement` (lane geometry), plus `cycleway:both`. Layercake has none of
     these.
   - **Options, cheapest first:**
     - (a) Propose these columns upstream to Layercake (CC0 code, github.com/osmus/layercake; a "highways"
       column list change).
     - (b) Build our own highways extract offline from the Open Planet Data planet parquet (tags map) or from
       Geofabrik PBFs: Hilbert-sorted, one row per way with the ~20 keys we use, hosted like the other static
       assets. Without geometry (the join is by id) this would be a fraction of Layercake's 29 GB highways file, read
       in ranges the way osmtags does.
     - (c) Not Postpass or Overpass at runtime.
   - **Join:** the OSM way id from Overture `sources[].record_id` (98.6 % of segments), exactly as today.
2. **Street furniture and trees: no new source needed, read what Overture already has.**
   - Add Overture `base/land` (class `tree`, `tree_row`; points and lines) as a layer. It carries OSM's
     street trees: 728 per km² in Stuttgart, 501 in Melbourne, 368 in Florianópolis. Use them as exact tree
     positions on top of the canopy-height placement.
   - Use the `infrastructure` classes already in the cell: `traffic_signals` / `stop` / `give_way` (signal
     heads and signs at the nearest connector), `crossing` (zebra markings), `street_lamp`, `bench`,
     `fire_hydrant`, `bollard`, `bus_stop`, `waste_basket`, and `fence` / `wall` / `hedge` /
     `retaining_wall` lines. Counts equal OSM's within a few %.
   - **Join:** spatial. Snap points to the nearest connector or segment within a few metres; a signal or
     stop point that sits *on* a connector is that intersection's control.
3. **Buildings: stay with Overture; optionally take two OSM fields by id.**
   - Overture already has every OSM height, level, roof shape, colour and material (measured), plus ML
     footprints and ML heights.
   - **Small optional add:** `roof:levels` (7 % of Fells Point's row houses and Stuttgart's buildings:
     mansard and attic storeys) and colour strings Overture rejected (named colours, `#`-less hex). These
     come from Layercake buildings by OSM way/relation id (`sources[1].record_id`), at ~2 MB per km² plus a
     15.6 MB footer once. Low payoff; do it only when roofs are worked on.
   - Treat Microsoft ML heights (the `height_src` column already loaded) as a clamped hint.
4. **Places / addresses: Overture.**
   - If shop signs or shopfront ground floors are wanted, use Overture places with confidence ≥ 0.7 inside a
     footprint.
   - Overture addresses (official registers: NAD, G-NAF, state registers) give house numbers.
   - OSM's only extra here is `entrance` nodes (11–259 per km²), useful for doors; low priority.
5. **Release hygiene.** Overture keeps only about two releases online. The pinned 2026-09-23.1 should be
   bumped (to 2026-10-21.0) before 2026-11-18, or cells not yet cached will hit `ReleaseGone`. The current
   schema is v2.0.0; check `overture.LAYERS` against it when bumping.
