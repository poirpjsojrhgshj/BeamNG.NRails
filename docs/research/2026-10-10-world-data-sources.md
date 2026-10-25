# World data sources and generation methods: roads, buildings, trees, land cover, ground physics

Date: 2026-10-10. Scope: free/open data and generation methods to fill the streamed 1:1 Earth with
roads, buildings, trees, land cover and per-surface physics. Worldwide, with a US focus.

Tags used below:
- **[M]**: measured from this machine today. Scripts are in
  `scratchpad/research/scripts/{rasters,overture,overture2,overture3,overture4,mvt}.py`, run in a scratch venv.
- **[V-code]**: I read the game or upstream code myself (path:line).
- **[V-doc]**: official documentation or a bucket README.
- **[I]**: inference or recommendation, not verified.

The running game and its MCP server were not contacted.

---

## 0. TL;DR

1. **Vector data: use Overture GeoParquet, filtered by file through the STAC index.**
   - A 33 x 27 km bbox (0.3° x 0.3°) around Bakersfield loads in about 2.5 s cold and 0.3 s warm:
     223,184 buildings, 150,473 of them with a height, and 49,914 road segments. [M]
   - Querying the whole release glob is slow: 35 s for a 2.4 km bbox, because DuckDB has to read
     the footers of all 512 files. [M]
   - No API key is needed.
   - Licence is ODbL for buildings and transportation (attribution "© OpenStreetMap contributors,
     Overture Maps Foundation").
2. **Vector-tile services are a fallback, not the main source.**
   - OpenFreeMap: keyless, no stated limits, OpenMapTiles schema, z14.
   - Protomaps: daily 138.8 GB planet `.pmtiles`, range-readable; extract per region rather than
     hotlink.
   - Both lack lanes and width, and OpenFreeMap merges building polygons by height, so they are
     weaker for 3D than Overture.
   - The OSMF `vector.openstreetmap.org` service forbids bulk and offline use, which rules it out.
   - Overpass is ruled out for runtime use (already a project rule).
3. **Trees: use Meta/WRI CHMv2.**
   - CHMv2 is new in `s3://dataforgood-fb-data/forests/v2/`: a 1.19 m canopy-height COG in
     quadkey-level-10 tiles (~2 MB each), plus a 10 m mean derivative.
   - A 1 km window reads in 0.24–0.35 s. [M]
   - Enough to detect individual tree crowns, giving real tree positions and heights.
4. **Land cover: ESA WorldCover 10 m COG on S3** (CC BY 4.0). A 2 km window reads in 0.2–0.3 s. [M]
   NLCD (US, 30 m, public domain) is the optional US refinement.
5. **Per-surface physics already fits our TerrainBlock.**
   - `importMaps` takes N materials plus N opacity maps. Each map can name a channel R/G/B/A
     (`terrainGenerator.lua:184-185`), and for each cell the engine picks the material whose map is
     highest (Torque3D `terrImport.cpp:197-218`).
   - A material's `groundmodelName` sets its physics.
   - So the server can write **one or two RGBA layer PNGs per terrain block** next to the heightmap.
     Road cells become ASPHALT, tracks DIRT or GRAVEL, beaches SAND, and so on.
   - Runtime patching also exists: `tb:setMaterialIdxWs` plus `tb:updateGridMaterials`
     (`editor/toolUtilities/terrainPainter.lua:95-107`).
6. **The official maps' recipe is not what we need.**
   - west_coast_usa has 5,976 DecalRoads, 4,666 TSStatics, 14 GroundCovers, one Forest, and a
     terrain painted with 12 ground-model materials. [V-code]
   - Our equivalent: road ribbons and markings plus extruded buildings baked by the server into
     per-tile `.cdae` meshes; the physics surface type in the terrain layer map; Forest items for
     near trees; GroundCover driven by the same terrain layers for grass and shrubs.

---

## 1. Where we start (project code)

- **The physics terrain carries one material today.**
  - `mod/.../beamngEarth/terrain.lua:29` ships an all-white 1024² layer map, so material 0
    (`beamngEarthDirt`, `groundmodelName: "DIRT"`) covers every cell.
  - `terrain.lua:89-101` calls `tb:importMaps(path, squareSize, maxHeight, '', materials, textureMaps, false)`
    with `materials = {M.MATERIAL}` and one `textureMaps` entry
    `{path=LAYER_MAP, material=…, materialId=0, channel='R', channelId=0}`.
- **The server writes only the heightmap.**
  - `server/heightmap.py:120-130` (`write_png`) writes a 16-bit greyscale PNG, uncompressed, which
    imports about 7 ms faster than level-1 compression (43 vs 50 ms).
  - The server writes no layer data.
- **Everything visible is a server-built textured TSStatic tile.**
  - Tile builder: `server/farfield.py`, `server/cdae.py`, `server/imagery.py`.
  - The TerrainBlock is render-disabled and used for physics only. Collision is exactly bilinear
    per 2 m square (ARCHITECTURE.md, v1.3 results).
- **Planned data rule** (ARCHITECTURE.md "Data sources"): buildings and roads come from Overture and
  OSM "from extracts the server holds itself. Never query the public Overpass API at runtime."
  Land cover and vegetation come from ESA WorldCover and Meta canopy height. This report confirms
  and refines that plan.

---

## 2. Vector data: roads and buildings

### 2.1 Overture Maps GeoParquet on S3. Recommended primary source.

- **Location** [M]:
  - Bucket `s3://overturemaps-us-west-2/release/<rel>/theme=<theme>/type=<type>/*.zstd.parquet`,
    anonymous access over HTTPS: `https://overturemaps-us-west-2.s3.us-west-2.amazonaws.com/...`.
  - Latest release `2026-09-23.1` (`https://stac.overturemaps.org/catalog.json` → `"latest"`).
  - There is also an Azure mirror. Its path is not verified here.
- **Sizes for release 2026-09-23.1** [M, S3 listing]:

| theme/type | files | size |
|---|---|---|
| buildings/building | 512 | 276.9 GB |
| transportation/segment | 128 | 72.2 GB |
| base/land_cover | 128 | 109.1 GB |
| base/land_use | 64 | 18.8 GB |
| base/water | 128 | 28.6 GB |
| base/infrastructure (bridges, barriers, towers…) | 64 | 13.8 GB |

- **STAC per-file index (the important trick)** [M]:
  - `https://stac.overturemaps.org/<rel>/buildings/building/collection.json` has 512 `item` links.
  - `extent.spatial.bbox[1..512]` gives each file's bbox; files are spatially sorted.
  - Pick the 1–2 files that intersect the area, then read only those with DuckDB `read_parquet([...])`
    plus a `bbox.xmin/xmax/ymin/ymax` predicate, which row-group statistics prune.
- **Measured near Bakersfield, CA (35.373, -119.019)** [M]:

| query | glob over all files | STAC-selected files |
|---|---|---|
| buildings, 2.4 km bbox | 35.3 s (3,829 bldgs) | 2.3 s cold / 0.4 s warm |
| buildings, 0.3° bbox (~33 x 27 km) | n/a | **2.6 s cold / 0.3 s warm**, 223,184 bldgs, 36 MB WKB; written to local parquet in 1.2 s (35.9 MB) |
| road segments, 2.4 km bbox | 13.3 s | n/a |
| road segments, 0.3° bbox | n/a | **3.7 s** for 49,914 `subtype='road'` segments (2 files) |

- **Building attributes** [M schema]:
  - Fields: `height, min_height, num_floors, roof_shape, roof_height, roof_direction,
    roof_orientation, roof_material, roof_color, facade_material, facade_color, class, subtype,
    level, has_parts`. Separate `building_part` type.
  - Height coverage near Bakersfield [M]:
    - Overall: 2,020 of 3,829 buildings (53%) in the 2.4 km box, 67% in the 33 km box.
    - By source: OSM 1,796 of 3,513, Microsoft ML 179 of 179 (mean 3.1 m), Esri Community Maps 45 of 137.
  - `roof_shape`, `facade_material` and `roof_material` were 0% filled there, so roof shapes need
    heuristics (§5.2).
- **Transportation attributes** [M]:
  - Topology: `class`, `subclass`, `connectors` (shared connector IDs give junctions for free).
  - Per-range rules (linear referencing via `between`): `road_surface`, `road_flags`, `width_rules`,
    `level_rules`, `speed_limits`, `access_restrictions`, `prohibited_transitions`.
  - Coverage over the 49,914 road segments in the 33 km box:
    - `road_surface`: 8%. Values paved 3,609, unpaved 243, gravel 119, dirt 116.
    - `width_rules`: 13 segments.
    - `level_rules`: 443.
    - `road_flags`: 1,888, of which is_link 979, is_bridge 485, is_covered 460,
      is_under_construction 115, is_tunnel 61.
  - **There is no lane count.** So width must come from class defaults or from OSM `lanes`/`width` (§5.1).
- **Licence** [V-doc https://docs.overturemaps.org/attribution/]:
  - buildings, transportation, divisions: ODbL. Base: ODbL, plus ESA WorldCover CC BY 4.0 for land cover.
  - Attribution: "© OpenStreetMap contributors, Overture Maps Foundation". Buildings must also
    credit Esri Community Maps (CC BY 4.0), Google Open Buildings (CC BY 4.0), Microsoft ML
    Buildings, USGS 3DEP and others.
  - [I] Our local cache is a derivative database. Keeping it private (not redistributed) avoids the
    ODbL share-alike duty. Rendered game imagery is a "Produced Work" and needs attribution only.
- **PMTiles too** [M]: `https://tiles.overturemaps.org/<rel>/buildings.pmtiles` (180.7 GB) and
  `transportation.pmtiles` (133.7 GB), both range-readable (HTTP 206). These are useful for a
  tile-addressed fetch path (§2.3).
- **Python** [M]: `duckdb` 1.5.6 (`httpfs` + `spatial`) needs no credentials (`SET s3_region='us-west-2'`).
  `pip install overturemaps` also offers `overturemaps download --bbox … --type=building`.
- **Recommendation** [I]:
  - **Server worker:**
    - The server keeps a local GeoParquet or SQLite cache in fixed cells, for example
      0.25° x 0.25° (~28 x 23 km at 35°N).
    - It fetches the cell under the car plus the cell ahead along the velocity, using the STAC
      file selection: about 2.5–4 s per theme per cell, well ahead of need at 30 m/s
      (~800 m in 27 s of fetch time).
    - It then builds meshes from the local cache.
  - Refresh only when `stac.overturemaps.org/catalog.json` `latest` changes (about monthly).

### 2.2 OpenStreetMap raw extracts (for lanes, width, surface detail)

- Overture drops some OSM tags we want: `lanes`, `width`, `lanes:forward`, `turn:lanes`, `sidewalk`,
  `surface` beyond the 4 values above, `smoothness`, `tracktype`, `natural=*`, `landuse=*` detail.
- **Geofabrik** (no key):
  - California is 1.33 GB, `california-261008.osm.pbf` [M]. Daily updates.
  - Per-state PBFs: `https://download.geofabrik.de/north-america/us/<state>-latest.osm.pbf`.
  - Python: `pyosmium` or `osmium-tool` (`osmium extract -b`, `tags-filter`).
- **Overpass API** (public `overpass-api.de`) [V-doc wiki.openstreetmap.org/wiki/Overpass_API]:
  - Limits: "less than 10,000 queries per day", "less than 1 GB data per day"; for regular use
    "divide those numbers by 100" (under 100 queries/day).
  - "No parallel running of multiple scripts". Pause 30 s on 429/406.
  - "Commercial use should use self-hosted or paid Overpass servers."
  - **Not usable for streaming.**
- **Recommendation** [I]: Overture for geometry and topology. Optionally join OSM tags by the
  Overture `sources[].record_id` (e.g. `w123456@7`), taken from a state PBF cached once, for
  `lanes`, `width` and detailed `surface`.

### 2.3 Vector tile services (fallback, or a far-field/minimap source)

| Service | URL / scheme | Key? | Limits / terms | Schema notes |
|---|---|---|---|---|
| **OpenFreeMap** | TileJSON `https://tiles.openfreemap.org/planet` → `…/planet/20261004_113936_pt/{z}/{x}/{y}.pbf` [M] | none | "no limits on the number of map views or requests", commercial OK, donations asked, no SLA [V-doc openfreemap.org]. Attribution: OpenMapTiles + OpenStreetMap | OpenMapTiles. One z14 tile in downtown Bakersfield: 99.7 KB, 0.73 s [M]. `transportation`: class, oneway, `surface` (51/431 set, paved/unpaved only), `brunnel` (bridge 40, tunnel 5), `layer`, ramp; **no lanes/width**. `building`: **merged MultiPolygons per `render_height`** (9 features = 2,116 polygons, default height 5 m), no roof/type info. Extent 4096 at z14, so ~0.49 m quantisation at 35°N |
| **Protomaps** | daily `https://build.protomaps.com/YYYYMMDD.pmtiles`, 20261010 = 138.8 GB, HTTP range 206 in 0.22 s [M]; metadata `https://build-metadata.protomaps.dev/builds.json` | none | ODbL produced work; docs say URLs may change and "hotlinking is discouraged": copy to your own storage, or `pmtiles extract --bbox` a region [V-doc docs.protomaps.com/basemaps/downloads] | z0–15. roads: kind, kind_detail, is_bridge, is_tunnel, is_link, level, oneway, sidewalk [V-code protomaps/basemaps Roads.java]; no surface/lanes/width |
| **Overture PMTiles** | `https://tiles.overturemaps.org/<rel>/{buildings,transportation,base}.pmtiles` [M] | none | as Overture | Same attributes as the parquet, tile-addressed |
| **OSMF Shortbread** (`vector.openstreetmap.org`) | `https://vector.openstreetmap.org/$VERSION/{z}/{x}/{y}.mvt` | none | **"bulk downloading is prohibited… downloading for offline usage"**, cache ≥7 days, custom UA required, can block without notice [V-doc operations.osmfoundation.org/policies/vector/] | **Do not use** (prefetching ahead of a car is bulk use) |

[I] Vector tiles suit flat 2D overlays such as the minimap and far-field road lines on the
textures. For 3D buildings and road physics, Overture parquet is strictly better: individual
buildings, heights, connectors, surface, flags.

### 2.4 Building footprints and heights beyond OSM

- **Microsoft Global ML Building Footprints** [V-doc github.com/microsoft/GlobalMLBuildingFootprints]:
  - About 1.4B buildings in 225 regions.
  - Index `https://bfppub.blob.core.windows.net/%24web/2026-08-13/dataset-links.csv`.
  - Files are partitioned by country and **level-9 quadkey**. They are named `.csv.gz` but contain
    GeoJSONL.
  - Heights: 174M with height as of June 2023, -1 when missing.
  - Licence is stated as **CDLA Permissive 2.0** on the repo, while Overture lists it as ODbL. Moot
    if consumed through Overture.
  - Already merged into Overture: in the Bakersfield sample, 179 buildings came from
    "Microsoft ML Buildings", all with height [M].
- **Google Open Buildings v3** [V-doc sites.research.google/gr/open-buildings/]:
  - Covers Africa, S/SE Asia, Latin America and the Caribbean. **No mainland USA** (only PR and VI).
  - CC BY 4.0 or ODbL.
  - `gs://open-buildings-data/v3/polygons_s2_level_4_gzip` (178 GB, S2-level-4 CSVs).
  - Also folded into Overture.
  - The 2.5D Temporal dataset (heights) is Earth Engine-oriented and also non-US. [I]
- **US heights** [I]: Overture credits USGS 3DEP, so lidar heights are already in its US data.
  Most US gaps are small houses; a class-based default works for them (§5.2).

---

## 3. Trees, canopy, land cover

### 3.1 Meta/WRI canopy height (CHM). Recommended for tree placement.

- **Bucket** [M]: `s3://dataforgood-fb-data/forests/` (us-east-1, `--no-sign-request`).
  - Plain HTTPS: `https://dataforgood-fb-data.s3.amazonaws.com/...`.
  - Licence CC BY 4.0 [V-doc registry.opendata.aws/dataforgood-fb-forests].
- **v1**: `forests/v1/alsgedi_global_v6_float/chm/<quadkey9>.tif`, ~21–26 MB per tile [M].
- **v2 (CHMv2, DINOv3 model, imagery ~2019)** [M + V-doc README in the bucket]:
  - **1.19 m**: `forests/v2/global/dinov3_global_chm_v2_ml3/chm/<quadkey10>.tif`.
    - EPSG:3857, uint8 metres, 512² blocks, overviews 2/4/8/16.
    - ~2 MB per tile, 213,109 tiles.
    - Index: `forests/v2/aws_google_chmv2_global_transfer.tsv`.
  - **9.55 m mean**: `forests/v2/global/dinov3_global_chm_v2_ml3_10m_mean/chm/<quadkey7>.tif`.
    - 4,376 COGs, ~722 GB, nodata 255.
    - Also `…_10m_p95/`.
    - README caveats: water is valid 0, there is a false ~10 m signal above ~70°N, and 255 must be
      honoured.
- **Measured** [M, `/vsicurl` + rasterio window read]:

| place | product | window | open + read | stats |
|---|---|---|---|---|
| Kern River valley (35.70,-118.45) | 1.19 m | 1 km (1031²) | 0.32 + 0.35 s | max 17 m, 3.2% > 0 |
| Bakersfield (35.373,-119.019) | 1.19 m | 1 km | 0.23 + 0.24 s | max 21 m |
| same | 10 m mean | 2 km (257²) | 0.00 + 0.16 s (warm) | **25% nodata (255)** in this window: the derivative has gaps; fall back to 1.19 m |

- **Use** [I]:
  - Treetop detection: local maxima of the 1.19 m CHM above 3 m, with a window radius that grows
    with height (e.g. r = 1 + 0.1·h m, a standard "variable window filter").
  - That gives an (x, y, height) list per 64/128 m tile. Crown radius ≈ 0.15–0.25·h.
  - This yields *real* tree positions that line up with the satellite texture's tree blobs, unlike
    random scatter.

### 3.2 ESA WorldCover 10 m. Recommended land-cover base.

- **Location** [M]: `https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_<N|S>{lat3}<E|W>{lon3}_Map.tif`.
  - 3° x 3° tiles named by their SW corner, e.g. `N33W120` covers Kern and Bakersfield.
  - COG, EPSG:4326, 1024² blocks, overviews. 115.5 MB per tile; `Accept-Ranges: bytes`.
  - Grid index `v200/2021/esa_worldcover_grid.geojson`.
  - CC BY 4.0. Also a 2020 v100.
- **Measured** [M]: a 2 km window (216 x 265 px) reads in 0.19–0.28 s, open 0.54 s cold.
  - Kern valley class histogram: 10 tree 3,591; 20 shrub 1,297; 30 grass 18,821; 40 crop 1,568;
    50 built 7,893; 60 bare 5,751; 80 water 18,319 (Lake Isabella).
  - Bakersfield: 50 built 52,999 of 57,024.
- **Classes**: 10 tree, 20 shrubland, 30 grassland, 40 cropland, 50 built-up, 60 bare/sparse,
  70 snow/ice, 80 water, 90 herbaceous wetland, 95 mangroves, 100 moss/lichen.
  The class list comes from the product manual [I-recall]; the codes seen in the data match it.
- Overture `base/land_cover` is a vectorised WorldCover (109 GB). For our 2 m physics grid the raw
  raster is simpler.

### 3.3 US refinements

- **Annual NLCD** (MRLC/USGS, 30 m, 1985–2025):
  - WMS/WCS `https://dmsdata.cr.usgs.gov/geoserver/mrlc_Land-Cover-Native_conus_year_data/wms`.
  - Tree canopy cover `…/mrlc_NLCD-Tree-Canopy-Native_conus_year_data/wms`.
  - Fractional impervious `…/mrlc_Fractional-Impervious-Surface-Native_conus_year_data/wms`
    [V-doc mrlc.gov/data-services-page].
  - Public domain as a US government work [I].
  - 30 m is coarser than WorldCover. Its value is the **class detail** (developed open/low/med/high,
    deciduous/evergreen/mixed forest, pasture vs crops, woody wetlands) for species and ground
    choice. No keyless COG bucket was confirmed.
- **Dynamic World** (10 m near-real-time, 9 classes): served through Earth Engine
  (`GOOGLE/DYNAMICWORLD/V1`), which needs an EE account. **Not keyless**, so skip.
- [I] NAIP has a NIR band. Our planned NAIP `exportImage` fetch could request bands 4,1,2 to get
  NDVI for sub-metre vegetation and lawn masks, at no extra data source.

---

## 4. BeamNG side: how the official maps do it, and the hooks we can use

### 4.1 What west_coast_usa contains [V-code, extracted from `content/levels/west_coast_usa.zip`]

- **Scene objects** (`main/MissionGroup/*/items.level.json`, all 47 groups): DecalRoad 5,976,
  TSStatic 4,666, BeamNGWaypoint 838, Prefab 93, GroundCover 14, Forest 1, TerrainBlock 1, River 1,
  WaterBlock 1.
- **Some DecalRoads are AI-only.** Example:
  `{"class":"DecalRoad","__parent":"AIWaypointsGroup","drivability":1,"material":"road_invisible","nodes":[[x,y,z,width],…]}`.
  The AI graph reads every DecalRoad with `drivability > 0` (`lua/ge/map.lua:584-600`).
- **Terrain:**
  - `theTerrain_terrainPreset.json` lists opacity maps `theTerrain_layerMap_<i>_<name>.png`.
  - `art/terrains/main.materials.json` has 12 TerrainMaterials. groundmodelName counts:
    DIRT_ROCKY 3, GRASS 3, ASPHALT 1, ASPHALT_PREPPED 1, SAND 1, DIRT_GRASS 1, GRAVEL 1.
  - **Road physics comes from the painted terrain layer.** The DecalRoad is only the look.
- **GroundCover is keyed to terrain layers.** Example `shrubs_med`: `Types[i].layer = "Forest"`,
  `gridSize 2`, `maxElements 43688`, `dissolveRadius 150`, `material "wca_groundcover"`
  (billboard atlas UVs). Grass grows wherever the terrain layer says "Forest".
- **Forest:**
  - Items live in `forest/<type>.forest4.json`, one JSON line per item:
    `{"pos":[…],"rotationMatrix":[9],"scale":1,"type":"bollard_yellow"}`.
  - Types are defined in `art/forest/managedItemData.json` (`class: TSForestItemData`, `shapeFile`).
  - Trees ship `*.dae.imposter.dds` and `*.dae.imposter_normals.dds` (pre-baked impostors).
- **Mesh materials can carry physics.** Some carry `"groundType": "ASPHALT" | "GRASS" | "WOOD" |
  "METAL" | "CONCRETE" | …` (`art/shapes/**/main.materials.json`), so collision meshes can carry
  surface physics too.

### 4.2 Shared stock assets we can reference (no redistribution) [V-code]

- **Trees:** `content/assets/meshes.zip` → `assets/meshes/foliage/trees_library/{beech(36 files),
  oak(30), birch(28), cork_oak(4)}`, `foliage/bushes`.
  - Level trees with impostors: `levels/west_coast_usa/art/shapes/trees/trees_{conifer,oak,palm,
    eucalyptus,cypress,shrub}`, including `pine_radiata_forest.dae` with its imposter DDS.
  - [I] Referencing another level's files from our level depends on all level zips being mounted
    in the VFS. Probe before relying on it.
- **Facades:** `content/assets/materials/tileable.zip` has brick (25 sets, e.g. `brick_plain`,
  `eca_bld_bricks`) and concrete (35 sets, e.g. `concrete_plain`, `sidewalk1`, `road2_concrete`).
  Also `trim.zip`, `atlas.zip` (`eca_doors_windows`, `building_details`, `busstop`).
- **Roads:** `content/assets/materials/decalroad.zip` (1.39 GB, 606 files):
  - asphalt variants and edges (`ECA_road_edge_grass/dirt`), dirt and gravel roads;
  - markings: `line_white`, `line_white_dashed`, `line_yellow_double`, `line_yellow_double_discontinue`,
    `zebra_crossing`, `crossing_yellow`, `road_lines`, `rumblestrip`, `line_parking1`…;
  - the stock importer's default decal material is `road_asphalt_2lane`
    (`lua/ge/extensions/editor/terrainAndRoadImporter.lua:8`).
- **Industrial buildings:** `assets/meshes/architecture/buildings/industrial/ind_bld_02..08.cdae`.

### 4.3 Ground models (`gameengine.zip:art/groundmodels.json`) [V-code, line numbers in that file]

| model (line) | static μ | sliding μ | roughness | fluidDensity | defaultDepth | aliases |
|---|---|---|---|---|---|---|
| ASPHALT (10) | 0.98 | 0.70 | 0 | – | 0 | groundmodel_asphalt1, grid, concrete |
| ASPHALT_OLD (36) | 0.96 | 0.67 | 0 | – | 0 | |
| ASPHALT_WET (23) | 0.92 | 0.55 | 0.2 | – | 0 | |
| COBBLESTONE (91) | 0.93 | 0.69 | 0.05 | – | 0 | |
| ROCK (77) | 0.93 | 0.65 | 0.15 | – | 0 | rock_cliff |
| DIRT (158) | 0.70 | 0.73 | 0.42 | 14000 | 0 | dirt_grass |
| DIRT_DUSTY (177) | 0.68 | 0.70 | 0.38 | 12000 | 0 | dirt_rocky |
| DIRT_DUSTY_LOOSE (196) | 0.65 | 0.65 | 0.46 | 10000 | 0.02 | dirt_sandy |
| GRAVEL (215) | 0.69 | 0.74 | 0.44 | 16000 | 0 | dirt_loose |
| GRASS (252) | 0.61 | 0.65 | 0.43 | 8000 | 0.05 | grass, forest, forest_floor |
| MUD (271) | 0.55 | 0.55 | 0.5 | 7000 | 0.15 | |
| SAND (289) | 0.6 | 0.6 | 0.5 | 25000 | 0.1 | beachsand |
| SNOW (347) | 0.65 | 0.4 | 0.3 | 481 | 0 | |
| ICE (308) | 0.4 | 0.2 | 0.1 | – | 0 | |

### 4.4 Per-cell ground models on our physics-only TerrainBlock

- **Import path** [V-code]:
  - The stock generator builds `materials` and `textureMaps` lists, one entry per material
    (`lua/ge/extensions/util/terrainGenerator.lua:184-185` `getTextureMap` →
    `{path, material, materialId=#textureMaps, channel='R', channelId=0}`).
  - It then calls `terrain:addMaterial(mat,-1)` and `updateMaterial(i-1,mat)` per material
    (`:451-453`), then `terrain:importMaps(heightMap, scale, height, holeMap, materials, textureMaps, flipY)` (`:463`).
- **Resolving opacity maps to indices** [V-code upstream Torque3D `Engine/source/terrain/terrImport.cpp:150-218`]:
  - Each map is read through its named channel (R/G/B/A, `copyChannel`).
  - For every cell, the layer index is the map with the greatest value. The comparison is `>=`, so
    on ties the **later** layer wins.
  - BeamNG's `importMaps` is not open, but takes the same table shape. [I] Assume the same logic and
    verify with a probe.
- **Recommended encoding** [I]:
  - Server writes `ground_A.png` (RGBA, 1024², 8-bit). R = ASPHALT, G = GRAVEL, B = DIRT, A = SAND.
  - Server writes `ground_B.png`: R = GRASS, G = MUD, B = ROCK, A = SNOW.
  - Pass 8 `textureMaps` entries pointing at the 2 files with channels R/G/B/A, plus a final
    all-default entry. Binary 0/255 values give hard 2 m cells.
  - Because ties go to the later layer, list the default (e.g. DIRT or GRASS) **last** so that
    all-zero cells fall to it, or always set exactly one channel per cell.
  - Probe the import cost first. Today's single-layer import is ~43 ms; two extra 1024² RGBA PNG
    decodes are probably a few ms each, uncompressed (same reasoning as `heightmap.py:129`).
- **Runtime patching** (small changes, no re-import) [V-code]:
  - `tb:getMaterialIdxWs(pos)`, `tb:setMaterialIdxWs(pos, idx)`, then
    `tb:updateGridMaterials(minGrid, maxGrid)` and `tb:updateGrid(minGrid, maxGrid)`
    (`lua/ge/extensions/editor/toolUtilities/terrainPainter.lua:95-107`).
  - Index 255 marks a **hole** (`editor/tech/roadArchitect/tunnelMesh.lua:107-109`), useful for
    tunnel portals.
  - Each call is per cell, so it suits only small edits [I]. A 1 km road at 10 m width is
    ~2,500 cells.
- **Visual materials and GroundCover** [I]:
  - Each TerrainMaterial needs a v1.5 texture set, but our block is render-disabled, so the 8
    materials can all reuse the existing `beamngEarthDirt` textures and differ only in
    `groundmodelName` and `internalName`.
  - **GroundCover** binds to terrain layers by material name (§4.1). Giving the GRASS layer a
    GroundCover with stock grass billboards should give near-car 3D grass on the invisible terrain,
    following real land cover. Unverified: whether GroundCover still populates on a
    render-disabled TerrainBlock. Probe it.
- **Other paths:**
  - **Navgraph without DecalRoads**: `map.reset = loadMap` (`lua/ge/map.lua:3960`) and
    `loadMap(customMapNodes)` assigns `map.nodes = customMapNodes` directly (`map.lua:2497, 2513-2515`).
    So the server can send Overture road centrelines as a node table for AI traffic, with no scene
    objects. [I] The cost of a reload, and its interaction with rebase, are unmeasured.
  - **Trees at runtime**: `forestData:createNewItem(itemData, transform, scale)`
    (`lua/ge/extensions/editor/api/forest.lua:71`), with `forestData = core_forest.getForestObject():getData()`.
  - **DecalRoads over meshes**: stock tools set `dRoad:setField("overObjects",0,"true")`
    (`editor/tech/roadArchitect/decals.lua:108`), so decal markings can drape over our mesh tiles.
    [I] They cost one scene object each, re-project on every change, and must be recreated after a
    rebase. Prefer baked markings (§5.1).

---

## 5. Generation methods (open-source prior art → what to do here)

### 5.1 Roads

**Prior art:**
- **BeamNG Terrain And Road Importer** (stock, `terrainAndRoadImporter.lua`; docs
  documentation.beamng.com/beamng_tech/tools/terrainandroadimporter/):
  - Input: road JSON nodes `[x,y,z,width]`. It makes one DecalRoad per road (`:120-131`).
  - It conforms terrain to the road: a flat "margin" around the road (default 7 m, `:37`), blended
    over a "Domain of Influence" (default 150 m, `:36`) with Gaussian smoothing (`:147-230`).
- **BeamNG Road Architect** (stock, `editor/tech/roadArchitect/`): profiles, junctions, terraform,
  tunnelMesh, staticMesh, and an **OpenDRIVE importer** (`import.lua:45-196`). Shows the engine's
  own pattern: mesh roads + DecalRoad markings with `overObjects`.
- **TerraDrive** (github.com/Alezx311/terra-drive, MIT, early alpha): OSM to BeamNG level with
  lanes, divided roads, curbs, bridges, ramps, intersections, markings. **MapNG** (mapng.com): a web
  app exporting heightmaps, road masks, OSM buildings, trees, `.ter` and level ZIPs. Neither streams.
- **OSM2World** (osm2world.org, open source): 250+ tags, lane markings, LOD, glTF output.
  **Streets GL** (MIT): vector tiles from a modified Planetiler, on-the-fly roads and buildings.
  **Blosm** (GPL): roads are curves with a profile projected onto terrain.

**Recommended for us** [I]:
1. **Width:** OSM `width`, else `lanes` × lane width. Otherwise class defaults (US):

   | class | lanes | lane width |
   |---|---|---|
   | motorway | 2 per direction | 3.65 m + 3 m shoulders |
   | trunk / primary | 4 total | 3.5 m |
   | secondary | 2 | 3.5 m |
   | tertiary | 2 | 3.3 m |
   | residential | 2 | 3.0 m + parking |
   | service | 1 | 3 m |
   | track | 1 | 2.5 m |

2. **Surface → ground model:** from `road_surface`, else class (US: track → DIRT, everything
   residential or above → paved). Mapping: paved → ASPHALT; unpaved / dirt → DIRT; gravel → GRAVEL;
   paving_stones → COBBLESTONE.
3. **Profile and terrain carving on the server.** Before writing a block's heightmap and the near
   tile meshes:
   - Sample the DEM along the densified centreline (≤2 m).
   - Smooth the longitudinal profile (e.g. 40–80 m window, limited grade).
   - Set cells within half-width + 0.5 m to the profile (with crown or bank if wanted).
   - Blend to the DEM over 5–15 m.
   - Both physics (TerrainBlock) and visuals (L-2/L-1 meshes) read the same carved elevation, so
     they stay consistent. This fixes the "road on a 30 m-DEM slope" problem. Sub-metre US 3DEP
     already has flat roads; mostly needed outside the US.
4. **Bridges and tunnels** (`is_bridge`, `is_tunnel`, `level_rules`):
   - Bridges: do not carve. Build a deck mesh with collision (TSStatic, near ring only) spanning
     the connector endpoints' elevations. The terrain under it stays natural.
   - Tunnels: skip the mesh. Mark portal cells as holes (255) only if a tunnel mesh is built.
5. **Visual road:** per near tile (64/128 m), one merged ribbon mesh in the tile `.cdae`, a few cm
   above the ground mesh to avoid z-fighting, using a tiling asphalt material from `decalroad.zip`.
   - Markings: a second primitive with a marking atlas (centre double yellow, dashed white, edge
     white) along lane boundaries.
   - Junctions: Overture `connectors` with ≥3 segments → junction polygon (union of buffered stubs)
     painted asphalt with no markings. Same approach as OSM2World and Streets GL [I].
   - Far tiles: rasterise roads into the satellite texture (already 256 px per tile).
6. **Physics surface type:** rasterise the road polygons into the ground layer map (§4.4).
   No road collision meshes are needed except bridges.

### 5.2 Buildings

**Prior art** (roof shapes per OSM Simple 3D Buildings: flat, skillion, gabled, half-hipped, hipped,
pyramidal, gambrel, mansard, dome, onion, round, saltbox [V-doc wiki.openstreetmap.org/wiki/Simple_3D_Buildings]):
- OSM2World, Blosm and Streets GL extrude footprints, build roofs, and texture facades.
- Blosm free = untextured; Pro = tileable textures and lit windows.

**Recommended** [I]:
- **Shape:**
  - Footprint → `mapbox_earcut` for the roof cap.
  - Walls = extruded rings, from z = min terrain under footprint − 0.5 m to z = max terrain + height.
    This avoids floating corners on slopes.
- **Height:** `height`, else `num_floors × 3.0 m` (residential) or `× 4.0 m` (commercial), else a
  class default (house 6 m, garage/shed 3 m, commercial 8 m, industrial 10 m).
- **Roof:** use `roof_shape` when present (rare). US heuristic:
  - footprint < 300 m², height ≤ 10 m, class house/residential → hipped if near-square, else gabled;
  - otherwise flat with a 0.6 m parapet.
  - Hipped and gabled come from a straight skeleton (`polyskel` or CGAL `skgeom`).
- **Texture:**
  - One atlas per biome/style (brick, stucco, siding, concrete, glass) built from stock `tileable`
    and `atlas` textures referenced in place.
  - World-space UV on walls (1 tile = 3 m floor height) so windows line up with floors.
  - Roof colour from the satellite texel at the centroid; free and matches the imagery.
- **LOD:**
  - Near ring (≤500 m): full walls and roofs, merged per 128 m tile into the tile `.cdae`.
  - 0.5–3 km: flat roofs only, untextured colour.
  - Beyond that: the satellite imagery already shows roofs.
  - Collision: box or prism hulls only within ~300 m, in a separate collision-only TSStatic, to
    keep reloadCollision cheap (governor).

### 5.3 Trees and ground cover

**Recommended** [I]:
- **Positions:** CHMv2 1.19 m treetops (§3.1) inside WorldCover tree/shrub classes and OSM
  `natural=wood`/`landuse=forest`. Fall back to Poisson-disk sampling at density ∝ the 10 m canopy
  mean where the 1.19 m tile is missing.
- **Species by biome:**
  - WorldCover class plus latitude and elevation, refined in the US by NLCD
    (41 deciduous → oak/beech/birch, 42 evergreen → conifer, 43 mixed).
  - Palms below ~33°N on the US coasts; eucalyptus and cypress in CA.
  - Shrubland → `trees_shrub` / `foliage/bushes`.
- **Scale:** `scale = h_detected / h_model`, clamped to 0.6–1.6.
- **Engine:**
  - One Forest object with TSForestItemData per species, items via `createNewItem`. Forest
    batches, culls and uses the shipped impostors, and was built for the ~10⁵ items the official
    maps use.
  - Stream items in per tile through the governor and remove them on tile unload.
  - Keep 3D trees to ~1.5–2 km. Beyond that the satellite texture already has the canopy.
- **Grass and shrubs:** GroundCover bound to the GRASS terrain layer (§4.4).

### 5.4 Land cover → ground model (default, before roads override)

| WorldCover | ground model | notes [I] |
|---|---|---|
| 10 tree cover | GRASS (alias forest_floor) | |
| 20 shrubland | DIRT_DUSTY | desert scrub in the US West |
| 30 grassland | GRASS | |
| 40 cropland | DIRT | MUD where NLCD 82 is wet, optional |
| 50 built-up | ASPHALT_OLD within OSM parking/landuse=retail/commercial/industrial; else GRASS (lawns) | |
| 60 bare/sparse | DIRT_DUSTY_LOOSE; SAND where OSM `natural=sand/beach` or `desert`; ROCK where slope > 35° | |
| 70 snow/ice | SNOW | |
| 80 water | MUD (shore) | water itself is a separate visual plane |
| 90 wetland, 95 mangroves | MUD | |
| 100 moss/lichen | GRASS | |

Override order: road polygons > OSM `landuse`/`natural`/`amenity=parking` polygons > WorldCover > default.

---

## 6. Performance notes [I unless stated]

- **Object counts are fine.** The official map renders ~4.7 k TSStatics and ~6 k DecalRoads [V-code].
  Our per-tile merging (roads and buildings in the tile `.cdae`) adds **zero** extra objects per
  near tile, and only material slots. Textured tile import is 3.6–4.7 ms (ARCHITECTURE v1.3).
  Keep the atlas count small: one facade atlas plus one road atlas.
- **Server work per near tile:**
  - Overture query from the local cache (<50 ms);
  - CHM window (~0.25 s network on a cache miss, so prefetch with the imagery);
  - extrusion and earcut (~ms per hundred buildings).
  - All of this runs in background threads ahead of the car.
- **Physics:**
  - Layer maps add a few ms to the ~43 ms terrain commit.
  - Building and bridge collision is limited to ~300 m and batched into the existing collision
    scheduler.
- **Rebase:**
  - Forest items, GroundCover and any DecalRoads hold absolute positions and must be moved or
    recreated by `rebase.lua`.
  - Merged tile meshes already re-stream.

## 7. Suggested next steps

1. **Probe** (when the user is not driving):
   - `importMaps` with 2 RGBA layer PNGs and 8 materials: cost, and per-cell ground model check by
     driving over the cells.
   - Does GroundCover populate on a render-disabled TerrainBlock?
   - Can our level reference `levels/west_coast_usa/...` tree shapes?
   - `forestData:createNewItem` cost per 1,000 items.
2. **Server:** `worlddata.py` (Overture STAC-selected cell cache, WorldCover/CHM window reader),
   then `ground.py` (layer maps), then `roads.py` (carve + ribbons), then `buildings.py`.
3. **Attribution** in `ui.lua`: "© OpenStreetMap contributors, Overture Maps Foundation;
   ESA WorldCover 2021 (CC BY 4.0); Meta/WRI Canopy Height (CC BY 4.0)".

## Sources

- https://docs.overturemaps.org/getting-data/, https://docs.overturemaps.org/attribution/,
  https://stac.overturemaps.org/catalog.json
- https://wiki.openstreetmap.org/wiki/Overpass_API, https://operations.osmfoundation.org/policies/vector/
- https://openfreemap.org/, https://openfreemap.org/quick_start/, https://docs.protomaps.com/basemaps/downloads
- https://github.com/microsoft/GlobalMLBuildingFootprints, https://sites.research.google/gr/open-buildings/
- https://registry.opendata.aws/dataforgood-fb-forests/, https://registry.opendata.aws/esa-worldcover-vito/,
  https://www.mrlc.gov/data-services-page, https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_DYNAMICWORLD_V1
- https://wiki.openstreetmap.org/wiki/Simple_3D_Buildings, https://osm2world.org/,
  https://github.com/StrandedKitty/streets-gl, https://github.com/vvoovv/blosm
- https://documentation.beamng.com/beamng_tech/tools/terrainandroadimporter/,
  https://boxthislap.org/beamng-drive-real-world-map-generator-terradrive/, https://mapng.com,
  https://www.beamng.com/posts/1964979/
- https://raw.githubusercontent.com/TorqueGameEngines/Torque3D/development/Engine/source/terrain/terrImport.cpp
- Not covered in depth: vts-geospatial (Melown VTS) and the Cesium/ArcGIS procedural pipelines.
  Cesium OSM Buildings needs a Cesium ion token, and CityEngine/ArcGIS procedural is proprietary [I],
  so neither is a keyless source.
