"""EarthNRails: road bridges clear the railways under them (roads.BridgeProfiles, through nrails.hooks).

Upstream lifts a road deck DECK_ROAD_CLEAR (7.5 m, deck top over the road: ~5.3 m free under the girders) over the
ground roads it crosses and knows nothing of the tracks: a deck could sit on the rails, or a bridge over a line in a
cutting be taken for a junction at grade. Here the tracks on the ground (not their own bridges or tunnels) join the
bridge solver's ground lines under keys (fid, RAIL_KEY): the solver's road crossings leave them out (they would be
3-tuples, liable to be flattened into an at-grade junction near an abutment), and they come back as crossings with
their own clearance (4-tuples, never flattened): the rail top + RAIL_FREE_M of free height + the deck's depth and
girders. Its piers keep off them like off a road (roads.pier_sites' road lines are all the ground lines).

The rail top is where nrails.rails puts it: FORMATION_M over the ground's upper envelope (ENVELOPE_M along the track,
SIDE_SAMPLE_M across): a line in a cutting is measured at the cutting's rim if the terrain model rounds it off.
"""
import numpy as np

RAIL_KEY = "nrails_rail"
RAIL_FREE_M = 6.0           # m of free height over the rail top under a road bridge (catenary: UIC 505 / EN 15273 ~5.8)
RAIL_CLASSES = {"standard_gauge", "light_rail", "narrow_gauge", "subway", "monorail", "funicular"}   # (not "unknown":
#                             railway=abandoned / disused, nrails.rails.HEAVY_CLASSES)
ENVELOPE_SAMPLES = 5        # along the track either side of the crossing (rails.ENVELOPE_M)


# Junctions at grade that are not (the user's run, 2026-10-24: "l'autoroute qui passe au dessus d'une route descend au
# niveau de la route du dessous"; a motorway at a village). roads.deck_profile_once takes a road crossing within
# AT_GRADE_REACH_M of an abutment that the deck cannot clear by AT_GRADE_M as a junction at grade (Queens Plaza: a
# ramp's map line starting in the intersection it climbs from) and brings the deck down to the road's level: a short
# motorway bridge over a street came down to the street. A junction is where the map joins the two roads (a shared
# Overture connector); a crossing without one keeps its clearance (a 4-tuple: never taken for a junction): the deck
# stays at its abutments' level as far as it cannot climb.
CONNS = {}                  # road fid -> its connector ids (load_rails, from every cell the bridge solver reads)
CONNS_MAX = 400000


def deck_crossings(crossings, lines, comp, ground, ground_fn):
    """roads.BridgeProfiles._solve's crossings (parts index, arc, height[, clearance[, level]]) of the deck parts
    `lines` (pool keys comp: (fid, j)): the road crossings whose roads do not meet the deck's at a connector given
    their clearance (not junctions at grade), and the tracks' crossings added (deck_rail_crossings)."""
    import roads
    out = list(crossings)
    road_cr = [i for i, c in enumerate(out) if len(c) == 3]
    if road_cr and comp:
        own = [CONNS.get(str(k[0])) for k in comp]
        base = None                                 # (the straight line between the abutments: roads.deck_heights)
        where = []                                  # (part, arc, road fid) of every ground road crossing
        for key, v in ground.items():
            if is_rail_key(key) or not v:
                continue
            for pi, arc, _xy in roads._crossings(lines, v):
                where.append((pi, float(arc), str(key[0])))
        for i in road_cr:
            pi, arc, z = out[i]
            mine = own[pi] if pi < len(own) else None
            if not mine:
                continue                            # (no connector data: as upstream)
            hits = [f for p, a, f in where if p == pi and abs(a - arc) < 0.5]
            if not _near_abutment(lines, pi, arc, roads.AT_GRADE_REACH_M + 1.0):
                continue                            # (mid-span: never a junction; as upstream)
            if hits and not any(CONNS.get(f) and (CONNS[f] & mine) for f in hits):
                # its clearance, but no more than the deck's abutments give it there (a low bridge stays as low as
                # its ends: flat, rather than a hump it cannot climb or a dip to the road under it)
                if base is None:
                    base = roads.deck_heights(lines, ground_fn)
                ln = np.asarray(lines[pi], np.float64)[:, :2]
                s = np.r_[0.0, np.cumsum(np.hypot(*np.diff(ln, axis=0).T))]
                zb = float(np.interp(arc, s, base[pi])) if pi < len(base) else np.nan
                cl = roads.DECK_ROAD_CLEAR if not np.isfinite(zb) else float(np.clip(zb - z, 0.0, roads.DECK_ROAD_CLEAR))
                out[i] = (pi, arc, z, cl)
    return out + deck_rail_crossings(lines, ground, ground_fn)


def _near_abutment(lines, pi, arc, reach):
    """Is arc (m along deck part pi) within reach of an end of it that no other part of the chain shares (an
    abutment)? Pure."""
    ln = np.asarray(lines[pi], np.float64)[:, :2]
    total = float(np.hypot(*np.diff(ln, axis=0).T).sum())
    for end, d in ((ln[0], arc), (ln[-1], total - arc)):
        if d > reach:
            continue
        shared = any(j != pi and min(np.hypot(*(np.asarray(o)[0, :2] - end)), np.hypot(*(np.asarray(o)[-1, :2] - end)))
                     < 0.5 for j, o in enumerate(lines))
        if not shared:
            return True
    return False


def is_rail_key(k):
    return isinstance(k, tuple) and len(k) == 2 and k[1] == RAIL_KEY


def deck_clear():
    """m a road deck's top stands over a rail top it crosses."""
    import roadmesh
    return RAIL_FREE_M + roadmesh.DECK_DEPTH + roadmesh.GIRDER_D


