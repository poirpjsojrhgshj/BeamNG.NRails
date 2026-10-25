# Free high-resolution imagery sources worldwide (research 2026-10-10)

Contact sheet (not in git): docs/research/imagery_sources/contact_sheet.png. Scripts: scratchpad imgscripts/.

## Summary

**Live tests: 52 of 62 endpoints passed.** I fetched one z18 footprint per source; PASS means a real image, not a blank tile. The 10 failures:
- **Need a key:** Denmark (403), Finland (401), New Zealand (400) and Korea (connection closed).
- **Not open:** Norway now answers "Token Required".
- **Down:** Spain's main `www.ign.es` host returned 504 three times; its `tms-pnoa-ma.idee.es` mirror of the same data passed.
- **Moved:** Hamburg's WMS URL is gone (404).
- **Unreachable from here:** Slovakia timed out.
- **Blank images:** both Latvian open services.

**Top sources by region** (all free, no key unless stated):
- **US:** Maryland six-inch 2023–25 (0.15 m, free with acknowledgement), NY State orthos, then NAIP (0.6 m, public domain, about 1.5 s per request), then USGS, then EOX.
- **Canada:** Ontario only (16 cm, Open Government Licence – Ontario). No other province has a verified open service.
- **Switzerland:** swisstopo SWISSIMAGE (10 cm, XYZ, open, attribution and fair use).
- **France:** IGN Géoplateforme (20 cm, Etalab 2.0).
- **Spain:** PNOA (25 cm, CC BY 4.0) and Catalonia's ICGC.
- **Portugal:** DGT 2018/2021 (25 cm).
- **Italy:** only patchy regional services (Toscana tested) and a 2012 national 50 cm layer.
- **Netherlands:** PDOK (8 / 25 cm, CC BY 4.0).
- **Belgium:** Flanders (25 cm, winter imagery), Brussels (5 cm, CC0 for the 2022 sets) and Wallonia.
- **Luxembourg:** CC0.
- **Germany:** all 15 state 10–20 cm services work except Hamburg. Bavaria is CC BY 4.0, NRW and Berlin Datenlizenz Deutschland Zero, the rest DL-DE BY 2.0. Mecklenburg-Vorpommern stamps a copyright watermark into every image.
- **Austria, Czechia, Poland:** basemap.at (about 29 cm, CC BY), ČÚZK (CC BY since 2023) and Geoportal (≤10 cm, free for any use).
- **Croatia:** works, but the open WMS burns a "GEOPORTAL" watermark into every image, so it's unusable as texture.
- **Estonia:** Maa-amet (10–25 cm, open licence).
- **Japan:** GSI (about 20–40 cm). Software that loads the tiles live needs only attribution.
- **Taiwan:** NLSC passed, but its licence is unverified.
- **New Zealand:** LINZ (7.5–30 cm, CC BY 4.0) with a free key (1000 requests/min).
- **Australia:** NSW, Victoria, Queensland and Tasmania all pass. Western Australia needs a subscription.
- **No free high-res source:** UK (public sector only), Ireland, Iceland, Lithuania, most of Latin America (São Paulo city is the exception), Africa and Asia outside Japan and Taiwan. These stay on EOX, plus OpenAerialMap patches (CC BY 4.0).

**Need a key or account:**
- Free key: Denmark, Finland ("light use" only), New Zealand, Korea.
- Restricted: Norway.
- Unclear account/licence terms: Sweden.

**Global options:**
- **Esri World Imagery:** its terms expect an ArcGIS account/key and it isn't for offline export, so it can't be a default; at most an opt-in with the user's own key. The no-key endpoint answers, but that isn't permission.
- **Google, Bing, Mapbox, Maxar:** ruled out by keys and caching restrictions.
- **EOX:** keep as the global fallback (2023 is CC BY-NC-SA, fine for a free mod).

**Risks:**
- **Colour mismatch:** the aerial photos came out about 1.3× brighter (median) and more neutral than EOX's warm tone. Without colour matching you'll see seams between near and far tiles and at borders.
- **Seasons:** Flanders, the Netherlands and Denmark are leaf-off.
- **Services move or close:** Norway, Hamburg and Spain's main host all changed or failed today.

