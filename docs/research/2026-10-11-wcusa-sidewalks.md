# How West Coast USA builds curbs, sidewalks and storm drains (2026-10-11)

Asked by the user after the first raised sidewalks (MeshRoad slabs): "having physical curbs is a nice
first step, but they don't look very good. Look at other maps like West Coast to see how they model
and decorate the curbs, sidewalks, and storm drains. Also make sure you keep the generation fast and
don't tank the fps." Read-only study of the game's own level files (`content/levels/*.zip`,
`content/assets/`). Scripts: `wcusa_study.py`, `dae_study.py`, `dae_mats.py` (session scratch; they
count classes, shapes, decal-road materials, forest items and decals, and sum Collada triangles
per material).

## Objects
- West Coast USA: 22,067 TSStatic, 12,752 DecalRoad, **0 MeshRoad**.
- Sidewalks and curbs are **one modelled mesh per district**: 64 `sidewalk_<district>.dae`
  (`sidewalk_chinatown`, `_suburb1`, `_boulevard`, `_residential4`, ...), 231k triangles in all,
  each with a collision mesh (`Colmesh_*`) and distance LODs (`*_L900`, `*_L1800`, a
  `lod_vertcol` material for the far LOD). They also hold the gutter (`gutter1`), tactile paving at
  ramps, planters, retaining walls and stairs.
- Plus 427 `s_curb.dae` pieces (2.6 m, 106 triangles) and `curbramp.dae` (1.15 x 0.65 m).

## Materials (triangles across the 64 sidewalk meshes)
| material | triangles | what |
|---|---|---|
| `curbs` | 66,747 | the curb profile: `/assets/materials/trim/concrete/curbs`, a 1024 x 512 trim sheet of 8 bands (3 plain, red, red, yellow "TOW AWAY", white "NO PARKING", green "MON-SAT"); in each band the light upper ~60 % is the curb top / nose, the darker lower part the face; it tiles along the curb with joints every ~1/3 of the width |
| `slabs_large` | 59,373 | slab tops (no material definition in the level files; maps to a shared asset) |
| `sidewalk1` | 15,547 | `/assets/materials/tileable/concrete/sidewalk1`: 4096 x 1024, 5 sidewalk strips with panel joints along them |
| `gutter1` | 3,936 | the gutter pan, as mesh (also used as a decal road) |
| `tactile_indicator` | 50 | at curb ramps |

## Storm drains
Not in the sidewalk meshes. Decal-road materials in the shared library:
`/assets/materials/decalroad/detail/m_metal_grid_drain` (a slotted metal grate, 512 x 2048) and
`m_concrete_drain` (a concrete channel). Driver Training's `art/road/main.materials.json` defines them.

## Cost
- One draw call per material per district mesh. Our first cut (a MeshRoad per sidewalk piece, with
  top, side and bottom materials) cost about three per piece.
- In game at Fells Point: 89 MeshRoads, about +0.2 ms render time (within noise). Leaked objects
  from Lua reloads (3,558 DecalRoads for 1,011 tracked) were a bigger cost (fixed).

## What we took
`server/sidewalks.py`: one mesh per road tile, swept along the sidewalk runs with a curb profile in
the `curbs` plain band and `sidewalk1` tops, collision from the visible mesh. Storm drain grates as
small DecalRoads in the gutter at corners. See docs/ARCHITECTURE.md "Raised sidewalks".
Not yet: curb ramps with tactile paving, painted curbs (fire lanes, loading zones) by rule, LODs.
