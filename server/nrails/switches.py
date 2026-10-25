"""EarthNRails: turnouts that can be set (the user's run, 2026-10-25: "les intersections entre voies (aiguillages) posent
des problemes ... une chance sur le nombre de voies qu'un bogie aille sur la mauvaise voie; je ne sais pas comment on se
dirige sur les aiguillages").

The track has no moving blades: where a branch leaves another track, both tracks' rails are there and the frog mask
(rails.frog_mask) only drops the parts of a rail inside the other track's gauge, so a bogie followed whichever flange
caught first. Here every turnout is found from the map (a node where two or more tracks leave in the same direction,
within FAN_DEG: the "fan"); along each of its routes, from the node to where the routes are SPLIT_M apart (the switch
zone, ZONE_MAX_M at most), the rails' collision is made apart, one shape per route, without the frog mask against the
fan's other routes: the mod makes only the set route's shape solid (nrails.lua: the next turnout ahead set by the
player's keys, a turnout run through from a branch set to that branch). Pure.
"""
import math

import numpy as np

FAN_DEG = 20.0          # tracks leaving a node within this angle of each other: one turnout's routes
NODE_TOL_M = 1.0        # m: a track this close to a node passes through it
ARM_M = 140.0           # m of each route looked at from the node
DIR_AT_M = 14.0         # m out along a route its direction is taken
SPLIT_M = 3.4           # m between the routes' centre lines where the zone ends (past the frog: rails 2 m apart)
ZONE_MAX_M = 100.0
MIN_ARC_M = 6.0         # m: a zone is at least this long


class Route:
    __slots__ = ("fid", "xy", "side", "through")

    def __init__(self, fid, xy, side, through):
        self.fid, self.xy, self.side, self.through = fid, xy, side, through   # xy: the zone's centre line (k, 2)


class Switch:
    __slots__ = ("id", "at", "dir", "routes", "default")

    def __init__(self, sid, at, d, routes, default):
        self.id, self.at, self.dir, self.routes, self.default = sid, at, d, routes, default


def lines_of(feats):
    """{fid: centre line (k, 2)} of the heavy tracks [(fid, class, xy ring, ranges)] as rails profiles them (corners
    rounded, resampled): the zones fall on the profiles' own samples."""
    from nrails import rails
    out = {}
    for fid, cls, xy, _rg in feats:
        if cls not in rails.HEAVY_CLASSES or len(xy) < 2:
            continue
        line, _s = rails.resample(rails.chaikin(np.asarray(xy, np.float64)))
        if len(line) >= 2:
            out[fid] = line
    return out


def _arcs(xy):
    return np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]


def _dist_to_line(p, q):
    """Distances (n,) from points p (n, 2) to the polyline q (m, 2)."""
    a, b = q[:-1], q[1:]
    ab = b - a
    L2 = np.maximum((ab * ab).sum(1), 1e-12)
    t = np.clip(((p[:, None, :] - a[None]) * ab[None]).sum(-1) / L2[None], 0.0, 1.0)
    d = np.hypot(*(p[:, None, :] - (a[None] + t[..., None] * ab[None])).transpose(2, 0, 1))
    return d.min(1)


def _arms(lines, p):
    """[(fid, arm (k, 2) from p outward, through)] of the tracks passing within NODE_TOL_M of p."""
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
            fw = xy[i:][_arcs(xy[i:]) <= ARM_M]
            out.append((fid, np.vstack([p[None], fw[1:]]), through))
        if s[i] > DIR_AT_M:
            bw = xy[i::-1][_arcs(xy[i::-1]) <= ARM_M]
            out.append((fid, np.vstack([p[None], bw[1:]]), through))
    return out


def _dir(arm):
    s = _arcs(arm)
    j = int(np.searchsorted(s, DIR_AT_M))
    j = min(max(j, 1), len(arm) - 1)
    v = arm[j] - arm[0]
    return v / max(float(np.hypot(*v)), 1e-9)