**Integration plan for `server/imagery.py`:**
1. Move the sources into a data file. Each entry gets a request type (XYZ, TMS, WMTS, WMS, ArcGIS export), a coverage polygon, a priority, attribution, a caching policy and an optional user-supplied key.
2. Turn WMS and ArcGIS sources into virtual XYZ tiles so they reuse the existing cache, missing-tile markers and fallback chain.
3. Pick the source list per tile from the coverage polygons, then fall back to EOX 2023 and 2016. The existing coverage probes handle patchy areas.
4. Match colours per source and region against a shared target, blending across borders over 1–2 km.
5. Build the attribution line from the sources visible in the last minute or so.
6. Cache open-licence imagery on the user's disk only (never ship it in the mod zip); don't cache Esri, Google, Bing or Mapbox at all.
7. First step: the eight easiest XYZ sources (swisstopo, IGN, PDOK, Luxembourg, basemap.at, ČÚZK, GSI, NSW), then the German and Belgian WMS, then NAIP and Maryland.

Scripts and raw results are in the same scratchpad: `imgscripts/probe.py`, `sources.py`, `sheet.py`, `gen_table.py`, and `imagery_sources/tiles/results.json`.

## Per-source table

| Region | Source (id) | Resolution / years | Licence, attribution | Key? | Request template | CRS / protocol | Live test 2026-10-10 (spot, z18 footprint) |
|---|---|---|---|---|---|---|---|
| World | EOX Sentinel-2 cloudless 2023 (`eox2023`) | 10 m (z14 native) | CC BY-NC-SA 4.0; 'Sentinel-2 cloudless 2023 by EOX IT Services GmbH (Contains modified Copernicus Sentinel data 2023)' | no | `https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2023_3857/default/g/{z}/{y}/{x}.jpg` | 3857 WMTS/XYZ | PASS 200 image/jpeg 15 kB 543 ms @ 47.3779,8.5403 |
| World | EOX Sentinel-2 cloudless 2016 (`eox2016`) | 10 m | CC BY 4.0; 'Sentinel-2 cloudless 2016 by EOX ...' | no | `https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless_3857/default/g/{z}/{y}/{x}.jpg` | 3857 XYZ | PASS 200 image/jpeg 10 kB 359 ms @ 47.3779,8.5403 |
| World | Esri World Imagery (`esri_world`) | ~0.3-1 m cities, 0.5-15 m elsewhere (z19+) | Esri Master License Agreement + E300 product terms; NOT open; attribution 'Esri, Vantor, Earthstar Geographics, GIS User Community'; 'not intended to export tiles for offline' | terms require ArcGIS account / Location Platform key (endpoint answers without one) | `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}` | 3857 XYZ | PASS 200 image/jpeg 14 kB 374 ms @ 47.3779,8.5403 |
| World (patches) | OpenAerialMap (drone/aerial uploads) (`oam_accra`) | 2-50 cm, per image | CC BY 4.0 per image (check each image's licence field); attribute provider | no | `https://tiles.openaerialmap.org/{image path}/{z}/{x}/{y} (per image, from api.openaerialmap.org/meta)` | 3857 XYZ per image | PASS 200 image/jpeg 32 kB 1043 ms @ 5.5490,-0.2200 |
| US | USGS The National Map ImageryOnly (`us_usgs`) | ~1.9 m at z16 (max z16) | Public domain; 'USGS The National Map' | no | `https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}` | 3857 XYZ | PASS 200 image/jpeg 29 kB 186 ms @ 39.2825,-76.5930 |
| US | USGS NAIP ImageServer (`us_naip`) | 0.6 m (some states 0.3 m), 2-3 yr cycle, leaf-on summer | Public domain (USDA FSA NAIP) | no | `https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?bbox={bbox3857}&bboxSR=3857&imageSR=3857&size=256,256&format=jpg&f=image` | ArcGIS exportImage (any CRS) | PASS 200 image/jpeg 17 kB 1509 ms @ 39.2825,-76.5930 |
| US-MD | MD iMAP Six-Inch Imagery 2023-2025 (`us_md_6in`) | 0.15 m (6 in), 2023 W shore / 2024 E shore / 2025 | Free distribution; acknowledge 'State of Maryland / MD iMAP, DoIT' (metadata terms) | no | `https://mdgeodata.md.gov/imagery/rest/services/SixInch/SixInchImagery2023_2024_2025/MapServer/export?bbox={bbox3857}&bboxSR=3857&imageSR=3857&size=256,256&format=jpg&f=image` | ArcGIS export (cache uses a non-standard 512-px grid, so not XYZ) | PASS 200 image/jpeg 26 kB 325 ms @ 39.2825,-76.5930 |
| US-NY | NYS ITS Orthoimagery 'Latest' (`us_nys`) | ~0.15-0.3 m (6 in-1 ft), rolling | NYS GIS Program Office orthos, free public use (verify exact wording) | no | `https://orthos.its.ny.gov/arcgis/rest/services/wms/Latest/MapServer/export?bbox={bbox3857}&bboxSR=3857&imageSR=3857&size=256,256&format=jpg&f=image` | ArcGIS export / WMS | PASS 200 image/jpeg 25 kB 454 ms @ 40.7580,-73.9855 |
| CA-ON | Ontario GEO Imagery Data Service 2018-2022 (`ca_on`) | 0.16-0.5 m (16 cm at Toronto) | Open Government Licence - Ontario for collections Ontario owns (SCOOP 2018, DRAPE 2019-20, ...); partner-funded ones may differ | no | `https://ws.geoservices.lrc.gov.on.ca/arcgis5/rest/services/AerialImagery/GEO_Imagery_Data_Service_2018to2022/ImageServer/exportImage?bbox={bbox3857}&bboxSR=3857&imageSR=3857&size=256,256&format=jpg&f=image` | ArcGIS exportImage | PASS 200 image/jpeg 13 kB 342 ms @ 43.6426,-79.3871 |
| BR-SP (city) | GeoSampa ORTO_RGB_2020 (Sao Paulo city) (`br_sp`) | ~0.1-0.2 m, 2020 | City open data (AccessConstraints NONE in caps); exact licence not verified | no | `https://raster.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wms?...&LAYERS=ORTO_RGB_2020&CRS=EPSG:900913&BBOX={bbox3857}` | WMS (3857 as EPSG:900913, 4326, SIRGAS UTM) | PASS 200 image/jpeg 14 kB 1039 ms @ -23.5505,-46.6333 |
| CH | swisstopo SWISSIMAGE 10 cm (`ch_swisstopo`) | 0.1 m (0.25 m Alps), 3-yr cycle | swisstopo OGD: free incl. commercial; source mandatory: '(c) swisstopo'; fair-use limits on geo.admin.ch | no | `https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.swissimage/default/current/3857/{z}/{x}/{y}.jpeg` | 3857 XYZ (also LV95) | PASS 200 image/jpeg 19 kB 722 ms @ 47.3779,8.5403 |
| FR | IGN Geoplateforme ORTHOIMAGERY.ORTHOPHOTOS (BD ORTHO) (`fr_ign`) | 0.2 m (some 0.05-0.15 m), 3-yr cycle | Licence Ouverte / Etalab 2.0 (IGN open data since 2021; layer licence not restated in caps); attribution 'IGN' | no | `https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=ORTHOIMAGERY.ORTHOPHOTOS&STYLE=normal&TILEMATRIXSET=PM&FORMAT=image/jpeg&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}` | 3857 WMTS (PM) | PASS 200 image/jpeg 16 kB 996 ms @ 48.8530,2.3499 |
| ES | IGN PNOA WMTS (www.ign.es) (`es_pnoa`) | 0.25 m (0.15 m recent) | CC BY 4.0; 'PNOA cedido por (c) Instituto Geografico Nacional' | no | `https://www.ign.es/wmts/pnoa-ma?request=GetTile&service=WMTS&VERSION=1.0.0&Layer=OI.OrthoimageCoverage&Style=default&Format=image/jpeg&TileMatrixSet=GoogleMapsCompatible&TileMatrix={z}&TileRow={y}&TileCol={x}` | 3857 WMTS | FAIL HTTP 504 text/html 10132 ms @ 40.4169,-3.7035 |
| ES | IGN PNOA TMS mirror (idee.es) (`es_pnoa_tms`) | 0.25 m (0.15 m recent) | CC BY 4.0 (as above) | no | `https://tms-pnoa-ma.idee.es/1.0.0/pnoa-ma/{z}/{x}/{-y}.jpeg  ({-y} = 2^z-1-y, TMS)` | 3857 TMS | PASS 200 image/jpeg 17 kB 600 ms @ 40.4169,-3.7035 |
| ES-CT | ICGC Catalonia orto (`es_ct_icgc`) | 0.25 m | CC BY 4.0; 'Institut Cartografic i Geologic de Catalunya' (from knowledge, verify) | no | `https://geoserveis.icgc.cat/icc_mapesmultibase/noutm/wmts/orto/GRID3857/{z}/{x}/{y}.jpeg` | 3857 XYZ | PASS 200 image/jpeg 33 kB 459 ms @ 41.4036,2.1744 |
| PT | DGT Ortos2018 (`pt_dgt2018`) | 0.25 m, 2018, all mainland | as above | no | `https://cartografia.dgterritorio.gov.pt/ortos2018/service?...&LAYERS=Ortos2018-RGB&SRS=EPSG:3857&FORMAT=image/png` | WMS 1.1.1 | PASS 200 image/png 38 kB 700 ms @ 38.7075,-9.1364 |
| PT (north) | DGT Ortos2021 (`pt_dgt2021`) | 0.25 m, 2021, north mainland | DGT open data, Fees/AccessConstraints none (licence text not checked; DGT uses CC BY 4.0 for open data) | no | `https://cartografia.dgterritorio.gov.pt/ortos2021/service?SERVICE=WMS&REQUEST=GetMap&VERSION=1.1.1&LAYERS=Ortos2021-RGB&SRS=EPSG:3857&BBOX={bbox3857}&WIDTH=256&HEIGHT=256&FORMAT=image/png` | WMS 1.1.1 (3857, 3763); also WMTS in PT-TM06 only | PASS 200 image/png 46 kB 708 ms @ 41.1413,-8.6110 |
| IT | Geoportale Nazionale (MASE) ortofoto colore 2012 (`it_pcn2012`) | 0.5 m, 2012 (old) | CC BY 4.0 per INSPIRE records; Fees none | no | `http://wms.pcn.minambiente.it/ogc?map=/ms_ogc/WMS_v1.3/raster/ortofoto_colore_12.map&SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&LAYERS=OI.ORTOIMMAGINI.2012.33 (.32 west of 12E)&CRS=EPSG:3857&BBOX={bbox3857}` | WMS (http only) | PASS 200 image/jpeg 21 kB 1022 ms @ 41.8902,12.4922 |
| IT-TOS | Regione Toscana OFC (layer rt_ofc.5k22) (`it_toscana`) | ~0.2 m, 2022 (assumed from layer name) | Fees/AccessConstraints none; region data CC BY 4.0 (verify) | no | `https://www502.regione.toscana.it/ows_ofc/com.rt.wms.RTmap/wms?map=owsofc&SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&LAYERS=rt_ofc.5k22.32bit&CRS=EPSG:3857&BBOX={bbox3857}` | WMS | PASS 200 image/jpeg 12 kB 835 ms @ 43.7731,11.2560 |
| NL | PDOK Luchtfoto Actueel_orthoHR (`nl_pdok_hr`) | 0.08 m, yearly, leaf-off spring | CC BY 4.0; 'Beeldmateriaal.nl' (from knowledge) | no | `https://service.pdok.nl/hwh/luchtfotorgb/wmts/v1_0/Actueel_orthoHR/EPSG:3857/{z}/{x}/{y}.jpeg` | 3857 XYZ | PASS 200 image/jpeg 21 kB 762 ms @ 52.3731,4.8926 |
| NL | PDOK Luchtfoto Actueel_ortho25 (`nl_pdok_25`) | 0.25 m, yearly | CC BY 4.0 | no | `https://service.pdok.nl/hwh/luchtfotorgb/wmts/v1_0/Actueel_ortho25/EPSG:3857/{z}/{x}/{y}.jpeg` | 3857 XYZ | PASS 200 image/jpeg 21 kB 657 ms @ 52.3731,4.8926 |
| BE-VLG | Digitaal Vlaanderen OMWRGB25VL (winter 2025) (`be_vl`) | 0.25 m, yearly winter (leaf-off) | Modellicentie Gratis Hergebruik (free reuse, attribution 'Digitaal Vlaanderen') | no | `https://geo.api.vlaanderen.be/omw/wms?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&LAYERS=OMWRGB25VL&CRS=EPSG:3857&BBOX={bbox3857}&WIDTH=256&HEIGHT=256&FORMAT=image/jpeg` | WMS (also WMTS omwrgbmrvl) | PASS 200 image/jpeg 20 kB 542 ms @ 51.2213,4.4051 |
| BE-WAL | SPW ORTHO_LAST (`be_wal`) | 0.25 m (ORTHO_LAST = latest Wallonia mosaic) | SPW free reuse licence (verify wording); attribution 'SPW' | no | `https://geoservices.wallonie.be/arcgis/services/IMAGERIE/ORTHO_LAST/MapServer/WMSServer?...&LAYERS=0&CRS=EPSG:3857` | WMS / ArcGIS | PASS 200 image/jpeg 23 kB 657 ms @ 50.4669,4.8675 |
| BE-BRU | UrbIS Ortho (latest; 2024 layers) (`be_bru`) | 0.05 m | CC0 for 2022 sets, CC BY 4.0 for 2015-2019 (Geobru catalogue); latest layer licence not re-checked | no | `https://geoservices-urbis.irisnet.be/geoserver/urbisgrid/ows?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&LAYERS=Ortho&CRS=EPSG:3857&BBOX={bbox3857}` | WMS | PASS 200 image/jpeg 16 kB 1553 ms @ 50.8467,4.3525 |
| LU | geoportail.lu ortho_latest (`lu_geoportail`) | ~0.1-0.2 m, yearly | CC0 (open data portal; from knowledge) | no | `https://wmts1.geoportail.lu/opendata/wmts/ortho_latest/GLOBAL_WEBMERCATOR_4_V3/{z}/{x}/{y}.jpeg` | 3857 XYZ | PASS 200 image/jpeg 25 kB 648 ms @ 49.6116,6.1319 |
| DE-BY | LDBV DOP20 (open) (`de_by_dop20`) | 0.2 m, 2-yr cycle | CC BY 4.0 | no | `https://geoservices.bayern.de/od/wms/dop/v1/dop20?...&LAYERS=by_dop20c&CRS=EPSG:3857` | WMS | PASS 200 image/jpeg 12 kB 429 ms @ 48.1374,11.5755 |
| DE-BY | LDBV DOP40 (open) (`de_by_dop40`) | 0.4 m | CC BY 4.0; 'Bayerische Vermessungsverwaltung' | no | `https://geoservices.bayern.de/od/wms/dop/v1/dop40?...&LAYERS=by_dop40c&CRS=EPSG:3857` | WMS | PASS 200 image/jpeg 12 kB 679 ms @ 48.1374,11.5755 |
| DE-NW | Geobasis NRW DOP (`de_nw`) | 0.1 m (DOP10) | DL-DE Zero 2.0 (from knowledge) | no | `https://www.wms.nrw.de/geobasis/wms_nw_dop?...&LAYERS=nw_dop_rgb&CRS=EPSG:3857` | WMS (WMTS only in UTM32) | PASS 200 image/jpeg 12 kB 1095 ms @ 50.9413,6.9583 |
| DE-BW | LGL-BW DOP20 (`de_bw`) | 0.2 m | DL-DE BY 2.0 (LGL open data; verify) | no | `https://owsproxy.lgl-bw.de/owsproxy/ows/WMS_LGL-BW_ATKIS_DOP_20_C?...&LAYERS=IMAGES_DOP_20_RGB&CRS=EPSG:3857` | WMS | PASS 200 image/jpeg 12 kB 1257 ms @ 48.7784,9.1800 |
| DE-NI | LGLN DOP20 (`de_ni`) | 0.2 m | DL-DE BY 2.0 | no | `https://opendata.lgln.niedersachsen.de/doorman/noauth/dop_wms?...&LAYERS=ni_dop20&CRS=EPSG:3857` | WMS | PASS 200 image/jpeg 12 kB 1349 ms @ 52.3745,9.7386 |
| DE-BE | Berlin TrueDOP 2024 (`de_be`) | 0.2 m true ortho (no building lean) | DL-DE Zero 2.0 (from knowledge) | no | `https://gdi.berlin.de/services/wms/truedop_2024?...&LAYERS=truedop_2024&CRS=EPSG:3857` | WMS | PASS 200 image/jpeg 12 kB 634 ms @ 52.5163,13.3777 |
| DE-SN | GeoSN DOP RGB (`de_sn`) | 0.2 m | DL-DE BY 2.0 | no | `https://geodienste.sachsen.de/wms_geosn_dop-rgb/guest?...&LAYERS=sn_dop_020&CRS=EPSG:3857` | WMS | PASS 200 image/jpeg 21 kB 1274 ms @ 51.0519,13.7416 |
| DE-HE | HVBG DOP20 (free images) (`de_he`) | 0.2 m | DL-DE Zero/BY 2.0 (Hesse open since 2024; verify) | no | `https://www.gds-srv.hessen.de/cgi-bin/lika-services/ogc-free-images.ows?...&LAYERS=he_dop20_rgb&CRS=EPSG:3857` | WMS | PASS 200 image/jpeg 12 kB 756 ms @ 50.1109,8.6821 |
| DE-BB | LGB DOP20c (`de_bb`) | 0.2 m | DL-DE BY 2.0 | no | `https://isk.geobasis-bb.de/mapproxy/dop20c/service/wms?...&LAYERS=bebb_dop20c&CRS=EPSG:3857` | WMS | PASS 200 image/jpeg 26 kB 1727 ms @ 52.3989,13.0657 |
| DE-RP | LVermGeo RP DOP20 (`de_rp`) | 0.2 m | DL-DE BY 2.0 | no | `https://geo4.service24.rlp.de/wms/rp_dop20.fcgi?...&LAYERS=rp_dop20&CRS=EPSG:3857` | WMS | PASS 200 image/jpeg 20 kB 692 ms @ 49.9929,8.2473 |
| DE-SH | LVermGeo SH DOP20 (OpenGBD) (`de_sh`) | 0.2 m | DL-DE BY 2.0 (Open GBD) | no | `https://dienste.gdi-sh.de/WMS_SH_DOP20col_OpenGBD?...&LAYERS=sh_dop20_rgb&CRS=EPSG:3857` | WMS | PASS 200 image/jpeg 26 kB 929 ms @ 54.3233,10.1228 |
| DE-MV | LAiV MV DOP (`de_mv`) | 0.2 m | DL-DE BY 2.0; service stamps '(c) GeoBasis-DE/M-V' into every image | no | `https://www.geodaten-mv.de/dienste/adv_dop?...&LAYERS=mv_dop&CRS=EPSG:3857` | WMS | PASS 200 image/jpeg 9 kB 686 ms @ 54.0887,12.1405 |
| DE-ST | LVermGeo ST DOP20 OpenData (`de_st`) | 0.2 m | DL-DE BY 2.0 | no | `https://www.geodatenportal.sachsen-anhalt.de/wss/service/ST_LVermGeo_DOP_WMS_OpenData/guest?...&LAYERS=lsa_lvermgeo_dop20_2&CRS=EPSG:3857` | WMS | PASS 200 image/jpeg 44 kB 768 ms @ 52.1205,11.6276 |
| DE-SL | LVGL Saarland DOP20 2023 (`de_sl`) | 0.2 m, 2023 | AccessConstraints 'noLimitations'; DL-DE BY 2.0 (verify) | no | `https://geoportal.saarland.de/freewms/dop2023?...&LAYERS=sl_dop20_rgb&CRS=EPSG:3857` | WMS | PASS 200 image/jpeg 15 kB 759 ms @ 49.2354,6.9969 |
| DE-HB | GeoInformation Bremen DOP10 2025 (`de_hb`) | 0.1 m, 2025 | open, no access limits (licence text not checked) | no | `https://geodienste.bremen.de/wms_dop_lb?...&LAYERS=dop10_2025_HB&CRS=EPSG:3857` | WMS | PASS 200 image/jpeg 13 kB 597 ms @ 53.0758,8.8072 |
| DE-TH | TLBG DOP (th_dop, 20 cm) (`de_th`) | 0.2 m | AccessConstraints 'Es gelten keine Beschraenkungen'; DL-DE BY 2.0 (verify) | no | `https://www.geoproxy.geoportal-th.de/geoproxy/services/DOP?...&LAYERS=th_dop&CRS=EPSG:3857` | WMS | PASS 200 image/jpeg 16 kB 638 ms @ 50.9787,11.0328 |
| DE-HH | LGV Hamburg DOP (`de_hh`) | 0.2 m (yearly spring) | DL-DE BY 2.0 | no | `https://geodienste.hamburg.de/HH_WMS_DOP (404: endpoint name changed, not found)` | WMS | FAIL HTTP 404 text/html 774 ms @ 53.5503,9.9930 |
| AT | basemap.at Orthofoto (`at_basemap`) | ~0.29 m (0.15 m some Laender) | CC BY 4.0; 'Datenquelle: basemap.at' | no | `https://maps.wien.gv.at/basemap/bmaporthofoto30cm/normal/google3857/{z}/{y}/{x}.jpeg` | 3857 XYZ | PASS 200 image/jpeg 14 kB 592 ms @ 48.2085,16.3731 |
| CZ | CUZK ORTOFOTO_WM (`cz_cuzk`) | 0.125-0.25 m, 2-yr cycle | CC BY 4.0 since 2023-07-01 ('(c) CUZK') | no | `https://ags.cuzk.gov.cz/arcgis1/rest/services/ORTOFOTO_WM/MapServer/tile/{z}/{y}/{x}` | 3857 XYZ | PASS 200 image/jpeg 24 kB 694 ms @ 50.0875,14.4213 |
| PL | GUGiK Geoportal ORTO HighResolution (`pl_geoportal`) | <=0.10 m (HighResolution); StandardResolution 0.25 m | Free for any purpose under Polish geodesy law (no licence text); credit 'GUGiK / geoportal.gov.pl' | no | `https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/HighResolution?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0&LAYERS=Raster&CRS=EPSG:4326&BBOX={lat0,lon0,lat1,lon1}` | WMS (4326, 2180; also WMTS) | PASS 200 image/jpeg 13 kB 1106 ms @ 52.2497,21.0122 |
| SK | GKU ZBGIS Ortofoto (`sk_zbgis`) | 0.2-0.25 m, 2020-2022 cycle | CC BY 4.0; 'GKU Bratislava, NLC' | no | `https://zbgis.skgeodesy.sk/zbgis/rest/services/Ortofoto/MapServer/tile/{z}/{y}/{x} (and WMTS S-JTSK at zbgisws.skgeodesy.sk)` | ArcGIS tiles (3857?) / S-JTSK EPSG:5514 | FAIL URLError: <urlopen error timed out> @ 48.1435,17.1077 |
| HR | DGU DOF 2021-2022 (`hr_dgu2122`) | ~0.5 m (DOF5) | Otvorena dozvola (Croatian open licence); anonymous WMS has a 'GEOPORTAL' watermark in every image | no (auth endpoint without watermark needs login) | `https://geoportal.dgu.hr/services/inspire/orthophoto_2021_2022/wms?...&LAYERS=OI.OrthoimageCoverage&CRS=EPSG:4326` | WMS (3765, 4326, 3035) | PASS 200 image/jpeg 17 kB 906 ms @ 45.8131,15.9772 |
| HR | DGU DOF 2023 (east/south half) (`hr_dgu2023`) | ~0.5 m | as above, watermarked | no | `https://geoportal.dgu.hr/services/inspire/orthophoto_2023/wms?...&LAYERS=OI.OrthoimageCoverage&CRS=EPSG:4326` | WMS | PASS 200 image/jpeg 19 kB 822 ms @ 43.5081,16.4402 |
| DK | Dataforsyningen orto_foraar (spring) (`dk_nokey`) | 0.12 m, yearly spring | Free Danish geodata terms (attribution 'Klimadatastyrelsen'); verify | yes, free account token | `https://api.dataforsyningen.dk/orto_foraar_webm_DAF?SERVICE=WMTS&REQUEST=GetTile&...&LAYER=orto_foraar_webm&TILEMATRIXSET=DFD_GoogleMapsCompatible&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&token={token}` | 3857 WMTS | FAIL HTTP 403 text/xml 592 ms @ 55.6761,12.5683 |
| NO | Kartverket Norge i bilder (`no_nib`) | 0.1-0.5 m | Restricted to Norge digitalt parties; open caches being closed | token (not public) | `https://opencache.statkart.no/gatekeeper/gk/gk.open_nib_web_mercator_wmts_v2?... (old) / https://tilecache.norgeibilder.no/wmts/webmercator (499 Token Required)` | WMTS | FAIL URLError: <urlopen error [Errno 113] No route to host> @ 59.9075,10.7531 |
| FI | NLS open WMTS ortokuva (`fi_nls_nokey`) | ~0.5 m in open service (0.25 m+ product) | CC BY 4.0 (NLS open data); 'Maanmittauslaitos'; open API 'for testing and light use' | yes, free personal API key | `https://avoin-karttakuva.maanmittauslaitos.fi/avoin/wmts/1.0.0/ortokuva/default/WGS84_Pseudo-Mercator/{z}/{y}/{x}.jpg?api-key={key}` | 3857 WMTS | FAIL HTTP 401  658 ms @ 60.1699,24.9384 |
| EE | Maa-amet foto (TMS) (`ee_maaamet`) | 0.1-0.25 m, cities yearly | Maa-amet open data licence (free incl. commercial; cite 'Ortofoto: Maa-amet <year>') | no | `https://tiles.maaamet.ee/tm/tms/1.0.0/foto@GMC/{z}/{x}/{-y}.jpg` | 3857 TMS (flipped y) | PASS 200 image/jpeg 16 kB 849 ms @ 59.4370,24.7536 |
| LV | LGIA OPEN_DATA Latvijas_pilsetu_ortofotokartes (`lv_lgia_city`) | ? | CC BY 4.0 / CC0 (LGIA open data, cycles <= 6) | no | `https://wms.lgia.gov.lv/open/rest/services/OPEN_DATA/Latvijas_pilsetu_ortofotokartes/MapServer/export?...` | ArcGIS, cache in LKS-92 EPSG:3059 | FAIL 200 but blank image (2421 B) @ 56.9496,24.1052 |
| LV | LGIA OPEN_DATA Ortofoto3_rgb (2007-08) (`lv_lgia3`) | 0.5 m? | as above | no | `https://wms.lgia.gov.lv/open/rest/services/OPEN_DATA/Ortofoto3_rgb/MapServer/export?...` | ArcGIS, EPSG:3059 | FAIL 200 but blank image (2419 B) @ 56.9496,24.1052 |
| JP | GSI seamlessphoto (`jp_gsi`) | ~0.2-0.4 m (z18 max), mixed years | GSI content terms: software that loads GSI tiles live from GSI servers needs only attribution ('国土地理院' + link to tile list), no application | no | `https://cyberjapandata.gsi.go.jp/xyz/seamlessphoto/{z}/{x}/{y}.jpg` | 3857 XYZ | PASS 200 image/jpeg 15 kB 442 ms @ 35.6812,139.7671 |
| TW | NLSC PHOTO2 orthophoto (`tw_nlsc`) | ~0.25 m | Not verified (NLSC services generally under Open Government Data License v1.0) | no | `https://wmts.nlsc.gov.tw/wmts/PHOTO2/default/GoogleMapsCompatible/{z}/{y}/{x}` | 3857 WMTS | PASS 200 image/jpeg 22 kB 829 ms @ 25.0340,121.5645 |
| KR | VWorld Satellite (`kr_vworld_nokey`) | ~0.25-0.5 m | VWorld terms (free; data-licence claims on derived data) | yes, free key (Korean registration) | `https://api.vworld.kr/req/wmts/1.0.0/{key}/Satellite/{z}/{y}/{x}.jpeg` | 3857 WMTS | FAIL RemoteDisconnected: Remote end closed connection without res @ 37.5665,126.9780 |
| NZ | LINZ Basemaps aerial (`nz_linz_nokey`) | 0.075-0.3 m urban, 0.3-0.5 m rural | CC BY 4.0; 'LINZ CC BY 4.0' + link to LINZ data attribution | yes: free standard key (no registration, 1000 req/min, 1M/month, 90-day expiry) or developer key on request | `https://basemaps.linz.govt.nz/v1/tiles/aerial/3857/{z}/{x}/{y}.webp?api={key}` | 3857 XYZ (also NZTM 2193) | FAIL HTTP 400 application/json 1563 ms @ -41.2865,174.7762 |
| AU-NSW | NSW Spatial Services NSW_Imagery (`au_nsw`) | 0.1-0.5 m | CC BY 4.0 ('(c) Spatial Services NSW'; from knowledge) | no | `https://maps.six.nsw.gov.au/arcgis/rest/services/public/NSW_Imagery/MapServer/tile/{z}/{y}/{x}` | 3857 XYZ | PASS 200 image/jpeg 13 kB 1055 ms @ -33.8568,151.2153 |
| AU-VIC | Vicmap Basemaps AERIAL_WM_256 (`au_vic`) | ~0.1-0.4 m | CC BY 4.0 ('(c) State of Victoria'; verify) | no | `https://base.maps.vic.gov.au/wmts/AERIAL_WM_256/EPSG:3857:256/{z}/{x}/{y}.png` | 3857 XYZ (PNG, ~125 kB/tile) | PASS 200 image/png 123 kB 1366 ms @ -37.8183,144.9671 |
| AU-QLD | QLD LatestStateProgram_AllUsers (`au_qld`) | 0.1-0.5 m (state program) | CC BY 4.0 ('(c) State of Queensland'; verify) | no | `https://spatial-img.information.qld.gov.au/arcgis/rest/services/Basemaps/LatestStateProgram_AllUsers/ImageServer/exportImage?bbox={bbox3857}&bboxSR=3857&imageSR=3857&size=256,256&format=jpg&f=image` | ArcGIS exportImage | PASS 200 image/jpeg 20 kB 1445 ms @ -27.4698,153.0251 |
| AU-TAS | theLIST Basemaps/Orthophoto (`au_tas`) | ~0.1-0.5 m | theLIST terms ('(c) State of Tasmania'); licence not verified | no | `https://services.thelist.tas.gov.au/arcgis/rest/services/Basemaps/Orthophoto/MapServer/tile/{z}/{y}/{x}` | 3857 XYZ | PASS 200 image/jpeg 18 kB 1598 ms @ -42.8821,147.3272 |

