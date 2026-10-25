"""NRails: the functions upstream's files call, each from one line marked "# NRails hook".

    earthd.main / peerwork.main   boot(argv)                    the cache folder (nrails.paths) when none is given
    earthd.ANCHOR_TILE_FILES      ANCHOR_TILE_FILES             the shape file stems an anchor's prune must also clear
    grading._plan                 road_profile(...)             the road classes' profile limits (nrails.profile)
    blockworker.roads_tile,       tile_extras(...)              the tile's track (nrails.rails) and the deck mesh
      earthd.build_roads_tile                                   with its approach slabs (nrails.bridges)
    roads.shape_files             shape_files(aid, tx, ty)      the track's shape files (pooled slots)
    roads.write_tile              write_extras(...)             the track's shapes and fields in the tile
    blockworker._tunnel_holes,    terrain_holes(...)            the terrain cut at the rail tunnels' portals
      earthd._tunnel_holes
    roads.BridgeProfiles._load    load_rails(...)               the tracks join the bridge solver's ground lines ...
    roads.BridgeProfiles._solve   is_rail_key(k),               ... not as roads (no junction at grade) but as
                                  deck_rail_crossings(...)      crossings with the railway's clearance (nrails.decks)

Every hook is failure-safe: an exception here costs the tile its NRails parts (logged once per kind), never the
upstream content. Light at import (shape_files runs where numpy-heavy modules must not load).
"""
import logging
import os
import sys

log = logging.getLogger("earthd.nrails")

ANCHOR_TILE_FILES = ("tunnel", "rail", "railcol", "railx", "railtun", "railsw")
RAIL_PARTS_MAX = 4              # rails.PARTS_MAX (here: shape_files must stay light)
RAILCOL_PARTS_MAX = 12          # rails.COL_PARTS_MAX
RAILSW_MAX = 48                 # rails.SW_SHAPES_MAX
_FAILS = set()


def _once(what, e):
    kind = f"{what}: {type(e).__name__}: {e}"[:240]
    if kind not in _FAILS:
        _FAILS.add(kind)
        log.warning("NRails %s", kind, exc_info=e)


def boot(argv=None):
    """The server's command line with --cache-dir set to nrails.paths.default_cache_dir() when it names none (upstream's
    default ~/.cache/beamng-earth: a junction on some PCs, whose renames failed, 2026-10-24). argv None: sys.argv is
    changed in place (earthd.main parses sys.argv). Returns the (new) argv."""
    from nrails import paths
    args = sys.argv[1:] if argv is None else list(argv)
    if not any(a == "--cache-dir" or a.startswith("--cache-dir=") for a in args):
        args += ["--cache-dir", paths.default_cache_dir()]
    if argv is None:
        sys.argv[1:] = args
    return args


# Upstream's grading constants NRails sets otherwise (BNGE_ROAD_TUNE=off: upstream's). The street under the first span
# of a motorway viaduct by a village stood 1 m under the deck (the user's run, 2026-10-24: "l'autoroute descend au
# niveau de la route du dessous"): grading lowers a street under a short never-raised overpass (UNDER_*), but took this
# one, crossing 4.6 m from the bridge's end, for a junction at grade (APPROACH_MIN_CROSS_M 6 m: a road meeting a bridge
# at its end crosses it within its own half width, 4 m), and the viaduct, 121 m long, for no short span (120 m).
TUNE = {"APPROACH_MIN_CROSS_M": 4.0, "UNDER_MAX_BRIDGE_M": 250.0}


UNDER_KEEP = {"motorway", "trunk"}     # classes grading._lower_underpasses never lowers (lower_underpasses)