def find(lines, box):
    """The turnouts [Switch] whose zones reach into box (x0, y0, x1, y1), from the tracks' centre lines (lines_of).
    The same in every tile: a function of the lines round each node alone."""
    nodes = []
    for xy in lines.values():
        for p in (xy[0], xy[-1]):
            if not any(np.hypot(*(p - q)) <= NODE_TOL_M for q in nodes):
                nodes.append(np.asarray(p, np.float64))
    m = ZONE_MAX_M + NODE_TOL_M
    out = []
    for p in nodes:
        if p[0] < box[0] - m or p[0] > box[2] + m or p[1] < box[1] - m or p[1] > box[3] + m:
            continue
        arms = _arms(lines, p)
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
            sw = _switch(p, [arms[f] for f in fan], [dirs[f] for f in fan])
            if sw is not None:
                zb = np.concatenate([r.xy for r in sw.routes])
                if (zb[:, 0].max() >= box[0] and zb[:, 0].min() <= box[2] and zb[:, 1].max() >= box[1]
                        and zb[:, 1].min() <= box[3]):
                    out.append(sw)
    return out


def _switch(p, arms, dirs):
    d = np.sum(dirs, axis=0)
    d = d / max(float(np.hypot(*d)), 1e-9)
    routes = []
    for n, (fid, arm, through) in enumerate(arms):
        others = [a for m, (_f, a, _t) in enumerate(arms) if m != n]
        dist = np.min([_dist_to_line(arm, o) for o in others], axis=0)
        s = _arcs(arm)
        apart = np.flatnonzero((dist >= SPLIT_M) & (s >= MIN_ARC_M))
        end = int(apart[0]) if len(apart) else len(arm) - 1
        end = min(end, int(np.searchsorted(s, ZONE_MAX_M, side="right")) - 1)
        if end < 2:
            return None
        zone = arm[:end + 1]
        v = zone[-1] - p
        side = float(d[0] * v[1] - d[1] * v[0]) / max(float(np.hypot(*v)), 1e-9)   # (+: left of the fan's way)
        routes.append(Route(fid, zone, side, through))
    routes.sort(key=lambda r: -r.side)                  # left to right
    straight = min(range(len(routes)), key=lambda i: (abs(routes[i].side) - (0.05 if routes[i].through else 0.0)))
    sid = f"{int(round(p[0] * 2))}_{int(round(p[1] * 2))}"
    return Switch(sid, p, d, routes, straight)


def zone_mask(pts_xy, fid, switches, tol=0.35):
    """Per sample of a piece of track fid: (switch index, route index) of the zone it lies in, or (-1, -1)."""
    sw_i = np.full(len(pts_xy), -1)
    rt_i = np.full(len(pts_xy), -1)
    for i, sw in enumerate(switches):
        for j, r in enumerate(sw.routes):
            if r.fid != fid:
                continue
            lo, hi = r.xy.min(0) - 1.0, r.xy.max(0) + 1.0
            cand = np.flatnonzero((pts_xy[:, 0] >= lo[0]) & (pts_xy[:, 0] <= hi[0]) & (pts_xy[:, 1] >= lo[1])
                                  & (pts_xy[:, 1] <= hi[1]) & (sw_i < 0))
            if not len(cand):
                continue
            d = _dist_to_line(pts_xy[cand], r.xy)
            # (beyond the zone's end the same track goes on: only the samples along the zone, not past its ends)
            s = _arcs(r.xy)
            ends = np.hypot(pts_xy[cand, 0] - r.xy[-1, 0], pts_xy[cand, 1] - r.xy[-1, 1])
            starts = np.hypot(pts_xy[cand, 0] - r.xy[0, 0], pts_xy[cand, 1] - r.xy[0, 1])
            inside = (d <= tol) & (ends <= s[-1] + tol) & (starts <= s[-1] + tol)
            sw_i[cand[inside]] = i
            rt_i[cand[inside]] = j
    return sw_i, rt_i


def mod_rows(switches, whats):
    """The tile's turnouts for the mod (data["railsw"]): [{id, at, dir, def, routes: [{what, side, line}]}];
    whats: {(switch index, route index): the shape's name} of the routes with collision in the tile."""
    out = []
    for i, sw in enumerate(switches):
        routes = []
        for j, r in enumerate(sw.routes):
            line = r.xy[::2] if len(r.xy) > 4 else r.xy
            routes.append({"what": whats.get((i, j)), "side": round(r.side, 3),
                           "line": [round(float(v), 2) for v in np.asarray(line).ravel()]})
        out.append({"id": sw.id, "at": [round(float(sw.at[0]), 2), round(float(sw.at[1]), 2)],
                    "dir": [round(float(sw.dir[0]), 4), round(float(sw.dir[1]), 4)], "def": sw.default,
                    "routes": routes})
    return out
