"""NRails: turnouts that can be set (the user's runs, 2026-10-25 / 26: "une chance sur le nombre de voies qu'un bogie
aille sur la mauvaise voie"; "les aiguillages ... c'est pas du tout fonctionnel").

The rolling stock's wheelsets are a tread cylinder over a flange disc filling the whole gauge 0.155-0.18 m under the
rail top: no rail can lie inside the gauge of the route a train takes, and a wheelset between two routes follows
whichever flange catches first. So, as a real turnout's blades do, the switch zone of every route (from the node to
where its centre line is SPLIT_M from every other route of the fan: the two gauges no longer overlap, past the frog)
has its rails in collision shapes of their own, without the frog mask against the fan's other routes; the mod makes
solid only the set route's.

Overlapping zones (a crossover's two turnouts, a ladder, a double junction): a rail sample in several zones belongs to
one shape whose key lists every (turnout, route) it is in; it is solid only when each of those turnouts is set to that
route (zone_keys, mod_rows' "shapes").

The default route of a turnout is the main line (priority: a named line, as OSM draws the main lines dark and its
sidings, yards and spurs light, then the through track, then the straightest). For the mod each route also carries its
arm (DETECT_M of track from the node) and each turnout its trunk (the track behind the node), so a train is placed on
the line it runs on, not by its distance to the turnout's axis (a parallel track's turnout took the player's choice).
Pure.
"""
import math

import numpy as np

FAN_DEG = 20.0          # tracks leaving a node within this angle of each other: one turnout's routes
NODE_TOL_M = 1.0        # m: a track this close to a node passes through it
ARM_M = 140.0           # m of each route looked at from the node (its zone)
DIR_AT_M = 14.0         # m out along a route its direction is taken
SPLIT_M = 3.0           # m between the routes' centre lines where the zone ends: the other route's rails ~2.2 m off the train's
                        # centre, clear of its low parts (bogie frames, a WLD's snowplow 0.13 m over the rail top, ~1.5 m
                        # half wide): a track joining ours made no collision with the train any more (the user's run,
                        # 2026-10-26: "les aiguillages qui viennent sur notre voie ... ne generent pas de collisions").
                        # (1.9 m before: where the gauges (1.435 m + the rail heads) stop overlapping, enough for the
                        # wheels but not for the train's body; the zones of a crossover or a ladder that overlap
                        # now are one shape per key: zone_keys)
ZONE_MAX_M = 100.0
MIN_ARC_M = 6.0         # m: a zone is at least this long
DETECT_M = 250.0        # m of each route (and of the trunk) sent to the mod: on which line a train runs
TRUNK_DEG = 30.0        # a track leaving the node within this angle of the fan's opposite way: its trunk


class Route:
    __slots__ = ("fid", "xy", "side", "through", "arm", "prio")

    def __init__(self, fid, xy, side, through, arm=None, prio=0.0):
        self.fid, self.xy, self.side, self.through = fid, xy, side, through   # xy: the zone's centre line (k, 2)
        self.arm = xy if arm is None else arm           # DETECT_M of the route from the node
        self.prio = prio


class Switch:
    __slots__ = ("id", "at", "dir", "routes", "default", "trunk", "kind")

    def __init__(self, sid, at, d, routes, default, trunk=None, kind="turnout"):
        self.id, self.at, self.dir, self.routes, self.default = sid, at, d, routes, default
        self.trunk = trunk                              # (k, 2) from the node backwards, or None
        self.kind = kind                                # "turnout" | "diamond" (set by the train only)


_LINES = {}                 # (fid, n, first, last) -> resampled line: a 76 km line is resampled once, not per tile
_LINES_PTS = [0]
LINES_CACHE_PTS = 4_000_000  # samples kept at most (~64 MB)


def lines_of(feats):
    """{fid: centre line (k, 2)} of the heavy tracks [(fid, class, xy ring, ranges)] as rails profiles them (corners
    rounded, resampled): the zones fall on the profiles' own samples. Cached per process."""
    from nrails import rails
    out = {}
    for fid, cls, xy, _rg in feats:
        if cls not in rails.HEAVY_CLASSES or len(xy) < 2:
            continue
        xy = np.asarray(xy, np.float64)
        key = (fid, len(xy), round(float(xy[0, 0]), 2), round(float(xy[0, 1]), 2), round(float(xy[-1, 0]), 2),
               round(float(xy[-1, 1]), 2))
        line = _LINES.get(key)
        if line is None:
            line, _s = rails.resample(rails.chaikin(xy))
            if _LINES_PTS[0] + len(line) > LINES_CACHE_PTS:
                _LINES.clear()
                _LINES_PTS[0] = 0
            _LINES[key] = line
            _LINES_PTS[0] += len(line)
        if len(line) >= 2:
            out[fid] = line
    return out


