#!/usr/bin/env python3
"""EarthNRails dev tool: can a train go from A to B? (The user, 2026-10-24: "faire des voyages d'un point A à un point
B suivant une méthode de génération simple et uniforme ... sans accroc".) Real Overture cells along the corridor A-B:
  1. the rail graph (heavy rail segments, joined where their ends meet within NODE_TOL_M or at a shared connector):
     the shortest path from the track nearest A to the one nearest B; without one, the gap: the closest approach of the
     part reached from A to the part reaching B (a hole in the data, a missing link);
  2. along the path: its length, its tunnels (length, portals) and bridges;
  3. --profile: the path profiled window by window as the game does (rails.profile_network, a WINDOW_M square every
     STEP_KM, the ground from the DEM with the sea floor carved in): the steepest grade, the vault of every tunnel
     sample against the ground over it (a tube out of the ground, in the sea), and where two windows overlap the
     difference of their heights at the same samples (two tiles that would not meet);
  4. --portals: every tunnel portal on the path through tools/audit_rail_portals' check (terrain in the train's way).

    .venv\\Scripts\\python.exe tools\\audit_rail_route.py A_LAT A_LON B_LAT B_LON [--corridor 4] [--profile] [--portals]
"""
import argparse
import heapq
import math
import os
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import dem        # noqa: E402
import geodesy    # noqa: E402
import mapcells   # noqa: E402
import mapdata    # noqa: E402
import netfetch   # noqa: E402
from nrails import paths, rails      # noqa: E402

WINDOW_M = 1600.0
STEP_KM = 1.0
PORTAL_SKIP_M = 60.0        # m off a tunnel's portals its vault may stand in the open (tile seams' tunnel check)


def corridor_cells(a, b, km):
    """The map cell keys within km of the great-circle segment a-b (lat, lon)."""
    n = max(2, int(math.hypot(b[0] - a[0], (b[1] - a[1]) * math.cos(math.radians(a[0]))) * 111.0 / 1.0) + 1)
    keys = set()
    dl = km / 111.0
    for t in np.linspace(0.0, 1.0, n):
        la = a[0] + t * (b[0] - a[0])
        lo = a[1] + t * (b[1] - a[1])
        dlo = dl / max(math.cos(math.radians(la)), 0.1)
        keys |= set(mapcells.cells_for_bbox(la - dl, lo - dlo, la + dl, lo + dlo))
    return sorted(keys, key=str)


def connector_marks(cells):
    """{fid: [(fraction along the segment, connector id)]} of the rail segments (Overture's connectors rule)."""
    out = {}
    for feats in cells:
        if feats is None or len(feats) == 0 or "subtype" not in feats.attrs:
            continue
        t = feats.rules.get("connectors") if hasattr(feats, "rules") else None
        if t is None or len(t.feature) == 0:
            continue
        sub = feats.attrs["subtype"]
        for i in range(len(feats)):
            fid = str(feats.ids[i])
            if str(sub[i]) != "rail" or fid in out:
                continue
            out[fid] = sorted((float(t.start[j]), str(t.value[j])) for j in t.rows(i))
    return out


def graph(feats, marks):
    """nodes: {node: xy}, adj: {node: [(node, length, (fid, f0, f1))]}: every segment cut at its connectors (Overture's
    network: segments meet at shared connectors), its ends without one merged within NODE_TOL_M (a grid)."""
    nodes, adj, idx = {}, {}, {}
    cell = rails.NODE_TOL_M

    def add(key, p):
        if key not in nodes:
            nodes[key] = np.asarray(p, np.float64)
            adj[key] = []
            k = (int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell)))
            idx.setdefault(k, []).append(key)
        return key

    def loose(p):
        k = (int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell)))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for nid in idx.get((k[0] + dx, k[1] + dy), ()):
                    if math.hypot(*(nodes[nid] - p)) <= rails.NODE_TOL_M:
                        return nid
        return add(("xy", round(float(p[0]), 1), round(float(p[1]), 1)), p)
    seg = {}
    for fid, cls, xy, _rg in feats:
        if cls not in rails.HEAVY_CLASSES or len(xy) < 2:
            continue
        s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
        L = float(s[-1])

        def at(f):
            return np.array([np.interp(f * L, s, xy[:, 0]), np.interp(f * L, s, xy[:, 1])])
        mk = list(marks.get(fid, []))
        if not mk or mk[0][0] > 1e-3:
            mk.insert(0, (0.0, None))
        if mk[-1][0] < 1 - 1e-3:
            mk.append((1.0, None))
        keys = [add(("c", c), at(f)) if c is not None else loose(at(f)) for f, c in mk]
        for (f0, _a), (f1, _b), u, v in zip(mk[:-1], mk[1:], keys[:-1], keys[1:]):
            if u == v:
                continue
            adj[u].append((v, (f1 - f0) * L, (fid, f0, f1)))
            adj[v].append((u, (f1 - f0) * L, (fid, f1, f0)))
        seg[fid] = xy
    return nodes, adj, seg