def lower_underpasses(grader, key, plans, specs):
    """grading.Grader._make_cell: upstream's _lower_underpasses (a street under a short overpass lowered for its
    clearance) but never a motorway or trunk carriageway: a link's bridge over a motorway by a test town (its deck read
    at the ground's level) had the motorway's own plan lowered 5 m, a pit across its lanes (the user's run,
    2026-10-25). Those roads are where the map and the terrain have them; the deck over them is what must climb.
    BNGE_ROAD_TUNE=off: upstream's."""
    if os.environ.get("BNGE_ROAD_TUNE", "on") == "off":
        return grader._lower_underpasses(key, plans)
    idx = [i for i, sp in enumerate(specs) if getattr(sp, "cls", None) not in UNDER_KEEP]
    if len(idx) == len(plans):
        return grader._lower_underpasses(key, plans)
    sub = [plans[i] for i in idx]
    grader._lower_underpasses(key, sub)
    for i, p in zip(idx, sub):
        plans[i] = p


def tune(name, upstream):
    """grading's constant `name` as NRails sets it (TUNE), upstream's otherwise."""
    if os.environ.get("BNGE_ROAD_TUNE", "on") == "off":
        return upstream
    return TUNE.get(name, upstream)


def road_profile(zs, z, step, spec, smooth):
    """grading._plan: the built road's smoothed profile zs (from the raw z) after the class limits."""
    try:
        from nrails import profile
        return profile.road_profile(zs, z, step, spec, smooth)
    except Exception as e:      # noqa: BLE001 - upstream's profile rather than none
        _once("road profile", e)
        return zs


class Extras:
    """What NRails adds to a road tile: the track (rails.RailTile or None)."""

    def __init__(self, rail=None):
        self.rail = rail
        self.walls_cut = False          # the road tile's retaining walls were cut (its tunnel mesh to be made again)

    def tunnel_mesh(self, tmesh, chunks, origin, walls):
        """blockworker / earthd: the tile's tunnel mesh (roadmesh.tunnel: its tubes and retaining walls), made again
        when tile_extras cut its walls."""
        if not self.walls_cut:
            return tmesh
        try:
            import roadmesh
            return roadmesh.tunnel(chunks, origin, walls)
        except Exception as e:      # noqa: BLE001
            _once("tunnel mesh without the walls on the track", e)
            return tmesh


def tile_extras(frame, tx, ty, cell_fn, elev, chunks, ctx, dmesh, md=None, deck_parts=None, props=None, wires=None,
                walls=None):
    """(deck mesh, Extras) of a road tile being built: dmesh with the approach slabs past its abutments
    (nrails.bridges), and its track (nrails.rails). cell_fn(key): a map cell's "roads" layer; md: the map data
    (mapdata.MapData: the stations' platforms from its "infrastructure" layer), None: no platforms. deck_parts:
    (piers, beams) roadmesh.deck made dmesh with: the decks over the track too low for their girders are made
    again as thin slabs (nrails.thin). props, wires (lists): the street furniture and its wires, changed in place:
    none on the track (nrails.clearway)."""
    rt = rail_tile(frame, tx, ty, cell_fn, elev, chunks, md)
    walls_cut = False
    if rt is not None and rt.lines:
        try:
            from nrails import clearway
            if props:
                props[:] = clearway.clear_props(props, rt.lines)
            if wires:
                clearway.clear_wires(wires, rt.lines)
            if walls:
                walls_cut = clearway.clear_walls(walls, rt.lines) > 0
        except Exception as e:      # noqa: BLE001 - upstream's furniture
            _once(f"furniture on the track of road tile {tx}_{ty}", e)
    if rt is not None and deck_parts is not None and dmesh is not None:
        try:
            from nrails import thin
            import roadmesh
            import roads
            from nrails import clearway
            piers, beams = deck_parts
            piers, dropped = clearway.clear_piers(piers, rt.lines)
            if thin.mark(chunks, rt.lines) + thin.mark(ctx, rt.lines) + dropped:
                x0, y0, _, _ = roads.tile_bbox(tx, ty)
                dmesh = roadmesh.deck(chunks, (x0, y0, 0.0), thin.raise_piers(piers, chunks), ctx, beams)
        except Exception as e:      # noqa: BLE001 - upstream's decks
            _once(f"thin decks of road tile {tx}_{ty}", e)
    try:
        from nrails import bridges
        dmesh = bridges.with_slabs(dmesh, ctx, tx, ty)
    except Exception as e:      # noqa: BLE001
        _once("approach slabs", e)
    ex = Extras(rt)
    ex.walls_cut = walls_cut
    return dmesh, ex


