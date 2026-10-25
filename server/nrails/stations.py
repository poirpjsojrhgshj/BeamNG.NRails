"""NRails: stations (the user's run, 2026-10-24: "au niveau des gares, les quais sont construits en batiments
bloquant les voies").

Two things went wrong at a station. The map's building footprints there include machine-learnt ones (Microsoft ML
Buildings) traced from the platform canopies: a test town two platforms came as a 24 x 44 m building, 3 m tall, over
the tracks. And the platforms themselves (OSM railway=platform: Overture's infrastructure transit / platform) were not
built at all.

- clear_tracks: a building whose footprint a track runs through or comes within CLEAR_M of (the train's half width
  and a margin) is left out, unless it stands CLEAR_MIN_H_M or more off the ground (a roof over the tracks, a hall).
- platforms: each mapped platform beside a track becomes a slab PLATFORM_H_M over the rail top (EN 14 / France: 550
  mm), its edge PLATFORM_EDGE_M from the track's centre (EN 15273: 1.65 m at that height), reaching away from the
  track as far as the mapped outline does (at most PLATFORM_MAX_W_M); an island platform between two tracks is one
  from each. Drawn and colliding (the player walks on it), concrete.
"""
import numpy as np

CLEAR_M = 2.0
CLEAR_MIN_H_M = 5.5
PLATFORM_H_M = 0.55
PLATFORM_EDGE_M = 1.65
PLATFORM_MAX_W_M = 14.0
PLATFORM_DEPTH_M = 1.0          # m the slab reaches under the rail top (into the ballast / ground)
PROBE_M = 2.4                   # m from the track's centre a point must be inside the outline: the platform is there
STEP_OUT_M = 0.5