def dijkstra(adj, src):
    dist, prev = {src: 0.0}, {}
    q = [(0.0, src)]
    while q:
        d, u = heapq.heappop(q)
        if d > dist.get(u, np.inf):
            continue
        for v, w, fid in adj[u]:
            nd = d + w
            if nd < dist.get(v, np.inf):
                dist[v], prev[v] = nd, (u, fid)
                heapq.heappush(q, (nd, v))
    return dist, prev


def nearest_node(nodes, p):
    best = min(nodes, key=lambda n: math.hypot(*(nodes[n] - p)))
    return best, math.hypot(*(nodes[best] - p))


def main():
    ap = argparse.ArgumentParser()
    for k in ("alat", "alon", "blat", "blon"):
        ap.add_argument(k, type=float)
    ap.add_argument("--corridor", type=float, default=4.0, help="km either side of the line A-B")
    ap.add_argument("--profile", action="store_true")
    ap.add_argument("--portals", action="store_true")
    ap.add_argument("--step", type=float, default=STEP_KM, help="km between the profile's windows")
    ap.add_argument("--tile-seams", type=float, default=0.0, help="km from each end: the game's tiles' seams")
    ap.add_argument("--windows", action="store_true", help="tile seams: each tile its own window (before canon)")
    ap.add_argument("--raw", action="store_true", help="the DEM (sea floor carved) without the grading: faster")
    ap.add_argument("--no-sea", action="store_true", help="no sea floor carving (no bathymetry downloads)")
    a = ap.parse_args()
    cache = paths.default_cache_dir()
    net = netfetch.Fetcher(stats_dir=os.path.join(cache, "netstats"))
    md = mapdata.MapData(cache, fetcher=net)
    frame = geodesy.EnuFrame((a.alat + a.blat) / 2, (a.alon + a.blon) / 2)
    keys = corridor_cells((a.alat, a.alon), (a.blat, a.blon), a.corridor)
    print(f"{len(keys)} map cells along the corridor")
    cells = [md.cell(k, layers=("roads",)).layers.get("roads") for k in keys]
    feats = rails.rail_features(cells, frame, (-1e9, -1e9, 1e9, 1e9))
    nodes, adj, seg = graph(feats, connector_marks(cells))
    pa = np.array(frame.geodetic_to_enu(a.alat, a.alon, 0.0)[:2], np.float64)
    pb = np.array(frame.geodetic_to_enu(a.blat, a.blon, 0.0)[:2], np.float64)
    na, da = nearest_node(nodes, pa)
    nb, db = nearest_node(nodes, pb)
    print(f"{len(seg)} heavy rail segments, {len(nodes)} nodes; A's track {da:.0f} m away, B's {db:.0f} m")
    dist, prev = dijkstra(adj, na)
    if nb not in dist:
        dist_b, _ = dijkstra(adj, nb)
        ra = np.array([nodes[n] for n in dist])
        rb = np.array([nodes[n] for n in dist_b])
        best = (np.inf, None, None)
        for i in range(0, len(ra), max(1, len(ra) // 4000)):
            d = np.hypot(*(rb - ra[i]).T)
            j = int(np.argmin(d))
            if d[j] < best[0]:
                best = (float(d[j]), ra[i], rb[j])
        la1, lo1, _ = frame.enu_to_geodetic(best[1][0], best[1][1], 0.0)
        la2, lo2, _ = frame.enu_to_geodetic(best[2][0], best[2][1], 0.0)
        print(f"NO PATH: the network reached from A ({len(dist)} nodes) and the one reaching B ({len(dist_b)}) come "
              f"within {best[0]:.1f} m at {float(la1):.5f},{float(lo1):.5f} / {float(la2):.5f},{float(lo2):.5f} "
              "(a missing link in the data, or the corridor too narrow: --corridor)")
        return
    path, n = [], nb
    while n != na:
        u, edge = prev[n]
        path.append(edge)
        n = u
    path.reverse()
    fr = {f: (c, rg) for f, c, _xy, rg in feats}
    route, tunnels, bridges = [], [], []
    for fid, f0, f1 in path:
        xy = seg[fid]
        s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
        L = float(s[-1])
        a0, a1 = sorted((f0, f1))
        ss = np.r_[a0 * L, s[(s > a0 * L) & (s < a1 * L)], a1 * L]
        part = np.c_[np.interp(ss, s, xy[:, 0]), np.interp(ss, s, xy[:, 1])]
        route.append((fid, part if f0 <= f1 else part[::-1]))
        for s0, s1, kind in fr[fid][1]:
            o = min(s1, a1) - max(s0, a0)
            if kind in ("tunnel", "bridge") and o > 0:
                (tunnels if kind == "tunnel" else bridges).append((fid, o * L))
    total = dist[nb]
    print(f"PATH: {total / 1000:.1f} km over {len(route)} segment parts; {len(tunnels)} tunnel parts "
          f"({sum(t[1] for t in tunnels) / 1000:.2f} km, longest {max([t[1] for t in tunnels] or [0]):.0f} m), "
          f"{len(bridges)} bridge parts ({sum(b[1] for b in bridges) / 1000:.2f} km)")
    if a.profile or a.portals or a.tile_seams:
        d = dem.Dem(os.path.join(cache, "dem"), fetcher=net)
        sc = None
        if not a.no_sea:
            try:
                import seacarve
                sc = seacarve.SeaCarver(md, cache, dem=d)
            except Exception as e:      # noqa: BLE001
                print("(no sea carving:", e, ")")
        zoom = dem.zoom_for(frame.lat0 if hasattr(frame, "lat0") else a.alat, 1.25, dem.FINE_ZOOM)

        import grading
        grader = grading.Grader(frame, md, lambda la, lo: np.asarray(d.sample(np.asarray(la), np.asarray(lo),
                                                                              grading.PROFILE_ZOOM), np.float64))
        from nrails import canon
        canon.grader_made(grader)       # (as the game: the shared profiles read the grader's own ground)

        def raw(la, lo):
            z = np.asarray(d.sample(np.asarray(la), np.asarray(lo), zoom), np.float64)
            return sc.carve(np.asarray(la), np.asarray(lo), z) if sc is not None else z

        def elev(la, lo):           # (as the game's physics ground: the sea floor carved, the roads' and rails' beds)
            return grader.apply(la, lo, raw(la, lo), grading.ROAD_LIFT)
        ground = rails.Ground(frame, raw if a.raw else elev)
    if a.profile:
        profile(route, feats, cells, ground, a.step)
    if a.tile_seams:
        cf = (lambda k: md.cell(k, layers=("roads",)).layers.get("roads")) if not a.windows else None
        tile_seams(route, feats, cells, ground, a.tile_seams, cf)
    if a.portals:
        import audit_rail_portals as arp
        done = bad = 0
        boxes = set()
        for fid, _xy in route:
            xy = next(x for f, _c, x, _r in feats if f == fid)          # (its mapped direction: the ranges')
            ss = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
            for s0, s1, k in fr[fid][1]:
                if k != "tunnel":
                    continue
                for f in (s0, s1):
                    p = np.array([np.interp(f * ss[-1], ss, xy[:, 0]), np.interp(f * ss[-1], ss, xy[:, 1])])
                    boxes.add((int(p[0] // 1000), int(p[1] // 1000)))
        for bx, by in sorted(boxes):
            box = (bx * 1000.0 - 500, by * 1000.0 - 500, bx * 1000.0 + 1500, by * 1000.0 + 1500)
            for t in rails.block_tubes(frame, cells, elev, box):
                for e in (0, 1):
                    if not t["portal"][e]:
                        continue
                    p = t["xy"][0 if e == 0 else -1]
                    if not (box[0] + 500 <= p[0] < box[2] - 500 and box[1] + 500 <= p[1] < box[3] - 500):
                        continue
                    res = arp.portal_check(t, e, ground)
                    done += 1
                    if res["on"][0]:
                        bad += 1
                        la, lo, _ = frame.enu_to_geodetic(p[0], p[1], 0.0)
                        print(f"   portal at {float(la):.5f},{float(lo):.5f}: {res['on'][0]} points of terrain in "
                              f"the way (worst +{res['on'][1]:.2f} m)")
        print(f"PORTALS: {done} checked, {bad} with terrain in the train's way")
    md.close()


def tile_seams(route, feats, cells, ground, km, cell_fn=None):
    """As the game builds them: the road tiles (roads.TILE) the path crosses within km of either end, each profiled in
    its own window (the tile + NEAR_M); every track's height where two neighbouring tiles both hold it (their seams)."""
    import roads
    pts = np.concatenate([xy for _f, xy in route])
    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    keep = (s <= km * 1000) | (s >= s[-1] - km * 1000)
    tiles = sorted({(int(math.floor(x / roads.TILE)), int(math.floor(y / roads.TILE))) for x, y in pts[keep]})
    segs = [(f, xy, rg) for f, c, xy, rg in feats if c in rails.HEAVY_CLASSES]
    conns = rails.rail_connectors(cells)
    got = {}
    steep = [0.0, None, None]
    tun = [0, 0, (-1e9, None, None)]        # tunnel samples, vault out of the ground, worst (m, track, where)
    t0 = time.perf_counter()
    for tx, ty in tiles:
        x0, y0, x1, y1 = roads.tile_bbox(tx, ty)
        near = (x0 - rails.NEAR_M, y0 - rails.NEAR_M, x1 + rails.NEAR_M, y1 + rails.NEAR_M)
        if cell_fn is not None:         # (as the game: the map cells' shared profiles, nrails.canon)
            from nrails import canon
            prof = canon.profile_box(ground.frame, (x0 - 4, y0 - 4, x1 + 4, y1 + 4), cell_fn, ground.elev)[0]
        else:
            prof = rails.profile_network(ground, segs, near, rails.road_lines(cells, ground.frame, near), None, None,
                                         rails.road_structs(cells, ground.frame, near), conns)
        got[(tx, ty)] = {}
        for fid, parts in prof.items():
            for p, _kind in parts:
                inn = (p[:, 0] >= x0) & (p[:, 0] <= x1) & (p[:, 1] >= y0) & (p[:, 1] <= y1)
                kd = np.asarray(_kind)
                for run in rails._runs(kd == 2):            # tunnel vault out of the ground, PORTAL_SKIP_M off portals
                    pin = run[inn[run]]
                    if not len(pin):
                        continue
                    ss = np.r_[0.0, np.cumsum(np.hypot(*np.diff(p[:, :2], axis=0).T))]
                    far = pin[(ss[pin] - ss[run[0]] > PORTAL_SKIP_M) & (ss[run[-1]] - ss[pin] > PORTAL_SKIP_M)]
                    if len(far):
                        gz = ground.z(p[far, 0], p[far, 1])
                        out = p[far, 2] - rails.TUNNEL_FLOOR_M + rails.TUNNEL_H - gz
                        tun[0] += len(far)
                        tun[1] += int((out > 0).sum())
                        j = int(np.argmax(out))
                        if out[j] > tun[2][0]:
                            tun[2] = (float(out[j]), fid[:8], p[far[j], :3].round(1).tolist())
                ds = np.hypot(*np.diff(p[:, :2], axis=0).T)
                g = np.where((ds > 0.5) & inn[1:], np.abs(np.diff(p[:, 2])) / np.maximum(ds, 1e-9), 0.0)
                if len(g) and g.max() > steep[0]:
                    steep[:] = [float(g.max()), fid[:8], p[int(np.argmax(g)), :3].round(1).tolist()]
                for q in p:
                    if x0 - 4 <= q[0] <= x1 + 4 and y0 - 4 <= q[1] <= y1 + 4:      # (its own tile and the seam)
                        got[(tx, ty)][(fid, round(float(q[0]) / 2), round(float(q[1]) / 2))] = float(q[2])
    worst = []
    for (tx, ty), m in got.items():
        for dx, dy in ((1, 0), (0, 1), (1, 1), (1, -1)):
            o = got.get((tx + dx, ty + dy))
            if not o:
                continue
            for k in m.keys() & o.keys():
                worst.append((abs(m[k] - o[k]), k[0][:8], (tx, ty), (tx + dx, ty + dy), k[1] * 2, k[2] * 2))
    worst.sort(reverse=True)
    print(f"TILE SEAMS: {len(tiles)} tiles in {time.perf_counter() - t0:.0f} s, {len(worst)} shared samples; worst:")
    for w in worst[:6]:
        print(f"   {w[0]:.3f} m track {w[1]} tiles {w[2]} / {w[3]} at ({w[4]}, {w[5]})")
    n = np.array([w[0] for w in worst]) if worst else np.zeros(1)
    print(f"   over 5 cm: {(n > 0.05).sum()}, over 0.5 m: {(n > 0.5).sum()}")
    print(f"   steepest grade in the tiles: {steep[0] * 100:.2f} % (track {steep[1]} at {steep[2]})")
    print(f"   tunnels ({PORTAL_SKIP_M:.0f} m off their portals): {tun[0]} samples, vault out of the ground at {tun[1]};"
          f" highest vault over the ground {tun[2][0]:.2f} m (track {tun[2][1]} at {tun[2][2]})")


def profile(route, feats, cells, ground, step_km=STEP_KM):
    pts = np.concatenate([xy for _f, xy in route])
    s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    centres = np.arange(0.0, s[-1] + 1, step_km * 1000.0)
    segs = [(f, xy, rg) for f, c, xy, rg in feats if c in rails.HEAVY_CLASSES]
    fids = {f for f, _ in route}
    seen = {}               # (fid, round x, round y) -> z
    worst_dz, worst_grade, out_of_ground, n_tun = 0.0, 0.0, 0, 0
    where = grade_at = where_info = None
    vault = rails.TUNNEL_H - rails.TUNNEL_FLOOR_M
    t0 = time.perf_counter()
    for c in centres:
        x = float(np.interp(c, s, pts[:, 0]))
        y = float(np.interp(c, s, pts[:, 1]))
        h = WINDOW_M / 2
        near = (x - h, y - h, x + h, y + h)
        prof = rails.profile_network(ground, segs, near, rails.road_lines(cells, ground.frame, near), None, None,
                                     rails.road_structs(cells, ground.frame, near), rails.rail_connectors(cells))
        for fid, parts in prof.items():
            if fid not in fids:
                continue
            for p, kind in parts:
                ds = np.hypot(*np.diff(p[:, :2], axis=0).T)
                ok = ds > 0.5
                if ok.any():
                    g = np.where(ok, np.abs(np.diff(p[:, 2])) / np.maximum(ds, 1e-9), 0.0)
                    i = int(np.argmax(g))
                    if g[i] > worst_grade:
                        worst_grade, grade_at = float(g[i]), (p[i].round(1).tolist(), int(kind[i]), fid[:8], c)
                tun = np.asarray(kind) == 2
                if tun.any():
                    gz = ground.z(p[tun, 0], p[tun, 1])
                    n_tun += int(tun.sum())
                    out_of_ground += int((p[tun, 2] + vault > gz + 0.5).sum())
                for q in p[:: 5]:
                    k = (fid, round(float(q[0]) / 2), round(float(q[1]) / 2))
                    if k in seen:
                        dz = abs(seen[k][0] - float(q[2]))
                        if dz > worst_dz:
                            worst_dz, where = dz, q
                            where_info = (fid[:8], seen[k][1] / 1000, c / 1000, seen[k][0], float(q[2]))
                    else:
                        seen[k] = (float(q[2]), c)
        print(f"   window at {c / 1000:.1f} km ({x:.0f}, {y:.0f}): {time.perf_counter() - t0:.1f} s", flush=True)
        t0 = time.perf_counter()
    print(f"PROFILE: steepest grade {worst_grade * 100:.2f} %; tunnel samples {n_tun}, vault out of the ground "
          f"(more than the portals' 0.5 m) at {out_of_ground}; windows disagree by up to {worst_dz:.3f} m"
          + (f" at {where[:2].round(0).tolist()}" if where is not None else ""))
    if where is not None:
        print("   seam: track %s, windows at %.1f / %.1f km: %.2f / %.2f m" % where_info)
    if worst_grade > 0:
        print(f"   steepest at {grade_at[0]} (kind {grade_at[1]}, track {grade_at[2]}, window {grade_at[3] / 1000:.1f} km)")
    print("   (portal samples count as out of the ground: a portal's vault stands in the open by nature)")


if __name__ == "__main__":
    main()