def clear_tracks(items, frame, tx, ty, cells):
    """blockworker.roads_tile / earthd.build_roads_tile: the tile's buildings (buildings.road_tile_items) without
    those standing on a track (nrails.stations.clear_tracks: platform canopies the ML footprints took for buildings)."""
    if not items:
        return items
    try:
        from nrails import rails, stations
        if not rails.enabled():
            return items
        return stations.clear_tracks(items, frame, tx, ty, cells)
    except Exception as e:      # noqa: BLE001 - the buildings as upstream has them
        _once(f"buildings on the tracks of road tile {tx}_{ty}", e)
        return items


def rail_tile(frame, tx, ty, cell_fn, elev, chunks, md=None):
    """The tile's railway track (rails.build), None when rails are off (BNGE_RAILS) or none is near. The cells of the
    whole profiling window (rails.NEAR_M round the tile), so every tile whose window holds a node or a level crossing
    sees the same tracks and roads there (the same heights across tile seams)."""
    try:
        from nrails import rails
        import roads
        if not rails.enabled():
            return None
        # the cells under the tile: its tracks' heights come from the map cells' shared profiles (nrails.canon), each
        # profiled once in its own window
        get = _safe(cell_fn)
        canon = rails._on("BNGE_RAIL_CANON")
        if canon:
            cells = [get(k) for k in roads.cells_of_tile(frame, tx, ty, margin=rails.OVERLAP_M + 10.0)]
        else:                   # (the whole window here, and the tunnel chains reaching into it: rails.more_cells)
            cells = list(rails.more_cells(roads.cells_of_tile(frame, tx, ty, margin=rails.NEAR_M), get).values())
        platforms = []
        if md is not None:
            try:
                from nrails import stations
                infra = [md.cell(k, layers=("infrastructure",), kind="demand").layers.get("infrastructure")
                         for k in roads.cells_of_tile(frame, tx, ty, margin=0.0)]
                platforms = stations.platform_rings(infra, frame, roads.tile_bbox(tx, ty))
            except Exception as e:      # noqa: BLE001 - the track without its platforms
                _once(f"platforms of road tile {tx}_{ty}", e)
        return rails.build(frame, tx, ty, cells, elev, chunks, platforms=platforms,
                           cell_fn=get if canon else None)
    except Exception as e:      # noqa: BLE001 - the roads must still come
        _once(f"rails of road tile {tx}_{ty}", e)
        return None


def _safe(cell_fn):
    def get(k):
        try:
            return cell_fn(k)
        except Exception as e:      # noqa: BLE001 - a cell not at hand: no track from it this time
            log.debug("NRails cell %s: %s: %s", k, type(e).__name__, e)
            return None
    return get


