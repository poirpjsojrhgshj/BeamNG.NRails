# Road study of BeamNG's official maps (2026-10-11)

How BeamNG's own maps build roads, measured from the level files (read-only, from the game's
`content/levels/*.zip`; scripts: `tools/roadstudy/study.py <levels dir> <out dir> level...` and `study2.py <levels dir> level...`).
Ten levels: West Coast USA, East Coast USA, Italy, Utah, Johnson Valley, Jungle Rock Island,
Small Island, Industrial, Hirochi Raceway and Driver Training. Asked by the user after the first
road cut (2026-10-11), who noted that the driving width looked right but parking lanes were
missing, and asked to look at road variety and at how a road shapes the ground on and near it.
Utah and Johnson Valley are based on real places.

Method:
- The AI path DecalRoads (`road_invisible`: the centreline and drivable width, 54 to 1,299 per map)
  are walked every 10 m.
- At each point the terrain is sampled at right angles out to ±30 m (every 0.5 m): height relative
  to the centreline, and the terrain material from the `.ter` layer map (format v9: u8 version,
  u32 size, u16 heights, u8 layer map, material names). Materials are classed by name as paved
  (asphalt / concrete / road), dirt (gravel / dirt / sand / mud) or other.
- This gave 50,000 cross-sections in total.

## 1. What a road is in an official map
- **No mesh roads at all.** No level has a MeshRoad or a ProceduralMesh road. A road is:
  1. **the terrain itself**: the surface painted into the terrain layer map (`Asphalt`,
     `groundmodel_asphalt1`, `asphalt_prepped`, `Concrete`; `gravel`, `dirt_loose`, ...), and the
     ground shaped under it;
  2. **an AI path** (`road_invisible` DecalRoad: navgraph centreline and drivable width);
  3. **decal layers** on top. Per map (most used, median width):
     - **WCUSA:** `line_white` (3,141, 0.2 m), `line_yellow` (1,478), `track_rubber` (828, 5 m),
       `road_crack`, `road_rubber_double`, `road_edge` (1 m), `road_asphalt_2lane` (385, 8 m),
       `gutter1` (0.5 m), `bank_erosion`.
     - **ECA:** edge blends `ECA_road_edge_dirt` / `_grass` / `_dirt_grass` (2 m, ~750 together),
       `m_asphalt_damaged_*`, `line_white_damage_01`, `Dirt_road_variation_03`.
     - **Italy:** `italy_road_markings_line_thin` (1,333, 0.15 m),
       `italy_road_edge_damage_wide_grassy` (938, 2 m), `italy_road_cracks` (706, 4 m),
       `italy_asphalt_overlay_light` (7 m), `italy_road_edge_concrete` (0.4 m), zebra crossings.
     - **Utah:** `dirt_road_flows` (2.5 m), `AsphaltRoad_damage_large_cracks_decal`,
       `dirt_road_gravels`, tyre tracks, `utah_asphalt_road_dirt_edge` (Industrial,
       Small Island: 1.5-3.5 m).
     - **Johnson Valley:** `m_dirt_tiretracks` (1,127, 3.5 m), `m_dirt_road_flows`,
       `m_dirt_variation_01..04` (8 m), `m_bank_erosion` (7 m), `m_dirt_road`.
     - **Jungle Rock Island:** `dirt_road_flows`, `grassy_edge_01` (2 m), `mud_furrows`, cracks,
       `AsphaltRoad_variation_01/02` (6 m), `line_white_damage_01`.
  - So the asphalt or dirt *colour* comes from the terrain material, and the decals add markings,
    **edge blends** (asphalt to grass / dirt, ~2 m wide, on both edges), wear, cracks, tyre tracks
    and erosion. Dirt roads are mostly overlays (flows, gravels, tyre tracks) on a dirt terrain
    layer.

## 2. Surface width against the drivable (AI) width
Median width of the contiguous paved / dirt surface across the centreline, by AI width bucket:

| Map | AI 4 m | AI 6 m | AI 8 m | AI 10-12 m | AI 14-16 m |
|---|---|---|---|---|---|
| Italy | 6.0 | 8.5 | 10.5 | 16 | - |
| ECA | 6.0 (dirt) | 8.0 | 9.5 | 19 | - |
| Jungle Rock Island | 5.5 | 8.0 | 21 | - | - |
| Utah | 11 | (dirt) | 10.0 | - | - |
| Small Island | 7.0 | 6.5 | - | - | - |
| WCUSA (city) | 30 | 27 | 21.5 (p25 12.5) | 21.5-37 | 24.5-26 |