def load_rails(feats, frame, ground):
    """ground[(fid, RAIL_KEY)] = the on-ground pieces (polylines in metres) of the rail segments of a map cell (feats),
    the trams left out (they run in the streets: upstream already clears those)."""
    import mapgeom
    import roads
    if feats is None or len(feats) == 0 or "subtype" not in feats.attrs:
        return
    from nrails import rails
    sub = feats.attrs["subtype"]
    cls = feats.attrs.get("class")
    for i in range(len(feats)):
        if str(sub[i]) != "rail":
            fid = str(feats.ids[i])
            if fid not in CONNS:                    # (the roads' connectors: deck_crossings)
                if len(CONNS) > CONNS_MAX:
                    CONNS.clear()
                CONNS[fid] = frozenset(rails.feature_connectors(feats, i))
            continue
        c = str(cls[i]) if cls is not None else "standard_gauge"
        if c not in RAIL_CLASSES:
            continue
        key = (str(feats.ids[i]), RAIL_KEY)
        if key in ground:
            continue
        ground[key] = []
        for ring in roads.ground_parts(feats, i):
            if len(ring) < 2:
                continue
            e, n = mapgeom.enu_xy(feats, frame, ring)
            ground[key].append(np.stack([e, n], axis=1))


def rail_top(xy, line, ground_fn):
    """The rail top at xy on the track `line` ((k, 2) m) as nrails.rails would lay it there: FORMATION_M over the
    ground's upper envelope round it (ENVELOPE_M along, SIDE_SAMPLE_M across)."""
    from nrails import rails
    p = np.asarray(line, np.float64)[:, :2]
    ab = np.diff(p, axis=0)
    L2 = np.maximum((ab * ab).sum(1), 1e-12)
    t = np.clip(((xy - p[:-1]) * ab).sum(1) / L2, 0.0, 1.0)
    d = np.hypot(*(p[:-1] + t[:, None] * ab - xy).T)
    k = int(np.argmin(d))
    u = ab[k] / np.sqrt(L2[k])
    n = np.array([-u[1], u[0]])
    along = np.linspace(-rails.ENVELOPE_M, rails.ENVELOPE_M, 2 * ENVELOPE_SAMPLES + 1)
    across = np.array([-rails.SIDE_SAMPLE_M, 0.0, rails.SIDE_SAMPLE_M])
    pts = (xy[None, None, :] + along[:, None, None] * u + across[None, :, None] * n).reshape(-1, 2)
    g = np.asarray(ground_fn(pts), np.float64)
    g = g[np.isfinite(g)]
    if not len(g):
        return None
    return float(g.max()) + rails.FORMATION_M


def deck_rail_crossings(lines, ground, ground_fn, clear=None):
    """[(part index, arc m, rail top, clearance)] where a track on the ground (ground's RAIL_KEY entries) crosses
    under the deck parts `lines` (roads.deck_profile's crossings, with their own clearance)."""
    import roads
    rl = [ln for k, v in ground.items() if is_rail_key(k) for ln in v if len(ln) >= 2]
    if not rl or not lines:
        return []
    clear = deck_clear() if clear is None else clear
    out, base = [], None
    for pi, arc, xy in roads._crossings(lines, rl):
        xy = np.asarray(xy, np.float64)
        best, bd = None, np.inf
        for ln in rl:                           # the track it is: the nearest
            p = np.asarray(ln, np.float64)[:, :2]
            if ((p.min(0) - 1.0 > xy) | (p.max(0) + 1.0 < xy)).any():
                continue
            ab = np.diff(p, axis=0)
            L2 = np.maximum((ab * ab).sum(1), 1e-12)
            t = np.clip(((xy - p[:-1]) * ab).sum(1) / L2, 0.0, 1.0)
            d = float(np.hypot(*(p[:-1] + t[:, None] * ab - xy).T).min())
            if d < bd:
                best, bd = p, d
        if best is None:
            continue
        z = rail_top(xy, best, ground_fn)
        if z is None or any(o[0] == pi and abs(o[1] - arc) < 1.0 for o in out):   # (a crossing on a vertex: twice)
            continue
        if base is None:
            base = roads.deck_heights(lines, ground_fn)
        ln = np.asarray(lines[pi], np.float64)[:, :2]
        zb = float(np.interp(arc, np.r_[0.0, np.cumsum(np.hypot(*np.diff(ln, axis=0).T))], base[pi]))
        if np.isfinite(zb) and zb < z - UNDER_M:
            # the straight line between the abutments passes this far under the track: the road goes under the
            # railway's embankment (a bridge over a stream beside it, the track on the ground there: east of
            # a test town station, the deck 4.7 m under the rails); lifting it over the trains would be wrong
            continue
        # over the whole width of the track's room (the deck is smoothed after: a requirement at one point came out
        # ~0.5 m under it)
        total = float(np.hypot(*np.diff(ln, axis=0).T).sum())
        # ... and the deck's smoothing takes a tent's tip down by ~sqrt(2/pi) grade sigma: asked that much higher
        sigma = float(np.clip(total / roads.DECK_SIGMA_SHARE, roads.DECK_SIGMA, roads.DECK_SIGMA_MAX))
        cl = float(clear) + SMOOTH_SHARE * roads.DECK_GRADE * sigma
        for da in (0.0, -CLEAR_HALF_M, CLEAR_HALF_M):
            out.append((int(pi), float(np.clip(arc + da, 0.0, total)), z, cl))
    return out


CLEAR_HALF_M = 3.0          # m either side of a crossing along the deck the clearance is asked (a track's room)
UNDER_M = 1.5               # m: a deck whose abutments' line passes this far under a track goes under it (no clearance)
SMOOTH_SHARE = 0.8          # sqrt(2/pi): a Gaussian's mean distance, the loss at a tent's tip per unit grade and sigma
