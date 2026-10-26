"""NRails: the street furniture kept off the track (the user's run, 2026-10-25, a test town - a test city: "a chaque
passage ... ce cable electrique bloquant les 2 voies"; "presence d'arbres sur la voie (passage a niveau)").

Upstream places utility poles, lamps, signs and street trees along each road and strings wires from pole to pole
(furniture.place / wire_lines): it knows the road bridges (furniture.under_decks) but not the railway. A street under a
railway bridge carried its wires 7.4 m over the street, through the bridge and 1.5 m over its rails; the trees and
poles along a street crossing the line at grade stood on the track. Here, with the tile's track (nrails.rails):
  - a prop whose footprint comes within PROP_CLEAR_M of a track's centre line, from under its rail top + PROP_DZ_M up
    to over it (not one on a street far under a viaduct, nor up on a road bridge), is left out;
  - a wire passing within WIRE_REACH_M of a track's centre line lower than WIRE_FREE_M over its rail top (and not
    under it by more than WIRE_UNDER_M: a street's wires under a high viaduct stay) is left out.
"""
import numpy as np

PROP_CLEAR_M = 3.2          # m from the centre line: the track's room (gauge 1.435 + the trains' 3.15 m width / 2)
PROP_DZ_M = 3.0             # m: a prop standing lower than rail - this (and short enough) is under a viaduct
WIRE_REACH_M = 3.5
WIRE_FREE_M = 7.5           # m over the rail top a crossing power wire keeps (EN 50122 / UTE: 7 m and more)
WIRE_UNDER_M = 1.0          # m under the rail top a wire passing below a railway bridge may come


def _near(xy, lines, reach):
    """For each point of xy (n, 2): the rail top of the nearest track sample within reach (nan if none), from lines
    [(k, (m, 3))] (2 m samples: the nearest sample is within 1 m of the nearest point on the line)."""
    out = np.full(len(xy), np.nan)
    best = np.full(len(xy), np.inf)
    for _k, p in lines:
        p = np.asarray(p, np.float64)
        if not len(p):
            continue
        lo, hi = p[:, :2].min(0) - reach - 1.0, p[:, :2].max(0) + reach + 1.0
        sel = np.flatnonzero((xy[:, 0] > lo[0]) & (xy[:, 0] < hi[0]) & (xy[:, 1] > lo[1]) & (xy[:, 1] < hi[1]))
        if not len(sel):
            continue
        for i0 in range(0, len(sel), 256):
            s = sel[i0:i0 + 256]
            d = np.hypot(xy[s, None, 0] - p[None, :, 0], xy[s, None, 1] - p[None, :, 1])
            j = np.argmin(d, 1)
            dj = d[np.arange(len(s)), j]
            take = (dj < reach + 1.0) & (dj < best[s])
            best[s[take]] = dj[take]
            out[s[take]] = p[j[take], 2]
    return out, best


def clear_props(rows, lines):
    """rows (furniture's [group, x, y, z, yaw, scale, height, rank]) without those on the track."""
    if not rows or not lines:
        return rows
    xy = np.array([[float(r[1]), float(r[2])] for r in rows])
    zr, d = _near(xy, lines, PROP_CLEAR_M)
    out = []
    for r, z, dd in zip(rows, zr, d):
        if np.isfinite(z) and dd < PROP_CLEAR_M:
            base, top = float(r[3]), float(r[3]) + float(r[6] if len(r) > 6 else 10.0)
            if top > z - 0.5 and base < z + PROP_DZ_M:     # (on the track's level: not under a viaduct, not on a deck)
                continue
        out.append(r)
    return out


WALL_CLEAR_M = 3.0          # m from a track's centre line a road's retaining wall stops
WALL_UNDER_M = 1.0          # m: a wall whose top stays this far under the rails passes under the railway's bridge


def clear_walls(walls, lines):
    """Cuts in place the road retaining walls (roads.retaining_walls' dicts: base (k, 2), top (k,), foot (k,) ...)
    where they cross the track at its level: a street lowered under a short railway bridge had its cutting's wall
    run on across the track, a low wall the train hit (the user's run, 2026-10-25, by Bavilliers). Returns how many
    walls were cut."""
    if not walls or not lines:
        return 0
    out, cut = [], 0
    for w in walls:
        base = np.asarray(w["base"], np.float64)
        k = len(base)
        zr, d = _near(base[:, :2], lines, WALL_CLEAR_M)
        top = np.asarray(w["top"], np.float64)
        bad = np.isfinite(zr) & (d < WALL_CLEAR_M) & (top > zr - WALL_UNDER_M)
        if not bad.any():
            out.append(w)
            continue
        cut += 1
        good = ~bad
        i = 0
        while i < k:
            if not good[i]:
                i += 1
                continue
            j = i
            while j + 1 < k and good[j + 1]:
                j += 1
            if j - i + 1 >= 2:
                out.append({key: (v[i:j + 1] if isinstance(v, (np.ndarray, list)) and len(v) == k else v)
                            for key, v in w.items()})
            i = j + 1
    walls[:] = out
    return cut


PIER_CLEAR_M = 2.2          # m from a track's centre a road bridge's pier keeps (a train's half width 1.6 + room)


def clear_piers(piers, lines):
    """The road bridges' piers (roads.pier_sites' / bridgetypes' tuples (x, y, ux, uy, z_top, z_bottom, width
    [, thick])) without those standing in a track's room at its level: their footprint (a wall across the deck as
    roadmesh._pier draws it, or a truss's anchor pier) within PIER_CLEAR_M of a track's centre line (the LGV under an
    overpass near a tunnel portal: a pier between its two tracks, the user's run 2026-10-25). Returns (kept, dropped count)."""
    if not piers or not lines:
        return list(piers or ()), 0
    import roadmesh
    pts = np.concatenate([np.asarray(p, np.float64) for _k, p in lines if len(p)]) if lines else np.zeros((0, 3))
    if not len(pts):
        return list(piers), 0
    out, n = [], 0
    for p in piers:
        x, y, ux, uy, zt, zb, width = (float(v) for v in p[:7])
        thick = float(p[7]) if len(p) > 7 and p[7] is not None else None
        t = np.array([ux, uy]) / max(float(np.hypot(ux, uy)), 1e-9)
        nrm = np.array([-t[1], t[0]])
        half_t = (thick if thick is not None else roadmesh.PIER_T) / 2 + 0.3
        half_n = width / 2 if thick is not None else float(np.clip(0.7 * width, 2.5, 14.0)) / 2
        d = pts[:, :2] - [x, y]
        a, b = np.abs(d @ t) - half_t, np.abs(d @ nrm) - half_n
        dist = np.hypot(np.maximum(a, 0.0), np.maximum(b, 0.0))
        near = (dist < PIER_CLEAR_M) & (pts[:, 2] > zb - 1.0) & (pts[:, 2] < zt + 1.0)
        if near.any():
            n += 1
            continue
        out.append(p)
    return out, n


def clear_wires(wires, lines):
    """Removes in place the wires (each (k, 3)) through the track's room."""
    if not wires or not lines:
        return 0
    keep, gone = [], 0
    for w in wires:
        w = np.asarray(w, np.float64)
        zr, d = _near(w[:, :2], lines, WIRE_REACH_M)
        hit = np.isfinite(zr) & (d < WIRE_REACH_M) & (w[:, 2] < zr + WIRE_FREE_M) & (w[:, 2] > zr - WIRE_UNDER_M)
        if hit.any():
            gone += 1
            continue
        keep.append(w)
    wires[:] = keep
    return gone