- **Rural paved roads: surface ≈ AI width + 2-2.5 m** (paved shoulders / edge strip ~1 m each side).
- **City streets (WCUSA): the paved area is far wider than the driving width.** It includes parking
  lanes, and parking lots and plazas that join the street (the p25 of 12.5 m for 8 m AI width is
  the plain-street case: **~2.3 m of parking on each side**). This is the user's parking-lane
  observation, in the official map.
- Half-widths at the edge search (study2): paved 3-5 m rural (Italy 3.5, Jungle 3.5, Utah 4.0,
  ECA 4.5, JV 5.0), WCUSA 6.5 m (city). Dirt roads 2-4 m half-width (JV 3.0, Jungle 2.0, ECA 3.5),
  Utah 6.5 m (wide desert dirt roads).

## 3. The ground on and near the road
- **Across the road it is flat.** |height - centre| at 2 m: median 0.00-0.08 m (crown /
  cross-slope ~1-3 %). At the surface edge: median -0.08 to +0.04 m (the edge is level with the
  centre).
- **Just outside the edge**: the first 1-2 m are still near road level (median within ±0.12 m).
  Then the ground goes back to the natural terrain: |dz| 4 m beyond the edge has a median of
  0.11-0.71 m and a p90 of 0.4-3.6 m (Italy's dirt roads on hillsides: 1.5 / 5.6 m). Those are cuts
  and fills (signed medians near 0: as many up as down).
- **Ditches**: the ground drops more than 0.25 m within 4 m of the edge in **20-44 %** of edge
  samples on paved roads (Italy 44 %, Utah 40 %, WCUSA 33 %, Small Island 32 %, ECA 25 %, Jungle
  22 %, JV 20 %), and 9-39 % on dirt roads.
- **Along the road it is smooth**: |second difference of the centreline height| per 10 m has a
  median of 0.02-0.13 m on paved-road maps (WCUSA 0.024, Italy 0.056, Utah 0.091, ECA 0.112, Jungle
  0.128). It is rougher on dirt-road maps (Johnson Valley 0.26, Small Island 0.23, p90 1.5 m).
  Grades: median 1.7-4.9 %, p95 12-17 % on paved maps, 26-37 % on the off-road maps.

## 4. Ours, measured the same way (first cut, Overture centrelines on our DEM at zoom 15)
- Along the road: median 0.052 / 0.063 m, p90 0.19 / 0.21 m (Fells Point / Monument Valley). That
  is as smooth as the official paved maps, because the US DEM is LiDAR-based.
- Across: |dz| at 2 m median 0.035 / 0.045 m, p90 0.10 / 0.20 m; at 4 m median 0.074 / 0.082 m,
  p90 0.23 / 0.39 m. The median is fine, but the tail is roads tilting with the hillside. Outside
  LiDAR coverage (30 m DEMs) it will be far worse.
- Not done yet: comparing Utah's and Johnson Valley's road layouts with the real places' Overture
  roads. The levels carry no georeference, so it needs a manual alignment first.

## 5. What this means for BeamNG.Earth
1. **Width = carriageway, not driving width.**
   - Paved roads get edge strips (~1 m each side, rural).
   - Streets in built-up areas (WorldCover class 50 at the road) get parking lanes (~2.3 m each
     side) on residential / tertiary / secondary / unclassified streets.
   - Overture width rules, where present, stay as the carriageway width.
2. **Layers like the official maps:**
   - The surface stays painted into the physics block (done), plus the base decal (done, standing
     in for the official maps' painted terrain colour, since our visual ground is imagery).
   - New: **edge blend decals** (~2 m, both edges: asphalt to dirt / grass, chosen from the land
     cover; the ECA / Italy / Utah edge materials), **centre and edge lines** (WCUSA `line_yellow`
     / `line_white` by class and country), and wear / cracks by a hash of the road id.
3. **Grade the ground under roads** (server, in the height function shared by the physics block
   and the near mesh tiles, so decals, tyres and visuals agree):
   - Flat across the carriageway, 1.5-2 % crown.
   - The centreline smoothed along the road (to the official maps' 0.02-0.1 m second difference per
     10 m).
   - The edge level with the road, a 1-2 m shoulder, then a cut or fill slope back to the natural
     ground within ~4-8 m.
   - Ditches on rural roads where the road is in a cut (about 1 in 3 edges in the maps).
   - Junctions get one shared surface.