def _window(xy, lo, hi):
    """The run of polyline xy (k, 2) whose samples lie in the box lo..hi (a sample before and after kept), or None.
    (a crossing search over two whole 40 km lines paired every segment of one with every segment of the other: tens
    of GB, the user's PC frozen a minute after the map loaded, 2026-10-26)"""
    inside = np.flatnonzero((xy[:, 0] >= lo[0]) & (xy[:, 0] <= hi[0]) & (xy[:, 1] >= lo[1]) & (xy[:, 1] <= hi[1]))
    if not len(inside):
        return None, 0
    i0, i1 = max(int(inside[0]) - 1, 0), min(int(inside[-1]) + 2, len(xy))
    return xy[i0:i1], i0


def _arcs(xy):
    return np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]


def _dist_to_line(p, q):
    """Distances (n,) from points p (n, 2) to the polyline q (m, 2) (in chunks: n x m bounded by DIST_CELLS)."""
    a, b = q[:-1], q[1:]
    ab = b - a
    L2 = np.maximum((ab * ab).sum(1), 1e-12)
    out = np.empty(len(p))
    step = max(1, DIST_CELLS // max(len(a), 1))
    for k0 in range(0, len(p), step):
        pp = p[k0:k0 + step]
        t = np.clip(((pp[:, None, :] - a[None]) * ab[None]).sum(-1) / L2[None], 0.0, 1.0)
        d = np.hypot(*(pp[:, None, :] - (a[None] + t[..., None] * ab[None])).transpose(2, 0, 1))
        out[k0:k0 + step] = d.min(1)
    return out


DIST_CELLS = 400_000        # point x segment pairs at a time in _dist_to_line (a few tens of MB)


def _arms(lines, p, reach=ARM_M):
    """[(fid, arm (k, 2) from p outward, through)] of the tracks passing within NODE_TOL_M of p, each arm `reach` m."""
    out = []
    for fid, xy in lines.items():
        lo, hi = xy.min(0) - NODE_TOL_M, xy.max(0) + NODE_TOL_M
        if p[0] < lo[0] or p[0] > hi[0] or p[1] < lo[1] or p[1] > hi[1]:
            continue
        d = np.hypot(xy[:, 0] - p[0], xy[:, 1] - p[1])
        i = int(np.argmin(d))
        if d[i] > NODE_TOL_M + 1.5:     # (2 m samples: within a sample of the node)
            continue
        if _dist_to_line(p[None], xy)[0] > NODE_TOL_M:
            continue
        s = _arcs(xy)
        through = s[i] > NODE_TOL_M + 2.0 and s[-1] - s[i] > NODE_TOL_M + 2.0
        if s[-1] - s[i] > DIR_AT_M:
            fw = xy[i:][_arcs(xy[i:]) <= reach]
            out.append((fid, np.vstack([p[None], fw[1:]]), through))
        if s[i] > DIR_AT_M:
            bw = xy[i::-1][_arcs(xy[i::-1]) <= reach]
            out.append((fid, np.vstack([p[None], bw[1:]]), through))
    return out


def _dir(arm):
    s = _arcs(arm)
    j = int(np.searchsorted(s, DIR_AT_M))
    j = min(max(j, 1), len(arm) - 1)
    v = arm[j] - arm[0]
    return v / max(float(np.hypot(*v)), 1e-9)


def find(lines, box, prio=None):
    """The turnouts [Switch] whose zones reach into box (x0, y0, x1, y1), from the tracks' centre lines (lines_of);
    prio: {fid: score} (rail_priority: the main lines first). The same in every tile: a function of the lines round
    each node alone."""
    prio = prio or {}
    nodes = _nodes(lines)
    m = ZONE_MAX_M + NODE_TOL_M
    out = []
    for p in nodes:
        if p[0] < box[0] - m or p[0] > box[2] + m or p[1] < box[1] - m or p[1] > box[3] + m:
            continue
        arms = _arms(lines, p, DETECT_M)
        if len(arms) < 2:
            continue
        dirs = [_dir(a) for _f, a, _t in arms]
        used = set()
        for i in range(len(arms)):
            if i in used:
                continue
            fan = [i]
            for j in range(i + 1, len(arms)):
                if j in used or arms[j][0] in {arms[f][0] for f in fan}:
                    continue
                if all(float(np.dot(dirs[j], dirs[f])) >= math.cos(math.radians(FAN_DEG)) for f in fan):
                    fan.append(j)
            if len(fan) < 2:
                continue
            used.update(fan)
            fdir = np.sum([dirs[f] for f in fan], axis=0)
            fdir = fdir / max(float(np.hypot(*fdir)), 1e-9)
            back = [(float(np.dot(dirs[j], -fdir)), j) for j in range(len(arms)) if j not in fan]
            back = [b for b in back if b[0] >= math.cos(math.radians(TRUNK_DEG))]
            trunk = arms[max(back)[1]][1] if back else None
            sw = _switch(p, [arms[f] for f in fan], [dirs[f] for f in fan], trunk, prio)
            if sw is not None and reaches(sw, box):
                out.append(sw)
    return out


def _nodes(lines):
    """The lines' ends, those within NODE_TOL_M of one another once (a grid of NODE_TOL_M cells: linear in the
    lines, not each end against every node found)."""
    nodes, grid = [], {}
    for xy in lines.values():
        for p in (xy[0], xy[-1]):
            p = np.asarray(p, np.float64)
            gx, gy = int(math.floor(p[0] / NODE_TOL_M)), int(math.floor(p[1] / NODE_TOL_M))
            near = False
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for q in grid.get((gx + dx, gy + dy), ()):
                        if math.hypot(p[0] - q[0], p[1] - q[1]) <= NODE_TOL_M:
                            near = True
                            break
                    if near:
                        break
                if near:
                    break
            if not near:
                nodes.append(p)
                grid.setdefault((gx, gy), []).append(p)
    return nodes


def reaches(sw, box):
    """Does a turnout's zone (its routes' samples) reach into box (x0, y0, x1, y1)?"""
    zb = np.concatenate([r.xy for r in sw.routes])
    return bool(zb[:, 0].max() >= box[0] and zb[:, 0].min() <= box[2] and zb[:, 1].max() >= box[1]
                and zb[:, 1].min() <= box[3])


def _switch(p, arms, dirs, trunk=None, prio=None):
    prio = prio or {}
    d = np.sum(dirs, axis=0)
    d = d / max(float(np.hypot(*d)), 1e-9)
    routes = []
    zone_arms = [a[_arcs(a) <= ARM_M] for _f, a, _t in arms]
    for n, (fid, arm, through) in enumerate(arms):
        za = zone_arms[n]
        others = [a for m, a in enumerate(zone_arms) if m != n]
        dist = np.min([_dist_to_line(za, o) for o in others], axis=0)
        s = _arcs(za)
        apart = np.flatnonzero((dist >= SPLIT_M) & (s >= MIN_ARC_M))
        end = int(apart[0]) if len(apart) else len(za) - 1
        end = min(end, int(np.searchsorted(s, ZONE_MAX_M, side="right")) - 1)
        if end < 2:
            return None
        zone = za[:end + 1]
        v = zone[-1] - p
        side = float(d[0] * v[1] - d[1] * v[0]) / max(float(np.hypot(*v)), 1e-9)   # (+: left of the fan's way)
        routes.append(Route(fid, zone, side, through, arm, float(prio.get(fid, 0.0))))
    routes.sort(key=lambda r: -r.side)                  # left to right
    # the default: the main line (a named track), then a through track, then the straightest
    main = min(range(len(routes)), key=lambda i: (-routes[i].prio, not routes[i].through, abs(routes[i].side)))
    sid = f"{int(round(p[0] * 2))}_{int(round(p[1] * 2))}"
    return Switch(sid, p, d, routes, main, trunk)


DIAMOND_MIN_DEG = 5.0   # tracks crossing at this angle or more (not at a node of both): a diamond


SEG_CHUNK = 256             # segments of one line paired at a time with the other's (memory: CHUNK x m x a few floats)


def _seg_cross(p, q):
    """The crossings of polylines p (n, 2) and q (m, 2): [(point, i, j, unit dir of p there, of q)]. Chunked, each
    chunk only against q's segments within its box: memory bounded whatever the lines' length."""
    out = []
    c, d = q[:-1], q[1:]
    s = d - c
    qlo, qhi = np.minimum(c, d), np.maximum(c, d)
    for k0 in range(0, len(p) - 1, SEG_CHUNK):
        a, b = p[k0:k0 + SEG_CHUNK], p[k0 + 1:k0 + SEG_CHUNK + 1]
        n = min(len(a), len(b))
        a, b = a[:n], b[:n]
        if not n:
            continue
        lo, hi = np.minimum(a, b).min(0), np.maximum(a, b).max(0)
        js = np.flatnonzero((qhi[:, 0] >= lo[0]) & (qlo[:, 0] <= hi[0]) & (qhi[:, 1] >= lo[1]) & (qlo[:, 1] <= hi[1]))
        if not len(js):
            continue
        r = b - a
        cc, ss = c[js], s[js]
        den = r[:, None, 0] * ss[None, :, 1] - r[:, None, 1] * ss[None, :, 0]
        ok = np.abs(den) > 1e-12
        den = np.where(ok, den, 1.0)
        ca = cc[None, :, :] - a[:, None, :]
        t = (ca[..., 0] * ss[None, :, 1] - ca[..., 1] * ss[None, :, 0]) / den
        u = (ca[..., 0] * r[:, None, 1] - ca[..., 1] * r[:, None, 0]) / den
        hit = ok & (t >= 0) & (t < 1) & (u >= 0) & (u < 1)
        for i, jj in zip(*np.nonzero(hit)):
            j = int(js[jj])
            pt = a[i] + t[i, jj] * r[i]
            out.append((pt, k0 + int(i), j, r[i] / max(float(np.hypot(*r[i])), 1e-9),
                        s[j] / max(float(np.hypot(*s[j])), 1e-9)))
    return out


def find_diamonds(lines, box, prio=None):
    """The diamond crossings [Switch kind "diamond"] whose zones reach into box: two tracks crossing at
    DIAMOND_MIN_DEG or more away from a node of both. Each track through the crossing is a route; its zone is where
    its centre line is within SPLIT_M of the other's (the two gauges overlap: no rail can be in both), its arm
    DETECT_M of it either way. Only the set track's zone rails are solid; the mod sets it to the track a train comes
    on (no player choice). Pure."""
    prio = prio or {}
    m = ZONE_MAX_M + NODE_TOL_M
    lo = np.array([box[0] - m, box[1] - m])
    hi = np.array([box[2] + m, box[3] + m])
    items = []
    for fid, xy in lines.items():
        if len(xy) < 2:
            continue
        w, _i0 = _window(xy, lo, hi)                # (only the stretch round the box is searched)
        if w is not None and len(w) >= 2:
            items.append((fid, xy, w, _i0, w.min(0), w.max(0)))
    items.sort(key=lambda it: it[0])
    out = []
    for n, (fa, a, wa, ia, alo, ahi) in enumerate(items):
        for fb, b, wb, ib, blo, bhi in items[n + 1:]:
            if alo[0] > bhi[0] or blo[0] > ahi[0] or alo[1] > bhi[1] or blo[1] > ahi[1]:
                continue
            for pt, i, j, da, db in _seg_cross(wa, wb):
                i, j = i + ia, j + ib
                if pt[0] < box[0] - m or pt[0] > box[2] + m or pt[1] < box[1] - m or pt[1] > box[3] + m:
                    continue
                ang = math.degrees(math.acos(min(1.0, abs(float(np.dot(da, db))))))
                if ang < DIAMOND_MIN_DEG:
                    continue
                ends = [a[0], a[-1], b[0], b[-1]]
                if any(np.hypot(*(pt - e)) <= NODE_TOL_M + 2.0 for e in ends):
                    continue                    # (a turnout's node: find's)
                routes = []
                for fid, xy, k, other in ((fa, a, i, b), (fb, b, j, a)):
                    s = _arcs(xy)
                    s0 = s[k] + float(np.hypot(*(pt - xy[k])))
                    near = np.flatnonzero(np.abs(s - s0) <= DETECT_M)
                    arm = xy[near]
                    ow, _o = _window(other, pt - DETECT_M - 10.0, pt + DETECT_M + 10.0)
                    dz = _dist_to_line(arm, ow if ow is not None and len(ow) >= 2 else other)
                    inz = np.flatnonzero(dz < SPLIT_M + 0.3)
                    if not len(inz):
                        break
                    zone = arm[max(int(inz[0]) - 1, 0):int(inz[-1]) + 2]
                    routes.append(Route(fid, zone, 0.0, True, arm, float(prio.get(fid, 0.0))))
                if len(routes) != 2:
                    continue
                main = min(range(2), key=lambda q: (-routes[q].prio, routes[q].fid))
                sid = f"x{int(round(pt[0] * 2))}_{int(round(pt[1] * 2))}"
                zb = np.concatenate([r.xy for r in routes])
                if (zb[:, 0].max() >= box[0] and zb[:, 0].min() <= box[2] and zb[:, 1].max() >= box[1]
                        and zb[:, 1].min() <= box[3]):
                    out.append(Switch(sid, pt, da, routes, main, None, "diamond"))
    return out


def zone_keys(pts_xy, fid, switches, tol=0.35):
    """Per sample of a piece of track fid: the tuple of (switch index, route index) of every zone it lies in (sorted;
    () outside every zone)."""
    keys = [[] for _ in range(len(pts_xy))]
    for i, sw in enumerate(switches):
        for j, r in enumerate(sw.routes):
            if r.fid != fid:
                continue
            lo, hi = r.xy.min(0) - 1.0, r.xy.max(0) + 1.0
            cand = np.flatnonzero((pts_xy[:, 0] >= lo[0]) & (pts_xy[:, 0] <= hi[0]) & (pts_xy[:, 1] >= lo[1])
                                  & (pts_xy[:, 1] <= hi[1]))
            if not len(cand):
                continue
            d = _dist_to_line(pts_xy[cand], r.xy)
            # (beyond the zone's end the same track goes on: only the samples along the zone, not past its ends)
            s = _arcs(r.xy)
            ends = np.hypot(pts_xy[cand, 0] - r.xy[-1, 0], pts_xy[cand, 1] - r.xy[-1, 1])
            starts = np.hypot(pts_xy[cand, 0] - r.xy[0, 0], pts_xy[cand, 1] - r.xy[0, 1])
            inside = (d <= tol) & (ends <= s[-1] + tol) & (starts <= s[-1] + tol)
            for c in cand[inside]:
                keys[int(c)].append((i, j))
    return [tuple(sorted(k)) for k in keys]


def zone_mask(pts_xy, fid, switches, tol=0.35):
    """Per sample: (switch index, route index) of the first zone it lies in, or (-1, -1) (zone_keys' first)."""
    ks = zone_keys(pts_xy, fid, switches, tol)
    sw_i = np.array([k[0][0] if k else -1 for k in ks], int)
    rt_i = np.array([k[0][1] if k else -1 for k in ks], int)
    return sw_i, rt_i


def _flat(xy, every=2):
    xy = np.asarray(xy)
    line = xy[::every] if len(xy) > 2 * every else xy
    if len(xy) > 2 * every and not np.allclose(line[-1], xy[-1]):
        line = np.vstack([line, xy[-1:]])
    return [round(float(v), 2) for v in line.ravel()]


def mod_rows(switches, whats):
    """The tile's turnouts for the mod (data["railsw"]): [{id, at, dir, def, trunk, routes: [{what, side, line, arm}]}];
    whats: {key: the shape's name}, key a zone_keys tuple ((switch index, route index), ...). A route's "what" is the
    shape of its zone alone (the one-zone key), kept for the older mod."""
    out = []
    for i, sw in enumerate(switches):
        routes = []
        for j, r in enumerate(sw.routes):
            routes.append({"what": whats.get(((i, j),)), "side": round(r.side, 3), "line": _flat(r.xy),
                           "arm": _flat(r.arm, 2), "main": r.prio > 0})
        out.append({"id": sw.id, "at": [round(float(sw.at[0]), 2), round(float(sw.at[1]), 2)],
                    "dir": [round(float(sw.dir[0]), 4), round(float(sw.dir[1]), 4)], "def": sw.default,
                    "trunk": _flat(sw.trunk, 2) if sw.trunk is not None else None, "routes": routes,
                    "kind": getattr(sw, "kind", "turnout")})
    return out


def shape_rows(switches, whats):
    """The tile's turnout shapes for the mod (data["railsw_shapes"]): [{what, need: [[switch id, route (1-based)]]}]:
    the shape is solid when every listed turnout is set to that route."""
    return [{"what": w, "need": [[switches[i].id, j + 1] for i, j in key]} for key, w in sorted(whats.items(),
                                                                                               key=lambda kv: kv[1])]