def terrain_holes(holes, frame, elev, keep, cx, cy, square, cell_fn=None):
    """blockworker._tunnel_holes / earthd._tunnel_holes: upstream's holes (bool mask or None) of a terrain block
    with the rail tunnels' portals cut too (nrails.rails.tunnel_hole_mask). keep: heightmap.generate's (lat, lon, u).
    cell_fn(key): a map cell's "roads" layer; None: the block worker process' map data (blockworker._s.md)."""
    try:
        from nrails import rails
        import mapcells
        if not rails.enabled():
            return holes
        if cell_fn is None:
            import blockworker
            md = blockworker._s.md
            cell_fn = lambda key: md.cell(key, layers=("roads",), kind="demand").layers.get("roads")  # noqa: E731
        u = keep["u"]
        half = u.shape[0] * square / 2
        box = (cx - half, cy - half, cx + half, cy + half)
        m = rails.NEAR_M / 111320.0
        lat, lon = keep["lat"], keep["lon"]
        keys = mapcells.cells_for_bbox(float(lat.min()) - m, float(lon.min()) - 2 * m,
                                       float(lat.max()) + m, float(lon.max()) + 2 * m)
        if rails._on("BNGE_RAIL_CANON"):            # (the cells' shared profiles: nrails.canon)
            from nrails import canon
            tubes = canon.block_tubes(frame, _safe(cell_fn), elev, box)
        else:
            cells = list(rails.more_cells(keys, _safe(cell_fn)).values())
            tubes = rails.block_tubes(frame, cells, elev, box)
        if not tubes:
            return holes
        mask = rails.tunnel_hole_mask(tubes, u, cx, cy, square)
        log.info("NRails: block (%s, %s): %d rail tunnel tubes, %d terrain samples cut at their portals", cx, cy,
                 len(tubes), int(mask.sum()))
        if not mask.any():
            return holes
        return mask if holes is None else (holes | mask)
    except Exception as e:      # noqa: BLE001 - upstream's holes rather than none
        _once(f"rail tunnel holes of block ({cx}, {cy})", e)
        return holes


def rail_corridor(gen, frame, cx, cy, size, square, elev, cell_fn=None):
    """blockworker.build / earthd._make_heightmap_here_: the block's height function gen(la, lo) with the tracks'
    corridor cut into it (nrails.corridor: the terrain kept under the ballast beside every track in the open)."""
    try:
        from nrails import rails, corridor
        if not rails.enabled() or not rails._on("BNGE_RAIL_CORRIDOR") or not rails._on("BNGE_RAIL_CANON"):
            return gen
        if cell_fn is None:
            import blockworker
            md = blockworker._s.md
            cell_fn = lambda key: md.cell(key, layers=("roads",), kind="demand").layers.get("roads")  # noqa: E731
        half = size * square / 2
        ceil = corridor.block_ceiling(frame, (cx - half, cy - half, cx + half, cy + half), _safe(cell_fn), elev)
        if ceil is None:
            return gen
        log.info("NRails: block (%s, %s): rail corridor of %d track samples", cx, cy, ceil.n)
        return corridor.cut(gen, frame, ceil)
    except Exception as e:      # noqa: BLE001 - upstream's heights rather than none
        _once(f"rail corridor of block ({cx}, {cy})", e)
        return gen


def grader_made(grader):
    """blockworker / earthd: a grading.Grader made for an anchor: the ground of the tracks' shared profiles
    (nrails.canon)."""
    try:
        from nrails import canon
        canon.grader_made(grader)
    except Exception as e:      # noqa: BLE001
        _once("grader for the rail profiles", e)


def cell_rail_plans(grader, key, plans):
    """grading.Grader._make_cell: the cell's road plans and the railway's bed (nrails.grade: the terrain cut and
    filled under and beside the track)."""
    try:
        from nrails import grade
        return plans + grade.cell_plans(grader, key)
    except Exception as e:      # noqa: BLE001 - the roads' grading as upstream makes it
        _once(f"rail bed grading of cell {key}", e)
        return plans


def is_rail_key(k):
    """roads.BridgeProfiles._solve: a key of its ground lines that is a track's (load_rails), not a road's."""
    return isinstance(k, tuple) and len(k) == 2 and k[1] == "nrails_rail"      # decks.RAIL_KEY (light here)


def load_rails(feats, frame, ground):
    """roads.BridgeProfiles._load: the tracks on the ground of a map cell into the bridge solver's ground lines
    (nrails.decks)."""
    try:
        from nrails import rails, decks
        if rails.enabled():
            decks.load_rails(feats, frame, ground)
    except Exception as e:      # noqa: BLE001 - the decks as upstream makes them
        _once("rails under the road decks", e)