def points_in_ring(p, ring):
    """Which of the points p (n, 2) lie inside the polygon ring (m, 2) (crossing number). Pure."""
    p = np.asarray(p, np.float64)
    r = np.asarray(ring, np.float64)
    if len(r) < 3 or not len(p):
        return np.zeros(len(p), bool)
    a, b = r, np.roll(r, -1, axis=0)
    x, y = p[:, 0:1], p[:, 1:2]
    ay, by = a[None, :, 1], b[None, :, 1]
    ax, bx = a[None, :, 0], b[None, :, 0]
    cond = (ay > y) != (by > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xint = ax + (y - ay) * (bx - ax) / (by - ay)
    return ((cond & (x < xint)).sum(axis=1) % 2) == 1


def _track_lines(cells, frame, box, margin=20.0):
    from nrails import rails
    near = (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)
    out = []
    for fid, cls, xy, ranges in rails.rail_features(cells, frame, near):
        if cls in rails.TRAM_CLASSES:
            continue
        pts, _ = rails.resample(rails.chaikin(np.asarray(xy, np.float64)), 1.0)
        out.append(pts)
    return out


def clear_tracks(items, frame, tx, ty, cells):
    """items (buildings.road_tile_items: (Shape, ..) with tile-local rings) without the buildings on a track (see
    above)."""
    import roads
    from nrails import rails
    x0, y0, x1, y1 = roads.tile_bbox(tx, ty)
    tracks = [t - [x0, y0] for t in _track_lines(cells, frame, (x0, y0, x1, y1))]
    if not tracks:
        return items
    out, dropped, lifted = [], 0, 0
    for it in items:
        s = it[0]
        ring = np.asarray(getattr(s, "ring", np.zeros((0, 2))), np.float64)[:, :2]
        if len(ring) < 3 or (getattr(s, "min_h", 0) or 0) >= CLEAR_MIN_H_M:
            out.append(it)
            continue
        kind = track_relation(ring, tracks)
        if kind == "across":                        # a structure spanning the tracks: a bridge over them
            s.min_h = SPAN_MIN_H_M
            if getattr(s, "height", None) is not None and np.isfinite(s.height or np.nan):
                s.height = max(float(s.height), SPAN_OWN_H_M)
            lifted += 1
            out.append(it)
        elif kind == "on":
            dropped += 1
        else:
            out.append(it)
    if dropped or lifted:
        import logging
        logging.getLogger("earthd.nrails").info("NRails: road tile %s_%s: %d buildings on the tracks left out, %d "
                                                "over them lifted", tx, ty, dropped, lifted)
    return out


SPAN_MIN_H_M = 7.0          # m off the ground a structure spanning the tracks starts (6 m free over the rail top)
SPAN_OWN_H_M = 3.0          # m of its own height at least
SPAN_THROUGH_M = 4.0        # m of track inside a footprint, entering and leaving it: the footprint spans the track
SPAN_REACH_M = 3.0          # m a footprint the track crosses reaches out on both sides: it spans it (a footbridge)


def track_relation(ring, tracks):
    """How a footprint ring (k, 2) stands to the tracks (lines sampled every ~1 m): "across" (a track runs through it
    over SPAN_THROUGH_M and on beyond both sides: a station hall, a footbridge's outline, a canopy over the tracks: it
    is lifted over them), "on" (a track inside it or within CLEAR_M of its edge otherwise: it stands in the train's
    way), None. Pure."""
    from nrails import rails
    lo, hi = ring.min(0) - CLEAR_M, ring.max(0) + CLEAR_M
    rel = None
    for t in tracks:
        sel = (t[:, 0] >= lo[0]) & (t[:, 0] <= hi[0]) & (t[:, 1] >= lo[1]) & (t[:, 1] <= hi[1])
        if not sel.any():
            continue
        inside = points_in_ring(t, ring)
        if inside.any():
            for run in rails._runs(inside):
                through = run[0] > 0 and run[-1] < len(t) - 1
                # (a footbridge is a few m along the track but reaches well out on both sides of it)
                m = run[len(run) // 2]
                d = t[min(m + 1, len(t) - 1)] - t[max(m - 1, 0)]
                nrm = np.array([-d[1], d[0]]) / max(np.hypot(*d), 1e-9)
                lat = (ring - t[m]) @ nrm
                wide = lat.min() <= -SPAN_REACH_M and lat.max() >= SPAN_REACH_M
                if through and (wide or np.hypot(*(t[run[-1]] - t[run[0]])) >= SPAN_THROUGH_M):
                    rel = "across"
                elif rel is None:
                    rel = "on"
            continue
        d, *_ = rails._nearest_on(t[sel], np.vstack([ring, ring[:1]]))
        if (d < CLEAR_M).any() and rel is None:
            rel = "on"
    return rel


def platform_rings(infra_cells, frame, box, margin=50.0):
    """[xy (k, 2)] outlines (anchor frame) of the mapped platforms (infrastructure transit / platform) near box."""
    import mapgeom
    out, seen = [], set()
    x0, y0, x1, y1 = box
    for feats in infra_cells:
        if feats is None or len(feats) == 0:
            continue
        cls = feats.attrs.get("class")
        if cls is None:
            continue
        lvl = feats.attrs.get("level")
        for i in range(len(feats)):
            if str(cls[i]) != "platform" or str(feats.ids[i]) in seen:
                continue
            try:
                if lvl is not None and float(lvl[i]) != 0.0 and np.isfinite(float(lvl[i])):
                    continue                # (an upper floor's concourse mapped as a platform: not at the tracks)
            except (TypeError, ValueError):
                pass
            seen.add(str(feats.ids[i]))
            for part in feats.parts(i):
                for ring in part:
                    if len(ring) < 3:
                        continue
                    e, n = mapgeom.enu_xy(feats, frame, ring)
                    xy = np.c_[e, n]
                    if xy[:, 0].max() < x0 - margin or xy[:, 0].min() > x1 + margin or \
                            xy[:, 1].max() < y0 - margin or xy[:, 1].min() > y1 + margin:
                        continue
                    out.append(xy)
                    break               # (the outer ring)
    return out


def add_platforms(vis, col, heavy, rings):
    """The platforms (see above) of the outlines rings beside the tile's track pieces heavy [(k, pts (n, 3), kind)]
    into the meshes vis (drawn) and col (colliding)."""
    from nrails import rails
    n_made = 0
    rooms = {}
    for ring in rings:
        lo, hi = ring.min(0) - PLATFORM_MAX_W_M, ring.max(0) + PLATFORM_MAX_W_M
        for ii, (_k, pts, kind) in enumerate(heavy):
            sel = (pts[:, 0] >= lo[0]) & (pts[:, 0] <= hi[0]) & (pts[:, 1] >= lo[1]) & (pts[:, 1] <= hi[1])
            if sel.sum() < 2:
                continue
            nrm = rails.normals(pts[:, :2])
            # (never over the next track: a platform outline mapped round the whole station, the tracks inside it,
            # gave slabs reaching across them; the slab stops PLATFORM_EDGE_M short of the next track's centre)
            if ii not in rooms:
                rooms[ii] = rails.side_room(pts, nrm, [p[:, :2] for jj, (_k2, p, _kd) in enumerate(heavy) if jj != ii],
                                           reach=2 * (PLATFORM_EDGE_M + PLATFORM_MAX_W_M))
            for sgn, room in ((1.0, rooms[ii][0]), (-1.0, rooms[ii][1])):
                probe = pts[:, :2] + nrm * sgn * PROBE_M
                wide = room >= 2 * PLATFORM_EDGE_M + 1.0
                beside = points_in_ring(probe, ring) & sel & (np.asarray(kind) != 2) & wide
                for run in rails._runs(beside):
                    if len(run) < 2:
                        continue
                    # how far the outline reaches away from the track (the median over the run: one straight edge)
                    widths = []
                    for j in run[:: max(1, len(run) // 12)]:
                        d = PROBE_M
                        while d < PLATFORM_EDGE_M + PLATFORM_MAX_W_M:
                            p = pts[j, :2] + nrm[j] * sgn * (d + STEP_OUT_M)
                            if not points_in_ring(p[None], ring)[0]:
                                break
                            d += STEP_OUT_M
                        widths.append(d)
                    far = float(np.clip(np.median(widths), PLATFORM_EDGE_M + 1.0, PLATFORM_EDGE_M + PLATFORM_MAX_W_M))
                    far = min(far, float(room[run].min()) - PLATFORM_EDGE_M)
                    if far < PLATFORM_EDGE_M + 1.0:
                        continue
                    a = max(run[0] - 1, 0)
                    b = min(run[-1] + 2, len(pts))
                    x0, x1 = sorted((sgn * PLATFORM_EDGE_M, sgn * far))
                    for m in (vis, col):
                        rails._box_strip(m, pts[a:b], nrm[a:b], x0, x1, PLATFORM_H_M, -PLATFORM_DEPTH_M,
                                         rails.MAT_CONCRETE)
                    n_made += 1
    return n_made
