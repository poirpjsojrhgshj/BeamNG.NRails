"""EarthNRails: the railway's bed in the terrain (through grading.Grader, nrails.hooks.cell_rail_plans).

The track (nrails.rails) floats over the DEM on its own profile: on an embankment where the grade cap raised it, in a
cutting where the ground beside it is higher (a hillside, a tunnel's approach). The terrain stayed as it was: ballast
over thin air, and hillsides standing in the train's way beside the track and at the tunnel mouths (the user's run,
2026-10-24: "je suis rentre en collision avec les entrees et sorties [des tunnels] du a la map se retrouvant en plein
milieu"). Each map cell's grading plans get the track's too: a grading.Plan along every stretch of track on the
ground, its target RAIL_BED_M under the rail top over RAIL_BED_HALF_M either side of the centre line (the ballast's
foot and a cess beyond), the terrain cut and filled back to the ground beside it as the roads' (grading.grade_points:
1:2 slopes, T_MAX at most), at the road's own level across a level crossing. Upstream's grader then shapes every
terrain block, road tile and far tile with it; nothing else changes. BNGE_RAIL_GRADE=off: none.

The profile is the one the road tiles build (rails.profile_network over the cell's box + NEAR_M, its tunnel chains
whole, the same level crossings), from the grader's own elevation: the road tiles' track then lies RAIL_BED_M -
FORMATION_M (~0.1 m) under it over the graded bed, the same everywhere along it.
"""
import numpy as np

RAIL_BED_M = 0.6            # m under the rail top: the graded ground under the ballast (its foot: 1.13 m)
RAIL_BED_HALF_M = 3.5       # m either side of the centre line at that level (ballast to 2.95 m, then the cess)
X_FLAT_M = 5.0              # m past a level crossing's slab the bed stays at the road's level
MOUTH_M = 6.0               # m into a tunnel from its portal the bed goes on (grading.MOUTH_PLAN_M for roads)


def enabled():
    from nrails import rails
    return rails.enabled() and rails._on("BNGE_RAIL_GRADE")


def cell_plans(grader, key):
    """[(fid + ':rail', grading.Plan)] of the track on the ground in map cell `key`, trimmed to the cell's own box."""
    if not enabled():
        return []
    import grading
    import mapcells
    from nrails import rails
    own = grader._clip_box(key, 0.0)
    if own is None:
        return []
    frame = grader.frame

    def cell_fn(k):
        try:
            return grader.md.cell(k, layers=("roads",), kind="demand").layers.get("roads")
        except Exception:       # noqa: BLE001 - a cell not at hand: no track from it
            return None
    if rails._on("BNGE_RAIL_CANON"):
        # (the cell's samples of the shared profile, nrails.canon: the road tiles draw the same)
        from nrails import canon
        canon.grader_made(grader)
        cp = canon.cell_profile(frame, key, cell_fn, grader.elev)
        prof = {fid: [(p, k) for p, k, _a in ps] for fid, ps in cp.parts.items()}
        found = cp.found
        return _plans(prof, found, own, grading, rails)
    near = (own[0] - rails.NEAR_M, own[1] - rails.NEAR_M, own[2] + rails.NEAR_M, own[3] + rails.NEAR_M)
    la, lo, _ = frame.enu_to_geodetic(np.array([near[0], near[2]]), np.array([near[1], near[3]]), 0.0)
    la, lo = np.asarray(la, np.float64), np.asarray(lo, np.float64)
    keys = mapcells.cells_for_bbox(float(la.min()), float(lo.min()), float(la.max()), float(lo.max()))
    own_feats = cell_fn(key)                        # (most cells: no track in them, nothing more read)
    if own_feats is None or not rails.rail_features([own_feats], frame, own):
        return []
    first = {k: (own_feats if str(k) == str(key) else cell_fn(k)) for k in keys}
    cells = list(rails.more_cells(keys, cell_fn, first).values())
    feats = rails.rail_features(cells, frame, rails._feature_box(near))
    segments = [(fid, xy, ranges) for fid, cls, xy, ranges in feats if cls in rails.HEAVY_CLASSES]
    if not segments:
        return []
    with_x = rails._on("BNGE_RAIL_CROSSINGS")
    roads_near = rails.road_lines(cells, frame, near) if with_x else ()
    structs = rails.road_structs(cells, frame, near) if with_x else None
    found = []
    ground = rails.Ground(frame, grader.elev)
    prof = rails.profile_network(ground, segments, near, roads_near, found, None, structs, rails.rail_connectors(cells))
    return _plans(prof, found, own, grading, rails)


def _plans(prof, found, own, grading, rails):
    out = []
    for fid, parts in prof.items():
        for pts, kind in parts:
            z = pts[:, 2] - RAIL_BED_M
            for x in found:                         # across a level crossing: the road's own level
                if x["fid"] != fid:
                    continue
                d = np.hypot(pts[:, 0] - x["at"][0], pts[:, 1] - x["at"][1])
                z = np.where(d <= x["half"] + X_FLAT_M, pts[:, 2] - rails.X_RISE_M, z)
            kd = np.asarray(kind)
            for run in rails._runs(kd == 0):
                if len(run) < 2:
                    continue
                # a tunnel's mouth: the bed carried MOUTH_M into it (the portal's opening graded at the floor, as
                # grading's own Grader._mouth_plans for the roads' tunnels)
                k = max(1, int(round(MOUTH_M / rails.STEP_M)))
                lo, hi = int(run[0]), int(run[-1])
                if lo > 0 and kd[lo - 1] == 2:
                    lo = max(0, lo - k)
                if hi < len(kd) - 1 and kd[hi + 1] == 2:
                    hi = min(len(kd) - 1, hi + k)
                run = np.arange(lo, hi + 1)
                idx = np.r_[run[::2], run[-1]] if len(run) > 2 else run
                idx = np.unique(idx)
                p = grading.Plan(np.ascontiguousarray(pts[idx, :2]), np.ascontiguousarray(z[idx]), RAIL_BED_HALF_M)
                p.rid = grading.road_id(fid + ":rail")
                for q in grading.trim_plan(p, own):
                    out.append((fid + ":rail", q))
    return out