def rail_lines(feats, frame):
    """roads.BridgeProfiles._roads_near: the tracks on the ground of a map cell [(k, 2)] (the piers of a bridge's
    structure keep off them as off the roads; [] when NRails is off)."""
    try:
        from nrails import rails, decks
        if rails.enabled():
            g = {}
            decks.load_rails(feats, frame, g)
            return [ln for k, v in g.items() if k[1] == decks.RAIL_KEY for ln in v]
    except Exception as e:      # noqa: BLE001 - the piers as upstream places them
        _once("rails under the bridge structures", e)
    return []


def deck_crossings(crossings, lines, comp, ground, ground_fn):
    """roads.BridgeProfiles._solve: its crossings with the road crossings that are no junctions at grade kept clear,
    and the deck's crossings over the tracks with the railway's clearance (nrails.decks)."""
    try:
        from nrails import decks
        return decks.deck_crossings(crossings, lines, comp, ground, ground_fn)
    except Exception as e:      # noqa: BLE001 - upstream's crossings
        _once("road deck crossings", e)
        return crossings


def deck_rail_crossings(lines, ground, ground_fn):
    """The deck crossings over the tracks, with the railway's clearance (nrails.decks)."""
    try:
        from nrails import decks
        return decks.deck_rail_crossings(lines, ground, ground_fn)
    except Exception as e:      # noqa: BLE001
        _once("road deck clearance over the rails", e)
        return []


def shape_files(aid, tx, ty):
    """{what: file name} of the track's shape files (roads.shape_files: the pooled slots)."""
    out = {"rail": f"rail_{aid}_{tx}_{ty}.cdae", "railcol": f"railcol_{aid}_{tx}_{ty}.cdae",
           "railx": f"railx_{aid}_{tx}_{ty}.cdae", "railtun": f"railtun_{aid}_{tx}_{ty}.cdae"}
    for k in range(2, RAIL_PARTS_MAX + 1):
        out[f"rail{k}"] = f"rail_{aid}_{tx}_{ty}_{k}.cdae"
    for k in range(2, RAILCOL_PARTS_MAX + 1):
        out[f"railcol{k}"] = f"railcol_{aid}_{tx}_{ty}_{k}.cdae"
    for k in range(1, RAILSW_MAX + 1):
        out[f"railsw{k}"] = f"railsw_{aid}_{tx}_{ty}_{k}.cdae"
    return out


def write_extras(extras, data, boxes, out_dir, vfs_dir, aid, tx, ty):
    """roads.write_tile: the track's shapes written next to the tile's, and its fields in the tile (data) and its
    collider boxes (boxes)."""
    rail = getattr(extras, "rail", None)
    if rail is None:
        return
    try:
        from nrails import rails
        import roads
        x0, y0, _, _ = roads.tile_bbox(tx, ty)
        names = shape_files(aid, tx, ty)
        for what, mesh, col_only in rail.shapes():
            shape = names[what]
            rails.write(os.path.join(out_dir, shape), mesh, collision_only=col_only)
            data[what] = {"shape": f"{vfs_dir}/{shape}", "pos": [x0, y0, 0.0]}
        if rail.lines:                  # the track's centre lines: the mod puts a rail vehicle on them (snapToRail)
            data["rail_lines"] = rail.line_rows()
        if getattr(rail, "sw_rows", None):  # the turnouts (nrails.switches): the mod sets their routes' collision
            data["railsw"] = rail.sw_rows
        if rail.inner is not None and rail.xpts:
            data["railx_pts"] = rail.xpts     # the crossings' centres: nrails.lua drops the inner slabs' collision
            boxes.update(rail.boxes)          # near a rail vehicle (and holds them while the player is on one)
    except Exception as e:      # noqa: BLE001
        _once(f"track shapes of road tile {tx}_{ty}", e)
